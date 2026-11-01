"""深读的「读」这一侧：文章类条目、信息推荐深读复用条目、旧对话认领、深读事项、追问与感想。"""
from app import db, kb
from app.modules import _reads, learn

from test_learn import _job, fake_submit  # noqa: F401

REPLY = "# 深度解析：LangChain 的新思路\n\n## TL;DR\n- 一\n- 二\n- 三\n\n" + "正文。" * 200


def _loose_chat(url: str, reply: str = REPLY, created: str = "") -> int:
    at = created or db.now()
    sid = db.insert("chat_sessions", {"module": "learn", "ref": "", "engine": "claude", "engine_session": "",
                                      "title": f"深度解析：{url}", "created_at": at, "updated_at": at})
    db.insert("chat_messages", {"session_id": sid, "role": "user", "content": f"深度解析：{url}", "created_at": at})
    db.insert("chat_messages", {"session_id": sid, "role": "assistant", "content": reply, "created_at": at})
    return sid


def test_detect_kind_article():
    assert learn.detect_kind("https://x.com/hwchase17/status/1") == "article"
    assert learn.detect_kind("https://gist.github.com/karpathy/abc") == "article"
    assert learn.detect_kind("https://github.com/karpathy/nanoGPT") == "github"
    assert learn.detect_kind("karpathy/nanoGPT") == "github"
    assert learn.detect_kind("https://arxiv.org/abs/2401.00001") == "paper"
    assert learn.detect_kind("https://example.com/a.pdf") == "paper"


def test_article_item_task_and_reads(client, fake_submit):
    url = "https://x.com/someone/status/42"
    it = client.post("/api/learn/items", json={"url": url, "reuse": True}).json()
    assert it["kind"] == "article" and "note.md" in fake_submit[-1]["prompt"] and "fxtwitter" in fake_submit[-1]["prompt"]
    # 同一链接再点深读：复用条目，不重跑
    n = len(fake_submit)
    assert client.post("/api/learn/items", json={"url": url + "?s=20", "reuse": True}).json()["id"] == it["id"]
    assert len(fake_submit) == n
    t = _reads.task_of(it["id"])
    assert t and t["status"] == "doing" and t["kind"] == "learning"
    out = learn._item_dir(it)
    (out / "note.md").write_text(REPLY, "utf-8")
    learn.on_job_done(_job(fake_submit[-1]["id"], "好了"))
    t = _reads.task_of(it["id"])
    assert t["progress"] == 50 and t["status"] == "doing" and "LangChain" in t["title"]
    # 在条目对话里写感想、追问：事项完成，复盘和知识库里能看到
    ref = _reads.ref_of(it["id"])
    sid = db.insert("chat_sessions", {"module": "learn", "ref": ref, "engine": "claude", "engine_session": "", "title": "t",
                                      "created_at": db.now(), "updated_at": db.now()})
    for text in (f"深度解析：{url}", "这个思路和我做的规划板块很像，值得借鉴", "为什么不用向量库？"):
        db.insert("chat_messages", {"session_id": sid, "role": "user", "content": text, "created_at": db.now()})
    learn.on_chat(ref, "为什么不用向量库？")
    assert _reads.task_of(it["id"])["status"] == "done"
    r = client.get(f"/api/learn/items/{it['id']}/reads").json()
    assert [x["kind"] for x in r["lines"]] == ["thought", "ask"] and r["task"]["status"] == "done"
    day = next(x for x in _reads.day_reads(db.today()) if x["id"] == it["id"])
    assert day["asks"] == 1 and day["thoughts"] == ["这个思路和我做的规划板块很像，值得借鉴"]
    assert any("追问 1 次" in s for s in _reads.day_lines(db.today()))
    sec = _reads.kb_section(it["id"])
    assert "### 感想" in sec and "### 追问" in sec and "深度解析" not in sec
    assert any("值得借鉴" in d["body"] for d in kb.build())


def test_import_loose_chats(client, fake_submit):
    url = "https://x.com/hwchase17/status/999"
    sid = _loose_chat(url)
    short = _loose_chat("https://example.com/short", reply="太短")
    made = learn.import_chat_reads()
    assert len(made) == 1
    it = db.row("SELECT * FROM learn_items WHERE id=?", [made[0]])
    assert it["kind"] == "article" and it["status"] == "done" and it["title"] == "LangChain 的新思路"
    assert it["summary"] == "一\n二\n三" and it["output_path"].endswith("note.md")
    assert client.get(f"/api/learn/items/{it['id']}/file").text.startswith("# 深度解析")
    assert db.row("SELECT ref FROM chat_sessions WHERE id=?", [sid])["ref"] == _reads.ref_of(it["id"])
    assert db.row("SELECT ref FROM chat_sessions WHERE id=?", [short])["ref"] == ""  # 没像样回复的不动
    assert _reads.task_of(it["id"])  # 今天的对话补一条深读事项
    assert learn.import_chat_reads() == []  # 可以反复调用
    # 已有条目：新开的松散对话直接认领过去
    sid2 = _loose_chat(url + "/")
    _reads.bind_chats(it)
    assert db.row("SELECT ref FROM chat_sessions WHERE id=?", [sid2])["ref"] == _reads.ref_of(it["id"])
    assert len(db.rows("SELECT id FROM learn_items WHERE url LIKE ?", [f"%{url[8:]}%"])) == 1
