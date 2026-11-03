"""理财信号提醒：每只关注标的的结论（增持 / 持有 / 减持、估值区间）和美团减持计划的关键数，跟上一次比；
有变化就发通知（app.notify：页内弹出 + Mac 系统通知），每天到点再发一条汇总。状态存在 data/wealth/alerts.json。"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

ALERTS_FILE = "alerts.json"
MODULE = "wealth"


def load(data_dir: Path) -> dict[str, Any]:
    path = data_dir / ALERTS_FILE
    stored = json.loads(path.read_text()) if path.exists() else {}
    return {"state": stored.get("state"), "checked_at": stored.get("checked_at"), "summary_date": stored.get("summary_date")}


def save(data_dir: Path, store: dict[str, Any]) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    tmp = data_dir / (ALERTS_FILE + ".tmp")
    tmp.write_text(json.dumps(store, ensure_ascii=False))
    tmp.replace(data_dir / ALERTS_FILE)


def _conclusion(reasons: list[str]) -> str:
    return next((r for r in reversed(reasons) if r.startswith("结论")), reasons[-1] if reasons else "")


def snapshot(plan: dict[str, Any] | None, exit_plan: dict[str, Any] | None) -> dict[str, Any]:
    """The parts of the target plan and the Meituan exit plan whose change is worth a notification."""
    state: dict[str, Any] = {"target": plan["target"] if plan else None, "assets": {}, "exit": None}
    for a in (plan or {}).get("assets", []):
        if a.get("kind") == "fund":
            continue   # the bond basket's call is fixed ("底仓 · 稳定器")
        timing = a.get("timing") or {}
        state["assets"][a["symbol"]] = {
            "name": a["name"], "action": a["action"], "label": a["action_label"], "probability": a["probability"],
            "price": a.get("price"), "currency": a.get("currency"), "reason": _conclusion(a["reasons"]), "reasons": a["reasons"],
            "zone": timing.get("zone"), "zone_label": timing.get("zone_label"), "pacing": a.get("pacing")}
    if exit_plan:
        p, switch = exit_plan["plan"], exit_plan.get("switch") or {}
        best = (switch.get("optimal") or {}).get("median") or {}
        strategies = {s["key"]: s for s in switch.get("strategies", [])}
        state["exit"] = {
            "symbol": exit_plan["symbol"], "name": exit_plan["name"], "currency": exit_plan["currency"], "price": exit_plan["quote"]["price"],
            "now_shares": p["recommended_now_shares"], "remaining": p["remaining_shares"], "probability": p["probability_target"],
            "target_avg": p["target_avg"],
            "rungs": [{"price": r["price"], "shares": r["shares"]} for r in p["ladder"] if r["kind"] == "limit"],
            "switch_fraction": best.get("fraction"),
            "hold_median": (strategies.get("hold") or {}).get("median_ratio"),
            "switch_median": (strategies.get("switch_now") or {}).get("median_ratio"),
            "now_reasons": (p.get("reasons") or {}).get("now", []), "switch_reasons": switch.get("reasons", [])}
    return state


def _event(kind: str, symbol: str, title: str, body: str, reasons: list[str]) -> dict[str, Any]:
    return {"kind": kind, "symbol": symbol, "title": title, "body": body, "reasons": reasons}


def changes(prev: dict[str, Any] | None, cur: dict[str, Any]) -> list[dict[str, Any]]:
    """Events between two snapshots. With no earlier snapshot there is nothing to compare, so no events."""
    if not prev:
        return []
    events = []
    for symbol, a in cur["assets"].items():
        old = prev.get("assets", {}).get(symbol)
        if not old:
            continue
        if old["action"] != a["action"]:
            events.append(_event("action", symbol, f"{a['name']}：{old['label']} → {a['label']}",
                                 f"达标概率 {old['probability']:.0%} → {a['probability']:.0%}。{a['reason']}", a["reasons"]))
        if a.get("zone") and old.get("zone") and old["zone"] != a["zone"]:
            events.append(_event("valuation", symbol, f"{a['name']}估值：{old['zone_label']} → {a['zone_label']}",
                                 f"买入节奏改为：{a['pacing']}", [r for r in a["reasons"] if r.startswith("估值择时")]))
    e, old = cur.get("exit"), prev.get("exit")
    if e and old:
        name, cur_ = e["name"], e["currency"]
        if old["now_shares"] != e["now_shares"]:
            events.append(_event("exit_now", e["symbol"], f"{name}：建议现价卖出 {old['now_shares']:,} → {e['now_shares']:,} 股",
                                 f"现价 {e['price']} {cur_}，目标均价 {e['target_avg']}，达标概率 {e['probability']:.0%}。", e["now_reasons"]))
        for rung in e["rungs"]:
            if old["price"] < rung["price"] <= e["price"]:
                events.append(_event("exit_rung", e["symbol"], f"{name}涨到挂单价 {rung['price']} {cur_}",
                                     f"按计划这一档卖 {rung['shares']:,} 股（已挂限价单的话应已成交，记得在看板登记成交）；现价 {e['price']}。",
                                     e["now_reasons"]))
        if old.get("switch_fraction") is not None and e.get("switch_fraction") is not None and old["switch_fraction"] != e["switch_fraction"]:
            events.append(_event("exit_switch", e["symbol"], f"{name}：按中位数最优的换仓比例 {old['switch_fraction']:.0%} → {e['switch_fraction']:.0%}",
                                 _switch_line(e), e["switch_reasons"]))
    return events


def _switch_line(e: dict[str, Any]) -> str:
    if e.get("hold_median") is None or e.get("switch_median") is None:
        return ""
    keep = "继续持有不占优" if e["hold_median"] < e["switch_median"] else "继续持有占优"
    return f"税后财富中位数：全部持有 {e['hold_median']:.2f} 倍，现在全换 QQQ {e['switch_median']:.2f} 倍，{keep}。"


def summary(cur: dict[str, Any]) -> dict[str, Any]:
    groups: dict[str, list[str]] = {}
    for a in cur["assets"].values():
        groups.setdefault(a["label"], []).append(f"{a['name']} {a['probability']:.0%}")
    parts = [f"{label}：{'、'.join(names)}" for label, names in groups.items()]
    reasons = [f"{a['name']}（{a['label']}）{a['reason']}" for a in cur["assets"].values()]
    reasons += [f"{a['name']}估值「{a['zone_label']}」：{a['pacing']}" for a in cur["assets"].values() if a.get("zone_label")]
    e = cur.get("exit")
    if e:
        above = [r for r in e["rungs"] if r["price"] > e["price"]]
        nxt = f"，下一档挂单 {above[0]['price']}（+{above[0]['price'] / e['price'] - 1:.1%}）" if above else ""
        frac = f"按中位数最优现在换 {e['switch_fraction']:.0%}" if e.get("switch_fraction") is not None else ""
        parts.append(f"{e['name']}：现价 {e['price']}，建议现卖 {e['now_shares']:,} 股{nxt}" + (f"；{frac}" if frac else ""))
        reasons += [f"{e['name']}：{_switch_line(e)}"] + e["switch_reasons"][:2] + e["now_reasons"][:1]
    target = f" · 目标 {cur['target']:.0%}" if cur.get("target") is not None else ""
    return _event("summary", "", f"每日信号汇总{target}", "；".join(parts) + "。", reasons + ["统计估算，不构成投资建议。"])


def summary_due(store: dict[str, Any], now: datetime, at: str) -> bool:
    hour, minute = (int(x) for x in at.split(":"))
    return store.get("summary_date") != now.date().isoformat() and (now.hour, now.minute) >= (hour, minute)
