import json
from datetime import date, datetime, timedelta

from app.modules import _review_sessions as rs

DAY = date(2026, 10, 29)


def _z(local_hms: str) -> str:
    """本地时间 → 日志里的 UTC 'Z' 时间戳（与解析器的本地时区换算对称）。"""
    from datetime import datetime, timezone
    dt = datetime.fromisoformat(f"2026-10-29T{local_hms}").astimezone()
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _write(path, recs):
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False, separators=(",", ":")) for r in recs) + "\n", "utf-8")
    return path


def _cu(ts, content, **kw):
    return {"type": "user", "timestamp": _z(ts), "cwd": "/w/proj", "message": {"role": "user", "content": content}, **kw}


def _ca(ts, blocks):
    return {"type": "assistant", "timestamp": _z(ts), "message": {"role": "assistant", "content": blocks}}


def test_claude_session_parse(tmp_path):
    proj = tmp_path / "claude" / "-w-proj"
    proj.mkdir(parents=True)
    f = _write(proj / "s1.jsonl", [
        {"type": "api-request", "timestamp": _z("09:00:00"), "params": {"x": "y" * 100}},
        {"type": "custom-title", "customTitle": "做登录页"},
        _cu("09:00:00", "实现登录页", origin={"kind": "human"}),
        _ca("09:00:05", [{"type": "tool_use", "name": "Bash", "input": {"command": "ls"}}]),
        _cu("09:00:06", [{"type": "tool_result", "content": "Permission for this action was denied", "is_error": True}]),
        _ca("09:01:00", [{"type": "text", "text": "完成了，要我提交吗？"}]),
        _cu("09:03:00", "提交", origin={"kind": "human"}),
        _ca("09:03:30", [{"type": "tool_use", "name": "Edit", "input": {}}]),
        _cu("09:04:00", [{"type": "tool_result", "content": "ok"}]),
        _cu("09:04:10", "[Request interrupted by user]"),
        _cu("09:05:00", "不对，应该用 OAuth", origin={"kind": "human"}),
        _ca("09:06:00", [{"type": "text", "text": "已改为 OAuth。"}]),
        _cu("09:07:00", "<task-notification>done</task-notification>", origin={"kind": "task-notification"}),
        _cu("09:08:00", "进度怎样了", origin={"kind": "human"}),
        _cu("09:08:00", "meta stuff", isMeta=True),
        _ca("09:08:30", [{"type": "text", "text": "好了"}]),
        {**_cu("09:09:00", "subagent prompt"), "isSidechain": True},
    ])
    meta, events = rs.read_claude(f)
    assert meta["title"] == "做登录页" and meta["cwd"] == "/w/proj" and not meta["automated"]
    s = rs.summarize(meta, events, DAY)
    assert s["project"] == "proj"
    kinds = [m["kind"] for m in s["messages"]]
    assert kinds == ["new_task", "approve", "interrupt", "correct", "check"]
    assert s["human_turns"] == 5
    assert s["tool_calls"] == 2 and s["tool_errors"] == 1 and s["denials"] == 1
    assert s["messages"][1]["wait_min"] == 2.0     # 09:01 Agent 提问 → 09:03 回复
    assert s["wall_min"] == 8.5
    assert 0 < s["active_min"] < s["wall_min"]
    assert rs.summarize(meta, events, date(2026, 10, 28)) is None


def test_claude_sdk_session_is_automated(tmp_path):
    f = _write(tmp_path / "s2.jsonl", [
        _cu("10:00:00", "只回复：收到", turnOrigin="sdk"),
        _ca("10:00:02", [{"type": "text", "text": "收到"}]),
    ])
    meta, events = rs.read_claude(f)
    s = rs.summarize(meta, events, DAY)
    assert s["automated"] and s["human_turns"] == 0 and s["auto_prompts"] == 1


def _cx(ts, typ, payload):
    return {"timestamp": _z(ts), "type": typ, "payload": payload}


def test_codex_session_parse(tmp_path):
    f = _write(tmp_path / "rollout-x.jsonl", [
        _cx("11:00:00", "session_meta", {"id": "abc", "cwd": "/w/codexproj", "originator": "Codex Desktop", "source": "vscode"}),
        _cx("11:00:00", "response_item", {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "# AGENTS.md ..."}]}),
        _cx("11:00:01", "event_msg", {"type": "user_message", "message": "写个脚本"}),
        _cx("11:00:01", "event_msg", {"type": "item_completed", "item": {"type": "UserMessage", "content": [{"type": "text", "text": "写个脚本"}]}}),
        _cx("11:00:05", "response_item", {"type": "custom_tool_call", "name": "exec", "input": "..."}),
        _cx("11:00:06", "event_msg", {"type": "item_completed", "item": {"type": "CommandExecution", "exit_code": 1}}),
        _cx("11:00:07", "event_msg", {"type": "token_count", "info": {}}),
        _cx("11:01:00", "event_msg", {"type": "task_complete", "last_agent_message": "写好了"}),
        _cx("11:05:00", "event_msg", {"type": "user_message", "message": "再加个重试"}),
        _cx("11:05:30", "event_msg", {"type": "agent_message", "message": "在改"}),
        _cx("11:06:00", "event_msg", {"type": "turn_aborted", "reason": "interrupted"}),
        _cx("11:06:30", "event_msg", {"type": "patch_apply_end", "success": False}),
    ])
    meta, events = rs.read_codex(f)
    assert meta["session_id"] == "abc" and not meta["automated"]
    s = rs.summarize(meta, events, DAY)
    assert s["project"] == "codexproj"
    assert [m["kind"] for m in s["messages"]] == ["new_task", "new_task", "interrupt"]
    assert s["messages"][1]["wait_min"] == 4.0
    assert s["tool_calls"] == 1 and s["tool_errors"] == 2


def test_codex_injected_developer_message_does_not_hide_wait(tmp_path):
    """Codex Desktop 每轮开头注入 developer 上下文消息，和人的消息同一时刻；不能当成 Agent 活动把等待清零。"""
    f = _write(tmp_path / "rollout-d.jsonl", [
        _cx("09:00:00", "session_meta", {"id": "d1", "cwd": "/w/p", "originator": "Codex Desktop", "source": "vscode"}),
        _cx("09:00:00", "event_msg", {"type": "item_completed", "item": {"type": "UserMessage", "content": [{"type": "text", "text": "做 A"}]}}),
        _cx("09:00:05", "response_item", {"type": "message", "role": "assistant", "content": []}),
        _cx("09:01:00", "event_msg", {"type": "task_complete", "last_agent_message": "做好了"}),
        _cx("09:41:00", "response_item", {"type": "message", "role": "developer", "content": []}),
        _cx("09:41:00", "response_item", {"type": "message", "role": "user", "content": []}),
        _cx("09:41:00", "event_msg", {"type": "item_completed", "item": {"type": "UserMessage", "content": [{"type": "text", "text": "再做 B"}]}}),
    ])
    s = rs.summarize(*rs.read_codex(f), DAY)
    assert s["messages"][1]["wait_min"] == 40.0


def test_codex_exec_automated_and_scan(tmp_path):
    d = tmp_path / "codex" / "2026" / "10" / "29"
    d.mkdir(parents=True)
    _write(d / "rollout-a.jsonl", [
        _cx("12:00:00", "session_meta", {"id": "e1", "cwd": "/w/batch", "originator": "codex_exec", "source": "exec"}),
        _cx("12:00:01", "event_msg", {"type": "user_message", "message": "评估视频"}),
        _cx("12:02:00", "event_msg", {"type": "task_complete", "last_agent_message": "完成"}),
    ])
    cl = tmp_path / "claude" / "-w-p"
    cl.mkdir(parents=True)
    _write(cl / "s.jsonl", [_cu("13:00:00", "hi", origin={"kind": "human"}), _ca("13:00:10", [{"type": "text", "text": "hello"}])])
    sessions = rs.scan(DAY, {"claude": [str(tmp_path / "claude")], "codex": [str(tmp_path / "codex")]})
    assert len(sessions) == 2
    agg = rs.aggregate(sessions)
    assert agg["automated"] == 1 and agg["interactive"] == 1 and agg["human_turns"] == 1
    assert "交互会话 1" in agg["headline"]


def test_classify():
    assert rs.classify("继续", False, False) == "approve"
    assert rs.classify("用 A 方案", False, True) == "answer"
    assert rs.classify("打不开，IPv4?", False, False) == "correct"
    assert rs.classify("再加一个导出功能", False, False) == "new_task"
    assert rs.classify("[Request interrupted by user for tool use]", False, False) == "interrupt"


def test_parse_suggestions_and_on_job_done(client):
    from app.modules import review
    d = "2026-01-02"
    t1 = client.post("/api/tasks", json={"title": "写接口", "date": d, "goal": "接口通过测试"}).json()
    t2 = client.post("/api/tasks", json={"title": "读论文", "date": d, "kind": "learning"}).json()
    out = ("## 分析\n- 写接口：有提交\n\n```json\n" + json.dumps({"suggestions": [
        {"task_id": t1["id"], "status": "done", "progress": 100, "evidence": "abc123 提交", "problem": ""},
        {"task_id": t2["id"], "status": "bogus", "progress": 140, "evidence": "无证据", "problem": "没开始"},
        {"task_id": 999999, "status": "done", "progress": 100},
    ]}, ensure_ascii=False) + "\n```\n")
    review.on_job_done({"id": 1, "ref": f"check:{d}", "status": "done", "output": out})
    rec = client.get(f"/api/review/day?date={d}").json()["record"]
    assert "写接口：有提交" in rec["ai_analysis"] and "```json" not in rec["ai_analysis"]
    sugg = rec["task_suggestions"]
    assert [s["task_id"] for s in sugg] == [t1["id"], t2["id"]]
    assert sugg[1]["status"] is None and sugg[1]["progress"] == 100
    r = client.post(f"/api/review/suggestions/{d}/1/apply").json()
    assert r["task"]["progress"] == 100 and "没开始" in r["task"]["notes"] and r["suggestion"]["applied"]
    # 失败的 job 也要留下提示
    review.on_job_done({"id": 2, "ref": "reflect:" + d, "status": "failed", "output": ""})
    from app import db
    assert "失败" in db.row("SELECT reflection FROM review_agent_stats WHERE date=?", [d])["reflection"]


def test_record_notes_timeline(client):
    d = "2026-01-05"
    client.post("/api/tasks", json={"title": "A", "date": d, "status": "done", "progress": 100})
    client.post("/api/tasks", json={"title": "B", "date": d, "progress": 50})
    client.post("/api/tasks", json={"title": "L", "date": d, "kind": "learning", "status": "done"})
    assert client.put(f"/api/review/day/{d}", json={"summary": "还行", "problems": "估时偏短"}).json()["summary"] == "还行"
    n = client.post("/api/review/notes", json={"date": d, "kind": "lesson", "title": "先写验收标准", "tags": "agent"}).json()
    client.post("/api/review/notes", json={"date": "2026-01-03", "kind": "problem", "content": "环境坏了"})
    assert client.get("/api/review/notes?q=验收").json()[0]["id"] == n["id"]
    assert all(x["kind"] == "problem" for x in client.get("/api/review/notes?kind=problem").json())
    day = client.get(f"/api/review/day?date={d}").json()
    assert day["stats"]["work"] == {"total": 2, "done": 1, "avg_progress": 75}
    assert day["stats"]["learning"]["done"] == 1 and len(day["notes"]) == 1
    tl = client.get("/api/review/timeline?start=2026-01-01&end=2026-01-06").json()
    by = {x["date"]: x for x in tl}
    assert [x["date"] for x in tl] == sorted(by, reverse=True)
    assert by[d]["tasks"]["done"] == 1 and by[d]["learning"]["total"] == 1 and by[d]["summary"] == "还行"
    assert by["2026-01-03"]["notes"][0]["title"] == "环境坏了"
    from app.modules import review
    ctx = review.agent_context(f"review:{d}")
    assert "先写验收标准" in ctx and "估时偏短" in ctx


def test_parse_quick_note():
    from app.modules.review import parse_quick_note, parse_record_line
    assert parse_quick_note("问题：需求没写验收标准 #流程 #plan") == {
        "kind": "problem", "title": "需求没写验收标准", "content": "", "tags": "流程,plan"}
    n = parse_quick_note("先写测试再改代码\n细节在这里")
    assert n["kind"] == "lesson" and n["title"] == "先写测试再改代码" and n["content"] == "细节在这里"
    assert parse_quick_note("想法: 做个周报 #idea")["kind"] == "idea"
    assert parse_quick_note("C#语言很好")["tags"] == ""
    assert parse_record_line("明天：先修 bug") == ("next_actions", "先修 bug")
    assert parse_record_line("今天还行") == ("summary", "今天还行")


def test_quick_capture_api(client):
    d = "2001-01-02"
    n = client.post("/api/review/notes/quick", json={"text": "洞察：并行更快 #agent", "date": d}).json()
    assert n["kind"] == "insight" and n["tags"] == "agent" and n["date"] == d
    client.post(f"/api/review/day/{d}/append", json={"text": "问题：等太久"})
    r = client.post(f"/api/review/day/{d}/append", json={"text": "又一条", "field": "problems"}).json()
    assert [e["text"] for e in r["record"]["entries"]] == ["等太久", "又一条"]
    assert r["improve_job_id"]
    assert client.post(f"/api/review/suggestions/{d}/0/dismiss").status_code == 404


def test_record_entries_timeline_and_improve(client):
    """写复盘每条带时间，按时间线排；提交后派改进分析，排队中的那次被最新内容替换，只认最新一次的输出。"""
    from app import db
    from app.modules import review
    d = "2001-02-03"
    review.upsert_record(d, {"summary": "老的一条没时间\n[21:30] 晚上写的", "problems": "[09:15] 早上的问题",
                             "wins": "[02-04 07:10] 第二天补的"})
    es = review.get_record(d)["entries"]
    assert [(e["time"], e["field"], e["text"]) for e in es] == [
        ("", "summary", "老的一条没时间"), ("09:15", "problems", "早上的问题"),
        ("21:30", "summary", "晚上写的"), ("07:10", "wins", "第二天补的")]
    assert es[-1]["next_day"] and not es[1]["next_day"]
    assert review.stamp(d, f"{d}T08:05:09") == "[08:05] " and review.stamp(d, "2001-02-04T07:10:00") == "[02-04 07:10] "

    r1 = client.post(f"/api/review/day/{d}/append", json={"text": "学习：测试题太难"}).json()
    r2 = client.post(f"/api/review/day/{d}/append", json={"text": "问题：后台任务失败"}).json()
    assert r1["improve_job_id"] == r2["improve_job_id"]           # 还在排队：换成最新内容，不重复排
    job = db.row("SELECT * FROM jobs WHERE id=?", [r2["improve_job_id"]])
    assert job["ref"] == f"improve:{d}" and "后台任务失败" in job["prompt"] and "学习平台反馈" in job["prompt"]
    db.execute("UPDATE jobs SET status='running' WHERE id=?", [job["id"]])
    r3 = client.post("/api/review/improve", json={"date": d}).json()
    assert r3["job_id"] != job["id"]
    review.on_job_done({**job, "status": "done", "output": "旧的分析"})  # 被新一次取代的输出不写回
    assert review.get_record(d)["improve_md"] == ""
    review.on_job_done({"id": r3["job_id"], "ref": f"improve:{d}", "status": "done", "output": "## 改进\n- 先跑 trace"})
    day = client.get(f"/api/review/day?date={d}").json()
    assert day["record"]["improve_md"].startswith("## 改进") and any(j["ref"] == f"improve:{d}" for j in day["jobs"])
    rec = client.put(f"/api/review/day/{d}", json={"next_actions": "明天先跑 trace"}).json()
    assert rec["improve_job_id"]                                   # 改了内容才重新分析
    n = db.row("SELECT count(*) n FROM jobs WHERE ref=?", [f"improve:{d}"])["n"]
    client.put(f"/api/review/day/{d}", json={"next_actions": "明天先跑 trace"})
    assert db.row("SELECT count(*) n FROM jobs WHERE ref=?", [f"improve:{d}"])["n"] == n


def test_efficiency_snapshot_taken_during_the_day_is_rescanned(monkeypatch):
    from datetime import datetime, timedelta
    from app import db
    from app.modules import review
    db.init([review.SCHEMA])
    assert review._stale("2020-01-01", "2020-01-01T19:41:00")            # 当天扫的：过了那天要重扫
    assert not review._stale("2020-01-01", "2020-01-02T00:05:00")        # 那天结束后扫的：定稿
    today = db.today()
    assert not review._stale(today, datetime.now().isoformat(timespec="seconds"))
    assert review._stale(today, (datetime.now() - timedelta(minutes=30)).isoformat(timespec="seconds"))
    calls = []
    monkeypatch.setattr(review.rs, "scan", lambda d, *a: calls.append(d) or [])
    review._upsert_stats("2020-01-05", {"summary": json.dumps({"v": review.rs.VERSION}), "sessions": "[]", "scanned_at": "2020-01-05T19:00:00"})
    review.get_efficiency("2020-01-05")
    review.get_efficiency("2020-01-05")                                   # 第二次已定稿，不再扫
    assert len(calls) == 1


def test_platform_chat_session_counts_as_human():
    """平台对话面板走 claude -p：日志里是 sdk 提示（auto），但提示是人在面板里打的字。"""
    t = datetime(2026, 10, 29, 10, 0)
    ev = [{"kind": "auto", "ts": t, "text": "帮我排一下今天"}, {"kind": "agent", "ts": t + timedelta(minutes=1), "end": True},
          {"kind": "auto", "ts": t + timedelta(minutes=21), "text": "把 3 号挪到下午"}]
    meta = {"engine": "claude", "session_id": "chat-1", "file": "/x/p/chat-1.jsonl", "cwd": "/w/data", "automated": True}
    assert rs.promote_platform_chat(meta, ev, {"other"}) == (meta, ev)
    m2, ev2 = rs.promote_platform_chat(meta, ev, {"chat-1"})
    s = rs.summarize(m2, ev2, DAY)
    assert not s["automated"] and s["human_turns"] == 2 and s["messages"][1]["wait_min"] == 20.0
    assert ev[0]["kind"] == "auto"            # 不改缓存里的原事件


def test_wait_definition_matches_board():
    """复盘的等待和看板同一口径：≤3 小时的等待全额计入（不再单次封顶 30 分钟），更长视为离开。"""
    t = datetime(2026, 10, 29, 9, 0)
    ev = [{"kind": "human", "ts": t, "text": "做 A"}, {"kind": "agent", "ts": t + timedelta(minutes=1)},
          {"kind": "human", "ts": t + timedelta(minutes=61), "text": "做 B"}, {"kind": "agent", "ts": t + timedelta(minutes=62)},
          {"kind": "human", "ts": t + timedelta(hours=6), "text": "做 C"}]
    s = rs.summarize({"engine": "claude", "session_id": "s", "file": "/x/p/s.jsonl", "cwd": "/w/p"}, ev, DAY)
    assert s["wait_total_min"] == 60.0


def test_check_auto_applies_evidence_backed_progress(client):
    from app import tasks
    from app.modules import review
    d = "2020-02-03"
    a = tasks.create({"date": d, "title": "A"})["id"]
    b = tasks.create({"date": d, "title": "B"})["id"]
    c = tasks.create({"date": d, "title": "C", "progress": 80, "status": "doing"})["id"]
    e = tasks.create({"date": d, "title": "E"})["id"]
    review.upsert_record(d, {"task_suggestions": [
        {"task_id": a, "status": "done", "progress": 100, "evidence": "commit abc123 已 push"},
        {"task_id": b, "status": "partial", "progress": 40, "evidence": "无证据：仓库里没有脚本"},
        {"task_id": c, "status": "partial", "progress": 50, "evidence": "只完成一半"},          # 会让进度倒退：留给人
        {"task_id": e, "status": "todo", "progress": 0, "evidence": "没开始"}]})
    assert review.auto_apply(d) == [0]
    assert tasks.get(a)["status"] == "done" and tasks.get(b)["status"] == "todo" and tasks.get(c)["progress"] == 80
    s = review.get_record(d)["task_suggestions"]
    assert s[0]["applied"] and s[0]["auto"] and not s[1].get("applied")
