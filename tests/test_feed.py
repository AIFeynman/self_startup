"""信息推荐：排序、各来源解析（RSS / X / Product Hunt / 官方站）、API。不触网、不调 LLM。"""
import json
from datetime import datetime, timedelta, timezone

import httpx

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
          {"title": "Memory for coding agents", "source": "hn", "polarity": 1},      # 至少 2 条赞过才算线索
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
    items = [{"id": f"r{i}", "type": "repo", "source": f"gh{i}"} for i in range(10)] + [
        {"id": "p", "type": "paper", "source": "arxiv"}, {"id": "b", "type": "blog", "source": "blog"}]
    out = rk.diversify(items, top=8, max_share=0.4)
    assert [x["id"] for x in out[:5]] == ["r0", "r1", "p", "b", "r2"]     # 精选：每类最多 2 条，不够再放宽
    assert [x["id"] for x in out[5:8]] == ["r3", "r4", "r5"]              # 其余候选不够多样时按原序补上，不丢条目
    assert len(out) == len(items)


def test_diversify_picks_one_per_source():
    items = ([{"id": f"x{i}", "type": "discussion", "source": "twitter"} for i in range(6)]
             + [{"id": f"ph{i}", "type": "product", "source": "producthunt"} for i in range(6)]
             + [{"id": "a", "type": "paper", "source": "arxiv"}, {"id": "h", "type": "discussion", "source": "hn"},
                {"id": "g", "type": "repo", "source": "github"}])
    out = rk.diversify(items, top=10, src_share=0.2)
    assert [x["id"] for x in out[:5]] == ["x0", "ph0", "a", "h", "g"]
    assert [x["id"] for x in out[5:7]] == ["x1", "ph1"]       # 前 10 条每源 ≤ 2：先各补一条，剩下的原序顺延
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


# ---------- X / Product Hunt / 官方站 / .env ----------

def _tw(**kw):
    tw = {"id": "1", "text": "Shipping a new coding agent today. Details below https://t.co/abc", "likeCount": 500,
          "retweetCount": 20, "createdAt": "Wed Oct 28 10:00:00 +0000 2026", "url": "https://x.com/a/status/1",
          "author": {"userName": "a", "name": "A", "followers": 9}, "entities": {"urls": [{"expanded_url": "https://e.com/x"}]}}
    return {**tw, **kw}


def test_x_item_shape_and_filters():
    it = src.x_item(_tw(), "@a")
    assert it["id"] == "twitter:1" and it["source"] == "twitter" and it["type"] == "discussion"
    assert it["title"] == "@a：Shipping a new coding agent today" and "t.co" not in it["summary"]
    assert it["date"].startswith("2026-10-28T10:00") and it["popularity"] == 500 and it["extra"]["links"] == ["https://e.com/x"]
    assert src.x_item(_tw(retweeted_tweet={"id": "9"}), "@a") is None
    assert src.x_item(_tw(isReply=True), "@a") is None
    assert "引用 @b" in src.x_item(_tw(quoted_tweet={"text": "orig", "author": {"userName": "b"}}), "@a")["summary"]


def test_fetch_x_falls_back_and_filters(monkeypatch):
    monkeypatch.setenv("GETXAPI_KEY", "k1")
    monkeypatch.setenv("TWITTER_API_KEY", "k2")
    recent = datetime.now(timezone.utc).strftime("%a %b %d %H:%M:%S +0000 %Y")
    calls = []

    def handler(req):
        calls.append(req.url.host)
        if req.url.host == "api.getxapi.com":
            return httpx.Response(500)
        tweets = [_tw(id="1", createdAt=recent), _tw(id="2", createdAt=recent, likeCount=5),
                  _tw(id="3", createdAt="Mon Jan 01 00:00:00 +0000 2024")]
        return httpx.Response(200, json={"data": {"tweets": tweets}})

    monkeypatch.setattr(src, "_client", lambda: httpx.Client(transport=httpx.MockTransport(handler)))
    items, errs = src.fetch_x(["a"], [], days=3, min_likes=100)
    assert [i["id"] for i in items] == ["twitter:1"] and not errs
    assert calls == ["api.getxapi.com", "api.twitterapi.io"]


def test_fetch_x_search_requires_ai_terms(monkeypatch):
    monkeypatch.setenv("GETXAPI_KEY", "k1")
    recent = datetime.now(timezone.utc).strftime("%a %b %d %H:%M:%S +0000 %Y")
    tweets = [_tw(id="1", createdAt=recent, text="My agent just closed the hockey deal"),
              _tw(id="2", createdAt=recent, text="Our coding agent now runs evals overnight"),
              _tw(id="3", createdAt=recent, text="Claude wrote this whole migration")]
    monkeypatch.setattr(src, "_client", lambda: httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json={"tweets": tweets}))))
    items, _ = src.fetch_x([], ["agent min_faves:300"])
    assert sorted(i["id"] for i in items) == ["twitter:2", "twitter:3"]


def test_fetch_x_needs_key(monkeypatch):
    monkeypatch.delenv("GETXAPI_KEY", raising=False)
    monkeypatch.delenv("TWITTER_API_KEY", raising=False)
    try:
        src.fetch_x(["a"], [])
        assert False
    except RuntimeError as e:
        assert "GETXAPI_KEY" in str(e)


def test_producthunt_graphql(monkeypatch):
    monkeypatch.setenv("PRODUCTHUNT_TOKEN", "t")
    node = lambda i, name, tag, topics: {"node": {"id": i, "name": name, "tagline": tag, "description": "", "votesCount": 9,
                                                  "url": "https://www.producthunt.com/products/x?utm_source=api",
                                                  "commentsCount": 1, "createdAt": "2026-10-29T07:00:00Z", "website": "",
                                                  "topics": {"edges": [{"node": {"name": t}} for t in topics]}}}
    body = {"data": {"posts": {"edges": [node("1", "Agenty", "Your AI agent for email", ["Productivity"]),
                                         node("2", "Socks", "Warm socks for winter", ["Fashion"])]}}}
    monkeypatch.setattr(src, "_client", lambda: httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=body))))
    got = src.fetch_producthunt()
    assert [g["id"] for g in got] == ["producthunt:1"]
    assert got[0]["url"] == "https://www.producthunt.com/products/x" and got[0]["title"].startswith("Agenty：")


def test_page_date_sources_and_future_guard():
    assert src.page_date('<meta property="article:published_time" content="2026-10-15T08:00:00Z">').day == 15
    assert src.page_date('<script>{"datePublished":"2026-10-01"}</script>').month == 10
    assert src.page_date("<p>Posted Oct 3, 2026 by team</p>").day == 3
    assert src.page_date("<p>发布于 2026年9月8日</p>").month == 9
    # 正文里的未来活动日期不能当发布日期；JSON-LD 的 dateModified 兜底
    assert src.page_date('<script>{"dateModified":"2026-10-24"}</script><p>Event on 2099-11-04</p>').day == 24
    assert src.page_date("<p>no date here</p>") is None


def test_fetch_sites(monkeypatch):
    recent = (datetime.now(timezone.utc) - timedelta(days=2)).strftime("%Y-%m-%d")
    pages = {
        "/blog": '<a href="/blog/new-agent">x</a><a href="/blog/old-post">y</a><a href="/blog/known">z</a><a href="/about">a</a>',
        "/blog/new-agent": f'<meta property="og:title" content="New agent"><meta name="description" content="About &amp; agents">'
                           f'<meta property="article:published_time" content="{recent}">',
        "/blog/old-post": '<meta property="og:title" content="Old"><meta property="article:published_time" content="2020-01-01">',
    }
    seen = []

    def handler(req):
        seen.append(req.url.path)
        return httpx.Response(200, text=pages.get(req.url.path, ""))

    real = httpx.Client
    monkeypatch.setattr(src.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler), follow_redirects=True))
    items, errs = src.fetch_sites([{"name": "Lab", "url": "https://lab.example/blog", "link_re": r"/blog/[a-z-]+"}],
                                  known_urls={"https://lab.example/blog/known"})
    assert not errs and [i["title"] for i in items] == ["New agent"]
    assert items[0]["summary"] == "About & agents" and items[0]["extra"]["feed"] == "Lab"
    assert "/blog/known" not in seen


def test_load_env(tmp_path, monkeypatch):
    from app import settings
    p = tmp_path / ".env"
    p.write_text("# c\nFOO_A=1\nexport FOO_B='two'\nFOO_C=keep\n")
    monkeypatch.delenv("FOO_A", raising=False)
    monkeypatch.delenv("FOO_B", raising=False)
    monkeypatch.setenv("FOO_C", "env")
    settings.load_env(p)
    import os
    assert os.environ["FOO_A"] == "1" and os.environ["FOO_B"] == "two" and os.environ["FOO_C"] == "env"


def _xyz_handler(direct_ok: bool, hub_ok: set[str]):
    recent = (datetime.now(timezone.utc) - timedelta(days=3)).strftime("%Y-%m-%dT00:00:00.000Z")
    pod = {"title": "张小珺", "episodes": [
        {"eid": "a" * 24, "title": "E1 机器人", "pubDate": recent, "description": "嘉宾聊具身", "playCount": "2100",
         "commentCount": "5", "duration": "3600"},
        {"eid": "b" * 24, "title": "Old", "pubDate": "2020-01-01T00:00:00.000Z", "playCount": "9"}]}
    rss = f"""<?xml version="1.0"?><rss version="2.0"><channel><title>张小珺</title><item><title>E1 hub</title>
<link>https://www.xiaoyuzhoufm.com/episode/{'c' * 24}</link><pubDate>{datetime.now(timezone.utc).strftime('%a, %d %b %Y %H:%M:%S GMT')}</pubDate>
<description>hub desc</description></item></channel></rss>"""

    def handler(req):
        if req.url.host == "www.xiaoyuzhoufm.com":
            if not direct_ok:
                return httpx.Response(200, text="<html>blocked</html>")
            return httpx.Response(200, text=f'<script id="__NEXT_DATA__" type="application/json">'
                                            f'{json.dumps({"props": {"pageProps": {"podcast": pod}}})}</script>')
        return httpx.Response(200, text=rss) if req.url.host in hub_ok else httpx.Response(502)
    return handler


def test_xiaoyuzhou_direct(monkeypatch):
    real = httpx.Client
    monkeypatch.setattr(src.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(_xyz_handler(True, set()))))
    items, errs = src.fetch_xiaoyuzhou(["https://www.xiaoyuzhoufm.com/podcast/" + "0" * 24, "https://example.com/x"])
    assert [i["id"] for i in items] == ["xiaoyuzhou:" + "a" * 24]
    it = items[0]
    assert it["type"] == "podcast" and it["popularity"] == 2100 and it["extra"] == {"feed": "张小珺", "comments": 5, "minutes": 60}
    assert len(errs) == 1 and "不是小宇宙节目页" in errs[0]


def test_xiaoyuzhou_rsshub_fallback(monkeypatch):
    real = httpx.Client
    monkeypatch.setattr(src.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(_xyz_handler(False, {"hub2.example"}))))
    items, errs = src.fetch_xiaoyuzhou(["https://www.xiaoyuzhoufm.com/podcast/" + "0" * 24],
                                       rsshub_bases=["https://hub1.example", "https://hub2.example/"])
    assert not errs and [i["id"] for i in items] == ["xiaoyuzhou:" + "c" * 24]
    assert items[0]["source"] == "xiaoyuzhou" and items[0]["extra"]["via"] == "https://hub2.example/"
    monkeypatch.setattr(src.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(_xyz_handler(False, set()))))
    items, errs = src.fetch_xiaoyuzhou(["https://www.xiaoyuzhoufm.com/podcast/" + "0" * 24], rsshub_bases=["https://hub1.example"])
    assert not items and "RSSHub 也没取到" in errs[0]


# ---------- 排序优化：按类型半衰期 / 只到天的日期 / 热度百分位 / 关注账号 / 多源印证 / 时间筛选与排序 ----------

def test_type_half_life():
    # 同样 3 天前：论文（半衰期 ×1.67）比讨论（×0.5）新鲜度高得多
    paper = {**_it("p", "zz paper", hours=72, pop=0), "type": "paper", "source": "blog"}
    disc = {**_it("d", "zz disc", hours=72, pop=0), "source": "blog"}
    out = {x["id"]: x["score"] for x in rk.rank([paper, disc], now=NOW, half_life_h=72)}
    assert out["p"] - out["d"] > 0.5


def test_date_only_counts_as_noon():
    it = {"date": "2026-10-29T00:00:00+00:00"}
    assert rk.item_time(it, NOW).hour == 12
    assert rk.item_time({"date": "2026-10-29"}, datetime(2026, 10, 29, 3, tzinfo=timezone.utc)).hour == 3   # 不晚于现在
    assert rk.item_time({"date": "2026-10-29T08:30:00+00:00"}, NOW).hour == 8


def test_pop_percentile_ignores_old_outliers():
    items = [_it("old", "viral old", pop=100000, hours=24 * 90)] + [_it(f"n{i}", f"t{i}", pop=p) for i, p in enumerate([10, 20, 30, 40])]
    pops = rk.pop_index(items, NOW)
    assert rk.pop_norm(pops, items[-1]) == 1.0 and rk.pop_norm(pops, items[1]) == 0.25
    assert rk.pop_norm({"blog": [0, 0]}, {"source": "blog", "popularity": 0}) == rk.NO_POP_BASE


def test_follow_and_also_bonus():
    a = _it("twitter:1", "same tweet text here", source="twitter", extra={"via": "@karpathy"})
    b = _it("twitter:2", "other tweet text here", source="twitter", extra={"via": "LLM min_faves:500"})
    out = {x["id"]: x for x in rk.rank([a, b], now=NOW)}
    assert "关注账号" in out["twitter:1"]["why"] and "关注账号" not in out["twitter:2"]["why"]
    dup = [_it("hn:1", "A shared article", url="https://e.com/a"), _it("blog:1", "A shared article", source="blog", url="https://e.com/a"),
           _it("hn:2", "Lonely article", url="https://e.com/b")]
    out = rk.rank(dup, now=NOW)
    assert len(out) == 2 and "也见于" in out[0]["why"] and out[0]["score"] > out[1]["score"]


def test_source_affinity_needs_enough_examples():
    ex = [{"id": f"e{i}", "title": f"zz{i}", "source": "producthunt", "polarity": 1} for i in range(3)]
    out = rk.rank([_it("ph", "Some product", source="producthunt")], now=NOW, examples=ex)
    assert "你常赞" not in out[0]["why"]
    ex = [{"id": f"e{i}", "title": f"zz{i}", "source": "producthunt", "polarity": 1} for i in range(8)]
    out = rk.rank([_it("ph", "Some product", source="producthunt")], now=NOW, examples=ex)
    assert "你常赞 Product Hunt" in out[0]["why"]


def test_affinity_ignores_filler_words():
    ex = [{"id": "e", "title": "You don't need this today", "source": "hn", "polarity": 1}]
    out = rk.rank([_it("x", "Why you don't need agents today")], now=NOW, examples=ex)
    assert "你赞过相似内容" not in out[0]["why"]


def test_within_days_and_sort():
    items = rk.rank([_it("a", "fresh low", hours=2, pop=10), _it("b", "old high", hours=24 * 5, pop=500),
                     _it("c", "mid", hours=30, pop=100)], now=NOW)
    assert {x["id"] for x in rk.within_days(items, 1, NOW)} == {"a"}
    assert {x["id"] for x in rk.within_days(items, 3, NOW)} == {"a", "c"}
    assert [x["id"] for x in rk.sort_items(items, "new", NOW)] == ["a", "c", "b"]
    assert [x["id"] for x in rk.sort_items(items, "hot", NOW)] == ["b", "c", "a"]


def test_api_days_sort(client, monkeypatch):
    from app.modules import feed
    now = datetime.now(timezone.utc)
    fake = [{**_it("hn:1", "New one", pop=5), "date": (now - timedelta(hours=2)).isoformat()},
            {**_it("hn:2", "Old big", pop=900), "date": (now - timedelta(days=10)).isoformat()}]
    monkeypatch.setattr(feed, "_collectors", lambda: {"hn": lambda: fake})
    client.post("/api/feed/refresh", json={"sources": ["hn"], "wait": True})
    ids = lambda q: [x["id"] for x in client.get("/api/feed/items?" + q).json()["items"] if x["id"] in ("hn:1", "hn:2")]
    assert ids("days=1") == ["hn:1"]
    assert ids("sort=hot")[0] == "hn:2" and ids("sort=new")[0] == "hn:1"
    assert client.get("/api/feed/items?sort=bogus").status_code == 400


# ---------- X 长文标记 / 官方博客加权 ----------

def test_x_article_detection():
    stub = {"text": "https://t.co/BF6TE1AT9I", "entities": {"urls": []}, "media": []}
    assert src.is_x_article(stub)                                                     # GetXAPI 形状
    assert src.is_x_article({"text": "https://t.co/BF6", "entities": {"urls": [
        {"expanded_url": "https://x.com/i/article/2108450979251130368"}]}})               # twitterapi.io 形状
    assert not src.is_x_article({**stub, "media": [{"type": "photo"}]})               # 只有图
    assert not src.is_x_article({"text": "https://t.co/x", "entities": {"urls": [{"expanded_url": "https://e.com"}]}})
    assert not src.is_x_article({"text": "Real words here https://t.co/x", "entities": {"urls": []}})

    it = src.x_item(_tw(text="https://t.co/BF6TE1AT9I", entities={"urls": []}), "@a")
    assert it["title"] == "@a：发布了一篇 X 长文" and it["extra"]["x_article"] == "own" and it["extra"]["links"] == []
    q = src.x_item(_tw(quoted_tweet={"text": "https://t.co/zz", "entities": {"urls": []}, "author": {"userName": "b"}}), "@a")
    assert q["extra"]["x_article"] == "quoted" and "引用 @b：一篇 X 长文" in q["summary"]
    assert "x_article" not in src.x_item(_tw(), "@a")["extra"]
    g = src.x_item(_tw(quoted_tweet={"id": "9", "text": "orig words", "user": {"screen_name": "OpenRouter"}}), "@a")
    assert "引用 @OpenRouter：orig words" in g["summary"]                          # GetXAPI 的引用作者字段
    assert "引用：orig" in src.x_item(_tw(quoted_tweet={"text": "orig"}), "@a")["summary"]


def test_x_search_drops_untitled_articles(monkeypatch):
    monkeypatch.setenv("GETXAPI_KEY", "k1")
    recent = datetime.now(timezone.utc).strftime("%a %b %d %H:%M:%S +0000 %Y")
    tweets = [_tw(id="1", createdAt=recent, text="https://t.co/abc", entities={"urls": []}),
              _tw(id="2", createdAt=recent, text="My agent closed the hockey deal")]
    monkeypatch.setattr(src, "_client", lambda: httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json={"tweets": tweets}))))
    items, _ = src.fetch_x([], ["Claude min_faves:300"])
    assert items == []          # 长文补不到标题（这里接口没返回 article）就无从判断是否与 AI 相关，丢掉


def test_official_blog_and_article_bonus():
    assert rk.official_org({"source": "blog", "url": "https://www.anthropic.com/news/x"}) == "Anthropic"
    assert rk.official_org({"source": "blog", "url": "https://openai.com/index/model-spec"}) == "OpenAI"
    assert rk.official_org({"source": "blog", "url": "https://research.google/blog/x"}) == "Google Research"
    assert rk.official_org({"source": "hn", "url": "https://openai.com/x"}) == ""          # 只认博客条目
    assert rk.official_org({"source": "blog", "url": "https://notopenai.com/x"}) == ""
    items = [{**_it("blog:1", "zz official", source="blog", url="https://openai.com/index/a"), "type": "blog"},
             {**_it("blog:2", "zz personal", source="blog", url="https://someone.dev/a"), "type": "blog"},
             _it("twitter:1", "zz art", source="twitter", extra={"x_article": "own"}),
             _it("twitter:2", "zz plain", source="twitter")]
    out = {x["id"]: x for x in rk.rank(items, now=NOW)}
    assert abs(out["blog:1"]["score"] - out["blog:2"]["score"] - rk.W["official"]) < 1e-6 and "OpenAI 官方" in out["blog:1"]["why"]
    assert out["twitter:1"]["score"] > out["twitter:2"]["score"] and "X 长文" in out["twitter:1"]["why"]


def test_x_article_title_enrichment(monkeypatch):
    monkeypatch.setenv("GETXAPI_KEY", "k1")
    monkeypatch.setenv("TWITTER_API_KEY", "k2")
    recent = datetime.now(timezone.utc).strftime("%a %b %d %H:%M:%S +0000 %Y")
    stub = dict(text="https://t.co/abc", entities={"urls": []}, createdAt=recent)
    titles = {"1": "How we evaluate coding agents", "2": "How to build a profitable digital product", "4": "LLM eval notes"}
    article_calls = []

    def handler(req):
        if req.url.path == "/twitter/article":
            tid = req.url.params["tweet_id"]
            article_calls.append(tid)
            return httpx.Response(200, json={"article": {"title": titles.get(tid, ""), "preview_text": "opening text"}})
        if "advanced_search" in req.url.path:
            return httpx.Response(200, json={"tweets": [_tw(id="1", **stub), _tw(id="2", **stub), _tw(id="3", **stub)]})
        return httpx.Response(200, json={"tweets": [_tw(id="4", **stub)]})

    monkeypatch.setattr(src, "_client", lambda: httpx.Client(transport=httpx.MockTransport(handler)))
    items, errs = src.fetch_x(["a"], ["q"], min_likes=0, known_articles={"9"})
    got = {i["id"]: i for i in items}
    # 搜索来的：1 补到 AI 标题保留；2 与 AI 无关丢掉；3 没标题丢掉。名单账号发的 4 保留
    assert set(got) == {"twitter:1", "twitter:4"} and not errs
    assert got["twitter:1"]["title"] == "@a：How we evaluate coding agents" and got["twitter:1"]["summary"] == "opening text"
    assert sorted(article_calls) == ["1", "2", "3", "4"]
    article_calls.clear()
    items, _ = src.fetch_x([], ["q"], known_articles={"twitter:1"})
    assert "1" not in article_calls and "twitter:1" in {i["id"] for i in items}


def test_upsert_keeps_enriched_article_title(client):
    from app.modules import feed
    base = _it("twitter:77", "@a：Real article title", source="twitter", extra={"x_article": "own", "article_title": "Real article title"})
    feed.upsert([base])
    feed.upsert([{**base, "title": "@a：发布了一篇 X 长文", "summary": "", "popularity": 999, "extra": {"x_article": "own"}}])
    from app import db
    row = db.row("SELECT title, popularity FROM feed_items WHERE id='twitter:77'")
    assert row["title"] == "@a：Real article title" and row["popularity"] == 999


# ---------- 呈现清晰度：简介去重 / why 顺序与去重 / GitHub 标题 / HN 原文简介 ----------

def test_display_summary_drops_repeated_title():
    t = "@a：Shipping a new coding agent today"
    assert rk.display_summary(t, "Shipping a new coding agent today. It runs evals overnight and files PRs.") == \
        "It runs evals overnight and files PRs."
    assert rk.display_summary(t, "Shipping a new coding agent today") == ""                 # 只剩重复 → 不显示
    assert rk.display_summary("Paper title here", "Abstract text that differs a lot") == "Abstract text that differs a lot"
    assert rk.display_summary("@a：Long first sentence that got cu…", "Long first sentence that got cut off here, and more.") \
        == "cut off here, and more."


def test_why_order_and_dedup():
    it = _it("twitter:1", "Building a coding agent harness", source="twitter", extra={"via": "@karpathy", "x_article": "own"})
    ex = [{"id": "e", "title": "coding agent harness tricks", "source": "hn", "polarity": 1},
          {"id": "f", "title": "harness design notes", "source": "hn", "polarity": 1}]
    why = rk.rank([it], now=NOW, interests=["agent", "coding agent"], examples=ex)[0]["why"]
    assert why.startswith("X 长文 · 关注账号 @karpathy · X 100赞")
    assert "命中 coding agent" in why and "命中 agent" not in why
    assert "你赞过相似内容（harness）" in why          # coding / agent 已在「命中」里，不再重复


def test_github_title_has_description_and_age():
    items = [{**_it("github:o/r", "r：Tiny agent runtime", source="github", pop=1600, hours=24 * 5), "type": "repo"}]
    assert "GitHub 1.6k★（建 5 天）" in rk.rank(items, now=NOW)[0]["why"]


def test_fetch_github_title(monkeypatch):
    body = {"items": [{"full_name": "andy/digital-human", "description": "AI talking-head videos from one photo. Plus MCP.",
                       "html_url": "https://github.com/andy/digital-human", "stargazers_count": 10, "created_at": "2026-10-26"}]}
    monkeypatch.setattr(src, "_client", lambda: httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=body))))
    it = src.fetch_github(["llm"])[0]
    assert it["title"] == "digital-human：AI talking-head videos from one photo" and it["extra"]["repo"] == "andy/digital-human"


def test_fetch_hn_reads_link_description(monkeypatch):
    hits = {"hits": [
        {"objectID": "1", "title": "Big post", "url": "https://blog.example/a", "points": 500, "num_comments": 9, "created_at": "2026-10-30T00:00:00Z"},
        {"objectID": "2", "title": "Known post", "url": "https://blog.example/b", "points": 400, "created_at": "2026-10-30T00:00:00Z"},
        {"objectID": "3", "title": "Ask HN: thing", "story_text": "My own question text", "points": 50, "created_at": "2026-10-30T00:00:00Z"}]}
    pages = []

    def handler(req):
        if req.url.host == "hn.algolia.com":
            return httpx.Response(200, json=hits)
        pages.append(req.url.path)
        return httpx.Response(200, headers={"content-type": "text/html"},
                              text='<meta property="og:description" content="A long description of what the article says in detail.">')

    monkeypatch.setattr(src, "_client", lambda: httpx.Client(transport=httpx.MockTransport(handler)))
    got = {i["id"]: i for i in src.fetch_hn(["llm"], known_ids={"hn:2"})}
    assert got["hn:1"]["summary"] == "A long description of what the article says in detail."
    assert got["hn:2"]["summary"].startswith("链接到") and got["hn:3"]["summary"] == "My own question text"
    assert pages == ["/a"]


def test_upsert_keeps_hn_description(client):
    from app import db
    from app.modules import feed
    base = _it("hn:777", "Some HN post", summary="Real article description that we read once.")
    feed.upsert([base])
    feed.upsert([{**base, "summary": "链接到 example.com · 900 分", "popularity": 900}])
    row = db.row("SELECT summary, popularity FROM feed_items WHERE id='hn:777'")
    assert row["summary"] == "Real article description that we read once." and row["popularity"] == 900


def test_same_event_merge():
    items = [_it("hn:1", "Backdoors in official Claude Code extensions", pop=650),
             _it("hn:2", "Backdoor in Claude Code for VS Code extension on the Cursor Marketplace", pop=300),
             _it("twitter:1", "@GoogleDeepMind：Gemini 4 Carbon is our next frontier model", source="twitter", pop=100),
             {**_it("blog:1", "Gemini 4 Carbon: Our next frontier model", source="blog"), "type": "blog"},
             _it("hn:3", "10 Claude Code plugins I'd install on day one", pop=100),
             _it("hn:4", "Backdoors in official Claude Code extensions again", pop=100, hours=24 * 9)]   # 超过 4 天：不算同一件
    out = {x["id"]: x for x in rk.rank(items, now=NOW)}
    assert "hn:2" not in out and "也见于 HN" in out["hn:1"]["why"]
    assert len({"twitter:1", "blog:1"} & set(out)) == 1                       # 官方博客和官方推文是同一条新闻
    assert "hn:3" in out and "hn:4" in out
    assert rk.event_tokens("@a：Backdoors in Extensions") == {"backdoor", "extension"}


# ---------- 中文一句话 ----------

def _gist_handler(calls):
    def handler(req):
        rows = json.loads(json.loads(req.content)["messages"][1]["content"])
        calls.append(len(rows))
        items = [{"id": r["id"], "gist": f"中文概括{r['id']}"} for r in rows] + [{"id": "bogus", "gist": "不该出现"}]
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({"items": items}, ensure_ascii=False)}}]})
    return handler


def test_gist_pick_and_generate(monkeypatch):
    from app.modules import _feed_gist as g
    a = _it("a", "Title A", summary="sum a")
    b = {**_it("b", "Title B"), "extra": {"gist": "旧", "gist_src": g.gist_key(_it("b", "Title B"))}}
    c = {**_it("c", "Title C changed"), "extra": {"gist": "旧", "gist_src": "stale"}}
    zh = _it("zh", "新的创业机会，正在 Claude Code 和 Codex 周围长出来｜对谈 Treg")
    assert g.is_chinese(zh["title"]) and not g.is_chinese("@a：Claude Code 插件 plugins I'd install on day one")
    todo = g.pick([a, b, c, zh], {"paper": [a]}, top=10, per_type=5)
    assert [x["id"] for x in todo] == ["a", "c"]                    # b 已有且没变；a 只算一次；c 标题变了重做
    monkeypatch.setenv("DEEPSEEK_API_KEY", "k")
    calls = []
    many = [_it(f"i{n}", f"T{n}") for n in range(45)]
    got, errs = g.generate(many, client=httpx.Client(transport=httpx.MockTransport(_gist_handler(calls))))
    assert calls == [20, 20, 5] and len(got) == 45 and got["i3"] == "中文概括i3" and "bogus" not in got and not errs
    assert g.fit("短句") == "短句"
    long = "有文章称 Anthropic 官方 Claude Code 的 VS Code 扩展在 Cursor 上含恶意代码，会创建后门并上传本地文件，影响大量开发者的机器安全与凭据，社区正在讨论如何排查与清理受影响的安装"
    assert g.fit(long).endswith("…") and len(g.fit(long)) <= g.MAX_CHARS + 1 and "，会创建" not in g.fit(long)[-6:]
    monkeypatch.delenv("DEEPSEEK_API_KEY")
    assert g.generate(many)[1][0].startswith("未配置 DEEPSEEK_API_KEY")


def test_gist_runs_only_on_full_refresh(client, monkeypatch):
    from app import db
    from app.modules import _feed_gist as g, feed
    monkeypatch.setattr(feed, "_collectors", lambda: {"hn": lambda: [_it("hn:g1", "Gist me please")]})
    ran = []
    monkeypatch.setattr(g, "generate", lambda items, **kw: (ran.append(len(items)) or {x["id"]: "一句话" for x in items}, []))
    monkeypatch.setattr(feed, "cfg", lambda k: {"sources": ["hn"]}.get(k, feed.CFG_DEFAULTS.get(k)))
    st = client.post("/api/feed/refresh", json={"sources": ["hn"], "wait": True}).json()
    assert "gist" not in st["results"] and not ran                  # 只刷部分来源：不调模型
    st = client.post("/api/feed/refresh", json={"wait": True}).json()
    assert st["results"]["gist"]["count"] >= 1
    item = next(x for x in client.get("/api/feed/items?q=一句话").json()["items"] if x["id"] == "hn:g1")
    assert item["gist"] == "一句话"
    before = len(ran)
    client.post("/api/feed/gist")
    assert len(ran) == before or ran[-1] < ran[0]                    # 已生成且没变的不再送
    assert '"gist_src"' in db.row("SELECT extra FROM feed_items WHERE id='hn:g1'")["extra"]
