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
