from app.modules import plan

CFG = {"focus_windows": [{"start": "10:00", "end": "11:40"}, {"start": "13:30", "end": "16:50"}],
       "day_start": "08:30", "day_end": "23:00", "max_agent_concurrency": 2}


def T(id_, level="heavy", est=60, prio=2, deps=(), group="", title=None):
    return {"id": id_, "title": title or f"t{id_}", "human_level": level, "est_minutes": est, "priority": prio,
            "depends_on": list(deps), "parallel_group": group}


def m(hhmm):
    return plan._m(hhmm)


def in_focus(start, end):
    return any(m(w["start"]) <= m(start) and m(end) <= m(w["end"]) for w in CFG["focus_windows"])


def test_lessons_feed_planning(client):
    d = "2026-03-10"
    client.post("/api/review/notes", json={"date": d, "kind": "lesson", "title": "先写完成标准", "content": "目标/标准/约束", "tags": "plan,agent"})
    client.post("/api/review/notes", json={"date": d, "kind": "lesson", "title": "不相关", "tags": "planning"})
    client.post("/api/review/notes", json={"date": "2026-01-01", "kind": "lesson", "title": "太久以前", "tags": "plan"})
    client.put(f"/api/review/day/{d}", json={"next_actions": "09-15 点跑低干预长任务"})
    s = plan._lessons("2026-03-11")
    assert "先写完成标准" in s and "09-15 点" in s
    assert "不相关" not in s and "太久以前" not in s


def test_heavy_into_focus_by_priority():
    r = plan.schedule_day([T(1, prio=3, est=90), T(2, prio=1, est=90), T(3, "medium", est=60, prio=2)], CFG)
    p = r["placements"]
    assert all(in_focus(*p[i]) for i in (1, 2, 3))
    assert p[2][0] == "10:00"                       # P1 先占第一个专注窗
    assert m(p[3][0]) < m(p[1][0])                  # P2 早于 P3
    s = r["summary"]
    assert s["human_focus_minutes"] == 240 and s["human_outside_minutes"] == 0 and not s["warnings"]


def test_light_goes_outside_focus():
    r = plan.schedule_day([T(1, "light", est=20), T(2, "light", est=30)], CFG)
    for st, en in r["placements"].values():
        assert not in_focus(st, en)
    assert r["placements"][1][0] == "08:30"


def test_overflow_spill_and_unschedulable():
    # 专注时间共 300 分钟；第三个 heavy 放不进专注窗 → 溢出到非专注并标记
    items = [T(1, est=100, prio=1), T(2, est=200, prio=1), T(3, est=60, prio=2), T(4, est=2000, prio=3)]
    r = plan.schedule_day(items, CFG)
    p, s = r["placements"], r["summary"]
    assert in_focus(*p[1]) and in_focus(*p[2]) and not in_focus(*p[3])
    assert s["flags"]["3"] == "溢出到非专注时间"
    assert 4 not in p and 4 in s["unscheduled"]
    assert len(s["warnings"]) == 2


def test_dependencies_respected():
    r = plan.schedule_day([T(2, est=30, deps=[1], prio=1), T(1, est=60, prio=3), T(3, "light", est=10, deps=[2])], CFG)
    p = r["placements"]
    assert m(p[1][1]) <= m(p[2][0]) and m(p[2][1]) <= m(p[3][0])


def test_agent_lanes_and_concurrency():
    items = [T(i, "auto", est=120, group="A") for i in range(1, 5)]
    r = plan.schedule_day(items, CFG)
    s = r["summary"]
    agent = [b for b in r["blocks"] if b["type"] == "agent"]
    assert len(agent) == 4 and {b["lane"] for b in agent} == {"agent1", "agent2"}
    assert s["agent_peak_concurrency"] == 2 and s["agent_minutes"] == 480
    # 每个 auto 任务都有人启动 + 验收，计入人时间，且不占专注窗
    kick = [b for b in r["blocks"] if b["type"] in ("kickoff", "review")]
    assert len(kick) == 8 and all(not in_focus(b["start"], b["end"]) for b in kick)
    assert s["human_minutes"] == 4 * (plan.KICKOFF_MIN + plan.REVIEW_MIN) and s["human_focus_minutes"] == 0
    # 同一 lane 内不重叠
    for lane in ("agent1", "agent2"):
        iv = sorted((m(b["start"]), m(b["end"])) for b in agent if b["lane"] == lane)
        assert all(a[1] <= b[0] for a, b in zip(iv, iv[1:]))


def test_agent_runs_parallel_with_focus_work():
    r = plan.schedule_day([T(1, "heavy", est=100, prio=1), T(2, "auto", est=90, prio=2)], CFG)
    agent = next(b for b in r["blocks"] if b["type"] == "agent")
    assert agent["start"] == "08:35"                # 一早启动，跑进专注窗与人并行
    assert r["summary"]["parallel_ratio"] > 1


def test_auto_depends_on_human():
    r = plan.schedule_day([T(1, "medium", est=60, prio=1), T(2, "auto", est=30, deps=[1])], CFG)
    kick = next(b for b in r["blocks"] if b["type"] == "kickoff" and b["task_id"] == 2)
    assert m(kick["start"]) >= m(r["placements"][1][1])


def test_from_time():
    r = plan.schedule_day([T(1, est=60)], CFG, from_time="14:00")
    assert r["placements"][1] == ("14:00", "15:00")


def test_extract_json_variants():
    assert plan.extract_json('思考…\n```json\n{"items": []}\n```\n') == {"items": []}
    assert plan.extract_json('先 {"a":1} 后 {"items":[{"task_id":1}]} 完') == {"items": [{"task_id": 1}]}
    assert plan.extract_json("no json") is None


def test_on_job_done_decompose_and_schedule(client):
    parent = client.post("/api/tasks", json={"title": "做报告", "date": "2030-01-02", "priority": 1, "repo": "/tmp"}).json()
    out = """好的，拆解如下：
```json
{"items": [{"task_id": %d, "subtasks": [
  {"title": "收集数据", "goal": "csv", "human_level": "auto", "executor": "codex", "est_minutes": 40, "parallel_group": "A", "depends_on": []},
  {"title": "写结论", "goal": "一页", "human_level": "heavy", "executor": "human", "est_minutes": 60, "depends_on": [0], "priority": 1},
  {"title": "发邮件", "human_level": "bogus", "est_minutes": "x", "depends_on": [1, 9]}
]}]}
```""" % parent["id"]
    plan.on_job_done({"id": 0, "ref": "plan:decompose:2030-01-02", "status": "done", "output": out, "log": ""})
    assert not [t for t in client.get("/api/tasks?date=2030-01-02").json() if t["parent_id"]]  # 先是草稿，不写子任务
    dr = client.get("/api/plan/drafts?date=2030-01-02").json()["draft"]
    assert dr["data"]["items"][0]["title"] == "做报告" and len(dr["data"]["items"][0]["subtasks"]) == 3
    client.post(f"/api/plan/drafts/{dr['id']}/apply")
    kids = [t for t in client.get("/api/tasks?date=2030-01-02").json() if t["parent_id"] == parent["id"]]
    by = {k["title"]: k for k in kids}
    assert set(by) == {"收集数据", "写结论", "发邮件"}
    assert by["收集数据"]["executor"] == "codex" and by["收集数据"]["repo"] == "/tmp"
    assert by["写结论"]["depends_on"] == [by["收集数据"]["id"]]
    assert by["发邮件"]["human_level"] == "medium" and by["发邮件"]["est_minutes"] == 30
    assert by["发邮件"]["depends_on"] == [by["写结论"]["id"]]

    # 重新拆解替换 todo 子任务
    out2 = '```json\n{"items":[{"task_id": %d, "subtasks":[{"title":"一步到位","human_level":"light"}]}]}\n```' % parent["id"]
    plan.on_job_done({"id": 0, "ref": "plan:decompose:2030-01-02", "status": "done", "output": out2, "log": ""})
    client.post(f"/api/plan/drafts/{client.get('/api/plan/drafts?date=2030-01-02').json()['draft']['id']}/apply")
    day = client.get("/api/plan/day?date=2030-01-02").json()
    assert [c["title"] for c in day["tree"][0]["children"]] == ["一步到位"]

    s = client.post("/api/plan/schedule", json={"date": "2030-01-02"}).json()
    assert s["summary"]["scheduled"] == 1
    day = client.get("/api/plan/day?date=2030-01-02").json()
    assert day["tree"][0]["start_time"] and day["schedule"]["blocks"]
    assert "一步到位" in plan.agent_context("plan:2030-01-02")


def test_carry_over(client):
    a = client.post("/api/tasks", json={"title": "未完成事项", "date": "2030-02-01"}).json()
    client.post("/api/tasks", json={"title": "子", "date": "2030-02-01", "parent_id": a["id"]})
    client.post("/api/tasks", json={"title": "已完成事项", "date": "2030-02-01", "status": "done"})
    r = client.post("/api/plan/carry", json={"date": "2030-02-03"}).json()
    assert r["from"] == "2030-02-01" and len(r["created"]) == 2
    titles = [t["title"] for t in client.get("/api/tasks?date=2030-02-03").json()]
    assert sorted(titles) == ["子", "未完成事项"]
    assert client.post("/api/plan/carry", json={"date": "2030-02-03"}).json()["created"] == []


def test_run_finish_marks_task(client):
    t = client.post("/api/tasks", json={"title": "自动跑", "date": "2030-03-01", "human_level": "auto"}).json()
    plan.db.insert("plan_runs", {"task_id": t["id"], "job_id": 99999, "status": "running", "started_at": plan.db.now()})
    plan.on_job_done({"id": 99999, "ref": f"plan:run:{t['id']}", "status": "done", "engine": "claude",
                      "output": "做完了\nSTATUS: done\n写了脚本 a.py"})
    t2 = client.get(f"/api/tasks/{t['id']}").json()
    assert t2["status"] == "done" and "a.py" in t2["notes"]
    run = client.get(f"/api/plan/runs?task_id={t['id']}").json()[0]
    assert run["status"] == "done" and run["finished_at"]


def test_short_kickoff_does_not_wait_hours():
    r = plan.schedule_day([T(1, "heavy", est=30, prio=1, deps=[]), T(2, "auto", est=20, deps=[1])],
                          {**CFG, "day_start": "13:30"})
    kick = next(b for b in r["blocks"] if b["type"] == "kickoff")
    assert kick["start"] == "14:00"                 # 不会等到 16:50 才启动


def _card(key, project, title, column="review", **kw):
    return {"key": key, "engine": "claude", "project": project, "title": title, "last_human": "", "last_agent": kw.get("reply", ""),
            "reason": "已停", "last": "2026-03-10T09:00:00", "plan": [], "plan_current": "", "output": kw.get("output"),
            "cwd": "", "column": column}


def test_progress_finds_related_sessions(monkeypatch):
    from app.modules import agents
    cards = [_card("a", "feynman_claw", "分析 viral 链路怎么压缩到1分钟以内生成1分钟视频", reply="提速分支已合并 main",
                   output={"status": "delivered", "labels": ["推送"], "at": "06:09"}),
             _card("b", "wealth", "yfinance 有哪些有价值的信息"),
             _card("c", "self_startup", "学习平台看板", column="running"),
             _card("d", "other", "跑着的无关会话", column="running")]
    monkeypatch.setattr(agents, "board", lambda hours: {"columns": [{"cards": cards}]})
    monkeypatch.setattr(agents, "deliveries_text", lambda d: "无")
    tops = [{"id": 1, "title": "优化viral模板链路的速度，1分钟以内生成1分钟左右视频", "goal": "", "repo": ""},
            {"id": 2, "title": "优化self-startup的规划和看板", "goal": "", "repo": ""}]
    text, _ = plan._progress("2026-03-10", tops)
    one, two = text.split("### task_id=2")[0], text.split("### task_id=2")[1].split("### 其它")[0]
    assert "提速分支已合并 main" in one and "已交付" in one and "wealth" not in one
    assert "self_startup" in two and "wealth" not in two
    assert "跑着的无关会话" in text.split("### 其它")[1]


def test_budget_and_prompt_limits(client, monkeypatch):
    b = plan._budget("2000-01-01", CFG)  # 不是今天：整天可用
    assert b["focus_left"] == 100 + 200 and b["free_left"] == 870 - 300 and b["agent_left"] == 870 * 2
    sent = {}
    monkeypatch.setattr(plan.jobs, "submit", lambda *a, **kw: sent.update(prompt=a[1], kw=kw) or 1)
    monkeypatch.setattr(plan, "_progress", lambda d, t: ("- 已有会话 X 做完了基线", ["/tmp"]))
    t = client.post("/api/tasks", json={"date": "2030-02-01", "title": "事项"}).json()
    client.post("/api/plan/decompose", json={"date": "2030-02-01"})
    assert f"最多 {plan.MAX_SUBS} 个子任务" in sent["prompt"] and "已有会话 X 做完了基线" in sent["prompt"]
    assert "/tmp" in sent["kw"]["add_dirs"] and t["id"]


def test_draft_discuss_flow(client):
    p = client.post("/api/tasks", json={"title": "讲解 skill", "date": "2030-03-01"}).json()
    out = ('```json\n{"basis": ["会话 X 已完成分析"], "questions": [{"q": "今天做到哪？", "default": "做到评测集"}, "只问一句"],'
           ' "items": [{"task_id": %d, "note": "接着 X", "subtasks": [{"title": "a"}, {"title": "b", "depends_on": [0]}]}]}\n```') % p["id"]
    plan.on_job_done({"id": 0, "ref": "plan:decompose:2030-03-01", "status": "done", "output": out, "log": ""})
    d1 = client.get("/api/plan/day?date=2030-03-01").json()["draft"]
    assert d1["data"]["questions"] == [{"q": "今天做到哪？", "default": "做到评测集"}, {"q": "只问一句", "default": ""}]
    ctx = plan.agent_context("plan:2030-03-01")
    assert f"拆解草稿 #{d1['id']}" in ctx and "会话 X 已完成分析" in ctx

    # 讨论后改草稿（对话 Agent 走 PUT），再出一份新草稿会替换旧的
    data = d1["data"]
    data["items"][0]["subtasks"] = data["items"][0]["subtasks"][:1]
    assert len(client.put(f"/api/plan/drafts/{d1['id']}", json={"data": data}).json()["data"]["items"][0]["subtasks"]) == 1
    plan.on_job_done({"id": 0, "ref": "plan:decompose:2030-03-01", "status": "done", "output": out, "log": ""})
    d2 = client.get("/api/plan/drafts?date=2030-03-01").json()["draft"]
    assert d2["id"] != d1["id"] and client.post(f"/api/plan/drafts/{d1['id']}/apply").status_code == 404

    client.post(f"/api/plan/drafts/{d2['id']}/discard")
    assert client.get("/api/plan/drafts?date=2030-03-01").json()["draft"] is None
    assert not [t for t in client.get("/api/tasks?date=2030-03-01").json() if t["parent_id"]]
