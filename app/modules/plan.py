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
import os
import re
import threading
import time
from datetime import date as Date, datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import db, jobs, settings, tasks

TITLE = "规划"
ORDER = 5
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
CREATE TABLE IF NOT EXISTS plan_drafts (     -- AI 拆解先出草稿，讨论 / 修改后用户确认才写成子任务
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    date        TEXT NOT NULL,
    job_id      INTEGER,
    status      TEXT DEFAULT 'pending',     -- pending / applied / discarded / superseded
    data        TEXT DEFAULT '{}',          -- {basis:[], questions:[{q, default}], items:[{task_id, note, subtasks:[...]}]}
    created_at  TEXT,
    updated_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_plan_drafts_date ON plan_drafts(date);
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
    return {k: s.get(k) for k in ("focus_windows", "day_start", "day_end", "max_agent_concurrency", "plan_auto_dispatch")}


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

## 少而精（硬性要求）
- 每个事项最多 {max_subs} 个子任务，宁可一个 auto 子任务做完「实现+自测+对比报告+commit/push」，也不要拆成一串小步。
- 人工部分合并：同一事项的验收、取舍、确认合并 main 放进一个人工子任务，不要单列 10 分钟的确认。
- 今天可用预算：人的专注时间约 {focus_left} 分钟、非专注人时间约 {free_left} 分钟、Agent 车道约 {agent_left} 分钟（{conc} 路并行）。
  所有事项的人工子任务合计不超过人可用时间的 70%，auto 合计不超过 Agent 车道的 70%；放不下就只拆今天能完成的一段，其余写进最后一个子任务的 goal「明天继续：…」。
- 先看下面「已有进展」：已经完成或已有产出的步骤（调研、审计、基线、分析报告）不要再拆；还在进行的会话，子任务写成「接着 XX 会话 / 基于 XX 报告继续」，goal 里写明从哪儿接、还差什么。
- parallel_group：可同时进行的子任务填同一个组名（如 "A"），否则留空。
- depends_on：依赖本事项内其它子任务的下标（从 0 开始）。
- priority：1 最高 … 4 最低，一般继承父事项，可微调。

## 待拆解事项
{items}

## 输出格式（严格）
这是一份给用户讨论的草稿，用户确认后才生效。basis 写 2-4 条你依据的已有进展（哪个会话做到哪、哪份产出），
questions 写最多 3 个需要用户拍板的取舍（目标范围、今天做到哪一步、质量 vs 速度…），每个给出你的默认选择；
每个事项的 note 用一句话说明今天做到哪、为什么这样拆。
只输出一个 ```json 代码块，不要其它解释：
```json
{{"basis": ["…"], "questions": [{{"q": "…", "default": "…"}}],
 "items": [{{"task_id": 12, "note": "…", "subtasks": [
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
        conc=cfg["max_agent_concurrency"], items=items, max_subs=MAX_SUBS, **_budget(date, cfg))
    prog, dirs = _progress(date, tops)
    if prog:
        prompt += f"\n\n## 已有进展（最近 36 小时的 Claude Code / Codex 会话与交付，拆解前先看；相关目录可直接读）\n{prog}"
    ins = _insights()
    if ins:
        prompt += f"\n\n## 时间利用的历史规律（请据此安排 auto / 人工任务）\n{ins}"
    les = _lessons(date)
    if les:
        prompt += f"\n\n## 复盘沉淀的规划经验（拆解时照做：完成标准、何时跑、怎么验收、哪些要人）\n{les}"
    lrn = _learning_next(date)
    if lrn:
        prompt += (f"\n\n## 学习计划的下一步（供参考，不是待拆解事项）\n{lrn}\n"
                   "预算有余时，在 questions 里问一句要不要把它排进今天（默认：放非专注时间），不要擅自加进 items。")
    if body.hint:
        prompt += f"\n\n## 用户补充要求\n{body.hint}"
    # 拆解只需要读：工作目录放在数据目录，事项关联的代码库作为额外可读目录
    repos = sorted({str(Path(t["repo"]).expanduser()) for t in tops if t["repo"]} | set(dirs))
    db.DATA_DIR.mkdir(parents=True, exist_ok=True)
    jid = jobs.submit("plan", prompt, ref=f"plan:decompose:{date}", engine=body.engine,
                      cwd=str(db.DATA_DIR), add_dirs=repos)
    return {"job_id": jid, "task_ids": [t["id"] for t in tops]}


MAX_SUBS = 4


def _budget(date: str, cfg: dict) -> dict:
    """今天还剩多少：专注时间 / 非专注人时间 / Agent 车道分钟数（规划的是今天就从现在算起）。"""
    now = datetime.now()
    cur = now.hour * 60 + now.minute if date == db.today() else 0
    start, end = max(cur, _m(cfg["day_start"])), _m(cfg["day_end"])
    focus = sum(max(0, min(_m(w["end"]), end) - max(_m(w["start"]), start)) for w in cfg["focus_windows"])
    total = max(0, end - start)
    return {"focus_left": focus, "free_left": max(0, total - focus),
            "agent_left": total * int(cfg.get("max_agent_concurrency") or 1)}


def _words(text: str) -> set[str]:
    """粗分词做相关性：英文词（self-startup / self_startup 视为同一个）+ 中文二字组。"""
    text = (text or "").lower()
    out = {w.replace("-", "").replace("_", "") for w in re.findall(r"[a-z][a-z0-9_-]{2,}", text)}
    for run in re.findall(r"[\u4e00-\u9fff]+", text):
        out |= {run[i:i + 2] for i in range(len(run) - 1) if not _FUNC & set(run[i:i + 2])}
    return {w.rstrip("s") if w.isascii() else w for w in out} - _STOP


_FUNC = set("的和里对下是有在了把个这那一以及与或就都也要能")


_STOP = {"优化", "分析", "目标", "现在", "需要", "一个", "可以", "是否", "看下", "检查", "这个", "实现", "the", "and", "http", "https"}


def _progress(date: str, tops: list[dict], hours: float = 36) -> tuple[str, list[str]]:
    """和待拆事项相关的最近会话（进度、产出、最后回复）+ 当天与前一天的交付，给拆解用。返回 (文本, 相关目录)。"""
    try:
        from . import agents
        cards = [c for col in agents.board(hours)["columns"] for c in col["cards"]
                 if c["engine"] != "platform" and c["column"] != "archived"]
    except Exception:  # noqa: BLE001
        return "", []
    parts, dirs = [], []
    used: set[str] = set()
    bag = {c["key"]: _words(f"{c['project']} {c['title']} {c['last_human']}") for c in cards}
    df: dict[str, int] = {}
    for ws in bag.values():
        for w in ws:
            df[w] = df.get(w, 0) + 1
    for t in tops:
        want = _words(f"{t['title']} {t['goal']} {Path(t['repo']).name if t['repo'] else ''}")
        scored = []
        for c in cards:
            # 越少会话共有的词越说明相关（idf）；项目名对上直接算相关
            score = sum(1 / df[w] for w in want & bag[c["key"]])
            score += 3 if c["project"].lower().replace("-", "").replace("_", "") in want else 0
            if score >= 1.5:
                scored.append((score, c))
        scored.sort(key=lambda x: (x[0], x[1]["last"]), reverse=True)
        lines = []
        for _, c in [x for x in scored if x[0] >= scored[0][0] / 2][:4]:
            used.add(c["key"])
            o = c.get("output")
            out = f"{agents.OUT_STATUS.get(o['status'], o['status'])} {'/'.join(o['labels'])} {o['at']}" if o else "暂无产出"
            plan = f" · 当前步骤：{c['plan_current']}" if c["plan_current"] else ""
            lines.append(f"- [{c['engine']}] {c['project']} · {c['title']} · {c['reason']}（最后活动 {c['last'][5:16].replace('T', ' ')}）"
                         f" · 产出：{out}{plan} · key={c['key']}" + (f" · 目录 {c['cwd']}" if c["cwd"] else "")
                         + f"\n  最后回复：{(c['last_agent'] or '').replace(chr(10), ' ')[:400]}")
            if c["cwd"] and os.path.isdir(c["cwd"]) and c["cwd"] not in dirs:
                dirs.append(c["cwd"])
        parts.append(f"### task_id={t['id']} {t['title'][:40]}\n" + ("\n".join(lines) or "（没找到相关会话，按从零开始拆）"))
    running = [c for c in cards if c["column"] == "running" and c["key"] not in used]
    if running:
        parts.append("### 其它正在跑的会话（占用 Agent 并发）\n" + "\n".join(f"- {c['project']} · {c['title']}" for c in running[:6]))
    prev = (Date.fromisoformat(date) - timedelta(days=1)).isoformat()
    for d in (prev, date):
        try:
            parts.append(f"### {d} 的交付\n" + agents.deliveries_text(d)[:2000])
        except Exception:  # noqa: BLE001
            pass
    return "\n\n".join(parts), dirs[:4]


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


# ---------------------------------------------------------------- 拆解草稿
def _norm_draft(data) -> dict:
    if isinstance(data, list):
        data = {"items": data}
    data = data if isinstance(data, dict) else {}
    qs = []
    for q in data.get("questions") or []:
        if isinstance(q, str):
            q = {"q": q}
        if isinstance(q, dict) and q.get("q"):
            qs.append({"q": str(q["q"]), "default": str(q.get("default") or "")})
    items = [it for it in data.get("items") or [] if isinstance(it, dict) and isinstance(it.get("subtasks"), list)]
    return {"basis": [str(b) for b in data.get("basis") or [] if b][:6], "questions": qs[:5], "items": items}


def save_draft(date: str, data, job_id: int | None = None) -> int:
    """新草稿替换当天还在讨论中的旧草稿。"""
    db.execute("UPDATE plan_drafts SET status='superseded', updated_at=? WHERE date=? AND status='pending'", [db.now(), date])
    return db.insert("plan_drafts", {"date": date, "job_id": job_id, "status": "pending",
                                     "data": json.dumps(_norm_draft(data), ensure_ascii=False), "created_at": db.now(), "updated_at": db.now()})


def get_draft(date: str = "", did: int | None = None) -> dict | None:
    r = (db.row("SELECT * FROM plan_drafts WHERE id=?", [did]) if did else
         db.row("SELECT * FROM plan_drafts WHERE date=? AND status='pending' ORDER BY id DESC LIMIT 1", [date]))
    if not r:
        return None
    d = {**r, "data": json.loads(r["data"] or "{}")}
    titles = {t["id"]: t["title"] for t in tasks.list_for(r["date"])}
    for it in d["data"].get("items", []):
        it["title"] = titles.get(_int(it.get("task_id")), f"（事项 {it.get('task_id')} 不存在）")
    return d


def _int(x):
    try:
        return int(x)
    except (TypeError, ValueError):
        return None


@router.get("/drafts")
def draft_for(date: str = ""):
    return {"draft": get_draft(date or db.today())}


class DraftIn(BaseModel):
    data: dict


@router.put("/drafts/{did}")
def update_draft(did: int, body: DraftIn):
    d = get_draft(did=did)
    if not d or d["status"] != "pending":
        raise HTTPException(404, "草稿不存在或已处理")
    db.update("plan_drafts", did, {"data": json.dumps(_norm_draft(body.data), ensure_ascii=False), "updated_at": db.now()})
    return get_draft(did=did)


@router.post("/drafts/{did}/apply")
def apply_draft(did: int):
    d = get_draft(did=did)
    if not d or d["status"] != "pending":
        raise HTTPException(404, "草稿不存在或已处理")
    ids = apply_decomposition(d["data"])
    db.update("plan_drafts", did, {"status": "applied", "updated_at": db.now()})
    return {"created": ids, "schedule": run_schedule(d["date"]) if ids else None}


@router.post("/drafts/{did}/discard")
def discard_draft(did: int):
    db.update("plan_drafts", did, {"status": "discarded", "updated_at": db.now()})
    return {"ok": True}


def on_job_done(job: dict) -> None:
    ref = job.get("ref") or ""
    if ref.startswith("plan:decompose:"):
        if job.get("status") != "done":
            return
        data = extract_json(job.get("output") or "")
        if not data:
            return
        did = save_draft(ref.split(":", 2)[2], data, job["id"])
        n = sum(len(it["subtasks"]) for it in _norm_draft(data)["items"])
        db.update("jobs", job["id"], {"log": (job.get("log") or "") + f"\n[plan] 拆解草稿 #{did}：{n} 个子任务，讨论 / 确认后生效"})
    elif ref.startswith(("plan:run:", "approval:")):  # 审批续接 / 暂停后继续也回写到最初那次执行
        _finish_run(job)


def on_job_resumed(old: dict, new_jid: int) -> None:
    run = db.row("SELECT * FROM plan_runs WHERE job_id=?", [jobs.lineage(old["id"])[0]])
    if run:
        db.update("plan_runs", run["id"], {"status": "running", "finished_at": None})
        tasks.patch(run["task_id"], {"status": "doing"})


# ---------------------------------------------------------------- 让 Agent 执行
RUN_PROMPT = """你是被「规划」板块派发的自动执行 Agent，请独立完成下面的任务，尽量不要等待人。
任务：{title}
完成标准：{goal}
{parent}{repo}
完成后在回复最后单独一行输出 `STATUS: done` 或 `STATUS: partial`（未完全达成），再用 3-5 行中文总结做了什么、产出在哪、还需要人做什么。
""" + jobs.ASK_RULE


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
    root = jobs.lineage(job["id"])[0]
    run = db.row("SELECT * FROM plan_runs WHERE job_id=?", [root])
    if not run:
        return
    out = job.get("output") or ""
    m = re.findall(r"STATUS:\s*(done|partial)", out, re.I)
    if job.get("status") == "paused":  # 用户暂停：不算失败，也不触发下一个任务
        db.update("plan_runs", run["id"], {"status": "paused", "finished_at": db.now()})
        if (t := db.row("SELECT status FROM tasks WHERE id=?", [run["task_id"]])) and t["status"] == "doing":
            tasks.patch(run["task_id"], {"status": "todo"})
        return
    if root != job["id"] and job.get("status") == "done" and not m:  # 续接这一轮没给新结论，保持原状态
        return
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
    try:  # 依赖它的下一个任务不用等下一轮
        auto_dispatch()
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------- 到点自动派发
AUTO_TICK = 60  # 秒


def due_tasks(date: str, now_hm: str) -> list[dict]:
    """到点、可以直接交给 Agent 的子任务：auto + claude/codex、还没开始、没派过、依赖都已完成、排程开始时间已到。"""
    ts = tasks.list_for(date)
    byid = {t["id"]: t for t in ts}
    parents = set(_children_map(ts))
    ran = {r["task_id"] for r in db.rows("SELECT DISTINCT task_id FROM plan_runs")}
    out = [t for t in ts if t["id"] not in parents and t["id"] not in ran and t["status"] == "todo"
           and t["human_level"] == "auto" and t["executor"] in ("claude", "codex")
           and t["start_time"] and t["start_time"] <= now_hm
           and all(byid.get(d, {}).get("status") == "done" for d in t["depends_on"])]
    return sorted(out, key=lambda t: (t["start_time"], t["priority"], t["id"]))


def auto_dispatch(now: datetime | None = None) -> list[int]:
    """把到点的自动任务派出去（设置 plan_auto_dispatch，默认开），不超过 Agent 并发度。返回派出的任务 id。"""
    cfg = settings.load()
    if not cfg.get("plan_auto_dispatch", True):
        return []
    now = now or datetime.now()
    busy = db.row("SELECT count(*) AS n FROM jobs WHERE status IN ('queued','running') AND (ref LIKE 'plan:run:%' OR ref LIKE 'approval:%')")["n"]
    free = int(cfg.get("max_agent_concurrency", 3)) - busy
    sent = []
    for t in due_tasks(now.date().isoformat(), now.strftime("%H:%M"))[:max(0, free)]:
        launch(t["id"])
        tasks.patch(t["id"], {"notes": ((t["notes"] or "") + f"\n[自动派发 {now:%H:%M}] 到排程时间、依赖已完成").strip()})
        sent.append(t["id"])
    return sent


def _dispatch_loop() -> None:
    while True:
        try:
            auto_dispatch()
        except Exception:  # noqa: BLE001 —— 下一轮再试
            pass
        time.sleep(AUTO_TICK)


def on_startup() -> None:
    threading.Thread(target=_dispatch_loop, daemon=True, name="plan-auto-dispatch").start()


@router.get("/runs")
def runs(date: str = "", task_id: int = 0):
    sql = ("SELECT r.*, t.title, t.date, t.est_minutes FROM plan_runs r JOIN tasks t ON t.id=r.task_id WHERE 1=1")
    args: list = []
    if date:
        sql, args = sql + " AND t.date=?", args + [date]
    if task_id:
        sql, args = sql + " AND r.task_id=?", args + [task_id]
    out = db.rows(sql + " ORDER BY r.id DESC LIMIT 200", args)
    for r in out:  # 审批续接 / 继续执行之后，看最新一轮
        tip, rnd = jobs.chain_tip(r["job_id"])
        r.update(tip_job_id=tip["id"] if tip else r["job_id"], tip_status=tip["status"] if tip else "", round=rnd)
    return out


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
                            [f"plan:decompose:{date}"]),
            "draft": get_draft(date)}


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
def _insights() -> str:
    """Agent 看板算出的时间利用情况与近 7 天规律（模块缺失时为空）。"""
    try:
        from .agents import planning_insights
        return planning_insights()
    except Exception:  # noqa: BLE001
        return ""


def _lessons(date: str, days: int = 30) -> str:
    """复盘里打了 plan 标签的经验 + 最近一次复盘的 next_actions（复盘模块缺失时为空）。"""
    try:
        start = (Date.fromisoformat(date) - timedelta(days=days)).isoformat()
        notes = db.rows("SELECT date, title, content FROM review_notes WHERE kind='lesson' AND date BETWEEN ? AND ? "
                        "AND (',' || replace(tags, ' ', '') || ',') LIKE '%,plan,%' ORDER BY date DESC, id DESC LIMIT 8",
                        [start, date])
        rec = db.row("SELECT date, next_actions FROM review_days WHERE date<=? AND next_actions<>'' "
                     "ORDER BY date DESC LIMIT 1", [date])
    except Exception:  # noqa: BLE001
        return ""
    lines = [f"- [{n['date']}] {n['title']}：{n['content'][:200]}" for n in notes]
    if rec:
        lines.append(f"最近一次复盘（{rec['date']}）的改进行动：\n{rec['next_actions'][:1200]}")
    return "\n".join(lines)


def _learning_next(date: str) -> str:
    """进行中的学习计划各自的下一步（还没加入今天的事项时），给拆解 / 对话当候选的学习块（学习模块缺失时为空）。"""
    try:
        plans = db.rows("SELECT id, topic FROM learn_plans WHERE status='active' ORDER BY updated_at DESC LIMIT 3")
        today = " ".join(t.get("notes") or "" for t in tasks.list_for(date))
        lines = []
        for p in plans:
            s = db.row("SELECT * FROM learn_steps WHERE plan_id=? AND status IN ('doing','todo') "
                       "ORDER BY status='doing' DESC, stage, ord, id LIMIT 1", [p["id"]])
            if not s or f"step:{s['id']}" in today:
                continue
            n = db.row("SELECT count(*) total, sum(status IN ('done','skipped')) done FROM learn_steps WHERE plan_id=?",
                       [p["id"]]) or {}
            lines.append(f"- 计划{p['id']}「{p['topic']}」进度 {int(n.get('done') or 0)}/{n.get('total') or 0}，下一步 "
                         f"step {s['id']}（阶段 {s['stage']}，约 {s['est_hours']} 小时，{s['status']}）：{s['title']}")
    except Exception:  # noqa: BLE001
        return ""
    if not lines:
        return ""
    return "\n".join(lines) + ("\n用户要排学习时，用 POST /api/learn/steps/<step_id>/today 加入今日事项（kind=learning），"
                               "默认放非专注时间的 medium 学习块，学完提醒在学习板块给这一步打理解度和反馈。")


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
    ins = _insights()
    if ins:
        lines.append("时间利用（真实会话事件统计）：\n" + ins)
    les = _lessons(date)
    if les:
        lines.append("复盘沉淀的规划经验（拆解 / 排程 / 验收时参考）：\n" + les)
    lrn = _learning_next(date)
    if lrn:
        lines.append("学习计划的下一步（还没排进今天）：\n" + lrn)
    d = get_draft(date)
    if d:
        data = {**d["data"], "items": [{k: v for k, v in it.items() if k != "title"} for it in d["data"]["items"]]}
        lines.append(f"\n## 讨论中的拆解草稿 #{d['id']}（还没生效；用户在和你讨论它）\n"
                     "按讨论结果改草稿：PUT /api/plan/drafts/{id} 传完整的 {\"data\": {...}}（同下面的结构）；"
                     "用户明确说「就这样 / 采用 / 写入」时才 POST /api/plan/drafts/{id}/apply（会写成子任务并重新排程）。\n"
                     "```json\n" + json.dumps(data, ensure_ascii=False) + "\n```")
    return "\n".join(lines)
