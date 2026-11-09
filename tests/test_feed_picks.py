"""精选换掉的不丢：深读完没看的固定在上面，进过精选还没处理的收进「之前的精选」，7 天后退回列表。"""
from datetime import datetime, timedelta, timezone

import pytest

from app import db
from app.modules import feed, intel, learn
from tests.test_feed_radar_dedup import _clear, _item


@pytest.fixture()
def fresh(client, monkeypatch):
    monkeypatch.setattr(learn.jobs, "submit", lambda *a, **k: 1)
    intel.seed()
    _clear()
    client.get("/api/learn/items")
    db.execute("DELETE FROM learn_items")
    db.execute("DELETE FROM feed_picks")
    feed.upsert([_item(f"blog:{i}") for i in range(7)])
    return client


def _picks(client):
    return client.get("/api/feed/picks").json()


def _ids(rows):
    return [x["id"] for x in rows]


def _bump_out(client) -> str:
    """让当前精选第一条的分数掉下去，等于它被新内容换掉。"""
    victim = _picks(client)["top"][0]["id"]
    old = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
    db.execute("UPDATE feed_items SET date=?, popularity=0 WHERE id=?", [old, victim])
    assert victim not in _ids(_picks(client)["top"])
    return victim


def _start_deep(client, item_id, status="done"):
    it = client.post("/api/learn/items", json={"url": f"https://e.x/{item_id}", "reuse": True}).json()
    db.update("learn_items", it["id"], {"status": status})
    return it["id"]


def test_top_still_five_and_nothing_earlier_at_first(fresh):
    r = _picks(fresh)
    assert len(r["top"]) == 5 and r["earlier"] == [] and r["waiting"] == []


def test_replaced_pick_moves_to_earlier(fresh):
    victim = _bump_out(fresh)
    assert _ids(_picks(fresh)["earlier"]) == [victim]


def test_item_never_in_top_is_not_in_earlier(fresh):
    _bump_out(fresh)
    r = _picks(fresh)
    never = {f"blog:{i}" for i in range(7)} - set(_ids(r["top"])) - set(_ids(r["earlier"]))
    assert len(never) == 1


@pytest.mark.parametrize("handle", [
    lambda c, i: c.post("/api/feed/click", json={"id": i}),
    lambda c, i: c.post("/api/feed/feedback", json={"id": i, "vote": -1}),
    lambda c, i: c.post("/api/feed/feedback", json={"id": i, "hidden": True}),
    lambda c, i: _start_deep(c, i, "running"),
], ids=["opened", "disliked", "hidden", "deep_started"])
def test_handled_item_leaves_earlier(fresh, handle):
    victim = _bump_out(fresh)
    handle(fresh, victim)
    assert victim not in _ids(_picks(fresh)["earlier"])


def test_failed_deep_stays_in_earlier(fresh):
    victim = _bump_out(fresh)
    _start_deep(fresh, victim, "failed")
    assert _ids(_picks(fresh)["earlier"]) == [victim]


def test_like_or_save_does_not_count_as_handled(fresh):
    victim = _bump_out(fresh)
    fresh.post("/api/feed/feedback", json={"id": victim, "saved": True})
    assert _ids(_picks(fresh)["earlier"]) == [victim]


@pytest.mark.parametrize("days,kept", [(6, True), (8, False)])
def test_earlier_expires_after_seven_days(fresh, days, kept):
    victim = _bump_out(fresh)
    at = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
    db.execute("UPDATE feed_picks SET last_at=? WHERE item_id=?", [at, victim])
    assert (victim in _ids(_picks(fresh)["earlier"])) is kept


def test_item_back_in_top_is_not_also_in_earlier(fresh):
    victim = _bump_out(fresh)
    now = datetime.now(timezone.utc).isoformat()
    db.execute("UPDATE feed_items SET date=?, popularity=100000 WHERE id=?", [now, victim])
    r = _picks(fresh)
    assert victim in _ids(r["top"]) and victim not in _ids(r["earlier"])


def test_finished_deep_waits_above_top_until_started_reading(fresh):
    iid = _start_deep(fresh, "blog:3")
    r = _picks(fresh)
    assert _ids(r["waiting"]) == ["blog:3"]
    assert "blog:3" not in _ids(r["top"]) and len(r["top"]) == 5
    fresh.post(f"/api/learn/items/{iid}/seen")
    assert _ids(_picks(fresh)["waiting"]) == ["blog:3"]
    fresh.post(f"/api/learn/items/{iid}/progress", json={"pos": 0.2})
    assert _picks(fresh)["waiting"] == []


def test_finished_deep_waits_however_old(fresh):
    _start_deep(fresh, "blog:3")
    old = (datetime.now(timezone.utc) - timedelta(days=400)).isoformat()
    db.execute("UPDATE feed_items SET date=?, popularity=0 WHERE id=?", [old, "blog:3"])
    assert _ids(_picks(fresh)["waiting"]) == ["blog:3"]


def test_running_deep_is_not_waiting(fresh):
    _start_deep(fresh, "blog:3", "running")
    assert _picks(fresh)["waiting"] == []
