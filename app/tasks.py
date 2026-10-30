"""每日事项的通用 CRUD（规划写、复盘改状态都用它）。"""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import db

router = APIRouter(prefix="/api/tasks", tags=["tasks"])

FIELDS = ["date", "parent_id", "title", "goal", "kind", "priority", "human_level", "executor", "est_minutes",
          "parallel_group", "depends_on", "start_time", "end_time", "status", "progress", "repo", "notes"]


class TaskIn(BaseModel):
    date: str | None = None
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


def list_for(date: str) -> list[dict]:
    return [decode(t) for t in db.rows("SELECT * FROM tasks WHERE date=? ORDER BY COALESCE(start_time,''), priority, id", [date])]


def create(data: dict) -> dict:
    data = {k: v for k, v in data.items() if k in FIELDS and v is not None}
    data.setdefault("date", db.today())
    if not data.get("title"):
        raise HTTPException(400, "title required")
    data["created_at"] = data["updated_at"] = db.now()
    tid = db.insert("tasks", data)
    return get(tid)


def get(tid: int) -> dict:
    t = db.row("SELECT * FROM tasks WHERE id=?", [tid])
    if not t:
        raise HTTPException(404, "task not found")
    return decode(t)


def patch(tid: int, data: dict) -> dict:
    get(tid)
    data = {k: v for k, v in data.items() if k in FIELDS and v is not None}
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
