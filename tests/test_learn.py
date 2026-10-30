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
