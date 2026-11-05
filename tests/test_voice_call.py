"""语音通话的中转和本机 Claude 调度：百炼、浏览器、Claude Code 都用假的，不联网。"""
import asyncio
import base64
import json
import threading
import time

import httpx
import pytest
import websockets

from app import agent, chat, db, settings, voice_call, voice_rt, voice_search_mcp, voice_tools
from app.voice_think import Thinker, body_of, fallback_spoken

ANSWER = "<spoken>你上周定的是先做中转。</spoken>\n完整回答：记录在 secret.md 第 3 行"


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


def _ours(env, call, text):
    """百炼念我们要它念的话。"""
    async def go():
        await call._say(text)
        env.feed("response.created")
        env.feed("response.audio.delta", delta=audio(5))
        env.feed("response.audio_transcript.done", transcript=text)
    return go()


def _hear(env, text):
    env.feed("input_audio_buffer.speech_started")
    env.feed("input_audio_buffer.speech_stopped")
    env.feed("conversation.item.input_audio_transcription.completed", transcript=text)


def _slow_brain(monkeypatch, gate=None, answer=ANSWER):
    asked = []

    def run(prompt, **kw):
        asked.append(prompt)
        kw["on_proc"](object())
        if gate:
            gate.wait(3)
        yield {"type": "delta", "text": answer}
        yield {"type": "done", "text": answer}
    monkeypatch.setattr(agent, "run_stream", run)
    return asked


def test_session_goes_up_only_to_read_and_mic_is_forwarded(env):
    async def body(ws, call):
        ws.in_.put_nowait({"type": "websocket.receive", "bytes": b"\x01\x02"})
        await until(lambda: env.of("input_audio_buffer.append"))
    _call(body)
    session = env.of("session.update")[0]["session"]
    assert session["tools"] == [] and session["max_history_turns"] == 1 and "念" in session["instructions"]
    assert base64.b64decode(env.of("input_audio_buffer.append")[0]["audio"]) == b"\x01\x02"
    assert env.closed and chat.active == 0


def test_every_sentence_goes_to_claude_and_only_spoken_goes_up(env, monkeypatch):
    asked = _slow_brain(monkeypatch)

    async def body(ws, call):
        _hear(env, "上周定了啥")
        await until(lambda: "你上周定的是先做中转。" in env.said())
        await until(lambda: ws.told("slow"))
    ws, call = _call(body)
    assert "用户刚说：上周定了啥" in asked[0]
    assert env.said() == ["你上周定的是先做中转。"]  # 没有任何标记，也没有别的
    assert "secret.md" not in json.dumps(env.sent, ensure_ascii=False)
    assert ("assistant", "完整回答：记录在 secret.md 第 3 行") in _rows(call.sid)


def test_auto_response_is_dropped_and_ours_is_played(env):
    # 百炼听完会自己接一句，关不掉（create_response:false 它不认），不能放出来
    async def body(ws, call):
        env.feed("response.created")
        env.feed("response.audio.delta", delta=audio())
        env.feed("response.audio_transcript.done", transcript="它自己接的话")
        env.feed("response.done", response={"status": "completed"})
        await until(lambda: call.reply_done)
        assert not ws.audio and not ws.told("reply")
        await _ours(env, call, "我们的话")
        await until(lambda: ws.audio and ws.told("reply"))
    ws, call = _call(body)
    assert all("它自己接的话" not in c for _, c in _rows(call.sid))


def test_barge_in_cancels_clears_and_drops_late_audio(env, monkeypatch):
    _slow_brain(monkeypatch, threading.Event())

    async def body(ws, call):
        _hear(env, "第一句")
        await until(lambda: call.thinker.task)
        await _ours(env, call, "这是一句很长的回答，用户没听完")
        await until(lambda: ws.audio and call.reply)
        env.feed("input_audio_buffer.speech_started")
        await until(lambda: ws.told("clear"))
        assert env.of("response.cancel")
        env.feed("response.audio.delta", delta=audio())  # 取消之后才到的
        env.feed("response.done", response={"status": "cancelled"})
        await asyncio.sleep(0.05)
        assert len(ws.audio) == 1
        call.thinker.cancel()
    ws, call = _call(body)
    rows = _rows(call.sid)
    assert rows[0] == ("user", "第一句")
    assert rows[1][0] == "fast" and rows[1][1].endswith(chat.INTERRUPTED)
    assert ws.told("metrics")[0]["first_audio_after_stop_s"] >= 0


def test_barge_in_after_generation_finished_still_stops_playback(env):
    # 实测模型生成比播放快得多：用户打断时回应常常已经结束，cancel 会报错，但还在放的声音要停
    async def body(ws, call):
        await _ours(env, call, "已经全部生成完的一句")
        env.feed("response.done", response={"status": "completed"})
        await until(lambda: not call.response_active and call.reply_done)
        env.feed("input_audio_buffer.speech_started")
        await until(lambda: ws.told("clear"))
        assert not env.of("response.cancel")
    ws, call = _call(body)
    assert _rows(call.sid)[0][1].endswith(chat.INTERRUPTED)


def test_barge_in_before_our_response_starts_drops_it(env):
    async def body(ws, call):
        await call._say("要念还没开始的话")
        env.feed("input_audio_buffer.speech_started")
        await until(lambda: call.user_speaking)
        env.feed("response.created")
        env.feed("response.audio.delta", delta=audio())
        await asyncio.sleep(0.05)
        assert not ws.audio
    _call(body)


def test_answer_waits_while_user_is_talking(env, monkeypatch):
    _slow_brain(monkeypatch)

    async def body(ws, call):
        _hear(env, "上周定了啥")
        env.feed("input_audio_buffer.speech_started")
        await until(lambda: ws.told("slow"))
        await asyncio.sleep(0.1)
        assert not env.said()
        env.feed("input_audio_buffer.speech_stopped")
        await until(lambda: env.said())
    _call(body)


def test_new_sentence_drops_answer_not_read_yet(env, monkeypatch):
    asked = _slow_brain(monkeypatch)

    async def body(ws, call):
        _hear(env, "第一句")
        env.feed("input_audio_buffer.speech_started")
        await until(lambda: call.outbox)
        env.feed("input_audio_buffer.speech_stopped")
        env.feed("conversation.item.input_audio_transcription.completed", transcript="不对，第二句")
        await until(lambda: len(asked) == 2)
    _call(body)
    assert "用户刚说：不对，第二句" in asked[1] and "第一句\n" not in asked[1].split("用户刚说：")[1]


def test_filler_only_when_claude_is_slow(env, monkeypatch):
    monkeypatch.setattr(voice_call, "FILLER_S", 0.05)
    gate = threading.Event()
    _slow_brain(monkeypatch, gate)

    async def body(ws, call):
        _hear(env, "这个怎么选")
        await until(lambda: env.said())
        assert env.said()[0] in voice_call.FILLERS
        env.feed("response.created")
        env.feed("response.done", response={"status": "completed"})
        gate.set()
        await until(lambda: "你上周定的是先做中转。" in env.said())
        assert len(env.said()) == 2
    _call(body)


def test_no_filler_when_answer_is_quick(env, monkeypatch):
    _slow_brain(monkeypatch, answer="<spoken>在呢。</spoken>")

    async def body(ws, call):
        _hear(env, "喂")
        await until(lambda: env.said())
        await asyncio.sleep(0.1)
    ws, _ = _call(body)
    assert env.said() == ["在呢。"] and not ws.told("slow")  # 寒暄没有屏幕正文


def test_progress_question_answers_without_restarting(env, monkeypatch):
    gate = threading.Event()
    asked = _slow_brain(monkeypatch, gate)

    async def body(ws, call):
        _hear(env, "查一下")
        await until(lambda: call.thinker.task)
        task = call.thinker.task
        task.doing = "在上网查"
        _hear(env, "还没找到吗？")
        await until(lambda: "在上网查，稍等。" in env.said())
        assert call.thinker.task is task and len(asked) == 1
        call.thinker.cancel()
    _call(body)


def test_cancel_stops_thinking(env, monkeypatch):
    _slow_brain(monkeypatch, threading.Event())

    async def body(ws, call):
        _hear(env, "查一下")
        await until(lambda: call.thinker.task)
        _hear(env, "算了")
        await until(lambda: "好，不想了。" in env.said())
        assert call.thinker.task is None
    _call(body)


def test_brain_switched_off_says_so(env, monkeypatch):
    real = settings.get
    monkeypatch.setattr(settings, "get", lambda p, d=None: False if p == "voice_rt.permissions.claude_code" else real(p, d))
    asked = _slow_brain(monkeypatch)

    async def body(ws, call):
        _hear(env, "在吗")
        await until(lambda: env.said())
    _call(body)
    assert env.said() == [voice_call.NO_BRAIN] and not asked


def test_failed_brain_says_so(env, monkeypatch):
    def run(prompt, **kw):
        kw["on_proc"](object())
        yield {"type": "error", "text": "坏了", "fatal": True}
    monkeypatch.setattr(agent, "run_stream", run)

    async def body(ws, call):
        _hear(env, "在吗")
        await until(lambda: env.said())
    ws, call = _call(body)
    assert "没想出来" in env.said()[0] and "坏了" not in json.dumps(env.sent, ensure_ascii=False)
    assert any(role == "error" for role, _ in _rows(call.sid))


def test_response_that_never_starts_does_not_block_results(env, monkeypatch):
    monkeypatch.setattr(voice_call, "RESPONSE_WAIT_S", 0.05)

    async def body(ws, call):
        call.outbox.append("一句话")
        await until(lambda: env.of("response.create"))
        await until(lambda: not call.response_active)  # 百炼没有回应 response.create，不能一直占着
    _call(body)


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


def test_other_sites_cannot_open_the_call():
    assert voice_call._same_origin(FakeWS(origin="http://127.0.0.1:8780"))
    assert voice_call._same_origin(FakeWS())
    assert not voice_call._same_origin(FakeWS(origin="https://evil.example"))
    assert not voice_call._same_origin(FakeWS(origin="http://127.0.0.1:9999"))


# ---------- 本机 Claude ----------
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


def test_new_sentence_merges_before_answer_and_replaces_after(monkeypatch):
    gate = threading.Event()
    t, got, run = _thinker(monkeypatch, [{"type": "delta", "text": ANSWER}, {"type": "done", "text": ANSWER}], gate)
    t.hear("甲")
    old = t.task
    t.hear("其实是周四")
    assert old.cancelled and "甲\n其实是周四" == t.task.objective
    t.task.spoke = True
    t.hear("乙")
    assert t.task.objective == "乙"
    t.cancel()
    assert t.status() == {"state": "idle"}
    gate.set()
    time.sleep(0.05)
    assert got == []


def test_spoken_is_sent_as_soon_as_written_before_the_rest(monkeypatch):
    gate = threading.Event()
    t, got, run = _thinker(monkeypatch)

    def later(prompt, **kw):
        kw["on_proc"](object())
        yield {"type": "delta", "text": "<spoken>先说这句。</spoken>"}
        gate.wait(3)
        yield {"type": "delta", "text": "正文"}
        yield {"type": "done", "text": "<spoken>先说这句。</spoken>正文"}
    monkeypatch.setattr(agent, "run_stream", later)
    t.hear("甲")
    end = time.monotonic() + 3
    while not got and time.monotonic() < end:
        time.sleep(0.01)
    assert got == [("spoken", "先说这句。")]
    gate.set()
    while len(got) < 2 and time.monotonic() < end:
        time.sleep(0.01)
    assert got[1] == ("full", "正文")


def test_cue_only_reports_real_new_activity(monkeypatch):
    t, _, _ = _thinker(monkeypatch, [], threading.Event())
    t.hear("甲")
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
    assert body_of("<spoken>只有这句</spoken>") == ""


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


# ---------- 只走本机登录 ----------
def test_claude_child_drops_gateway_env(monkeypatch):
    for k in agent.GATEWAY_ENV:
        monkeypatch.setenv(k, "x")
    assert not set(agent.GATEWAY_ENV) & set(agent._child_env("claude"))
    assert set(agent.GATEWAY_ENV) <= set(agent._child_env("codex"))


def test_non_first_party_stops_without_fallback(monkeypatch, tmp_path):
    fake = tmp_path / "fake-claude"
    fake.write_text("""#!/bin/sh
echo '{"type":"assistant","message":{"content":[{"type":"text","text":"网关答的"}]}}'
echo '{"type":"result","result":"网关答的","session_id":"s","modelUsage":{"m":{"provider":"openrouter"}}}'
""")
    fake.chmod(0o755)
    monkeypatch.setattr(agent, "_claude_cmd", lambda *a, **k: [str(fake)])
    monkeypatch.setattr(agent, "_codex_cmd", lambda *a, **k: pytest.fail("不该回退到别的引擎"))
    monkeypatch.setattr(agent, "available", lambda e: True)
    evs = list(agent.run_stream("问", engine="claude"))
    assert any(e.get("gateway") and "本机登录" in e["text"] for e in evs)
    assert not any(e["type"] == "done" for e in evs)


def test_first_party_passes(monkeypatch, tmp_path):
    fake = tmp_path / "fake-claude"
    fake.write_text("""#!/bin/sh
echo '{"type":"result","result":"好","session_id":"s","modelUsage":{"m":{"provider":"firstParty"}}}'
""")
    fake.chmod(0o755)
    monkeypatch.setattr(agent, "_claude_cmd", lambda *a, **k: [str(fake)])
    monkeypatch.setattr(agent, "available", lambda e: True)
    assert agent.run_once("问", engine="claude")["text"] == "好"


def test_helper_call_without_provider_passes_but_no_provider_at_all_stops():
    ok = {"type": "result", "result": "好", "modelUsage": {"haiku": {}, "sonnet": {"provider": "firstParty"}}}
    assert not any(e.get("gateway") for e in agent._parse_claude(ok))
    none = {"type": "result", "result": "好", "modelUsage": {"haiku": {}}}
    assert any(e.get("gateway") for e in agent._parse_claude(none))


@pytest.mark.parametrize("text,held", [("等一下。", True), ("稍等一下", True), ("你先等我一下", True), ("等等！", True),
                                       ("等一下，我补充一点", False), ("等一下我们再聊这个问题", False), ("好的", False)])
def test_hold_only_when_the_whole_sentence_is_a_pause(text, held):
    assert bool(voice_call.HOLD.fullmatch(text)) is held


def test_answer_waits_during_hold_and_speaking_again_lifts_it(env):
    async def body(ws, call):
        env.feed("input_audio_buffer.speech_started")
        env.feed("input_audio_buffer.speech_stopped")
        env.feed("conversation.item.input_audio_transcription.completed", transcript="等一下")
        await until(lambda: call.hold_until)
        call.last_speech_end = 0.0
        call.outbox.append("想好的话")
        await asyncio.sleep(0.25)
        assert call.outbox and not env.of("response.create")
        env.feed("input_audio_buffer.speech_started")
        await until(lambda: call.user_speaking)
        env.feed("input_audio_buffer.speech_stopped")
        await until(lambda: not call.user_speaking)
        assert call.hold_until == 0.0
    _call(body)


# ---------- 通话记录、成本、工具权限 ----------
def _call_row():
    return db.row("SELECT * FROM voice_calls ORDER BY id DESC LIMIT 1")


def _usage(text=1000, audio=10, out_text=5, out_audio=20):
    return {"input_tokens_details": {"text_tokens": text, "audio_tokens": audio}, "output_tokens_details": {"text_tokens": out_text, "audio_tokens": out_audio}}


def test_call_keeps_audio_events_and_cost(env, monkeypatch, tmp_path):
    from app import voice_record
    monkeypatch.setattr(voice_record, "CALLS_DIR", tmp_path)
    monkeypatch.setattr(voice_record, "finish", lambda d: None)

    async def body(ws, call):
        ws.in_.put_nowait({"type": "websocket.receive", "bytes": b"\x01\x02" * 100})
        env.feed("input_audio_buffer.speech_started")
        env.feed("conversation.item.input_audio_transcription.completed", transcript="你好")
        await until(lambda: ws.told("user"))
        await call._say("你好呀")
        env.feed("response.created")
        env.feed("response.audio.delta", delta=audio(0.1))
        env.feed("response.audio_transcript.done", transcript="你好呀")
        env.feed("response.done", response={"status": "completed", "usage": _usage()})
        await until(lambda: _call_row() and _call_row()["responses"] == 1)
    _call(body)
    row = _call_row()
    assert (row["input_text"], row["output_audio"]) == (1000, 20)
    assert row["cost_yuan"] == pytest.approx((1000 * 1.5 + 10 * 6 + 5 * 4.5 + 20 * 12) / 1e6, abs=1e-6)
    d = tmp_path / str(row["id"])
    assert (d / "mic.pcm").stat().st_size == 200
    assert (d / "bot.pcm").stat().st_size >= int(voice_call.OUT_RATE * 0.1) * 2
    events = [json.loads(x) for x in (d / "events.jsonl").read_text("utf-8").splitlines()]
    kinds = {e["kind"] for e in events}
    assert {"sent", "got", "user", "fast"} <= kinds
    assert not any(e["kind"] == "got" and e["ev"]["type"] == "response.audio.delta" for e in events)
    assert not any(e["kind"] == "sent" and e["type"] == "input_audio_buffer.append" for e in events)


def test_ready_tells_page_which_call_for_cost(env, monkeypatch, tmp_path):
    from app import voice_record
    monkeypatch.setattr(voice_record, "CALLS_DIR", tmp_path)
    monkeypatch.setattr(voice_record, "finish", lambda d: None)
    seen = []

    async def body(ws, call):
        seen.append(ws.told("ready")[0]["call"])
    _call(body)
    assert seen[0] == _call_row()["id"]


def _old_call(tmp_path, monkeypatch):
    """一通打完的电话：说了两句，慢思考的完整回答只在本机。"""
    from app import voice_record
    monkeypatch.setattr(voice_record, "CALLS_DIR", tmp_path)
    monkeypatch.setattr(voice_record, "finish", lambda d: None)
    sid = db.insert("chat_sessions", {"module": "talk", "ref": "", "engine": "claude", "title": "旧话题", "engine_session": "claude-1",
                                      "created_at": "2026-11-01T10:00:00", "updated_at": "2026-11-01T10:05:00"})
    cid = db.insert("voice_calls", {"session_id": sid, "started_at": "2026-11-01T10:00:00", "ended_at": "2026-11-01T10:05:00"})
    db.insert("chat_messages", {"session_id": sid, "role": "user", "content": "先做哪个", "created_at": "2026-11-01T10:01:00"})
    d = tmp_path / str(cid)
    d.mkdir()
    (d / "call.m4a").write_bytes(bytes(1000))
    (d / "events.jsonl").write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in [
        {"t": 1, "kind": "user", "text": "先做哪个"}, {"t": 2, "kind": "slow_full", "text": "本机才有的正文"},
        {"t": 3, "kind": "fast", "text": "先做 A"}]) + "\n", "utf-8")
    return cid, sid, d


def test_resume_continues_the_same_discussion_without_local_only_text(env, monkeypatch, tmp_path):
    cid, sid, _ = _old_call(tmp_path, monkeypatch)
    ws = FakeWS()
    seen = {}

    async def go():
        c = voice_call.Call(ws, resume=cid)
        seen["c"] = c
        run = asyncio.create_task(c.run())
        await until(lambda: ws.told("ready"))
        env.feed("conversation.item.input_audio_transcription.completed", transcript="接着说")
        await until(lambda: ("user", "接着说") in _rows(sid))
        ws.in_.put_nowait({"type": "websocket.disconnect"})
        await asyncio.wait_for(run, 3)
    asyncio.run(go())
    assert ws.told("ready")[0]["resumed"] is True
    said = "\n".join(seen["c"].recent)
    assert "用户：先做哪个" in said and "你：先做 A" in said and "本机才有的正文" not in said
    assert seen["c"].thinker.session == "claude-1"
    assert "先做哪个" not in json.dumps(env.of("session.update"), ensure_ascii=False)  # 上文只在本机 Claude 这边
    new = _call_row()
    assert new["id"] != cid and new["session_id"] == sid


def test_resume_of_missing_call_is_a_new_call(env):
    ws = FakeWS()

    async def go():
        run = asyncio.create_task(voice_call.Call(ws, resume=999).run())
        await until(lambda: ws.told("ready"))
        ws.in_.put_nowait({"type": "websocket.disconnect"})
        await asyncio.wait_for(run, 3)
    asyncio.run(go())
    assert ws.told("ready")[0]["resumed"] is False


def test_calls_report_size_and_total(env, client, monkeypatch, tmp_path):
    cid, _, _ = _old_call(tmp_path, monkeypatch)
    with client:
        row = next(c for c in client.get("/api/voice/calls").json() if c["id"] == cid)
        assert row["size_bytes"] > 1000
        assert client.get("/api/voice/calls/usage").json()["bytes"] == row["size_bytes"]


def test_delete_call_removes_its_content_only(env, client, monkeypatch, tmp_path):
    cid, sid, d = _old_call(tmp_path, monkeypatch)
    later = db.insert("voice_calls", {"session_id": sid, "started_at": "2026-11-02T10:00:00", "ended_at": "2026-11-02T10:05:00"})
    db.insert("chat_messages", {"session_id": sid, "role": "user", "content": "后来说的", "created_at": "2026-11-02T10:01:00"})
    with client:
        assert client.delete(f"/api/voice/calls/{cid}").json() == {"ok": True}
        assert client.delete(f"/api/voice/calls/{cid}").status_code == 404
    assert not d.exists() and not db.row("SELECT id FROM voice_calls WHERE id=?", [cid])
    assert _rows(sid) == [("user", "后来说的")]  # 接着聊的那通还在，讨论留着
    with client:
        client.delete(f"/api/voice/calls/{later}")
    assert not _rows(sid) and not db.row("SELECT id FROM chat_sessions WHERE id=?", [sid])


def test_delete_keeps_typed_messages_and_refuses_live_call(env, client, monkeypatch, tmp_path):
    cid, sid, _ = _old_call(tmp_path, monkeypatch)
    db.insert("chat_messages", {"session_id": sid, "role": "user", "content": "后来打字续的", "created_at": "2026-11-03T09:00:00"})
    monkeypatch.setattr(voice_call, "live_calls", {cid})
    with client:
        assert client.delete(f"/api/voice/calls/{cid}").status_code == 409
        monkeypatch.setattr(voice_call, "live_calls", set())
        client.delete(f"/api/voice/calls/{cid}")
    assert _rows(sid) == [("user", "后来打字续的")]
    assert db.row("SELECT id FROM chat_sessions WHERE id=?", [sid])


def test_barge_cuts_what_was_not_played(tmp_path, monkeypatch):
    from app import voice_record
    monkeypatch.setattr(voice_record, "CALLS_DIR", tmp_path)
    monkeypatch.setattr(voice_record.db, "insert", lambda *a: 7)
    rec = voice_record.Recorder()
    rec.open("m", "v")
    rec.bot(bytes(48000), 1.0)  # 第 1 秒开始放 1 秒
    rec.cut(1.5)
    rec.close_files()
    assert (tmp_path / "7" / "bot.pcm").stat().st_size == 72000  # 前 1 秒留空 + 放出去的 0.5 秒


def test_finish_makes_playable_files_and_only_then_removes_raw(tmp_path):
    from app import voice_record
    (tmp_path / "mic.pcm").write_bytes(bytes(32000))
    (tmp_path / "bot.pcm").write_bytes(bytes(48000))
    assert voice_record.finish(tmp_path)
    assert all((tmp_path / f).stat().st_size for f in ("call.m4a", "mic.flac", "bot.flac"))
    assert not (tmp_path / "mic.pcm").exists() and voice_record.finish(tmp_path)


def test_finish_keeps_raw_when_conversion_fails(tmp_path, monkeypatch):
    from app import voice_record
    (tmp_path / "mic.pcm").write_bytes(bytes(3200))
    monkeypatch.setattr(voice_record.subprocess, "run", lambda *a, **k: type("P", (), {"returncode": 1, "stderr": "坏了"})())
    assert not voice_record.finish(tmp_path)
    assert (tmp_path / "mic.pcm").exists()


# ---------- 搜索接给本机 Claude ----------
def test_slow_stays_readonly_with_only_search_added():
    cmd = agent._claude_cmd("q", "", "", [], readonly=True)
    assert cmd[cmd.index("--tools") + 1] == "Read,Glob,Grep,WebSearch,WebFetch" and "--strict-mcp-config" in cmd and "--mcp-config" not in cmd
    cmd = agent._claude_cmd("q", "", "", [], readonly=True, mcp=voice_tools.slow_mcp())
    servers = json.loads(cmd[cmd.index("--mcp-config") + 1])["mcpServers"]
    assert list(servers) == ["voice_search"] and "mcp__voice_search" in cmd and "--strict-mcp-config" in cmd
    assert "KEY" not in json.dumps(servers)  # 密钥不进命令行


def test_search_tool_follows_its_switch(monkeypatch):
    real = settings.get
    monkeypatch.setattr(settings, "get", lambda p, d=None: False if p == "voice_rt.permissions.web_search" else real(p, d))
    assert voice_tools.slow_mcp() == {}
    assert not voice_tools.enabled("rm_rf")


def test_search_server_speaks_mcp(monkeypatch):
    monkeypatch.setattr(voice_rt, "web_search", lambda q: {"results": [{"title": q}]})
    handle = voice_search_mcp.handle
    assert handle({"id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}})["result"]["protocolVersion"] == "2025-06-18"
    assert handle({"method": "notifications/initialized"}) is None
    assert handle({"id": 2, "method": "tools/list"})["result"]["tools"][0]["name"] == "web_search"
    out = handle({"id": 3, "method": "tools/call", "params": {"name": "web_search", "arguments": {"query": "杭州天气"}}})["result"]
    assert "杭州天气" in out["content"][0]["text"] and not out["isError"]
    assert "error" in handle({"id": 4, "method": "没有的"})
