from __future__ import annotations

import math
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest import mock

from app.modules import _wealth_target_plan as tp

ASSETS = {
    "QQQ": {"mu": 0.09, "spread": 0.23},
    "GOOGL": {"mu": 0.12, "spread": 0.40},
    "MSFT": {"mu": 0.12, "spread": 0.30},
    "512890.SS": {"mu": 0.09, "spread": 0.14},
}
CORR = {a: {b: 1.0 if a == b else (0.0 if "512890.SS" in (a, b) else 0.6) for b in ASSETS} for a in ASSETS}
# Mild enough that the drawdown limit does not bind unless a test tightens it.
STRESS = {"QQQ": -0.05, "GOOGL": -0.05, "MSFT": -0.05, "512890.SS": -0.03}


def replay(rule: float, equal: float, hold: float, drawdown: float = -0.3) -> dict:
    return {"rule": {"cagr": rule, "max_drawdown": drawdown}, "equal": {"cagr": equal, "max_drawdown": -0.3}, "hold": {"cagr": hold, "max_drawdown": -0.3}}


class ModelTest(unittest.TestCase):
    def test_repair_splits_rescales_history_before_a_jump(self) -> None:
        self.assertEqual([5.0, 5.5, 5.5, 6.0], tp.repair_splits([10.0, 11.0, 5.5, 6.0]))   # 2-for-1 split
        self.assertEqual([1.0, 1.1, 1.2], tp.repair_splits([1.0, 1.1, 1.2]))               # ordinary moves untouched

    def test_probability_and_quantile_agree(self) -> None:
        mu, s = 0.08, 0.2
        self.assertAlmostEqual(0.5, tp.hit_probability(mu, s, math.expm1(mu)))
        for share in (0.1, 0.5, 0.9):
            with self.subTest(share=share):
                self.assertAlmostEqual(1 - share, tp.hit_probability(mu, s, tp.quantile(mu, s, share)))
        self.assertGreater(tp.hit_probability(mu, s, 0.05), tp.hit_probability(mu, s, 0.20))

    def test_long_run_shrinks_toward_the_prior(self) -> None:
        closes = [100 * math.exp(0.3 * i / tp.YEAR) for i in range(10 * tp.YEAR + 1)]   # 30% a year for 10 years
        etf, stock = tp.long_run(closes, years0=tp.SHRINK_YEARS), tp.long_run(closes, years0=tp.SHRINK_YEARS_STOCK)
        self.assertAlmostEqual(0.3, etf["history"])
        self.assertAlmostEqual(0.5, etf["weight"])
        self.assertAlmostEqual((0.3 + tp.PRIOR_LOG_RETURN) / 2, etf["mu"])
        self.assertLess(stock["mu"], etf["mu"])                    # single stocks lean harder on the prior
        self.assertEqual(tp.SHRINK_YEARS_STOCK, tp.shrink_years("GOOGL"))
        self.assertEqual(tp.SHRINK_YEARS, tp.shrink_years("QQQ"))

    def test_action_rules(self) -> None:
        self.assertEqual("reduce", tp.action(0.6, -0.01))           # below the 200-day average wins
        self.assertEqual("reduce", tp.action(0.3, 0.05))
        self.assertEqual("add", tp.action(0.5, 0.05))
        self.assertEqual("hold", tp.action(0.45, None))


class AllocationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.result = tp.allocate(ASSETS, CORR, 0.10)

    def test_constraints_hold(self) -> None:
        weights = self.result["weights"]
        self.assertAlmostEqual(1.0, sum(weights.values()))
        self.assertTrue(all(w >= tp.MIN_WEIGHT - 1e-9 for w in weights.values()))
        self.assertTrue(all(weights[s] <= tp.MAX_SINGLE_STOCK + 1e-9 for s in tp.SINGLE_STOCKS))
        self.assertGreaterEqual(self.result["stats"]["p10"], tp.P10_FLOOR)
        self.assertGreaterEqual(self.result["unconstrained_best"] + 1e-12, self.result["stats"]["probability"])

    def test_pick_is_within_a_point_of_the_best_and_steadiest(self) -> None:
        frontier = self.result["frontier"]
        top = frontier[0]["probability"]
        self.assertGreaterEqual(self.result["stats"]["probability"], top - tp.TIE_PROBABILITY)
        tied = [row for row in frontier if row["probability"] >= top - tp.TIE_PROBABILITY]
        self.assertGreaterEqual(self.result["stats"]["p10"] + 1e-12, max(row["p10"] for row in tied))   # frontier lists only the top 8

    def test_single_asset_portfolio_matches_the_asset(self) -> None:
        stats = self.result["references"]["QQQ"]["stats"]
        self.assertAlmostEqual(tp.hit_probability(ASSETS["QQQ"]["mu"], ASSETS["QQQ"]["spread"], 0.10), stats["probability"])


class BacktestHelpersTest(unittest.TestCase):
    def test_auc(self) -> None:
        self.assertEqual(1.0, tp._auc([0.1, 0.2, 0.8, 0.9], [False, False, True, True]))
        self.assertEqual(0.0, tp._auc([0.9, 0.8, 0.2, 0.1], [False, False, True, True]))
        self.assertEqual(0.5, tp._auc([0.5, 0.5], [True, False]))
        self.assertIsNone(tp._auc([0.1, 0.2], [True, True]))

    def test_max_drawdown(self) -> None:
        self.assertAlmostEqual(-0.5, tp._max_drawdown([1.0, 2.0, 1.0, 1.5]))

    def test_verdict_follows_the_numbers(self) -> None:
        self.assertIn("都更高", tp._replay_verdict(replay(0.2, 0.1, 0.1), replay(0.2, 0.1, 0.1)))
        self.assertIn("只在一段", tp._replay_verdict(replay(0.2, 0.1, 0.1), replay(0.1, 0.2, 0.1)))
        self.assertIn("都没有胜过", tp._replay_verdict(replay(0.1, 0.2, 0.1), replay(0.1, 0.2, 0.1)))


if __name__ == "__main__":
    unittest.main()


class SafeAllocationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.safe = tp.safe_allocate(ASSETS, CORR, 0.10, STRESS)

    def test_pick_meets_the_steady_constraints(self) -> None:
        stats, weights = self.safe["stats"], self.safe["weights"]
        self.assertFalse(self.safe["relaxed"])
        self.assertGreaterEqual(stats["nonneg"], tp.SAFE_NONNEG)
        self.assertGreaterEqual(stats["p10"], tp.SAFE_P10_FLOOR)
        self.assertAlmostEqual(1.0, sum(weights.values()))
        for s in tp.SINGLE_STOCKS:
            self.assertLessEqual(weights.get(s, 0), tp.MAX_SINGLE_STOCK + 1e-9)

    def test_options_cover_each_set_of_holdings_once(self) -> None:
        keys = [tuple(row["holdings"]) for row in self.safe["options"]]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertIn(("QQQ", "512890.SS"), keys)
        self.assertIn(("512890.SS",), keys)
        best_ok = max(row["probability"] for row in self.safe["options"] if row["ok"])
        self.assertAlmostEqual(best_ok, max(r["probability"] for r in self.safe["options"] if r["ok"]))
        self.assertGreaterEqual(best_ok + 1e-9, self.safe["stats"]["probability"])

    def test_falls_back_to_the_steadiest_mix_when_nothing_passes(self) -> None:
        with mock.patch.object(tp, "SAFE_NONNEG", 0.999):
            safe = tp.safe_allocate(ASSETS, CORR, 0.10, STRESS)
        self.assertTrue(safe["relaxed"])
        self.assertFalse(any(row["ok"] for row in safe["options"]))
        self.assertAlmostEqual(max(row["nonneg"] for row in safe["options"]), safe["stats"]["nonneg"])

    def test_drawdown_limit_binds_and_moves_the_pick(self) -> None:
        assets = {**ASSETS, tp.BOND: {"mu": 0.035, "spread": 0.02}}
        corr = {a: {b: 1.0 if a == b else (0.0 if tp.BOND in (a, b) else CORR[a][b]) for b in assets} for a in assets}
        loose = tp.safe_allocate(assets, corr, 0.10, {s: -0.01 for s in assets})
        stress = {"QQQ": -0.30, "GOOGL": -0.40, "MSFT": -0.35, "512890.SS": -0.15, tp.BOND: -0.01}
        safe = tp.safe_allocate(assets, corr, 0.10, stress)
        self.assertFalse(safe["relaxed"])
        self.assertGreaterEqual(safe["stats"]["stress_drawdown"], -tp.SAFE_MAX_DRAWDOWN - 1e-9)
        self.assertAlmostEqual(sum(w * stress[s] for s, w in safe["weights"].items()), safe["stats"]["stress_drawdown"])
        self.assertLess(safe["stats"]["probability"], loose["stats"]["probability"])
        self.assertEqual({"max_drawdown": tp.SAFE_MAX_DRAWDOWN, "grid": 1 / tp.SAFE_GRID},
                         {k: safe["constraints"][k] for k in ("max_drawdown", "grid")})
        for row in safe["options"]:
            if row["ok"]:
                self.assertGreaterEqual(row["stress_drawdown"], -tp.SAFE_MAX_DRAWDOWN - 1e-9)
        by_holdings = {tuple(row["holdings"]): row for row in safe["options"]}
        self.assertFalse(by_holdings[("QQQ",)]["ok"])

    def test_stress_drawdowns_use_the_window_and_the_funds_own_record(self) -> None:
        start = int(datetime(2020, 1, 1, tzinfo=UTC).timestamp())
        ts = [start - 86_400, start, start + 86_400, start + 2 * 86_400]
        stress = tp.stress_drawdowns({
            "A": {"ts": ts, "close": [100.0, 10.0, 8.0, 9.0]},       # the crash before the window does not count
            "B": {"ts": ts, "close": [1.0, 1.0, 0.99, 1.0], "funds": {"x": {"max_drawdown": -0.03}, "y": {"max_drawdown": -0.001}}},
        }, ["A", "B"])
        self.assertAlmostEqual(-0.2, stress["A"])
        self.assertAlmostEqual(-0.03, stress["B"])


class LadderTest(unittest.TestCase):
    def test_levels_round_down_to_the_tick(self) -> None:
        self.assertEqual([1.238, 1.200, 1.163, 1.114], [round(x, 3) for x in tp.ladder_levels("512890.SS", 1.238)])
        levels = tp.ladder_levels("GOOGL", 279.52)
        self.assertEqual(279.52, levels[0])
        self.assertAlmostEqual(271.13, levels[1])
        for level, depth in zip(levels[1:], tp.LADDER_DEPTHS[1:]):
            self.assertLessEqual(level, 279.52 * (1 - depth) + 1e-9)

    def test_dip_probability_falls_with_depth(self) -> None:
        self.assertEqual(1.0, tp.dip_probability(100, 100, 0.015, 0.08, 63))
        probs = [tp.dip_probability(100, 100 * (1 - d), 0.015, 0.08, 63) for d in (0.03, 0.06, 0.10, 0.20)]
        self.assertEqual(probs, sorted(probs, reverse=True))
        self.assertTrue(all(0 < p < 1 for p in probs))

    def test_fill_probability_agrees_with_the_simulation(self) -> None:
        price, sigma, mu = 100.0, 0.015, 0.08
        levels = [price * (1 - d) for d in tp.LADDER_DEPTHS]
        sim = tp.simulate_ladder(price, levels, sigma, mu, 0.10, samples=3000)
        for level, rate in zip(levels[1:], sim["fill_rates"][1:]):
            with self.subTest(level=level):   # the simulation sees daily closes only, so it fills a little less
                self.assertAlmostEqual(tp.dip_probability(price, level, sigma, mu, tp.LADDER_DAYS), rate, delta=0.12)
        self.assertIn(sim["model_pick"], tp.LADDER_SHAPES)

    def test_ladder_return_by_hand(self) -> None:
        levels, shape = (1.0, 0.9), (0.5, 0.5)
        self.assertAlmostEqual(0.5 / 1.0 + 0.5 / 0.9 - 1, tp.ladder_return(levels, shape, 0.85, 1.05, 1.0))   # dip filled
        self.assertAlmostEqual((0.5 + 0.5 / 1.05) * 1.2 - 1, tp.ladder_return(levels, shape, 0.95, 1.05, 1.2))  # bought at window end
        self.assertAlmostEqual(0.2, tp.ladder_return((1.0,), (1.0,), 0.5, 2.0, 1.2))

    def test_orders_round_to_lots_and_report_leftover(self) -> None:
        levels = tp.ladder_levels("512890.SS", 1.238)
        plan = tp.ladder_orders("512890.SS", 1.238, levels, tp.LADDER_SHAPES["balanced"], 50_000, [1, 0.8, 0.6, 0.4])
        self.assertEqual(100, plan["lot"])
        self.assertTrue(all(o["units"] % 100 == 0 for o in plan["orders"]))
        self.assertEqual(["market", "limit", "limit", "limit"], [o["kind"] for o in plan["orders"]])
        self.assertAlmostEqual(50_000 - plan["spent"], plan["leftover"])
        self.assertGreaterEqual(plan["leftover"], 0)
        us = tp.ladder_orders("QQQ", 600.0, tp.ladder_levels("QQQ", 600.0), tp.LADDER_SHAPES["lump"], 1_000, [1, 0, 0, 0])
        self.assertEqual(1, us["orders"][0]["units"])

    def test_replay_on_a_steady_rise_never_fills_the_dips(self) -> None:
        closes = [100 * 1.001 ** i for i in range(tp.YEAR * 3)]
        rep = tp.ladder_replay(closes, 0.10)
        self.assertGreater(rep["n"], 0)
        self.assertEqual([1.0, 0.0, 0.0, 0.0], rep["fill_rates"])
        self.assertEqual(0.0, rep["shapes"]["balanced"]["beats_lump"])
        self.assertLess(rep["shapes"]["balanced"]["mean"], rep["shapes"]["lump"]["mean"])
        self.assertIsNone(tp.ladder_replay(closes[:tp.YEAR], 0.10))

    def test_verdict_reads_the_replay(self) -> None:
        self.assertEqual("", tp.ladder_verdict({}))
        row = {"n": 10, "shapes": {"lump": {"mean": 0.10, "p10": -0.10}, "balanced": {"mean": 0.08, "p10": -0.07, "beats_lump": 0.4}}}
        text = tp.ladder_verdict({"QQQ": row, "X": None})
        self.assertIn("40%", text)
        self.assertIn("低 2.0", text)
        self.assertIn("好 3.0", text)


class MixHistoryTest(unittest.TestCase):
    def test_weighted_buy_and_hold(self) -> None:
        n = tp.YEAR * 3
        ts = [86_400 * i for i in range(n)]
        up = [100 * 1.2 ** (i / tp.YEAR) for i in range(n)]     # +20% a year
        flat = [50.0] * n
        mix = tp.mix_history({"A": {"ts": ts, "close": up}, "B": {"ts": ts, "close": flat}}, {"A": 0.5, "B": 0.5}, 0.05)
        self.assertAlmostEqual(0.10, mix["median"])
        self.assertEqual(1.0, mix["hit_rate"])
        self.assertEqual(1.0, mix["nonneg_rate"])
        self.assertIsNone(tp.mix_history({"A": {"ts": ts, "close": up}}, {"A": 0.0}, 0.05))
        self.assertIsNone(tp.mix_history({"A": {"ts": ts[:tp.YEAR], "close": up[:tp.YEAR]}}, {"A": 1.0}, 0.05))

    def test_max_drawdown_of_the_rebalanced_mix(self) -> None:
        n = tp.YEAR * 2
        ts = [86_400 * i for i in range(n)]
        # A halves inside one rebalancing period, then stays flat; B never moves.
        drop = [100.0 if i < tp.STEP // 2 else 50.0 for i in range(n)]
        flat = [50.0] * n
        histories = {"A": {"ts": ts, "close": drop}, "B": {"ts": ts, "close": flat}}
        self.assertAlmostEqual(-0.1, tp.mix_history(histories, {"A": 0.2, "B": 0.8}, 0.05)["max_drawdown"])
        self.assertAlmostEqual(0.0, tp.mix_history(histories, {"B": 1.0}, 0.05)["max_drawdown"])


class FxTest(unittest.TestCase):
    def test_falls_back_without_network_and_caches_fresh_quotes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(tp, "fetch_fx", side_effect=OSError("offline")):
                out = tp.fx_rates(Path(tmp), ["USD", "HKD"])
            self.assertEqual({"rate": 1.0, "source": "same"}, out["HKD"])
            self.assertEqual("fallback", out["USD"]["source"])
            self.assertAlmostEqual(tp.FX_FALLBACK["USD"], out["USD"]["rate"])
            self.assertIsNone(out["USD"]["as_of"])
            self.assertFalse((Path(tmp) / tp.FX_FILE).exists())
            with mock.patch.object(tp, "fetch_fx", return_value=0.85):
                self.assertEqual("yahoo", tp.fx_rates(Path(tmp), ["CNY"])["CNY"]["source"])
            with mock.patch.object(tp, "fetch_fx", side_effect=AssertionError("cache should be used")):
                self.assertAlmostEqual(0.85, tp.fx_rates(Path(tmp), ["CNY"])["CNY"]["rate"])


class DelayTest(unittest.TestCase):
    def test_horizon_scales_drift_and_spread(self) -> None:
        self.assertEqual(ASSETS, tp.horizon_assets(ASSETS, 1.0))
        self.assertAlmostEqual(0.2, tp.horizon_spread(0.2, 1.0))
        h = tp.delay_horizon(1)
        self.assertAlmostEqual((tp.YEAR - tp.MONTH) / tp.YEAR, h)
        short = tp.horizon_assets(ASSETS, h)
        sigma = 0.23 / math.sqrt(1 + tp.KAPPA)
        self.assertAlmostEqual(0.09 * h, short["QQQ"]["mu"])
        self.assertAlmostEqual(sigma * math.sqrt(h * (1 + tp.KAPPA * h)), short["QQQ"]["spread"])

    def test_waiting_lowers_the_chance_of_the_target(self) -> None:
        weights = {"QQQ": 0.3, "GOOGL": 0.0, "MSFT": 0.0, "512890.SS": 0.7}
        full = tp.portfolio(weights, ASSETS, CORR, 0.10)["probability"]
        late = [tp.portfolio(weights, tp.horizon_assets(ASSETS, tp.delay_horizon(m)), CORR, 0.10)["probability"] for m in (1, 2, 3)]
        self.assertEqual(late, sorted(late, reverse=True))
        self.assertLess(late[0], full)

    def test_ladder_and_history_follow_the_shorter_hold(self) -> None:
        levels = [100 * (1 - d) for d in tp.LADDER_DEPTHS]
        year = tp.simulate_ladder(100, levels, 0.015, 0.08, 0.10, samples=1500)
        short = tp.simulate_ladder(100, levels, 0.015, 0.08, 0.10, samples=1500, horizon=tp.YEAR - 3 * tp.MONTH)
        self.assertLess(short["shapes"]["lump"]["probability"], year["shapes"]["lump"]["probability"])
        self.assertEqual(year["fill_rates"], short["fill_rates"])          # same seed, same first 63 sessions
        n = tp.YEAR * 3
        ts, up = [86_400 * i for i in range(n)], [100 * 1.2 ** (i / tp.YEAR) for i in range(n)]
        held = tp.mix_history({"A": {"ts": ts, "close": up}}, {"A": 1.0}, 0.05, days=tp.YEAR - tp.MONTH)
        self.assertAlmostEqual(1.2 ** ((tp.YEAR - tp.MONTH) / tp.YEAR) - 1, held["median"])


class BondTest(unittest.TestCase):
    def test_basket_is_equal_weight_on_common_dates(self) -> None:
        navs = {"A": {"2025-01-01": 1.0, "2025-01-02": 1.02, "2025-01-03": 1.02},
                "B": {"2025-01-02": 2.0, "2025-01-03": 2.0, "2025-01-04": 2.1}}
        basket = tp.bond_basket(navs)
        self.assertEqual(2, len(basket["close"]))                       # only 01-02 and 01-03 are shared
        self.assertAlmostEqual(1.0, basket["close"][-1])
        navs["B"]["2025-01-03"] = 2.04
        self.assertAlmostEqual(1.01, tp.bond_basket(navs)["close"][-1])  # half of +0% and half of +2%

    def test_centre_is_last_year_return_and_action_holds(self) -> None:
        day = 86_400
        ts = [i * day for i in range(800)]
        closes = [1.0 * math.exp(0.04 * i / 365) for i in range(800)]
        result = tp.assess_bond(closes, ts, 0.03)
        self.assertAlmostEqual(0.04, result["mu"], places=6)
        self.assertEqual("hold", result["action"])
        self.assertGreater(result["probability"], 0.5)

    def test_bond_may_be_left_out_of_the_aggressive_mix(self) -> None:
        assets = {**ASSETS, tp.BOND: {"mu": 0.04, "spread": 0.012}}
        corr = {a: {b: 1.0 if a == b else (0.0 if tp.BOND in (a, b) else CORR[a][b]) for b in assets} for a in assets}
        result = tp.allocate(assets, corr, 0.10)
        weights = result["weights"]
        self.assertTrue(all(w >= tp.MIN_WEIGHT - 1e-9 for s, w in weights.items() if s != tp.BOND))
        self.assertIn(tp.BOND, weights)


def valuation(pes: list[float], cgb: float = 3.0, start: str = "2017-01-06") -> dict:
    from datetime import date, timedelta
    day0 = date.fromisoformat(start)
    pe = [[(day0 + timedelta(weeks=i)).isoformat(), p] for i, p in enumerate(pes)]
    return {"pe": pe, "cgb": [["2016-12-30", cgb]], "dividend_yield": 0.05, "pe_now": pes[-1], "fetched_at": 0}


class TimingTest(unittest.TestCase):
    def setUp(self) -> None:
        n = 9 * 365
        self.ts = [1_483_228_800 + 86_400 * i for i in range(n)]      # daily from 2017-01-01
        self.closes = [1.0 * 1.0002 ** i for i in range(n)]

    def test_zone_thresholds(self) -> None:
        self.assertEqual("cheap", tp.timing_zone(0.29))
        self.assertEqual("fair", tp.timing_zone(0.30))
        self.assertEqual("fair", tp.timing_zone(0.70))
        self.assertEqual("dear", tp.timing_zone(0.71))

    def test_record_high_pe_reads_dear_and_low_reads_cheap(self) -> None:
        rising = [6 + 0.01 * i for i in range(400)]                    # P/E at its high, spread at its low
        t = tp.dividend_timing(valuation(rising), self.closes, self.ts)
        self.assertEqual(1.0, t["pe_percentile"])
        self.assertAlmostEqual(1 / len(rising), t["spread_percentile"])
        self.assertEqual(("dear", "dear"), (t["zone"], t["shape"]))
        self.assertAlmostEqual(0.05 - 0.03, t["dividend_spread"])
        # the replay only looks back, so a steady rise sits in "dear" every week, with the ETF's next-year return
        self.assertIsNone(t["zones"]["cheap"])
        self.assertAlmostEqual(1.0002 ** 365 - 1, t["zones"]["dear"]["median"], places=6)
        falling = [10 - 0.01 * i for i in range(400)]
        c = tp.dividend_timing(valuation(falling), self.closes, self.ts)
        self.assertEqual(("cheap", "cheap"), (c["zone"], c["shape"]))
        self.assertIn("便宜", tp.timing_reason(c))

    def test_fair_keeps_the_chosen_shape_and_short_history_is_none(self) -> None:
        flat = [8 + (0.5 if i % 2 else -0.5) for i in range(400)] + [8.0]
        t = tp.dividend_timing(valuation(flat), self.closes, self.ts)
        self.assertEqual("fair", t["zone"])
        self.assertIsNone(t["shape"])
        self.assertIsNone(tp.dividend_timing(valuation(flat[:100]), self.closes, self.ts))

    def test_stale_cache_is_served_when_the_fetch_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(tp, "fetch_valuation", side_effect=OSError("down")):
                self.assertIsNone(tp.load_valuation(Path(tmp)))
            fresh = valuation([8.0] * 200)
            with mock.patch.object(tp, "fetch_valuation", return_value=fresh):
                self.assertFalse(tp.load_valuation(Path(tmp), refresh=True)["stale"])
            with mock.patch.object(tp, "fetch_valuation", side_effect=OSError("down")):
                served = tp.load_valuation(Path(tmp), refresh=True)
            self.assertTrue(served["stale"])
            self.assertEqual(fresh["pe"], served["pe"])

    def test_extra_shape_is_simulated_but_never_the_model_pick(self) -> None:
        levels = tp.ladder_levels("512890.SS", 1.2)
        sim = tp.simulate_ladder(1.2, levels, 0.01, 0.08, 0.10, samples=800, extra={"timing": tp.TIMING_SHAPES["dear"]})
        self.assertIn("timing", sim["shapes"])
        self.assertIn(sim["model_pick"], tp.LADDER_SHAPES)

    def test_orders_follow_the_timing_shape(self) -> None:
        from app.modules import _wealth_service as svc
        levels = tp.ladder_levels("512890.SS", 1.2)
        base = {"currency": "CNY", "price": 1.2, "levels": levels, "dip_probability": [1, 0.6, 0.4, 0.2]}
        ladders = {"512890.SS": {**base, "timing": {"zone": "dear", "weights": tp.TIMING_SHAPES["dear"]}},
                   "QQQ": {**base, "currency": "USD", "price": 600.0, "levels": tp.ladder_levels("QQQ", 600.0), "timing": None}}
        fx = {"CNY": {"rate": 0.9}, "USD": {"rate": 0.128}}
        rows = svc.target_orders({"512890.SS": 0.5, "QQQ": 0.5}, ladders, fx, {"net": 1_000_000}, "lump")
        div, qqq = rows
        self.assertEqual("timing", div["shape"])
        self.assertEqual([0.0, 0.03, 0.06], [round(o["depth"], 2) for o in div["plan"]["orders"]])   # no −10% order when dear
        self.assertTrue(all(o["units"] > 0 for o in div["plan"]["orders"]))
        self.assertEqual("lump", qqq["shape"])
        self.assertEqual(["market"], [o["kind"] for o in qqq["plan"]["orders"]])
