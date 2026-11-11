"""知识库板块：检索 / 阅读 data/kb/ 下自动同步的 markdown 知识树（逻辑在 app/kb.py）。"""
import json
import subprocess
import threading
from typing import Literal

import httpx

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

import re

from .. import kb, kb_graph, kb_idea, kb_judge, kb_lens, kb_verify, kb_whynot
from . import _paper_add as paper_add, _paper_label as paper_label, _paper_maintain as paper_maintain, _paper_map as paper_map

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


@router.get("/lens")
def lens():
    return kb_lens.overview()


def agent_context(ref: str) -> str:
    if ref.startswith("think:"):
        return kb_idea.context(int(ref.split(":")[1]))
    if ref.startswith("lens:"):
        return kb_lens.context(ref.removeprefix("lens:"))
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


@router.get("/think/latest")
def think_latest():
    return kb_idea.latest()


@router.post("/think")
def think_start(body: RecheckIn):
    t = kb_idea.start(body.sid)
    if not t:
        raise HTTPException(404, "judgment not found")
    return t


class ThinkNewIn(BaseModel):
    question: str = ""
    stance: str = ""
    mode: Literal["brainstorm", "idea", "judgment"] = "judgment"
    images: list[str] = Field(default_factory=list, max_length=4)


@router.post("/think/new")
def think_new(body: ThinkNewIn):
    try:
        return kb_idea.ask(body.question, body.stance, body.mode, body.images)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/think/history")
def think_history(q: str = "", mode: Literal["", "brainstorm", "idea", "judgment"] = "", limit: int = 20, offset: int = 0):
    if not 1 <= limit <= 100 or offset < 0:
        raise HTTPException(400, "invalid pagination")
    return kb_idea.history(q, mode, limit, offset)


@router.get("/think/{tid}")
def think_get(tid: int):
    t = kb_idea.get(tid)
    if not t:
        raise HTTPException(404, "think not found")
    return t


@router.delete("/think/{tid}")
def think_delete(tid: int):
    try:
        deleted = kb_idea.delete(tid)
    except RuntimeError as e:
        raise HTTPException(409, str(e))
    if not deleted:
        raise HTTPException(404, "think not found")
    return {"ok": True}


class ThinkRecordIn(BaseModel):
    text: str
    type: str = ""
    confidence: str = ""
    due: str = ""


@router.post("/think/{tid}/record")
def think_record(tid: int, body: ThinkRecordIn):
    try:
        t = kb_idea.record(tid, body.text, body.type, body.confidence, body.due)
    except ValueError:
        raise HTTPException(400, "empty")
    if not t:
        raise HTTPException(404, "think not found")
    kb_graph.schedule_refresh()
    return {"ok": True, "sid": t["judgment"]["sid"], "think": t}


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
    """生成中返回 {running, step}；刚失败返回 {error}（只报一次）；否则返回已生成的脉络。"""
    if p := paper_map.progress(topic):
        return p
    paper_map._init()
    row = paper_map.db.row("SELECT result FROM paper_maps WHERE topic=?", [paper_map.norm(topic)])
    if not row:
        raise HTTPException(404, "还没生成过这个主题")
    return paper_map.view(json.loads(row["result"]))


PAPER_CARD = "s2id, arxiv, title, year, pub_date, venue, cites, infl, tier, tldr, abstract"


def _paper_cards(rows: list[dict]) -> list[dict]:
    read = paper_map.reads([r["s2id"] for r in rows])
    return [{"s2id": r["s2id"], "title": r["title"], "year": r["year"], "pub_date": r["pub_date"], "venue": r["venue"],
             "cites": r["cites"], "infl": r["infl"], "tier": r["tier"],
             "tldr": r["tldr"] or (r["abstract"] or "")[:300],
             "url": paper_map.paper_url(r) or f"https://www.semanticscholar.org/paper/{r['s2id']}",
             **({"read": read[r["s2id"]]} if r["s2id"] in read else {})} for r in rows]


@router.get("/papers/search")
def papers_search(q: str, limit: int = 20):
    """论文库全文检索，按被引排序；带一句话简介，已深读的带上深读条目。"""
    paper_map._init()
    ids = paper_map._fts(q.strip())
    if not ids:
        return []
    return _paper_cards(paper_map.db.rows(f"SELECT {PAPER_CARD} FROM paper_items WHERE rowid IN ({','.join('?' * len(ids))}) "
                                          "ORDER BY cites DESC LIMIT ?", [*ids, max(1, min(limit, 100))]))


@router.get("/papers/lineage")
def papers_lineage(s2id: str, limit: int = 10):
    """一篇论文在库里的前后脉络：它引用了库里哪些（builds_on），库里哪些引用了它（followed_by），都按被引排序。"""
    me = paper_map.db.row(f"SELECT {PAPER_CARD}, refs FROM paper_items WHERE s2id=?", [s2id])
    if not me:
        raise HTTPException(404, "论文库里没有这篇")
    limit = max(1, min(limit, 50))
    refs = json.loads(me["refs"] or "[]")
    before = paper_map.db.rows(f"SELECT {PAPER_CARD} FROM paper_items WHERE s2id IN ({','.join('?' * len(refs))}) "
                               "ORDER BY cites DESC LIMIT ?", [*refs, limit]) if refs else []
    after = paper_map.db.rows(f"SELECT {PAPER_CARD} FROM paper_items WHERE refs LIKE ? ORDER BY cites DESC LIMIT ?",
                              [f'%"{s2id}"%', limit])
    return {"paper": _paper_cards([me])[0], "builds_on": _paper_cards(before), "followed_by": _paper_cards(after)}


class PaperReadIn(BaseModel):
    s2ids: list[str]
    dry_run: bool = False    # 只看哪些复用、哪些要新跑，不建任务


PAPER_READ_MAX = 10          # 一次最多新开几篇深读（每篇是一个本机 Claude Code 任务，十几分钟）


@router.post("/papers/read")
def papers_read(body: PaperReadIn):
    """脉络里的论文送去深度学习板块深读：已有深读的复用，没有的新建条目（排队跑，受 Agent 并发上限约束）。"""
    from . import learn
    paper_map._init()
    ids = list(dict.fromkeys(s for s in body.s2ids if s))
    rows = {r["s2id"]: r for r in paper_map.db.rows(
        f"SELECT s2id, arxiv, title FROM paper_items WHERE s2id IN ({','.join('?' * len(ids))})", ids)} if ids else {}
    have = paper_map.reads(ids)
    reuse = [{"s2id": s, **have[s]} for s in ids if s in have]
    todo = [s for s in ids if s not in have and paper_map.paper_url(rows.get(s) or {})]
    skip = [s for s in ids if s not in have and s not in todo]       # 不在库里 / 没有 arXiv 链接，深读不了
    if body.dry_run:
        return {"reuse": reuse, "new": todo, "skip": skip}
    if len(todo) > PAPER_READ_MAX:
        raise HTTPException(400, f"一次最多新开 {PAPER_READ_MAX} 篇深读，这次要新开 {len(todo)} 篇")
    made = []
    for s in todo:
        it = learn.create_item(learn.ItemIn(url=paper_map.paper_url(rows[s]), kind="paper", reuse=True))
        if not it.get("title"):
            paper_map.db.update("learn_items", it["id"], {"title": rows[s]["title"]})   # 深度学习列表里跑完前就有标题
        made.append({"s2id": s, "id": it["id"], "status": it["status"]})
    return {"reuse": reuse, "new": made, "skip": skip}


class PaperMapIn(BaseModel):
    topic: str
    force: bool = False      # 不用缓存，重新生成


@router.post("/papers/map")
def papers_build(body: PaperMapIn):
    """有缓存直接返回；否则后台生成（改写 → 召回 → 子图选点 → 模型成线，1–3 分钟），返回 {running, step}，用 GET 轮询。"""
    topic = body.topic.strip()
    if not topic:
        raise HTTPException(400, "主题不能为空")
    if paper_label.engine() == "deepseek" and not kb_graph.has_llm():
        raise HTTPException(400, "未配置 DEEPSEEK_API_KEY")
    if not paper_map.overview()["labeled"]:
        raise HTTPException(400, "论文库还是空的：先跑采集和标注")
    if not body.force and (row := paper_map.db.row("SELECT result FROM paper_maps WHERE topic=?", [paper_map.norm(topic)])):
        return paper_map.view(json.loads(row["result"]))
    return paper_map.start(topic, body.force)


class PaperAddIn(BaseModel):
    text: str                # arXiv 编号 / 链接 / 论文标题


def _paper_errors(fn, *a):
    try:
        return fn(*a)
    except LookupError as e:
        raise HTTPException(404, str(e))
    except httpx.HTTPError as e:
        raise HTTPException(502, f"模型接口暂时不可用，稍后再试（{type(e).__name__}）")
    except (RuntimeError, subprocess.TimeoutExpired) as e:
        raise HTTPException(502, f"调用失败：{str(e)[:200]}")


@router.post("/papers/add")
def papers_add(body: PaperAddIn):
    """补一篇具体论文：不看门槛直接入库并标注，约 10–40 秒。"""
    if not body.text.strip():
        raise HTTPException(400, "填 arXiv 编号、链接或论文标题")
    return _paper_errors(paper_add.add_paper, body.text)


class PaperTopicIn(BaseModel):
    topic: str


@router.post("/papers/topic/preview")
def papers_topic_preview(body: PaperTopicIn):
    """补一个方向：改写 + S2 检索 + 按门槛预判「将新增 N 篇」，不写论文库，约 20–40 秒。"""
    if not body.topic.strip():
        raise HTTPException(400, "主题不能为空")
    return _paper_errors(paper_add.preview_topic, body.topic)


@router.post("/papers/topic/{aid}/start")
def papers_topic_start(aid: int):
    """确认预览，后台入库 → 标注 → 重新生成这个主题的脉络。"""
    if not _paper_errors(paper_add.start_topic, aid):
        raise HTTPException(409, "已有一个方向在补充，等它跑完再来")
    return paper_add.adds_view(paper_map.db.row("SELECT * FROM paper_adds WHERE id=?", [aid]))


@router.get("/papers/topic/{aid}")
def papers_topic_get(aid: int, full: bool = False):
    paper_add.init()
    a = paper_map.db.row("SELECT * FROM paper_adds WHERE id=?", [aid])
    if not a:
        raise HTTPException(404, "没有这个补充记录")
    return paper_add.adds_view(a, full)


@router.post("/papers/maintain")
def papers_maintain():
    """立即跑一次每周维护（后台，几分钟）：刷新被引 → 重判门槛 → 标注新收的和要重标 builds_on 的。"""
    if not paper_maintain.start(force=True):
        raise HTTPException(409, "维护已经在跑了")
    return {"started": True}


@router.get("/papers/adds")
def papers_adds(limit: int = 10):
    return paper_add.adds(limit)
