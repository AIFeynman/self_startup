import json
from datetime import datetime, timedelta

from app.modules import _deliveries as D


def _w(path, rows):
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False, separators=(",", ":")) for r in rows) + "\n")


def test_classify_cmd():
    assert D.classify_cmd("git add -A && git commit -m x && git push origin main") == "push"
    assert D.classify_cmd("git -C /w/p push") == "push"
    assert D.classify_cmd("git push --dry-run") == ""
    assert D.classify_cmd("gh pr create --fill") == "pr"
    assert D.classify_cmd("vercel --prod") == "deploy"
    assert D.classify_cmd("./scripts/deploy_prod.sh") == "deploy"
    assert D.classify_cmd("rsync -av dist/ root@1.2.3.4:/srv/www") == "deploy"
    assert D.classify_cmd("git commit -m 'wip'") == "commit"
    assert D.classify_cmd("grep -r 'git push' docs") == ""
    assert D.classify_cmd("git status && git log") == ""


def _a(ts, kind, ok=True):
    return {"ts": ts, "kind": kind, "ok": ok, "detail": kind}


def test_judge_rules():
    t = datetime(2026, 10, 30, 10)
    m = lambda n: t + timedelta(minutes=n)  # noqa: E731
    assert D.judge([_a(m(0), "code"), _a(m(5), "commit"), _a(m(6), "push")])["status"] == "delivered"
    assert D.judge([_a(m(0), "code"), _a(m(6), "push"), _a(m(9), "code")])["status"] == "changed_after"
    assert D.judge([_a(m(0), "code"), _a(m(5), "commit")])["status"] == "committed"
    assert D.judge([_a(m(0), "code"), _a(m(5), "commit"), _a(m(7), "code")]) is None
    assert D.judge([_a(m(0), "code"), _a(m(6), "push", ok=False)]) is None
    j = D.judge([_a(m(0), "doc"), _a(m(3), "doc")])
    assert j["status"] == "delivered" and j["kind"] == "doc"
    assert D.judge([_a(m(0), "doc"), _a(m(1), "code")]) is None  # 改了代码又没提交：不算
    assert D.judge([_a(m(0), "code"), _a(m(2), "publish")])["labels"] == ["发布页面"]


def _c(ts, typ, **kw):
    return {"type": typ, "timestamp": ts.astimezone().isoformat(), "cwd": "/w/proj", "sessionId": "s", **kw}


def test_scan_claude_and_codex(tmp_path):
    now = datetime.now().replace(microsecond=0)
    t0 = max(now - timedelta(minutes=50), now.replace(hour=0, minute=0, second=1))  # 刚过零点时也落在今天
    proj = tmp_path / "claude" / "-w-proj"
    proj.mkdir(parents=True)
    use = lambda i, name, inp: _c(t0, "assistant", message={"content": [{"type": "tool_use", "id": i, "name": name, "input": inp}], "stop_reason": "tool_use"})  # noqa: E731
    res = lambda i, text, err=False: _c(t0, "user", message={"role": "user", "content": [{"type": "tool_result", "tool_use_id": i, "content": text, "is_error": err}]})  # noqa: E731
    _w(proj / "a.jsonl", [
        _c(t0, "user", message={"role": "user", "content": "修登录 bug 并上线"}),
        use("1", "Edit", {"file_path": "/w/proj/app.py"}), res("1", "ok"),
        use("2", "Bash", {"command": "git commit -am fix && git push"}), res("2", "To github.com:x/y.git\n  a..b  main -> main"),
        _c(t0, "assistant", message={"content": [{"type": "text", "text": "已推送"}], "stop_reason": "end_turn"}),
    ])
    _w(proj / "b.jsonl", [  # 推送被拒
        _c(t0, "user", message={"role": "user", "content": "推一下"}),
        use("3", "Bash", {"command": "git push"}), res("3", "! [rejected] main -> main (fetch first)", True),
        _c(t0, "assistant", message={"content": [{"type": "text", "text": "被拒了"}], "stop_reason": "end_turn"}),
    ])
    doc = tmp_path / "report.md"
    doc.write_text("# r")
    cx = tmp_path / "codex" / f"{now:%Y}" / f"{now:%m}" / f"{now:%d}"
    cx.mkdir(parents=True)
    ts = t0.astimezone().isoformat()
    _w(cx / "rollout-x.jsonl", [
        {"timestamp": ts, "type": "session_meta", "payload": {"id": "cx1", "cwd": "/w/notes", "originator": "codex_tui"}},
        {"timestamp": ts, "type": "event_msg", "payload": {"type": "user_message", "message": "写一份调研报告"}},
        {"timestamp": ts, "type": "event_msg", "payload": {"type": "item_completed", "item": {"type": "FileChange", "changes": {str(doc): {"type": "add"}}}}},
        {"timestamp": ts, "type": "event_msg", "payload": {"type": "task_complete", "last_agent_message": "报告写好了"}},
    ])
    out = D.scan({"claude": [str(tmp_path / "claude")], "codex": [str(tmp_path / "codex")]}, now.date(), now=now)
    by = {x["project"]: x for x in out}
    assert set(by) == {"proj", "notes"}
    assert by["proj"]["status"] == "delivered" and by["proj"]["labels"] == ["推送"]
    assert by["notes"]["kind"] == "doc" and by["notes"]["docs"] == [str(doc)]
