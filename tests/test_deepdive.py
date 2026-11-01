"""GitHub 项目 Deep Dive：理解 → 实验 → 写作 → 审稿四阶段串行，每阶段校验、失败停在该阶段可重试、历史版本保留、进知识库。
不调用真实 LLM。"""
import json

import pytest

from app import db, jobs, kb
from app.modules import _deepdive, learn

SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 50"><text x="5" y="20">图</text></svg>'


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


def _understanding(dd):
    ds = "".join(f"### D{i} 设计{i}\n矛盾、朴素做法 A / B、选择、类比、样例、代价。" + "说明。" * 200 + "\n" for i in (1, 2, 3))
    (dd / "understanding.md").write_text(
        "## 0 资料来源\n- 作者设计文章\n## 2 动机链\n" + "痛点。" * 600 + "\n## 4 术语表\n- Trigger：事件\n## 5 设计决定\n" + ds
        + "## 6 可检验主张\n- C1 双层更快\n- C2 批处理摊薄\n", "utf-8")


def _experiments(dd, n=3, compare=2, figs=True):
    exps = []
    for i in range(1, n + 1):
        d = dd / "lab" / f"E{i}-x"
        d.mkdir(parents=True, exist_ok=True)
        (d / "out.txt").write_text(f"ok {i} passed\n", "utf-8")
        fig = f"figs/exp-E{i}.svg"
        if figs:
            (dd / "figs").mkdir(exist_ok=True)
            (dd / fig).write_text(SVG, "utf-8")
        exps.append({"id": f"E{i}", "title": f"实验{i}", "type": "对照" if i <= compare else "边界", "claim": "C1", "runs": 3,
                     "cmd": "node run.js", "out": f"lab/E{i}-x/out.txt", "fig": fig, "exit_code": 0, "verdict": "证实",
                     "finding": f"结论{i}"})
    (dd / "lab" / "experiments.json").write_text(json.dumps({"repo_commit": "abc", "experiments": exps}), "utf-8")
    (dd / "results.md").write_text("## E1\n" + "解读。" * 800, "utf-8")


def _article(dd, n_figs=6, bullets=False):
    (dd / "figs").mkdir(exist_ok=True)
    figs = ""
    for i in range(n_figs):
        (dd / "figs" / f"c{i}.svg").write_text(SVG, "utf-8")
        figs += f"![图{i}](figs/c{i}.svg)\n\n"
    para = ("- 要点。\n" * 400) if bullets else ("这一段讲清设计为什么这样做。" * 60 + "\n\n") * 15
    (dd / "deepdive.md").write_text("# Proto Deep Dive：事件驱动\n\n## TL;DR\n- 甲\n- 乙\n- 丙\n\n## 1 问题\n" + para + figs
                                    + "## 实验\nE1、E2、E3 的结果。\n", "utf-8")


def _review(dd):
    (dd / "review.json").write_text(json.dumps({
        "before": {k: {"score": 2, "issues": ["x"]} for k in _deepdive.RUBRIC}, "fixes": ["补了动机"],
        "after": {k: {"score": 4, "note": "ok"} for k in _deepdive.RUBRIC}}), "utf-8")


def _stage(fake_submit):
    return fake_submit[-1]["ref"].rsplit(":", 1)[-1]


def test_deepdive_stages_chain_to_done(client, fake_submit):
    it = _repo_item(client, fake_submit)
    n = len(fake_submit)
    d = client.get(f"/api/learn/items/{it['id']}/deepdive").json()
    assert d["status"] == "" and not d["ready"] and len(fake_submit) == n   # 不点不生成
    d = client.post(f"/api/learn/items/{it['id']}/deepdive").json()
    call = fake_submit[-1]
    assert d["status"] == "running" and d["stage"] == "understand" and call["ref"] == f"learn:item:{it['id']}:deepdive:understand"
    dd = _deepdive.dd_dir(learn._item_dir(it))
    assert call["cwd"] == str(dd) and (dd / "lab").is_dir()
    # 理解阶段：要去找作者的设计文章，建立动机链 / 术语 / trade-off / 可检验主张
    for kw in ("git clone", "设计文章", "WebSearch", "动机链", "术语表", "### D<n>", "朴素做法", "类比", "可检验主张", it["url"]):
        assert kw in call["prompt"], kw
    # 生成中重复点：不再提交新任务
    assert client.post(f"/api/learn/items/{it['id']}/deepdive").json()["job_id"] == call["id"] and fake_submit[-1] is call

    _understanding(dd)
    learn.on_job_done(_job(call["id"], '```json\n{"stage": "understand"}\n```'))
    assert _stage(fake_submit) == "experiment"
    for kw in ("对照", "消融", "扫描", "figs/exp-E<n>.svg", "results.md", "@ARGV' 180", "时间预算", "合计 ≤ 20 分钟", "experiments.json"):
        assert kw in fake_submit[-1]["prompt"], kw

    _experiments(dd)
    learn.on_job_done(_job(fake_submit[-1]["id"]))
    assert _stage(fake_submit) == "write"
    for kw in ("叙事", "机制示意图", "首次出现", "对比图", "figs/arch.svg", "开放问题"):
        assert kw in fake_submit[-1]["prompt"], kw
    assert client.get(f"/api/learn/items/{it['id']}/deepdive").json()["stage"] == "write"

    _article(dd)
    learn.on_job_done(_job(fake_submit[-1]["id"], '```json\n{"stage": "write", "title": "Proto Deep Dive"}\n```'))
    assert _stage(fake_submit) == "review"
    assert "deepdive.draft.md" in fake_submit[-1]["prompt"] and "R10" in fake_submit[-1]["prompt"]

    _review(dd)
    learn.on_job_done(_job(fake_submit[-1]["id"], '```json\n{"stage": "review", "title": "Proto Deep Dive：事件驱动"}\n```'))
    d = client.get(f"/api/learn/items/{it['id']}/deepdive").json()
    assert d["status"] == "done" and d["ready"] and d["title"] == "Proto Deep Dive：事件驱动" and d["error"] == ""
    assert [x["id"] for x in d["experiments"]] == ["E1", "E2", "E3"] and d["experiments"][0]["claim"] == "C1"
    assert d["review"]["R1"] == {"name": "动机链", "before": 2, "after": 4}
    assert client.get(f"/api/learn/items/{it['id']}/deepdive/file").text.startswith("# Proto Deep Dive")
    assert "ok 1" in client.get(f"/api/learn/items/{it['id']}/out/deepdive/lab/E1-x/out.txt").text
    assert "deepdive.md" in learn.agent_context(f"learn:item:{it['id']}")

    # 同步进本地知识库：单独一篇，带 TL;DR 和正文
    docs = [x for x in kb._learn_items() if x["id"] == f"repo:{it['id']}-deepdive"]
    assert docs and "deepdive" in docs[0]["tags"] and docs[0]["summary"].startswith("甲") and "设计为什么" in docs[0]["text"]

    # 重新生成：上一版挪进 history，正文另存为历史版本（图片链接改指 history），不覆盖
    client.post(f"/api/learn/items/{it['id']}/deepdive")
    d = client.get(f"/api/learn/items/{it['id']}/deepdive").json()
    assert d["status"] == "running" and d["stage"] == "understand" and not d["ready"] and len(d["versions"]) == 1
    assert d["experiments"] == [] and not (dd / "understanding.md").exists() and (dd / "lab").is_dir()
    old = client.get(f"/api/learn/items/{it['id']}/deepdive/file", params={"version": d["versions"][0]}).text
    ts = d["versions"][0][len("deepdive."):-len(".md")]
    assert old.startswith("# Proto Deep Dive") and f"](history/{ts}/figs/c0.svg)" in old
    hist = dd / "history" / ts
    assert (hist / "figs" / "c0.svg").is_file() and (hist / "lab" / "E1-x" / "out.txt").is_file() and (hist / "review.json").is_file()
    assert client.get(f"/api/learn/items/{it['id']}/deepdive/file", params={"version": "../../app.db"}).status_code == 404


def test_stage_failure_stops_and_resumes(client, fake_submit):
    it = _repo_item(client, fake_submit, "https://github.com/acme/no-exp")
    client.post(f"/api/learn/items/{it['id']}/deepdive")
    dd = _deepdive.dd_dir(learn._item_dir(it))
    _understanding(dd)
    learn.on_job_done(_job(fake_submit[-1]["id"]))
    _experiments(dd, n=4, compare=1)                       # 只有 1 个对照类实验：打不到设计主张
    n = len(fake_submit)
    learn.on_job_done(_job(fake_submit[-1]["id"]))
    d = client.get(f"/api/learn/items/{it['id']}/deepdive").json()
    assert d["status"] == "failed" and d["stage"] == "experiment" and "对照" in d["error"] and "「实验」阶段" in d["error"]
    assert len(fake_submit) == n                           # 不往下串
    # 从失败的阶段重试：理解阶段的产物保留，不重新跑
    d = client.post(f"/api/learn/items/{it['id']}/deepdive", params={"resume": True}).json()
    assert d["status"] == "running" and d["stage"] == "experiment" and _stage(fake_submit) == "experiment"
    assert (dd / "understanding.md").is_file()


def test_stage_job_failure_reason(client, fake_submit):
    it = _repo_item(client, fake_submit, "https://github.com/acme/boom")
    client.post(f"/api/learn/items/{it['id']}/deepdive")
    learn.on_job_done(_job(fake_submit[-1]["id"], "", status="failed", log="[tool] Bash: git clone\n[error] rate limited"))
    d = client.get(f"/api/learn/items/{it['id']}/deepdive").json()
    assert d["status"] == "failed" and d["stage"] == "understand" and "rate limited" in d["error"]


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


def test_check_understand(tmp_path):
    dd = tmp_path / "deepdive"
    dd.mkdir()
    assert not _deepdive.check_stage("understand", dd)[0]
    _understanding(dd)
    assert _deepdive.check_stage("understand", dd) == (True, "")
    (dd / "understanding.md").write_text((dd / "understanding.md").read_text().replace("### D3", "D3"))
    ok, why = _deepdive.check_stage("understand", dd)
    assert not ok and "设计决定只有 2 个" in why


def test_check_experiment_needs_figs(tmp_path):
    dd = tmp_path / "deepdive"
    (dd / "lab").mkdir(parents=True)
    _experiments(dd, figs=False)
    ok, why = _deepdive.check_stage("experiment", dd)
    assert not ok and "数据图" in why
    _experiments(dd)
    assert _deepdive.check_stage("experiment", dd) == (True, "")
    (dd / "figs" / "exp-E1.svg").write_text("<svg><text>A & B</text></svg>")   # 未转义的 & 解析失败
    assert not _deepdive.check_stage("experiment", dd)[0]


def test_check_article(tmp_path):
    dd = tmp_path / "deepdive"
    (dd / "lab").mkdir(parents=True)
    _experiments(dd)
    _article(dd, n_figs=3)
    ok, why = _deepdive.check_stage("write", dd)
    assert not ok and "只有 3 张" in why
    _article(dd, bullets=True)
    assert not _deepdive.check_stage("write", dd)[0]
    _article(dd)
    assert _deepdive.check_stage("write", dd) == (True, "")
    ok, why = _deepdive.check_stage("review", dd)
    assert not ok and "review.json" in why
    _review(dd)
    assert _deepdive.check_stage("review", dd) == (True, "")


def test_experiments_reject_paths_outside(tmp_path):
    dd = tmp_path / "deepdive"
    (dd / "lab").mkdir(parents=True)
    (tmp_path / "secret.txt").write_text("x")
    (dd / "lab" / "experiments.json").write_text(json.dumps({"experiments": [{"id": "E1", "out": "../secret.txt"}]}))
    assert _deepdive.experiments(dd) == []
