import json

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


def _tw(i, user="u", fol=10, views=0, likes=0, at="Tue Nov 17 01:00:00 +0000 2026"):
    return {"id": str(i), "createdAt": at, "viewCount": views, "likeCount": likes, "author": {"userName": user, "followers": fol}}


class _Ctx:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_xart_daily_runs_once_a_day_and_stops_over_budget(client, monkeypatch):
    from datetime import datetime
    from app.modules import _xart as x
    x.init()
    monkeypatch.setattr(x, "crawl_since", lambda now: {"calls": 400})
    monkeypatch.setattr(x, "gate", lambda: {})
    monkeypatch.setattr(x, "grab_ids", lambda: [])
    monkeypatch.setattr(x, "grab", lambda **k: {"ok": 10, "drop": 2})
    monkeypatch.setattr(x, "stale", lambda: 0)
    monkeypatch.setattr(x, "dedupe", lambda: {})
    monkeypatch.setattr(x, "relevance", lambda **k: {"todo": 0, "miss": 0, "err": 0})
    monkeypatch.setattr(x, "fulltext", lambda **k: {"ok": 3, "short": 0, "failed": 0})
    monkeypatch.setattr(x, "score", lambda **k: {"todo": 0, "miss": 0, "err": 0})
    now = datetime(2026, 11, 17, 5, 0)
    assert x.due(now) and not x.due(datetime(2026, 11, 17, 3, 0))
    assert x.daily(now)["calls"] == 415
    assert not x.due(now)
    db.execute("UPDATE x_art_run SET calls=?", [x.MONTH_STOP_CALLS])
    assert x.daily(datetime(2026, 11, 18, 5, 0)) == {"stopped": "月调用数到上限"}


def test_xart_crawl_since_uses_watermark_with_overlap_and_dedupes(client, monkeypatch):
    import pytest
    from app.modules import _xart as x
    x.init()
    db.execute("DELETE FROM x_art_mark")
    spans = []
    monkeypatch.setattr(x, "_client", lambda: _Ctx())
    monkeypatch.setattr(x, "search_window", lambda c, t0, t1, stat: spans.append((t0, t1)) or [_tw("w1", views=50), _tw("w1", views=50)])
    now = 1_800_000_000
    r = x.crawl_since(now)
    assert spans[0][0] == now - x.FIRST_SPAN and spans[-1][1] == now and r["new"] == 1 and x._mark() == now
    spans.clear()
    x.crawl_since(now + 7200)
    assert spans[0][0] == now - x.OVERLAP and spans[-1][1] == now + 7200
    spans.clear()
    r = x.crawl_since(now + 10 * 86400)
    assert spans[0][0] == now + 10 * 86400 - x.MAX_GAP and r["gap"]

    def boom(*a):
        raise RuntimeError("x")
    monkeypatch.setattr(x, "search_window", boom)
    with pytest.raises(RuntimeError):
        x.crawl_since(now + 20 * 86400)
    assert x._mark() == now + 10 * 86400


def test_xart_resight_updates_views_and_revives_dropped(client):
    from app.modules import _xart as x
    x.init()
    assert x._save_found(_tw("rv1", views=10), "2026-11-17")
    assert not x._save_found(_tw("rv1", views=900, likes=3, fol=50), "2026-11-17")
    db.execute("UPDATE x_art SET stage='drop_view' WHERE id='rv1'")
    assert not x._save_found(_tw("rv1", views=400), "2026-11-17")
    r = db.row("SELECT stage,views,likes,fol FROM x_art WHERE id='rv1'")
    assert (r["stage"], r["views"], r["likes"], r["fol"]) == ("drop_view", 900, 3, 50)
    assert not x._save_found(_tw("rv1", views=1500), "2026-11-17")
    assert db.row("SELECT stage FROM x_art WHERE id='rv1'")["stage"] == "found"


def test_xart_gate_tiers_and_grab_priority(client, monkeypatch):
    from app.modules import _xart as x
    x.init()
    monkeypatch.setattr(x, "watch", lambda: ["watched"])
    db.execute("DELETE FROM x_art WHERE stage='found'")
    rows = [("g1", "nobody", 5, 0, 0), ("g2", "nobody", 5, 100, 0), ("g3", "nobody", 5, 0, 5), ("g4", "watched", 5, 0, 0),
            ("g5", "big", 600000, 0, 0), ("g6", "mid", 30000, 0, 0), ("g7", "nobody", 5, 300, 0)]
    for i, u, f, v, l in rows:
        db.execute("INSERT INTO x_art (id,user,fol,views,likes,stage) VALUES (?,?,?,?,?,'found')", [i, u, f, v, l])
    x.gate()
    st = {r["id"]: r["stage"] for r in db.rows("SELECT id,stage FROM x_art WHERE id LIKE 'g%'")}
    assert st["g1"] == "drop_view" and all(st[k] == "found" for k in ("g2", "g3", "g4", "g5", "g6", "g7"))
    ids = [i for i in x.grab_ids(cap=1) if i.startswith("g")]
    assert set(ids) == {"g4", "g5", "g6", "g7"}


def test_xart_dedupe_same_author_same_title_keeps_earliest(client):
    from app.modules import _xart as x
    x.init()
    for i, st in [("d1", "scored"), ("d2", "titled"), ("d3", "titled")]:
        db.execute("INSERT INTO x_art (id,user,title,stage) VALUES (?, 'dupa', ?, ?)", [i, "同一篇" if i != "d3" else "另一篇", st])
    db.execute("INSERT INTO x_art (id,user,title,stage) VALUES ('d4','dupb','同一篇','titled')")
    x.dedupe()
    st = {r["id"]: r["stage"] for r in db.rows("SELECT id,stage FROM x_art WHERE id LIKE 'd_'")}
    assert st == {"d1": "scored", "d2": "drop_dup", "d3": "titled", "d4": "titled"}


def test_xart_refresh_endpoint_rejects_double_start(client):
    from app.modules import _xart as x
    assert x._lock.acquire(blocking=False)
    try:
        assert client.post("/api/kb/xarticles/refresh").json() == {"started": False}
        assert client.get("/api/kb/xarticles/status").json()["running"] is True
    finally:
        x._lock.release()


def test_xart_listing_sorts_by_views_and_followers(client):
    from app.modules import _xart as x
    x.init()
    for i, (v, f) in enumerate([(100, 9000), (900, 10), (500, 500)]):
        db.execute("INSERT INTO x_art (id,user,fol,views,stage,q,title,day) VALUES (?,?,?,?,'scored',3,?,'2026-11-01')", [f"sort{i}", f"u{i}", f, v, f"t{i}"])
    pick = lambda sort: [r for r in x.listing(sort=sort) if r["id"].startswith("sort")]
    assert [r["id"] for r in pick("views")] == ["sort1", "sort2", "sort0"]
    top = pick("fol")
    assert [r["id"] for r in top] == ["sort0", "sort2", "sort1"] and top[0]["fol"] == 9000


def test_library_counts_total_and_last_day_added(client):
    from datetime import datetime, timedelta
    from app.modules import _xart
    _xart.init()
    base = client.get("/api/kb/library").json()
    old = (datetime.now() - timedelta(days=3)).isoformat(timespec="seconds")
    db.execute("INSERT INTO x_art (id,user,stage,mkt,updated) VALUES ('lib1','a','scored',0,?)", [db.now()])
    db.execute("INSERT INTO x_art (id,user,stage,mkt,updated) VALUES ('lib2','a','scored',0,?)", [old])
    got = client.get("/api/kb/library").json()
    assert got["xart"]["total"] == base["xart"]["total"] + 2 and got["xart"]["added"] == base["xart"]["added"] + 1
    assert set(got) == {"xart", "paper", "repo"}


def test_xarticle_listing_filters_by_domain_and_kind_and_score_unhides_good_marketing(client, monkeypatch):
    from app.modules import _xart
    _xart.init()
    for i, (d, k) in enumerate([("agent", "教程"), ("agent", "观点"), ("strategy", "教程")]):
        db.execute("INSERT INTO x_art (id,user,title,text,stage,q,domain,kind) VALUES (?,'a','t','x','scored',3,?,?)", [f"4{i}", d, k])
    assert sorted(r["id"] for r in _xart.listing(domain="agent")) == ["40", "41"]
    assert [r["id"] for r in _xart.listing(domain="agent", kind="教程")] == ["40"]
    assert sorted(r["id"] for r in _xart.listing(kind="教程")) == ["40", "42"]
    assert all(r["domain"] for r in _xart.listing(limit=1000) if r["id"] in {"40", "41", "42"})
    from datetime import datetime, timedelta
    db.execute("UPDATE x_art SET day=? WHERE id='40'", [datetime.now().strftime("%Y-%m-%d")])
    db.execute("UPDATE x_art SET day=? WHERE id='41'", [(datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d")])
    mine = lambda days: sorted(r["id"] for r in _xart.listing(days=days, limit=1000) if r["id"] in {"40", "41", "42"})
    assert mine(1) == ["40"] and mine(7) == ["40", "41"] and mine(0) == ["40", "41", "42"]

    db.execute("INSERT INTO x_art (id,user,title,text,stage) VALUES ('51','a','t','课程 正文','full')")
    db.execute("INSERT INTO x_art (id,user,title,text,stage) VALUES ('52','a','t','课程 正文','full')")
    out = {"51": {"q": 3, "mkt": True, "kind": "教程"}, "52": {"q": 3, "mkt": True, "kind": "产品介绍"}}
    monkeypatch.setattr(_xart.pl, "chat", lambda *a, **k: (json.dumps([{"id": i, **v} for i, v in out.items()]), 0))
    _xart.score(ids=["51", "52"])
    assert {r["id"]: r["mkt"] for r in db.rows("SELECT id,mkt FROM x_art WHERE id IN ('51','52')")} == {"51": 0, "52": 1}


def _sync_in_another_process(n_docs: int, rounds: int) -> None:
    from app import kb as k
    docs = [{"id": i, "path": f"x-articles/{i}-器用貧乏な人ほど稼ぎやすくなっている理由.md", "text": f"# {i}\n",
             "type": "xarticle", "title": str(i), "tags": [], "summary": "", "body": "", "date": "2026-01-01"} for i in range(n_docs)]
    k.build = lambda: docs
    k._graph_layer = lambda d: ({}, [], 0)
    k._index = lambda d: ("# index\n", {})
    for _ in range(rounds):
        k.sync(refresh_graph=False)


def test_sync_from_concurrent_processes_keeps_manifest_readable():
    """服务进程和各个 jobrun 进程都会 sync；manifest 不能被并发写成半新半旧（曾在末尾留下另一份的残尾，读时 UnicodeDecodeError）。"""
    import multiprocessing as mp
    db.init([kb.FTS_SCHEMA])
    ctx = mp.get_context("spawn")
    procs = [ctx.Process(target=_sync_in_another_process, args=(1500 + 37 * i, 80)) for i in range(8)]
    for p in procs:
        p.start()
    for p in procs:
        p.join(120)
    assert [p.exitcode for p in procs] == [0] * len(procs)
    assert isinstance(json.loads((kb.KB_DIR / kb.MANIFEST).read_text("utf-8")), list)


def test_sync_updates_fulltext_index_incrementally(client):
    db.insert("review_notes", {"date": "2026-01-04", "kind": "idea", "title": "不变的笔记", "content": "稳定内容", "tags": ""})
    edit = db.insert("review_notes", {"date": "2026-01-05", "kind": "idea", "title": "会改的笔记", "content": "旧的正文", "tags": ""})
    gone = db.insert("review_notes", {"date": "2026-01-06", "kind": "idea", "title": "会删的笔记", "content": "要删掉", "tags": ""})
    kb.sync()
    writes = []
    db.conn().set_trace_callback(lambda sql: writes.append(sql) if "kb_fts" in sql and not sql.lstrip().upper().startswith(("SELECT", "CREATE", "--")) else None)
    try:
        kb.sync()
        assert writes == []

        db.execute("UPDATE review_notes SET content=? WHERE id=?", ["新写的正文内容", edit])
        db.execute("DELETE FROM review_notes WHERE id=?", [gone])
        kb.sync()
    finally:
        db.conn().set_trace_callback(None)
    assert 0 < len(writes) <= 8
    assert not any(w.replace(" ", "").upper().startswith("DELETEFROMKB_FTS") and "WHERE" not in w.upper() for w in writes)
    titles = {r["title"] for r in db.rows("SELECT title FROM kb_fts")}
    assert "不变的笔记" in titles and "会删的笔记" not in titles
    assert [h["title"] for h in kb.search("新写的正文", "note")] == ["会改的笔记"]
    assert not kb.search("旧的正文", "note")


def test_search_mixed_sentence_matches_by_terms(client):
    kb._sync_fts([
        {"path": "research/a.md", "type": "research", "title": "Hugging Face 评测指南", "tags": [], "summary": "LLM 评测怎么做", "body": "evaluation guidebook", "date": "2026-11-01"},
        {"path": "research/b.md", "type": "research", "title": "Hugging Face 产品时间线", "tags": [], "summary": "", "body": "Hub 和模型托管", "date": "2026-11-02"},
        {"path": "notes/c.md", "type": "note", "title": "评测方法笔记", "tags": [], "summary": "", "body": "benchmark", "date": "2026-11-03"},
    ])
    hits = [h["path"] for h in client.get("/api/kb/search", params={"q": "hugging face的评测课"}).json()]
    assert hits[0] == "research/a.md"
    assert "notes/c.md" not in hits
    assert [h["path"] for h in kb.search("Hugging Face 的评测")] == ["research/a.md"]
    assert {h["path"] for h in kb.search("评测课")} == {"research/a.md", "notes/c.md"}
