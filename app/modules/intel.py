"""产品雷达（设计稿 docs/designs/2026-11-01-product-intel-design.md）。

目前只有第 6 个标签「开源雷达」：stars ≥ 1000 的 GitHub 项目按功能检索（docs/designs/2026-11-01-oss-radar-design.md）。
采集 / 标注 / 检索在 _oss_collect / _oss_label / _oss_search；长任务在独立进程 _oss_run 里跑，不新建服务。
"""
from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import db
from . import _oss_collect as col, _oss_label as lab, _oss_search as srch

log = logging.getLogger(__name__)

TITLE = "产品雷达"
ORDER = 35
SCHEMA = col.SCHEMA
router = APIRouter()

TASKS = {"collect": "全量采集", "label": "标注", "daily": "每日新增", "weekly": "每周刷新"}
DAILY_HOURS, WEEKLY_DAYS = 24, 7


# ---------- 长任务 ----------

def _alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def running() -> dict | None:
    for r in db.rows("SELECT * FROM oss_runs WHERE status='running' ORDER BY id DESC"):
        if r["pid"] and not _alive(r["pid"]):   # 进程没了（机器重启）：标失败，下次可以重新开
            db.update("oss_runs", r["id"], {"status": "failed", "log": "进程已退出", "finished": db.now()})
            continue
        return r
    return None


def _spawn(rid: int) -> None:
    logs = db.DATA_DIR / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    with open(logs / "oss.log", "ab") as out:
        subprocess.Popen([sys.executable, "-m", "app.modules._oss_run", str(rid)], cwd=str(db.ROOT),
                         stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT, start_new_session=True)


def start_run(task: str, limit: int = 0) -> dict:
    if task not in TASKS:
        raise HTTPException(400, f"未知任务：{task}")
    if cur := running():
        raise HTTPException(409, f"已有任务在跑：{TASKS.get(cur['task'], cur['task'])}（#{cur['id']}）")
    rid = db.insert("oss_runs", {"task": task, "status": "running", "progress": {"limit": limit} if limit else {},
                                 "started": db.now()})
    _spawn(rid)
    return db.row("SELECT * FROM oss_runs WHERE id=?", [rid])


def stop_run(rid: int) -> dict:
    r = db.row("SELECT * FROM oss_runs WHERE id=?", [rid])
    if not r:
        raise HTTPException(404, "没有这个任务")
    if r["status"] == "running" and r["pid"] and _alive(r["pid"]):
        os.kill(r["pid"], signal.SIGTERM)   # 当前批次做完后停
    elif r["status"] == "running":
        db.update("oss_runs", rid, {"status": "stopped", "finished": db.now()})
    return db.row("SELECT * FROM oss_runs WHERE id=?", [rid])


def _last(task: str) -> str:
    r = db.row("SELECT started FROM oss_runs WHERE task=? AND status IN ('done','running') ORDER BY id DESC LIMIT 1", [task])
    return r["started"] if r else ""


def maybe_schedule() -> str:
    """库建起来以后（有标注过的仓库）才自动跑：每天一次新增，每周一次刷新。全量采集 / 全量标注只手动开。"""
    if running() or not db.row("SELECT 1 AS x FROM oss_labels LIMIT 1"):
        return ""
    now = datetime.now()
    if _last("weekly") < (now - timedelta(days=WEEKLY_DAYS)).isoformat(timespec="seconds") \
            and _last("collect") < (now - timedelta(days=WEEKLY_DAYS)).isoformat(timespec="seconds"):
        start_run("weekly")
        return "weekly"
    if _last("daily") < (now - timedelta(hours=DAILY_HOURS)).isoformat(timespec="seconds"):
        start_run("daily")
        return "daily"
    return ""


def _auto_loop():
    time.sleep(120)
    while True:
        try:
            if s := maybe_schedule():
                log.info("oss radar auto run: %s", s)
        except Exception as e:  # noqa: BLE001
            log.warning("oss radar schedule failed: %s", e)
        time.sleep(1800)


def on_startup():
    if os.environ.get("SELF_STARTUP_NO_AUTOREFRESH"):
        return
    threading.Thread(target=_auto_loop, daemon=True, name="oss-radar-auto").start()


# ---------- 接口 ----------

def status() -> dict:
    n = lambda sql, a=(): db.row(sql, a)["n"]  # noqa: E731
    by_d = {r["d"]: r["n"] for r in db.rows("SELECT d, count(*) AS n FROM oss_labels l JOIN oss_repos r ON r.name=l.name "
                                             "WHERE r.status='ok' AND r.stars>=900 GROUP BY d")}
    return {"repos": n("SELECT count(*) AS n FROM oss_repos WHERE status='ok' AND stars>=900"),
            "labeled": n("SELECT count(*) AS n FROM oss_labels"),
            "gone": n("SELECT count(*) AS n FROM oss_repos WHERE status='gone'"),
            "todo": len(lab.todo()),
            "tax_ver": lab.taxonomy()["version"], "by_domain": by_d,
            "running": running(), "runs": db.rows("SELECT * FROM oss_runs ORDER BY id DESC LIMIT 8"),
            "last": {t: _last(t) for t in TASKS}}


@router.get("/oss/status")
def oss_status():
    return status()


@router.get("/oss/taxonomy")
def oss_taxonomy():
    return lab.taxonomy()


@router.get("/oss/search")
def oss_search(q: str = "", by: str = "rel", kind: str = "", domain: str = "", lang: str = "", active: int = 0,
               offset: int = 0, k: int = 30):
    if not q.strip():
        return {"mode": "browse", **srch.browse(domain, kind, lang, active, offset, k)}
    return {"mode": "search", **srch.search(q, by, kind, domain, lang, active, k)}


@router.get("/oss/repo")
def oss_repo(name: str):
    r = db.row("SELECT * FROM oss_repos WHERE name=?", [name])
    if not r:
        raise HTTPException(404, "库里没有这个仓库")
    r["label"] = db.row("SELECT * FROM oss_labels WHERE name=?", [name])
    return r


class RunIn(BaseModel):
    task: str
    limit: int = 0


@router.post("/oss/runs")
def oss_start(body: RunIn):
    return start_run(body.task, body.limit)


@router.post("/oss/runs/{rid}/stop")
def oss_stop(rid: int):
    return stop_run(rid)


# ---------- 给信息推荐用（设计稿 §7.1 反向复用） ----------

def labels_for(names: list[str]) -> dict[str, dict]:
    """owner/repo → 雷达标签（ai / s / d / t）；库里没有的不返回。"""
    if not names:
        return {}
    out = {}
    for i in range(0, len(names), 900):
        part = names[i:i + 900]
        for r in db.rows(f"SELECT name, k, d, ai, t, s, label_src FROM oss_labels WHERE name IN ({','.join('?' * len(part))})", part):
            r["t"] = json.loads(r["t"] or "[]")
            out[r["name"]] = r
    return out


def agent_context(ref: str) -> str:
    st = status()
    names = lab.domain_names()
    top = sorted(st["by_domain"].items(), key=lambda x: -x[1])[:15]
    return (f"开源雷达：库内 {st['repos']} 个 stars≥1000 的仓库，已标注 {st['labeled']}，待标注 {st['todo']}；"
            f"分类体系 {st['tax_ver']}。领域分布：" + "、".join(f"{names.get(d, d)} {c}" for d, c in top) +
            "\n检索接口：GET /api/intel/oss/search?q=<中文功能描述>&by=rel|stars")
