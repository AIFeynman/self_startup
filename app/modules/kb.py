"""知识库板块：检索 / 阅读 data/kb/ 下自动同步的 markdown 知识树（逻辑在 app/kb.py）。"""
import json
import threading

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

import re

from .. import kb, kb_graph, kb_judge, kb_verify, kb_whynot
from . import _paper_map as paper_map

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
        return (kb.read("GRAPH.md")[:4000] + "\n\n" + kb.read("INDEX.md")[:3000]
                + "\n\n我的判断台账在 JUDGMENTS.md / judgments/（问题线、复查记录）。").strip()
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


# ---------- 判断台账（逻辑在 app/kb_judge.py） ----------

@router.get("/judgments")
def judgments():
    return kb_judge.ledger_json()


class JudgmentIn(BaseModel):
    text: str
    type: str = ""          # 观点 / 预测 / 评价；空 = 让 LLM 判断
    confidence: str = ""
    due: str = ""
    note: str = ""
    sources: list = []      # 依据材料：[{sid,title,url,link,sub}]（看过的材料）/ 链接或一句话（自己指定）；空 = 没有源


@router.get("/materials")
def materials(q: str = "", limit: int = 20):
    """记判断时引用：看过的材料，按关键词筛。"""
    return kb_judge.materials(q, min(max(limit, 1), 50))


@router.post("/judgments")
def judgment_add(body: JudgmentIn):
    try:
        jid = kb_judge.add(body.text, body.type, body.confidence, body.due, body.note, body.sources)
    except ValueError:
        raise HTTPException(400, "empty")
    kb_graph.schedule_refresh()       # 归类 + Agent 评价在后台跑
    return {"ok": True, "sid": f"my:{jid}"}


class ReviewIn(BaseModel):
    sid: str
    verdict: str            # holds / revised / overturned / pending / resolved / snooze
    note: str = ""
    due: str = ""


@router.post("/judgments/review")
def judgment_review(body: ReviewIn):
    try:
        kb_judge.review(body.sid, body.verdict, body.note, body.due)
    except ValueError as e:
        raise HTTPException(400, str(e))
    kb.sync(refresh_graph=body.verdict in ("revised", "overturned") and bool(body.note.strip()))
    return {"ok": True}


class RecheckIn(BaseModel):
    sid: str


@router.post("/judgments/verify")
def judgment_verify(body: RecheckIn):
    """联网核验：派一个后台调研任务（走 jobs，完成后 on_job_done 回填）。"""
    try:
        vid = kb_verify.start(body.sid)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "id": vid}


@router.get("/judgments/verify")
def judgment_verify_get(sid: str):
    kb_verify._init()
    return kb_verify.latest().get(sid)


@router.get("/judgments/verify/{vid}/report", response_class=PlainTextResponse)
def judgment_verify_report(vid: int):
    return kb_verify.report(vid)


def on_job_done(job: dict) -> None:
    m = re.fullmatch(r"kbverify:(\d+)", job.get("ref") or "")
    if m:
        kb_verify.finish(int(m.group(1)), job)


@router.post("/judgments/recheck")
def judgment_recheck(body: RecheckIn):
    if not kb_graph.has_llm():
        raise HTTPException(400, "未配置 DEEPSEEK_API_KEY")
    r = kb_judge.recheck(body.sid, force=True)
    if r is None:
        raise HTTPException(404, "not found")
    return r


# ---------- 论文「为什么不 XX」（逻辑在 app/kb_whynot.py） ----------

@router.get("/whynot")
def whynot_list(item_id: int = 0):
    """item_id 给了 = 这篇论文下的；不给 = 判断页用的计分 + 最近的。"""
    return kb_whynot.of_item(item_id) if item_id else kb_whynot.overview()


class WhyNotIn(BaseModel):
    item_id: int
    alt: str                # 替代方案 XX
    guess: str = "说不准"    # 我猜 XX 比论文做法：更好 / 差不多 / 更差 / 说不准
    confidence: str = ""
    reason: str = ""


@router.post("/whynot")
def whynot_add(body: WhyNotIn):
    if not kb_graph.has_llm():
        raise HTTPException(400, "未配置 DEEPSEEK_API_KEY")
    try:
        wid = kb_whynot.add(body.item_id, body.alt, body.guess, body.confidence, body.reason)
    except ValueError as e:
        raise HTTPException(400, str(e))
    kb_graph.schedule_refresh()       # 同时进了判断台账：归类 + Agent 评价在后台跑
    return {"ok": True, "id": wid}


@router.post("/whynot/{wid}/recheck")
def whynot_recheck(wid: int, layer: str = ""):
    if not kb_graph.has_llm():
        raise HTTPException(400, "未配置 DEEPSEEK_API_KEY")
    kb_whynot._init()
    if not kb_whynot.db.row("SELECT 1 FROM kb_whynot WHERE id=?", [wid]):
        raise HTTPException(404, "not found")
    kb_whynot.start_check(wid, (layer,) if layer in ("paper", "followup") else ("paper", "followup"))
    return {"ok": True}


# ---------- 论文脉络（逻辑在 app/modules/_paper_map.py） ----------

@router.get("/papers")
def papers_overview():
    return paper_map.overview()


@router.get("/papers/map")
def papers_map(topic: str):
    paper_map._init()
    row = paper_map.db.row("SELECT result FROM paper_maps WHERE topic=?", [paper_map.norm(topic)])
    if not row:
        raise HTTPException(404, "还没生成过这个主题")
    return paper_map.view(json.loads(row["result"]))


class PaperMapIn(BaseModel):
    topic: str
    force: bool = False      # 不用缓存，重新生成


@router.post("/papers/map")
def papers_build(body: PaperMapIn):
    """约 20 秒、$0.004：改写 → 召回 → 子图选点 → 模型成线。"""
    topic = body.topic.strip()
    if not topic:
        raise HTTPException(400, "主题不能为空")
    if not kb_graph.has_llm():
        raise HTTPException(400, "未配置 DEEPSEEK_API_KEY")
    if not paper_map.overview()["labeled"]:
        raise HTTPException(400, "论文库还是空的：先跑采集和标注")
    try:
        return paper_map.view(paper_map.build(topic, use_cache=not body.force))
    except httpx.HTTPError as e:
        raise HTTPException(502, f"模型接口暂时不可用，稍后再试（{e.response.status_code if isinstance(e, httpx.HTTPStatusError) else type(e).__name__}）")
