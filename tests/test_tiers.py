from app.modules import _tiers_rules as tr


def _it(source="blog", type_="blog", title="t", summary="", url="https://example.com/a", pop=0.0, **extra):
    return {"id": f"{source}:{title}", "source": source, "type": type_, "title": title, "summary": summary,
            "url": url, "pop_norm": pop, "extra": extra}


def _cls(it, **kw):
    r = tr.classify(it, **kw)
    return r["tier"], r["cat"]


def test_lab_technical_report_is_tier1():
    it = _it("arxiv", "paper", "DeepSeek-V4 Technical Report", affil="DeepSeek-AI")
    assert _cls(it) == (1, "report")


def test_lab_paper_without_report_is_tier2():
    it = _it("hf", "paper", "Sparse attention for long context", pop=0.5, orgs="DeepSeek-AI")
    assert _cls(it) == (2, "paper")


def test_unknown_org_technical_report_is_not_tier1():
    it = _it("arxiv", "paper", "NorthCUA Technical Report", affil="NorthCUA Team")
    assert _cls(it)[0] == 3


def test_official_blog_with_substance_is_tier1():
    it = _it(url="https://www.anthropic.com/research/evals", title="Building strong safety evaluations", judge_important=0.86)
    assert _cls(it) == (1, "official")


def test_official_blog_customer_story_is_dropped():
    it = _it(url="https://openai.com/index/shield", title="Shield hands off legacy work with OpenAI", judge_important=0.05)
    assert _cls(it)[0] == 3


def test_official_blog_mid_importance_is_product_update():
    it = _it(url="https://blog.google/products/x", title="Gemini Intelligence: New features", judge_important=0.6)
    assert _cls(it) == (2, "launch")


def test_org_new_repo_is_tier1():
    it = _it("github", "repo", "superagent", url="https://github.com/deepseek-ai/superagent", watch_org="deepseek-ai",
             repo="deepseek-ai/superagent", judge_important=0.85)
    assert _cls(it) == (1, "repo")


def test_org_demo_repo_without_substance_drops_to_tier2():
    it = _it("github", "repo", "chat-demo", summary="Chat Demo", url="https://github.com/deepseek-ai/chat-demo", watch_org="deepseek-ai",
             repo="deepseek-ai/chat-demo", judge_important=0.77)
    assert _cls(it) == (2, "trending")


def test_announcement_post_from_whitelist_person_is_dropped():
    it = _it("twitter", "discussion", "@demishassabis：launch", summary="Today we are launching " + "x" * 400, author="demishassabis")
    assert _cls(it)[0] == 3


def test_interest_keyword_needs_word_boundary():
    it = _it("arxiv", "paper", "Harnessing LLMs physics awareness for video", pop=0.9)
    r = tr.classify(it)
    assert (r["tier"], r["boosted"]) == (2, False)


def test_blog_title_naming_a_person_is_not_their_content():
    it = _it("blog", "blog", "Anthropic CEO Amodei admits uncertainty", url="https://news.example.com/a")
    assert _cls(it) == (2, "author")


def test_interest_does_not_promote_repo_to_tier1():
    it = _it("github", "repo", "agent-skills：skills for Claude Code coding agent", url="https://github.com/a/b", pop=0.95, trending="daily", repo="a/b")
    r = tr.classify(it)
    assert (r["tier"], r["boosted"]) == (2, False)


def test_unknown_owner_trending_repo_is_tier2():
    it = _it("github", "repo", "tensorfold", url="https://github.com/a/b", pop=0.95, trending="daily", repo="a/b")
    assert _cls(it) == (2, "trending")


def test_whitelist_person_long_post_is_tier1():
    it = _it("twitter", "discussion", "@karpathy：rules", summary="x" * 400, author="karpathy")
    assert _cls(it) == (1, "person")


def test_whitelist_person_short_tweet_is_dropped():
    it = _it("twitter", "discussion", "@karpathy：nice", summary="nice one", author="karpathy")
    assert _cls(it)[0] == 3


def test_whitelist_person_x_article_is_tier1():
    it = _it("twitter", "discussion", "@karpathy：article", summary="short", author="karpathy", x_article=True)
    assert _cls(it) == (1, "person")


def test_second_tier_person_long_post_is_tier2_author():
    it = _it("twitter", "discussion", "@simonw：notes", summary="x" * 390, author="simonw")
    assert _cls(it) == (2, "author")


def test_interview_video_needs_thirty_minutes_for_tier1():
    long_ = _it("youtube", "video", "Andrej Karpathy: deep dive", duration=3600, channel="Dwarkesh")
    short = _it("youtube", "video", "Andrej Karpathy: clip", duration=300, channel="Dwarkesh")
    assert _cls(long_) == (1, "person")
    assert _cls(short)[0] == 3


def test_hot_hn_post_is_tier2_top():
    assert _cls(_it("hn", "discussion", "Show HN: x", pop=0.96)) == (2, "top")


def test_launch_product_hot_is_tier2_product():
    assert _cls(_it("producthunt", "product", "Cue", pop=0.9)) == (2, "product")


def test_interest_pulls_noise_into_tier2():
    it = _it("reddit", "discussion", "My Claude Code harness setup for subagents", pop=0.1)
    assert _cls(it) == (2, "interest")


def test_interest_promotes_substantive_tier2_to_tier1():
    it = _it("blog", "blog", "Agent harness design for long-running coding agents", summary="context engineering", url="https://x.dev/p",
             judge_important=0.7)
    r = tr.classify(it)
    assert (r["tier"], r["boosted"]) == (1, True)


def test_interest_does_not_promote_shallow_content():
    it = _it("hn", "discussion", "Claude Code subagents are neat", pop=0.97)
    r = tr.classify(it)
    assert (r["tier"], r["boosted"]) == (2, False)


def test_irrelevant_item_is_tier3():
    assert _cls(_it("reddit", "discussion", "Best GPU for gaming?", pop=0.2))[0] == 3


def test_official_product_announcement_is_tier2_not_tier1():
    it = _it(url="https://openai.com/index/introducing-chatgpt-wallet", title="Introducing ChatGPT Wallet", judge_important=0.88)
    assert _cls(it) == (2, "launch")


def test_org_paper_with_low_heat_is_tier2():
    it = _it("arxiv", "paper", "Bandit-based LLM routing", pop=0.0, affil="Google Research")
    assert _cls(it) == (2, "paper")


def test_x_article_with_title_from_unknown_author_is_tier2():
    it = _it("twitter", "discussion", "@someone：Goal Engineering", summary="x" * 190, author="someone", article_title="Goal Engineering", x_article=True, pop=0.4)
    assert _cls(it) == (2, "author")


def test_clickbait_x_post_without_article_title_is_dropped():
    it = _it("twitter", "discussion", "@someone：this is wild..", summary="x" * 400, author="someone", x_article=True, pop=0.66)
    assert _cls(it)[0] == 3


def test_interest_does_not_promote_paper_or_x_article():
    paper = _it("arxiv", "paper", "Agent harness design for coding agents", pop=0.9, affil="Google")
    xart = _it("twitter", "discussion", "@someone：harness", summary="x" * 190, author="someone", article_title="Agent harness design", x_article=True, pop=0.7)
    for it in (paper, xart):
        r = tr.classify(it)
        assert (r["tier"], r["boosted"]) == (2, False)


def test_launch_is_never_tier1():
    assert tr.CATS["launch"][0] == 2


def test_growth_case_enters_tier1_only_when_jev_approves():
    from app.modules import tiers
    cards = [{"id": "case:1", "score": 8.0, "why": [], "tier": 2}, {"id": "case:2", "score": 8.0, "why": [], "tier": 2}, {"id": "case:3", "score": 8.0, "why": [], "tier": 2}]
    tiers.apply_case(cards, {"case:1": 0.85, "case:2": 0.3})
    assert [c["tier"] for c in cards] == [1, 2, 2] and cards[0]["deep"] == 0.85 and "Jev" in cards[1]["why"][0]


def test_balance_hard_caps_each_category():
    from app.modules import tiers
    cards = [{"cat": "update", "score": 9 - i * 0.1} for i in range(10)] + [{"cat": "paper", "score": 1.0}, {"cat": "top", "score": 0.5}]
    out = tiers.balance(cards, limit=8, per_cat=3)
    assert sorted(c["cat"] for c in out) == ["paper", "top", "update", "update", "update"]


def test_balance_accepts_per_category_caps():
    from app.modules import tiers
    cards = [{"cat": "paper", "score": 9 - i * 0.1} for i in range(10)] + [{"cat": "top", "score": 0.1}]
    out = tiers.balance(cards, limit=9, per_cat={"*": 1, "paper": 4})
    assert sorted(c["cat"] for c in out) == ["paper"] * 4 + ["top"]


def test_items_api_returns_tier_structure(client):
    d = client.get("/api/tiers/items?refresh=true").json()
    assert set(d) >= {"days", "range", "range_options", "interests"}
    assert d["range_options"] == [1, 7, 14, 30]
    assert set(d["days"][0]) >= {"day", "t1", "t2", "t2_more", "t3"}
    assert [l["href"] for l in d["days"][0]["t3"]["links"]] == ["#feed", "#intel"]


def _card(cat, tier, id_="feed:1"):
    return {"id": id_, "cat": cat, "tier": tier, "boosted": tier == 1, "why": ["规则"], "score": 1.0, "cat_label": ""}


def test_deep_judge_promotes_tier2_update_to_tier1():
    from app.modules import tiers
    cards = [_card("launch", 2)]
    tiers.apply_deep(cards, {"feed:1": 0.9})
    assert (cards[0]["tier"], cards[0]["cat"]) == (1, "deep")
    assert "Jev" in cards[0]["why"][0]


def test_deep_judge_demotes_rule_tier1_it_rejects():
    from app.modules import tiers
    cards = [_card("person", 1)]
    tiers.apply_deep(cards, {"feed:1": 0.2})
    assert (cards[0]["tier"], cards[0]["boosted"]) == (2, False)


def test_deep_judge_middle_score_keeps_rule_result_and_skips_papers():
    from app.modules import tiers
    cards = [_card("launch", 2, "a"), _card("paper", 2, "b")]
    tiers.apply_deep(cards, {"a": 0.55, "b": 0.99})
    assert [c["tier"] for c in cards] == [2, 2]


def test_deep_scores_cache_by_content_and_survive_missing_key(client, monkeypatch):
    from app.modules import _tiers_judge as tj
    it = {"id": "feed:x", "source": "blog", "type": "blog", "title": "t", "summary": "s", "url": "https://claude.com/resources/articles/a", "extra": {}}
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.delenv("JEV_API_KEY", raising=False)
    scores, errors = tj.scores([it], "deep")
    assert scores == {} and errors
    calls = []
    monkeypatch.setattr(tj.fj, "judge", lambda todo, client=None: (calls.append(len(todo)) or {todo[0][0]["id"]: {"judge_deep": 0.88}}, []))
    assert tj.scores([it], "deep")[0] == {"feed:x": 0.88}
    assert tj.scores([it], "deep")[0] == {"feed:x": 0.88}
    assert calls == [1]


def test_merge_same_news_keeps_highest_and_notes_merged():
    from app.modules import tiers
    cards = [{"title": "DeepMind 发布 Gemini 4 Hydrogen 模型", "score": 10, "why": ["a"], "source": "雷达 · Google"},
             {"title": "GitHub Copilot 上线 Gemini 4 Hydrogen 模型", "score": 8, "why": ["b"], "source": "雷达 · GitHub"},
             {"title": "Qwen 开源 qwen-code 终端编码代理", "score": 8, "why": ["c"], "source": "雷达 · Qwen"}]
    out = tiers.merge_same_news(cards)
    assert len(out) == 2 and any("合并同类" in w for w in out[0]["why"])


def test_pick_floor_drops_low_scores_and_ranks_by_score():
    from app.modules import tiers
    cards = [{"id": "a", "score": 1, "why": []}, {"id": "b", "score": 1, "why": []}, {"id": "c", "score": 1, "why": [], "deep": 0.1}]
    out = tiers.apply_pick(cards, {"a": 0.8, "b": 0.3})
    assert [c["id"] for c in out] == ["a"]


def test_read_flag_follows_shared_read_log(client):
    from app.modules import _read_log, tiers
    _read_log.log("intel_event", 7, "t", "#intel/e/7", "产品雷达")
    d = {"t1": [], "t2": [{"kind": "event", "read_ref": 7, "url": ""}, {"kind": "event", "read_ref": 8, "url": ""}]}
    assert [c["read"] for c in tiers._marker()(d)["t2"]] == [True, False]


def test_read_view_carries_deep_read_state(client, monkeypatch):
    from app.modules import feed, tiers
    monkeypatch.setattr(feed, "_deep_latest", lambda: {"a.com/x": {"id": 5, "status": "done", "finished_at": "t", "read_pos": 0}})
    d = {"t1": [{"kind": "feed", "read_ref": "z", "url": "https://a.com/x"}], "t2": [{"kind": "feed", "read_ref": "y", "url": ""}]}
    out = tiers._marker()(d)
    assert out["t1"][0]["read"] is True and out["t1"][0]["deep_read"]["id"] == 5
    assert out["t2"][0]["deep_read"] is None


def test_top_lab_trending_repo_is_tier1_candidate():
    it = _it("github", "repo", "codex-security", summary="OpenAI's Codex Security CLI and TypeScript SDK for agents", url="https://github.com/openai/codex-security",
             repo="openai/codex-security", trending="daily", pop=0.83)
    assert _cls(it) == (1, "repo")


def _report_on(day_offset: int, name: str) -> dict:
    from datetime import datetime, timedelta, timezone
    noon = (datetime.now().replace(hour=12, minute=0, second=0, microsecond=0) - timedelta(days=day_offset)).astimezone(timezone.utc)
    return {"id": f"arxiv:range-{name}", "source": "arxiv", "type": "paper", "title": f"DeepSeek-{name} Technical Report",
            "url": f"https://arxiv.org/abs/range-{name}", "date": noon.isoformat(timespec="seconds"), "extra": {"affil": "DeepSeek-AI"}}


def _no_judge(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.delenv("JEV_API_KEY", raising=False)


def test_items_default_to_today_and_ranges_show_each_past_day(client, monkeypatch):
    from app import db
    from app.modules import feed, tiers
    _no_judge(monkeypatch)
    db.execute("DELETE FROM tiers_days")
    feed.upsert([_report_on(0, "Today"), _report_on(3, "ThreeAgo"), _report_on(20, "TwentyAgo")])
    tiers.daily_tick()

    d = client.get("/api/tiers/items").json()
    assert [x["day"] for x in d["days"]] == [db.today()]
    assert "DeepSeek-Today Technical Report" in [c["title"] for c in d["days"][0]["t1"]]
    assert "DeepSeek-ThreeAgo Technical Report" not in [c["title"] for c in d["days"][0]["t1"]]

    week = client.get("/api/tiers/items?days=7").json()["days"]
    assert len(week) == 7 and week[0]["day"] == db.today() and week[0]["day"] > week[-1]["day"]
    assert [c["title"] for c in week[3]["t1"] if "range" in c["url"]] == ["DeepSeek-ThreeAgo Technical Report"]
    month = client.get("/api/tiers/items?days=30").json()["days"]
    assert len(month) == 30
    assert [c["title"] for c in month[20]["t1"] if "range" in c["url"]] == ["DeepSeek-TwentyAgo Technical Report"]
    assert len(client.get("/api/tiers/items?days=14").json()["days"]) == 14


def test_past_days_are_kept_once_final_and_today_keeps_updating(client, monkeypatch):
    from app import db
    from app.modules import tiers
    _no_judge(monkeypatch)
    db.execute("DELETE FROM tiers_days")
    tiers.daily_tick()
    assert db.row("SELECT count(*) n FROM tiers_days")["n"] == 30
    old = db.row("SELECT * FROM tiers_days ORDER BY day LIMIT 1")
    assert old["final"] == 1
    today = db.row("SELECT * FROM tiers_days WHERE day=?", (db.today(),))
    assert today["final"] == 0

    built = []
    real = tiers.build
    monkeypatch.setattr(tiers, "build", lambda day, now=None: built.append(day) or real(day, now))
    db.execute("UPDATE tiers_days SET built_at = built_at - 7200")
    tiers.daily_tick()
    assert sorted(built) == sorted(tiers.recent_days(db.today(), tiers.OPEN_DAYS))
    assert db.row("SELECT data FROM tiers_days WHERE day=?", (old["day"],))["data"] == old["data"]


def test_missing_past_day_shows_pending_and_starts_backfill(client, monkeypatch):
    from app import db
    from app.modules import tiers
    _no_judge(monkeypatch)
    db.execute("DELETE FROM tiers_days")
    kicked = []
    monkeypatch.setattr(tiers, "_tick_bg", lambda: kicked.append(1))
    days = client.get("/api/tiers/items?days=7").json()["days"]
    assert "t1" in days[0] and all(x.get("pending") for x in days[1:])
    assert kicked


def test_late_fetched_item_still_lands_on_its_publish_day(client, monkeypatch):
    from app import db
    from app.modules import feed, tiers
    _no_judge(monkeypatch)
    db.execute("DELETE FROM tiers_days")
    tiers.daily_tick()
    feed.upsert([_report_on(2, "LateTwo")])
    db.execute("UPDATE tiers_days SET built_at = built_at - 7200")
    tiers.daily_tick()
    two_ago = client.get("/api/tiers/items?days=7").json()["days"][2]
    assert "DeepSeek-LateTwo Technical Report" in [c["title"] for c in two_ago["t1"]]
