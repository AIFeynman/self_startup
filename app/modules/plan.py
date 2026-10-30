"""规划：每日事项 → AI 拆解 → 按优先级 / 并行 / 并发 / 人干预度排程 → 可选让 Agent 自动执行。

排程原则（schedule_day 纯函数，可单测）：
- heavy / medium（人重度/中度干预）放进专注时间窗，按优先级 + 依赖先后；放不下则溢出到非专注时间并标记。
- light（轻度）放非专注的人时间；非专注放不下再借用专注时间。
- auto（Agent 自动跑）：人先花几分钟启动（kickoff，放非专注时间），Agent 在 N 条并行车道上跑
  （N = max_agent_concurrency，运行本身可以与专注时间重叠——这正是并行的收益），结束后人花几分钟验收（review）。
- depends_on 是任务 id 列表；同一 parallel_group 的任务连续排，Agent 任务会尽量同时启动。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import db, jobs, settings, tasks

TITLE = "规划"
ORDER = 20
SCHEMA = """
CREATE TABLE IF NOT EXISTS plan_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id     INTEGER NOT NULL,
    job_id      INTEGER NOT NULL,
    engine      TEXT DEFAULT '',
    status      TEXT DEFAULT 'running',     -- running / done / partial / failed
    result      TEXT DEFAULT '',
    started_at  TEXT,
    finished_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_plan_runs_task ON plan_runs(task_id);
CREATE TABLE IF NOT EXISTS plan_schedules (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    date        TEXT NOT NULL,
    blocks      TEXT DEFAULT '[]',          -- [{task_id, lane, start, end, type}]
    summary     TEXT DEFAULT '{}',
    created_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_plan_sched_date ON plan_schedules(date);
"""
router = APIRouter()

LEVELS = ("heavy", "medium", "light", "auto")
EXECUTORS = ("human", "claude", "codex", "mixed")
KICKOFF_MIN = 5
REVIEW_MIN = 10
MAX_WAIT_MIN = 30   # 阻塞后续任务的启动/验收，为避开专注窗最多愿意等多久
OPEN = ("todo", "doing", "partial")


# ---------------------------------------------------------------- 时间工具
def _m(hhmm: str) -> int:
    h, m = hhmm.strip().split(":")
    return int(h) * 60 + int(m)


def _t(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _subtract(region: tuple[int, int], cuts: list[tuple[int, int]]) -> list[tuple[int, int]]:
    out, cur = [], region[0]
    for s, e in sorted(cuts):
        if e <= cur or s >= region[1]:
            continue
        if s > cur:
            out.append((cur, s))
        cur = max(cur, e)
    if cur < region[1]:
        out.append((cur, region[1]))
    return out


def _find_slot(busy: list[tuple[int, int]], regions: list[tuple[int, int]], earliest: int, dur: int) -> int | None:
    """在 regions 内找最早的、不与 busy 重叠、长度 dur 的起点（不跨 region）。"""
    cands = sorted({earliest, *(e for _, e in busy), *(s for s, _ in regions)})
    for t in cands:
        if t < earliest:
            continue
        if not any(s <= t and t + dur <= e for s, e in regions):
            continue
        if any(t < be and bs < t + dur for bs, be in busy):
            continue
        return t
    return None


def _union_minutes(iv: list[tuple[int, int]]) -> int:
    total, cur_s, cur_e = 0, None, None
    for s, e in sorted(iv):
        if cur_e is None or s > cur_e:
            if cur_e is not None:
                total += cur_e - cur_s
            cur_s, cur_e = s, e
        else:
            cur_e = max(cur_e, e)
    return total + (cur_e - cur_s if cur_e is not None else 0)


# ---------------------------------------------------------------- 排程（纯函数）
def schedule_day(items: list[dict], cfg: dict, from_time: str = "") -> dict:
    """items: 待排的叶子任务（id, title, priority, human_level, est_minutes, depends_on, parallel_group）。
    cfg: focus_windows, day_start, day_end, max_agent_concurrency。
    返回 {placements: {id: (start,end)}, blocks: [...], summary: {...}}，时间都是 HH:MM。"""
    day_s, day_e = _m(cfg.get("day_start", "08:30")), _m(cfg.get("day_end", "23:00"))
    if from_time:
        day_s = max(day_s, _m(from_time))
    focus = sorted((max(_m(w["start"]), day_s), min(_m(w["end"]), day_e)) for w in cfg.get("focus_windows", []))
    focus = [(s, e) for s, e in focus if s < e]
    whole = [(day_s, day_e)]
    nonfocus = _subtract((day_s, day_e), focus)
    lanes_n = max(1, int(cfg.get("max_agent_concurrency", 3) or 1))

    byid = {t["id"]: t for t in items}
    deps = {t["id"]: [d for d in (t.get("depends_on") or []) if d in byid and d != t["id"]] for t in items}
    # 同组任务连续排：组的排序键取组内最高优先级
    gprio: dict[str, int] = {}
    for t in items:
        g = t.get("parallel_group") or ""
        if g:
            gprio[g] = min(gprio.get(g, 9), int(t.get("priority") or 2))

    def key(t):
        g = t.get("parallel_group") or ""
        p = int(t.get("priority") or 2)
        return (gprio.get(g, p), g, p, t["id"])

    human: list[tuple[int, int]] = []
    lanes: list[list[tuple[int, int]]] = [[] for _ in range(lanes_n)]
    finish: dict[int, int] = {}
    placements: dict[int, tuple[str, str]] = {}
    blocks: list[dict] = []
    warnings: list[str] = []
    flags: dict[int, str] = {}
    done: set[int] = set()

    def place_human(tid, earliest, dur, prefer, fallback, btype):
        st = _find_slot(human, prefer, earliest, dur)
        used = "prefer"
        if st is None and fallback:
            st, used = _find_slot(human, fallback, earliest, dur), "fallback"
        if st is None:
            return None, used
        human.append((st, st + dur))
        blocks.append({"task_id": tid, "lane": "human", "start": _t(st), "end": _t(st + dur), "type": btype})
        return st, used

    pending = sorted(items, key=key)
    while pending:
        ready = [t for t in pending if all(d in done for d in deps[t["id"]])]
        if not ready:  # 循环依赖：忽略依赖继续排
            warnings.append("存在循环依赖：" + "、".join(t["title"] for t in pending))
            for t in pending:
                deps[t["id"]] = [d for d in deps[t["id"]] if d in done]
            continue
        t = ready[0]
        pending.remove(t)
        tid = t["id"]
        done.add(tid)
        dur = max(5, int(t.get("est_minutes") or 30))
        earliest = max([day_s] + [finish[d] for d in deps[tid] if d in finish])
        if any(d not in finish for d in deps[tid]):
            flags[tid] = "依赖未排上"
            warnings.append(f"「{t['title']}」依赖的任务未排上，已跳过")
            continue
        lvl = t.get("human_level") if t.get("human_level") in LEVELS else "medium"

        if lvl in ("heavy", "medium"):
            st, used = place_human(tid, earliest, dur, focus, nonfocus, "work")
            if st is None:
                st, used = place_human(tid, earliest, dur, whole, None, "work")
            if st is None:
                flags[tid] = "放不下"
                warnings.append(f"「{t['title']}」({dur} 分钟) 今天放不下")
                continue
            if used == "fallback":
                flags[tid] = "溢出到非专注时间"
                warnings.append(f"「{t['title']}」需要专注但专注时间已满，溢出到 {_t(st)}")
            placements[tid] = (_t(st), _t(st + dur))
            finish[tid] = st + dur

        elif lvl == "light":
            st, _ = place_human(tid, earliest, dur, nonfocus, whole, "work")
            if st is None:
                flags[tid] = "放不下"
                warnings.append(f"「{t['title']}」({dur} 分钟) 今天放不下")
                continue
            placements[tid] = (_t(st), _t(st + dur))
            finish[tid] = st + dur

        else:  # auto：人 kickoff → Agent 车道运行 → 人 review
            def short_slot(at, d):  # 启动/验收只要几分钟：优先非专注，等太久就插进专注窗
                a, b = _find_slot(human, nonfocus, at, d), _find_slot(human, whole, at, d)
                return a if a is not None and (b is None or a - b <= MAX_WAIT_MIN) else b

            def kick(at):  # 紧接着前置任务完成时顺手启动可以插进专注窗；等车道空出的启动不打断专注
                if deps[tid] and at == earliest:
                    return short_slot(at, KICKOFF_MIN)
                ks = _find_slot(human, nonfocus, at, KICKOFF_MIN)
                return ks if ks is not None else _find_slot(human, whole, at, KICKOFF_MIN)

            def lane_slot(at):  # 最早空出的车道
                cands = [(s, i) for i, ln in enumerate(lanes) if (s := _find_slot(ln, whole, at, dur)) is not None]
                return min(cands) if cands else None

            placed = None
            ls = lane_slot(earliest + KICKOFF_MIN)
            ks = kick(ls[0] - KICKOFF_MIN if ls else earliest) if ls else None
            if ks is not None:
                rs = _find_slot(lanes[ls[1]], whole, ks + KICKOFF_MIN, dur)
                lane_i = ls[1]
                if rs is None:
                    ls2 = lane_slot(ks + KICKOFF_MIN)
                    rs, lane_i = ls2 if ls2 else (None, None)
                if rs is not None:
                    blocking = any(tid in deps[o["id"]] for o in pending)  # 有后续任务在等它才值得插进专注窗验收
                    rv = short_slot(rs + dur, REVIEW_MIN) if blocking else _find_slot(human, nonfocus, rs + dur, REVIEW_MIN)
                    rv = rv if rv is not None else _find_slot(human, whole, rs + dur, REVIEW_MIN)
                    if rv is not None:
                        placed = (ks, lane_i, rs, rv)
            if placed is None:
                flags[tid] = "放不下"
                warnings.append(f"「{t['title']}」(Agent {dur} 分钟) 今天放不下")
                continue
            ks, lane_i, rs, rv = placed
            human += [(ks, ks + KICKOFF_MIN), (rv, rv + REVIEW_MIN)]
            lanes[lane_i].append((rs, rs + dur))
            blocks += [
                {"task_id": tid, "lane": "human", "start": _t(ks), "end": _t(ks + KICKOFF_MIN), "type": "kickoff"},
                {"task_id": tid, "lane": f"agent{lane_i + 1}", "start": _t(rs), "end": _t(rs + dur), "type": "agent"},
                {"task_id": tid, "lane": "human", "start": _t(rv), "end": _t(rv + REVIEW_MIN), "type": "review"},
            ]
            placements[tid] = (_t(ks), _t(rv + REVIEW_MIN))
            finish[tid] = rv + REVIEW_MIN

    # ---- 汇总
    def overlap(iv, regions):
        return sum(max(0, min(e, re) - max(s, rs)) for s, e in iv for rs, re in regions)

    h_total = sum(e - s for s, e in human)
    h_focus = overlap(human, focus)
    agent_iv = [iv for lane in lanes for iv in lane]
    agent_min = sum(e - s for s, e in agent_iv)
    span = _union_minutes(human + agent_iv)
    focus_total = sum(e - s for s, e in focus)
    peak = 0
    for s, _ in agent_iv:
        peak = max(peak, sum(1 for a, b in agent_iv if a <= s < b))
    summary = {
        "human_minutes": h_total,
        "human_focus_minutes": h_focus,
        "human_outside_minutes": h_total - h_focus,
        "focus_capacity_minutes": focus_total,
        "focus_utilization": round(h_focus / focus_total, 2) if focus_total else 0,
        "agent_minutes": agent_min,
        "agent_peak_concurrency": peak,
        "lanes": lanes_n,
        "busy_span_minutes": span,
        # >1 表示人与 Agent 有并行：(人时间 + Agent 时间) / 实际占用的墙钟时间
        "parallel_ratio": round((h_total + agent_min) / span, 2) if span else 0,
        "scheduled": len(placements),
        "unscheduled": [i for i, f in flags.items() if f in ("放不下", "依赖未排上")],
        "flags": {str(k): v for k, v in flags.items()},
        "warnings": warnings,
        "from_time": _t(day_s),
    }
    blocks.sort(key=lambda b: (b["lane"], b["start"]))
    return {"placements": placements, "blocks": blocks, "summary": summary}


def _cfg() -> dict:
    s = settings.load()
    return {k: s.get(k) for k in ("focus_windows", "day_start", "day_end", "max_agent_concurrency")}


def _children_map(ts: list[dict]) -> dict[int, list[dict]]:
    ch: dict[int, list[dict]] = {}
    for t in ts:
        if t.get("parent_id"):
            ch.setdefault(t["parent_id"], []).append(t)
    return ch


def run_schedule(date: str, from_time: str = "") -> dict:
    ts = tasks.list_for(date)
    ch = _children_map(ts)
    leaves = [t for t in ts if t["id"] not in ch and t["status"] in OPEN]
    res = schedule_day(leaves, _cfg(), from_time)
    for t in leaves:
        st, en = res["placements"].get(t["id"], ("", ""))
        db.update("tasks", t["id"], {"start_time": st, "end_time": en, "updated_at": db.now()})
    # 父任务时间 = 子任务跨度
    for pid in ch:
        kids = [tasks.get(k["id"]) for k in ch[pid]]
        ss = [k["start_time"] for k in kids if k["start_time"]]
        es = [k["end_time"] for k in kids if k["end_time"]]
        db.update("tasks", pid, {"start_time": min(ss) if ss else "", "end_time": max(es) if es else ""})
    db.insert("plan_schedules", {"date": date, "blocks": res["blocks"], "summary": res["summary"], "created_at": db.now()})
    return {"date": date, "blocks": res["blocks"], "summary": res["summary"]}


def last_schedule(date: str) -> dict | None:
    r = db.row("SELECT * FROM plan_schedules WHERE date=? ORDER BY id DESC LIMIT 1", [date])
    if not r:
        return None
    return {"blocks": json.loads(r["blocks"] or "[]"), "summary": json.loads(r["summary"] or "{}"), "created_at": r["created_at"]}


# ---------------------------------------------------------------- 拆解
DECOMPOSE_PROMPT = """请把下面每个顶层事项拆解成可执行的子任务，用于排程。日期：{date}

## 排程规则（供你判断）
- 专注时间窗（人重度干预）：{focus}；其余时间放低干预/自动任务。Agent 最大并发：{conc}。
- human_level：heavy=需要人全程深度思考/决策（设计、写作、难题）；medium=人主导但可被打断；
  light=琐碎、几分钟级、碎片时间可做；auto=可交给 Claude Code/Codex 自动完成，人只需启动+验收。
- executor：human / claude / codex / mixed。auto 任务的 executor 必须是 claude 或 codex。
- 尽量把能自动化的部分拆成独立 auto 子任务（目标写清楚、可验收），把需要人判断的部分单独拆出。
- est_minutes 为该子任务本身耗时（auto 为 Agent 运行时长估计），子任务一般 15-120 分钟。
- parallel_group：可同时进行的子任务填同一个组名（如 "A"），否则留空。
- depends_on：依赖本事项内其它子任务的下标（从 0 开始）。
- priority：1 最高 … 4 最低，一般继承父事项，可微调。

## 待拆解事项
{items}

## 输出格式（严格）
只输出一个 ```json 代码块，不要其它解释：
```json
{{"items": [{{"task_id": 12, "subtasks": [
  {{"title": "…", "goal": "完成标准", "human_level": "heavy|medium|light|auto", "executor": "human|claude|codex|mixed",
    "est_minutes": 30, "parallel_group": "", "depends_on": [], "priority": 2}}
]}}]}}
```"""


class DecomposeIn(BaseModel):
    date: str = ""
    task_ids: list[int] | None = None
    engine: str = ""
    hint: str = ""


@router.post("/decompose")
def decompose(body: DecomposeIn):
    date = body.date or db.today()
    tops = [t for t in tasks.list_for(date) if not t.get("parent_id") and t["status"] in OPEN]
    if body.task_ids:
        tops = [t for t in tops if t["id"] in body.task_ids]
    if not tops:
        raise HTTPException(400, "没有可拆解的顶层事项")
    items = "\n".join(
        f"- task_id={t['id']} | {t['title']} | 目标: {t['goal'] or '-'} | P{t['priority']} | {t['kind']} | "
        f"预计 {t['est_minutes']} 分钟" + (f" | 代码库: {t['repo']}" if t["repo"] else "")
        for t in tops)
    cfg = _cfg()
    prompt = DECOMPOSE_PROMPT.format(
        date=date, focus="、".join(f"{w['start']}-{w['end']}" for w in cfg["focus_windows"]),
        conc=cfg["max_agent_concurrency"], items=items)
    if body.hint:
        prompt += f"\n\n## 用户补充要求\n{body.hint}"
    # 拆解只需要读：工作目录放在数据目录，事项关联的代码库作为额外可读目录
    repos = sorted({str(Path(t["repo"]).expanduser()) for t in tops if t["repo"]})
    db.DATA_DIR.mkdir(parents=True, exist_ok=True)
    jid = jobs.submit("plan", prompt, ref=f"plan:decompose:{date}", engine=body.engine,
                      cwd=str(db.DATA_DIR), add_dirs=repos)
    return {"job_id": jid, "task_ids": [t["id"] for t in tops]}


def extract_json(text: str):
    """从 Agent 输出里取 JSON：优先最后一个 ```json 代码块，否则最后一个能解析的 {...}/[...]。"""
    fences = re.findall(r"```(?:json)?\s*\n(.*?)```", text or "", re.S)
    for f in reversed(fences):
        try:
            return json.loads(f)
        except json.JSONDecodeError:
            pass
    dec, found, i = json.JSONDecoder(), None, 0
    text = text or ""
    while i < len(text):
        if text[i] in "{[":
            try:
                obj, end = dec.raw_decode(text, i)
                found, i = obj, end
                continue
            except json.JSONDecodeError:
                pass
        i += 1
    return found


def _norm_sub(s: dict, parent: dict) -> dict:
    lvl = s.get("human_level") if s.get("human_level") in LEVELS else "medium"
    ex = s.get("executor") if s.get("executor") in EXECUTORS else ("claude" if lvl == "auto" else "human")
    if lvl == "auto" and ex not in ("claude", "codex"):
        ex = "claude"
    try:
        pr = min(4, max(1, int(s.get("priority") or parent["priority"] or 2)))
    except (TypeError, ValueError):
        pr = parent["priority"] or 2
    try:
        est = max(5, int(s.get("est_minutes") or 30))
    except (TypeError, ValueError):
        est = 30
    return {"date": parent["date"], "parent_id": parent["id"], "title": str(s.get("title") or "未命名")[:200],
            "goal": str(s.get("goal") or ""), "kind": parent["kind"], "priority": pr, "human_level": lvl,
            "executor": ex, "est_minutes": est, "parallel_group": str(s.get("parallel_group") or ""),
            "repo": parent.get("repo") or ""}


def apply_decomposition(data) -> list[int]:
    """把拆解 JSON 写成子任务，返回新建的 id。重新拆解时替换该事项下仍是 todo 的旧子任务。"""
    items = data.get("items") if isinstance(data, dict) else data
    created: list[int] = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        try:
            parent = tasks.get(int(it.get("task_id")))
        except Exception:  # noqa: BLE001
            continue
        subs = [s for s in it.get("subtasks") or [] if isinstance(s, dict)]
        if not subs:
            continue
        db.execute("DELETE FROM tasks WHERE parent_id=? AND status='todo'", [parent["id"]])
        ids = [tasks.create(_norm_sub(s, parent))["id"] for s in subs]
        for s, tid in zip(subs, ids):
            dep = [ids[d] for d in (s.get("depends_on") or []) if isinstance(d, int) and 0 <= d < len(ids) and ids[d] != tid]
            if dep:
                db.update("tasks", tid, {"depends_on": dep})
        created += ids
    return created


def on_job_done(job: dict) -> None:
    ref = job.get("ref") or ""
    if ref.startswith("plan:decompose:"):
        if job.get("status") != "done":
            return
        data = extract_json(job.get("output") or "")
        n = apply_decomposition(data) if data else []
        db.update("jobs", job["id"], {"log": (job.get("log") or "") + f"\n[plan] 新建子任务 {len(n)} 个"})
    elif ref.startswith("plan:run:"):
        _finish_run(job)


# ---------------------------------------------------------------- 让 Agent 执行
RUN_PROMPT = """你是被「规划」板块派发的自动执行 Agent，请独立完成下面的任务，尽量不要等待人。
任务：{title}
完成标准：{goal}
{parent}{repo}
完成后在回复最后单独一行输出 `STATUS: done` 或 `STATUS: partial`（未完全达成），再用 3-5 行中文总结做了什么、产出在哪、还需要人做什么。"""


class LaunchIn(BaseModel):
    engine: str = ""


@router.post("/tasks/{tid}/launch")
def launch(tid: int, body: LaunchIn | None = None):
    t = tasks.get(tid)
    engine = (body.engine if body else "") or (t["executor"] if t["executor"] in ("claude", "codex") else "")
    parent = tasks.get(t["parent_id"]) if t.get("parent_id") else None
    prompt = RUN_PROMPT.format(
        title=t["title"], goal=t["goal"] or "（未写，按标题合理完成）",
        parent=f"所属事项：{parent['title']}（{parent['goal']}）\n" if parent else "",
        repo=f"工作目录：{t['repo']}\n" if t["repo"] else "")
    cwd = str(Path(t["repo"]).expanduser()) if t["repo"] and Path(t["repo"]).expanduser().is_dir() else None
    jid = jobs.submit("plan", prompt, ref=f"plan:run:{tid}", engine=engine, cwd=cwd, add_dirs=[cwd] if cwd else [])
    rid = db.insert("plan_runs", {"task_id": tid, "job_id": jid, "engine": engine or settings.get("engines.default", "claude"),
                                  "status": "running", "started_at": db.now()})
    tasks.patch(tid, {"status": "doing"})
    return {"job_id": jid, "run_id": rid}


def _finish_run(job: dict) -> None:
    run = db.row("SELECT * FROM plan_runs WHERE job_id=?", [job["id"]])
    if not run:
        return
    out = job.get("output") or ""
    m = re.findall(r"STATUS:\s*(done|partial)", out, re.I)
    if job.get("status") != "done":
        st = "failed"
    else:
        st = m[-1].lower() if m else "partial"
    tail = re.split(r"STATUS:\s*(?:done|partial)", out, flags=re.I)[-1].strip()
    result = (tail or out or job.get("log") or "")[-600:]
    db.update("plan_runs", run["id"], {"status": st, "result": result, "engine": job.get("engine") or run["engine"],
                                       "finished_at": db.now()})
    t = db.row("SELECT * FROM tasks WHERE id=?", [run["task_id"]])
    if t:
        notes = (t["notes"] + "\n" if t["notes"] else "") + f"[Agent {job.get('engine')} {st}] {result[:400]}"
        tasks.patch(t["id"], {"status": "done" if st == "done" else "partial",
                              "progress": 100 if st == "done" else 50, "notes": notes})


@router.get("/runs")
def runs(date: str = "", task_id: int = 0):
    sql = ("SELECT r.*, t.title, t.date, t.est_minutes FROM plan_runs r JOIN tasks t ON t.id=r.task_id WHERE 1=1")
    args: list = []
    if date:
        sql, args = sql + " AND t.date=?", args + [date]
    if task_id:
        sql, args = sql + " AND r.task_id=?", args + [task_id]
    return db.rows(sql + " ORDER BY r.id DESC LIMIT 200", args)


# ---------------------------------------------------------------- 日视图 / 顺延 / 排程
def _tree(ts: list[dict]) -> list[dict]:
    ch = _children_map(ts)
    return [{**t, "children": ch.get(t["id"], [])} for t in ts if not t.get("parent_id")]


@router.get("/day")
def day(date: str = ""):
    date = date or db.today()
    ts = tasks.list_for(date)
    return {"date": date, "tasks": ts, "tree": _tree(ts), "config": _cfg(), "schedule": last_schedule(date),
            "runs": runs(date=date),
            "jobs": db.rows("SELECT id,ref,status,created_at FROM jobs WHERE module='plan' AND ref=? AND status IN ('queued','running')",
                            [f"plan:decompose:{date}"])}


class DateIn(BaseModel):
    date: str = ""
    from_time: str = ""


@router.post("/schedule")
def schedule(body: DateIn):
    return run_schedule(body.date or db.today(), body.from_time)


@router.post("/carry")
def carry(body: DateIn):
    """把之前最近一天未完成的顶层事项（及其未完成子任务）顺延到 date。"""
    date = body.date or db.today()
    prev = db.row("SELECT MAX(date) d FROM tasks WHERE date<?", [date])
    src = prev and prev["d"]
    if not src:
        return {"from": None, "created": []}
    existing = {t["title"] for t in tasks.list_for(date) if not t.get("parent_id")}
    ts = tasks.list_for(src)
    ch = _children_map(ts)
    keep = ("title", "goal", "kind", "priority", "human_level", "executor", "est_minutes", "parallel_group", "repo", "progress")
    created: list[int] = []
    for t in ts:
        if t.get("parent_id") or t["status"] not in OPEN or t["title"] in existing:
            continue
        nt = tasks.create({**{k: t[k] for k in keep}, "date": date, "notes": f"顺延自 {src}"})
        created.append(nt["id"])
        idmap = {}
        kids = [k for k in ch.get(t["id"], []) if k["status"] in OPEN]
        for k in kids:
            idmap[k["id"]] = tasks.create({**{x: k[x] for x in keep}, "date": date, "parent_id": nt["id"]})["id"]
        for k in kids:
            dep = [idmap[d] for d in k["depends_on"] if d in idmap]
            if dep:
                db.update("tasks", idmap[k["id"]], {"depends_on": dep})
        created += list(idmap.values())
    return {"from": src, "created": created}


# ---------------------------------------------------------------- 给对话 Agent 的快照
def agent_context(ref: str) -> str:
    m = re.search(r"\d{4}-\d{2}-\d{2}", ref or "")
    date = m.group(0) if m else db.today()
    ts = tasks.list_for(date)
    cfg = _cfg()
    lines = [f"日期 {date}；专注时间窗 " + "、".join(f"{w['start']}-{w['end']}" for w in cfg["focus_windows"]) +
             f"；一天 {cfg['day_start']}-{cfg['day_end']}；Agent 并发 {cfg['max_agent_concurrency']}",
             "任务（id|父|P|干预|执行者|预计分钟|状态|时间|依赖|并行组|标题 — 目标）："]
    for t in ts:
        lines.append(f"- {t['id']}|{t['parent_id'] or '-'}|P{t['priority']}|{t['human_level']}|{t['executor']}|"
                     f"{t['est_minutes']}|{t['status']}|{t['start_time'] or '?'}-{t['end_time'] or '?'}|"
                     f"{t['depends_on'] or ''}|{t['parallel_group'] or ''}|{t['title']} — {(t['goal'] or '')[:80]}")
    if not ts:
        lines.append("（今天还没有事项）")
    sch = last_schedule(date)
    if sch:
        s = sch["summary"]
        lines.append(f"上次排程 {sch['created_at']}：人 {s.get('human_minutes')} 分钟（专注内 {s.get('human_focus_minutes')}，"
                     f"专注外 {s.get('human_outside_minutes')}），Agent {s.get('agent_minutes')} 分钟，"
                     f"并行度 {s.get('parallel_ratio')}，峰值并发 {s.get('agent_peak_concurrency')}")
        for w in s.get("warnings", [])[:10]:
            lines.append(f"  ⚠ {w}")
    return "\n".join(lines)
