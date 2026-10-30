"""信息推荐：排序、learn_evolve 导入、RSS 解析、API。不触网、不调 LLM。"""
import json
import sqlite3
from datetime import datetime, timedelta, timezone

from app.modules import _feed_rank as rk
from app.modules import _feed_sources as src

NOW = datetime(2026, 10, 29, 12, tzinfo=timezone.utc)


def _it(id_, title, *, source="hn", hours=1, pop=100, summary="", url="", extra=None):
    return {"id": id_, "source": source, "type": "discussion", "title": title, "summary": summary,
            "url": url or f"https://example.com/{id_}", "date": (NOW - timedelta(hours=hours)).isoformat(),
            "popularity": pop, "extra": extra or {}}


def test_freshness_decay():
    out = rk.rank([_it("a", "old post", hours=24 * 10), _it("b", "new post", hours=1)], now=NOW, half_life_h=48)
    assert [x["id"] for x in out] == ["b", "a"]
    assert "24 小时内" in out[0]["why"]


def test_interest_match_word_boundary():
    items = [_it("a", "A world of tools", pop=100), _it("b", "Scaling RL for coding agent", pop=100)]
    out = rk.rank(items, now=NOW, interests=["rl", "coding agent"])
    assert out[0]["id"] == "b" and "命中 rl、coding agent" in out[0]["why"]
    assert "命中" not in out[1]["why"]  # rl 不应命中 world


def test_popularity_normalized_per_source():
    items = [_it("g1", "repo one", source="github", pop=5000), _it("g2", "repo two", source="github", pop=50),
             _it("h1", "story one", source="hn", pop=300)]
    out = {x["id"]: x for x in rk.rank(items, now=NOW)}
    # 各来源的头部都拿满热度分，不会因 stars 量级大就压过 HN
    assert out["g1"]["score"] == out["h1"]["score"] > out["g2"]["score"]
    assert "GitHub 5.0k★" in out["g1"]["why"] and "HN 300分" in out["h1"]["why"]


def test_feedback_affinity_and_hidden():
    items = [_it("a", "Agent memory benchmark", pop=50), _it("b", "Image diffusion trick", pop=50),
             _it("c", "Hidden thing", pop=999)]
    ex = [{"title": "Long-term agent memory", "source": "hn", "polarity": 1},
          {"title": "Diffusion image editing", "source": "hn", "polarity": -1}]
    out = rk.rank(items, now=NOW, examples=ex, feedback={"c": {"hidden": 1}})
    assert [x["id"] for x in out] == ["a", "b"]
    assert "你赞过相似内容" in out[0]["why"] and "踩过" in out[1]["why"]


def test_learn_evolve_prior():
    items = [_it("a", "x one", extra={"le_rating": "bad"}), _it("b", "x two", extra={"le_rating": "star"})]
    out = rk.rank(items, now=NOW)
    assert out[0]["id"] == "b" and "learn_evolve 标星" in out[0]["why"]


def test_dedupe_by_url_and_title():
    items = [_it("hf:2610.1", "Cool Paper Title Here", source="hf", pop=10, url="https://huggingface.co/papers/2610.12345"),
             _it("arxiv:2610.1", "Cool paper title here!", source="arxiv", pop=99, url="https://arxiv.org/abs/2610.12345"),
             _it("blog:1", "Post", source="blog", url="https://www.Example.com/post/?utm_source=x"),
             _it("hn:1", "Different title for post", source="hn", url="http://example.com/post")]
    out = rk.rank(items, now=NOW)
    assert len(out) == 2
    assert any("也见于" in x["why"] for x in out)


def test_learn_evolve_importer(tmp_path):
    (tmp_path / "raw/arxiv/2026-06-27").mkdir(parents=True)
    (tmp_path / "raw/arxiv/2026-06-27/p.json").write_text(json.dumps(
        {"title": "P", "abstract": "We propose a new agent memory method that works really well on benchmarks.", "likes": 42}))
    (tmp_path / "raw/hn/2026-06-26").mkdir(parents=True)
    (tmp_path / "raw/hn/2026-06-26/h.json").write_text(json.dumps(
        {"url": "https://blog.example/x", "hn_url": "https://news.ycombinator.com/item?id=1", "points": 300,
         "article": {"description": "An article about <b>LLM</b> inference that is long enough to count."}}))
    dbp = tmp_path / ".news.db"
    c = sqlite3.connect(dbp)
    c.execute("CREATE TABLE items (id TEXT PRIMARY KEY, source TEXT, content_type TEXT, title TEXT, url TEXT, date TEXT, "
              "score REAL, raw_path TEXT, rating TEXT, tags TEXT)")
    c.executemany("INSERT INTO items VALUES (?,?,?,?,?,?,?,?,?,?)", [
        ("arxiv:1", "arxiv", "paper", "Paper One", "https://arxiv.org/abs/1", "2026-06-27", 1e6, "raw/arxiv/2026-06-27/p.json", "star", '["agent"]'),
        ("hn:1", "hn", "hn_thread", "HN One", "https://news.ycombinator.com/item?id=1", "2026-06-26", 300, "raw/hn/2026-06-26/h.json", None, "[]"),
        ("changelog:1", "changelog", "changelog", "b123", "", "2026-06-27", 0, "", None, "[]"),
        ("hn:old", "hn", "hn_thread", "Old", "", "2025-01-01", 5, "", None, "[]"),
        ("hn:rated", "hn", "hn_thread", "Old but rated", "", "2025-01-01", 5, "missing.json", "bad", "[]")])
    c.commit()
    c.close()
    got = {x["id"]: x for x in src.fetch_learn_evolve(str(dbp), days=30)}
    assert set(got) == {"arxiv:1", "hn:1", "hn:rated"}
    assert got["arxiv:1"]["popularity"] == 42 and got["arxiv:1"]["extra"]["le_rating"] == "star"
    assert got["arxiv:1"]["type"] == "paper" and got["arxiv:1"]["summary"].startswith("We propose")
    assert got["hn:1"]["url"] == "https://blog.example/x" and "<b>" not in got["hn:1"]["summary"]
    assert got["hn:rated"]["extra"]["le_rating"] == "bad"


RSS = """<?xml version="1.0"?><rss version="2.0"><channel><title>Test Blog</title>
<item><title>New &amp; shiny agent</title><link>https://b.example/1</link><guid>g1</guid>
<pubDate>Wed, 28 Oct 2026 10:00:00 GMT</pubDate><description><![CDATA[<p>Hello <b>agents</b></p>]]></description></item>
<item><title>Ancient</title><link>https://b.example/0</link><pubDate>Mon, 01 Jan 2001 10:00:00 GMT</pubDate></item>
</channel></rss>"""


def test_rss_parsing():
    items = src.parse_feed(RSS, "https://b.example/rss", days=3650)
    assert len(items) == 1
    it = items[0]
    assert it["title"] == "New & shiny agent" and it["summary"] == "Hello agents"
    assert it["id"].startswith("blog:") and it["extra"]["feed"] == "Test Blog" and it["date"].startswith("2026-10-28")
    assert len(src.parse_feed(RSS, days=0)) == 2


def test_api_flow(client, monkeypatch):
    from app.modules import feed
    fake = [_it("hn:9", "Claude Code agent tips", pop=200), _it("hn:8", "Other thing", pop=10)]
    monkeypatch.setattr(feed, "_collectors", lambda: {"hn": lambda: fake, "rss": lambda: ([], ["x: boom"]),
                                                      "bad": lambda: 1 / 0})
    st = client.post("/api/feed/refresh", json={"sources": ["hn", "rss", "bad"], "wait": True}).json()
    assert st["results"]["hn"]["count"] == 2 and st["results"]["rss"]["errors"] == ["x: boom"]
    assert "ZeroDivisionError" in st["results"]["bad"]["errors"][0]
    assert st["last_fetched"] and st["by_source"]["hn"] == 2
    items = client.get("/api/feed/items?type=discussion").json()["items"]
    assert items[0]["id"] == "hn:9" and items[0]["why"]
    assert client.post("/api/feed/feedback", json={"id": "hn:8", "hidden": True, "saved": True}).json()["hidden"] == 1
    assert all(x["id"] != "hn:8" for x in client.get("/api/feed/items").json()["items"])
    assert [x["id"] for x in client.get("/api/feed/items?saved=true").json()["items"]] == ["hn:8"]
    assert client.post("/api/feed/feedback", json={"id": "nope", "vote": 1}).status_code == 404
    assert "Claude Code agent tips" in feed.agent_context("")


def test_affinity_leave_one_out():
    items = [_it("a", "Unique zebra title", pop=50)]
    out = rk.rank(items, now=NOW, examples=[{"id": "a", "title": "Unique zebra title", "source": "hn", "polarity": 1}])
    assert "你赞过相似内容" not in out[0]["why"]


def test_hn_link_summary_is_factual():
    s = src.hn_link_summary({"url": "https://www.example.com/post", "points": 120, "num_comments": 45})
    assert s == "链接到 example.com · 120 分 · 45 条评论"
    assert src.hn_link_summary({"points": 3}) == "HN 讨论帖 · 3 分"


def test_stale_items_downweighted_and_marked():
    now = datetime(2026, 10, 30, tzinfo=timezone.utc)
    items = [{"id": "x:old", "source": "x", "type": "blog", "title": "old", "date": "2026-06-01", "popularity": 0, "extra": {}},
             {"id": "x:new", "source": "x", "type": "blog", "title": "new", "date": "2026-10-28", "popularity": 0, "extra": {}},
             {"id": "x:gone", "source": "x", "type": "blog", "title": "gone", "date": "2026-10-28", "popularity": 0,
              "extra": {"gone": True}}]
    out = {x["id"]: x for x in rk.rank(items, now=now)}
    assert "天前" in out["x:old"]["why"] and out["x:old"]["score"] < out["x:new"]["score"]
    assert "可能已删除" in out["x:gone"]["why"] and out["x:gone"]["score"] < out["x:new"]["score"]


def test_diversify_caps_type_share():
    items = [{"id": f"r{i}", "type": "repo"} for i in range(10)] + [{"id": "p", "type": "paper"}, {"id": "b", "type": "blog"}]
    out = rk.diversify(items, top=5, max_share=0.4)
    assert [x["id"] for x in out[:5]] == ["r0", "r1", "p", "b", "r2"]
    assert len(out) == len(items)


def test_norm_date():
    from app.modules import feed
    assert feed.norm_date("2026-10-28T00:00:00.000Z") == "2026-10-28T00:00:00+00:00"
    assert feed.norm_date("2026-06-10") == "2026-06-10T00:00:00+00:00"
    assert feed.norm_date("bad") == "bad" and feed.norm_date("") == ""


def test_click_counts_and_funnel(client):
    from app.modules import feed
    feed.upsert([{"id": "hn:click1", "source": "hn", "type": "discussion", "title": "clicky", "url": "https://e.x/c"}])
    for _ in range(2):
        assert client.post("/api/feed/click", json={"id": "hn:click1"}).status_code == 200
    assert client.post("/api/feed/click", json={"id": "nope"}).status_code == 404
    fbk = client.get("/api/feed/status").json()["feedback"]
    assert fbk["clicks"] >= 2 and fbk["clicked_items"] >= 1 and "deep_reads" in fbk
    # 点击不改变赞踩
    client.post("/api/feed/feedback", json={"id": "hn:click1", "vote": 1})
    row = feed.db.row("SELECT * FROM feed_feedback WHERE item_id='hn:click1'")
    assert row["clicks"] == 2 and row["vote"] == 1


def test_auto_refresh_respects_threshold(client, monkeypatch):
    from app.modules import feed
    calls = []
    monkeypatch.setattr(feed, "_bg", lambda only: calls.append(only) or feed._state.update(running=False))
    monkeypatch.setattr(feed, "_stale_hours", lambda: 1.0)
    assert feed.maybe_auto_refresh() is False
    monkeypatch.setattr(feed, "_stale_hours", lambda: 100.0)
    assert feed.maybe_auto_refresh() is True
    import time as _t
    _t.sleep(0.1)
    assert calls == [None]
