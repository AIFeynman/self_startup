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
    assert _cls(it) == (2, "update")


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
    assert _cls(it) == (2, "update")


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


def test_growth_case_needs_perfect_score_and_ai_to_reach_tier1():
    from app.modules import tiers
    assert tiers.case_tier(15, "How an AI agent app hit $1M ARR") == 1
    assert tiers.case_tier(15, "How Tinder ran a paywall experiment") == 2
    assert tiers.case_tier(14, "AI app growth") == 2


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
    assert set(d) >= {"t1", "t2", "t2_more", "t3", "interests", "windows"}
    assert [l["href"] for l in d["t3"]["links"]] == ["#feed", "#intel"]
