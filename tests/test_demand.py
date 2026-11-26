"""产品需求：被跳过的卡重试、联网补全的选取、AICPB 榜单入库的门槛与去重。不触网、不调 LLM。"""
from app.modules import _demand_run as dr
from app.modules import _intel_head as head
from app.modules import intel


def test_skipped_card_retries_only_when_material_grows():
    skip = {"skip": True, "tl": 300}
    assert not dr._retry(skip, {"text": "x" * 500})
    assert not dr._retry(skip, {"text": "x" * 590})
    assert dr._retry(skip, {"text": "x" * 700})
    assert not dr._retry({"skip": True, "tl": 700}, {"text": "x" * 800})
    assert not dr._retry({"scene": "s"}, {"text": "x" * 5000})


def test_enrich_todo_heads_first_then_big_startups_without_growth():
    P = {k: {"text": t} for k, t in {"a": "AICPB 榜单", "b": "原始名单", "c": "", "d": "", "e": "", "f": ""}.items()}
    cards = {
        "a": {"sources": ["大公司 / AI native"]},
        "b": {"sources": ["大公司 / AI native"]},
        "c": {"sources": ["创业公司"], "arr_v": 900000, "growth": ""},
        "d": {"sources": ["创业公司"], "arr_v": 2000000, "growth": "", "bm_type": "订阅制"},
        "e": {"sources": ["创业公司"], "arr_v": 900000, "growth": "靠 SEO", "bm_type": "订阅制"},
        "f": {"sources": ["大公司 / AI native"], "enriched": "2026-11-20"},
    }
    assert dr._enrich_todo(P, cards) == ["b", "a", "d", "c"]


def test_aicpb_names_are_normalised_and_volume_parsed():
    assert head.key("Character.AI") == head.key("character ai")
    assert head.short(head.key("Perplexity AI")) == head.key("Perplexity")
    assert head.vol("27.97M") == 27.97e6 and head.vol("949.38K") == 949.38e3 and head.vol("x") == 0


def test_head_sync_adds_only_new_big_products_once_a_week(client, monkeypatch):
    from app import db
    intel.seed()
    db.execute("DELETE FROM intel_state WHERE key='head_day'")
    db.execute("DELETE FROM intel_company WHERE slug LIKE 'zz-test-%'")
    rows = [{"name": "ZZ Test Agent", "cat": "个人 Agent", "rank": 1, "visits": "3.00M", "list": "AI Agent 榜"},
            {"name": "OpenAI", "cat": "模型 / 通用助手", "rank": 2, "visits": "9.00M", "list": "AI 聊天机器人榜"}]
    monkeypatch.setattr(head, "fetch_rows", lambda client=None: rows)
    assert intel.head_sync() == {"added": 1}
    r = db.row("SELECT * FROM intel_company WHERE name='ZZ Test Agent'")
    assert r["kind"] == "native" and "第 1 名" in r["note"]
    assert intel.head_sync() == {"skipped": True}
    db.execute("DELETE FROM intel_company WHERE name='ZZ Test Agent'")
    db.execute("DELETE FROM intel_state WHERE key='head_day'")


# ---------- 中段：中型 AI 创业公司 ----------

def test_size_tier_from_revenue_funding_and_source():
    from app.modules import _demand_mid as mid
    assert mid.tier({"arr_v": 5e5, "sources": ["创业公司"]}) == "small"
    assert mid.tier({"arr_v": 2e6, "sources": ["创业公司"]}) == "mid"
    assert mid.tier({"arr_v": 9e7, "sources": ["大公司 / AI native"]}) == "mid"
    assert mid.tier({"arr_v": 4e8, "sources": ["大公司 / AI native"]}) == "large"
    assert mid.tier({"funding": "Series B，$40M，2026-03", "sources": ["中型 AI 创业公司"]}) == "mid"
    assert mid.tier({"funding": "B 轮 3 亿元，2026-05", "sources": ["创业公司"]}) == "mid"
    assert mid.tier({"funding": "Series D，$500M，估值 $5B", "sources": ["中型 AI 创业公司"]}) == "large"
    assert mid.tier({"sources": ["大公司 / AI native"]}) == "large"
    assert mid.tier({"sources": ["PH 日榜"]}) == "small"


def test_discover_merges_candidates_keeps_only_mid_and_skips_known_large(monkeypatch, tmp_path):
    from app.modules import _demand_mid as mid
    monkeypatch.setattr(dr, "BASE", tmp_path)
    answers = dict(zip(['"q1"', '"q2"'], [
        {"companies": [
            {"name": "Lovable", "website": "https://lovable.dev", "one_liner": "AI 生成应用", "stage": "Series A", "funding": "Series A $200M",
             "arr": "ARR $50M（2025-07）", "source_url": "https://a"},
            {"name": "TinyTool", "one_liner": "小工具", "stage": "bootstrapped", "arr": "MRR $2k", "source_url": "https://b"},
            {"name": "OpenAI", "one_liner": "大模型", "stage": "late", "arr": "ARR $50B", "source_url": "https://c"}]},
        {"companies": [{"name": "lovable", "one_liner": "Vibe coding", "stage": "Series B", "funding": "Series B，估值 $1.8B",
                        "source_url": "https://d"}]},
    ]))

    class Fake:
        def call(self, model, system, user, web=False):
            assert web
            return next(v for k, v in answers.items() if k in user)
        light = strong = "m"
    got = mid.discover(Fake(), ["q1", "q2"], known={"openai": {"arr_v": 5e10}})
    assert set(got) == {"lovable"}
    lv = got["lovable"]
    assert lv["funding"] == "Series B，估值 $1.8B" and lv["sources"] == ["https://a", "https://d"] and lv["queries"] == ["q1", "q2"]
    assert dr._load("mid.json", {}) == got


def test_collect_includes_mid_companies(monkeypatch, tmp_path):
    from app.modules import _demand_mid as mid
    monkeypatch.setattr(dr, "BASE", tmp_path)
    dr._save("mid.json", {"lovable": {"name": "Lovable", "one_liner": "AI 生成应用", "website": "https://lovable.dev",
                                      "funding": "Series A $200M", "arr": "ARR $50M", "sources": ["https://a"], "found": "2026-11-26"}})
    P = {}
    mid.add_to(P, dr.norm)
    p = P[dr.norm("Lovable")]
    assert p["sources"] == ["中型 AI 创业公司"] and "AI 生成应用" in "\n".join(p["parts"]) and ("官网", "https://lovable.dev") in p["links"]
    assert p["date"] == "2026-11-26"


def test_thin_mid_candidates_get_profiled_before_cards(monkeypatch, tmp_path):
    from app.modules import _demand_mid as mid
    monkeypatch.setattr(dr, "BASE", tmp_path)
    dr._save("mid.json", {"fal": {"name": "fal", "arr": "约 $40M", "sources": [], "queries": []},
                          "krea": {"name": "Krea", "users": "设计师", "scenario": "边画边看", "pain": "试错慢", "sources": [], "queries": []}})
    asked = []

    class Fake:
        light = strong = "m"

        def call(self, model, system, user, web=False):
            asked.append(user)
            assert web
            return {"users": "做生成式应用的开发者", "scenario": "想快速调用图像视频模型", "pain": "自己部署 GPU 推理慢又贵",
                    "one_liner": "生成式媒体推理平台", "growth": "开发者口碑", "source_url": "https://fal.ai/blog"}
    assert mid.fill_profiles(Fake(), ["fal", "krea"]) == 1
    rec = dr._load("mid.json", {})["fal"]
    assert len(asked) == 1 and '"fal"' in asked[0]
    assert rec["pain"] == "自己部署 GPU 推理慢又贵" and rec["arr"] == "约 $40M" and rec["sources"] == ["https://fal.ai/blog"]
