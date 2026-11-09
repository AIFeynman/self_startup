"""信息推荐点「深读」后留在列表里：解析中 / 完成 / 失败都能看到；打开后进「在读」，读完才算已读。"""
import pytest

from app import db
from app.modules import feed, intel, learn
from tests.test_feed_radar_dedup import _clear, _item


URL = "https://e.x/deep-post"


def _row(client, read=""):
    rows = client.get(f"/api/feed/items?limit=50&read={read}").json()["items"]
    return next((x for x in rows if x["id"] == "blog:deep"), None)


@pytest.fixture()
def fresh(client, monkeypatch):
    monkeypatch.setattr(learn.jobs, "submit", lambda *a, **k: 1)
    intel.seed()
    _clear()
    client.get("/api/learn/items")
    db.execute("DELETE FROM learn_items")
    feed.upsert([_item("blog:deep", URL)])
    return client


def test_started_item_stays_unread_and_shows_running(fresh):
    it = fresh.post("/api/learn/items", json={"url": URL, "reuse": True}).json()
    row = _row(fresh, "unread")
    assert row["deep"] == {"id": it["id"], "status": "running", "seen": False, "reading": False, "pos": 0}


def _picks(client):
    return {k: [x["id"] for x in v] for k, v in client.get("/api/feed/picks").json().items()}


def test_opened_half_read_stays_findable_until_finished(fresh):
    it = fresh.post("/api/learn/items", json={"url": URL, "reuse": True}).json()
    db.update("learn_items", it["id"], {"status": "done"})
    assert _picks(fresh)["waiting"] == ["blog:deep"]
    fresh.post(f"/api/learn/items/{it['id']}/seen")
    fresh.post(f"/api/learn/items/{it['id']}/progress", json={"pos": 0.4})
    assert _row(fresh, "unread")["deep"]["reading"] is True
    assert _picks(fresh)["waiting"] == [] and _picks(fresh)["reading"] == ["blog:deep"]
    assert fresh.get(f"/api/learn/items/{it['id']}").json()["read_pos"] == 0.4
    fresh.post(f"/api/learn/items/{it['id']}/finish", json={"done": True})
    assert _picks(fresh)["reading"] == []
    assert _row(fresh, "unread") is None
    assert _row(fresh, "read")["deep"]["reading"] is False


def test_scrolling_to_end_finishes(fresh):
    it = fresh.post("/api/learn/items", json={"url": URL, "reuse": True}).json()
    db.update("learn_items", it["id"], {"status": "done"})
    fresh.post(f"/api/learn/items/{it['id']}/seen")
    fresh.post(f"/api/learn/items/{it['id']}/progress", json={"pos": 1})
    assert _row(fresh, "read")["deep"]["reading"] is False
    fresh.post(f"/api/learn/items/{it['id']}/finish", json={"done": False})
    assert _picks(fresh)["reading"] == ["blog:deep"]


def test_failed_stays_unread_and_retry_shows_new_run(fresh):
    it = fresh.post("/api/learn/items", json={"url": URL, "reuse": True}).json()
    db.update("learn_items", it["id"], {"status": "failed"})
    assert _row(fresh, "unread")["deep"]["status"] == "failed"
    again = fresh.post("/api/learn/items", json={"url": URL, "reuse": True}).json()
    assert again["id"] != it["id"]
    assert _row(fresh, "unread")["deep"] == {"id": again["id"], "status": "running", "seen": False, "reading": False, "pos": 0}


def test_never_deep_read_has_no_state(fresh):
    assert _row(fresh, "unread")["deep"] is None


def test_reading_original_while_deep_pending_marks_read_and_done_still_waits(fresh):
    it = fresh.post("/api/learn/items", json={"url": URL, "reuse": True}).json()
    fresh.post("/api/feed/click", json={"id": "blog:deep"})
    assert _row(fresh, "unread") is None
    assert _row(fresh, "read")["deep"]["status"] == "running"
    db.update("learn_items", it["id"], {"status": "done"})
    assert [x["id"] for x in fresh.get("/api/feed/picks").json()["waiting"]] == ["blog:deep"]
    fresh.post(f"/api/learn/items/{it['id']}/seen")
    assert fresh.get("/api/feed/picks").json()["waiting"] == []
    assert _picks(fresh)["reading"] == ["blog:deep"]


def test_manual_mark_read(fresh):
    assert fresh.post("/api/feed/read", json={"id": "blog:deep"}).status_code == 200
    assert _row(fresh, "unread") is None
    assert _row(fresh, "read")["read"] is True
    assert fresh.post("/api/feed/read", json={"id": "nope"}).status_code == 404


def test_deep_filter_lists_finished_deep_reads(fresh):
    feed.upsert([_item("blog:other", "https://e.x/other")])
    it = fresh.post("/api/learn/items", json={"url": URL, "reuse": True}).json()
    assert _row(fresh, "deep") is None
    db.update("learn_items", it["id"], {"status": "done"})
    fresh.post(f"/api/learn/items/{it['id']}/seen")
    assert _row(fresh, "deep") is None
    fresh.post(f"/api/learn/items/{it['id']}/finish", json={"done": True})
    rows = fresh.get("/api/feed/items?limit=50&read=deep").json()["items"]
    assert [x["id"] for x in rows] == ["blog:deep"]
