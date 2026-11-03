import json
import math
import time
from datetime import UTC, date, datetime, timedelta

import pytest

from app.modules import _wealth_target_plan as tp
from app.modules import _wealth_valuation as av


def _series(start="2017-01-01", years=9, level=lambda i: 100 * math.exp(0.0003 * i + 0.25 * math.sin(i / 200))):
    days = [date.fromisoformat(start) + timedelta(days=i) for i in range(int(years * 365))]
    return [[d.isoformat(), level(i)] for i, d in enumerate(days)]


def _closes(rows):
    return [r[1] for r in rows], [int(datetime.fromisoformat(r[0]).replace(tzinfo=UTC).timestamp()) for r in rows]


def _zone_at(timing, metrics, history, directions):
    return tp.timing_zone(tp._score(history, directions, metrics)[0])


class TestTtmEps:
    def row(self, start, end, val, filed):
        return {"start": start, "end": end, "val": val, "filed": filed}

    def test_q4_from_full_year_and_earliest_filing_wins(self):
        rows = [self.row("2020-01-01", "2020-03-31", 1, "2020-04-30"), self.row("2020-01-01", "2020-03-31", 9, "2021-04-30"),
                self.row("2020-04-01", "2020-06-30", 2, "2020-07-30"), self.row("2020-07-01", "2020-09-30", 3, "2020-10-30"),
                self.row("2020-01-01", "2020-12-31", 10, "2021-02-01")]
        assert av.ttm_eps(rows) == [["2021-02-01", 10]]

    def test_a_late_restated_filing_date_does_not_delay_the_figures(self):
        rows = [self.row("2020-01-01", "2020-03-31", 1, "2020-04-30"), self.row("2020-04-01", "2020-06-30", 2, "2020-07-30"),
                self.row("2020-07-01", "2020-09-30", 3, "2020-10-30"), self.row("2020-01-01", "2020-12-31", 10, "2023-02-01")]
        assert av.ttm_eps(rows) == [["2021-03-16", 10]]

    def test_figures_filed_before_a_split_are_restated(self):
        rows = [self.row(f"2021-{a}-01", f"2021-{b}", 20, f) for a, b, f in (
            ("01", "03-31", "2021-05-01"), ("04", "06-30", "2021-08-01"), ("07", "09-30", "2021-11-01"), ("10", "12-31", "2022-02-01"))]
        assert av.ttm_eps(rows, [["2022-07-18", 20.0]]) == [["2022-02-01", 4.0]]


def test_ttm_sales_uses_cumulative_reports_and_waits_for_the_report():
    rows = [{"REPORT_DATE": "2020-06-30 00:00:00", "DATE_TYPE_CODE": "002", "OPERATE_INCOME": 40, "ISSUED_COMMON_SHARES": 10, "EPS_TTM": -1},
            {"REPORT_DATE": "2020-12-31 00:00:00", "DATE_TYPE_CODE": "001", "OPERATE_INCOME": 100, "ISSUED_COMMON_SHARES": 10, "EPS_TTM": -1},
            {"REPORT_DATE": "2021-06-30 00:00:00", "DATE_TYPE_CODE": "002", "OPERATE_INCOME": 60, "ISSUED_COMMON_SHARES": None, "EPS_TTM": -2}]
    series = av.ttm_sales_per_share(rows)
    assert series == [["2021-03-31", 10.0, -1], ["2021-09-28", 12.0, -2]]


def _check_edges(timing, price):
    levels = timing["levels"]
    assert levels["cheap_below"] < levels["dear_above"]
    assert levels["to_cheap"] == pytest.approx(levels["cheap_below"] / price - 1)
    assert set(levels["bands"]) == {"cheap", "fair", "dear"}
    assert f"{levels['cheap_below']:.2f}" in levels["headline"] or f"{levels['cheap_below']:.3f}" in levels["headline"]
    assert sum((z or {"n": 0})["n"] for z in timing["zones"].values()) > 52
    assert timing["cards"] and timing["note"]


def test_every_kind_gets_a_table_and_price_levels():
    bars = _series()
    closes, ts = _closes(bars)
    price = closes[-1] * 1.02
    us10y = _series(level=lambda i: 3 + math.sin(i / 300))
    pes = [[r[0], r[1] / 5] for r in bars[::7]]
    eps = [["2016-01-01", 5.0]]
    sales = [["2016-01-01", 50.0, -1.0]]
    data = {"sources": {"us10y": us10y, "QQQ": pes, "GOOGL": {"bars": bars, "eps": eps}, "3690.HK": {"bars": bars, "fx": _series(level=lambda i: 0.9), "sales": sales}}}
    qqq = av.timing_for("QQQ", data, closes, ts, price, currency="USD", forward_pe=20.0)
    google = av.timing_for("GOOGL", data, closes, ts, price, currency="USD")
    meituan = av.timing_for("3690.HK", data, closes, ts, price, currency="HKD")
    for timing in (qqq, google, meituan):
        _check_edges(timing, price)
    assert qqq["cards"][-1]["label"] == "远期 PE" and meituan["metric"] == "PS"
    bond = av.timing_for(tp.BOND, None, closes, ts, closes[-1], currency="CNY", cgb=us10y)
    assert "%" in bond["levels"]["bands"]["cheap"]["price"] and bond["levels"]["price"] is None


def test_price_at_each_edge_flips_the_zone_and_live_price_moves_the_zone():
    bars = _series()
    closes, ts = _closes(bars)
    sales = [["2016-01-01", 50.0, 1.0]]
    data = {"sources": {"3690.HK": {"bars": bars, "fx": _series(level=lambda i: 1.0), "sales": sales}}}
    timing = av.timing_for("3690.HK", data, closes, ts, closes[-1], currency="HKD")
    levels = timing["levels"]
    at = lambda p: av.timing_for("3690.HK", data, closes, ts, p, currency="HKD")["zone"]
    assert at(levels["cheap_below"] * 0.99) == "cheap"
    assert at(levels["cheap_below"] * 1.01) == "fair"
    assert at(levels["dear_above"] * 0.99) == "fair"
    assert at(levels["dear_above"] * 1.01) == "dear"
    # 分界线不随现价变
    again = av.timing_for("3690.HK", data, closes, ts, closes[-1] * 0.8, currency="HKD")["levels"]
    assert again["cheap_below"] == pytest.approx(levels["cheap_below"], rel=1e-6)


def test_loss_making_earnings_or_short_history_shows_no_table():
    bars = _series(years=2)
    closes, ts = _closes(bars)
    data = {"sources": {"us10y": _series(), "GOOGL": {"bars": bars, "eps": [["2016-01-01", 5.0]]}}}
    assert av.timing_for("GOOGL", data, closes, ts, 100, currency="USD") is None
    assert av.timing_for("NVDA", data, closes, ts, 100, currency="USD") is None
    assert av.timing_for("QQQ", None, closes, ts, 100, currency="USD") is None


def _bars(level, years=8):
    start = datetime.now(UTC).date() - timedelta(days=int(years * 365))
    return [[(start + timedelta(days=i)).isoformat(), level(i)] for i in range(int(years * 365) + 1)]


class TestMaReference:
    def test_lines_bracket_the_average_and_follow_the_price(self):
        bars = _bars(lambda i: 100 + 20 * math.sin(i / 90))
        ma = av.ma_reference(bars, bars[-1][1])
        assert ma["low"] < ma["high"]
        assert ma["ma200"] == pytest.approx(sum(b[1] for b in bars[-200:]) / 200)
        assert av.ma_reference(bars, ma["low"] * 0.99)["zone"] == "cheap"
        assert av.ma_reference(bars, ma["high"] * 1.01)["zone"] == "dear"
        assert av.ma_reference(bars, (ma["low"] + ma["high"]) / 2)["zone"] == "fair"

    def test_useful_only_when_higher_positions_did_worse_by_enough(self):
        zone = lambda median, n=52: {"n": n, "median": median, "loss": 0.2}
        assert av._ma_useful({"cheap": zone(0.2), "fair": zone(0.1), "dear": zone(0.0)})
        assert not av._ma_useful({"cheap": zone(0.1), "fair": zone(0.2), "dear": zone(0.0)})
        assert not av._ma_useful({"cheap": zone(0.12), "fair": zone(0.11), "dear": zone(0.1)})
        assert not av._ma_useful({"cheap": zone(0.2, 5), "fair": zone(0.1), "dear": zone(0.0)})
        assert not av._ma_useful({"cheap": None, "fair": zone(0.1), "dear": zone(0.0)})

    def test_short_or_old_history_gives_nothing(self):
        assert av.ma_reference(_bars(lambda i: 100.0, years=1), 100) is None
        old = [[(date(2020, 1, 1) + timedelta(days=i)).isoformat(), 100.0] for i in range(1400)]
        assert av.ma_reference(old, 100) is None

    def test_attach_strips_the_replay_and_keeps_the_table_without_bars(self):
        timing = {"metric": "PE", "zone": "fair", "replay": [("2020-01-01", "fair")], "levels": {"currency": "USD", "headline": "old", "cheap_below": 90, "dear_above": 110}}
        assert av.attach_ma(timing, tp.BOND, {"sources": {}}, 1.0) == {k: v for k, v in timing.items() if k != "replay"}
        assert av.attach_ma(None, "QQQ", {"sources": {}}, 1.0) is None

    def test_sales_table_says_it_is_not_a_target_price(self):
        bars = _bars(lambda i: 100 + 20 * math.sin(i / 90))
        timing = {"metric": "PS", "zone": "cheap", "replay": [(b[0], "cheap") for b in bars[::7]], "levels": {"currency": "HKD", "headline": "old", "cheap_below": 180, "dear_above": 447}}
        out = av.attach_ma(timing, "3690.HK", {"sources": {"3690.HK": {"bars": bars}}}, 100)
        assert "不是目标价" in out["levels"]["headline"] and out["decision"]["stuck"] and "rows" not in out["ma"]
        # 估值分不出贵贱时，价位只来自均线，不用市销率算出来的 180 / 447
        assert out["decision"]["buy_line"] == out["ma"]["low"] and out["decision"]["sell_line"] == out["ma"]["high"]


def _ma(zone, rows):
    return {"zone": zone, "low": 90.0, "high": 110.0, "rows": rows}


def _rows(pairs, year, quarter=0.01):
    """pairs: (估值档, 均线档) 各放 30 周。"""
    start = date(2020, 1, 3)
    rows, replay = [], []
    for k, (v, m) in enumerate(p for p in pairs for _ in range(30)):
        day = (start + timedelta(days=7 * k)).isoformat()
        replay.append((day, v))
        rows.append({"day": day, "zone": m, "year": year(v, m), "quarter": quarter})
    return rows, replay


class TestDecision:
    MIXED = [("cheap", "cheap"), ("cheap", "fair"), ("fair", "fair"), ("dear", "fair"), ("dear", "dear")]

    def test_both_sides_combine_into_five_actions(self):
        rows, replay = _rows(self.MIXED, lambda v, m: -0.1 if v == m == "dear" else 0.1)
        cases = {("cheap", "cheap"): "buy", ("cheap", "fair"): "small_buy", ("fair", "cheap"): "small_buy", ("fair", "fair"): "hold",
                 ("cheap", "dear"): "hold", ("dear", "fair"): "no_add", ("fair", "dear"): "no_add", ("dear", "dear"): "sell"}
        for (v, m), action in cases.items():
            assert av.decision(v, replay, 80.0, 120.0, _ma(m, rows), 100.0)["action"] == action, (v, m)

    def test_lines_need_both_sides_to_agree(self):
        rows, replay = _rows(self.MIXED, lambda v, m: -0.1 if v == m == "dear" else 0.1)
        out = av.decision("fair", replay, 80.0, 120.0, _ma("fair", rows), 100.0)
        assert (out["buy_line"], out["sell_line"]) == (80.0, 120.0)
        assert "分批买线 80.00（-20.0%）" in out["plan"] and "分批减线 120.00（+20.0%）" in out["plan"]

    def test_history_can_veto_a_buy_or_a_sell(self):
        losing = lambda v, m: -0.2 if v == m == "cheap" else 0.1
        rows, replay = _rows(self.MIXED, losing)
        out = av.decision("cheap", replay, 80.0, 120.0, _ma("cheap", rows), 100.0)
        assert out["action"] == "wait" and "到了也不买" in out["plan"]
        rows, replay = _rows(self.MIXED, lambda v, m: 0.1)
        out = av.decision("dear", replay, 80.0, 120.0, _ma("dear", rows), 100.0)
        assert out["action"] == "no_add" and "到了也先不卖" in out["plan"]

    def test_stuck_valuation_is_ignored(self):
        rows, replay = _rows([("cheap", "cheap"), ("cheap", "fair"), ("cheap", "dear")], lambda v, m: -0.1 if m == "dear" else 0.1)
        out = av.decision("cheap", replay, 180.0, 447.0, _ma("fair", rows), 100.0)
        assert out["stuck"] and out["action"] == "hold" and (out["buy_line"], out["sell_line"]) == (90.0, 110.0)
        assert av.decision("cheap", replay, 180.0, 447.0, _ma("cheap", rows), 100.0)["action"] == "buy"

    def test_thin_history_keeps_the_rule_and_says_so(self):
        rows, replay = _rows(self.MIXED, lambda v, m: 0.1)
        rows, replay = rows[:-20], replay[:-20]
        out = av.decision("dear", replay, 80.0, 120.0, _ma("dear", rows), 100.0)
        assert out["action"] == "sell" and "样本少" in out["evidence"]


def test_refresh_keeps_the_old_copy_of_a_failed_source(tmp_path, monkeypatch):
    def fetch(name):
        if name == "QQQ":
            raise OSError("down")
        return [["2026-01-01", 1.0]]
    (tmp_path / av.CACHE_FILE).write_text(json.dumps({"fetched_at": 0, "sources": {"QQQ": "old"}}))
    monkeypatch.setattr(av, "fetch_source", fetch)
    stored = av.refresh(tmp_path)
    assert stored["sources"]["QQQ"] == "old" and stored["failed"] == ["QQQ"]
    assert stored["sources"]["MSFT"] == [["2026-01-01", 1.0]]
    # 有源失败：一小时后再试，不等 20 小时
    assert time.time() - stored["fetched_at"] == pytest.approx(3600 * (tp.CACHE_HOURS - 1), abs=60)


def test_load_never_waits_for_the_sources(tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr(av, "refresh", lambda d: called.append(d))
    assert av.load(tmp_path) is None
    for _ in range(100):
        if called:
            break
        time.sleep(0.01)
    assert called == [tmp_path]
    (tmp_path / av.CACHE_FILE).write_text(json.dumps({"fetched_at": time.time(), "sources": {"QQQ": []}}))
    called.clear()
    (tmp_path / av.CACHE_FILE).write_text(json.dumps({"fetched_at": time.time(), "sources": {name: [] for name in av.SOURCES}}))
    assert set(av.load(tmp_path)["sources"]) == set(av.SOURCES)
    assert called == []
