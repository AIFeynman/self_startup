import json
from datetime import date, timedelta

import pytest

from app import db

TODAY = date.today().isoformat()
YDAY = (date.today() - timedelta(days=1)).isoformat()

PRODUCT_SECTIONS = {
    "变了什么": "- 某视频平台上线动效工作室，开始做讲解视频。[官方博客](https://example.com/a, 2026-11-25)",
    "用户问题": "- 知识类创作者做讲解视频成本高。",
    "产品逻辑": "- 从生成工具走向工作流。",
    "商业逻辑": "- 订阅制。",
    "所以呢": "- **可验证预测**：到 2027-02-28，它会推出知识讲解模板。判断标准是官方页面出现模板入口。\n- **值得亲手试**：用同一份讲稿各生成一遍。",
}
GROWTH_CONTENT = """## 一句话
Revid 用榜单和 Reddit 评论，把 ChatGPT 带来的新用户 10 周翻倍。

## 背景与数字
- 每周新用户从 355 涨到 781。

## 触达动作
1. 挖榜单并买前排位置。

## 我能怎么用
- 先摸清买家会问 AI 什么问题。
"""


def _company(name="某视频平台"):
    return db.insert("intel_company", {"slug": name, "name": name})


def _event(level="S", title="某视频平台上线动效工作室", day=TODAY, content=None, sections=None, complete=1, type_="launch"):
    eid = db.insert("intel_event", {"company_id": _company(title), "title": title, "level": level, "date": day,
                                    "card_status": "done", "type": type_,
                                    "sources": json.dumps([{"label": "媒体", "url": "https://news.example.com/a"},
                                                           {"label": "官方", "url": "https://official.example.com/post", "official": True}])})
    db.insert("intel_analysis", {"event_id": eid, "content": content if content is not None else "## 变了什么\n" + "x" * 800,
                                 "sections": json.dumps(sections if sections is not None else PRODUCT_SECTIONS, ensure_ascii=False),
                                 "complete": complete})
    return eid


def _growth(day=TODAY, item="twitter:1"):
    db.insert("intel_growth_item", {"id": item, "title": "how we doubled the users ChatGPT sends Revid", "company": "Revid"})
    return db.insert("intel_growth_case", {"item_id": item, "day": day, "company": "Revid", "status": "done",
                                           "content": GROWTH_CONTENT, "complete": 1})


def _paper(pid="hf:1", title="Agent memory that learns", day=TODAY, pop=50):
    db.insert("feed_items", {"id": pid, "source": "hf", "type": "paper", "title": title, "url": f"https://arxiv.org/abs/{pid}",
                             "date": day, "popularity": pop, "extra": json.dumps({"gist": "让 Agent 记忆按价值更新"}, ensure_ascii=False)})


@pytest.fixture(autouse=True)
def _clean(client, monkeypatch):
    from app import kb_judge
    from app.modules import today

    def offline(system, payload):
        raise RuntimeError("no llm in tests")
    monkeypatch.setattr(today, "_llm", offline)
    kb_judge._init()
    for t in ("intel_analysis", "intel_event", "intel_company", "intel_growth_case", "intel_growth_item",
              "feed_items", "today_marks", "today_feedback", "today_opps", "today_days", "today_scores", "kb_judgments", "intel_ph_day", "learn_items"):
        db.execute(f"DELETE FROM {t}")
    yield


def test_deep_cards_cover_product_tech_growth(client):
    _event()
    _growth()
    _paper()
    d = client.get("/api/today").json()
    kinds = [c["kind"] for c in d["deep"]]
    assert sorted(kinds) == ["growth", "product", "tech"]
    prod = next(c for c in d["deep"] if c["kind"] == "product")
    assert prod["prediction"].startswith("到 2027-02-28")
    assert prod["due"] == "2027-02-28"
    assert prod["link"].startswith("#intel/e/")
    growth = next(c for c in d["deep"] if c["kind"] == "growth")
    assert "10 周翻倍" in growth["reveal"]["一句话"]
    assert growth["link"].startswith("#intel/g/")


def test_pure_news_goes_to_quick_not_deep(client):
    _event(level="S", title="某助手套餐升级到新模型", type_="pricing")
    d = client.get("/api/today").json()
    assert all(c["title"] != "某助手套餐升级到新模型" for c in d["deep"])
    assert any(c["title"] == "某助手套餐升级到新模型" for c in d["quick"])


def test_deep_slots_follow_depth_score_and_personal_questions(client, monkeypatch):
    from app.modules import today
    _event(level="S", title="某助手套餐升级到新模型", type_="pricing")
    _event(level="S", title="连接器与技能合并为插件", type_="packaging")
    seen = {}

    def fake(system, payload):
        seen["payload"] = payload
        out = []
        for it in payload["items"]:
            deep = "插件" in it["title"]
            out.append({"key": it["key"], "score": 8 if deep else 2, "why": "技能怎么组织是你一直在问的" if deep else "",
                        "question": "合并后 skill 该怎么组织才能少 token 加载？" if deep else "", "hit": "这么多 skill 怎么组织" if deep else ""})
        return {"items": out}
    monkeypatch.setattr(today, "_llm", fake)
    db.insert("annotations", {"doc": "learn:item:1", "title": "Uber skills", "quote": "700 个 skill", "created_at": db.now()})
    aid = db.row("SELECT MAX(id) id FROM annotations")["id"]
    db.insert("annotation_msgs", {"annotation_id": aid, "role": "user", "content": "这么多 skill 怎么组织能准确且少 token 地加载", "created_at": db.now()})
    d = client.get("/api/today").json()
    deep = [c for c in d["deep"] if c["kind"] == "product"]
    assert [c["title"] for c in deep] == ["连接器与技能合并为插件"]
    assert deep[0]["why"] and deep[0]["hit"] and deep[0]["question"].startswith("合并后")
    assert any("skill" in q for q in seen["payload"]["open_questions"])


def test_deep_is_left_short_when_nothing_is_worth_it(client, monkeypatch):
    from app.modules import today
    _event(level="S", title="只是一条新闻", type_="launch")
    monkeypatch.setattr(today, "_llm", lambda s, p: {"items": [{"key": it["key"], "score": 3} for it in p["items"]]})
    d = client.get("/api/today").json()
    assert d["deep"] == [] and d["quick"]


def test_new_products_from_product_hunt_and_yc_enter_the_pool(client):
    db.execute("INSERT OR REPLACE INTO intel_ph_day (date, items, summary) VALUES (?,?,?)", [TODAY, json.dumps([
        {"id": "producthunt:1", "rank": 1, "name": "Granular", "title": "Granular：Put your AI agents to work in a visual workspace",
         "url": "https://www.producthunt.com/products/granular", "votes": 131, "why": "可视化编排多个 Agent"}], ensure_ascii=False), ""])
    db.insert("feed_items", {"id": "yc:1", "source": "yc", "type": "product", "title": "Light Anchor: the AI-native P&G",
                             "summary": "Building self-driving consumer brands", "url": "https://lightanchor.ai", "date": TODAY, "popularity": 11})
    _event(level="S", title="大公司某功能更新", type_="feature")
    cards = client.get("/api/today").json()["all"]
    new = [c for c in cards if c["label"].startswith("新产品")]
    assert {c["title"].split("：")[0] for c in new} >= {"Granular", "Light Anchor: the AI-native P&G"}
    ph = next(c for c in new if c["title"].startswith("Granular"))
    assert ph["summary"] == "可视化编排多个 Agent" and ph["due"] and ph["prediction"]


def test_deep_cards_carry_other_angles(client, monkeypatch):
    from app.modules import _people, today
    from app.db import DATA_DIR
    db.init([_people.SCHEMA])
    db.execute("DELETE FROM people_items")
    _event(level="S", title="Anthropic 推出 Claude Ship 测试版", type_="launch")
    monkeypatch.setattr(today, "_llm", lambda s, p: {"items": [{"key": it["key"], "score": 8, "why": "多 Agent 评审", "question": "评审该拿多少上下文？",
                                                               "terms": ["Claude Ship"]} for it in p["items"]]})
    db.insert("people_items", {"id": "blog:1", "channel": "blog", "people": json.dumps(["simonw"]), "title": "Notes on Claude Ship",
                               "summary": "PR Steward is the interesting part", "url": "https://simonwillison.net/x", "date": TODAY})
    db.insert("feed_items", {"id": "hn:99", "source": "hn", "type": "discussion", "title": "Claude Ship: code review to merge",
                             "url": "https://example.com", "date": TODAY, "popularity": 300})
    cache = DATA_DIR / "absorb" / "hn" / "_cache" / "digests"
    cache.mkdir(parents=True, exist_ok=True)
    (cache / "99.json").write_text(json.dumps({"d": {"tldr": "多数人担心审批被自动化", "opinions": [
        {"stance": "反对", "claim": "自动审批会放过回归", "by": "alice", "quote": "q"}]}}, ensure_ascii=False))
    card = next(c for c in client.get("/api/today").json()["deep"] if c["kind"] == "product")
    angles = card["angles"]
    assert any(a["kind"] == "people" and "Simon" in a["who"] for a in angles)
    hn = next(a for a in angles if a["kind"] == "hn")
    assert hn["tldr"] == "多数人担心审批被自动化" and hn["opinions"][0]["claim"] == "自动审批会放过回归"


def test_deepread_sends_card_to_learn_history_once(client):
    _event()
    card = next(c for c in client.get("/api/today").json()["deep"] if c["kind"] == "product")
    assert card["src_url"] == "https://official.example.com/post"
    r = client.post("/api/today/deepread", json={"key": card["key"]}).json()
    again = client.post("/api/today/deepread", json={"key": card["key"]}).json()
    assert r["id"] == again["id"]
    rows = db.rows("SELECT * FROM learn_items WHERE url=?", [card["src_url"]])
    assert len(rows) == 1 and card["question"][:10] in rows[0]["focus"]
    c = next(c for c in client.get("/api/today").json()["deep"] if c["key"] == card["key"])
    assert c["deepread"]["id"] == r["id"] and c["deepread"]["status"] in ("queued", "running", "done")
    assert c["deepread"]["link"] == f"#learn/item/{r['id']}"


def test_deepread_an_angle_by_its_own_url(client):
    _event()
    card = client.get("/api/today").json()["deep"][0]
    r = client.post("/api/today/deepread", json={"key": card["key"], "url": "https://simonwillison.net/post"}).json()
    assert db.row("SELECT url FROM learn_items WHERE id=?", [r["id"]])["url"].startswith("https://simonwillison.net/post")


def test_your_track_gets_its_own_card(client, monkeypatch):
    from app.modules import today
    _event(level="A", title="某 AI 讲解视频工具上线知识模板", type_="launch")
    _event(level="S", title="某大模型发布新推理能力", type_="model")

    def fake(system, payload):
        return {"items": [{"key": it["key"], "score": 7, "why": "w", "question": "q",
                           "track": 9 if "讲解视频" in it["title"] else 1,
                           "track_question": "它对你的产品是威胁还是可借鉴？" if "讲解视频" in it["title"] else ""} for it in payload["items"]]}
    monkeypatch.setattr(today, "_llm", fake)
    d = client.get("/api/today").json()
    track = [c for c in d["deep"] if c.get("slot") == "track"]
    assert len(track) == 1 and "讲解视频" in track[0]["title"]
    assert track[0]["label"].startswith("你的赛道") and track[0]["question"] == "它对你的产品是威胁还是可借鉴？"
    assert len(d["deep"]) <= 4


def test_your_track_falls_back_to_keywords(client):
    _event(level="A", title="某 AI 讲解视频工具上线知识模板", type_="launch")
    d = client.get("/api/today").json()
    assert any(c.get("slot") == "track" for c in d["deep"])


def test_broken_cards_are_filtered_out(client):
    _event(title="正常的卡")
    _event(title="额度报错的卡", content="You've hit your weekly limit · resets 5pm", sections={})
    _event(title="不完整的卡", complete=0)
    titles = [c["title"] for c in client.get("/api/today?refresh=1").json()["all"]]
    assert "正常的卡" in titles
    assert "额度报错的卡" not in titles
    assert "不完整的卡" not in titles


def test_quick_cards_keep_some_s_level_and_respect_cap(client):
    for i in range(6):
        _event(level="S", title=f"S 级事件 {i}")
    for i in range(10):
        _paper(pid=f"hf:{i}", title=f"论文 {i}")
    d = client.get("/api/today").json()
    assert len(d["deep"]) <= 4
    assert len(d["quick"]) <= 9
    quick_s = [c for c in d["quick"] if c.get("level") == "S"]
    assert 1 <= len(quick_s) <= 3


def test_many_s_level_events_do_not_crowd_out_papers(client):
    for i in range(8):
        _event(level="S", title=f"S 级事件 {i}")
    for i in range(4):
        _paper(pid=f"hf:{i}", title=f"Agent 论文 {i}")
    quick = client.get("/api/today").json()["quick"]
    assert len(quick) <= 9
    assert sum(c["kind"] == "tech" for c in quick) >= 1


def test_relates_tags_are_specific(client):
    _event(level="S", title="某模型 API 定价公布", sections={**PRODUCT_SECTIONS, "变了什么": "- 输入 $2，输出 $10，推理 token 按输出计价。",
                                                           "用户问题": "- 开发者关心成本。"})
    card = client.get("/api/today").json()["deep"][0]
    assert "增长" not in card["relates"] and "基座机制" not in card["relates"]


def test_selection_is_stable_within_a_day(client):
    _event()
    _paper()
    first = [c["key"] for c in client.get("/api/today").json()["deep"]]
    _event(level="S", title="后来才抓到的事件")
    assert [c["key"] for c in client.get("/api/today").json()["deep"]] == first


def test_judgment_goes_into_existing_ledger_with_probability(client):
    _event()
    card = next(c for c in client.get("/api/today").json()["deep"] if c["kind"] == "product")
    r = client.post("/api/today/judge", json={"key": card["key"], "text": card["prediction"], "prob": 70,
                                              "reason": "大平台补齐工作流是常规动作", "due": card["due"]})
    assert r.status_code == 200
    row = db.row("SELECT * FROM kb_judgments")
    assert row["type"] == "预测" and row["due"] == "2027-02-28"
    assert "70%" in row["note"] and "大平台补齐工作流" in row["note"]
    assert json.loads(row["sources"])[0]["link"] == card["link"]
    d = client.get("/api/today").json()
    assert d["progress"]["deep_done"] == 1
    assert next(c for c in d["deep"] if c["key"] == card["key"])["done"]


def test_growth_guess_is_kept_but_not_sent_to_ledger(client):
    _growth()
    card = client.get("/api/today").json()["deep"][0]
    client.post("/api/today/guess", json={"key": card["key"], "text": "靠 SEO 榜单"})
    assert db.row("SELECT COUNT(*) n FROM kb_judgments")["n"] == 0
    c = next(c for c in client.get("/api/today").json()["deep"] if c["key"] == card["key"])
    assert c["done"] and c["guess"] == "靠 SEO 榜单"


def test_no_gain_feedback_and_opportunity_card(client):
    _event()
    card = client.get("/api/today").json()["deep"][0]
    client.post("/api/today/feedback", json={"key": card["key"], "value": "no_gain"})
    r = client.post("/api/today/opps", json={"key": card["key"], "title": "知识讲解模板市场",
                                             "change": "大平台开始做讲解视频", "pain": "创作者做讲解视频慢", "test": "做 3 个模板看转化", "prob": 40})
    assert r.status_code == 200
    opps = client.get("/api/today/opps").json()
    assert opps[0]["title"] == "知识讲解模板市场" and opps[0]["prob"] == 40 and opps[0]["status"] == "idea"
    d = client.get("/api/today").json()
    assert d["progress"]["no_gain"] == 1 and d["progress"]["opps"] == 1


def test_seen_items_are_not_repeated_next_day(client):
    _event(day=YDAY)
    old = client.get(f"/api/today?day={YDAY}").json()["deep"][0]
    client.post("/api/today/feedback", json={"key": old["key"], "value": "useful", "day": YDAY})
    _event(title="今天的新事件")
    keys = [c["key"] for c in client.get("/api/today").json()["all"]]
    assert old["key"] not in keys


def test_due_judgments_come_from_ledger(client):
    db.insert("kb_judgments", {"text": "到期的预测", "type": "预测", "due": YDAY, "created_at": db.now()})
    due = client.get("/api/today").json()["due"]
    assert any(j["claim"] == "到期的预测" or j.get("title") == "到期的预测" for j in due)
