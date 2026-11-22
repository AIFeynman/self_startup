import pytest

from app import db, notify


@pytest.fixture(autouse=True)
def _app(client):
    return client


def _alerts(module):
    return db.rows("SELECT * FROM notifications WHERE module=? AND kind='failure' ORDER BY id", [module])


def test_same_failure_alerts_once_until_recovered():
    m = "t_once"
    assert notify.failures(m, "抓取", {"hn": "ConnectTimeout: timed out"}, link="#feed")
    assert notify.failures(m, "抓取", {"hn": "ConnectTimeout: timed out again"}) is None
    assert len(_alerts(m)) == 1
    notify.failures(m, "抓取", {"hn": ""})
    assert len(_alerts(m)) == 1


def test_many_failures_in_one_round_make_one_message_grouped_by_error():
    m = "t_group"
    nid = notify.failures(m, "抓取", {"a": "HTTP 403", "b": "ConnectTimeout: timed out", "c": "ConnectTimeout: timed out", "d": ""},
                          names={"a": "源A", "b": "源B", "c": "源C"})
    rows = _alerts(m)
    assert len(rows) == 1 and rows[0]["id"] == nid
    assert "源A" in rows[0]["title"] and "抓取失败" in rows[0]["title"]
    assert "源B、源C：ConnectTimeout: timed out" in rows[0]["body"]
    assert notify.failures(m, "抓取", {"a": "HTTP 403", "e": "HTTP 500"}) and "e" in _alerts(m)[-1]["title"]


def test_flapping_source_does_not_realert_within_a_day(monkeypatch):
    m = "t_flap"
    notify.failures(m, "解析", {"x": "boom"})
    notify.failures(m, "解析", {"x": ""})
    assert notify.failures(m, "解析", {"x": "boom"}) is None
    db.execute("UPDATE notify_failures SET notified_at='2000-01-01T00:00:00' WHERE key=?", [f"{m}:x"])
    notify.failures(m, "解析", {"x": ""})
    assert notify.failures(m, "解析", {"x": "boom"})
    assert len(_alerts(m)) == 2


def test_failure_alert_shows_in_inbox_as_failed(client):
    notify.failures("t_inbox", "抓取", {"z": "HTTP 502"}, link="#feed")
    it = next(x for x in client.get("/api/notify/history").json() if x["module"] == "t_inbox")
    assert it["failed"] and "HTTP 502" in it["body"]


def test_feed_refresh_alerts_only_sources_that_got_nothing(monkeypatch):
    from app.modules import feed
    monkeypatch.setattr(feed, "refresh_sync", lambda only, gists=None: {
        "hn": {"count": 0, "errors": ["ConnectTimeout: timed out"]},
        "x": {"count": 12, "errors": ["一个搜索词超时"]},
        "gist": {"count": 0, "errors": ["模型返回不是 JSON"]},
        "reddit": {"count": 5, "errors": []}})
    monkeypatch.setattr(feed, "_warm_rank", lambda: None)
    monkeypatch.setattr(feed, "paper_ingest", lambda: None)
    feed._bg(["hn", "x", "reddit"])
    rows = _alerts("feed")
    assert len(rows) == 1
    assert "ConnectTimeout" in rows[0]["body"] and "JSON" in rows[0]["body"] and "一个搜索词" not in rows[0]["body"]
    feed._bg(["hn", "x", "reddit"])
    assert len(_alerts("feed")) == 1


def test_xart_daily_failure_alerts(monkeypatch):
    from app.modules import _xart
    monkeypatch.setattr(_xart, "crawl_since", lambda ts: (_ for _ in ()).throw(RuntimeError("cookie 过期")))
    try:
        _xart.daily()
    except RuntimeError:
        pass
    rows = _alerts("xart")
    assert len(rows) == 1 and "cookie 过期" in rows[0]["body"]


def test_paper_record_failure_alerts():
    from app.modules import _paper_maintain
    try:
        _paper_maintain.record("weekly", lambda step: (_ for _ in ()).throw(ValueError("解析失败")))
    except ValueError:
        pass
    assert "解析失败" in _alerts("paper")[-1]["body"]


def test_intel_fetch_alert_names_company_and_source():
    from app.modules import intel
    cid = db.insert("intel_company", {"name": "Acme测试", "slug": "acme-test-alert", "created_at": db.now()})
    ok = db.insert("intel_source", {"company_id": cid, "kind": "rss", "label": "Blog", "url": "https://a.test/rss", "last_err": ""})
    bad = db.insert("intel_source", {"company_id": cid, "kind": "page", "label": "Changelog", "url": "https://a.test/c", "last_err": "HTTP 403"})
    intel.alert_fetch([ok, bad])
    row = _alerts("intel")[-1]
    assert "Acme测试 · Changelog" in row["title"] and "Blog" not in row["title"]


def test_people_channel_with_nothing_fetched_alerts(monkeypatch):
    from app.modules import _people
    monkeypatch.setattr(_people, "FETCHERS", {"blog": lambda pool: ([], ["HTTP 500 rss.test"]), "news": lambda pool: ([], [])})
    monkeypatch.setattr(_people, "people", lambda: [])
    monkeypatch.setattr(_people, "backfill", lambda runner, model: [])
    monkeypatch.setattr(_people, "summarize_and_notify", lambda: None)
    monkeypatch.setattr(_people, "_haiku_runner", lambda: (None, ""))
    _people.run(["blog", "news"])
    row = _alerts("people")[-1]
    assert row["title"].startswith("名人发声抓取失败：博客") and "新闻" not in row["title"]
