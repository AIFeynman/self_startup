import json
import wave
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException


def _wav(path, samples):
    import array
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
        w.writeframes(array.array("h", samples).tobytes())


def test_has_speech_rejects_silence_and_steady_noise(tmp_path):
    import math
    import random

    from app import voice
    random.seed(1)
    silence, noise, speech = tmp_path / "s.wav", tmp_path / "n.wav", tmp_path / "v.wav"
    _wav(silence, [0] * 16000 * 3)
    _wav(noise, [random.randint(-800, 800) for _ in range(16000 * 3)])  # 持续噪音，响但没有起伏
    quiet = [random.randint(-50, 50) for _ in range(8000)]
    loud = [int(6000 * math.sin(i / 8)) for i in range(16000)]
    _wav(speech, quiet + loud + quiet)
    assert not voice.has_speech(silence)
    assert not voice.has_speech(noise)
    assert voice.has_speech(speech)


def test_clean_only_touches_punctuation_after_chinese():
    from app import voice
    assert voice._clean("你好,世界?a, b,再见") == "你好，世界？a, b，再见"


def test_transcribe_drops_hallucination(client, monkeypatch, tmp_path):
    import math

    from app import voice
    model = tmp_path / "m.bin"
    model.write_bytes(b"x")
    monkeypatch.setattr(voice.settings, "get", lambda k, d=None: {"bin": "whisper-cli", "model": str(model)} if k == "voice" else d)
    monkeypatch.setattr(voice.shutil, "which", lambda b: "/usr/bin/" + b)
    said = {"text": ""}

    def run(cmd):
        if cmd[0] == "ffmpeg":
            _wav(cmd[-1], [int(6000 * math.sin(i / 8)) if i % 16000 < 8000 else 0 for i in range(16000 * 2)])
        else:
            with open(cmd[cmd.index("-f") + 1] + ".json", "w") as f:
                json.dump({"transcription": [{"text": said["text"], "tokens": [{"text": "a", "p": 0.9}]}]}, f)
    monkeypatch.setattr(voice, "_run", run)
    said["text"] = "请不吝点赞 订阅"
    assert voice.transcribe(b"x")["text"] == ""
    said["text"] = "我在想要不要做,这件事"
    assert voice.transcribe(b"x")["text"] == "我在想要不要做，这件事"


def test_long_recording_splits_at_pauses_and_skips_silence(tmp_path):
    import math

    from app import voice
    second = [int(6000 * math.sin(i / 8)) for i in range(16000)]
    pause = [0] * 8000
    talk = (second * 9 + pause) * 8          # 76 秒的说话，每 9 秒停一下
    src = tmp_path / "in.wav"
    _wav(src, talk + [0] * 16000 * 60)       # 后面一分钟没声音
    parts = voice.split_at_pauses(src, tmp_path)
    assert 2 <= len(parts) <= 6
    lengths = []
    for f in parts:
        with wave.open(str(f)) as w:
            lengths.append(w.getnframes() / 16000)
    assert max(lengths) <= 28
    assert 70 <= sum(lengths) <= 100         # 话都在，静音大部分丢掉
    assert voice.split_at_pauses(_silent(tmp_path), tmp_path) == []


def _silent(tmp_path):
    f = tmp_path / "silent.wav"
    _wav(f, [0] * 16000 * 40)
    return f


def test_join_adds_comma_only_where_needed():
    from app import voice
    assert voice._join(["先这样", "", "再那样。", "最后"]) == "先这样，再那样。最后"


def test_transcribe_reports_missing_model(monkeypatch):
    from app import voice
    monkeypatch.setattr(voice.settings, "get", lambda k, d=None: {"model": "/no/such.bin"} if k == "voice" else d)
    monkeypatch.setattr(voice.shutil, "which", lambda b: "/usr/bin/" + b)
    with pytest.raises(HTTPException) as e:
        voice.transcribe(b"x")
    assert e.value.status_code == 503


def test_readonly_commands_cannot_write():
    from app import agent
    cmd = agent._claude_cmd("hi", "", "", [], "", readonly=True)
    assert "acceptEdits" not in cmd and cmd[cmd.index("--tools") + 1] == "Read,Glob,Grep,WebSearch,WebFetch"
    assert "read-only" in agent._codex_cmd("hi", "", "", [], "/tmp", readonly=True)
    assert "--tools" not in agent._claude_cmd("hi", "", "", [], "")
    job = agent._claude_cmd("hi", "", "", [], "")
    assert json.loads(job[job.index("--settings") + 1])["sandbox"]["network"]["allowLocalBinding"] is True


def test_partial_text_comes_as_delta():
    from app import agent
    ev = {"type": "stream_event", "event": {"delta": {"type": "text_delta", "text": "你"}}}
    assert agent._parse_claude(ev) == [{"type": "delta", "text": "你"}]
    assert agent._parse_claude({"type": "stream_event", "event": {"delta": {"type": "input_json_delta"}}}) == []


def test_talk_chat_is_readonly_others_are_not(client, monkeypatch):
    from app import agent
    seen = {}

    def fake(prompt, **kw):
        seen[prompt] = kw["readonly"]
        yield {"type": "done", "text": "好", "engine": "claude"}
    monkeypatch.setattr(agent, "run_stream", fake)
    client.post("/api/chat/talk", json={"message": "讨论"})
    client.post("/api/chat/plan", json={"message": "规划"})
    assert seen == {"讨论": True, "规划": False}


CARD = {"title": "要不要拆任务", "mode": "判断", "frame": "prod-worth", "goal": "把时间花在最能推进的事上",
        "lenses": ["做完能动哪个指标"], "options": [{"name": "拆细", "how": "每件半天内"}], "headroom": ["上限看并行度"],
        "quality": ["一周后看完成率"], "risks": ["拆得过碎"], "conclusions": ["先拆成半天一件"], "open_questions": ["拆到多细"],
        "next_steps": ["写任务清单"]}


def _talk_session(db, *lines, at=None):
    at = at or db.now()
    sid = db.insert("chat_sessions", {"module": "talk", "ref": "", "engine": "", "title": "t", "created_at": at, "updated_at": at})
    for i, text in enumerate(lines):
        db.insert("chat_messages", {"session_id": sid, "role": "user" if i % 2 == 0 else "assistant", "content": text, "created_at": at})
    return sid


def _model(monkeypatch, card=CARD):
    from app import agent
    calls = []

    def once(prompt, **kw):
        calls.append((prompt, kw))
        return {"text": "好的\n" + json.dumps(card, ensure_ascii=False), "session": "", "engine": "claude", "log": ""}
    monkeypatch.setattr(agent, "run_once", once)
    return calls


def test_idle_discussion_becomes_topic_card_and_is_archived(client, monkeypatch):
    from app import db
    from app.modules import talk
    old = (datetime.now() - timedelta(minutes=talk.IDLE_MIN + 1)).strftime("%Y-%m-%dT%H:%M:%S")
    sid = _talk_session(db, "要不要拆任务", "先说说你的判断", at=old)
    fresh = _talk_session(db, "还在聊")
    calls = _model(monkeypatch)
    assert talk.sweep() == [sid]
    prompt, kw = calls[0]
    assert kw["readonly"] and "要不要拆任务" in prompt
    t = client.get("/api/talk/topics").json()[0]
    assert t["session_id"] == sid and t["title"] == "要不要拆任务" and t["card"]["conclusions"] == ["先拆成半天一件"]
    assert t["frame"] == {"id": "prod-worth", "title": "这个需求值不值得做"}
    note = db.row("SELECT kind, tags, content FROM review_notes WHERE id=?", [t["note_id"]])
    assert note["kind"] == "insight" and "讨论" in note["tags"] and "先拆成半天一件" in note["content"] and "拆得过碎" in note["content"]
    assert t["judgments"] == []
    assert not db.row("SELECT 1 FROM sqlite_master WHERE name='kb_judgments'") or not db.rows("SELECT id FROM kb_judgments WHERE text='先拆成半天一件'")
    assert not db.rows("SELECT id FROM tasks WHERE title='写任务清单'")
    assert fresh not in [x["session_id"] for x in client.get("/api/talk/topics").json()]
    # 没有新内容不重跑；接着聊了再整理：更新同一张卡和同一条笔记
    assert talk.sweep() == [] and len(calls) == 1
    later = (datetime.now() - timedelta(minutes=talk.IDLE_MIN, seconds=30)).strftime("%Y-%m-%dT%H:%M:%S")
    db.insert("chat_messages", {"session_id": sid, "role": "user", "content": "还是拆细", "created_at": later})
    _model(monkeypatch, {**CARD, "conclusions": ["先拆成半天一件", "每天收尾对一次"]})
    assert talk.sweep() == [sid]
    topics = client.get("/api/talk/topics").json()
    assert len([x for x in topics if x["session_id"] == sid]) == 1
    assert topics[0]["card"]["conclusions"] == ["先拆成半天一件", "每天收尾对一次"]
    assert db.row("SELECT count(*) AS n FROM review_notes WHERE tags LIKE '%讨论%'")["n"] == 1


def test_failed_or_old_discussions_are_not_retried_every_sweep(client, monkeypatch):
    from app import agent, db
    from app.modules import talk
    idle = (datetime.now() - timedelta(minutes=talk.IDLE_MIN + 1)).strftime("%Y-%m-%dT%H:%M:%S")
    ancient = (datetime.now() - timedelta(days=talk.SWEEP_DAYS + 1)).strftime("%Y-%m-%dT%H:%M:%S")
    db.execute("DELETE FROM chat_sessions WHERE module='talk'")
    bad = _talk_session(db, "说不清的话", at=idle)
    old = _talk_session(db, "很久以前的闲聊", at=ancient)
    calls = []
    monkeypatch.setattr(agent, "run_once", lambda p, **k: calls.append(p) or {"text": "不是 JSON", "session": "", "engine": "claude", "log": ""})
    assert talk.sweep() == [] and talk.sweep() == [] and len(calls) == 1
    db.insert("chat_messages", {"session_id": bad, "role": "user", "content": "补一句", "created_at": (datetime.fromisoformat(idle) + timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%S")})
    _model(monkeypatch)
    assert talk.sweep() == [bad] and old not in [t["session_id"] for t in client.get("/api/talk/topics").json()]


def test_same_discussion_is_not_organized_twice_at_once(client):
    from app import db
    from app.modules import talk
    sid = _talk_session(db, "x")
    talk._busy.add(sid)
    try:
        assert client.post("/api/talk/topics/refresh", json={"session_id": sid}).status_code == 409
    finally:
        talk._busy.discard(sid)


def test_conclusion_goes_to_ledger_only_when_clicked(client, monkeypatch):
    from app import db, kb_judge
    kb_judge._init()
    db.execute("DELETE FROM kb_judgments")
    sid = _talk_session(db, "x")
    _model(monkeypatch)
    t = client.post("/api/talk/topics/refresh", json={"session_id": sid}).json()
    assert t["judgments"] == [] and not db.rows("SELECT id FROM kb_judgments")
    r = client.post(f"/api/talk/topics/{t['id']}/judgments", json={"text": "先拆成半天一件"}).json()
    client.post(f"/api/talk/topics/{t['id']}/judgments", json={"text": "先拆成半天一件"})
    rows = db.rows("SELECT text, sources FROM kb_judgments")
    assert [x["text"] for x in rows] == ["先拆成半天一件"] and f"#talk/t/{t['id']}" in rows[0]["sources"]
    assert [j["text"] for j in r["judgments"]] == ["先拆成半天一件"]
    assert client.post(f"/api/talk/topics/{t['id']}/judgments", json={"text": " "}).status_code == 400


def test_old_daily_thinks_move_into_discussion(client):
    from app import db
    from app.modules import talk
    db.execute("CREATE TABLE IF NOT EXISTS kb_thinks (id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT, question TEXT, origin_sid TEXT DEFAULT '', "
               "mode TEXT DEFAULT 'judgment', stance TEXT DEFAULT '', judgment_id INTEGER, done_on TEXT DEFAULT '', created_at TEXT)")
    db.execute("DELETE FROM kb_thinks")
    chatted = db.insert("kb_thinks", {"date": "2026-11-10", "question": "AI 组织怎么设计", "created_at": "2026-11-10T09:00:00"})
    quiet = db.insert("kb_thinks", {"date": "2026-11-10", "question": "评测值不值得做", "stance": "值得", "created_at": "2026-11-10T10:00:00"})
    sess = db.insert("chat_sessions", {"module": "kb", "ref": f"think:{chatted}", "engine": "claude", "title": "x", "created_at": db.now(), "updated_at": db.now()})
    assert talk.adopt_thinks() == 2 and talk.adopt_thinks() == 0
    assert db.row("SELECT module FROM chat_sessions WHERE id=?", [sess])["module"] == "talk"
    new = db.row("SELECT id FROM chat_sessions WHERE module='talk' AND ref=?", [f"think:{quiet}"])["id"]
    assert "值得" in db.row("SELECT content FROM chat_messages WHERE session_id=?", [new])["content"]
    assert "AI 组织怎么设计" in talk.agent_context(f"think:{chatted}")


def test_keep_thinking_from_a_ledger_judgment(client, monkeypatch):
    from app import kb_judge
    from app.modules import talk
    card = {"sid": "my:1", "date": "2026-11-01", "type": "预测", "claim": "Agent 团队会取代流水线", "confidence": "中", "thread": "", "reviews": []}
    monkeypatch.setattr(kb_judge, "ledger_json", lambda: {"due": [], "open": [], "singles": [card], "threads": []})
    assert "Agent 团队会取代流水线" in talk.agent_context("judge:my:1")
    assert "Agent 团队会取代流水线" not in talk.agent_context("judge:my:2")


def test_refresh_now_and_add_next_steps_once(client, monkeypatch):
    from app import db
    sid = _talk_session(db, "x")
    _model(monkeypatch)
    t = client.post("/api/talk/topics/refresh", json={"session_id": sid}).json()
    assert t["card"]["next_steps"] == ["写任务清单"] and t["task_ids"] == []
    r = client.post(f"/api/talk/topics/{t['id']}/tasks", json={"next_steps": ["写任务清单"]}).json()
    client.post(f"/api/talk/topics/{t['id']}/tasks", json={"next_steps": ["写任务清单"]})
    assert len(r["task_ids"]) == 1 and len(db.rows("SELECT id FROM tasks WHERE title='写任务清单'")) == 1
    empty = _talk_session(db)
    assert client.post("/api/talk/topics/refresh", json={"session_id": empty}).status_code == 400


def test_bad_model_output_is_an_error(client, monkeypatch):
    from app import agent, db
    sid = _talk_session(db, "x")
    monkeypatch.setattr(agent, "run_once", lambda p, **k: {"text": "不是 JSON", "session": "", "engine": "claude", "log": ""})
    assert client.post("/api/talk/topics/refresh", json={"session_id": sid}).status_code == 502


def test_talk_context_picks_mode_and_frames_by_itself():
    from app.modules import talk
    ctx = talk.agent_context("")
    assert "脑暴" in ctx and "这个需求值不值得做" in ctx and "eng-perf" in ctx
    card = talk.agent_context("lens:eng-perf")
    assert "缓存" in card and "练习题" in card
    assert talk.agent_context("lens:nope") == ctx


def test_frames_library_moved_from_kb_to_talk(client):
    data = client.get("/api/talk/frames").json()
    assert [d["name"] for d in data["domains"]] == ["产品", "设计", "运营", "工程", "算法", "增长"]
    assert sum(len(d["cards"]) for d in data["domains"]) >= 18
    assert client.get("/api/kb/lens").status_code == 404


def test_live_skips_silence_without_starting_server(client, monkeypatch, tmp_path):
    from app import voice
    monkeypatch.setattr(voice, "_ensure_server", lambda: pytest.fail("静音不该启动转写"))
    _wav(tmp_path / "s.wav", [0] * 16000)
    r = client.post("/api/voice/live", content=(tmp_path / "s.wav").read_bytes())
    assert r.status_code == 200 and r.json()["text"] == ""
    assert client.post("/api/voice/live", content=b"not wav").status_code == 400


def test_speak_returns_audio_and_rejects_empty(client, monkeypatch):
    from app import voice
    monkeypatch.setattr(voice, "synthesize", lambda text: b"RIFF" + text.encode())
    r = client.post("/api/voice/speak", json={"text": " 你好 "})
    assert r.status_code == 200 and r.headers["content-type"] == "audio/wav" and r.content == "RIFF你好".encode()
    assert client.post("/api/voice/speak", json={"text": "  "}).status_code == 400


def test_synthesize_writes_playable_wav_and_falls_back_to_say(monkeypatch):
    import io, types, wave
    from app import voice

    class Fake:
        def generate(self, text, sid, speed):
            return types.SimpleNamespace(samples=[0.0, 0.5, -1.0, 2.0], sample_rate=24000)
    monkeypatch.setattr(voice, "_load_kokoro", lambda: Fake())
    with wave.open(io.BytesIO(voice.synthesize("你好")), "rb") as w:
        assert (w.getframerate(), w.getnframes(), w.getnchannels()) == (24000, 4, 1)

    def broken():
        raise FileNotFoundError("没有模型")
    monkeypatch.setattr(voice, "_load_kokoro", broken)
    monkeypatch.setattr(voice, "_say", lambda text: b"say:" + text.encode())
    assert voice.synthesize("你好") == "say:你好".encode()


def test_speak_prepare_never_blocks_the_call_when_model_is_missing(client, monkeypatch):
    from app import voice

    def broken():
        raise FileNotFoundError("没有模型")
    monkeypatch.setattr(voice, "_load_kokoro", broken)
    assert client.post("/api/voice/speak/prepare").json()["ok"]


def test_stop_kills_running_reply_and_next_turn_is_told(client, monkeypatch):
    from app import agent, chat, db
    stopped = []
    monkeypatch.setattr(agent, "stop", stopped.append)
    chat._procs[7] = "proc"
    assert client.post("/api/chat/stop/7").json()["ok"]
    assert stopped == ["proc"] and 7 in chat._stopping
    chat._procs.clear(); chat._stopping.clear()

    sid = db.insert("chat_sessions", {"module": "talk", "ref": "", "engine": "", "title": "t", "created_at": db.now(), "updated_at": db.now()})
    for role, content in (("user", "第一句"), ("assistant", "答到一半" + chat.INTERRUPTED), ("user", "接着说")):
        db.insert("chat_messages", {"session_id": sid, "role": role, "content": content, "created_at": db.now()})
    told = chat._with_interruption(sid, "接着说")
    assert "第一句" in told and "答到一半" in told and told.endswith("接着说")


def test_warm_process_only_serves_the_same_command(monkeypatch):
    import io

    from app import agent

    class Fake:
        pid, killed = 0, False
        def __init__(self): self.stdin = _Keep()
        def poll(self): return None
        def terminate(self): self.killed = True

    class _Keep(io.StringIO):
        def close(self): self.sent = self.getvalue()

    monkeypatch.setattr(agent, "available", lambda e: True)
    monkeypatch.setattr(agent.subprocess, "Popen", lambda *a, **k: Fake())
    monkeypatch.setattr(agent, "_warm", {})
    agent.warm_up(system="s", session="a", model="m")
    other = agent._claude_cmd("问题", "s", "b", [], "m", True)  # 别的会话不能用
    assert agent._take_warm(other, "问题") is None and agent._warm
    same = agent._claude_cmd("问题", "s", "a", [], "m", True)
    proc = agent._take_warm(same, "问题")
    assert json.loads(proc.stdin.sent)["message"]["content"] == "问题"
    assert "问题" not in agent._warm and not agent._warm  # 只用一次
    assert agent._take_warm(same, "问题") is None
