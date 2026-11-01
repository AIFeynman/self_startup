"""信息推荐：Trending 只留 AI 项目；重要官方更新（Jev 判断或关键词规则）在「全部」置顶、进精选。"""
from datetime import datetime, timedelta, timezone

import httpx

from app import db
from app.modules import _feed_judge as judge, _feed_rank as rk, feed

NOW = datetime(2026, 10, 31, 12, tzinfo=timezone.utc)


def _repo(id_, title, *, extra, hours=2, pop=1000):
    return {"id": f"github:{id_}", "source": "github", "type": "repo", "title": title, "summary": "",
            "url": f"https://github.com/{id_}", "date": (NOW - timedelta(hours=hours)).isoformat(),
            "popularity": pop, "extra": extra}


def _blog(id_, title, *, host="openai.com", hours=2, extra=None):
    return {"id": f"blog:{id_}", "source": "blog", "type": "blog", "title": title, "summary": "",
            "url": f"https://{host}/index/{id_}", "date": (NOW - timedelta(hours=hours)).isoformat(),
            "popularity": 0, "extra": extra or {}}


def test_trending_non_ai_filtered():
    t = {"trending": "daily", "stars_gained": 900}
    items = [_repo("a/ziwei", "ziwei：紫微斗数排盘引擎", extra=dict(t)),
             _repo("a/mem", "mem：Persistent memory for every agent", extra=dict(t)),
             _repo("a/judged", "judged：A toolkit", extra={**t, "judge_ai": 0.9}),         # Jev 判是 AI，关键词没中也留
             _repo("a/devops", "devops：Interview questions about LLM ops", extra={**t, "judge_ai": 0.1}),  # Jev 优先于关键词
             _repo("a/searched", "searched：menu bar app", extra={**t, "query": "llm"})]   # 搜索收的不按 Trending 过滤
    ids = {x["id"] for x in rk.rank(items, now=NOW)}
    assert ids == {"github:a/mem", "github:a/judged", "github:a/searched"}
    # 收藏过的不丢
    kept = rk.rank(items, now=NOW, feedback={"github:a/ziwei": {"saved": 1}}, include_hidden=True)
    assert "github:a/ziwei" in {x["id"] for x in kept}


def test_important_official_rules():
    assert rk.important_official(_blog("x", "How we detect frontier model misalignment"), NOW)
    assert not rk.important_official(_blog("y", "Credit Saison achieves 954% ROI in a ChatGPT Enterprise pilot"), NOW)
    assert not rk.important_official(_blog("z", "OpenAI and ServiceNow expand partnership"), NOW)
    assert not rk.important_official(_blog("old", "Gemini 9", host="blog.google", hours=24 * 5), NOW)   # 过了 PIN_DAYS
    assert not rk.important_official(_blog("n", "A new model", host="example.com"), NOW)              # 不是官方
    # Jev 判断优先于关键词
    assert rk.important_official(_blog("j", "Expanding partnership for safety research", extra={"judge_important": 0.8}), NOW)
    assert not rk.important_official(_blog("k", "Our new model", extra={"judge_important": 0.2}), NOW)
    # 机构新仓库：没判断时看星数
    assert rk.important_official(_repo("deepseek-ai/x", "x", extra={"watch_org": "deepseek-ai"}, pop=2400), NOW)
    assert not rk.important_official(_repo("microsoft/y", "y", extra={"watch_org": "microsoft"}, pop=20), NOW)


def test_pinned_official_go_first_and_into_picks():
    hot = [{**_repo(f"h/{i}", f"hot {i}", extra={"query": "llm"}, pop=90000), "type": "discussion",
            "source": f"src{i}"} for i in range(10)]
    pins = [_blog("p1", "How we detect frontier model misalignment"),
            _blog("p2", "An updated Model Spec", host="anthropic.com"),
            _blog("p3", "Community safety report")]
    out = rk.diversify(rk.rank(hot + pins, now=NOW))
    flags = [bool(x.get("pinned")) for x in out]
    # 分最高的 2 条进精选（前 5），剩下的紧接在精选之后；精选其余 3 个位置照常按分数 + 来源配额
    assert flags[:6] == [True, True, False, False, False, True] and sum(flags) == 3
    assert "重要更新" in out[0]["why"] and len(out) == len(hot) + len(pins)


def test_judge_parses_noul_and_skips_missing(monkeypatch):
    monkeypatch.setenv("JEV_API_KEY", "test-key")
    a, b = _repo("a/x", "x：agent", extra={"trending": "daily"}), _blog("y", "Model Spec")
    seen = {}

    def handler(req: httpx.Request):
        body = __import__("json").loads(req.content)
        seen.update(body)
        return httpx.Response(200, json={"answers": {"i0_ai": {"type": "noul", "noul": 0.93}}})   # i1 漏了

    got, errs = judge.judge([(a, "ai", ""), (b, "important", "OpenAI")], client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert got == {"github:a/x": {"judge_ai": 0.93}} and "少返回 1 条" in errs[0]
    assert seen["model"] == "jev-latest" and set(seen["questions"]) == {"i0_ai", "i1_important"}
    assert "OpenAI" in seen["questions"]["i1_important"]["instructions"]
    assert seen["state"]["items"]["i0"]["title"] == "x：agent"


def test_judge_without_key(monkeypatch):
    monkeypatch.delenv("JEV_API_KEY", raising=False)
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    got, errs = judge.judge([(_blog("y", "x"), "important", "OpenAI")])
    assert got == {} and "TYPESAFE_API_KEY" in errs[0]


def test_run_judge_writes_back_once(monkeypatch):
    now = datetime.now(timezone.utc)
    feed.upsert([{**_repo("q/trend", "trend：a thing", extra={"trending": "daily"}), "date": now.isoformat()},
                 {**_blog("q1", "Our next frontier model"), "date": now.isoformat()},
                 {**_blog("q2", "Old post"), "date": (now - timedelta(days=10)).isoformat()}])
    calls = []

    def fake(todo):
        calls.append([(it["id"], kind) for it, kind, _ in todo])
        return {it["id"]: {f"judge_{kind}": 0.7} for it, kind, _ in todo}, []
    monkeypatch.setattr(judge, "judge", fake)
    feed.run_judge()
    assert sorted(calls[0]) == [("blog:q1", "important"), ("github:q/trend", "ai")]   # 旧帖不问
    ex = feed._extra(db.row("SELECT extra FROM feed_items WHERE id='blog:q1'"))
    assert ex["judge_important"] == 0.7 and ex["judge_src"] == judge.judge_key({"title": "Our next frontier model", "summary": ""})
    feed.run_judge()
    assert len(calls) == 1 or all(i not in {"blog:q1", "github:q/trend"} for i, _ in calls[1])   # 内容没变不重复问


def test_new_badge_and_days_on_list():
    seen = lambda h: {"first_seen": (NOW - timedelta(hours=h)).isoformat()}
    items = [_repo("n/fresh", "fresh：agent", extra=seen(3)),
             _repo("n/stale", "stale：agent", extra=seen(24 * 5)),
             _repo("n/legacy", "legacy：agent", extra={}, hours=24 * 10),      # 加字段前收的：按发布时间，不算在榜天数
             _repo("n/legacy2", "legacy2：agent", extra={}, hours=2)]
    got = {x["id"]: (x["new"], x["seen_days"]) for x in rk.rank(items, now=NOW)}
    assert got == {"github:n/fresh": (True, 0), "github:n/stale": (False, 5),
                   "github:n/legacy": (False, 0), "github:n/legacy2": (True, 0)}


def test_upsert_keeps_first_seen():
    feed.upsert([_blog("fs", "First")])
    first = feed._extra(db.row("SELECT extra FROM feed_items WHERE id='blog:fs'"))["first_seen"]
    feed.upsert([_blog("fs", "First, edited")])
    assert feed._extra(db.row("SELECT extra FROM feed_items WHERE id='blog:fs'"))["first_seen"] == first
