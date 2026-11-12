"""通用通知：任何板块调 notify() —— 写进 notifications 表（页面轮询后右下角弹出，各板块可查记录），
设置里 notify.system 打开时同时发 macOS 系统通知。"""
from __future__ import annotations

import json
import logging
import subprocess
import sys

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

router = APIRouter(prefix="/api/notify", tags=["notify"])


def notify(module: str, title: str, body: str = "", reasons: list[str] | None = None, link: str = "", kind: str = "",
           subtitle: str = "") -> int:
    sent = system(title, body, subtitle)
    return db.insert("notifications", {"module": module, "kind": kind, "title": title, "body": body, "reasons": reasons or [],
                                       "link": link, "system": int(sent), "created_at": db.now()})


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
    out = [{"at": n["created_at"], "title": n["title"], "body": n["body"], "link": n["link"], "module": n["module"], "failed": False}
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
