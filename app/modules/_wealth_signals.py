"""理财板块的强弱信号：和大盘比、成交量趋势、均线变化，合成一个 -3 ~ +3 的分数；再用真实历史回放几种减持组合。

分数只作观察和退出保护，不进概率模型，也不改挂单。信号本身预测不了后面涨跌（evidence() 的分组结果就是证据），
历史上有用的只是「转弱后把剩余仓位卖掉」这条退出规则，它压低了最差情况，也会卖飞涨势。
"""
from __future__ import annotations

import json
import time
from bisect import bisect_right
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import _wealth_market as market
from . import _wealth_sell_plan as sell_plan
from . import _wealth_switch_plan as switch_plan

HISTORY_FILE = "signals_history.json"
RESULT_FILE = "signals_backtest.json"
HISTORY_RANGE = "10y"
CACHE_DAYS = 7
MIN_BARS = 200
BENCHMARKS = {"3690.HK": ("3033.HK", "恒生科技 ETF"), "QQQ": ("SPY", "标普 500"), "GOOGL": ("QQQ", "纳指 100"),
              "MSFT": ("QQQ", "纳指 100"), "512890.SS": ("510300.SS", "沪深 300 ETF")}
HK_GROUP = ("3690.HK", "0700.HK", "9988.HK", "1810.HK", "9618.HK", "0981.HK")
US_GROUP = ("NVDA", "AAPL", "AMZN", "TSLA", "GOOGL", "MSFT")
HK_BENCH, US_BENCH = "3033.HK", "QQQ"
EXTRA = ("QQQ", "SPY", "512890.SS", "510300.SS")
HOLDOUT = "3690.HK"
UP_VOLUME, DOWN_VOLUME = 1.15, 0.87     # 20 日内上涨日成交量 ÷ 下跌日成交量
HEAVY_VOLUME, LIGHT_VOLUME = 1.2, 0.8   # 20 日均量 ÷ 60 日均量
SLOPE_FLAT = 0.005                      # 均线 20 日变化不到 0.5% 算走平
STRONG, WEAK = 2, -2
ARM_DAYS = 60                           # 转弱要从强转下来：之前 60 个交易日内分数到过 +1
PRIOR_HIGH_DAYS = 20                    # 「前高」取近一个月最高价，再往前的高点离现价太远，起不到观察作用
HORIZONS = (63, 252)
COMBO_DAYS = (252, 756)
COMBO_STEP, BUCKET_STEP = 10, 5
LOW_LADDER = (1.05, 1.10, 1.15, 1.20, 1.25)  # 比现价高 5%–25% 等量挂，每档一成仓位，配合先卖一半
COMBOS = {"now": "今天全卖转红利低波", "halflowweak": "卖一半 + 低阶梯 + 转弱全卖", "halflow": "卖一半 + 低阶梯",
          "ladweak": "页面阶梯 + 转弱全卖", "lad": "页面阶梯", "laddefer": "页面阶梯 + 强势时缓卖", "hold": "一直持有"}
GROUPS = {"holdout": ("美团", (HOLDOUT,), HK_BENCH), "hk": ("港股六只", HK_GROUP, HK_BENCH), "us": ("美股六只", US_GROUP, US_BENCH)}
SCORE_LABELS = {"strong": "偏强（≥ +2）", "mid": "中性", "weak": "偏弱（≤ -2）"}
DISCLAIMER = "统计估算，不构成投资建议"


# ---- 指标 ----------------------------------------------------------------------------------------

def _sma(values: Sequence[float], n: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    total = 0.0
    for i, v in enumerate(values):
        total += v
        if i >= n:
            total -= values[i - n]
        if i >= n - 1:
            out[i] = total / n
    return out


def _ret(values: Sequence[float | None], i: int, k: int) -> float | None:
    if i < k:
        return None
    a, b = values[i], values[i - k]
    return a / b - 1 if a and b else None


def _gap(a: float | None, b: float | None) -> float | None:
    return a - b if a is not None and b is not None else None


def _sign(high: bool, low: bool) -> int:
    return 1 if high else -1 if low else 0


def series(ts: Sequence[int], close: Sequence[float], adj: Sequence[float], volume: Sequence[float | None],
           bench_ts: Sequence[int], bench_adj: Sequence[float]) -> dict[str, list]:
    """每天的信号，只用当天和之前的数据。收益和涨跌方向用复权价，均线用实际价（和盘面一致）。"""
    n = len(close)
    vols = [float(v or 0) for v in volume]
    bench = [bench_adj[j] if j >= 0 else None for j in (bisect_right(bench_ts, t) - 1 for t in ts)]
    up = _sma([vols[i] if i and adj[i] > adj[i - 1] else 0.0 for i in range(n)], 20)
    down = _sma([vols[i] if i and adj[i] < adj[i - 1] else 0.0 for i in range(n)], 20)
    v20, v60 = _sma(vols, 20), _sma(vols, 60)
    m20, m60, m200 = _sma(close, 20), _sma(close, 60), _sma(close, 200)
    out: dict[str, list] = {k: [None] * n for k in ("rs20", "rs60", "up_down", "vol_ratio", "rs_state", "vol_state", "ma_state", "score", "weak_exit")}
    out.update(bench=bench, m20=m20, m60=m60, m200=m200)
    for i in range(n):
        rs20, rs60 = _gap(_ret(adj, i, 20), _ret(bench, i, 20)), _gap(_ret(adj, i, 60), _ret(bench, i, 60))
        up_down = up[i] / down[i] if up[i] is not None and down[i] else None
        out["rs20"][i], out["rs60"][i], out["up_down"][i] = rs20, rs60, up_down
        out["vol_ratio"][i] = v20[i] / v60[i] if v20[i] and v60[i] else None
        if rs60 is None or up_down is None or m60[i] is None or m20[i] is None:
            continue
        rs = _sign(rs20 is not None and rs20 > 0 and rs60 > 0, rs20 is not None and rs20 < 0 and rs60 < 0)
        vol = _sign(up_down > UP_VOLUME, up_down < DOWN_VOLUME)
        ma = _sign(close[i] > m60[i] and m20[i] > m60[i], close[i] < m60[i] and m20[i] < m60[i])
        score = rs + vol + ma
        out["rs_state"][i], out["vol_state"][i], out["ma_state"][i], out["score"][i] = rs, vol, ma, score
        recent = (s for s in out["score"][max(0, i - ARM_DAYS):i] if s is not None)
        out["weak_exit"][i] = score <= WEAK and any(s >= 1 for s in recent)
    return out


def _slope_label(slope: float | None) -> str:
    if slope is None:
        return "—"
    return "上行" if slope > SLOPE_FLAT else "下行" if slope < -SLOPE_FLAT else "走平"


def _points(v: float | None) -> str:
    return "—" if v is None else f"{v * 100:+.1f} 点"


def _pct(v: float | None) -> str:
    return "—" if v is None else f"{v * 100:+.1f}%"


def score_key(score: int) -> str:
    return "strong" if score >= STRONG else "weak" if score <= WEAK else "mid"


def snapshot(bars: Sequence[dict[str, Any]], bench_bars: Sequence[dict[str, Any]], bench_name: str) -> dict[str, Any] | None:
    """最新一根日线上的信号，给页面和对话。"""
    if len(bars) < MIN_BARS or len(bench_bars) < 61:
        return None
    close = [b["close"] for b in bars]
    s = series([b["ts"] for b in bars], close, [b.get("adj_close") or b["close"] for b in bars], [b.get("volume") for b in bars],
               [b["ts"] for b in bench_bars], [b.get("adj_close") or b["close"] for b in bench_bars])
    t = len(close) - 1
    if s["score"][t] is None:
        return None
    slope = {k: _ret(s[k], t, 20) for k in ("m20", "m60", "m200")}
    bench_close = [b["close"] for b in bench_bars]
    b20, b60 = _sma(bench_close, 20)[-1], _sma(bench_close, 60)[-1]
    bench_state = _sign(bench_close[-1] > b60 and b20 > b60, bench_close[-1] < b60 and b20 < b60)
    rs_state, vol_state, ma_state, score = s["rs_state"][t], s["vol_state"][t], s["ma_state"][t], s["score"][t]
    ratio = s["vol_ratio"][t]
    level = "放量" if ratio and ratio > HEAVY_VOLUME else "缩量" if ratio and ratio < LIGHT_VOLUME else "量能平稳"
    bench_ret = {k: _ret(s["bench"], t, k) for k in (20, 60)}
    return {
        "as_of": datetime.fromtimestamp(bars[-1]["ts"], UTC).date().isoformat(), "score": score,
        "key": score_key(score), "label": {"strong": "偏强", "mid": "中性", "weak": "偏弱"}[score_key(score)],
        "weak_exit": bool(s["weak_exit"][t]),
        "relative": {"state": rs_state, "label": {1: "跑赢大盘", 0: "强弱分化", -1: "跑输大盘"}[rs_state], "d20": s["rs20"][t], "d60": s["rs60"][t],
                     "text": f"比{bench_name}：近 20 日 {_points(s['rs20'][t])}，近 60 日 {_points(s['rs60'][t])}"},
        "volume": {"state": vol_state, "label": {1: "上涨日量大", 0: "涨跌量均衡", -1: "下跌日量大"}[vol_state], "up_down": s["up_down"][t], "ratio": ratio, "level": level,
                   "text": f"近 20 日上涨日量是下跌日的 {s['up_down'][t]:.2f} 倍；20 日均量是 60 日的 {ratio:.2f} 倍（{level}）" if ratio else "成交量数据不足"},
        "ma": {"state": ma_state, "label": {1: "多头排列", 0: "均线缠绕", -1: "空头排列"}[ma_state], "m20": s["m20"][t], "m60": s["m60"][t], "m200": s["m200"][t],
               "slopes": slope, "text": f"20 日线 {s['m20'][t]:.2f}（{_slope_label(slope['m20'])}）、60 日线 {s['m60'][t]:.2f}（{_slope_label(slope['m60'])}）、"
                                        + (f"200 日线 {s['m200'][t]:.2f}（{_slope_label(slope['m200'])}）" if s["m200"][t] else "200 日线数据不足")},
        "benchmark": {"name": bench_name, "state": bench_state, "label": {1: "自身走强", 0: "方向不明", -1: "自身走弱"}[bench_state], "d20": bench_ret[20], "d60": bench_ret[60],
                      "text": f"{bench_name}近 20 日 {_pct(bench_ret[20])}，近 60 日 {_pct(bench_ret[60])}"},
    }


# ---- 历史数据 ------------------------------------------------------------------------------------

def _stats(values: Sequence[float]) -> dict[str, float]:
    ordered = sorted(values)
    at = lambda q: ordered[min(len(ordered) - 1, int(q * len(ordered)))]
    return {"n": len(ordered), "mean": sum(ordered) / len(ordered), "p10": at(0.1), "median": at(0.5), "p90": at(0.9)}


def fetch_history() -> dict[str, dict[str, list]]:
    out: dict[str, dict[str, list]] = {}
    for symbol in dict.fromkeys((*HK_GROUP, *US_GROUP, HK_BENCH, US_BENCH, *EXTRA)):
        bars = market.chart(symbol, HISTORY_RANGE, "1d")["bars"]
        out[symbol] = {"ts": [b["ts"] for b in bars], "close": [b["close"] for b in bars], "adj": [b["adj_close"] for b in bars],
                       "high": [b["high"] or b["close"] for b in bars], "volume": [b["volume"] for b in bars]}
        time.sleep(0.2)
    return out


def load_history(data_dir: Path, refresh: bool = False, fetch: Callable[[], dict[str, dict[str, list]]] = fetch_history) -> dict[str, dict[str, list]]:
    path = data_dir / HISTORY_FILE
    if path.exists() and not refresh:
        return json.loads(path.read_text(encoding="utf-8"))
    data = fetch()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return data


def _with_series(history: dict[str, dict[str, list]], symbol: str, bench: str) -> dict[str, Any]:
    d, b = history[symbol], history[bench]
    return {**d, **series(d["ts"], d["close"], d["adj"], d["volume"], b["ts"], b["adj"])}


# ---- 信号分组：强 / 中 / 弱之后真实涨跌 --------------------------------------------------------------

def _buckets(frames: Sequence[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in SCORE_LABELS:
        row: dict[str, Any] = {"label": SCORE_LABELS[key]}
        for h in HORIZONS:
            rets, excess = [], []
            for f in frames:
                adj, bench = f["adj"], f["bench"]
                for t in range(MIN_BARS, len(adj) - h, BUCKET_STEP):
                    score = f["score"][t]
                    if score is None or score_key(score) != key or not bench[t]:
                        continue
                    rets.append(adj[t + h] / adj[t] - 1)
                    excess.append(rets[-1] - (bench[t + h] / bench[t] - 1))
            row[str(h)] = {**_stats(rets), "up": sum(r > 0 for r in rets) / len(rets), "excess": _stats(excess)["median"], "n_eff": len(rets) * BUCKET_STEP / h} if len(rets) >= 10 else None
        out[key] = row
    return out


def _rebound(frames: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """截图第二行的检验：较 60 日低点涨了 20%–26%（相当于 75 涨到 90–95）时，近一月跑赢 / 跑输，之后半年内再涨 8%（到 100 左右）的比例。"""
    days, rise = 126, 1.08
    hits: dict[str, list[bool]] = {"lead": [], "lag": []}
    for f in frames:
        adj, high, last = f["adj"], f["high"], -99
        scale = [a / c for a, c in zip(adj, f["close"])]
        for t in range(MIN_BARS, len(adj) - days):
            gain = adj[t] / min(adj[t - 60:t + 1]) - 1
            if not 0.20 <= gain <= 0.26 or f["rs20"][t] is None or t - last < 10:
                continue
            last = t
            peak = max(high[i] * scale[i] for i in range(t + 1, t + days + 1))
            hits["lead" if f["rs20"][t] > 0 else "lag"].append(peak >= adj[t] * rise)
    return {k: {"n": len(v), "rate": sum(v) / len(v) if v else None} for k, v in hits.items()}


def _breakout(frames: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """截图第一行的检验：收盘创 60 日新高（前 20 日没创过），放量和不放量分别之后三个月的涨跌。"""
    days = 63
    rets: dict[str, list[float]] = {"heavy": [], "light": []}
    for f in frames:
        adj, last = f["adj"], -99
        for t in range(MIN_BARS, len(adj) - days):
            if adj[t] <= max(adj[t - 60:t]) or t - last < 20 or f["vol_ratio"][t] is None:
                continue
            last = t
            rets["heavy" if f["vol_ratio"][t] > 1 else "light"].append(adj[t + days] / adj[t] - 1)
    return {k: {**_stats(v), "up": sum(r > 0 for r in v) / len(v)} if v else None for k, v in rets.items()}


# ---- 组合回放 -------------------------------------------------------------------------------------

def _replay(f: dict[str, Any], etf: dict[str, list], s: int, days: int, rule: str, price: float, ladder: Sequence[tuple[float, float]],
            net: Callable[[float], float]) -> float:
    """从第 s 天开始按规则卖，卖出所得转红利低波，到期每股价值（路径按比例缩放到现价，税费按现价口径）。"""
    scale = price / f["close"][s]
    ets, eadj = etf["ts"], etf["adj"]
    value_at = lambda i: eadj[max(0, bisect_right(ets, f["ts"][i]) - 1)]
    left, units = 1.0, 0.0

    def sell(i: int, p: float, weight: float) -> None:
        nonlocal left, units
        weight = min(weight, left)
        left -= weight
        units += weight * net(p) * (1 - switch_plan.SWITCH_COST_RATE) / value_at(i)

    if rule == "now":
        sell(s, price, 1.0)
    rungs: list[tuple[float, float]] = []
    if rule.startswith("halflow"):
        sell(s, price, 0.5)
        rungs = [(price * m, 0.1) for m in LOW_LADDER]
    elif rule.startswith("lad"):
        for m, w in ladder:
            if m <= 1:
                sell(s, price, w)
            else:
                rungs.append((price * m, w))
    pending = 0.0
    for i in range(s + 1, s + days + 1) if rule not in ("now", "hold") else ():
        high, close, score = f["high"][i] * scale, f["close"][i] * scale, f["score"][i]
        for rung in [r for r in rungs if high >= r[0]]:
            rungs.remove(rung)
            if rule == "laddefer" and score is not None and score >= STRONG:
                pending += rung[1]
            else:
                sell(i, rung[0], rung[1])
        if pending and (score is None or score < STRONG):
            sell(i, close, pending)
            pending = 0.0
        if rule.endswith("weak") and f["weak_exit"][i]:
            sell(i, close, 1.0)
            break
    end = s + days
    return units * value_at(end) * (1 - switch_plan.SWITCH_COST_RATE) + left * net(f["close"][end] * scale)


def _combos(frames: Sequence[dict[str, Any]], etf: dict[str, list], price: float, ladder: Sequence[tuple[float, float]],
            net: Callable[[float], float]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for days in COMBO_DAYS:
        results: dict[str, list[float]] = {k: [] for k in COMBOS}
        independent = 0.0
        for f in frames:
            first = max(MIN_BARS, bisect_right(f["ts"], etf["ts"][0]))
            starts = [s for s in range(first, len(f["close"]) - days, COMBO_STEP) if f["score"][s] is not None]
            independent += len(starts) * COMBO_STEP / days
            for s in starts:
                for rule in COMBOS:
                    results[rule].append(_replay(f, etf, s, days, rule, price, ladder, net))
        if not results["now"]:
            continue
        base = results["now"]
        out[str(days)] = {"n": len(base), "n_eff": independent,
                          "rows": {k: {"label": COMBOS[k], **_stats(v), "beat_now": sum(a > b for a, b in zip(v, base)) / len(v)} for k, v in results.items()}}
    return out


def run_backtest(data_dir: Path, price: float, ladder: Sequence[tuple[float, float]], cost_rate: float, refresh: bool = False,
                 fetch: Callable[[], dict[str, dict[str, list]]] = fetch_history) -> dict[str, Any]:
    """ladder 是当前页面阶梯：(相对现价的倍数, 仓位比例)，倍数不大于 1 的是现价卖出。"""
    history = load_history(data_dir, refresh, fetch)
    tax = switch_plan.DEFAULT_TAX
    net = lambda p: p * (1 - cost_rate) - max(p - tax["threshold"], 0.0) * tax["rate"]
    frames = {name: [_with_series(history, s, bench) for s in symbols] for name, (_, symbols, bench) in GROUPS.items()}
    extra = {"qqq": ("QQQ 比标普 500", [_with_series(history, "QQQ", "SPY")]), "dividend": ("红利低波比沪深 300", [_with_series(history, "512890.SS", "510300.SS")])}
    etf = history["512890.SS"]
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"), "price": price, "ladder": [list(r) for r in ladder],
        "labels": {k: g[0] for k, g in GROUPS.items()}, "symbols": {k: list(g[1]) for k, g in GROUPS.items()},
        "benchmarks": {k: g[2] for k, g in GROUPS.items()}, "low_ladder": list(LOW_LADDER),
        "buckets": {**{k: {"label": GROUPS[k][0], "rows": _buckets(v)} for k, v in frames.items()},
                    **{k: {"label": label, "rows": _buckets(v)} for k, (label, v) in extra.items()}},
        "rebound": {k: _rebound(frames[k]) for k in ("holdout", "hk")},
        "breakout": {k: _breakout(frames[k]) for k in ("holdout", "hk")},
        "combos": {k: _combos(v, etf, price, ladder, net) for k, v in frames.items()},
        "start": {k: datetime.fromtimestamp(history[k]["ts"][0], UTC).date().isoformat() for k in (HK_BENCH, "512890.SS")},
    }


def save(report: dict[str, Any], data_dir: Path) -> None:
    path = data_dir / RESULT_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def load(data_dir: Path) -> dict[str, Any] | None:
    path = data_dir / RESULT_FILE
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


# ---- 页面用的结论 ---------------------------------------------------------------------------------

def evidence(report: dict[str, Any] | None, days: int = 756) -> dict[str, Any] | None:
    """把回放结果压成页面要的几句话；句子跟着数字走，数字变了结论也会变。"""
    if not report:
        return None
    combos = {k: v[str(days)] for k, v in report["combos"].items() if str(days) in v}
    one_year = {k: v["252"] for k, v in report["combos"].items() if "252" in v}
    if not combos:
        return None
    findings: list[str] = []

    def spread(group: str) -> float | None:
        rows = report["buckets"][group]["rows"]
        a, b = rows["strong"].get("252"), rows["weak"].get("252")
        return a["mean"] - b["mean"] if a and b else None

    gaps = {k: spread(k) for k in ("holdout", "hk", "us")}
    known = [v for v in gaps.values() if v is not None]
    if known:
        same_way = all(v > 0.05 for v in known)
        findings.append(("信号分数有一定区分度" if same_way else "信号分数预测不了之后的涨跌")
                        + "：偏强减偏弱，之后一年平均差 "
                        + "、".join(f"{report['labels'][k]} {v * 100:+.0f} 点" for k, v in gaps.items() if v is not None) + "。")
    for key in combos:
        rows = combos[key]["rows"]
        a, b = rows["halflowweak"], rows["halflow"]
        c, e = rows["ladweak"], rows["lad"]
        findings.append(f"{report['labels'][key]}：加转弱全卖后，卖一半 + 低阶梯平均 {a['mean'] - b['mean']:+.1f}、最差 10% {a['p10'] - b['p10']:+.1f}；"
                        f"页面阶梯平均 {c['mean'] - e['mean']:+.1f}、最差 10% {c['p10'] - e['p10']:+.1f}。")
    return {"generated_at": report["generated_at"], "days": days, "years": round(days / 252), "price": report["price"],
            "labels": report["labels"], "symbols": report["symbols"], "start": report["start"], "combos": combos, "one_year": one_year, "buckets": report["buckets"],
            "rebound": report["rebound"], "breakout": report["breakout"], "findings": findings,
            "stale": (datetime.now(UTC) - datetime.fromisoformat(report["generated_at"])).days > CACHE_DAYS}


def stages(price: float, target: float, bars: Sequence[dict[str, Any]], report: dict[str, Any] | None) -> list[dict[str, Any]]:
    """减持观察表：按现价和目标价分段。原表说法和回测结论并排，两者不一致时不替人取舍。"""
    prior = max((b.get("high") or b["close"] for b in bars[-PRIOR_HIGH_DAYS:]), default=price)
    low, high = target * 0.90, target * 0.98
    cap = min(prior, low)
    breakout = (report or {}).get("breakout", {}).get("hk") or {}
    rebound = (report or {}).get("rebound", {})
    combos = ((report or {}).get("combos", {}).get("holdout") or {}).get("756", {}).get("rows")
    early = (f"美团 3 年回放：页面阶梯平均 {combos['lad']['mean']:.1f}、最差 10% {combos['lad']['p10']:.1f}；先卖一半 + 低阶梯 + 转弱全卖 {combos['halflowweak']['mean']:.1f}、{combos['halflowweak']['p10']:.1f}。"
             + ("这段历史里低位先卖更好，但美团同期大跌，不能直接外推。" if combos["halflowweak"]["mean"] > combos["lad"]["mean"] else "")
             if combos else "回测还没生成")
    volume = (f"港股六只创 60 日新高后三个月：放量上涨 {breakout['heavy']['up'] * 100:.0f}%（中位 {breakout['heavy']['median'] * 100:+.1f}%），不放量上涨 {breakout['light']['up'] * 100:.0f}%（中位 {breakout['light']['median'] * 100:+.1f}%）。"
              if breakout.get("heavy") and breakout.get("light") else "回测还没生成")
    lag = rebound.get("hk") or {}
    relative = (f"港股六只反弹 20%–26% 后半年内再涨 8%：近一月跑赢 {lag['lead']['rate'] * 100:.0f}%（{lag['lead']['n']} 次），跑输 {lag['lag']['rate'] * 100:.0f}%（{lag['lag']['n']} 次）。"
                + ("跑输时到达比例并不更低，这一条没有得到历史支持。" if lag["lag"]["rate"] >= lag["lead"]["rate"] else "")
                if lag.get("lead", {}).get("rate") is not None and lag.get("lag", {}).get("rate") is not None else "回测还没生成")
    rows = [
        {"key": "before", "name": "突破前高之前", "range": f"低于 {cap:.1f}" + ("（近 20 日最高价）" if prior < low else ""), "active": price < cap,
         "watch": "是否突破前高、回调后守住；大盘是否同步改善", "view": "暂不为了分批在远低于目标的位置大量卖，否则剩余持仓的补差要求更高", "evidence": early},
        {"key": "middle", "name": "突破后的上涨段", "range": f"{prior:.1f} – {low:.1f}", "active": prior <= price < low,
         "watch": "上涨是否有量，均线是否转上行", "view": "按挂单走，不追加判断", "evidence": volume},
        {"key": "near", "name": "接近目标区", "range": f"{low:.1f} – {high:.1f}", "active": low <= price < high,
         "watch": "近一个月是否跑赢大盘；上涨是否有量，盈利预期是否改善", "view": "强势就继续等目标区；大盘涨而自己持续落后，就降低对目标的信心，重新选价格或退出期限", "evidence": relative},
        {"key": "window", "name": "目标区及以上", "range": f"{high:.1f} 以上", "active": price >= high,
         "watch": "是快速突破，还是反复冲高回落", "view": "主要减持窗口，优先完成目标，不再把大量股份留给更高价", "evidence": "没有单独回测：样本太少，只作观察。"},
    ]
    return [r for r in rows if r["key"] != "middle" or prior < low]


def combo_example(price: float, remaining: int, lot: int, market_code: str) -> dict[str, Any] | None:
    """「卖一半 + 低阶梯 + 转弱全卖」换成当前股数和价格的样子，只作展示，不下单。"""
    if remaining < lot * 10:
        return None
    half = int(remaining / 2 / lot) * lot
    rest = remaining - half
    each = int(rest / len(LOW_LADDER) / lot) * lot
    rungs = [{"price": sell_plan.round_to_tick(price * m, market_code), "shares": each, "gain": m - 1} for m in LOW_LADDER]
    rungs[-1]["shares"] = rest - each * (len(LOW_LADDER) - 1)
    return {"now_shares": half, "price": price, "rungs": rungs, "exit": f"分数之前 {ARM_DAYS} 个交易日到过 +1、现在跌到 {WEAK} 或更低时，把没卖的按市价卖掉"}
