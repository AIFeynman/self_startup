from app import chat, db, kb_idea

from test_kb_judge import _clean, _setup  # noqa: F401


def _wipe():
    db.execute("DELETE FROM chat_messages WHERE session_id IN (SELECT id FROM chat_sessions WHERE module='kb')")
    db.execute("DELETE FROM chat_sessions WHERE module='kb'")
    if db.row("SELECT 1 FROM sqlite_master WHERE name='kb_thinks'"):
        db.execute("DELETE FROM kb_thinks")


def test_daily_think_guides_then_records_judgment(client, monkeypatch):
    _wipe()
    _setup(monkeypatch)
    monkeypatch.setattr(kb_idea, "_today", lambda: "2026-11-08")
    j = client.get("/api/kb/judgments").json()
    first_due = j["due"][0]

    t = client.get("/api/kb/think/today").json()
    assert t["origin_sid"] == first_due["sid"] and first_due["claim"] in t["question"]
    assert t["judgment"] is None and not t["chatted"]
    assert client.get("/api/kb/think/today").json()["id"] == t["id"]

    ctx, _ = chat._context("kb", f"think:{t['id']}")
    assert "主动提出判断" in ctx and t["question"] in ctx
    assert first_due["claim"] in ctx and f"/api/kb/think/{t['id']}/record" in ctx

    monkeypatch.setattr(kb_idea, "_today", lambda: "2026-11-09")
    assert client.get("/api/kb/think/today").json()["id"] == t["id"]

    assert client.post(f"/api/kb/think/{t['id']}/record", json={"text": " "}).status_code == 400
    r = client.post(f"/api/kb/think/{t['id']}/record", json={"text": "甲概念要先做，但前提是数据够", "type": "观点", "confidence": "中"}).json()
    row = db.row("SELECT * FROM kb_judgments WHERE id=?", [int(r["sid"].split(":")[1])])
    assert row["text"] == "甲概念要先做，但前提是数据够" and t["question"] in row["note"]
    assert client.get("/api/kb/think/today").json()["id"] == t["id"]

    monkeypatch.setattr(kb_idea, "_today", lambda: "2026-11-10")
    nxt = client.get("/api/kb/think/today").json()
    assert nxt["id"] != t["id"] and nxt["origin_sid"] != t["origin_sid"]
    ctx, _ = chat._context("kb", f"think:{nxt['id']}")
    assert "甲概念要先做，但前提是数据够" in ctx


def test_think_from_any_judgment(client, monkeypatch):
    _wipe()
    _setup(monkeypatch)
    q = client.get("/api/kb/judgments").json()["open"][0]
    t = client.post("/api/kb/think", json={"sid": q["sid"]}).json()
    assert t["origin_sid"] == q["sid"] and q["claim"].removeprefix("疑问：") in t["question"]
    assert client.post("/api/kb/think", json={"sid": q["sid"]}).json()["id"] == t["id"]
    assert client.post("/api/kb/think", json={"sid": "my:999999"}).status_code == 404


def _say(sess_id, role, content):
    db.insert("chat_messages", {"session_id": sess_id, "role": role, "content": content, "created_at": db.now()})


def test_three_modes_saved_searchable_and_resumable(client, monkeypatch):
    _wipe()
    topics = []
    for mode in ("brainstorm", "idea", "judgment"):
        t = client.post("/api/kb/think/new", json={"question": "Agent 评测怎么做？", "mode": mode}).json()
        assert t["mode"] == mode and not t["chatted"]
        topics.append(t)
    assert len({t["id"] for t in topics}) == 3
    assert client.post("/api/kb/think/new", json={"question": " ", "mode": "idea"}).status_code == 400
    assert client.post("/api/kb/think/new", json={"question": "x", "mode": "unknown"}).status_code == 422
    t = topics[0]
    sid = db.insert("chat_sessions", {"module": "kb", "ref": t["ref"], "engine": "claude", "title": "x", "created_at": db.now(), "updated_at": db.now()})
    _say(sid, "user", "考虑先做失败案例库")
    _say(sid, "assistant", "关键分歧是案例是否能区分两种方案")
    history = client.get("/api/kb/think/history", params={"q": "失败案例"}).json()
    assert [x["id"] for x in history["items"]] == [t["id"]]
    assert history["items"][0]["session_id"] == sid
    assert history["items"][0]["chatted"]
    assert client.get("/api/kb/think/history", params={"mode": "idea"}).json()["total"] == 1
    assert client.get("/api/kb/think/history", params={"limit": 1, "offset": 1}).json()["total"] == 3
    for topic in topics:
        ctx = chat._context("kb", topic["ref"])[0]
        assert topic["question"] in ctx
        assert "主动提出判断" in ctx and "模拟" in ctx and "搜索" in ctx
        assert "〔第 N / 5 层〕" not in ctx
    assert "突破" in chat._context("kb", topics[0]["ref"])[0]
    assert "瓶颈" in chat._context("kb", topics[1]["ref"])[0]
    assert "反例" in chat._context("kb", topics[2]["ref"])[0]


def test_think_uses_opus_without_engine_fallback(client, monkeypatch):
    _wipe()
    t = client.post("/api/kb/think/new", json={"question": "评测值得做吗", "mode": "judgment", "stance": "值得"}).json()
    calls = []
    def stream(prompt, **kw):
        calls.append(kw)
        yield {"type": "done", "text": "先看它能否影响一次真实选择。", "engine": "claude"}
    monkeypatch.setattr(chat.agent, "run_stream", stream)
    r = client.post("/api/chat/kb", json={"message": "一起想", "ref": t["ref"], "engine": "codex"})
    assert r.status_code == 200
    assert calls[0]["engine"] == "claude"
    assert calls[0]["model"] == "claude-opus-5-5"
    assert calls[0]["fallback"] is False
    saved = client.get(f"/api/kb/think/{t['id']}").json()
    messages = client.get(f"/api/chat/session/{saved['session_id']}").json()["messages"]
    assert messages[-1]["content"] == "先看它能否影响一次真实选择。"


def test_new_database_keeps_thinking_context(client, monkeypatch, tmp_path):
    original = db.conn()
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "fresh.db")
    connection = db.connect()
    monkeypatch.setattr(db, "_conn", connection)
    db.init()
    try:
        t = client.post("/api/kb/think/new", json={"question": "如何学得更好", "mode": "brainstorm"}).json()
        ctx = chat._context("kb", t["ref"])[0]
        assert "主动提出判断" in ctx and "如何学得更好" in ctx
    finally:
        monkeypatch.setattr(db, "_conn", original)
        connection.close()


def test_think_saves_visible_reply_before_stream_finishes(client, monkeypatch):
    _wipe()
    t = client.post("/api/kb/think/new", json={"question": "一个新方向", "mode": "idea"}).json()
    def stream(prompt, **kw):
        yield {"type": "session", "id": "local-opus-session"}
        yield {"type": "text", "text": "关键是反馈能否改变下一次行为。"}
        session = db.row("SELECT * FROM chat_sessions WHERE ref=?", [t["ref"]])
        assert session["engine_session"] == "local-opus-session"
        assert db.row("SELECT content FROM chat_messages WHERE session_id=? AND role='assistant'", [session["id"]])["content"] == "关键是反馈能否改变下一次行为。"
        yield {"type": "done", "text": "关键是反馈能否改变下一次行为。", "engine": "claude"}
    monkeypatch.setattr(chat.agent, "run_stream", stream)
    client.post("/api/chat/kb", json={"message": "继续", "ref": t["ref"]})
    saved = client.get(f"/api/kb/think/{t['id']}").json()
    assert len(db.rows("SELECT * FROM chat_messages WHERE session_id=? AND role='assistant'", [saved["session_id"]])) == 1


def test_old_codex_topic_continues_with_its_arguments(client, monkeypatch):
    _wipe()
    t = client.post("/api/kb/think/new", json={"question": "方案怎么选", "mode": "idea"}).json()
    sid = db.insert("chat_sessions", {"module": "kb", "ref": t["ref"], "engine": "codex", "engine_session": "codex-thread", "title": "x", "created_at": db.now(), "updated_at": db.now()})
    _say(sid, "user", "最硬的约束是不能增加维护时间")
    _say(sid, "assistant", "共识是只复用现有记录")
    def stream(prompt, **kw):
        assert "不能增加维护时间" in prompt and "只复用现有记录" in prompt
        assert kw["session"] == "" and kw["engine"] == "claude"
        yield {"type": "done", "text": "继续检查现有记录的偏差。", "engine": "claude"}
    monkeypatch.setattr(chat.agent, "run_stream", stream)
    client.post("/api/chat/kb", json={"message": "沿这个继续想", "session_id": sid})
