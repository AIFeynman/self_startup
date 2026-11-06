"""已读：点开过的条目在信息推荐 / 产品雷达标已读，信息推荐可按已读筛选，历史按天进复盘。"""
import json
from datetime import datetime, timezone

import pytest

from app import db
from app.modules import _read_log, feed, intel

DAY = db.today()


def _item(id_, title="标题", url=""):
    return {"id": id_, "source": "hn", "type": "discussion", "title": title, "url": url or f"https://e.x/{id_}",
            "date": datetime.now(timezone.utc).isoformat(), "popularity": 100}


def _ids(client, query):
    return {x["id"] for x in client.get("/api/feed/items?limit=500&" + query).json()["items"]}


@pytest.fixture()
def fresh(client):
    db.execute("DELETE FROM read_log") if db.row("SELECT 1 FROM sqlite_master WHERE name='read_log'") else None
    db.execute("DELETE FROM feed_feedback")
    db.execute("DELETE FROM feed_items")
    db.execute("DELETE FROM learn_items")
    return client


def test_opened_item_shows_read_and_filters(fresh):
    feed.upsert([_item("hn:a"), _item("hn:b")])
    assert fresh.post("/api/feed/click", json={"id": "hn:a"}).status_code == 200
    by_id = {x["id"]: x for x in fresh.get("/api/feed/items?limit=500").json()["items"]}
    assert by_id["hn:a"]["read"] is True and by_id["hn:b"]["read"] is False
    assert _ids(fresh, "read=unread") == {"hn:b"}
    assert _ids(fresh, "read=read") == {"hn:a"}
    assert _ids(fresh, "") == {"hn:a", "hn:b"}
    assert fresh.get("/api/feed/items?read=bogus").status_code == 400


def test_saved_tab_keeps_read_items(fresh):
    feed.upsert([_item("hn:a")])
    fresh.post("/api/feed/click", json={"id": "hn:a"})
    fresh.post("/api/feed/feedback", json={"id": "hn:a", "saved": True})
    assert _ids(fresh, "saved=true&read=unread") == {"hn:a"}


def test_opened_deep_read_counts_as_read(fresh):
    feed.upsert([_item("hn:a", url="https://e.x/deep"), _item("hn:b")])
    db.insert("learn_items", {"kind": "article", "url": "https://e.x/deep", "title": "t", "status": "done", "opened_at": "2026-11-06T09:00:00"})
    assert _ids(fresh, "read=unread") == {"hn:b"}


def test_clicks_before_this_feature_count_as_read(fresh, monkeypatch):
    feed.upsert([_item("hn:old", title="以前点过的")])
    fresh.get("/api/feed/status")
    db.execute("INSERT INTO feed_feedback (item_id, clicks, last_click, updated_at) VALUES ('hn:old',3,'2026-10-20T09:00:00','')")
    db.execute("DROP TABLE IF EXISTS read_log")
    monkeypatch.setattr(_read_log, "_ready", False)
    assert _ids(fresh, "read=read") == {"hn:old"}
    day = fresh.get("/api/review/reads?start=2026-10-20&end=2026-10-20").json()
    assert [(x["title"], x["times"]) for d in day for x in d["items"]] == [("以前点过的", 1)]


def test_reopen_on_another_day_stays_in_both_days(fresh):
    feed.upsert([_item("hn:a", title="读两遍")])
    fresh.post("/api/feed/click", json={"id": "hn:a"})
    db.execute("UPDATE read_log SET at='2026-10-01T08:00:00'")
    fresh.post("/api/feed/click", json={"id": "hn:a"})
    fresh.post("/api/feed/click", json={"id": "hn:a"})
    days = fresh.get(f"/api/review/reads?start=2026-10-01&end={DAY}").json()
    assert [(d["date"], [x["times"] for x in d["items"]]) for d in days] == [(DAY, [2]), ("2026-10-01", [1])]
    today = fresh.get(f"/api/review/day?date={DAY}").json()["reads"]
    assert today[0]["title"] == "读两遍" and today[0]["url"] == "https://e.x/hn:a" and today[0]["source"]


def test_intel_event_read_shows_in_lists_and_review(fresh):
    db.execute("DELETE FROM intel_event")
    intel.seed()
    co = db.row("SELECT * FROM intel_company ORDER BY id LIMIT 1")
    eid = db.insert("intel_event", {"company_id": co["id"], "title": "发布新模型", "date": DAY, "level": "S", "level_auto": "S", "type": "launch"})
    flag = lambda: next(e for e in fresh.get("/api/intel/events?level=S").json()["events"] if e["id"] == eid)["read"]
    assert flag() is False
    assert fresh.post(f"/api/intel/events/{eid}/read").status_code == 200
    assert fresh.post("/api/intel/events/999999/read").status_code == 404
    assert flag() is True
    assert next(e for e in fresh.get(f"/api/intel/companies/{co['slug']}").json()["events"] if e["id"] == eid)["read"] is True
    x = fresh.get(f"/api/review/day?date={DAY}").json()["reads"][0]
    assert x["title"] == "发布新模型" and x["url"] == f"#intel/e/{eid}" and x["source"] == "产品雷达"


def test_ph_row_read_follows_feed_click(fresh):
    db.execute("DELETE FROM intel_ph_day")
    feed.upsert([_item("producthunt:1", url="https://www.producthunt.com/products/p1")])
    db.insert("intel_ph_day", {"date": DAY, "items": json.dumps([{"id": "producthunt:1", "url": "https://www.producthunt.com/products/p1", "title": "P1", "votes": 5}])})
    assert fresh.get("/api/intel/ph").json()[0]["items"][0]["read"] is False
    fresh.post("/api/feed/click", json={"id": "producthunt:1"})
    assert fresh.get("/api/intel/ph").json()[0]["items"][0]["read"] is True


def test_growth_case_read_survives_rewrite(fresh):
    for t in ("intel_growth_case", "intel_growth_item"):
        db.execute(f"DELETE FROM {t}")
    db.insert("intel_growth_item", {"id": "growth:1", "title": "增长素材", "url": "https://e.x/g", "status": "picked", "company": "Acme"})
    db.insert("intel_growth_case", {"item_id": "growth:1", "day": DAY, "status": "done"})
    assert fresh.get("/api/intel/growth").json()["cases"][0]["read"] is False
    assert fresh.post("/api/intel/growth/read", json={"item_id": "growth:1"}).status_code == 200
    assert fresh.post("/api/intel/growth/read", json={"item_id": "nope"}).status_code == 404
    new = db.insert("intel_growth_case", {"item_id": "growth:1", "day": DAY, "status": "done"})
    assert fresh.get("/api/intel/growth").json()["cases"][0]["read"] is True
    x = fresh.get(f"/api/review/day?date={DAY}").json()["reads"][0]
    assert x["title"] == "Acme · 增长素材" and x["source"] == "增长 Case" and x["url"].startswith("#intel/g/") and new
