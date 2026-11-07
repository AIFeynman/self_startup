from app import db
from app.modules import _read_log, _review_sessions as rs, review

DAY = "2026-03-10"
PREV = "2026-03-09"


def _session(project, *times):
    return {"project": project, "automated": False, "messages": [{"t": t, "kind": "new_task", "text": "继续"} for t in times]}


def _seed(date, sessions):
    review._upsert_stats(date, {"summary": {"v": rs.VERSION}, "sessions": sessions, "scanned_at": "2026-03-11T00:00:00"})


def _human(client, date=DAY):
    r = client.get(f"/api/review/human?date={date}")
    assert r.status_code == 200
    return r.json()


def _add(client, category, start, end, output="", date=DAY):
    r = client.post("/api/review/time-entries", json={"date": date, "category": category, "start": start, "end": end, "output": output})
    assert r.status_code == 200
    return r.json()["id"]


def test_minutes_fragment_blocks_and_blanks(client):
    a = [f"09:{m:02d}" for m in range(0, 31, 5)]
    _seed(DAY, [_session("proj-a", *a), _session("proj-b", "10:00", "10:05"),
                {**_session("cron", "10:30"), "automated": True}])
    h = _human(client)
    assert h["minutes"] == 37 and h["whole_min"] == 31 and h["fragment_pct"] == 16
    assert [(s["label"], s["start"], s["end"], s["whole"]) for s in h["segments"]] == [
        ("proj-a", "09:00", "09:31", True), ("proj-b", "10:00", "10:06", False)]
    assert h["blanks"] == [{"start": "09:31", "end": "10:00", "minutes": 29}]


def test_manual_records_fill_blanks_and_only_work_counts(client):
    _seed(DAY, [_session("proj-a", *[f"09:{m:02d}" for m in range(0, 31, 5)]), _session("proj-b", "10:00", "10:05")])
    meal = _add(client, "吃饭", "09:31", "10:00", "午饭")
    h = _human(client)
    assert h["blanks"] == [] and h["minutes"] == 37
    assert [(e["category"], e["start"], e["end"], e["output"]) for e in h["entries"]] == [("吃饭", "09:31", "10:00", "午饭")]

    work = _add(client, "开发", "11:00", "12:00")
    h = _human(client)
    assert h["minutes"] == 97 and h["whole_min"] == 91 and h["fragment_pct"] == 6
    assert h["blanks"][-1] == {"start": "10:06", "end": "11:00", "minutes": 54}

    for i in (meal, work):
        assert client.delete(f"/api/review/time-entries/{i}").status_code == 200
    assert _human(client)["minutes"] == 37 and _human(client)["entries"] == []


def test_editing_a_record_keeps_history(client):
    _seed(DAY, [])
    old = _add(client, "学习", "14:00", "14:30", "读论文")
    r = client.put(f"/api/review/time-entries/{old}", json={"date": DAY, "category": "学习", "start": "14:00", "end": "15:00", "output": "读完论文"})
    assert r.status_code == 200
    new = r.json()["id"]
    h = _human(client)
    assert [(e["id"], e["end"], e["output"]) for e in h["entries"]] == [(new, "15:00", "读完论文")]
    assert h["minutes"] == 60
    assert db.row("SELECT output FROM review_time_entries WHERE id=?", [old])["output"] == "读论文"
    assert client.delete(f"/api/review/time-entries/{new}").status_code == 200
    assert db.row("SELECT output FROM review_time_entries WHERE id=?", [new])["output"] == "读完论文"
    assert _human(client)["entries"] == []


def test_rejects_unknown_category_and_bad_time(client):
    for body in ({"category": "摸鱼", "start": "09:00", "end": "10:00"}, {"category": "开发", "start": "9点", "end": "10:00"},
                 {"category": "开发", "start": "10:00", "end": "10:00"}):
        assert client.post("/api/review/time-entries", json={"date": DAY, **body}).status_code == 400


def test_sleep_can_cross_midnight(client):
    _seed(DAY, [])
    i = _add(client, "睡觉", "23:30", "07:00")
    e = _human(client)["entries"][0]
    assert (e["start"], e["end"]) == ("23:30", "07:00")
    assert _human(client)["minutes"] == 0
    client.delete(f"/api/review/time-entries/{i}")


def test_trend_covers_seven_days_ending_on_the_date(client):
    _seed(DAY, [_session("proj-a", "09:00", "09:05")])
    _seed(PREV, [_session("proj-a", *[f"09:{m:02d}" for m in range(0, 31, 5)])])
    trend = _human(client)["trend"]
    assert [t["date"] for t in trend][-2:] == [PREV, DAY] and len(trend) == 7
    assert (trend[-2]["minutes"], trend[-2]["fragment_pct"]) == (31, 0)
    assert (trend[-1]["minutes"], trend[-1]["fragment_pct"]) == (6, 100)
    assert trend[0]["minutes"] is None


def test_segments_say_what_each_period_was_and_totals_by_type(client):
    day = "2026-02-01"
    _seed(day, [_session("proj-a", *[f"09:{m:02d}" for m in range(0, 31, 5)]), _session("proj-b", "09:40")])
    _add(client, "学习", "14:00", "15:00", "读论文", day)
    _add(client, "吃饭", "12:00", "12:30", "午饭", day)
    h = _human(client, day)
    assert [(s["start"], s["end"], s["type"], s["label"], s["whole"]) for s in h["segments"]] == [
        ("09:00", "09:31", "开发", "proj-a", True),
        ("09:31", "09:40", "开发", "proj-a", False),
        ("09:40", "09:41", "开发", "proj-b", False),
        ("12:00", "12:30", "吃饭", "午饭", False),
        ("14:00", "15:00", "学习", "读论文", True),
    ]
    assert h["by_type"]["开发"] == 41 and h["by_type"]["学习"] == 60 and h["by_type"]["吃饭"] == 30
    assert h["by_type"]["运动"] == 0
    assert h["minutes"] == 101 and h["whole_min"] == 91 and h["fragment_min"] == 10


def test_reading_and_learning_activity_count_as_learning(client):
    day = "2026-02-03"
    _seed(day, [])
    _read_log._ensure()
    db.insert("read_log", {"kind": "feed", "ref": "learning-activity", "title": "", "url": "", "source": "", "at": f"{day}T08:00:00"})
    h = _human(client, day)
    assert [(s["type"], s["label"]) for s in h["segments"]] == [("学习", "阅读")]
    assert h["by_type"]["学习"] == 1


def test_manual_record_wins_over_activity_in_the_same_minutes(client):
    day = "2026-02-05"
    _seed(day, [_session("proj-a", *[f"09:{m:02d}" for m in range(0, 31, 5)])])
    _add(client, "运动", "09:10", "09:20", "跑步", day)
    h = _human(client, day)
    assert [(s["start"], s["end"], s["type"]) for s in h["segments"]] == [
        ("09:00", "09:10", "开发"), ("09:10", "09:20", "运动"), ("09:20", "09:31", "开发")]
    assert h["minutes"] == 21 and h["by_type"] == {**h["by_type"], "开发": 21, "运动": 10}


def test_overnight_sleep_shows_on_both_days(client):
    night, morning = "2026-02-07", "2026-02-08"
    _add(client, "睡觉", "23:30", "07:00", "", night)
    _seed(morning, [])
    assert [(s["start"], s["end"], s["type"]) for s in _human(client, night)["segments"]] == [("23:30", "24:00", "睡觉")]
    h = _human(client, morning)
    assert [(s["start"], s["end"], s["type"]) for s in h["segments"]] == [("00:00", "07:00", "睡觉")]
    assert h["by_type"]["睡觉"] == 420 and h["entries"] == [] and h["minutes"] == 0


def _at(monkeypatch, moment):
    monkeypatch.setattr(db, "now", lambda: moment)


def _away(client):
    r = client.get("/api/review/away")
    assert r.status_code == 200
    return r.json()


def _leave_and_return(client, monkeypatch, left, back):
    _at(monkeypatch, left)
    assert client.post("/api/review/away/start").status_code == 200
    _at(monkeypatch, back)
    r = client.post("/api/review/away/back")
    assert r.status_code == 200
    return r.json()


def _drop_entries(client, date):
    for e in _human(client, date)["entries"]:
        client.delete(f"/api/review/time-entries/{e['id']}")


def test_away_button_records_the_exact_period_with_type_and_gain(client, monkeypatch):
    day = "2026-04-01"
    _seed(day, [])
    assert _away(client) is None

    _at(monkeypatch, f"{day}T15:04:30")
    assert client.post("/api/review/away/start").status_code == 200
    _at(monkeypatch, f"{day}T15:10:30")
    a = _away(client)
    assert a["started_at"] == f"{day}T15:04:30" and a["ended_at"] is None and a["seconds"] == 360

    _at(monkeypatch, f"{day}T15:49:10")
    assert client.post("/api/review/away/back").json()["ended_at"] == f"{day}T15:49:10"
    _at(monkeypatch, f"{day}T18:00:00")
    assert _away(client)["seconds"] == 2680

    r = client.post("/api/review/away/submit", json={"category": "思考复盘", "output": "想清楚了指标口径"})
    assert r.status_code == 200 and r.json()["date"] == day
    assert _away(client) is None
    h = _human(client, day)
    assert [(e["category"], e["start"], e["end"], e["output"]) for e in h["entries"]] == [("思考复盘", "15:04", "15:49", "想清楚了指标口径")]
    assert h["minutes"] == 45
    _drop_entries(client, day)


def test_away_survives_repeat_clicks_and_keeps_the_first_time(client, monkeypatch):
    day = "2026-04-02"
    _at(monkeypatch, f"{day}T09:00:00")
    client.post("/api/review/away/start")
    _at(monkeypatch, f"{day}T09:30:00")
    assert client.post("/api/review/away/start").json()["started_at"] == f"{day}T09:00:00"
    client.post("/api/review/away/back")
    _at(monkeypatch, f"{day}T10:00:00")
    assert client.post("/api/review/away/back").json()["ended_at"] == f"{day}T09:30:00"
    assert client.delete("/api/review/away").status_code == 200
    assert _away(client) is None


def test_away_crossing_midnight_lands_on_both_days(client, monkeypatch):
    day, next_day = "2026-04-03", "2026-04-04"
    _seed(day, [])
    _seed(next_day, [])
    _leave_and_return(client, monkeypatch, f"{day}T23:50:00", f"{next_day}T00:20:00")
    r = client.post("/api/review/away/submit", json={"category": "学习", "output": ""})
    assert r.status_code == 200 and r.json()["date"] == day
    assert _human(client, day)["minutes"] == 10
    assert _human(client, next_day)["minutes"] == 20
    _drop_entries(client, day)


def test_away_too_short_or_forgotten_leaves_no_record(client, monkeypatch):
    day = "2026-04-05"
    _seed(day, [])
    too_short = _leave_and_return(client, monkeypatch, f"{day}T09:00:05", f"{day}T09:00:50")
    assert "不足 1 分钟" in too_short["discarded"] and _away(client) is None
    forgotten = _leave_and_return(client, monkeypatch, f"{day}T09:00:00", "2026-04-06T09:00:00")
    assert "超过 24 小时" in forgotten["discarded"] and _away(client) is None
    assert _human(client, day)["entries"] == []


def test_away_rejects_steps_out_of_order_and_unknown_type(client, monkeypatch):
    day = "2026-04-07"
    assert client.post("/api/review/away/back").status_code == 404
    assert client.post("/api/review/away/submit", json={"category": "开发"}).status_code == 409
    _at(monkeypatch, f"{day}T09:00:00")
    client.post("/api/review/away/start")
    assert client.post("/api/review/away/submit", json={"category": "开发"}).status_code == 409
    _at(monkeypatch, f"{day}T10:00:00")
    client.post("/api/review/away/back")
    assert client.post("/api/review/away/submit", json={"category": "摸鱼"}).status_code == 400
    assert _away(client)["ended_at"] == f"{day}T10:00:00"
    assert client.post("/api/review/away/submit", json={"category": "开发"}).status_code == 200
    _seed(day, [])
    _drop_entries(client, day)
