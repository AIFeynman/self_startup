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
