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
    # 没选类型不进便签
    client.post("/api/annotations", json={**base, "text": "不贴"})
    assert len(client.get("/api/notes").json()["notes"]) == 2
    # 删评论不删便签
    client.delete(f"/api/annotations/{t['id']}")
    assert len(client.get("/api/notes").json()["notes"]) == 2


def test_question_to_claude_becomes_note(client, monkeypatch):
    from app import annotations
    monkeypatch.setattr(annotations, "_answer", lambda *a: None)
    _clean()
    base = {"doc": "research_doc:9", "title": "某调研", "link": "#research/docs/9", "quote": "划的这句"}
    t = client.post("/api/annotations", json={**base, "text": "这句怎么理解", "ask": True, "note_kind": "经验"}).json()
    notes = client.get("/api/notes").json()["notes"]
    assert [n["title"] for n in notes] == ["这句怎么理解"]
    assert notes[0]["sources"][0]["quote"] == "划的这句" and notes[0]["sources"][0]["annotation_id"] == t["id"]
    a = t["id"]
    from app import db
    db.execute("UPDATE annotation_msgs SET status='done' WHERE annotation_id=?", [a])
    client.post(f"/api/annotations/{a}/msgs", json={"text": "再追问一句", "ask": True, "note_kind": "经验"})
    assert {n["title"] for n in client.get("/api/notes").json()["notes"]} == {"这句怎么理解", "再追问一句"}
    # 只点「问 Claude」没写字、或选了不进便签：没有便签
    client.post("/api/annotations", json={**base, "ask": True, "note_kind": "经验"})
    client.post("/api/annotations", json={**base, "text": "不贴", "ask": True})
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


def test_review_template_saves_one_note_with_every_filled_area(client):
    _clean()
    r = client.post("/api/notes/review", json={"date": "2026-03-01", "entries": {
        "产品迭代·做得好的": ["模板上线了"],
        "产品迭代·有问题的": ["排期写不清，下一步先写标准"],
        "个人效率·做得好的": ["   "],
        "AI协作·有问题的": [],
        "学习提升·做得好的": ["读完一篇论文 #论文"],
    }})
    assert r.status_code == 200
    wall = client.get("/api/notes?kind=review").json()
    assert len(wall["notes"]) == 1
    n = wall["notes"][0]
    assert n["kind"] == "review" and n["author"] == "me" and n["date"] == "2026-03-01" and n["tags"] == "论文"
    assert n["text"].splitlines() == ["复盘 03-01", "产品迭代·做得好的：模板上线了",
                                      "产品迭代·有问题的：排期写不清，下一步先写标准", "学习提升·做得好的：读完一篇论文"]
    review_kind = next(k for k in wall["kinds"] if k["key"] == "review")
    assert review_kind["label"] == "复盘" and review_kind["builtin"] and review_kind["count"] == 1


def test_review_template_keeps_each_entry_of_an_aspect_as_its_own_line(client):
    _clean()
    r = client.post("/api/notes/review", json={"date": "2026-03-02", "entries": {
        "个人效率·做得好的": ["找到了复盘的节奏", " ", "口播的工作方式"],
        "个人效率·有问题的": ["单篇内容要看 5 分钟", "没想清楚就开工"],
    }}).json()
    assert r["note"]["text"].splitlines() == ["复盘 03-02", "个人效率·做得好的：找到了复盘的节奏", "个人效率·做得好的：口播的工作方式",
                                              "个人效率·有问题的：单篇内容要看 5 分钟", "个人效率·有问题的：没想清楚就开工"]
    assert len(r["issues"]) == 2


def test_review_template_needs_at_least_one_area(client):
    _clean()
    assert client.post("/api/notes/review", json={"entries": {"产品迭代": [" "], "AI协作": [""]}}).status_code == 400
    assert client.get("/api/notes").json()["notes"] == []


def test_review_is_a_builtin_kind_by_name_and_prefix(client):
    _clean()
    assert client.post("/api/notes", json={"text": "选的类型", "kind": "复盘"}).json()["kind"] == "review"
    prefixed = client.post("/api/notes", json={"text": "复盘：写了前缀"}).json()
    assert prefixed["kind"] == "review" and prefixed["title"] == "写了前缀"


def test_deep_read_discussion_becomes_deep_note(client, monkeypatch):
    from app import annotations
    monkeypatch.setattr(annotations, "_answer", lambda *a: None)
    _clean()
    assert {"key": "deep", "label": "深度"} in [{"key": k["key"], "label": k["label"]} for k in client.get("/api/notes/kinds").json()]
    base = {"doc": "learn:item:3", "title": "某论文", "link": "#learn/item/3", "quote": "关键的一段"}
    client.post("/api/annotations", json={**base, "text": "这里的假设站不住", "note_kind": "deep"})
    asked = client.post("/api/annotations", json={**base, "ask": True, "note_kind": "deep"}).json()
    notes = client.get("/api/notes?kind=deep").json()["notes"]
    assert {n["title"] for n in notes} == {"这里的假设站不住", "问 Claude：关键的一段"}
    assert next(n for n in notes if n["title"].startswith("问 Claude"))["sources"][0]["annotation_id"] == asked["id"]


def test_old_deep_read_discussions_backfilled_once(client):
    from app import db
    from app.modules import notes
    _clean()
    db.execute("DELETE FROM note_backfills")
    db.execute("DELETE FROM annotation_msgs")
    db.execute("DELETE FROM annotations")
    def thread(doc, text, at="2026-11-02 10:00:00"):
        aid = db.insert("annotations", {"doc": doc, "title": "T", "link": "#x", "quote": "原句", "created_at": at, "updated_at": at})
        db.insert("annotation_msgs", {"annotation_id": aid, "role": "user", "content": text, "created_at": at})
        db.insert("annotation_msgs", {"annotation_id": aid, "role": "assistant", "content": "答", "created_at": at})
        return aid
    old = thread("learn:chapter:5", "老评论")
    asked = thread("learn:item:5", annotations_default())
    linked = thread("learn:item:5", "已经贴过")
    client.post("/api/notes", json={"text": "已经贴过", "kind": "idea", "sources": [{"doc": "learn:item:5", "annotation_id": linked}]})
    thread("research_doc:1", "调研里的")
    notes.on_startup()
    notes.on_startup()
    got = {n["title"]: n for n in client.get("/api/notes").json()["notes"]}
    assert set(got) == {"老评论", "问 Claude：原句", "已经贴过"}
    assert got["老评论"]["kind"] == "deep" and got["老评论"]["date"] == "2026-11-02" and got["老评论"]["created_at"].startswith("2026-11-02")
    assert got["老评论"]["sources"][0]["annotation_id"] == old
    assert got["问 Claude：原句"]["sources"][0]["annotation_id"] == asked


def annotations_default():
    from app import annotations
    return annotations.DEFAULT_QUESTION


def test_continue_a_note_as_a_thread(client):
    _clean()
    root = client.post("/api/notes", json={"text": "做内容的动效，什么生成方式最合适"}).json()
    a = client.post("/api/notes", json={"text": "先试 Lottie 模板", "thread": root["id"]}).json()
    b = client.post("/api/notes", json={"text": "HyperFrames 更灵活", "thread": a["id"]}).json()  # 续写续写的那条，也挂到线头
    assert a["thread_id"] == root["id"] and b["thread_id"] == root["id"]
    assert client.post("/api/notes", json={"text": "x", "thread": 999999}).status_code == 404
    wall = client.get("/api/notes").json()
    th = wall["threads"]
    assert len(th) == 1 and th[0]["id"] == root["id"] and th[0]["count"] == 3 and th[0]["state"] == "open"
    t = client.get(f"/api/notes/threads/{root['id']}").json()
    assert [n["title"] for n in t["items"]] == ["做内容的动效，什么生成方式最合适", "先试 Lottie 模板", "HyperFrames 更灵活"]
    t = client.patch(f"/api/notes/threads/{root['id']}", json={"state": "clear", "gist": "先 HyperFrames，Lottie 做兜底"}).json()
    assert t["state"] == "clear" and t["gist"] == "先 HyperFrames，Lottie 做兜底"
    assert client.patch(f"/api/notes/threads/{root['id']}", json={"state": "nope"}).status_code == 400
    assert client.get(f"/api/notes/threads/{a['id']}").json()["id"] == root["id"]
    # 删掉线头：最早的续写接任线头，状态和目前想法跟过去
    client.delete(f"/api/notes/{root['id']}")
    t = client.get(f"/api/notes/threads/{a['id']}").json()
    assert t["id"] == a["id"] and [n["id"] for n in t["items"]] == [a["id"], b["id"]] and t["gist"] == "先 HyperFrames，Lottie 做兜底"
    # 线头移回系统记录：同样交给下一条
    client.patch(f"/api/notes/{a['id']}", json={"author": "system"})
    assert client.get(f"/api/notes/threads/{b['id']}").json()["id"] == b["id"]


def test_new_note_suggests_threads_it_may_continue(client):
    _clean()
    root = client.post("/api/notes", json={"text": "做内容的动效，什么生成方式最合适"}).json()
    client.post("/api/notes", json={"text": "周末去爬山"})
    hits = client.get("/api/notes/suggest", params={"text": "动效生成还可以用 Remotion"}).json()
    assert [x["id"] for x in hits] == [root["id"]]
    assert client.get("/api/notes/suggest", params={"text": "买菜"}).json() == []


def test_kb_merges_a_thread_into_one_doc(client):
    from app import kb
    _clean()
    root = client.post("/api/notes", json={"text": "动效生成怎么选"}).json()
    client.post("/api/notes", json={"text": "补充：模板太死板", "thread": root["id"]})
    client.patch(f"/api/notes/threads/{root['id']}", json={"gist": "倾向代码生成"})
    docs = [d for d in kb._notes() if "动效生成怎么选" in d["body"] or "模板太死板" in d["body"]]
    assert len(docs) == 1 and "模板太死板" in docs[0]["body"] and "倾向代码生成" in docs[0]["body"]


def test_agent_summarizes_a_thread_only_when_asked(client, monkeypatch):
    from app import agent
    _clean()
    root = client.post("/api/notes", json={"text": "动效生成怎么选"}).json()
    client.post("/api/notes", json={"text": "模板太死板", "thread": root["id"]})
    seen = []
    monkeypatch.setattr(agent, "run_once", lambda p, **k: seen.append((p, k)) or {"text": "倾向代码生成，模板只做兜底。", "session": "", "engine": "claude", "log": ""})
    t = client.post(f"/api/notes/threads/{root['id']}/summarize").json()
    assert t["gist"] == "倾向代码生成，模板只做兜底。" and "模板太死板" in seen[0][0] and seen[0][1]["readonly"]
