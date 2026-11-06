"""产品雷达里已有的内容，信息推荐不再重复展示；搜索、收藏、已读筛选仍能找到。"""
import json
from datetime import datetime, timezone

import pytest

from app import db
from app.modules import feed, intel


def _item(id_, url="", source="blog", type_="blog"):
    return {"id": id_, "source": source, "type": type_, "title": f"标题 {id_}", "url": url or f"https://e.x/{id_}",
            "date": datetime.now(timezone.utc).isoformat(), "popularity": 100}


def _ids(client, query=""):
    return {x["id"] for x in client.get("/api/feed/items?limit=500&" + query).json()["items"]}


def _event(url, level="A", **kw):
    cid = db.row("SELECT id FROM intel_company WHERE slug='dedup-co'")["id"]
    return db.insert("intel_event", {"company_id": cid, "title": "事件", "level": level, "level_auto": level,
                                     "sources": json.dumps([{"label": "官方", "url": url, "official": True}]), **kw})


def _case(item_id, url, status="done"):
    db.insert("intel_growth_item", {"id": item_id, "url": url, "title": "素材"})
    db.insert("intel_growth_case", {"item_id": item_id, "day": db.today(), "status": status})


def _clear():
    for t in ("intel_event", "intel_ph_day", "intel_growth_case", "intel_growth_item", "feed_feedback", "feed_items"):
        db.execute(f"DELETE FROM {t}")
    db.execute("DELETE FROM intel_company WHERE kind='startup' OR slug='dedup-co'")


@pytest.fixture()
def fresh(client):
    intel.seed()
    _clear()
    db.insert("intel_company", {"slug": "dedup-co", "name": "DedupCo"})
    yield client
    _clear()


def test_radar_content_leaves_feed(fresh):
    feed.upsert([_item("blog:event", "https://e.x/post/?utm_source=rss"), _item("producthunt:1", source="producthunt", type_="product"),
                 _item("blog:case", "https://e.x/case"), _item("trustmrr:vidgen", source="trustmrr", type_="product"),
                 _item("blog:other")])
    _event("https://e.x/post")
    db.insert("intel_ph_day", {"date": db.today(), "items": json.dumps([{"id": "producthunt:1", "name": "P"}])})
    _case("growth:1", "https://e.x/case")
    db.insert("intel_company", {"slug": "s-vidgen", "name": "Vidgen", "kind": "startup", "ext": json.dumps({"trustmrr": "vidgen"})})
    assert _ids(fresh) == {"blog:other"}
    assert fresh.get("/api/feed/items?limit=500").json()["total"] == 1
    assert _ids(fresh, "type=product") == set()


def test_content_radar_does_not_show_by_default_stays_in_feed(fresh):
    feed.upsert([_item("blog:c"), _item("blog:merged"), _item("blog:pool"), _item("blog:failed"),
                 _item("trustmrr:off", source="trustmrr", type_="product")])
    _event("https://e.x/blog:c", level="C")
    keep = _event("https://e.x/other")
    _event("https://e.x/blog:merged", merged_into=keep)
    db.insert("intel_growth_item", {"id": "growth:pool", "url": "https://e.x/blog:pool", "title": "素材"})
    _case("growth:2", "https://e.x/blog:failed", status="failed")
    db.insert("intel_company", {"slug": "s-off", "name": "Off", "kind": "startup", "enabled": 0, "ext": json.dumps({"trustmrr": "off"})})
    assert _ids(fresh) == {"blog:c", "blog:merged", "blog:pool", "blog:failed", "trustmrr:off"}


def test_radar_content_still_findable(fresh):
    feed.upsert([_item("blog:event", "https://e.x/post")])
    _event("https://e.x/post")
    assert _ids(fresh) == set()
    assert _ids(fresh, "q=blog:event") == {"blog:event"}
    fresh.post("/api/feed/feedback", json={"id": "blog:event", "saved": True})
    assert _ids(fresh, "saved=true") == {"blog:event"}
    fresh.post("/api/feed/click", json={"id": "blog:event"})
    assert _ids(fresh, "read=read") == {"blog:event"}
    assert _ids(fresh, "read=unread") == set()
