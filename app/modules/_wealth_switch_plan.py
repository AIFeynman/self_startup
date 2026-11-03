"""Hold or switch: after-tax wealth at the end of a comparison period when the remaining shares are kept,
sold now, sold in stages or sold on the GTC limit ladder, with every sale's proceeds moved into QQQ.

Model: the stock follows sell_plan's GBM with drift uncertainty (kappa, linear beyond a year), around a user-set expected annual
return (default 0: no view). QQQ follows its own GBM with drift uncertainty around an assumed return (default
8%, below its 13-20% trailing CAGRs on purpose), with volatility and correlation to the stock measured from
weekly history. Paths are simulated jointly on a grid of STEP trading days; within each step the stock's
maximum is drawn exactly from the Brownian bridge, so a limit order fills at its price in the first step whose
high reaches it and the cash buys QQQ at the end of that step.

Taxes and costs: each stock sale pays HK selling costs (sell_plan's linear schedule) and ``rate`` on the part
of the price above ``threshold``, per share. Moving into QQQ costs SWITCH_COST_RATE on the way in (conversion
and commission) and again on the way out. At the end everything is valued as if liquidated: unsold shares at
the final price less costs and tax, QQQ less costs and ``switch_rate`` on its net gain over the amount put in.
HKD is treated as pegged to USD. Pure standard library, deterministic for a given input.

Wealth is linear in the shares given to each sale except for the QQQ tax (taxed on the net gain), so every path
is reduced to per-share contributions once and each strategy — including every switch fraction — is a cheap
weighted sum over them.
"""

from __future__ import annotations

import bisect
import math
import random
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, datetime
from typing import Any, Sequence

from . import _wealth_sell_plan as sp

COMPARE_DAYS = (252, 756, 1260)
DEFAULT_COMPARE_DAYS = 756
DEFAULT_ASSUMPTIONS = {"qqq_return": 0.08, "qqq_sigma": 0.226, "correlation": 0.27, "stock_return": 0.0}
# Sale tax above a price threshold (user-provided: 20% on the part above 100) and the same rate on QQQ gains.
# Overridden per position by a "tax" object in positions.json.
DEFAULT_TAX = {"threshold": 100.0, "rate": 0.2, "switch_rate": 0.2}
SWITCH_COST_RATE = 0.0005
SWITCH_SYMBOL = "QQQ"
# Historical replay: the holdout (sell_backtest.HOLDOUT) and the Hong Kong names of the backtest basket.
REPLAY_BASKET = ("0700.HK", "9988.HK", "1810.HK", "9618.HK", "0981.HK")
RESULT_FILE = "switch_backtest.json"
FRACTIONS = tuple(step / 10 for step in range(11))
QQQ_SENSITIVITY = (0.0, 0.08, 0.13, 0.20)
SAMPLES = 2500
SEED = 20261103
STEP = 12
# Staged switching: equal market sales at these trading days.
STAGES = {"quarterly": (63, 126, 189, 252), "monthly": tuple(21 * month for month in range(1, 13))}
STRATEGY_LABELS = {
    "hold": "全部持有到期末", "switch_now": "现在全部换 QQQ", "switch_quarterly": "分 4 个季度换 QQQ",
    "switch_monthly": "分 12 个月换 QQQ", "plan": "当前方案（现卖 + 限价挂单，成交即换 QQQ）",
}


def tax_settings(overrides: dict[str, Any] | None = None) -> dict[str, float]:
    settings = dict(DEFAULT_TAX)
    for name, value in (overrides or {}).items():
        if name in settings and isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
            settings[name] = float(value)
    return settings


# ---- assumptions from history -------------------------------------------------------------------

def weekly_closes(history: dict[str, list[float]]) -> dict[tuple[int, int], float]:
    weeks: dict[tuple[int, int], float] = {}
    for ts, close in zip(history["ts"], history["close"]):
        weeks[tuple(datetime.fromtimestamp(ts, UTC).isocalendar()[:2])] = close
    return weeks


def estimate_assumptions(stock: dict[str, list[float]] | None, qqq: dict[str, list[float]] | None, years: int = 5) -> dict[str, Any]:
    """QQQ volatility, its correlation with the stock (weekly log returns over ``years``) and trailing CAGRs."""
    result: dict[str, Any] = dict(DEFAULT_ASSUMPTIONS, source="default")
    if not qqq or len(qqq["close"]) < 300:
        return result
    q_weeks = weekly_closes(qqq)
    keys = sorted(q_weeks)[-52 * years - 1:]
    q_returns = [math.log(q_weeks[b] / q_weeks[a]) for a, b in zip(keys, keys[1:])]
    mean = sum(q_returns) / len(q_returns)
    result["qqq_sigma"] = math.sqrt(sum((x - mean) ** 2 for x in q_returns) / (len(q_returns) - 1) * 52)
    closes, stamps = qqq["close"], qqq["ts"]
    result["qqq_cagr"] = {}
    for span in (5, 10, 15):
        start = bisect.bisect_left(stamps, stamps[-1] - span * 365.25 * 86400)
        if start > 0:
            result["qqq_cagr"][str(span)] = (closes[-1] / closes[start]) ** (1 / span) - 1
    result["source"] = "history"
    if stock:
        s_weeks = weekly_closes(stock)
        common = [key for key in keys if key in s_weeks]
        pairs = [(math.log(s_weeks[b] / s_weeks[a]), math.log(q_weeks[b] / q_weeks[a])) for a, b in zip(common, common[1:])]
        if len(pairs) > 50:
            mx = sum(x for x, _ in pairs) / len(pairs)
            my = sum(y for _, y in pairs) / len(pairs)
            cov = sum((x - mx) * (y - my) for x, y in pairs)
            result["correlation"] = cov / math.sqrt(sum((x - mx) ** 2 for x, _ in pairs) * sum((y - my) ** 2 for _, y in pairs))
        result["stock_cagr_since_listing"] = (stock["close"][-1] / stock["close"][0]) ** (365.25 * 86400 / (stock["ts"][-1] - stock["ts"][0])) - 1
    result["weeks"] = len(q_returns)
    return result


# ---- simulation ---------------------------------------------------------------------------------

def grid_for(days: int, step: int = STEP) -> list[int]:
    return list(range(step, days, step)) + [days]


def simulate(
    price: float, sigma_daily: float, days: int, *, qqq_sigma: float, correlation: float, stock_return: float = 0.0,
    qqq_return: float = DEFAULT_ASSUMPTIONS["qqq_return"], kappa: float = sp.DRIFT_KAPPA, samples: int = SAMPLES,
    seed: int = SEED, step: int = STEP, keep: Sequence[int] = (),
) -> dict[str, Any]:
    """Joint paths: per path the running maximum of the stock after each step (``peaks``), QQQ relative to its
    start (``qqq``, one per step), the stock at the grid indices in ``keep`` and at the end."""
    grid = grid_for(days, step)
    rng = random.Random(seed)
    q_daily = qqq_sigma / math.sqrt(sp.TRADING_DAYS)
    s_center, s_tau = sp._drift_center(sigma_daily, days, kappa, stock_return), sp.drift_spread(sigma_daily, kappa, days)
    q_center, q_tau = sp._drift_center(q_daily, days, kappa, qqq_return), sp.drift_spread(q_daily, kappa, days)
    rho = max(-0.99, min(0.99, correlation))
    rest = math.sqrt(1 - rho * rho)
    steps = [(t - s, math.sqrt(t - s)) for s, t in zip([0] + grid[:-1], grid)]
    keep_set = set(keep)
    log_price = math.log(price)
    paths = []
    for _ in range(samples):
        z = rng.gauss(0.0, 1.0)
        s_mu = s_center + s_tau * z
        q_mu = q_center + q_tau * (rho * z + rest * rng.gauss(0.0, 1.0))
        x = y = 0.0
        peak = 0.0
        peaks, qqq, kept = [], [], {}
        for index, (dt, root) in enumerate(steps):
            e1 = rng.gauss(0.0, 1.0)
            x1 = x + s_mu * dt + sigma_daily * root * e1
            y += q_mu * dt + q_daily * root * (rho * e1 + rest * rng.gauss(0.0, 1.0))
            top = 0.5 * (x + x1 + math.sqrt((x1 - x) ** 2 - 2 * sigma_daily * sigma_daily * dt * math.log(1.0 - rng.random())))
            peak = max(peak, top)
            x = x1
            peaks.append(math.exp(log_price + peak))
            qqq.append(math.exp(y))
            if index in keep_set:
                kept[index] = price * math.exp(x)
        paths.append({"peaks": peaks, "qqq": qqq, "kept": kept, "final": price * math.exp(x)})
    return {"grid": grid, "paths": paths, "days": days}


# ---- strategies ---------------------------------------------------------------------------------

def stage_indices(grid: Sequence[int], days_list: Sequence[int]) -> list[int]:
    """Grid index closest to each stage day (stages past the period are dropped)."""
    return [min(range(len(grid)), key=lambda i: abs(grid[i] - day)) for day in days_list if day < grid[-1]]


def split_shares(total: int, parts: int, lot: int) -> list[int]:
    if parts <= 0 or total <= 0:
        return []
    base = (total // parts) // lot * lot
    shares = [base] * parts
    shares[-1] += total - base * parts
    return shares


def scale_ladder(rungs: Sequence[tuple[float, int]], shares: int, lot: int) -> list[tuple[float, int]]:
    """The plan's limit prices with ``shares`` spread in the plan's proportions (lot-rounded, rest on the top)."""
    planned = sum(n for _, n in rungs)
    if not rungs or not planned or shares <= 0:
        return []
    out = [(level, int(n * shares / planned) // lot * lot) for level, n in rungs]
    out[-1] = (out[-1][0], out[-1][1] + shares - sum(n for _, n in out))
    return [(level, n) for level, n in out if n > 0]


def strategies(remaining: int, lot: int, plan_now: int, rungs: Sequence[tuple[float, int]], grid: Sequence[int]) -> dict[str, dict[str, Any]]:
    """Each strategy as {"now": shares, "staged": [(grid index, shares)], "rungs": [(level, shares)]}; the rest is held."""
    out: dict[str, dict[str, Any]] = {
        "hold": {"now": 0, "staged": [], "rungs": []},
        "switch_now": {"now": remaining, "staged": [], "rungs": []},
    }
    for name, days in STAGES.items():
        indices = stage_indices(grid, days)
        if indices:
            out[f"switch_{name}"] = {"now": 0, "staged": list(zip(indices, split_shares(remaining, len(indices), lot))), "rungs": []}
    out["plan"] = {"now": plan_now, "staged": [], "rungs": list(rungs)}
    for fraction in FRACTIONS:
        now = min(remaining, round(remaining * fraction / lot) * lot)
        out[f"hold_{fraction:.1f}"] = {"now": now, "staged": [], "rungs": [], "fraction": fraction, "rest": "hold"}
        if rungs:
            out[f"ladder_{fraction:.1f}"] = {"now": now, "staged": [], "rungs": scale_ladder(rungs, remaining - now, lot),
                                             "fraction": fraction, "rest": "ladder"}
    return out


def _quantile(sorted_values: Sequence[float], share: float) -> float:
    return sorted_values[min(len(sorted_values) - 1, max(0, int(share * len(sorted_values))))]


def evaluate(
    sim: dict[str, Any], specs: dict[str, dict[str, Any]], *, price: float, remaining: int, costs: dict[str, float],
    tax: dict[str, float], switch_cost: float = SWITCH_COST_RATE, qqq_shift: float = 0.0, stock_shift: float = 0.0,
    total_shares: int | None = None, sold_proceeds: float = 0.0, target_avg: float | None = None,
) -> dict[str, list[float] | dict[str, Any]]:
    """Per-path after-tax wealth for each strategy. ``qqq_shift``/``stock_shift`` add to the annual drift the
    paths were simulated with (QQQ by rescaling its paths; the stock only for strategies without limit orders,
    whose fills would move). Also the fraction of paths whose gross average sale price reaches ``target_avg``."""
    fixed, rate = sp._linear_cost(costs)
    threshold, sale_tax, gain_tax = tax["threshold"], tax["rate"], tax["switch_rate"]
    grid, days = sim["grid"], sim["days"]
    keep = (1 - switch_cost) ** 2

    def net(p: float) -> float:
        return p * (1 - rate) - sale_tax * max(0.0, p - threshold)

    def growth(index: int | None) -> float:
        start = 0 if index is None else grid[index]
        return math.exp((qqq_shift / sp.TRADING_DAYS) * (days - start))

    levels = sorted({level for spec in specs.values() for level, _ in spec["rungs"]})
    if stock_shift and levels:
        raise ValueError("stock_shift is only supported for strategies without limit orders")
    level_net = {level: net(level) for level in levels}
    now_net = net(price)
    wealth: dict[str, list[float]] = {name: [] for name in specs}
    hits: dict[str, int] = {name: 0 for name in specs}
    filled: dict[str, float] = {name: 0.0 for name in specs}
    total_shares = total_shares or remaining
    for path in sim["paths"]:
        qqq, peaks = path["qqq"], path["peaks"]
        final_q = qqq[-1]
        drift = math.exp(stock_shift / sp.TRADING_DAYS * days) if stock_shift else 1.0
        final = path["final"] * drift
        held_net = net(final)
        fills = {level: bisect.bisect_left(peaks, level) for level in levels}
        for name, spec in specs.items():
            value = gain = gross = 0.0
            orders = 0
            held = remaining
            if spec["now"]:
                multiple = keep * final_q * growth(None)
                value += spec["now"] * now_net * multiple
                gain += spec["now"] * now_net * (multiple - 1)
                gross += spec["now"] * price
                held -= spec["now"]
                orders += 1
            for index, shares in spec["staged"]:
                stage_price = path["kept"][index] * (math.exp(stock_shift / sp.TRADING_DAYS * grid[index]) if stock_shift else 1.0)
                contribution = shares * net(stage_price)
                multiple = keep * final_q / qqq[index] * growth(index)
                value += contribution * multiple
                gain += contribution * (multiple - 1)
                gross += shares * stage_price
                held -= shares
                orders += 1
            for level, shares in spec["rungs"]:
                index = fills[level]
                if index < len(peaks):
                    multiple = keep * final_q / qqq[index] * growth(index)
                    value += shares * level_net[level] * multiple
                    gain += shares * level_net[level] * (multiple - 1)
                    gross += shares * level
                    held -= shares
                    orders += 1
                    filled[name] += shares
            result = value - gain_tax * max(0.0, gain) + held * held_net - fixed * (orders + (1 if held else 0))
            wealth[name].append(result)
            if target_avg is not None and (sold_proceeds + gross + held * final) / total_shares >= target_avg - 1e-9:
                hits[name] += 1
    count = len(sim["paths"])
    return {"wealth": wealth, "target": {name: hits[name] / count for name in specs},
            "filled": {name: filled[name] / count for name in specs}}


def summarize(values: Sequence[float], base: float, days: int, *, hold: Sequence[float], switch: Sequence[float]) -> dict[str, Any]:
    ordered = sorted(values)
    mean = sum(values) / len(values)
    median = _quantile(ordered, 0.5)
    years = days / sp.TRADING_DAYS
    return {
        "mean": mean, "p10": _quantile(ordered, 0.1), "p50": median, "p90": _quantile(ordered, 0.9),
        "mean_ratio": mean / base, "median_ratio": median / base, "p10_ratio": _quantile(ordered, 0.1) / base,
        "median_cagr": (median / base) ** (1 / years) - 1 if median > 0 else None,
        "beats_hold": sum(a > b + 1e-6 for a, b in zip(values, hold)) / len(values),
        "beats_switch": sum(a > b + 1e-6 for a, b in zip(values, switch)) / len(values),
    }


def break_even_return(sim: dict[str, Any], *, price: float, remaining: int, costs: dict[str, float], tax: dict[str, float],
                      qqq_shift: float = 0.0, statistic: str = "mean") -> float | None:
    """The stock's expected annual return (added to the simulated one) at which holding everything ties with
    switching everything now on ``statistic`` (mean or median) of after-tax wealth."""
    specs = {"hold": {"now": 0, "staged": [], "rungs": []}, "switch_now": {"now": remaining, "staged": [], "rungs": []}}

    def gap(shift: float) -> float:
        result = evaluate(sim, specs, price=price, remaining=remaining, costs=costs, tax=tax, qqq_shift=qqq_shift, stock_shift=shift)["wealth"]
        if statistic == "median":
            return _quantile(sorted(result["hold"]), 0.5) - _quantile(sorted(result["switch_now"]), 0.5)
        return sum(result["hold"]) / len(result["hold"]) - sum(result["switch_now"]) / len(result["switch_now"])

    low, high = -0.5, 1.5
    if gap(low) > 0 or gap(high) < 0:
        return None
    for _ in range(30):
        middle = (low + high) / 2
        if gap(middle) > 0:
            high = middle
        else:
            low = middle
    return (low + high) / 2


def compare(
    *, price: float, sigma_daily: float, remaining: int, lot: int, plan_now: int, rungs: Sequence[tuple[float, int]],
    costs: dict[str, float], tax: dict[str, float], days: int = DEFAULT_COMPARE_DAYS, assumptions: dict[str, Any] | None = None,
    total_shares: int | None = None, sold_proceeds: float = 0.0, target_avg: float | None = None, samples: int = SAMPLES,
    kappa: float = sp.DRIFT_KAPPA, name: str = "该股", detail: bool = True,
) -> dict[str, Any]:
    """The full hold-or-switch comparison for the dashboard; ``detail=False`` (backtests) skips the QQQ
    sensitivity, the break-even search and the written reasoning."""
    started = time.time()
    a = dict(DEFAULT_ASSUMPTIONS, **{key: value for key, value in (assumptions or {}).items() if value is not None})
    grid = grid_for(days)
    keep = sorted({index for stage in STAGES.values() for index in stage_indices(grid, stage)})
    sim = simulate(price, sigma_daily, days, qqq_sigma=a["qqq_sigma"], correlation=a["correlation"], stock_return=a["stock_return"],
                   qqq_return=a["qqq_return"], kappa=kappa, samples=samples, keep=keep)
    specs = strategies(remaining, lot, plan_now, rungs, grid)
    common = dict(price=price, remaining=remaining, costs=costs, tax=tax)
    result = evaluate(sim, specs, total_shares=total_shares, sold_proceeds=sold_proceeds, target_avg=target_avg, **common)
    wealth = result["wealth"]
    fixed, rate = sp._linear_cost(costs)
    base = remaining * (price * (1 - rate) - tax["rate"] * max(0.0, price - tax["threshold"])) - fixed
    stats = {name: summarize(values, base, days, hold=wealth["hold"], switch=wealth["switch_now"])
             | {"target_probability": result["target"][name], "expected_filled_shares": result["filled"][name]}
             for name, values in wealth.items()}
    named = [{"key": key, "label": STRATEGY_LABELS[key], **stats[key]} for key in STRATEGY_LABELS if key in stats]
    sweep = [{"fraction": spec["fraction"], "rest": spec["rest"], "now_shares": spec["now"], **stats[name]}
             for name, spec in specs.items() if "fraction" in spec]

    def best(metric: str) -> dict[str, Any]:
        row = max(sweep, key=lambda item: (round(item[metric], 2), item["fraction"]))
        return {"metric": metric, "fraction": row["fraction"], "rest": row["rest"], "value": row[metric]}

    report = {
        "days": days, "years": days / sp.TRADING_DAYS, "assumptions": a, "tax": tax, "switch_cost_rate": SWITCH_COST_RATE,
        "samples": samples, "step_days": STEP, "base_value": base, "remaining_shares": remaining,
        "strategies": named, "sweep": sweep,
        "optimal": {"mean": best("mean_ratio"), "median": best("median_ratio"), "p10": best("p10_ratio")},
    }
    if not detail:
        return report

    def break_even(**options: Any) -> float | None:
        found = break_even_return(sim, **common, **options)
        return None if found is None else found + a["stock_return"]

    sensitivity = []
    returns = sorted(set(QQQ_SENSITIVITY) | {round(a["qqq_return"], 4)})
    keys = ["hold", "switch_now", "plan"] + [name for name in specs if name.startswith("hold_")]
    subset = {name: specs[name] for name in keys}
    for qqq_return in returns:
        shift = qqq_return - a["qqq_return"]
        values = evaluate(sim, subset, qqq_shift=shift, **common)["wealth"] if shift else {name: wealth[name] for name in keys}
        means = {name: sum(v) / len(v) / base for name, v in values.items()}
        medians = {name: _quantile(sorted(v), 0.5) / base for name, v in values.items()}
        fraction_best = max((specs[name]["fraction"] for name in keys if name.startswith("hold_")),
                            key=lambda f: (round(medians[f"hold_{f:.1f}"], 3), f))
        sensitivity.append({
            "qqq_return": qqq_return, "current": abs(shift) < 1e-9,
            "mean_ratio": {name: means[name] for name in ("hold", "switch_now", "plan")},
            "median_ratio": {name: medians[name] for name in ("hold", "switch_now", "plan")},
            "best_fraction_median": fraction_best,
            "break_even": break_even(qqq_shift=shift),
        })
    report["break_even"] = {"mean": break_even(), "median": break_even(statistic="median")}
    report["sensitivity"] = sensitivity
    report["reasons"] = explain(report, name)
    report["elapsed_seconds"] = round(time.time() - started, 2)
    return report


def _pct(value: float | None, digits: int = 1) -> str:
    return "—" if value is None else f"{value * 100:.{digits}f}%"


def explain(report: dict[str, Any], name: str = "该股") -> list[str]:
    a, years = report["assumptions"], report["years"]
    rows = {row["key"]: row for row in report["strategies"]}
    hold, switch, plan = rows["hold"], rows["switch_now"], rows.get("plan")
    lines = [
        f"比较期 {years:.0f} 年：按{name}预期年化 {_pct(a['stock_return'])}（无方向观点）、QQQ 预期年化 {_pct(a['qqq_return'])}、"
        f"QQQ 波动 {_pct(a['qqq_sigma'])}、两者相关 {a['correlation']:.2f}，税后财富中位数："
        f"全部持有 {hold['median_ratio']:.2f} 倍，现在全换 {switch['median_ratio']:.2f} 倍"
        + (f"，当前方案 {plan['median_ratio']:.2f} 倍" if plan else "") + "（以现在全部卖出的税后到手为 1 倍）。",
        f"现在全换在 {_pct(switch['beats_hold'], 0)} 的路径上胜过全部持有；持有的下行更深："
        f"P10 {hold['p10_ratio']:.2f} 倍 vs 全换 {switch['p10_ratio']:.2f} 倍。",
    ]
    be = report["break_even"]
    if be["mean"] is not None:
        listed = a.get("stock_cagr_since_listing")
        lines.append(f"{name}要年化 {_pct(be['mean'])} 才能在平均值上和换 QQQ 打平，按中位数需要 {_pct(be['median'])}"
                     + (f"；作为参照，{name}上市以来年化 {_pct(listed)}" if listed is not None else "") + "。")
    optimal = report["optimal"]
    picks = {key: f"{optimal[key]['fraction'] * 100:.0f}%" for key in ("median", "p10", "mean")}
    if len(set(picks.values())) == 1:
        head = f"换仓比例：中位数、P10（坏情况）和均值三个口径都指向现在换 {picks['median']}"
    else:
        head = f"换仓比例：按中位数最优是现在换 {picks['median']}，按 P10（坏情况）{picks['p10']}，按均值 {picks['mean']}"
    lines.append(head + "；预期收益不同的两种资产之间，财富对比例近似线性，最优点通常在端点，中间比例是在分摊风险和后悔。")
    staged = rows.get("switch_monthly")
    if staged:
        lines.append(f"时机：分 12 个月换的中位数 {staged['median_ratio']:.2f} 倍、比现在全换的胜率 {_pct(staged['beats_switch'], 0)}——"
                     f"推迟换仓等于在推迟期间继续持有{name}，只有认为它短期更强时才有利。")
    lines.append("税的影响：卖出价超过门槛的部分按比例计税，QQQ 期末按净收益计税；持有到期末的部分按期末价扣税费估值。"
                 "这些都是模型假设下的统计估算，不构成投资建议。")
    return lines


# ---- historical replay --------------------------------------------------------------------------

def align(stock: dict[str, list[float]], other: dict[str, list[float]]) -> list[float | None]:
    """``other``'s last close at or before each of ``stock``'s timestamps."""
    out = []
    for ts in stock["ts"]:
        index = bisect.bisect_right(other["ts"], ts) - 1
        out.append(other["close"][index] if index >= 0 else None)
    return out


def replay_rows(symbol: str, stock: dict[str, list[float]], qqq: dict[str, list[float]], *, days_list: Sequence[int] = COMPARE_DAYS,
                step: int = 21, threshold_ratio: float, target_ratio: float, warmup: int = 260, samples: int = 400,
                assumptions: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """At each start: the plan built for a target ``target_ratio`` x the close, the tax threshold at
    ``threshold_ratio`` x the close, then every strategy replayed on the real stock and QQQ paths. Also the
    model's own prediction at that start (its P(switch beats hold) and median ratios) for calibration."""
    closes, highs = stock["close"], stock["high"]
    q = align(stock, qqq)
    market = "HK" if symbol.endswith(".HK") else ""
    costs = sp.cost_schedule(market)
    fixed, rate = sp._linear_cost(costs)
    shares, lot = (8500, 100) if market == "HK" else (1000, 1)
    a = dict(DEFAULT_ASSUMPTIONS, **(assumptions or {}))
    keep = (1 - SWITCH_COST_RATE) ** 2
    rows = []
    for t in range(warmup, len(closes), step):
        if q[t] is None:
            continue
        sigma = sp.daily_volatility(closes[max(0, t - 600):t + 1])["daily"]
        if not sigma:
            continue
        price = closes[t]
        tax = dict(DEFAULT_TAX, threshold=price * threshold_ratio)
        for days in days_list:
            end = t + days
            if end >= len(closes) or q[end] is None:
                continue
            plan = sp.build_plan(price=price, total_shares=shares, target_avg=price * target_ratio, sigma_daily=sigma,
                                 horizon_days=days, lot=lot, market=market, costs=costs, samples=samples, explain=False)
            rungs = [(row["price"], row["shares"]) for row in plan["ladder"] if row["kind"] == "limit"]

            def net(p: float) -> float:
                return p * (1 - rate) - tax["rate"] * max(0.0, p - tax["threshold"])

            def wealth(sales: Sequence[tuple[int, float, int]]) -> float:
                """sales: (day offset, price, shares) moved into QQQ at that day's close."""
                value = gain = 0.0
                held = shares
                for offset, p, n in sales:
                    multiple = keep * q[end] / q[t + offset]
                    value += n * net(p) * multiple
                    gain += n * net(p) * (multiple - 1)
                    held -= n
                return value - tax["switch_rate"] * max(0.0, gain) + held * net(closes[end]) - fixed * (len(sales) + (1 if held else 0))

            base = shares * net(price) - fixed
            realized = {"hold": wealth([]), "switch_now": wealth([(0, price, shares)])}
            for name, stage_days in STAGES.items():
                points = [d for d in stage_days if d < days]
                realized[f"switch_{name}"] = wealth([(d, closes[t + d], n) for d, n in zip(points, split_shares(shares, len(points), lot))])
            sales = [(0, price, plan["now_shares"])] if plan["now_shares"] else []
            for level, n in rungs:
                day = next((offset for offset in range(1, days + 1) if highs[t + offset] >= level - 1e-9), None)
                if day is not None:
                    sales.append((day, level, n))
            realized["plan"] = wealth(sales)
            model = compare(price=price, sigma_daily=sigma, remaining=shares, lot=lot, plan_now=plan["now_shares"], rungs=rungs,
                            costs=costs, tax=tax, days=days, assumptions=a, samples=samples, detail=False)
            predicted = {row["key"]: row for row in model["strategies"]}
            rows.append({
                "symbol": symbol, "start": stock["ts"][t], "days": days,
                "realized": {name: value / base for name, value in realized.items()},
                "predicted_median": {name: row["median_ratio"] for name, row in predicted.items()},
                "predicted_switch_beats_hold": predicted["switch_now"]["beats_hold"],
                "stock_cagr": (closes[end] / price) ** (sp.TRADING_DAYS / days) - 1,
                "qqq_cagr": (q[end] / q[t]) ** (sp.TRADING_DAYS / days) - 1,
            })
    return rows


def _replay_job(args: tuple) -> list[dict[str, Any]]:
    symbol, stock, qqq, kwargs = args
    return replay_rows(symbol, stock, qqq, **kwargs)


def summarize_replay(rows: Sequence[dict[str, Any]], spans: dict[str, int]) -> list[dict[str, Any]]:
    out = []
    for days in sorted({row["days"] for row in rows}):
        group = [row for row in rows if row["days"] == days]
        if not group:
            continue
        names = list(group[0]["realized"])
        n_eff = sum(max(1.0, (spans[s] - days) / days) for s in {row["symbol"] for row in group} if spans.get(s, 0) > days)
        out.append({
            "days": days, "windows": len(group), "n_eff": round(n_eff, 1),
            "realized_median": {name: _quantile(sorted(row["realized"][name] for row in group), 0.5) for name in names},
            "realized_mean": {name: sum(row["realized"][name] for row in group) / len(group) for name in names},
            "predicted_median": {name: sum(row["predicted_median"][name] for row in group) / len(group) for name in names},
            "switch_beats_hold": {"predicted": sum(row["predicted_switch_beats_hold"] for row in group) / len(group),
                                  "realized": sum(row["realized"]["switch_now"] > row["realized"]["hold"] for row in group) / len(group)},
            "stock_cagr_median": _quantile(sorted(row["stock_cagr"] for row in group), 0.5),
            "qqq_cagr_median": _quantile(sorted(row["qqq_cagr"] for row in group), 0.5),
        })
    return out


def run_replay(histories: dict[str, dict[str, list[float]]], qqq: dict[str, list[float]], symbols: Sequence[str], groups: dict[str, list[str]], *,
               threshold_ratio: float, target_ratio: float, workers: int | None = None, step: int = 21) -> dict[str, Any]:
    started = time.time()
    kwargs = {"threshold_ratio": threshold_ratio, "target_ratio": target_ratio, "step": step}
    jobs = [(symbol, histories[symbol], qqq, kwargs) for symbol in symbols]
    with ProcessPoolExecutor(max_workers=workers or min(len(jobs), 8)) as pool:
        results = dict(zip(symbols, pool.map(_replay_job, jobs)))
    spans = {symbol: len(histories[symbol]["close"]) - 260 for symbol in symbols}
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "assumptions": DEFAULT_ASSUMPTIONS, "threshold_ratio": threshold_ratio, "target_ratio": target_ratio, "step": step,
        "groups": {name: {"symbols": members, "rows": summarize_replay([row for s in members for row in results[s]], spans)}
                   for name, members in groups.items()},
        "elapsed_seconds": round(time.time() - started, 1),
    }


def markdown(report: dict[str, Any]) -> str:
    names = list(STRATEGY_LABELS)
    lines = [
        "# 持有 vs 换 QQQ 回测", "",
        f"生成时间：{report['generated_at']}　每 {report['step']} 个交易日一个起点；税门槛 = 起点价 × {report['threshold_ratio']:.3f}，"
        f"方案目标 = 起点价 × {report['target_ratio']:.3f}（与当前持仓同比例）；QQQ 用真实走势，模型预测用 QQQ 年化 "
        f"{report['assumptions']['qqq_return'] * 100:.0f}% 的先验。数值为期末税后财富 ÷ 起点全部卖出的税后到手。", "",
    ]
    for group, body in report["groups"].items():
        lines += [f"## {'美团（留出）' if group == 'holdout' else '港股一篮子'}：{', '.join(body['symbols'])}", "",
                  "| 期限 | 窗口 / 独立 | 股票年化中位 | QQQ 年化中位 | " + " | ".join(STRATEGY_LABELS[n] for n in names) + " | 全换胜过持有：预测 / 实际 |",
                  "|---|---|---|---|" + "---|" * len(names) + "---|"]
        for row in body["rows"]:
            cells = [f"{row['realized_median'][n]:.2f}（模型 {row['predicted_median'][n]:.2f}）" for n in names]
            lines.append(f"| {row['days'] // 252} 年 | {row['windows']} / {row['n_eff']} | {row['stock_cagr_median'] * 100:.1f}% | "
                         f"{row['qqq_cagr_median'] * 100:.1f}% | " + " | ".join(cells) +
                         f" | {row['switch_beats_hold']['predicted'] * 100:.0f}% / {row['switch_beats_hold']['realized'] * 100:.0f}% |")
        lines.append("")
    lines.append("窗口互相重叠，独立样本数很少（尤其 5 年），实际结果反映的是这段历史，不是未来的保证。")
    return "\n".join(lines) + "\n"
