from app import db, kb, kb_graph
from app.modules import feed, learn


def _fake_llm(system, payload, max_tokens=6000):
    if system == kb_graph.EXTRACT_SYSTEM:
        out = []
        for it in payload["items"]:
            cs = [c for c in ("甲概念", "乙概念") if c in it["mine"] + it["title"]]
            out.append({"sid": it["sid"], "concepts": cs, "claim": it["title"]})
        return {"items": out}
    if system == kb_graph.NORMALIZE_SYSTEM:
        return {"groups": [{"name": c["name"], "category": "方法", "aliases": []} for c in payload["concepts"]]}
    if system == kb_graph.TOPIC_SYSTEM:
        return {"topics": [{"name": "测试主题", "desc": "测试用", "concepts": [c["name"] for c in payload["concepts"]]}]}
    if system == kb_graph.SUMMARY_SYSTEM:
        return {"points": ["先看甲再看乙[1]"], "open": ["还没想清楚"]}
    return {}


def _setup(monkeypatch):
    monkeypatch.setattr(kb_graph, "llm_json", _fake_llm)
    monkeypatch.setattr(kb_graph, "has_llm", lambda: True)
    for i, t in enumerate(["甲概念要先做", "甲概念和乙概念要一起看", "乙概念不靠谱"]):
        db.insert("review_notes", {"date": f"2026-02-0{i + 1}", "kind": "insight", "title": t, "content": t, "tags": ""})
    r = kb_graph.refresh()
    assert r["state"] == "idle", r


def test_refresh_builds_concepts_and_obsidian_files(client, monkeypatch):
    _setup(monkeypatch)
    g = client.get("/api/kb/graph").json()
    ids = {n["id"] for n in g["nodes"]}
    assert {"甲概念", "乙概念"} <= ids
    assert any({e["a"], e["b"]} == {"甲概念", "乙概念"} for e in g["edges"])
    assert any(t["name"] == "测试主题" for t in g["topics"])
    c = client.get("/api/kb/concept", params={"name": "甲概念"}).json()
    assert len(c["judgments"]) == 2 and c["topic"] == "测试主题"
    assert c["summary"]["points"] and c["judgments"][0]["date"] <= c["judgments"][1]["date"]
    assert any(r["name"] == "乙概念" for r in c["related"])
    page = (kb.KB_DIR / "concepts/甲概念.md").read_text()
    assert "[[乙概念]]" in page and "[[topics/测试主题|测试主题]]" in page
    assert (kb.KB_DIR / "GRAPH.md").exists() and (kb.KB_DIR / "topics/测试主题.md").exists()
    hits = client.get("/api/kb/search", params={"q": "甲概念"}).json()
    assert any(h["type"] == "concept" for h in hits)


def test_edits_rename_undo_hide(client, monkeypatch):
    _setup(monkeypatch)
    assert client.post("/api/kb/concept/edit", json={"op": "rename", "src": "甲概念", "dst": "丙概念"}).status_code == 200
    c = client.get("/api/kb/concept", params={"name": "甲概念"}).json()
    assert c["name"] == "丙概念" and "甲概念" in c["aliases"]
    assert (kb.KB_DIR / "concepts/丙概念.md").exists() and not (kb.KB_DIR / "concepts/甲概念.md").exists()
    # 改回原名 = 撤销
    client.post("/api/kb/concept/edit", json={"op": "rename", "src": "丙概念", "dst": "甲概念"})
    assert client.get("/api/kb/concept", params={"name": "甲概念"}).json()["name"] == "甲概念"
    # 编辑只追加，重刷不会丢
    kb_graph.refresh()
    assert db.row("SELECT count(*) AS n FROM kb_concept_edit")["n"] >= 2
    client.post("/api/kb/concept/edit", json={"op": "hide", "src": "乙概念"})
    ids = {n["id"] for n in client.get("/api/kb/graph").json()["nodes"]}
    assert "乙概念" not in ids and "甲概念" in ids
    client.post("/api/kb/concept/edit", json={"op": "unhide", "src": "乙概念"})
    assert "乙概念" in {n["id"] for n in client.get("/api/kb/graph").json()["nodes"]}


def test_my_notes_and_comments_stay_local(client, monkeypatch):
    """我写的便签、文档评论不发给大模型；系统记的问题与经验照旧。"""
    sent = []

    def spy(system, payload, max_tokens=6000):
        sent.append(str(payload))
        return _fake_llm(system, payload, max_tokens)
    monkeypatch.setattr(kb_graph, "llm_json", spy)
    monkeypatch.setattr(kb_graph, "has_llm", lambda: True)
    assert client.post("/api/notes", json={"text": "本地便签原文", "kind": "spark"}).status_code == 200
    assert client.post("/api/review/notes/quick", json={"text": "灵感: 本地快记原文"}).status_code == 200
    r = client.post("/api/annotations", json={"doc": "doc:local", "title": "本地文档", "quote": "本地划线原文",
                                              "text": "本地评论原文", "note_kind": "spark"})
    assert r.status_code == 200
    client.post("/api/review/notes", json={"date": "2026-01-02", "kind": "lesson", "title": "系统经验原文", "content": "x"})
    db.execute("INSERT INTO products(name, experience, pros, created_at) VALUES ('本地产品','本地体验原文','本地优点原文',?)", [db.now()])
    item = db.insert("learn_items", {"kind": "paper", "title": "本地论文", "url": "http://x/local", "status": "done", "my_notes": "本地笔记原文",
                                     "created_at": db.now(), "updated_at": db.now()})
    plan = db.insert("learn_plans", {"topic": "本地计划", "created_at": db.now(), "updated_at": db.now()})
    db.insert("learn_steps", {"plan_id": plan, "title": "本地步骤", "feedback": "本地反馈原文"})
    feed._ensure_cols()
    db.execute("INSERT INTO feed_items(id, source, type, title, url, summary, date) VALUES ('t:local','t','paper','本地条目','http://x/f','',?)", [db.today()])
    db.execute("INSERT INTO feed_feedback(item_id, verdict, verdict_at, updated_at) VALUES ('t:local','本地判断原文',?,?)", [db.now(), db.now()])
    # 以前抽取过的，下次刷新清掉缓存
    db.execute("INSERT INTO kb_sig_cache(sid, hash, concepts, claim, at) VALUES ('ann:99999','h','[]','',?)", [db.now()])
    assert kb_graph.refresh()["state"] == "idle"
    text = "\n".join(sent)
    assert "系统经验原文" in text
    for mark in ("本地便签原文", "本地快记原文", "本地评论原文", "本地划线原文", "本地体验原文", "本地优点原文", "本地笔记原文", "本地反馈原文", "本地判断原文"):
        assert mark not in text
    assert not db.row("SELECT 1 FROM kb_sig_cache WHERE sid='ann:99999'")
    assert "本地笔记原文" not in learn._known_knowledge(item + 1)
    kb.sync(refresh_graph=False)
    assert client.get("/api/kb/search", params={"q": "本地便签原文"}).json()   # 本地搜索还能找到
