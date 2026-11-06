"""信息推荐点「深读」后留在列表里：解析中 / 完成 / 失败都能看到，打开看过结果才算已读。"""
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
    assert row["deep"] == {"id": it["id"], "status": "running"}


def test_done_but_unopened_stays_unread_then_opening_marks_read(fresh):
    it = fresh.post("/api/learn/items", json={"url": URL, "reuse": True}).json()
    db.update("learn_items", it["id"], {"status": "done"})
    assert _row(fresh, "unread")["deep"]["status"] == "done"
    fresh.post(f"/api/learn/items/{it['id']}/seen")
    assert _row(fresh, "unread") is None
    assert _row(fresh, "read")["deep"]["status"] == "done"


def test_failed_stays_unread_and_retry_shows_new_run(fresh):
    it = fresh.post("/api/learn/items", json={"url": URL, "reuse": True}).json()
    db.update("learn_items", it["id"], {"status": "failed"})
    assert _row(fresh, "unread")["deep"]["status"] == "failed"
    again = fresh.post("/api/learn/items", json={"url": URL, "reuse": True}).json()
    assert again["id"] != it["id"]
    assert _row(fresh, "unread")["deep"] == {"id": again["id"], "status": "running"}


def test_never_deep_read_has_no_state(fresh):
    assert _row(fresh, "unread")["deep"] is None


def test_reading_original_while_deep_pending_keeps_it_in_list(fresh):
    it = fresh.post("/api/learn/items", json={"url": URL, "reuse": True}).json()
    fresh.post("/api/feed/click", json={"id": "blog:deep"})
    assert _row(fresh, "unread")["deep"]["status"] == "running"
    db.update("learn_items", it["id"], {"status": "done"})
    assert _row(fresh, "unread")["deep"]["status"] == "done"
    fresh.post(f"/api/learn/items/{it['id']}/seen")
    assert _row(fresh, "unread") is None
