"""快慢思考语音通话的中转：浏览器 ↔ 这里 ↔ 百炼实时模型。密钥只在服务端。

上行二进制帧是 16k PCM，下行二进制帧是 24k PCM，其余都是 JSON 控制消息。
工具在这里执行：think_deep 等交给本机慢思考（voice_think），web_search 走 DeepSeek。
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
import time
from collections import deque
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from . import agent, chat, db, settings, voice_record, voice_rt, voice_tools
from .voice_think import Thinker

log = logging.getLogger(__name__)
router = APIRouter(tags=["voice"])

OUT_RATE = 24000
SAFE_SILENCE_S = 1.0  # 用户停了这么久才插话送结果
CUE_AT = (8.0, 25.0)  # 慢思考想了这么久时报进度，一个任务最多两次
RESPONSE_WAIT_S = 5  # 要了回应这么久还没开始（比如百炼报错），就别再占着，后面的结果还要送
IDLE_S = 600  # 这么久没人说话就挂断，免得一直计费
TICK_S = 0.1
HEARD_WAIT_S = 1  # 工具调用比转写早到约 0.15 秒（2026-11-04 实测），等它到了再执行，最多等这么久
HOLD_S = 10  # 用户说「等一下」后，这么久内不主动开口；再说话就解除
BRIEF_MAX = 200  # 提纲留在百炼的历史里，每轮都要算钱
# 这些事件量大又没有内容，不进通话记录（音频本身在录音文件里，转写的完整句子在 done 事件里）
NOISY_EVENTS = {"response.audio.delta", "response.audio_transcript.delta", "response.function_call_arguments.delta", "response.text.delta"}
# 模型偶尔嘴上说转交却没调工具（2026-11-04 实测），用户就白等了：听到这些话而没调用，替它转
CLAIMS_SEARCH = re.compile(r"我[^。！？]{0,6}搜")
CLAIMS_FORWARD = re.compile(r"think_deep|第一反应|这边(?:看不到|没)|转给|转交|慢思考|后台|稍等|想一下|想想|帮你(?:理|想|捋)|我[^。！？]{0,6}(?:查|搜|翻|找|看看|看一下)")
# 提示词压不到零：工具名、方括号占位、「让后台想」还会冒出来。文字比音频早到（2026-11-04 实测约 15 毫秒，且一句话整句先到），先拦不增加延迟
INTERNAL_WORDS = re.compile(r"慢思考|快思考|转给|转交|交出去|交给|让(?:后台|搭档)|让\s*Claude|Claude\s*帮|think_deep|update_thinking|get_thinking_status|cancel_thinking|web_search|^\s*[\[【]")
# 模型直接听音频，常常和转写不一致，纯「等一下」也可能接话甚至去搜（2026-11-04 实测），只能看转写来拦。整句都是才算，「等一下，我补充一点」不算
HOLD = re.compile(r"(?:你先|你|先)?(?:等一?下|等等|稍等(?:一下)?|等会儿?|等我一下)[啊哈吧]?[。！？!?,，.\s]*")


def _terms(text: str) -> set[str]:
    return set(re.findall(r"[a-z]+|[\u4e00-\u9fff]", text.lower())) - set("年月日号")


def _query_from_user(query: str, heard: str) -> bool:
    """搜索词的每个字都在用户原话里（日期除外），就不是听错后跑了题。比连着的词宽松：模型常省掉「的」、调换语序。"""
    return _terms(query) <= _terms(heard)


class _End(Exception):
    pass


def configured() -> bool:
    try:
        voice_rt.endpoint(), voice_rt.headers()
        return True
    except RuntimeError:
        return False


def _rt_config() -> dict:
    return settings.get("voice_rt", {}) or {}


live_calls: set[int] = set()  # 正在打的电话不能删


class Call:
    def __init__(self, ws: WebSocket, resume: int = 0):
        self.ws, self.up, self.sid = ws, None, None
        self.resume = resume
        self.rec = voice_record.Recorder()
        self.speech_start = 0.0
        self.once: list[str] = []  # 念完就从百炼的历史里删掉的注入：念出来的话模型自己的回应里有，留着每轮多算一遍
        self.injected = 0
        self.reading_answer, self.forward_said = False, ""
        self.loop = asyncio.get_running_loop()
        self.response_active = self.user_speaking = self.dropping = self.want_response = self.reply_done = False
        self.searching = 0
        self.asked_at = 0.0
        self.spoke_this_response = self.tool_called = self.from_user = self.forward_waiting = False
        self.muted, self.muted_text, self.retrying, self.guarded = False, "", False, False
        self.last_user = ""
        self.query_checked = False
        self.heard = asyncio.Event()
        self.early_reply = ""  # 转写到之前不显示回复：可能是「等一下」，这句要拦
        self.heard.set()
        self.hold_until = 0.0
        now = time.monotonic()
        self.play_until = self.audio_started = 0.0
        self.audio_s = 0.0
        self.last_speech_end, self.last_voice, self.t_stop = 0.0, now, None
        self.reply = ""
        self.outbox: deque[tuple[str, str]] = deque()
        self.recent: deque[str] = deque(maxlen=8)
        self.last_status: dict = {}
        self.thinker: Thinker | None = None

    # ---------- 记录：通话也进讨论，只追加 ----------
    def _session(self, title: str = "") -> int:
        if not self.sid:
            self.sid = db.insert("chat_sessions", {"module": "talk", "ref": "", "engine": "claude", "title": title[:40] or "语音通话",
                                                   "created_at": db.now(), "updated_at": db.now()})
            self.rec.link(self.sid)
        return self.sid

    def _record(self, role: str, text: str) -> None:
        db.insert("chat_messages", {"session_id": self._session(text), "role": role, "content": text, "created_at": db.now()})
        db.update("chat_sessions", self.sid, {"updated_at": db.now()})

    def _pick_up(self) -> tuple[str, str]:
        """接着哪通电话聊：同一个讨论、同一个 Claude 会话。返回 (Claude 会话, 给快思考的那几句)；那通电话没了就是新通话。"""
        row = db.row("SELECT session_id FROM voice_calls WHERE id=?", [self.resume]) if self.resume else None
        if not row:
            return "", ""
        said = voice_record.spoken_lines(self.resume)
        self.recent.extend(f"{'用户' if who == 'user' else '快思考'}：{text}" for who, text in said)
        session = db.row("SELECT id, engine_session FROM chat_sessions WHERE id=?", [row["session_id"]]) if row["session_id"] else None
        if session:
            self.sid = session["id"]
            self.rec.link(self.sid)
        return (session or {}).get("engine_session") or "", voice_rt.resume_note(said)

    def _on_slow_session(self, session: str) -> None:
        db.update("chat_sessions", self._session(), {"engine_session": session, "updated_at": db.now()})

    # ---------- 收发 ----------
    async def tell(self, **msg) -> None:
        try:
            await self.ws.send_text(json.dumps(msg, ensure_ascii=False))
        except (WebSocketDisconnect, RuntimeError):
            pass

    async def _up(self, type_: str, **kw) -> None:
        if type_ != "input_audio_buffer.append":
            self.rec.event("sent", type=type_, **kw)
        await self.up.send(json.dumps({"type": type_, **kw}, ensure_ascii=False))

    async def _inject(self, text: str, once: bool = False) -> None:
        self.injected += 1
        item_id = f"inj_{self.injected}"
        if once:
            self.once.append(item_id)
        await self._up("conversation.item.create",
                       item={"id": item_id, "type": "message", "role": "user", "content": [{"type": "input_text", "text": text}]})

    async def _drop_once(self) -> None:
        ids, self.once = self.once, []
        for item_id in ids:
            await self._up("conversation.item.delete", item_id=item_id)

    async def _respond(self) -> None:
        self.want_response = False
        self.response_active, self.asked_at = True, time.monotonic()  # 先占住，下一次检查不会重复触发
        await self._up("response.create", response={"modalities": ["audio", "text"]})

    # ---------- 工具 ----------
    async def _on_tool(self, ev: dict) -> None:
        name, call_id = ev.get("name"), ev.get("call_id")
        try:
            args = json.loads(ev.get("arguments") or "{}")
        except json.JSONDecodeError:
            args = {}
        t = self.thinker
        log.info("语音工具 %s", name)
        search_for = ""
        try:
            await asyncio.wait_for(self.heard.wait(), HEARD_WAIT_S)
        except asyncio.TimeoutError:
            pass
        if not voice_tools.tool_allowed(name):  # 没登记或没打开的一律不执行
            log.warning("语音工具没有权限：%s", name)
            out, follow = {"error": "这个工具现在不能用，直说做不了，不要假装做了"}, True
        elif time.monotonic() < self.hold_until:
            out, follow = {"status": "用户让你等，这件事不做"}, False
        elif name == "think_deep":
            out, follow = {"status": t.ask(str(args.get("objective", "")))}, not self.spoke_this_response
        elif name == "update_thinking":
            out, follow = {"status": t.update(str(args.get("info", "")))}, not self.spoke_this_response
        elif name == "get_thinking_status":
            out, follow = t.status(), True
        elif name == "cancel_thinking":
            out, follow = {"status": t.cancel()}, True
        elif name == "web_search" and self.last_user and not self.query_checked and not _query_from_user(str(args.get("query", "")), self.last_user):
            # 模型听错时搜词跟着错，结果会念成别的话题（2026-11-04 实测：新模型→新车、电影）。这时它手上有文字了，让它再给一次；追问时搜词本来就和原话不同，再给一次也能过
            self.query_checked = True
            log.info("搜索词和原话不一致，让模型核对")
            out = {"error": f"还没有搜。用户的原话是「{self.last_user}」，你可能听错了。按这句话的意思重新用 web_search，这次不要说话；这句话不是要搜东西就不要搜，按规矩处理。"}
            follow = True
        elif name == "web_search":
            search_for = str(args.get("query", ""))
            out, follow = {"status": "在查，结果会送来"}, False  # 结果几秒就到，不为这个多算一轮
        else:
            out, follow = {"error": f"没有这个工具：{name}"}, True
        self.rec.event("tool", name=name, args=args, out=out)
        await self._up("conversation.item.create",
                       item={"type": "function_call_output", "call_id": call_id, "output": json.dumps(out, ensure_ascii=False)})
        self.want_response = self.want_response or follow
        if search_for:
            await self._search(search_for)

    async def _search(self, query: str) -> None:
        """搜到的原文只留在本机，百炼只拿到念的那句。"""
        self.searching += 1
        started = time.monotonic()
        try:
            found = await asyncio.to_thread(voice_rt.web_search, query)
            spoken, usage = await asyncio.to_thread(voice_rt.spoken_search, self.last_user or query, found)
        finally:
            self.searching -= 1
        self._record("tool", f"web_search: {query}")
        self.rec.event("search", query=query, found=found, spoken=spoken, usage=usage, took_s=round(time.monotonic() - started, 2))
        self.outbox.append(("spoken", spoken))

    async def _forward_claimed(self, said: str = "") -> None:
        self.forward_said = said or self.forward_said
        wants_search = CLAIMS_SEARCH.search(self.forward_said) and voice_tools.enabled("web_search")
        if not wants_search and (self.thinker.task or not voice_tools.enabled("claude_code")):  # 已经在想了，多半是在说进度
            return
        if wants_search and self.searching:
            return
        if not self.last_user:  # 转写还没到，到了再转
            self.forward_waiting = True
            return
        self.forward_waiting = False
        self.rec.event("forward", said=self.forward_said, to="web_search" if wants_search else "think_deep", user=self.last_user)
        if wants_search:  # 说「我搜一下」就是搜，转去慢思考要多等半分钟（2026-11-04 实测）
            log.warning("模型说了搜却没调用工具，补搜")
            self._later(self._search(self.last_user))
            return
        log.warning("模型说了转交但没调用工具，补转")
        status = self.thinker.ask(self.last_user)
        await self._inject(f"【系统】这个问题开始想了（{status}），想好的答案之后会送来。")

    def _on_slow(self, kind: str, text: str) -> None:
        if kind in ("spoken", "brief"):
            self.rec.event("slow_" + kind, text=text, elapsed_s=self.thinker.status().get("elapsed_s"))
            self.outbox.append((kind, text))
        elif kind == "full":
            self.rec.event("slow_full", text=text)
            self._record("assistant", text)
            self._later(self.tell(type="slow", text=text))
        else:
            log.warning("慢思考没有结果：%s", text)
            self._record("error", f"慢思考没有结果：{text[:300]}")
            self.outbox.append(("failed", ""))

    def _later(self, coro) -> None:
        self.loop.create_task(coro)

    # ---------- 百炼事件 ----------
    def _flush_reply(self, heard: float | None = None) -> str:
        """把这一句记下来。被打断时只记听到的部分（模型生成得比播放快）。"""
        text, self.reply = self.reply.strip(), ""
        if not text:
            return ""
        if heard is None:
            self._record("fast", text)
            self.rec.event("fast", at=self.rec.at(self.audio_started), text=text)
            self.recent.append(f"快思考：{text}")
            return text
        part = text[:int(len(text) * heard)]
        self._record("fast", part + chat.INTERRUPTED)
        self.rec.event("fast", at=self.rec.at(self.audio_started), text=part, interrupted=True)
        self.recent.append(f"快思考：{part}（被打断）")
        return part

    async def _barge(self, now: float) -> None:
        active, audible = self.response_active, now < self.play_until
        if active:
            self.dropping = True
            await self._up("response.cancel")
        if not (active or audible):
            return
        heard = min(1.0, (now - self.audio_started) / self.audio_s) if self.audio_s else 0.0
        self.play_until = now
        self.rec.cut(self.rec.at(now))
        await self.tell(type="clear")
        part = self._flush_reply(heard)
        # 百炼没有截断接口，云端记的是整句：告诉它用户其实听到哪
        note = f"【系统】刚才那句用户只听到「{part[-60:]}」就打断了，后面的没听到。" if part else "【系统】刚才那句用户没听到就打断了。"
        if self.reading_answer:  # 用户问「有答案了吗」时直接接着念，不用再想一遍（2026-11-04 实测重想了 14 秒，结论一样）
            note += "这句是想好的答案，用户问结果时接着念没听到的部分，不要重新想。"
        await self._inject(note)

    async def _mute(self) -> None:
        """这句不让用户听到。不取消回应：工具调用可能还在后面，取消了问题就没人想了。"""
        self.muted, self.muted_text, self.dropping = True, self.reply, True
        self.reply = ""
        self.play_until = time.monotonic()
        self.rec.cut(self.rec.at(self.play_until))
        await self.tell(type="clear")  # 前面的句子可能已经发出去了

    async def _after_mute(self) -> None:
        """没调工具就重说一次；重说的不再拦，宁可漏一句也不能一直没声音。"""
        if CLAIMS_FORWARD.search(self.muted_text):
            await self._forward_claimed(self.muted_text)
        # 「等一下」这类话模型也可能回方括号：不能逼它开口，否则会没话找话
        await self._inject("【系统】刚才那句用户没听到。用户在等你回应就重新说，只说给用户听的话；用户让你等、或者不是在跟你说话，就什么都不说，也不要用工具。", once=True)
        self.retrying, self.want_response = True, True

    async def _on_event(self, ev: dict) -> None:
        t, now = ev.get("type"), time.monotonic()
        if t not in NOISY_EVENTS:
            self.rec.event("got", ev=ev)
        if t == "response.audio.delta":
            if self.dropping:
                return
            pcm = base64.b64decode(ev.get("delta", ""))
            if self.t_stop is not None:
                await self.tell(type="metrics", first_audio_after_stop_s=round(now - self.t_stop, 3))
                log.info("语音首响 %.3fs（从判定说完算）", now - self.t_stop)
                self.t_stop = None
            if now >= self.play_until:
                self.audio_started, self.audio_s = now, 0.0
            self.rec.bot(pcm, self.rec.at(max(now, self.play_until)))
            self.spoke_this_response = True
            self.audio_s += len(pcm) / 2 / OUT_RATE
            self.play_until = max(now, self.play_until) + len(pcm) / 2 / OUT_RATE
            await self.ws.send_bytes(pcm)
        elif t == "response.created":
            self.from_user = not self.asked_at or self.retrying  # 我们要的回应（念结果、报进度）不算回答用户
            self.guarded, self.retrying = not self.asked_at, False
            self.muted = False
            self.response_active, self.want_response, self.spoke_this_response, self.asked_at = True, False, False, 0.0
            self.tool_called = False
            self.dropping = self.reply_done = False
            if self.reply:  # 上一句还没放完就来了新回应
                self._flush_reply()
            if now < self.hold_until:
                await self._mute()
        elif t == "response.audio_transcript.delta":
            if self.muted:  # 判断要不要补转得看整句，一拦住就只有个「[」
                self.muted_text += ev.get("delta", "")
            elif not self.dropping:
                self.reply += ev.get("delta", "")
                if self.guarded and INTERNAL_WORDS.search(self.reply):
                    await self._mute()
        elif t == "response.audio_transcript.done":
            if self.muted:
                self.muted_text = ev.get("transcript") or self.muted_text
            elif not self.dropping:
                self.reply = ev.get("transcript") or self.reply
                if self.guarded and INTERNAL_WORDS.search(self.reply):
                    await self._mute()
                elif not self.heard.is_set():
                    self.early_reply = self.reply
                else:
                    await self.tell(type="reply", text=self.reply)
        elif t == "response.done":
            self.response_active, self.reply_done = False, True
            resp = ev.get("response") or {}
            self.rec.usage(resp.get("usage") or {})
            if resp.get("status") == "completed":
                await self._drop_once()
            elif resp.get("status") == "cancelled":  # 念到一半被打断的留着，后面的只在这里有
                self.once = []
            if resp.get("status") == "failed":
                log.warning("百炼回应失败：%s", resp.get("status_details"))
                await self.tell(type="error", message="这一句没答上来，再说一次")
            elif self.muted and now >= self.hold_until:
                log.warning("拦下内部说法：%s", self.muted_text[:80])
                if not self.tool_called and resp.get("status") == "completed":
                    await self._after_mute()
            elif self.from_user and not self.tool_called and not self.dropping and CLAIMS_FORWARD.search(self.reply):
                await self._forward_claimed(self.reply)
        elif t == "response.function_call_arguments.done":
            self.tool_called = True
            self.loop.create_task(self._on_tool(ev))
        elif t == "input_audio_buffer.speech_started":
            self.user_speaking, self.last_voice, self.last_user = True, now, ""
            self.speech_start = now
            self.early_reply = ""
            self.hold_until, self.query_checked = 0.0, False
            self.heard.clear()
            await self._barge(now)
        elif t == "input_audio_buffer.speech_stopped":
            self.user_speaking, self.last_speech_end, self.t_stop = False, now, now
        elif t == "conversation.item.input_audio_transcription.completed":
            text = (ev.get("transcript") or "").strip()
            self.heard.set()
            if HOLD.fullmatch(text):
                log.info("用户让等：%s", text)
                self._record("user", text)
                self.rec.event("user", at=self.rec.at(self.speech_start), text=text, hold=True)
                self.recent.append(f"用户：{text}")
                self.last_user, self.hold_until, self.forward_waiting = text, now + HOLD_S, False
                self.want_response = self.retrying = False  # 拦下内部说法时可能已经要了重说
                self.early_reply = ""
                await self.tell(type="user", text=text)
                if self.response_active or now < self.play_until:
                    await self._mute()
            elif text:
                self._record("user", text)
                self.rec.event("user", at=self.rec.at(self.speech_start), text=text)
                self.recent.append(f"用户：{text}")
                self.last_user = text
                self.reading_answer = False
                await self.tell(type="user", text=text)
                if self.forward_waiting:
                    await self._forward_claimed()
        elif t == "error":
            log.warning("百炼报错：%s", ev.get("error"))

    # ---------- 调度：回应、结果、进度都等安全的时候才说 ----------
    def _safe(self, now: float) -> bool:
        return now >= self.play_until and now - self.last_speech_end >= SAFE_SILENCE_S

    async def _send_status(self, now: float) -> None:
        st = self.thinker.status()
        status = {"talk": "listening" if self.user_speaking else "speaking" if now < self.play_until else "idle",
                  "thinking": st["state"] == "thinking", "doing": st.get("doing", ""), "searching": self.searching > 0}
        if status != self.last_status:
            self.last_status = status
            await self.tell(type="status", **status)

    async def _pump(self) -> None:
        now = time.monotonic()
        if self.reply and self.reply_done and now >= self.play_until:
            self._flush_reply()
        await self._send_status(now)
        if self.early_reply and (self.heard.is_set() or now - self.last_speech_end > HEARD_WAIT_S):
            await self.tell(type="reply", text=self.early_reply)
            self.early_reply = ""
        if self.asked_at and now - self.asked_at > RESPONSE_WAIT_S:
            self.response_active, self.asked_at = False, 0.0
        if now - self.last_voice > IDLE_S:
            await self.tell(type="end", reason="很久没听到说话，已挂断")
            raise _End
        if self.response_active or self.user_speaking or now < self.hold_until:
            return
        if self.want_response:
            await self._respond()
            return
        if not self._safe(now):
            return
        while self.outbox and self.outbox[0][0] == "brief":
            await self._inject(f"{voice_rt.NOTES_MARK}{self.outbox.popleft()[1][:BRIEF_MAX]}")
        if self.outbox:
            kind, text = self.outbox.popleft()
            await self._inject(f"{voice_rt.ANSWER_MARK}（直接念下面这段，一字不改）{text}" if kind == "spoken"
                               else "【系统】这个问题这次没想出结果。告诉用户没想出来，可以换个问法，不要自己回答这个问题。", once=True)
            self.reading_answer = kind == "spoken"
            await self._respond()
            return
        doing = self.thinker.due_cue(CUE_AT)
        if doing:
            await self._inject(f"【进度】你正{doing}。用一句很短的话告诉用户，不要说别的。", once=True)
            await self._respond()

    # ---------- 三个循环 ----------
    async def _from_client(self) -> None:
        while True:
            msg = await self.ws.receive()
            if msg["type"] == "websocket.disconnect":
                return
            if msg.get("bytes"):
                self.rec.mic(msg["bytes"])
                await self._up("input_audio_buffer.append", audio=base64.b64encode(msg["bytes"]).decode())
            elif msg.get("text") and json.loads(msg["text"]).get("type") == "hangup":
                return

    async def _from_up(self) -> None:
        async for raw in self.up:
            await self._on_event(json.loads(raw))

    async def _tick(self) -> None:
        while True:
            await asyncio.sleep(TICK_S)
            await self._pump()

    async def run(self) -> None:
        import websockets
        cfg = _rt_config()
        model = cfg.get("model") or voice_rt.DEFAULT_MODEL
        try:
            self.up = await websockets.connect(voice_rt.endpoint(model), additional_headers=voice_rt.headers(),
                                               proxy=None, max_size=None, open_timeout=5)
        except Exception as e:  # noqa: BLE001 —— 连不上就让前端切回本地链路
            log.warning("连不上百炼：%s", e)
            await self.tell(type="fallback", reason="实时通话连不上，切回本地")
            return
        voice = cfg.get("voice") or voice_rt.DEFAULT_VOICE
        self.rec.open(model, voice)
        live_calls.add(self.rec.id)
        engine_session, resume_note = self._pick_up()
        ctx, dirs = chat._context("talk", "")
        self.thinker = Thinker(self.loop, self._on_slow, system=agent.build_system("talk", ctx), dirs=dirs,
                               model=agent.module_model("talk"), session=engine_session, history=lambda: "\n".join(self.recent),
                               on_session=self._on_slow_session)
        chat.active += 1  # 自动重启要等通话结束
        tasks = []
        try:
            await self._up("session.update", session=voice_rt.session_config(
                voice=voice, speech_rate=cfg.get("speech_rate") or 1.0,
                turn_detection=cfg.get("turn_detection"), resume=resume_note))
            asyncio.get_running_loop().run_in_executor(None, self.thinker.warm)
            client, upstream, tick = [asyncio.create_task(c) for c in (self._from_client(), self._from_up(), self._tick())]
            tasks = [client, upstream, tick]
            await self.tell(type="ready", model=model, call=self.rec.id, resumed=bool(resume_note or self.sid))
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            if not client.done():
                failed = tick.done() and isinstance(tick.exception(), _End)
                if not failed:  # 中途断线：前端切回本地，下一句接着说
                    log.warning("和百炼的连接断了：%s", upstream.exception() if upstream.done() else tick.exception())
                    await self.tell(type="fallback", reason="实时通话断了，切回本地")
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            self.thinker.cancel()
            self._flush_reply()
            await self.up.close()
            self.rec.close()
            live_calls.discard(self.rec.id)
            if self.rec.dir:
                self.loop.run_in_executor(None, voice_record.finish, self.rec.dir)
            chat.active -= 1


def _same_origin(ws: WebSocket) -> bool:
    """WebSocket 不受跨域限制：别的网页不能借本机连接用密钥、问本机资料。"""
    origin = ws.headers.get("origin")
    return not origin or urlsplit(origin).netloc == ws.headers.get("host")


@router.get("/api/voice/rt/status")
def rt_status():
    cfg = _rt_config()
    return {"configured": configured(), "model": cfg.get("model") or voice_rt.DEFAULT_MODEL,
            "voice": cfg.get("voice") or voice_rt.DEFAULT_VOICE}


@router.get("/api/voice/tools")
def tools():
    return voice_tools.listing()


@router.get("/api/voice/calls")
def calls(limit: int = 50):
    rows = db.rows("""SELECT c.*, s.title FROM voice_calls c LEFT JOIN chat_sessions s ON s.id=c.session_id
                      ORDER BY c.id DESC LIMIT ?""", [limit])
    return [{**r, "size_bytes": voice_record.size_of(r["id"])} for r in rows]


@router.get("/api/voice/calls/usage")
def calls_usage():
    return {"bytes": voice_record.total_size()}


@router.get("/api/voice/calls/{call_id}")
def call_detail(call_id: int):
    """原始事件太多，页面只要说的话和工具；要分析就看 /raw。"""
    row = db.row("SELECT * FROM voice_calls WHERE id=?", [call_id])
    if not row:
        raise HTTPException(404)
    return {**row, "events": [e for e in voice_record.events(call_id) if e["kind"] not in ("sent", "got")]}


@router.delete("/api/voice/calls/{call_id}")
def delete_call(call_id: int):
    if not db.row("SELECT id FROM voice_calls WHERE id=?", [call_id]):
        raise HTTPException(404)
    if call_id in live_calls:
        raise HTTPException(409, "这通电话还没挂")
    voice_record.remove(call_id)
    return {"ok": True}


@router.get("/api/voice/calls/{call_id}/raw")
def call_raw(call_id: int):
    return voice_record.events(call_id)


@router.get("/api/voice/calls/{call_id}/audio")
def call_audio(call_id: int):
    call_dir = voice_record.CALLS_DIR / str(call_id)
    if not voice_record.finish(call_dir):
        raise HTTPException(404, "这通电话没有录音")
    return FileResponse(call_dir / "call.m4a", media_type="audio/mp4")


@router.websocket("/api/voice/rt")
async def rt(ws: WebSocket, resume: int = 0):
    if not _same_origin(ws):
        await ws.close(code=4403)
        return
    await ws.accept()
    try:
        await Call(ws, resume).run()
    finally:
        try:
            await ws.close()
        except (RuntimeError, WebSocketDisconnect):
            pass
