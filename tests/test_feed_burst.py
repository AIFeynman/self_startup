from datetime import datetime, timedelta, timezone

from app.modules import _feed_cluster as cluster
from app.modules import _feed_rank as rk

NOW = datetime(2026, 11, 21, 12, tzinfo=timezone.utc)


def _it(id_, title, *, source, hours=6, pop=100, summary="", type_="discussion"):
    return {"id": id_, "source": source, "type": type_, "title": title, "summary": summary,
            "url": f"https://example.com/{id_}", "date": (NOW - timedelta(hours=hours)).isoformat(),
            "popularity": pop, "extra": {}}


def background(n=40):
    """近 30 天的日常条目：claude / agent 天天有人说，不算突发。"""
    return [_it(f"bg{i}", f"Claude agent tips part {i}", source=("hn", "reddit", "twitter", "blog")[i % 4], hours=24 * (3 + i % 25))
            for i in range(n)] + [_it(f"now{i}", f"Claude agent workflow {i}", source=("hn", "twitter")[i % 2], hours=5) for i in range(6)]


def riemann():
    return [
        _it("paper", "A Claimed Proof of the Riemann Hypothesis", source="arxiv", type_="paper", pop=80),
        _it("blog1", "Hours after Anthropic claims a Claude proof of the Riemann hypothesis, Stanford releases a draft", source="blog", type_="blog"),
        _it("x1", "@emollick：Riemann Hypothesis may have been solved with the help of Claude", source="twitter", pop=2300),
        _it("x2", "@amasad：With two separate Riemann proofs coming out at the same time", source="twitter", pop=900),
        _it("zh1", "数学家称与 AI 合作证明了黎曼猜想，证明稿超 25 万页", source="zhihu", summary="Riemann"),
        _it("zh2", "Lean与 Mathlib 社区联合声明，确认对黎曼猜想的证明正确", source="zhihu"),
        _it("bili", "Claude 证明了黎曼猜想？11分钟讲清它到底证明了什么", source="bilibili", type_="video"),
        _it("hn1", "Riemann Hypothesis proved, twice independently", source="hn", pop=900),
        _it("rd", "What the Riemann proof means for number theory", source="reddit", pop=300),
        _it("yt", "Number theorists react to the Riemann news", source="youtube", type_="video"),
        _it("blog2", "Quoting Levent Alpöge on the Riemann Hypothesis", source="blog", type_="blog"),
    ]


def test_cross_source_burst_boosts_one_lead_and_names_sources():
    plain = {x["id"]: x for x in rk.rank(riemann() + background(), now=NOW)}
    out = rk.lead_bursts(rk.rank(riemann() + background(), now=NOW))
    burst = [x for x in out if x.get("burst")]
    lead = max(burst, key=lambda x: x["score"])
    assert {x["id"] for x in burst} >= {"paper", "blog1", "x1", "x2", "hn1", "rd", "yt", "blog2"}
    assert len({x["burst"]["key"] for x in burst}) == 1
    assert lead["burst"]["sources"] >= 6 and lead["why"].count("个来源都在讨论") == 1
    assert lead["score"] > max(x["score"] for x in out if not x.get("burst"))
    assert all(x["score"] == plain[x["id"]]["score"] for x in out if x.get("burst") and x is not lead and x["id"] in plain)


def test_everyday_topics_are_not_bursts():
    out = rk.rank(background(), now=NOW)
    assert not any(x.get("burst") for x in out)


def test_chinese_items_join_the_event_through_english_items_gist():
    items = riemann() + background()
    for x in items:
        if x["id"] in ("paper", "x1", "x2", "hn1", "rd", "blog1"):
            x["extra"] = {"gist": "作者称借助 Claude 完成黎曼猜想证明"}
    out = {x["id"]: x for x in rk.rank(items, now=NOW)}
    assert out["zh2"].get("burst") and out["bili"].get("burst")
    assert out["zh2"]["burst"]["key"] == out["paper"]["burst"]["key"]
    assert out["zh2"]["burst"]["title"] in ("Riemann", "黎曼猜想")


def test_lead_is_picked_after_filtering_so_the_boost_survives():
    out = rk.rank(riemann() + background(), now=NOW)
    top = max((x for x in out if x.get("burst")), key=lambda x: x["score"])
    rest = rk.lead_bursts([x for x in out if x["id"] != top["id"]])
    assert "个来源都在讨论" in max((x for x in rest if x.get("burst")), key=lambda x: x["score"])["why"]


def test_spike_of_a_plain_word_is_not_an_event():
    src = ("github", "hn", "reddit", "twitter", "blog")
    spam = [_it(f"r{i}", f"tips for running local models {i}", source=src[i % 5]) for i in range(10)]
    cn = [_it(f"c{i}", t, source=src[i % 5]) for i, t in enumerate((
        "阿里分拆平头哥上市，怎样解读这一动作", "机器人从视频里学习动作", "动作识别的新基准", "世界模型统一感知与动作",
        "人形机器人做出高难度动作", "大厂最近的动作有哪些", "动作生成模型开源", "游戏角色动作捕捉方案", "用语言控制机械臂动作"))]
    assert not any(x.get("burst") for x in rk.rank(spam + cn + background(), now=NOW))


def test_versioned_name_is_an_event():
    src = ("twitter", "blog", "zhihu", "youtube", "hn")
    rel = [_it(f"g{i}", f"OpenAI just dropped gpt-6.2 sol, first look {i}", source=src[i % 5]) for i in range(9)]
    assert any(x.get("burst") for x in rk.rank(rel + background(), now=NOW))


def test_old_spike_is_not_a_burst_today():
    old = [{**x, "date": (NOW - timedelta(days=5)).isoformat()} for x in riemann()]
    assert not any(x.get("burst") for x in rk.rank(old + background(), now=NOW))


def test_collapse_folds_burst_members_under_lead():
    out = cluster.collapse(rk.lead_bursts(rk.rank(riemann() + background(), now=NOW)))
    leads = [x for x in out if x.get("event")]
    assert len(leads) == 1
    lead = leads[0]
    assert lead["event"]["n"] >= 6 and "来源" in lead["event"]["title"]
    assert not any(x.get("burst") and x is not lead for x in out)
