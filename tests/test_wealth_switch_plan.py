from __future__ import annotations

import math
import unittest

from app.modules import _wealth_sell_plan as sp
from app.modules import _wealth_switch_plan as sw

SIGMA = 0.025
NO_COST: dict[str, float] = {}
TAX = sw.tax_settings()


def one_path(final: float, peak: float, qqq: float) -> dict:
    """A single hand-built path on a one-step grid, so every number in the wealth formula can be checked by hand."""
    return {"grid": [12], "days": 12, "paths": [{"peaks": [peak], "qqq": [qqq], "kept": {}, "final": final}]}


class TaxAndWealthTest(unittest.TestCase):
    def test_tax_settings_ignore_invalid_overrides(self) -> None:
        self.assertEqual(sw.DEFAULT_TAX, sw.tax_settings({"rate": -1, "threshold": True, "unknown": 5}))
        self.assertEqual(0.1, sw.tax_settings({"rate": 0.1})["rate"])

    def test_hold_is_taxed_only_above_the_threshold(self) -> None:
        specs = {"hold": {"now": 0, "staged": [], "rungs": []}}
        for final, expected in ((90.0, 90.0), (130.0, 130.0 - 0.2 * 30)):
            with self.subTest(final=final):
                wealth = sw.evaluate(one_path(final, final, 1.0), specs, price=80.0, remaining=10, costs=NO_COST, tax=TAX)["wealth"]
                self.assertAlmostEqual(10 * expected, wealth["hold"][0])

    def test_switch_pays_sale_tax_switch_cost_and_gain_tax(self) -> None:
        specs = {"switch_now": {"now": 10, "staged": [], "rungs": []}}
        wealth = sw.evaluate(one_path(50.0, 120.0, 1.5), specs, price=110.0, remaining=10, costs=NO_COST, tax=TAX)["wealth"]
        proceeds = 10 * (110.0 - 0.2 * 10)                       # 20% on the part above 100
        gross = proceeds * (1 - sw.SWITCH_COST_RATE) ** 2 * 1.5   # in and out of QQQ
        self.assertAlmostEqual(gross - 0.2 * (gross - proceeds), wealth["switch_now"][0])

    def test_limit_fill_sells_at_the_level_and_buys_qqq(self) -> None:
        specs = {"plan": {"now": 0, "staged": [], "rungs": [(105.0, 4), (140.0, 6)]}}
        result = sw.evaluate(one_path(90.0, 120.0, 1.0), specs, price=100.0, remaining=10, costs=NO_COST, tax=TAX, target_avg=95.0)
        filled = 4 * (105.0 - 0.2 * 5)
        moved = filled * (1 - sw.SWITCH_COST_RATE) ** 2
        expected = moved - 0.2 * max(0.0, moved - filled) + 6 * 90.0   # 140 not reached: 6 shares held at 90
        self.assertAlmostEqual(expected, result["wealth"]["plan"][0])
        self.assertEqual(4, result["filled"]["plan"])
        self.assertEqual(1.0, result["target"]["plan"])                  # (4*105 + 6*90) / 10 = 96 >= 95


class CompareTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        price, lot, remaining = 74.55, 100, 8500
        rungs = [(85.0, 3000), (95.0, 3000), (110.0, 2500)]
        cls.report = sw.compare(price=price, sigma_daily=SIGMA, remaining=remaining, lot=lot, plan_now=0, rungs=rungs,
                                costs=sp.cost_schedule("HK"), tax=TAX, days=252, samples=600, target_avg=90.0)

    def by_key(self, key: str) -> dict:
        return next(row for row in self.report["strategies"] if row["key"] == key)

    def sweep(self, fraction: float, rest: str) -> dict:
        return next(row for row in self.report["sweep"] if row["fraction"] == fraction and row["rest"] == rest)

    def test_sweep_endpoints_match_hold_and_switch(self) -> None:
        for metric in ("mean", "p10", "p50"):
            with self.subTest(metric=metric):
                self.assertAlmostEqual(self.by_key("hold")[metric], self.sweep(0.0, "hold")[metric])
                self.assertAlmostEqual(self.by_key("switch_now")[metric], self.sweep(1.0, "hold")[metric])
                self.assertAlmostEqual(self.by_key("plan")[metric], self.sweep(0.0, "ladder")[metric])

    def test_switch_now_never_hits_a_target_above_the_price(self) -> None:
        self.assertEqual(0.0, self.by_key("switch_now")["target_probability"])
        self.assertGreater(self.by_key("plan")["target_probability"], self.by_key("hold")["target_probability"] - 0.05)

    def test_break_even_ties_hold_and_switch(self) -> None:
        mean = self.report["break_even"]["mean"]
        self.assertIsNotNone(mean)
        # Holding has to earn roughly QQQ's assumed return (less costs and the tax asymmetry) to tie on the mean.
        self.assertGreater(mean, 0.0)
        self.assertLess(mean, 0.2)
        rows = {row["qqq_return"]: row for row in self.report["sensitivity"]}
        self.assertEqual({0.0, 0.08, 0.13, 0.2}, set(rows))
        self.assertTrue(rows[0.08]["current"])
        self.assertLess(rows[0.0]["break_even"], rows[0.2]["break_even"])     # a better QQQ raises the bar for holding
        self.assertLess(rows[0.0]["mean_ratio"]["switch_now"], rows[0.2]["mean_ratio"]["switch_now"])
        self.assertTrue(self.report["reasons"])

    def test_kappa_unchanged_within_a_year(self) -> None:
        self.assertEqual(sp.drift_spread(SIGMA, 0.2, 252), sp.drift_spread(SIGMA, 0.2))
        self.assertAlmostEqual(sp.drift_spread(SIGMA, 0.2, 756) ** 2 * 3, sp.drift_spread(SIGMA, 0.2) ** 2)

    def test_split_and_scale_respect_lots(self) -> None:
        self.assertEqual([2100, 2100, 2100, 2200], sw.split_shares(8500, 4, 100))
        scaled = sw.scale_ladder([(85.0, 3000), (95.0, 3000), (110.0, 2500)], 4250, 100)
        self.assertEqual(4250, sum(n for _, n in scaled))
        self.assertTrue(all(n % 100 == 0 for _, n in scaled[:-1]))


if __name__ == "__main__":
    unittest.main()
