"""学习习惯三项：停一下四栏格式与统计、学完当天用到项目、每日论文笔记。"""
from app import db, kb
from app.modules import _habits, learn

from test_learn import _job, _plan_with_steps, _write_chapter, fake_submit  # noqa: F401


def test_check_parts_and_stats(client, fake_submit):
    p = _plan_with_steps(client, fake_submit)
    s1 = p["steps"][0]
    client.post(f"/api/learn/steps/{s1['id']}/open", json={})
    _write_chapter(client, fake_submit, s1)
    url = f"/api/learn/steps/{s1['id']}/checks/0"
    parts = {"结论": "先别上线", "机制": "pass^k 随 k 指数下降", "例子": "0.8^3≈0.5", "应用": "给讲解评估加三次重跑"}
    c = client.post(url, json={"q": "该上线吗？", "points": "看 pass^k", "parts": parts, "review": True}).json()
    assert c["parts"] == parts and c["answer"].startswith("结论：先别上线\n机制：")
    prompt = fake_submit[-1]["prompt"]
    assert "机制" in prompt and '"parts"' in prompt
    learn.on_job_done(_job(c["job_id"], '```json\n{"covered": ["先别上线"], "missing": [], "better": "b", "score": 0.8,'
                                        ' "parts": {"结论": 1, "机制": 0.9, "例子": 0.4, "应用": 2}}\n```'))
    rv = client.get(f"/api/learn/steps/{s1['id']}").json()["checks"]["0"]["review"]
    assert rv["parts"] == {"结论": 1.0, "机制": 0.9, "例子": 0.4, "应用": 1.0}  # 夹到 0–1
    k = client.get(f"/api/learn/plans/{p['id']}/growth").json()["checks"]
    assert k["target"] == 65 and k["recent_avg"] == 80 and k["weakest"] == "例子"
    # 老格式（只有 answer）照样能交
    old = client.post(f"/api/learn/steps/{s1['id']}/checks/1", json={"q": "q", "answer": "一句话"}).json()
    assert old["answer"] == "一句话" and not old.get("parts")
    assert client.get("/api/learn/habits").json()["check"]["recent_n"] >= 1
    client.delete(f"/api/learn/plans/{p['id']}")


def test_apply_record_and_status(client, fake_submit):
    p = _plan_with_steps(client, fake_submit)
    s1 = p["steps"][0]
    sid = s1["id"]
    client.post(f"/api/learn/steps/{sid}/open", json={})
    _write_chapter(client, fake_submit, s1)
    info = client.get(f"/api/learn/steps/{sid}/apply").json()
    assert f"《{s1['title']}》" in info["prompt"] and "pass^k 是什么？" in info["prompt"]
    assert s1["title"] in info["terms"] and f"step-{sid}" in info["terms"]
    assert info["today"] is None  # 今天还没学完
    client.patch(f"/api/learn/steps/{sid}", json={"status": "done"})
    st = _habits.apply_status(db.today())
    row = next(x for x in st["learned"] if x["step_id"] == sid)
    assert not row["applied"]
    assert client.post(f"/api/learn/steps/{sid}/apply", json={"what": " "}).status_code == 400
    client.post(f"/api/learn/steps/{sid}/apply", json={"project": "self_startup", "what": "讲解评估改成二元评判", "evidence": "abc123"})
    info = client.get(f"/api/learn/steps/{sid}/apply").json()
    assert info["today"]["applied"] and info["today"]["refs"][0]["kind"] == "manual"
    assert info["records"][0]["project"] == "self_startup"
    h = client.get("/api/learn/habits").json()["apply"]
    assert h["applied"] >= 1 and h["total"] >= 1
    assert any("学完当天用到项目" in x for x in _habits.lines(db.today()))
    client.delete(f"/api/learn/plans/{p['id']}")


def test_chapter_terms_and_hit():
    s = {"id": 7, "title": "错误分析：二元评判与 TPR/TNR", "cards": '[{"front": "二元评判为什么好"}, {"front": "短"}]'}
    strong, weak = m = _habits.chapter_match(s)
    assert strong == ["错误分析：二元评判与 TPR/TNR", "step-7", "二元评判为什么好"] and "错误分析" in weak
    assert _habits._hit("改了 二元评判为什么好 那一段", m) == "二元评判为什么好"
    # 章名片段太泛：只出现一个不算，两个不同片段同时出现才算
    assert _habits._hit("今天给讲解评估做了错误分析", m) == ""
    assert _habits._hit("错误分析之后把二元评判与 TPR 一起算", m) == "错误分析 + 二元评判与 TPR"
    assert _habits._generated("/x/repo", "output/run1/diagnostics/recall_prompt.md")
    assert not _habits._generated("/x/repo", "docs/eval.md")


def test_paper_task_and_verdict_note(client):
    today = db.today()
    t = _habits.ensure_paper_task(today)
    assert t and _habits.PAPER_TAG in t["notes"] and t["est_minutes"] == 30
    assert _habits.ensure_paper_task(today)["id"] == t["id"]  # 不重复加
    assert _habits.ensure_paper_task("2000-01-01") is None   # 只给今天加
    client.get(f"/api/plan/day?date={today}")
    assert len(db.rows("SELECT id FROM tasks WHERE date=? AND notes LIKE ?", [today, f"%{_habits.PAPER_TAG}%"])) == 1
    base = _habits.paper_status(today)["count"]  # 前面的用例可能留下了当天读过的论文深读
    assert not _habits.paper_status(today)["kb_path"]

    db.insert("feed_items", {"id": "arxiv:hab1", "source": "arxiv", "type": "paper", "title": "A Habit Paper", "summary": "s",
                             "url": "https://arxiv.org/abs/2610.00001", "date": today, "popularity": 1, "extra": "{}",
                             "fetched_at": db.now()})
    assert client.post("/api/feed/verdict", json={"id": "nope", "text": "x"}).status_code == 404
    r = client.post("/api/feed/verdict", json={"id": "arxiv:hab1", "text": "增量小，评测只有一个数据集，不跟"}).json()
    assert r["verdict"].startswith("增量小") and r["verdict_at"][:10] == today
    ps = _habits.paper_status(today)
    assert ps["done"] and ps["count"] == base + 1 and ps["kb_path"] == f"learn/paper-notes/{today}.md"
    assert db.row("SELECT status FROM tasks WHERE id=?", [t["id"]])["status"] == "done"
    docs = {d["path"]: d for d in kb.build()}
    assert "增量小" in docs[f"learn/paper-notes/{today}.md"]["body"]
    # 推荐列表里带上判断；清空 = 删除
    items = client.get("/api/feed/items?type=paper&limit=200").json()["items"]
    assert next(x for x in items if x["id"] == "arxiv:hab1")["feedback"]["verdict"].startswith("增量小")
    client.post("/api/feed/verdict", json={"id": "arxiv:hab1", "text": ""})
    assert _habits.paper_status(today)["count"] == base and not _habits.paper_status(today)["kb_path"]
