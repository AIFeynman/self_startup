"""项目：GitHub 每日 Trending + 新建仓库搜索；X 长文标签页。"""
from datetime import datetime, timezone

from app.modules import _feed_rank as rk, _feed_sources as src, feed

ROW = """<article class="Box-row">
  <h2 class="h3 lh-condensed"><a href="/{name}" class="Link">x</a></h2>
  <p class="col-9 color-fg-muted my-1 tmp-my-1 pr-4 tmp-pr-4">{desc}</p>
  <span itemprop="programmingLanguage">{lang}</span>
  <a href="/{name}/stargazers" class="Link"><svg class="octicon octicon-star"></svg>
        {stars}</a>
  <span class="d-inline-block float-sm-right"><svg></svg>{today} stars today</span>
</article>"""


def _page(*rows):
    return "<div>" + "".join(ROW.format(**r) for r in rows) + "</div>"


def test_parse_trending():
    page = _page({"name": "thedotmack/claude-mem", "desc": "Persistent context for every agent. Second sentence.",
                  "lang": "TypeScript", "stars": "106,289", "today": "1,140"},
                 {"name": "a/b", "desc": "", "lang": "", "stars": "12", "today": "3"})
    a, b = src.parse_trending(page, day="2026-10-31T00:00:00+00:00")
    assert a["id"] == "github:thedotmack/claude-mem" and a["title"] == "claude-mem：Persistent context for every agent"
    assert a["popularity"] == 106289 and a["extra"] == {"language": "TypeScript", "repo": "thedotmack/claude-mem",
                                                         "trending": "daily", "stars_gained": 1140, "trending_rank": 1}
    assert a["date"] == "2026-10-31T00:00:00+00:00" and b["title"] == "a/b" and b["extra"]["trending_rank"] == 2


def test_github_all_merges_and_is_fail_soft(monkeypatch):
    new = {"id": "github:x/new", "source": "github", "type": "repo", "title": "new", "date": "2026-10-28",
           "popularity": 150, "extra": {"query": "llm", "repo": "x/new"}}
    hot = {"id": "github:x/new", "source": "github", "type": "repo", "title": "new", "date": "2026-10-31",
           "popularity": 160, "extra": {"trending": "daily", "stars_gained": 90}}
    monkeypatch.setattr(src, "fetch_github", lambda q, min_stars: [new])
    monkeypatch.setattr(src, "fetch_github_trending", lambda since, langs: [hot])
    (it,), errs = src.fetch_github_all(["llm"])
    assert it["date"] == "2026-10-28" and it["extra"]["query"] == "llm" and it["extra"]["stars_gained"] == 90 and not errs

    def boom(*a):
        raise RuntimeError("403")
    monkeypatch.setattr(src, "fetch_github", boom)
    items, errs = src.fetch_github_all(["llm"])
    assert [i["extra"].get("trending") for i in items] == ["daily"] and "github search" in errs[0]


def test_trending_boost_and_no_repo_age_label():
    now = datetime(2026, 10, 31, 12, tzinfo=timezone.utc)
    it = {"id": "github:a/b", "source": "github", "type": "repo", "title": "b", "summary": "", "date": "2026-10-31T08:00:00+00:00",
          "popularity": 90000, "extra": {"trending": "daily", "stars_gained": 1200}}
    plain = {**it, "id": "github:c/d", "extra": {}}
    s1, why1 = rk.score_item(it, pop_norm=0.9, now=now, half_life_h=72, interests=[])
    s2, why2 = rk.score_item(plain, pop_norm=0.9, now=now, half_life_h=72, interests=[])
    assert s1 > s2 and "GitHub 今日 Trending +1200★" in why1 and not any("建" in w for w in why1)
    assert any("建 1 天" in w for w in why2)


def test_x_article_tab(client):
    feed.upsert([
        {"id": "twitter:1", "source": "twitter", "type": "discussion", "title": "@a：How to build agents", "date": "2026-10-30",
         "popularity": 300, "extra": {"x_article": "own", "article_title": "How to build agents"}},
        {"id": "twitter:2", "source": "twitter", "type": "discussion", "title": "@b：quote", "date": "2026-10-30",
         "popularity": 300, "extra": {"x_article": "quoted"}},
        {"id": "twitter:3", "source": "twitter", "type": "discussion", "title": "@c：plain tweet", "date": "2026-10-30",
         "popularity": 300, "extra": {}},
    ])
    ids = {x["id"] for x in client.get("/api/feed/items", params={"type": "x_article"}).json()["items"]}
    assert {"twitter:1", "twitter:2"} <= ids and "twitter:3" not in ids


def test_gists_cover_x_article_tab(client, monkeypatch):
    from app.modules import _feed_gist as gist
    seen = {}
    monkeypatch.setattr(gist, "pick", lambda top, tabs, n, m: seen.update(tabs) or [])
    feed.run_gists()
    assert "x_article" in seen and "repo" in seen
