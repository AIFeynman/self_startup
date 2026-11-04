"""快慢思考通话的中转和慢思考调度：百炼、浏览器、Claude Code 都用假的，不联网。"""
import asyncio
import base64
import json
import threading
import time

import httpx
import pytest
import websockets

from app import agent, chat, db, voice_call, voice_rt
from app.voice_think import Thinker, body_of, fallback_spoken

ANSWER = "<spoken>你上周定的是先做中转。</spoken><brief>先做中转，理由是最影响体验</brief>\n完整回答：记录在 secret.md 第 3 行"


class FakeWS:
    """假浏览器：in_ 放它要发的消息，sent 收服务端发来的。"""

    def __init__(self, origin=None, host="127.0.0.1:8780"):
        self.in_, self.sent, self.audio = asyncio.Queue(), [], []
        self.headers = {"host": host, **({"origin": origin} if origin else {})}

    async def receive(self):
        return await self.in_.get()

    async def send_text(self, text):
        self.sent.append(json.loads(text))

    async def send_bytes(self, b):
        self.audio.append(b)

    def told(self, kind):
        return [m for m in self.sent if m["type"] == kind]


class FakeUp:
    """假百炼：sent 收中转发上去的事件，feed() 模拟百炼发下来。"""

    def __init__(self):
        self.q, self.sent, self.closed = asyncio.Queue(), [], False

    async def send(self, raw):
        self.sent.append(json.loads(raw))

    async def close(self):
        self.closed = True

    def __aiter__(self):
        return self

    async def __anext__(self):
        ev = await self.q.get()
        if isinstance(ev, Exception):
            raise ev
        return json.dumps(ev, ensure_ascii=False)

    def feed(self, type_, **kw):
        self.q.put_nowait({"type": type_, **kw})

    def of(self, kind):
        return [e for e in self.sent if e["type"] == kind]

    def said(self):
        return [e["item"]["content"][0]["text"] for e in self.of("conversation.item.create") if e["item"]["type"] == "message"]


def audio(seconds=0.1):
    return base64.b64encode(bytes(int(voice_call.OUT_RATE * seconds) * 2)).decode()


async def until(cond, timeout=3):
    end = time.monotonic() + timeout
    while not cond():
        assert time.monotonic() < end, "等不到"
        await asyncio.sleep(0.01)


@pytest.fixture
def env(monkeypatch, client):
    up = FakeUp()
    with client:  # 进一次 lifespan 建好表
        pass

    async def connect(*a, **k):
        return up

    def run(prompt, **kw):
        kw["on_proc"](object())
        yield {"type": "delta", "text": ANSWER}
        yield {"type": "done", "text": ANSWER}
    monkeypatch.setattr(websockets, "connect", connect)
    monkeypatch.setenv("DASHSCOPE_WORKSPACE_ID", "ws-x")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "k")
    monkeypatch.setattr(agent, "warm_up", lambda **k: None)
    monkeypatch.setattr(agent, "stop", lambda p: None)
    monkeypatch.setattr(agent, "run_stream", run)
    monkeypatch.setattr(voice_call, "SAFE_SILENCE_S", 0.05)
    monkeypatch.setattr(voice_call, "TICK_S", 0.01)
    return up


def _call(body):
    ws = FakeWS()
    call = {}

    async def go():
        call["c"] = voice_call.Call(ws)
        run = asyncio.create_task(call["c"].run())
        await until(lambda: ws.told("ready"))
        try:
            await body(ws, call["c"])
        finally:
            ws.in_.put_nowait({"type": "websocket.disconnect"})
            await asyncio.wait_for(run, 3)
    asyncio.run(go())
    return ws, call["c"]


def _rows(sid):
    return [(r["role"], r["content"]) for r in db.rows("SELECT role, content FROM chat_messages WHERE session_id=? ORDER BY id", [sid])]


def test_session_goes_up_with_tools_and_mic_is_forwarded(env):
    async def body(ws, call):
        ws.in_.put_nowait({"type": "websocket.receive", "bytes": b"\x01\x02"})
        await until(lambda: env.of("input_audio_buffer.append"))
    _call(body)
    assert {t["function"]["name"] for t in env.of("session.update")[0]["session"]["tools"]} >= {"ask_claude", "web_search"}
    assert base64.b64decode(env.of("input_audio_buffer.append")[0]["audio"]) == b"\x01\x02"
    assert env.closed and chat.active == 0


def test_barge_in_cancels_clears_and_drops_late_audio(env):
    async def body(ws, call):
        env.feed("input_audio_buffer.speech_stopped")
        env.feed("conversation.item.input_audio_transcription.completed", transcript="第一句")
        env.feed("response.created")
        env.feed("response.audio.delta", delta=audio(5))
        env.feed("response.audio_transcript.delta", delta="这是一句很长的回答，用户没听完")
        await until(lambda: ws.audio and call.reply)
        env.feed("input_audio_buffer.speech_started")
        await until(lambda: ws.told("clear"))
        assert env.of("response.cancel")
        env.feed("response.audio.delta", delta=audio())  # 取消之后才到的
        env.feed("response.done", response={"status": "cancelled"})
        await asyncio.sleep(0.05)
        assert len(ws.audio) == 1
        assert any("打断" in t for t in env.said())  # 云端记的是整句，要告诉它用户只听到哪
    ws, call = _call(body)
    rows = _rows(call.sid)
    assert rows[0] == ("user", "第一句")
    assert rows[1][0] == "fast" and rows[1][1].endswith(chat.INTERRUPTED)
    assert ws.told("metrics")[0]["first_audio_after_stop_s"] >= 0


def test_barge_in_after_generation_finished_still_stops_playback(env):
    # 实测模型生成比播放快得多：用户打断时回应常常已经结束，cancel 会报错，但还在放的声音要停
    async def body(ws, call):
        env.feed("response.created")
        env.feed("response.audio.delta", delta=audio(5))
        env.feed("response.audio_transcript.done", transcript="已经全部生成完的一句")
        env.feed("response.done", response={"status": "completed"})
        await until(lambda: not call.response_active and call.reply_done)
        env.feed("input_audio_buffer.speech_started")
        await until(lambda: ws.told("clear"))
        assert not env.of("response.cancel")
    ws, call = _call(body)
    assert _rows(call.sid)[0][1].endswith(chat.INTERRUPTED)


def test_ask_claude_result_is_spoken_when_safe_and_full_stays_local(env):
    async def body(ws, call):
        env.feed("response.created")
        env.feed("response.function_call_arguments.done", call_id="c1", name="ask_claude", arguments='{"objective":"上周定了啥"}')
        await until(lambda: env.of("conversation.item.create"))
        env.feed("response.done", response={"status": "completed"})
        await until(lambda: env.of("response.create"))  # 先接一句
        env.feed("response.created")
        env.feed("response.done", response={"status": "completed"})
        await until(lambda: any("慢思考结果" in t for t in env.said()))
        await until(lambda: ws.told("slow"))
        env.feed("response.created")
        env.feed("response.done", response={"status": "completed"})
        await until(lambda: any("慢思考提纲" in t for t in env.said()))  # 提纲悄悄记下，不触发说话
    ws, call = _call(body)
    output = [e["item"] for e in env.of("conversation.item.create") if e["item"]["type"] == "function_call_output"][0]
    assert json.loads(output["output"]) == {"status": "accepted"} and output["call_id"] == "c1"
    said = env.said()
    assert "【慢思考提纲】先做中转，理由是最影响体验" in said and any("你上周定的是先做中转。" in t and "慢思考结果" in t for t in said)
    assert env.of("response.create")
    # 完整回答只给本机：不上云，进记录，显示在屏幕上
    assert "secret.md" not in json.dumps(env.sent, ensure_ascii=False)
    assert "secret.md" in ws.told("slow")[0]["text"]
    assert ("assistant", "完整回答：记录在 secret.md 第 3 行") in _rows(call.sid)


def _say_without_tool(reply, transcript_first=True):
    def feed(env):
        if transcript_first:
            env.feed("conversation.item.input_audio_transcription.completed", transcript="我纠结先做哪个")
        env.feed("response.created")
        env.feed("response.audio_transcript.done", transcript=reply)
        env.feed("response.done", response={"status": "completed"})
        if not transcript_first:
            env.feed("conversation.item.input_audio_transcription.completed", transcript="我纠结先做哪个")
    return feed


@pytest.mark.parametrize("transcript_first", [True, False])
def test_claimed_forward_without_tool_call_is_forwarded(env, monkeypatch, transcript_first):
    # 实测 Flash 会只说「我转给慢思考」而不调工具；转写也可能比回应晚到
    asked = []

    def run(prompt, **kw):
        asked.append(prompt)
        kw["on_proc"](object())
        yield {"type": "done", "text": ANSWER}
    monkeypatch.setattr(agent, "run_stream", run)

    async def body(ws, call):
        _say_without_tool("这个我想一下。", transcript_first)(env)
        await until(lambda: any("你上周定的是先做中转" in t for t in env.said()))  # 念结果等下一拍，不能只等 slow
    ws, call = _call(body)
    assert "我纠结先做哪个" in asked[0]


def test_tool_name_spoken_aloud_counts_as_forward(env, monkeypatch):
    # 实测 Flash 偶尔把「[调用 ask_claude]」当话说出来，工具其实没调
    asked = []

    def run(prompt, **kw):
        asked.append(prompt)
        kw["on_proc"](object())
        yield {"type": "done", "text": ANSWER}
    monkeypatch.setattr(agent, "run_stream", run)

    async def body(ws, call):
        _say_without_tool("[调用 ask_claude]")(env)
        await until(lambda: asked)
    _call(body)


def test_plain_reply_or_our_own_response_is_not_forwarded(env):
    async def body(ws, call):
        _say_without_tool("听得见，我在呢。")(env)
        await asyncio.sleep(0.05)
        assert call.thinker.task is None
        call.last_user = "好的"
        await call._respond()  # 念结果时的话里有「慢思考」，不算转交
        env.feed("response.created")
        env.feed("response.audio_transcript.done", transcript="慢思考说先做中转。")
        env.feed("response.done", response={"status": "completed"})
        await until(lambda: call.reply_done and not call.response_active)
        await asyncio.sleep(0.05)
        assert call.thinker.task is None
    _call(body)


def test_result_waits_while_user_is_talking(env):
    async def body(ws, call):
        env.feed("input_audio_buffer.speech_started")
        await until(lambda: call.user_speaking)
        call.thinker.ask("上周定了啥")
        await until(lambda: ws.told("slow"))
        await asyncio.sleep(0.1)
        assert not any("慢思考结果" in t for t in env.said())
        env.feed("input_audio_buffer.speech_stopped")
        await until(lambda: any("慢思考结果" in t for t in env.said()))
    _call(body)


def test_web_search_tool_returns_results_and_replies(env, monkeypatch):
    monkeypatch.setattr(voice_rt, "web_search", lambda q: {"results": [{"title": q}]})

    async def body(ws, call):
        env.feed("response.created")
        env.feed("response.function_call_arguments.done", call_id="s1", name="web_search", arguments='{"query":"杭州天气"}')
        await until(lambda: env.of("conversation.item.create"))
        env.feed("response.done", response={"status": "completed"})
        await until(lambda: env.of("response.create"))
    _call(body)
    out = env.of("conversation.item.create")[0]["item"]
    assert out["call_id"] == "s1" and json.loads(out["output"]) == {"results": [{"title": "杭州天气"}]}


def test_upstream_drop_falls_back_to_local(env):
    ws = FakeWS()

    async def go():
        run = asyncio.create_task(voice_call.Call(ws).run())
        await until(lambda: ws.told("ready"))
        env.q.put_nowait(OSError("断了"))
        await asyncio.wait_for(run, 3)
    asyncio.run(go())
    assert ws.told("fallback") and chat.active == 0


def test_cannot_connect_falls_back_to_local(env, monkeypatch):
    async def refuse(*a, **k):
        raise OSError("连不上")
    monkeypatch.setattr(websockets, "connect", refuse)
    ws = FakeWS()

    async def go():
        await voice_call.Call(ws).run()
    asyncio.run(go())
    assert ws.told("fallback") and chat.active == 0


def test_response_that_never_starts_does_not_block_results(env, monkeypatch):
    monkeypatch.setattr(voice_call, "RESPONSE_WAIT_S", 0.05)

    async def body(ws, call):
        call.want_response = True
        await until(lambda: env.of("response.create"))
        await until(lambda: not call.response_active)  # 百炼没有回应 response.create，不能一直占着
    _call(body)


def test_other_sites_cannot_open_the_call():
    assert voice_call._same_origin(FakeWS(origin="http://127.0.0.1:8780"))
    assert voice_call._same_origin(FakeWS())
    assert not voice_call._same_origin(FakeWS(origin="https://evil.example"))
    assert not voice_call._same_origin(FakeWS(origin="http://127.0.0.1:9999"))


# ---------- 慢思考调度 ----------
def _thinker(monkeypatch, events=(), gate=None):
    got = []

    def run(prompt, **kw):
        run.prompts.append(prompt)
        kw["on_proc"](object())
        if gate:
            gate.wait(3)
        yield from events
    run.prompts = []
    monkeypatch.setattr(agent, "run_stream", run)
    monkeypatch.setattr(agent, "warm_up", lambda **k: None)
    monkeypatch.setattr(agent, "stop", lambda p: None)

    class Loop:
        def call_soon_threadsafe(self, fn):
            fn()
    return Thinker(Loop(), lambda k, t: got.append((k, t)), system="s", dirs=[], history=lambda: "用户：你好"), got, run


def test_second_question_queues_and_third_merges(monkeypatch):
    gate = threading.Event()
    t, got, run = _thinker(monkeypatch, [{"type": "done", "text": ANSWER}], gate)
    assert t.ask("甲") == "accepted" and t.ask("乙") == "queued" and t.ask("丙") == "queued"
    assert t.queued == "乙；丙"
    gate.set()
    end = time.monotonic() + 3
    while len(run.prompts) < 2 and time.monotonic() < end:
        time.sleep(0.01)
    assert "乙；丙" in run.prompts[1] and "用户：你好" in run.prompts[1]


def test_update_restarts_with_new_info_and_old_result_is_dropped(monkeypatch):
    gate = threading.Event()
    t, got, run = _thinker(monkeypatch, [{"type": "done", "text": ANSWER}], gate)
    t.ask("甲")
    old = t.task
    assert t.update("其实是周四") == "updated"
    assert old.cancelled and "其实是周四" in t.task.objective and "甲" in t.task.objective
    assert t.cancel() == "cancelled" and t.status() == {"state": "idle"}
    gate.set()
    time.sleep(0.05)
    assert got == []


def test_cue_only_reports_real_new_activity(monkeypatch):
    t, _, _ = _thinker(monkeypatch, [], threading.Event())
    t.ask("甲")
    assert t.due_cue((0, 0)) == ""  # 还没有工具动作，不编
    t.task.doing = "在读资料"
    assert t.due_cue((0, 0)) == "在读资料"
    assert t.due_cue((0, 0)) == ""  # 没有新动作
    t.task.doing = "在上网查"
    assert t.due_cue((0, 0)) == "在上网查"
    t.task.doing = "在搜资料"
    assert t.due_cue((0, 0)) == ""  # 最多两次
    t.cancel()


def test_output_format_fallbacks():
    assert fallback_spoken("**结论**是先做。理由有二。第一快。第二稳。") == "结论是先做。理由有二。第一快。"
    assert body_of(ANSWER) == "完整回答：记录在 secret.md 第 3 行"
    assert body_of("<spoken>只有这句</spoken>") == "只有这句"


# ---------- 搜索 ----------
def test_web_search_trims_and_survives_errors(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "k")
    results = [{"title": f"t{i}", "site_name": "s", "date": "2026-11-01T00:00", "summary": "x" * 900, "content": "y" * 9000} for i in range(9)]
    seen = {}

    def ok(url, **kw):
        seen.update(url=url, **kw)
        return httpx.Response(200, json={"results": results}, request=httpx.Request("POST", url))
    monkeypatch.setattr(httpx, "post", ok)
    r = voice_rt.web_search("杭州天气")
    assert seen["url"].endswith("/v1/tools/search") and seen["json"] == {"model": "deepseek-search", "query": "杭州天气"}
    assert seen["trust_env"] is False
    assert len(r["results"]) == 5 and len(r["results"][0]["summary"]) == 300 and "content" not in r["results"][0]
    assert r["results"][0]["date"] == "2026-11-01"

    def bad(url, **kw):
        raise httpx.ConnectTimeout("超时")
    monkeypatch.setattr(httpx, "post", bad)
    assert "error" in voice_rt.web_search("杭州天气")
    monkeypatch.delenv("DEEPSEEK_API_KEY")
    assert "error" in voice_rt.web_search("杭州天气")
