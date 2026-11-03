"""理财板块的服务层：持仓配置、行情 / 新闻刷新、美团减持计划、一年收益目标计划、回测缓存。

计算都在 _wealth_sell_plan / _wealth_switch_plan / _wealth_sell_backtest / _wealth_target_plan 里（从 wealth 仓库原样迁来），
这里只管数据进出：持仓在 data/wealth/positions.json，K 线 / 报价 / 新闻 / 成交在 app.db 的 wealth_* 表，回测缓存在 data/wealth/*.json。
"""
from __future__ import annotations

import json
import math
import re
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

from .. import db
from . import _wealth_market as market
from . import _wealth_sell_backtest as sell_backtest
from . import _wealth_sell_plan as sell_plan
from . import _wealth_switch_plan as switch_plan
from . import _wealth_target_plan as target_plan

SCHEMA = """
CREATE TABLE IF NOT EXISTS wealth_bars (
    symbol TEXT NOT NULL, interval TEXT NOT NULL, ts INTEGER NOT NULL,
    open REAL, high REAL, low REAL, close REAL, adj_close REAL, volume REAL,
    PRIMARY KEY(symbol, interval, ts)
);
CREATE TABLE IF NOT EXISTS wealth_quotes (
    symbol TEXT PRIMARY KEY, observed_at TEXT, price REAL, previous_close REAL, change_pct REAL,
    volume REAL, market_state TEXT, currency TEXT, retrieved_at TEXT
);
-- symbols：JSON 数组，标题里提到的持仓 / 关注标的；bucket：抓它的查询（position:<symbol>）
CREATE TABLE IF NOT EXISTS wealth_news (
    hash TEXT PRIMARY KEY, bucket TEXT DEFAULT '', symbols TEXT DEFAULT '[]',
    title TEXT, url TEXT, source TEXT, published_at TEXT, retrieved_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_wealth_news_time ON wealth_news(published_at);
-- kind：profile（估值）/ estimates（业绩超预期）
CREATE TABLE IF NOT EXISTS wealth_research (
    symbol TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT, retrieved_at TEXT, PRIMARY KEY(symbol, kind)
);
CREATE TABLE IF NOT EXISTS wealth_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT NOT NULL, executed_at TEXT NOT NULL,
    shares INTEGER NOT NULL, price REAL NOT NULL, note TEXT DEFAULT '', created_at TEXT
);
CREATE TABLE IF NOT EXISTS wealth_jobs (
    job_name TEXT PRIMARY KEY, last_started_at TEXT, last_completed_at TEXT, last_status TEXT, last_error TEXT DEFAULT ''
);
"""

DATA = db.DATA_DIR / "wealth"
POSITIONS = DATA / "positions.json"
HISTORY_RANGE = "2y"
RESEARCH_HOURS = 24

# 名称、币种、新闻里认它的词。持仓配置里写了 name / currency 时以配置为准。
ASSETS: dict[str, dict[str, Any]] = {
    "3690.HK": {"name": "美团", "currency": "HKD", "aliases": ["美团", "Meituan", "MEITUAN-W"]},
    "QQQ": {"name": "Nasdaq 100", "currency": "USD", "aliases": ["Nasdaq 100", "Nasdaq-100", "QQQ"]},
    "GOOGL": {"name": "Alphabet", "currency": "USD", "aliases": ["Google", "Alphabet"]},
    "MSFT": {"name": "Microsoft", "currency": "USD", "aliases": ["Microsoft", "Azure"]},
    "512890.SS": {"name": "红利低波ETF", "currency": "CNY", "aliases": ["红利低波", "华泰柏瑞红利低波动ETF", "512890"]},
}
# 目标计划的四个标的每小时也拉一次新闻（只做理由里的背景，不进概率模型）
FOCUS_NEWS = {
    "QQQ": [{"query": "Nasdaq 100 QQQ when:7d", "locale": "en-US"}],
    "GOOGL": [{"query": "Alphabet Google stock when:7d", "locale": "en-US"}],
    "MSFT": [{"query": "Microsoft stock when:7d", "locale": "en-US"}],
    "512890.SS": [{"query": "红利低波 when:7d", "locale": "zh-CN"}],
}
RESEARCH_SYMBOLS = ("QQQ", "GOOGL", "MSFT")

_refresh_lock = threading.Lock()
_backtest_lock = threading.Lock()
_target_lock = threading.Lock()
_positions_lock = threading.Lock()
_switch_memo: tuple[Any, Any] | None = None
LIVE: market.LiveFeed | None = None   # 板块启动时打开（wealth.on_startup）


def start_live() -> None:
    global LIVE
    if LIVE is None:
        LIVE = market.LiveFeed(list(ASSETS))
        LIVE.start()


class Busy(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


# ---- 持仓配置 -------------------------------------------------------------------------------------

def read_positions() -> dict[str, Any]:
    if not POSITIONS.is_file():
        return {"refresh_minutes": 60, "positions": []}
    return json.loads(POSITIONS.read_text("utf-8"))


def write_positions(payload: dict[str, Any]) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    tmp = POSITIONS.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(POSITIONS)


def asset(symbol: str, item: dict[str, Any] | None = None) -> dict[str, Any]:
    base = ASSETS.get(symbol, {"name": symbol, "currency": "USD", "aliases": []})
    item = item or {}
    return {**base, "name": item.get("name") or base["name"], "currency": item.get("currency") or base["currency"]}


def positions() -> list[dict[str, Any]]:
    return [p for p in read_positions().get("positions", []) if p.get("symbol")]


def position(symbol: str) -> dict[str, Any]:
    match = next((p for p in positions() if p["symbol"] == symbol), None)
    if match is None:
        raise ValueError(f"{symbol} 不在持仓配置（data/wealth/positions.json）中")
    return match


# ---- 存取 -----------------------------------------------------------------------------------------

def price_history(symbol: str, days: int = 365, interval: str = "1d") -> list[dict[str, Any]]:
    rows = db.rows("SELECT ts, open, high, low, close, adj_close, volume FROM wealth_bars WHERE symbol=? AND interval=? "
                   "ORDER BY ts DESC LIMIT ?", (symbol, interval, max(1, min(days, 2000))))
    return rows[::-1]


def store_bars(symbol: str, interval: str, bars: list[dict[str, Any]]) -> int:
    with db._lock:
        c = db.conn()
        c.executemany("INSERT OR REPLACE INTO wealth_bars(symbol, interval, ts, open, high, low, close, adj_close, volume) "
                      "VALUES(?,?,?,?,?,?,?,?,?)",
                      [(symbol, interval, b["ts"], b["open"], b["high"], b["low"], b["close"], b["adj_close"], b["volume"]) for b in bars])
        c.commit()
    return len(bars)


def store_quote(symbol: str, quote: dict[str, Any]) -> None:
    keys = ("observed_at", "price", "previous_close", "change_pct", "volume", "market_state", "currency", "retrieved_at")
    db.execute(f"INSERT OR REPLACE INTO wealth_quotes(symbol, {', '.join(keys)}) VALUES(?{', ?' * len(keys)})",
               [symbol, *(quote.get(k) for k in keys)])


def trades(symbol: str) -> list[dict[str, Any]]:
    return db.rows("SELECT * FROM wealth_trades WHERE symbol=? ORDER BY executed_at, id", (symbol,))


def _decode_news(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for r in rows:
        r["symbols"] = json.loads(r.get("symbols") or "[]")
    return rows


def symbol_news(symbol: str, limit: int = 120) -> list[dict[str, Any]]:
    return _decode_news(db.rows("SELECT * FROM wealth_news WHERE bucket=? OR symbols LIKE ? "
                                "ORDER BY COALESCE(published_at, retrieved_at) DESC LIMIT ?",
                                (_bucket(symbol), f'%"{symbol}"%', limit)))


def recent_news(limit: int = 400) -> list[dict[str, Any]]:
    return _decode_news(db.rows("SELECT * FROM wealth_news ORDER BY COALESCE(published_at, retrieved_at) DESC LIMIT ?", (limit,)))


def store_news(items: list[dict[str, Any]], bucket: str, symbol: str) -> int:
    inserted = 0
    for n in items:
        searchable = n["title"].lower()
        symbols = sorted({symbol, *(s for s, a in ASSETS.items() if _mentions(searchable, s, a["aliases"]))})
        inserted += db.execute("INSERT OR IGNORE INTO wealth_news(hash, bucket, symbols, title, url, source, published_at, retrieved_at) "
                               "VALUES(?,?,?,?,?,?,?,?)",
                               (n["hash"], bucket, json.dumps(symbols), n["title"], n["url"], n["source"], n["published_at"], n["retrieved_at"]))
    return inserted


def _mentions(searchable: str, symbol: str, aliases: list[str]) -> bool:
    if any(len(t) >= 3 and t.lower() in searchable for t in aliases):
        return True
    base = symbol.split(".")[0].lower()
    return len(base) >= 3 and re.search(rf"(?<![a-z0-9]){re.escape(base)}(?![a-z0-9])", searchable) is not None


def latest_research(kind: str) -> dict[str, dict[str, Any]]:
    return {r["symbol"]: {**r, "payload": json.loads(r["payload"] or "{}")}
            for r in db.rows("SELECT * FROM wealth_research WHERE kind=?", (kind,))}


def record_job(name: str, started: str, status: str, error: str = "") -> None:
    db.execute("INSERT OR REPLACE INTO wealth_jobs(job_name, last_started_at, last_completed_at, last_status, last_error) VALUES(?,?,?,?,?)",
               (name, started, utc_now(), status, error))


def job_state(name: str) -> dict[str, Any] | None:
    return db.row("SELECT * FROM wealth_jobs WHERE job_name=?", (name,))


# ---- 刷新 -----------------------------------------------------------------------------------------

def refresh(symbols: Iterable[str] | None = None) -> dict[str, Any]:
    """每小时：持仓的日线 + 小时线 + 专属新闻；目标计划四个标的的最新价和新闻；估值背景一天一次。"""
    if not _refresh_lock.acquire(blocking=False):
        raise Busy("行情刷新正在进行")
    started = utc_now()
    wanted = set(symbols) if symbols else None
    stats: dict[str, Any] = {"started_at": started, "symbols": {}, "errors": {}}
    try:
        held = {p["symbol"]: p for p in positions()}
        for symbol in [*held, *(s for s in target_plan.FOCUS if s not in held)]:
            if wanted is not None and symbol not in wanted:
                continue
            item = held.get(symbol)
            result: dict[str, Any] = {}
            try:
                if item:
                    data = market.chart(symbol, HISTORY_RANGE, "1d")
                    result["daily_bars"] = store_bars(symbol, "1d", data["bars"])
                    result["hourly_bars"] = store_bars(symbol, "60m", market.chart(symbol, "1mo", "60m")["bars"])
                else:
                    data = market.chart(symbol, "5d", "1d")
                    store_bars(symbol, "1d", data["bars"])
                store_quote(symbol, data["quote"])
            except Exception as exc:
                stats["errors"][f"{symbol}:prices"] = f"{type(exc).__name__}: {exc}"
            queries = (item or {}).get("news_queries") or FOCUS_NEWS.get(symbol, [])
            terms = [t.lower() for t in (item or {}).get("relevance_terms") or []]
            inserted = 0
            for i, q in enumerate(queries):
                try:
                    found = market.news(q["query"], q.get("locale", "en-US"))
                except Exception as exc:
                    stats["errors"][f"{symbol}:news{i}"] = f"{type(exc).__name__}: {exc}"
                    continue
                inserted += store_news([n for n in found if not terms or any(t in n["title"].lower() for t in terms)], _bucket(symbol), symbol)
            result["news_inserted"] = inserted
            stats["symbols"][symbol] = result
        stats["research"] = refresh_research()
        record_job("positions", started, "partial" if stats["errors"] else "completed", json.dumps(stats["errors"], ensure_ascii=False) if stats["errors"] else "")
        return stats
    except Exception as exc:
        record_job("positions", started, "failed", f"{type(exc).__name__}: {exc}")
        raise
    finally:
        _refresh_lock.release()


def refresh_research(force: bool = False) -> dict[str, Any]:
    fresh = {(r["symbol"], r["kind"]): r["retrieved_at"] for r in db.rows("SELECT symbol, kind, retrieved_at FROM wealth_research")}
    out = {}
    for symbol in RESEARCH_SYMBOLS:
        if not force and all(_hours_since(fresh.get((symbol, k))) < RESEARCH_HOURS for k in ("profile", "estimates")):
            continue
        got = market.research(symbol)
        for kind, payload in got.items():
            if payload:
                db.execute("INSERT OR REPLACE INTO wealth_research(symbol, kind, payload, retrieved_at) VALUES(?,?,?,?)",
                           (symbol, kind, json.dumps(payload, ensure_ascii=False), utc_now()))
        out[symbol] = [k for k, v in got.items() if v]
    return out


def current_price(symbol: str) -> dict[str, Any]:
    """最新价：实时流、存下的报价、最近一根小时线里取最新的那个。"""
    candidates = []
    live = (LIVE.quote(symbol) if LIVE else None) or {}
    if live.get("price"):
        candidates.append((live.get("time") or "", live["price"], "live"))
    quote = db.row("SELECT * FROM wealth_quotes WHERE symbol=?", (symbol,)) or {}
    if quote.get("price"):
        candidates.append((quote.get("observed_at") or "", quote["price"], "quote"))
    hourly = price_history(symbol, days=1, interval="60m")
    if hourly:
        candidates.append((datetime.fromtimestamp(hourly[-1]["ts"], UTC).isoformat(timespec="seconds"), hourly[-1]["close"], "hourly"))
    if not candidates:
        raise ValueError(f"{symbol} 还没有价格数据，请先刷新")
    observed, price, source = max(candidates, key=lambda r: r[0])
    # Yahoo 给的是 float32 精度（74.55000305），做最小价位计算前先去掉噪声
    return {"price": round(float(price), 4), "observed_at": observed, "source": source}


# ---- 减持计划 -------------------------------------------------------------------------------------

def sell(symbol: str, target_avg: float | None = None, horizon_days: int | None = None, now_shares: int | None = None,
         shape: str | None = None, compare_days: int | None = None, qqq_return: float | None = None,
         stock_return: float | None = None) -> dict[str, Any]:
    item = position(symbol)
    meta = asset(symbol, item)
    market_code = "HK" if symbol.endswith(".HK") else ""
    quote = current_price(symbol)
    price = quote["price"]
    daily = price_history(symbol, days=600)
    hourly = price_history(symbol, days=24 * 30, interval="60m")
    volatility = sell_plan.daily_volatility([r["close"] for r in daily])
    if not volatility["daily"]:
        raise ValueError(f"{symbol} 日线不足 20 根，无法估计波动率")
    total = int(item["shares"])
    lot = int(item.get("lot_size") or 1)
    # horizon_days 0 = 不设期限：限价单在整个对比期内一直挂着（GTC）
    stored = horizon_days if horizon_days is not None else item.get("horizon_days")
    stored_horizon = 63 if stored is None else int(stored)
    compare = int(compare_days or item.get("compare_days") or switch_plan.DEFAULT_COMPARE_DAYS)
    if compare not in switch_plan.COMPARE_DAYS:
        raise ValueError(f"compare_days 必须是 {', '.join(map(str, switch_plan.COMPARE_DAYS))} 之一")
    unlimited = stored_horizon == 0
    horizon = compare if unlimited else stored_horizon
    target = float(target_avg or item.get("target_avg") or sell_plan.round_to_tick(price * 1.1, market_code))
    done = trades(symbol)
    sold_shares = sum(r["shares"] for r in done)
    sold_proceeds = sum(r["shares"] * r["price"] for r in done)
    if sold_shares > total:
        raise ValueError(f"已记录卖出 {sold_shares} 股，超过持仓 {total} 股")
    costs = sell_plan.cost_schedule(market_code, read_positions().get("costs"))
    # 登记的成交没有费用明细，按同一费率估算
    sold_costs = sum(sell_plan.order_cost(r["price"], r["shares"], costs)["total"] for r in done)
    chosen = shape or item.get("shape") or "balanced"
    common = dict(price=price, total_shares=total, sigma_daily=volatility["daily"], horizon_days=horizon, lot=lot, market=market_code,
                  sold_shares=sold_shares, sold_proceeds=sold_proceeds, costs=costs, sold_costs=sold_costs)
    plan = sell_plan.build_plan(target_avg=target, now_shares=now_shares, shape=chosen, **common)
    # 同一目标在其它挂单形状下的结果（各自的建议现卖股数），让形状是看得见的取舍而不是默认值
    plan["shape_comparison"] = [
        {"shape": name, **{k: other[k] for k in ("probability_target", "expected_net_avg", "p10_net_avg", "recommended_now_shares")},
         "rungs": sum(r["kind"] == "limit" for r in other["ladder"])}
        for name in sell_plan.SHAPES
        for other in [plan if name == chosen and now_shares is None else sell_plan.build_plan(target_avg=target, shape=name, explain=False, **common)]
    ]
    # 目标按扣费后算：全部成交后净均价等于目标所需的税前均价
    fixed, rate = sell_plan._linear_cost(costs)
    gross_for_net = sell_plan.round_to_tick(target / (1 - rate) + fixed * max(1, len(plan["ladder"])) / total, market_code)
    net_plan = sell_plan.build_plan(target_avg=gross_for_net, shape=chosen, explain=False, **common)
    plan["net_target"] = {"gross_avg_needed": gross_for_net, "probability_target": net_plan["probability_target"],
                          "recommended_now_shares": net_plan["recommended_now_shares"]}
    ceiling = sell_plan.target_ceiling(price, volatility["daily"], horizon, target, total, sold_shares, sold_proceeds)
    ceiling["net_probability"] = sell_plan.target_ceiling(price, volatility["daily"], horizon, gross_for_net, total, sold_shares,
                                                          sold_proceeds, points=2)["probability"]
    cost = item.get("cost_basis")
    topics = item.get("topics") or {}
    terms = [t.lower() for t in item.get("relevance_terms") or []]
    news = [{k: r[k] for k in ("title", "url", "source", "published_at", "retrieved_at")} | sell_plan.tag_news(r["title"], topics)
            for r in symbol_news(symbol) if not terms or any(t in r["title"].lower() for t in terms)]
    recent = [r for r in news if _hours_since(r["published_at"]) <= 24 * 7]
    topic_counts: dict[str, dict[str, int]] = {}
    for r in recent:
        for topic in r["topics"] or ["其他"]:
            bucket = topic_counts.setdefault(topic, {"count": 0, "positive": 0, "negative": 0})
            bucket["count"] += 1
            if r["tone"] in ("positive", "negative"):
                bucket[r["tone"]] += 1
    return {
        "symbol": symbol, "name": meta["name"], "currency": meta["currency"], "market": market_code, "quote": quote,
        "position": {"shares": total, "lot_size": lot, "cost_basis": cost, "target_avg": item.get("target_avg"),
                     "horizon_days": stored_horizon, "unlimited": unlimited, "compare_days": compare, "shape": item.get("shape") or "balanced"},
        "volatility": volatility,
        "summary": sell_plan.price_summary(daily, hourly, price),
        "execution": {
            "trades": done, "sold_shares": sold_shares, "sold_proceeds": sold_proceeds,
            "realized_avg": sold_proceeds / sold_shares if sold_shares else None,
            "remaining_shares": total - sold_shares, "remaining_value": (total - sold_shares) * price,
            "required_avg_remaining": plan["required_avg_remaining"],
            "realized_pnl": (sold_proceeds - sold_shares * cost) if cost and sold_shares else None,
            "unrealized_pnl": ((price - cost) * (total - sold_shares)) if cost else None,
        },
        "plan": plan,
        "costs": {"schedule": costs, "labels": sell_plan.COST_LABELS},
        "backtest": sell_backtest_evidence(horizon, target / price - 1),
        "ceiling": ceiling,
        "switch": switch_comparison(symbol, meta["name"], item, price=price, sigma_daily=volatility["daily"], plan=plan, total=total, lot=lot,
                                    sold_shares=sold_shares, sold_proceeds=sold_proceeds, target=target, costs=costs, days=compare,
                                    qqq_return=qqq_return, stock_return=stock_return),
        "hourly": [{"ts": r["ts"], "close": r["close"], "volume": r["volume"]} for r in hourly[-24 * 15:]],
        "news": news[:30],
        "topic_counts": topic_counts,
        "news_7d": {"count": len(recent), "positive": sum(r["tone"] == "positive" for r in recent),
                    "negative": sum(r["tone"] == "negative" for r in recent)},
        "notable_moves": sell_plan.notable_moves(hourly, news),
        "refresh": job_state("positions"),
        "refresh_minutes": read_positions().get("refresh_minutes", 60),
        "generated_at": utc_now(),
    }


def switch_comparison(symbol: str, name: str, item: dict[str, Any], *, price: float, sigma_daily: float, plan: dict[str, Any], total: int,
                      lot: int, sold_shares: int, sold_proceeds: float, target: float, costs: dict[str, float], days: int,
                      qqq_return: float | None, stock_return: float | None) -> dict[str, Any] | None:
    """剩下的继续持有，还是现在 / 分批 / 随挂单成交换成 QQQ（税后，见 switch_plan）。"""
    remaining = total - sold_shares
    if remaining <= 0:
        return None
    for label, value in (("qqq_return", qqq_return), ("stock_return", stock_return)):
        if value is not None and not (math.isfinite(value) and -0.5 <= value <= 0.5):
            raise ValueError(f"{label} 必须在 -50%–50% 之间")
    assumptions = dict(switch_assumptions(symbol), qqq_return=qqq_return, stock_return=stock_return)
    rungs = [(r["price"], r["shares"]) for r in plan["ladder"] if r["kind"] == "limit"]
    result = switch_plan.compare(price=price, sigma_daily=sigma_daily, remaining=remaining, lot=lot, plan_now=plan["now_shares"], rungs=rungs,
                                 costs=costs, tax=switch_plan.tax_settings(item.get("tax")), days=days, assumptions=assumptions,
                                 total_shares=total, sold_proceeds=sold_proceeds, target_avg=target, name=name)
    result["backtest"] = switch_backtest_evidence()
    return result


def switch_assumptions(symbol: str) -> dict[str, Any]:
    """QQQ 的波动率和相关性，取自回测缓存的日线（请求时不联网）。"""
    global _switch_memo
    cache = DATA / "sell_backtest_history.json"
    key = (symbol, cache.stat().st_mtime if cache.exists() else None)
    if _switch_memo and _switch_memo[0] == key:
        return _switch_memo[1]
    histories = json.loads(cache.read_text()).get("symbols", {}) if key[1] else {}
    estimate = switch_plan.estimate_assumptions(histories.get(symbol), histories.get(switch_plan.SWITCH_SYMBOL))
    _switch_memo = (key, estimate)
    return estimate


def switch_backtest_evidence() -> dict[str, Any] | None:
    path = DATA / switch_plan.RESULT_FILE
    if not path.exists():
        return None
    report = json.loads(path.read_text())
    report["stale"] = _hours_since(report["generated_at"]) > 24 * sell_backtest.CACHE_DAYS
    return report


def sell_backtest_evidence(horizon: int, premium: float) -> dict[str, Any] | None:
    """离当前期限和目标溢价最近的回测行，给看板的「回测」卡片。"""
    report = sell_backtest.load(DATA)
    if not report:
        return None
    days = min(sell_backtest.HORIZONS, key=lambda v: abs(v - horizon))
    premium_row = min(sell_backtest.PREMIUMS, key=lambda v: abs(v - premium))
    groups = {}
    for name, group in report["groups"].items():
        groups[name] = {
            "symbols": group["symbols"],
            "strategy": next((r for r in group["strategy"] if r["days"] == days and r["premium"] == premium_row), None),
            "calibration": next((r for r in group["calibration"] if r["days"] == days), None),
            "all_strategy": [{k: r[k] for k in ("days", "premium", "predicted", "realized", "realized_interval", "n_eff")} for r in group["strategy"]]}
    return {"generated_at": report["generated_at"], "days": days, "premium": premium_row, "holdout": report["holdout"],
            "kappa": report["model"]["kappa"], "symbols": report["symbols"], "groups": groups,
            "stale": _hours_since(report["generated_at"]) > 24 * sell_backtest.CACHE_DAYS}


def run_sell_backtest(refresh: bool = False) -> dict[str, Any]:
    """重跑滚动回测（8 核约 2 分钟），写 JSON 和 Markdown 报告。"""
    if not _backtest_lock.acquire(blocking=False):
        raise Busy("减持回测正在运行")
    try:
        report = sell_backtest.run_backtest(DATA, refresh=refresh)
        sell_backtest.save(report, DATA)
        switch = run_switch_backtest()
        path = DATA / "sell-plan-backtest.md"
        path.write_text(sell_backtest.markdown(report) + "\n" + switch_plan.markdown(switch), encoding="utf-8")
        return {"generated_at": report["generated_at"], "elapsed_seconds": report["elapsed_seconds"], "report": str(path)}
    finally:
        _backtest_lock.release()


def run_switch_backtest() -> dict[str, Any]:
    """持有 vs 换 QQQ 在真实历史上回放；税的门槛和目标价都换成相对现价的比例。"""
    symbols = (sell_backtest.HOLDOUT, *switch_plan.REPLAY_BASKET)
    histories = sell_backtest.load_histories(DATA, (sell_backtest.HOLDOUT, *sell_backtest.BASKET, switch_plan.SWITCH_SYMBOL))
    price = histories[sell_backtest.HOLDOUT]["close"][-1]
    item = next((p for p in positions() if p["symbol"] == sell_backtest.HOLDOUT), {})
    tax = switch_plan.tax_settings(item.get("tax"))
    report = switch_plan.run_replay(histories, histories[switch_plan.SWITCH_SYMBOL], symbols,
                                    {"holdout": [sell_backtest.HOLDOUT], "basket": list(switch_plan.REPLAY_BASKET)},
                                    threshold_ratio=tax["threshold"] / price, target_ratio=float(item.get("target_avg") or price * 1.1) / price)
    (DATA / switch_plan.RESULT_FILE).write_text(json.dumps(report, ensure_ascii=False, indent=1))
    return report


def sell_backtest_due() -> bool:
    report = sell_backtest.load(DATA)
    return not report or _hours_since(report["generated_at"]) > 24 * sell_backtest.CACHE_DAYS


# ---- 一年收益目标 ---------------------------------------------------------------------------------

def target_histories() -> dict[str, dict[str, list[float]]]:
    """长日线取缓存；缓存过期照样先用，后台再刷新。"""
    symbols = (*target_plan.PLAN, *target_plan.BACKTEST_EXTRA)
    cache = DATA / target_plan.HISTORY_FILE
    if not cache.exists():
        return target_plan.load_histories(DATA, symbols)
    if target_plan_due():
        threading.Thread(target=_refresh_target_quietly, daemon=True).start()
    stored = json.loads(cache.read_text()).get("symbols", {})
    if any(s not in stored for s in symbols):
        return target_plan.load_histories(DATA, symbols)
    return {s: stored[s] for s in symbols}


def target_plan_due() -> bool:
    cache = DATA / target_plan.HISTORY_FILE
    report = target_plan.load(DATA)
    return (not cache.exists() or time.time() - cache.stat().st_mtime > target_plan.CACHE_HOURS * 3600
            or not report or _hours_since(report["generated_at"]) > target_plan.CACHE_HOURS)


def _refresh_target_quietly() -> None:
    try:
        run_target_backtest(refresh=True)
    except Exception:
        pass


def run_target_backtest(refresh: bool = False) -> dict[str, Any]:
    """重拉长日线（要求时）并重跑滚动检验（约 10 秒），写报告。"""
    if not _target_lock.acquire(blocking=False):
        raise Busy("目标计划正在刷新")
    try:
        report = target_plan.run_backtest(DATA, refresh=refresh)
        target_plan.load_valuation(DATA, refresh=refresh)
        target_plan.save(report, DATA)
        path = DATA / "target-plan-backtest.md"
        path.write_text(target_plan.markdown(report), encoding="utf-8")
        return {"generated_at": report["generated_at"], "elapsed_seconds": report["elapsed_seconds"], "report": str(path)}
    finally:
        _target_lock.release()


def _with_latest_price(symbol: str, history: dict[str, list[float]]) -> tuple[list[float], dict[str, Any] | None]:
    """日收盘序列，有更新的报价时把今天的价格接在最后。"""
    closes = list(history["close"])
    try:
        quote = current_price(symbol)
    except ValueError:
        return closes, None
    last_day = datetime.fromtimestamp(history["ts"][-1], UTC).date()
    try:
        observed = datetime.fromisoformat(quote["observed_at"]).astimezone(UTC).date()
    except (TypeError, ValueError):
        return closes, None
    # 差太多说明价格口径不同（比如未复权），那就信历史
    if abs(quote["price"] / closes[-1] - 1) > 0.25:
        return closes, None
    if observed > last_day:
        closes.append(quote["price"])
    elif observed == last_day:
        closes[-1] = quote["price"]
    return closes, quote


def target(goal: float | None = None, shape: str | None = None, delay: int | None = None) -> dict[str, Any]:
    tp = target_plan
    delay = tp.DEFAULT_DELAY if delay is None else int(delay)
    if delay not in tp.DELAY_MONTHS:
        raise ValueError(f"到账延迟必须是 {', '.join(map(str, tp.DELAY_MONTHS))} 个月之一")
    shape = shape or tp.DEFAULT_SHAPE
    if shape not in tp.LADDER_SHAPES:
        raise ValueError(f"买入方式必须是 {', '.join(tp.LADDER_SHAPES)} 之一")
    goal = tp.DEFAULT_TARGET if goal is None else float(goal)
    low, high = tp.TARGET_RANGE
    if not (math.isfinite(goal) and low <= goal <= high):
        raise ValueError(f"目标收益必须在 {low * 100:.0f}%–{high * 100:.0f}% 之间")
    histories = target_histories()
    profiles, estimates, news_rows = latest_research("profile"), latest_research("estimates"), recent_news()
    assets, results, closes_by_symbol = [], {}, {}
    try:
        valuation_data = tp.load_valuation(DATA)
        h = histories[tp.TIMING_SYMBOL]
        timing = tp.dividend_timing(valuation_data, h["close"], h["ts"]) if valuation_data else None
    except Exception:       # 估值源是可选的：没有它就只用趋势信号
        timing = None
    for symbol in tp.FOCUS:
        closes, quote = _with_latest_price(symbol, histories[symbol])
        closes_by_symbol[symbol] = closes
        result = results[symbol] = tp.assess(closes, goal, years0=tp.shrink_years(symbol))
        # QQQ 自己的记录从 1999 年开始；NASDAQ-100 指数同样的敞口能追到 1990 年
        similar_source = "^NDX" if symbol == "QQQ" else symbol
        similar = tp.similar_states(histories[similar_source]["close"], goal, result["state"])
        profile = ((profiles.get(symbol) or {}).get("payload") or {}).get("valuation") or {}
        surprises = (((estimates.get(symbol) or {}).get("payload") or {}).get("surprises") or [])[-4:]
        beats = [r for r in surprises if r.get("surprise_pct") is not None]
        valuation = {"forwardPE": profile.get("forwardPE"), "trailingPE": profile.get("trailingPE"),
                     "beat_count": sum(r["surprise_pct"] > 0 for r in beats), "beat_window": len(beats)}
        week = [r for r in news_rows if symbol in r.get("symbols", []) and _hours_since(r["published_at"]) <= 24 * 7]
        tones = [sell_plan.tag_news(r["title"], {})["tone"] for r in week]
        news = {"count": len(week), "positive": tones.count("positive"), "negative": tones.count("negative"),
                "headlines": [{k: r[k] for k in ("title", "url", "source", "published_at")} for r in week[:3]]}
        context = {"similar": similar, "similar_source": tp.LABELS.get(similar_source, similar_source), "valuation": valuation, "news": news}
        own_timing = timing if symbol == tp.TIMING_SYMBOL else None
        lines = tp.reasons(symbol, result, goal, context)
        if own_timing:
            lines.insert(-1, tp.timing_reason(own_timing))
        assets.append({
            "symbol": symbol, "name": tp.LABELS[symbol], "currency": asset(symbol)["currency"],
            "price": closes[-1], "quote": quote, "history_start": datetime.fromtimestamp(histories[symbol]["ts"][0], UTC).date().isoformat(),
            **{k: result[k] for k in ("mu", "spread", "probability", "loss10", "p10", "p50", "p90", "action", "state", "volatility", "long_run")},
            "action_label": tp.ACTION_LABELS[result["action"]],
            "pacing": (own_timing or {}).get("pacing") or tp.PACING[result["action"]],
            "curve": [{"target": g, "probability": tp.hit_probability(result["mu"], result["spread"], g)} for g in tp.CURVE],
            "similar": similar, "valuation": valuation, "news": news, "timing": own_timing, "reasons": lines,
        })
    # 债基组合：按净值，没有实时报价、趋势和新闻背景
    bond = histories[tp.BOND]
    closes_by_symbol[tp.BOND] = bond["close"]
    result = results[tp.BOND] = tp.assess_bond(bond["close"], bond["ts"], goal)
    assets.append({
        "symbol": tp.BOND, "name": tp.LABELS[tp.BOND], "currency": "CNY", "kind": "fund",
        "price": bond["close"][-1], "quote": None, "history_start": datetime.fromtimestamp(bond["ts"][0], UTC).date().isoformat(),
        "nav_date": datetime.fromtimestamp(bond["ts"][-1], UTC).date().isoformat(), "funds": bond.get("funds", {}),
        **{k: result[k] for k in ("mu", "spread", "probability", "loss10", "p10", "p50", "p90", "action", "state", "volatility", "long_run", "max_drawdown")},
        "action_label": "底仓 · 稳定器", "pacing": tp.BOND_PACING,
        "curve": [{"target": g, "probability": tp.hit_probability(result["mu"], result["spread"], g)} for g in tp.CURVE],
        "similar": None, "valuation": {}, "news": None, "reasons": tp.bond_reasons(result, bond.get("funds", {}), goal),
    })
    weekly = tp.weekly_returns({s: {"ts": histories[s]["ts"], "close": histories[s]["close"]} for s in tp.PLAN}, tp.PLAN)
    corr = tp.correlations(weekly)
    # 一年从今天算起；钱晚到就只投剩下的时间，到账前是现金
    hz = tp.delay_horizon(delay)
    wait_days, held_days = delay * tp.MONTH, tp.YEAR - delay * tp.MONTH
    modeled = tp.horizon_assets(results, hz)
    allocation = tp.allocate(modeled, corr, goal)
    allocation["curve"] = [{"target": g, "probability": tp.portfolio(allocation["weights"], modeled, corr, g)["probability"]} for g in tp.CURVE]
    allocation["correlations"] = corr
    funding = target_funding()
    allocation["funding"] = funding
    safe = tp.safe_allocate(modeled, corr, goal)
    safe["curve"] = [{"target": g, "probability": tp.portfolio(safe["weights"], modeled, corr, g)["probability"]} for g in tp.CURVE]
    safe["funding"] = funding
    # 等待的代价：同样的组合如果今天就有钱、投满一年
    for mode in (safe, allocation):
        mode["no_wait"] = {k: v for k, v in tp.portfolio(mode["weights"], results, corr, goal).items() if k in tp.SUMMARY_KEYS}
    # 各组合在共同历史（红利 ETF 2019 年上市起）上持有同样时长的真实表现
    for row in [safe, allocation, *safe["options"]]:
        row["history"] = tp.mix_history(histories, row["weights"], goal, days=held_days)
    currencies = {a["symbol"]: a["currency"] or "USD" for a in assets}
    fx = tp.fx_rates(DATA, [*currencies.values(), "USD"])
    # 基金按当日净值申购：没有挂单阶梯
    ladders = {tp.BOND: {"price": bond["close"][-1], "levels": [], "currency": "CNY", "arrival": None, "kind": "fund", "funds": bond.get("funds", {})}}
    for index, symbol in enumerate(tp.FOCUS):
        price = closes_by_symbol[symbol][-1]
        levels = tp.ladder_levels(symbol, price)
        result = results[symbol]
        # 红利指数偏便宜 / 偏贵时，ETF 的买入方式由估值择时决定；模型结果并排显示
        zone = timing.get("shape") if timing and symbol == tp.TIMING_SYMBOL else None
        extra = {"timing": tp.TIMING_SHAPES[zone]} if zone else None
        sim = tp.simulate_ladder(price, levels, result["volatility"]["daily"], result["mu"], goal, seed=11 + index, horizon=held_days, extra=extra)
        sim["dip_probability"] = [tp.dip_probability(price, level, result["volatility"]["daily"], result["mu"], tp.LADDER_DAYS) for level in levels]
        # 钱到账那天价格可能在哪：阶梯从那天的价格重新铺
        arrival = None
        if wait_days:
            w = wait_days / tp.YEAR
            mu_w, s_w = result["mu"] * w, tp.horizon_spread(result["spread"], w)
            arrival = {"days": wait_days, **{f"p{q}": price * (1 + tp.quantile(mu_w, s_w, q / 100)) for q in (10, 50, 90)},
                       "up": tp.hit_probability(mu_w, s_w, 0.0)}
        ladders[symbol] = {"price": price, "levels": levels, "currency": currencies[symbol], "arrival": arrival, **sim,
                           "timing": {"zone": zone, "zone_label": tp.TIMING_LABELS[zone], "weights": tp.TIMING_SHAPES[zone],
                                      "label": tp.TIMING_SHAPE_LABELS[zone]} if zone else None}
    # 每种买入方式都很便宜，一起算好，看板切换不用再请求
    for mode in (safe, allocation):
        mode["orders_by_shape"] = {name: target_orders(mode["weights"], ladders, fx, funding, name) for name in tp.LADDER_SHAPES}
        mode["orders"] = mode["orders_by_shape"][shape]
    return {
        "target": goal, "target_range": list(tp.TARGET_RANGE), "curve_targets": list(tp.CURVE),
        "assets": assets, "allocation": allocation, "safe": safe, "ladders": ladders, "fx": fx, "shape": shape,
        "delay": {"months": delay, "options": list(tp.DELAY_MONTHS), "wait_days": wait_days, "held_days": held_days, "horizon": hz},
        "ladder_model": {"depths": list(tp.LADDER_DEPTHS), "shapes": tp.LADDER_SHAPES, "labels": tp.LADDER_LABELS,
                         "days": tp.LADDER_DAYS, "lots": tp.LOTS},
        "model": {"prior": tp.PRIOR_LOG_RETURN, "shrink_years": tp.SHRINK_YEARS, "shrink_years_stock": tp.SHRINK_YEARS_STOCK,
                  "kappa": tp.KAPPA, "add_probability": tp.ADD_PROBABILITY, "reduce_probability": tp.REDUCE_PROBABILITY},
        "tax_note": "若收益按 20% 计税，税后 10% 需要税前约 12.5%：税前目标 = 税后目标 ÷ (1 − 税率)。",
        "backtest": target_backtest_summary(tp.load(DATA)),
        "generated_at": utc_now(),
    }


def target_orders(weights: dict[str, float], ladders: dict[str, Any], fx: dict[str, Any], funding: dict[str, Any] | None,
                  shape_name: str) -> list[dict[str, Any]]:
    """每个持有的标的：按今天汇率换算它那份港币，铺到指定的挂单形状上。"""
    rows = []
    for symbol, weight in weights.items():
        if weight <= 0:
            continue
        ladder = ladders[symbol]
        hkd = funding["net"] * weight if funding else None
        rate = fx[ladder["currency"]]["rate"]
        amount = hkd * rate if hkd is not None else None
        if ladder.get("kind") == "fund":
            funds = ladder["funds"]
            split = [{"code": code, "name": f["name"], "amount": amount / len(funds) if amount else None} for code, f in funds.items()]
            rows.append({"symbol": symbol, "weight": weight, "hkd": hkd, "currency": ladder["currency"], "fx": rate, "amount": amount,
                         "shape": shape_name, "kind": "fund", "funds": split, "plan": None})
            continue
        timing = ladder.get("timing")
        shape = timing["weights"] if timing else target_plan.LADDER_SHAPES[shape_name]
        plan = target_plan.ladder_orders(symbol, ladder["price"], ladder["levels"], shape, amount, ladder["dip_probability"]) if amount else None
        rows.append({"symbol": symbol, "weight": weight, "hkd": hkd, "currency": ladder["currency"], "fx": rate, "amount": amount,
                     "shape": "timing" if timing else shape_name, "timing": timing, "plan": plan})
    return rows


def target_funding() -> dict[str, Any] | None:
    """美团卖完能腾出的钱：剩余股数 × 现价，扣费用和税。"""
    item = next((p for p in positions() if p["symbol"] == sell_backtest.HOLDOUT), None)
    if not item:
        return None
    try:
        price = current_price(item["symbol"])["price"]
    except ValueError:
        return None
    remaining = int(item["shares"]) - sum(r["shares"] for r in trades(item["symbol"]))
    if remaining <= 0:
        return None
    costs = sell_plan.cost_schedule("HK", read_positions().get("costs"))
    tax = switch_plan.tax_settings(item.get("tax"))
    gross = remaining * price
    fee = sell_plan.order_cost(price, remaining, costs)["total"]
    levy = tax["rate"] * max(0.0, price - tax["threshold"]) * remaining
    return {"symbol": item["symbol"], "shares": remaining, "price": price, "gross": gross, "costs": fee, "tax": levy,
            "net": gross - fee - levy, "currency": asset(item["symbol"], item)["currency"]}


def target_backtest_summary(report: dict[str, Any] | None) -> dict[str, Any] | None:
    if not report:
        return None
    pooled = report["pooled"]
    return {"generated_at": report["generated_at"], "target": report["target"], "pooled_symbols": report["pooled_symbols"],
            "all": pooled["all"], "eras": pooled["eras"], "actions_by_era": pooled["actions_by_era"], "buckets": pooled["buckets"],
            "portfolios": report["portfolios"], "ladders": report.get("ladders"),
            "ladder_verdict": target_plan.ladder_verdict(report.get("ladders") or {}),
            "verdict": target_plan._replay_verdict(report["portfolios"]["focus"]["strategies"], report["portfolios"]["long"]["strategies"]),
            "stale": _hours_since(report["generated_at"]) > 24 * 7}


# ---- 持仓与成交登记 -------------------------------------------------------------------------------

def update_position(symbol: str, changes: dict[str, Any]) -> dict[str, Any]:
    position(symbol)
    cleaned: dict[str, Any] = {}
    for key in ("target_avg", "cost_basis"):
        if key in changes:
            value = changes[key]
            if value in (None, ""):
                cleaned[key] = None
            elif isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"{key} 必须是正数")
            else:
                cleaned[key] = float(value)
    if "shares" in changes:
        if isinstance(changes["shares"], bool) or not isinstance(changes["shares"], int) or changes["shares"] <= 0:
            raise ValueError("shares 必须是正整数")
        cleaned["shares"] = changes["shares"]
    if "horizon_days" in changes:
        value = changes["horizon_days"]
        if isinstance(value, bool) or not isinstance(value, int) or not (value == 0 or 5 <= value <= 252):
            raise ValueError("horizon_days 必须是 0（不设期限）或 5–252 个交易日（1 年）：更长的固定期限没有回测支撑")
        cleaned["horizon_days"] = value
    if "compare_days" in changes:
        if isinstance(changes["compare_days"], bool) or changes["compare_days"] not in switch_plan.COMPARE_DAYS:
            raise ValueError(f"compare_days 必须是 {', '.join(map(str, switch_plan.COMPARE_DAYS))} 之一")
        cleaned["compare_days"] = changes["compare_days"]
    if "shape" in changes:
        if changes["shape"] not in sell_plan.SHAPES:
            raise ValueError(f"shape 必须是 {', '.join(sell_plan.SHAPES)} 之一")
        cleaned["shape"] = changes["shape"]
    with _positions_lock:
        payload = read_positions()
        for item in payload["positions"]:
            if item["symbol"] == symbol:
                item.update(cleaned)
        write_positions(payload)
    return {"updated": symbol, "changes": cleaned}


def add_trade(symbol: str, shares: Any, price: Any, executed_at: str | None = None, note: str = "") -> dict[str, Any]:
    item = position(symbol)
    if isinstance(shares, bool) or not isinstance(shares, int) or shares <= 0:
        raise ValueError("成交股数必须是正整数")
    if isinstance(price, bool) or not isinstance(price, (int, float)) or not math.isfinite(price) or price <= 0:
        raise ValueError("成交价必须是正数")
    sold = sum(r["shares"] for r in trades(symbol))
    if sold + shares > int(item["shares"]):
        raise ValueError(f"累计卖出 {sold + shares} 股会超过持仓 {item['shares']} 股")
    when = executed_at or utc_now()
    try:
        datetime.fromisoformat(when)
    except ValueError as exc:
        raise ValueError("成交时间格式应为 ISO 8601") from exc
    trade_id = db.insert("wealth_trades", {"symbol": symbol, "executed_at": when, "shares": shares, "price": float(price),
                                           "note": str(note)[:200], "created_at": utc_now()})
    return {"id": trade_id, "symbol": symbol, "shares": shares, "price": float(price), "executed_at": when}


def delete_trade(trade_id: int) -> dict[str, Any]:
    if not db.execute("DELETE FROM wealth_trades WHERE id=?", (trade_id,)):
        raise ValueError(f"成交记录 {trade_id} 不存在")
    return {"deleted": trade_id}


def _bucket(symbol: str) -> str:
    return f"position:{symbol}"


def _hours_since(value: str | None) -> float:
    if not value:
        return math.inf
    try:
        then = datetime.fromisoformat(value)
    except ValueError:
        return math.inf
    if then.tzinfo is None:
        then = then.astimezone()
    return (datetime.now(UTC) - then).total_seconds() / 3600


def data_dir() -> Path:
    return DATA
