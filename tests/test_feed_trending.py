"""项目：GitHub 每日 Trending + 新建仓库搜索；X 长文标签页。"""
from datetime import datetime, timedelta, timezone

import pytest

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
    plain = {**it, "id": "github:c/d", "popularity": 300, "extra": {}}
    s1, why1 = rk.score_item(it, pop_norm=0.9, now=now, half_life_h=72, interests=[])
    s2, why2 = rk.score_item(plain, pop_norm=0.9, now=now, half_life_h=72, interests=[])
    assert s1 > s2 and "GitHub 今日 Trending +1200★" in why1 and not any("建" in w for w in why1)
    assert any("建 1 天" in w for w in why2)



def test_new_repo_velocity_boost():
    """刚建、还没上 Trending 但涨星飞快的仓库，按 Trending 同等加分；涨得慢或建得久的不加。"""
    now = datetime(2026, 11, 1, 0, tzinfo=timezone.utc)
    base = {"source": "github", "type": "repo", "title": "x", "summary": "", "extra": {}}
    fast = {**base, "id": "github:a/fast", "date": "2026-10-31T09:30:00+00:00", "popularity": 1890}
    slow = {**base, "id": "github:a/slow", "date": "2026-10-31T09:30:00+00:00", "popularity": 300}
    old = {**base, "id": "github:a/old", "date": "2026-10-20T00:00:00+00:00", "popularity": 9000}
    hours = {**base, "id": "github:a/hours", "date": "2026-10-31T22:00:00+00:00", "popularity": 400}
    kw = dict(pop_norm=0.5, now=now, half_life_h=72, interests=[])
    (sf, wf), (ss, ws) = rk.score_item(fast, **kw), rk.score_item(slow, **kw)
    assert sf - ss == pytest.approx(rk.W["trending"]) and "新仓库涨星快 ≈1.9k★/天" in wf
    assert not any("涨星快" in w for w in ws)
    assert not any("涨星快" in w for w in rk.score_item(old, **kw)[1])     # 建 12 天，超出一周窗口
    assert not any("涨星快" in w for w in rk.score_item(hours, **kw)[1])   # 不满一天按一天算：400★ 不够


def test_github_orgs_watch(monkeypatch):
    """重点机构新仓库：只要窗口内、非 fork / 归档、过了星数门槛的；标上 watch_org，排序时按官方加分。"""
    now = datetime.now(timezone.utc)
    ago = lambda d: (now - timedelta(days=d)).strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
    repos = {"deepseek-ai": [
        {"full_name": "deepseek-ai/new", "description": "Towards a More Autonomous Agent System", "created_at": ago(0.5),
         "stargazers_count": 1890, "html_url": "https://github.com/deepseek-ai/new"},
        {"full_name": "deepseek-ai/fork", "created_at": ago(1), "stargazers_count": 50, "fork": True},
        {"full_name": "deepseek-ai/empty", "created_at": ago(2), "stargazers_count": 0},
        {"full_name": "deepseek-ai/old", "created_at": ago(30), "stargazers_count": 9000}]}

    class Resp:
        status_code = 200
        def __init__(self, data):
            self.data = data
        def raise_for_status(self):
            pass
        def json(self):
            return self.data

    class Client:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            pass
        def get(self, url, **kw):
            return Resp(repos[url.split("/users/")[1].split("/")[0]])

    monkeypatch.setattr(src, "_client", Client)
    (it,) = src.fetch_github_orgs(["deepseek-ai"])
    assert it["id"] == "github:deepseek-ai/new" and it["extra"]["watch_org"] == "deepseek-ai"
    assert it["title"] == "new：Towards a More Autonomous Agent System"

    kw = dict(pop_norm=0.5, now=now, half_life_h=72, interests=[])
    s1, why1 = rk.score_item(it, **kw)
    s2, _ = rk.score_item({**it, "id": "github:x/new", "extra": {}}, **kw)
    assert s1 - s2 == pytest.approx(rk.W["official"]) and "DeepSeek 官方" in why1
    # 机构的老仓库上 Trending（没有 watch_org）不叠官方分
    assert rk.official_org({"source": "github", "extra": {"trending": "daily", "repo": "anthropics/skills"}}) == ""

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
