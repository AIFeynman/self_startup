"""每类标的的估值分档数据和分档表：红利低波之外的 QQQ（纳指 100 指数 PE + 美债利差）、谷歌 / 微软（SEC 财报算滚动 PE + 美债利差）、
美团（亏损期 PE 没有意义，用市销率）、纯债基金（10 年国债收益率）。只作参考，不进概率模型，也不改挂单。"""
from __future__ import annotations

import json
import threading
import time
from bisect import bisect_right
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from . import _wealth_market as market
from . import _wealth_target_plan as tp

CACHE_FILE = "asset_valuation.json"
SEC_URL = "https://data.sec.gov/api/xbrl/companyconcept/CIK{cik}/us-gaap/EarningsPerShareDiluted.json"
SEC_CIK = {"GOOGL": "0001652044", "MSFT": "0000789019"}
HK_REPORT_URL = ("https://datacenter.eastmoney.com/securities/api/data/v1/get?reportName=RPT_HKF10_FN_MAININDICATOR"
                 "&columns=REPORT_DATE,DATE_TYPE_CODE,OPERATE_INCOME,ISSUED_COMMON_SHARES,EPS_TTM&filter=(SECUCODE%3D%22{code}%22)"
                 "&pageNumber=1&pageSize=60&sortTypes=-1&sortColumns=REPORT_DATE&source=F10&client=PC")
MEITUAN = "3690.HK"
MA_WINDOW_WEEKS = 156       # 均线偏离的分位只看最近 3 年
MA_MIN_ZONE_WEEKS = 26
MA_MIN_GAP = 0.05           # 偏低档比偏高档之后一年中位至少高这么多，才算有区分度
MA_LABELS = {"cheap": "偏低", "fair": "中性", "dear": "偏高"}
RANK = {"cheap": -1, "fair": 0, "dear": 1}
VALUATION_STUCK = 0.9       # 九成时间都在同一档，估值就分不出贵贱
BUY_MAX_LOSS = 0.5          # 这个位置买入，一年后亏的占比超过它就不买
SELL_MIN_LOSS = 0.3         # 这个位置之后一年亏的占比不到它，就先不卖
ACTIONS = {-2: "buy", -1: "small_buy", 0: "hold", 1: "no_add", 2: "sell"}
ACTION_LABELS = {"buy": "分批买", "small_buy": "可少量买", "hold": "持有不动", "no_add": "不追加", "sell": "分批减", "wait": "先不买"}
REPORT_LAG_DAYS = 90        # 港股财报没有公告日字段：报告期结束 90 天后才算市场知道，不偷看
SEC_LAG_DAYS = 75           # SEC 明细里部分老数据只留了后来重述的公布日；大公司 60 天内必须出财报，超过这个天数就按它算
_refreshing = threading.Lock()


def _weekly(rows: Sequence[Sequence[Any]]) -> list[Sequence[Any]]:
    """每个自然周留最后一行；rows 按日期升序，第一列是 ISO 日期。"""
    out: dict[tuple[int, int], Sequence[Any]] = {}
    for row in rows:
        out[tuple(date.fromisoformat(row[0]).isocalendar()[:2])] = row
    return list(out.values())


def _daily(symbol: str) -> dict[str, Any]:
    result = market.chart(symbol, "10y", "1d")      # range=max 时 Yahoo 会把日线降成周线 / 月线
    return {"bars": [[datetime.fromtimestamp(b["ts"], UTC).date().isoformat(), b["close"]] for b in result["bars"]],
            "splits": result.get("splits", [])}


def ttm_eps(rows: Sequence[dict[str, Any]], splits: Sequence[Sequence[Any]] = ()) -> list[list[Any]]:
    """SEC 的稀释 EPS 明细 → [财报公布日, 滚动四季 EPS]。同一区间取最早公布的值（当时能看到的）；拆股前公布的按拆股比例还原；
    Q4 = 全年 − 前三季。生效日取公布日和报告期后 SEC_LAG_DAYS 天里较早的。"""
    first: dict[tuple[str, str], tuple[str, float]] = {}
    for r in rows:
        if "start" not in r:
            continue
        value = r["val"] / _split_factor(r["filed"], splits)
        key = (r["start"], r["end"])
        known = min(r["filed"], (date.fromisoformat(r["end"]) + timedelta(days=SEC_LAG_DAYS)).isoformat())
        if key not in first or known < first[key][0]:
            first[key] = (known, value)
    quarters: dict[str, tuple[str, float]] = {}
    years = []
    for (start, end), (filed, value) in first.items():
        days = (date.fromisoformat(end) - date.fromisoformat(start)).days
        if 80 <= days <= 100:
            quarters[end] = (filed, value)
        elif 350 <= days <= 380:
            years.append((start, end, filed, value))
    for start, end, filed, value in years:
        inside = [q for e, q in quarters.items() if start < e < end]
        if end not in quarters and len(inside) == 3:
            quarters[end] = (filed, value - sum(q[1] for q in inside))
    ends = sorted(quarters)
    series = []
    for i in range(3, len(ends)):
        window = ends[i - 3:i + 1]
        if (date.fromisoformat(window[-1]) - date.fromisoformat(window[0])).days <= 300:
            series.append([max(quarters[e][0] for e in window), sum(quarters[e][1] for e in window)])
    return sorted(series)


def _split_factor(filed: str, splits: Sequence[Sequence[Any]]) -> float:
    factor = 1.0
    for day, ratio in splits:
        if filed < day:
            factor *= ratio
    return factor


def ttm_sales_per_share(rows: Sequence[dict[str, Any]]) -> list[list[Any]]:
    """港股累计口径财报（一季 / 中期 / 三季 / 全年）→ [可见日, 滚动四季每股收入, 滚动四季 EPS]。"""
    by_end = {r["REPORT_DATE"][:10]: r for r in rows if r.get("OPERATE_INCOME")}
    series, shares = [], None
    for end in sorted(by_end):
        r = by_end[end]
        shares = r.get("ISSUED_COMMON_SHARES") or shares
        day = date.fromisoformat(end)
        if r["DATE_TYPE_CODE"] == "001":
            ttm = r["OPERATE_INCOME"]
        else:
            year_end = by_end.get(f"{day.year - 1}-12-31")
            last_year = by_end.get(f"{day.year - 1}-{end[5:]}")
            if not year_end or not last_year:
                continue
            ttm = r["OPERATE_INCOME"] + year_end["OPERATE_INCOME"] - last_year["OPERATE_INCOME"]
        if shares:
            series.append([(day + timedelta(days=REPORT_LAG_DAYS)).isoformat(), ttm / shares, r.get("EPS_TTM")])
    return series


def _at(series: Sequence[Sequence[Any]], day: str) -> Sequence[Any] | None:
    i = bisect_right([row[0] for row in series], day) - 1
    return series[i] if i >= 0 else None


def fetch_source(name: str) -> Any:
    if name.startswith("bars:"):
        return _daily(name.removeprefix("bars:"))["bars"]
    if name == "us10y":
        return _daily("^TNX")["bars"]
    if name == "QQQ":
        rows = tp._danjuan("pe_history/NDX?day=all")["index_eva_pe_growths"]
        return [[(datetime.fromtimestamp(r["ts"] / 1000, UTC) + timedelta(hours=8)).date().isoformat(), r["pe"]] for r in rows if r.get("pe")]
    if name in SEC_CIK:
        rows = json.loads(market.get_bytes(SEC_URL.format(cik=SEC_CIK[name]), timeout=30, headers={"User-Agent": "Mozilla/5.0"}))["units"]["USD/shares"]
        daily = _daily(name)
        return {"bars": daily["bars"], "eps": ttm_eps(rows, daily["splits"])}
    if name == MEITUAN:
        payload = json.loads(market.get_bytes(HK_REPORT_URL.format(code="03690.HK"), timeout=30, headers={"User-Agent": "Mozilla/5.0"}))
        return {"bars": _daily(MEITUAN)["bars"], "fx": _daily("HKDCNY=X")["bars"], "sales": ttm_sales_per_share(payload["result"]["data"])}
    raise ValueError(name)


SOURCES = ("us10y", "QQQ", "GOOGL", "MSFT", MEITUAN, "bars:QQQ", f"bars:{tp.TIMING_SYMBOL}")


def refresh(cache_dir: Path) -> dict[str, Any]:
    """逐个数据源刷新；某个源失败就留它的旧副本，不影响其他标的。"""
    cache = cache_dir / CACHE_FILE
    stored = json.loads(cache.read_text()) if cache.exists() else {}
    data, failed = dict(stored.get("sources", {})), list(SOURCES)
    for _ in range(2):      # 单个源偶尔抖一下，失败的再试一轮
        for name in list(failed):
            try:
                data[name] = fetch_source(name)
                failed.remove(name)
            except Exception:
                pass
    # 有源失败时只算刷新了 CACHE_HOURS - 1 小时前，一小时后再试
    stored = {"fetched_at": time.time() - (3600 * (tp.CACHE_HOURS - 1) if failed else 0), "sources": data, "failed": failed}
    if not data:
        return stored
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(stored))
    return stored


def load(cache_dir: Path) -> dict[str, Any] | None:
    """不让页面等数据源：有缓存就直接用，过期或没有缓存都在后台刷新，刷好之后下次打开才有表。"""
    cache = cache_dir / CACHE_FILE
    stored = json.loads(cache.read_text()) if cache.exists() else None
    expired = time.time() - (stored or {}).get("fetched_at", 0) >= tp.CACHE_HOURS * 3600
    incomplete = any(name not in (stored or {}).get("sources", {}) for name in SOURCES)
    if (expired or incomplete) and _refreshing.acquire(blocking=False):
        def run() -> None:
            try:
                refresh(cache_dir)
            except Exception:
                pass
            finally:
                _refreshing.release()
        threading.Thread(target=run, daemon=True).start()
    return stored


def _stats(values: Sequence[float | None]) -> dict[str, Any] | None:
    known = sorted(v for v in values if v is not None)
    return {"n": len(known), "median": known[len(known) // 2], "loss": sum(v < 0 for v in known) / len(known)} if known else None


def _enough(stats: dict[str, Any] | None) -> bool:
    return bool(stats) and stats["n"] >= MA_MIN_ZONE_WEEKS


def _ma_useful(zones: dict[str, dict[str, Any] | None]) -> bool:
    if not all(_enough(z) for z in zones.values()):
        return False
    low, mid, high = (zones[k]["median"] for k in tp.TIMING_LABELS)
    return low > mid > high and low - high >= MA_MIN_GAP


def ma_reference(bars: Sequence[Sequence[Any]], price: float) -> dict[str, Any] | None:
    """现价相对 200 日均线的位置和对应价格。每周取样，分位只用当时之前 3 年，看之后的价格涨跌（不含分红）。"""
    days, closes = [b[0] for b in bars], [b[1] for b in bars]
    if len(closes) < 200 or (datetime.now(UTC).date() - date.fromisoformat(days[-1])).days > 14:
        return None
    weekly: dict[Any, tuple[int, float]] = {}
    total = sum(closes[:199])
    for i in range(199, len(closes)):
        total += closes[i]
        weekly[date.fromisoformat(days[i]).isocalendar()[:2]] = (i, closes[i] / (total / 200) - 1)
        total -= closes[i - 199]
    if len(weekly) < MA_WINDOW_WEEKS:
        return None

    def ahead(i: int, n: int) -> float | None:
        day = (date.fromisoformat(days[i]) + timedelta(days=n)).isoformat()
        return closes[bisect_right(days, day) - 1] / closes[i] - 1 if day <= days[-1] else None

    history: list[float] = []
    rows = []
    for i, deviation in weekly.values():
        history.append(deviation)
        if len(history) >= MA_WINDOW_WEEKS:
            window = history[-MA_WINDOW_WEEKS:]
            rows.append({"day": days[i], "zone": tp.timing_zone(sum(v <= deviation for v in window) / len(window)), "year": ahead(i, 365), "quarter": ahead(i, 91)})
    zones = {zone: _stats([r["year"] for r in rows if r["zone"] == zone]) for zone in tp.TIMING_LABELS}
    ma50, ma200 = sum(closes[-50:]) / 50, sum(closes[-200:]) / 200
    ordered = sorted(history[-MA_WINDOW_WEEKS:])
    low, high = ma200 * (1 + ordered[int(len(ordered) * 0.3)]), ma200 * (1 + ordered[int(len(ordered) * 0.7)])
    zone = "cheap" if price < low else "dear" if price > high else "fair"
    return {"ma50": ma50, "ma200": ma200, "low": low, "high": high, "zone": zone, "zone_label": MA_LABELS[zone], "zones": zones,
            "useful": _ma_useful(zones), "rows": rows}


def decision(valuation_zone: str, replay: Sequence[Sequence[str]], cheap: float | None, dear: float | None, ma: dict[str, Any], price: float) -> dict[str, Any]:
    """估值看长期贵不贵，均线看这段涨跌过头没有，两边合成一个买卖动作。规则对所有标的相同；
    每个位置在这个标的上的历史结果只用来否决：买了多半亏就不买，卖了多半还涨就先不卖。"""
    replay_days = [r[0] for r in replay]
    rows = []
    for row in ma["rows"]:
        i = bisect_right(replay_days, row["day"]) - 1
        if i >= 0 and (date.fromisoformat(row["day"]) - date.fromisoformat(replay_days[i])).days <= 14:
            rows.append({**row, "valuation": replay[i][1]})
    # 美团这种估值一路走低的，估值几乎永远“便宜”，说明不了贵贱，只看均线
    stuck = not rows or max(sum(r["valuation"] == z for r in rows) for z in tp.TIMING_LABELS) / len(rows) >= VALUATION_STUCK
    score = lambda v, m: RANK[m] * 2 if stuck else RANK[v] + RANK[m]
    tiers = {}
    for tier in range(-2, 3):
        same = [r for r in rows if score(r["valuation"], r["zone"]) == tier]
        tiers[tier] = {"year": _stats([r["year"] for r in same]), "quarter": _stats([r["quarter"] for r in same])}
    buy_vetoed = lambda t: _enough(tiers[t]["year"]) and tiers[t]["year"]["loss"] > BUY_MAX_LOSS
    sell_vetoed = _enough(tiers[2]["year"]) and tiers[2]["year"]["loss"] < SELL_MIN_LOSS

    def action(tier: int) -> str:
        if tier <= 0 and buy_vetoed(tier):
            return "wait"
        if tier == 2 and sell_vetoed:
            return "no_add"
        return ACTIONS[tier]

    tier = score(valuation_zone, ma["zone"])
    act = action(tier)
    buy_line = ma["low"] if stuck or not cheap else min(cheap, ma["low"])
    sell_line = ma["high"] if stuck or not dear else max(dear, ma["high"])
    text = tp.price_text
    reason = f"均线{MA_LABELS[ma['zone']]}，估值只看不算（长期偏一边，分不出贵贱）" if stuck else f"估值{tp.TIMING_LABELS[valuation_zone]}，均线{MA_LABELS[ma['zone']]}"

    def seen(stats: dict[str, Any] | None, span: str) -> str:
        if not stats:
            return f"{span}没有样本"
        return f"{span}中位 {stats['median'] * 100:+.1f}%、亏损占比 {stats['loss'] * 100:.0f}%（{stats['n']} 周{'，样本少' if not _enough(stats) else ''}）"

    plans = []
    if action(-2) == "buy":
        plans.append(f"分批买线 {text(buy_line)}" + ("（已到）" if price <= buy_line else f"（{(buy_line / price - 1) * 100:+.1f}%）"))
    else:
        plans.append(f"偏低线 {text(buy_line)} 到了也不买：历史上这个位置多半亏")
    if action(2) == "sell":
        plans.append(f"分批减线 {text(sell_line)}" + ("（已到）" if price >= sell_line else f"（{(sell_line / price - 1) * 100:+.1f}%）"))
    else:
        plans.append(f"偏高线 {text(sell_line)} 到了也先不卖，只是不追加：历史上这个位置之后多半还涨")
    quarter = tiers[tier]["quarter"]
    warning = "短期可能继续跌，分批别一次买满。" if act in ("buy", "small_buy") and quarter and quarter["loss"] > 0.5 else ""
    return {"action": act, "label": ACTION_LABELS[act], "tier": tier, "reason": reason, "stuck": stuck, "buy_line": buy_line, "sell_line": sell_line,
            "plan": "；".join(plans) + "。", "tiers": {str(k): v for k, v in tiers.items()},
            "evidence": f"同样位置历史：{seen(tiers[tier]['year'], '之后一年')}；{seen(quarter, '之后 3 个月')}。{warning}统计估算，不构成投资建议。"}


def attach_ma(timing: dict[str, Any] | None, symbol: str, data: dict[str, Any] | None, price: float) -> dict[str, Any] | None:
    """给分档表加均线参考和合并后的买卖判断。只作展示，不进模型、不改挂单和提醒。"""
    if not timing:
        return timing
    replay = timing.pop("replay", ())
    sources = (data or {}).get("sources", {})
    source = sources.get(symbol)
    bars = source.get("bars") if isinstance(source, dict) else sources.get(f"bars:{symbol}")
    ma = ma_reference(bars, price) if bars else None
    if not ma:
        return timing
    text = tp.price_text
    cheap, dear = timing["levels"]["cheap_below"], timing["levels"]["dear_above"]
    judged = decision(timing["zone"], replay, cheap, dear, ma, price)
    gap = lambda v: f"{text(v)}（{(v / price - 1) * 100:+.1f}%）"
    zones = ma.pop("rows") and ma["zones"]
    record = " / ".join(f"{MA_LABELS[k]} {z['median'] * 100:+.1f}%" if (z := zones[k]) else f"{MA_LABELS[k]} 无样本" for k in tp.TIMING_LABELS)
    ma["text"] = f"现价 {text(price)} {ma['zone_label']}：50 日 {text(ma['ma50'])} · 200 日 {text(ma['ma200'])} · 偏低线 {gap(ma['low'])} · 偏高线 {gap(ma['high'])}"
    ma["verdict"] = f"只看均线位置，之后一年中位（不含分红）：{record}。" + ("历史上有区分度。" if ma["useful"] else "只作价位参考，历史上不能预测涨跌。")
    if timing.get("metric") == "PS":
        timing["levels"] = {**timing["levels"], "headline": f"市销率这张表只看估值水平，不是目标价；操作价位看上面的判断。现价 {text(price)} {timing['levels']['currency']}。"}
    return {**timing, "ma": ma, "decision": judged}


def _earnings_timing(symbol: str, weeks: list[tuple], y: float, closes: Sequence[float], ts: Sequence[int], price: float,
                     currency: str, index: str, forward_pe: float | None, note: str) -> dict[str, Any] | None:
    """weeks: (day, PE, 利差)。价格变成 m 倍时 PE 也变 m 倍（盈利不变）。"""
    if not weeks:
        return None
    pe = weeks[-1][1]
    core = tp.zone_timing(weeks, (1, -1), lambda m: (pe * m, 100 / (pe * m) - y), closes, ts, price)
    if not core:
        return None
    live_pe, live_spread = pe * core["move"], 100 / (pe * core["move"]) - y
    cards = [{"label": "PE 分位", "value": f"{core['percentiles'][0] * 100:.0f}%", "note": f"PE {live_pe:.2f}，越高越贵"},
             {"label": "利差分位", "value": f"{core['percentiles'][1] * 100:.0f}%",
              "note": f"盈利收益率 {100 / live_pe:.2f}% − 10 年美债 {y:.2f}%，越低越贵"}]
    if forward_pe:
        cards.append({"label": "远期 PE", "value": f"{forward_pe:.1f}", "note": "按分析师预期盈利，仅作对照"})
    return {**core, "symbol": symbol, "index": index, "cards": cards, "metric": "PE",
            "levels": tp.price_levels(core, price, currency, "PE", pe * core["move"]), "note": note,
            "shape": None, "pacing": None, "stale": False}


def timing_for(symbol: str, data: dict[str, Any] | None, closes: Sequence[float], ts: Sequence[int], price: float,
               *, currency: str, forward_pe: float | None = None, stale_cgb: bool = False, cgb: Sequence[Sequence[Any]] = ()) -> dict[str, Any] | None:
    """某个标的的分档表。数据不全或样本不够就返回 None，页面不显示这张表。"""
    sources = (data or {}).get("sources", {})
    failed = (data or {}).get("failed", [])
    stale = symbol in failed or "us10y" in failed and symbol in ("QQQ", *SEC_CIK)
    timing = None
    if symbol == tp.BOND:
        timing = _bond_timing(cgb, closes, ts, price)
    elif symbol == "QQQ":
        pes, us10y = sources.get("QQQ"), sources.get("us10y")
        if pes and us10y:
            weeks = [(day, pe, 100 / pe - row[1]) for day, pe in pes if day >= tp.TIMING_START and (row := _at(us10y, day))]
            timing = _earnings_timing(symbol, weeks, us10y[-1][1], closes, ts, price, currency, "纳指 100 指数", forward_pe,
                                      "对应价格 = 盈利不变时 PE 到分界线的 QQQ 价格（QQQ 按跟随指数估算）。这张表只作参考，不改挂单和达标概率。")
    elif symbol in SEC_CIK:
        source, us10y = sources.get(symbol), sources.get("us10y")
        if source and us10y:
            weeks = []
            for day, close in _weekly(source["bars"]):
                eps, row = _at(source["eps"], day), _at(us10y, day)
                if day >= tp.TIMING_START and eps and row and eps[1] > 0:
                    weeks.append((day, close / eps[1], eps[1] / close * 100 - row[1]))
            timing = _earnings_timing(symbol, weeks, us10y[-1][1], closes, ts, price, currency, f"{tp.LABELS[symbol]} 滚动 PE", forward_pe,
                                      "PE 用 SEC 财报的滚动四季稀释 EPS，按财报公布日生效；EPS 含投资收益等一次性项目时 PE 会偏低，要和远期 PE 对照看。这张表只作参考，不改挂单和达标概率。")
    elif symbol == MEITUAN:
        timing = _sales_timing(sources.get(MEITUAN), closes, ts, price, currency)
    if timing:
        timing["stale"] = stale or stale_cgb
    return timing


def _sales_timing(source: dict[str, Any] | None, closes: Sequence[float], ts: Sequence[int], price: float, currency: str) -> dict[str, Any] | None:
    if not source or not source.get("sales") or not source.get("fx"):
        return None
    weeks = []
    for day, close in _weekly(source["bars"]):
        sales, fx = _at(source["sales"], day), _at(source["fx"], day)
        if sales and fx and sales[1] > 0:
            weeks.append((day, close * fx[1] / sales[1]))
    if not weeks:
        return None
    ps = weeks[-1][1]
    core = tp.zone_timing(weeks, (1,), lambda m: (ps * m,), closes, ts, price)
    if not core:
        return None
    eps = source["sales"][-1][2]
    live = ps * core["move"]
    cards = [{"label": "市销率分位", "value": f"{core['percentiles'][0] * 100:.0f}%", "note": f"PS {live:.2f}，越高越贵"},
             {"label": "滚动 EPS", "value": f"{eps:.2f}" if eps is not None else "—", "note": "人民币；亏损时 PE 没有意义，所以用市销率"}]
    return {**core, "symbol": MEITUAN, "index": "美团 市销率", "cards": cards, "metric": "PS",
            "levels": tp.price_levels(core, price, currency, "PS", live), "shape": None, "pacing": None, "stale": False,
            "note": "PS = 市值 ÷ 滚动四季收入，财报按报告期后 90 天生效。市销率看不到利润率变化：便宜可能是因为赚不到钱，这张表只作卖出价位的参考，不改挂单和达标概率。"}


def _bond_timing(cgb: Sequence[Sequence[Any]], closes: Sequence[float], ts: Sequence[int], nav: float) -> dict[str, Any] | None:
    """债基的「贵」看 10 年国债收益率：收益率越低，债券越贵。基金按当日净值申购，给收益率分界，不给价格。"""
    weeks = [(row[0], row[1]) for row in _weekly(cgb) if row[0] >= tp.TIMING_START]
    if not weeks:
        return None
    y = weeks[-1][1]
    core = tp.zone_timing(weeks, (-1,), lambda m: (y * m,), closes, ts, None)
    if not core:
        return None
    ordered = sorted(w[1] for w in weeks)
    cheap, dear = ordered[int(len(ordered) * 0.7)], ordered[int(len(ordered) * 0.3)]
    state = {"cheap": f"已在便宜区（≥ {cheap:.2f}%），跌破 {dear:.2f}% 才算偏贵",
             "dear": f"已在偏贵区（< {dear:.2f}%），涨到 {cheap:.2f}% 以上才算便宜",
             "fair": f"涨到 {cheap:.2f}% 以上算便宜，跌破 {dear:.2f}% 算偏贵"}[core["zone"]]
    cards = [{"label": "收益率分位", "value": f"{core['percentiles'][0] * 100:.0f}%", "note": f"10 年国债 {y:.2f}%，越低越贵"},
             {"label": "组合净值", "value": f"{nav:.4f}", "note": "按当日净值申购，没有挂单价"}]
    levels = {"currency": "", "header": "10 年国债收益率", "price": None, "to_cheap": None, "to_dear": None,
              "bands": {"cheap": {"price": f"≥ {cheap:.2f}%", "metric": ""}, "fair": {"price": f"{dear:.2f}%–{cheap:.2f}%", "metric": ""},
                        "dear": {"price": f"< {dear:.2f}%", "metric": ""}},
              "headline": f"10 年国债现在 {y:.2f}%，{state}。基金按当日净值申购，不用挂单。"}
    return {**core, "symbol": tp.BOND, "index": "10 年国债收益率", "cards": cards, "metric": "收益率", "levels": levels,
            "shape": None, "pacing": None, "stale": False, "note": "收益率分位只代表利率水平，组合里的短久期债基对利率不敏感，差异主要来自票息。这张表只作参考，不改配比和达标概率。"}
