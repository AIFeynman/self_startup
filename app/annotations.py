"""阅读批注：平台里能读的材料（调研报告、深读笔记、知识库文档、学习计划）可以划线评论、直接问 Claude，讨论都存下来。

doc 是材料的稳定标识：research:<id>:synth / research:<id>:r<结果id> / research_doc:<id> / learn:item:<id> /
learn:plan:<id> / learn:step:<id> / kb:<相对路径>。一条批注 = 一段划线（quote 为空表示针对全文）+ 一串讨论；
问 Claude 时在后台线程里跑 claude -p，第一问带上全文和划线，追问续接同一个会话。讨论同步进知识库 annotations/。
"""
from __future__ import annotations

import logging
import threading

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import agent, db, kb, settings

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/annotations", tags=["annotations"])
active = 0  # 正在回答的提问数；自动重启会等它归零（和对话一起算）
_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS annotations (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    doc            TEXT NOT NULL,
    title          TEXT DEFAULT '',
    link           TEXT DEFAULT '',           -- 平台内链接，如 #research/r/3
    quote          TEXT DEFAULT '',           -- 划线的原文；空 = 针对全文
    prefix         TEXT DEFAULT '',           -- 划线前后的原文，材料重新渲染后用来重新定位
    suffix         TEXT DEFAULT '',
    status         TEXT DEFAULT 'open',       -- open / resolved
    engine_session TEXT DEFAULT '',           -- 问 Claude 的会话，追问时续接
    created_at     TEXT,
    updated_at     TEXT
);
CREATE INDEX IF NOT EXISTS idx_annotations_doc ON annotations(doc);
CREATE TABLE IF NOT EXISTS annotation_msgs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    annotation_id INTEGER NOT NULL,
    role          TEXT NOT NULL,              -- user / assistant
    content       TEXT DEFAULT '',
    status        TEXT DEFAULT 'done',        -- assistant：pending / done / failed
    log           TEXT DEFAULT '',            -- assistant：回答过程中用到的工具
    created_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_annotation_msgs ON annotation_msgs(annotation_id);
"""

SYSTEM = agent.PLATFORM_GUIDE + """

## 你现在的角色：阅读助手
用户正在平台里读一份材料，对其中一段（或全文）提问。围绕这份材料回答：先直接回答，再补充必要的背景；
引用原文时用「」标出；材料里没有、需要外部信息的可以联网查，给出来源和日期；不确定就说不确定。
这是讨论，不要修改平台数据。回答用中文 markdown，一般 3–10 行，用户要求展开时再展开。"""

ASK_PROMPT = """材料：《{title}》{link}
{quote_part}
材料全文（markdown{cut}）：
<<<材料
{source}
材料>>>

用户的问题：{question}"""
FOLLOW_PROMPT = """（继续讨论同一份材料{quote_ref}）用户追问：{question}"""
DEFAULT_QUESTION = "解释这段：在说什么、为什么重要、有什么容易误解或需要注意的地方。"
MAX_SOURCE = 60000


def _thread(aid: int) -> dict:
    a = db.row("SELECT * FROM annotations WHERE id=?", [aid])
    if not a:
        raise HTTPException(404, "批注不存在")
    a["msgs"] = db.rows("SELECT * FROM annotation_msgs WHERE annotation_id=? ORDER BY id", [aid])
    return a


@router.get("")
def list_annotations(doc: str):
    return [_thread(a["id"]) for a in db.rows("SELECT id FROM annotations WHERE doc=? ORDER BY id", [doc])]


@router.get("/recent")
def recent(limit: int = 30):
    """最近有讨论的批注（不分材料），给知识库 / 对话 Agent 用。"""
    rows = db.rows("SELECT id FROM annotations ORDER BY updated_at DESC LIMIT ?", [limit])
    return [_thread(a["id"]) for a in rows]


class NewIn(BaseModel):
    doc: str
    title: str = ""
    link: str = ""
    quote: str = ""
    prefix: str = ""
    suffix: str = ""
    text: str = ""
    ask: bool = False        # 要 Claude 回答
    source: str = ""         # 材料全文（markdown），第一次提问时作为上下文


@router.post("")
def create(body: NewIn):
    if not body.doc.strip():
        raise HTTPException(400, "缺少 doc")
    if not body.text.strip() and not body.ask:
        raise HTTPException(400, "写点评论，或者问 Claude")
    now = db.now()
    aid = db.insert("annotations", {"doc": body.doc, "title": body.title[:200], "link": body.link, "quote": body.quote[:2000],
                                    "prefix": body.prefix[-200:], "suffix": body.suffix[:200], "created_at": now, "updated_at": now})
    _post(aid, body.text, body.ask, body.source)
    return _thread(aid)


class MsgIn(BaseModel):
    text: str = ""
    ask: bool = False
    source: str = ""


@router.post("/{aid}/msgs")
def reply(aid: int, body: MsgIn):
    a = _thread(aid)
    if not body.text.strip() and not body.ask:
        raise HTTPException(400, "内容为空")
    if any(m["status"] == "pending" for m in a["msgs"]):
        raise HTTPException(400, "Claude 还在回答上一个问题")
    _post(aid, body.text, body.ask, body.source)
    return _thread(aid)


class PatchIn(BaseModel):
    status: str


@router.patch("/{aid}")
def patch(aid: int, body: PatchIn):
    if body.status not in ("open", "resolved"):
        raise HTTPException(400, "status 只能是 open / resolved")
    _thread(aid)
    db.update("annotations", aid, {"status": body.status, "updated_at": db.now()})
    kb.schedule_sync()
    return _thread(aid)


@router.delete("/{aid}")
def delete(aid: int):
    _thread(aid)
    db.execute("DELETE FROM annotation_msgs WHERE annotation_id=?", [aid])
    db.execute("DELETE FROM annotations WHERE id=?", [aid])
    kb.schedule_sync()
    return {"ok": True}


def _post(aid: int, text: str, ask: bool, source: str) -> None:
    now = db.now()
    text = text.strip()
    if text:
        db.insert("annotation_msgs", {"annotation_id": aid, "role": "user", "content": text, "created_at": now})
    elif ask:  # 只点了「问 Claude」：记下默认问题，讨论串里看得出问了什么
        db.insert("annotation_msgs", {"annotation_id": aid, "role": "user", "content": DEFAULT_QUESTION, "created_at": now})
    db.update("annotations", aid, {"updated_at": now})
    if ask:
        mid = db.insert("annotation_msgs", {"annotation_id": aid, "role": "assistant", "status": "pending", "created_at": now})
        threading.Thread(target=_answer, args=(aid, mid, text or DEFAULT_QUESTION, source), daemon=True,
                         name=f"annotation-{aid}").start()
    kb.schedule_sync()


def _prompt(a: dict, question: str, source: str) -> str:
    if a["engine_session"]:
        return FOLLOW_PROMPT.format(quote_ref=f"，划线：「{a['quote'][:200]}」" if a["quote"] else "", question=question)
    quote_part = (f"用户划线的段落：「{a['quote']}」\n（前文：…{a['prefix'][-80:]}　后文：{a['suffix'][:80]}…）\n"
                  if a["quote"] else "用户针对全文提问。\n")
    cut = len(source) > MAX_SOURCE
    return ASK_PROMPT.format(title=a["title"] or a["doc"], link=f"（平台链接 {a['link']}）" if a["link"] else "",
                             quote_part=quote_part, cut="，太长已截断" if cut else "",
                             source=(source[:MAX_SOURCE] if source else "（没有提供全文，只根据划线和你能查到的资料回答）"),
                             question=question)


def _answer(aid: int, mid: int, question: str, source: str) -> None:
    global active
    with _lock:
        active += 1
    texts, tools, errors, session, final, status = [], [], [], "", "", "failed"
    try:
        a = db.row("SELECT * FROM annotations WHERE id=?", [aid])
        engine = settings.get("engines.default", "claude")
        for ev in agent.run_stream(_prompt(a, question, source), engine=engine, system=SYSTEM,
                                   session=a["engine_session"], add_dirs=[str(kb.KB_DIR)]):
            if ev["type"] == "session":
                session = ev["id"]
            elif ev["type"] == "text":  # 边写边存，页面轮询时能看到进度
                texts.append(ev["text"])
                db.update("annotation_msgs", mid, {"content": "\n\n".join(texts)})
            elif ev["type"] == "tool":
                tools.append(ev["text"])
                db.update("annotation_msgs", mid, {"log": "\n".join(tools[-30:])})
            elif ev["type"] == "error":
                errors.append(ev["text"])
            elif ev["type"] == "done":
                final = ev["text"]
        status = "done" if final else "failed"
    except Exception as e:  # noqa: BLE001
        log.exception("annotation %s answer failed", aid)
        errors.append(str(e))
    finally:
        content = final or "\n\n".join(texts) or "（没有得到回答：" + (errors[-1] if errors else "Claude 没有输出") + "）"
        db.update("annotation_msgs", mid, {"content": content, "status": status,
                                           "log": "\n".join(tools[-30:] + [f"[error] {x}" for x in errors[-5:]])})
        patch_ = {"updated_at": db.now()}
        if session:
            patch_["engine_session"] = session
        db.update("annotations", aid, patch_)
        kb.schedule_sync()
        with _lock:
            active -= 1
