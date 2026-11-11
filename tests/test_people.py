import json
from datetime import datetime, timedelta, timezone

import httpx

from app import db
from app.modules import _feed_sources as src
from app.modules import _people as P


def _iso(days_ago=0.0):
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _xtime(days_ago=0.0):
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime("%a %b %d %H:%M:%S +0000 %Y")


def _mock(monkeypatch, handler):
    monkeypatch.setattr(src, "_client", lambda: httpx.Client(transport=httpx.MockTransport(handler)))


def _person(pid):
    return P.by_id()[pid]


def _wipe():
    P._init()
    db.execute("DELETE FROM people_rejected")
    db.execute("DELETE FROM people_items")
    db.execute("DELETE FROM people_runs")


def test_people_file_is_complete():
    ps = P.people()
    assert len(ps) == 110 and len({p["id"] for p in ps}) == 110
    assert all(p["name"] and p["tier"] in (1, 2) for p in ps)
    assert all(p["orgs"] for p in ps if p["strict"])


def test_mentions_uses_names_aliases_and_org_for_common_names():
    karpathy, tony, feifei = _person("karpathy"), _person("tonywu"), _person("feifei")
    assert P.mentions(karpathy, "Andrej Karpathy on agents")
    assert not P.mentions(karpathy, "Andrej Karpathyx")
    assert P.mentions(feifei, "李飞飞谈空间智能") and P.mentions(feifei, "Fei-Fei Li at Stanford")
    assert not P.mentions(tony, "Tony Wu wins local chess cup")
    assert P.mentions(tony, "Tony Wu, xAI co-founder, on math reasoning")
    assert P.mentions(_person("dario"), "Anthropic CEO predicts AI could help end major diseases")
    assert P.mentions(_person("yanjunjie"), "MiniMax CEO：低推理成本就是护城河")
    assert not P.mentions(_person("dario"), "OpenAI CEO on compute")


def test_fetch_x_maps_authors_and_drops_old(monkeypatch):
    seen = []

    def call(c, provs, kind, q):
        seen.append(q)
        if "from:karpathy" not in q:
            return []
        return [{"id": "1", "text": "new thoughts on agents", "createdAt": _xtime(0.2), "likeCount": 9, "author": {"userName": "karpathy"}},
                {"id": "2", "text": "old", "createdAt": _xtime(5), "author": {"userName": "karpathy"}},
                {"id": "3", "text": "reply", "createdAt": _xtime(0.1), "isReply": True, "author": {"userName": "karpathy"}}]
    monkeypatch.setattr(src, "_x_providers", lambda: [{"name": "fake"}])
    monkeypatch.setattr(src, "_x_call", call)
    items, errs = P.fetch_x(P.people())
    assert not errs and [i["id"] for i in items] == ["twitter:1"] and items[0]["people"] == ["karpathy"]
    assert all("-filter:replies" in q and "since:" in q for q in seen)
    assert all(q.count("from:") <= P.X_CHUNK for q in seen)


def test_fetch_youtube_keeps_own_talks_and_drops_shorts_and_unrelated(monkeypatch):
    sn = lambda t, ch="UCother": {"title": t, "description": "", "publishedAt": _iso(0.5), "channelId": ch, "channelTitle": "c",
                                  "defaultAudioLanguage": "en"}
    vids = {"a": (sn("Andrej Karpathy: full interview on agents"), "PT1H2M"), "b": (sn("Andrej Karpathy #shorts"), "PT50S"),
            "c": (sn("Cooking pasta at home"), "PT20M"), "d": (sn("Weekly roundup", "UCtrusted"), "PT30M")}
    vids["d"][0]["description"] = "with Andrej Karpathy"

    def handler(req):
        if req.url.path.endswith("/search"):
            return httpx.Response(200, json={"items": [{"id": {"videoId": v}, "snippet": vids[v][0]} for v in vids]})
        ids = req.url.params["id"].split(",")
        return httpx.Response(200, json={"items": [{"id": v, "snippet": vids[v][0], "contentDetails": {"duration": vids[v][1]},
                                                    "statistics": {"viewCount": "10"}} for v in ids]})
    _mock(monkeypatch, handler)
    monkeypatch.setattr(P, "trusted_channels", lambda: {"UCtrusted"})
    items, errs = P.fetch_youtube([_person("karpathy")], key="k")
    assert not errs and sorted(i["id"] for i in items) == ["youtube:a", "youtube:d"]
    assert all(i["people"] == ["karpathy"] for i in items)


def test_fetch_podcast_needs_recent_and_named(monkeypatch):
    def handler(req):
        return httpx.Response(200, json={"results": [
            {"trackId": 1, "trackName": "Jim Fan on foundation agents", "releaseDate": _iso(1), "collectionName": "Show"},
            {"trackId": 2, "trackName": "Jim Fan on robots", "releaseDate": _iso(30)},
            {"trackId": 3, "trackName": "Gardening tips", "releaseDate": _iso(1)}]})
    _mock(monkeypatch, handler)
    items, _ = P.fetch_podcast([_person("jimfan")], pause=0)
    assert [i["id"] for i in items] == ["podcast:1"] and items[0]["extra"]["show"] == "Show"


def test_fetch_paper_matches_exact_author(monkeypatch):
    feed = f"""<feed xmlns="http://www.w3.org/2005/Atom">
      <entry><id>http://arxiv.org/abs/2611.00001v1</id><published>{_iso(1)}</published><title>A</title><summary>s</summary>
        <author><name>Neel Nanda</name></author></entry>
      <entry><id>http://arxiv.org/abs/2611.00002v1</id><published>{_iso(1)}</published><title>B</title><summary>s</summary>
        <author><name>Neel Nandakumar</name></author></entry></feed>"""
    _mock(monkeypatch, lambda req: httpx.Response(200, text=feed))
    items, errs = P.fetch_paper([_person("neel")], pause=0)
    assert not errs and [i["id"] for i in items] == ["arxiv:2611.00001"] and items[0]["people"] == ["neel"]


def test_news_items_keep_titles_naming_the_person_within_window():
    pub = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
    old = (datetime.now(timezone.utc) - timedelta(days=9)).strftime("%a, %d %b %Y %H:%M:%S GMT")
    rss = f"""<rss><channel>
      <item><title>Geoffrey Hinton likens AI risks to Chernobyl - Outlet</title><link>https://n/1</link><pubDate>{pub}</pubDate></item>
      <item><title>Yoshua Bengio on safety - Outlet</title><link>https://n/2</link><pubDate>{pub}</pubDate></item>
      <item><title>Geoffrey Hinton wins prize - Outlet</title><link>https://n/3</link><pubDate>{old}</pubDate></item>
    </channel></rss>"""
    items = P.news_items(_person("hinton"), rss)
    assert [i["title"] for i in items] == ["Geoffrey Hinton likens AI risks to Chernobyl"]
    assert "hl=zh-CN" in P.news_url("杨植麟") and "hl=en-US" in P.news_url("Geoffrey Hinton")
    assert P.search_names(_person("ng")) == ["Andrew Ng", "吴恩达"] and P.search_names(_person("yangzhilin")) == ["杨植麟"]


def test_bilingual_people_are_searched_in_both_languages(monkeypatch):
    terms = []

    def handler(req):
        terms.append((req.url.params["term"], req.url.params["country"]))
        return httpx.Response(200, json={"results": []})
    _mock(monkeypatch, handler)
    P.fetch_podcast([_person("feifei")], pause=0)
    assert terms == [("Fei-Fei Li", "us"), ("李飞飞", "cn")]


def test_loud_x_accounts_are_searched_alone(monkeypatch):
    seen = []
    monkeypatch.setattr(src, "_x_providers", lambda: [{"name": "fake"}])
    monkeypatch.setattr(src, "_x_call", lambda c, provs, kind, q: seen.append(q) or [])
    P.fetch_x(P.people())
    assert any(q.startswith("(from:elonmusk)") for q in seen)
    assert not any("from:elonmusk" in q and " OR " in q for q in seen)


def test_voice_filter_drops_commentary_and_keeps_batch_on_failure():
    items = [P._item("news:1", "news", ["hinton"], "Hinton warns", "u", ""), P._item("news:2", "news", ["hinton"], "About Hinton", "u", "")]
    judge = lambda prompt, system, model: {"text": json.dumps({"items": [{"id": "news:1", "voice": True}, {"id": "news:2", "voice": False}]})}
    kept, rejected, errs = P.voice_filter(items, judge)
    assert [i["id"] for i in kept] == ["news:1"] and rejected == ["news:2"] and not errs

    calls = []

    def boom(*a, **k):
        calls.append(1)
        raise RuntimeError("offline")
    kept, rejected, errs = P.voice_filter(items, boom, retry_wait=0)
    assert kept == [] and rejected == [] and len(calls) == 2 and "下轮重判" in errs[0]

    replies = iter(["busy", json.dumps({"items": [{"id": "news:1", "voice": True}, {"id": "news:2", "voice": False}]})])
    kept, _, errs = P.voice_filter(items, lambda *a, **k: {"text": next(replies)}, retry_wait=0)
    assert [i["id"] for i in kept] == ["news:1"] and not errs


def test_run_merges_people_judges_new_only_and_notifies_once(monkeypatch):
    _wipe()
    sent = []
    monkeypatch.setattr(P.notify, "notify", lambda *a, **k: sent.append((a, k)) or 1)
    batches = [[P._item("youtube:v1", "youtube", ["karpathy"], "Karpathy talk", "u", "2026-11-10"),
                P._item("youtube:v2", "youtube", ["karpathy"], "About Karpathy", "u", "2026-11-10")],
               [P._item("youtube:v1", "youtube", ["feifei"], "Karpathy talk", "u", "2026-11-10"),
                P._item("youtube:v2", "youtube", ["karpathy"], "About Karpathy", "u", "2026-11-10")]]
    monkeypatch.setattr(P, "FETCHERS", {"youtube": lambda pool: (batches.pop(0), []), "x": lambda pool: ([], ["X boom"])})
    judged = []

    def judge(prompt, system, model):
        rows = json.loads(prompt)
        judged.extend(r["id"] for r in rows)
        return {"text": json.dumps({"items": [{"id": r["id"], "voice": r["id"] == "youtube:v1"} for r in rows]})}
    r = P.run(["youtube", "x"], judge=(judge, "m"))
    assert r["youtube"] == {"count": 1, "new": 1, "errors": []} and r["x"]["errors"] == ["X boom"]
    assert len(sent) == 1 and "名人新发声 1 条" in sent[0][0][1]
    r = P.run(["youtube"], judge=(judge, "m"))
    assert judged == ["youtube:v1", "youtube:v2"] and r["youtube"]["new"] == 0 and len(sent) == 1
    assert db.row("SELECT id FROM people_rejected WHERE id='youtube:v2'")
    row = db.row("SELECT people, notified FROM people_items WHERE id='youtube:v1'")
    assert json.loads(row["people"]) == ["feifei", "karpathy"] and row["notified"] == 1
    assert set(P.due()) == set(P.CHANNELS) - {"youtube", "x"}


def test_people_api(client, monkeypatch):
    _wipe()
    P.upsert([P._item("arxiv:1", "paper", ["neel", "hinton"], "Paper", "https://arxiv.org/abs/1", "2026-11-10")])
    r = client.get("/api/feed/people?days=1").json()
    assert [g["person"]["id"] for g in r["groups"]] == ["hinton", "neel"]
    assert {c["id"] for c in r["channels"]} == set(P.CHANNELS)
    r = client.get("/api/feed/people?person=neel").json()
    assert r["person"]["id"] == "neel" and [i["id"] for i in r["items"]] == ["arxiv:1"]
    calls = []
    monkeypatch.setattr(P, "start", lambda chans=None: calls.append(chans) or True)
    assert client.post("/api/feed/people/refresh", json={"channels": ["x"]}).json()["started"] is True
    assert calls == [["x"]]
    db.execute("INSERT OR REPLACE INTO people_runs(channel, at) VALUES('youtube', ?)", [db.now()])
    assert "youtube" not in P.manual_channels() and "x" in P.manual_channels()


def test_fetch_blog_reads_own_feeds_within_window(monkeypatch):
    pub = lambda d: (datetime.now(timezone.utc) - timedelta(days=d)).strftime("%a, %d %b %Y %H:%M:%S GMT")
    rss = f"""<rss><channel>
      <item><title>New essay</title><link>https://garymarcus.substack.com/p/new</link><pubDate>{pub(1)}</pubDate></item>
      <item><title>Old essay</title><link>https://garymarcus.substack.com/p/old</link><pubDate>{pub(30)}</pubDate></item>
    </channel></rss>"""
    _mock(monkeypatch, lambda req: httpx.Response(200, text=rss))
    items, errs = P.fetch_blog([_person("marcus"), _person("hinton")])
    assert not errs and [i["title"] for i in items] == ["New essay"] and items[0]["people"] == ["marcus"]
    assert items[0]["extra"]["site"] == "garymarcus.substack.com"


def test_local_haiku_runs_outside_any_repo(monkeypatch):
    from pathlib import Path
    from app.modules import feed
    seen = {}
    monkeypatch.setattr(feed.agent, "run_once", lambda prompt, **kw: seen.update(kw) or {"text": "{}"})
    feed._haiku("p", system="s", model="m")
    repo = Path(__file__).resolve().parents[1]
    assert seen.get("cwd") and not Path(seen["cwd"]).resolve().is_relative_to(repo)
    assert not (Path(seen["cwd"]) / ".git").exists()
