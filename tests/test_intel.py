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
