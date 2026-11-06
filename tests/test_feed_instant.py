"""信息推荐秒开：翻页和切分类不重算全量排序，但用户的操作和新数据要立刻反映出来。"""
import json
import time
from datetime import datetime, timedelta, timezone

import pytest

from app import db, settings
from app.modules import feed


def _item(id_, title="some post", hours=1, pop=10, extra=None):
    return {"id": id_, "source": "hn", "type": "discussion", "title": title, "summary": "s",
            "url": f"https://e.x/{id_}", "date": (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(),
            "popularity": pop, "extra": extra or {}}


@pytest.fixture
def fresh(client):
    for t in ("feed_items", "feed_feedback", "read_log"):
        db.execute(f"DELETE FROM {t}") if db.row("SELECT 1 FROM sqlite_master WHERE name=?", [t]) else None
    yield client
    with feed._state_lock:
        feed._state["running"] = False


def _ids(c, query=""):
    return [x["id"] for x in c.get("/api/feed/items?limit=500&" + query).json()["items"]]


def _timed(c, query):
    t = time.perf_counter()
    assert c.get("/api/feed/items?" + query).status_code == 200
    return time.perf_counter() - t


def test_next_page_does_not_pay_for_ranking_again(fresh):
    feed.upsert([_item(f"hn:{i}", f"distinct headline number {i} about topic {i % 97}", hours=i % 500, pop=i) for i in range(3000)])
    first = _timed(fresh, "limit=40")
    later = min(_timed(fresh, f"limit=40&offset={off}") for off in (40, 80, 120))
    assert later < first / 3, f"首次 {first:.3f}s，翻页 {later:.3f}s"


def test_hide_and_vote_show_up_on_the_next_request(fresh):
    feed.upsert([_item("hn:a", "alpha story"), _item("hn:b", "beta story")])
    assert set(_ids(fresh)) == {"hn:a", "hn:b"}
    fresh.post("/api/feed/feedback", json={"id": "hn:a", "hidden": True})
    assert _ids(fresh) == ["hn:b"]
    fresh.post("/api/feed/feedback", json={"id": "hn:b", "vote": 1})
    assert fresh.get("/api/feed/items").json()["items"][0]["feedback"]["vote"] == 1
    assert _ids(fresh, "saved=true") == []
    fresh.post("/api/feed/feedback", json={"id": "hn:a", "saved": True})
    assert _ids(fresh, "saved=true") == ["hn:a"]


def test_new_items_and_patched_gist_show_up_on_the_next_request(fresh):
    feed.upsert([_item("hn:a", "alpha story")])
    assert _ids(fresh) == ["hn:a"]
    feed.upsert([_item("hn:b", "beta story")])
    assert set(_ids(fresh)) == {"hn:a", "hn:b"}
    feed._patch_extra("hn:a", {"gist": "一句话"})
    assert next(x for x in fresh.get("/api/feed/items").json()["items"] if x["id"] == "hn:a")["gist"] == "一句话"
    feed._patch_extra("hn:a", {"gist": "两句话"})
    assert next(x for x in fresh.get("/api/feed/items").json()["items"] if x["id"] == "hn:a")["gist"] == "两句话"


def test_new_interest_reranks_immediately(fresh):
    feed.upsert([_item("hn:a", "alpha story", pop=100), _item("hn:b", "zebra story", pop=1)])
    before = _ids(fresh)
    assert before[0] == "hn:a"
    old = list(settings.get("feed.interests", []) or [])
    fresh.put("/api/settings", json={"feed": {"interests": ["zebra"]}})
    try:
        assert "命中 zebra" in next(x for x in fresh.get("/api/feed/items").json()["items"] if x["id"] == "hn:b")["why"]
    finally:
        fresh.put("/api/settings", json={"feed": {"interests": old}})


def test_opening_an_item_marks_it_read_immediately(fresh):
    feed.upsert([_item("hn:a", "alpha story"), _item("hn:b", "beta story")])
    assert set(_ids(fresh, "read=unread")) == {"hn:a", "hn:b"}
    fresh.post("/api/feed/click", json={"id": "hn:a"})
    assert _ids(fresh, "read=unread") == ["hn:b"]
    assert _ids(fresh, "read=read") == ["hn:a"]


def test_results_do_not_leak_read_flag_between_requests(fresh):
    feed.upsert([_item("hn:a", "alpha story")])
    fresh.post("/api/feed/click", json={"id": "hn:a"})
    assert fresh.get("/api/feed/items").json()["items"][0]["read"] is True
    db.execute("DELETE FROM read_log")
    assert fresh.get("/api/feed/items").json()["items"][0]["read"] is False


def test_list_stays_instant_during_refresh_then_catches_up(fresh):
    feed.upsert([_item("hn:a", "alpha story")])
    assert _ids(fresh) == ["hn:a"]
    with feed._state_lock:
        feed._state["running"] = True
    feed.upsert([_item("hn:b", "beta story")])
    assert _ids(fresh) == ["hn:a"]
    assert {x["id"] for x in feed.ranked()} == {"hn:a", "hn:b"}  # 刷新里的一句话 / 产品分析要挑到刚抓到的条目
    with feed._state_lock:
        feed._state["running"] = False
    assert set(_ids(fresh)) == {"hn:a", "hn:b"}


def test_public_items_have_no_internal_fields(fresh):
    feed.upsert([_item("hn:a", "alpha story", extra={"author": "x"})])
    item = fresh.get("/api/feed/items").json()["items"][0]
    assert "norm_url" not in item
    assert json.dumps(item)
