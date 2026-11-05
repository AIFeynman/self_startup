"""便签：和系统记录分开、自定义类型、关系、引用来源、评论进便签、老库迁移。"""
import sqlite3


def _clean():
    from app import db
    db.execute("DELETE FROM review_notes")
    db.execute("DELETE FROM note_links")


def test_mine_and_system_are_separate(client):
    _clean()
    client.post("/api/review/notes", json={"kind": "lesson", "title": "系统记的"})
    me = client.post("/api/notes", json={"text": "我想到的\n第二行"}).json()
    assert me["author"] == "me" and me["kind"] == "spark" and me["title"] == "我想到的" and me["text"] == "我想到的\n第二行"
    quick = client.post("/api/review/notes/quick", json={"text": "⌘K 记的"}).json()
    assert quick["author"] == "me"
    assert {n["title"] for n in client.get("/api/notes").json()["notes"]} == {"我想到的", "⌘K 记的"}
    assert [n["title"] for n in client.get("/api/review/notes?author=system").json()] == ["系统记的"]
    assert [n["title"] for n in client.get("/api/review/day").json()["notes"]] == ["系统记的"]
    # 划错了可以来回移，退回时自定义类型落回系统类型，关系解除
    sys_note = client.get("/api/review/notes?author=system").json()[0]
    assert client.patch(f"/api/review/notes/{sys_note['id']}", json={"author": "me"}).json()["author"] == "me"
    custom = client.patch(f"/api/notes/{sys_note['id']}", json={"kind": "读书"}).json()
    client.post(f"/api/notes/{custom['id']}/links", json={"to": me["id"]})
    back = client.patch(f"/api/notes/{custom['id']}", json={"author": "system"}).json()
    assert back["author"] == "system" and back["kind"] == "lesson"
    assert client.get("/api/notes").json()["links"] == []
    assert client.patch(f"/api/review/notes/{sys_note['id']}", json={"author": "x"}).status_code == 400


def test_custom_kinds(client):
    _clean()
    assert client.post("/api/notes", json={"text": "a", "kind": "问题"}).json()["kind"] == "problem"  # 中文名也认
    assert client.post("/api/notes", json={"text": "b", "kind": "读书"}).json()["kind"] == "读书"
    assert client.post("/api/notes", json={"text": "问题：c", "kind": "读书"}).json()["kind"] == "problem"  # 前缀优先
    n = client.post("/api/notes", json={"text": "读书：用过的类型能当前缀"}).json()
    assert n["kind"] == "读书" and n["title"] == "用过的类型能当前缀"
    assert client.post("/api/notes", json={"text": "没用过：不算前缀"}).json()["title"] == "没用过：不算前缀"
    ks = {k["key"]: k for k in client.get("/api/notes/kinds").json()}
    assert ks["读书"]["count"] == 2 and not ks["读书"]["builtin"] and ks["spark"]["label"] == "灵感"
    client.delete(f"/api/notes/{n['id']}")
    for x in client.get("/api/notes?kind=读书").json()["notes"]:
        client.delete(f"/api/notes/{x['id']}")
    assert "读书" not in {k["key"] for k in client.get("/api/notes/kinds").json()}  # 没人用就消失
    assert client.post("/api/notes", json={"text": "  "}).status_code == 400


def test_links(client):
    _clean()
    a = client.post("/api/notes", json={"text": "a"}).json()["id"]
    b = client.post("/api/notes", json={"text": "b"}).json()["id"]
    s = client.post("/api/review/notes", json={"title": "系统"}).json()["id"]
    l = client.post(f"/api/notes/{a}/links", json={"to": b, "rel": "追问"}).json()
    assert l["rel"] == "追问"
    assert client.post(f"/api/notes/{b}/links", json={"to": a}).status_code == 400  # 反向也算重复
    assert client.post(f"/api/notes/{a}/links", json={"to": a}).status_code == 400
    assert client.post(f"/api/notes/{a}/links", json={"to": s}).status_code == 404  # 只连自己的便签
    assert client.patch(f"/api/notes/links/{l['id']}", json={"rel": "反驳"}).json()["rel"] == "反驳"
    assert client.patch(f"/api/notes/links/{l['id']}", json={"rel": "乱写"}).status_code == 400
    client.delete(f"/api/notes/{b}")
    assert client.get("/api/notes").json()["links"] == []


def test_sources(client):
    _clean()
    from app import db
    lid = db.insert("learn_items", {"kind": "paper", "url": "https://x.dev/a", "title": "快慢思考深读", "status": "done"})
    rid = db.insert("research_docs", {"title": "快慢思考调研", "content": "x"})
    fid = "notes-test:1"
    db.insert("feed_items", {"id": fid, "source": "hn", "type": "blog", "title": "快慢思考博客", "url": "https://y.dev/b", "date": "2026-01-01"})
    found = client.get("/api/notes/sources?q=快慢思考").json()
    assert {(s["type"], s["doc"]) for s in found} >= {("深读", f"learn:item:{lid}"), ("调研", f"research_doc:{rid}"), ("信息流", f"feed:{fid}")}
    by_url = client.get("/api/notes/sources?q=https://x.dev/a").json()
    assert by_url[0]["doc"] == f"learn:item:{lid}"
    ext = client.get("/api/notes/sources?q=https://nowhere.dev/z").json()
    assert ext == [{"doc": "", "title": "https://nowhere.dev/z", "link": "https://nowhere.dev/z", "type": "链接"}]
    n = client.post("/api/notes", json={"text": "引用", "sources": [
        {"doc": f"learn:item:{lid}", "title": "快慢思考深读", "link": f"#learn/item/{lid}", "type": "深读", "quote": "原文"},
        {"title": "坏链接", "link": "javascript:alert(1)"}, {"title": "", "link": ""},
    ]}).json()
    assert [s["title"] for s in n["sources"]] == ["快慢思考深读", "坏链接"]
    assert n["sources"][0]["quote"] == "原文" and n["sources"][1]["link"] == ""
    assert client.patch(f"/api/notes/{n['id']}", json={"sources": []}).json()["sources"] == []


def test_comment_becomes_note(client):
    _clean()
    base = {"doc": "research_doc:9", "title": "某调研", "link": "#research/docs/9", "quote": "划的这句"}
    t = client.post("/api/annotations", json={**base, "text": "这里值得试试", "note_kind": "感想"}).json()
    notes = client.get("/api/notes").json()["notes"]
    assert len(notes) == 1 and notes[0]["kind"] == "feeling" and notes[0]["title"] == "这里值得试试"
    src = notes[0]["sources"][0]
    assert src == {"doc": "research_doc:9", "title": "某调研", "link": "#research/docs/9", "type": "调研", "quote": "划的这句", "annotation_id": t["id"]}
    client.post(f"/api/annotations/{t['id']}/msgs", json={"text": "回复也算", "note_kind": "读书"})
    assert client.get("/api/notes?kind=读书").json()["notes"][0]["sources"][0]["annotation_id"] == t["id"]
    # 不进便签：没选类型、问 Claude 的问题
    client.post("/api/annotations", json={**base, "text": "不贴"})
    assert len(client.get("/api/notes").json()["notes"]) == 2
    # 删评论不删便签
    client.delete(f"/api/annotations/{t['id']}")
    assert len(client.get("/api/notes").json()["notes"]) == 2


def test_sources_find_intel(client):
    """产品雷达里的公司能按名字和拆解卡正文找到，事件和增长 Case 也能找到；出处能指回去。"""
    from app import db
    from app.modules import intel  # noqa: F401 —— 建表
    cid = db.insert("intel_company", {"slug": "acme-x", "name": "AcmeX"})
    db.insert("intel_profile", {"company_id": cid, "content": "渠道和产品合一的打法"})
    db.insert("intel_event", {"company_id": cid, "title": "BetaWidget 发布"})
    assert {"doc": "intel:company:acme-x", "title": "AcmeX", "link": "#intel/c/acme-x", "type": "产品雷达"} in client.get("/api/notes/sources?q=AcmeX").json()
    assert "intel:company:acme-x" in [s["doc"] for s in client.get("/api/notes/sources?q=渠道和产品").json()]
    assert any(s["title"] == "BetaWidget 发布" and s["type"] == "产品雷达" for s in client.get("/api/notes/sources?q=BetaWidget").json())


def test_chat_quote_source(client):
    """从 Agent 对话划线记的便签：出处标成 Agent 对话，链接留得住。"""
    _clean()
    n = client.post("/api/notes", json={"text": "渠道和产品合一", "sources": [{"doc": "chat:7", "title": "讨论：选题", "link": "#chat/7"}]}).json()
    assert n["sources"][0]["type"] == "Agent 对话" and n["sources"][0]["link"] == "#chat/7"


def test_old_db_migration(tmp_path, monkeypatch):
    """老库没有新字段：补上列，已有记录算系统记的，内容不变。"""
    from app import db
    p = tmp_path / "old.db"
    c = sqlite3.connect(p)
    c.execute("CREATE TABLE review_notes (id INTEGER PRIMARY KEY, date TEXT, kind TEXT, title TEXT, content TEXT, tags TEXT, created_at TEXT, updated_at TEXT)")
    c.execute("INSERT INTO review_notes VALUES (16, '2026-11-04', 'lesson', '老记录', '正文', '', 'x', 'x')")
    c.commit()
    c.close()
    monkeypatch.setattr(db, "DB_PATH", p, raising=False)
    monkeypatch.setattr(db, "_conn", None, raising=False)
    db.init()
    r = db.row("SELECT * FROM review_notes WHERE id=16")
    assert r["author"] == "system" and r["sources"] == "[]" and r["title"] == "老记录" and r["content"] == "正文"
    db.init()  # 再跑一次不报错
    db.conn().close()
