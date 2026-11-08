"""视野板块的统计和显著度：全部是纯函数，不用大模型。

输入是一个指标按时间升序的 [(period, value)]；日频指标先压成月（取每月最后一个观测值）。
显著度信号：N 年新高 / 新低、偏离历史波动 2 个标准差、方向反转、跨过关口。
"""
from __future__ import annotations

import statistics
from datetime import date

PER_YEAR = {"Y": 1, "H": 2, "Q": 4, "M": 12}


def monthly(points: list[tuple[str, float]]) -> list[tuple[str, float]]:
    last: dict[str, float] = {}
    for p, v in points:
        last[p[:7]] = v
    return sorted(last.items())


def stat_points(cfg: dict, points: list[tuple[str, float]]) -> list[tuple[str, float]]:
    return monthly(points) if cfg["freq"] == "D" else points


def period_start(p: str) -> date:
    if len(p) == 4:
        return date(int(p), 1, 1)
    if "-Q" in p:
        return date(int(p[:4]), (int(p[-1]) - 1) * 3 + 1, 1)
    if "-H" in p:
        return date(int(p[:4]), 1 if p[-1] == "1" else 7, 1)
    if len(p) == 7:
        return date(int(p[:4]), int(p[5:7]), 1)
    return date.fromisoformat(p[:10])


def _years_between(a: str, b: str) -> float:
    return (period_start(b) - period_start(a)).days / 365.25


def _lag(cfg: dict) -> int:
    return PER_YEAR.get("M" if cfg["freq"] == "D" else cfg["freq"], 12)


def summary(cfg: dict, points: list[tuple[str, float]]) -> dict:
    """指标卡要显示的数：最新值、上一期、同比（是比率类指标就是差值）、历史位置。"""
    pts = stat_points(cfg, points)
    if not pts:
        return {}
    p, v = pts[-1]
    out = {"period": points[-1][0], "value": v, "count": len(pts), "first": pts[0][0]}
    if len(pts) > 1:
        out["prev_period"], out["prev"] = pts[-2]
        out["change"] = round(v - pts[-2][1], 4)
    lag = _lag(cfg)
    if len(pts) > lag and cfg["freq"] != "Y":
        out["yoy_period"], ago = pts[-1 - lag]
        out["yoy_change"] = round(v - ago, 4)
        if ago and not _is_rate(cfg):
            out["yoy_pct"] = round((v / ago - 1) * 100, 2)
    vals = [x for _, x in pts]
    out["rank_pct"] = round(sum(x <= v for x in vals) / len(vals) * 100, 1)
    out["max"], out["min"] = max(pts, key=lambda t: t[1]), min(pts, key=lambda t: t[1])
    return out


def _is_rate(cfg: dict) -> bool:
    return cfg.get("unit") in ("%", "‰") or "=100" in (cfg.get("unit") or "") or cfg.get("unit") == ""


def extreme(pts: list[tuple[str, float]]) -> dict | None:
    """最新值是不是「N 年新高 / 新低」：往回找最近一个不低于（不高于）它的值，隔了多少年。"""
    if len(pts) < 3:
        return None
    p, v = pts[-1]
    prev = pts[:-1]
    if v > prev[-1][1] or v < prev[-1][1]:
        hi = v > prev[-1][1]
        beat = [q for q, x in prev if (x >= v if hi else x <= v)]
        if not beat:
            return {"kind": "high" if hi else "low", "years": round(_years_between(pts[0][0], p), 1), "since": pts[0][0], "all_time": True}
        years = _years_between(beat[-1], p)
        if years >= 1:
            return {"kind": "high" if hi else "low", "years": round(years, 1), "since": beat[-1], "all_time": False}
    return None


def zscore(pts: list[tuple[str, float]], window: int = 60) -> float | None:
    """最新一期的变化，相对过去 window 期变化的波动有多大。"""
    diffs = [b[1] - a[1] for a, b in zip(pts, pts[1:])]
    hist = diffs[-window - 1:-1]
    if len(hist) < 8:
        return None
    sd = statistics.pstdev(hist)
    return round((diffs[-1] - statistics.mean(hist)) / sd, 2) if sd else None


def reversal(cfg: dict, pts: list[tuple[str, float]]) -> dict | None:
    """同比类指标：正负翻转；其他：连跌（涨）3 期以上后首次反向。"""
    if len(pts) < 5:
        return None
    vals = [v for _, v in pts]
    if cfg.get("unit") == "%" and "同比" in cfg["name"]:
        if vals[-2] < 0 <= vals[-1] or vals[-2] >= 0 > vals[-1]:
            return {"kind": "sign", "from": vals[-2], "to": vals[-1]}
    d = [b - a for a, b in zip(vals, vals[1:])]
    if not d[-1]:
        return None
    up = d[-1] > 0
    run = 0
    for x in reversed(d[:-1]):
        if (x < 0 if up else x > 0):
            run += 1
        else:
            break
    return {"kind": "turn_up" if up else "turn_down", "after": run} if run >= 3 else None


def gates(cfg: dict, pts: list[tuple[str, float]]) -> list[float]:
    if len(pts) < 2:
        return []
    a, b = pts[-2][1], pts[-1][1]
    return [g for g in cfg.get("gates", []) if min(a, b) < g <= max(a, b) and a != b]


def signals(cfg: dict, points: list[tuple[str, float]]) -> dict:
    """返回 {score, reasons[], extreme, z, reversal, gates}；score 为 0 表示不够写解读卡。"""
    pts = stat_points(cfg, points)
    ex = None if cfg.get("monotonic") else extreme(pts)
    z, rv, gt = zscore(pts), reversal(cfg, pts), gates(cfg, pts)
    reasons, score = [], 0.0
    macro = cfg["theme"] == "macro"
    if ex and ex["years"] >= (5 if macro else 3):
        hl = "高" if ex["kind"] == "high" else "低"
        reasons.append(f"有数据以来新{hl}（数据始于 {ex['since']}）" if ex["all_time"] else f"{ex['years']:g} 年新{hl}（上次这么{hl}在 {ex['since']}）")
        score += 2 + min(ex["years"], 20) / 10
    if z is not None and abs(z) >= 2 and not macro:
        reasons.append(f"这一期的变化是平时波动的 {abs(z):g} 倍")
        score += abs(z) / 2
    if rv:
        if rv["kind"] == "sign":
            reasons.append(f"同比由{'负转正' if rv['to'] >= 0 else '正转负'}")
        else:
            reasons.append(f"连{'降' if rv['kind'] == 'turn_up' else '涨'} {rv['after']} 期后首次{'回升' if rv['kind'] == 'turn_up' else '回落'}")
        score += 2
    if gt and not macro:
        reasons.append("跨过关口 " + "、".join(f"{g:g}" for g in gt))
        score += 3
    elif gt:
        reasons.append("跨过关口 " + "、".join(f"{g:g}" for g in gt))
    if macro and not (ex and ex["years"] >= 5) and not rv:
        score = 0
    weight = {"ai": 1.5, "fun": 1.0, "life": 1.0, "learn": 1.0, "macro": 0.8}[cfg["theme"]]
    return {"score": round(score * weight, 2), "reasons": reasons, "extreme": ex, "z": z, "reversal": rv, "gates": gt}


def should_notify(cfg: dict, sig: dict) -> bool:
    if cfg["theme"] == "ai":
        return bool(sig["gates"])
    ex = sig.get("extreme")
    return bool(ex and ex["years"] >= 5)


def judge(op: str, actual: float, target: float) -> bool:
    return {">": actual > target, ">=": actual >= target, "<": actual < target, "<=": actual <= target}[op]
