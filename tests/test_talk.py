import json
import json
import wave

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


def test_organize_then_save_once(client, monkeypatch):
    from app import agent, db
    sid = db.insert("chat_sessions", {"module": "talk", "ref": "", "engine": "", "title": "t", "created_at": db.now(), "updated_at": db.now()})
    assert client.post("/api/talk/organize", json={"session_id": sid}).status_code == 400
    db.insert("chat_messages", {"session_id": sid, "role": "user", "content": "要不要拆任务", "created_at": db.now()})
    kw_seen = {}

    def once(prompt, **kw):
        kw_seen.update(kw)
        return {"text": '好的\n{"title":"拆任务","content":"**结论** 拆细","next_steps":["写清单"]}', "session": "", "engine": "claude", "log": ""}
    monkeypatch.setattr(agent, "run_once", once)
    d = client.post("/api/talk/organize", json={"session_id": sid}).json()
    assert kw_seen["readonly"] and d["next_steps"] == ["写清单"] and not d["saved_at"]
    # 只整理不保存：还没有写笔记
    assert not db.rows("SELECT id FROM review_notes WHERE title='拆任务'")

    body = {"title": "拆任务", "content": "改过的结论", "next_steps": ["写清单"]}
    r = client.post(f"/api/talk/summaries/{d['id']}/save", json=body).json()
    assert r["note_id"] and len(r["task_ids"]) == 1
    client.post(f"/api/talk/summaries/{d['id']}/save", json=body)
    notes = db.rows("SELECT content,tags,kind FROM review_notes WHERE title='拆任务'")
    assert len(notes) == 1 and notes[0]["content"] == "改过的结论" and notes[0]["kind"] == "insight"
    assert len(db.rows("SELECT id FROM tasks WHERE title='写清单'")) == 1


def test_organize_bad_json_is_an_error(client, monkeypatch):
    from app import agent, db
    sid = db.insert("chat_sessions", {"module": "talk", "ref": "", "engine": "", "title": "t", "created_at": db.now(), "updated_at": db.now()})
    db.insert("chat_messages", {"session_id": sid, "role": "user", "content": "x", "created_at": db.now()})
    monkeypatch.setattr(agent, "run_once", lambda p, **k: {"text": "不是 JSON", "session": "", "engine": "claude", "log": ""})
    assert client.post("/api/talk/organize", json={"session_id": sid}).status_code == 502


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
