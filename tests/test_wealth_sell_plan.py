from __future__ import annotations

import json
import math
import random
import shutil
import tempfile
import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.modules import _wealth_sell_plan as sp


SIGMA = 0.025  # ~40% annualised, roughly Meituan
CASES = [
    # (market, price, shares, target, lot): an HK lot-traded stock and a US single-share stock.
    ("HK", 74.55, 8500, 85.0, 100),
    ("", 182.4, 1300, 200.0, 1),
]


class EngineTest(unittest.TestCase):
    def test_touch_probability_limits(self) -> None:
        self.assertEqual(1.0, sp.touch_probability(100, 99, SIGMA, 63))
        near, far = sp.touch_probability(100, 105, SIGMA, 63), sp.touch_probability(100, 130, SIGMA, 63)
        self.assertGreater(near, far)
        self.assertLess(sp.touch_probability(100, 120, SIGMA, 21), sp.touch_probability(100, 120, SIGMA, 126))
        # With no deadline a martingale touches B with probability S/B, an upper bound for any horizon.
        self.assertAlmostEqual(100 / 120, sp.unlimited_touch_probability(100, 120))
        self.assertLess(sp.touch_probability(100, 120, SIGMA, 2000), sp.unlimited_touch_probability(100, 120))
        level = sp.level_for_probability(100, 0.5, SIGMA, 63)
        self.assertAlmostEqual(0.5, sp.touch_probability(100, level, SIGMA, 63), places=3)

    def test_sampled_paths_match_closed_form(self) -> None:
        draws = sp.sample_paths(SIGMA, 63, samples=20000)
        self.assertTrue(all(peak >= max(final, 0.0) - 1e-12 for peak, final in draws))
        self.assertAlmostEqual(1.0, sum(math.exp(final) for _, final in draws) / len(draws), delta=0.01)  # martingale
        level = math.log(1.15)
        sampled = sum(peak >= level for peak, _ in draws) / len(draws)
        self.assertAlmostEqual(sp.touch_probability(1, 1.15, SIGMA, 63), sampled, delta=0.015)

    def test_volatility_blend(self) -> None:
        rng = random.Random(7)
        closes = [100.0]
        for _ in range(300):
            closes.append(closes[-1] * math.exp(rng.gauss(0, 0.02)))
        vol = sp.daily_volatility(closes)
        self.assertAlmostEqual(0.02, vol["daily"], delta=0.004)
        self.assertAlmostEqual(vol["annual"], vol["daily"] * math.sqrt(sp.TRADING_DAYS))
        self.assertIsNone(sp.daily_volatility(closes[:10])["daily"])

    def test_hk_ticks(self) -> None:
        self.assertEqual(0.05, sp.tick_size(74.55, "HK"))
        self.assertEqual(0.2, sp.tick_size(250, "HK"))
        self.assertAlmostEqual(74.6, sp.round_to_tick(74.56, "HK"))
        self.assertAlmostEqual(74.55, sp.round_to_tick(74.56, "HK", up=False))
        self.assertAlmostEqual(182.41, sp.round_to_tick(182.405, ""))

    def test_allocation_respects_lots_and_required_average(self) -> None:
        prices = [77.15, 79.95, 83.2, 86.6, 90.1]
        probabilities = [sp.touch_probability(74.55, p, SIGMA, 63) for p in prices]
        for shares, required in ((8500, 85.0), (8450, 83.0), (300, 88.0)):
            lots = sp.allocate(prices, probabilities, shares, required, 100)
            self.assertEqual(shares, sum(lots))
            self.assertTrue(all(count % 100 == 0 for count in lots[1:]))
            self.assertGreaterEqual(sum(c * p for c, p in zip(lots, prices)) / shares, required - 1e-9)

    def test_plans_for_every_shape_and_market(self) -> None:
        for market, price, shares, target, lot in CASES:
            for shape in sp.SHAPES:
                with self.subTest(market=market or "US", shape=shape):
                    plan = sp.build_plan(price=price, total_shares=shares, target_avg=target, sigma_daily=SIGMA,
                                         horizon_days=63, lot=lot, market=market, shape=shape, samples=4000)
                    self.assertEqual(shares, sum(row["shares"] for row in plan["ladder"]))
                    limits = [row for row in plan["ladder"] if row["kind"] == "limit"]
                    self.assertEqual(sorted(row["price"] for row in limits), [row["price"] for row in limits])
                    self.assertEqual(len({row["price"] for row in limits}), len(limits))
                    self.assertTrue(all(row["shares"] % lot == 0 for row in limits))
                    self.assertGreaterEqual(plan["ladder_avg"], target - 1e-9)
                    self.assertGreater(plan["probability_target"], 0.05)
                    self.assertLessEqual(plan["p10_avg"], plan["p50_avg"])
                    self.assertLessEqual(plan["p50_avg"], plan["p90_avg"])
                    # Zero drift: no ladder can manufacture expected value above today's price.
                    self.assertAlmostEqual(price, plan["expected_avg"], delta=price * 0.01)
                    sweep = plan["sweep"]
                    self.assertEqual([0, shares], [sweep[0]["now_shares"], sweep[-1]["now_shares"]])
                    self.assertEqual(0.0, sweep[-1]["probability_target"])  # target above price: selling all now misses it
                    best = max(row["probability_target"] for row in sweep)
                    chosen = next(row for row in sweep if row["now_shares"] == plan["recommended_now_shares"])
                    self.assertGreaterEqual(chosen["probability_target"], best - 0.02 - 1e-9)

    def test_now_override_and_already_sold(self) -> None:
        plan = sp.build_plan(price=74.55, total_shares=8500, target_avg=85, sigma_daily=SIGMA, horizon_days=63,
                             lot=100, market="HK", sold_shares=1000, sold_proceeds=80000, now_shares=2000, samples=4000)
        self.assertTrue(plan["overridden"])
        self.assertEqual(7500, plan["remaining_shares"])
        self.assertAlmostEqual((85 * 8500 - 80000) / 7500, plan["required_avg_remaining"])
        market = [row for row in plan["ladder"] if row["kind"] == "market"]
        self.assertEqual([(74.55, 2000)], [(row["price"], row["shares"]) for row in market])
        self.assertAlmostEqual((80000 + 7500 * 74.55) / 8500, plan["sell_all_now_avg"])

    def test_target_below_price_sells_now(self) -> None:
        plan = sp.build_plan(price=74.55, total_shares=8500, target_avg=70, sigma_daily=SIGMA, horizon_days=63,
                             lot=100, market="HK", samples=2000)
        self.assertEqual(8500, plan["recommended_now_shares"])
        self.assertEqual(1.0, plan["probability_target"])

    def test_rejects_unknown_shape(self) -> None:
        with self.assertRaises(ValueError):
            sp.build_plan(price=10, total_shares=100, target_avg=11, sigma_daily=SIGMA, horizon_days=63, shape="yolo")

    def test_news_tags_and_word_boundaries(self) -> None:
        topics = {"AI": ["AI", "大模型"], "监管": ["反垄断"]}
        self.assertEqual(["AI"], sp.tag_news("美团发布大模型", topics)["topics"])
        self.assertEqual([], sp.tag_news("Retail sales rebound", topics)["topics"])  # "ai" inside "retail"
        self.assertEqual("negative", sp.tag_news("美团股价大跌，遭反垄断调查", topics)["tone"])

    def test_notable_moves_window_covers_overnight_gap(self) -> None:
        start = int(datetime(2026, 10, 27, 1, 30, tzinfo=UTC).timestamp())
        bars = [{"ts": start + i * 3600, "close": 70 + (0.05 if i % 2 else 0)} for i in range(12)]
        jump_ts = bars[-1]["ts"] + 18 * 3600  # next session's first bar
        bars.append({"ts": jump_ts, "close": 74.0})
        overnight = datetime.fromtimestamp(jump_ts - 10 * 3600, UTC).isoformat()
        news = [{"title": "隔夜消息", "url": "https://example.com", "source": "x", "published_at": overnight}]
        moves = sp.notable_moves(bars, news)
        self.assertEqual(jump_ts, moves[0]["ts"])
        self.assertTrue(moves[0]["gap"])
        self.assertEqual(["隔夜消息"], [item["title"] for item in moves[0]["news"]])


class CostAndReasoningTest(unittest.TestCase):
    def test_hk_costs_round_stamp_duty_and_apply_minimums(self) -> None:
        schedule = sp.cost_schedule("HK")
        small = sp.order_cost(10.0, 100, schedule)  # HK$1,000 notional
        self.assertEqual(1, small["stamp_duty"])  # 0.1% rounded up to the dollar
        self.assertEqual(3.0, small["commission"])  # minimum commission
        self.assertEqual(2.0, small["settlement"])  # minimum settlement fee
        self.assertAlmostEqual(sum(value for key, value in small.items() if key != "total"), small["total"], places=2)
        big = sp.order_cost(80.0, 8500, schedule)  # HK$680,000
        self.assertEqual(680, big["stamp_duty"])
        self.assertAlmostEqual(204.0, big["commission"])
        self.assertEqual(100.0, sp.order_cost(500.0, 100000, schedule)["settlement"])  # capped
        self.assertEqual({"total": 0.0}, sp.order_cost(80.0, 0, schedule))
        overridden = sp.cost_schedule("HK", {"HK": {"platform_fee": 0, "commission_rate": True, "bogus": 1}})
        self.assertEqual(0.0, overridden["platform_fee"])
        self.assertEqual(schedule["commission_rate"], overridden["commission_rate"])  # bools are ignored
        self.assertNotIn("bogus", overridden)

    def test_us_taf_is_capped(self) -> None:
        schedule = sp.cost_schedule("")
        self.assertNotIn("stamp_duty", sp.order_cost(180.0, 1000, schedule))
        self.assertEqual(schedule["taf_max"], sp.order_cost(10.0, 1_000_000, schedule)["taf"])

    def test_zero_kappa_matches_plain_reflection_formula(self) -> None:
        price, level, days = 100.0, 115.0, 63
        spread = SIGMA * math.sqrt(days)
        barrier, nu = math.log(level / price), -0.5 * SIGMA * SIGMA
        normal = sp._NORMAL
        expected = normal.cdf((-barrier + nu * days) / spread) + math.exp(2 * nu * barrier / SIGMA ** 2) * normal.cdf((-barrier - nu * days) / spread)
        self.assertAlmostEqual(expected, sp.touch_probability(price, level, SIGMA, days, kappa=0.0), places=12)
        # Drift uncertainty fattens both tails: far levels become more likely to be touched.
        self.assertGreater(sp.touch_probability(price, 160, SIGMA, 252, kappa=0.2), sp.touch_probability(price, 160, SIGMA, 252, kappa=0.0))

    def test_drift_mixture_paths_stay_a_martingale(self) -> None:
        for kappa in (0.0, 0.2):
            draws = sp.sample_paths(SIGMA, 252, samples=40000, kappa=kappa)
            mean = sum(math.exp(final) for _, final in draws) / len(draws)
            self.assertAlmostEqual(1.0, mean, delta=0.02, msg=f"kappa={kappa}")
            touched = sum(peak >= math.log(1.3) for peak, _ in draws) / len(draws)
            self.assertAlmostEqual(sp.touch_probability(1.0, 1.3, SIGMA, 252, kappa=kappa), touched, delta=0.015)

    def test_fill_timing_is_monotone_and_ordered(self) -> None:
        timing = sp.fill_timing(100, 112, SIGMA, 252)
        values = [timing["by_day"][str(day)] for day in sp.CHECKPOINTS]
        self.assertEqual(values, sorted(values))
        self.assertAlmostEqual(sp.touch_probability(100, 112, SIGMA, 252), values[-1])
        self.assertLessEqual(timing["q25_days"], timing["median_days"])
        self.assertLessEqual(timing["median_days"], timing["q75_days"])
        self.assertLessEqual(timing["q75_days"], 252)
        self.assertEqual(["21", "63"], list(sp.fill_timing(100, 112, SIGMA, 63)["by_day"]))

    def test_plan_explains_every_rung_and_carries_costs(self) -> None:
        plan = sp.build_plan(price=74.3, total_shares=8500, target_avg=81.3, sigma_daily=SIGMA, horizon_days=252,
                             lot=100, market="HK", costs=sp.cost_schedule("HK"))
        reasons = plan["reasons"]
        self.assertEqual({"overview", "now", "rungs", "contingency"}, set(reasons))
        limits = [row for row in plan["ladder"] if row["kind"] == "limit" and row["shares"]]
        self.assertEqual([(row["price"], row["shares"]) for row in limits], [(rung["price"], rung["shares"]) for rung in reasons["rungs"]])
        for rung in reasons["rungs"]:
            self.assertTrue(rung["price_reason"] and rung["shares_reason"] and rung["timing_reason"])
        for row in plan["ladder"]:
            if row["shares"]:
                self.assertLess(row["net_price"], row["price"])
                self.assertIn("median_date", row["timing"])
        self.assertLess(plan["all_filled_net_avg"], plan["all_filled_avg"])
        self.assertLess(plan["sell_all_now_net_avg"], plan["sell_all_now_avg"])
        self.assertGreater(plan["expected_costs"], 0)
        self.assertEqual([-0.2, 0.0, 0.2], [row["drift_annual"] for row in plan["drift_sensitivity"]])
        lean = sp.build_plan(price=74.3, total_shares=8500, target_avg=81.3, sigma_daily=SIGMA, horizon_days=252,
                             lot=100, market="HK", explain=False, samples=1500)
        self.assertNotIn("reasons", lean)

    def test_ceiling_bounds_every_shape_and_inverts(self) -> None:
        price, target, horizon = 74.3, 95.0, 252
        ceiling = sp.target_ceiling(price, SIGMA, horizon, target, 8500)
        self.assertAlmostEqual(sp.touch_probability(price, target, SIGMA, horizon), ceiling["probability"])
        self.assertGreaterEqual(ceiling["unlimited"], ceiling["probability"])
        by_days = [row["probability"] for row in ceiling["by_horizon"]]
        self.assertEqual(by_days, sorted(by_days))
        for shape in sp.SHAPES:
            plan = sp.build_plan(price=price, total_shares=8500, target_avg=target, sigma_daily=SIGMA, horizon_days=horizon,
                                 lot=100, market="HK", shape=shape, explain=False, samples=3000)
            self.assertLessEqual(plan["probability_target"], ceiling["probability"] + 0.02, shape)  # Monte Carlo noise
        for row in ceiling["targets"]:
            self.assertAlmostEqual(row["probability"], sp.touch_probability(price, row["target_avg"], SIGMA, horizon), places=4)
        curve = [point["probability"][str(horizon)] for point in ceiling["curve"]]
        self.assertEqual(curve, sorted(curve, reverse=True))
        self.assertAlmostEqual(1.0, curve[0])
        # After a sale the bound applies to the level the remaining shares still need.
        sold = sp.target_ceiling(price, SIGMA, horizon, target, 8500, sold_shares=2000, sold_proceeds=2000 * 80.0)
        self.assertAlmostEqual((target * 8500 - 160000) / 6500, sold["required_level"])
        for row in sold["targets"]:
            level = (row["target_avg"] * 8500 - 160000) / 6500
            self.assertAlmostEqual(row["probability"], sp.touch_probability(price, level, SIGMA, horizon), places=4)


