from datetime import date, datetime, timedelta

from app.modules import _utilization as U


def _ev(kind, ts, **kw):
    return {"kind": kind, "ts": ts, **kw}


def test_session_timeline_active_wait_and_humans():
    d = date(2026, 1, 5)
    t = datetime(2026, 1, 5, 9, 0)
    events = [
        _ev("human", t, text="实现登录"),
        _ev("agent", t + timedelta(minutes=1), tool="Bash"),
        _ev("agent", t + timedelta(minutes=30)),          # 长命令：工具调用后 29 分钟仍算在干活
        _ev("agent", t + timedelta(minutes=31), end=True),
        _ev("human", t + timedelta(minutes=71), text="不对，应该用 JWT"),   # 等了 40 分钟
        _ev("agent", t + timedelta(minutes=72)),
        _ev("agent", t + timedelta(minutes=100)),         # 普通间隔 28 分钟 > WORK_GAP：不算干活
    ]
    tl = U.session_timeline({"engine": "claude", "session_id": "s", "file": "/x/p/s.jsonl", "cwd": "/w/proj"}, events, d)
    assert tl["active"] == [(t, t + timedelta(minutes=31)), (t + timedelta(minutes=71), t + timedelta(minutes=72))]
    assert tl["waits"] == [(t + timedelta(minutes=31), t + timedelta(minutes=71))]
    assert [h["kind"] for h in tl["humans"]] == ["new_task", "correct"]


def test_analyze_gaps_focus_and_advice(monkeypatch):
    d = date(2026, 1, 5)
    t = datetime(2026, 1, 5, 9, 0)
    tl = {"engine": "claude", "session_id": "s", "automated": False, "project": "proj", "title": "登录",
          "active": [(t, t + timedelta(minutes=60))], "waits": [(t + timedelta(minutes=60), t + timedelta(minutes=110))],
          "humans": [{"ts": t, "kind": "new_task", "text": "a"}, {"ts": t + timedelta(minutes=110), "kind": "correct", "text": "b"}]}
    monkeypatch.setattr(U, "_files", lambda *a: [("x", None)])
    monkeypatch.setattr(U, "_read", lambda *a: ({}, []))
    monkeypatch.setattr(U, "session_timeline", lambda *a: tl)
    r = U.analyze(d, {}, [{"start": "10:00", "end": "11:40"}], "09:00", "12:00", 2, now=datetime(2026, 1, 6))
    s = r["summary"]
    assert s["coverage_pct"] == 33 and s["capacity_pct"] == 17       # 1 小时 / 3 小时；1 个 / 上限 2
    assert r["gaps"] == [{"start": "10:00", "end": "12:00", "minutes": 120, "in_focus": 100}]
    assert s["human_total"] == 2 and s["human_out_focus"] == 1        # 09:00 在专注外，10:50 在专注内
    assert s["wait_total_min"] == 50 and s["idle_focus_min"] == 100
    assert any("空档" in a for a in r["advice"]) and any("专注时间里" in a for a in r["advice"])


def _tl(sid, active=(), waits=(), humans=(), automated=False):
    return {"engine": "claude", "session_id": sid, "automated": automated, "project": "proj", "title": sid,
            "active": list(active), "waits": list(waits), "humans": [{"ts": h, "kind": "new_task", "text": ""} for h in humans]}


def _run(monkeypatch, tls, now, day_start="08:30", day_end="23:00", conc=3, focus=(), day=None):
    it = iter(tls)
    monkeypatch.setattr(U, "_files", lambda *a: [("x", None)] * len(tls))
    monkeypatch.setattr(U, "_read", lambda *a: ({}, []))
    monkeypatch.setattr(U, "session_timeline", lambda *a: next(it))
    return U.analyze(day or now.date(), {}, list(focus), day_start, day_end, conc, now=now)["summary"]


def test_overnight_activity_before_day_start_is_not_zero_coverage(monkeypatch):
    """复现「Agent 覆盖 0% 但等你 451 分钟」：工作时间（08:30）还没开始，凌晨真实在用。"""
    t = datetime(2026, 10, 30, 0, 0)
    a = _tl("a", active=[(t, t + timedelta(hours=2))], waits=[(t + timedelta(hours=2), t + timedelta(hours=4))],
            humans=[t, t + timedelta(hours=4)])
    b = _tl("b", active=[(t + timedelta(hours=1), t + timedelta(hours=2))], waits=[(t + timedelta(hours=2), t + timedelta(hours=4))],
            humans=[t + timedelta(hours=1), t + timedelta(hours=4)])
    s = _run(monkeypatch, [a, b], now=datetime(2026, 10, 30, 7, 9))
    assert s["work_elapsed_min"] == 0 and s["coverage_work_pct"] == 0
    assert s["elapsed_min"] == 250                                  # 0:00–4:10（活跃 + 等待 + 最后一条消息后的时间片）
    assert s["coverage_pct"] == 48                                  # 120 / 250
    assert s["wait_total_min"] == 240 and s["wait_wall_min"] == 120  # 两个会话同时等：累加 240 Agent·分钟，墙钟 120
    assert s["wait_wall_min"] <= s["elapsed_min"] and s["coverage_pct"] > 0
    assert s["peak_parallel"] == 2 and s["agent_active_min"] == 180 and s["agent_active_wall_min"] == 120


def test_exact_minutes_not_slot_rounding(monkeypatch):
    """10 分钟时间片里只跑 3 分钟，不能算成整片在跑；同片但不重叠的两个会话不算并行。"""
    t = datetime(2026, 1, 5, 9, 0)
    a = _tl("a", active=[(t + timedelta(minutes=10 * i), t + timedelta(minutes=10 * i + 3)) for i in range(6)])
    b = _tl("b", active=[(t + timedelta(minutes=10 * i + 5), t + timedelta(minutes=10 * i + 8)) for i in range(6)])
    s = _run(monkeypatch, [a, b], now=datetime(2026, 1, 6), day_start="09:00", day_end="10:00", conc=2, day=t.date())
    assert s["coverage_pct"] == 60 and s["coverage_work_pct"] == 60   # 36 / 60 分钟
    assert s["capacity_pct"] == 30 and s["peak_parallel"] == 1


def test_today_only_counts_until_now(monkeypatch):
    t = datetime(2026, 1, 5, 9, 0)
    a = _tl("a", active=[(t, t + timedelta(minutes=30))])
    s = _run(monkeypatch, [a], now=datetime(2026, 1, 5, 10, 0), day_start="09:00", day_end="18:00")
    assert s["elapsed_min"] == 60 and s["coverage_pct"] == 50


def test_wait_focus_uses_wall_clock(monkeypatch):
    t = datetime(2026, 1, 5, 10, 0)
    w = [(t, t + timedelta(minutes=30))]
    s = _run(monkeypatch, [_tl("a", waits=w, humans=[t + timedelta(minutes=30)]), _tl("b", waits=w, humans=[t + timedelta(minutes=30)])],
             now=datetime(2026, 1, 6), day_start="09:00", day_end="12:00", focus=[{"start": "10:00", "end": "11:00"}], day=t.date())
    assert s["wait_focus_min"] == 30 and s["wait_total_min"] == 60


def test_snapshot_taken_during_the_day_is_recomputed(monkeypatch):
    """当天算的快照（只有半天数据）和旧口径快照，过了那天都要重算，不能当最终结果缓存。"""
    import json
    from app import db
    from app.modules import agents
    db.init([agents.SCHEMA])
    calls = []
    monkeypatch.setattr(agents.util, "analyze", lambda d, *a, **k: calls.append(d) or {"summary": {"v": U.VERSION, "sessions": 1}, "slots": []})
    import time as _t
    put = lambda day, upd, v, tz=None: db.execute(  # noqa: E731
        "INSERT INTO agent_util(date,summary,data,updated_at) VALUES (?,?,?,?) ON CONFLICT(date) DO UPDATE SET "
        "summary=excluded.summary, updated_at=excluded.updated_at", [day, json.dumps({"v": v, "tz": tz or _t.tzname[0]}), "{}", upd])
    put("2020-01-01", "2020-01-01T21:30:00", U.VERSION)       # 当天算的：重算
    agents.utilization("2020-01-01")
    put("2020-01-02", "2020-01-03T08:00:00", U.VERSION - 1)   # 旧口径：重算
    agents.utilization("2020-01-02")
    put("2020-01-03", "2020-01-04T08:00:00", U.VERSION)       # 当天结束后、当前口径：用缓存
    assert agents.utilization("2020-01-03")["cached"]
    put("2020-01-04", "2020-01-05T08:00:00", U.VERSION, "XYZ")  # 别的时区算的：重算
    agents.utilization("2020-01-04")
    assert [d.isoformat() for d in calls] == ["2020-01-01", "2020-01-02", "2020-01-04"]


def test_timezone_setting_shifts_local_clock_and_bad_name_is_ignored():
    import time as _t
    from app import settings
    system = settings.apply_timezone("")
    try:
        assert settings.apply_timezone("Asia/Shanghai") in ("CST", "+08")
        assert _t.localtime(0).tm_hour == 8
        assert settings.apply_timezone("Not/AZone") == system   # 写错：回到系统时区，而不是静默变成 UTC
    finally:
        settings.apply_timezone("")


def test_timezone_mismatch_advice(monkeypatch):
    """人工交互大多落在工作时间外 → 提示检查时区（真实数据里系统是 America/Los_Angeles，人在 UTC+8）。"""
    t = datetime(2026, 1, 5, 0, 30)
    hs = [t + timedelta(minutes=5 * i) for i in range(30)]       # 00:30–02:55，全在 08:30–23:00 之外
    s = _run(monkeypatch, [_tl("a", active=[(t, t + timedelta(hours=2))], humans=hs)], now=datetime(2026, 1, 6), day=t.date())
    assert s["human_in_work"] == 0
    it = iter([_tl("a", active=[(t, t + timedelta(hours=2))], humans=hs)])
    monkeypatch.setattr(U, "session_timeline", lambda *a: next(it))
    r = U.analyze(t.date(), {}, [], "08:30", "23:00", 3, now=datetime(2026, 1, 6))
    assert any("时区" in a for a in r["advice"])
