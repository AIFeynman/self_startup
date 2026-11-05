"""语音通话的中转：浏览器 ↔ 这里 ↔ 百炼实时模型。密钥只在服务端。

上行二进制帧是 16k PCM，下行二进制帧是 24k PCM，其余都是 JSON 控制消息。
用户的每句话都交给本机 Claude（voice_think）答，百炼只负责听和念。
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
SAFE_SILENCE_S = 1.0  # 用户停了这么久才开口
CUE_AT = (8.0, 25.0)  # 想了这么久时报进度，一个任务最多两次
RESPONSE_WAIT_S = 5  # 要了回应这么久还没开始（比如百炼报错），就别再占着，后面的话还要念
IDLE_S = 600  # 这么久没人说话就挂断，免得一直计费
TICK_S = 0.1
HOLD_S = 10  # 用户说「等一下」后，这么久内不主动开口；再说话就解除
FILLER_S = 2.0  # 这么久还没想出来就先垫一句，免得用户以为断了
FILLERS = ("嗯，我想想。", "我想一下。", "好，稍等。")
NO_BRAIN = "本机 Claude 现在关着，我答不了，可以在讨论页打开。"
# 这些事件量大又没有内容，不进通话记录（音频本身在录音文件里，转写的完整句子在 done 事件里）
NOISY_EVENTS = {"response.audio.delta", "response.audio_transcript.delta", "response.function_call_arguments.delta", "response.text.delta"}
# 整句都是才算，「等一下，我补充一点」不算
HOLD = re.compile(r"(?:你先|你|先)?(?:等一?下|等等|稍等(?:一下)?|等会儿?|等我一下)[啊哈吧]?[。！？!?,，.\s]*")
CANCEL = re.compile(r"[那好]?就?(?:别想了|不用想了|别查了|不用查了|别搜了|不用搜了|算了)[啊哈吧]?[。！？!?,，.\s]*")
# 还在想的时候问进度：照实说在做什么，不用停掉重想
PROGRESS = re.compile(r"好了(?:吗|没)|还没(?:好|想好|找到|查到|搜到)|怎么样了|还要多久|还要等")
PROGRESS_MAX = 12  # 长句多半是在说别的
# 固定的客套话不用等 Claude。百炼自己接话只会复述（「谢谢」答「谢谢」，2026-11-05 实测），所以回什么写死。
# 「好的」「行」可能是在答应上一句，要留给 Claude。
QUICK = ((re.compile(r"(?:喂)?(?:你|您)?(?:能|可以)?听(?:得到|得见|到了?|见了?)(?:我说话|我的声音)?(?:吗|嘛|没|没有)"), "听得到，你说。"),
         (re.compile(r"喂+|你好|您好|哈喽|嗨|hello|hi|在吗|喂在吗"), "你好，你说。"),
         (re.compile(r"(?:好的)?谢谢(?:你|您)?|多谢|感谢"), "不客气。"),
         (re.compile(r"(?:好的)?(?:再见|拜拜)"), "好，再见。"))


def quick_reply(text: str) -> str:
    said = re.sub(r"[\s，。！？,.!?、~～]", "", text).lower()
    return next((reply for pattern, reply in QUICK if pattern.fullmatch(said)), "")


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
        self.loop = asyncio.get_running_loop()
        self.response_active = self.user_speaking = self.dropping = self.reply_done = self.reply_now = False
        self.asked_at = 0.0
        self.hold_until = self.filler_at = 0.0
        self.fillers = 0
        now = time.monotonic()
        self.play_until = self.audio_started = 0.0
        self.audio_s = 0.0
        self.last_speech_end, self.last_voice, self.t_stop = 0.0, now, None
        self.reply = ""
        self.outbox: deque[str] = deque()
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

    def _pick_up(self) -> str:
        """接着哪通电话聊：同一个讨论、同一个 Claude 会话。返回 Claude 会话；那通电话没了就是新通话。"""
        row = db.row("SELECT session_id FROM voice_calls WHERE id=?", [self.resume]) if self.resume else None
        if not row:
            return ""
        self.recent.extend(f"{'用户' if who == 'user' else '你'}：{text}" for who, text in voice_record.spoken_lines(self.resume))
        session = db.row("SELECT id, engine_session FROM chat_sessions WHERE id=?", [row["session_id"]]) if row["session_id"] else None
        if session:
            self.sid = session["id"]
            self.rec.link(self.sid)
        return (session or {}).get("engine_session") or ""

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

    async def _say(self, text: str) -> None:
        """让百炼把这段话念出来。"""
        await self._up("conversation.item.create", item={"type": "message", "role": "user", "content": [{"type": "input_text", "text": text}]})
        self.response_active, self.asked_at = True, time.monotonic()  # 先占住，下一次检查不会重复触发
        self.reply_now = False
        await self._up("response.create", response={"modalities": ["audio", "text"], "instructions": voice_rt.read_instructions(text)})

    # ---------- 用户说的每句话都到这里 ----------
    def _route(self, text: str) -> None:
        t = self.thinker
        self.outbox.clear()  # 还没念的是回答上一句的，用户已经往下说了
        quick = "" if t.task else quick_reply(text)  # 还在想就并进去，别丢了正在想的事
        if quick:
            self.outbox.append(quick)
            self.reply_now = True
        elif not voice_tools.enabled("claude_code"):
            self.outbox.append(NO_BRAIN)
        elif t.task and CANCEL.fullmatch(text):
            t.cancel()
            self.outbox.append("好，不想了。")
        elif t.task and not t.task.spoke and len(text) <= PROGRESS_MAX and PROGRESS.search(text):
            self.outbox.append(f"{t.status()['doing']}，稍等。")
        else:
            t.hear(text)
            self.filler_at = time.monotonic() + FILLER_S

    def _on_slow(self, kind: str, text: str) -> None:
        if kind == "spoken":
            self.rec.event("slow_spoken", text=text, elapsed_s=self.thinker.status().get("elapsed_s"))
            self.filler_at = 0.0
            self.outbox.append(text)
        elif kind == "tool":
            self.rec.event("tool", text=text)
            self._record("tool", text.replace("mcp__voice_search__", ""))
        elif kind == "full":
            self.rec.event("slow_full", text=text)
            self._record("assistant", text)
            self._later(self.tell(type="slow", text=text))
        else:
            log.warning("本机 Claude 没有结果：%s", text)
            self._record("error", f"本机 Claude 没有结果：{text[:300]}")
            self.filler_at = 0.0
            self.outbox.append("这个问题这次没想出来，可以换个问法。")

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
            self.recent.append(f"你：{text}")
            return text
        part = text[:int(len(text) * heard)]
        self._record("fast", part + chat.INTERRUPTED)
        self.rec.event("fast", at=self.rec.at(self.audio_started), text=part, interrupted=True)
        self.recent.append(f"你：{part}（被打断，后面的用户没听到）")
        return part

    async def _barge(self, now: float) -> None:
        reading, audible = self.response_active and not self.dropping, now < self.play_until
        self.asked_at = 0.0  # 要了还没开始的回应，开始了也别念
        if reading:
            self.dropping = True
            await self._up("response.cancel")
        if not (reading or audible):
            return
        heard = min(1.0, (now - self.audio_started) / self.audio_s) if self.audio_s else 0.0
        self.play_until = now
        self.rec.cut(self.rec.at(now))
        await self.tell(type="clear")
        self._flush_reply(heard)

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
            self.audio_s += len(pcm) / 2 / OUT_RATE
            self.play_until = max(now, self.play_until) + len(pcm) / 2 / OUT_RATE
            await self.ws.send_bytes(pcm)
        elif t == "response.created":
            # 不是我们要的就是百炼听完自己接的话，丢掉不播：create_response:false 它不认，取消也来不及，几十毫秒就生成完了（2026-11-04 实测）
            self.dropping = not self.asked_at
            self.response_active, self.asked_at, self.reply_done = True, 0.0, False
            if self.reply:  # 上一句还没放完就来了新回应
                self._flush_reply()
        elif t == "response.audio_transcript.delta":
            if not self.dropping:
                self.reply += ev.get("delta", "")
        elif t == "response.audio_transcript.done":
            if not self.dropping:
                self.reply = ev.get("transcript") or self.reply
                await self.tell(type="reply", text=self.reply)
        elif t == "response.done":
            self.response_active, self.reply_done = False, True
            resp = ev.get("response") or {}
            self.rec.usage(resp.get("usage") or {})
            if resp.get("status") == "failed" and not self.dropping:
                log.warning("百炼回应失败：%s", resp.get("status_details"))
                await self.tell(type="error", message="这一句没念出来，再说一次")
        elif t == "input_audio_buffer.speech_started":
            self.user_speaking, self.last_voice, self.speech_start, self.hold_until = True, now, now, 0.0
            await self._barge(now)
        elif t == "input_audio_buffer.speech_stopped":
            self.user_speaking, self.last_speech_end, self.t_stop = False, now, now
        elif t == "conversation.item.input_audio_transcription.completed":
            text = (ev.get("transcript") or "").strip()
            if text:
                hold = bool(HOLD.fullmatch(text))
                self._record("user", text)
                self.rec.event("user", at=self.rec.at(self.speech_start), text=text, **({"hold": True} if hold else {}))
                self.recent.append(f"用户：{text}")
                await self.tell(type="user", text=text)
                if hold:
                    log.info("用户让等：%s", text)
                    self.hold_until = now + HOLD_S
                else:
                    self._route(text)
        elif t == "error":
            log.warning("百炼报错：%s", ev.get("error"))

    # ---------- 调度：等安全的时候才说 ----------
    def _safe(self, now: float) -> bool:
        return now >= self.play_until and (self.reply_now or now - self.last_speech_end >= SAFE_SILENCE_S)

    async def _send_status(self, now: float) -> None:
        st = self.thinker.status()
        status = {"talk": "listening" if self.user_speaking else "speaking" if now < self.play_until else "idle",
                  "thinking": st["state"] == "thinking", "doing": st.get("doing", "")}
        if status != self.last_status:
            self.last_status = status
            await self.tell(type="status", **status)

    async def _pump(self) -> None:
        now = time.monotonic()
        if self.reply and self.reply_done and now >= self.play_until:
            self._flush_reply()
        await self._send_status(now)
        if self.asked_at and now - self.asked_at > RESPONSE_WAIT_S:
            self.response_active, self.asked_at = False, 0.0
        if now - self.last_voice > IDLE_S:
            await self.tell(type="end", reason="很久没听到说话，已挂断")
            raise _End
        if self.response_active or self.user_speaking or now < self.hold_until or not self._safe(now):
            return
        if self.filler_at and now >= self.filler_at:
            self.filler_at = 0.0
            if self.thinker.task and not self.thinker.task.spoke and not self.outbox:
                self.outbox.append(FILLERS[self.fillers % len(FILLERS)])
                self.fillers += 1
        if self.outbox:
            await self._say(self.outbox.popleft())
            return
        doing = self.thinker.due_cue(CUE_AT)
        if doing:
            await self._say(f"{doing}，稍等。")

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
        engine_session = self._pick_up()
        ctx, dirs = chat._context("talk", "")
        self.thinker = Thinker(self.loop, self._on_slow, system=agent.build_system("talk", ctx), dirs=dirs,
                               model=agent.module_model("talk"), mcp=voice_tools.slow_mcp(), session=engine_session, history=lambda: "\n".join(self.recent),
                               on_session=self._on_slow_session)
        chat.active += 1  # 自动重启要等通话结束
        tasks = []
        try:
            await self._up("session.update", session=voice_rt.session_config(
                voice=voice, speech_rate=cfg.get("speech_rate") or 1.0, turn_detection=cfg.get("turn_detection")))
            asyncio.get_running_loop().run_in_executor(None, self.thinker.warm)
            client, upstream, tick = [asyncio.create_task(c) for c in (self._from_client(), self._from_up(), self._tick())]
            tasks = [client, upstream, tick]
            await self.tell(type="ready", model=model, call=self.rec.id, resumed=bool(self.sid))
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
