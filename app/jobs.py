"""后台 Agent 任务：长时间运行的调研/解析放到线程里跑，结果写 jobs 表，完成后回调板块的 on_job_done。"""
from __future__ import annotations

import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import agent, db, kb, modules, settings

log = logging.getLogger(__name__)
# 各板块共享；比 Agent 并发度留些余量，避免长调研任务堵住短任务（拆解等）
_pool = ThreadPoolExecutor(max_workers=max(4, 2 * int(settings.get("max_agent_concurrency", 3))))
router = APIRouter(prefix="/api/jobs", tags=["jobs"])


def submit(module: str, prompt: str, *, ref: str = "", engine: str = "", system: str = "",
           cwd: str | None = None, add_dirs: list[str] | None = None, chat_session_id: int | None = None,
           session: str = "") -> int:
    """提交后台 Agent 任务，返回 job id。完成后调用 modules.<module>.on_job_done(job)，
    有 chat_session_id 时再把结果回帖到那个对话（对话里让 Agent 提交的任务，见 chat.link_jobs）。"""
    engine = engine or settings.get("engines.default", "claude")
    jid = db.insert("jobs", {"module": module, "ref": ref, "engine": engine, "prompt": prompt,
                             "status": "queued", "created_at": db.now(), "chat_session_id": chat_session_id, "cwd": cwd or ""})
    _pool.submit(_run, jid, module, prompt, engine, system, cwd, [*(add_dirs or []), str(kb.KB_DIR)], session)
    return jid


def _run(jid: int, module: str, prompt: str, engine: str, system: str, cwd, add_dirs, session_in: str = "") -> None:
    db.update("jobs", jid, {"status": "running", "started_at": db.now()})
    log_lines: list[str] = []
    text, session, used = "", "", engine
    try:
        for ev in agent.run_stream(prompt, engine=engine, system=system, session=session_in, cwd=cwd, add_dirs=add_dirs,
                                   fallback=not session_in):
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
    record_approvals(db.row("SELECT * FROM jobs WHERE id=?", [jid]))
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
    if m := re.fullmatch(r"approval:(\d+)", ref):
        src = one("SELECT j.* FROM jobs j WHERE j.id=?", int(m[1]))
        return (describe(src)[0] if src else ref), (describe(src)[1] if src else "#plan"), "审批后续"
    if m := re.fullmatch(r"plan:run:(\d+)", ref):
        return one("SELECT title FROM tasks WHERE id=?", int(m[1])).get("title") or ref, "#plan", "规划任务"
    if m := re.fullmatch(r"plan:decompose:(\S+)", ref):
        return f"拆解 {m[1]} 的事项", "#plan", "拆解草稿"
    first = next((ln.strip("# ").strip() for ln in (job.get("prompt") or "").splitlines() if ln.strip()), "")
    return (first[:60] or ref or module), f"#{module}", "后台任务"


_FYI = re.compile(r"需要你(?:知道|了解|注意)|供你参考")  # 告知类小节，不是要审批的
_NONE = re.compile(r"(?:没有|无|不再|不用|不需要)[^。；;:：]{0,8}(?:需要你|待你|要你)")  # 「这次没有需要你决定的事」不是小节标题
_NEED_HEAD = re.compile(r"需要你|待你|要你(?:决定|确认|拍板)|人工(?:确认|决策|审批)|NEEDS_YOU")


def needs_you(text: str, tagged_only: bool = False) -> list[str]:
    """Agent 结果里要人审批 / 决策的事项：`NEEDS_YOU:` 行，或「需要你做」小节下的条目、「需要你做：…」这样的行。
    tagged_only：提示里明确要求了 `NEEDS_YOU:`（审批后续），没写就是没有，不再按小节猜。"""
    tagged = re.findall(r"NEEDS_YOU[:：]\s*(.+)", text or "")
    if tagged or tagged_only:  # Agent 按约定写了，就只认这些，避免和总结里的复述重复
        return list(dict.fromkeys(x.strip() for x in tagged))[:8]
    out, in_sec = [], False
    for raw in (text or "").splitlines():
        ln = raw.strip()
        if not ln:
            continue
        bullet = re.match(r"(?:[-*•]|\d+[.、)])\s+", ln)
        body = (ln[bullet.end():] if bullet else ln).replace("**", "").strip("# ").strip()
        if m := re.match(r"NEEDS_YOU[:：]\s*(.+)", body):
            out.append(m[1].strip())
        elif not bullet and _NEED_HEAD.search(body) and not _FYI.search(body) and not _NONE.search(body):  # 小节标题，可能自带内容「需要你做：xxx」
            rest = re.split(r"[:：]", body, 1)[1:]
            if rest and rest[0].strip():
                out.append(rest[0].strip())
            in_sec = True
            continue
        elif bullet and in_sec:
            out.append(body)
            continue
        elif bullet and re.match(r"(?:需要你|待你)[^:：]{0,8}[:：]", body):
            out.append(re.split(r"[:：]", body, 1)[1].strip())
        in_sec = False
    return list(dict.fromkeys(x for x in out if x))[:8]


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


# ---------------------------------------------------------------- 审批
APPROVAL_REFS = re.compile(r"plan:run:\d+|approval:\d+")  # 只从「执行类」任务里提取，深读 / 调研的正文里也会出现「需要你」
DECISION = {"approved": "批准", "rejected": "不批准", "replied": "回复", "dismissed": "忽略（不用处理）"}
FOLLOWUP_PROMPT = """用户在学习平台上对你上次列出的待审批 / 待决策事项做了决定：

{decisions}

请按这些决定继续：批准的照做（合并 main / 发布 dev / 发布线上：按仓库流程执行，完成后汇报版本、改动和回滚方式）；
不批准的不要执行，说明你会怎么调整；回复的按附言处理；忽略的不用管。
还有需要人审批或决策的，每条单独一行以 `NEEDS_YOU:` 开头。最后用 3-5 行中文总结做了什么、产出在哪。"""


def record_approvals(job: dict | None) -> None:
    if not job or job.get("status") != "done" or not APPROVAL_REFS.fullmatch(job.get("ref") or ""):
        return
    for item in needs_you(job.get("output") or "", tagged_only=(job.get("ref") or "").startswith("approval:")):
        db.execute("INSERT OR IGNORE INTO approvals(job_id,item,status,created_at) VALUES (?,?, 'pending', ?)",
                   [job["id"], item[:1000], db.now()])


def _job_cwd(job: dict) -> str | None:
    if job.get("cwd"):
        return job["cwd"]
    m = re.fullmatch(r"plan:run:(\d+)", job.get("ref") or "")  # 加 cwd 列之前的任务：用事项的代码库
    if m:
        r = db.row("SELECT repo FROM tasks WHERE id=?", [int(m[1])]) or {}
        p = os.path.expanduser(r.get("repo") or "")
        return p if p and os.path.isdir(p) else None
    return None


def approvals(status: str = "pending") -> list[dict]:
    since = (datetime.now() - timedelta(days=2)).isoformat(timespec="seconds")
    for j in db.rows("SELECT * FROM jobs WHERE status='done' AND finished_at>=?", [since]):
        record_approvals(j)  # 幂等：同一任务同一条只记一次
    out = []
    for a in db.rows("SELECT * FROM approvals WHERE (?='' OR status=?) ORDER BY id DESC LIMIT 100", [status, status]):
        j = db.row("SELECT id,module,ref,prompt,status,finished_at FROM jobs WHERE id=?", [a["job_id"]]) or {}
        title, link, kind = describe(j) if j else ("（任务已删除）", "", "")
        f = db.row("SELECT status FROM jobs WHERE id=?", [a["followup_job_id"]]) if a["followup_job_id"] else None
        out.append({**a, "title": title, "link": link, "kind": kind, "finished_at": j.get("finished_at"),
                    "followup_status": f["status"] if f else ""})
    return out


@router.get("/approvals")
def get_approvals(status: str = "pending"):
    return approvals(status)


class DecideIn(BaseModel):
    decision: str            # approved / rejected / replied / dismissed
    note: str = ""


@router.post("/approvals/{aid}/decide")
def decide(aid: int, body: DecideIn):
    a = db.row("SELECT * FROM approvals WHERE id=?", [aid])
    if not a:
        raise HTTPException(404)
    if a["status"] != "pending":
        raise HTTPException(400, "这一项已经决定过了")
    if body.decision not in DECISION:
        raise HTTPException(400, "decision 只能是 " + "/".join(DECISION))
    db.update("approvals", aid, {"status": body.decision, "note": body.note.strip(), "decided_at": db.now()})
    left = db.row("SELECT COUNT(*) n FROM approvals WHERE job_id=? AND status='pending'", [a["job_id"]])["n"]
    if left:
        return {"ok": True, "left": left, "followup_job_id": None}
    return {"ok": True, "left": 0, "followup_job_id": _followup(a["job_id"])}


def _followup(job_id: int) -> int | None:
    """这个任务的事项都决定了：除了全是「忽略」，否则续接同一个 Agent 会话把决定发过去。"""
    items = db.rows("SELECT * FROM approvals WHERE job_id=? AND followup_job_id IS NULL ORDER BY id", [job_id])
    if not items or all(i["status"] == "dismissed" for i in items):
        return None
    job = db.row("SELECT * FROM jobs WHERE id=?", [job_id])
    lines = "\n".join(f"{n}. {i['item']}\n   → {DECISION[i['status']]}" + (f"：{i['note']}" if i["note"] else "")
                      for n, i in enumerate(items, 1))
    cwd = _job_cwd(job)
    fid = submit(job["module"], FOLLOWUP_PROMPT.format(decisions=lines), ref=f"approval:{job_id}", engine=job["engine"],
                 cwd=cwd, add_dirs=[cwd] if cwd else [], chat_session_id=job.get("chat_session_id"),
                 session=job.get("engine_session") or "")
    db.execute(f"UPDATE approvals SET followup_job_id=? WHERE id IN ({','.join('?' * len(items))})", [fid, *[i["id"] for i in items]])
    return fid


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
