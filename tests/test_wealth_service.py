"""理财板块：持仓服务（用合成行情）、信号提醒、通用通知和接口。"""
import json
import math
import random
from datetime import UTC, datetime, timedelta

import pytest

from app import db, notify
from app.modules import _wealth_alerts as alerts
from app.modules import _wealth_service as svc
from app.modules import wealth


@pytest.fixture
def positions(client, tmp_path, monkeypatch):
    """临时 data/wealth：美团 8500 股 + NVDA 1300 股，合成 300 天日线和 60 小时线。"""
    monkeypatch.setattr(svc, "DATA", tmp_path)
    monkeypatch.setattr(svc, "POSITIONS", tmp_path / "positions.json")
    monkeypatch.setattr(svc, "LIVE", None)
    monkeypatch.setattr(svc, "_switch_memo", None)
    monkeypatch.setattr(svc.asset_valuation, "load", lambda _: None)
    for table in ("wealth_bars", "wealth_quotes", "wealth_trades"):
        db.execute(f"DELETE FROM {table}")
    svc.write_positions({"positions": [
        {"symbol": "3690.HK", "shares": 8500, "lot_size": 100, "target_avg": None, "horizon_days": 63, "shape": "balanced"},
        {"symbol": "NVDA", "shares": 1300, "lot_size": 1, "horizon_days": 63, "shape": "balanced"}]})
    now = datetime.now(UTC).replace(minute=30, second=0, microsecond=0)
    rng = random.Random(3)
    for symbol, price in (("3690.HK", 74.55), ("NVDA", 182.4)):
        daily, close = [], price
        for day in range(300, 0, -1):
            close *= math.exp(rng.gauss(0, 0.02))
            daily.append(_bar(now - timedelta(days=day), close))
        svc.store_bars(symbol, "1d", daily)
        svc.store_bars(symbol, "60m", [_bar(now - timedelta(hours=h), price) for h in range(60, 0, -1)])
    return tmp_path


def _bar(when, price):
    return {"ts": int(when.timestamp()), "open": price, "high": price, "low": price, "close": price, "adj_close": price, "volume": 1}


def _saved(symbol):
    return next(p for p in svc.read_positions()["positions"] if p["symbol"] == symbol)


@pytest.mark.parametrize("drawdown", [0.0, 0.5, float("nan")])
def test_target_rejects_a_drawdown_limit_out_of_range(drawdown):
    with pytest.raises(ValueError, match="回撤上限"):
        svc.target(0.1, drawdown=drawdown)


def test_plan_for_hk_and_us_positions(positions):
    assert {p["symbol"] for p in svc.positions()} == {"3690.HK", "NVDA"}
    for symbol, price in (("3690.HK", 74.55), ("NVDA", 182.4)):
        data = svc.sell(symbol)
        assert data["quote"]["price"] == pytest.approx(price)
        assert data["execution"]["remaining_shares"] == data["position"]["shares"]
        assert data["plan"]["target_avg"] > price   # 默认目标：现价上浮 10%
        assert sum(r["shares"] for r in data["plan"]["ladder"]) == data["position"]["shares"]


def test_trades_drive_realised_and_required_average(positions):
    svc.add_trade("3690.HK", 1000, 80.0, "2026-11-02T03:00:00+00:00", "first")
    trade = svc.add_trade("3690.HK", 500, 82.0)
    ex = svc.sell("3690.HK", target_avg=85)["execution"]
    assert ex["sold_shares"] == 1500
    assert ex["realized_avg"] == pytest.approx((80000 + 41000) / 1500)
    assert ex["required_avg_remaining"] == pytest.approx((85 * 8500 - 121000) / 7000)
    svc.delete_trade(trade["id"])
    assert svc.sell("3690.HK", target_avg=85)["execution"]["sold_shares"] == 1000


@pytest.mark.parametrize("shares,price,when", [(0, 80, None), (100, -1, None), (True, 80, None), (100, float("nan"), None),
                                               (100, 80, "yesterday"), (9000, 80, None)])
def test_trade_validation(positions, shares, price, when):
    with pytest.raises(ValueError):
        svc.add_trade("3690.HK", shares, price, when)


def test_trade_needs_configured_position_and_existing_id(positions):
    with pytest.raises(ValueError):
        svc.add_trade("AAPL", 1, 1)
    with pytest.raises(ValueError):
        svc.delete_trade(999)


def test_update_position_persists_and_validates(positions):
    svc.update_position("3690.HK", {"target_avg": 88.5, "shape": "wide", "horizon_days": 126})
    saved = _saved("3690.HK")
    assert (saved["target_avg"], saved["shape"], saved["horizon_days"]) == (88.5, "wide", 126)
    plan = svc.sell("3690.HK")["plan"]
    assert (plan["target_avg"], plan["shape"], plan["horizon_days"]) == (88.5, "wide", 126)
    for bad in ({"shape": "yolo"}, {"horizon_days": 2}, {"target_avg": -5}, {"horizon_days": 300}, {"horizon_days": True},
                {"target_avg": float("inf")}):
        with pytest.raises(ValueError):
            svc.update_position("3690.HK", bad)


def test_plan_reports_costs_alternatives_and_ceiling(positions):
    data = svc.sell("3690.HK", target_avg=82, horizon_days=252)
    plan = data["plan"]
    assert plan["horizon_days"] == 252
    assert "stamp_duty_rate" in data["costs"]["schedule"]
    assert {r["shape"] for r in plan["shape_comparison"]} == {"concentrated", "balanced", "wide"}
    assert plan["net_target"]["gross_avg_needed"] >= plan["target_avg"]
    assert data["backtest"] is None
    assert plan["probability_target"] <= data["ceiling"]["probability"] + 0.02
    assert data["ceiling"]["net_probability"] <= data["ceiling"]["probability"]
    assert "taf_per_share" in svc.sell("NVDA")["costs"]["schedule"]


def test_unlimited_horizon_and_switch_comparison(positions):
    svc.update_position("3690.HK", {"horizon_days": 0, "compare_days": 252})
    assert (_saved("3690.HK")["horizon_days"], _saved("3690.HK")["compare_days"]) == (0, 252)
    data = svc.sell("3690.HK", target_avg=90, qqq_return=0.13)
    assert data["position"]["unlimited"] and data["position"]["compare_days"] == 252
    assert data["switch"]["days"] == 252
    assert data["switch"]["assumptions"]["qqq_return"] == pytest.approx(0.13)
    assert {"hold", "switch_now", "plan"} <= {r["key"] for r in data["switch"]["strategies"]}
    for bad in ({"compare_days": 500}, {"compare_days": True}, {"horizon_days": 3}):
        with pytest.raises(ValueError):
            svc.update_position("3690.HK", bad)
    with pytest.raises(ValueError):
        svc.sell("3690.HK", compare_days=100)


# ---------------------------------------------------------------- 信号提醒

def _state(action="hold", label="持有", zone="fair", now_shares=1000, price=74.0, fraction=0.5):
    asset = {"name": "红利低波ETF", "action": action, "label": label, "probability": 0.6, "price": 1.2, "currency": "CNY",
             "reason": "结论：示例", "reasons": ["估值择时：示例", "结论：示例"], "zone": zone, "zone_label": {"fair": "合理", "dear": "偏贵"}[zone],
             "pacing": "分批"}
    exit_ = {"symbol": "3690.HK", "name": "美团", "currency": "HKD", "price": price, "now_shares": now_shares, "remaining": 8500,
             "probability": 0.3, "target_avg": 85, "rungs": [{"price": 80.0, "shares": 2000}, {"price": 90.0, "shares": 2000}],
             "switch_fraction": fraction, "hold_median": 1.0, "switch_median": 1.1, "now_reasons": ["现卖理由"], "switch_reasons": ["换仓理由"]}
    return {"target": 0.1, "assets": {"512890.SS": asset}, "exit": exit_}


def test_no_events_without_an_earlier_snapshot():
    assert alerts.changes(None, _state()) == []
    assert alerts.changes(_state(), _state()) == []


def test_changes_report_action_valuation_and_exit_with_reasons():
    events = alerts.changes(_state(), _state(action="reduce", label="减持", zone="dear", now_shares=2000, price=81.0, fraction=0.7))
    kinds = {e["kind"]: e for e in events}
    assert set(kinds) == {"action", "valuation", "exit_now", "exit_rung", "exit_switch"}
    assert "持有 → 减持" in kinds["action"]["title"]
    assert kinds["valuation"]["reasons"] == ["估值择时：示例"]
    assert "80.0" in kinds["exit_rung"]["title"]   # 只报穿过的那一档，90 没到
    assert all(e["reasons"] for e in events)


def test_summary_due_once_a_day_after_the_time():
    at = datetime(2026, 11, 3, 16, 29)
    assert not alerts.summary_due({"summary_date": None}, at, "16:30")
    assert alerts.summary_due({"summary_date": None}, at.replace(minute=30), "16:30")
    assert not alerts.summary_due({"summary_date": "2026-11-03"}, at.replace(hour=20), "16:30")
    summary = alerts.summary(_state())
    assert summary["title"] == "每日信号汇总 · 目标 10%"
    assert summary["reasons"][-1] == "统计估算，不构成投资建议。"


def test_check_alerts_sends_changes_and_summary(client, tmp_path, monkeypatch):
    states = iter([_state(), _state(action="add", label="增持")])
    monkeypatch.setattr(svc, "DATA", tmp_path)
    monkeypatch.setattr(svc, "target", lambda goal: {})
    monkeypatch.setattr(svc, "positions", lambda: [])
    monkeypatch.setattr(alerts, "snapshot", lambda plan, exit_plan: next(states))
    first = wealth.check_alerts(now=datetime(2026, 11, 3, 10, 0))
    assert first["events"] == []
    second = wealth.check_alerts(now=datetime(2026, 11, 3, 16, 31))
    assert [e["kind"] for e in second["events"]] == ["action", "summary"]
    log = notify.list_notifications(alerts.MODULE, 5)
    assert log[0]["title"].startswith("每日信号汇总") and log[0]["reasons"]
    assert log[1]["link"] == "#wealth/target" and "持有 → 增持" in log[1]["title"]
    assert alerts.load(tmp_path)["summary_date"] == "2026-11-03"


# ---------------------------------------------------------------- 通用通知和接口

def test_notify_since_starts_from_the_latest(client):
    db.execute("DELETE FROM notifications")
    assert client.get("/api/notify/since").json() == {"last": 0, "items": []}
    assert client.get("/api/notify/since?after=0").json() == {"last": 0, "items": []}
    nid = notify.notify("wealth", "标题", "正文", ["理由一"], link="#wealth/alerts")
    got = client.get("/api/notify/since?after=0").json()
    assert got["last"] == nid and got["items"][0]["reasons"] == ["理由一"]
    assert client.get("/api/notify/since").json() == {"last": nid, "items": []}
    assert client.get(f"/api/notify/since?after={nid}").json() == {"last": nid, "items": []}


def test_notify_respects_system_setting(client, monkeypatch):
    calls = []
    monkeypatch.setattr(notify, "system_notify", lambda *a: calls.append(a) or True)
    nid = notify.notify("wealth", "关掉系统通知", "x")
    assert calls == [] and db.row("SELECT system FROM notifications WHERE id=?", (nid,))["system"] == 0


def test_wealth_routes(client):
    assert "alerts" in client.get("/api/wealth/status").json()
    nid = client.post("/api/wealth/alerts/test").json()["id"]
    assert client.get("/api/notify?module=wealth&limit=1").json()[0]["id"] == nid
    assert client.get("/api/wealth/alerts?limit=1").json()["log"][0]["kind"] == "test"
    assert client.post("/api/wealth/backtest/nope").status_code == 404
    assert client.get("/api/wealth/sell-plan?symbol=NOPE").status_code == 400
    assert client.get("/api/wealth/region-mix?overseas=2").status_code == 400
    assert client.get("/api/wealth/region-mix?basket=nope").status_code == 400
    assert "wealth" in json.dumps(client.get("/api/meta").json(), ensure_ascii=False)
    assert client.post("/api/wealth/view/nope", json={}).status_code == 400
    assert client.post("/api/wealth/view/target", json={"target": "abc"}).status_code == 400


def test_chat_context_uses_page_view(client, monkeypatch):
    from app.modules import wealth
    seen = {}
    plan = {"target": 0.15, "assets": [{"symbol": "QQQ", "name": "纳指100 ETF", "currency": "USD", "price": 685.28, "action_label": "持有 / 定投", "probability": 0.49,
                                        "p10": -0.19, "p50": 0.1, "p90": 0.48, "val_timing": {"index": "纳指", "metric": "PE", "zone_label": "合理",
                                                                                               "decision": {"label": "可少量买", "reason": "估值合理", "plan": "分批买线 486.10"}, "ma": {"text": "现价偏低"}}},
                                       {"symbol": "BOND.CN", "name": "纯债基金", "price": 1.1, "val_timing": None}],
            "allocation": {"weights": {"QQQ": 0.1}, "stats": {"probability": 0.56}, "orders": []},
            "safe": {"weights": {"BOND.CN": 0.9, "QQQ": 0}, "stats": {"probability": 0.16, "stress_drawdown": -0.03},
                     "orders": [{"symbol": "BOND.CN", "weight": 0.9, "amount": 1000, "currency": "CNY"}]}}
    monkeypatch.setattr(wealth.svc, "target", lambda *a: seen.update(args=a) or plan)
    monkeypatch.setattr(wealth.svc, "region_mix", lambda *a: seen.update(region=a) or {"overseas": 0.3, "mainland": 0.7, "basket": "qqq", "baskets": {"qqq": "只买 QQQ"}, "start": "2019-01-18", "years": 7.75,
                                                                                       "rows": [{"dividend": 1.0, "annual": 0.14, "max_drawdown": -0.13, "worst_year": -0.05, "worst_3y": 0.19}]})
    assert client.post("/api/wealth/view/target", json={"target": 0.15, "delay": 2, "drawdown": 0.03, "shape": "wide", "mode": "safe", "region": 30, "basket": "qqq", "junk": 1}).status_code == 200
    text = wealth.agent_context("wealth:target")
    assert seen == {"args": (0.15, "wide", 2, 0.03), "region": (0.3, "qqq")}
    for part in ("目标页", "回撤上限 3%", "可少量买", "分批买线 486.10", "纯债基金 90%", "压力回撤 -3.0%", "只买 QQQ", "只回答和计算", "不替用户下单"):
        assert part in text, part
    assert "junk" not in wealth._views["target"]


def test_chat_context_sell_page(positions):
    from app.modules import wealth
    text = wealth.agent_context("wealth:sell")
    for part in ("减持页", "美团", "挂单阶梯", "换 QQQ 对比", "不替用户下单"):
        assert part in text, part
    assert len(text) < 12000


def test_chat_context_survives_plan_errors(client, monkeypatch):
    from app.modules import wealth
    def boom(*_a):
        raise wealth.svc.Busy("正在回测")
    monkeypatch.setattr(wealth.svc, "target", boom)
    assert "暂时算不出来：正在回测" in wealth.agent_context("wealth:target")
    assert "用户正在看" not in wealth.agent_context("")      # 侧边栏的新对话没有绑定页面


def test_sell_plan_includes_signals_without_changing_plan(positions):
    before = svc.sell("3690.HK")
    assert before["signals"]["snapshot"] is None    # 还没有大盘数据
    assert before["signals"]["evidence"] is None
    assert any(r["active"] for r in before["signals"]["stages"])
    bench = [_bar(datetime.now(UTC) - timedelta(days=d), 3.0) for d in range(300, 0, -1)]
    svc.store_bars("3033.HK", "1d", bench)
    after = svc.sell("3690.HK")
    assert after["signals"]["snapshot"]["benchmark"]["name"] == "恒生科技 ETF"
    assert after["plan"]["ladder"] == before["plan"]["ladder"]
    assert after["plan"]["probability_target"] == before["plan"]["probability_target"]


def test_startup_does_not_refresh_in_the_background(tmp_path, monkeypatch):
    import threading
    monkeypatch.delenv("SELF_STARTUP_NO_AUTOREFRESH", raising=False)
    monkeypatch.setattr(svc, "DATA", tmp_path)
    monkeypatch.setattr(svc, "start_live", lambda: None)
    wealth.on_startup()
    assert "wealth-loop" not in {t.name for t in threading.enumerate()}


def test_manual_refresh_recomputes_signals_and_due_backtests(client, tmp_path, monkeypatch):
    import threading
    ran = []
    monkeypatch.setattr(svc, "DATA", tmp_path)
    monkeypatch.setattr(svc, "refresh", lambda: ran.append("refresh") or {"ok": True})
    monkeypatch.setattr(svc, "target_plan_due", lambda: False)
    monkeypatch.setattr(svc, "sell_backtest_due", lambda: True)
    monkeypatch.setattr(svc, "signals_backtest_due", lambda: False)
    monkeypatch.setattr(svc, "run_sell_backtest", lambda: ran.append("sell_backtest"))
    monkeypatch.setattr(svc, "run_signals_backtest", lambda: ran.append("signals_backtest"))
    monkeypatch.setattr(wealth, "check_alerts", lambda: ran.append("alerts"))
    assert client.post("/api/wealth/refresh").json() == {"ok": True}
    for t in threading.enumerate():
        if t.name == "wealth-after-refresh":
            t.join(5)
    assert ran == ["refresh", "alerts", "sell_backtest"]
