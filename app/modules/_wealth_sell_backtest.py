"""Walk-forward backtest of the exit planner (ai_monitor.sell_plan) on full daily history.

Two studies, both using only data available at each start date:

* Calibration — at every start, for levels 0.25..2.5 horizon standard deviations above the close, the model's
  touch probability against whether the (dividend/split-adjusted) high actually reached the level within the
  horizon. Brier score, Brier skill against always predicting the base rate, and reliability buckets, with and
  without drift uncertainty (kappa). kappa is also re-estimated from the dispersion of realized returns on the
  basket and checked on the held-out symbol, so the model correction is validated out of sample.
* Strategy — at every start the full plan is built (recommended at-market sale + ladder, HK/US costs) for a
  target a fixed premium above the close and replayed on the real path: a rung fills at its limit on the first
  day from t+1 whose high reaches it (gap-ups fill at the limit, conservatively), the unfilled rest is sold at
  the close on the last day. Compared with selling everything now, a TWAP and a single limit at the target.

Windows overlap (one start every few days), so ``n_eff`` — the number of non-overlapping windows — is the
honest sample size; with it come normal-approximation intervals on hit rates.
"""

from __future__ import annotations

import json
import math
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Sequence

from . import _wealth_sell_plan as sp
from ._wealth_market import get_bytes

HOLDOUT = "3690.HK"
BASKET = ("0700.HK", "9988.HK", "1810.HK", "9618.HK", "0981.HK", "NVDA", "AAPL", "AMZN", "TSLA")
HORIZONS = (21, 63, 126, 252)
PREMIUMS = (0.05, 0.10, 0.20)
CAL_Z = (0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.5)
BUCKETS = (0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0001)
WARMUP = 260
SAMPLES = 1500
# Position replayed in the strategy study: the real holding for HK names, a similar notional for US ones.
POSITION = {"HK": (8500, 100), "US": (1000, 1)}
CACHE_DAYS = 7
RESULT_FILE = "sell_backtest.json"


# ---- data ---------------------------------------------------------------------------------------

def fetch_history(symbol: str) -> dict[str, list[float]]:
    """Full daily history since 2010 (``range=max`` would return monthly bars, so period1/period2)."""
    now = int(time.time())
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?period1=1262304000&period2={now}"
           "&interval=1d&events=div,splits")
    result = json.loads(get_bytes(url, timeout=30))["chart"]["result"][0]
    quote = result["indicators"]["quote"][0]
    adjusted = result["indicators"].get("adjclose", [{}])[0].get("adjclose") or quote["close"]
    rows = {"ts": [], "high": [], "close": []}
    for ts, high, close, adj in zip(result["timestamp"], quote["high"], quote["close"], adjusted):
        if not (high and close and adj) or high <= 0 or close <= 0:
            continue
        factor = adj / close
        rows["ts"].append(ts)
        rows["close"].append(adj)
        rows["high"].append(max(high, close) * factor)
    return rows


def load_histories(cache_dir: Path, symbols: Sequence[str], refresh: bool = False) -> dict[str, dict[str, list[float]]]:
    cache = cache_dir / "sell_backtest_history.json"
    stored: dict[str, Any] = {}
    if cache.exists():
        stored = json.loads(cache.read_text())
    fresh = time.time() - stored.get("fetched_at", 0) < CACHE_DAYS * 86400
    if refresh or not fresh or any(symbol not in stored.get("symbols", {}) for symbol in symbols):
        data = {symbol: fetch_history(symbol) for symbol in symbols}
        stored = {"fetched_at": time.time(), "symbols": data}
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(stored))
    return {symbol: stored["symbols"][symbol] for symbol in symbols}


def _market(symbol: str) -> str:
    return "HK" if symbol.endswith(".HK") else ""


# ---- per-symbol studies (run in worker processes) ------------------------------------------------

def _sigma(closes: Sequence[float], t: int) -> float | None:
    return sp.daily_volatility(closes[max(0, t - 600):t + 1])["daily"]


def calibration_rows(symbol: str, history: dict[str, list[float]], step: int, kappas: Sequence[float]) -> list[tuple]:
    """(symbol, horizon, z, predicted per kappa, hit, realized log return / (sigma*sqrt(h)))."""
    closes, highs = history["close"], history["high"]
    out = []
    for t in range(WARMUP, len(closes) - 1, step):
        sigma = _sigma(closes, t)
        if not sigma:
            continue
        for days in HORIZONS:
            if t + days >= len(closes):
                continue
            peak = max(highs[t + 1:t + days + 1])
            spread = sigma * math.sqrt(days)
            realized_z = math.log(closes[t + days] / closes[t]) / spread
            for z in CAL_Z:
                level = closes[t] * math.exp(z * spread)
                predicted = tuple(sp.touch_probability(closes[t], level, sigma, days, kappa) for kappa in kappas)
                out.append((symbol, days, z, predicted, peak >= level, realized_z))
    return out


def _fills(limits: Sequence[tuple[float, int]], highs: Sequence[float], t: int, days: int) -> list[int | None]:
    """First day offset (1..days) on which each limit's price was reached, or None."""
    result = []
    for level, _ in limits:
        day = next((offset for offset in range(1, days + 1) if highs[t + offset] >= level - 1e-9), None)
        result.append(day)
    return result


def _proceeds(orders: Sequence[tuple[float, int]], schedule: dict[str, float]) -> tuple[float, float]:
    gross = sum(price * shares for price, shares in orders)
    costs = sum(sp.order_cost(price, shares, schedule)["total"] for price, shares in orders if shares)
    return gross, costs


def strategy_rows(symbol: str, history: dict[str, list[float]], step: int) -> list[dict[str, Any]]:
    closes, highs = history["close"], history["high"]
    market = _market(symbol)
    schedule = sp.cost_schedule(market)
    shares, lot = POSITION["HK" if market == "HK" else "US"]
    out = []
    for t in range(WARMUP, len(closes) - 1, step):
        sigma = _sigma(closes, t)
        if not sigma:
            continue
        price = closes[t]
        for days in HORIZONS:
            if t + days >= len(closes):
                continue
            final = closes[t + days]
            peak = max(highs[t + 1:t + days + 1])
            now_orders = [(price, shares)]
            now_gross, now_costs = _proceeds(now_orders, schedule)
            # TWAP: equal lots at the close, one order per trading day (or per lot when lots run out first).
            lots = shares // lot
            orders = min(days, lots)
            per_order = [lots // orders + (1 if index < lots % orders else 0) for index in range(orders)]
            twap = [(closes[t + 1 + (index * days) // orders], count * lot) for index, count in enumerate(per_order)]
            twap_gross, twap_costs = _proceeds(twap, schedule)
            for premium in PREMIUMS:
                target = sp.round_to_tick(price * (1 + premium), market)
                plan = sp.build_plan(price=price, total_shares=shares, target_avg=target, sigma_daily=sigma, horizon_days=days,
                                     lot=lot, market=market, costs=schedule, explain=False, samples=SAMPLES)
                limits = [(row["price"], row["shares"]) for row in plan["ladder"] if row["kind"] == "limit"]
                fills = _fills(limits, highs, t, days)
                executed = [(price, plan["now_shares"])] if plan["now_shares"] else []
                executed += [(level, count) for (level, count), day in zip(limits, fills) if day is not None]
                unfilled = shares - sum(count for _, count in executed)
                if unfilled:
                    executed.append((final, unfilled))
                plan_gross, plan_costs = _proceeds(executed, schedule)
                single = [(target, shares)] if peak >= target else [(final, shares)]
                single_gross, single_costs = _proceeds(single, schedule)
                out.append({
                    "symbol": symbol, "t": t, "days": days, "premium": premium,
                    "predicted": plan["probability_target"],
                    "predicted_avg": plan["expected_avg"] / price,
                    "hit": plan_gross >= target * shares - 1e-6,
                    "plan": plan_gross / shares / price, "plan_net": (plan_gross - plan_costs) / shares / price,
                    "plan_cost_bps": plan_costs / plan_gross * 1e4, "orders": len(executed),
                    "now": now_gross / shares / price, "now_net": (now_gross - now_costs) / shares / price,
                    "twap": twap_gross / shares / price, "twap_net": (twap_gross - twap_costs) / shares / price,
                    "twap_hit": twap_gross >= target * shares - 1e-6,
                    "single": single_gross / shares / price, "single_net": (single_gross - single_costs) / shares / price,
                    "single_hit": peak >= target,
                    "rungs": [(row["touch_probability"], day) for row, day in zip(
                        (row for row in plan["ladder"] if row["kind"] == "limit"), fills)],
                })
    return out


def _symbol_job(args: tuple[str, dict[str, list[float]], int, tuple[float, ...]]) -> tuple[str, list, list]:
    symbol, history, step, kappas = args
    return symbol, calibration_rows(symbol, history, step, kappas), strategy_rows(symbol, history, step)


# ---- aggregation --------------------------------------------------------------------------------

def _n_eff(rows: Sequence[Any], days: int, spans: dict[str, int]) -> float:
    return sum(span / days for span in spans.values()) if rows else 0.0


def _interval(rate: float, n_eff: float) -> list[float]:
    if n_eff <= 0:
        return [0.0, 1.0]
    half = 1.96 * math.sqrt(max(rate * (1 - rate), 1e-6) / n_eff)
    return [max(0.0, rate - half), min(1.0, rate + half)]


def summarize_calibration(rows: Sequence[tuple], kappas: Sequence[float], spans: dict[str, int]) -> list[dict[str, Any]]:
    result = []
    for days in HORIZONS:
        subset = [row for row in rows if row[1] == days]
        if not subset:
            continue
        base = sum(row[4] for row in subset) / len(subset)
        climatology = base * (1 - base)
        entry: dict[str, Any] = {"days": days, "n": len(subset), "n_eff": _n_eff(subset, days, spans), "base_rate": base,
                                 "brier_climatology": climatology, "models": []}
        for index, kappa in enumerate(kappas):
            brier = sum((row[3][index] - row[4]) ** 2 for row in subset) / len(subset)
            buckets = []
            for low, high in zip(BUCKETS, BUCKETS[1:]):
                inside = [row for row in subset if low <= row[3][index] < high]
                if inside:
                    buckets.append({"low": low, "high": min(high, 1.0), "n": len(inside),
                                    "predicted": sum(row[3][index] for row in inside) / len(inside),
                                    "realized": sum(row[4] for row in inside) / len(inside)})
            entry["models"].append({"kappa": kappa, "brier": brier, "skill": 1 - brier / climatology if climatology else None,
                                    "buckets": buckets})
        # Dispersion of realized returns in units of the volatility-implied sd, de-meaned per symbol so a bull
        # market's drift does not count as dispersion. Plain GBM predicts 1; drift uncertainty 1 + kappa*h/252.
        squares, count = 0.0, 0
        for symbol in {row[0] for row in subset}:
            values = [row[5] for row in subset if row[0] == symbol and row[2] == CAL_Z[0]]
            mean = sum(values) / len(values)
            squares += sum((value - mean) ** 2 for value in values)
            count += len(values)
        entry["z_variance"] = squares / count
        entry["kappa_implied"] = (entry["z_variance"] - 1) * sp.TRADING_DAYS / days
        result.append(entry)
    return result


def summarize_strategy(rows: Sequence[dict[str, Any]], spans: dict[str, int]) -> list[dict[str, Any]]:
    result = []
    for days in HORIZONS:
        for premium in PREMIUMS:
            subset = [row for row in rows if row["days"] == days and row["premium"] == premium]
            if not subset:
                continue
            count = len(subset)
            n_eff = _n_eff(subset, days, spans)

            def mean(key: str) -> float:
                return sum(row[key] for row in subset) / count

            def p10(key: str) -> float:
                values = sorted(row[key] for row in subset)
                return values[int(0.1 * (count - 1))]

            hit = mean("hit")
            rung_pairs = [pair for row in subset for pair in row["rungs"]]
            rung_buckets = []
            for low, high in zip(BUCKETS, BUCKETS[1:]):
                inside = [pair for pair in rung_pairs if low <= pair[0] < high]
                if inside:
                    rung_buckets.append({"low": low, "high": min(high, 1.0), "n": len(inside),
                                         "predicted": sum(p for p, _ in inside) / len(inside),
                                         "realized": sum(day is not None for _, day in inside) / len(inside)})
            result.append({
                "days": days, "premium": premium, "n": count, "n_eff": n_eff,
                "predicted": mean("predicted"), "realized": hit, "realized_interval": _interval(hit, n_eff),
                "brier": sum((row["predicted"] - row["hit"]) ** 2 for row in subset) / count,
                "predicted_avg": mean("predicted_avg"),
                "strategies": {
                    name: {"avg": mean(name), "net": mean(f"{name}_net"), "p10_net": p10(f"{name}_net"),
                           "hit": mean(f"{name}_hit") if f"{name}_hit" in subset[0] else (mean("hit") if name == "plan" else 0.0)}
                    for name in ("plan", "now", "twap", "single")
                },
                "plan_cost_bps": mean("plan_cost_bps"), "plan_orders": mean("orders"),
                "rung_fill_buckets": rung_buckets,
            })
    return result


def run_backtest(
    data_dir: Path, *, symbols: Sequence[str] = (HOLDOUT, *BASKET), holdout: str = HOLDOUT, holdout_step: int = 5,
    basket_step: int = 10, refresh: bool = False, workers: int | None = None,
) -> dict[str, Any]:
    started = time.time()
    histories = load_histories(data_dir, symbols, refresh=refresh)
    kappas = (0.0, sp.DRIFT_KAPPA)
    jobs = [(symbol, histories[symbol], holdout_step if symbol == holdout else basket_step, kappas) for symbol in symbols]
    with ProcessPoolExecutor(max_workers=workers or min(len(jobs), 8)) as pool:
        results = list(pool.map(_symbol_job, jobs))
    spans = {symbol: max(0, len(histories[symbol]["close"]) - WARMUP) for symbol in symbols}
    groups = {"holdout": [holdout], "basket": [symbol for symbol in symbols if symbol != holdout]}
    report: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "model": {"kappa": sp.DRIFT_KAPPA, "rung_probabilities": list(sp.RUNG_PROBABILITIES), "samples": SAMPLES},
        "symbols": {symbol: {"from": datetime.fromtimestamp(histories[symbol]["ts"][0], UTC).date().isoformat(),
                             "to": datetime.fromtimestamp(histories[symbol]["ts"][-1], UTC).date().isoformat(),
                             "days": len(histories[symbol]["close"])} for symbol in symbols},
        "steps": {"holdout": holdout_step, "basket": basket_step},
        "holdout": holdout,
        "groups": {},
    }
    for name, members in groups.items():
        calibration = [row for symbol, cal, _ in results if symbol in members for row in cal]
        strategy = [row for symbol, _, rows in results if symbol in members for row in rows]
        member_spans = {symbol: spans[symbol] for symbol in members}
        report["groups"][name] = {
            "symbols": members,
            "calibration": summarize_calibration(calibration, kappas, member_spans),
            "strategy": summarize_strategy(strategy, member_spans),
        }
    report["elapsed_seconds"] = round(time.time() - started, 1)
    return report


def save(report: dict[str, Any], data_dir: Path) -> Path:
    path = data_dir / RESULT_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=1))
    return path


def load(data_dir: Path) -> dict[str, Any] | None:
    path = data_dir / RESULT_FILE
    return json.loads(path.read_text()) if path.exists() else None


# ---- report -------------------------------------------------------------------------------------

def _p(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.1f}%"


def markdown(report: dict[str, Any]) -> str:
    lines = [
        "# 减持方案回测报告", "",
        f"生成时间：{report['generated_at']}　模型：零漂移 GBM + 漂移不确定性 κ={report['model']['kappa']}　"
        f"每次方案蒙特卡洛 {report['model']['samples']} 条路径", "",
        "数据：Yahoo 日线（复权），每个起点只用当时及以前的数据估计波动率。窗口相互重叠，"
        "n_eff 为不重叠窗口数，区间按 n_eff 计算的 95% 正态近似。", "",
        "| 标的 | 起 | 止 | 交易日 |", "|---|---|---|---|",
    ]
    for symbol, meta in report["symbols"].items():
        lines.append(f"| {symbol} | {meta['from']} | {meta['to']} | {meta['days']} |")
    for name, title in (("holdout", f"样本外：{report['holdout']}"), ("basket", "一篮子（κ 的估计集）")):
        group = report["groups"][name]
        lines += ["", f"## {title}", "", "### 1. 触及概率校准", "",
                  "| 期限 | 样本 | n_eff | 基准率 | Brier κ=0 | Brier κ=0.2 | 技能分 κ=0.2 | 隐含 κ |", "|---|---|---|---|---|---|---|---|"]
        for row in group["calibration"]:
            plain, mixed = row["models"]
            lines.append(f"| {row['days']} 日 | {row['n']} | {row['n_eff']:.0f} | {_p(row['base_rate'])} | {plain['brier']:.4f} | "
                         f"{mixed['brier']:.4f} | {mixed['skill']:.3f} | {row['kappa_implied']:.2f} |")
        lines += ["", "可靠性（κ=0.2，预测概率分桶 → 实际触及率（样本数））：", ""]
        for row in group["calibration"]:
            buckets = "；".join(f"{b['predicted'] * 100:.0f}%→{b['realized'] * 100:.0f}%（{b['n']}）" for b in row["models"][1]["buckets"])
            lines.append(f"- {row['days']} 日：{buckets}")
        lines += ["", "### 2. 方案回放（推荐现价卖出 + 阶梯 + 费用）", "",
                  "| 期限 | 目标溢价 | n_eff | 预测达标率 | 实际达标率（95% 区间） | Brier | 单一限价达标率 | 模型期望均价 | 方案毛/净均价 | 现在全卖 | TWAP | 单一限价 | P10：方案 / 单一限价 / TWAP | 费用 bp |",
                  "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for row in group["strategy"]:
            s = row["strategies"]
            low, high = row["realized_interval"]
            lines.append(
                f"| {row['days']} 日 | +{row['premium'] * 100:.0f}% | {row['n_eff']:.0f} | {_p(row['predicted'])} | "
                f"{_p(row['realized'])}（{_p(low)}–{_p(high)}） | {row['brier']:.3f} | {_p(s['single']['hit'])} | {row['predicted_avg']:.4f} | "
                f"{s['plan']['avg']:.4f} / {s['plan']['net']:.4f} | {s['now']['net']:.4f} | {s['twap']['net']:.4f} | {s['single']['net']:.4f} | "
                f"{s['plan']['p10_net']:.3f} / {s['single']['p10_net']:.3f} / {s['twap']['p10_net']:.3f} | {row['plan_cost_bps']:.1f} |")
        lines += ["", "均价以起点收盘价为 1 表示；除「方案毛均价」外都是扣除佣金、平台费、印花税等全部费用后的净值。"
                  "「现在全卖」的 P10 恒为 1 减费用，故不列。", ""]
    lines += [
        "## 读法与局限", "",
        "- 预测达标率与实际达标率接近、落在区间内，说明概率可以按字面理解；Brier 技能分 > 0 表示好于只报基准率。",
        "- 单一限价（全部挂在目标价）达标率总是最高，但没成交时整笔按到期价卖出，P10 最差；阶梯用一部分达标率换更好的最差情形。",
        "- 任何挂单方式的期望均价都不显著优于现在全卖：均价差异主要来自样本期的涨跌趋势（一篮子是牛市），不是方案本身创造的。",
        "- 21 日的「隐含 κ」主要反映短期波动率估计误差，不代表漂移；κ 以 252 日为准。",
        "- 一篮子含美股牛市样本（含幸存者偏差），实际触及率偏高属预期，因此 κ 只从收益离散度估计，不从命中率拟合。",
        "- 成交假设：日内最高价触及即按限价全部成交，跳空高开也按限价（保守），不计排队与流动性；碎股不单独计。",
        "- 美团独立的 1 年窗口只有约 7 个，长期限结论的不确定性大，看区间而不是点估计。",
    ]
    return "\n".join(lines) + "\n"
