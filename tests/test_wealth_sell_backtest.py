from __future__ import annotations

import math
import random
import tempfile
import unittest
from pathlib import Path

from app.modules import _wealth_sell_backtest as bt
from app.modules import _wealth_sell_plan as sp


def synthetic_history(seed: int, days: int = 1300, sigma: float = 0.022) -> dict[str, list[float]]:
    """Zero-drift GBM closes with an intraday high drawn from the Brownian-bridge maximum of each day."""
    rng = random.Random(seed)
    close, closes, highs, ts = 50.0, [], [], []
    for day in range(days):
        step = -0.5 * sigma * sigma + sigma * rng.gauss(0, 1)
        peak = 0.5 * (step + math.sqrt(step * step - 2 * sigma * sigma * math.log(1 - rng.random())))
        highs.append(close * math.exp(max(peak, step, 0.0)))
        close *= math.exp(step)
        closes.append(close)
        ts.append(1_500_000_000 + day * 86400)
    return {"ts": ts, "close": closes, "high": highs}


class SellBacktestTest(unittest.TestCase):
    def test_calibration_recovers_gbm_touch_rates(self) -> None:
        rows, spans = [], {}
        for seed in range(6):
            history = synthetic_history(seed)
            rows += bt.calibration_rows(f"SYN{seed}", history, 3, (0.0, sp.DRIFT_KAPPA))
            spans[f"SYN{seed}"] = len(history["close"]) - bt.WARMUP
        summary = {entry["days"]: entry for entry in bt.summarize_calibration(rows, (0.0, sp.DRIFT_KAPPA), spans)}
        month = summary[21]
        plain = month["models"][0]
        self.assertLess(plain["brier"], month["brier_climatology"])  # the model has skill on its own world
        for bucket in plain["buckets"]:
            if bucket["n"] >= 200:
                self.assertAlmostEqual(bucket["predicted"], bucket["realized"], delta=0.1, msg=bucket)
        self.assertAlmostEqual(1.0, month["z_variance"], delta=0.25)

    def test_strategy_rows_replay_every_baseline(self) -> None:
        history = synthetic_history(11, days=700)
        rows = bt.strategy_rows("SYN.HK", history, 200)
        self.assertTrue(rows)
        row = rows[0]
        for key in ("plan", "plan_net", "now", "now_net", "twap", "twap_net", "single", "single_net"):
            self.assertGreater(row[key], 0, key)
        self.assertLess(row["now_net"], row["now"])
        self.assertAlmostEqual(1.0, row["now"])
        self.assertTrue(0 <= row["predicted"] <= 1)
        summary = bt.summarize_strategy(rows, {"SYN.HK": len(history["close"]) - bt.WARMUP})
        self.assertTrue(summary)
        self.assertEqual({"plan", "now", "twap", "single"}, set(summary[0]["strategies"]))
        lo, hi = summary[0]["realized_interval"]
        self.assertLessEqual(lo, summary[0]["realized"])
        self.assertLessEqual(summary[0]["realized"], hi)

    def test_report_round_trip_and_markdown(self) -> None:
        history = synthetic_history(5, days=700)
        spans = {"SYN.HK": len(history["close"]) - bt.WARMUP}
        report = {
            "generated_at": "2026-11-02T00:00:00+00:00", "holdout": "SYN.HK", "model": {"kappa": sp.DRIFT_KAPPA, "rung_probabilities": list(sp.RUNG_PROBABILITIES), "samples": bt.SAMPLES},
            "symbols": {"SYN.HK": {"from": "2017-07-14", "to": "2019-06-13", "days": 700}},
            "steps": {"holdout": 50, "basket": 50},
            "groups": {"holdout": {"symbols": ["SYN.HK"],
                                   "calibration": bt.summarize_calibration(bt.calibration_rows("SYN.HK", history, 20, (0.0, 0.2)), (0.0, 0.2), spans),
                                   "strategy": bt.summarize_strategy(bt.strategy_rows("SYN.HK", history, 200), spans)}},
        }
        report["groups"]["basket"] = report["groups"]["holdout"]
        with tempfile.TemporaryDirectory() as temp:
            bt.save(report, Path(temp))
            self.assertEqual(report["groups"]["holdout"]["symbols"], bt.load(Path(temp))["groups"]["holdout"]["symbols"])
            self.assertIsNone(bt.load(Path(temp) / "missing"))
        self.assertIn("SYN.HK", bt.markdown(report))


if __name__ == "__main__":
    unittest.main()
