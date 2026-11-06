"""已读记录（只追加）：打开过的信息推荐条目、产品雷达事件、增长 Case，每打开一次记一行，按天进复盘。

标题和链接存快照，原条目被清理后历史还在。建表时把已有的点击记录（feed_feedback.clicks）补进来。
"""
from __future__ import annotations

from .. import db
from ._feed_rank import SOURCE_LABEL, norm_url

_ready = False


def _ensure() -> None:
    global _ready
    if _ready:
        return
    if not db.row("SELECT 1 FROM sqlite_master WHERE type='table' AND name='read_log'"):
        db.execute("CREATE TABLE read_log (id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, ref TEXT NOT NULL, "
                   "title TEXT DEFAULT '', url TEXT DEFAULT '', source TEXT DEFAULT '', at TEXT NOT NULL)")
        db.execute("CREATE INDEX idx_read_log_ref ON read_log(kind, ref)")
        db.execute("CREATE INDEX idx_read_log_at ON read_log(at)")
        _import_feed_clicks()
    _ready = True


def _import_feed_clicks() -> None:
    if "clicks" not in {r["name"] for r in db.rows("PRAGMA table_info(feed_feedback)")}:
        return
    for r in db.rows("SELECT f.item_id, f.last_click, f.updated_at, i.title, i.url, i.source FROM feed_feedback f "
                     "JOIN feed_items i ON i.id=f.item_id WHERE f.clicks>0"):
        db.insert("read_log", {"kind": "feed", "ref": r["item_id"], "title": r["title"], "url": r["url"],
                               "source": SOURCE_LABEL.get(r["source"], r["source"]), "at": r["last_click"] or r["updated_at"] or db.now()})


def log(kind: str, ref: str, title: str, url: str, source: str) -> None:
    _ensure()
    db.insert("read_log", {"kind": kind, "ref": str(ref), "title": title, "url": url, "source": source, "at": db.now()})


def has(kind: str, ref) -> bool:
    _ensure()
    return bool(db.row("SELECT 1 FROM read_log WHERE kind=? AND ref=? LIMIT 1", [kind, str(ref)]))


def urls(kind: str) -> set[str]:
    _ensure()
    return {norm_url(r["url"]) for r in db.rows("SELECT DISTINCT url FROM read_log WHERE kind=?", [kind])} - {""}


def refs(kind: str) -> set[str]:
    _ensure()
    return {r["ref"] for r in db.rows("SELECT DISTINCT ref FROM read_log WHERE kind=?", [kind])}


def days(start: str, end: str) -> list[dict]:
    """按天分组（新的在前）；同一天重复打开同一条合成一行，times 是打开次数。"""
    _ensure()
    rows = db.rows("SELECT substr(at,1,10) date, kind, ref, title, url, source, max(at) at, count(*) times FROM read_log "
                   "WHERE substr(at,1,10) BETWEEN ? AND ? GROUP BY date, kind, ref ORDER BY date DESC, at DESC", [start, end])
    out: dict[str, list[dict]] = {}
    for r in rows:
        out.setdefault(r["date"], []).append(r)
    return [{"date": d, "items": items} for d, items in out.items()]


def day(date: str) -> list[dict]:
    found = days(date, date)
    return found[0]["items"] if found else []
