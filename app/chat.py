"""每个板块的对话 Agent：/api/chat/<module>，SSE 流式返回，会话可续聊。"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from . import agent, chat_images, db, jobs, kb, kb_idea, modules

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/chat", tags=["chat"])
active = 0  # 正在进行的对话轮数；自动重启会等它归零
INTERRUPTED = "（说到这里被打断）"
_procs: dict[int, object] = {}  # 正在回复的会话 → CLI 进程，打断时用
_stopping: set[int] = set()


class ChatIn(BaseModel):
    message: str
    session_id: int | None = None   # 平台会话 id；空则新建
    ref: str = ""                   # 绑定对象，如 learn:plan:3
    engine: str = ""                # claude / codex，空=默认
    images: list[str] = Field(default_factory=list, max_length=4)


class ImageIn(BaseModel):
    name: str = Field(default="图片", max_length=255)
    data: str = Field(max_length=12_000_000)


@router.post("/images")
def upload_image(body: ImageIn):
    try:
        return chat_images.upload(body.name, body.data)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/images/{image_id}")
def image_file(image_id: str):
    try:
        img = chat_images.get(image_id)
    except ValueError:
        raise HTTPException(404, "image not found")
    return FileResponse(chat_images.path(img), media_type=img["mime"], headers={"X-Content-Type-Options": "nosniff"})


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
    return ctx, [*dirs, str(kb.KB_DIR), str(chat_images.directory())]


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
    for message in s["messages"]:
        message["images"] = chat_images.of("message", message["id"])
    return s


@router.delete("/session/{sid}")
def delete_session(sid: int):
    db.execute("DELETE FROM chat_messages WHERE session_id=?", [sid])
    db.execute("DELETE FROM chat_sessions WHERE id=?", [sid])
    return {"ok": True}


def _with_interruption(sid: int, message: str) -> str:
    """上一轮被打断时，CLI 会话里未必留下了那半句话和用户的问题，这一轮告诉它。只给 Agent 看，不进对话记录。"""
    last = db.rows("SELECT role,content FROM chat_messages WHERE session_id=? AND role IN ('user','assistant') ORDER BY id DESC LIMIT 3", [sid])
    if len(last) < 3 or last[1]["role"] != "assistant" or not last[1]["content"].endswith(INTERRUPTED):
        return message
    said = last[1]["content"].removesuffix(INTERRUPTED)
    return f"（上一轮我说的是「{last[2]['content']}」，你答到「{said[-200:]}」时被我打断了，下面是我接着说的）\n{message}"


def _prepare_next(module: str, ref: str, session: str) -> None:
    ctx, dirs = _context(module, ref)
    agent.warm_up(system=agent.build_system(module, ctx), session=session, add_dirs=dirs, model=agent.module_model(module))


@router.post("/warm/{module}")
def warm(module: str, session_id: int = 0):
    """语音通话开始时先起好 CLI，第一句也接得快。只有只读板块才有。"""
    if getattr(modules.get(module), "CHAT_READONLY", False):
        sess = db.row("SELECT * FROM chat_sessions WHERE id=?", [session_id]) if session_id else None
        if not sess or (sess["engine"] in ("", "claude")):
            _prepare_next(module, sess["ref"] if sess else "", sess["engine_session"] if sess else "")
    return {"ok": True}


@router.post("/stop/{sid}")
def stop_reply(sid: int):
    """打断正在生成的回复：停掉 CLI，已生成的部分照常存下，会话还能续聊。"""
    _stopping.add(sid)
    if sid in _procs:
        agent.stop(_procs[sid])
    return {"ok": True}


@router.post("/{module}")
def chat(module: str, body: ChatIn):
    try:
        images = chat_images.resolve(body.images)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not body.message.strip() and not images:
        raise HTTPException(400, "请填写消息或添加图片")
    sess = db.row("SELECT * FROM chat_sessions WHERE id=?", [body.session_id]) if body.session_id else None
    if not sess:
        sid = db.insert("chat_sessions", {"module": module, "ref": body.ref, "engine": body.engine or "",
                                          "title": body.message[:40], "created_at": db.now(), "updated_at": db.now()})
        sess = db.row("SELECT * FROM chat_sessions WHERE id=?", [sid])
    sid = sess["id"]
    _stopping.discard(sid)
    prompt = _with_interruption(sid, body.message)
    message_id = db.insert("chat_messages", {"session_id": sid, "role": "user", "content": body.message, "created_at": db.now()})
    chat_images.attach("message", message_id, body.images)
    mod = modules.get(module)
    if mod and hasattr(mod, "on_chat"):  # 板块按用户的话更新自己的记录（如深读条目的追问 / 感想推进当天事项）
        try:
            mod.on_chat(sess["ref"] or "", body.message)
        except Exception:  # noqa: BLE001
            log.exception("on_chat %s", module)

    # 每轮都带上最新数据快照，让 Agent 看到平台的当前状态
    ctx, dirs = _context(module, sess["ref"] or body.ref)
    system = agent.build_system(module, ctx)
    think = module == "kb" and (sess["ref"] or body.ref).startswith("think:")
    engine_session = sess["engine_session"] if not think or sess["engine"] in ("", "claude") else ""
    engine = "claude" if think else (sess["engine"] if sess["engine_session"] else (body.engine or sess["engine"]))
    if think and sess["engine"] not in ("", "claude"):
        prior = db.rows("SELECT role,content FROM chat_messages WHERE session_id=? AND id<? AND role IN ('user','assistant') ORDER BY id", [sid, message_id])
        if prior:
            transcript = json.dumps(prior, ensure_ascii=False)
            prompt = f"以下是同一话题此前的讨论记录，仅作背景：\n{transcript}\n\n用户现在接着说：\n{prompt}"

    if think:
        prompt = "这是「今日一想」的分析讨论，只交换想法，不执行工程任务；不输出工程验收或自主决策汇报。\n用户这轮说：\n" + prompt

    prompt += chat_images.prompt(images)

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
        final, eng_session, used = "", engine_session, engine
        said, live = [], ""
        reply_id = None

        def save_reply(text, role="assistant"):
            nonlocal reply_id
            if reply_id:
                db.update("chat_messages", reply_id, {"content": text, "role": role})
            else:
                reply_id = db.insert("chat_messages", {"session_id": sid, "role": role, "content": text, "created_at": db.now()})

        def on_proc(proc):
            _procs[sid] = proc
            if sid in _stopping:  # 打断时进程还没起来
                agent.stop(proc)

        run = agent.run_stream(prompt, engine=engine, system=system,
                               session=engine_session, add_dirs=dirs,
                               model=kb_idea.MODEL if think else agent.module_model(module, engine),
                               fallback=not think,
                               readonly=getattr(mod, "CHAT_READONLY", False), on_proc=on_proc)
        for ev in run:
            if sid in _stopping:  # 不往下读：进程被杀后的报错不是真错，也不该回退到备选引擎
                run.close()
                final = "\n\n".join([*said, live]).strip() + INTERRUPTED
                yield _sse({"type": "done", "text": final, "engine": used})
                break
            if ev["type"] == "delta":
                live += ev["text"]
            elif ev["type"] == "text":
                said.append(ev["text"])
                live = ""
            if ev["type"] == "session":
                eng_session = ev["id"]
                if think:
                    db.update("chat_sessions", sid, {"engine": engine, "engine_session": eng_session, "updated_at": db.now()})
            elif ev["type"] == "done":
                final, used = ev["text"], ev["engine"]
            elif ev["type"] == "tool":
                db.insert("chat_messages", {"session_id": sid, "role": "tool", "content": ev["text"], "created_at": db.now()})
            if think and ev["type"] in ("text", "done"):
                visible = final or "\n\n".join(said).strip()
                if visible:
                    save_reply(visible)
            yield _sse(ev)
        _procs.pop(sid, None)
        _stopping.discard(sid)
        save_reply(final or "（无回复，见上方错误）", "assistant" if final else "error")
        db.update("chat_sessions", sid, {"engine": used, "engine_session": eng_session, "updated_at": db.now()})
        if getattr(mod, "CHAT_READONLY", False) and used == "claude" and eng_session:
            _prepare_next(module, sess["ref"] or body.ref, eng_session)
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


def engine_sessions() -> set[str]:
    """对话面板对应的 Claude / Codex 会话 id：日志里像 claude -p 脚本会话，但提示是人打的字（效率统计按人工交互算）。"""
    try:
        return {r["engine_session"] for r in db.rows("SELECT engine_session FROM chat_sessions WHERE engine_session<>''")}
    except Exception:  # noqa: BLE001 —— 表还没建
        return set()


def _sse(obj: dict) -> str:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"
