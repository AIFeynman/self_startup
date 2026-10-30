"""信息推荐：从 learn_evolve（只读）+ HN/HF/AlphaXiv/GitHub/RSS/Reddit 收集 AI 相关内容，按热度/新鲜度/兴趣/反馈排序。

不做逐条提炼：只展示标题 + 简介 + 链接 + 「为什么推荐」。排序逻辑见 _feed_rank.py，采集见 _feed_sources.py。
"""
from __future__ import annotations

import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import db, settings
from . import _feed_rank as rk
from . import _feed_sources as src

log = logging.getLogger(__name__)

TITLE = "信息推荐"
ORDER = 30
SCHEMA = """
CREATE TABLE IF NOT EXISTS feed_items (
    id          TEXT PRIMARY KEY,          -- source:external_id，稳定去重键
    source      TEXT NOT NULL,             -- hn / hf / arxiv / github / blog / reddit / producthunt / twitter ...
    type        TEXT NOT NULL,             -- paper / blog / product / repo / discussion / news
    title       TEXT NOT NULL,
    summary     TEXT DEFAULT '',           -- ≤400 字
    url         TEXT DEFAULT '',
    date        TEXT DEFAULT '',
    popularity  REAL DEFAULT 0,            -- 来源热度：points / stars / likes / upvotes
    extra       TEXT DEFAULT '{}',
    fetched_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_feed_items_fetched ON feed_items(fetched_at);
CREATE TABLE IF NOT EXISTS feed_feedback (
    item_id     TEXT PRIMARY KEY,
    vote        INTEGER DEFAULT 0,         -- 1 赞 / -1 踩 / 0 无
    saved       INTEGER DEFAULT 0,
    hidden      INTEGER DEFAULT 0,
    updated_at  TEXT
);
"""

# settings.feed 之外的旋钮的缺省值（可在 data/settings.json 的 feed 下覆盖）
CFG_DEFAULTS = {
    "half_life_hours": 72,
    "learn_evolve_days": 30,
    "hn_queries": ["LLM", "AI agent", "Claude", "OpenAI", "GPT", "coding agent"],
    "github_queries": ["llm", "ai agent", "mcp", "claude code"],
    "reddit": ["LocalLLaMA", "ClaudeAI", "MachineLearning"],
    "sources": ["learn_evolve", "hn", "hf", "alphaxiv", "github", "rss", "reddit"],
}
TYPES = {"paper": "论文", "blog": "博客", "product": "产品", "repo": "项目", "discussion": "讨论", "news": "资讯"}

router = APIRouter()
_state: dict = {"running": False, "started_at": "", "finished_at": "", "results": {}}
_state_lock = threading.Lock()


def cfg(key: str):
    v = settings.get(f"feed.{key}")
    return CFG_DEFAULTS.get(key) if v is None else v


# ---------- 存储 ----------

def upsert(items: list[dict]) -> int:
    """写入/合并：新值非空才覆盖；extra 合并（保留 learn_evolve 评分等）。"""
    n = 0
    ts = db.now()
    for it in items:
        if not it.get("id") or not it.get("title"):
            continue
        old = db.row("SELECT * FROM feed_items WHERE id=?", [it["id"]])
        extra = dict(it.get("extra") or {})
        if old:
            merged = {**_extra(old), **{k: v for k, v in extra.items() if v not in ("", None, [], {})}}
            db.execute("UPDATE feed_items SET source=?, type=?, title=?, summary=?, url=?, date=?, popularity=?, extra=?, "
                       "fetched_at=? WHERE id=?",
                       [it["source"], it["type"], it["title"], it.get("summary") or old["summary"],
                        it.get("url") or old["url"], it.get("date") or old["date"],
                        max(float(it.get("popularity") or 0), float(old["popularity"] or 0))
                        if it["source"] == old["source"] else float(it.get("popularity") or 0),
                        json.dumps(merged, ensure_ascii=False), ts, it["id"]])
        else:
            db.insert("feed_items", {"id": it["id"], "source": it["source"], "type": it["type"], "title": it["title"],
                                     "summary": it.get("summary") or "", "url": it.get("url") or "",
                                     "date": it.get("date") or "", "popularity": float(it.get("popularity") or 0),
                                     "extra": extra, "fetched_at": ts})
        n += 1
    return n


def _extra(r: dict) -> dict:
    try:
        return json.loads(r.get("extra") or "{}") if isinstance(r.get("extra"), str) else (r.get("extra") or {})
    except ValueError:
        return {}


def _load_items(limit: int = 5000) -> list[dict]:
    rows = db.rows("SELECT * FROM feed_items ORDER BY fetched_at DESC LIMIT ?", [limit])
    for r in rows:
        r["extra"] = _extra(r)
    return rows


def _feedback() -> dict[str, dict]:
    return {r["item_id"]: {"vote": r["vote"], "saved": r["saved"], "hidden": r["hidden"]}
            for r in db.rows("SELECT * FROM feed_feedback")}


def _examples(items: list[dict], fb: dict[str, dict]) -> list[dict]:
    """亲和度样本：本平台的赞/收藏（+）与踩（-），以及 learn_evolve 的 star/good（+）与 bad（-）。"""
    ex = []
    for it in items:
        f = fb.get(it["id"], {})
        pol = 1 if (f.get("vote", 0) > 0 or f.get("saved")) else (-1 if f.get("vote", 0) < 0 else 0)
        if not pol:
            pol = {"star": 1, "good": 1, "bad": -1}.get(it["extra"].get("le_rating", ""), 0)
        if pol:
            ex.append({"id": it["id"], "title": it["title"], "summary": it.get("summary", ""), "source": it["source"], "polarity": pol})
    return ex


def ranked(type_: str = "", saved: bool = False, q: str = "", now: datetime | None = None) -> list[dict]:
    items = _load_items()
    fb = _feedback()
    out = rk.rank(items, now=now or datetime.now(timezone.utc), half_life_h=float(cfg("half_life_hours")),
                  interests=list(cfg("interests") or []), feedback=fb, examples=_examples(items, fb),
                  include_hidden=saved)
    if saved:
        out = [x for x in out if x["feedback"].get("saved")]
    if type_:
        out = [x for x in out if x["type"] == type_]
    if q:
        ql = q.lower()
        out = [x for x in out if ql in f"{x['title']} {x['summary']}".lower()]
    return out


# ---------- 采集 ----------

def _collectors() -> dict:
    fc = settings.get("feed", {}) or {}
    return {
        "learn_evolve": lambda: src.fetch_learn_evolve(fc.get("learn_evolve_db", ""), int(cfg("learn_evolve_days"))),
        "hn": lambda: src.fetch_hn(list(cfg("hn_queries"))),
        "hf": lambda: src.fetch_hf_papers(),
        "alphaxiv": lambda: src.fetch_alphaxiv(),
        "github": lambda: src.fetch_github(list(cfg("github_queries"))),
        "rss": lambda: src.fetch_rss(list(fc.get("rss") or [])),
        "reddit": lambda: src.fetch_reddit(list(cfg("reddit"))),
    }


def refresh_sync(only: list[str] | None = None) -> dict:
    """跑一遍采集；每个来源独立 fail-soft。返回 {source: {count, errors}}。"""
    cols = _collectors()
    names = [n for n in (only or cfg("sources")) if n in cols]
    results: dict = {}

    def run(name):
        try:
            got = cols[name]()
            items, errs = got if isinstance(got, tuple) else (got, [])
            return name, {"count": upsert(items), "errors": errs}
        except Exception as e:  # noqa: BLE001
            log.warning("feed source %s failed: %s", name, e)
            return name, {"count": 0, "errors": [f"{type(e).__name__}: {str(e)[:200]}"]}

    with ThreadPoolExecutor(max_workers=4) as ex:
        for name, res in ex.map(run, names):
            results[name] = res
    return results


def _bg(only):
    try:
        res = refresh_sync(only)
    except Exception as e:  # noqa: BLE001
        res = {"_": {"count": 0, "errors": [str(e)]}}
    with _state_lock:
        _state.update(running=False, finished_at=db.now(), results=res)


class RefreshIn(BaseModel):
    sources: list[str] = []      # 空 = 全部
    wait: bool = False           # true = 同步等结果（CLI / Agent 用）


@router.post("/refresh")
def refresh(body: RefreshIn | None = None):
    body = body or RefreshIn()
    if body.wait:
        res = refresh_sync(body.sources or None)
        with _state_lock:
            _state.update(finished_at=db.now(), results=res)
        return status()
    with _state_lock:
        if not _state["running"]:
            _state.update(running=True, started_at=db.now(), results={})
            threading.Thread(target=_bg, args=(body.sources or None,), daemon=True).start()
    return status()


@router.get("/status")
def status():
    with _state_lock:
        st = json.loads(json.dumps(_state))
    st["total"] = (db.row("SELECT count(*) n FROM feed_items") or {}).get("n", 0)
    st["by_source"] = {r["source"]: r["n"] for r in db.rows("SELECT source, count(*) n FROM feed_items GROUP BY source")}
    st["last_fetched"] = (db.row("SELECT max(fetched_at) t FROM feed_items") or {}).get("t") or ""
    st["feedback"] = feedback_stats()
    return st


# ---------- 列表与反馈 ----------

def _public(x: dict) -> dict:
    return {k: x[k] for k in ("id", "source", "type", "title", "summary", "url", "date", "popularity", "score",
                              "why", "feedback", "also")} | {"extra": x.get("extra", {}),
                                                              "source_label": rk.SOURCE_LABEL.get(x["source"], x["source"])}


@router.get("/items")
def items(type: str = "", saved: bool = False, q: str = "", limit: int = 60, offset: int = 0):
    out = ranked(type, saved, q)
    return {"total": len(out), "items": [_public(x) for x in out[offset: offset + limit]]}


class FeedbackIn(BaseModel):
    id: str
    vote: int | None = None      # 1 / -1 / 0
    saved: bool | None = None
    hidden: bool | None = None


@router.post("/feedback")
def feedback(body: FeedbackIn):
    if not db.row("SELECT id FROM feed_items WHERE id=?", [body.id]):
        raise HTTPException(404, "条目不存在")
    cur = db.row("SELECT * FROM feed_feedback WHERE item_id=?", [body.id]) or {"vote": 0, "saved": 0, "hidden": 0}
    new = {"vote": max(-1, min(1, body.vote)) if body.vote is not None else cur["vote"],
           "saved": int(body.saved) if body.saved is not None else cur["saved"],
           "hidden": int(body.hidden) if body.hidden is not None else cur["hidden"]}
    db.execute("INSERT INTO feed_feedback (item_id, vote, saved, hidden, updated_at) VALUES (?,?,?,?,?) "
               "ON CONFLICT(item_id) DO UPDATE SET vote=excluded.vote, saved=excluded.saved, hidden=excluded.hidden, "
               "updated_at=excluded.updated_at", [body.id, new["vote"], new["saved"], new["hidden"], db.now()])
    return {"id": body.id, **new}


def feedback_stats() -> dict:
    r = db.row("SELECT sum(vote>0) likes, sum(vote<0) dislikes, sum(saved) saved, sum(hidden) hidden FROM feed_feedback") or {}
    return {k: int(r.get(k) or 0) for k in ("likes", "dislikes", "saved", "hidden")}


@router.get("/config")
def config():
    return {k: cfg(k) for k in ("interests", "half_life_hours", "learn_evolve_days", "hn_queries", "github_queries",
                                "reddit", "sources")} | {"rss": settings.get("feed.rss", []), "types": TYPES}


# ---------- Agent ----------

def agent_context(ref: str) -> str:
    top = ranked()[:30]
    lines = [f"兴趣词：{', '.join(cfg('interests') or [])}",
             f"反馈统计：{json.dumps(feedback_stats(), ensure_ascii=False)}；库内共 {status()['total']} 条",
             "", "## 当前排序前 30（标题 | 类型 | 推荐理由 | 链接 | 简介）"]
    for i, x in enumerate(top, 1):
        lines.append(f"{i}. [{x['id']}] {x['title']} | {TYPES.get(x['type'], x['type'])} | {x['why'] or '-'} | "
                     f"{x['url']} | {src.clean(x['summary'], 120)}")
    return "\n".join(lines)
