import json
from datetime import date

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
