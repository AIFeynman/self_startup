"""便签：用户自己写的灵感、感想、想法（和系统记的「问题与经验」分开），按时间线贴在墙上，可以自定义类型、互相连线、引用来源文章。

数据还在 review_notes 表（author='me'），这样知识库、搜索照常能读到，但不进概念抽取（不发给大模型）；sources 是引用的文章 JSON：
[{doc, title, link, type, quote}]，doc 和批注用的是同一套材料标识；note_links 是便签之间的关系。
"""
from __future__ import annotations

import json
import logging
import re
from urllib.parse import quote

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import db, kb, tasks
from . import review

log = logging.getLogger(__name__)
TITLE = "便签"
ORDER = 11
SCHEMA = """
CREATE TABLE IF NOT EXISTS note_links (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    a          INTEGER NOT NULL,
    b          INTEGER NOT NULL,
    rel        TEXT DEFAULT '相关',           -- 相关 / 延伸 / 来自 / 追问 / 反驳
    created_at TEXT,
    UNIQUE (a, b)
);
CREATE INDEX IF NOT EXISTS idx_note_links_b ON note_links(b);
"""
router = APIRouter()

RELS = ("相关", "延伸", "来自", "追问", "反驳")
_MAX_SOURCES = 20


def clean_sources(items: list[dict] | None) -> list[dict]:
    """只留认识的字段；链接只能是平台内（#）或 http(s)，页面上会直接放进 href。"""
    out, seen = [], set()
    for s in items or []:
        link = str(s.get("link") or "").strip()
        if link and not re.match(r"(#|https?://)", link):
            link = ""
        title = str(s.get("title") or link or s.get("doc") or "").strip()[:300]
        doc = str(s.get("doc") or "").strip()[:300]
        key = (doc or link or title, s.get("quote") or "")
        if not title or key in seen:
            continue
        seen.add(key)
        item = {"doc": doc, "title": title, "link": link, "type": str(s.get("type") or source_type(doc))[:12],
                "quote": str(s.get("quote") or "").strip()[:2000]}
        if s.get("annotation_id"):
            item["annotation_id"] = int(s["annotation_id"])
        out.append(item)
    return out[:_MAX_SOURCES]


def _full(n: dict) -> dict:
    n = dict(n)
    n["sources"] = review._loads(n.get("sources"), [])
    n["text"] = "\n".join(x for x in (n.get("title"), n.get("content")) if x)
    return n


def _get(nid: int) -> dict:
    n = db.row("SELECT * FROM review_notes WHERE id=? AND author='me'", [nid])
    if not n:
        raise HTTPException(404, "便签不存在")
    return n


def kinds() -> list[dict]:
    """内置类型 + 自己用过的类型；自定义类型不单独存，没有便签在用就自然消失。"""
    used = {r["kind"]: r["n"] for r in db.rows("SELECT kind, COUNT(*) n FROM review_notes WHERE author='me' GROUP BY kind")}
    out = [{"key": k, "label": v, "builtin": True, "count": used.pop(k, 0)} for k, v in review.KIND_LABEL.items()]
    return out + [{"key": k, "label": k, "builtin": False, "count": v} for k, v in sorted(used.items())]


@router.get("")
def wall(q: str = "", kind: str = "", limit: int = 500):
    notes = [_full(n) for n in review.list_notes(q=q, kind=kind, author="me", limit=limit)]
    links = db.rows("SELECT id, a, b, rel FROM note_links ORDER BY id")
    return {"notes": notes, "links": links, "kinds": kinds(), "rels": list(RELS)}


@router.get("/kinds")
def api_kinds():
    return kinds()


def add(text: str, kind: str = "", sources: list[dict] | None = None, date: str | None = None) -> dict:
    """贴一张便签。文字里写了前缀（问题: / 自定义类型:）以前缀为准，否则用选的类型，都没有归「灵感」。"""
    custom = [k["key"] for k in kinds() if not k["builtin"]]
    parsed = review.parse_quick_note(text, review.normalize_kind(kind), custom)
    if not parsed["title"]:
        raise HTTPException(400, "写点内容")
    now = db.now()
    nid = db.insert("review_notes", {**parsed, "date": review._day(date), "author": "me",
                                     "sources": json.dumps(clean_sources(sources), ensure_ascii=False),
                                     "created_at": now, "updated_at": now})
    return _full(db.row("SELECT * FROM review_notes WHERE id=?", [nid]))


class AddIn(BaseModel):
    text: str
    kind: str = ""
    sources: list[dict] = []
    date: str | None = None


@router.post("")
def api_add(body: AddIn):
    return add(body.text, body.kind, body.sources, body.date)


ISSUE_ASPECT = "有问题的"


class ReviewIn(BaseModel):
    entries: dict[str, list[str]]
    date: str | None = None


@router.post("/review")
def api_review(body: ReviewIn):
    filled = [(key, text.strip()) for key, texts in body.entries.items() for text in texts if text.strip()]
    if not filled:
        raise HTTPException(400, "至少填一栏")
    date = body.date or db.today()
    note = add("\n".join([f"复盘 {date[5:]}", *(f"{key}：{text}" for key, text in filled)]), "review", date=date)
    issues = [tasks.add_open(f"{key.split('·')[0]}：{review.parse_quick_note(text)['title']}", date, f"来自 {date} 的复盘")
              for key, text in filled if key.endswith(f"·{ISSUE_ASPECT}")]
    return {"note": note, "issues": [i for i in issues if i]}


class PatchIn(BaseModel):
    text: str | None = None
    kind: str | None = None
    sources: list[dict] | None = None
    author: str | None = None


@router.patch("/{nid}")
def api_patch(nid: int, body: PatchIn):
    _get(nid)
    d = {"updated_at": db.now()}
    if body.text is not None:
        lines = [ln.strip() for ln in body.text.strip().splitlines()]
        if not lines or not lines[0]:
            raise HTTPException(400, "写点内容")
        d |= {"title": lines[0], "content": "\n".join(lines[1:]).strip()}
    if body.kind is not None:
        d["kind"] = review.normalize_kind(body.kind)
    if body.sources is not None:
        d["sources"] = json.dumps(clean_sources(body.sources), ensure_ascii=False)
    if body.author == "system":  # 不是自己写的：退回「问题与经验」，类型要落回系统认识的那几种
        d["author"] = "system"
        kind = d.get("kind") or db.row("SELECT kind FROM review_notes WHERE id=?", [nid])["kind"]
        d["kind"] = kind if kind in review.NOTE_KINDS else "lesson"
        db.execute("DELETE FROM note_links WHERE a=? OR b=?", [nid, nid])
    db.update("review_notes", nid, d)
    return _full(db.row("SELECT * FROM review_notes WHERE id=?", [nid]))


@router.delete("/{nid}")
def api_delete(nid: int):
    _get(nid)
    return review.api_del_note(nid)


# ---------- 关系 ----------

class LinkIn(BaseModel):
    to: int
    rel: str = "相关"


@router.post("/{nid}/links")
def api_link(nid: int, body: LinkIn):
    _get(nid)
    _get(body.to)
    if nid == body.to:
        raise HTTPException(400, "不能连自己")
    if db.row("SELECT id FROM note_links WHERE (a=? AND b=?) OR (a=? AND b=?)", [nid, body.to, body.to, nid]):
        raise HTTPException(400, "已经连上了")
    rel = body.rel if body.rel in RELS else "相关"
    lid = db.insert("note_links", {"a": nid, "b": body.to, "rel": rel, "created_at": db.now()})
    return db.row("SELECT id, a, b, rel FROM note_links WHERE id=?", [lid])


class RelIn(BaseModel):
    rel: str


@router.patch("/links/{lid}")
def api_rel(lid: int, body: RelIn):
    if body.rel not in RELS:
        raise HTTPException(400, "关系类型不对")
    db.update("note_links", lid, {"rel": body.rel})
    return db.row("SELECT id, a, b, rel FROM note_links WHERE id=?", [lid])


@router.delete("/links/{lid}")
def api_unlink(lid: int):
    db.execute("DELETE FROM note_links WHERE id=?", [lid])
    return {"ok": True}


# ---------- 引用来源 ----------

def source_type(doc: str) -> str:
    return {"research": "调研", "research_doc": "调研", "learn": "深读", "kb": "知识库",
            "paper": "论文", "feed": "信息流", "intel": "产品雷达", "chat": "Agent 对话"}.get((doc or "").split(":", 1)[0], "链接")


def _search(table: str, cols: str, where: str, q: str, limit: int) -> list[dict]:
    if not review._has_table(table):
        return []
    return db.rows(f"SELECT {cols} FROM {table} WHERE {where} ORDER BY rowid DESC LIMIT ?",
                   [f"%{q}%"] * where.count("?") + [limit])


def _intel_sources(q: str, limit: int) -> list[dict]:
    """产品雷达：公司（名字优先，其次生意拆解卡正文）、变化事件、增长 Case。"""
    named = _search("intel_company", "id, slug, name", "name LIKE ? OR slug LIKE ? OR aliases LIKE ?", q, limit)
    mention = _search("intel_company", "id, slug, name", "id IN (SELECT company_id FROM intel_profile WHERE content LIKE ?)", q, limit)
    names = {r["id"] for r in named}
    out = [{"doc": f"intel:company:{r['slug']}", "title": r["name"], "link": f"#intel/c/{r['slug']}", "type": "产品雷达"}
           for r in named + [m for m in mention if m["id"] not in names]][:limit]
    for r in _search("intel_event", "id, title", "title LIKE ? OR summary LIKE ?", q, limit):
        out.append({"doc": f"intel:event:{r['id']}", "title": r["title"], "link": f"#intel/e/{r['id']}", "type": "产品雷达"})
    for r in _search("intel_growth_case", "id, company", "company LIKE ? OR content LIKE ?", q, limit):
        out.append({"doc": f"intel:growth:{r['id']}", "title": f"{r['company'] or '?'} · 增长 Case", "link": f"#intel/g/{r['id']}", "type": "产品雷达"})
    return out


@router.get("/sources")
def sources(q: str = "", limit: int = 5):
    """找能引用的文章：深读、调研、产品雷达、论文、信息流、知识库；贴的是链接就先看平台里有没有这篇。没写关键词时只列最近的深读和调研。"""
    q = q.strip()
    url = bool(re.match(r"https?://", q))
    out = []
    col = "url" if url else "title"
    for r in _search("learn_items", "id, title, url", f"{col} LIKE ?", q, limit):
        out.append({"doc": f"learn:item:{r['id']}", "title": r["title"] or r["url"], "link": f"#learn/item/{r['id']}", "type": "深读"})
    if not url:
        for r in _search("research_docs", "id, title", "title LIKE ?", q, limit):
            out.append({"doc": f"research_doc:{r['id']}", "title": r["title"], "link": f"#research/docs/{r['id']}", "type": "调研"})
        for r in _search("research", "id, topic", "topic LIKE ?", q, limit):
            out.append({"doc": f"research:{r['id']}:synth", "title": r["topic"], "link": f"#research/r/{r['id']}", "type": "调研"})
    if q and not url:
        out += _intel_sources(q, limit)
    if q:
        for r in _search("feed_items", "id, title, url", f"{col} LIKE ?", q, limit):
            out.append({"doc": f"feed:{r['id']}", "title": r["title"], "link": r["url"], "type": "信息流"})
        if not url:
            for r in _search("paper_items", "id, s2id, arxiv, title", "title LIKE ? AND status!='out'", q, limit):
                link = f"https://arxiv.org/abs/{r['arxiv']}" if r.get("arxiv") else f"https://www.semanticscholar.org/paper/{r['s2id']}"
                out.append({"doc": f"paper:{r['s2id']}", "title": r["title"], "link": link, "type": "论文"})
            for r in kb.search(q, limit=limit):  # 正文也搜，别的板块里见过的一句话能找回来；便签自己不算文章，要关联走连线
                if not r["path"].startswith("notes/"):
                    out.append({"doc": f"kb:{r['path']}", "title": r["title"] or r["path"], "link": f"#kb/doc/{quote(r['path'], safe='')}", "type": "知识库"})
    if url and not out:
        out.append({"doc": "", "title": q, "link": q, "type": "链接"})
    return out


# ---------- 批注进便签 ----------

def from_comment(annotation: dict, text: str, kind: str) -> dict | None:
    """评论时选了类型：同一句话贴一张便签，出处是被评论的文章和划线。便签失败不影响评论本身。"""
    try:
        return add(text, kind, [{"doc": annotation["doc"], "title": annotation["title"] or annotation["doc"], "link": annotation["link"],
                                 "type": source_type(annotation["doc"]), "quote": annotation["quote"], "annotation_id": annotation["id"]}])
    except Exception:  # noqa: BLE001
        log.exception("评论 %s 贴便签失败", annotation.get("id"))
        return None


def agent_context(ref: str) -> str:
    lines = ["用户最近的便签（用户自己写的灵感和想法）："]
    for n in review.list_notes(author="me", limit=30):
        lines.append(f"- {n['date']} [{review.KIND_LABEL.get(n['kind'], n['kind'])}] {n['title']}")
    return "\n".join(lines)
