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
