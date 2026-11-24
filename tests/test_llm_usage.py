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



def test_usage_daily_groups_by_kind_and_module(client):
    day = "2026-10-05"
    for module, ref, engine, cost in (("learn", "job:1", "claude", 1.0), ("learn", "job:2", "claude", 0.5), ("chat:plan", "chat:3", "claude", 0.2),
                                      ("xart", "", "claude", 0.01), ("intel", "", "deepseek", 0.002)):
        db.insert("llm_usage", {"at": f"{day}T10:00:00", "module": module, "ref": ref, "engine": engine, "model": "m",
                                "input_tokens": 10, "output_tokens": 5, "cache_read": 100, "cache_write": 1, "cost_usd": cost})
    db.insert("llm_usage", {"at": "2026-10-09T10:00:00", "module": "learn", "ref": "job:9", "engine": "claude", "cost_usd": 9})
    r = client.get("/api/usage", params={"start": day, "end": day}).json()
    got = {(x["day"], x["kind"], x["module"]): (x["calls"], round(x["cost_usd"], 3), x["output_tokens"]) for x in r["rows"]}
    assert got == {(day, "job", "learn"): (2, 1.5, 10), (day, "chat", "chat:plan"): (1, 0.2, 5),
                   (day, "light", "xart"): (1, 0.01, 5), (day, "deepseek", "intel"): (1, 0.002, 5)}
    assert r["since"] <= day


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


# ---------- 以前漏记的调用 ----------

def _mock(body):
    import httpx
    return httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200, json=body)))


def _fresh():
    db.execute("DELETE FROM llm_usage")


DS_REPLY = {"model": "deepseek-v4-flash", "usage": {"prompt_tokens": 1000, "prompt_cache_hit_tokens": 400, "completion_tokens": 50}}


def test_run_once_records_usage_under_its_module(client, monkeypatch):
    _fresh()
    def fake_stream(prompt, **kw):
        assert "module" not in kw
        yield {"type": "done", "text": "ok", "engine": "claude", "usage": usage.from_claude(CLAUDE_JSON)}

    monkeypatch.setattr(agent, "run_stream", fake_stream)
    assert agent.run_once("p", module="notes")["text"] == "ok"
    [r] = rows("notes")
    assert r["engine"] == "claude" and r["output_tokens"] == 20 and r["ref"] == ""


def test_feed_deepseek_calls_are_recorded(client, monkeypatch):
    _fresh()
    from app.modules import _feed_product as pa, _feed_topics as tp
    monkeypatch.setenv("DEEPSEEK_API_KEY", "k")
    item = {"id": "ph:1", "title": "t", "summary": "s", "extra": {}}
    pa.generate([item], client=_mock({**DS_REPLY, "choices": [{"message": {"content": '{"items": []}'}}]}))
    tp.suggest(["a", "b", "c"], [], [], client=_mock({**DS_REPLY, "choices": [{"message": {"content": '{"topics": []}'}}]}))
    rs = rows("feed")
    assert len(rs) == 2 and {r["engine"] for r in rs} == {"deepseek"}
    assert rs[0]["input_tokens"] == 600 and rs[0]["cache_read"] == 400 and rs[0]["output_tokens"] == 50 and rs[0]["cost_usd"] > 0


def test_jev_calls_are_recorded_per_batch_and_module(client, monkeypatch):
    _fresh()
    from app.modules import _feed_judge as judge
    monkeypatch.setenv("JEV_API_KEY", "k")
    item = {"id": "github:a/x", "source": "github", "title": "x", "summary": "", "extra": {}}
    reply = {"answers": {"i0_ai": {"noul": 0.9}}, "usage": {"input_tokens": 300, "output_tokens": 4}}
    judge.judge([(item, "ai", "")], client=_mock(reply))
    judge.judge([(item, "ai", "")], client=_mock({"answers": {}}), module="people")
    [f] = rows("feed")
    assert (f["engine"], f["model"], f["input_tokens"], f["output_tokens"]) == ("jev", "jev-latest", 300, 4)
    [p] = rows("people")
    assert p["engine"] == "jev" and p["input_tokens"] == 0


def test_voice_search_and_spoken_summary_are_recorded(client, monkeypatch):
    _fresh()
    import httpx
    from app import voice_rt
    monkeypatch.setenv("DEEPSEEK_API_KEY", "k")

    def post(url, **kw):
        body = {"results": [{"title": "t"}]} if url.endswith("/tools/search") else {**DS_REPLY, "choices": [{"message": {"content": "念"}}]}
        return httpx.Response(200, json=body, request=httpx.Request("POST", url))
    monkeypatch.setattr(httpx, "post", post)
    found = voice_rt.web_search("天气")
    voice_rt.spoken_search("天气", found)
    models = sorted(r["model"] for r in rows("voice"))
    assert models == ["deepseek-search", "deepseek-v4-flash"]


def test_bailian_realtime_response_is_recorded_in_dollars(client, monkeypatch, tmp_path):
    _fresh()
    from app import voice_record
    monkeypatch.setattr(voice_record, "CALLS_DIR", tmp_path)
    rec = voice_record.Recorder()
    rec.open("qwen-audio-3.1-realtime-flash", "v")
    rec.usage({"input_tokens_details": {"text_tokens": 1000, "audio_tokens": 0}, "output_tokens_details": {"text_tokens": 0, "audio_tokens": 1000}})
    rec.close_files()
    [r] = rows("voice")
    assert (r["engine"], r["model"], r["input_tokens"], r["output_tokens"]) == ("bailian", "qwen-audio-3.1-realtime-flash", 1000, 1000)
    yuan = voice_record.cost_of({"input_text": 1000, "output_audio": 1000})
    assert abs(r["cost_usd"] - yuan * usage.USD_PER_CNY) < 1e-12


def test_usage_daily_puts_other_apis_in_their_own_kind(client):
    _fresh()
    day = "2026-10-06"
    for engine in ("jev", "bailian"):
        db.insert("llm_usage", {"at": f"{day}T10:00:00", "module": "feed", "engine": engine, "model": "m", "input_tokens": 1})
    r = client.get("/api/usage", params={"start": day, "end": day}).json()
    assert {x["kind"] for x in r["rows"]} == {"api"} and r["rows"][0]["calls"] == 2
