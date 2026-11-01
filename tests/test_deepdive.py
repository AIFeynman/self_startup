"""GitHub 项目 Deep Dive：按需生成、校验真实实验输出、失败原因、历史版本保留、进知识库。不调用真实 LLM。"""
import json

import pytest

from app import db, jobs, kb
from app.modules import _deepdive, learn


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


def _job(jid, output="", status="done", log=""):
    db.update("jobs", jid, {"status": status, "output": output, "log": log})
    return db.row("SELECT * FROM jobs WHERE id=?", [jid])


def _repo_item(client, fake_submit, url="https://github.com/acme/agent-proto"):
    it = client.post("/api/learn/items", json={"url": url}).json()
    learn.on_job_done(_job(fake_submit[-1]["id"], "done"))   # 深读本身先结束（没有产物也无妨）
    return it


def _write_result(dd, n_exp=3, n_out=None, md="# Proto Deep Dive：事件驱动\n\n## TL;DR\n- 甲\n- 乙\n- 丙\n\n" + "正文。" * 300):
    (dd / "deepdive.md").write_text(md, "utf-8")
    exps = []
    for i in range(1, n_exp + 1):
        d = dd / "lab" / f"E{i}-x"
        d.mkdir(parents=True, exist_ok=True)
        if i <= (n_exp if n_out is None else n_out):
            (d / "out.txt").write_text(f"ok {i} passed\n", "utf-8")
        exps.append({"id": f"E{i}", "title": f"实验{i}", "type": "自写测试", "cmd": "pnpm test", "out": f"lab/E{i}-x/out.txt",
                     "exit_code": 0, "verdict": "证实", "finding": f"结论{i}"})
    (dd / "lab" / "experiments.json").write_text(json.dumps({"repo_commit": "abc", "experiments": exps}), "utf-8")


def test_deepdive_on_demand_and_done(client, fake_submit):
    it = _repo_item(client, fake_submit)
    n = len(fake_submit)
    d = client.get(f"/api/learn/items/{it['id']}/deepdive").json()
    assert d["status"] == "" and not d["ready"] and len(fake_submit) == n   # 不点不生成
    d = client.post(f"/api/learn/items/{it['id']}/deepdive").json()
    call = fake_submit[-1]
    assert d["status"] == "running" and call["ref"] == f"learn:item:{it['id']}:deepdive"
    dd = _deepdive.dd_dir(learn._item_dir(it))
    assert call["cwd"] == str(dd) and (dd / "lab").is_dir()
    # 提示词要求真实动手：克隆、自写测试、消融、边界、原样输出、实验清单
    for kw in ("git clone", "自己写的测试", "消融", "边界", "out.txt", "experiments.json", "@ARGV' 180", "时间预算",
               "合计 ≤ 20 分钟", it["url"]):
        assert kw in call["prompt"], kw
    # 生成中重复点：不再提交新任务
    assert client.post(f"/api/learn/items/{it['id']}/deepdive").json()["job_id"] == call["id"] and fake_submit[-1] is call

    _write_result(dd)
    meta = {"title": "Proto Deep Dive", "tldr": ["a", "b", "c"], "experiments": 3, "output": "deepdive.md"}
    learn.on_job_done(_job(call["id"], "```json\n" + json.dumps(meta) + "\n```"))
    d = client.get(f"/api/learn/items/{it['id']}/deepdive").json()
    assert d["status"] == "done" and d["ready"] and d["title"] == "Proto Deep Dive" and d["error"] == ""
    assert [x["id"] for x in d["experiments"]] == ["E1", "E2", "E3"] and d["experiments"][0]["finding"] == "结论1"
    assert client.get(f"/api/learn/items/{it['id']}/deepdive/file").text.startswith("# Proto Deep Dive")
    assert "ok 1" in client.get(f"/api/learn/items/{it['id']}/out/deepdive/lab/E1-x/out.txt").text
    assert "deepdive.md" in learn.agent_context(f"learn:item:{it['id']}")

    # 同步进本地知识库：单独一篇，带 TL;DR 和正文
    docs = [x for x in kb._learn_items() if x["id"] == f"repo:{it['id']}-deepdive"]
    assert docs and "deepdive" in docs[0]["tags"] and docs[0]["summary"].startswith("甲") and "正文。" in docs[0]["text"]

    # 重新生成：旧版正文保留为历史版本，不覆盖
    client.post(f"/api/learn/items/{it['id']}/deepdive")
    d = client.get(f"/api/learn/items/{it['id']}/deepdive").json()
    assert d["status"] == "running" and not d["ready"] and len(d["versions"]) == 1
    old = client.get(f"/api/learn/items/{it['id']}/deepdive/file", params={"version": d["versions"][0]})
    assert old.text.startswith("# Proto Deep Dive")
    assert client.get(f"/api/learn/items/{it['id']}/deepdive/file", params={"version": "../../app.db"}).status_code == 404


def test_deepdive_without_real_experiments_fails(client, fake_submit):
    it = _repo_item(client, fake_submit, "https://github.com/acme/no-exp")
    client.post(f"/api/learn/items/{it['id']}/deepdive")
    dd = _deepdive.dd_dir(learn._item_dir(it))
    _write_result(dd, n_exp=4, n_out=2)   # 清单写了 4 个，只有 2 个真有输出
    learn.on_job_done(_job(fake_submit[-1]["id"], "写完了"))
    d = client.get(f"/api/learn/items/{it['id']}/deepdive").json()
    assert d["status"] == "failed" and "只有 2 个" in d["error"] and d["ready"]
    assert not [x for x in kb._learn_items() if x["id"] == f"repo:{it['id']}-deepdive"]


def test_deepdive_job_failure_reason(client, fake_submit):
    it = _repo_item(client, fake_submit, "https://github.com/acme/boom")
    client.post(f"/api/learn/items/{it['id']}/deepdive")
    learn.on_job_done(_job(fake_submit[-1]["id"], "", status="failed", log="[tool] Bash: git clone\n[error] rate limited"))
    d = client.get(f"/api/learn/items/{it['id']}/deepdive").json()
    assert d["status"] == "failed" and "rate limited" in d["error"]


def test_deepdive_stale_job_ignored(client, fake_submit):
    it = _repo_item(client, fake_submit, "https://github.com/acme/stale")
    client.post(f"/api/learn/items/{it['id']}/deepdive")
    first = fake_submit[-1]["id"]
    db.update("jobs", first, {"status": "failed"})          # 第一个任务挂了，用户重试
    client.post(f"/api/learn/items/{it['id']}/deepdive")
    assert fake_submit[-1]["id"] != first
    learn.on_job_done(_job(first, "", status="failed"))     # 老任务的回调晚到，不改新任务的状态
    assert client.get(f"/api/learn/items/{it['id']}/deepdive").json()["status"] == "running"


def test_deepdive_only_for_github(client, fake_submit):
    it = client.post("/api/learn/items", json={"url": "https://arxiv.org/abs/2401.00001"}).json()
    assert client.post(f"/api/learn/items/{it['id']}/deepdive").status_code == 400


def test_experiments_reject_paths_outside(tmp_path):
    dd = tmp_path / "deepdive"
    (dd / "lab").mkdir(parents=True)
    (tmp_path / "secret.txt").write_text("x")
    (dd / "lab" / "experiments.json").write_text(json.dumps({"experiments": [{"id": "E1", "out": "../secret.txt"}]}))
    assert _deepdive.experiments(dd) == []
