import json
from datetime import date, timedelta

import pytest

from app import db

TODAY = date.today().isoformat()


@pytest.fixture(autouse=True)
def _clean(client, monkeypatch):
    from app import kb_judge
    from app.modules import today

    def offline(system, payload):
        raise RuntimeError("no llm in tests")
    monkeypatch.setattr(today, "_llm", offline)
    kb_judge._init()
    for t in ("today_topics", "today_memos", "today_trials", "today_opps", "today_kv", "kb_judgments", "products",
              "learn_plans", "learn_steps", "annotations", "annotation_msgs"):
        db.execute(f"DELETE FROM {t}")
    yield


def _ask(q):
    db.insert("annotations", {"doc": "learn:item:1", "title": "t", "quote": "q", "created_at": db.now()})
    aid = db.row("SELECT MAX(id) id FROM annotations")["id"]
    db.insert("annotation_msgs", {"annotation_id": aid, "role": "user", "content": q, "created_at": db.now()})


# ---------- 深度 ----------

def test_topic_candidates_come_from_open_questions_when_offline(client):
    _ask("这么多 skill 怎么组织能准确且少 token 地加载")
    _ask("Loop Transformer 和直接叠加两倍深度层的区别是什么")
    r = client.post("/api/today/deep/suggest").json()
    titles = [c["title"] for c in r["candidates"]]
    assert any("skill" in t for t in titles) and len(titles) <= 3


def test_topic_suggestions_use_llm(client, monkeypatch):
    from app.modules import today
    _ask("记忆的 Q 值在检索噪音下怎么更新")
    monkeypatch.setattr(today, "_llm", lambda s, p: {"topics": [
        {"title": "Agent 记忆的写入闸门与价值更新", "why": "你问过 Q 值和检索噪音", "track": "M3"}]})
    r = client.post("/api/today/deep/suggest").json()
    assert r["candidates"][0]["title"] == "Agent 记忆的写入闸门与价值更新"


def test_pick_topic_then_memo_and_critique(client, monkeypatch):
    from app.modules import today
    t = client.post("/api/today/deep/topic", json={"title": "Agent 记忆的写入闸门"}).json()
    d = client.get("/api/today/deep").json()
    assert d["topic"]["title"] == "Agent 记忆的写入闸门" and d["topic"]["id"] == t["id"]
    m = client.post("/api/today/deep/memo", json={"topic_id": t["id"], "conclusion": "要加写入闸门", "why": "错笔记会被信任",
                                                    "numbers": "", "verify": "", "transfer": "学习平台的经验库"}).json()
    monkeypatch.setattr(today, "_llm", lambda s, p: {"score": 55, "dims": {"结论先行": 15, "量化": 0, "验证方法": 0},
                                                       "followups": ["数字呢？", "怎么验证？", "反例是什么？"]})
    c = client.post(f"/api/today/deep/memo/{m['id']}/critique").json()
    assert c["score"] == 55 and c["followups"][0] == "数字呢？"
    memo = client.get("/api/today/deep").json()["memos"][0]
    assert memo["score"] == 55 and memo["critique"]["followups"]


def test_critique_offline_flags_missing_sections(client):
    t = client.post("/api/today/deep/topic", json={"title": "x"}).json()
    m = client.post("/api/today/deep/memo", json={"topic_id": t["id"], "conclusion": "结论", "why": "原因"}).json()
    c = client.post(f"/api/today/deep/memo/{m['id']}/critique").json()
    assert any("数字" in f for f in c["followups"]) and any("验证" in f for f in c["followups"])


def test_materials_reuse_learning_history(client):
    db.insert("learn_items", {"kind": "article", "url": "https://x.com/a", "title": "Agent 记忆的写入闸门实践", "status": "done",
                              "created_at": db.now(), "updated_at": db.now()})
    client.post("/api/today/deep/topic", json={"title": "Agent 记忆 写入闸门"})
    mats = client.get("/api/today/deep").json()["materials"]
    assert any(m["title"] == "Agent 记忆的写入闸门实践" and m["link"].startswith("#learn/item/") for m in mats)


# ---------- 动手 ----------

def test_product_trial_plan_record_goes_to_product_log_and_ledger(client):
    p = client.post("/api/today/hands/plan", json={"kind": "product", "name": "tday.com", "url": "https://tday.com"}).json()
    assert p["status"] == "planned" and len(p["plan"]["tasks"]) == 3
    r = client.post(f"/api/today/hands/{p['id']}/record", json={
        "minutes_to_value": 4, "tasks_done": [True, True, False], "best": "一句话生成演示", "worst": "旁白太机械",
        "compare": "比我的产品快但讲不深", "verdict": "借鉴", "keep_using": False, "prob": 30, "note": "适合开发者，不适合知识讲解"}).json()
    assert r["status"] == "done"
    prod = db.row("SELECT * FROM products WHERE name='tday.com'")
    assert prod and "旁白太机械" in prod["cons"] and "今日亲测" in prod["tags"]
    j = db.row("SELECT * FROM kb_judgments ORDER BY id DESC")
    assert j["type"] == "预测" and "30%" in j["note"]
    t = client.get("/api/today/hands").json()["trials"][0]
    assert t["review_due"] == (date.today() + timedelta(days=30)).isoformat()


def test_oss_trial_has_exercises(client):
    p = client.post("/api/today/hands/plan", json={"kind": "oss", "name": "claude-mem", "url": "https://github.com/x/claude-mem"}).json()
    assert len(p["plan"]["tasks"]) == 3 and p["plan"]["guess"]
    r = client.post(f"/api/today/hands/{p['id']}/record", json={"verdict": "只借鉴", "note": "压缩思路可以用", "tasks_done": [True, True, False]}).json()
    assert r["status"] == "done"
    assert db.row("SELECT COUNT(*) n FROM products")["n"] == 0


def test_hands_candidates_include_repos_and_track_products(client):
    db.insert("feed_items", {"id": "github:x/claude-mem", "source": "github", "type": "repo", "title": "claude-mem：跨会话记忆",
                             "url": "https://github.com/x/claude-mem", "date": TODAY, "popularity": 900})
    d = client.get("/api/today/hands").json()
    assert any(c["kind"] == "oss" and c["name"].startswith("claude-mem") for c in d["candidates"])


# ---------- 学 / 台账 / 画像 ----------

def test_learn_shows_two_pinned_plans_with_next_step(client):
    ids = [db.insert("learn_plans", {"topic": f"计划 {i}", "status": "active", "method": "business" if i == 2 else "tech",
                                     "created_at": db.now(), "updated_at": db.now()}) for i in range(3)]
    for pid in ids:
        db.insert("learn_steps", {"plan_id": pid, "stage": 1, "ord": 1, "title": "第一步", "status": "done"})
        db.insert("learn_steps", {"plan_id": pid, "stage": 1, "ord": 2, "title": "第二步", "status": "todo"})
    d = client.get("/api/today/learn").json()
    assert len(d["plans"]) == 2
    assert all(p["next"]["title"] == "第二步" and p["next"]["link"].startswith(f"#learn/plan/{p['id']}/step/") for p in d["plans"])
    client.post("/api/today/learn/pin", json={"plan_ids": [ids[0]]})
    assert [p["id"] for p in client.get("/api/today/learn").json()["plans"]] == [ids[0]]


def test_ledger_moves_opportunity_through_stages(client):
    oid = client.post("/api/today/opps", json={"title": "讲解模板市场"}).json()["id"]
    client.post(f"/api/today/opps/{oid}", json={"status": "written", "note": "写透了"})
    d = client.get("/api/today/ledger").json()
    o = next(o for o in d["opps"] if o["id"] == oid)
    assert o["status"] == "written" and "写透了" in o["note"]
    assert "stats" in d and "due" in d


def test_profile_lists_motivations_and_signals(client):
    _ask("策略的含义是什么")
    d = client.get("/api/today/profile").json()
    assert [m["id"] for m in d["motivations"]] == ["M0", "M1", "M2", "M3", "M4", "M5"]
    assert "questions" in d["signals"]


def test_task_sheet_is_grounded_and_guess_stays_a_question(client, monkeypatch):
    from app.modules import today
    db.execute("DELETE FROM today_days")
    db.execute("INSERT INTO today_days (day, payload, created_at) VALUES (?,?,?)", [TODAY, json.dumps({"deep": [
        {"key": "ph:1", "kind": "new", "title": "tday.com：Ask your coding agent for a narrated demo", "summary": "让编码 Agent 生成带旁白的功能演示视频",
         "link": "https://ph", "label": "新产品"}], "quick": []}, ensure_ascii=False), db.now()])
    seen = {}

    def fake(system, payload):
        seen.update(payload)
        return {"tasks": ["a", "b", "c"], "claims": ["x"], "guess": "我猜不会留用"}
    monkeypatch.setattr(today, "_llm", fake)
    p = client.post("/api/today/hands/plan", json={"kind": "product", "name": "tday.com", "key": "ph:1"}).json()
    assert "带旁白的功能演示视频" in seen["about"]
    assert p["plan"]["guess"].endswith("？")
