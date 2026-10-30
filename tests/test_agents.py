import json
from datetime import datetime, timedelta

from app.modules import _agents_scan as A


def _w(path, rows):
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False, separators=(",", ":")) for r in rows) + "\n")


def _claude(ts, typ, **kw):
    return {"type": typ, "timestamp": ts.astimezone().isoformat(), "cwd": "/w/proj", "sessionId": "s", **kw}


def test_claude_states_and_plan(tmp_path):
    now = datetime.now()
    t0 = now - timedelta(minutes=30)
    proj = tmp_path / "claude" / "-w-proj"
    proj.mkdir(parents=True)
    plan = {"type": "tool_use", "id": "t1", "name": "mcp__ccd_turn__update_plan",
            "input": {"items": [{"content": "看代码", "status": "in_progress"}, {"content": "写实现", "status": "pending"}]}}
    rows = [
        _claude(t0, "user", message={"role": "user", "content": "帮我实现登录"}),
        _claude(t0, "assistant", message={"content": [plan], "stop_reason": "tool_use"}),
        _claude(t0, "user", message={"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]}),
        _claude(t0, "assistant", message={"content": [{"type": "tool_use", "id": "t2", "name": "mcp__ccd_turn__update_plan", "input": {"advance": True}}], "stop_reason": "tool_use"}),
        _claude(t0, "user", message={"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t2", "content": "ok"}]}),
        _claude(t0, "assistant", message={"content": [{"type": "text", "text": "要用 JWT 还是 session？"}], "stop_reason": "end_turn"}),
    ]
    _w(proj / "a.jsonl", rows)
    # 正在跑：刚写入、回合未结束
    _w(proj / "b.jsonl", [_claude(now, "user", message={"role": "user", "content": "跑测试"}),
                          _claude(now, "assistant", message={"content": [{"type": "tool_use", "id": "x", "name": "Bash", "input": {}}], "stop_reason": "tool_use"})])
    # 等待批准：工具调用无结果且很久不动
    old = now - timedelta(minutes=40)
    _w(proj / "c.jsonl", [_claude(old, "user", message={"role": "user", "content": "部署"}),
                          _claude(old, "assistant", message={"content": [{"type": "tool_use", "id": "y", "name": "Bash", "input": {}}], "stop_reason": "tool_use"})])
    # 被中断
    _w(proj / "d.jsonl", [_claude(old, "user", message={"role": "user", "content": "重构"}),
                          _claude(old, "user", message={"role": "user", "content": "[Request interrupted by user]"})])
    cards = {c["session_id"]: c for c in A.scan({"claude": [str(tmp_path / "claude")]}, 24, now)}
    a = cards["a"]
    assert (a["state"], a["reason"]) == ("attention", "等你回复")
    assert [p["status"] for p in a["plan"]] == ["done", "doing"] and a["plan_current"] == "写实现"
    assert a["title"] == "帮我实现登录" and a["project"] == "proj"
    assert cards["b"]["state"] == "running"
    assert cards["c"]["reason"] == "等待批准？"
    assert cards["d"]["reason"] == "已中断"


def test_codex_complete_and_unfinished_plan(tmp_path):
    now = datetime.now()
    day = tmp_path / "codex" / f"{now:%Y}" / f"{now:%m}" / f"{now:%d}"
    day.mkdir(parents=True)
    ts = (now - timedelta(minutes=5)).astimezone().isoformat()
    rows = [
        {"timestamp": ts, "type": "session_meta", "payload": {"id": "cx1", "cwd": "/w/repo", "originator": "codex_desktop"}},
        {"timestamp": ts, "type": "event_msg", "payload": {"type": "task_started"}},
        {"timestamp": ts, "type": "event_msg", "payload": {"type": "user_message", "message": "修复 CI"}},
        {"timestamp": ts, "type": "response_item", "payload": {"type": "function_call", "name": "update_plan",
                                                                "arguments": json.dumps({"plan": [{"step": "复现", "status": "completed"}, {"step": "修复", "status": "pending"}]})}},
        {"timestamp": ts, "type": "event_msg", "payload": {"type": "task_complete", "last_agent_message": "已定位原因。"}},
    ]
    _w(day / "r.jsonl", rows)
    (c,) = A.scan({"codex": [str(tmp_path / "codex")]}, 24, now)
    assert c["session_id"] == "cx1" and c["state"] == "review" and c["reason"] == "已停 · 计划 1/2"
    assert c["last_agent"] == "已定位原因。" and not c["automated"]


def test_board_marks_expire_on_new_activity(client):
    from app import db
    db.insert("jobs", {"module": "plan", "ref": "x", "engine": "claude", "prompt": "跑一下", "status": "done",
                       "output": "好了", "created_at": db.now(), "finished_at": db.now()})
    jid = db.row("SELECT max(id) AS i FROM jobs")["i"]
    key = f"job:{jid}"
    find = lambda b: next((c for col in b["columns"] for c in col["cards"] if c["key"] == key), None)  # noqa: E731
    assert find(client.get("/api/agents/board").json())["column"] == "review"
    client.post("/api/agents/state", json={"key": key, "col": "done"})
    assert find(client.get("/api/agents/board").json())["column"] == "done"
    db.execute("UPDATE agent_board SET updated_at='2000-01-01' WHERE key=?", [key])  # 标记早于最近活动 → 失效
    assert find(client.get("/api/agents/board").json())["column"] == "review"
