"""后台 Agent 任务：长时间运行的调研/解析，结果写 jobs 表，完成后回调板块的 on_job_done。

每个任务在自己的 runner 进程里跑（python -m app.jobrun <id>，独立会话），不在服务进程里：
服务重启（改代码后 supervisor 自动重启）不用等任务，也不会杀掉任务。
排队 → kick() 有空位就起 runner；runner 跑完再 kick() 一次接下一个；暂停 = 给 runner 发 SIGTERM。
"""
from __future__ import annotations

import json
import logging
import os
import re
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import agent, db, kb, modules, settings

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/jobs", tags=["jobs"])
_procs: dict[int, object] = {}  # job id → 正在跑的 CLI 子进程（runner 进程内）
_paused: set[int] = set()       # 用户要求暂停、还没收尾的 job（runner 进程内）
_children: list[subprocess.Popen] = []  # 本进程起的 runner，poll 一下回收僵尸进程
STARTING_GRACE = 60  # 秒：刚认领、runner 还没写 pid 的任务不当成已中断


def _cap() -> int:
    """同时在跑的后台任务总数上限 = Agent 并发度（各板块共享，多的排队）。"""
    return max(1, int(settings.get("max_agent_concurrency", 3)))


def _free_mem_gb() -> float | None:
    """可用内存（空闲 + 可回收）。macOS 读 vm_stat，Linux 读 /proc/meminfo；读不到返回 None（不拦）。"""
    try:
        if sys.platform == "darwin":
            out = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=3).stdout
            page = int(re.search(r"page size of (\d+)", out)[1])
            pages = sum(int(m[1]) for k in ("free", "inactive", "speculative", "purgeable")
                        if (m := re.search(rf"Pages {k}:\s+(\d+)", out)))
            return pages * page / 2**30
        with open("/proc/meminfo") as f:
            return int(re.search(r"MemAvailable:\s+(\d+)", f.read())[1]) / 2**20
    except Exception:  # noqa: BLE001
        return None


def machine() -> dict:
    """机器现在能不能再起任务：{ok, reason, load, cpus, free_gb}。"""
    cfg = {"max_load_per_cpu": 0.9, "min_free_mem_gb": 4, **(settings.get("job_guard") or {})}
    cpus = os.cpu_count() or 1
    load = os.getloadavg()[0]
    free = _free_mem_gb()
    reason = ""
    if load > cfg["max_load_per_cpu"] * cpus:
        reason = f"CPU 负载 {load:.1f}（{cpus} 核，上限 {cfg['max_load_per_cpu'] * cpus:.1f}）"
    elif free is not None and free < cfg["min_free_mem_gb"]:
        reason = f"可用内存 {free:.1f}GB（低于 {cfg['min_free_mem_gb']}GB）"
    return {"ok": not reason, "reason": reason, "load": round(load, 1), "cpus": cpus,
            "free_gb": round(free, 1) if free is not None else None}


# 每个后台任务的提示词末尾都带上：平台按上限和机器负载排队，Agent 自己别再开并行重活
RESOURCE_RULE = """【机器资源约定】平台同时只跑少数几个后台任务，并按机器负载排队；请遵守：
- 不要在后台挂常驻进程（nohup / & / 监控循环 / dev server），需要等结果就在前台等，任务结束前停掉你起的所有进程；
- 重活（视频渲染、批量出片、全量测试、模型推理、大批量下载）一次只跑一路；需要并行的，把剩下的写成清单在总结里列出，由人拆成多个平台任务排队跑。"""


def submit(module: str, prompt: str, *, ref: str = "", engine: str = "", system: str = "",
           cwd: str | None = None, add_dirs: list[str] | None = None, chat_session_id: int | None = None,
           session: str = "") -> int:
    """提交后台 Agent 任务，返回 job id。完成后调用 modules.<module>.on_job_done(job)，
    有 chat_session_id 时再把结果回帖到那个对话（对话里让 Agent 提交的任务，见 chat.link_jobs）。"""
    engine = engine or settings.get("engines.default", "claude")
    prompt = prompt.rstrip() + "\n\n" + RESOURCE_RULE
    jid = db.insert("jobs", {"module": module, "ref": ref, "engine": engine, "prompt": prompt,
                             "status": "queued", "created_at": db.now(), "chat_session_id": chat_session_id, "cwd": cwd or "",
                             "system": system, "add_dirs": json.dumps([*(add_dirs or []), str(kb.KB_DIR)]), "session_in": session})
    kick()
    return jid


def _alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def reap() -> list[int]:
    """runner 进程已经不在、状态却还是 running 的任务（机器重启、进程被杀）记为失败。"""
    _children[:] = [p for p in _children if p.poll() is None]
    grace = (datetime.now() - timedelta(seconds=STARTING_GRACE)).isoformat(timespec="seconds")
    dead = [j["id"] for j in db.rows("SELECT id,pid,started_at FROM jobs WHERE status='running'")
            if not _alive(j["pid"]) and (j["pid"] or (j["started_at"] or "") < grace)]
    for jid in dead:
        db.execute("UPDATE jobs SET status='failed', log=log||?, finished_at=? WHERE id=? AND status='running'",
                   ["\n[runner 进程已退出，任务中断]", db.now(), jid])
    return dead


def kick() -> list[int]:
    """有空位就把排队的任务交给 runner 进程。返回这次启动的 job id。"""
    reap()
    busy = db.row("SELECT count(*) n FROM jobs WHERE status='running'")["n"]
    started = []
    free = max(0, _cap() - busy)
    if free and db.row("SELECT id FROM jobs WHERE status='queued' LIMIT 1") and not machine()["ok"]:
        return started  # 机器忙：继续排队，kicker 每 30 秒再看一次
    for j in db.rows("SELECT id FROM jobs WHERE status='queued' ORDER BY id LIMIT ?", [free]):
        # 先认领再起进程：服务和各个 runner 可能同时 kick
        if db.execute("UPDATE jobs SET status='running', started_at=?, pid=NULL WHERE id=? AND status='queued'",
                      [db.now(), j["id"]]) != 1:
            continue
        try:
            _spawn(j["id"])
            started.append(j["id"])
        except Exception as e:  # noqa: BLE001
            log.exception("启动 runner 失败 job %s", j["id"])
            db.execute("UPDATE jobs SET status='failed', log=log||?, finished_at=? WHERE id=?",
                       [f"\n[runner 启动失败] {e}", db.now(), j["id"]])
    return started


KICK_EVERY = 30  # 秒


def start_kicker() -> None:
    """服务进程里的定时 kick：机器从忙变闲、或 runner 意外退出后，排队的任务也能接上。"""
    def loop():
        while True:
            time.sleep(KICK_EVERY)
            try:
                kick()
            except Exception:  # noqa: BLE001 —— 下一轮再试
                log.exception("kick failed")
    threading.Thread(target=loop, daemon=True, name="jobs-kicker").start()


def _spawn(jid: int) -> None:
    logs = db.DATA_DIR / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    with open(logs / "jobs.log", "ab") as out:
        _children.append(subprocess.Popen([sys.executable, "-m", "app.jobrun", str(jid)], cwd=str(db.ROOT),
                                          stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
                                          start_new_session=True))  # 独立会话：服务进程退出不连带它


def _on_proc(jid: int):
    def track(proc) -> None:
        _procs[jid] = proc
        if jid in _paused:
            agent.stop(proc)
    return track


def _run(jid: int, module: str, prompt: str, engine: str, system: str, cwd, add_dirs, session_in: str = "") -> None:
    if jid in _paused:  # 排队时就被暂停了
        _paused.discard(jid)
        return
    db.update("jobs", jid, {"status": "running", "started_at": db.now()})
    log_lines: list[str] = []
    text, session, used = "", "", engine
    try:
        for ev in agent.run_stream(prompt, engine=engine, system=system, session=session_in, cwd=cwd, add_dirs=add_dirs,
                                   fallback=not session_in, on_proc=_on_proc(jid)):
            if jid in _paused:
                break
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
    finally:
        _procs.pop(jid, None)
    if jid in _paused:  # 暂停：留下会话 id 以便续接；不提取审批、不回帖
        _paused.discard(jid)
        log_lines.append("[paused] 用户暂停，会话已保存，可在平台上「继续」")
        db.update("jobs", jid, {"status": "paused", "output": text, "engine_session": session or session_in,
                                "log": "\n".join(log_lines[-200:]), "finished_at": db.now()})
        _hook(module, "on_job_done", db.row("SELECT * FROM jobs WHERE id=?", [jid]))
        return
    db.update("jobs", jid, {"status": status, "output": text, "engine": used, "engine_session": session,
                            "fallback_from": engine if used and used != engine else "",
                            "log": "\n".join(log_lines[-200:]), "finished_at": db.now()})
    _hook(module, "on_job_done", db.row("SELECT * FROM jobs WHERE id=?", [jid]))
    notify_chat(db.row("SELECT * FROM jobs WHERE id=?", [jid]))
    record_approvals(db.row("SELECT * FROM jobs WHERE id=?", [jid]))
    kb.schedule_sync()


def _hook(module: str, name: str, *args) -> None:
    mod = modules.get(module)
    fn = getattr(mod, name, None) if mod else None
    if fn:
        try:
            fn(*args)
        except Exception:  # noqa: BLE001
            log.exception("%s %s failed", name, module)


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
    # 只认行首（可带列表符号 / 加粗）的标记；句子里提到「`NEEDS_YOU:` 行」不算
    tagged = re.findall(r"(?m)^[ \t]*(?:[-*•]|\d+[.、)])?[ \t]*\**NEEDS_YOU\**[:：]\**\s*(.+)", text or "")
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
# 执行类 Agent 什么时候才问人（规划派发、审批续接共用）：一个任务汇总问一次，别每轮追问
ASK_RULE = """只有**之前没问过**、且不可逆的决定（合并 main、发布 dev / 线上、删改用户数据、对外发送、花钱或大量 token）才问人：
每条单独一行以 `NEEDS_YOU:` 开头，写清要决定什么、你的建议和在哪看材料，最多 3 条，一次问全。
其余可逆的选择按你的建议默认继续，在总结里列「我按默认做的决定」；已经决定过的事不要再问。"""
FOLLOWUP_PROMPT = """用户在学习平台上对你上次列出的待审批 / 待决策事项做了决定：

{decisions}

请按这些决定继续：批准的照做（合并 main / 发布 dev / 发布线上：按仓库流程执行，完成后汇报版本、改动和回滚方式）；
不批准的不要执行，说明你会怎么调整；回复的按附言处理；忽略的不用管。
""" + ASK_RULE + "\n最后用 3-5 行中文总结做了什么、产出在哪。"


def lineage(job_id: int) -> list[int]:
    """这个 job 往上追溯到最初的执行任务：[最初, …, 自己]（审批续接的 ref 是 approval:<上一轮 job>）。"""
    out, jid = [], job_id
    while jid and jid not in out:
        out.append(jid)
        r = db.row("SELECT ref FROM jobs WHERE id=?", [jid]) or {}
        m = re.fullmatch(r"approval:(\d+)", r.get("ref") or "")
        jid = int(m[1]) if m else 0
    return out[::-1]


def chain_tip(job_id: int) -> tuple[dict | None, int]:
    """最初任务 → 最新一轮（审批续接 / 继续执行都挂在上一轮下面）。返回 (最新 job, 第几轮)。"""
    tip, rnd = db.row("SELECT * FROM jobs WHERE id=?", [job_id]), 1
    while tip and (nxt := db.row("SELECT * FROM jobs WHERE ref=? ORDER BY id DESC LIMIT 1", [f"approval:{tip['id']}"])):
        tip, rnd = nxt, rnd + 1
    return tip, rnd


def _grams(t: str) -> set[str]:
    t = re.sub(r"[\s`*_，。、：:；;,.()（）「」“”\"'-]+", "", t.lower())
    return {t[i:i + 2] for i in range(len(t) - 1)}


def _asked_before(item: str, prev: list[str]) -> bool:
    g = _grams(item)
    return any(len(g & (p := _grams(x))) / max(1, len(g | p)) >= 0.5 for x in prev)


def record_approvals(job: dict | None) -> None:
    if not job or job.get("status") != "done" or not APPROVAL_REFS.fullmatch(job.get("ref") or ""):
        return
    if db.row("SELECT id FROM approvals WHERE job_id=?", [job["id"]]):  # 已经提取过（含被去重全部跳过的情况见下）
        return
    ups = lineage(job["id"])[:-1]
    prev = [r["item"] for r in db.rows(f"SELECT item FROM approvals WHERE job_id IN ({','.join('?' * len(ups))})", ups)] if ups else []
    for item in needs_you(job.get("output") or "", tagged_only=(job.get("ref") or "").startswith("approval:")):
        if _asked_before(item, prev):  # 前几轮问过的同一件事，不再问一遍
            continue
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
        line = lineage(a["job_id"])
        out.append({**a, "title": title, "link": link, "kind": kind, "finished_at": j.get("finished_at"),
                    "followup_status": f["status"] if f else "", "root_job_id": line[0], "round": len(line)})
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


# ---------------------------------------------------------------- 暂停 / 继续
RESUME_PROMPT = """你上次的执行被用户在学习平台上暂停了，现在继续：先确认已经做到哪一步，从停下的地方接着把原来的任务做完，不要重复已完成的部分。
结束时照原来的要求输出（STATUS 行、总结等）。""" + "\n" + ASK_RULE


def pause(jid: int) -> bool:
    j = db.row("SELECT * FROM jobs WHERE id=?", [jid])
    if not j or j["status"] not in ("queued", "running"):
        return False
    if db.execute("UPDATE jobs SET status='paused', log=log||?, finished_at=? WHERE id=? AND status='queued'",
                  ["\n[paused] 排队中被暂停", db.now(), jid]) == 1:  # 还没开始
        _hook(j["module"], "on_job_done", db.row("SELECT * FROM jobs WHERE id=?", [jid]))
        return True
    if _alive(j["pid"]) and j["pid"] != os.getpid():  # runner 收到 SIGTERM 后停掉 CLI，记为已暂停（见 jobrun）
        os.kill(j["pid"], signal.SIGTERM)
        return True
    _paused.add(jid)  # 在本进程里跑的（runner 自己 / 测试）
    if proc := _procs.get(jid):
        agent.stop(proc)
    return True


@router.get("/machine")
def get_machine():
    """机器负载 + 排队情况：页面上显示「机器忙，排队中」。"""
    q = db.row("SELECT count(*) n FROM jobs WHERE status='queued'")["n"]
    r = db.row("SELECT count(*) n FROM jobs WHERE status='running'")["n"]
    return {**machine(), "queued": q, "running": r, "cap": _cap()}


@router.post("/pause_all")
def pause_all():
    """暂停所有执行类任务（规划派发 + 审批续接），并关掉规划的到点自动派发。调研、深读等不受影响。"""
    settings.save({"plan_auto_dispatch": False})
    ids = [j["id"] for j in db.rows("SELECT id,ref FROM jobs WHERE status IN ('queued','running')")
           if APPROVAL_REFS.fullmatch(j["ref"] or "") and pause(j["id"])]
    return {"paused": ids, "auto_dispatch": False}


@router.post("/{jid}/pause")
def pause_job(jid: int):
    if not pause(jid):
        raise HTTPException(400, "只有排队中或执行中的任务能暂停")
    return {"ok": True}


@router.post("/{jid}/resume")
def resume_job(jid: int):
    """续接被暂停的会话继续做；新 job 挂在原 job 下（approval:<原 job>），审批、看板都按同一条链显示。"""
    j = db.row("SELECT * FROM jobs WHERE id=?", [jid])
    if not j or j["status"] != "paused":
        raise HTTPException(400, "只有已暂停的任务能继续")
    if db.row("SELECT id FROM jobs WHERE ref=?", [f"approval:{jid}"]):
        raise HTTPException(400, "这个任务已经继续过了")
    sess, cwd = j.get("engine_session") or "", _job_cwd(j)
    nid = submit(j["module"], RESUME_PROMPT if sess else j["prompt"], ref=f"approval:{jid}", engine=j["engine"],
                 cwd=cwd, add_dirs=[cwd] if cwd else [], chat_session_id=j.get("chat_session_id"), session=sess)
    _hook(j["module"], "on_job_resumed", j, nid)
    return {"ok": True, "job_id": nid}


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
