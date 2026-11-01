"""复盘：每日目标 vs 证据、学习完成度、问题与经验、时间线、Claude Code / Codex 效率反思。"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from datetime import date as Date, datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import agent, chat, db, jobs, settings, tasks
from . import _review_sessions as rs, _utilization as util

TITLE = "复盘"
ORDER = 10
SCHEMA = """
CREATE TABLE IF NOT EXISTS review_days (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    date             TEXT NOT NULL UNIQUE,
    summary          TEXT DEFAULT '',
    wins             TEXT DEFAULT '',
    problems         TEXT DEFAULT '',
    next_actions     TEXT DEFAULT '',
    ai_analysis      TEXT DEFAULT '',          -- AI 检查完成情况（markdown）
    task_suggestions TEXT DEFAULT '[]',        -- JSON [{task_id,status,progress,evidence,problem,applied}]
    check_job_id     INTEGER,
    improve_md       TEXT DEFAULT '',          -- 写复盘后 AI 结合会话与学习反馈的改进分析（markdown）
    improve_job_id   INTEGER,
    created_at       TEXT,
    updated_at       TEXT
);
CREATE TABLE IF NOT EXISTS review_notes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    date        TEXT NOT NULL,
    kind        TEXT DEFAULT 'lesson',         -- problem / lesson / insight / idea
    title       TEXT DEFAULT '',
    content     TEXT DEFAULT '',
    tags        TEXT DEFAULT '',               -- 逗号分隔
    created_at  TEXT,
    updated_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_review_notes_date ON review_notes(date);
CREATE TABLE IF NOT EXISTS review_agent_stats (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    date           TEXT NOT NULL UNIQUE,
    summary        TEXT DEFAULT '{}',          -- JSON 当日汇总（含 headline）
    sessions       TEXT DEFAULT '[]',          -- JSON 每个会话的统计 + 人工消息
    reflection     TEXT DEFAULT '',            -- AI 反思（markdown）
    reflect_job_id INTEGER,
    scanned_at     TEXT
);
"""
router = APIRouter()

NOTE_KINDS = ("problem", "lesson", "insight", "idea")
STATUSES = ("todo", "doing", "done", "partial", "dropped")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _day(s: str | None) -> str:
    m = _DATE.search(s or "")
    return m.group(0) if m else db.today()


def _has_table(name: str) -> bool:
    return bool(db.row("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", [name]))


def _cols(name: str) -> set[str]:
    return {r["name"] for r in db.rows(f"PRAGMA table_info({name})")}


def _loads(s, default):
    try:
        return json.loads(s) if s else default
    except (json.JSONDecodeError, TypeError):
        return default


# ---------- 当日数据 ----------

def _tree(items: list[dict]) -> list[dict]:
    by_id = {t["id"]: {**t, "children": []} for t in items}
    roots = []
    for t in by_id.values():
        p = by_id.get(t.get("parent_id"))
        (p["children"] if p else roots).append(t)
    return roots


_DAY_COLS = {"improve_md": "TEXT DEFAULT ''", "improve_job_id": "INTEGER"}
_day_cols_ok = False


def _ensure_day_cols() -> None:
    """老库补上改进分析列。"""
    global _day_cols_ok
    if _day_cols_ok:
        return
    cols = _cols("review_days")
    for k, decl in _DAY_COLS.items():
        if k not in cols:
            db.execute(f"ALTER TABLE review_days ADD COLUMN {k} {decl}")
    _day_cols_ok = True


def get_record(date: str) -> dict:
    _ensure_day_cols()
    r = db.row("SELECT * FROM review_days WHERE date=?", [date])
    if not r:
        r = {"date": date, "summary": "", "wins": "", "problems": "", "next_actions": "",
             "ai_analysis": "", "task_suggestions": [], "check_job_id": None, "improve_md": "", "improve_job_id": None}
    else:
        r["task_suggestions"] = _loads(r["task_suggestions"], [])
    r["entries"] = record_entries(r)
    return r


# 「写复盘」逐条追加时每行带时间：同一天「[HH:MM] 」，第二天补写「[MM-DD HH:MM] 」
_STAMP = re.compile(r"^\[(?:(\d{2}-\d{2}) )?(\d{2}:\d{2})\]\s*")


def stamp(date: str, at: str | None = None) -> str:
    at = at or db.now()
    return f"[{at[11:16]}] " if at[:10] == date else f"[{at[5:10]} {at[11:16]}] "


def record_entries(rec: dict) -> list[dict]:
    """把四栏复盘拆成一条条，按时间线排好（没时间的行沿用上一条的时间，保持原来的先后）。"""
    date = rec.get("date") or db.today()
    out = []
    for f in RECORD_FIELDS:
        last = ""
        for i, line in enumerate(ln.strip() for ln in (rec.get(f) or "").splitlines()):
            if not line:
                continue
            m = _STAMP.match(line)
            if m:
                md, hm = m.groups()
                last = (f"{date[:4]}-{md}" if md else date) + "T" + hm
                line = line[m.end():]
            out.append({"field": f, "text": line, "at": last, "time": last[11:16] if last else "",
                        "next_day": bool(last) and last[:10] != date, "_i": i})
    out.sort(key=lambda e: (e["at"] or "", RECORD_FIELDS.index(e["field"]), e["_i"]))
    for e in out:
        e.pop("_i")
    return out


def upsert_record(date: str, data: dict) -> dict:
    data = {**data, "updated_at": db.now()}
    cur = db.row("SELECT id FROM review_days WHERE date=?", [date])
    if cur:
        db.update("review_days", cur["id"], data)
    else:
        db.insert("review_days", {"date": date, "created_at": db.now(), **data})
    return get_record(date)


def learning_extra(date: str) -> dict:
    """深度学习板块的数据（表存在才读）：当天完成/进行中的学习步骤、当天完成的解析。"""
    out: dict = {"steps": [], "items": [], "events": []}
    if _has_table("learn_steps") and {"title", "status", "done_at"} <= _cols("learn_steps"):
        join = _has_table("learn_plans") and "topic" in _cols("learn_plans")
        sql = ("SELECT s.id, s.title, s.status, s.done_at, s.understanding, s.plan_id"
               + (", p.topic AS plan_topic FROM learn_steps s LEFT JOIN learn_plans p ON p.id=s.plan_id" if join
                  else " FROM learn_steps s")
               + " WHERE substr(s.done_at,1,10)=?" + (" OR s.status='doing'" if date == db.today() else "")
               + " ORDER BY s.plan_id, s.id LIMIT 50")
        out["steps"] = db.rows(sql, [date])
    if _has_table("learn_items") and {"title", "status", "updated_at"} <= _cols("learn_items"):
        try:  # 当天开始 / 生成好 / 追问过的深读，带追问次数和感想
            from . import _reads
            out["items"] = _reads.day_reads(date)[:30]
            out["reads"] = _reads.day_lines(date)[:30]
        except Exception:  # noqa: BLE001
            out["items"] = db.rows("SELECT id, kind, title, url, status, rating FROM learn_items "
                                   "WHERE status='done' AND substr(updated_at,1,10)=? LIMIT 30", [date])
    if _has_table("learn_events"):  # 学习记录：测试、停一下作答与点评、理解度 / 反馈变化
        try:
            from . import learn
            titles = {r["id"]: r["title"] for r in db.rows("SELECT id, title FROM learn_steps")}
            out["events"] = [learn.event_line(e, titles) for e in learn.events_of(date=date) if e["kind"] not in ("check", "qa")]
        except Exception:  # noqa: BLE001  学习模块出错不影响复盘
            pass
        try:  # 学习习惯三项：停一下平均分 / 学完当天用到项目 / 每日论文笔记
            from . import _habits
            out["habits"] = _habits.lines(date)
        except Exception:  # noqa: BLE001
            pass
    return out


def _stats(items: list[dict]) -> dict:
    n = len(items)
    done = sum(1 for t in items if t["status"] == "done")
    avg = round(sum(int(t.get("progress") or 0) for t in items) / n) if n else 0
    return {"total": n, "done": done, "avg_progress": avg}


def day_data(date: str) -> dict:
    all_tasks = tasks.list_for(date)
    work = [t for t in all_tasks if t.get("kind") != "learning"]
    learning = [t for t in all_tasks if t.get("kind") == "learning"]
    eff = get_efficiency(date, scan_if_missing=False)
    return {
        "date": date,
        "tasks": _tree(work), "learning": _tree(learning), "learning_extra": learning_extra(date),
        "stats": {"work": _stats(work), "learning": _stats(learning)},
        "record": get_record(date),
        "notes": list_notes(date=date),
        "efficiency": {"headline": eff["summary"].get("headline", ""), "scanned_at": eff.get("scanned_at"),
                       "summary": {k: v for k, v in eff["summary"].items() if k != "by_project"}} if eff else None,
        "jobs": db.rows("SELECT id, ref, status, created_at, finished_at FROM jobs WHERE module='review' AND ref IN (?,?,?) "
                        "ORDER BY id DESC LIMIT 6", [f"check:{date}", f"reflect:{date}", f"improve:{date}"]),
    }


class RecordIn(BaseModel):
    summary: str | None = None
    wins: str | None = None
    problems: str | None = None
    next_actions: str | None = None


class DateIn(BaseModel):
    date: str = ""


@router.get("/day")
def api_day(date: str = ""):
    return day_data(_day(date))


@router.put("/day/{date}")
def api_put_day(date: str, body: RecordIn):
    date = _day(date)
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    before = get_record(date)
    rec = upsert_record(date, patch)
    if any((before.get(k) or "").strip() != (v or "").strip() for k, v in patch.items()):
        rec = {**rec, "improve_job_id": submit_improve(date)}
    return rec


class AppendIn(BaseModel):
    field: str = "summary"
    text: str


RECORD_FIELDS = ("summary", "wins", "problems", "next_actions")
REC_LABEL = {"summary": "总结", "wins": "收获", "problems": "问题", "next_actions": "下一步"}
_REC_PREFIX = {"总结": "summary", "收获": "wins", "做成": "wins", "问题": "problems", "下一步": "next_actions",
               "明天": "next_actions", "next": "next_actions"}


def parse_record_line(text: str, default: str = "summary") -> tuple[str, str]:
    """「问题：xxx」→ (problems, xxx)；无前缀 → (default, 原文)。"""
    m = re.match(r"\s*([^\s:：]{1,4})\s*[:：]\s*(.+)", text or "", re.S)
    if m and m.group(1).lower() in _REC_PREFIX:
        return _REC_PREFIX[m.group(1).lower()], m.group(2).strip()
    return (default if default in RECORD_FIELDS else "summary"), (text or "").strip()


@router.post("/day/{date}/append")
def api_append_day(date: str, body: AppendIn):
    """往当天复盘的某一栏追加一行（快捷输入用，可带「问题：」等前缀自动分栏）。"""
    date = _day(date)
    field, text = parse_record_line(body.text, body.field)
    if not text:
        raise HTTPException(400, "text required")
    cur = (get_record(date).get(field) or "").rstrip()
    upsert_record(date, {field: (cur + "\n" + stamp(date) + text).strip()})
    jid = submit_improve(date)
    return {"field": field, "text": text, "record": get_record(date), "improve_job_id": jid}


# ---------- 证据包：git / 文档 ----------

def repo_dirs(date: str | None = None) -> list[str]:
    dirs = list(settings.get("repos", []) or [])
    if date:
        dirs += [t["repo"] for t in db.rows("SELECT DISTINCT repo FROM tasks WHERE date=? AND repo!=''", [date])]
    else:
        dirs += [t["repo"] for t in db.rows("SELECT DISTINCT repo FROM tasks WHERE repo!='' ORDER BY id DESC LIMIT 20")]
    out = []
    for d in dirs:
        p = str(Path(d).expanduser())
        if p not in out and Path(p).is_dir():
            out.append(p)
    return out


def _git(d: str, *args: str, limit: int = 4000) -> str:
    try:
        r = subprocess.run(["git", "-C", d, *args], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"(git 失败: {e})"
    out = (r.stdout or r.stderr).rstrip()
    return out[:limit] + ("\n…(截断)" if len(out) > limit else "")


_SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".next", "data"}


def recent_docs(d: str, date: str, limit: int = 20) -> list[str]:
    start = datetime.fromisoformat(date).timestamp()
    end = start + 86400
    found, scanned = [], 0
    for root, dirs, files in os.walk(d):
        dirs[:] = [x for x in dirs if x not in _SKIP_DIRS and not x.startswith(".")]
        for f in files:
            if not f.endswith(".md"):
                continue
            scanned += 1
            p = os.path.join(root, f)
            try:
                mt = os.path.getmtime(p)
            except OSError:
                continue
            if start <= mt < end:
                found.append((mt, os.path.relpath(p, d)))
        if scanned > 20000:
            break
    return [f"{datetime.fromtimestamp(m):%H:%M} {p}" for m, p in sorted(found, reverse=True)[:limit]]


def evidence(date: str) -> str:
    nxt = (Date.fromisoformat(date) + timedelta(days=1)).isoformat()
    parts = []
    for d in repo_dirs(date):
        sec = [f"### {d}"]
        if _git(d, "rev-parse", "--is-inside-work-tree") == "true":
            log = _git(d, "log", "--all", "--no-merges", f"--since={date} 00:00", f"--until={nxt} 00:00",
                       "--date=format:%H:%M", "--format=%h %ad %an %s", "--shortstat", limit=5000)
            files = _git(d, "log", "--all", "--no-merges", f"--since={date} 00:00", f"--until={nxt} 00:00",
                         "--name-only", "--format=", limit=3000)
            uniq = sorted(set(x for x in files.splitlines() if x.strip()))
            sec.append("**当天提交**\n```\n" + (log or "（无）") + "\n```")
            if uniq:
                sec.append(f"**当天改动文件（{len(uniq)}）**\n```\n" + "\n".join(uniq[:80]) + "\n```")
            if date == db.today():
                st = _git(d, "status", "--short", limit=2000)
                ds = _git(d, "diff", "--stat", "HEAD", limit=2000)
                sec.append("**未提交改动**\n```\n" + (st or "（干净）") + ("\n\n" + ds if ds else "") + "\n```")
        else:
            sec.append("（非 git 目录）")
        docs = recent_docs(d, date)
        if docs:
            sec.append("**当天修改的文档**\n```\n" + "\n".join(docs) + "\n```")
        parts.append("\n".join(sec))
    try:
        from . import agents
        parts.append("### 当天交付（Claude Code / Codex 会话里检测到的推送 / 部署 / PR / 发布 / 文档材料）\n" + agents.deliveries_text(date))
    except Exception:  # noqa: BLE001
        pass
    return "\n\n".join(parts) or "（没有配置复盘分析目录：设置 → 复盘分析目录，或给事项填 repo）"


@router.get("/evidence")
def api_evidence(date: str = ""):
    date = _day(date)
    return {"date": date, "dirs": repo_dirs(date), "evidence": evidence(date)}


# ---------- AI 检查完成情况 ----------

def _task_lines(items: list[dict]) -> str:
    lines = []
    for t in items:
        ind = "  " if t.get("parent_id") else ""
        lines.append(f"{ind}- [#{t['id']}] {t['title']} | 类型 {t.get('kind')} | 执行 {t.get('executor')} | "
                     f"状态 {t['status']} {t.get('progress', 0)}% | repo {t.get('repo') or '-'}"
                     + (f"\n{ind}  目标：{t['goal']}" if t.get("goal") else "")
                     + (f"\n{ind}  备注：{t['notes'][:200]}" if t.get("notes") else ""))
    return "\n".join(lines) or "（当天没有事项）"


def check_prompt(date: str) -> str:
    rec = get_record(date)
    learn = learning_extra(date)
    learn_txt = "\n".join(f"- 学习步骤 {s['title']}（{s['status']}）" for s in learn["steps"]) or ""
    if learn["events"]:
        learn_txt += "\n学习记录（测试、停一下作答与点评）：\n" + "\n".join(f"- {x}" for x in learn["events"][-20:])
    if learn.get("reads"):
        learn_txt += "\n深读（追问次数、用户写下的感想）：\n" + "\n".join(f"- {x}" for x in learn["reads"])
    if learn.get("habits"):
        learn_txt += "\n学习习惯（停一下 / 学完当天用到项目 / 每日论文）：\n" + "\n".join(f"- {x}" for x in learn["habits"])
    return f"""请检查 {date} 的事项完成情况。只读分析：不要修改任何文件或平台数据，不要运行测试、不要启动服务（会污染平台数据），用 git / Read / Grep 看证据即可。

## 当天事项与目标
{_task_lines(tasks.list_for(date))}
{learn_txt}

## 用户已写的复盘
{rec.get('summary') or '（无）'}
问题：{rec.get('problems') or '（无）'}

## 证据包（平台自动收集）
{evidence(date)}

## 要求
1. 逐个事项对照「目标/完成标准」与证据（提交、改动文件、文档、代码）判断完成度；需要时用 Read/Grep/git 进一步查看上述目录里的代码和文档。
2. 指出遇到的问题、可能的根因、遗漏或偏离目标的地方；没有证据的事项明确写「无证据」，不要臆测为完成。
3. 输出 markdown 分析（简洁，按事项分点），最后附一个 ```json 代码块，格式：
{{"suggestions": [{{"task_id": 1, "status": "done|partial|doing|todo|dropped", "progress": 0-100, "evidence": "一句话证据", "problem": "问题，无则空"}}]}}
task_id 必须是上面列出的事项 id。"""


@router.post("/check")
def api_check(body: DateIn):
    date = _day(body.date)
    prompt = check_prompt(date)
    system = agent.build_system("review", agent_context(date))
    jid = jobs.submit("review", prompt, ref=f"check:{date}", system=system, add_dirs=repo_dirs(date))
    upsert_record(date, {"check_job_id": jid})
    return {"job_id": jid, "date": date}


def parse_suggestions(text: str) -> tuple[str, list[dict]]:
    """从 Agent 输出里拆出 markdown 分析和最后一个 JSON 建议块。"""
    blocks = list(re.finditer(r"```(?:json)?\s*\n(.*?)```", text or "", re.S))
    data, used = None, None
    for m in reversed(blocks):
        try:
            data = json.loads(m.group(1))
            used = m
            break
        except json.JSONDecodeError:
            continue
    if data is None:
        m = re.search(r"\{\s*\"suggestions\".*\}", text or "", re.S)
        if m:
            try:
                data, used = json.loads(m.group(0)), m
            except json.JSONDecodeError:
                pass
    items = data.get("suggestions", []) if isinstance(data, dict) else data if isinstance(data, list) else []
    out = []
    for s in items:
        if not isinstance(s, dict):
            continue
        try:
            tid = int(s.get("task_id"))
        except (TypeError, ValueError):
            continue
        st = s.get("status") if s.get("status") in STATUSES else None
        try:
            prog = max(0, min(100, int(s.get("progress"))))
        except (TypeError, ValueError):
            prog = None
        out.append({"task_id": tid, "status": st, "progress": prog, "evidence": str(s.get("evidence") or ""),
                    "problem": str(s.get("problem") or ""), "applied": False})
    md = (text[:used.start()] + text[used.end():]).strip() if used else (text or "").strip()
    return md, out


def on_job_done(job: dict) -> None:
    ref = job.get("ref") or ""
    kind, _, date = ref.partition(":")
    if not date:
        return
    if job.get("status") != "done":
        msg = f"（AI 任务 #{job['id']} 失败，见 /api/jobs/{job['id']} 日志）"
        if kind == "check":
            upsert_record(date, {"ai_analysis": msg})
        elif kind == "reflect":
            _upsert_stats(date, {"reflection": msg})
        elif kind == "improve" and get_record(date).get("improve_job_id") == job["id"]:
            upsert_record(date, {"improve_md": msg})
        return
    if kind == "check":
        md, sugg = parse_suggestions(job.get("output") or "")
        valid = {t["id"] for t in tasks.list_for(date)}
        upsert_record(date, {"ai_analysis": md, "task_suggestions": [s for s in sugg if s["task_id"] in valid]})
        auto_apply(date)
    elif kind == "reflect":
        _upsert_stats(date, {"reflection": (job.get("output") or "").strip()})
    elif kind == "improve" and get_record(date).get("improve_job_id") == job["id"]:  # 只认最新一次提交的分析
        upsert_record(date, {"improve_md": (job.get("output") or "").strip()})


_NO_EVIDENCE = re.compile(r"^\s*(无证据|没有证据|未找到|暂无|无)")


def auto_apply(date: str) -> list[int]:
    """AI 检查完成后，把「有证据、且让事项往前走」的建议直接写回事项（done / partial 且进度高于当前）；
    其它（降级、无证据、todo）留给人在复盘页点「采用」。返回自动采用的建议下标。"""
    rec = get_record(date)
    done = []
    for i, s in enumerate(rec["task_suggestions"]):
        if s.get("applied") or s.get("dismissed") or s.get("status") not in ("done", "partial"):
            continue
        if not (s.get("evidence") or "").strip() or _NO_EVIDENCE.match(s["evidence"]):
            continue
        t = db.row("SELECT status, progress FROM tasks WHERE id=?", [s["task_id"]])
        if not t or t["status"] == "done" or (s["status"] != "done" and (s.get("progress") or 0) <= (t["progress"] or 0)):
            continue
        _apply(date, i, auto=True)
        done.append(i)
    return done


@router.post("/suggestions/{date}/{idx}/apply")
def api_apply(date: str, idx: int):
    return _apply(date, idx)


def _apply(date: str, idx: int, auto: bool = False) -> dict:
    rec = get_record(date)
    sugg = rec["task_suggestions"]
    if idx < 0 or idx >= len(sugg):
        raise HTTPException(404, "suggestion not found")
    s = sugg[idx]
    patch = {k: s[k] for k in ("status", "progress") if s.get(k) is not None}
    if s.get("problem"):
        t = tasks.get(s["task_id"])
        if s["problem"] not in (t.get("notes") or ""):
            patch["notes"] = ((t.get("notes") or "") + f"\n[复盘] {s['problem']}").strip()
    task = tasks.patch(s["task_id"], patch)
    s["applied"] = True
    if auto:
        s["auto"] = True
    upsert_record(date, {"task_suggestions": sugg})
    return {"task": task, "suggestion": s}


@router.post("/suggestions/{date}/{idx}/dismiss")
def api_dismiss(date: str, idx: int):
    rec = get_record(date)
    sugg = rec["task_suggestions"]
    if idx < 0 or idx >= len(sugg):
        raise HTTPException(404, "suggestion not found")
    sugg[idx]["dismissed"] = True
    upsert_record(date, {"task_suggestions": sugg})
    return {"suggestion": sugg[idx]}


# ---------- 问题与经验 ----------

class NoteIn(BaseModel):
    date: str | None = None
    kind: str | None = None
    title: str | None = None
    content: str | None = None
    tags: str | None = None


def list_notes(date: str = "", q: str = "", kind: str = "", start: str = "", end: str = "", limit: int = 200) -> list[dict]:
    sql, args = "SELECT * FROM review_notes WHERE 1=1", []
    if date:
        sql, args = sql + " AND date=?", args + [date]
    if start:
        sql, args = sql + " AND date>=?", args + [start]
    if end:
        sql, args = sql + " AND date<=?", args + [end]
    if kind:
        sql, args = sql + " AND kind=?", args + [kind]
    if q:
        sql += " AND (title LIKE ? OR content LIKE ? OR tags LIKE ?)"
        args += [f"%{q}%"] * 3
    return db.rows(sql + " ORDER BY date DESC, id DESC LIMIT ?", args + [limit])


@router.get("/notes")
def api_notes(date: str = "", q: str = "", kind: str = "", start: str = "", end: str = "", limit: int = 200):
    return list_notes(date, q, kind, start, end, limit)


@router.post("/notes")
def api_add_note(body: NoteIn):
    d = {k: v for k, v in body.model_dump().items() if v is not None}
    if not (d.get("title") or d.get("content")):
        raise HTTPException(400, "title or content required")
    d["date"] = _day(d.get("date"))
    if d.get("kind") not in NOTE_KINDS:
        d["kind"] = "lesson"
    d["created_at"] = d["updated_at"] = db.now()
    nid = db.insert("review_notes", d)
    return db.row("SELECT * FROM review_notes WHERE id=?", [nid])


_KIND_PREFIX = {"问题": "problem", "坑": "problem", "经验": "lesson", "教训": "lesson", "洞察": "insight",
                "发现": "insight", "想法": "idea", "点子": "idea", "idea": "idea", "problem": "problem",
                "lesson": "lesson", "insight": "insight"}


def parse_quick_note(text: str) -> dict:
    """一句话快记：「问题：xxx #标签」→ {kind, title, content, tags}。首行为标题，其余为内容。"""
    text = (text or "").strip()
    kind = "lesson"
    m = re.match(r"([^\s:：]{1,7})\s*[:：]\s*", text)
    if m and m.group(1).lower() in _KIND_PREFIX:
        kind, text = _KIND_PREFIX[m.group(1).lower()], text[m.end():]
    tags = []
    for t in re.findall(r"(?:^|\s)#([^\s#,，]+)", text):
        if t not in tags:
            tags.append(t)
    text = re.sub(r"(?:^|\s)#[^\s#,，]+", " ", text)
    lines = [ln.strip() for ln in text.strip().splitlines()]
    title = re.sub(r"\s{2,}", " ", lines[0]) if lines else ""
    return {"kind": kind, "title": title, "content": "\n".join(lines[1:]).strip(), "tags": ",".join(tags)}


class QuickIn(BaseModel):
    text: str
    date: str | None = None


@router.post("/notes/quick")
def api_quick_note(body: QuickIn):
    return api_add_note(NoteIn(date=body.date, **parse_quick_note(body.text)))


@router.patch("/notes/{nid}")
def api_patch_note(nid: int, body: NoteIn):
    if not db.row("SELECT id FROM review_notes WHERE id=?", [nid]):
        raise HTTPException(404)
    d = {k: v for k, v in body.model_dump().items() if v is not None}
    d["updated_at"] = db.now()
    db.update("review_notes", nid, d)
    return db.row("SELECT * FROM review_notes WHERE id=?", [nid])


@router.delete("/notes/{nid}")
def api_del_note(nid: int):
    db.execute("DELETE FROM review_notes WHERE id=?", [nid])
    return {"ok": True}


# ---------- 时间线 ----------

def timeline(start: str = "", end: str = "") -> list[dict]:
    end = _day(end)
    start = _day(start) if start else (Date.fromisoformat(end) - timedelta(days=29)).isoformat()
    days: dict[str, dict] = {}

    def day(d: str) -> dict:
        return days.setdefault(d, {"date": d, "tasks": {"total": 0, "done": 0, "avg_progress": 0},
                                   "learning": {"total": 0, "done": 0}, "summary": "", "notes": [],
                                   "efficiency": "", "has_ai": False})

    for t in db.rows("SELECT date, kind, status, progress FROM tasks WHERE date BETWEEN ? AND ?", [start, end]):
        x = day(t["date"])
        key = "learning" if t["kind"] == "learning" else "tasks"
        x[key]["total"] += 1
        x[key]["done"] += t["status"] == "done"
        if key == "tasks":
            x["tasks"]["avg_progress"] += int(t["progress"] or 0)
    for x in days.values():
        if x["tasks"]["total"]:
            x["tasks"]["avg_progress"] = round(x["tasks"]["avg_progress"] / x["tasks"]["total"])
    for r in db.rows("SELECT date, summary, ai_analysis FROM review_days WHERE date BETWEEN ? AND ?", [start, end]):
        x = day(r["date"])
        x["summary"] = r["summary"] or ""
        x["has_ai"] = bool(r["ai_analysis"])
    for n in db.rows("SELECT id, date, kind, title, content FROM review_notes WHERE date BETWEEN ? AND ? ORDER BY id",
                     [start, end]):
        day(n["date"])["notes"].append({"id": n["id"], "kind": n["kind"], "title": n["title"] or n["content"][:40]})
    for s in db.rows("SELECT date, summary FROM review_agent_stats WHERE date BETWEEN ? AND ?", [start, end]):
        day(s["date"])["efficiency"] = _loads(s["summary"], {}).get("headline", "")
    return sorted(days.values(), key=lambda x: x["date"], reverse=True)


@router.get("/timeline")
def api_timeline(start: str = "", end: str = ""):
    return timeline(start, end)


# ---------- Agent 效率 ----------

def _upsert_stats(date: str, data: dict) -> None:
    cur = db.row("SELECT id FROM review_agent_stats WHERE date=?", [date])
    if cur:
        db.update("review_agent_stats", cur["id"], data)
    else:
        db.insert("review_agent_stats", {"date": date, **data})


def platform_runs(date: str) -> dict:
    """本平台的后台 job 与规划板块的自动执行（plan_runs，表存在才读）。"""
    out = {"jobs": db.rows("SELECT id, module, ref, engine, status, created_at, started_at, finished_at FROM jobs "
                           "WHERE substr(created_at,1,10)=? ORDER BY id", [date])}
    if _has_table("plan_runs") and {"task_id", "job_id"} <= _cols("plan_runs"):
        out["plan_runs"] = db.rows(
            "SELECT r.*, t.title AS task_title, t.human_level, t.executor FROM plan_runs r "
            "LEFT JOIN tasks t ON t.id=r.task_id LEFT JOIN jobs j ON j.id=r.job_id "
            "WHERE substr(COALESCE(r.started_at, j.created_at, ''),1,10)=? ORDER BY r.id", [date])
    for j in out["jobs"]:
        try:
            j["minutes"] = round((datetime.fromisoformat(j["finished_at"]) - datetime.fromisoformat(j["started_at"])).total_seconds() / 60, 1)
        except (TypeError, ValueError):
            j["minutes"] = None
    return out


def _stale(date: str, scanned_at: str, minutes: int = 10) -> bool:
    """当天扫描的快照只有半天数据：那天还没结束时超过 10 分钟就重扫，那天结束后重扫一次定稿。"""
    if scanned_at >= (Date.fromisoformat(date) + timedelta(days=1)).isoformat():
        return False
    return date != db.today() or scanned_at < (datetime.now() - timedelta(minutes=minutes)).isoformat(timespec="seconds")


def scan_efficiency(date: str) -> dict:
    cfg = settings.load()
    ids = chat.engine_sessions()
    sessions = rs.scan(Date.fromisoformat(date), cfg.get("session_dirs", {}) or {}, ids)
    summary = rs.aggregate(sessions)
    summary["tz"] = time.tzname[0]
    try:  # 墙钟等待与「Agent 看板 · 时间利用」同一算法（多个会话同时等只算一次）
        u = util.analyze(Date.fromisoformat(date), cfg.get("session_dirs", {}) or {}, cfg["focus_windows"], cfg["day_start"],
                         cfg["day_end"], int(cfg.get("max_agent_concurrency", 3)), chat_ids=ids)["summary"]
        summary["wait_wall_min"] = u["wait_wall_min"]
        summary["headline"] = rs.headline(summary)
    except Exception:  # noqa: BLE001
        pass
    runs = platform_runs(date)
    summary["platform_jobs"] = len(runs["jobs"])
    summary["platform_jobs_failed"] = sum(1 for j in runs["jobs"] if j["status"] == "failed")
    _upsert_stats(date, {"summary": summary, "sessions": sessions, "scanned_at": db.now()})
    return get_efficiency(date, scan_if_missing=False)


def get_efficiency(date: str, scan_if_missing: bool = True) -> dict | None:
    r = db.row("SELECT * FROM review_agent_stats WHERE date=?", [date])
    if scan_if_missing and (not r or not r.get("scanned_at") or _stale(date, r["scanned_at"])
                            or _loads(r["summary"], {}).get("v") != rs.VERSION
                            or _loads(r["summary"], {}).get("tz", time.tzname[0]) != time.tzname[0]):
        return scan_efficiency(date)
    if not r or not r.get("scanned_at"):
        return None
    r["summary"] = _loads(r["summary"], {})
    r["sessions"] = _loads(r["sessions"], [])
    r["kind_labels"] = rs.KIND_LABELS
    return r


@router.get("/efficiency")
def api_efficiency(date: str = "", refresh: bool = False):
    date = _day(date)
    eff = scan_efficiency(date) if refresh else get_efficiency(date)
    eff["platform"] = platform_runs(date)
    eff["reflect_job"] = db.row("SELECT id, status FROM jobs WHERE module='review' AND ref=? ORDER BY id DESC LIMIT 1",
                                [f"reflect:{date}"])
    return eff


def reflect_prompt(date: str) -> str:
    eff = get_efficiency(date) or {"summary": {}, "sessions": []}
    summ = {k: v for k, v in eff["summary"].items() if k != "by_project"}
    lines = []
    for s in eff["sessions"]:
        if s["automated"] and not s["human_turns"]:
            continue
        lines.append(f"\n### [{s['engine']}] {s['project']} {s.get('title', '')[:40]} "
                     f"{s['start'][11:16]}-{s['end'][11:16]} 活跃 {s['active_min']} 分 / 墙钟 {s['wall_min']} 分，"
                     f"工具 {s['tool_calls']} 次，错误 {s['tool_errors']}，权限拒绝 {s['denials']}")
        for m in s["messages"][:40]:
            w = f"等 {m['wait_min']} 分后" if m["wait_min"] is not None else ""
            lines.append(f"- {m['t']} {w} [{rs.KIND_LABELS.get(m['kind'], m['kind'])}] {m['text'][:200]}")
    auto = [s for s in eff["sessions"] if s["automated"]]
    runs = platform_runs(date)
    plan = runs.get("plan_runs") or []
    focus = settings.get("focus_windows", [])
    return f"""请反思 {date} 使用 Claude Code / Codex 的效率，重点是「人工介入」。只读分析：不要修改文件、不要运行测试或启动服务。

## 当日汇总（自动统计，分类是启发式的，可能有误）
{json.dumps(summ, ensure_ascii=False)}
自动化会话 {len(auto)} 个（脚本化 claude -p / codex exec）；本平台后台任务 {len(runs['jobs'])} 个；规划自动执行 {len(plan)} 个。
专注时间窗：{json.dumps(focus, ensure_ascii=False)}

## 各交互会话的人工消息（时间、等待、分类、内容截断）
{chr(10).join(lines) or '（无）'}

## 规划板块自动执行
{json.dumps(plan[:30], ensure_ascii=False, default=str) if plan else '（无）'}

## 输出（markdown，中文，具体）
1. 概览：今天人花在盯 Agent 上的时间、介入次数和主要类型。
2. 逐类判断介入是否必要：哪些是必要的（真实决策、需求变化），哪些可避免（纠正本可在需求里写清、确认/继续类、权限拒绝、询问进度、等待过长）。举出具体消息为例。
3. 可避免的根因与对策：更好的前置规格（给出可复用的提示词模板片段）、权限 allowlist（给出具体的工具/命令模式）、沉淀成 skill 的重复操作、可以并行的会话、可以挪到非专注时间自动跑的任务。
4. 明天可执行的 3-5 条改进清单。"""


@router.post("/reflect")
def api_reflect(body: DateIn):
    date = _day(body.date)
    prompt = reflect_prompt(date)
    jid = jobs.submit("review", prompt, ref=f"reflect:{date}", system=agent.build_system("review"))
    _upsert_stats(date, {"reflect_job_id": jid})
    return {"job_id": jid, "date": date}


# ---------- 写复盘后的改进分析 ----------

def learning_feedback(date: str) -> list[str]:
    """学习平台当天的反馈：测试 / 停一下的批改、对步骤的理解度与反馈、读材料时划线问的问题。"""
    lx = learning_extra(date)
    out = [f"- 学习习惯 · {x}" for x in lx.get("habits") or []] + [f"- {x}" for x in lx["events"]]
    out += [f"- {x}" for x in lx.get("reads") or []]
    if _has_table("learn_steps") and {"feedback", "understanding"} <= _cols("learn_steps"):
        for s in db.rows("SELECT title, status, understanding, feedback FROM learn_steps "
                         "WHERE substr(done_at,1,10)=? AND (feedback!='' OR understanding>0) LIMIT 20", [date]):
            out.append(f"- 步骤「{s['title']}」{s['status']} 理解 {s['understanding'] or '-'}/5"
                       + (f"，反馈：{(s['feedback'] or '')[:200]}" if s["feedback"] else ""))
    if _has_table("annotations") and _has_table("annotation_msgs"):
        for a in db.rows("SELECT a.title, a.quote, m.content FROM annotation_msgs m JOIN annotations a ON a.id=m.annotation_id "
                         "WHERE m.role='user' AND substr(m.created_at,1,10)=? ORDER BY m.id LIMIT 30", [date]):
            out.append(f"- 读「{(a['title'] or '')[:30]}」" + (f"划线「{a['quote'][:50]}」" if a["quote"] else "")
                       + f"问/评：{(a['content'] or '')[:150]}")
    return out


def improve_prompt(date: str) -> str:
    rec = get_record(date)
    entries = "\n".join(f"- {('次日 ' if e['next_day'] else '') + e['time'] if e['time'] else '（未记时间）'} "
                        f"[{REC_LABEL[e['field']]}] {e['text']}" for e in rec["entries"]) or "（无）"
    eff = get_efficiency(date, scan_if_missing=False) or scan_efficiency(date) or {"summary": {}, "sessions": []}
    sess = []
    for x in eff["sessions"]:
        if x["automated"] and not x["human_turns"]:
            continue
        sess.append(f"\n### [{x['engine']}] {x['project']} {x.get('title', '')[:40]} {x['start'][11:16]}-{x['end'][11:16]} "
                    f"活跃 {x['active_min']} 分 / 墙钟 {x['wall_min']} 分，工具错误 {x['tool_errors']}，权限拒绝 {x['denials']}")
        for m in x["messages"][:25]:
            w = f"等 {m['wait_min']} 分后" if m["wait_min"] is not None else ""
            sess.append(f"- {m['t']} {w} [{rs.KIND_LABELS.get(m['kind'], m['kind'])}] {m['text'][:160]}")
    runs = platform_runs(date)
    failed = [f"- #{j['id']} {j['module']} {j['ref']} {j['status']}" for j in runs["jobs"] if j["status"] != "done"]
    learn_fb = learning_feedback(date)
    since = (Date.fromisoformat(date) - timedelta(days=7)).isoformat()
    prev = [f"- {n['date']} [{n['kind']}] {n['title']}" for n in list_notes(start=since, end=date, limit=30)]
    return f"""用户刚写完 {date} 的复盘。请结合当天的 Claude Code / Codex 会话和学习平台的反馈，分析怎么改进。
只读分析：不要修改文件或平台数据，不要运行测试、不要启动服务。

## 用户写的复盘（按写下的时间排列）
{entries}

## 当天事项
{_task_lines(tasks.list_for(date))}

## 当天 Agent 会话（人工消息：时间、等待、分类、内容截断）
汇总：{eff["summary"].get("headline", "") or "（无）"}
{chr(10).join(sess) or "（无交互会话）"}

## 本平台后台任务
共 {len(runs["jobs"])} 个，未成功：
{chr(10).join(failed) or "（无）"}

## 学习平台反馈（测试 / 停一下批改 / 理解度与反馈 / 划线提问）
{chr(10).join(learn_fb) or "（无）"}

## 近 7 天已记的问题与经验（别重复给，看有没有落实）
{chr(10).join(prev) or "（无）"}

## 输出（markdown，中文，具体、简洁，不要复述原文）
1. **时间线**：把复盘的每一条放回当天的时间线（对应哪个会话 / 学习步骤 / 后台任务、发生在几点），一条一行。
2. **逐条诊断**：每条复盘的证据（引用上面具体的消息、测试分数、失败任务）、根因；证据不足就直说「无证据」。
3. **改进**：分「怎么用 Agent」「怎么学习」「平台该补的能力」三类，每条写清楚做什么、怎么验证有效；已在近 7 天记过的标注「已记过，未落实 / 已落实」。
4. **明天就做的 3 条**：可执行、可检查。"""


def submit_improve(date: str) -> int:
    """写复盘后派一次改进分析。还在排队的那次直接换成最新内容，不重复排队。"""
    prompt = improve_prompt(date)
    q = db.row("SELECT id FROM jobs WHERE module='review' AND ref=? AND status='queued' ORDER BY id DESC LIMIT 1",
               [f"improve:{date}"])
    if q and db.execute("UPDATE jobs SET prompt=? WHERE id=? AND status='queued'", [prompt, q["id"]]):
        jid = q["id"]
    else:
        jid = jobs.submit("review", prompt, ref=f"improve:{date}", system=agent.build_system("review"),
                          add_dirs=repo_dirs(date))
    upsert_record(date, {"improve_job_id": jid})
    return jid


@router.post("/improve")
def api_improve(body: DateIn):
    date = _day(body.date)
    return {"job_id": submit_improve(date), "date": date}


# ---------- 对话 Agent ----------

def agent_context(ref: str) -> str:
    date = _day(ref)
    d = day_data(date)
    rec = d["record"]
    parts = [f"复盘日期：{date}（今天 {db.today()}）",
             "### 事项\n" + _task_lines([t for t in tasks.list_for(date)])]
    if d["learning_extra"]["steps"]:
        parts.append("### 学习步骤\n" + "\n".join(f"- [{s['id']}] {s['title']}（{s['status']}）" for s in d["learning_extra"]["steps"]))
    if d["learning_extra"].get("reads"):
        parts.append("### 深读（追问次数、用户写下的感想）\n" + "\n".join(f"- {x}" for x in d["learning_extra"]["reads"]))
    if d["learning_extra"].get("events"):
        parts.append("### 学习记录（测试 / 停一下 / 理解度变化；复盘学习时据此评价理解、判断、应用，并给出怎么提升）\n"
                     + "\n".join(f"- {x}" for x in d["learning_extra"]["events"][-30:]))
    parts.append("### 复盘记录\n" + "\n".join(f"- {k}：{rec.get(k) or '（空）'}" for k in ("summary", "wins", "problems", "next_actions")))
    if rec.get("ai_analysis"):
        parts.append("### AI 检查结论（摘要）\n" + rec["ai_analysis"][:1500])
    if rec.get("improve_md"):
        parts.append("### AI 改进分析（摘要）\n" + rec["improve_md"][:1500])
    if d["notes"]:
        parts.append("### 问题与经验\n" + "\n".join(f"- [{n['kind']}] {n['title']}：{(n['content'] or '')[:150]}" for n in d["notes"]))
    if d["efficiency"]:
        parts.append("### Agent 效率\n" + d["efficiency"]["headline"])
    parts.append("分析目录：" + (", ".join(repo_dirs(date)) or "（未配置）"))
    return "\n\n".join(parts)


def agent_dirs(ref: str) -> list[str]:
    return repo_dirs(_day(ref))
