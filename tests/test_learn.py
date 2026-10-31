"""深度学习板块：不调用真实 LLM，jobs.submit 被替换为假函数。"""
import json

import pytest

from app import db, jobs
from app.modules import learn


@pytest.fixture
def fake_submit(monkeypatch):
    calls = []

    def submit(module, prompt, *, ref="", **kw):
        jid = db.insert("jobs", {"module": module, "ref": ref, "engine": "fake", "prompt": prompt,
                                 "status": "queued", "created_at": db.now()})
        calls.append({"id": jid, "ref": ref, "prompt": prompt, **kw})
        return jid

    monkeypatch.setattr(jobs, "submit", submit)
    return calls


def _job(jid, output, status="done"):
    db.update("jobs", jid, {"status": status, "output": output})
    return db.row("SELECT * FROM jobs WHERE id=?", [jid])


@pytest.mark.parametrize("url,kind", [
    ("https://arxiv.org/abs/2401.12345", "paper"),
    ("https://arxiv.org/pdf/2401.12345v2", "paper"),
    ("https://example.com/paper.pdf", "paper"),
    ("10.1145/3290605.3300857", "paper"),
    ("https://doi.org/10.1038/nature14539", "paper"),
    ("https://github.com/anthropics/claude-code", "github"),
    ("karpathy/nanoGPT", "github"),
])
def test_detect_kind(url, kind):
    assert learn.detect_kind(url) == kind


def test_slugify():
    assert learn.slugify("https://github.com/karpathy/nanoGPT.git") == "karpathy-nanogpt"
    assert learn.slugify("https://arxiv.org/abs/2401.12345v2") == "arxiv-2401.12345"


def test_extract_json_prefers_fenced_and_key():
    text = 'blah {"x": 1} more\n```json\n{"steps": [{"title": "a"}]}\n```\n trailing {"y": {"z": 2}}'
    assert learn.extract_json(text, "steps") == {"steps": [{"title": "a"}]}
    assert learn.extract_json('前言 {"edits": [], "summary": "s"} 结尾', "edits")["summary"] == "s"
    assert learn.extract_json("no json here", "steps") is None


PLAN_OUT = """好的，计划如下：
```json
{"overview_md": "# 世界模型\\n总览",
 "stages": [
  {"stage": 1, "name": "领域综述", "steps": [
    {"title": "读综述", "description": "d", "resources": [{"title": "Survey", "url": "https://arxiv.org/abs/1", "type": "paper", "why": "全景"}, "https://x.org"],
     "questions": ["世界模型解决什么？"], "est_hours": 3}]},
  {"stage": 5, "steps": [{"title": "前沿", "est_hours": "2"}, {"description": "无标题会被丢弃"}]}
 ]}
```"""


def test_plan_generation_and_parse(client, fake_submit):
    p = client.post("/api/learn/plans", json={"topic": "世界模型", "background": "DL", "goal": "复现", "hours_per_week": 6}).json()
    assert p["status"] == "generating" and fake_submit[-1]["ref"] == f"learn:plan:{p['id']}"
    assert "领域综述" in fake_submit[-1]["prompt"]
    learn.on_job_done(_job(fake_submit[-1]["id"], PLAN_OUT))
    p = client.get(f"/api/learn/plans/{p['id']}").json()
    assert p["status"] == "active" and p["overview_md"].startswith("# 世界模型")
    assert [(s["stage"], s["title"]) for s in p["steps"]] == [(1, "读综述"), (5, "前沿")]
    s0 = p["steps"][0]
    assert s0["resources"][0]["url"] == "https://arxiv.org/abs/1" and s0["resources"][1]["url"] == "https://x.org"
    assert s0["questions"] == ["世界模型解决什么？"] and p["steps"][1]["est_hours"] == 2.0
    assert p["progress"]["total"] == 2


def test_plan_bad_output_marks_failed(client, fake_submit):
    p = client.post("/api/learn/plans", json={"topic": "坏输出"}).json()
    learn.on_job_done(_job(fake_submit[-1]["id"], "抱歉，没有 JSON"))
    p = client.get(f"/api/learn/plans/{p['id']}").json()
    assert p["status"] == "failed" and "解析失败" in p["overview_md"]


def test_feedback_adapt_and_today(client, fake_submit):
    p = client.post("/api/learn/plans", json={"topic": "RL"}).json()
    learn.on_job_done(_job(fake_submit[-1]["id"], PLAN_OUT))
    s1, s2 = client.get(f"/api/learn/plans/{p['id']}").json()["steps"]
    r = client.patch(f"/api/learn/steps/{s1['id']}", json={"status": "done", "understanding": 2, "feedback": "公式没懂"}).json()
    assert r["status"] == "done" and r["understanding"] == 2 and r["done_at"]

    client.post(f"/api/learn/plans/{p['id']}/adapt", json={"note": "太难"})
    job = fake_submit[-1]
    assert job["ref"] == f"learn:plan:{p['id']}:adapt" and "公式没懂" in job["prompt"] and f"step_id={s1['id']}" in job["prompt"]
    edits = {"summary": "补前置", "edits": [
        {"op": "add", "after_step_id": s1["id"], "title": "补：基础", "est_hours": 1},
        {"op": "add_resources", "step_id": s1["id"], "resources": [{"title": "易懂博客", "url": "https://b.log"}]},
        {"op": "modify", "step_id": s1["id"], "title": "已完成不应被改"},
        {"op": "skip", "step_id": s2["id"], "reason": "已掌握"},
        {"op": "modify", "step_id": 999999, "title": "不存在"},
        {"op": "bogus"},
    ]}
    learn.on_job_done(_job(job["id"], "```json\n" + json.dumps(edits, ensure_ascii=False) + "\n```"))
    p2 = client.get(f"/api/learn/plans/{p['id']}").json()
    steps = p2["steps"]
    assert [s["title"] for s in steps] == ["读综述", "补：基础", "前沿"]
    assert steps[0]["resources"][-1]["url"] == "https://b.log"
    assert steps[2]["status"] == "skipped" and "已掌握" in steps[2]["notes"]
    assert p2["status"] == "active" and "调整记录" in p2["overview_md"]

    # 手动新增 / 删除步骤
    ns = client.post(f"/api/learn/plans/{p['id']}/steps", json={"stage": 6, "title": "写一篇讲解"}).json()
    assert ns["stage"] == 6
    assert client.delete(f"/api/learn/steps/{ns['id']}").json()["ok"]

    t = client.post(f"/api/learn/steps/{steps[1]['id']}/today", json={}).json()
    assert t["kind"] == "learning" and "补：基础" in t["title"] and t["est_minutes"] == 60
    ctx = learn.agent_context(f"learn:plan:{p['id']}")
    assert f"step_id={steps[1]['id']}" in ctx and "PATCH" in ctx


def test_item_job_done(client, fake_submit):
    it = client.post("/api/learn/items", json={"url": "https://arxiv.org/abs/2401.12345", "focus": "评测"}).json()
    assert it["kind"] == "paper" and it["status"] == "running"
    call = fake_submit[-1]
    assert call["ref"] == f"learn:item:{it['id']}" and "paper-library" in call["prompt"] and "TL;DR" in call["prompt"]
    out = learn._item_dir(it)
    assert out.is_dir() and call["cwd"] == str(out)
    (out / "note.md").write_text("# 论文\n\n## TL;DR\n- 第一行\n- 第二行\n- 第三行\n\n## 动机\n...", "utf-8")
    # 没有 JSON 尾巴时从文件提取 TL;DR
    learn.on_job_done(_job(call["id"], "完成了解读。"))
    it2 = client.get(f"/api/learn/items/{it['id']}").json()
    assert it2["status"] == "done" and it2["output_path"].endswith("note.md")
    assert it2["summary"] == "第一行\n第二行\n第三行"
    assert client.get(f"/api/learn/items/{it['id']}/file").text.startswith("# 论文")
    assert client.patch(f"/api/learn/items/{it['id']}", json={"my_notes": "有用", "rating": 9}).json()["rating"] == 5
    assert "有用" in learn.agent_context(f"learn:item:{it['id']}")


def test_github_item_with_json_meta(client, fake_submit):
    it = client.post("/api/learn/items", json={"url": "https://github.com/karpathy/nanoGPT"}).json()
    assert it["kind"] == "github" and "最小上手实验" in fake_submit[-1]["prompt"]
    out = learn._item_dir(it)
    (out / "index.html").write_text("<html><body>tutorial</body></html>", "utf-8")
    meta = {"title": "nanoGPT", "tldr": ["a", "b", "c"], "output": "index.html"}
    learn.on_job_done(_job(fake_submit[-1]["id"], "done\n```json\n" + json.dumps(meta) + "\n```"))
    it2 = client.get(f"/api/learn/items/{it['id']}").json()
    assert it2["title"] == "nanoGPT" and it2["summary"] == "a\nb\nc" and it2["output_path"].endswith("index.html")
    assert "tutorial" in client.get(f"/api/learn/items/{it['id']}/out/index.html").text
    assert client.get(f"/api/learn/items/{it['id']}/out/..%2F..%2Fapp.db").status_code == 404


def test_item_failed_job(client, fake_submit):
    it = client.post("/api/learn/items", json={"url": "https://example.com/x.pdf"}).json()
    learn.on_job_done(_job(fake_submit[-1]["id"], "", status="failed"))
    assert client.get(f"/api/learn/items/{it['id']}").json()["status"] == "failed"
    assert "深读条目" in learn.agent_context("")


def test_normalize_target_strips_instructions():
    from app.modules.learn import normalize_target
    assert normalize_target("https://github.com/aliyun/ai-agent-handbook 这个加入到深度学习里") == ("https://github.com/aliyun/ai-agent-handbook", "")
    assert normalize_target("深读 2210.03629") == ("https://arxiv.org/abs/2210.03629", "")
    assert normalize_target("https://arxiv.org/abs/2303.11366 重点看反思机制") == ("https://arxiv.org/abs/2303.11366", "重点看反思机制")
    assert normalize_target("https://github.com/a/b.git") == ("https://github.com/a/b", "")


def test_github_defaults_to_quick_read(client, monkeypatch):
    from app.modules import learn
    sent = {}
    monkeypatch.setattr(learn.jobs, "submit", lambda module, prompt, **kw: sent.setdefault("prompt", prompt) and 999)
    it = client.post("/api/learn/items", json={"url": "https://github.com/foo/bar 帮我解析一下"}).json()
    assert it["url"] == "https://github.com/foo/bar" and it["kind"] == "github" and it["depth"] == "quick"
    assert "速读" in sent["prompt"] and "note.md" in sent["prompt"] and "阅读指南" in sent["prompt"]
    sent.clear()
    client.post(f"/api/learn/items/{it['id']}/rerun", json={"depth": "full"})
    assert client.get(f"/api/learn/items/{it['id']}").json()["depth"] == "full"
    assert "github-code-walkthrough" in sent["prompt"] or "代码解读" in sent["prompt"]


TWO_STEPS = '```json\n{"overview_md": "o", "steps": [{"stage": 1, "title": "领域地图", "goal": "能定位新论文"}, {"stage": 3, "title": "读经典"}]}\n```'
QUIZ = {"cards": [{"front": "pass^k 是什么？", "back": "k 次<b>都</b>成功的概率", "tag": "概念"}, {"front": "", "back": "坏卡"}],
        "questions": [
    {"id": "q1", "type": "choice", "q": "哪个是痛点？", "options": ["a", "b", "c", "d"], "answer": 2, "explain": "因为 c", "skill": "痛点识别"},
    {"id": "q2", "type": "short", "dim": "应用", "about": "你最近读的 ReAct", "q": "这篇新论文归哪个方向？", "reference": "规划", "rubric": ["说出方向", "说出痛点"]},
    {"type": "choice", "q": "坏题", "options": ["x"], "answer": 5},
]}


def _plan_with_steps(client, fake_submit):
    p = client.post("/api/learn/plans", json={"topic": "Agent 评测"}).json()
    learn.on_job_done(_job(fake_submit[-1]["id"], TWO_STEPS))
    return client.get(f"/api/learn/plans/{p['id']}").json()


def _write_chapter(client, fake_submit, s, quiz=QUIZ):
    call = fake_submit[-1]
    assert call["ref"] == f"learn:step:{s['id']}:chapter"
    out = learn._step_dir(s)
    (out / "chapter.md").write_text("# 本章\n" + "正文" * 200, "utf-8")
    (out / "quiz.json").write_text(json.dumps(quiz, ensure_ascii=False), "utf-8")
    learn.on_job_done(_job(call["id"], "写完了"))


def test_chapter_quiz_flow(client, fake_submit):
    p = _plan_with_steps(client, fake_submit)
    assert p["stage_goals"]["1"].startswith("建立整体地图")
    s1, s2 = p["steps"]
    assert s1["goal"] == "能定位新论文" and s1["chapter_status"] == ""
    # 打开第一章 → 生成；提示词带阶段目的和能力目标
    assert client.post(f"/api/learn/steps/{s1['id']}/open", json={}).json()["chapter_status"] == "generating"
    assert "建立整体地图" in fake_submit[-1]["prompt"] and "能定位新论文" in fake_submit[-1]["prompt"]
    _write_chapter(client, fake_submit, s1)
    s = client.get(f"/api/learn/steps/{s1['id']}").json()
    assert s["chapter_status"] == "ready" and s["chapter_md"].startswith("# 本章")
    assert [q["id"] for q in s["quiz"]] == ["q1", "q2"]  # 坏题被丢掉
    assert all("answer" not in q and "reference" not in q for q in s["quiz"])  # 交卷前不给答案
    assert s["cards"] == [{"front": "pass^k 是什么？", "back": "k 次<b>都</b>成功的概率", "tag": "概念"}]
    w = learn._step_dir(s) / "widgets"
    w.mkdir(exist_ok=True)
    (w / "passk.html").write_text("<p>slider</p>", "utf-8")
    r = client.get(f"/api/learn/steps/{s1['id']}/out/widgets/passk.html")
    assert "slider" in r.text and r.headers["content-security-policy"] == "sandbox allow-scripts"
    assert client.get(f"/api/learn/steps/{s1['id']}/out/..%2F..%2F..%2Fapp.db").status_code == 404
    # 再次打开 → 预生成下一章
    client.post(f"/api/learn/steps/{s1['id']}/open", json={})
    assert fake_submit[-1]["ref"] == f"learn:step:{s2['id']}:prefetch"
    # 交卷：选择题当场判，简答题交给批改任务
    r = client.post(f"/api/learn/steps/{s1['id']}/quiz", json={"answers": {"q1": 2, "q2": "规划方向，痛点是长程"}}).json()
    assert r["quiz_result"]["status"] == "grading" and r["quiz_result"]["items"]["q1"]["score"] == 1
    assert fake_submit[-1]["ref"] == f"learn:step:{s1['id']}:grade" and "规划方向" in fake_submit[-1]["prompt"]
    assert client.post(f"/api/learn/steps/{s1['id']}/quiz", json={"answers": {}}).status_code == 409
    learn.on_job_done(_job(fake_submit[-1]["id"], '```json\n{"items": [{"id": "q2", "score": 0.5, "feedback": "缺痛点依据"}],'
                                                  ' "summary": "还行", "assessment": {"理解": "方向清楚", "应用": "能落到项目上"},'
                                                  ' "weak_points": ["痛点识别"], "advice": "回看全景图"}\n```'))
    s = client.get(f"/api/learn/steps/{s1['id']}").json()
    qr = s["quiz_result"]
    assert qr["status"] == "graded" and qr["score"] == 75 and qr["passed"] and qr["weak_points"] == ["痛点识别"]
    assert qr["dims"] == {"理解": 100, "应用": 50} and qr["assessment"]["应用"] == "能落到项目上"  # q1 的 skill「痛点识别」归到理解
    assert s["status"] == "done" and s["understanding"] == 4
    assert s["quiz"][0]["answer"] == 2  # 批改后给答案
    assert "测试 75 分" in learn._plan_snapshot(p["id"]) and "痛点识别" in learn.agent_context(f"learn:step:{s1['id']}")
    # 重做
    # 重新生成本章：旧答卷作废、保留上次分数、新题不带答案
    client.post(f"/api/learn/steps/{s1['id']}/open", json={"force": True, "note": "多画图"})
    assert "多画图" in fake_submit[-1]["prompt"] and "dg-tree" in fake_submit[-1]["prompt"]
    _write_chapter(client, fake_submit, s1)
    s = client.get(f"/api/learn/steps/{s1['id']}").json()
    assert s["quiz_result"] == {"attempt": 1, "last_score": 75} and "answer" not in s["quiz"][0]
    assert client.post(f"/api/learn/steps/{s1['id']}/quiz/reset").json()["quiz_result"]["last_score"] == 75
    client.delete(f"/api/learn/plans/{p['id']}")  # 别留下进行中的计划影响其他测试


def test_quiz_choice_only_and_fail(client, fake_submit):
    p = _plan_with_steps(client, fake_submit)
    s1 = p["steps"][0]
    client.post(f"/api/learn/steps/{s1['id']}/open", json={})
    _write_chapter(client, fake_submit, s1, {"questions": QUIZ["questions"][:1]})
    n = len(fake_submit)
    s = client.post(f"/api/learn/steps/{s1['id']}/quiz", json={"answers": {"q1": 0}}).json()
    assert len(fake_submit) == n  # 全是选择题不起批改任务
    assert s["quiz_result"]["score"] == 0 and not s["quiz_result"]["passed"] and s["status"] == "doing"
    client.delete(f"/api/learn/plans/{p['id']}")


def test_chapter_failed_and_grade_failed(client, fake_submit):
    p = _plan_with_steps(client, fake_submit)
    s1 = p["steps"][0]
    client.post(f"/api/learn/steps/{s1['id']}/open", json={})
    learn.on_job_done(_job(fake_submit[-1]["id"], "", status="failed"))
    assert client.get(f"/api/learn/steps/{s1['id']}").json()["chapter_status"] == "failed"
    client.post(f"/api/learn/steps/{s1['id']}/open", json={})  # 失败后再打开会重试
    _write_chapter(client, fake_submit, s1)
    client.post(f"/api/learn/steps/{s1['id']}/quiz", json={"answers": {"q1": 2, "q2": "x"}})
    learn.on_job_done(_job(fake_submit[-1]["id"], "no json"))
    assert client.get(f"/api/learn/steps/{s1['id']}").json()["quiz_result"]["status"] == "failed"
    client.delete(f"/api/learn/plans/{p['id']}")


def test_module_model_only_for_learn(monkeypatch):
    from app import agent, settings
    monkeypatch.setattr(settings, "get", lambda k, d=None: {"module_models": {"learn": "claude-sonnet-5-5"},
                                                             "engines.claude": {"bin": "claude", "model": "opus"}}.get(k, d))
    assert agent.module_model("learn") == "claude-sonnet-5-5"
    assert agent.module_model("plan") == "" and agent.module_model("learn", "codex") == ""
    cmd = agent._claude_cmd("p", "", "", [], agent.module_model("learn"))
    assert cmd[cmd.index("--model") + 1] == "claude-sonnet-5-5"
    cmd = agent._claude_cmd("p", "", "", [], agent.module_model("review"))
    assert cmd[cmd.index("--model") + 1] == "opus"


def test_check_answer_and_review(client, fake_submit):
    p = _plan_with_steps(client, fake_submit)
    s1 = p["steps"][0]
    client.post(f"/api/learn/steps/{s1['id']}/open", json={})
    _write_chapter(client, fake_submit, s1)
    url = f"/api/learn/steps/{s1['id']}/checks/0"
    # 不写判断直接看要点：不起任务
    n = len(fake_submit)
    assert client.post(url, json={"q": "该上线吗？", "points": "看 pass^k"}).json()["status"] == "viewed"
    assert len(fake_submit) == n
    # 写了判断请求点评
    c = client.post(url, json={"q": "该上线吗？", "points": "看 pass^k", "answer": "80% 够了，上线", "review": True}).json()
    assert c["status"] == "reviewing" and fake_submit[-1]["ref"] == f"learn:step:{s1['id']}:check:0"
    assert "80% 够了" in fake_submit[-1]["prompt"] and "看 pass^k" in fake_submit[-1]["prompt"]
    learn.on_job_done(_job(c["job_id"], '```json\n{"covered": [], "missing": ["没看 pass^k"], "off": ["只看 pass@1"],'
                                        ' "extra": [], "better": "先算 pass^3", "score": 0.2}\n```'))
    s = client.get(f"/api/learn/steps/{s1['id']}").json()
    rv = s["checks"]["0"]["review"]
    assert s["checks"]["0"]["status"] == "reviewed" and rv["missing"] == ["没看 pass^k"] and rv["score"] == 0.2
    assert "没看 pass^k" in learn.agent_context(f"learn:step:{s1['id']}")
    # 答案没改再保存：保留点评；重新生成章节：作答清空
    assert client.post(url, json={"q": "该上线吗？", "answer": "80% 够了，上线"}).json()["review"]["score"] == 0.2
    client.post(f"/api/learn/steps/{s1['id']}/open", json={"force": True})
    _write_chapter(client, fake_submit, s1)
    assert client.get(f"/api/learn/steps/{s1['id']}").json()["checks"] == {}
    client.delete(f"/api/learn/plans/{p['id']}")


def test_quiz_limits_and_recent_context(client, fake_submit, monkeypatch):
    qs = [{"type": "short", "q": f"简答{i}", "reference": "r"} for i in range(4)] + \
         [{"type": "choice", "q": f"选择{i}", "options": ["a", "b"], "answer": 0, "skill": "证据评估"} for i in range(6)]
    out = learn._clean_quiz({"questions": qs})
    assert len(out) == 6 and sum(q["type"] == "short" for q in out) == 2
    assert {q["dim"] for q in out if q["type"] == "choice"} == {"判断"}
    # 出章节时带上最近在读 / 在做的东西
    db.insert("tasks", {"date": db.today(), "title": "给自己的 Agent 搭评测集", "kind": "work"})
    it = client.post("/api/learn/items", json={"url": "https://arxiv.org/abs/2210.03629"}).json()
    db.update("learn_items", it["id"], {"status": "done", "title": "ReAct", "summary": "推理与行动交替"})
    ctx = learn._recent_context()
    assert "ReAct" in ctx and "给自己的 Agent 搭评测集" in ctx
    p = _plan_with_steps(client, fake_submit)
    client.post(f"/api/learn/steps/{p['steps'][0]['id']}/open", json={})
    assert "学以致用" in fake_submit[-1]["prompt"] and "ReAct" in fake_submit[-1]["prompt"]
    client.delete(f"/api/learn/plans/{p['id']}")
