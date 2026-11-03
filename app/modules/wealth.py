"""理财板块：一年收益目标（QQQ / 谷歌 / 微软 / 红利低波 + 债基底仓，含买入时机和挂单）、美团减持 / 换仓计划、信号提醒。

计算从 wealth 仓库迁来（_wealth_*）；数据在 data/wealth/ 和 app.db 的 wealth_* 表。
后台每 wealth.refresh_minutes 分钟刷新行情和新闻、重算信号，有变化就通过 app.notify 提醒（页内 + Mac），每天 wealth.summary_time 发一条汇总。
统计估算，不构成投资建议。
"""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException

from .. import db, notify, settings
from . import _wealth_alerts as alerts
from . import _wealth_service as svc
from ._wealth_service import SCHEMA  # noqa: F401 —— main 按模块的 SCHEMA 建表

log = logging.getLogger(__name__)

TITLE = "理财"
ORDER = 45
EXIT_SYMBOL = "3690.HK"
TICK_SECONDS = 300

router = APIRouter()
_check_lock = threading.Lock()


def cfg(key: str, default: Any = None) -> Any:
    return settings.get(f"wealth.{key}", default)


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except svc.Busy as exc:
        raise HTTPException(409, str(exc)) from exc
    except (ValueError, KeyError) as exc:
        raise HTTPException(400, str(exc)) from exc


# ---------------------------------------------------------------- 接口

@router.get("/target-plan")
def get_target_plan(target: float | None = None, shape: str | None = None, delay: int | None = None, drawdown: float | None = None):
    return _call(svc.target, target if target is not None else cfg("target"), shape, delay, drawdown)


@router.get("/region-mix")
def get_region_mix(overseas: float | None = None, basket: str | None = None):
    return _call(svc.region_mix, overseas, basket)


@router.get("/sell-plan")
def get_sell_plan(symbol: str = EXIT_SYMBOL, target_avg: float | None = None, horizon_days: int | None = None,
                  now_shares: int | None = None, shape: str | None = None, compare_days: int | None = None,
                  qqq_return: float | None = None, stock_return: float | None = None):
    return _call(svc.sell, symbol, target_avg, horizon_days, now_shares, shape, compare_days, qqq_return, stock_return)


@router.post("/positions")
def post_position(body: dict):
    symbol = body.get("symbol") or EXIT_SYMBOL
    return _call(svc.update_position, symbol, {k: v for k, v in body.items() if k != "symbol"})


@router.post("/trades")
def post_trade(body: dict):
    return _call(svc.add_trade, body.get("symbol") or EXIT_SYMBOL, body.get("shares"), body.get("price"),
                 body.get("executed_at") or None, body.get("note") or "")


@router.delete("/trades/{trade_id}")
def remove_trade(trade_id: int):
    return _call(svc.delete_trade, trade_id)


@router.post("/refresh")
def post_refresh():
    """手动刷新：行情和新闻同步跑（十几秒），回测在后台补。"""
    stats = _call(svc.refresh)
    threading.Thread(target=_after_refresh, daemon=True, name="wealth-after-refresh").start()
    return stats


@router.post("/backtest/{kind}")
def post_backtest(kind: str):
    """重跑回测（后台）：target = 目标计划（约 10 秒，含重拉长日线）；sell = 减持 / 换仓（约 2 分钟）。"""
    runner = {"target": lambda: svc.run_target_backtest(refresh=True), "sell": svc.run_sell_backtest}.get(kind)
    if runner is None:
        raise HTTPException(404, "kind 只能是 target 或 sell")
    threading.Thread(target=_quietly, args=(runner,), daemon=True, name=f"wealth-backtest-{kind}").start()
    return {"started": kind}


@router.get("/status")
def status():
    store = alerts.load(svc.DATA)
    return {"refresh": svc.job_state("positions"), "alerts": {"checked_at": store["checked_at"], "summary_date": store["summary_date"]},
            "settings": settings.get("wealth", {}), "system_notify": settings.get("notify.system", True),
            "live": {k: v for k, v in svc.LIVE.snapshot().items() if k != "quotes"} if svc.LIVE else None}


@router.get("/alerts")
def get_alerts(limit: int = 50):
    store = alerts.load(svc.DATA)
    return {"log": notify.list_notifications(alerts.MODULE, limit), "checked_at": store["checked_at"],
            "summary_date": store["summary_date"], "state": store["state"], "settings": settings.get("wealth", {})}


@router.post("/alerts/check")
def post_check(body: dict | None = None):
    """立刻重算信号；summary=true 时不管时间都发一条汇总。"""
    return check_alerts(force_summary=bool((body or {}).get("summary")))


@router.post("/alerts/test")
def post_test():
    nid = notify.notify(alerts.MODULE, "理财提醒测试", "看到这条说明页内提醒和 Mac 系统通知都通了。", ["这是一条测试通知。"],
                        link="#wealth/alerts", kind="test")
    return {"id": nid}


# ---------------------------------------------------------------- 信号提醒

def check_alerts(force_summary: bool = False, now: datetime | None = None) -> dict[str, Any]:
    """重算目标计划和美团减持计划，跟上次的快照比；变化逐条提醒，到点发汇总。"""
    if not _check_lock.acquire(blocking=False):
        raise HTTPException(409, "信号正在重算")
    try:
        now = now or datetime.now()
        plan = svc.target(cfg("target"))
        try:
            exit_plan = svc.sell(EXIT_SYMBOL) if any(p["symbol"] == EXIT_SYMBOL for p in svc.positions()) else None
        except ValueError:
            exit_plan = None
        store = alerts.load(svc.DATA)
        cur = alerts.snapshot(plan, exit_plan)
        events = alerts.changes(store["state"], cur)
        enabled = bool(cfg("alerts", True))
        sent = []
        for e in events:
            if enabled:
                _send(e)
            sent.append(e)
        if force_summary or (enabled and alerts.summary_due(store, now, cfg("summary_time", "16:30"))):
            e = alerts.summary(cur)
            _send(e)
            sent.append(e)
            store["summary_date"] = now.date().isoformat()
        store.update(state=cur, checked_at=db.now())
        alerts.save(svc.DATA, store)
        return {"events": sent, "checked_at": store["checked_at"], "enabled": enabled}
    finally:
        _check_lock.release()


def _send(event: dict[str, Any]) -> int:
    link = "#wealth/sell" if event["kind"].startswith("exit") else "#wealth/target"
    return notify.notify(alerts.MODULE, event["title"], event["body"], event["reasons"], link=link, kind=event["kind"],
                         subtitle="统计估算，不构成投资建议")


# ---------------------------------------------------------------- 后台

def _quietly(fn) -> None:
    try:
        fn()
    except svc.Busy:
        pass
    except Exception:  # noqa: BLE001 —— 下一轮再试
        log.exception("理财后台任务失败：%s", getattr(fn, "__name__", fn))


def _after_refresh() -> None:
    if svc.target_plan_due():
        _quietly(lambda: svc.run_target_backtest(refresh=True))
    _quietly(check_alerts)


def _refresh_due() -> bool:
    state = svc.job_state("positions") or {}
    return svc._hours_since(state.get("last_completed_at")) * 60 >= float(cfg("refresh_minutes", 60) or 60)


def _tick() -> None:
    if _refresh_due():
        _quietly(svc.refresh)
        _after_refresh()
    else:
        store = alerts.load(svc.DATA)
        if cfg("alerts", True) and alerts.summary_due(store, datetime.now(), cfg("summary_time", "16:30")):
            _quietly(check_alerts)
    if svc.sell_backtest_due():
        _quietly(svc.run_sell_backtest)


def _loop() -> None:
    time.sleep(20)   # 等服务起完再联网
    while True:
        _quietly(_tick)
        time.sleep(TICK_SECONDS)


def on_startup() -> None:
    svc.DATA.mkdir(parents=True, exist_ok=True)
    if os.environ.get("SELF_STARTUP_NO_AUTOREFRESH"):
        return
    svc.start_live()
    threading.Thread(target=_loop, daemon=True, name="wealth-loop").start()


def agent_context(ref: str) -> str:
    state = alerts.load(svc.DATA)["state"] or {}
    lines = [f"{a['name']}：{a['label']}，一年达标概率 {a['probability']:.0%}。{a['reason']}" for a in (state.get("assets") or {}).values()]
    e = state.get("exit")
    if e:
        lines.append(f"{e['name']}：现价 {e['price']} {e['currency']}，剩余 {e['remaining']:,} 股，建议现卖 {e['now_shares']:,} 股，"
                     f"目标均价 {e['target_avg']}，达标概率 {e['probability']:.0%}。")
    return ("理财信号（统计估算，不构成投资建议）：\n" + "\n".join(lines)) if lines else "理财板块还没有算过信号。"
