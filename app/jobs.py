"""后台 Agent 任务：长时间运行的调研/解析放到线程里跑，结果写 jobs 表，完成后回调板块的 on_job_done。"""
from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, HTTPException

from . import agent, db, kb, modules, settings

log = logging.getLogger(__name__)
# 各板块共享；比 Agent 并发度留些余量，避免长调研任务堵住短任务（拆解等）
_pool = ThreadPoolExecutor(max_workers=max(4, 2 * int(settings.get("max_agent_concurrency", 3))))
router = APIRouter(prefix="/api/jobs", tags=["jobs"])


def submit(module: str, prompt: str, *, ref: str = "", engine: str = "", system: str = "",
           cwd: str | None = None, add_dirs: list[str] | None = None, chat_session_id: int | None = None) -> int:
    """提交后台 Agent 任务，返回 job id。完成后调用 modules.<module>.on_job_done(job)，
    有 chat_session_id 时再把结果回帖到那个对话（对话里让 Agent 提交的任务，见 chat.link_jobs）。"""
    engine = engine or settings.get("engines.default", "claude")
    jid = db.insert("jobs", {"module": module, "ref": ref, "engine": engine, "prompt": prompt,
                             "status": "queued", "created_at": db.now(), "chat_session_id": chat_session_id})
    _pool.submit(_run, jid, module, prompt, engine, system, cwd, [*(add_dirs or []), str(kb.KB_DIR)])
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
    notify_chat(db.row("SELECT * FROM jobs WHERE id=?", [jid]))
    kb.schedule_sync()


def describe(job: dict) -> tuple[str, str, str]:
    """(标题, 页面链接, 类型) —— 给回帖、通知、交付列表用。"""
    ref, module = job.get("ref") or "", job["module"]

    def one(sql, *a):
        try:
            return db.row(sql, a) or {}
        except Exception:  # noqa: BLE001 —— 板块表可能不存在
            return {}
    if m := re.fullmatch(r"learn:item:(\d+)", ref):
        r = one("SELECT title,url FROM learn_items WHERE id=?", int(m[1]))
        return r.get("title") or r.get("url") or ref, f"#learn/item/{m[1]}", "深读笔记"
    if m := re.fullmatch(r"learn:plan:(\d+)", ref):
        return one("SELECT topic FROM learn_plans WHERE id=?", int(m[1])).get("topic") or ref, f"#learn/plan/{m[1]}", "学习计划"
    if m := re.fullmatch(r"research:(\d+):(r\d+|synth)", ref):
        topic = one("SELECT topic FROM research WHERE id=?", int(m[1])).get("topic") or ref
        return topic, f"#research/r/{m[1]}", "调研综合报告" if m[2] == "synth" else "调研结果"
    first = next((ln.strip("# ").strip() for ln in (job.get("prompt") or "").splitlines() if ln.strip()), "")
    return (first[:60] or ref or module), f"#{module}", "后台任务"


def notify_chat(job: dict | None) -> None:
    """任务结束后在发起它的对话里补一条 Agent 消息（完成 → 结果摘要 + 链接；失败 → 日志末尾）。"""
    if not job or not job.get("chat_session_id") or job["status"] not in ("done", "failed"):
        return
    sid = job["chat_session_id"]
    if not db.row("SELECT id FROM chat_sessions WHERE id=?", [sid]):
        return
    title, link, kind = describe(job)
    if job["status"] == "done":
        out = (job.get("output") or "").strip()
        body = out if len(out) <= 2500 else out[:2500] + "…"
        text = f"**{kind}完成** · [{title}]({link})\n\n{body}\n\n[打开查看 →]({link})"
    else:
        tail = "\n".join((job.get("log") or "").splitlines()[-8:])
        text = f"**{kind}失败** · [{title}]({link})\n\n```\n{tail or '（无日志）'}\n```\n可以在页面上点「重跑」，或告诉我怎么调整。"
    db.insert("chat_messages", {"session_id": sid, "role": "assistant", "content": text, "created_at": db.now()})
    db.update("chat_sessions", sid, {"updated_at": db.now()})


@router.get("/finished")
def finished(since: str):
    """since 之后结束的任务，前端轮询用来弹通知、刷新对话。"""
    out = []
    for j in db.rows("SELECT id,module,ref,status,prompt,chat_session_id,finished_at FROM jobs WHERE finished_at>? ORDER BY finished_at", [since]):
        title, link, kind = describe(j)
        j.pop("prompt")
        out.append({**j, "title": title, "link": link, "kind": kind})
    return out


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
