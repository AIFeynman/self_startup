"""每个板块的对话 Agent：/api/chat/<module>，SSE 流式返回，会话可续聊。"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from . import agent, db, jobs, kb, modules

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/chat", tags=["chat"])
active = 0  # 正在进行的对话轮数；自动重启会等它归零


class ChatIn(BaseModel):
    message: str
    session_id: int | None = None   # 平台会话 id；空则新建
    ref: str = ""                   # 绑定对象，如 learn:plan:3
    engine: str = ""                # claude / codex，空=默认


def _context(module: str, ref: str) -> tuple[str, list[str]]:
    mod = modules.get(module)
    ctx, dirs = "", []
    if mod and hasattr(mod, "agent_context"):
        try:
            ctx = mod.agent_context(ref) or ""
        except Exception:  # noqa: BLE001
            log.exception("agent_context %s", module)
    if mod and hasattr(mod, "agent_dirs"):
        try:
            dirs = mod.agent_dirs(ref) or []
        except Exception:  # noqa: BLE001
            log.exception("agent_dirs %s", module)
    return ctx, [*dirs, str(kb.KB_DIR)]


@router.get("/recent")
def recent(limit: int = 8):
    return db.rows("SELECT id,module,ref,title,engine,updated_at FROM chat_sessions ORDER BY updated_at DESC LIMIT ?", [limit])


@router.get("/{module}/sessions")
def sessions(module: str, ref: str = ""):
    sql, args = "SELECT * FROM chat_sessions WHERE module=?", [module]
    if ref:
        sql, args = sql + " AND ref=?", args + [ref]
    return db.rows(sql + " ORDER BY updated_at DESC LIMIT 50", args)


@router.get("/session/{sid}")
def session_messages(sid: int):
    s = db.row("SELECT * FROM chat_sessions WHERE id=?", [sid])
    if not s:
        raise HTTPException(404)
    s["messages"] = db.rows("SELECT * FROM chat_messages WHERE session_id=? ORDER BY id", [sid])
    return s


@router.delete("/session/{sid}")
def delete_session(sid: int):
    db.execute("DELETE FROM chat_messages WHERE session_id=?", [sid])
    db.execute("DELETE FROM chat_sessions WHERE id=?", [sid])
    return {"ok": True}


@router.post("/{module}")
def chat(module: str, body: ChatIn):
    sess = db.row("SELECT * FROM chat_sessions WHERE id=?", [body.session_id]) if body.session_id else None
    if not sess:
        sid = db.insert("chat_sessions", {"module": module, "ref": body.ref, "engine": body.engine or "",
                                          "title": body.message[:40], "created_at": db.now(), "updated_at": db.now()})
        sess = db.row("SELECT * FROM chat_sessions WHERE id=?", [sid])
    sid = sess["id"]
    db.insert("chat_messages", {"session_id": sid, "role": "user", "content": body.message, "created_at": db.now()})

    # 每轮都带上最新数据快照，让 Agent 看到平台的当前状态
    ctx, dirs = _context(module, sess["ref"] or body.ref)
    system = agent.build_system(module, ctx)
    engine = sess["engine"] if sess["engine_session"] else (body.engine or sess["engine"])

    def stream():
        global active
        active += 1
        try:
            yield from _stream()
        finally:
            active -= 1

    def _stream():
        last_job = (db.row("SELECT max(id) AS m FROM jobs") or {}).get("m") or 0
        yield _sse({"type": "meta", "session_id": sid})
        final, eng_session, used = "", sess["engine_session"], engine
        for ev in agent.run_stream(body.message, engine=engine, system=system,
                                   session=sess["engine_session"], add_dirs=dirs):
            if ev["type"] == "session":
                eng_session = ev["id"]
            elif ev["type"] == "done":
                final, used = ev["text"], ev["engine"]
            elif ev["type"] == "tool":
                db.insert("chat_messages", {"session_id": sid, "role": "tool", "content": ev["text"], "created_at": db.now()})
            yield _sse(ev)
        db.insert("chat_messages", {"session_id": sid, "role": "assistant" if final else "error",
                                    "content": final or "（无回复，见上方错误）", "created_at": db.now()})
        db.update("chat_sessions", sid, {"engine": used, "engine_session": eng_session, "updated_at": db.now()})
        linked = link_jobs(sid, last_job)
        yield _sse({"type": "end", "jobs": linked})

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def link_jobs(sid: int, after_id: int) -> list[int]:
    """这一轮对话里 Agent 通过 API 提交的后台任务（id > 本轮开始时的最大 id），挂到这个对话上：任务结束时结果会回帖过来。
    （Agent 用 curl 调接口，带不上会话 id，所以按本轮期间新建的任务认领；已经结束的立即回帖。）"""
    js = db.rows("SELECT * FROM jobs WHERE id>? AND chat_session_id IS NULL", [after_id])
    for j in js:
        db.execute("UPDATE jobs SET chat_session_id=? WHERE id=? AND chat_session_id IS NULL", [sid, j["id"]])
        if j["status"] in ("done", "failed"):
            jobs.notify_chat({**j, "chat_session_id": sid})
    return [j["id"] for j in js]


def _sse(obj: dict) -> str:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"
