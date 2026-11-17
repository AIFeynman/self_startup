from app import db, kb


def test_sync_writes_tree_and_searches(client):
    client.post("/api/tasks", json={"title": "整理知识库设计", "date": "2026-01-02", "goal": "能被大模型检索"})
    db.insert("review_notes", {"date": "2026-01-02", "kind": "lesson", "title": "检索先看摘要",
                               "content": "大模型先读 frontmatter 的 summary 再决定读全文，省上下文。", "tags": "kb,检索"})
    r = kb.sync()
    assert r["docs"] >= 2
    assert (kb.KB_DIR / "INDEX.md").exists() and (kb.KB_DIR / "daily/2026-01-02.md").exists()
    note = next((kb.KB_DIR / "notes").glob("2026-01-02-*.md")).read_text()
    assert note.startswith("---\n") and "type: note" in note and "summary:" in note
    assert "检索先看摘要" in (kb.KB_DIR / "daily/2026-01-02.md").read_text()  # 每日记录链接当天笔记
    assert (kb.KB_DIR / "tags/kb.md").exists()
    hits = client.get("/api/kb/search", params={"q": "frontmatter"}).json()
    assert hits and hits[0]["type"] == "note"
    assert client.get("/api/kb/search", params={"q": "检索"}).json()  # 2 字中文走 LIKE 回退
    assert "知识库索引" in client.get("/api/kb/doc", params={"path": "INDEX.md"}).text
    assert client.get("/api/kb/doc", params={"path": "../app.db"}).status_code == 404


def test_sync_removes_stale_files(client):
    nid = db.insert("review_notes", {"date": "2026-01-03", "kind": "idea", "title": "临时想法", "content": "x", "tags": ""})
    kb.sync()
    assert list((kb.KB_DIR / "notes").glob(f"2026-01-03-{nid}-*.md"))
    db.execute("DELETE FROM review_notes WHERE id=?", [nid])
    kb.sync()
    assert not list((kb.KB_DIR / "notes").glob(f"2026-01-03-{nid}-*.md"))


def test_xarticle_fulltext_endpoint(client):
    from app.modules import _xart
    _xart.init()
    db.execute("INSERT INTO x_art (id,user,title,text,stage,q) VALUES ('11','a','t','正文第一段\n\n第二段','scored',3)")
    db.execute("INSERT INTO x_art (id,user,title,text,stage) VALUES ('12','a','t','没打分','titled')")
    assert client.get("/api/kb/xarticles/11").json() == {"text": "正文第一段\n\n第二段"}
    assert client.get("/api/kb/xarticles/12").status_code == 404
    assert client.get("/api/kb/xarticles/search").json()["running"] is False


def test_xarticle_blocks_keep_images_and_translate_skips_them(client, monkeypatch):
    from app.modules import _xart
    _xart.init()
    text = _xart._blocks_text({"contents": [{"type": "unstyled", "text": "Hello"},
                                            {"type": "image", "url": "https://pbs.twimg.com/media/a.jpg"},
                                            {"type": "unstyled", "text": "World"}]})
    assert text == "Hello\n![](https://pbs.twimg.com/media/a.jpg)\nWorld"
    db.execute("INSERT INTO x_art (id,user,title,text,stage,q) VALUES ('21','a','t',?,'scored',3)", [text])
    sent = []
    monkeypatch.setattr(_xart.pl, "chat", lambda system, user, *a, **k: (sent.append(user) or "你好\n![](https://pbs.twimg.com/media/a.jpg)\n世界", 0))
    zh = client.post("/api/kb/xarticles/21/translate").json()["text"]
    assert "![](https://pbs.twimg.com/media/a.jpg)" in zh and "你好" in zh
    client.post("/api/kb/xarticles/21/translate")
    assert len(sent) == 1
    assert client.post("/api/kb/xarticles/999/translate").status_code == 404


def test_xarticle_search_splits_cjk_and_matches_fulltext(client):
    from app.modules import _xart
    _xart.init()
    db.execute("INSERT INTO x_art (id,user,title,text,stage,q) VALUES ('31','a','Agent 手册','讲 AI 公司怎么创业，找客户','scored',3)")
    assert [r["id"] for r in _xart.listing("AI创业")] == ["31"]
    assert _xart.listing("AI融资") == []


def test_xart_daily_runs_once_a_day_and_stops_over_budget(client, monkeypatch):
    from datetime import datetime
    from app.modules import _xart as x
    x.init()
    crawled = []
    monkeypatch.setattr(x, "crawl_day", lambda d: crawled.append(d) or {"day": d, "calls": 400})
    monkeypatch.setattr(x, "gate", lambda: {})
    monkeypatch.setattr(x, "grab", lambda **k: {"ok": 10, "drop": 2})
    monkeypatch.setattr(x, "relevance", lambda **k: {})
    monkeypatch.setattr(x, "fulltext", lambda **k: {"ok": 3, "short": 0, "failed": 0})
    monkeypatch.setattr(x, "score", lambda **k: {})
    now = datetime(2026, 11, 17, 5, 0)
    assert x.due(now) and not x.due(datetime(2026, 11, 17, 3, 0))
    res = x.daily(now)
    assert crawled[-1] == "2026-11-15" and res["calls"] == 400 * len(crawled) + 15
    assert not x.due(now)
    db.execute("UPDATE x_art_run SET calls=?", [x.MONTH_STOP_CALLS])
    assert x.daily(datetime(2026, 11, 18, 5, 0)) == {"stopped": "月调用数到上限"}


def test_xart_listing_sorts_by_views_and_followers(client):
    from app.modules import _xart as x
    x.init()
    for i, (v, f) in enumerate([(100, 9000), (900, 10), (500, 500)]):
        db.execute("INSERT INTO x_art (id,user,fol,views,stage,q,title,day) VALUES (?,?,?,?,'scored',3,?,'2026-11-01')", [f"sort{i}", f"u{i}", f, v, f"t{i}"])
    pick = lambda sort: [r for r in x.listing(sort=sort) if r["id"].startswith("sort")]
    assert [r["id"] for r in pick("views")] == ["sort1", "sort2", "sort0"]
    top = pick("fol")
    assert [r["id"] for r in top] == ["sort0", "sort2", "sort1"] and top[0]["fol"] == 9000
