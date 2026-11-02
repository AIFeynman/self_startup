"""产品雷达：跟踪大公司 / 明星 AI native 公司的产品与商业变化，分级后为 B 级及以上的事件出「五层解读卡」。

链路（P1）：采集（官方 changelog / 定价页快照 diff + 专属 RSS + 认领信息推荐里的官方 blog / X / GitHub）
→ 识别（实体链接 → DeepSeek 分类 + 跨源去重 → 代码规则分级）→ 解读（后台 Claude 任务写解读卡，校验 6 节齐全）。
名单见 _intel_watch.py，快照 / diff 见 _intel_snap.py，分类 / 分级 / 解读卡见 _intel_events.py。
设计稿：docs/designs/2026-11-01-product-intel-design.md。
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from hashlib import sha1

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import db, jobs, settings
from . import _intel_events as ev
from . import _intel_snap as snap
from . import _intel_watch as watch

log = logging.getLogger(__name__)

TITLE = "产品雷达"
ORDER = 35
SCHEMA = """
CREATE TABLE IF NOT EXISTS intel_company (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    slug        TEXT UNIQUE NOT NULL,
    name        TEXT NOT NULL,
    tier        INTEGER DEFAULT 2,           -- 1 大公司 / 头部模型厂，2 明星 AI native，3 观察中
    category    TEXT DEFAULT '',
    aliases     TEXT DEFAULT '[]',           -- 产品名 / 别名：第三方条目按它认公司
    domains     TEXT DEFAULT '[]',           -- 官方域名：信息推荐里这些域名的博客算官方
    x           TEXT DEFAULT '[]',           -- 官方 X 账号
    github      TEXT DEFAULT '[]',           -- 官方 GitHub 组织
    feed_urls   TEXT DEFAULT '[]',           -- 信息推荐里属于这家公司的 RSS（镜像源域名对不上时用）
    enabled     INTEGER DEFAULT 1,
    note        TEXT DEFAULT '',
    created_at  TEXT,
    updated_at  TEXT
);
CREATE TABLE IF NOT EXISTS intel_source (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id  INTEGER NOT NULL,
    kind        TEXT NOT NULL,               -- changelog / pricing / docs / rss
    label       TEXT DEFAULT '',
    url         TEXT UNIQUE NOT NULL,
    product     TEXT DEFAULT '',
    every_hours REAL DEFAULT 6,
    enabled     INTEGER DEFAULT 1,
    note        TEXT DEFAULT '',
    last_fetch  TEXT,
    last_ok     TEXT,
    last_err    TEXT DEFAULT '',
    last_hash   TEXT DEFAULT '',
    last_chars  INTEGER DEFAULT 0,
    created_at  TEXT
);
CREATE TABLE IF NOT EXISTS intel_snapshot (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id   INTEGER NOT NULL,
    fetched_at  TEXT,
    hash        TEXT,
    chars       INTEGER,
    path        TEXT,                        -- data/intel/snapshots/<source_id>/<时间>.txt
    structure   TEXT DEFAULT '{}',           -- 定价页的结构化结果
    changes     INTEGER DEFAULT 0            -- 这一版产生了几个候选
);
CREATE INDEX IF NOT EXISTS idx_intel_snapshot_src ON intel_snapshot(source_id, id);
CREATE TABLE IF NOT EXISTS intel_candidate (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id   INTEGER NOT NULL,
    origin       TEXT NOT NULL,              -- snapshot / rss / feed
    origin_key   TEXT UNIQUE NOT NULL,       -- 去重键：同一条只收一次
    official     INTEGER DEFAULT 1,
    source_label TEXT DEFAULT '',
    type_hint    TEXT DEFAULT '',            -- 定价页来的固定是 pricing
    product      TEXT DEFAULT '',
    title        TEXT DEFAULT '',
    text         TEXT DEFAULT '',
    url          TEXT DEFAULT '',
    date         TEXT DEFAULT '',
    found_at     TEXT,
    status       TEXT DEFAULT 'pending',     -- pending / event / merged / ignored
    event_id     INTEGER,
    note         TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_intel_cand_status ON intel_candidate(status, company_id);
CREATE TABLE IF NOT EXISTS intel_event (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id   INTEGER NOT NULL,
    product      TEXT DEFAULT '',
    type         TEXT DEFAULT 'other',
    title        TEXT NOT NULL,
    summary      TEXT DEFAULT '',
    date         TEXT DEFAULT '',
    scale        TEXT DEFAULT 'normal',
    level_auto   TEXT DEFAULT 'C',
    level        TEXT DEFAULT 'C',            -- 人工升降级后和 level_auto 不同（记 intel_level_log）
    sources      TEXT DEFAULT '[]',           -- [{label, url, date, official}]
    card_status  TEXT DEFAULT '',             -- '' / queued / done / incomplete / failed / skipped
    merged_into  INTEGER,                     -- 去重复查判定和另一个事件是同一件事：来源已并过去，列表里不再出现
    card_job_id  INTEGER,
    card_requested_at TEXT,
    created_at   TEXT,
    updated_at   TEXT
);
CREATE INDEX IF NOT EXISTS idx_intel_event_date ON intel_event(date);
CREATE TABLE IF NOT EXISTS intel_analysis (    -- 只追加：重新生成也是新的一行
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id    INTEGER NOT NULL,
    kind        TEXT DEFAULT 'card',
    content     TEXT DEFAULT '',
    sections    TEXT DEFAULT '{}',
    missing     TEXT DEFAULT '[]',
    complete    INTEGER DEFAULT 0,
    job_id      INTEGER,
    created_at  TEXT
);
CREATE TABLE IF NOT EXISTS intel_level_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id    INTEGER NOT NULL,
    old         TEXT, new TEXT, reason TEXT DEFAULT '', at TEXT
);
CREATE TABLE IF NOT EXISTS intel_state (key TEXT PRIMARY KEY, value TEXT);
"""

SNAP_DIR = db.DATA_DIR / "intel" / "snapshots"
CFG_DEFAULTS = {
    "cards_per_day": 20,       # 每天最多自动出几张解读卡（手动「重新生成」不算）
    "card_days": 7,            # 只给最近这么多天的事件自动出卡
    "feed_lookback_days": 3,   # 首次认领信息推荐条目时往回看几天
    "cycle_minutes": 10,       # 后台多久跑一轮
    "max_age_days": 21,        # 发布日期早于这么多天的候选直接忽略（旧文被重新收录、页面重排冒出的老条目）
}
_lock = threading.Lock()


def cfg(key: str):
    return settings.get(f"intel.{key}", CFG_DEFAULTS.get(key))


def _j(v, default):
    if isinstance(v, (list, dict)):
        return v
    try:
        return json.loads(v) if v else default
    except (TypeError, ValueError):
        return default


def _state(key: str, default=None):
    r = db.row("SELECT value FROM intel_state WHERE key=?", [key])
    return _j(r["value"], default) if r else default


def _set_state(key: str, value) -> None:
    db.execute("INSERT INTO intel_state(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
               [key, json.dumps(value, ensure_ascii=False)])


COMPANY_JSON = ("aliases", "domains", "x", "github", "feed_urls")


def _company(r: dict) -> dict:
    return {**r, **{k: _j(r.get(k), []) for k in COMPANY_JSON}}


def _event(r: dict) -> dict:
    return {**r, "sources": _j(r.get("sources"), [])}


# ---------- 名单 ----------

def seed() -> int:
    """把默认名单里库中没有的公司 / 信息源补进去；已有的不动（用户可能改过）。返回新增数。"""
    n = 0
    for c in watch.COMPANIES:
        row = db.row("SELECT id FROM intel_company WHERE slug=?", [c["slug"]])
        if row:
            cid = row["id"]
        else:
            cid = db.insert("intel_company", {**{k: c.get(k, []) for k in COMPANY_JSON}, "slug": c["slug"], "name": c["name"],
                                              "tier": c["tier"], "category": c.get("category", ""), "created_at": db.now(),
                                              "updated_at": db.now()})
            n += 1
        for s in c.get("sources") or []:
            if db.row("SELECT 1 FROM intel_source WHERE url=?", [s["url"]]):
                continue
            db.insert("intel_source", {"company_id": cid, "kind": s["kind"], "label": s.get("label", ""), "url": s["url"],
                                       "product": s.get("product", ""), "every_hours": watch.EVERY_HOURS.get(s["kind"], 6),
                                       "note": s.get("note", ""), "created_at": db.now()})
            n += 1
    return n


def companies(enabled_only: bool = True) -> list[dict]:
    sql = "SELECT * FROM intel_company" + (" WHERE enabled=1" if enabled_only else "") + " ORDER BY tier, id"
    return [_company(r) for r in db.rows(sql)]


# ---------- 采集：快照 ----------

def _add_candidate(company_id: int, origin: str, key: str, **f) -> int | None:
    if db.row("SELECT 1 FROM intel_candidate WHERE origin_key=?", [key]):
        return None
    if f.get("date") and f["date"] > db.today():  # 正文里的「优惠截至 12 月 31 日」不是发布日期；新出现的就算今天
        f["date"] = db.today()
    return db.insert("intel_candidate", {"company_id": company_id, "origin": origin, "origin_key": key, "found_at": db.now(),
                                         "status": "pending", **f})


def _last_snapshot(sid: int) -> dict | None:
    return db.row("SELECT * FROM intel_snapshot WHERE source_id=? ORDER BY id DESC LIMIT 1", [sid])


def _save_snapshot(sid: int, text: str, h: str, structure: dict | None, changes: int) -> None:
    d = SNAP_DIR / str(sid)
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{datetime.now().strftime('%Y%m%d-%H%M%S')}.txt"
    p.write_text(text, "utf-8")
    db.insert("intel_snapshot", {"source_id": sid, "fetched_at": db.now(), "hash": h, "chars": len(text),
                                 "path": str(p.relative_to(db.DATA_DIR)), "structure": structure or {}, "changes": changes})


def _old_text(last: dict | None) -> str:
    if not last or not last.get("path"):
        return ""
    try:
        return (db.DATA_DIR / last["path"]).read_text("utf-8")
    except OSError:
        return ""


def process_page(src: dict, status: int, ctype: str, body: str) -> dict:
    """一个信息源抓回来的内容 → 快照 + 候选。和抓取分开，测试直接喂内容。"""
    sid, label = src["id"], src.get("label") or src["url"]
    base = {"source_label": f"{label}", "product": src.get("product", ""), "official": 1}
    if status >= 400:
        db.update("intel_source", sid, {"last_fetch": db.now(), "last_err": f"HTTP {status}"})
        return {"ok": False, "error": f"HTTP {status}"}
    if src["kind"] == "rss":
        items = snap.rss_entries(body, src["url"])
        new = 0
        for it in items:
            if _add_candidate(src["company_id"], "rss", f"rss:{sid}:{it['id']}", title=it["title"], text=it.get("summary", ""),
                              url=it["url"], date=(it.get("date") or db.now())[:10], **base):
                new += 1
        db.update("intel_source", sid, {"last_fetch": db.now(), "last_ok": db.now(), "last_err": "" if items or body else "空 feed",
                                        "last_hash": snap.text_hash(body), "last_chars": len(body)})
        return {"ok": True, "candidates": new}
    text = snap.extract_text(body, ctype, src["url"])
    h = snap.text_hash(text)
    upd = {"last_fetch": db.now(), "last_chars": len(text)}
    if len(text) < 200:
        db.update("intel_source", sid, {**upd, "last_err": f"正文只有 {len(text)} 字（页面可能靠 JS 渲染，需浏览器 / 人工）"})
        return {"ok": False, "error": "正文太短"}
    if h == src.get("last_hash"):
        db.update("intel_source", sid, {**upd, "last_ok": db.now(), "last_err": ""})
        return {"ok": True, "unchanged": True, "candidates": 0}
    last = _last_snapshot(sid)
    old = _old_text(last)
    new, structure = 0, None
    if src["kind"] == "pricing":
        try:
            structure, changes = snap.pricing_diff(_j((last or {}).get("structure"), {}), old, text)
        except Exception as e:  # noqa: BLE001 —— 不存这一版，下轮重试，定价变化不能丢
            db.update("intel_source", sid, {**upd, "last_err": f"定价结构化失败：{type(e).__name__}: {str(e)[:160]}"})
            return {"ok": False, "error": "定价结构化失败"}
        for ch in changes:
            key = f"snap:{sid}:{sha1((ch['title'] + ch.get('summary', '')).encode()).hexdigest()[:16]}"
            if _add_candidate(src["company_id"], "snapshot", key, title=ch["title"],
                              text=f"{ch.get('summary', '')}\n（定价页规模判断：{ch.get('scale', 'normal')}）", url=src["url"],
                              date=db.today(), type_hint="pricing", **base):
                new += 1
    elif src["kind"] == "changelog":
        blocks = [e for b in snap.added_blocks(old, text) for e in snap.split_entries(b)] if old else snap.recent_entries(text)
        for b in blocks[:30]:  # 一次改版冒出几十块多半是页面重排，只收前 30 块，其余靠分类去噪
            key = f"snap:{sid}:{sha1(b.encode()).hexdigest()[:16]}"
            if _add_candidate(src["company_id"], "snapshot", key, title=snap.entry_title(b), text=b[:snap.BLOCK_MAX],
                              url=src["url"], date=snap.find_date(b) or db.today(), **base):
                new += 1
    _save_snapshot(sid, text, h, structure, new)
    db.update("intel_source", sid, {**upd, "last_ok": db.now(), "last_err": "", "last_hash": h})
    return {"ok": True, "candidates": new, "first": not old}


def fetch_source(src: dict) -> dict:
    try:
        status, ctype, body = snap.fetch(src["url"])
    except Exception as e:  # noqa: BLE001
        db.update("intel_source", src["id"], {"last_fetch": db.now(), "last_err": f"{type(e).__name__}: {str(e)[:160]}"})
        return {"ok": False, "error": type(e).__name__}
    return process_page(src, status, ctype, body)


def due_sources(force: bool = False) -> list[dict]:
    rows = db.rows("SELECT s.* FROM intel_source s JOIN intel_company c ON c.id=s.company_id WHERE s.enabled=1 AND c.enabled=1")
    if force:
        return rows
    now = datetime.now()
    out = []
    for s in rows:
        try:
            last = datetime.fromisoformat(s["last_fetch"]) if s.get("last_fetch") else None
        except ValueError:
            last = None
        if not last or now - last >= timedelta(hours=float(s.get("every_hours") or 6)):
            out.append(s)
    return out


# ---------- 采集：认领信息推荐里的官方条目 ----------

def scan_feed() -> int:
    """信息推荐新收的条目里，属于关注公司的官方 blog / X / GitHub → 候选；HN 高分 / 第三方新闻 → 第三方候选（只并入）。"""
    if not ev_has_table("feed_items"):
        return 0
    cursor = _state("feed_cursor") or (datetime.now() - timedelta(days=float(cfg("feed_lookback_days")))).isoformat(timespec="seconds")
    rows = db.rows("SELECT * FROM feed_items WHERE fetched_at > ? ORDER BY fetched_at", [cursor])
    cos = companies()
    n = 0
    for r in rows:
        it = {**r, "extra": _j(r.get("extra"), {})}
        if (it.get("date") or "9999")[:10] < _stale_before():
            continue
        c, official = ev.match_feed_item(it, cos)
        if not c:
            continue
        label = {"twitter": "X", "github": "GitHub", "blog": "博客", "hn": "HN", "producthunt": "Product Hunt"}.get(it["source"], it["source"])
        if it["source"] == "twitter":
            label = f"X @{it['extra'].get('author', '')}"
        elif it["source"] == "blog":
            label = it["extra"].get("feed") or ev.host(it["url"])
        if _add_candidate(c["id"], "feed", f"feed:{it['id']}", official=int(official), source_label=label, title=it["title"],
                          text=it.get("summary") or "", url=it.get("url") or "", date=(it.get("date") or it["fetched_at"] or "")[:10]):
            n += 1
    if rows:
        _set_state("feed_cursor", rows[-1]["fetched_at"])
    return n


def _stale_before() -> str:
    return (datetime.now() - timedelta(days=float(cfg("max_age_days")))).strftime("%Y-%m-%d")


def ev_has_table(name: str) -> bool:
    return bool(db.row("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", [name]))


# ---------- 识别：分类、去重、分级 ----------

def _create_event(company: dict, cand: dict, x: dict) -> int:
    type_ = cand.get("type_hint") or (x.get("type") if x.get("type") in ev.TYPES else "other")
    scale = x.get("scale") if x.get("scale") in ("major", "normal", "minor") else "normal"
    level = ev.auto_level(type_, scale, int(company["tier"]))
    return db.insert("intel_event", {
        "company_id": company["id"], "product": x.get("product") or cand.get("product") or "", "type": type_,
        "title": (x.get("title") or cand["title"])[:120], "summary": (x.get("summary") or "")[:400],
        "date": cand.get("date") or db.today(), "scale": scale, "level_auto": level, "level": level,
        "sources": [_src_of(cand)], "card_status": "", "created_at": db.now(), "updated_at": db.now()})


def _src_of(cand: dict) -> dict:
    return {"label": cand.get("source_label", ""), "url": cand.get("url", ""), "date": cand.get("date", ""),
            "official": bool(cand.get("official")), "title": cand.get("title", "")[:160]}


def _merge(event_id: int, cand: dict, x: dict | None = None) -> None:
    e = db.row("SELECT * FROM intel_event WHERE id=?", [event_id])
    if not e:
        return
    upd = {"sources": ev.merge_sources(_j(e["sources"], []), _src_of(cand)), "updated_at": db.now()}
    # 更早的官方日期覆盖事件日期（同一发布：changelog 当天、博客隔天）
    if cand.get("official") and cand.get("date") and cand["date"] < (e.get("date") or "9999"):
        upd["date"] = cand["date"]
    db.update("intel_event", event_id, upd)
    db.update("intel_candidate", cand["id"], {"status": "merged", "event_id": event_id})


def classify_pending(limit_per_company: int = 60) -> dict:
    out = {"events": 0, "merged": 0, "ignored": 0, "errors": []}
    cos = {c["id"]: c for c in companies()}
    for cid, company in cos.items():
        cands = db.rows("SELECT * FROM intel_candidate WHERE company_id=? AND status='pending' ORDER BY official DESC, id LIMIT ?",
                        [cid, limit_per_company])
        if not cands:
            continue
        since = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        events = [_event(e) for e in db.rows("SELECT * FROM intel_event WHERE company_id=? AND date>=? AND merged_into IS NULL "
                                             "ORDER BY date DESC", [cid, since])]
        # 确定性去重：链接已经在某个事件的来源里
        by_url = {s["url"]: e["id"] for e in events for s in e["sources"] if s.get("url")}
        rest = []
        for c in cands:
            if (c.get("date") or "9999") < _stale_before():
                db.update("intel_candidate", c["id"], {"status": "ignored", "note": "发布日期太早，不是新变化"})
                out["ignored"] += 1
            elif c.get("url") and c["url"] in by_url and c.get("origin") == "feed":
                _merge(by_url[c["url"]], c)
                out["merged"] += 1
            else:
                rest.append(c)
        if not rest:
            continue
        res, errs = ev.classify(company, events, rest)
        out["errors"] += errs
        made: dict[int, int] = {}  # candidate id → event id（本轮新建的）
        for c in rest:
            x = res.get(c["id"])
            if x is None:
                continue  # 这批调用失败，留待下轮
            if not x.get("is_change"):
                db.update("intel_candidate", c["id"], {"status": "ignored", "note": "不是产品 / 商业变化"})
                out["ignored"] += 1
                continue
            target = str(x.get("merge_into") or "")
            eid = None
            if target.startswith("e") and target[1:].isdigit():
                eid = int(target[1:]) if any(e["id"] == int(target[1:]) for e in events) else None
            elif target.startswith("c") and target[1:].isdigit():
                eid = made.get(int(target[1:]))
            if eid:
                _merge(eid, c, x)
                out["merged"] += 1
                continue
            if not c.get("official"):
                db.update("intel_candidate", c["id"], {"status": "ignored", "note": "第三方来源，没有对应的官方事件"})
                out["ignored"] += 1
                continue
            eid = _create_event(company, c, x)
            made[c["id"]] = eid
            db.update("intel_candidate", c["id"], {"status": "event", "event_id": eid})
            out["events"] += 1
        if made:
            m = dedup_pass(company, list(made.values()), events)
            out["merged"] += m
            out["events"] -= m
    return out


def dedup_pass(company: dict, new_ids: list[int], recent: list[dict]) -> int:
    """分类时同批的两条官方源（博客 + X）偶尔没认出是同一件事：本轮新建的事件再和近 7 天事件对一遍，同一件事并成一个。"""
    news = [_event(e) for e in db.rows(f"SELECT * FROM intel_event WHERE id IN ({','.join('?' * len(new_ids))})", new_ids)]
    pool = {e["id"]: e for e in [*recent, *news]}
    if len(pool) < 2:
        return 0
    payload = {"company": company["name"], "new": [f"e{i}" for i in new_ids],
               "events": [{"id": f"e{e['id']}", "title": e["title"], "summary": (e.get("summary") or "")[:160], "product": e.get("product", ""),
                           "date": e.get("date", "")} for e in pool.values()]}
    try:
        groups = snap.llm_json(ev.DEDUP_SYSTEM, payload, max_tokens=2000).get("groups") or []
    except Exception as e:  # noqa: BLE001 —— 复查失败不影响已建的事件
        log.warning("intel dedup failed: %s", e)
        return 0
    n = 0
    for g in groups:
        ids = sorted({int(str(x)[1:]) for x in g if str(x)[1:].isdigit() and int(str(x)[1:]) in pool})
        if len(ids) < 2 or not any(i in new_ids for i in ids):
            continue
        keep = next((i for i in ids if i not in new_ids), ids[0])  # 优先留已有的（可能已经出了解读卡）
        for i in ids:
            if i == keep or i not in new_ids:
                continue
            k = _event(db.row("SELECT * FROM intel_event WHERE id=?", [keep]))
            d = pool[i]
            srcs = k["sources"]
            for s in d["sources"]:
                srcs = ev.merge_sources(srcs, s)
            upd = {"sources": srcs, "updated_at": db.now()}
            if d.get("date") and d["date"] < (k.get("date") or "9999"):
                upd["date"] = d["date"]
            if ev.LEVELS.index(d["level"]) < ev.LEVELS.index(k["level"]) and k["level"] == k["level_auto"]:
                upd["level"] = upd["level_auto"] = d["level"]  # 取更高的自动级别；人工改过的不动
            db.update("intel_event", keep, upd)
            db.update("intel_event", i, {"merged_into": keep, "updated_at": db.now()})
            db.execute("UPDATE intel_candidate SET event_id=?, status='merged' WHERE event_id=?", [keep, i])
            n += 1
    return n


# ---------- 解读卡 ----------

def _cards_today() -> int:
    return (db.row("SELECT count(*) AS n FROM intel_event WHERE card_requested_at >= ? AND card_requested_at IS NOT NULL",
                   [db.today()]) or {}).get("n", 0)


def request_card(event_id: int) -> int:
    e = db.row("SELECT * FROM intel_event WHERE id=?", [event_id])
    if not e:
        raise HTTPException(404, "事件不存在")
    e = _event(e)
    company = _company(db.row("SELECT * FROM intel_company WHERE id=?", [e["company_id"]]))
    timeline = db.rows("SELECT id, date, level, title FROM intel_event WHERE company_id=? AND merged_into IS NULL ORDER BY date DESC LIMIT 15", [e["company_id"]])
    jid = jobs.submit("intel", ev.card_prompt(e, company, timeline), ref=f"intel:event:{event_id}:card", tier="standard")
    db.update("intel_event", event_id, {"card_status": "queued", "card_job_id": jid, "card_requested_at": db.now()})
    return jid


def queue_cards() -> int:
    left = int(cfg("cards_per_day")) - _cards_today()
    if left <= 0:
        return 0
    since = (datetime.now() - timedelta(days=float(cfg("card_days")))).strftime("%Y-%m-%d")
    rows = db.rows("SELECT id FROM intel_event WHERE card_status='' AND merged_into IS NULL AND level IN ('S','A','B') AND date>=? "
                   "ORDER BY CASE level WHEN 'S' THEN 0 WHEN 'A' THEN 1 ELSE 2 END, date DESC LIMIT ?", [since, left])
    for r in rows:
        request_card(r["id"])
    return len(rows)


def on_job_done(job: dict) -> None:
    import re
    m = re.fullmatch(r"intel:event:(\d+):card", job.get("ref") or "")
    if not m:
        return
    eid = int(m[1])
    if job.get("status") != "done":
        db.update("intel_event", eid, {"card_status": "failed" if job.get("status") == "failed" else job.get("status") or "failed"})
        return
    q = ev.card_quality(job.get("output") or "")
    db.insert("intel_analysis", {"event_id": eid, "kind": "card", "content": job.get("output") or "", "sections": q["sections"],
                                 "missing": q["missing"], "complete": int(q["complete"]), "job_id": job["id"], "created_at": db.now()})
    db.update("intel_event", eid, {"card_status": "done" if q["complete"] else "incomplete", "updated_at": db.now()})


# ---------- 调度 ----------

def run_cycle(force_fetch: bool = False, cards: bool = True) -> dict:
    """一轮：到期的快照 → 认领信息推荐条目 → 分类 → 解读卡。同一时间只跑一轮。"""
    if not _lock.acquire(blocking=False):
        return {"skipped": "上一轮还在跑"}
    t0 = time.time()
    try:
        seed()
        srcs = due_sources(force_fetch)
        with ThreadPoolExecutor(max_workers=6) as ex:
            fetched = list(ex.map(fetch_source, srcs))
        res = {"fetched": len(srcs), "fetch_errors": sum(1 for f in fetched if not f.get("ok")),
               "snapshot_candidates": sum(f.get("candidates", 0) for f in fetched), "feed_candidates": scan_feed()}
        res.update(classify_pending())
        res["cards"] = queue_cards() if cards else 0
        res["at"], res["seconds"] = db.now(), round(time.time() - t0, 1)
        _set_state("last_run", res)
        return res
    finally:
        _lock.release()


def _bg(**kw) -> bool:
    if _lock.locked():
        return False
    threading.Thread(target=lambda: _safe_cycle(**kw), daemon=True, name="intel-run").start()
    return True


def _safe_cycle(**kw):
    try:
        run_cycle(**kw)
    except Exception:  # noqa: BLE001
        log.exception("intel cycle failed")


def _loop():
    time.sleep(120)  # 等信息推荐先起来
    while True:
        _safe_cycle()
        time.sleep(float(cfg("cycle_minutes") or 10) * 60)


def on_startup():
    try:
        seed()
    except Exception:  # noqa: BLE001
        log.exception("intel seed failed")
    if os.environ.get("SELF_STARTUP_NO_AUTOREFRESH"):
        return
    threading.Thread(target=_loop, daemon=True, name="intel-loop").start()


# ---------- 接口 ----------

router = APIRouter()


def _with_card(e: dict, full: bool = False) -> dict:
    a = db.row("SELECT * FROM intel_analysis WHERE event_id=? ORDER BY id DESC LIMIT 1", [e["id"]])
    e = _event(e)
    if a:
        e["card"] = {"id": a["id"], "complete": bool(a["complete"]), "missing": _j(a["missing"], []), "created_at": a["created_at"],
                     "content": a["content"] if full else None}
    return e


@router.get("/events")
def list_events(level: str = "", company: str = "", days: float = 30, q: str = "", limit: int = 100):
    sql = ("SELECT e.*, c.name AS company_name, c.slug AS company_slug, c.tier AS company_tier FROM intel_event e "
           "JOIN intel_company c ON c.id=e.company_id WHERE e.date >= ? AND e.merged_into IS NULL")
    args: list = [(datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d") if days else "0000"]
    if level:
        lv = [x for x in level.upper().split(",") if x in ev.LEVELS]
        sql += f" AND e.level IN ({','.join('?' * len(lv))})"
        args += lv
    if company:
        sql += " AND c.slug=?"
        args.append(company)
    if q:
        sql += " AND (e.title LIKE ? OR e.summary LIKE ? OR e.product LIKE ?)"
        args += [f"%{q}%"] * 3
    sql += " ORDER BY e.date DESC, CASE e.level WHEN 'S' THEN 0 WHEN 'A' THEN 1 WHEN 'B' THEN 2 ELSE 3 END, e.id DESC LIMIT ?"
    rows = [_with_card(r) for r in db.rows(sql, [*args, limit])]
    counts = {r["level"]: r["n"] for r in db.rows("SELECT level, count(*) AS n FROM intel_event WHERE date >= ? AND merged_into IS NULL GROUP BY level", args[:1])}
    return {"events": rows, "counts": counts, "types": ev.TYPES}


@router.get("/events/{eid}")
def get_event(eid: int):
    e = db.row("SELECT e.*, c.name AS company_name, c.slug AS company_slug, c.tier AS company_tier FROM intel_event e "
               "JOIN intel_company c ON c.id=e.company_id WHERE e.id=?", [eid])
    if not e:
        raise HTTPException(404, "事件不存在")
    out = _with_card(e, full=True)
    out["candidates"] = db.rows("SELECT id, origin, official, source_label, title, url, date, status FROM intel_candidate WHERE event_id=? "
                                "ORDER BY id", [eid])
    out["level_log"] = db.rows("SELECT * FROM intel_level_log WHERE event_id=? ORDER BY id", [eid])
    out["versions"] = db.rows("SELECT id, complete, created_at, job_id FROM intel_analysis WHERE event_id=? ORDER BY id DESC", [eid])
    return out


class LevelIn(BaseModel):
    level: str
    reason: str = ""


@router.post("/events/{eid}/level")
def set_level(eid: int, body: LevelIn):
    e = db.row("SELECT * FROM intel_event WHERE id=?", [eid])
    lv = body.level.upper()
    if not e or lv not in ev.LEVELS:
        raise HTTPException(400, "事件不存在或级别不对（S/A/B/C）")
    if lv != e["level"]:
        db.insert("intel_level_log", {"event_id": eid, "old": e["level"], "new": lv, "reason": body.reason, "at": db.now()})
        db.update("intel_event", eid, {"level": lv, "updated_at": db.now()})
        if ev.needs_card(lv) and e["card_status"] in ("", "skipped"):
            request_card(eid)
    return get_event(eid)


@router.post("/events/{eid}/card")
def regen_card(eid: int):
    return {"job_id": request_card(eid)}


@router.get("/companies")
def list_companies():
    out = []
    for c in companies(enabled_only=False):
        n = db.row("SELECT count(*) AS n, max(date) AS latest FROM intel_event WHERE company_id=? AND merged_into IS NULL", [c["id"]]) or {}
        out.append({**c, "events": n.get("n", 0), "latest": n.get("latest") or "",
                    "sources": db.rows("SELECT id, kind, label, url, enabled, last_ok, last_err FROM intel_source WHERE company_id=?", [c["id"]])})
    return out


@router.get("/companies/{slug}")
def get_company(slug: str):
    r = db.row("SELECT * FROM intel_company WHERE slug=?", [slug])
    if not r:
        raise HTTPException(404, "公司不存在")
    c = _company(r)
    c["events"] = [_with_card(e) for e in db.rows("SELECT * FROM intel_event WHERE company_id=? AND merged_into IS NULL ORDER BY date DESC, id DESC LIMIT 200", [c["id"]])]
    c["sources"] = db.rows("SELECT * FROM intel_source WHERE company_id=? ORDER BY id", [c["id"]])
    c["experiences"] = []  # D1：调研板块里记过的一手产品体验
    if ev_has_table("products"):
        for a in [c["name"], *c["aliases"]][:12]:
            c["experiences"] += [p for p in db.rows("SELECT id, name, rating, used_at FROM products WHERE name LIKE ?", [f"%{a}%"])
                                 if p["id"] not in {x["id"] for x in c["experiences"]}]
    return c


class CompanyIn(BaseModel):
    name: str
    slug: str = ""
    tier: int = 3
    category: str = ""
    aliases: list[str] = []
    domains: list[str] = []
    x: list[str] = []
    github: list[str] = []
    feed_urls: list[str] = []


@router.post("/companies")
def add_company(body: CompanyIn):
    import re
    slug = body.slug or re.sub(r"[^a-z0-9]+", "-", body.name.lower()).strip("-") or f"co-{int(time.time())}"
    if db.row("SELECT 1 FROM intel_company WHERE slug=?", [slug]):
        raise HTTPException(409, "已经在名单里了")
    cid = db.insert("intel_company", {**body.model_dump(exclude={"slug"}), "slug": slug, "aliases": body.aliases or [body.name],
                                      "created_at": db.now(), "updated_at": db.now()})
    return {"id": cid, "slug": slug}


@router.patch("/companies/{cid}")
def patch_company(cid: int, body: dict):
    allowed = {k: v for k, v in body.items() if k in ("name", "tier", "category", "enabled", "note", *COMPANY_JSON)}
    db.update("intel_company", cid, {**allowed, "updated_at": db.now()})
    return _company(db.row("SELECT * FROM intel_company WHERE id=?", [cid]) or {})


class SourceIn(BaseModel):
    company_id: int
    kind: str = "changelog"
    url: str
    label: str = ""
    product: str = ""


@router.get("/sources")
def list_sources():
    return db.rows("SELECT s.*, c.name AS company_name, c.slug AS company_slug, c.enabled AS company_enabled, "
                   "(SELECT count(*) FROM intel_snapshot WHERE source_id=s.id) AS snapshots, "
                   "(SELECT count(*) FROM intel_candidate WHERE origin_key LIKE 'snap:' || s.id || ':%' "
                   " OR origin_key LIKE 'rss:' || s.id || ':%') AS candidates "
                   "FROM intel_source s JOIN intel_company c ON c.id=s.company_id ORDER BY c.tier, c.id, s.id")


@router.post("/sources")
def add_source(body: SourceIn):
    if body.kind not in watch.EVERY_HOURS:
        raise HTTPException(400, f"kind 只能是 {', '.join(watch.EVERY_HOURS)}")
    if db.row("SELECT 1 FROM intel_source WHERE url=?", [body.url]):
        raise HTTPException(409, "这个链接已经在跟了")
    sid = db.insert("intel_source", {**body.model_dump(), "every_hours": watch.EVERY_HOURS[body.kind], "created_at": db.now()})
    return {"id": sid}


@router.patch("/sources/{sid}")
def patch_source(sid: int, body: dict):
    allowed = {k: v for k, v in body.items() if k in ("label", "url", "product", "kind", "every_hours", "enabled", "note")}
    db.update("intel_source", sid, allowed)
    return db.row("SELECT * FROM intel_source WHERE id=?", [sid])


@router.post("/sources/{sid}/fetch")
def fetch_now(sid: int):
    s = db.row("SELECT * FROM intel_source WHERE id=?", [sid])
    if not s:
        raise HTTPException(404, "信息源不存在")
    r = fetch_source(s)
    return {**r, "source": db.row("SELECT * FROM intel_source WHERE id=?", [sid])}


class RunIn(BaseModel):
    force_fetch: bool = False
    cards: bool = True


@router.post("/run")
def run(body: RunIn | None = None):
    body = body or RunIn()
    return {"started": _bg(force_fetch=body.force_fetch, cards=body.cards)}


@router.get("/status")
def status():
    pend = db.row("SELECT count(*) AS n FROM intel_candidate WHERE status='pending'") or {}
    bad = db.rows("SELECT s.id, s.label, s.url, s.last_err, c.name AS company_name FROM intel_source s JOIN intel_company c ON c.id=s.company_id "
                  "WHERE s.enabled=1 AND s.last_err != ''")
    return {"running": _lock.locked(), "last_run": _state("last_run"), "pending_candidates": pend.get("n", 0),
            "companies": (db.row("SELECT count(*) AS n FROM intel_company WHERE enabled=1") or {}).get("n", 0),
            "sources": (db.row("SELECT count(*) AS n FROM intel_source WHERE enabled=1") or {}).get("n", 0),
            "events": (db.row("SELECT count(*) AS n FROM intel_event WHERE merged_into IS NULL") or {}).get("n", 0),
            "cards_today": _cards_today(), "cards_per_day": cfg("cards_per_day"), "failing_sources": bad,
            "deepseek": bool(os.environ.get("DEEPSEEK_API_KEY"))}


# ---------- Agent ----------

def agent_context(ref: str) -> str:
    since = (datetime.now() - timedelta(days=14)).strftime("%Y-%m-%d")
    rows = db.rows("SELECT e.*, c.name AS cn FROM intel_event e JOIN intel_company c ON c.id=e.company_id WHERE e.date>=? "
                   "AND e.level IN ('S','A','B') AND e.merged_into IS NULL ORDER BY e.date DESC LIMIT 60", [since])
    lines = [f"产品雷达：跟踪 {status()['companies']} 家公司；近 14 天 B 级及以上事件 {len(rows)} 条。"
             "接口：GET /api/intel/events?level=S,A&company=<slug>、GET /api/intel/events/<id>（含解读卡全文）、GET /api/intel/companies/<slug>（时间线）。",
             "", "## 近 14 天 B+ 事件（日期 | 级别 | 公司 | 标题 | 解读卡）"]
    for r in rows:
        lines.append(f"- {r['date']} | {r['level']} | {r['cn']} | [{r['id']}] {r['title']} | {r['card_status'] or '-'}")
    return "\n".join(lines)
