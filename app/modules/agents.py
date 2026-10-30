"""Agent 看板：本地 Claude Code / Codex 会话 + 平台后台任务的进度流转看板（解析在 _agents_scan.py）。

列：running 运行中 → attention 等你处理 → review 待验收 → done 已验收（另有 archived 归档，默认隐藏）。
前三列由日志自动判断；「已验收 / 归档」是用户操作，存在 agent_board 表里。
会话之后又有新活动（比如你续聊了），用户标记自动失效，卡片回到自动判断的列。
"""
from __future__ import annotations

import shlex
import subprocess
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import db, settings, tasks
from . import _agents_scan as scanner

TITLE = "Agent 看板"
ORDER = 8
SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_board (
    key         TEXT PRIMARY KEY,          -- claude:<session> / codex:<session> / job:<id>
    col         TEXT DEFAULT '',           -- done / archived / ''（自动）
    note        TEXT DEFAULT '',
    task_id     INTEGER,                   -- 关联的规划事项；验收时一并标记完成
    updated_at  TEXT
);
"""
COLUMNS = [("running", "运行中"), ("attention", "等你处理"), ("review", "待验收"), ("done", "已验收")]
router = APIRouter()


def _job_cards(hours: float) -> list[dict]:
    since = (datetime.now() - timedelta(hours=hours)).isoformat(timespec="seconds")
    out = []
    for j in db.rows("SELECT id,module,ref,engine,status,prompt,output,created_at,started_at,finished_at FROM jobs "
                     "WHERE created_at>=? ORDER BY id DESC LIMIT 100", [since]):
        last = j["finished_at"] or j["started_at"] or j["created_at"]
        state, reason = {"queued": ("running", "排队中"), "running": ("running", "执行中"),
                         "done": ("review", "已完成"), "failed": ("attention", "失败")}.get(j["status"], ("review", j["status"]))
        first = next((ln.strip() for ln in (j["prompt"] or "").splitlines() if ln.strip()), "")
        out.append({"key": f"job:{j['id']}", "engine": "platform", "session_id": str(j["id"]), "project": j["module"],
                    "cwd": "", "branch": "", "title": scanner._clip(f"{j['ref'] or j['module']} · {first}", 80),
                    "last_human": "", "last_agent": scanner._clip(j["output"] or ""), "plan": [], "plan_done": 0, "plan_current": "",
                    "humans": 0, "tools": 0, "automated": False, "start": j["created_at"], "last": last,
                    "idle_min": round((datetime.now() - datetime.fromisoformat(last)).total_seconds() / 60, 1),
                    "state": state, "reason": reason, "error": "", "file": ""})
    return out


def board(hours: float = 24, automated: bool = False) -> dict:
    cards = scanner.scan(settings.get("session_dirs", {}), hours) + _job_cards(hours)
    marks = {r["key"]: r for r in db.rows("SELECT * FROM agent_board")}
    hidden_auto, archived = 0, 0
    cols: dict[str, list] = {c: [] for c, _ in COLUMNS}
    for c in cards:
        m = marks.get(c["key"])
        col = c["state"]
        if m:
            c.update(note=m["note"] or "", task_id=m["task_id"])
            # 用户标记只在会话之后没有新活动时有效
            if m["col"] and (m["updated_at"] or "") >= c["last"]:
                col = m["col"]
        if col == "archived":
            archived += 1
            continue
        if c["automated"] and not automated and col != "done":
            hidden_auto += 1
            continue
        c["column"] = col
        cols.setdefault(col, []).append(c)
    return {"columns": [{"id": k, "title": t, "cards": cols.get(k, [])} for k, t in COLUMNS],
            "hidden_automated": hidden_auto, "archived": archived, "hours": hours, "generated_at": db.now()}


@router.get("/board")
def get_board(hours: float = 24, automated: bool = False):
    return board(hours, automated)


class StateIn(BaseModel):
    key: str
    col: str | None = None      # done / archived / ''（恢复自动）
    note: str | None = None
    task_id: int | None = None


@router.post("/state")
def set_state(body: StateIn):
    if body.col not in (None, "", "done", "archived"):
        raise HTTPException(400, "col must be done / archived / ''")
    cur = db.row("SELECT * FROM agent_board WHERE key=?", [body.key]) or {"key": body.key, "col": "", "note": "", "task_id": None}
    new = {"col": cur["col"] if body.col is None else body.col,
           "note": cur["note"] if body.note is None else body.note,
           "task_id": cur["task_id"] if body.task_id is None else (body.task_id or None)}
    db.execute("INSERT INTO agent_board(key,col,note,task_id,updated_at) VALUES (?,?,?,?,?) "
               "ON CONFLICT(key) DO UPDATE SET col=excluded.col, note=excluded.note, task_id=excluded.task_id, updated_at=excluded.updated_at",
               [body.key, new["col"], new["note"], new["task_id"], db.now()])
    if new["col"] == "done" and new["task_id"]:
        try:
            tasks.patch(int(new["task_id"]), {"status": "done", "progress": 100})
        except HTTPException:
            pass
    return {"key": body.key, **new}


def resume_command(key: str, cwd: str) -> str:
    engine, sid = key.split(":", 1)
    cd = f"cd {shlex.quote(cwd)} && " if cwd else ""
    if engine == "claude":
        return f"{cd}claude --resume {sid}"
    if engine == "codex":
        return f"{cd}codex resume {sid}"
    raise HTTPException(400, "只有 Claude Code / Codex 会话可以续接")


class OpenIn(BaseModel):
    key: str
    cwd: str = ""


@router.post("/resume-command")
def get_resume_command(body: OpenIn):
    return {"command": resume_command(body.key, body.cwd)}


@router.post("/open")
def open_terminal(body: OpenIn):
    """在 macOS 终端里打开并续接这个会话（用户点击触发）。"""
    cmd = resume_command(body.key, body.cwd)
    script = f'tell application "Terminal" to do script "{cmd.replace(chr(92), chr(92) * 2).replace(chr(34), chr(92) + chr(34))}"'
    try:
        subprocess.run(["osascript", "-e", script, "-e", 'tell application "Terminal" to activate'], check=True,
                       capture_output=True, timeout=10)
    except (subprocess.SubprocessError, FileNotFoundError) as e:
        raise HTTPException(500, f"打开终端失败：{e}")
    return {"ok": True, "command": cmd}


def agent_context(ref: str) -> str:
    b = board(24)
    lines = [f"最近 24 小时（{b['generated_at']}），隐藏脚本会话 {b['hidden_automated']} 个、归档 {b['archived']} 个："]
    for col in b["columns"]:
        lines.append(f"\n## {col['title']}（{len(col['cards'])}）")
        for c in col["cards"][:15]:
            plan = f" · 计划 {c['plan_done']}/{len(c['plan'])} 当前：{c['plan_current']}" if c["plan"] else ""
            lines.append(f"- [{c['engine']}] {c['project']} · {c['title']} · {c['reason']} · {c['idle_min']} 分钟前{plan}"
                         f" · key={c['key']}\n  最近要求：{c['last_human'][:120]}\n  最近回复：{c['last_agent'][:160]}")
    return "\n".join(lines)
