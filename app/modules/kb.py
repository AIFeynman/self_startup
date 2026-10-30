"""知识库板块：检索 / 阅读 data/kb/ 下自动同步的 markdown 知识树（逻辑在 app/kb.py）。"""
from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse

from .. import kb

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
        return kb.read("INDEX.md")[:6000]
    except FileNotFoundError:
        return "知识库还没生成，可调用 POST /api/kb/sync。"
