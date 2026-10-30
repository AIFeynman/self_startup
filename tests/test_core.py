def test_meta_and_tasks(client):
    assert "modules" in client.get("/api/meta").json()
    t = client.post("/api/tasks", json={"title": "写周报", "priority": 1}).json()
    assert client.patch(f"/api/tasks/{t['id']}", json={"status": "done"}).json()["status"] == "done"
    assert any(x["id"] == t["id"] for x in client.get(f"/api/tasks?date={t['date']}").json())


def test_settings_roundtrip(client):
    s = client.get("/api/settings").json()
    assert s["focus_windows"][0]["start"] == "10:00"
    assert client.put("/api/settings", json={"max_agent_concurrency": 2}).json()["max_agent_concurrency"] == 2


def test_chat_jobs_post_back(client):
    from app import chat, db, jobs
    sid = db.insert("chat_sessions", {"module": "learn", "ref": "", "title": "深读", "engine": "", "created_at": db.now(), "updated_at": db.now()})
    t0 = db.now()
    before = db.row("SELECT max(id) AS m FROM jobs")["m"] or 0
    # 对话这一轮里 Agent 提交的任务：一个已经跑完，一个还在跑
    done = db.insert("jobs", {"module": "learn", "ref": "learn:item:99", "engine": "claude", "prompt": "p", "status": "done",
                              "output": "笔记写好了", "created_at": t0, "finished_at": db.now()})
    run = db.insert("jobs", {"module": "research", "ref": "research:1:r1", "engine": "claude", "prompt": "p", "status": "running", "created_at": t0})
    assert sorted(chat.link_jobs(sid, before)) == [done, run]
    msgs = db.rows("SELECT * FROM chat_messages WHERE session_id=?", [sid])
    assert len(msgs) == 1 and "完成" in msgs[0]["content"] and "#learn/item/99" in msgs[0]["content"]
    # 还在跑的那个结束后回帖
    db.update("jobs", run, {"status": "failed", "log": "[error] boom", "finished_at": db.now()})
    jobs.notify_chat(db.row("SELECT * FROM jobs WHERE id=?", [run]))
    last = db.rows("SELECT * FROM chat_messages WHERE session_id=? ORDER BY id", [sid])[-1]["content"]
    assert "失败" in last and "boom" in last
    fin = client.get("/api/jobs/finished", params={"since": "2000-01-01T00:00:00"}).json()
    assert {j["id"] for j in fin} >= {done, run} and all(j["link"] for j in fin)


def test_needs_you_parses_approvals():
    from app.jobs import needs_you
    out = ("做完了。\n\n**需要你做的**\n- **决策 D1**：要不要换 RSS 列表\n- 确认是否合并 main\n\n产出：\n- 文档 a.md\n"
           "NEEDS_YOU: 发布 dev？建议先合并\n- 需要你做：看一眼报告")
    assert needs_you(out) == ["发布 dev？建议先合并"]  # 写了 NEEDS_YOU 就只认它
    assert needs_you(out.replace("NEEDS_YOU: 发布 dev？建议先合并\n", "")) == ["决策 D1：要不要换 RSS 列表", "确认是否合并 main", "看一眼报告"]
    assert needs_you("## 总结\n- 改了 A\n- 测试通过") == []
    assert needs_you("**需要你知道的**\n- 借用了另一个环境\n\n需要你拍板的有：\n- 选 A 还是 B") == ["选 A 还是 B"]


def test_approvals_decide_and_followup(client, monkeypatch):
    from app import db, jobs
    sent = []
    monkeypatch.setattr(jobs, "submit", lambda *a, **kw: sent.append((a, kw)) or 999)
    jid = db.insert("jobs", {"module": "plan", "ref": "plan:run:1", "engine": "claude", "prompt": "p", "status": "done",
                             "engine_session": "sess-1", "cwd": "/tmp/repo", "created_at": db.now(), "finished_at": db.now(),
                             "output": "做完了\nNEEDS_YOU: 合并 main？建议合\nNEEDS_YOU: 换 RSS 列表？"})
    db.insert("jobs", {"module": "learn", "ref": "learn:item:1", "engine": "claude", "prompt": "p", "status": "done",
                       "created_at": db.now(), "finished_at": db.now(), "output": "NEEDS_YOU: 深读正文里的字样不算"})
    items = client.get("/api/jobs/approvals").json()
    assert [a["item"] for a in items] == ["换 RSS 列表？", "合并 main？建议合"]
    assert len(client.get("/api/jobs/approvals").json()) == 2  # 幂等

    by = {a["item"]: a["id"] for a in items}
    r = client.post(f"/api/jobs/approvals/{by['合并 main？建议合']}/decide", json={"decision": "approved", "note": "合完发 dev 前停下"}).json()
    assert r == {"ok": True, "left": 1, "followup_job_id": None} and not sent
    assert client.post(f"/api/jobs/approvals/{by['合并 main？建议合']}/decide", json={"decision": "approved"}).status_code == 400
    r = client.post(f"/api/jobs/approvals/{by['换 RSS 列表？']}/decide", json={"decision": "replied", "note": "换成新默认列表"}).json()
    assert r["followup_job_id"] == 999
    (args, kw), = sent
    assert kw["session"] == "sess-1" and kw["cwd"] == "/tmp/repo" and kw["ref"] == f"approval:{jid}"
    assert "批准：合完发 dev 前停下" in args[1] and "回复：换成新默认列表" in args[1]
    assert client.get("/api/jobs/approvals").json() == []


def test_job_records_engine_fallback(client, monkeypatch):
    from app import agent, db, jobs

    def fake_stream(prompt, **kw):
        yield {"type": "error", "text": "model_not_found；回退到备选引擎"}
        yield {"type": "engine", "text": "切换到 claude"}
        yield {"type": "done", "text": "ok", "engine": "claude"}

    monkeypatch.setattr(agent, "run_stream", fake_stream)
    jid = db.insert("jobs", {"module": "nomod", "ref": "", "engine": "codex", "prompt": "p", "status": "queued", "created_at": db.now()})
    jobs._run(jid, "nomod", "p", "codex", "", None, [])
    j = db.row("SELECT * FROM jobs WHERE id=?", [jid])
    assert j["engine"] == "claude" and j["fallback_from"] == "codex" and j["status"] == "done"
