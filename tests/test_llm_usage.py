import json
import subprocess
from datetime import datetime

from app import agent, db, jobs, usage

CLAUDE_JSON = {"result": "[]", "is_error": False, "total_cost_usd": 0.0123,
               "usage": {"input_tokens": 100, "output_tokens": 20, "cache_read_input_tokens": 300, "cache_creation_input_tokens": 40},
               "modelUsage": {"claude-haiku-5-5": {"provider": "firstParty"}}}


def fake_run(seen):
    def run(cmd, **kw):
        seen.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, json.dumps(CLAUDE_JSON), "")
    return run


def rows(module):
    return db.rows("SELECT * FROM llm_usage WHERE module=?", [module])


def test_light_calls_disable_user_hooks_and_record_usage(client, monkeypatch):
    from app.modules import _oss_label, _paper_label
    seen = []
    monkeypatch.setattr(subprocess, "run", fake_run(seen))
    _paper_label._claude("sys", "user", 100, False, module="xart")
    _oss_label._cli("prompt")
    for cmd in seen:
        assert json.loads(cmd[cmd.index("--settings") + 1]) == {"disableAllHooks": True}
    [r] = rows("xart")
    assert (r["input_tokens"], r["output_tokens"], r["cache_read"], r["cache_write"]) == (100, 20, 300, 40)
    assert r["model"] == "claude-haiku-5-5" and abs(r["cost_usd"] - 0.0123) < 1e-9
    assert len(rows("oss")) == 1


def test_stream_done_event_carries_summed_usage():
    lines = [json.dumps({"type": "result", "result": "a", "session_id": "s", **CLAUDE_JSON}),
             json.dumps({"type": "result", "result": "", "session_id": "s", **CLAUDE_JSON})]

    class Proc:
        stdout = iter(line + "\n" for line in lines)
        stderr = None
        returncode = 0

        def wait(self):
            return 0

    done = [ev for ev in agent._read("claude", Proc(), agent._parse_claude) if ev["type"] == "done"][0]
    assert done["usage"]["input_tokens"] == 200 and done["usage"]["output_tokens"] == 40
    assert abs(done["usage"]["cost_usd"] - 0.0246) < 1e-9


def test_job_records_usage(client, monkeypatch):
    def fake_stream(prompt, **kw):
        yield {"type": "done", "text": "ok", "engine": "claude", "usage": usage.from_claude(CLAUDE_JSON)}

    monkeypatch.setattr(agent, "run_stream", fake_stream)
    jid = db.insert("jobs", {"module": "learn", "ref": "learn:item:1", "engine": "claude", "prompt": "p", "status": "queued", "created_at": db.now()})
    jobs._run(jid, "learn", "p", "claude", "", None, [])
    [r] = rows("learn")
    assert r["ref"] == f"job:{jid}" and r["engine"] == "claude" and r["output_tokens"] == 20
    s = client.get("/api/usage", params={"days": 1}).json()
    assert {"module": "learn", "calls": 1} in [{"module": m["module"], "calls": m["calls"]} for m in s["by_module"]]
    assert sum(d["calls"] for d in s["by_day"]) == len(db.rows("SELECT id FROM llm_usage"))


def _stub_xart(x, monkeypatch, rel):
    ok = {"todo": 0, "miss": 0, "err": 0}
    monkeypatch.setattr(x, "crawl_since", lambda now: {"calls": 400})
    monkeypatch.setattr(x, "gate", lambda: {})
    monkeypatch.setattr(x, "grab_ids", lambda: [])
    monkeypatch.setattr(x, "grab", lambda **k: {"ok": 10, "drop": 2})
    monkeypatch.setattr(x, "stale", lambda: 0)
    monkeypatch.setattr(x, "dedupe", lambda: {})
    monkeypatch.setattr(x, "relevance", lambda **k: rel)
    monkeypatch.setattr(x, "fulltext", lambda **k: {"ok": 3, "short": 0, "failed": 0})
    monkeypatch.setattr(x, "score", lambda **k: ok)


def test_xart_failed_run_still_counts_paid_calls(client, monkeypatch):
    from app.modules import _xart as x
    x.init()
    _stub_xart(x, monkeypatch, {"todo": 40, "miss": 40, "err": 0})
    try:
        x.daily(datetime(2026, 12, 17, 5, 0))
    except RuntimeError:
        pass
    run = db.row("SELECT status, calls FROM x_art_run WHERE day='2026-12-17'")
    assert run == {"status": "failed", "calls": 412}
    assert x._month_calls("2026-12-17") == 412


def test_xart_orphaned_running_row_is_reaped_on_start(client, monkeypatch):
    from app.modules import _xart as x
    x.init()
    rid = db.insert("x_art_run", {"day": datetime.now().strftime("%Y-%m-%d"), "status": "running", "started": db.now()})
    monkeypatch.setattr(x, "daily", lambda: None)
    x.start()
    assert db.row("SELECT status FROM x_art_run WHERE id=?", [rid])["status"] == "interrupted"
    assert x.due(datetime.now().replace(hour=23))
