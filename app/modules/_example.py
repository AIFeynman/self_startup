"""板块模板（下划线开头不会被加载）。复制为 app/modules/<name>.py。"""
from fastapi import APIRouter

from .. import db, jobs  # noqa: F401

TITLE = "示例"
ORDER = 99
SCHEMA = """
CREATE TABLE IF NOT EXISTS example_notes (id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT, created_at TEXT);
"""
router = APIRouter()


@router.get("/notes")
def notes():
    return db.rows("SELECT * FROM example_notes ORDER BY id DESC")


def agent_context(ref: str) -> str:
    return "最近笔记：" + "; ".join(n["text"] for n in notes()[:10])
