from app import chat, db, kb_idea

from test_kb_judge import _clean, _setup  # noqa: F401


def _wipe():
    db.execute("DELETE FROM chat_messages WHERE session_id IN (SELECT id FROM chat_sessions WHERE module='kb')")
    db.execute("DELETE FROM chat_sessions WHERE module='kb'")
    if db.row("SELECT 1 FROM sqlite_master WHERE name='kb_thinks'"):
        db.execute("DELETE FROM kb_thinks")


def test_latest_discussion_is_shown_instead_of_daily_assignment(client, monkeypatch):
    _wipe()
    _setup(monkeypatch)
    assert client.get("/api/kb/think/latest").json() is None
    older = client.post("/api/kb/think/new", json={"question": "先开的题", "mode": "idea"}).json()
    newer = client.post("/api/kb/think/new", json={"question": "后开的题", "mode": "brainstorm"}).json()
    assert client.get("/api/kb/think/latest").json()["id"] == newer["id"]
    db.insert("chat_sessions", {"module": "kb", "ref": older["ref"], "engine": "claude", "title": "x", "created_at": db.now(), "updated_at": "2099-01-01T00:00:00"})
    assert client.get("/api/kb/think/latest").json()["id"] == older["id"]
    assert client.post(f"/api/kb/think/{older['id']}/record", json={"text": " "}).status_code == 400
    result = client.post(f"/api/kb/think/{older['id']}/record", json={"text": "我的判断"}).json()
    assert result["think"]["judgment"]["text"] == "我的判断"


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
        assert "分析讨论" in prompt and "一起想" in prompt
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


def test_delete_topic_removes_its_chats_but_keeps_judgment_and_other_topics(client, monkeypatch):
    from app import chat_images
    from test_chat_images import PNG
    _wipe()
    pic = client.post("/api/chat/images", json={"name": "topic.png", "data": "data:image/png;base64," + PNG}).json()
    first = client.post("/api/kb/think/new", json={"question": "保留的讨论", "mode": "idea", "images": [pic["id"]]}).json()
    target = client.post("/api/kb/think/new", json={"question": "要删除的讨论", "mode": "idea", "images": [pic["id"]]}).json()
    recorded = client.post(f"/api/kb/think/{target['id']}/record", json={"text": "独立保留的判断"}).json()
    sids = []
    for i in range(2):
        sid = db.insert("chat_sessions", {"module": "kb", "ref": target["ref"], "engine": "claude", "title": "x", "created_at": db.now(), "updated_at": db.now()})
        sids.append(sid)
        mid = db.insert("chat_messages", {"session_id": sid, "role": "user", "content": "看图片", "created_at": db.now()})
        chat_images.attach("message", mid, [pic["id"]])
    assert client.delete(f"/api/kb/think/{target['id']}").status_code == 200
    assert client.get(f"/api/kb/think/{target['id']}").status_code == 404
    assert all(client.get(f"/api/chat/session/{sid}").status_code == 404 for sid in sids)
    assert not db.rows("SELECT * FROM chat_messages WHERE session_id IN (?,?)", sids)
    assert not chat_images.of("think", target["id"])
    assert client.get("/api/kb/think/latest").json()["id"] == first["id"]
    assert db.row("SELECT text FROM kb_judgments WHERE id=?", [int(recorded["sid"].split(":")[1])])["text"] == "独立保留的判断"
    assert client.get(pic["url"]).status_code == 200
    assert client.delete(f"/api/kb/think/{target['id']}").status_code == 404


def test_delete_topic_refuses_running_reply_and_stale_new_messages(client, monkeypatch):
    _wipe()
    t = client.post("/api/kb/think/new", json={"question": "正在讨论的题", "mode": "idea"}).json()
    def stream(prompt, **kw):
        assert client.delete(f"/api/kb/think/{t['id']}").status_code == 409
        yield {"type": "done", "text": "讨论结束。", "engine": "claude"}
    monkeypatch.setattr(chat.agent, "run_stream", stream)
    client.post("/api/chat/kb", json={"message": "开始", "ref": t["ref"]})
    assert client.delete(f"/api/kb/think/{t['id']}").status_code == 200
    assert client.post("/api/chat/kb", json={"message": "旧页面继续发", "ref": t["ref"]}).status_code == 404
    assert not db.rows("SELECT * FROM chat_sessions WHERE ref=?", [t["ref"]])


def test_failed_chat_preparation_releases_topic_delete_guard(client, monkeypatch):
    import pytest
    _wipe()
    t = client.post("/api/kb/think/new", json={"question": "准备失败的题", "mode": "idea"}).json()
    def context(module, ref):
        assert client.delete(f"/api/kb/think/{t['id']}").status_code == 409
        raise RuntimeError("准备失败")
    monkeypatch.setattr(chat, "_context", context)
    with pytest.raises(RuntimeError, match="准备失败"):
        client.post("/api/chat/kb", json={"message": "开始", "ref": t["ref"]})
    assert client.delete(f"/api/kb/think/{t['id']}").status_code == 200
