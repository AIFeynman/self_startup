"""产品雷达：跟踪大公司 / 明星 AI native 公司的产品与商业变化，分级后为 B 级及以上的事件出「五层解读卡」。

链路（P1）：采集（官方 changelog / 定价页快照 diff + 专属 RSS + 认领信息推荐里的官方 blog / X / GitHub）
→ 识别（实体链接 → DeepSeek 分类 + 跨源去重 → 代码规则分级）→ 解读（后台 Claude 任务写解读卡，校验 6 节齐全）。
名单见 _intel_watch.py，快照 / diff 见 _intel_snap.py，分类 / 分级 / 解读卡见 _intel_events.py。
设计稿：docs/designs/2026-11-01-product-intel-design.md。

P2 创业公司（kind=startup）：TrustMRR 每日收入快照 → intel_metric → 收入异动事件；16 个赛道归类；生意拆解卡；
Product Hunt 日榜解读；新闻里的公开 ARR（reported，和 verified 分开）。纯函数见 _intel_startup.py，
设计稿：docs/designs/2026-11-01-startup-intel-design.md。

每日增长 Case：增长类 RSS + X 名单账号 → DeepSeek 打分 → 每天挑 1 条 → 后台 Claude 写「增长 Case 卡」。
纯函数见 _intel_growth.py，设计稿：docs/designs/2026-11-02-growth-case-daily-design.md。
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from hashlib import sha1

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import db, jobs, settings
from . import _intel_events as ev
from . import _intel_growth as gr
from . import _intel_snap as snap
from . import _intel_startup as st
from . import _intel_watch as watch
from . import _read_log
from . import _oss_radar as oss

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
CREATE TABLE IF NOT EXISTS intel_metric (      -- 只追加：每天每个指标一行
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id  INTEGER NOT NULL,
    date        TEXT NOT NULL,
    metric      TEXT NOT NULL,               -- mrr / revenue_30d / growth_30d / growth_mrr_30d / total_revenue / subscriptions / asking_price / on_sale / arr
    value       REAL NOT NULL,
    grade       TEXT DEFAULT 'verified',     -- verified：支付渠道验证（TrustMRR）；reported：公开报道 / 公司自述
    source      TEXT DEFAULT 'trustmrr',     -- trustmrr 或报道链接
    note        TEXT DEFAULT '',
    created_at  TEXT,
    UNIQUE(company_id, date, metric, source)
);
CREATE INDEX IF NOT EXISTS idx_intel_metric_co ON intel_metric(company_id, metric, date);
CREATE TABLE IF NOT EXISTS intel_profile (     -- 生意拆解卡，只追加
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id  INTEGER NOT NULL,
    content     TEXT DEFAULT '',
    sections    TEXT DEFAULT '{}',
    missing     TEXT DEFAULT '[]',
    complete    INTEGER DEFAULT 0,
    inputs_hash TEXT DEFAULT '',
    job_id      INTEGER,
    created_at  TEXT
);
CREATE TABLE IF NOT EXISTS intel_ph_day (      -- Product Hunt 每日 AI 榜 + 解读
    date        TEXT PRIMARY KEY,
    items       TEXT DEFAULT '[]',           -- [{id, rank, name, title, url, votes, comments, track, why}]
    summary     TEXT DEFAULT '',
    created_at  TEXT
);
CREATE TABLE IF NOT EXISTS intel_growth_item (  -- 增长 Case 候选池：每条素材收一次、打一次分
    id          TEXT PRIMARY KEY,            -- growth:<hash> / twitter:<id>
    source      TEXT DEFAULT '',
    tier        TEXT DEFAULT 'B',
    title       TEXT DEFAULT '',
    summary     TEXT DEFAULT '',
    url         TEXT DEFAULT '',
    date        TEXT DEFAULT '',
    company     TEXT DEFAULT '',
    one_line    TEXT DEFAULT '',
    scores      TEXT DEFAULT '{}',           -- {case, numbers, actions, fit, firsthand}，各 0–3
    total       INTEGER DEFAULT 0,
    status      TEXT DEFAULT 'new',          -- new 待打分 / scored / picked 出过卡
    found_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_intel_growth_item ON intel_growth_item(status, total);
CREATE TABLE IF NOT EXISTS intel_growth_case (  -- 增长 Case 卡，只追加：重写也是新的一行
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id     TEXT NOT NULL,
    day         TEXT NOT NULL,               -- 哪一天的 Case
    auto        INTEGER DEFAULT 1,           -- 1 每日自动选的；0 手动选 / 重写
    company     TEXT DEFAULT '',
    status      TEXT DEFAULT 'queued',       -- queued / done / incomplete / failed
    content     TEXT DEFAULT '',
    sections    TEXT DEFAULT '{}',
    missing     TEXT DEFAULT '[]',
    complete    INTEGER DEFAULT 0,
    job_id      INTEGER,
    created_at  TEXT,
    updated_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_intel_growth_case ON intel_growth_case(day);
""" + oss.SCHEMA

SNAP_DIR = db.DATA_DIR / "intel" / "snapshots"
CFG_DEFAULTS = {
    "cards_per_day": 20,       # 每天最多自动出几张解读卡（手动「重新生成」不算）
    "card_days": 7,            # 只给最近这么多天的事件自动出卡
    "feed_lookback_days": 3,   # 首次认领信息推荐条目时往回看几天
    "cycle_minutes": 10,       # 后台多久跑一轮
    "max_age_days": 21,        # 发布日期早于这么多天的候选直接忽略（旧文被重新收录、页面重排冒出的老条目）
    "startups": True,          # TrustMRR 每日快照 / 赛道 / 拆解卡 / PH 日榜 / 公开 ARR
    "details_per_day": 120,    # 每天最多读几个 TrustMRR 详情页（补渠道、定价、分类；总览的打法汇总靠它）
    "profiles_per_day": 10,    # 每天最多自动写几张生意拆解卡（手动不算）
    "profile_days": 30,        # 同一家多少天内不重复自动写
    "ph_top": 20,              # PH 日榜取前几名
    "tracks_per_round": 1500,  # 每轮最多归几家赛道（30 家一批、6 批并发）
    "growth": True,            # 每日增长 Case
    "growth_collect_hours": 12,  # 增长素材多久采一次（X 名单每次每个账号约 $0.001）
    "growth_score_per_round": 120,  # 每轮最多给几条素材打分（20 条一批）
    "growth_repeat_days": 90,
    "growth_daily_max": 5, "growth_extra_min": 13, "growth_extra_days": 7,  # 同一家公司多少天内不重复出 Case
    "growth_x_accounts": gr.X_ACCOUNTS,
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
    return {**r, **{k: _j(r.get(k), []) for k in (*COMPANY_JSON, "tracks")}, "ext": _j(r.get("ext"), {})}


_migrated = False


def _migrate() -> None:
    """P2 加的列（老库迁移）。kind：lab 大公司 / native 明星 AI native / startup TrustMRR 等来源的创业公司。"""
    global _migrated
    if _migrated:
        return
    cols = {r["name"] for r in db.rows("PRAGMA table_info(intel_company)")}
    for k, t in {"kind": "TEXT DEFAULT 'lab'", "track": "TEXT DEFAULT ''", "tracks": "TEXT DEFAULT '[]'",
                 "track_manual": "INTEGER DEFAULT 0", "ai": "INTEGER DEFAULT 1",  # 1 是 AI 产品 / 0 不是（不再记指标）/ -1 待判断
                 "watch": "INTEGER DEFAULT 0", "ext": "TEXT DEFAULT '{}'", "profile_status": "TEXT DEFAULT ''",
                 "profile_requested_at": "TEXT"}.items():
        if k not in cols:
            db.execute(f"ALTER TABLE intel_company ADD COLUMN {k} {t}")
            if k == "kind":
                db.execute("UPDATE intel_company SET kind='native' WHERE tier>1")
    if "ext_key" not in {r["name"] for r in db.rows("PRAGMA table_info(intel_event)")}:
        db.execute("ALTER TABLE intel_event ADD COLUMN ext_key TEXT DEFAULT ''")  # 收入事件的去重键（里程碑 / 月度暴涨…）
    if "fetch_via" not in {r["name"] for r in db.rows("PRAGMA table_info(intel_source)")}:
        db.execute("ALTER TABLE intel_source ADD COLUMN fetch_via TEXT DEFAULT ''")  # jina = 直连不行，固定走 Jina Reader
    db.execute("CREATE INDEX IF NOT EXISTS idx_intel_company_kind ON intel_company(kind, ai)")
    _migrated = True


def _event(r: dict) -> dict:
    return {**r, "sources": _j(r.get("sources"), [])}


# ---------- 名单 ----------

def seed() -> int:
    """把默认名单里库中没有的公司 / 信息源补进去；已有的不动（用户可能改过）。返回新增数。"""
    _migrate()
    n = 0
    for c in watch.COMPANIES:
        row = db.row("SELECT id FROM intel_company WHERE slug=?", [c["slug"]])
        if row:
            cid = row["id"]
        else:
            cid = db.insert("intel_company", {**{k: c.get(k, []) for k in COMPANY_JSON}, "slug": c["slug"], "name": c["name"],
                                              "tier": c["tier"], "category": c.get("category", ""), "created_at": db.now(),
                                              "kind": "lab" if c["tier"] == 1 else "native",
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
    """产品名单（大公司 + AI native）；创业公司走 startups()，不参与信息推荐认领。"""
    _migrate()
    sql = "SELECT * FROM intel_company WHERE kind != 'startup'" + (" AND enabled=1" if enabled_only else "") + " ORDER BY tier, id"
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


def process_page(src: dict, status: int, ctype: str, body: str, rebase: bool = False) -> dict:
    """一个信息源抓回来的内容 → 快照 + 候选。和抓取分开，测试直接喂内容。rebase：换了抓法，这版当首次快照，不和旧版 diff。"""
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
    last = None if rebase else _last_snapshot(sid)
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


def _fetch_error(src: dict, e: Exception) -> dict:
    db.update("intel_source", src["id"], {"last_fetch": db.now(), "last_err": f"{type(e).__name__}: {str(e)[:160]}"})
    return {"ok": False, "error": type(e).__name__}


def _jina_usable(src: dict, status: int, ctype: str, body: str) -> bool:
    """Jina 也可能只拿回站点外壳（Gemini 定价页就只有一段欢迎横幅），这种不算抓到。"""
    if status >= 400:
        return False
    text = snap.extract_text(body, ctype, src["url"])
    return len(text) >= 200 and (src["kind"] != "pricing" or bool(snap.PRICE_RE.search(text)))


def _switch_to_jina(src: dict) -> dict | None:
    """直连不行时改走 Jina，以后这个源固定走 Jina：两种抓法的正文写法不同，来回切会把整页当新增。None = Jina 也不行。"""
    try:
        status, ctype, body = snap.jina_fetch(src["url"])
    except Exception:  # noqa: BLE001 —— 记直连的错误，下轮再试
        return None
    if not _jina_usable(src, status, ctype, body):
        return None
    r = process_page(src, status, ctype, body, rebase=True)
    if r.get("ok"):
        db.update("intel_source", src["id"], {"fetch_via": "jina"})
    return r


def fetch_source(src: dict) -> dict:
    if src.get("fetch_via") == "jina":
        try:
            return process_page(src, *snap.jina_fetch(src["url"]))
        except Exception as e:  # noqa: BLE001
            return _fetch_error(src, e)
    can_switch = src["kind"] != "rss"  # Jina 返回的是 markdown，解析不了 feed
    try:
        status, ctype, body = snap.fetch_retry(src["url"])
    except Exception as e:  # noqa: BLE001
        # 成功过的源连不上多半是网络抖动，不换抓法；从没成功过的（如证书一直不过）才换
        r = _switch_to_jina(src) if can_switch and not src.get("last_ok") else None
        return r or _fetch_error(src, e)
    if can_switch and (status in snap.BLOCKED_STATUS or (status < 400 and len(snap.extract_text(body, ctype, src["url"])) < 200)):
        r = _switch_to_jina(src)
        if r:
            return r
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
    if re.fullmatch(r"intel:company:\d+:profile(:\w+)?", job.get("ref") or ""):
        return on_profile_done(job)
    if re.fullmatch(r"intel:growth:\d+", job.get("ref") or ""):
        return on_growth_done(job)
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



# ---------- P2 创业公司：TrustMRR 每日快照 → 指标 → 收入异动 ----------

def _ext_patch(cid: int, patch: dict) -> dict:
    r = db.row("SELECT ext FROM intel_company WHERE id=?", [cid]) or {}
    ext = {**_j(r.get("ext"), {}), **patch}
    db.update("intel_company", cid, {"ext": ext, "updated_at": db.now()})
    return ext


def _upsert_startup(slug: str, o: dict) -> dict:
    """TrustMRR 对象 → intel_company（kind=startup）。slug 和产品名单撞了就加 tm- 前缀。"""
    r = db.row("SELECT * FROM intel_company WHERE kind='startup' AND json_extract(ext, '$.trustmrr')=?", [slug])
    if r:
        c = _company(r)
        if (o.get("description") and not c["ext"].get("description")) or c["name"] != o.get("name", c["name"]):
            _ext_patch(c["id"], {"description": (o.get("description") or "")[:1200], "intro_zh": ""} if o.get("description") else {})
        return c
    s = slug if not db.row("SELECT 1 FROM intel_company WHERE slug=?", [slug]) else f"tm-{slug}"
    cid = db.insert("intel_company", {"slug": s, "name": (o.get("name") or slug)[:120], "tier": 3, "kind": "startup",
                                      "ai": 1 if o.get("_ai_hint") else -1, "aliases": [], "domains": [], "x": [], "github": [],
                                      "feed_urls": [], "ext": {"trustmrr": slug, "description": (o.get("description") or "")[:1200],
                                                               **({"category": o["userCategory"]} if o.get("userCategory") else {})},
                                      "created_at": db.now(), "updated_at": db.now()})
    return _company(db.row("SELECT * FROM intel_company WHERE id=?", [cid]))


def _write_metrics(cid: int, day: str, m: dict, grade: str = "verified", source: str = "trustmrr", note: str = "") -> int:
    """只追加：同一天同一口径同一来源已有就跳过（不覆盖历史）。返回新写入的条数。"""
    n = 0
    for k, v in m.items():
        if db.row("SELECT 1 FROM intel_metric WHERE company_id=? AND date=? AND metric=? AND source=?", [cid, day, k, source]):
            continue
        db.execute("INSERT OR IGNORE INTO intel_metric(company_id, date, metric, value, grade, source, note, created_at) "
                   "VALUES(?,?,?,?,?,?,?,?)", [cid, day, k, float(v), grade, source, note, db.now()])
        n += 1
    return n


def metric_series(cid: int, grade: str = "verified", since: str = "0000") -> list[dict]:
    """按日期透视：[{date, mrr, revenue_30d, growth_30d, ...}]（只取 grade 这一种口径）。"""
    by: dict[str, dict] = {}
    for r in db.rows("SELECT date, metric, value FROM intel_metric WHERE company_id=? AND grade=? AND date>=? ORDER BY date",
                     [cid, grade, since]):
        by.setdefault(r["date"], {"date": r["date"]})[r["metric"]] = r["value"]
    return list(by.values())


def _prev_metrics(cid: int, day: str) -> dict | None:
    r = db.row("SELECT max(date) AS d FROM intel_metric WHERE company_id=? AND grade='verified' AND source='trustmrr' AND date<?", [cid, day])
    if not r or not r.get("d"):
        return None
    return {x["metric"]: x["value"] for x in db.rows("SELECT metric, value FROM intel_metric WHERE company_id=? AND date=? "
                                                     "AND grade='verified' AND source='trustmrr'", [cid, r["d"]])}


def _revenue_event(c: dict, x: dict, day: str, src: dict) -> int | None:
    """收入 / 挂牌事件（不出五层解读卡，card_status=profile：看公司页的生意拆解卡）。同一 ext_key 只记一次。"""
    if db.row("SELECT 1 FROM intel_event WHERE company_id=? AND ext_key=?", [c["id"], x["key"]]):
        return None
    return db.insert("intel_event", {"company_id": c["id"], "product": c["name"], "type": x["type"], "title": f"{c['name']}：{x['title']}"[:120],
                                     "summary": x.get("summary", "")[:400], "date": day, "scale": "normal", "level_auto": x["level"],
                                     "level": x["level"], "sources": [src], "card_status": "profile", "ext_key": x["key"],
                                     "created_at": db.now(), "updated_at": db.now()})


def startup_snapshot(force: bool = False) -> dict:
    """每天一次：TrustMRR 首页 + 各分类页 + 在售列表（.env 有 TRUSTMRR_API_KEY 时再用官方 API 全量拉 AI 分类）→ 指标；和上一次快照比出收入异动；再补一批详情页。"""
    day = db.today()
    if not force and _state("startup_day") == day:
        return {}
    key = os.environ.get("TRUSTMRR_API_KEY", "").strip()
    board, errors = st.fetch_board(api_key=key)
    res = {"source": "api+pages" if key else "pages", "board": len(board), "companies": 0, "new_companies": 0, "metrics": 0,
           "revenue_events": 0, "details": 0, "errors": errors}
    for slug, o in board.items():
        before = db.row("SELECT 1 FROM intel_company WHERE kind='startup' AND json_extract(ext, '$.trustmrr')=?", [slug])
        c = _upsert_startup(slug, o)
        res["new_companies"] += 0 if before else 1
        if c["ai"] == 0 or not c["enabled"]:
            continue
        res["companies"] += 1
        cur = st.metrics_of(o)
        prev = _prev_metrics(c["id"], day)
        res["metrics"] += _write_metrics(c["id"], day, cur)
        listed = (o.get("firstListedForSaleAt") or c["ext"].get("listed_at") or "")[:10]
        src = {"label": "TrustMRR", "url": f"{st.TRUSTMRR}/startup/{slug}", "date": day, "official": True, "title": "支付渠道验证的收入"}
        for x in st.detect(prev, cur, day, listed):
            res["revenue_events"] += 1 if _revenue_event(c, x, day, src) else 0
    if board:
        res["details"] = fetch_details(int(cfg("details_per_day")), errors)
        _set_state("startup_day", day)
        if _state("startup_source") != res["source"]:  # 首次 / 换了抓取范围：这天之前没见过的不算「新上榜」
            _set_state("startup_source", res["source"])
            _set_state("coverage_since", day)
    res["at"] = db.now()
    _set_state("startup_last", res)
    return res


def fetch_details(limit: int, errors: list[str]) -> int:
    """AI 公司里没读过详情页（或 30 天前读的）的，按最新收入从高到低读 limit 个，补分类 / 渠道 / 定价 / 订阅数。"""
    stale = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    rows = db.rows("SELECT c.id, c.ext, (SELECT value FROM intel_metric WHERE company_id=c.id AND metric IN ('mrr','revenue_30d') "
                   "ORDER BY date DESC, metric LIMIT 1) AS rev FROM intel_company c WHERE c.kind='startup' AND c.ai!=0 AND c.enabled=1 "
                   "AND json_extract(c.ext, '$.trustmrr') IS NOT NULL AND ifnull(json_extract(c.ext, '$.detail_at'), '') < ? "
                   "ORDER BY rev DESC LIMIT ?", [stale, limit])

    def one(r):
        slug = _j(r["ext"], {})["trustmrr"]
        try:
            return r, st.fetch_detail(slug), None
        except Exception as e:  # noqa: BLE001
            return r, None, f"详情 {slug}: {type(e).__name__}: {str(e)[:80]}"

    n = 0
    with ThreadPoolExecutor(max_workers=4) as ex:
        for r, o, err in ex.map(one, rows):
            if err:
                errors.append(err)
            ext = {"detail_at": db.today()}
            if o:
                ext.update(st.detail_ext(o), detail_ok=1)
                subs = st.metrics_of(o).get("subscriptions")
                if subs:
                    _write_metrics(r["id"], db.today(), {"subscriptions": subs})
                n += 1
            _ext_patch(r["id"], ext)
    return n


def startups(track: str = "", q: str = "", ai: bool = True, watch_only: bool = False) -> list[dict]:
    """创业公司列表 + 最新 verified 指标 + 近 60 天 MRR 走势 + 最新 reported。"""
    sql, args = "SELECT * FROM intel_company WHERE kind='startup' AND enabled=1", []
    if ai:
        sql += " AND ai=1"
    if track:
        sql += " AND (track=? OR EXISTS (SELECT 1 FROM json_each(intel_company.tracks) WHERE value=?))"
        args += [track, track]
    if q:
        sql += " AND (name LIKE ? OR ext LIKE ?)"
        args += [f"%{q}%"] * 2
    if watch_only:
        sql += " AND watch=1"
    cos = [_company(r) for r in db.rows(sql, args)]
    since = (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%d")
    out = []
    for c in cos:
        ser = metric_series(c["id"], since=since)
        last = ser[-1] if ser else {}
        rep = db.row("SELECT metric, value, date, source FROM intel_metric WHERE company_id=? AND grade='reported' ORDER BY date DESC LIMIT 1", [c["id"]])
        if not last and not rep:
            continue
        out.append({"id": c["id"], "slug": c["slug"], "name": c["name"], "track": c["track"], "tracks": c["tracks"],
                    "track_name": st.TRACK_NAMES.get(c["track"], ""), "watch": c["watch"], "ai": c["ai"],
                    "description": (c["ext"].get("description") or "")[:200], "intro": c["ext"].get("intro_zh", ""), "website": c["ext"].get("website", ""),
                    "channels": c["ext"].get("channels", []), "profile_status": c["profile_status"],
                    "date": last.get("date", ""), "mrr": last.get("mrr"), "revenue_30d": last.get("revenue_30d"),
                    "growth_30d": last.get("growth_30d"), "on_sale": last.get("on_sale"), "asking_price": last.get("asking_price"),
                    "subscriptions": last.get("subscriptions"), "reported": rep,
                    "spark": [x.get("mrr") or x.get("revenue_30d") for x in ser if x.get("mrr") or x.get("revenue_30d")]})
    return out


def _rev(x: dict) -> float:
    return x.get("mrr") or x.get("revenue_30d") or 0


# ---------- P2b 赛道 ----------

NEEDS_INTRO = "ai!=0 AND coalesce(json_extract(ext, '$.intro_zh'), '')='' AND coalesce(json_extract(ext, '$.description'), '')!=''"


def classify_startup_tracks(limit: int = 0) -> dict:
    """没归过赛道（也没人手改过）、或还没有中文简介的创业公司交给 DeepSeek：是不是 AI 产品 + 主赛道 + 次赛道 + 中文一句话简介。
    已有赛道的只补简介，不动赛道和 ai 标记；没归赛道的先做，再按收入从高到低补简介。"""
    rows = [_company(r) for r in db.rows(
        f"SELECT * FROM intel_company WHERE kind='startup' AND enabled=1 AND ((track='' AND track_manual=0) OR ({NEEDS_INTRO})) "
        "ORDER BY (track='') DESC, ai DESC, (SELECT max(value) FROM intel_metric m WHERE m.company_id=intel_company.id "
        "AND m.metric IN ('mrr', 'revenue_30d')) DESC, id LIMIT ?", [limit or int(cfg("tracks_per_round"))])]
    if not rows or not os.environ.get("DEEPSEEK_API_KEY") and snap.llm_json is snap._deepseek:
        return {"tracked": 0, "track_errors": []}
    items = [{"id": str(c["id"]), "name": c["name"], "description": (c["ext"].get("description") or "")[:400],
              "category": c["ext"].get("category", "")} for c in rows]
    got, errors = st.classify_tracks(items)
    todo = {str(c["id"]): c for c in rows}
    for cid, x in got.items():
        c = todo[cid]
        if not c["track"] and not c["track_manual"]:
            db.update("intel_company", int(cid), {"track": x["track"] or "vertical", "tracks": x["tracks"], "ai": 1 if x["ai"] else 0,
                                                  "updated_at": db.now()})
        if x["intro"]:
            _ext_patch(int(cid), {"intro_zh": x["intro"]})
    return {"tracked": len(got), "track_errors": errors}


def track_summary() -> list[dict]:
    return track_summary_of(startups())


def track_summary_of(cos: list[dict]) -> list[dict]:
    since = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    evn = {r["track"]: r["n"] for r in db.rows(
        "SELECT c.track, count(*) AS n FROM intel_event e JOIN intel_company c ON c.id=e.company_id "
        "WHERE c.kind='startup' AND e.date>=? AND e.merged_into IS NULL GROUP BY c.track", [since])}
    out = []
    for slug, name, scope in st.TRACKS:
        cs = sorted([c for c in cos if c["track"] == slug], key=_rev, reverse=True)
        gs = sorted(c["growth_30d"] for c in cs if c.get("growth_30d") is not None)
        out.append({"slug": slug, "name": name, "scope": scope, "companies": len(cs), "total_rev": sum(_rev(c) for c in cs),
                    "median_growth": gs[len(gs) // 2] if gs else None, "growing": sum(1 for g in gs if g > 0),
                    "on_sale": sum(1 for c in cs if c.get("on_sale") == 1), "events_30d": evn.get(slug, 0),
                    "top": [{"slug": c["slug"], "name": c["name"], "rev": _rev(c)} for c in cs[:3]]})
    return out


# ---------- 总览：赛道格局 / 本周异动 / 头部与黑马 / 打法汇总 ----------

HORSE_MIN, HORSE_MAX, HORSE_GROWTH = 1000, 20000, 30   # 黑马：收入 $1k–20k、30 天增长 ≥30%
MOVER_MIN = 1000                                       # 涨跌榜只看收入 ≥$1k 的，小基数的百分比没意义


def _brief(c: dict) -> dict:
    return {k: c.get(k) for k in ("id", "slug", "name", "track", "track_name", "intro", "mrr", "revenue_30d", "growth_30d",
                                  "on_sale", "asking_price", "watch")} | {"rev": _rev(c)}


def _detail_ok(e: dict) -> bool:
    """真读到了详情页（读失败的只写 detail_at）；detail_ok 之前读的看有没有详情页才有的字段。"""
    return bool(e.get("detail_ok")) or any(k in e for k in ("payment", "website", "channels", "pricing", "audience", "founded"))


def overview(days: int = 7) -> dict:
    cos = startups()
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    tracks = track_summary_of(cos)
    # 本周异动：收入事件 + 新挂牌 + TrustMRR 30 天增长涨跌榜 + 新上榜
    by_id = {c["id"]: c for c in cos}
    events = [e for e in list_events(company="", days=days, limit=300, kind="startup")["events"]
              if e["type"] in ("revenue", "listing") and _rev(by_id.get(e["company_id"]) or {}) >= MOVER_MIN]
    big = [c for c in cos if _rev(c) >= MOVER_MIN and c.get("growth_30d") is not None]
    cov = _state("coverage_since") or ""
    first = {r["company_id"]: r["d"] for r in db.rows(
        "SELECT company_id, min(date) AS d FROM intel_metric WHERE source='trustmrr' GROUP BY company_id")}
    new = [c for c in cos if cov and first.get(c["id"], "") > cov and first[c["id"]] >= since]
    # 头部与黑马
    tops = [{"slug": t["slug"], "name": t["name"], "top": [_brief(c) for c in sorted((c for c in cos if c["track"] == t["slug"]),
                                                                                       key=_rev, reverse=True)[:3]]} for t in tracks]
    horses = sorted((c for c in cos if HORSE_MIN <= _rev(c) <= HORSE_MAX and (c.get("growth_30d") or 0) >= HORSE_GROWTH),
                    key=lambda c: c["growth_30d"], reverse=True)[:12]
    # 打法汇总：详情页里的获客渠道 / 定价方式（按家数 + 按收入），拆解卡里的「可抄的打法」
    ext = {r["id"]: _j(r["ext"], {}) for r in db.rows("SELECT id, ext FROM intel_company WHERE kind='startup' AND ai=1 AND enabled=1")}
    with_detail = [c for c in cos if _detail_ok(ext.get(c["id"], {}))]
    def agg(key_of) -> list[dict]:  # 一家可以有多个渠道 / 定价方式：按家数计，同时累计这些公司的收入
        n: dict[str, list] = {}
        for c in with_detail:
            for k in set(key_of(ext[c["id"]])):
                n.setdefault(k, [0, 0.0])
                n[k][0] += 1
                n[k][1] += _rev(c)
        return [{"name": k, "n": v[0], "rev": v[1]} for k, v in sorted(n.items(), key=lambda x: -x[1][0])]
    chs = lambda e: e.get("channels") or []  # noqa: E731
    channels = [{**x, "label": st.CHANNEL_ZH.get(x["name"], x["name"])} for x in agg(chs)]
    families = agg(lambda e: [st.channel_family(ch) for ch in chs(e)])
    pricing = agg(lambda e: st.pricing_kinds(str(e.get("pricing") or "")))
    no_channel = sum(1 for c in with_detail if not chs(ext[c["id"]]))
    plays = []
    for r in db.rows("SELECT p.company_id, p.sections, p.created_at FROM intel_profile p WHERE p.complete=1 AND p.id IN "
                     "(SELECT max(id) FROM intel_profile GROUP BY company_id) ORDER BY p.created_at DESC LIMIT 12"):
        c = by_id.get(r["company_id"])
        txt = _j(r["sections"], {}).get("可抄的打法", "")
        if c and txt:
            plays.append({**_brief(c), "plays": txt, "at": r["created_at"]})
    return {"days": days, "since": since, "total": len(cos), "total_rev": sum(_rev(c) for c in cos), "tracks": tracks,
            "events": events[:30], "gainers": [_brief(c) for c in sorted(big, key=lambda c: c["growth_30d"], reverse=True)[:8]],
            "losers": [_brief(c) for c in sorted(big, key=lambda c: c["growth_30d"])[:8] if c["growth_30d"] < 0],
            "new": [_brief(c) for c in sorted(new, key=_rev, reverse=True)[:20]], "new_total": len(new), "coverage_since": cov,
            "on_sale": [_brief(c) for c in sorted((c for c in cos if c.get("on_sale") == 1), key=_rev, reverse=True)[:8]],
            "tops": tops, "horses": [_brief(c) for c in horses],
            "horse_rule": {"min": HORSE_MIN, "max": HORSE_MAX, "growth": HORSE_GROWTH},
            "channels": channels[:15], "families": families, "pricing": pricing, "detail_n": len(with_detail), "no_channel": no_channel, "plays": plays,
            "last": _state("startup_last") or {}}


# ---------- P2c 生意拆解卡 ----------

def _profiles_today() -> int:
    return (db.row("SELECT count(*) AS n FROM intel_company WHERE profile_requested_at >= ?", [db.today()]) or {}).get("n", 0)


def _profile_inputs(c: dict) -> tuple[list[dict], list[dict], list[dict], str]:
    metrics = metric_series(c["id"])
    reported = db.rows("SELECT date, metric, value, source FROM intel_metric WHERE company_id=? AND grade='reported' ORDER BY date", [c["id"]])
    events = db.rows("SELECT date, level, title FROM intel_event WHERE company_id=? AND merged_into IS NULL ORDER BY date DESC LIMIT 10", [c["id"]])
    return metrics, reported, events, c["ext"].get("notes") or ""


def request_profile(cid: int) -> int:
    r = db.row("SELECT * FROM intel_company WHERE id=?", [cid])
    if not r:
        raise HTTPException(404, "公司不存在")
    c = _company(r)
    metrics, reported, events, notes = _profile_inputs(c)
    h = st.profile_inputs_hash(c, metrics, notes)
    jid = jobs.submit("intel", st.profile_prompt(c, metrics, reported, events, notes), ref=f"intel:company:{cid}:profile:{h}", tier="standard")
    db.update("intel_company", cid, {"profile_status": "queued", "profile_requested_at": db.now()})
    return jid


def profile_queue() -> list[tuple[int, str]]:
    """自动写拆解卡的候选（按优先级）：手动关注 → 近 30 天 B+ 收入事件 → 30 天增长 ≥100% 且收入 ≥$1k → 近 30 天挂牌且 ≥$5k → 各赛道收入前 10。"""
    cos = startups()
    since = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    hot = {r["company_id"] for r in db.rows("SELECT DISTINCT company_id FROM intel_event WHERE type IN ('revenue','listing') "
                                            "AND level IN ('S','A','B') AND date>=?", [since])}
    top = set()
    for slug, _, _ in st.TRACKS:
        top |= {c["id"] for c in sorted([c for c in cos if c["track"] == slug], key=_rev, reverse=True)[:10]}
    out = []
    for c in cos:
        ext = _j((db.row("SELECT ext FROM intel_company WHERE id=?", [c["id"]]) or {}).get("ext"), {})
        why = ("关注" if c["watch"] else "收入异动" if c["id"] in hot
               else "高增长" if (c.get("growth_30d") or 0) >= 100 and _rev(c) >= 1000
               else "新挂牌" if c.get("on_sale") == 1 and (ext.get("listed_at") or "") >= since and _rev(c) >= 5000
               else "赛道前 10" if c["id"] in top else "")
        if why:
            out.append((["关注", "收入异动", "高增长", "新挂牌", "赛道前 10"].index(why), -_rev(c), c["id"], why))
    return [(cid, why) for _, _, cid, why in sorted(out)]


def queue_profiles() -> int:
    left = int(cfg("profiles_per_day")) - _profiles_today()
    if left <= 0:
        return 0
    recent = (datetime.now() - timedelta(days=float(cfg("profile_days")))).strftime("%Y-%m-%d")
    n = 0
    for cid, _why in profile_queue():
        if n >= left:
            break
        c = db.row("SELECT profile_status, profile_requested_at FROM intel_company WHERE id=?", [cid]) or {}
        if c.get("profile_status") == "queued" or (c.get("profile_requested_at") or "") >= recent:
            continue
        request_profile(cid)
        n += 1
    return n


def on_profile_done(job: dict) -> None:
    m = re.fullmatch(r"intel:company:(\d+):profile(?::(\w+))?", job.get("ref") or "")
    cid = int(m[1])
    if job.get("status") != "done":
        db.update("intel_company", cid, {"profile_status": "failed"})
        return
    q = st.profile_quality(job.get("output") or "")
    db.insert("intel_profile", {"company_id": cid, "content": job.get("output") or "", "sections": q["sections"], "missing": q["missing"],
                                "complete": int(q["complete"]), "inputs_hash": m[2] or "", "job_id": job["id"], "created_at": db.now()})
    db.update("intel_company", cid, {"profile_status": "done" if q["complete"] else "incomplete", "updated_at": db.now()})


# ---------- P2d Product Hunt 日榜解读 + 公开 ARR ----------

def ph_daily(max_days: int = 3) -> int:
    """信息推荐里收到的 Product Hunt 条目（AI 相关）按发布日分组；已过完的日子各取票数前 N，交给 DeepSeek 归赛道 + 写解读。"""
    if not ev_has_table("feed_items"):
        return 0
    since = (datetime.now() - timedelta(days=max_days + 1)).strftime("%Y-%m-%d")
    done = {r["date"] for r in db.rows("SELECT date FROM intel_ph_day WHERE date>=?", [since])}
    rows = db.rows("SELECT * FROM feed_items WHERE source='producthunt' AND substr(date,1,10)>=? AND substr(date,1,10)<? "
                   "ORDER BY popularity DESC", [since, db.today()])
    by: dict[str, list] = {}
    for r in rows:
        by.setdefault(r["date"][:10], []).append({**r, "extra": _j(r.get("extra"), {})})
    n = 0
    for day, items in sorted(by.items(), reverse=True):
        if day in done or len(items) < 3:
            continue
        items = items[:int(cfg("ph_top"))]
        try:
            res = snap.llm_json(st.PH_SYSTEM, st.ph_payload(day, items), max_tokens=4000)
        except Exception as e:  # noqa: BLE001
            log.warning("PH 日榜解读失败 %s: %s", day, e)
            continue
        info = {str(x.get("id")): x for x in res.get("items") or [] if isinstance(x, dict)}
        out = [{"id": it["id"], "rank": i + 1, "name": it["title"].split("：")[0], "title": it["title"], "url": it["url"],
                "website": it["extra"].get("website", ""), "votes": int(it.get("popularity") or 0),
                "comments": it["extra"].get("comments", 0), "topics": it["extra"].get("topics", []),
                "track": info.get(it["id"], {}).get("track") if info.get(it["id"], {}).get("track") in st.TRACK_NAMES else "",
                "why": (info.get(it["id"], {}).get("why") or "")[:120]} for i, it in enumerate(items)]
        db.execute("INSERT OR REPLACE INTO intel_ph_day(date, items, summary, created_at) VALUES(?,?,?,?)",
                   [day, ev.dumps(out), str(res.get("summary") or "")[:4000], db.now()])
        n += 1
    return n


def _find_company(name: str) -> dict | None:
    k = name.strip().lower()
    for r in db.rows("SELECT * FROM intel_company"):
        c = _company(r)
        if k in {c["name"].lower(), c["slug"], *[a.lower() for a in c["aliases"]]}:
            return c
    return None


def scan_reported_arr(limit: int = 80) -> dict:
    """信息推荐新收的条目里提到 ARR / MRR 的 → DeepSeek 抽「公司 + 数字」（数字必须在原文里）→ reported 指标 + 事件。"""
    if not ev_has_table("feed_items"):
        return {"reported": 0}
    cursor = _state("arr_cursor") or (datetime.now() - timedelta(days=3)).isoformat(timespec="seconds")
    rows = db.rows("SELECT * FROM feed_items WHERE fetched_at > ? AND source NOT IN ('trustmrr','arxiv','hf','github','analysis') "
                   "ORDER BY fetched_at LIMIT 2000", [cursor])
    if not rows:
        return {"reported": 0}
    items = [{"id": r["id"], "title": r["title"], "text": r.get("summary") or "", "url": r.get("url") or "",
              "date": (r.get("date") or r["fetched_at"] or "")[:10], "source": r["source"]}
             for r in rows if st.ARR_HINT.search(f"{r['title']} {r.get('summary') or ''}")][:limit]
    found, errors = st.extract_arr(items) if items else ([], [])
    by = {it["id"]: it for it in items}
    n = 0
    for x in found:
        it = by[x["item_id"]]
        c = _find_company(x["company"])
        if not c:
            slug = re.sub(r"[^a-z0-9]+", "-", x["company"].lower()).strip("-") or f"co-{int(time.time())}"
            if db.row("SELECT 1 FROM intel_company WHERE slug=?", [slug]):
                slug = f"rp-{slug}"
            cid = db.insert("intel_company", {"slug": slug, "name": x["company"], "tier": 3, "kind": "startup", "ai": -1,
                                              "aliases": [x["company"]], "domains": [], "x": [], "github": [], "feed_urls": [],
                                              "ext": {"reported_only": True}, "created_at": db.now(), "updated_at": db.now()})
            c = _company(db.row("SELECT * FROM intel_company WHERE id=?", [cid]))
        if not _write_metrics(c["id"], it["date"], {x["metric"]: x["value"]}, grade="reported", source=it["url"] or it["id"],
                              note=x["quote"]):
            continue
        n += 1
        same = db.row("SELECT 1 FROM intel_event WHERE company_id=? AND ext_key LIKE ?", [c["id"], f"reported:{x['metric']}:{round(x['value'] / 1e6, 1)}%"])
        if same:
            continue
        level = "A" if c["kind"] != "startup" or x["value"] >= 1e8 else "B" if x["value"] >= 1e6 else "C"
        db.insert("intel_event", {"company_id": c["id"], "product": c["name"], "type": "revenue",
                                  "title": f"{c['name']}：公开 {x['metric'].upper()} {st.usd(x['value'])}（reported）"[:120],
                                  "summary": x["quote"][:400], "date": it["date"], "scale": "normal", "level_auto": level, "level": level,
                                  "sources": [{"label": it["source"], "url": it["url"], "date": it["date"], "official": False, "title": it["title"][:160]}],
                                  "card_status": "profile", "ext_key": f"reported:{x['metric']}:{round(x['value'] / 1e6, 1)}",
                                  "created_at": db.now(), "updated_at": db.now()})
    if not errors:
        _set_state("arr_cursor", rows[-1]["fetched_at"])
    return {"reported": n, "arr_errors": errors}


def startup_cycle(force: bool = False, cards: bool = True) -> dict:
    res = {}
    for name, fn in (("growth", lambda: growth_daily(cards=cards) if cfg("growth") else {}), ("snapshot", lambda: startup_snapshot(force)), ("tracks", classify_startup_tracks), ("ph", ph_daily),
                     ("arr", scan_reported_arr), ("profiles", lambda: queue_profiles() if cards else 0)):
        try:
            res[name] = fn()
        except Exception as e:  # noqa: BLE001
            log.exception("intel startup %s failed", name)
            res[name] = {"error": f"{type(e).__name__}: {str(e)[:200]}"}
    return res


# ---------- 每日增长 Case ----------

def growth_collect() -> dict:
    """增长类 RSS（各源自己的回看天数）+ X 名单账号近 3 天 ≥100 赞原创 → 候选池（已收过的不再收）。"""
    from . import _feed_sources as fs
    items, errors = [], []
    for s in gr.SOURCES:
        got, errs = fs.fetch_rss([s["url"]], days=s["days"], per_feed=s["per_feed"], source="growth", typ="blog")
        items += [{**it, "source_name": s["name"], "tier": s["tier"]} for it in got]
        errors += errs
    accounts = cfg("growth_x_accounts") or []
    if accounts:
        try:
            got, errs = fs.fetch_x(accounts, [], days=3, min_likes=100, per_account=3)
            items += [{**it, "source_name": f"X @{it['extra'].get('author') or ''}", "tier": "B"} for it in got]
            errors += errs
        except Exception as e:  # noqa: BLE001 —— 没配 X 密钥时只用 RSS
            errors.append(f"x: {type(e).__name__}: {str(e)[:120]}")
    n = 0
    for it in items:
        if db.row("SELECT 1 FROM intel_growth_item WHERE id=?", [it["id"]]):
            continue
        db.insert("intel_growth_item", {"id": it["id"], "source": it["source_name"], "tier": it["tier"], "title": it["title"][:300],
                                        "summary": (it.get("summary") or "")[:4000], "url": it["url"], "date": (it.get("date") or "")[:10],
                                        "status": "new", "found_at": db.now()})
        n += 1
    return {"new": n, "fetched": len(items), "errors": errors[:10]}


def growth_score(limit: int = 0) -> dict:
    """待打分的素材 20 条一批交给 DeepSeek；一批失败只记错误，下一轮再打。"""
    rows = db.rows("SELECT * FROM intel_growth_item WHERE status='new' ORDER BY date DESC LIMIT ?",
                   [limit or int(cfg("growth_score_per_round"))])
    n, errors = 0, []
    for i in range(0, len(rows), 20):
        batch = rows[i:i + 20]
        try:
            res = snap.llm_json(gr.SCORE_SYSTEM, gr.score_payload(batch), max_tokens=4000)
        except Exception as e:  # noqa: BLE001
            errors.append(f"{type(e).__name__}: {str(e)[:120]}")
            continue
        got = {str(x.get("id")): x for x in res.get("items") or [] if isinstance(x, dict)}
        for r in batch:
            x = got.get(r["id"])
            if not x:
                continue
            sc = gr.clamp_scores(x)
            db.execute("UPDATE intel_growth_item SET scores=?, total=?, company=?, one_line=?, status='scored' WHERE id=?",
                       [ev.dumps(sc), gr.total(sc), str(x.get("company") or "")[:80], str(x.get("one_line") or "")[:200], r["id"]])
            n += 1
    return {"scored": n, "errors": errors}


def _growth_item(r: dict) -> dict:
    return {**r, "scores": _j(r.get("scores"), {})}


def growth_pool(limit: int = 0) -> list[dict]:
    """打过分、合格、还没出过卡的候选，按选题顺序排。"""
    today = db.today()
    pool = [_growth_item(r) for r in db.rows("SELECT * FROM intel_growth_item WHERE status='scored'")]
    pool = [it for it in pool if gr.eligible(it["scores"])]
    pool.sort(key=lambda it: (gr.rank_key(it, today), it.get("date") or ""), reverse=True)
    return pool[:limit] if limit else pool


def _growth_used() -> set[str]:
    since = (datetime.now() - timedelta(days=float(cfg("growth_repeat_days")))).strftime("%Y-%m-%d")
    return {gr.norm_company(r["company"]) for r in db.rows("SELECT company FROM intel_growth_case WHERE day>=?", [since])}


def _growth_metrics(company: str) -> str:
    """主角在平台里有 TrustMRR / 公开 ARR 记录的，带给写卡任务做核验。"""
    c = _find_company(company) if company else None
    if not c:
        return ""
    lines = [f"- {m['date']} · verified MRR {st.usd(m['mrr']) if m.get('mrr') else '-'} · 30 天收入 "
             f"{st.usd(m['revenue_30d']) if m.get('revenue_30d') else '-'}（TrustMRR）" for m in metric_series(c["id"])[-6:]]
    lines += [f"- {r['date']} · reported {r['metric'].upper()} {st.usd(r['value'])} · {r.get('source') or ''}"
              for r in db.rows("SELECT date, metric, value, source FROM intel_metric WHERE company_id=? AND grade='reported' "
                               "ORDER BY date DESC LIMIT 6", [c["id"]])]
    return "\n".join(lines)


def request_growth_case(item_id: str, auto: bool = False) -> dict:
    r = db.row("SELECT * FROM intel_growth_item WHERE id=?", [item_id])
    if not r:
        raise HTTPException(404, "素材不存在")
    it = _growth_item(r)
    cid = db.insert("intel_growth_case", {"item_id": item_id, "day": db.today(), "auto": int(auto), "company": it["company"],
                                          "status": "queued", "created_at": db.now(), "updated_at": db.now()})
    jid = jobs.submit("intel", gr.case_prompt(it, _growth_metrics(it["company"])), ref=f"intel:growth:{cid}", tier="standard")
    db.update("intel_growth_case", cid, {"job_id": jid})
    db.execute("UPDATE intel_growth_item SET status='picked' WHERE id=?", [item_id])
    return {"id": cid, "job_id": jid}


def growth_daily(force_collect: bool = False, cards: bool = True) -> dict:
    """每轮都会被调：素材到点才采（默认 12 小时一次）→ 打分 → 每天保底 1 张；近 7 天有总分 ≥13 的新素材就加写，一天最多 5 张。"""
    res = {}
    last = _state("growth_collect_at") or ""
    due = (datetime.now() - timedelta(hours=float(cfg("growth_collect_hours")))).isoformat(timespec="seconds")
    if force_collect or last < due:
        res["collect"] = growth_collect()
        _set_state("growth_collect_at", db.now())
    res.update(growth_score())
    if cards:
        res["picked"] = []
        n = db.row("SELECT count(*) AS n FROM intel_growth_case WHERE day=? AND auto=1 AND status!='failed'", [db.today()])["n"]
        while n < int(cfg("growth_daily_max")):
            pool = growth_pool()
            if n:  # 第 2 张起只收「优秀」的新素材：近 N 天发布、总分达标；存档再好也不挤占
                since = (datetime.now() - timedelta(days=float(cfg("growth_extra_days")))).strftime("%Y-%m-%d")
                pool = [it for it in pool if (it.get("date") or "") >= since and it["total"] >= int(cfg("growth_extra_min"))]
            it = gr.pick(pool, _growth_used(), db.today())
            if not it:
                break
            res["picked"].append(request_growth_case(it["id"], auto=True)["id"])
            n += 1
        if not n:
            res["picked_reason"] = "候选池里没有合格素材（或主角公司近期都出过卡）"
    _set_state("growth_last", {**res, "at": db.now()})
    return res


def on_growth_done(job: dict) -> None:
    cid = int(job["ref"].rsplit(":", 1)[1])
    if job.get("status") != "done":
        db.update("intel_growth_case", cid, {"status": "failed", "updated_at": db.now()})
        return
    q = gr.case_quality(job.get("output") or "")
    db.update("intel_growth_case", cid, {"content": job.get("output") or "", "sections": q["sections"], "missing": q["missing"],
                                         "complete": int(q["complete"]), "status": "done" if q["complete"] else "incomplete",
                                         "updated_at": db.now()})


def _growth_case(r: dict, full: bool = False) -> dict:
    it = db.row("SELECT * FROM intel_growth_item WHERE id=?", [r["item_id"]]) or {}
    out = {**r, "sections": None, "missing": _j(r.get("missing"), []), "item": _growth_item(it) if it else None,
           "read": _read_log.has("growth", r["item_id"])}
    if not full:
        out["content"] = None
    return out


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
        if cfg("startups"):  # 官方 API 全量翻页要几十分钟，放独立线程，不挡产品雷达这一轮
            res["startups"] = {"started": run_startups({"force_fetch": force_fetch, "cards": cards})["started"]}
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
    oss.on_startup()


# ---------- 接口 ----------

router = APIRouter()


def _with_card(e: dict, full: bool = False) -> dict:
    a = db.row("SELECT * FROM intel_analysis WHERE event_id=? ORDER BY id DESC LIMIT 1", [e["id"]])
    e = {**_event(e), "read": _read_log.has("intel_event", e["id"])}
    if a:
        e["card"] = {"id": a["id"], "complete": bool(a["complete"]), "missing": _j(a["missing"], []), "created_at": a["created_at"],
                     "content": a["content"] if full else None}
    return e


@router.get("/events")
def list_events(level: str = "", company: str = "", days: float = 30, q: str = "", limit: int = 100, type: str = "", kind: str = ""):
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
    if type == "revenue":  # 「收入」筛选：TrustMRR 异动 + 挂牌 + 公开 ARR
        sql += " AND e.type IN ('revenue','listing')"
    elif type:
        sql += " AND e.type=?"
        args.append(type)
    if kind:
        sql += " AND c.kind=?"
        args.append(kind)
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


@router.post("/events/{eid}/read")
def read_event(eid: int):
    e = db.row("SELECT title FROM intel_event WHERE id=?", [eid])
    if not e:
        raise HTTPException(404, "事件不存在")
    _read_log.log("intel_event", eid, e["title"], f"#intel/e/{eid}", "产品雷达")
    return {"ok": True}


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
    since = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
    c["metrics"] = metric_series(c["id"], since=since)
    c["reported"] = db.rows("SELECT date, metric, value, source, note FROM intel_metric WHERE company_id=? AND grade='reported' ORDER BY date", [c["id"]])
    c["track_name"] = st.TRACK_NAMES.get(c["track"], "")
    c["track_options"] = [{"slug": s, "name": n} for s, n, _ in st.TRACKS]
    p = db.row("SELECT * FROM intel_profile WHERE company_id=? ORDER BY id DESC LIMIT 1", [c["id"]])
    c["profile"] = {"id": p["id"], "content": p["content"], "complete": bool(p["complete"]), "missing": _j(p["missing"], []),
                    "created_at": p["created_at"]} if p else None
    c["profile_versions"] = (db.row("SELECT count(*) AS n FROM intel_profile WHERE company_id=?", [c["id"]]) or {}).get("n", 0)
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
    allowed = {k: v for k, v in body.items() if k in ("name", "tier", "category", "enabled", "note", "watch", "ai", "tracks", *COMPANY_JSON)}
    if "track" in body:  # 人工改赛道：以后不再被模型覆盖
        if body["track"] and body["track"] not in st.TRACK_NAMES:
            raise HTTPException(400, f"赛道只能是 {', '.join(st.TRACK_NAMES)}")
        allowed.update(track=body["track"], track_manual=1)
    if isinstance(body.get("ext"), dict):  # BizPeel 链接、手动粘贴的资料等：合并，不覆盖其它字段
        _ext_patch(cid, {k: v for k, v in body["ext"].items() if k in ("bizpeel_url", "notes", "website", "x")})
    db.update("intel_company", cid, {**allowed, "updated_at": db.now()})
    return _company(db.row("SELECT * FROM intel_company WHERE id=?", [cid]) or {})


class SourceIn(BaseModel):
    company_id: int
    kind: str = "changelog"
    url: str
    label: str = ""
    product: str = ""


@router.post("/companies/{cid}/profile")
def regen_profile(cid: int):
    return {"job_id": request_profile(cid)}


@router.get("/startups")
def list_startups(track: str = "", q: str = "", sort: str = "rev", watch: int = 0, all: int = 0, limit: int = 300):
    rows = startups(track=track, q=q, ai=not all, watch_only=bool(watch))
    key = {"growth": lambda c: c.get("growth_30d") if c.get("growth_30d") is not None else -1e9,
           "reported": lambda c: (c.get("reported") or {}).get("value") or 0}.get(sort, _rev)
    rows.sort(key=key, reverse=True)
    last = _state("startup_last") or {}
    return {"startups": rows[:limit], "total": len(rows), "tracks": [{"slug": s, "name": n} for s, n, _ in st.TRACKS],
            "last": last, "pending_tracks": (db.row("SELECT count(*) AS n FROM intel_company WHERE kind='startup' AND enabled=1 "
                                                    "AND track='' AND track_manual=0") or {}).get("n", 0),
            "profiles_today": _profiles_today(), "profiles_per_day": cfg("profiles_per_day")}


@router.get("/overview")
def get_overview(days: int = 7):
    return overview(days)


@router.get("/tracks")
def list_tracks():
    return track_summary()


@router.get("/tracks/{slug}")
def get_track(slug: str):
    if slug not in st.TRACK_NAMES:
        raise HTTPException(404, "没有这个赛道")
    t = next(x for x in track_summary() if x["slug"] == slug)
    t["startups"] = sorted(startups(track=slug), key=_rev, reverse=True)
    t["events"] = list_events(company="", days=60, limit=100, type="revenue", kind="startup")["events"]
    ids = {c["id"] for c in t["startups"]}
    t["events"] = [e for e in t["events"] if e["company_id"] in ids]
    read_ids = _read_log.refs("feed")
    t["ph"] = [{**it, "date": d["date"], "track_name": t["name"], "read": it.get("id") in read_ids}
               for d in db.rows("SELECT * FROM intel_ph_day ORDER BY date DESC LIMIT 14")
               for it in _j(d["items"], []) if it.get("track") == slug]
    return t


@router.get("/ph")
def list_ph(days: int = 7):
    read_ids = _read_log.refs("feed")
    return [{**d, "items": [{**it, "track_name": st.TRACK_NAMES.get(it.get("track") or "", ""), "read": it.get("id") in read_ids}
                            for it in _j(d["items"], [])]}
            for d in db.rows("SELECT * FROM intel_ph_day ORDER BY date DESC LIMIT ?", [days])]


_st_lock = threading.Lock()


@router.post("/startups/run")
def run_startups(body: dict | None = None):
    """后台跑一遍创业公司链路（快照 / 赛道 / PH / 公开 ARR / 拆解卡排队）；结果看 /status 的 startup_last。"""
    body = body or {}
    if not _st_lock.acquire(blocking=False):
        return {"started": False}

    def go():
        try:
            _set_state("startup_cycle", startup_cycle(force=bool(body.get("force_fetch")), cards=body.get("cards", True)))
        finally:
            _st_lock.release()
    threading.Thread(target=go, daemon=True, name="intel-startups").start()
    return {"started": True}


@router.get("/growth")
def list_growth(limit: int = 30):
    """每天的增长 Case（同一素材重写过的只给最新一版）+ 候选池前 10 + 上一轮状态。"""
    rows = db.rows("SELECT * FROM intel_growth_case WHERE id IN (SELECT max(id) FROM intel_growth_case GROUP BY item_id) "
                   "ORDER BY day DESC, id DESC LIMIT ?", [limit])
    counts = {r["status"]: r["n"] for r in db.rows("SELECT status, count(*) AS n FROM intel_growth_item GROUP BY status")}
    return {"cases": [_growth_case(r) for r in rows], "pool": [{**it, "read": _read_log.has("growth", it["id"])} for it in growth_pool(10)], "counts": counts, "last": _state("growth_last"),
            "sources": [{"name": s["name"], "url": s["url"], "tier": s["tier"]} for s in gr.SOURCES],
            "x_accounts": cfg("growth_x_accounts") or []}


@router.get("/growth/{cid}")
def get_growth(cid: int):
    r = db.row("SELECT * FROM intel_growth_case WHERE id=?", [cid])
    if not r:
        raise HTTPException(404, "Case 不存在")
    versions = db.rows("SELECT id, status, created_at FROM intel_growth_case WHERE item_id=? ORDER BY id DESC", [r["item_id"]])
    return {**_growth_case(r, full=True), "versions": versions}


class GrowthPickIn(BaseModel):
    item_id: str


@router.post("/growth/read")
def read_growth(body: GrowthPickIn):
    it = db.row("SELECT title, url, company FROM intel_growth_item WHERE id=?", [body.item_id])
    if not it:
        raise HTTPException(404, "素材不存在")
    case = db.row("SELECT max(id) id FROM intel_growth_case WHERE item_id=?", [body.item_id])
    _read_log.log("growth", body.item_id, f"{it['company'] or '?'} · {it['title']}", f"#intel/g/{case['id']}" if case["id"] else it["url"], "增长 Case")
    return {"ok": True}


@router.post("/growth/pick")
def pick_growth(body: GrowthPickIn):
    """手动从候选池里选一条写卡（不占每天自动的那 1 张）。"""
    return request_growth_case(body.item_id)


@router.post("/growth/{cid}/regen")
def regen_growth(cid: int):
    r = db.row("SELECT item_id FROM intel_growth_case WHERE id=?", [cid])
    if not r:
        raise HTTPException(404, "Case 不存在")
    return request_growth_case(r["item_id"])


_gr_lock = threading.Lock()


@router.post("/growth/run")
def run_growth(body: dict | None = None):
    """后台跑一遍：采素材（force_collect=true 时不等 12 小时）→ 打分 → 今天没有就选一条写卡。"""
    if not _gr_lock.acquire(blocking=False):
        return {"started": False}

    def go():
        try:
            growth_daily(force_collect=bool((body or {}).get("force_collect")))
        except Exception:  # noqa: BLE001
            log.exception("growth run failed")
        finally:
            _gr_lock.release()
    threading.Thread(target=go, daemon=True, name="intel-growth").start()
    return {"started": True}


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
            "companies": (db.row("SELECT count(*) AS n FROM intel_company WHERE enabled=1 AND kind!='startup'") or {}).get("n", 0),
            "sources": (db.row("SELECT count(*) AS n FROM intel_source WHERE enabled=1") or {}).get("n", 0),
            "events": (db.row("SELECT count(*) AS n FROM intel_event WHERE merged_into IS NULL") or {}).get("n", 0),
            "cards_today": _cards_today(), "cards_per_day": cfg("cards_per_day"), "failing_sources": bad,
            "startups": (db.row("SELECT count(*) AS n FROM intel_company WHERE kind='startup' AND enabled=1 AND ai=1") or {}).get("n", 0),
            "startup_last": _state("startup_last"), "profiles_today": _profiles_today(), "profiles_per_day": cfg("profiles_per_day"),
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
    return "\n".join(lines) + "\n\n" + oss.agent_context(ref)


router.include_router(oss.router)   # 开源雷达：/api/intel/oss/...
labels_for = oss.labels_for        # 信息推荐给 GitHub 条目挂雷达标签用
