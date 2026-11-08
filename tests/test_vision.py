"""视野板块：真实来源取数、显著度、解读卡校验、数据修订只追加。"""
import json
from datetime import date

import pytest

from app import db, main  # noqa: F401  初始化建表
from app.modules import _vision_sources as src, _vision_stats as vs, vision


@pytest.fixture(scope="module")
def cache():
    return {}


@pytest.mark.parametrize("sid,not_before", [
    ("tfr_chn", "2023"),
    ("us_unrate", f"{date.today().year - 1}-06"),
    ("eci_closed", f"{date.today().year - 1}-06"),
    ("cn_retail_yoy", f"{date.today().year - 1}-06"),
])
def test_real_sources_are_fresh(sid, not_before, cache):
    pts = src.fetch(vision.BY_ID[sid], cache)
    assert len(pts) > 10
    assert pts[-1][0] >= not_before


def _upto(sid, period, cache):
    cfg = vision.BY_ID[sid]
    return cfg, [p for p in src.fetch(cfg, cache) if p[0] <= period]


def test_china_fertility_below_one_is_significant(cache):
    cfg, pts = _upto("tfr_chn", "2023", cache)
    sig = vs.signals(cfg, pts)
    assert sig["score"] > 0
    assert 1.0 in sig["gates"]
    assert any("新低" in r for r in sig["reasons"])


def test_retail_turning_negative_is_significant(cache):
    cfg, pts = _upto("cn_retail_yoy", "2026-05", cache)
    assert pts[-1] == ("2026-05", pytest.approx(-0.6))
    sig = vs.signals(cfg, pts)
    assert sig["score"] > 0
    assert "同比由正转负" in sig["reasons"]


def _seed(sid, pts):
    db.execute("DELETE FROM vision_points WHERE series_id=?", [sid])
    vision.save_points(sid, pts)


def test_card_with_invented_number_is_rejected():
    sid = "cn_retail_yoy"
    _seed(sid, [(f"2025-{m:02d}", 3.0 + m / 10) for m in range(1, 13)] + [("2026-01", -0.6)])
    cid = vision.start_card(sid, force=True, attempt=vision.MAX_ATTEMPTS)
    card = {"title": "大家突然不愿意花钱了", "plain": "上个月全国商店卖出的东西比去年少了", "analogy": "像一家店客流突然变少",
            "why": [{"text": "年初消费补贴退坡", "url": "", "date": "", "kind": "推测"}],
            "deeper": {"type": "交叉对照", "text": "和信心指数对照，下滑比信心更早出现，降幅 37.5 个百分点"},
            "predictions": [{"series_id": sid, "due": f"{date.today().year + 1}-06-30", "op": ">", "target": 0, "confidence": "中", "text": "明年年中转正"}],
            "meaning": "消费类创业要更看重性价比", "next": "下个月中旬看新一期数据"}
    job = {"status": "done", "output": json.dumps(card, ensure_ascii=False), "ref": f"vision:card:{cid}"}
    vision.on_job_done(job)
    row = db.row("SELECT * FROM vision_cards WHERE id=?", [cid])
    assert row["status"] == "rejected"
    problems = json.loads(row["checks"])["problems"]
    assert any("37.5" in p for p in problems)
    assert not db.rows("SELECT id FROM vision_cards WHERE status='done' AND id=?", [cid])


def test_revisions_append_and_latest_wins():
    sid = "us_unrate"
    _seed(sid, [("2026-01", 4.1), ("2026-02", 4.2)])
    vision.save_points(sid, [("2026-01", 4.1), ("2026-02", 4.3), ("2026-03", 4.4)])
    assert vision.points(sid) == [("2026-01", 4.1), ("2026-02", 4.3), ("2026-03", 4.4)]
    feb = db.rows("SELECT value, revision FROM vision_points WHERE series_id=? AND period='2026-02' ORDER BY revision", [sid])
    assert [(r["value"], r["revision"]) for r in feb] == [(4.2, 0), (4.3, 1)]


def test_overview_orders_themes_ai_first(client):
    d = client.get("/api/vision/overview").json()
    assert [t["id"] for t in d["themes"]] == ["ai", "fun", "life", "learn", "macro"]


@pytest.mark.parametrize("text", [
    "软件岗位比去年同月多 14%（同比，即和去年同一个月比）",
    "2024 年（3.8e25 FLOP，算力单位，指总共做了多少次计算）还比 2023 年高",
    "出生率从 6.39‰ 回升到 6.77‰，也就是每千人出生 6.77 个",
])
def test_explained_terms_pass(text):
    from app.modules import _vision_cards as vc
    card = {"title": "t", "plain": text, "analogy": "a", "meaning": "m", "next": "n", "why": [], "deeper": {}}
    probs = vc.check(card, [], set(), lambda u: (200, ""))["problems"]
    assert not any("术语" in p for p in probs)


@pytest.mark.parametrize("sid", ["eci_closed", "eci_open", "eci_china", "eci_gap_open", "bench_swe", "bench_metr", "compute_frontier"])
def test_frontier_series_name_the_model(sid, cache):
    *_, label = src.fetch(vision.BY_ID[sid], cache)[-1]
    assert label and not label[0].isdigit()
    if sid.startswith("eci_gap"):
        assert " 比 " in label


def test_series_page_and_agent_show_which_model(client):
    sid = "eci_open"
    _seed(sid, [("2026-01", 150.0, "旧模型"), ("2026-02", 152.5, "新模型 A")])
    vision.save_points(sid, [("2026-01", 150.0, "旧模型"), ("2026-02", 152.5, "新模型 A"), ("2026-03", 152.5, "新模型 A")])
    d = client.get(f"/api/vision/series/{sid}").json()
    assert d["summary"]["label"] == "新模型 A"
    assert d["labels"]["2026-01"] == "旧模型"
    tile = next(s for t in client.get("/api/vision/overview").json()["themes"] for s in t["series"] if s["id"] == sid)
    assert tile["summary"]["label"] == "新模型 A"
    ctx = vision.agent_context(f"vision:series:{sid}")
    assert "新模型 A" in ctx and "2026-01" in ctx and vision.BY_ID[sid]["name"] in ctx
