"""理财对话的数据快照：把用户正在看的页面（目标 / 减持）和页面上的设置整理成给 Agent 的文字。只读，不改计划。"""
from __future__ import annotations

import math
from typing import Any

PAGES = {
    "target": {"target": float, "delay": int, "drawdown": float, "shape": str, "mode": str, "region": float, "basket": str},
    "sell": {"now_shares": int, "compare_days": int, "qqq_return": float, "stock_return": float},
}
RULES = ("用户在理财页面上提问。默认只回答和计算，只用只读接口（GET）；登记成交、改持仓设置要用户明确要求才做，永远不替用户下单。"
         "数字以下面的快照和接口返回为准，不要自己估；快照够回答就不要再调接口，想算别的参数才带参数调（curl 加 --noproxy '*'）。"
         "回答先给结论，再给依据，最后写「统计估算，不构成投资建议」。")
MAX_REASONS = 6


def page_of(ref: str) -> str:
    """wealth:target / wealth:sell → 页面名；其他 ref（比如侧边栏的新对话）没有绑定页面。"""
    page = (ref or "").removeprefix("wealth:")
    return page if page in PAGES else ""


def clean_view(page: str, body: dict[str, Any]) -> dict[str, Any]:
    """只留下这个页面认识的设置；空值去掉。范围由计算函数自己校验。"""
    if page not in PAGES:
        raise ValueError(f"未知页面：{page}")
    view: dict[str, Any] = {}
    for key, kind in PAGES[page].items():
        value = body.get(key)
        if value is None or value == "":
            continue
        value = kind(value)
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError(f"{key} 不是有效数字")
        view[key] = value
    return view


def _pct(v: float | None, signed: bool = False, digits: int = 1) -> str:
    if v is None:
        return "—"
    return f"{v * 100:{'+' if signed else ''}.{digits}f}%"


def _num(v: float | None) -> str:
    if v is None:
        return "—"
    return f"{v:,.3f}" if abs(v) < 10 else f"{v:,.2f}"   # ETF、债基净值一两块钱，两位小数不够下单


def _timing(t: dict[str, Any] | None) -> list[str]:
    """估值分档 + 均线合并后的判断（目标页每个标的、减持页美团共用）。"""
    if not t:
        return []
    out = [f"估值：{t.get('index', '')} {t.get('metric', '')} 区间「{t.get('zone_label', '—')}」"]
    decision, ma = t.get("decision") or {}, t.get("ma") or {}
    if decision:
        out.append(f"估值 + 均线判断：{decision.get('label', '—')}（{decision.get('reason', '')}）。{decision.get('plan', '')}")
    if ma.get("text"):
        out.append(f"均线：{ma['text']}")
    return out


def _signal(s: dict[str, Any] | None) -> list[str]:
    """和大盘比、成交量、均线的现状（目标页每个标的、减持页共用）。"""
    if not s:
        return []
    return [f"强弱信号（{s.get('as_of')}）：分数 {s.get('score'):+d}，{s.get('label')}" + ("，已触发转弱" if s.get("weak_exit") else ""),
            *[f"{part.get('label')}：{part.get('text')}" for part in (s.get("relative") or {}, s.get("volume") or {}, s.get("ma") or {}, s.get("benchmark") or {})]]


def _orders(plan: dict[str, Any]) -> list[str]:
    out = []
    for order in plan.get("orders") or []:
        steps = (order.get("plan") or {}).get("orders") or []
        detail = "；".join(f"{'市价' if s.get('kind') == 'market' else '限价'} {_num(s.get('price'))} × {s.get('units')}"
                          f"（成交概率 {_pct(s.get('fill_probability'), digits=0)}）" for s in steps)
        out.append(f"- {order.get('symbol')} 占 {_pct(order.get('weight'), digits=0)}，约 {_num(order.get('amount'))} {order.get('currency', '')}"
                   + (f"：{detail}" if detail else ""))
    return out


def target_context(d: dict[str, Any], view: dict[str, Any], region: dict[str, Any] | None = None) -> str:
    mode = view.get("mode") if view.get("mode") in ("safe", "aggressive") else "safe"
    plan = d["safe"] if mode == "safe" and d.get("safe") else d["allocation"]
    mode_name = "稳妥" if plan is d.get("safe") else "进取"
    names = {a["symbol"]: a["name"] for a in d["assets"]}
    lines = [f"### 用户正在看：理财 · 目标页\n设置：一年收益目标 {_pct(d.get('target'), digits=0)}，方案 {mode_name}，"
             f"回撤上限 {_pct(view.get('drawdown', 0.05), digits=0)}，到账延迟 {view.get('delay', 1)} 个月，买法 {view.get('shape', 'balanced')}。", "### 各标的"]
    for a in d["assets"]:
        lines.append(f"- {a['name']}（{a['symbol']}）现价 {_num(a.get('price'))} {a.get('currency', '')}：{a.get('action_label', '—')}，"
                     f"一年达标概率 {_pct(a.get('probability'), digits=0)}，悲观 10% {_pct(a.get('p10'), True)} / 中位 {_pct(a.get('p50'), True)} / 乐观 10% {_pct(a.get('p90'), True)}")
        lines += [f"  {x}" for x in _timing(a.get("val_timing"))]
        lines += [f"  {x}" for x in _signal(a.get("signal"))]
    s, hist = plan.get("stats") or {}, plan.get("history") or {}
    weights = " · ".join(f"{names.get(k, k)} {_pct(v, digits=0)}" for k, v in (plan.get("weights") or {}).items() if v)
    lines += [f"### {mode_name}方案配比\n{weights}",
              f"达标概率 {_pct(s.get('probability'), digits=0)}，不亏概率 {_pct(s.get('nonneg'), digits=0)}，悲观 10% {_pct(s.get('p10'), True)}，"
              f"中位 {_pct(s.get('p50'), True)}，乐观 10% {_pct(s.get('p90'), True)}"
              + (f"，压力回撤 {_pct(s.get('stress_drawdown'))}" if s.get("stress_drawdown") is not None else ""),
              f"历史回看（{hist.get('start', '—')} 起）：达标率 {_pct(hist.get('hit_rate'), digits=0)}，最差 {_pct(hist.get('worst'), True)}，最大回撤 {_pct(hist.get('max_drawdown'))}"]
    orders = _orders(plan)
    if orders:
        lines += ["### 这个方案的挂单", *orders]
    if region:
        lines.append(f"### 长期按地区分配（海外 {_pct(region.get('overseas'), digits=0)} : 内地 {_pct(region.get('mainland'), digits=0)}，"
                     f"海外买 {(region.get('baskets') or {}).get(region.get('basket'), '—')}，{region.get('start')} 起 {region.get('years')} 年）")
        lines += [f"- 内地里红利低波 {_pct(r.get('dividend'), digits=0)}：年化 {_pct(r.get('annual'), True)}，最大回撤 {_pct(r.get('max_drawdown'))}，"
                  f"最差一年 {_pct(r.get('worst_year'), True)}，最差三年累计 {_pct(r.get('worst_3y'), True)}" for r in region.get("rows") or []]
    return "\n".join(lines)


def sell_context(d: dict[str, Any], view: dict[str, Any]) -> str:
    plan, pos, ex, sm = d["plan"], d.get("position") or {}, d.get("execution") or {}, d.get("summary") or {}
    cur = d.get("currency", "")
    lines = [f"### 用户正在看：理财 · 减持页（{d.get('name')} {d.get('symbol')}）\n"
             f"现价 {_num(plan.get('price'))} {cur}，剩余 {ex.get('remaining_shares', pos.get('shares'))} 股，已卖 {ex.get('sold_shares', 0)} 股"
             + (f"（均价 {_num(ex.get('realized_avg'))}）" if ex.get("realized_avg") else "") + f"；"
             f"目标均价 {_num(plan.get('target_avg'))}，期限 {plan.get('horizon_days')} 个交易日，挂法 {plan.get('shape')}。",
             f"涨跌：近 5 日 {sm.get('change_5d_pct', 0):+.1f}%，近 20 日 {sm.get('change_20d_pct', 0):+.1f}%，近 1 年 {sm.get('change_1y_pct', 0):+.1f}%；"
             f"52 周 {_num(sm.get('low_52w'))}–{_num(sm.get('high_52w'))}；200 日均线 {_num(sm.get('sma200'))}。",
             "### 减持计划",
             f"现在卖 {plan.get('now_shares')} 股（模型建议 {plan.get('recommended_now_shares')} 股），达标概率 {_pct(plan.get('probability_target'), digits=0)}，"
             f"期望均价 {_num(plan.get('expected_avg'))}，悲观 10% 均价 {_num(plan.get('p10_avg'))}，现在全卖均价 {_num(plan.get('sell_all_now_avg'))}。",
             "挂单阶梯："]
    lines += [f"- {_num(x.get('price'))} × {x.get('shares')} 股，触及概率 {_pct(x.get('touch_probability'), digits=0)}，比现价 {x.get('gain_pct', 0):+.1f}%" for x in plan.get("ladder") or []]
    reasons = (plan.get("reasons") or {}).get("overview") or []
    if reasons:
        lines += ["依据：", *[f"- {x}" for x in reasons[:MAX_REASONS]]]
    timing = _timing(d.get("timing"))
    if timing:
        lines += ["### 估值和均线", *timing]
    sig = d.get("signals") or {}
    if sig.get("snapshot"):
        lines += ["### 和大盘比、成交量、均线", *_signal(sig["snapshot"])]
    current = next((r for r in sig.get("stages") or [] if r.get("active")), None)
    if current:
        lines.append(f"当前阶段：{current['name']}（{current['range']}）。重点观察：{current['watch']}。减持含义：{current['view']}。回测：{current['evidence']}")
    ev = sig.get("evidence") or {}
    if ev.get("findings"):
        lines += [f"### 减持组合回放（{ev.get('years')} 年，每股价值，含卖出后转红利低波）", *[f"- {x}" for x in ev["findings"]]]
        for key, group in (ev.get("combos") or {}).items():
            lines.append(f"{(ev.get('labels') or {}).get(key, key)}：" + "；".join(f"{r['label']} 平均 {r['mean']:.1f}、最差 10% {r['p10']:.1f}" for r in group["rows"].values()))
    sw = d.get("switch") or {}
    if sw.get("strategies"):
        lines.append(f"### 换 QQQ 对比（{sw.get('years')} 年，以现在全部卖出的税后到手为 1 倍）")
        lines += [f"- {x.get('label')}：中位 {x.get('median_ratio', 0):.2f} 倍，悲观 10% {x.get('p10_ratio', 0):.2f} 倍，跑赢不卖的概率 {_pct(x.get('beats_hold'), digits=0)}" for x in sw["strategies"]]
        lines += [f"- {x}" for x in (sw.get("reasons") or [])[:MAX_REASONS]]
    if view.get("compare_days") or view.get("qqq_return") is not None or view.get("stock_return") is not None:
        lines.append(f"（页面上的换仓假设：{view}）")
    return "\n".join(lines)
