from app import chat, db, kb_idea

from test_kb_judge import _clean, _setup  # noqa: F401


def _wipe():
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
    assert "批判者" in ctx and "不给结论" in ctx and t["question"] in ctx
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


def test_own_question_digs_five_layers(client, monkeypatch):
    _wipe()
    assert client.post("/api/kb/think/new", json={"question": "要不要先做评测？", "stance": " "}).status_code == 400
    t = client.post("/api/kb/think/new", json={"question": "要不要先做评测？", "stance": "要，没评测就不知道改得对不对"}).json()
    assert t["stance"] == "要，没评测就不知道改得对不对" and t["origin_sid"] == ""
    assert t["depth"] == 0 and t["max_depth"] == 5 and not t["bottomed"]
    assert client.get("/api/kb/think/today").json()["id"] == t["id"]

    ctx, _ = chat._context("kb", t["ref"])
    assert "要不要先做评测？" in ctx and "没评测就不知道改得对不对" in ctx
    assert "〔第 N / 5 层〕" in ctx and "〔5 层到底〕" in ctx and "还没开始挖" in ctx
    assert all(k in ctx for k in ("隐含前提", "反例", "改主意"))

    sid = db.insert("chat_sessions", {"module": "kb", "ref": t["ref"], "engine": "claude", "title": "x", "created_at": db.now(), "updated_at": db.now()})
    _say(sid, "assistant", "〔第 1 / 5 层〕\n**一个认知**：……")
    _say(sid, "user", "因为改动多")
    _say(sid, "assistant", "〔第 2 / 5 层〕\n……")
    _say(sid, "user", "嗯")
    _say(sid, "assistant", "〔第 2 / 5 层〕\n换个角度……")
    got = client.get(f"/api/kb/think/{t['id']}").json()
    assert got["depth"] == 2 and got["chatted"] and not got["bottomed"]
    assert "已经挖到第 2 层" in chat._context("kb", t["ref"])[0]

    _say(sid, "assistant", "〔5 层到底〕\n第 1 层你说……")
    got = client.get(f"/api/kb/think/{t['id']}").json()
    assert got["depth"] == 5 and got["bottomed"]
    assert "5 层已经挖到底" in chat._context("kb", t["ref"])[0]

    r = client.post(f"/api/kb/think/{t['id']}/record", json={"text": "评测先做最小一版", "type": "观点"}).json()
    row = db.row("SELECT * FROM kb_judgments WHERE id=?", [int(r["sid"].split(":")[1])])
    assert "要不要先做评测？" in row["note"] and "没评测就不知道改得对不对" in row["note"]
