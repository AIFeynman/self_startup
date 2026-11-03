"""知识库板块：检索 / 阅读 data/kb/ 下自动同步的 markdown 知识树（逻辑在 app/kb.py）。"""
import threading

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from .. import kb, kb_graph

TITLE = "知识库"
ORDER = 60
router = APIRouter()


@router.get("/search")
def search(q: str = "", type: str = "", limit: int = 20):
    return kb.search(q, type, limit)


@router.get("/doc", response_class=PlainTextResponse)
def doc(path: str):
    try:
        return kb.read(path)
    except FileNotFoundError:
        raise HTTPException(404, "not found")


@router.post("/sync")
def sync():
    return kb.sync()


@router.get("/stats")
def stats():
    docs = kb.build()
    by: dict[str, int] = {}
    for d in docs:
        by[d["type"]] = by.get(d["type"], 0) + 1
    recent = sorted(docs, key=lambda d: d["updated"] or d["date"], reverse=True)[:12]
    return {"dir": str(kb.KB_DIR), "total": len(docs), "by_type": by, "names": kb.TYPE_NAMES,
            "recent": [{k: d[k] for k in ("path", "type", "title", "date", "summary")} for d in recent]}


def agent_context(ref: str) -> str:
    try:
        return (kb.read("GRAPH.md")[:4000] + "\n\n" + kb.read("INDEX.md")[:3000]).strip()
    except FileNotFoundError:
        try:
            return kb.read("INDEX.md")[:6000]
        except FileNotFoundError:
            return "知识库还没生成，可调用 POST /api/kb/sync。"


# ---------- 概念图谱（逻辑在 app/kb_graph.py） ----------

@router.get("/graph")
def graph():
    return kb_graph.graph_json()


@router.get("/concept")
def concept(name: str):
    c = kb_graph.concept_json(name)
    if not c:
        raise HTTPException(404, "not found")
    return c


@router.get("/stream")
def stream(limit: int = 60):
    return kb_graph.stream_json(limit)


@router.post("/graph/refresh")
def graph_refresh(force: bool = False):
    threading.Thread(target=kb_graph.refresh, kwargs={"force": force}, daemon=True).start()
    return kb_graph.status()


@router.get("/graph/status")
def graph_status():
    return kb_graph.status()


class ConceptEdit(BaseModel):
    op: str          # rename（目标已存在即合并）/ hide / unhide
    src: str
    dst: str = ""


@router.post("/concept/edit")
def concept_edit(body: ConceptEdit):
    try:
        kb_graph.edit(body.op, body.src, body.dst)
    except ValueError:
        raise HTTPException(400, "bad edit")
    kb.sync(refresh_graph=False)
    return {"ok": True, "name": body.dst if body.op == "rename" else body.src}


@router.get("/list")
def list_docs(type: str = "", limit: int = 200):
    """按类型列出（统计卡片点击筛选用），最新的在前。"""
    docs = [d for d in kb.build() if not type or d["type"] == type]
    docs.sort(key=lambda d: d["date"] or d["updated"] or "", reverse=True)
    return [{k: d[k] for k in ("path", "type", "title", "date", "summary")} for d in docs[:limit]]
