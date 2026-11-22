"""通用通知：任何板块调 notify() —— 写进 notifications 表（页面轮询后右下角弹出，各板块可查记录），
设置里 notify.system 打开时同时发 macOS 系统通知。"""
from __future__ import annotations

import json
import logging
import subprocess
import sys
from datetime import datetime, timedelta

from fastapi import APIRouter

from . import db, settings

log = logging.getLogger(__name__)

SCHEMA = """
-- 板块发出的提醒；reasons = JSON 数组，提醒的理由（页面展开显示）
CREATE TABLE IF NOT EXISTS notifications (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    module      TEXT NOT NULL,
    kind        TEXT DEFAULT '',
    title       TEXT NOT NULL,
    body        TEXT DEFAULT '',
    reasons     TEXT DEFAULT '[]',
    link        TEXT DEFAULT '',              -- 前端路由，如 #wealth/target
    system      INTEGER DEFAULT 0,            -- 是否已发出系统通知
    created_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_notifications_module ON notifications(module, id);
"""

FAILURE_SCHEMA = """
-- 定时任务的失败状态：key = 板块:来源；open = 还在失败，恢复后清零
CREATE TABLE IF NOT EXISTS notify_failures (
    key         TEXT PRIMARY KEY,
    module      TEXT NOT NULL,
    error       TEXT DEFAULT '',
    open        INTEGER DEFAULT 1,
    count       INTEGER DEFAULT 0,
    first_at    TEXT,
    last_at     TEXT,
    notified_at TEXT
);
"""
_failure_ready = False

REALERT_HOURS = 24

router = APIRouter(prefix="/api/notify", tags=["notify"])


def notify(module: str, title: str, body: str = "", reasons: list[str] | None = None, link: str = "", kind: str = "",
           subtitle: str = "", mac: bool = True) -> int:
    sent = mac and system(title, body, subtitle)
    return db.insert("notifications", {"module": module, "kind": kind, "title": title, "body": body, "reasons": reasons or [],
                                       "link": link, "system": int(sent), "created_at": db.now()})


def failures(module: str, what: str, results: dict[str, str], link: str = "", names: dict[str, str] | None = None) -> int | None:
    """定时任务的抓取 / 解析结果 {来源: 错误}，错误为空 = 正常。同一来源一直失败只提醒一次，恢复后再坏、且距上次提醒超过 REALERT_HOURS 才再提醒；
    一轮里新坏的来源合成一条消息，相同错误归在一起。返回新消息 id，没有新提醒返回 None。"""
    global _failure_ready
    if not _failure_ready:   # 板块子进程（开源雷达）和单测不走 app 启动建表
        db.execute(FAILURE_SCHEMA)
        _failure_ready = True
    now = db.now()
    cutoff = (datetime.now() - timedelta(hours=REALERT_HOURS)).isoformat(timespec="seconds")
    fresh: dict[str, str] = {}
    for name, err in results.items():
        key = f"{module}:{name}"
        r = db.row("SELECT * FROM notify_failures WHERE key=?", [key])
        if not err:
            if r and r["open"]:
                db.execute("UPDATE notify_failures SET open=0 WHERE key=?", [key])
            continue
        err = " ".join(str(err).split())[:200]
        quiet = r and (r["open"] or (r["notified_at"] or "") > cutoff)
        db.execute("INSERT INTO notify_failures(key, module, error, open, count, first_at, last_at, notified_at) VALUES(?,?,?,1,1,?,?,?) "
                   "ON CONFLICT(key) DO UPDATE SET error=excluded.error, count=CASE WHEN open THEN count+1 ELSE 1 END, "
                   "first_at=CASE WHEN open THEN first_at ELSE excluded.first_at END, open=1, last_at=excluded.last_at, "
                   "notified_at=CASE WHEN ? THEN notified_at ELSE excluded.notified_at END",
                   [key, module, err, now, now, now, int(bool(quiet))])
        if not quiet:
            fresh[name] = err
    if not fresh:
        return None
    label = lambda n: (names or {}).get(n, n)  # noqa: E731
    groups: dict[str, list[str]] = {}
    for name, err in fresh.items():
        groups.setdefault(err, []).append(label(name))
    shown = [label(n) for n in fresh]
    title = f"{what}失败：{'、'.join(shown[:3])}{f' 等 {len(shown)} 个' if len(shown) > 3 else ''}"
    reasons = [f"{'、'.join(ns)}：{err}" for err, ns in groups.items()]
    return notify(module, title, "；".join(reasons)[:600], reasons, link, kind="failure",
                  subtitle="同一来源一直失败不再重复提醒，恢复后再坏才会再提醒")


def system(title: str, body: str = "", subtitle: str = "") -> bool:
    """只发 Mac 系统通知、不进页内提醒（页内已有别的提醒时用，比如后台任务结束）。"""
    return bool(settings.get("notify.system", True)) and system_notify(title, body, subtitle)


def system_notify(title: str, body: str, subtitle: str = "") -> bool:
    """macOS 通知中心；文字走 argv，引号不用转义。不是 macOS 就跳过。"""
    if sys.platform != "darwin":
        return False
    script = ["on run argv", "display notification (item 2 of argv) with title (item 1 of argv) subtitle (item 3 of argv)", "end run"]
    args = ["osascript", *sum((["-e", line] for line in script), []), title, body[:240], subtitle]
    try:
        return subprocess.run(args, capture_output=True, timeout=10).returncode == 0
    except (OSError, subprocess.SubprocessError):
        log.warning("系统通知发送失败", exc_info=True)
        return False


def _decode(rows: list[dict]) -> list[dict]:
    for r in rows:
        try:
            r["reasons"] = json.loads(r.get("reasons") or "[]")
        except json.JSONDecodeError:
            r["reasons"] = []
    return rows


@router.get("")
def list_notifications(module: str = "", limit: int = 50):
    if module:
        return _decode(db.rows("SELECT * FROM notifications WHERE module=? ORDER BY id DESC LIMIT ?", (module, min(limit, 500))))
    return _decode(db.rows("SELECT * FROM notifications ORDER BY id DESC LIMIT ?", (min(limit, 500),)))


@router.get("/history")
def history(limit: int = 80):
    """消息中心：弹过的提醒（通知 + 后台任务完成 / 失败）按时间倒序放一处，错过了也能找回来。"""
    from . import jobs
    limit = min(limit, 300)
    out = [{"at": n["created_at"], "title": n["title"], "body": n["body"], "link": n["link"], "module": n["module"],
            "failed": n["kind"] == "failure"}
           for n in db.rows("SELECT * FROM notifications ORDER BY id DESC LIMIT ?", (limit,))]
    for j in db.rows("SELECT id, module, ref, status, finished_at FROM jobs WHERE status IN ('done','failed') AND finished_at IS NOT NULL "
                     "ORDER BY finished_at DESC LIMIT ?", (limit,)):
        title, link, kind = jobs.describe(j)
        ok = j["status"] == "done"
        out.append({"at": j["finished_at"], "title": f"{kind}{'完成' if ok else '失败'}", "body": title, "link": link,
                    "module": j["module"], "failed": not ok})
    return sorted(out, key=lambda x: x["at"] or "", reverse=True)[:limit]


@router.get("/since")
def since(after: int = -1):
    """页面轮询：after<0（刚打开页面）只返回当前最大 id，不把旧通知全弹一遍；之后带上次的 last 来取新的。"""
    if after < 0:
        return {"last": (db.row("SELECT max(id) AS n FROM notifications") or {}).get("n") or 0, "items": []}
    items = _decode(db.rows("SELECT * FROM notifications WHERE id>? ORDER BY id LIMIT 20", (after,)))
    return {"last": items[-1]["id"] if items else after, "items": items}
