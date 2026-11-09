"""每日事项的通用 CRUD（规划写、复盘改状态都用它）。"""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import db

router = APIRouter(prefix="/api/tasks", tags=["tasks"])

FIELDS = ["date", "end_date", "parent_id", "title", "goal", "kind", "priority", "human_level", "executor", "est_minutes",
          "parallel_group", "depends_on", "start_time", "end_time", "status", "progress", "repo", "notes"]


class TaskIn(BaseModel):
    date: str | None = None
    end_date: str | None = None
    parent_id: int | None = None
    title: str | None = None
    goal: str | None = None
    kind: str | None = None
    priority: int | None = None
    human_level: str | None = None
    executor: str | None = None
    est_minutes: int | None = None
    parallel_group: str | None = None
    depends_on: list[int] | None = None
    start_time: str | None = None
    end_time: str | None = None
    status: str | None = None
    progress: int | None = None
    repo: str | None = None
    notes: str | None = None


def decode(t: dict) -> dict:
    try:
        t["depends_on"] = json.loads(t.get("depends_on") or "[]")
    except json.JSONDecodeError:
        t["depends_on"] = []
    return t


CLOSED = ("done", "dropped")
SPAN = "(end_date IS NULL OR end_date>date)"


def is_span(t: dict) -> bool:
    return t.get("end_date") != t["date"]


def span_label(t: dict) -> str:
    if not is_span(t):
        return ""
    return f"【{t['date']} 起，不设结束】" if not t.get("end_date") else f"【{t['date']} ~ {t['end_date']}】"


def list_for(date: str) -> list[dict]:
    """date 当天要看的事项：当天的单日事项 + 覆盖这天的跨日事项（过了结束日还没关的算逾期，照样显示）
    + 这些跨日事项下之前加的子任务（没关的每天都在，关掉那天还显示）。"""
    spans = (f"SELECT id FROM tasks WHERE date<? AND {SPAN} AND (status NOT IN {CLOSED} OR "
             "(substr(updated_at,1,10)>=? AND (end_date IS NULL OR end_date>=?)))")
    return [decode(t) for t in db.rows(
        f"SELECT * FROM tasks WHERE date=? OR id IN ({spans}) OR (date<? AND parent_id IN ({spans}) AND "
        f"(status NOT IN {CLOSED} OR substr(updated_at,1,10)>=?)) "
        "ORDER BY COALESCE(start_time,''), priority, id", [date, date, date, date, date, date, date, date, date])]


def add_once(title: str, date: str, notes: str) -> dict | None:
    if db.row("SELECT id FROM tasks WHERE date=? AND title=?", [date, title]):
        return None
    return create({"title": title, "date": date, "notes": notes})


def _dates(data: dict) -> dict:
    if data.get("end_date") == "":
        data["end_date"] = None
    if data.get("end_date") and data["end_date"] < data["date"]:
        raise HTTPException(400, "结束日期早于开始日期")
    return data


def create(data: dict) -> dict:
    data = {k: v for k, v in data.items() if k in FIELDS and v is not None}
    data.setdefault("date", db.today())
    data.setdefault("end_date", data["date"])
    if not data.get("title"):
        raise HTTPException(400, "title required")
    _dates(data)
    data["created_at"] = data["updated_at"] = db.now()
    tid = db.insert("tasks", data)
    return get(tid)


def get(tid: int) -> dict:
    t = db.row("SELECT * FROM tasks WHERE id=?", [tid])
    if not t:
        raise HTTPException(404, "task not found")
    return decode(t)


def patch(tid: int, data: dict) -> dict:
    t = get(tid)
    data = {k: v for k, v in data.items() if k in FIELDS and v is not None}
    if "date" in data and "end_date" not in data and not is_span(t):
        data["end_date"] = data["date"]
    _dates({"date": t["date"], "end_date": t["end_date"], **data})
    if data.get("end_date") == "":
        data["end_date"] = None
    data["updated_at"] = db.now()
    db.update("tasks", tid, data)
    return get(tid)


@router.get("")
def list_tasks(date: str = "", start: str = "", end: str = ""):
    if start or end:
        rs = db.rows("SELECT * FROM tasks WHERE date BETWEEN ? AND ? ORDER BY date, start_time, priority",
                     [start or "0000", end or "9999"])
        return [decode(t) for t in rs]
    return list_for(date or db.today())


@router.post("")
def create_task(body: TaskIn):
    return create(body.model_dump())


@router.get("/{tid}")
def get_task(tid: int):
    return get(tid)


@router.patch("/{tid}")
def patch_task(tid: int, body: TaskIn):
    return patch(tid, body.model_dump())


@router.delete("/{tid}")
def delete_task(tid: int):
    db.execute("DELETE FROM tasks WHERE parent_id=?", [tid])
    db.execute("DELETE FROM tasks WHERE id=?", [tid])
    return {"ok": True}
