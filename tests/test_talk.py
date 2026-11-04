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
