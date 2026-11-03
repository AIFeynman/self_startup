"""Exit planning for a held position: touch probabilities, a sell ladder that hits a target average,
a Monte Carlo of how the ladder actually fills, trading costs and the reasoning behind every number.

Model: geometric Brownian motion on the daily close with no view on direction, volatility blended from a
recent EWMA and the trailing year. On top, the drift itself is uncertain: each path draws its own annual
drift from N(0, kappa*sigma^2), shifted so the price stays a martingale on average. Backtests over 2010-2026
(ai_monitor.sell_backtest) showed plain GBM is well calibrated at one month but overconfident at a year —
realized 1-year log returns are ~1.2x as dispersed as volatility alone implies — and kappa = 0.2 is that
excess dispersion, measured on a basket and validated out of sample on 3690.HK.

Because a ladder of limit orders fills in price order, the outcome of a path depends only on its running
maximum and its final price, so (max, final) pairs are sampled exactly (reflection principle) instead of
simulating whole paths. Unfilled shares are sold at the final price of the horizon. Pure standard library,
deterministic for a given input.
"""

from __future__ import annotations

import bisect
import math
import random
import re
from datetime import date, datetime, timedelta
from statistics import NormalDist
from typing import Any, Iterable, Sequence

TRADING_DAYS = 252
EWMA_LAMBDA = 0.94
SAMPLES = 12000
SEED = 20261102
# Touch probabilities the ladder rungs are placed at (the current price is the implicit 100% rung).
RUNG_PROBABILITIES = (0.85, 0.7, 0.55, 0.42, 0.3, 0.2, 0.12)
SWEEP_STEPS = 10
# Ladder shape → top rung as a multiple of the average the remaining shares need.
SHAPES = {"concentrated": 1.0, "balanced": 1.06, "wide": 1.15}
_NORMAL = NormalDist()
# Drift uncertainty: annual drift ~ N(0, DRIFT_KAPPA * sigma_annual^2). Estimated from the excess dispersion of
# realized 1-year returns (see the module docstring); 0 gives plain zero-drift GBM.
DRIFT_KAPPA = 0.2
# Equal-weight quadrature over the drift: normal quantiles rescaled to unit variance.
_RAW_NODES = [_NORMAL.inv_cdf((index + 0.5) / 21) for index in range(21)]
_NODE_SCALE = math.sqrt(sum(x * x for x in _RAW_NODES) / len(_RAW_NODES))
DRIFT_NODES = tuple(x / _NODE_SCALE for x in _RAW_NODES)
# Fill-timing checkpoints in trading days (1, 3, 6 and 12 months).
CHECKPOINTS = (21, 63, 126, 252)

# Per-order selling costs. HK: a typical online broker (0.03% commission, HK$3 minimum, HK$15 platform fee per
# executed order) plus statutory charges — stamp duty 0.1% rounded up to the dollar, HKEX trading fee 0.00565%,
# SFC levy 0.0027%, AFRC levy 0.00015%, CCASS settlement 0.002% (HK$2–100; brokers differ, verify yours).
# US: SEC fee and FINRA TAF on sells; commission defaults to zero. Overridden by "costs" in positions.json.
DEFAULT_COSTS = {
    "HK": {
        "commission_rate": 0.0003, "commission_min": 3.0, "platform_fee": 15.0,
        "stamp_duty_rate": 0.001, "trading_fee_rate": 0.0000565, "sfc_levy_rate": 0.000027,
        "afrc_levy_rate": 0.0000015, "settlement_rate": 0.00002, "settlement_min": 2.0, "settlement_max": 100.0,
    },
    "US": {
        "commission_rate": 0.0, "commission_min": 0.0, "platform_fee": 0.0,
        "sec_fee_rate": 0.0000278, "taf_per_share": 0.000166, "taf_max": 8.30,
    },
}
COST_LABELS = {
    "commission": "佣金", "platform_fee": "平台费", "stamp_duty": "印花税", "trading_fee": "交易费",
    "sfc_levy": "证监会征费", "afrc_levy": "会财局征费", "settlement": "交收费", "sec_fee": "SEC 费", "taf": "FINRA TAF",
}

# Hong Kong exchange spread table: (upper bound, tick).
HK_TICKS = (
    (0.25, 0.001), (0.5, 0.005), (10, 0.01), (20, 0.02), (100, 0.05), (200, 0.1),
    (500, 0.2), (1000, 0.5), (2000, 1.0), (5000, 2.0), (math.inf, 5.0),
)

POSITIVE_CUES = (
    "上调", "增持", "买入评级", "超预期", "回购", "扭亏", "大涨", "反弹", "创新高", "增长",
    "upgrade", "beat", "raise", "raises", "surge", "jump", "rally", "buyback", "outperform", "record",
)
NEGATIVE_CUES = (
    "下调", "减持", "亏损", "下滑", "下跌", "大跌", "暴跌", "处罚", "约谈", "承压", "不及预期",
    "downgrade", "miss", "cut", "loss", "plunge", "slump", "drop", "fall", "falls", "warn", "probe", "fine",
)


# ---- volatility & probabilities ----------------------------------------------------------------

def daily_volatility(closes: Sequence[float]) -> dict[str, float | None]:
    """Blend of EWMA (lambda 0.94, reacts to the current regime) and trailing-year realized volatility."""
    clean = [value for value in closes if value and value > 0]
    returns = [math.log(b / a) for a, b in zip(clean, clean[1:])]
    if len(returns) < 20:
        return {"daily": None, "annual": None, "ewma_annual": None, "realized_annual": None, "observations": len(returns)}
    window = returns[-TRADING_DAYS:]
    realized = math.sqrt(sum(r * r for r in window) / len(window))
    variance = sum(r * r for r in window[:20]) / 20
    for value in window[20:]:
        variance = EWMA_LAMBDA * variance + (1 - EWMA_LAMBDA) * value * value
    ewma = math.sqrt(variance)
    daily = math.sqrt(0.5 * ewma * ewma + 0.5 * realized * realized)
    root = math.sqrt(TRADING_DAYS)
    return {
        "daily": daily,
        "annual": daily * root,
        "ewma_annual": ewma * root,
        "realized_annual": realized * root,
        "observations": len(window),
    }


def drift_spread(sigma_daily: float, kappa: float = DRIFT_KAPPA, days: float | None = None) -> float:
    """Standard deviation of the per-day drift across paths. kappa is calibrated at one year; beyond that it is
    scaled by 252/days so the excess variance grows linearly (as if the drift were redrawn every year) rather
    than with the square of the horizon: realized 3- and 5-year log returns on the basket are ~1.3x and ~1.5x
    as dispersed as volatility implies (the latter inflated by drift differences between symbols), against
    1.6x and 2.0x for a drift fixed for the whole horizon."""
    if days and days > TRADING_DAYS:
        kappa = kappa * TRADING_DAYS / days
    return math.sqrt(max(kappa, 0.0) / TRADING_DAYS) * sigma_daily


def _drift_center(sigma_daily: float, days: float, kappa: float, drift_annual: float) -> float:
    """Mean per-day log drift: the requested drift, the Ito term, and the shift that keeps E[S_T] = S*e^(mu*T)
    once the drift is averaged over its uncertainty."""
    tau = drift_spread(sigma_daily, kappa, days)
    return drift_annual / TRADING_DAYS - 0.5 * sigma_daily * sigma_daily - 0.5 * tau * tau * days


def _touch_given_drift(barrier: float, nu: float, sigma_daily: float, days: float) -> float:
    """P(max over [0, days] of nu*t + sigma*W_t >= barrier), barrier > 0 (reflection principle with drift)."""
    spread = sigma_daily * math.sqrt(days)
    exponent = 2 * nu * barrier / (sigma_daily * sigma_daily)
    tail = math.exp(exponent) * _NORMAL.cdf((-barrier - nu * days) / spread) if exponent < 700 else 1.0
    return min(1.0, max(0.0, _NORMAL.cdf((-barrier + nu * days) / spread) + tail))


def touch_probability(
    price: float, level: float, sigma_daily: float, days: float, kappa: float = DRIFT_KAPPA, drift_annual: float = 0.0
) -> float:
    """P(the price trades at or above ``level`` at least once within ``days``), averaged over drift uncertainty."""
    if level <= price:
        return 1.0
    if sigma_daily <= 0 or days <= 0:
        return 0.0
    barrier = math.log(level / price)
    center = _drift_center(sigma_daily, days, kappa, drift_annual)
    tau = drift_spread(sigma_daily, kappa, days)
    if tau == 0:
        return _touch_given_drift(barrier, center, sigma_daily, days)
    return sum(_touch_given_drift(barrier, center + tau * x, sigma_daily, days) for x in DRIFT_NODES) / len(DRIFT_NODES)


def unlimited_touch_probability(price: float, level: float) -> float:
    """With no time limit a martingale price reaches ``level`` before going to zero with probability
    price/level (optional stopping) — an upper bound for any finite horizon."""
    return 1.0 if level <= price else price / level


def level_for_probability(price: float, probability: float, sigma_daily: float, days: float, kappa: float = DRIFT_KAPPA) -> float:
    """Inverse of touch_probability by bisection (touch probability falls as the level rises)."""
    low, high = price, price * math.exp(12 * sigma_daily * math.sqrt(max(days, 1)))
    for _ in range(60):
        middle = (low + high) / 2
        if touch_probability(price, middle, sigma_daily, days, kappa) > probability:
            low = middle
        else:
            high = middle
    return (low + high) / 2


def fill_timing(price: float, level: float, sigma_daily: float, days: int, kappa: float = DRIFT_KAPPA) -> dict[str, Any]:
    """When a limit at ``level`` fills: P(first touch within t) for the checkpoints inside the horizon, and the
    quartiles of the first-touch day conditional on filling within the horizon."""
    if level <= price:
        return {"by_day": {str(t): 1.0 for t in CHECKPOINTS if t <= days}, "q25_days": 0, "median_days": 0, "q75_days": 0}
    step = max(1, days // 84)
    grid = list(range(step, days, step)) + [days]
    cdf, running = [], 0.0
    for t in grid:
        running = max(running, touch_probability(price, level, sigma_daily, t, kappa))
        cdf.append(running)
    total = cdf[-1]

    def quantile(share: float) -> int | None:
        if total <= 0:
            return None
        return next(t for t, value in zip(grid, cdf) if value >= share * total)

    return {
        "by_day": {str(t): touch_probability(price, level, sigma_daily, t, kappa) for t in CHECKPOINTS if t <= days},
        "q25_days": quantile(0.25), "median_days": quantile(0.5), "q75_days": quantile(0.75),
    }


def sample_paths(
    sigma_daily: float, days: float, samples: int = SAMPLES, seed: int = SEED,
    kappa: float = DRIFT_KAPPA, drift_annual: float = 0.0,
) -> list[tuple[float, float]]:
    """Exact joint draws of (running-max log return, final log return): each path draws its drift, then the
    final value, then the maximum of the Brownian bridge between them (which does not depend on the drift)."""
    rng = random.Random(seed)
    spread = sigma_daily * math.sqrt(days)
    center = _drift_center(sigma_daily, days, kappa, drift_annual)
    tau = drift_spread(sigma_daily, kappa, days)
    draws = []
    for _ in range(samples):
        drift = (center + tau * rng.gauss(0.0, 1.0)) * days
        final = drift + spread * rng.gauss(0.0, 1.0)
        uniform = 1.0 - rng.random()  # (0, 1]
        peak = 0.5 * (final + math.sqrt(final * final - 2 * spread * spread * math.log(uniform)))
        draws.append((max(peak, 0.0, final), final))
    return draws


# ---- trading costs ------------------------------------------------------------------------------

def cost_schedule(market: str, overrides: dict[str, Any] | None = None) -> dict[str, float]:
    key = "HK" if market == "HK" else "US"
    schedule = dict(DEFAULT_COSTS[key])
    for name, value in ((overrides or {}).get(key) or {}).items():
        if name in schedule and isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
            schedule[name] = float(value)
    return schedule


def order_cost(price: float, shares: int, schedule: dict[str, float]) -> dict[str, float]:
    """Charges for one executed sell order, by component, plus ``total``."""
    if shares <= 0:
        return {"total": 0.0}
    notional = price * shares
    parts = {
        "commission": max(notional * schedule.get("commission_rate", 0.0), schedule.get("commission_min", 0.0)),
        "platform_fee": schedule.get("platform_fee", 0.0),
    }
    if "stamp_duty_rate" in schedule:
        parts["stamp_duty"] = math.ceil(notional * schedule["stamp_duty_rate"] - 1e-9)
        parts["trading_fee"] = max(0.01, notional * schedule["trading_fee_rate"])
        parts["sfc_levy"] = notional * schedule["sfc_levy_rate"]
        parts["afrc_levy"] = notional * schedule["afrc_levy_rate"]
        parts["settlement"] = min(max(notional * schedule["settlement_rate"], schedule["settlement_min"]), schedule["settlement_max"])
    if "sec_fee_rate" in schedule:
        parts["sec_fee"] = notional * schedule["sec_fee_rate"]
        parts["taf"] = min(shares * schedule["taf_per_share"], schedule["taf_max"])
    parts = {name: round(value, 2) for name, value in parts.items() if value}
    parts["total"] = round(sum(parts.values()), 2)
    return parts


def _linear_cost(schedule: dict[str, float]) -> tuple[float, float]:
    """(fixed, proportional) approximation of order_cost for a large order, used inside the Monte Carlo."""
    rate = schedule.get("commission_rate", 0.0) + schedule.get("stamp_duty_rate", 0.0) + schedule.get("trading_fee_rate", 0.0)
    rate += schedule.get("sfc_levy_rate", 0.0) + schedule.get("afrc_levy_rate", 0.0) + schedule.get("settlement_rate", 0.0)
    rate += schedule.get("sec_fee_rate", 0.0)
    return schedule.get("platform_fee", 0.0) + 0.5 * (1 if "stamp_duty_rate" in schedule else 0), rate


# ---- ladder construction ------------------------------------------------------------------------

def tick_size(price: float, market: str = "") -> float:
    if market == "HK":
        return next(tick for bound, tick in HK_TICKS if price < bound)
    return 0.01


def round_to_tick(price: float, market: str = "", up: bool = True) -> float:
    tick = tick_size(price, market)
    steps = price / tick
    steps = math.ceil(steps - 1e-9) if up else math.floor(steps + 1e-9)
    return round(steps * tick, 6)


def rung_prices(
    price: float, required_avg: float, sigma_daily: float, days: float, market: str = "", shape: str = "balanced",
    kappa: float = DRIFT_KAPPA, levels: Sequence[float] | None = None,
) -> list[float]:
    """Rungs above the current price at fixed touch probabilities, capped by a top rung a shape-dependent
    margin above the required average. Any ladder that averages the target needs a rung above it, and
    the target is met only once that rung fills, so a wider ladder trades probability of reaching the
    target for more partial fills (a better downside) when the price stalls on the way up."""
    ceiling = round_to_tick(required_avg * SHAPES[shape], market)
    if levels is None:
        levels = probability_levels(price, sigma_daily, days, market, kappa)
    floor_tick = tick_size(price, market)
    unique: list[float] = []
    # Probability rungs within 1% of the top rung would duplicate it.
    candidates = [level for level in levels if level < ceiling * 0.99] + [ceiling] if shape != "concentrated" else [ceiling]
    for level in candidates:
        if price + floor_tick / 2 < level <= ceiling and (not unique or level > unique[-1]):
            unique.append(level)
    return unique


def probability_levels(price: float, sigma_daily: float, days: float, market: str = "", kappa: float = DRIFT_KAPPA) -> list[float]:
    return [round_to_tick(level_for_probability(price, q, sigma_daily, days, kappa), market) for q in RUNG_PROBABILITIES]


def allocate(prices: Sequence[float], probabilities: Sequence[float], shares: int, required_avg: float, lot: int) -> list[int]:
    return allocate_with_theta(prices, probabilities, shares, required_avg, lot)[0]


def allocate_with_theta(
    prices: Sequence[float], probabilities: Sequence[float], shares: int, required_avg: float, lot: int
) -> tuple[list[int], float]:
    """Split ``shares`` over ``prices`` so the weighted price equals ``required_avg``.

    Weights are proportional to touch_probability**theta: one smooth knob between "everything on the
    most likely rung" (theta → +inf) and "everything on the least likely rung" (theta → -inf). The
    weighted average is monotonic in theta, so bisection finds the unique theta that hits the target.
    """
    if shares <= 0 or not prices:
        return [0 for _ in prices], 0.0
    floor_q = 1e-4
    lots_total = shares // lot
    odd = shares - lots_total * lot
    if lots_total and odd:
        # The odd lot sits on the lowest rung, so the round lots must carry a little more.
        required_avg = (required_avg * shares - odd * prices[0]) / (lots_total * lot)

    def weights(theta: float) -> list[float]:
        logs = [theta * math.log(max(q, floor_q)) for q in probabilities]
        top = max(logs)
        raw = [math.exp(value - top) for value in logs]
        total = sum(raw)
        return [value / total for value in raw]

    def average(theta: float) -> float:
        return sum(w * p for w, p in zip(weights(theta), prices))

    low, high = -60.0, 60.0
    if required_avg >= average(low):
        theta = low
    elif required_avg <= average(high):
        theta = high
    else:
        for _ in range(100):
            middle = (low + high) / 2
            if average(middle) > required_avg:
                low = middle
            else:
                high = middle
        theta = (low + high) / 2
    exact = [w * lots_total for w in weights(theta)]
    lots = [int(math.floor(value)) for value in exact]
    # Hand out the rounding remainder one lot at a time to whichever rung keeps the average closest
    # without dropping below the requirement, then shift lots upward until rounding cannot undercut it.
    def lot_average(counts: list[int]) -> float:
        total = sum(counts)
        return sum(c * p for c, p in zip(counts, prices)) / total if total else 0.0

    for _ in range(lots_total - sum(lots)):
        def score(index: int) -> tuple[bool, float]:
            trial = lots.copy()
            trial[index] += 1
            average_after = lot_average(trial)
            return (average_after < required_avg - 1e-9, abs(average_after - required_avg))

        lots[min(range(len(prices)), key=score)] += 1
    top = len(prices) - 1
    while lots_total and lot_average(lots) < required_avg - 1e-9 and prices[top] >= required_avg:
        lowest = next((index for index in range(top) if lots[index]), None)
        if lowest is None:
            break
        lots[lowest] -= 1
        lots[top] += 1
    allocation = [count * lot for count in lots]
    allocation[0] += odd  # odd lot (HK trades these on a separate, thinner board)
    return allocation, theta


def evaluate(
    tiers: Sequence[tuple[float, int]],
    leftover: int,
    price: float,
    draws: Sequence[tuple[float, float]],
    target_total_proceeds: float,
    locked_proceeds: float,
    total_shares: int,
    schedule: dict[str, float] | None = None,
    locked_costs: float = 0.0,
) -> dict[str, Any]:
    """Distribution of the overall average (already-sold + this plan) across sampled paths, before and after
    costs.

    ``tiers`` are limit sells above the current price; ``leftover`` shares have no order and are sold at
    the final price, as are rungs the path never reached. ``locked_proceeds`` covers shares already sold
    and the at-market sale at the current price; ``locked_costs`` their charges. The target is a gross
    average (what the user types); ``probability_target_net`` asks for the same average after costs.
    """
    ordered = sorted((p, s) for p, s in tiers if s > 0)
    log_levels = [math.log(p / price) for p, _ in ordered]
    cum_shares = [0]
    cum_proceeds = [0.0]
    cum_costs = [0.0]
    for p, s in ordered:
        cum_shares.append(cum_shares[-1] + s)
        cum_proceeds.append(cum_proceeds[-1] + p * s)
        cum_costs.append(cum_costs[-1] + (order_cost(p, s, schedule)["total"] if schedule else 0.0))
    fixed, rate = _linear_cost(schedule) if schedule else (0.0, 0.0)
    planned = cum_shares[-1] + leftover
    gross, net = [], []
    unfilled_total = 0
    hits = hits_net = 0
    cost_total = 0.0
    for peak, final in draws:
        filled = bisect.bisect_right(log_levels, peak + 1e-12)
        unfilled = planned - cum_shares[filled]
        tail = unfilled * price * math.exp(final)
        proceeds = locked_proceeds + cum_proceeds[filled] + tail
        costs = locked_costs + cum_costs[filled] + ((fixed + rate * tail) if unfilled else 0.0)
        gross.append(proceeds / total_shares)
        net.append((proceeds - costs) / total_shares)
        unfilled_total += unfilled
        cost_total += costs
        if proceeds >= target_total_proceeds - 1e-6:
            hits += 1
        if proceeds - costs >= target_total_proceeds - 1e-6:
            hits_net += 1
    gross.sort()
    net.sort()
    count = len(gross)

    def pick(values: list[float], share: float) -> float:
        return values[int(share * (count - 1))]

    return {
        "probability_target": hits / count,
        "probability_target_net": hits_net / count,
        "expected_avg": sum(gross) / count,
        "p10_avg": pick(gross, 0.1),
        "p50_avg": pick(gross, 0.5),
        "p90_avg": pick(gross, 0.9),
        "expected_net_avg": sum(net) / count,
        "p10_net_avg": pick(net, 0.1),
        "p90_net_avg": pick(net, 0.9),
        "expected_costs": cost_total / count,
        "expected_unfilled_shares": unfilled_total / count,
    }


def build_plan(
    *,
    price: float,
    total_shares: int,
    target_avg: float,
    sigma_daily: float,
    horizon_days: int,
    lot: int = 100,
    market: str = "",
    sold_shares: int = 0,
    sold_proceeds: float = 0.0,
    now_shares: int | None = None,
    shape: str = "balanced",
    samples: int = SAMPLES,
    costs: dict[str, float] | None = None,
    sold_costs: float = 0.0,
    kappa: float = DRIFT_KAPPA,
    explain: bool = True,
    today: date | None = None,
) -> dict[str, Any]:
    """Recommend how many shares to sell at the current price and where to place the rest.

    The at-market amount is chosen from a sweep (0%..100% of the remaining shares): the one with the
    highest probability of reaching the target average, preferring the larger sale when two are within
    two percentage points (the locked-in part carries no path risk). ``now_shares`` overrides the choice.
    ``costs`` is a cost_schedule (None: no costs); ``explain`` adds fill timing, drift sensitivity and the
    written reasoning (skipped in backtests).
    """
    if shape not in SHAPES:
        raise ValueError(f"shape must be one of {', '.join(SHAPES)}")
    remaining = max(0, total_shares - sold_shares)
    target_proceeds = target_avg * total_shares
    draws = sample_paths(sigma_daily, horizon_days, samples, kappa=kappa)
    lot = max(1, lot)
    levels = probability_levels(price, sigma_daily, horizon_days, market, kappa)

    def scenario(now: int) -> dict[str, Any]:
        now = min(max(0, now), remaining)
        rest = remaining - now
        locked = sold_proceeds + now * price
        required = (target_proceeds - locked) / rest if rest else None
        tiers: list[tuple[float, int, float]] = []
        theta = 0.0
        if rest and required is not None and required > price:
            prices = rung_prices(price, required, sigma_daily, horizon_days, market, shape, kappa, levels)
            probabilities = [touch_probability(price, level, sigma_daily, horizon_days, kappa) for level in prices]
            shares, theta = allocate_with_theta(prices, probabilities, rest, required, lot)
            tiers = [(p, s, q) for p, s, q in zip(prices, shares, probabilities) if s > 0]
            leftover = rest - sum(s for _, s, _ in tiers)
        else:
            # Target already reachable at the current price: the rest is a market sale too.
            leftover = 0
            if rest:
                locked += rest * price
                now, rest = remaining, 0
        locked_costs = sold_costs + (order_cost(price, now, costs)["total"] if costs and now else 0.0)
        stats = evaluate([(p, s) for p, s, _ in tiers], leftover, price, draws, target_proceeds, locked, total_shares,
                         costs, locked_costs)
        return {"now_shares": now, "required_avg_rest": required, "tiers": tiers, "leftover": leftover, "theta": theta,
                "locked_costs": locked_costs, **stats}

    sweep_sizes = sorted({min(remaining, round(remaining * step / SWEEP_STEPS / lot) * lot) for step in range(SWEEP_STEPS + 1)} | {remaining})
    sweep = [scenario(size) for size in sweep_sizes]
    best = max(row["probability_target"] for row in sweep)
    recommended = max((row for row in sweep if row["probability_target"] >= best - 0.02), key=lambda row: row["now_shares"])
    chosen = scenario(now_shares) if now_shares is not None else recommended

    ladder = []
    if chosen["now_shares"]:
        ladder.append({"kind": "market", "price": price, "shares": chosen["now_shares"], "touch_probability": 1.0,
                       "touch_probability_unlimited": 1.0, "gain_pct": 0.0})
    for index, (level, shares, probability) in enumerate(chosen["tiers"]):
        ladder.append({"kind": "limit", "price": level, "shares": shares, "touch_probability": probability,
                       "touch_probability_unlimited": unlimited_touch_probability(price, level),
                       "gain_pct": (level / price - 1) * 100})
    for row in ladder:
        row["cost"] = order_cost(row["price"], row["shares"], costs) if costs else {"total": 0.0}
        row["net_price"] = row["price"] - row["cost"]["total"] / row["shares"]
    planned = sum(row["shares"] for row in ladder)
    plan_avg = sum(row["price"] * row["shares"] for row in ladder) / planned if planned else None
    ladder_costs = sum(row["cost"]["total"] for row in ladder)
    all_now_costs = order_cost(price, remaining, costs)["total"] if costs and remaining else 0.0
    plan = {
        "price": price,
        "target_avg": target_avg,
        "horizon_days": horizon_days,
        "sigma_daily": sigma_daily,
        "kappa": kappa,
        "remaining_shares": remaining,
        "required_avg_remaining": (target_proceeds - sold_proceeds) / remaining if remaining else None,
        "recommended_now_shares": recommended["now_shares"],
        "now_shares": chosen["now_shares"],
        "overridden": now_shares is not None,
        "ladder": ladder,
        "ladder_avg": plan_avg,
        "all_filled_avg": ((sold_proceeds + (plan_avg or 0) * planned) / (sold_shares + planned)) if sold_shares + planned else None,
        "all_filled_net_avg": ((sold_proceeds - sold_costs + (plan_avg or 0) * planned - ladder_costs) / total_shares) if total_shares else None,
        "all_filled_costs": ladder_costs + sold_costs,
        "all_filled_probability": min((row["touch_probability"] for row in ladder), default=1.0),
        "all_filled_probability_unlimited": min((row["touch_probability_unlimited"] for row in ladder), default=1.0),
        "shape": shape,
        "theta": chosen["theta"],
        **{key: chosen[key] for key in (
            "probability_target", "probability_target_net", "expected_avg", "p10_avg", "p50_avg", "p90_avg",
            "expected_net_avg", "p10_net_avg", "p90_net_avg", "expected_costs", "expected_unfilled_shares")},
        "sell_all_now_avg": (sold_proceeds + remaining * price) / total_shares if total_shares else None,
        "sell_all_now_net_avg": (sold_proceeds - sold_costs + remaining * price - all_now_costs) / total_shares if total_shares else None,
        "sell_all_now_costs": all_now_costs + sold_costs,
        "sweep": [
            {key: row[key] for key in ("now_shares", "required_avg_rest", "probability_target", "probability_target_net",
                                       "expected_avg", "expected_net_avg", "p10_avg", "p90_avg", "expected_costs")}
            for row in sweep
        ],
        "samples": samples,
    }
    if explain:
        for row in ladder:
            row["timing"] = fill_timing(price, row["price"], sigma_daily, horizon_days, kappa)
            row["timing"]["median_date"] = _trading_date(today, row["timing"]["median_days"])
        plan["drift_sensitivity"] = [
            {"drift_annual": drift, **{key: value for key, value in evaluate(
                [(p, s) for p, s, _ in chosen["tiers"]], chosen["leftover"], price,
                sample_paths(sigma_daily, horizon_days, samples, kappa=kappa, drift_annual=drift),
                target_proceeds, sold_proceeds + chosen["now_shares"] * price, total_shares, costs, chosen["locked_costs"],
            ).items() if key in ("probability_target", "expected_avg", "p10_avg", "expected_net_avg")}}
            for drift in (-0.2, 0.0, 0.2)
        ]
        plan["reasons"] = explain_plan(plan, chosen, sweep, sold_shares=sold_shares)
    return plan


def _trading_date(today: date | None, trading_days: int | None) -> str | None:
    """Calendar date ``trading_days`` weekdays after ``today`` (holidays ignored, so approximate)."""
    if trading_days is None:
        return None
    day = today or date.today()
    left = trading_days
    while left > 0:
        day += timedelta(days=1)
        if day.weekday() < 5:
            left -= 1
    return day.isoformat()


def _pct(value: float | None, digits: int = 0) -> str:
    return "—" if value is None else f"{value * 100:.{digits}f}%"


def _money(value: float | None) -> str:
    return "—" if value is None else f"{value:,.2f}"


def explain_plan(plan: dict[str, Any], chosen: dict[str, Any], sweep: Sequence[dict[str, Any]], *, sold_shares: int = 0) -> dict[str, Any]:
    """Plain-language reasoning for every number in the plan: why this much now, why each rung's price,
    size and timing, what happens if it does not fill, and when to re-plan."""
    price, sigma, days = plan["price"], plan["sigma_daily"], plan["horizon_days"]
    spread = sigma * math.sqrt(days)
    required = plan["required_avg_remaining"]
    overview = [
        f"波动率：年化 {_pct(plan['sigma_daily'] * math.sqrt(TRADING_DAYS))}（近期 EWMA 与近一年已实现各占一半）；"
        f"{days} 个交易日内 1 个标准差约 ±{_pct(spread)}（再叠加漂移不确定性后约 ±{_pct(spread * math.sqrt(1 + plan['kappa'] * days / TRADING_DAYS))}）。",
        "方向：模型不预测涨跌（价格期望不变），所以任何挂单方案都不能提高期望均价，只能在"
        "「达到目标的概率」和「最差情形的均价」之间取舍；下面的数字都来自这个取舍。",
    ]
    if plan["sell_all_now_avg"] and plan["expected_avg"] < plan["sell_all_now_avg"] - 1e-9:
        overview.append(
            f"代价：本方案期望均价 {_money(plan['expected_avg'])}，低于现在全卖的 {_money(plan['sell_all_now_avg'])}"
            f"（{_pct(plan['expected_avg'] / plan['sell_all_now_avg'] - 1, 1)}）。原因是趋势本身不确定：限价单在上涨趋势里先成交、"
            "错过后面的涨幅，在下跌趋势里不成交、到期按更低的价格卖出。换来的是达到目标均价的机会。"
        )
    if required and required > price:
        z = math.log(required / price) / spread
        overview.append(
            f"难度：未卖的 {plan['remaining_shares']:,} 股需要均价 {_money(required)}，比现价高 {_pct(required / price - 1, 1)}，"
            f"约 {z:.2f} 个期限内标准差；期限内价格至少触及一次的概率 {_pct(touch_probability(price, required, sigma, days, plan['kappa']))}。"
        )
    elif required:
        overview.append(f"难度：目标均价 {_money(plan['target_avg'])} 不高于现价，按现价全部卖出即可达标。")
    overview.append(
        f"费用：全部按方案成交约 {_money(plan['all_filled_costs'])}，现在一次全卖约 {_money(plan['sell_all_now_costs'])}；"
        f"费用以按比例部分为主（港股印花税 0.1% 占大头），多拆几档只多出每单的固定平台费。"
    )

    rows = sorted(sweep, key=lambda row: row["now_shares"])
    index = next((i for i, row in enumerate(rows) if row["now_shares"] == chosen["now_shares"]), None)
    best = max(row["probability_target"] for row in rows)
    now_lines = []
    if plan["overridden"]:
        now_lines.append(f"现价卖出 {chosen['now_shares']:,} 股是手动设置；推荐值为 {plan['recommended_now_shares']:,} 股。")
    else:
        now_lines.append(
            f"扫描了现价卖出 0%…100% 共 {len(rows)} 档：达标概率最高 {_pct(best)}；在与最高值相差不超过 2 个百分点的方案里，"
            f"选现价卖得最多的一档（{chosen['now_shares']:,} 股），因为现价成交的部分锁定、不承担后续路径风险。"
        )
    if index is not None:
        for label, other in (("多卖", rows[index + 1] if index + 1 < len(rows) else None), ("少卖", rows[index - 1] if index > 0 else None)):
            if other is None:
                continue
            now_lines.append(
                f"{label}到 {other['now_shares']:,} 股：达标概率 {_pct(other['probability_target'])}"
                f"（{(other['probability_target'] - chosen['probability_target']) * 100:+.0f} 个百分点），"
                f"最差 10% 情形均价 {_money(other['p10_avg'])}（{other['p10_avg'] - chosen['p10_avg']:+.2f}）。"
            )
        now_lines.append("规律：现价多卖会抬高剩余股份需要的均价（更难达标），但抬高最差情形的均价；少卖则相反。")

    rung_lines = []
    limits = [row for row in plan["ladder"] if row["kind"] == "limit"]
    for position, row in enumerate(limits):
        top = position == len(limits) - 1
        if top:
            why_price = (f"顶档 = 剩余所需均价 {_money(chosen['required_avg_rest'])} × {SHAPES[plan['shape']]:g}（{plan['shape']} 形状）。"
                         "任何能凑出目标均价的阶梯都必须有一档高于所需均价，目标只在这一档成交时才达到。")
        else:
            why_price = f"放在期限内触及概率约 {_pct(row['touch_probability'])} 的价位（固定概率档，按港股价位表取整）。"
        share = row["shares"] / max(1, plan["remaining_shares"] - plan["now_shares"])
        why_shares = (f"占挂单股数 {_pct(share)}：股数按 触及概率^θ 分配，θ={plan['theta']:.2f} 是让挂单均价恰好等于所需均价的唯一值"
                      f"（θ>0 时越容易成交的档放得越多）。")
        timing = row.get("timing") or {}
        if timing.get("median_days") is not None and row["touch_probability"] > 0:
            checkpoints = "，".join(f"{int(k) // 21} 个月内 {_pct(v)}" for k, v in timing["by_day"].items())
            why_when = (f"期限内成交概率 {_pct(row['touch_probability'])}；若成交，中位在第 {timing['median_days']} 个交易日"
                        f"（约 {timing['median_date']}），一半落在第 {timing['q25_days']}–{timing['q75_days']} 日；{checkpoints}。")
        else:
            why_when = "期限内成交概率很低。"
        rung_lines.append({"price": row["price"], "shares": row["shares"], "price_reason": why_price,
                           "shares_reason": why_shares, "timing_reason": why_when})

    trigger_low = price * math.exp(-sigma * math.sqrt(21))
    contingency = [
        f"到期仍未成交的部分（期望约 {plan['expected_unfilled_shares']:,.0f} 股）按到期价卖出，已计入上面的概率与均价分布；"
        "到期时也可以改为重新规划下一期。",
        f"重新生成方案的时点：任一档成交后（剩余股数和所需均价都变了）；价格跌破 {_money(trigger_low)}（约 1 个月 1 个标准差）；"
        "年化波动率较现在变化超过 25%；没有触发时每月复核一次。",
        "港股限价单当日有效，需要每个交易日重新挂出（未成交的单不收费）；平台费按每笔成交收取，一档分多天成交会重复收取。",
    ]
    sensitivity = plan.get("drift_sensitivity") or []
    if sensitivity:
        down, flat, up = sensitivity
        contingency.append(
            f"方向敏感性：若实际年化漂移为 -20% / 0 / +20%，达标概率分别为 {_pct(down['probability_target'])} / "
            f"{_pct(flat['probability_target'])} / {_pct(up['probability_target'])}，期望均价 {_money(down['expected_avg'])} / "
            f"{_money(flat['expected_avg'])} / {_money(up['expected_avg'])}。"
        )
    return {"overview": overview, "now": now_lines, "rungs": rung_lines, "contingency": contingency}


CEILING_PROBABILITIES = (0.9, 0.7, 0.5, 0.3, 0.1)
CURVE_HORIZONS = (63, 126, 252)


def target_ceiling(
    price: float, sigma_daily: float, horizon_days: int, target_avg: float, total_shares: int,
    sold_shares: int = 0, sold_proceeds: float = 0.0, points: int = 41, kappa: float = DRIFT_KAPPA,
) -> dict[str, Any]:
    """The most any sell plan can reach for a gross target, and how that ceiling moves with target and horizon.

    Every fill is at or below the highest price traded, so if the price never reaches the average the remaining
    shares still need, no plan can hit the target: P(target) <= P(touch that level). A single limit order for
    everything at that level attains the bound, which makes it the ceiling rather than a loose estimate.
    """
    remaining = total_shares - sold_shares

    def level(target: float) -> float:
        return (target * total_shares - sold_proceeds) / remaining if remaining else 0.0

    def overall(level_price: float) -> float:
        return (sold_proceeds + level_price * remaining) / total_shares

    required = level(target_avg)
    horizons = sorted(set(CURVE_HORIZONS) | {horizon_days})
    longest = max(horizons)
    top = max(target_avg * 1.15, overall(level_for_probability(price, 0.03, sigma_daily, longest, kappa)))
    bottom = overall(price)
    curve = []
    for index in range(points):
        target = bottom + (top - bottom) * index / (points - 1)
        curve.append({"target_avg": target, "level": level(target),
                      "probability": {str(days): touch_probability(price, level(target), sigma_daily, days, kappa) for days in horizons}})
    return {
        "required_level": required,
        "probability": touch_probability(price, required, sigma_daily, horizon_days, kappa),
        "unlimited": unlimited_touch_probability(price, required),
        "by_horizon": [{"days": days, "probability": touch_probability(price, required, sigma_daily, days, kappa)} for days in horizons],
        "targets": [{"probability": q, "level": (found := level_for_probability(price, q, sigma_daily, horizon_days, kappa)),
                     "target_avg": overall(found)} for q in CEILING_PROBABILITIES],
        "horizons": horizons,
        "curve": curve,
    }


# ---- price & news analysis ---------------------------------------------------------------------

def price_summary(daily: Sequence[dict[str, Any]], hourly: Sequence[dict[str, Any]], price: float) -> dict[str, Any]:
    closes = [row["close"] for row in daily if row.get("close")]

    def change(bars_back: int) -> float | None:
        if len(closes) <= bars_back:
            return None
        base = closes[-1 - bars_back]
        return (price / base - 1) * 100 if base else None

    hourly_closes = [row["close"] for row in hourly if row.get("close")]
    year = closes[-TRADING_DAYS:]
    highs = [row.get("high") or row["close"] for row in daily[-TRADING_DAYS:] if row.get("close")]
    lows = [row.get("low") or row["close"] for row in daily[-TRADING_DAYS:] if row.get("close")]
    high, low = (max(highs + [price]), min(lows + [price])) if highs else (None, None)

    def sma(period: int) -> float | None:
        return sum(closes[-period:]) / period if len(closes) >= period else None

    # The latest daily bar is today's session while trading, so "1D" compares with the bar before it.
    return {
        "change_1h_pct": (price / hourly_closes[-2] - 1) * 100 if len(hourly_closes) >= 2 and hourly_closes[-2] else None,
        "change_1d_pct": change(1),
        "change_5d_pct": change(5),
        "change_20d_pct": change(20),
        "change_60d_pct": change(60),
        "change_1y_pct": change(len(year) - 1) if len(year) > 1 else None,
        "high_52w": high,
        "low_52w": low,
        "range_position": (price - low) / (high - low) if high and low and high != low else None,
        "sma20": sma(20),
        "sma60": sma(60),
        "sma200": sma(200),
    }


def tag_news(title: str, topics: dict[str, Iterable[str]]) -> dict[str, Any]:
    text = title.lower()
    matched = [name for name, needles in topics.items() if any(_contains(text, needle) for needle in needles)]
    positive = sum(1 for cue in POSITIVE_CUES if _contains(text, cue))
    negative = sum(1 for cue in NEGATIVE_CUES if _contains(text, cue))
    return {"topics": matched, "tone": "positive" if positive > negative else "negative" if negative > positive else "neutral"}


def _contains(text: str, needle: str) -> bool:
    needle = needle.lower()
    if needle.isascii() and needle.replace(" ", "").isalpha():
        return re.search(rf"(?<![a-z]){re.escape(needle)}(?![a-z])", text) is not None
    return needle in text


def notable_moves(hourly: Sequence[dict[str, Any]], news: Sequence[dict[str, Any]], limit: int = 6) -> list[dict[str, Any]]:
    """Largest hourly moves (beyond 2 standard deviations) with the headlines published since the previous
    bar — for a session's first bar that window covers the overnight gap."""
    bars = [row for row in hourly if row.get("close")]
    moves = []
    for previous, current in zip(bars, bars[1:]):
        if previous["close"]:
            moves.append({
                "ts": current["ts"], "previous_ts": previous["ts"], "close": current["close"],
                "change_pct": (current["close"] / previous["close"] - 1) * 100,
                "gap": current["ts"] - previous["ts"] > 3 * 3600,
            })
    if len(moves) < 10:
        return []
    deviation = math.sqrt(sum(m["change_pct"] ** 2 for m in moves) / len(moves))
    big = sorted((m for m in moves if abs(m["change_pct"]) >= 2 * deviation), key=lambda m: -abs(m["change_pct"]))[:limit]
    stamped = [(item, _epoch(item.get("published_at"))) for item in news]
    result = []
    for move in sorted(big, key=lambda m: -m["ts"]):
        start = move["previous_ts"] if move["gap"] else move["ts"] - 6 * 3600
        nearby = [item for item, published in stamped if published is not None and start <= published <= move["ts"] + 3600]
        result.append({
            "ts": move["ts"], "change_pct": move["change_pct"], "close": move["close"], "gap": move["gap"],
            "sigma": move["change_pct"] / deviation if deviation else None,
            "news": [{"title": item["title"], "url": item["url"], "source": item["source"]} for item in nearby[:3]],
        })
    return result


def _epoch(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())
    except ValueError:
        return None
