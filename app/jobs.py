"""后台 Agent 任务：长时间运行的调研/解析放到线程里跑，结果写 jobs 表，完成后回调板块的 on_job_done。"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, HTTPException

from . import agent, db, modules, settings

log = logging.getLogger(__name__)
_pool = ThreadPoolExecutor(max_workers=max(1, int(settings.get("max_agent_concurrency", 3))))
router = APIRouter(prefix="/api/jobs", tags=["jobs"])


def submit(module: str, prompt: str, *, ref: str = "", engine: str = "", system: str = "",
           cwd: str | None = None, add_dirs: list[str] | None = None) -> int:
    """提交后台 Agent 任务，返回 job id。完成后调用 modules.<module>.on_job_done(job)。"""
    engine = engine or settings.get("engines.default", "claude")
    jid = db.insert("jobs", {"module": module, "ref": ref, "engine": engine, "prompt": prompt,
                             "status": "queued", "created_at": db.now()})
    _pool.submit(_run, jid, module, prompt, engine, system, cwd, add_dirs or [])
    return jid


def _run(jid: int, module: str, prompt: str, engine: str, system: str, cwd, add_dirs) -> None:
    db.update("jobs", jid, {"status": "running", "started_at": db.now()})
    log_lines: list[str] = []
    text, session, used = "", "", engine
    try:
        for ev in agent.run_stream(prompt, engine=engine, system=system, cwd=cwd, add_dirs=add_dirs):
            if ev["type"] == "session":
                session = ev["id"]
            elif ev["type"] == "done":
                text, used = ev["text"], ev["engine"]
            elif ev["type"] in ("tool", "error", "engine"):
                log_lines.append(f"[{ev['type']}] {ev['text']}")
                db.update("jobs", jid, {"log": "\n".join(log_lines[-200:])})
        status = "done" if text else "failed"
    except Exception as e:  # noqa: BLE001
        log.exception("job %s failed", jid)
        log_lines.append(f"[exception] {e}")
        status = "failed"
    db.update("jobs", jid, {"status": status, "output": text, "engine": used, "engine_session": session,
                            "log": "\n".join(log_lines[-200:]), "finished_at": db.now()})
    mod = modules.get(module)
    hook = getattr(mod, "on_job_done", None) if mod else None
    if hook:
        try:
            hook(db.row("SELECT * FROM jobs WHERE id=?", [jid]))
        except Exception:  # noqa: BLE001
            log.exception("on_job_done %s/%s failed", module, jid)


@router.get("")
def list_jobs(module: str = "", ref: str = "", limit: int = 30):
    sql, args = "SELECT id,module,ref,engine,status,created_at,finished_at FROM jobs WHERE 1=1", []
    if module:
        sql, args = sql + " AND module=?", args + [module]
    if ref:
        sql, args = sql + " AND ref=?", args + [ref]
    return db.rows(sql + " ORDER BY id DESC LIMIT ?", args + [limit])


@router.get("/{jid}")
def get_job(jid: int):
    j = db.row("SELECT * FROM jobs WHERE id=?", [jid])
    if not j:
        raise HTTPException(404)
    return j


def _mark_interrupted() -> None:
    """进程重启时，把未完成的任务标记失败。"""
    db.execute("UPDATE jobs SET status='failed', log=log||'\n[interrupted by restart]' WHERE status IN ('queued','running')")
