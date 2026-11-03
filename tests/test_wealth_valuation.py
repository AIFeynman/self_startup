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
    assert av.load(tmp_path)["sources"] == {"QQQ": []}
    assert called == []
