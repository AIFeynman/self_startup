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
