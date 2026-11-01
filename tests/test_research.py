"""调研板块：不调用真实 LLM / GrokBot / Muse（jobs.submit、subprocess、线程全部替换）。"""
import json
import os
import subprocess
from pathlib import Path

import pytest

from app.modules import research as R


class FakeProc:
    def __init__(self, rc=0, out=""):
        self.returncode, self.stdout, self.stderr = rc, out, ""


@pytest.fixture
def fakes(monkeypatch, client):
    submitted, calls = [], []

    def fake_submit(module, prompt, *, ref="", engine="", **kw):
        submitted.append({"module": module, "prompt": prompt, "ref": ref, "engine": engine})
        return 1000 + len(submitted)

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return FakeProc()

    monkeypatch.setattr(R.jobs, "submit", fake_submit)
    monkeypatch.setattr(R.subprocess, "run", fake_run)
    monkeypatch.setattr(R, "_spawn", lambda fn, *a: fn(*a))  # 线程改同步
    monkeypatch.setattr(R.subprocess, "Popen", lambda cmd, **kw: calls.append(cmd) or type("P", (), {"pid": os.getpid()})())
    return submitted, calls


def test_create_and_job_done(client, fakes):
    submitted, _ = fakes
    r = client.post("/api/research", json={"topic": "向量数据库", "angles": ["技术原理", "关键玩家与竞品"],
                                           "engines": ["claude", "codex"], "context": "我在做 RAG"}).json()
    assert r["status"] == "running" and len(r["results"]) == 2
    assert {s["engine"] for s in submitted} == {"claude", "codex"}
    assert "技术原理" in submitted[0]["prompt"] and "来源" in submitted[0]["prompt"]

    res = r["results"][0]
    R.on_job_done({"ref": f"research:{r['id']}:r{res['id']}", "status": "done", "output": "## 结论\n内容A", "engine": "claude"})
    r2 = client.get(f"/api/research/{r['id']}").json()
    assert r2["results"][0]["status"] == "done" and r2["status"] == "running"
    R.on_job_done({"ref": f"research:{r['id']}:r{r['results'][1]['id']}", "status": "failed", "output": "", "log": "boom", "engine": "codex"})
    r3 = client.get(f"/api/research/{r['id']}").json()
    assert r3["status"] == "done"
    text = Path(r3["doc_path"]).read_text("utf-8")
    assert "向量数据库" in text and "内容A" in text and Path(r3["doc_path"]).name.startswith(f"{r['id']}-")

    # 综合
    j = client.post(f"/api/research/{r['id']}/synthesize").json()
    assert submitted[-1]["ref"] == f"research:{r['id']}:synth" and "内容A" in submitted[-1]["prompt"]
    R.on_job_done({"ref": f"research:{r['id']}:synth", "status": "done", "output": "综合文档X"})
    r4 = client.get(f"/api/research/{r['id']}").json()
    assert j["job_id"] and r4["synth_status"] == "done" and "综合文档X" in Path(r4["doc_path"]).read_text("utf-8")

    # 文档库检索 + agent_context
    docs = client.get("/api/research/docs", params={"q": "综合文档X"}).json()
    assert docs and docs[0]["research_id"] == r["id"]
    assert client.get("/api/research/docs", params={"tag": "技术原理"}).json()
    assert "向量数据库" in R.agent_context(f"research:{r['id']}") and "内容A" in R.agent_context(f"research:{r['id']}")
    assert "向量数据库" in R.agent_context("")

    # 删除文档 → 连同调研
    client.delete(f"/api/research/docs/{docs[0]['id']}")
    assert client.get(f"/api/research/{r['id']}").status_code == 404
    assert not Path(r4["doc_path"]).exists()


def test_muse_auto(client, fakes):
    _, calls = fakes
    r = client.post("/api/research", json={"topic": "Muse 自动", "engines": ["muse"]}).json()
    res = r["results"][0]
    assert res["status"] == "running" and res["request_id"] == f"pid:{os.getpid()}"
    assert any(c[-2:] == ["app.muse_bot", str(res["id"])] for c in calls)
    # 进程不在了 → 打开详情时收尾成待粘贴，可重试
    R.db.update("research_results", res["id"], {"request_id": "pid:999999"})
    r2 = client.get(f"/api/research/{r['id']}").json()
    assert r2["results"][0]["status"] == "awaiting_paste" and "意外退出" in r2["results"][0]["error"]
    assert client.post(f"/api/research/results/{res['id']}/muse_auto").json()["status"] == "running"


def test_muse_paste(client, fakes, monkeypatch):
    _, calls = fakes
    real_get = R.settings.get
    monkeypatch.setattr(R.settings, "get", lambda k, d=None: "web" if k == "engines.muse.mode" else real_get(k, d))
    r = client.post("/api/research", json={"topic": "Muse 测试", "engines": ["muse"]}).json()
    res = r["results"][0]
    assert res["status"] == "awaiting_paste" and r["status"] == "awaiting_paste" and "Muse 测试" in res["brief"]
    assert ["pbcopy"] in calls and ["open", "https://muse.ai"] in calls
    assert client.post(f"/api/research/results/{res['id']}/paste", json={"content": "Muse 的回答"}).json()["status"] == "done"
    r2 = client.get(f"/api/research/{r['id']}").json()
    assert r2["status"] == "done" and "Muse 的回答" in Path(r2["doc_path"]).read_text("utf-8")


def test_grokbot_unconfigured(client, fakes, monkeypatch, tmp_path):
    script = tmp_path / "grokbot.py"
    script.write_text("")
    monkeypatch.setattr(R, "_grok_script", lambda: str(script))
    seen = []

    def fake_run(cmd, **kw):
        seen.append(cmd)
        assert "send" not in cmd, "未配置时绝不能发送"
        return FakeProc(0, json.dumps({"configured": {"GROKBOT_WEBHOOK_URL": False, "GROKBOT_WEBHOOK_SECRET": False}}))

    monkeypatch.setattr(R.subprocess, "run", fake_run)
    r = client.post("/api/research", json={"topic": "X 上怎么评价 Claude Code", "engines": ["grokbot"]}).json()
    res = client.get(f"/api/research/results/{r['results'][0]['id']}").json()
    assert res["status"] == "failed" and "setup" in res["error"] and seen[0][-1] == "status"


def test_grokbot_send_and_wait(client, fakes, monkeypatch, tmp_path):
    script = tmp_path / "grokbot.py"
    script.write_text("")
    monkeypatch.setattr(R, "_grok_script", lambda: str(script))
    seen = []

    def fake_run(cmd, **kw):
        seen.append(cmd[2])
        if cmd[2] == "status":
            return FakeProc(0, json.dumps({"configured": {"A": True, "B": True}}))
        if cmd[2] == "send":
            return FakeProc(2, '{"status":"submitted","request_id":"' + "a" * 32 + '","delivery":"accepted"}\n'
                               '{"status":"pending","request_id":"' + "a" * 32 + '"}')
        return FakeProc(0, json.dumps({"status": "completed", "request_id": "a" * 32, "answer": "推特结论"}))

    monkeypatch.setattr(R.subprocess, "run", fake_run)
    r = client.post("/api/research", json={"topic": "grok 测试", "engines": ["grokbot"]}).json()
    res = client.get(f"/api/research/results/{r['results'][0]['id']}").json()
    assert seen == ["status", "send", "wait"] and res["status"] == "done" and res["content"] == "推特结论"
    assert res["request_id"] == "a" * 32


def test_manual_doc(client):
    d = client.post("/api/research/docs", json={"title": "手写笔记", "content": "# 我的笔记", "tags": ["笔记"]}).json()
    assert Path(d["path"]).read_text("utf-8") == "# 我的笔记"
    d2 = client.put(f"/api/research/docs/{d['id']}", json={"title": "手写笔记", "content": "改过", "tags": ["笔记"]}).json()
    assert d2["content"] == "改过" and "笔记" in client.get("/api/research/docs/tags").json()
    client.delete(f"/api/research/docs/{d['id']}")
    assert not Path(d["path"]).exists()


def test_products(client):
    p = client.post("/api/research/products", json={"name": "Cursor", "category": "IDE", "rating": 7,
                                                     "experience": "补全很快", "tags": ["编程"]}).json()
    assert p["rating"] == 5 and p["tags"] == ["编程"]
    assert client.get("/api/research/products", params={"q": "补全"}).json()[0]["id"] == p["id"]
    p2 = client.put(f"/api/research/products/{p['id']}", json={**p, "cons": "贵"}).json()
    assert p2["cons"] == "贵"
    draft = client.get(f"/api/research/products/{p['id']}/draft").json()
    assert draft["topic"] == "Cursor" and draft["angles"] == ["用户口碑与体验"] and "补全很快" in draft["context"]
    client.delete(f"/api/research/products/{p['id']}")
    assert client.get(f"/api/research/products/{p['id']}").status_code == 404


def test_quick_product_and_progress(client, fakes):
    d = R.parse_quick_product("Cursor 4星 补全快但贵 #AI编程 #IDE")
    assert (d["name"], d["rating"], d["experience"], d["tags"]) == ("Cursor", 4, "补全快但贵", ["AI编程", "IDE"])
    d = R.parse_quick_product("Raycast ★★★★★ https://raycast.com 启动器 优：快 缺：插件少")
    assert d["rating"] == 5 and d["url"] == "https://raycast.com" and d["experience"] == "启动器" and d["pros"] == "快" and d["cons"] == "插件少"
    assert R.parse_quick_product("Notion")["rating"] == 0
    p = client.post("/api/research/products/quick", json={"text": "Cursor 4星 补全快但贵 #AI编程"}).json()
    assert p["name"] == "Cursor" and p["rating"] == 4 and p["tags"] == ["AI编程"]
    assert client.post("/api/research/products/quick", json={"text": "#只有标签"}).status_code == 400
    r = client.post("/api/research", json={"topic": "进度点", "engines": ["claude", "codex"]}).json()
    row = next(x for x in client.get("/api/research").json() if x["id"] == r["id"])
    assert [x["engine"] for x in row["progress"]] == ["claude", "codex"] and row["progress"][0]["status"] == "running"


def test_fallback_keeps_requested_engine_and_is_labeled(client, fakes):
    submitted, _ = fakes
    r = client.post("/api/research", json={"topic": "回退标注", "angles": ["技术原理"], "engines": ["claude", "codex"]}).json()
    cl, cx = r["results"]
    R.on_job_done({"ref": f"research:{r['id']}:r{cl['id']}", "status": "done", "output": "A", "engine": "claude"})
    # codex 没跑通，平台回退到 claude 代跑
    R.on_job_done({"ref": f"research:{r['id']}:r{cx['id']}", "status": "done", "output": "B", "engine": "claude",
                   "fallback_from": "codex"})
    got = {x["id"]: x for x in client.get(f"/api/research/{r['id']}").json()["results"]}
    assert got[cx["id"]]["engine"] == "codex" and got[cx["id"]]["used_engine"] == "claude"
    assert got[cl["id"]]["used_engine"] == ""
    doc = Path(client.get(f"/api/research/{r['id']}").json()["doc_path"]).read_text("utf-8")
    assert "Codex（未跑通，由 Claude Code 代跑）" in doc
    client.post(f"/api/research/{r['id']}/synthesize")
    assert "由 Claude Code 代跑" in submitted[-1]["prompt"] and "不是独立来源" in submitted[-1]["prompt"]
