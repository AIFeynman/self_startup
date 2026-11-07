from app import db
from app.modules import _review_sessions as rs, review

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


def _add(client, category, start, end, output=""):
    r = client.post("/api/review/time-entries", json={"date": DAY, "category": category, "start": start, "end": end, "output": output})
    assert r.status_code == 200
    return r.json()["id"]


def test_minutes_fragment_blocks_and_blanks(client):
    a = [f"09:{m:02d}" for m in range(0, 31, 5)]
    _seed(DAY, [_session("proj-a", *a), _session("proj-b", "10:00", "10:05"),
                {**_session("cron", "10:30"), "automated": True}])
    h = _human(client)
    assert h["minutes"] == 37 and h["whole_min"] == 31 and h["fragment_pct"] == 16
    assert [(b["project"], b["start"], b["end"], b["whole"]) for b in h["blocks"]] == [
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
