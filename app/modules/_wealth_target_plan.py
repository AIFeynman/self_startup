"""One-year return target for the focus assets: probability of reaching it, a mild action signal with its
reasons, an allocation of fresh cash, and a walk-forward backtest that checks all of it.

Model (deliberately simple, validated in the backtest):

* Expected one-year log return ``mu`` is the asset's own long-run log return shrunk toward a prior
  (``PRIOR_LOG_RETURN``) with weight ``n / (n + SHRINK_YEARS)`` for ``n`` years of history — a short or
  extraordinary record (GOOGL, the dividend ETF since 2019) is not extrapolated at face value.
* One-year spread ``s`` is today's volatility (EWMA blended with realized, ``sell_plan.daily_volatility``),
  widened by the same drift-uncertainty factor ``sqrt(1 + kappa)`` the exit planner uses.
* ``P(R >= g) = 1 - Phi((log(1 + g) - mu) / s)``; quantiles follow from the same lognormal.

The action signal (add / hold / reduce-or-wait) combines that probability with the 200-day trend. The
backtest is explicit that such timing signals have not beaten simply holding across regimes; the signal is a
risk frame, not a forecast. Returns are in each asset's own currency (the dividend ETF in CNY), no FX.
"""

from __future__ import annotations

import json
import math
import random
import re
import time
from bisect import bisect_right
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from statistics import NormalDist
from typing import Any, Iterable, Sequence

from . import _wealth_sell_plan as sp
from ._wealth_market import get_bytes

FOCUS = ("QQQ", "GOOGL", "MSFT", "512890.SS")
SINGLE_STOCKS = ("GOOGL", "MSFT")
# Longer records used only by the backtest: NASDAQ-100 price index back to 1990 (QQQ starts 1999), SPY.
BACKTEST_EXTRA = ("^NDX", "SPY")
# Onshore pure-bond funds, bought equal-weight as one asset. Both are open for subscription and redemption
# (no holding lock), above 10 亿 and with records from 2022. 007520 dropped out in 2026-11: daily purchases
# capped at 5 万 and the fund shrank by ~60% in one quarter.
BOND = "BOND.CN"
BOND_FUNDS = {"009203": "鹏扬稳利债券A", "016426": "国泰信瑞纯债债券A"}
PLAN = (*FOCUS, BOND)               # what the allocation chooses from; the signal backtest stays on FOCUS
OPTIONAL = (BOND,)                  # exempt from the aggressive mix's per-asset minimum
LABELS = {"QQQ": "纳指100 ETF", "GOOGL": "谷歌", "MSFT": "微软", "512890.SS": "红利低波ETF", "^NDX": "纳指100指数", "SPY": "标普500 ETF",
          BOND: "纯债基金组合"}
DEFAULT_TARGET = 0.10
TARGET_RANGE = (0.0, 0.5)
CURVE = tuple(step / 100 for step in range(5, 21))
PRIOR_LOG_RETURN = 0.07
SHRINK_YEARS = 10.0
# Single stocks are on the list because they did well (survivorship), so their own record gets less weight.
SHRINK_YEARS_STOCK = 30.0
KAPPA = sp.DRIFT_KAPPA
YEAR = sp.TRADING_DAYS
MIN_HISTORY = 2 * YEAR
ADD_PROBABILITY = 0.5
REDUCE_PROBABILITY = 0.35
ACTION_WEIGHTS = {"add": 1.5, "hold": 1.0, "reduce": 0.5}
ACTION_LABELS = {"add": "分批加仓", "hold": "持有 / 定投", "reduce": "减仓或暂缓买入"}
# How new money goes in under each signal: the backtest found no timing edge, so the signal sets the pace only.
PACING = {"add": "分 2 批：本月一半、下月一半", "hold": "分 3 个月等额买入", "reduce": "分 6 个月买入，或等重新站上 200 日均线再加快"}
MAX_SINGLE_STOCK = 0.4
# All four are on the focus list, so none is dropped entirely by a flat optimum.
MIN_WEIGHT = 0.1
P10_FLOOR = -0.15
TIE_PROBABILITY = 0.01
GRID = 10
STEP = 21
# The steady mode: no minimum per asset (so “QQQ + dividend only” is allowed), but the year must end flat or
# better with at least this probability and the bad decile must stay above the floor; then maximize the target.
SAFE_NONNEG = 0.80
SAFE_P10_FLOOR = -0.10
# Buy ladder: part at market, the rest as limit orders this far below today's price, valid LADDER_DAYS; whatever
# has not filled by then is bought at that day's price. Shapes are the share of cash per rung.
LADDER_DEPTHS = (0.0, 0.03, 0.06, 0.10)
LADDER_SHAPES = {"lump": (1.0, 0.0, 0.0, 0.0), "balanced": (0.4, 0.25, 0.2, 0.15), "patient": (0.25, 0.25, 0.25, 0.25)}
DEFAULT_SHAPE = "balanced"          # the user's choice; the model's own pick is reported next to it
LADDER_LABELS = {"lump": "现价一次买入", "balanced": "现价 40% + 回调挂单 60%", "patient": "现价 25% + 回调挂单 75%"}
LADDER_DAYS = 63
LADDER_SAMPLES = 2000
LOTS = {"512890.SS": 100}           # A-share ETFs trade in 100-unit lots; US shares in single shares
TICKS = {"512890.SS": 0.001}
MONTH = 21                          # trading days
DELAY_MONTHS = (0, 1, 2, 3)         # how long the sale proceeds take to arrive; the year still counts from today
DEFAULT_DELAY = 1
FX_FALLBACK = {"USD": 1 / 7.8, "CNY": 0.92, "HKD": 1.0}   # HKD → currency, used only when the quote fetch fails
FX_FILE = "fx_rates.json"
FX_HOURS = 6
FUND_URL = "https://fund.eastmoney.com/pingzhongdata/{code}.js"
BOND_PACING = "到账后一次申购：净值一年波动不到 1%，分批没有意义"
# Valuation timing for the dividend ETF: the index's P/E and its earnings yield over the 10-year CGB, each as a
# percentile of its own record since 2017 (the index P/E jumps at the end of 2016 with a method change).
TIMING_SYMBOL = "512890.SS"
TIMING_INDEX = "CSIH30269"          # 中证红利低波动指数, the ETF's benchmark, on Danjuan
TIMING_START = "2017-01-01"
TIMING_MIN_YEARS = 3                # percentiles need this much record before a zone is read off them
TIMING_ZONES = (0.3, 0.7)           # dearness score below → cheap, above → dear
TIMING_SHAPES = {"cheap": (1.0, 0.0, 0.0, 0.0), "dear": (0.4, 0.3, 0.3, 0.0)}   # fair keeps the chosen shape
TIMING_LABELS = {"cheap": "便宜", "fair": "合理", "dear": "偏贵"}
TIMING_PACING = {"cheap": "估值便宜：到账后一次买入，不等回调",
                 "dear": "估值偏贵：现价 40%，其余挂 −3% / −6% 各 30%，3 个月内没成交按市价补齐"}
TIMING_SHAPE_LABELS = {"cheap": "按估值：现价一次买入", "dear": "按估值：现价 40% + −3% / −6% 各 30%"}
TIMING_FILE = "dividend_valuation.json"
DANJUAN_URL = "https://danjuanfunds.com/djapi/index_eva/"
CGB_URL = ("https://datacenter-web.eastmoney.com/api/data/v1/get?reportName=RPTA_WEB_TREASURYYIELD&columns=SOLAR_DATE,EMM00166466"
           "&sortColumns=SOLAR_DATE&sortTypes=-1&pageSize=500&pageNumber={page}")
HISTORY_FILE = "target_plan_history.json"
RESULT_FILE = "target_plan_backtest.json"
CACHE_HOURS = 20
_NORMAL = NormalDist()
_START = 631152000          # 1990-01-01


# ---- history ---------------------------------------------------------------------------------------------

def _yahoo(symbol: str) -> dict[str, list[float]]:
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?period1={_START}&period2={int(time.time())}"
           "&interval=1d&events=div,splits")
    result = json.loads(get_bytes(url, timeout=30))["chart"]["result"][0]
    quote = result["indicators"]["quote"][0]
    adjusted = result["indicators"].get("adjclose", [{}])[0].get("adjclose") or quote["close"]
    rows: dict[str, list[float]] = {"ts": [], "close": []}
    for ts, close, adj in zip(result["timestamp"], quote["close"], adjusted):
        if close and adj and close > 0 and adj > 0:
            rows["ts"].append(ts)
            rows["close"].append(adj)
    return rows


def _eastmoney(symbol: str) -> dict[str, list[float]]:
    """A-share fund/stock daily closes, forward-adjusted (fqt=1): Yahoo leaves 512890's 2019 split unadjusted."""
    code, exchange = symbol.split(".")
    secid = f"{1 if exchange == 'SS' else 0}.{code}"
    url = (f"https://push2his.eastmoney.com/api/qt/stock/kline/get?secid={secid}&fields1=f1,f2,f3&fields2=f51,f53"
           "&klt=101&fqt=1&beg=0&end=20500101")
    klines = (json.loads(get_bytes(url, timeout=30)).get("data") or {}).get("klines") or []
    rows: dict[str, list[float]] = {"ts": [], "close": []}
    for line in klines:
        day, close = line.split(",")[:2]
        if float(close) > 0:
            rows["ts"].append(int(datetime.strptime(day, "%Y-%m-%d").replace(hour=7, tzinfo=UTC).timestamp()))
            rows["close"].append(float(close))
    return rows


def _fund_nav(code: str) -> dict[str, float]:
    """Accumulated NAV by date (dividends added back), from the fund's Tiantian page data."""
    text = get_bytes(FUND_URL.format(code=code), timeout=30, headers={"Referer": "https://fund.eastmoney.com/"}).decode("utf-8", "replace")
    match = re.search(r"var\s+Data_ACWorthTrend\s*=\s*(\[.*?\])\s*;", text, re.S)
    if not match:
        raise ValueError(f"{code}: accumulated NAV not found")
    return {datetime.fromtimestamp(row[0] / 1000, UTC).date().isoformat(): float(row[1])
            for row in json.loads(match.group(1)) if len(row) > 1 and row[1] not in (None, "") and float(row[1]) > 0}


def bond_basket(navs: dict[str, dict[str, float]]) -> dict[str, Any]:
    """Equal-weight index of the funds on their common dates (rebalanced daily), plus each fund's own record."""
    days = sorted(set.intersection(*(set(nav) for nav in navs.values())))
    if len(days) < 2:
        raise ValueError("bond funds share no history")
    index = [1.0]
    for a, b in zip(days, days[1:]):
        index.append(index[-1] * (1 + sum(nav[b] / nav[a] - 1 for nav in navs.values()) / len(navs)))
    funds = {}
    for code, nav in navs.items():
        own = sorted(nav)
        year_ago = next(day for day in own if day >= (datetime.fromisoformat(own[-1]) - timedelta(days=365)).date().isoformat())
        funds[code] = {"name": BOND_FUNDS.get(code, code), "nav": nav[own[-1]], "nav_date": own[-1], "start": own[0],
                       "return_1y": nav[own[-1]] / nav[year_ago] - 1, "max_drawdown": _max_drawdown([nav[d] for d in own])}
    return {"ts": [int(datetime.fromisoformat(day).replace(hour=7, tzinfo=UTC).timestamp()) for day in days], "close": index, "funds": funds}


def _danjuan(path: str) -> Any:
    return json.loads(get_bytes(DANJUAN_URL + path, timeout=30, headers={"User-Agent": "Mozilla/5.0"}))["data"]


def fetch_valuation() -> dict[str, Any]:
    """Weekly index P/E (Danjuan), today's dividend yield, and the daily 10-year CGB yield (Eastmoney, in %)."""
    pe = [[(datetime.fromtimestamp(row["ts"] / 1000, UTC) + timedelta(hours=8)).date().isoformat(), row["pe"]]
          for row in _danjuan(f"pe_history/{TIMING_INDEX}?day=all")["index_eva_pe_growths"] if row.get("pe")]
    item = next(row for row in _danjuan("dj")["items"] if row["index_code"] == TIMING_INDEX)
    cgb, page = [], 1
    while True:
        result = json.loads(get_bytes(CGB_URL.format(page=page), timeout=30))["result"]
        cgb += [[row["SOLAR_DATE"][:10], row["EMM00166466"]] for row in result["data"] if row["EMM00166466"] is not None]
        if page >= result["pages"] or cgb[-1][0] < TIMING_START:
            break
        page += 1
    if len(pe) < 52 or not cgb:
        raise ValueError("valuation history too short")
    return {"pe": pe, "cgb": sorted(cgb), "dividend_yield": item.get("yeild"), "pe_now": item.get("pe"), "fetched_at": time.time()}


def load_valuation(cache_dir: Path, refresh: bool = False) -> dict[str, Any] | None:
    """Cached like the price histories; a failed fetch serves the stale copy (flagged), or None with no copy."""
    cache = cache_dir / TIMING_FILE
    stored = json.loads(cache.read_text()) if cache.exists() else None
    if stored and not refresh and time.time() - stored["fetched_at"] < CACHE_HOURS * 3600:
        return {**stored, "stale": False}
    try:
        fresh = fetch_valuation()
    except Exception:
        return {**stored, "stale": True} if stored else None
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(fresh))
    return {**fresh, "stale": False}


def _share_at_most(values: Sequence[float], x: float) -> float:
    return sum(v <= x for v in values) / len(values)


def timing_zone(score: float) -> str:
    return "cheap" if score < TIMING_ZONES[0] else "dear" if score > TIMING_ZONES[1] else "fair"


def dividend_timing(valuation: dict[str, Any], closes: Sequence[float], ts: Sequence[int]) -> dict[str, Any] | None:
    """Dearness score = mean of the P/E percentile and (1 − the earnings-yield-spread percentile), each against the
    record up to that week. The zone table replays the same score week by week (only the past at each point)
    against the ETF's next-year return, so it shows how the zones did, not a fitted rule."""
    days = [row[0] for row in valuation["cgb"]]

    def cgb(day: str) -> float | None:
        i = bisect_right(days, day) - 1
        return valuation["cgb"][i][1] if i >= 0 else None

    weeks = [(day, pe, 100 / pe - cgb(day)) for day, pe in valuation["pe"] if day >= TIMING_START and cgb(day) is not None]
    if len(weeks) < TIMING_MIN_YEARS * 52:
        return None
    price_days = [datetime.fromtimestamp(t, UTC).date().isoformat() for t in ts]

    def price(day: str) -> float | None:
        i = bisect_right(price_days, day) - 1
        return closes[i] if i >= 0 else None

    rows = []
    for i, (day, pe, spread_) in enumerate(weeks):
        if (date.fromisoformat(day) - date.fromisoformat(weeks[0][0])).days < TIMING_MIN_YEARS * 365:
            continue
        past = weeks[:i + 1]
        score = (_share_at_most([w[1] for w in past], pe) + 1 - _share_at_most([w[2] for w in past], spread_)) / 2
        ahead = (date.fromisoformat(day) + timedelta(days=365)).isoformat()
        if day >= price_days[0] and ahead <= price_days[-1]:
            rows.append((timing_zone(score), price(ahead) / price(day) - 1))
    zones = {}
    for zone in TIMING_LABELS:
        values = sorted(r for z, r in rows if z == zone)
        zones[zone] = {"n": len(values), "n_eff": len(values) / 52, "median": values[len(values) // 2], "worst": values[0],
                       "loss": sum(v < 0 for v in values) / len(values)} if values else None
    day, pe, spread_ = weeks[-1]
    pe_pct = _share_at_most([w[1] for w in weeks], pe)
    spread_pct = _share_at_most([w[2] for w in weeks], spread_)
    score = (pe_pct + 1 - spread_pct) / 2
    zone = timing_zone(score)
    y10 = valuation["cgb"][-1][1]
    dy = valuation.get("dividend_yield")
    return {"index": TIMING_INDEX, "as_of": day, "cgb_date": valuation["cgb"][-1][0], "pe": valuation.get("pe_now") or pe, "pe_percentile": pe_pct,
            "earnings_yield": 1 / pe, "cgb_10y": y10 / 100, "spread": spread_ / 100, "spread_percentile": spread_pct,
            "dividend_yield": dy, "dividend_spread": dy - y10 / 100 if dy is not None else None,
            "score": score, "zone": zone, "zone_label": TIMING_LABELS[zone], "zones": zones, "since": weeks[0][0],
            "shape": zone if zone in TIMING_SHAPES else None, "pacing": TIMING_PACING.get(zone),
            "stale": bool(valuation.get("stale"))}


def timing_reason(timing: dict[str, Any]) -> str:
    z = timing["zones"].get(timing["zone"])
    record = (f"2020 年以来估值处在这一档的 {z['n']} 周（约 {z['n_eff']:.1f} 年），之后一年 512890 中位 {_pct(z['median'], sign=True)}、"
              f"最差 {_pct(z['worst'], sign=True)}、亏损 {_pct(z['loss'], 0)}") if z else "2020 年以来没有出现过这一档"
    dividend = (f"；股息率 {_pct(timing['dividend_yield'], 2)}，比 10 年国债高 {timing['dividend_spread'] * 100:.2f} 个百分点"
                if timing.get("dividend_yield") is not None else "")
    action = {"cheap": "到账后一次买入", "dear": "拉长分批、只挂浅档回调单", "fair": "按选定的买法"}[timing["zone"]]
    return (f"估值择时：红利低波指数市盈率 {timing['pe']:.1f} 倍，处在 {timing['since'][:4]} 年以来的 {_pct(timing['pe_percentile'], 0)} 分位；"
            f"盈利收益率比 10 年国债（{_pct(timing['cgb_10y'], 2)}）高 {timing['spread'] * 100:.1f} 个百分点，处在 {_pct(timing['spread_percentile'], 0)} 分位{dividend}。"
            f"综合判断「{timing['zone_label']}」，所以{action}。{record}。只有约 6 年的样本，分档和时间段的影响混在一起，"
            "只调整买入节奏，不改达标概率。")


def repair_splits(closes: Sequence[float]) -> list[float]:
    """Undo unadjusted splits / consolidations: a one-day ratio outside 0.6–1.8 rescales everything before it."""
    fixed = list(closes)
    for index in range(len(fixed) - 1, 0, -1):
        ratio = fixed[index] / fixed[index - 1]
        if ratio < 0.6 or ratio > 1.8:
            for earlier in range(index):
                fixed[earlier] *= ratio
    return fixed


def fetch_history(symbol: str) -> dict[str, list[float]]:
    if symbol == BOND:
        return bond_basket({code: _fund_nav(code) for code in BOND_FUNDS})
    rows = _eastmoney(symbol) if symbol.endswith((".SS", ".SZ")) else _yahoo(symbol)
    rows["close"] = repair_splits(rows["close"])
    return rows


def load_histories(cache_dir: Path, symbols: Sequence[str], refresh: bool = False) -> dict[str, dict[str, list[float]]]:
    cache = cache_dir / HISTORY_FILE
    stored: dict[str, Any] = json.loads(cache.read_text()) if cache.exists() else {}
    fresh = time.time() - stored.get("fetched_at", 0) < CACHE_HOURS * 3600
    if refresh or not fresh or any(symbol not in stored.get("symbols", {}) for symbol in symbols):
        data = dict(stored.get("symbols", {}))
        for symbol in symbols:
            try:
                data[symbol] = fetch_history(symbol)
            except Exception:
                if symbol not in data:       # keep a stale copy over nothing
                    raise
        stored = {"fetched_at": time.time(), "symbols": data}
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(stored))
    return {symbol: stored["symbols"][symbol] for symbol in symbols}


# ---- model -----------------------------------------------------------------------------------------------

def shrink_years(symbol: str) -> float:
    return SHRINK_YEARS_STOCK if symbol in SINGLE_STOCKS else SHRINK_YEARS


def long_run(closes: Sequence[float], t: int | None = None, years0: float = SHRINK_YEARS) -> dict[str, float]:
    """Shrunk expected one-year log return from the record up to index ``t``."""
    t = len(closes) - 1 if t is None else t
    years = t / YEAR
    history = math.log(closes[t] / closes[0]) / years if years > 0 else PRIOR_LOG_RETURN
    weight = years / (years + years0)
    return {"years": years, "history": history, "weight": weight, "shrink_years": years0,
            "mu": weight * history + (1 - weight) * PRIOR_LOG_RETURN}


def spread(sigma_annual: float, kappa: float = KAPPA) -> float:
    return sigma_annual * math.sqrt(1 + kappa)


def horizon_spread(s: float, h: float, kappa: float = KAPPA) -> float:
    """Spread of the log return over ``h`` years (h <= 1) given the one-year spread s = σ√(1+κ): the diffusion
    grows with h and the per-path drift with h², so s_h = σ√(h(1+κh))."""
    return s * math.sqrt(h * (1 + kappa * h) / (1 + kappa))


def horizon_assets(assets: dict[str, dict[str, Any]], h: float) -> dict[str, dict[str, Any]]:
    """The same assets seen over ``h`` years instead of one: median log drift scales with h."""
    if h == 1:
        return assets
    return {k: {**a, "mu": a["mu"] * h, "spread": horizon_spread(a["spread"], h)} for k, a in assets.items()}


def delay_horizon(delay_months: int) -> float:
    """Share of the year left to be invested when the money arrives ``delay_months`` from now."""
    return (YEAR - delay_months * MONTH) / YEAR


def hit_probability(mu: float, s: float, target: float) -> float:
    return 1 - _NORMAL.cdf((math.log1p(target) - mu) / s)


def quantile(mu: float, s: float, share: float) -> float:
    return math.exp(mu + s * _NORMAL.inv_cdf(share)) - 1


def state(closes: Sequence[float], t: int | None = None) -> dict[str, float | None]:
    t = len(closes) - 1 if t is None else t
    price = closes[t]
    ma200 = sum(closes[t - 199:t + 1]) / 200 if t >= 199 else None
    high = max(closes[max(0, t - YEAR + 1):t + 1])
    return {"price": price, "ma200": ma200, "ma200_gap": price / ma200 - 1 if ma200 else None, "drawdown": price / high - 1}


def action(probability: float, ma200_gap: float | None) -> str:
    if (ma200_gap is not None and ma200_gap < 0) or probability < REDUCE_PROBABILITY:
        return "reduce"
    if probability >= ADD_PROBABILITY:
        return "add"
    return "hold"


def assess(closes: Sequence[float], target: float, t: int | None = None, years0: float = SHRINK_YEARS) -> dict[str, Any]:
    t = len(closes) - 1 if t is None else t
    run = long_run(closes, t, years0)
    volatility = sp.daily_volatility(closes[max(0, t - YEAR):t + 1])
    s = spread(volatility["annual"])
    now = state(closes, t)
    probability = hit_probability(run["mu"], s, target)
    return {
        "mu": run["mu"], "long_run": run, "volatility": volatility, "spread": s, "state": now,
        "probability": probability, "loss10": 1 - hit_probability(run["mu"], s, -0.10),
        "p10": quantile(run["mu"], s, 0.1), "p50": quantile(run["mu"], s, 0.5), "p90": quantile(run["mu"], s, 0.9),
        "action": action(probability, now["ma200_gap"]),
    }


def assess_bond(closes: Sequence[float], ts: Sequence[int], target: float) -> dict[str, Any]:
    """A bond fund earns roughly its running yield, so the centre is the basket's last-year return rather than a
    shrunk long-run drift; the spread is its own NAV volatility with the same drift-uncertainty factor."""
    start = next(i for i, x in enumerate(ts) if x >= ts[-1] - 365 * 86_400)
    mu = math.log(closes[-1] / closes[start])
    years = (ts[-1] - ts[0]) / (365.25 * 86_400)
    volatility = sp.daily_volatility(closes[-YEAR - 1:])
    s = spread(volatility["annual"])
    probability = hit_probability(mu, s, target)
    return {
        "mu": mu, "long_run": {"years": years, "history": math.log(closes[-1] / closes[0]) / years, "weight": 0.0, "shrink_years": 0.0, "mu": mu},
        "volatility": volatility, "spread": s, "state": state(closes), "probability": probability,
        "loss10": 1 - hit_probability(mu, s, -0.10),
        "p10": quantile(mu, s, 0.1), "p50": quantile(mu, s, 0.5), "p90": quantile(mu, s, 0.9),
        "action": "hold", "max_drawdown": _max_drawdown(closes),
    }


def _bucket(now: dict[str, float | None]) -> tuple[bool, str]:
    drawdown = now["drawdown"] or 0.0
    depth = "near_high" if drawdown > -0.1 else "dip" if drawdown > -0.2 else "deep"
    return (now["ma200_gap"] or 0.0) >= 0, depth


DEPTH_LABELS = {"near_high": "距一年高点不到 10%", "dip": "比一年高点低 10–20%", "deep": "比一年高点低 20% 以上"}


def similar_states(closes: Sequence[float], target: float, current: dict[str, float | None]) -> dict[str, Any]:
    """How one-year returns turned out from past days in the same trend/drawdown state, versus all days."""
    wanted = _bucket(current)
    same: list[float] = []
    every: list[float] = []
    for t in range(YEAR, len(closes) - YEAR, 5):
        forward = closes[t + YEAR] / closes[t] - 1
        every.append(forward)
        if _bucket(state(closes, t)) == wanted:
            same.append(forward)

    def stats(values: list[float]) -> dict[str, Any] | None:
        if not values:
            return None
        ordered = sorted(values)
        return {"n": len(values), "n_eff": len(values) * 5 / YEAR, "hit": sum(v >= target for v in values) / len(values),
                "loss10": sum(v <= -0.1 for v in values) / len(values), "median": ordered[len(ordered) // 2]}

    return {"above_ma200": wanted[0], "depth": wanted[1], "same": stats(same), "all": stats(every)}


def _pct(value: float | None, digits: int = 1, sign: bool = False) -> str:
    if value is None:
        return "—"
    return f"{value * 100:{'+' if sign else ''}.{digits}f}%"


def reasons(symbol: str, result: dict[str, Any], target: float, context: dict[str, Any]) -> list[str]:
    run, now, vol = result["long_run"], result["state"], result["volatility"]
    lines = [
        f"长期收益：自有记录 {run['years']:.1f} 年，年化对数收益 {_pct(run['history'])}；按 {run['shrink_years']:.0f} 年的先验权重向 "
        f"{_pct(PRIOR_LOG_RETURN)} 收缩（历史占 {run['weight'] * 100:.0f}%），得到一年期中位预期 {_pct(result['p50'], sign=True)}。",
        f"波动：当前年化 {_pct(vol['annual'])}（近期 EWMA {_pct(vol['ewma_annual'])}，一年实现 {_pct(vol['realized_annual'])}），"
        f"加上趋势不确定性后一年的 10%–90% 区间是 {_pct(result['p10'], sign=True)} 到 {_pct(result['p90'], sign=True)}。",
    ]
    if now["ma200_gap"] is not None:
        side = "上方" if now["ma200_gap"] >= 0 else "下方"
        lines.append(f"趋势：价格在 200 日均线{side} {_pct(abs(now['ma200_gap']))}，距一年高点 {_pct(now['drawdown'], sign=True)}。")
    similar = context.get("similar")
    if similar and similar.get("same") and similar.get("all"):
        same, every = similar["same"], similar["all"]
        trend = "均线上方" if similar["above_ma200"] else "均线下方"
        source = context.get("similar_source") or symbol
        lines.append(
            f"历史相似状态（{source}，{trend}且{DEPTH_LABELS[similar['depth']]}，约 {same['n_eff']:.0f} 个独立年份）："
            f"一年达到 {_pct(target, 0)} 的比例 {_pct(same['hit'], 0)}、跌超 10% 的比例 {_pct(same['loss10'], 0)}；"
            f"全部日子是 {_pct(every['hit'], 0)} / {_pct(every['loss10'], 0)}。样本少，只作风险参考。")
    valuation = context.get("valuation") or {}
    if valuation.get("forwardPE"):
        extra = f"，过去 4 季财报超预期 {valuation['beat_count']}/{valuation['beat_window']} 次" if valuation.get("beat_window") else ""
        lines.append(f"估值：远期市盈率 {valuation['forwardPE']:.1f} 倍（静态 {valuation.get('trailingPE') or 0:.1f} 倍）{extra}。估值不进入概率模型，只作背景。")
    if symbol.endswith(".SS"):
        lines.append("红利低波以人民币计价，收益按前复权价格计（基金至今未现金分红，成分股股息留在净值里）；未计人民币汇率。与美股相关性低，主要作用是降低组合波动。")
    news = context.get("news")
    if news and news["count"]:
        lines.append(f"资讯：近 7 天 {news['count']} 条相关报道，偏正面 {news['positive']}、偏负面 {news['negative']}（按标题关键词粗分），不进入概率模型。")
    verdict = {
        "add": f"达到目标的模型概率 {_pct(result['probability'], 0)}，且趋势在均线上方：可以按计划分批买入，不必一次买满。",
        "hold": f"达到目标的模型概率 {_pct(result['probability'], 0)}，处于中间区：保持现有仓位或定投，不追加大额。",
        "reduce": (f"价格在 200 日均线下方，" if (now["ma200_gap"] or 0) < 0 else "")
                  + f"达到目标的模型概率 {_pct(result['probability'], 0)}：新资金暂缓或分更长时间买入，已有仓位可适度降低。",
    }[result["action"]]
    lines.append("结论：" + verdict + "回测显示这类择时信号跨周期并不稳定地胜过一直持有，主要用来控制节奏与风险。")
    return lines


def bond_reasons(result: dict[str, Any], funds: dict[str, dict[str, Any]], target: float) -> list[str]:
    run, vol = result["long_run"], result["volatility"]
    names = "、".join(f"{f['name']}（{code}，近一年 {_pct(f['return_1y'], 2, True)}，最大回撤 {_pct(abs(f['max_drawdown']), 2)}）" for code, f in funds.items())
    return [
        f"构成：{names}，等权。两只都开放申购和赎回、没有持有期锁定，规模在 10 亿以上。",
        f"预期收益：纯债基金的收益主要来自票息，所以用组合近一年的收益 {_pct(math.exp(result['mu']) - 1, 2, True)} 作中枢，不向股票的 "
        f"{_pct(PRIOR_LOG_RETURN)} 先验收缩；自 {run['years']:.1f} 年前起的年化是 {_pct(math.exp(run['history']) - 1, 2)}。",
        f"波动：净值年化波动 {_pct(vol['annual'], 2)}，一年 10%–90% 区间 {_pct(result['p10'], 2, True)} 到 {_pct(result['p90'], 2, True)}；"
        f"组合历史最大回撤 {_pct(abs(result['max_drawdown']), 2)}。债市急跌（如 2022 年底赎回潮）时短期回撤会比这个模型估得大。",
        f"结论：一年达到 {_pct(target, 0)} 的模型概率 {_pct(result['probability'], 0)}。它的作用是压低组合波动、提高一年不亏的概率，"
        "不是提高收益；目标定在 4% 以上时单靠它基本达不到。",
    ]


# ---- allocation ------------------------------------------------------------------------------------------

def weekly_returns(histories: dict[str, dict[str, list[float]]], symbols: Sequence[str], years: int = 3) -> dict[str, list[float]]:
    weeks: dict[str, dict[tuple[int, int], float]] = {}
    for symbol in symbols:
        series: dict[tuple[int, int], float] = {}
        for ts, close in zip(histories[symbol]["ts"], histories[symbol]["close"]):
            series[tuple(datetime.fromtimestamp(ts, UTC).isocalendar()[:2])] = close
        weeks[symbol] = series
    common = sorted(set.intersection(*(set(series) for series in weeks.values())))[-(52 * years + 1):]
    return {symbol: [math.log(weeks[symbol][b] / weeks[symbol][a]) for a, b in zip(common, common[1:])] for symbol in symbols}


def correlations(returns: dict[str, list[float]]) -> dict[str, dict[str, float]]:
    def corr(a: list[float], b: list[float]) -> float:
        ma, mb = sum(a) / len(a), sum(b) / len(b)
        cov = sum((x - ma) * (y - mb) for x, y in zip(a, b))
        va, vb = sum((x - ma) ** 2 for x in a), sum((y - mb) ** 2 for y in b)
        return cov / math.sqrt(va * vb) if va and vb else 0.0
    return {a: {b: 1.0 if a == b else corr(returns[a], returns[b]) for b in returns} for a in returns}


def portfolio(weights: dict[str, float], assets: dict[str, dict[str, float]], corr: dict[str, dict[str, float]], target: float) -> dict[str, float]:
    """One-year portfolio return as a lognormal matched to the mean and variance of the weighted assets."""
    means = {k: math.exp(a["mu"] + a["spread"] ** 2 / 2) - 1 for k, a in assets.items()}
    sd = {k: math.sqrt(math.exp(a["spread"] ** 2) - 1) * (1 + means[k]) for k, a in assets.items()}
    mean = sum(w * means[k] for k, w in weights.items())
    variance = sum(weights[a] * weights[b] * sd[a] * sd[b] * corr[a][b] for a in weights for b in weights)
    s2 = math.log1p(variance / (1 + mean) ** 2)
    s, mu = math.sqrt(s2), math.log1p(mean) - s2 / 2
    return {"mean": mean, "mu": mu, "spread": s, "probability": hit_probability(mu, s, target),
            "p10": quantile(mu, s, 0.1), "p20": quantile(mu, s, 0.2), "p50": quantile(mu, s, 0.5), "p90": quantile(mu, s, 0.9),
            "loss10": 1 - hit_probability(mu, s, -0.10), "nonneg": hit_probability(mu, s, 0.0)}


def _grid(symbols: Sequence[str]) -> Iterable[dict[str, float]]:
    def rec(index: int, left: int) -> Iterable[list[int]]:
        if index == len(symbols) - 1:
            yield [left]
            return
        for units in range(left + 1):
            for rest in rec(index + 1, left - units):
                yield [units, *rest]
    for units in rec(0, GRID):
        yield {symbol: unit / GRID for symbol, unit in zip(symbols, units)}


def allocate(assets: dict[str, dict[str, float]], corr: dict[str, dict[str, float]], target: float) -> dict[str, Any]:
    symbols = list(assets)
    feasible = []
    for weights in _grid(symbols):
        if (any(weights.get(symbol, 0) > MAX_SINGLE_STOCK + 1e-9 for symbol in SINGLE_STOCKS)
                or min(w for s, w in weights.items() if s not in OPTIONAL) < MIN_WEIGHT - 1e-9):
            continue
        stats = portfolio(weights, assets, corr, target)
        if stats["p10"] >= P10_FLOOR:
            feasible.append((weights, stats))
    if not feasible:
        raise ValueError("没有满足回撤约束的组合")
    # The surface is flat near the top; within a point of the best probability, take the steadiest mix.
    top = max(stats["probability"] for _, stats in feasible)
    best_weights, best = max((row for row in feasible if row[1]["probability"] >= top - TIE_PROBABILITY), key=lambda row: row[1]["p10"])
    references = {"equal": {s: 1 / len(symbols) for s in symbols}}
    for symbol in ("QQQ", "512890.SS", BOND):
        if symbol in assets:
            references[symbol] = {s: float(s == symbol) for s in symbols}
    return {
        "weights": best_weights, "stats": best,
        "constraints": {"max_single_stock": MAX_SINGLE_STOCK, "min_weight": MIN_WEIGHT, "p10_floor": P10_FLOOR, "grid": 1 / GRID,
                        "tie": TIE_PROBABILITY},
        "unconstrained_best": max((portfolio(w, assets, corr, target)["probability"] for w in _grid(symbols)
                                   if all(w.get(x, 0) <= MAX_SINGLE_STOCK + 1e-9 for x in SINGLE_STOCKS)), default=None),
        "references": {name: {"weights": w, "stats": portfolio(w, assets, corr, target)} for name, w in references.items()},
        "frontier": sorted(({"weights": w, **{k: v for k, v in stats.items() if k in ("probability", "p10", "p50")}}
                            for w, stats in feasible), key=lambda row: -row["probability"])[:8],
    }


SUMMARY_KEYS = ("probability", "nonneg", "p10", "p20", "p50", "p90", "loss10")


def safe_allocate(assets: dict[str, dict[str, float]], corr: dict[str, dict[str, float]], target: float) -> dict[str, Any]:
    """Steady mix: any subset of the assets (single stocks still capped), P(year >= 0) >= SAFE_NONNEG and
    P10 >= SAFE_P10_FLOOR, then the highest probability of the target; within a point of it, the most likely
    to end flat or better. If nothing passes, the mix most likely to end flat or better, flagged ``relaxed``."""
    symbols = list(assets)
    rows = []
    for weights in _grid(symbols):
        if any(weights.get(s, 0) > MAX_SINGLE_STOCK + 1e-9 for s in SINGLE_STOCKS):
            continue
        stats = portfolio(weights, assets, corr, target)
        rows.append((weights, stats, stats["nonneg"] >= SAFE_NONNEG and stats["p10"] >= SAFE_P10_FLOOR))
    feasible = [row for row in rows if row[2]]
    if feasible:
        top = max(stats["probability"] for _, stats, _ in feasible)
        weights, stats, _ = max((row for row in feasible if row[1]["probability"] >= top - TIE_PROBABILITY), key=lambda row: row[1]["nonneg"])
    else:
        weights, stats, _ = max(rows, key=lambda row: row[1]["nonneg"])
    # The best mix for each set of holdings, so “QQQ + dividend only” can be read off directly.
    best: dict[tuple[str, ...], tuple[tuple[bool, float], dict[str, float], dict[str, float], bool]] = {}
    for w, s, ok in rows:
        key = tuple(x for x in symbols if w[x] > 0)
        rank = (ok, s["probability"] if ok else s["nonneg"])
        if key not in best or rank > best[key][0]:
            best[key] = (rank, w, s, ok)
    options = sorted(({"holdings": list(key), "weights": w, "ok": ok, **{k: s[k] for k in SUMMARY_KEYS}}
                      for key, (_, w, s, ok) in best.items()), key=lambda row: (not row["ok"], -row["probability"]))
    return {"weights": weights, "stats": stats, "relaxed": not feasible, "options": options,
            "constraints": {"nonneg": SAFE_NONNEG, "p10_floor": SAFE_P10_FLOOR, "max_single_stock": MAX_SINGLE_STOCK,
                            "grid": 1 / GRID, "tie": TIE_PROBABILITY}}


def mix_history(histories: dict[str, dict[str, list[float]]], weights: dict[str, float], target: float,
                days: int = YEAR) -> dict[str, Any] | None:
    """What fixed weights bought and held for ``days`` actually did, one start every STEP days on the common record."""
    held = [s for s, w in weights.items() if w > 0]
    if not held:
        return None
    ts, closes = _aligned(histories, held)
    if len(ts) <= days:
        return None
    returns = [sum(weights[s] * closes[s][t + days] / closes[s][t] for s in held) - 1 for t in range(0, len(ts) - days, STEP)]
    ordered = sorted(returns)
    return {"start": datetime.fromtimestamp(ts[0], UTC).date().isoformat(), "n": len(returns), "n_eff": len(returns) * STEP / YEAR,
            "hit_rate": sum(r >= target for r in returns) / len(returns), "nonneg_rate": sum(r >= 0 for r in returns) / len(returns),
            "worst": ordered[0], "median": ordered[len(ordered) // 2]}


# ---- buy ladder ------------------------------------------------------------------------------------------

def tick_for(symbol: str) -> float:
    return TICKS.get(symbol, 0.01)


def ladder_levels(symbol: str, price: float) -> list[float]:
    tick = tick_for(symbol)
    return [price] + [round(math.floor(price * (1 - depth) / tick + 1e-9) * tick, 6) for depth in LADDER_DEPTHS[1:]]


def dip_probability(price: float, level: float, sigma_daily: float, mu: float, days: float, kappa: float = KAPPA) -> float:
    """P(the price trades at or below ``level`` within ``days``): the reflection formula on the mirrored path,
    averaged over the same drift uncertainty as everything else (median log drift ``mu`` a year)."""
    if level >= price:
        return 1.0
    barrier = math.log(price / level)
    tau = sp.drift_spread(sigma_daily, kappa, days)
    center = mu / YEAR
    return sum(sp._touch_given_drift(barrier, -(center + tau * x), sigma_daily, days) for x in sp.DRIFT_NODES) / len(sp.DRIFT_NODES)


def ladder_return(levels_rel: Sequence[float], shape: Sequence[float], low: float, window_end: float, final: float) -> float:
    """One-year return on cash split by ``shape``: a rung fills at its level if the window's low reached it, else at
    the window-end price. All prices relative to today's (1.0)."""
    units = sum(w / (level if low <= level else window_end) for level, w in zip(levels_rel, shape) if w)
    return units * final - 1


def simulate_ladder(price: float, levels: Sequence[float], sigma_daily: float, mu: float, target: float,
                    days: int = LADDER_DAYS, samples: int = LADDER_SAMPLES, seed: int = 7, horizon: int = YEAR,
                    extra: dict[str, Sequence[float]] | None = None) -> dict[str, Any]:
    """Monte Carlo of each shape over ``horizon`` sessions from the day the money arrives (a year by default): daily log steps with a per-path drift (kappa), the low of the first
    ``days`` sessions decides fills, the rest of the year is one draw. Daily closes only, so fills are slightly
    understated against intraday lows; waiting cash earns nothing."""
    rng = random.Random(seed)
    tau = sp.drift_spread(sigma_daily, KAPPA, horizon)
    rel = [level / price for level in levels]
    every = {**LADDER_SHAPES, **(extra or {})}
    returns: dict[str, list[float]] = {name: [] for name in every}
    fills = [0] * len(rel)
    for _ in range(samples):
        nu = mu / YEAR + tau * rng.gauss(0, 1)
        log = low = 0.0
        for _ in range(days):
            log += nu + sigma_daily * rng.gauss(0, 1)
            low = min(low, log)
        final = log + nu * (horizon - days) + sigma_daily * math.sqrt(horizon - days) * rng.gauss(0, 1)
        low_rel, end_rel, final_rel = math.exp(low), math.exp(log), math.exp(final)
        for i, level in enumerate(rel):
            fills[i] += low_rel <= level
        for name, shape in every.items():
            returns[name].append(ladder_return(rel, shape, low_rel, end_rel, final_rel))
    shapes = {}
    for name, values in returns.items():
        ordered = sorted(values)
        shapes[name] = {"probability": sum(v >= target for v in values) / samples, "nonneg": sum(v >= 0 for v in values) / samples,
                        "mean": sum(values) / samples, "p10": ordered[samples // 10], "p50": ordered[samples // 2]}
    top = max(row["probability"] for name, row in shapes.items() if name in LADDER_SHAPES)
    # The model's pick: within a point of the best chance of the target, the shape with the best bad decile.
    model_pick = max((name for name, row in shapes.items() if name in LADDER_SHAPES and row["probability"] >= top - TIE_PROBABILITY),
                     key=lambda name: shapes[name]["p10"])
    return {"shapes": shapes, "model_pick": model_pick, "fill_rates": [count / samples for count in fills]}


def ladder_orders(symbol: str, price: float, levels: Sequence[float], shape: Sequence[float], amount: float,
                  fill: Sequence[float]) -> dict[str, Any]:
    """Concrete orders for ``amount`` (in the asset's currency): rounded down to whole lots; leftover cash reported."""
    lot = LOTS.get(symbol, 1)
    rows, spent = [], 0.0
    for i, (level, share) in enumerate(zip(levels, shape)):
        if not share:
            continue
        units = int(amount * share / level // lot) * lot
        spent += units * level
        rows.append({"kind": "market" if i == 0 else "limit", "depth": LADDER_DEPTHS[i], "price": level, "units": units,
                     "amount": units * level, "fill_probability": fill[i]})
    return {"lot": lot, "orders": rows, "spent": spent, "leftover": amount - spent}


def ladder_replay(closes: Sequence[float], target: float, start: int = 0) -> dict[str, Any] | None:
    """The same shapes on the real record: a start every STEP days, fills from the next LADDER_DAYS closes."""
    rel_levels = [1 - depth for depth in LADDER_DEPTHS]
    results: dict[str, list[float]] = {name: [] for name in LADDER_SHAPES}
    fills = [0] * len(rel_levels)
    starts = range(start, len(closes) - YEAR, STEP)
    for t in starts:
        p0 = closes[t]
        low = min(closes[t:t + LADDER_DAYS + 1]) / p0   # today's close counts: the first rung is a market buy
        end, final = closes[t + LADDER_DAYS] / p0, closes[t + YEAR] / p0
        for i, level in enumerate(rel_levels):
            fills[i] += low <= level
        for name, shape in LADDER_SHAPES.items():
            results[name].append(ladder_return(rel_levels, shape, low, end, final))
    n = len(results["lump"])
    if not n:
        return None
    out = {}
    for name, values in results.items():
        ordered = sorted(values)
        out[name] = {"mean": sum(values) / n, "hit_rate": sum(v >= target for v in values) / n, "nonneg_rate": sum(v >= 0 for v in values) / n,
                     "p10": ordered[n // 10], "beats_lump": sum(v > lump for v, lump in zip(values, results["lump"])) / n}
    return {"n": n, "n_eff": n * STEP / YEAR, "fill_rates": [count / n for count in fills], "shapes": out}


def ladder_verdict(replays: dict[str, dict[str, Any]]) -> str:
    """Plain reading of the replay: how often the ladder beat buying at once, and what it did to the mean."""
    rows = [r for r in replays.values() if r]
    if not rows:
        return ""
    beats = sum(r["shapes"]["balanced"]["beats_lump"] * r["n"] for r in rows) / sum(r["n"] for r in rows)
    mean_gap = sum((r["shapes"]["balanced"]["mean"] - r["shapes"]["lump"]["mean"]) * r["n"] for r in rows) / sum(r["n"] for r in rows)
    p10_gap = sum((r["shapes"]["balanced"]["p10"] - r["shapes"]["lump"]["p10"]) * r["n"] for r in rows) / sum(r["n"] for r in rows)
    return (f"历史上「现价 40% + 回调挂单」在 {beats * 100:.0f}% 的起点胜过一次买入，平均一年收益{'高' if mean_gap >= 0 else '低'} {abs(mean_gap) * 100:.1f} 个百分点，"
            f"悲观 10% {'好' if p10_gap >= 0 else '差'} {abs(p10_gap) * 100:.1f} 个百分点：分批挂单换来的是少后悔，不是更高收益。")


def fetch_fx(currency: str) -> float:
    """HKD → ``currency`` from Yahoo's last close."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/HKD{currency}=X?range=5d&interval=1d"
    closes = [c for c in json.loads(get_bytes(url, timeout=15))["chart"]["result"][0]["indicators"]["quote"][0]["close"] if c]
    return float(closes[-1])


def fx_rates(cache_dir: Path, currencies: Iterable[str]) -> dict[str, dict[str, Any]]:
    cache = cache_dir / FX_FILE
    stored: dict[str, Any] = json.loads(cache.read_text()) if cache.exists() else {}
    out, changed = {}, False
    for currency in set(currencies):
        if currency == "HKD":
            out[currency] = {"rate": 1.0, "source": "same"}
            continue
        row = stored.get(currency)
        if not row or time.time() - row["fetched_at"] > FX_HOURS * 3600:
            try:
                row = {"rate": fetch_fx(currency), "fetched_at": time.time(), "source": "yahoo"}
                stored[currency], changed = row, True
            except Exception:
                row = row or {"rate": FX_FALLBACK[currency], "fetched_at": 0, "source": "fallback"}
        out[currency] = {"rate": row["rate"], "source": row["source"],
                         "as_of": datetime.fromtimestamp(row["fetched_at"], UTC).isoformat(timespec="minutes") if row["fetched_at"] else None}
    if changed:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(stored))
    return out


# ---- backtest --------------------------------------------------------------------------------------------

def _auc(scores: Sequence[float], outcomes: Sequence[bool]) -> float | None:
    pairs = sorted(zip(scores, outcomes))
    positives = sum(outcomes)
    negatives = len(outcomes) - positives
    if not positives or not negatives:
        return None
    rank_sum, index = 0.0, 0
    while index < len(pairs):
        end = index
        while end < len(pairs) and pairs[end][0] == pairs[index][0]:
            end += 1
        average_rank = (index + end + 1) / 2
        rank_sum += average_rank * sum(1 for _, hit in pairs[index:end] if hit)
        index = end
    return (rank_sum - positives * (positives + 1) / 2) / (positives * negatives)


def _max_drawdown(values: Sequence[float]) -> float:
    peak, worst = values[0], 0.0
    for value in values:
        peak = max(peak, value)
        worst = min(worst, value / peak - 1)
    return worst


def _aligned(histories: dict[str, dict[str, list[float]]], symbols: Sequence[str]) -> tuple[list[int], dict[str, list[float]]]:
    days = {symbol: {datetime.fromtimestamp(ts, UTC).date(): close for ts, close in zip(h["ts"], h["close"])}
            for symbol, h in ((s, histories[s]) for s in symbols)}
    common = sorted(set.intersection(*(set(series) for series in days.values())))
    return [int(datetime(d.year, d.month, d.day, tzinfo=UTC).timestamp()) for d in common], {s: [days[s][d] for d in common] for s in symbols}


def signal_rows(symbol: str, closes: Sequence[float], ts: Sequence[int], target: float) -> list[dict[str, Any]]:
    rows = []
    for t in range(MIN_HISTORY, len(closes) - YEAR, STEP):
        result = assess(closes, target, t, shrink_years(symbol))
        forward = closes[t + YEAR] / closes[t] - 1
        rows.append({"symbol": symbol, "year": datetime.fromtimestamp(ts[t], UTC).year, "probability": result["probability"],
                     "loss10_p": result["loss10"], "action": result["action"], "forward": forward})
    return rows


def summarize_signals(rows: Sequence[dict[str, Any]], target: float) -> dict[str, Any]:
    def block(subset: Sequence[dict[str, Any]]) -> dict[str, Any] | None:
        if not subset:
            return None
        hits = [row["forward"] >= target for row in subset]
        probs = [row["probability"] for row in subset]
        rate = sum(hits) / len(hits)
        brier = sum((p - h) ** 2 for p, h in zip(probs, hits)) / len(hits)
        ordered = sorted(row["forward"] for row in subset)
        return {"n": len(subset), "n_eff": len(subset) * STEP / YEAR, "predicted": sum(probs) / len(probs), "realized": rate,
                "brier": brier, "brier_climatology": rate * (1 - rate), "auc": _auc(probs, hits),
                "loss10_predicted": sum(row["loss10_p"] for row in subset) / len(subset),
                "loss10_realized": sum(row["forward"] <= -0.1 for row in subset) / len(subset),
                "median_return": ordered[len(ordered) // 2], "mean_return": sum(ordered) / len(ordered)}

    buckets = []
    for low, high in ((0.0, 0.3), (0.3, 0.4), (0.4, 0.5), (0.5, 0.6), (0.6, 1.01)):
        subset = [row for row in rows if low <= row["probability"] < high]
        if subset:
            buckets.append({"low": low, "high": min(high, 1.0), **block(subset)})
    eras = {"before_2010": [r for r in rows if r["year"] < 2010], "since_2010": [r for r in rows if r["year"] >= 2010]}
    return {
        "all": block(rows),
        "buckets": buckets,
        "actions": {name: block([row for row in rows if row["action"] == name]) for name in ACTION_WEIGHTS},
        "actions_by_era": {era: {name: block([row for row in subset if row["action"] == name]) for name in ACTION_WEIGHTS}
                           for era, subset in eras.items()},
        "eras": {era: block(subset) for era, subset in eras.items()},
    }


def portfolio_replay(histories: dict[str, dict[str, list[float]]], symbols: Sequence[str], target: float) -> dict[str, Any]:
    """Monthly rebalanced sleeves: action-tilted weights vs equal weight vs buy-and-hold from the first day."""
    ts, closes = _aligned(histories, symbols)
    # Each asset's model uses its own full record up to the date, so long-run estimates are not truncated.
    offsets = {}
    for symbol in symbols:
        index = {datetime.fromtimestamp(value, UTC).date(): i for i, value in enumerate(histories[symbol]["ts"])}
        offsets[symbol] = [index.get(datetime.fromtimestamp(value, UTC).date()) for value in ts]
    full = {symbol: histories[symbol]["close"] for symbol in symbols}
    start = next(i for i in range(len(ts)) if all(offsets[s][i] is not None and offsets[s][i] >= MIN_HISTORY for s in symbols))
    values = {"rule": [1.0], "equal": [1.0], "hold": [1.0]}
    hold_units = {s: (1 / len(symbols)) / closes[s][start] for s in symbols}
    dates = [ts[start]]
    for t in range(start, len(ts) - 1, STEP):
        end = min(t + STEP, len(ts) - 1)
        growth = {s: closes[s][end] / closes[s][t] for s in symbols}
        signals = {}
        for s in symbols:
            own_t = offsets[s][t]
            signals[s] = assess(full[s], target, own_t, shrink_years(s))["action"] if own_t is not None else "hold"
        raw = {s: ACTION_WEIGHTS[signals[s]] for s in symbols}
        total = sum(raw.values())
        values["rule"].append(values["rule"][-1] * sum(raw[s] / total * growth[s] for s in symbols))
        values["equal"].append(values["equal"][-1] * sum(growth[s] / len(symbols) for s in symbols))
        values["hold"].append(sum(hold_units[s] * closes[s][end] for s in symbols))
        dates.append(ts[end])
    years = (dates[-1] - dates[0]) / (365.25 * 86400)
    out = {}
    for name, series in values.items():
        yearly = [series[i + 12] / series[i] - 1 for i in range(len(series) - 12)]
        out[name] = {"cagr": series[-1] ** (1 / years) - 1 if years > 0 else None, "max_drawdown": _max_drawdown(series),
                     "hit_rate": sum(r >= target for r in yearly) / len(yearly) if yearly else None,
                     "loss10_rate": sum(r <= -0.1 for r in yearly) / len(yearly) if yearly else None, "final": series[-1]}
    return {"symbols": list(symbols), "start": datetime.fromtimestamp(dates[0], UTC).date().isoformat(),
            "end": datetime.fromtimestamp(dates[-1], UTC).date().isoformat(), "years": years, "strategies": out}


def run_backtest(cache_dir: Path, target: float = DEFAULT_TARGET, refresh: bool = False) -> dict[str, Any]:
    started = time.time()
    symbols = (*FOCUS, *BACKTEST_EXTRA)
    # The bond basket rides along so a refresh keeps it current; its signals are not backtested.
    histories = load_histories(cache_dir, (*PLAN, *BACKTEST_EXTRA), refresh=refresh)
    per_symbol = {}
    pooled: list[dict[str, Any]] = []
    for symbol in symbols:
        h = histories[symbol]
        rows = signal_rows(symbol, h["close"], h["ts"], target)
        if symbol != "QQQ":          # QQQ overlaps ^NDX; pool the longer index instead
            pooled.extend(rows)
        per_symbol[symbol] = {"start": datetime.fromtimestamp(h["ts"][0], UTC).date().isoformat(), **summarize_signals(rows, target)}
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "elapsed_seconds": round(time.time() - started, 1),
        "target": target,
        "model": {"prior": PRIOR_LOG_RETURN, "shrink_years": SHRINK_YEARS, "shrink_years_stock": SHRINK_YEARS_STOCK, "kappa": KAPPA, "step": STEP,
                  "add_probability": ADD_PROBABILITY, "reduce_probability": REDUCE_PROBABILITY, "weights": ACTION_WEIGHTS},
        "pooled_symbols": [s for s in symbols if s != "QQQ"],
        "pooled": summarize_signals(pooled, target),
        "per_symbol": per_symbol,
        "portfolios": {
            "focus": portfolio_replay(histories, FOCUS, target),
            "long": portfolio_replay(histories, ("^NDX", "MSFT", "GOOGL"), target),
        },
        "ladders": {symbol: ladder_replay(histories[symbol]["close"], target) for symbol in (*FOCUS, "^NDX")},
        "ladder_model": {"depths": list(LADDER_DEPTHS), "shapes": LADDER_SHAPES, "days": LADDER_DAYS},
    }


def save(report: dict[str, Any], data_dir: Path) -> Path:
    path = data_dir / RESULT_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=1))
    return path


def load(data_dir: Path) -> dict[str, Any] | None:
    path = data_dir / RESULT_FILE
    return json.loads(path.read_text()) if path.exists() else None


def _replay_verdict(focus: dict[str, Any], long: dict[str, Any]) -> str:
    wins = [replay["rule"]["cagr"] > max(replay["equal"]["cagr"], replay["hold"]["cagr"]) for replay in (focus, long)]
    shallower = [replay["rule"]["max_drawdown"] > max(replay["equal"]["max_drawdown"], replay["hold"]["max_drawdown"]) for replay in (focus, long)]
    if all(wins):
        return "两段回放里按信号调权的年化都更高，但区间短、独立样本少，不足以证明信号可靠。"
    if any(wins):
        return ("按信号调权只在一段回放里胜出、另一段落后，" + ("回撤也只在部分区间更浅，" if not all(shallower) else "回撤都更浅，")
                + "说明它不能稳定胜过等权或一直持有。")
    return "按信号调权在两段回放里都没有胜过等权或一直持有。"


def markdown(report: dict[str, Any]) -> str:
    target = report["target"]
    model = report["model"]
    lines = [
        "# 一年期目标回测（QQQ / 谷歌 / 微软 / 红利低波）",
        "",
        f"生成时间：{report['generated_at']}　目标：一年收益 ≥ {_pct(target, 0)}（各自币种）。每 {model['step']} 个交易日一个起点，只用起点之前的数据；"
        f"长期收益向年化 {_pct(model['prior'])} 收缩（ETF/指数 {model['shrink_years']:.0f} 年权重，个股 {model.get('shrink_years_stock', model['shrink_years']):.0f} 年），波动 × √(1+{model['kappa']})。"
        f"信号：均线下方或概率 < {_pct(model['reduce_probability'], 0)} → 减仓/暂缓；概率 ≥ {_pct(model['add_probability'], 0)} → 加仓；其余持有。",
        "",
        "## 1. 概率校准",
        "",
        f"合并样本：{', '.join(report['pooled_symbols'])}（QQQ 与纳指100重叠，只计指数）。Brier 越低越好，低于“气候基准”（一直报历史平均命中率）才说明有信息量；AUC 0.5 = 没有区分能力。",
        "",
        "| 样本 | 起点数 / 独立年 | 平均预测 | 实际命中 | Brier | 气候基准 | AUC | 跌超10% 预测 / 实际 |",
        "|---|---|---|---|---|---|---|---|",
    ]

    def row(name: str, block: dict[str, Any] | None) -> str:
        if not block:
            return f"| {name} | — | | | | | | |"
        auc = f"{block['auc']:.2f}" if block["auc"] is not None else "—"
        return (f"| {name} | {block['n']} / {block['n_eff']:.0f} | {_pct(block['predicted'], 0)} | {_pct(block['realized'], 0)} | "
                f"{block['brier']:.3f} | {block['brier_climatology']:.3f} | {auc} | {_pct(block['loss10_predicted'], 0)} / {_pct(block['loss10_realized'], 0)} |")

    lines.append(row("合并", report["pooled"]["all"]))
    lines.append(row("合并 · 2010 年前", report["pooled"]["eras"]["before_2010"]))
    lines.append(row("合并 · 2010 年后", report["pooled"]["eras"]["since_2010"]))
    for symbol, block in report["per_symbol"].items():
        lines.append(row(f"{symbol}（{block['start'][:4]} 起）", block["all"]))
    lines += ["", "按预测概率分档（合并）：", "", "| 预测区间 | 起点数 | 平均预测 | 实际命中 |", "|---|---|---|---|"]
    for bucket in report["pooled"]["buckets"]:
        lines.append(f"| {_pct(bucket['low'], 0)}–{_pct(bucket['high'], 0)} | {bucket['n']} | {_pct(bucket['predicted'], 0)} | {_pct(bucket['realized'], 0)} |")
    lines += ["", "## 2. 信号分组后的实际一年表现", "",
              "| 时期 | 信号 | 起点数 / 独立年 | 达标率 | 跌超10% | 一年收益中位 |", "|---|---|---|---|---|---|"]
    for era, label in (("before_2010", "2010 年前"), ("since_2010", "2010 年后")):
        for name in ACTION_WEIGHTS:
            block = report["pooled"]["actions_by_era"][era][name]
            if block:
                lines.append(f"| {label} | {ACTION_LABELS[name]} | {block['n']} / {block['n_eff']:.0f} | {_pct(block['realized'], 0)} | "
                             f"{_pct(block['loss10_realized'], 0)} | {_pct(block['median_return'], 1, True)} |")
    lines += ["", "## 3. 组合回放：按信号调权 vs 等权 vs 一直持有", "",
              f"按信号调权：加仓 {model['weights']['add']}、持有 {model['weights']['hold']}、减仓 {model['weights']['reduce']} 的相对权重，每 {model['step']} 个交易日调仓；"
              "等权每期再平衡；一直持有 = 第一天等权买入后不动。未计交易成本与税。", "",
              "| 组合 | 区间 | 策略 | 年化 | 最大回撤 | 滚动一年达标率 | 滚动一年跌超10% |", "|---|---|---|---|---|---|---|"]
    names = {"rule": "按信号调权", "equal": "等权再平衡", "hold": "一直持有"}
    for key, label in (("focus", "四只重点标的"), ("long", "纳指100 + 微软 + 谷歌（长历史）")):
        replay = report["portfolios"][key]
        for name, stats in replay["strategies"].items():
            lines.append(f"| {label} | {replay['start'][:7]}–{replay['end'][:7]} | {names[name]} | {_pct(stats['cagr'], 1, True)} | "
                         f"{_pct(stats['max_drawdown'], 1)} | {_pct(stats['hit_rate'], 0)} | {_pct(stats['loss10_rate'], 0)} |")
    if report.get("ladders"):
        depths = " / ".join(f"−{d * 100:.0f}%" for d in LADDER_DEPTHS[1:])
        lines += ["", "## 4. 买入方式：一次买入 vs 现价一部分 + 回调挂限价", "",
                  f"挂单价位为起点价 {depths}，有效 {LADDER_DAYS} 个交易日，按日收盘价判断成交（略低估盘中成交），到期未成交部分按当天收盘价买入；"
                  "收益从起点算一年，等待中的现金不计利息。", "",
                  "| 标的 | 起点数 / 独立年 | 挂单成交率 | 做法 | 平均一年收益 | 达标率 | 不亏率 | 悲观 10% | 胜过一次买入 |",
                  "|---|---|---|---|---|---|---|---|---|"]
        for symbol, replay in report["ladders"].items():
            if not replay:
                continue
            fill = " / ".join(_pct(rate, 0) for rate in replay["fill_rates"][1:])
            for name, stats in replay["shapes"].items():
                lines.append(f"| {symbol} | {replay['n']} / {replay['n_eff']:.0f} | {fill} | {LADDER_LABELS[name]} | {_pct(stats['mean'], 1, True)} | "
                             f"{_pct(stats['hit_rate'], 0)} | {_pct(stats['nonneg_rate'], 0)} | {_pct(stats['p10'], 1, True)} | "
                             f"{'—' if name == 'lump' else _pct(stats['beats_lump'], 0)} |")
    pooled = report["pooled"]["all"]
    focus = report["portfolios"]["focus"]["strategies"]
    long = report["portfolios"]["long"]["strategies"]
    lines += ["", "## 结论", "",
              f"- 概率的整体水平：模型平均预测 {_pct(pooled['predicted'], 0)}，实际命中 {_pct(pooled['realized'], 0)}。"
              + ("模型偏保守（这段历史整体是牛市，收缩先验低于实际）。" if pooled["predicted"] < pooled["realized"] - 0.05 else "整体水平基本一致。"),
              f"- 区分能力：AUC {pooled['auc']:.2f}。" + ("低于或接近 0.5，说明“今天概率高的时候一年后更容易达标”这件事在历史上不成立，概率只能当作长期水平的估计，不能用来择时。"
                                                       if (pooled["auc"] or 0) < 0.55 else "有一定区分能力。"),
              f"- 组合：四只标的里按信号调权年化 {_pct(focus['rule']['cagr'], 1, True)}，等权 {_pct(focus['equal']['cagr'], 1, True)}，一直持有 {_pct(focus['hold']['cagr'], 1, True)}；"
              f"长历史组合分别为 {_pct(long['rule']['cagr'], 1, True)} / {_pct(long['equal']['cagr'], 1, True)} / {_pct(long['hold']['cagr'], 1, True)}。"
              + _replay_verdict(focus, long),
              "- 买入方式：" + (ladder_verdict(report.get("ladders") or {}) or "尚无数据。"),
              "- 起点每月一个、窗口一年，相邻起点高度重叠，“独立年”才是真实样本量；2010 年前后结论不同，说明任何单一时期的规律都不可靠。",
              "- 统计估算，不构成投资建议。"]
    return "\n".join(lines) + "\n"
