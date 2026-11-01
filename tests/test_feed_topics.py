"""信息推荐的关键词：主题表派生各来源搜索词、按词统计效果、候选词。不触网、不调 LLM。"""
from datetime import datetime, timedelta, timezone

from app.modules import _feed_rank as rk
from app.modules import _feed_topics as tp

NOW = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
TOPICS = [
    {"name": "Coding Agent", "en": ["claude code", "coding agent"], "zh": ["Claude Code"], "github": ["claude code"]},
    {"name": "LLM", "en": ["LLM", "Claude Code"], "youtube": ["LLM explained"]},
    {"name": "停用", "en": ["off topic"], "off": True},
    {"name": "仅知乎", "zh": ["推理部署"]},
]


def test_queries_for_derives_per_source():
    assert tp.queries_for(TOPICS, "hn") == ["claude code", "coding agent", "LLM"]   # 大小写不同的重复词去掉、停用主题不用
    assert tp.queries_for(TOPICS, "github") == ["claude code", "LLM"]               # 写了来源键就只用它，没写的退回 en
    assert tp.queries_for(TOPICS, "youtube") == ["claude code", "coding agent", "LLM explained"]
    assert tp.queries_for(TOPICS, "zhihu") == ["Claude Code", "推理部署"]
    assert tp.queries_for(TOPICS, "x") == []                                         # X 默认上限 0
    assert tp.queries_for(TOPICS, "hn", cap=2) == ["claude code", "coding agent"]


def test_bad_terms_go_last_and_get_capped():
    stats = {"hn|claude code": {"verdict": "低效"}, "hn|coding agent": {"verdict": "有效"}}
    assert tp.queries_for(TOPICS, "hn", stats) == ["coding agent", "LLM", "claude code"]
    assert tp.queries_for(TOPICS, "hn", stats, cap=2) == ["coding agent", "LLM"]


def _z(id_, q, jv=None, **ex):
    return {"id": id_, "source": "zhihu", "type": "blog", "title": id_, "url": f"https://zhuanlan.zhihu.com/p/{id_}",
            "extra": {"via": "search", "query": q, "first_seen": (NOW - timedelta(days=2)).isoformat(),
                      **({"judge_value": jv} if jv is not None else {}), **ex}}


def test_term_stats_and_verdicts():
    items = [_z(f"a{i}", "Agent", 0.8) for i in range(4)] + [_z(f"b{i}", "大模型", 0.2) for i in range(7)] \
        + [_z("c0", "强化学习", 0.1), _z("old", "Agent", 0.9, first_seen="2026-08-01T00:00:00+00:00")] \
        + [{"id": "tw1", "source": "twitter", "title": "t", "url": "", "fetched_at": "2026-10-31T10:00:00",
            "extra": {"via": "LLM min_faves:500"}},
           {"id": "tw2", "source": "twitter", "title": "t", "url": "", "fetched_at": "2026-10-31T10:00:00",
            "extra": {"via": "@karpathy"}}]
    fb = {"c0": {"saved": 1}, "b0": {"vote": -1}}
    deep = {rk.norm_url("https://zhuanlan.zhihu.com/p/a1")}
    runs = {"zhihu|ai infra": {"runs": 3}, "zhihu|agent": {"runs": 5}}
    st = tp.term_stats(items, fb, deep, runs, low_value=rk.low_value, norm_url=rk.norm_url, now=NOW)
    a = st["zhihu|agent"]
    assert (a["found"], a["kept"], a["judged"], a["deep"], a["runs"], a["verdict"]) == (4, 4, 4, 1, 5, "有效")   # 过期的不算
    assert st["zhihu|大模型"]["verdict"] == "低效" and st["zhihu|大模型"]["kept"] == 0
    assert st["zhihu|强化学习"]["verdict"] == "有效"          # 收藏过就算有效，哪怕 Jev 分低
    assert st["zhihu|ai infra"]["verdict"] == "没搜到"
    assert st["x|llm min_faves:500"]["found"] == 1 and not any(k.startswith("x|@") for k in st)
    # 没有价值判断的来源只看互动：搜到很多但一条没点 → 低效
    assert tp.verdict({"found": 25, "kept": 25, "judged": 0, "liked": 0, "saved": 0, "clicked": 0, "deep": 0, "runs": 4}) == "低效"
    assert tp.verdict({"found": 25, "kept": 25, "judged": 0, "liked": 0, "saved": 0, "clicked": 1, "deep": 0, "runs": 4}) == "有效"
    assert tp.verdict({"found": 5, "kept": 5, "judged": 0, "liked": 0, "saved": 0, "clicked": 0, "deep": 0, "runs": 4}) == "数据不足"


def test_normalize_cleans_input():
    got = tp.normalize([{"name": " A ", "en": ["x", " X ", ""], "zh": ["中"], "bogus": ["y"], "off": 1},
                        {"name": "a", "en": ["dup"]}, {"name": ""}, "junk"])
    assert got == [{"name": "A", "en": ["x"], "zh": ["中"], "off": True}]
    assert tp.lang_of("推理部署") == "zh" and tp.lang_of("KV cache") == "en"


def test_suggest_filters_existing(monkeypatch):
    import json

    class C:
        def post(self, url, headers, json):  # noqa: A002
            return R()

        def close(self):
            pass

    class R:
        def raise_for_status(self):
            pass

        def json(self):
            rows = [{"name": "推理加速", "en": ["speculative decoding", "Claude Code"], "zh": ["投机解码"], "reason": "赞过 3 篇"},
                    {"name": "全是旧词", "en": ["coding agent"], "zh": ["拒绝过"]}]
            return {"choices": [{"message": {"content": json.dumps({"topics": rows}, ensure_ascii=False)}}]}
    monkeypatch.setenv("DEEPSEEK_API_KEY", "k")
    got, err = tp.suggest(["a", "b", "c"], TOPICS, ["拒绝过"], client=C())
    assert err == "" and got == [{"name": "推理加速", "en": ["speculative decoding"], "zh": ["投机解码"], "reason": "赞过 3 篇"}]
    assert tp.suggest(["a"], TOPICS, [], client=C())[1].startswith("赞 / 收藏")


def test_topics_api(client, monkeypatch):
    from app.modules import feed
    v = client.get("/api/feed/topics").json()
    assert v["topics"] and v["queries"]["hn"] and "X" == v["labels"]["x"]
    assert "x" in v["explicit"]          # X 用 settings 里的高级搜索语法，不从主题表派生
    v = client.put("/api/feed/topics", json={"topics": [{"name": "KV", "en": ["KV cache"], "zh": ["KV 缓存"]}]}).json()
    assert v["queries"]["hn"] == ["KV cache"] and v["queries"]["zhihu"] == ["KV 缓存"]
    assert feed.queries("github") == ["KV cache"]

    monkeypatch.setattr(feed.topics, "suggest", lambda *a, **k: ([{"name": "推理加速", "en": ["speculative decoding"],
                                                                   "zh": ["投机解码"], "reason": "r"}], ""))
    v = client.post("/api/feed/topics/suggest").json()
    assert v["added"] == 1 and v["suggestions"][0]["name"] == "推理加速"
    v = client.post("/api/feed/topics/suggestion", json={"name": "推理加速", "action": "accept"}).json()
    assert [t["name"] for t in v["topics"]] == ["KV", "推理加速"] and v["suggestions"] == []
    assert "reason" not in v["topics"][1]
    assert client.post("/api/feed/topics/suggestion", json={"name": "推理加速", "action": "accept"}).status_code == 404

    monkeypatch.setattr(feed.topics, "suggest", lambda *a, **k: ([{"name": "N", "en": ["n1"], "zh": []}], ""))
    client.post("/api/feed/topics/suggest")
    client.post("/api/feed/topics/suggestion", json={"name": "N", "action": "dismiss"})
    from app import settings
    assert "n1" in settings.get("feed.topic_dismissed")


def test_refresh_logs_queries(client, monkeypatch):
    from app.modules import feed
    client.put("/api/feed/topics", json={"topics": [{"name": "KV", "en": ["KV cache", "boom"]}]})
    monkeypatch.setattr(feed, "_collectors", lambda stats=None: {"hn": lambda: ([], ["boom: 500"])})
    client.post("/api/feed/refresh", json={"sources": ["hn"], "wait": True})
    runs = feed.query_runs()
    assert runs["hn|kv cache"]["runs"] == 1 and "hn|boom" not in runs   # 报错的词不算搜过
