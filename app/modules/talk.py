"""讨论：语音或打字说想法，对话 Agent 帮忙理思路、给建议。对话走 /api/chat/talk（只读）；
讨论完「整理」成结论 / 待定问题 / 下一步，人确认后才写入知识库和规划事项。"""
from __future__ import annotations

import json
import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import agent, db, tasks
from . import review

TITLE = "讨论"
ORDER = 7
CHAT_READONLY = True  # 语音可能听错，讨论时 Agent 只能读；写入只走下面人确认过的 save
SCHEMA = """
CREATE TABLE IF NOT EXISTS talk_summaries (
  id INTEGER PRIMARY KEY AUTOINCREMENT, session_id INTEGER, title TEXT, content TEXT, next_steps TEXT,
  note_id INTEGER, task_ids TEXT, created_at TEXT, saved_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_talk_summaries_session ON talk_summaries(session_id);
"""
router = APIRouter()

ORGANIZE_PROMPT = """下面是用户和你的一次讨论记录（用户的话来自语音转写，可能有错字）。把它整理出来，只输出一个 JSON 对象，不要别的文字：
{{"title": "这次讨论的主题，20 字内",
  "content": "markdown 正文，三节：**结论**（已经想清楚的）、**待定问题**（还没想清楚的）、**理由和依据**（关键的为什么）。只写讨论里出现过的，不要补充新观点；没有的节省略",
  "next_steps": ["下一步要做的事，一条一件，动词开头，30 字内；讨论里没提到就给空数组"]}}

讨论记录：
{transcript}"""


def _transcript(sid: int) -> str:
    msgs = db.rows("SELECT role,content FROM chat_messages WHERE session_id=? AND role IN ('user','assistant','fast') ORDER BY id", [sid])
    return "\n\n".join(("用户：" if m["role"] == "user" else "你：") + m["content"] for m in msgs)


def _parse_summary(text: str) -> dict:
    m = re.search(r"\{.*\}", text or "", re.S)
    try:
        d = json.loads(m.group(0)) if m else None
    except json.JSONDecodeError:
        d = None
    if not isinstance(d, dict) or not d.get("content"):
        raise HTTPException(502, "整理结果解析失败，再试一次")
    steps = d.get("next_steps")
    return {"title": str(d.get("title") or "讨论")[:60], "content": str(d["content"]),
            "next_steps": [str(s) for s in steps if s] if isinstance(steps, list) else []}


def _row(r: dict | None) -> dict | None:
    if r:
        r["next_steps"] = json.loads(r["next_steps"] or "[]")
        r["task_ids"] = json.loads(r["task_ids"] or "[]")
    return r


class OrganizeIn(BaseModel):
    session_id: int


@router.post("/organize")
def organize(body: OrganizeIn):
    """只生成草稿存起来，不写知识库和事项。每次整理都是新的一条，不覆盖之前的。"""
    transcript = _transcript(body.session_id)
    if not transcript:
        raise HTTPException(400, "这个讨论还没有内容")
    r = agent.run_once(ORGANIZE_PROMPT.format(transcript=transcript), readonly=True, model=agent.module_model("talk"))
    d = _parse_summary(r["text"])
    sid = db.insert("talk_summaries", {"session_id": body.session_id, "title": d["title"], "content": d["content"],
                                       "next_steps": json.dumps(d["next_steps"], ensure_ascii=False), "created_at": db.now()})
    return _row(db.row("SELECT * FROM talk_summaries WHERE id=?", [sid]))


@router.get("/summaries")
def summaries(session_id: int = 0, limit: int = 20):
    sql, args = "SELECT * FROM talk_summaries", []
    if session_id:
        sql, args = sql + " WHERE session_id=?", [session_id]
    return [_row(r) for r in db.rows(sql + " ORDER BY id DESC LIMIT ?", args + [limit])]


class SaveIn(BaseModel):
    title: str
    content: str
    next_steps: list[str] = []  # 人勾选、改过的事项


@router.post("/summaries/{sid}/save")
def save(sid: int, body: SaveIn):
    """人确认后写入：正文记成一条洞察（进知识库），勾选的下一步加到今天的事项。重复点不会重复写。"""
    s = _row(db.row("SELECT * FROM talk_summaries WHERE id=?", [sid]))
    if not s:
        raise HTTPException(404)
    if s["saved_at"]:
        return s
    note = review.api_add_note(review.NoteIn(kind="insight", title=body.title, content=body.content, tags="讨论"))
    created = [tasks.create({"title": t.strip()}) for t in body.next_steps if t.strip()]
    db.update("talk_summaries", sid, {"title": body.title, "content": body.content,
                                      "next_steps": json.dumps(body.next_steps, ensure_ascii=False),
                                      "note_id": note["id"], "task_ids": json.dumps([t["id"] for t in created]), "saved_at": db.now()})
    return _row(db.row("SELECT * FROM talk_summaries WHERE id=?", [sid]))


def agent_context(ref: str) -> str:
    ts = tasks.list_for(db.today())
    lines = [f"今天 {db.today()}。今天的事项（讨论计划、取舍时参考，别主动念给用户听）："]
    lines += [f"- [{t['status']}] {t['title']}" for t in ts[:15]] or ["（还没有事项）"]
    return "\n".join(lines)
