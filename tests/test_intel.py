"""产品雷达：快照 diff、实体链接、分类去重、分级、解读卡校验。不触网、不调 LLM。"""
import json
from datetime import datetime, timedelta

import pytest

from app import db, jobs
from app.modules import _intel_events as ev
from app.modules import _intel_snap as snap
from app.modules import intel

TODAY = datetime.now().strftime("%Y-%m-%d")
D1 = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
OLD = (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%d")

CHANGELOG_V1 = f"""<html><body><nav>Docs Pricing Login</nav><main>
<h1>Changelog</h1>
<h2>{D1}</h2><p>Added background agents to the CLI so that long tasks keep running after you close the terminal window.</p>
<h2>{OLD}</h2><p>Initial public release of the editor with tab completion and chat panel for every user on the free plan.</p>
{'<p>filler paragraph about the product and its documentation for padding purposes only.</p>' * 4}
</main><footer>© 2026</footer></body></html>"""

CHANGELOG_V2 = CHANGELOG_V1.replace("<h1>Changelog</h1>", f"""<h1>Changelog</h1>
<h2>{TODAY}</h2><p>Launched Agent Teams: several agents can now split one task, review each other's diffs and merge the result automatically.</p>""")


@pytest.fixture()
def fresh(client):
    for t in ("intel_candidate", "intel_event", "intel_analysis", "intel_snapshot", "intel_level_log", "intel_state"):
        db.execute(f"DELETE FROM {t}")
    db.execute("UPDATE intel_source SET last_hash='', last_fetch=NULL")
    intel.seed()
    return client


def _co(slug):
    return intel._company(db.row("SELECT * FROM intel_company WHERE slug=?", [slug]))


def _src(company, kind="changelog"):
    return db.row("SELECT * FROM intel_source WHERE company_id=? AND kind=? ORDER BY id LIMIT 1", [_co(company)["id"], kind])


# ---------- 纯函数 ----------

def test_extract_and_diff():
    t1 = snap.extract_text(CHANGELOG_V1, "text/html")
    assert "Login" not in t1 and "## Changelog" in t1  # 只取 main
    t2 = snap.extract_text(CHANGELOG_V2, "text/html")
    added = snap.added_blocks(t1, t2)
    assert len(added) == 1 and "Agent Teams" in added[0]
    assert snap.find_date(added[0]) == TODAY
    # 首次快照只收近 14 天的条目
    recent = snap.recent_entries(t1)
    assert len(recent) == 1 and "background agents" in recent[0]


def test_verify_prices_drops_invented_numbers():
    ch = [{"title": "Pro 从 $20 涨到 $25/月", "summary": ""}, {"title": "Max 改成 $999", "summary": ""}]
    kept = snap.verify_prices(ch, "Pro $25 / month", "Pro $20 / month")
    assert [c["title"] for c in kept] == ["Pro 从 $20 涨到 $25/月"]


def test_match_feed_item(fresh):
    cos = intel.companies()
    a = lambda **kw: ev.match_feed_item({"extra": {}, "title": "", "url": "", **kw}, cos)  # noqa: E731
    c, off = a(source="twitter", extra={"author": "AnthropicAI"}, title="Claude can now ...")
    assert c["slug"] == "anthropic" and off
    c, off = a(source="github", url="https://github.com/openai/codex/releases/tag/v1")
    assert c["slug"] == "openai" and off
    c, off = a(source="blog", url="https://www.anthropic.com/news/foo")
    assert c["slug"] == "anthropic" and off
    c, off = a(source="hn", popularity=300, title="Cursor raises $900M", url="https://techcrunch.com/x")
    assert c["slug"] == "cursor" and not off
    assert a(source="hn", popularity=20, title="Cursor raises $900M")[0] is None  # 低分 HN 不要
    assert a(source="twitter", extra={"author": "random"}, title="Cursor is great")[0] is None  # 非官方推文不要


def test_auto_level():
    assert ev.auto_level("pricing", "normal", 1) == "S"
    assert ev.auto_level("model", "major", 1) == "S"
    assert ev.auto_level("model", "major", 2) == "A"
    assert ev.auto_level("feature", "normal", 1) == "B"
    assert ev.auto_level("feature", "minor", 1) == "C"
    assert ev.auto_level("other", "normal", 1) == "C"


GOOD_CARD = "\n".join(f"## {s}\n- 要点 [官方博客](https://x.com/a, 2026-10-30)\n- **【推测】** 推断" for s in ev.SECTIONS)


def test_card_quality():
    q = ev.card_quality(GOOD_CARD)
    assert q["complete"] and q["links"] == 6 and q["speculation"] == 6
    q = ev.card_quality(GOOD_CARD.replace("## 技术逻辑", "## 别的"))
    assert not q["complete"] and "技术逻辑" in q["missing"]
    q = ev.card_quality(GOOD_CARD.replace("https://x.com/a, 2026-10-30", "无"))
    assert not q["complete"]  # 没有带链接的出处


# ---------- 链路 ----------

def _fake_classify(monkeypatch, decide, groups=lambda payload: []):
    """decide(candidate_payload, events_payload) -> 分类结果项（不含 id）；groups(payload) -> 去重复查的分组。"""
    calls = []

    def fake(system, payload, **kw):
        if "new" in payload:
            return {"groups": groups(payload)}
        calls.append(payload)
        return {"items": [{"id": c["id"], **decide(c, payload["events"])} for c in payload["candidates"]]}
    monkeypatch.setattr(snap, "llm_json", fake)
    return calls


def test_changelog_snapshot_to_event_and_card(fresh, monkeypatch):
    src = _src("cursor")
    r = intel.process_page(src, 200, "text/html", CHANGELOG_V1)
    assert r["ok"] and r["first"] and r["candidates"] == 1  # 首次：只收近 14 天
    # 同一内容再来一次：没变化
    assert intel.process_page(db.row("SELECT * FROM intel_source WHERE id=?", [src["id"]]), 200, "text/html", CHANGELOG_V1)["unchanged"]
    r = intel.process_page(db.row("SELECT * FROM intel_source WHERE id=?", [src["id"]]), 200, "text/html", CHANGELOG_V2)
    assert r["candidates"] == 1
    assert db.row("SELECT count(*) AS n FROM intel_snapshot WHERE source_id=?", [src["id"]])["n"] == 2

    def decide(c, _):
        major = "Agent Teams" in c["text"]
        return {"is_change": True, "merge_into": None, "type": "launch" if major else "feature", "product": "Cursor",
                "title": "Cursor 上线 Agent Teams" if major else "Cursor CLI 支持后台 Agent", "summary": "…", "scale": "major" if major else "normal"}
    _fake_classify(monkeypatch, decide)
    out = intel.classify_pending()
    assert out["events"] == 2 and not out["errors"]
    evs = {e["title"]: e for e in db.rows("SELECT * FROM intel_event")}
    teams = evs["Cursor 上线 Agent Teams"]
    assert teams["level"] == "A" and teams["date"] == TODAY  # T2 major launch → A
    assert evs["Cursor CLI 支持后台 Agent"]["level"] == "B"

    # B+ 自动出卡，受每日上限约束
    monkeypatch.setitem(intel.CFG_DEFAULTS, "cards_per_day", 1)
    assert intel.queue_cards() == 1 and intel.queue_cards() == 0
    first = db.row("SELECT * FROM intel_event WHERE card_status='queued'")
    assert first["id"] == teams["id"]  # A 先于 B
    job = db.row("SELECT * FROM jobs WHERE id=?", [first["card_job_id"]])
    assert job["ref"] == f"intel:event:{teams['id']}:card" and "## 所以呢" in job["prompt"]
    assert jobs.describe(job)[1] == f"#intel/e/{teams['id']}"

    # 任务完成：校验 6 节 → done；重新生成追加一行，不覆盖
    intel.on_job_done({**job, "status": "done", "output": GOOD_CARD})
    intel.on_job_done({**job, "status": "done", "output": "## 变了什么\n- 只有一节"})
    rows = db.rows("SELECT * FROM intel_analysis WHERE event_id=?", [teams["id"]])
    assert len(rows) == 2 and rows[0]["complete"] == 1 and rows[1]["complete"] == 0
    assert db.row("SELECT card_status FROM intel_event WHERE id=?", [teams["id"]])["card_status"] == "incomplete"

    d = fresh.get(f"/api/intel/events/{teams['id']}").json()
    assert d["card"]["missing"] and len(d["versions"]) == 2
    lst = fresh.get("/api/intel/events?level=S,A,B").json()
    assert {e["id"] for e in lst["events"]} >= {teams["id"]} and lst["counts"]["A"] == 1


def test_cross_source_dedup(fresh, monkeypatch):
    """官方博客（feed）+ 官方 X + HN 第三方 + changelog 说的是同一件事 → 一个事件，4 个来源。"""
    co = _co("anthropic")
    blog = "https://www.anthropic.com/news/claude-agents"
    now = "2999-01-01T00:00:00"  # 晚于库里别的测试留下的条目，扫描游标只看到这几条
    intel._set_state("feed_cursor", "2998-12-31T00:00:00")
    for i, (source, url, extra, pop, title) in enumerate([
        ("blog", blog, {"feed": "Anthropic News"}, 0, "Introducing Claude Agents"),
        ("twitter", "https://x.com/AnthropicAI/status/1", {"author": "AnthropicAI"}, 0, "Claude Agents are here"),
        ("hn", "https://news.ycombinator.com/item?id=9", {}, 500, "Anthropic launches Claude Agents"),
        ("hn", "https://news.ycombinator.com/item?id=10", {}, 400, "Show HN: my weekend Claude wrapper"),
    ]):
        db.insert("feed_items", {"id": f"t:{i}", "source": source, "type": "blog", "title": title, "summary": "", "url": url,
                                 "date": TODAY, "popularity": pop, "extra": extra, "fetched_at": now})
    assert intel.scan_feed() == 4
    assert intel.scan_feed() == 0  # 游标：不重复收

    first = "c%d" % db.row("SELECT min(id) AS m FROM intel_candidate WHERE company_id=?", [co["id"]])["m"]

    def decide(c, events):
        if "weekend" in c["title"]:
            return {"is_change": True, "merge_into": None, "type": "other", "title": "x", "scale": "minor"}  # 第三方且无官方事件
        return {"is_change": True, "merge_into": None if c["id"] == first else first, "type": "launch", "product": "Claude",
                "title": "Anthropic 发布 Claude Agents", "summary": "…", "scale": "major"}
    _fake_classify(monkeypatch, decide)
    out = intel.classify_pending()
    assert out["events"] == 1 and out["merged"] == 2 and out["ignored"] == 1
    e = intel._event(db.row("SELECT * FROM intel_event"))
    assert e["level"] == "S" and len(e["sources"]) == 3
    assert sum(1 for s in e["sources"] if s["official"]) == 2

    # 同一篇博客的链接再从 feed 进来（比如镜像源）：不调 LLM，直接按链接合并
    db.insert("feed_items", {"id": "t:dup", "source": "blog", "type": "blog", "title": "Introducing Claude Agents", "summary": "",
                             "url": blog, "date": TODAY, "popularity": 0, "extra": {}, "fetched_at": "2999-01-02T00:00:00"})
    intel.scan_feed()
    calls = _fake_classify(monkeypatch, lambda c, e: pytest.fail("不该调 LLM"))
    assert intel.classify_pending()["merged"] == 1 and not calls


def test_pricing_first_then_change(fresh, monkeypatch):
    src = _src("anthropic", "pricing")
    page = lambda price: f"<main><h1>Pricing</h1><h2>Pro</h2><p>{price} per month, for individuals who use Claude every day.</p>" + \
        "".join(f"<p>Feature {i}: includes Claude Code, projects, and more usage than the free plan.</p>" for i in range(4)) + "</main>"  # noqa: E731
    seen = []

    def fake(system, payload, **kw):
        seen.append(payload)
        st = {"plans": [{"name": "Pro", "price": "$20/月" if not payload["old_structure"] else "$25/月"}], "usage": []}
        return {"structure": st, "changes": [] if not payload["old_structure"] else
                [{"title": "Pro 从 $20 涨到 $25/月", "summary": "涨价", "scale": "major"}, {"title": "免费版降到 $3", "summary": "", "scale": "major"}]}
    monkeypatch.setattr(snap, "llm_json", fake)
    assert intel.process_page(src, 200, "text/html", page("$20"))["candidates"] == 0  # 首次只出结构
    src = db.row("SELECT * FROM intel_source WHERE id=?", [src["id"]])
    assert intel.process_page(src, 200, "text/html", page("$25"))["candidates"] == 1  # 编造的 $3 被丢掉
    c = db.row("SELECT * FROM intel_candidate WHERE type_hint='pricing'")
    assert "$25" in c["title"]
    snapshot = db.row("SELECT structure FROM intel_snapshot WHERE source_id=? ORDER BY id DESC", [src["id"]])
    assert json.loads(snapshot["structure"])["plans"][0]["price"] == "$25/月"


def test_fetch_errors_recorded(fresh):
    src = _src("openai")
    assert not intel.process_page(src, 403, "text/html", "")["ok"]
    assert "403" in db.row("SELECT last_err FROM intel_source WHERE id=?", [src["id"]])["last_err"]
    assert not intel.process_page(src, 200, "text/html", "<div id=root></div>")["ok"]  # JS 渲染的空壳
    st = fresh.get("/api/intel/status").json()
    assert any(s["id"] == src["id"] for s in st["failing_sources"])


def test_api_level_override_and_companies(fresh, monkeypatch):
    co = _co("mistral")
    eid = db.insert("intel_event", {"company_id": co["id"], "title": "Mistral 小更新", "date": TODAY, "level": "C", "level_auto": "C",
                                    "sources": [], "card_status": "", "created_at": db.now(), "updated_at": db.now()})
    r = fresh.post(f"/api/intel/events/{eid}/level", json={"level": "A", "reason": "其实是战略级"}).json()
    assert r["level"] == "A" and r["level_auto"] == "C" and r["card_status"] == "queued" and r["level_log"][0]["reason"]
    cs = fresh.get("/api/intel/companies").json()
    assert len(cs) >= 20 and any(c["slug"] == "mistral" and c["events"] == 1 for c in cs)
    c = fresh.get("/api/intel/companies/mistral").json()
    assert c["events"][0]["id"] == eid
    assert fresh.post("/api/intel/companies", json={"name": "Windsurf", "tier": 3}).json()["slug"] == "windsurf"
    assert fresh.post("/api/intel/companies", json={"name": "Windsurf"}).status_code == 409
    assert "产品雷达" in intel.agent_context("")


def test_kb_exports_cards(fresh):
    from app import kb
    co = _co("deepseek")
    eid = db.insert("intel_event", {"company_id": co["id"], "title": "DeepSeek 降价", "date": TODAY, "level": "S", "level_auto": "S",
                                    "sources": [{"label": "官方", "url": "https://api-docs.deepseek.com/news", "official": True}],
                                    "card_status": "done", "created_at": db.now(), "updated_at": db.now()})
    db.insert("intel_analysis", {"event_id": eid, "content": GOOD_CARD, "complete": 1, "created_at": db.now()})
    docs = {d["path"]: d for d in kb.build()}
    card = next(d for p, d in docs.items() if p.startswith("intel/events/"))
    assert "## 商业逻辑" in card["text"] and "api-docs.deepseek.com" in card["text"]
    assert "intel/companies/deepseek.md" in docs


def test_dedup_pass_and_stale(fresh, monkeypatch):
    """分类没认出博客和 X 是同一次发布 → 复查合并；发布日期太早的旧文 / 未来日期按规则处理。"""
    co = _co("mistral")
    for i, (src, url, extra, title, date) in enumerate([
        ("blog", "https://mistral.ai/news/le-chonk", {}, "Le Chonk: Built for Coders", TODAY),
        ("twitter", "https://x.com/MistralAI/status/2", {"author": "MistralAI"}, "Today we release the weights of Le Chonk", TODAY),
        ("blog", "https://mistral.ai/news/old", {}, "Mistral Large 2", OLD),
    ]):
        db.insert("feed_items", {"id": f"m:{i}", "source": src, "type": "blog", "title": title, "summary": "", "url": url, "date": date,
                                 "popularity": 0, "extra": extra, "fetched_at": f"2999-02-01T00:00:0{i}"})
    intel._set_state("feed_cursor", "2999-01-31T00:00:00")
    assert intel.scan_feed() == 2  # 两个月前的旧文不收

    def decide(c, _):
        return {"is_change": True, "merge_into": None, "type": "model", "product": "Mistral Large 4", "title": c["title"][:20], "scale": "major"}

    def groups(payload):
        return [[e["id"] for e in payload["events"]]]
    _fake_classify(monkeypatch, decide, groups)
    out = intel.classify_pending()
    assert out["events"] == 1 and out["merged"] == 1
    live = db.rows("SELECT * FROM intel_event WHERE company_id=? AND merged_into IS NULL", [co["id"]])
    assert len(live) == 1 and len(json.loads(live[0]["sources"])) == 2
    assert db.row("SELECT count(*) AS n FROM intel_candidate WHERE event_id=?", [live[0]["id"]])["n"] == 2
    assert len(fresh.get("/api/intel/events?company=mistral").json()["events"]) == 1

    # 正文里的未来日期（优惠截止日）按今天算
    cid = intel._add_candidate(co["id"], "snapshot", "snap:x:future", title="intro price through Dec 31", date="2999-12-31")
    assert db.row("SELECT date FROM intel_candidate WHERE id=?", [cid])["date"] == TODAY


# ---------- P2 创业公司：TrustMRR 快照 / 收入异动 / 赛道 / 拆解卡 / PH / 公开 ARR ----------

from app.modules import _intel_startup as st  # noqa: E402


@pytest.fixture()
def startup_db(fresh):
    db.execute("DELETE FROM intel_event WHERE company_id IN (SELECT id FROM intel_company WHERE kind='startup')")
    for t in ("intel_metric", "intel_profile", "intel_ph_day"):
        db.execute(f"DELETE FROM {t}")
    db.execute("DELETE FROM intel_company WHERE kind='startup'")
    return fresh


def _tm(slug, mrr, growth=10, **kw):
    return {"_id": slug, "slug": slug, "name": slug.title(), "description": kw.pop("description", "AI video generator for creators"),
            "currentMrr": mrr, "currentLast30DaysRevenue": mrr, "cachedGrowth30d": growth, **kw}


def _board(monkeypatch, objs, details=None):
    """不触网：首页 = objs（不足 50 家时补无关的小公司，避免被当成页面结构变了）。"""
    filler = [_tm(f"filler{i}", 100, description="plain todo list app") for i in range(60)]
    pages = {"/": filler + objs, "/category/ai": [], "/acquire": []}
    monkeypatch.setattr(st, "fetch_board", lambda: (st.parse_board({p: json.dumps(v) for p, v in pages.items()}), []))
    monkeypatch.setattr(st, "rsc_objects", lambda html: json.loads(html))
    monkeypatch.setattr(st, "fetch_detail", lambda slug: (details or {}).get(slug))


def _sc(slug):
    return intel._company(db.row("SELECT * FROM intel_company WHERE json_extract(ext,'$.trustmrr')=?", [slug]))


def test_parse_board_and_metrics(monkeypatch):
    monkeypatch.setattr(st, "rsc_objects", lambda html: json.loads(html))
    pages = {"/": json.dumps([_tm("vidgen", 5000), _tm("hidden", 9000, stealthMode=True), _tm("zero", 0),
                              _tm("plain", 800, description="Invoice software for plumbers")]),
             "/category/ai": json.dumps([{"_id": "x", "slug": "plain", "userCategory": "Artificial Intelligence"}])}
    b = st.parse_board(pages)
    assert set(b) == {"vidgen", "plain"}  # 隐身 / 没收入的不要
    assert b["vidgen"]["_ai_hint"] and b["plain"]["_ai_hint"]  # 描述像 AI / 在 AI 分类页
    m = st.metrics_of({"currentMrr": 1200, "cachedGrowth30d": None, "askingPrice": 0, "onSale": True, "currentActiveSubscriptions": "abc"})
    assert m == {"mrr": 1200.0, "on_sale": 1.0}  # 缺的 / 解析不了的 / ≤0 的金额都不写


def test_detect_rules():
    day = "2026-11-01"
    assert st.detect(None, {"mrr": 200_000, "growth_30d": 500}, day) == []  # 首日不追溯
    listing = st.detect(None, {"mrr": 12_000, "on_sale": 1, "asking_price": 300_000}, day, listed_at="2026-10-30")
    assert [x["key"] for x in listing] == ["listing:2026-11"] and listing[0]["level"] == "B"
    ms = st.detect({"mrr": 8_000}, {"mrr": 120_000, "growth_30d": 20}, day)
    assert {x["key"] for x in ms} == {"milestone:10000", "milestone:50000", "milestone:100000"}
    assert next(x for x in ms if x["key"] == "milestone:100000")["level"] == "A"
    surge = st.detect({"mrr": 20_000, "growth_30d": 50}, {"mrr": 40_000, "growth_30d": 150}, day)
    assert [(x["key"], x["level"]) for x in surge] == [("surge:2026-11", "A")]
    assert st.detect({"mrr": 40_000, "growth_30d": 150}, {"mrr": 41_000, "growth_30d": 160}, day) == []  # 已经过阈值就不再报
    drop = st.detect({"mrr": 9_000, "growth_30d": -10}, {"mrr": 6_000, "growth_30d": -45}, day)
    assert [(x["key"], x["level"]) for x in drop] == [("drop:2026-11", "B")]
    assert st.detect({"mrr": 100, "growth_30d": 0}, {"mrr": 2_000, "growth_30d": 900}, day) == []  # 金额太小不算暴涨


def test_startup_snapshot_baseline_then_events(startup_db, monkeypatch):
    _board(monkeypatch, [_tm("vidgen", 60_000, growth=20)],
           details={"vidgen": {**_tm("vidgen", 60_000), "aiEnrichment": {"pricingModel": "subscription"}, "website": "https://vidgen.ai",
                               "marketingChannels": [{"name": "SEO"}], "currentActiveSubscriptions": 900}})
    r = intel.startup_snapshot(force=True)
    c = _sc("vidgen")
    assert r["new_companies"] >= 1 and c["ai"] == 1 and c["kind"] == "startup"
    assert c["ext"]["website"] == "https://vidgen.ai" and c["ext"]["channels"] == ["SEO"] and c["ext"]["pricing"] == "subscription"
    assert not db.rows("SELECT 1 FROM intel_event WHERE company_id=?", [c["id"]])  # 首日只记基线
    assert intel.metric_series(c["id"])[-1]["subscriptions"] == 900
    assert not intel.startup_snapshot()  # 当天已跑过：跳过
    assert "vidgen" not in {x["slug"] for x in intel.companies()}  # 不混进产品雷达的公司名单

    # 把今天的快照挪到昨天，再按新数字跑一次 → 里程碑 + 暴涨
    db.execute("UPDATE intel_metric SET date=? WHERE company_id=?", [D1, c["id"]])
    _board(monkeypatch, [_tm("vidgen", 130_000, growth=120)])
    intel.startup_snapshot(force=True)
    keys = {e["ext_key"] for e in db.rows("SELECT ext_key FROM intel_event WHERE company_id=?", [c["id"]])}
    assert keys == {"milestone:100000", "surge:" + TODAY[:7]}
    assert {e["card_status"] for e in db.rows("SELECT card_status FROM intel_event WHERE company_id=?", [c["id"]])} == {"profile"}
    intel.startup_snapshot(force=True)  # 同一天重跑：指标不覆盖、事件不重复
    assert len(db.rows("SELECT 1 FROM intel_event WHERE company_id=?", [c["id"]])) == 2
    assert db.row("SELECT value FROM intel_metric WHERE company_id=? AND date=? AND metric='mrr'", [c["id"], D1])["value"] == 60_000


def test_write_metrics_append_only(startup_db):
    c = intel._upsert_startup("abc", _tm("abc", 1000))
    assert intel._write_metrics(c["id"], TODAY, {"mrr": 1000}) == 1
    assert intel._write_metrics(c["id"], TODAY, {"mrr": 5}) == 0  # 同日同口径不覆盖
    assert intel._write_metrics(c["id"], TODAY, {"mrr": 1e6}, grade="reported", source="https://news") == 1  # reported 单独一条
    assert intel.metric_series(c["id"])[-1]["mrr"] == 1000


def test_empty_board_writes_nothing(startup_db, monkeypatch):
    monkeypatch.setattr(st, "fetch_board", lambda: ({}, ["首页只解析出 3 家公司"]))
    r = intel.startup_snapshot(force=True)
    assert r["errors"] and not db.rows("SELECT 1 FROM intel_metric")
    assert intel._state("startup_day") != db.today()  # 没成功就不标记今天跑过


def test_tracks_and_manual_override(startup_db, monkeypatch):
    _board(monkeypatch, [_tm("vidgen", 5000), _tm("codebot", 9000, description="AI code review bot")])
    intel.startup_snapshot(force=True)
    seen = {}

    def fake(system, payload, **kw):
        seen["n"] = len(payload["items"])
        name = {str(_sc(s)["id"]): s for s in ("vidgen", "codebot")}
        return {"items": [{"id": i["id"], "ai": True, "track": {"vidgen": "video", "codebot": "coding"}.get(name.get(i["id"]), "nope"),
                           "tracks": ["agent"]} for i in payload["items"]]}
    monkeypatch.setattr(snap, "llm_json", fake)
    intel.classify_startup_tracks()
    assert _sc("vidgen")["track"] == "video" and _sc("codebot")["tracks"] == ["agent"]
    assert _sc("filler1")["track"] == "vertical"  # 模型给了不存在的赛道 → 兜底
    c = _sc("vidgen")
    assert startup_db.patch(f"/api/intel/companies/{c['id']}", json={"track": "nope"}).status_code == 400
    startup_db.patch(f"/api/intel/companies/{c['id']}", json={"track": "image", "watch": 1, "ext": {"bizpeel_url": "https://bizpeel.com/x", "trustmrr": "evil"}})
    c = _sc("vidgen")
    assert c["track"] == "image" and c["track_manual"] == 1 and c["watch"] == 1
    assert c["ext"]["bizpeel_url"] == "https://bizpeel.com/x" and c["ext"]["trustmrr"] == "vidgen"  # 只合并允许的键
    db.execute("UPDATE intel_company SET track='' WHERE id=?", [c["id"]])
    seen.clear()
    intel.classify_startup_tracks()
    assert _sc("vidgen")["track"] == ""  # 人工改过的不再交给模型
    tr = startup_db.get("/api/intel/tracks/coding").json()
    assert [x["slug"] for x in tr["startups"]] == ["codebot"]
    assert next(t for t in startup_db.get("/api/intel/tracks").json() if t["slug"] == "coding")["companies"] == 1
    lst = startup_db.get("/api/intel/startups?track=coding").json()
    assert lst["total"] == 1 and lst["startups"][0]["mrr"] == 9000


def test_profile_queue_and_done(startup_db, monkeypatch):
    _board(monkeypatch, [_tm("vidgen", 5000), _tm("codebot", 9000, description="AI code review bot")])
    intel.startup_snapshot(force=True)
    db.execute("UPDATE intel_company SET track='video' WHERE kind='startup'")
    db.execute("UPDATE intel_company SET watch=1 WHERE json_extract(ext,'$.trustmrr')='vidgen'")
    q = intel.profile_queue()
    assert q[0] == (_sc("vidgen")["id"], "关注")
    n = intel.queue_profiles()
    assert 1 <= n <= int(intel.cfg("profiles_per_day"))
    c = _sc("vidgen")
    assert c["profile_status"] == "queued"
    job = db.row("SELECT * FROM jobs WHERE ref LIKE ?", [f"intel:company:{c['id']}:profile:%"])
    assert jobs.describe(job)[1] == f"#intel/c/{c['slug']}"
    assert intel.queue_profiles() == 0 or _sc("vidgen")["profile_status"] == "queued"  # 排过队的不重复排
    good = "\n".join(f"## {s}\n- 要点 [来源](https://trustmrr.com/startup/vidgen, 2026-11-01)" for s in st.PROFILE_SECTIONS)
    intel.on_job_done({**job, "status": "done", "output": good})
    c = startup_db.get(f"/api/intel/companies/{_sc('vidgen')['slug']}").json()
    assert c["profile_status"] == "done" and c["profile"]["complete"] and c["track_options"]
    intel.on_job_done({**job, "status": "failed", "output": ""})
    assert _sc("vidgen")["profile_status"] == "failed"
    assert len(db.rows("SELECT 1 FROM intel_profile WHERE company_id=?", [c["id"]])) == 1  # 失败不删旧卡


def test_ph_daily(startup_db, monkeypatch):
    db.execute("DELETE FROM feed_items WHERE source='producthunt'")
    for i in range(5):
        db.execute("INSERT INTO feed_items(id, source, type, title, url, date, popularity, extra, fetched_at) VALUES(?,?,?,?,?,?,?,?,?)",
                   [f"producthunt:{i}", "producthunt", "product", f"Prod{i}：AI thing {i}", f"https://ph/{i}", D1, 100 - i,
                    json.dumps({"topics": ["AI"]}), db.now()])
    monkeypatch.setattr(snap, "llm_json", lambda system, payload, **kw: {
        "items": [{"id": it["id"], "track": "video" if it["rank"] == 1 else "bogus", "why": "因为"} for it in payload["items"]],
        "summary": "- 视频扎堆"})
    assert intel.ph_daily() == 1 and intel.ph_daily() == 0  # 每天只解读一次
    d = startup_db.get("/api/intel/ph").json()[0]
    assert d["date"] == D1 and d["items"][0]["track"] == "video" and d["items"][0]["track_name"] and d["items"][1]["track"] == ""
    assert startup_db.get("/api/intel/tracks/video").json()["ph"][0]["name"] == "Prod0"


def test_reported_arr(startup_db, monkeypatch):
    db.execute("DELETE FROM feed_items WHERE id LIKE 'hn:arr%'")
    rows = [("hn:arr1", "Lovable hits $200M ARR", "Lovable says annual recurring revenue reached $200M this month."),
            ("hn:arr2", "Foo reaches $5M ARR", "Foo, an AI notetaker, reached 5 million in ARR."),
            ("hn:arr3", "Bar raises at $1B valuation", "Bar ARR is growing fast")]
    for i, t, s in rows:
        db.execute("INSERT INTO feed_items(id, source, type, title, summary, url, date, popularity, fetched_at) VALUES(?,?,?,?,?,?,?,?,?)",
                   [i, "hn", "news", t, s, f"https://news/{i}", D1, 300, db.now()])
    intel._set_state("arr_cursor", "2000-01-01")
    monkeypatch.setattr(snap, "llm_json", lambda system, payload, **kw: {"items": [
        {"id": "hn:arr1", "company": "Lovable", "metric": "arr", "value_usd": 200_000_000, "quote": "reached $200M"},
        {"id": "hn:arr2", "company": "Foo", "metric": "arr", "value_usd": 5_000_000, "quote": "5 million"},
        {"id": "hn:arr3", "company": "Bar", "metric": "arr", "value_usd": 30_000_000, "quote": "编的"}]})  # 原文里没有 30M
    r = intel.scan_reported_arr()
    assert r["reported"] == 2
    foo = intel._find_company("Foo")
    assert foo["kind"] == "startup" and foo["ai"] == -1 and not intel._find_company("Bar")
    m = db.row("SELECT * FROM intel_metric WHERE company_id=?", [foo["id"]])
    assert m["grade"] == "reported" and m["value"] == 5e6 and m["source"] == "https://news/hn:arr2"
    ev_ = db.row("SELECT * FROM intel_event WHERE company_id=?", [foo["id"]])
    assert "reported" in ev_["title"] and ev_["card_status"] == "profile"
    assert intel.scan_reported_arr()["reported"] == 0  # 游标前进，不重复
    assert startup_db.get("/api/intel/events?type=revenue&kind=startup&level=S,A,B,C").json()["events"]


def test_value_in_text():
    assert st._value_in_text(200e6, "hit $200M ARR")
    assert st._value_in_text(1.2e9, "run-rate of $1.2 billion")
    assert st._value_in_text(1e8, "年化收入突破 1 亿美元")
    assert not st._value_in_text(30e6, "raised $300M at a $3B valuation")
