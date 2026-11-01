"""信息推荐：分类页手动刷新、关注源增删（输入解析、默认名单增删不冻结）。"""
import pytest

from app import settings
from app.modules import _feed_follow as follow, feed


def test_effective_add_remove_dedup():
    fc = {"add": {"x_accounts": ["karpathy", "NewGuy"]}, "remove": {"x_accounts": ["openai"]}}
    assert follow.effective(["OpenAI", "Karpathy", "simonw"], fc, "x_accounts") == ["Karpathy", "simonw", "NewGuy"]
    sites = [{"name": "A", "url": "https://a.com/blog/"}]
    assert follow.effective(sites, {"add": {"sites": [{"name": "A2", "url": "https://a.com/blog"}]}}, "sites") == sites


@pytest.mark.parametrize("group,text,want", [
    ("x", "@karpathy", ("x_accounts", "karpathy")),
    ("x", "https://x.com/simonw/status/123", ("x_accounts", "simonw")),
    ("x", "twitter.com/_jasonwei", ("x_accounts", "_jasonwei")),
    ("reddit", "r/LocalLLaMA", ("reddit", "LocalLLaMA")),
    ("reddit", "https://www.reddit.com/r/ClaudeAI/", ("reddit", "ClaudeAI")),
])
def test_resolve_handles(group, text, want):
    assert follow.resolve(group, text)[:2] == want


def test_resolve_rejects_garbage():
    with pytest.raises(follow.FollowError):
        follow.resolve("x", "not a handle!!")
    with pytest.raises(follow.FollowError):
        follow.resolve("site", "hello")


def test_guess_link_re_from_listing_page():
    page = """<a href="/about">About</a><a href="/pricing">x</a>
      <a href="/news/introducing-model-x">1</a><a href="https://ex.com/news/agents-at-scale/">2</a>
      <a href="/news/2026-safety-report">3</a><a href="/careers/senior-engineer-ml">job</a>"""
    rx = follow.guess_link_re("https://ex.com/news", page)
    import re
    hits = [m for m in re.findall(rf"""href\s*=\s*['"]({rx})['"]""", page)]
    assert hits == ["/news/introducing-model-x", "https://ex.com/news/agents-at-scale/", "/news/2026-safety-report"]
    assert follow.guess_link_re("https://ex.com/", '<a href="/about">a</a>') == ""


def test_site_rss_discovery_and_podcast_search():
    import httpx
    feed_xml = """<?xml version="1.0"?><rss version="2.0"><channel><title>Ex Blog</title>
      <item><title>Post</title><link>https://ex.com/p/1</link></item></channel></rss>"""

    def handler(req: httpx.Request):
        u = str(req.url)
        if u.startswith("https://ex.com/feed"):
            return httpx.Response(200, text=feed_xml)
        if u.startswith("https://ex.com"):
            return httpx.Response(200, text='<html><head><link rel="alternate" type="application/rss+xml" href="/feed.xml"></head></html>')
        if "itunes.apple.com/search" in u:
            return httpx.Response(200, json={"results": [{"collectionName": "Latent Space", "feedUrl": "https://pod.example/rss"}]})
        return httpx.Response(404)
    c = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    assert follow.resolve("site", "ex.com", client=c) == ("rss", "https://ex.com/feed.xml", "Ex Blog")
    assert follow.resolve("podcast", "Latent Space", client=c) == ("podcasts", "https://pod.example/rss", "Latent Space")
    assert follow.resolve("podcast", "https://www.xiaoyuzhoufm.com/podcast/626b46ea9cbbf0451cf5a962", client=c)[:2] == \
        ("xiaoyuzhou", "https://www.xiaoyuzhoufm.com/podcast/626b46ea9cbbf0451cf5a962")


def test_add_remove_sources_api(client, monkeypatch):
    started = []
    monkeypatch.setattr(feed, "start_refresh", lambda only=None, gists=None, scope="": started.append(only) or True)
    r = client.post("/api/feed/sources", json={"group": "x", "value": "@SomeNewAuthor"}).json()
    assert r["list"] == "x_accounts" and r["refreshing"] and started == [["x"]]
    assert "SomeNewAuthor" in feed.src_list("x_accounts")
    x = next(g for g in r["groups"] if g["id"] == "x")
    assert any(i["key"] == "somenewauthor" and i["custom"] for i in x["items"])
    # 再加一次：已存在，不重复、不再刷新
    assert client.post("/api/feed/sources", json={"group": "x", "value": "x.com/somenewauthor"}).json()["exists"]
    assert len(started) == 1
    # 删自己加的 → 从 add 里删；删默认的 → 记进 remove，默认名单本身不写进设置
    client.post("/api/feed/sources/remove", json={"list": "x_accounts", "key": "somenewauthor"})
    client.post("/api/feed/sources/remove", json={"list": "x_accounts", "key": "karpathy"})
    lst = [h.lower() for h in feed.src_list("x_accounts")]
    assert "somenewauthor" not in lst and "karpathy" not in lst and "simonw" in lst
    assert settings.get("feed.follow.remove.x_accounts") == ["karpathy"]
    # 重新关注默认里删掉的：从 remove 里拿掉
    client.post("/api/feed/sources", json={"group": "x", "value": "karpathy"})
    assert "karpathy" in [h.lower() for h in feed.src_list("x_accounts")]
    assert client.post("/api/feed/sources", json={"group": "x", "value": "bad handle!"}).status_code == 400
    assert client.post("/api/feed/sources/remove", json={"list": "x_accounts", "key": "nobody"}).status_code == 404


def test_refresh_by_type(client, monkeypatch):
    calls = []
    monkeypatch.setattr(feed, "refresh_sync", lambda only=None, gists=None: calls.append((only, gists)) or {})
    client.post("/api/feed/refresh", json={"type": "podcast", "wait": True})
    assert calls == [(["podcast", "xiaoyuzhou"], True)]
    assert client.post("/api/feed/refresh", json={"type": "nope"}).status_code == 400


def test_upsert_counts_new():
    it = {"id": "blog:zz1", "source": "blog", "type": "blog", "title": "T", "summary": "", "url": "https://e.com/1",
          "date": "", "popularity": 0, "extra": {}}
    assert feed._upsert([it]) == (1, 1)
    assert feed._upsert([it, {**it, "id": "blog:zz2"}]) == (2, 1)
