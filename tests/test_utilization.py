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
