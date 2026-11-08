"""视野：AI 发展、吃喝玩乐 / 生活 / 学习、国家宏观与行业的大数据变化，以及给小白看的解读卡。

链路：每天一轮定时取数（_vision_sources，不用大模型）→ 数据点按修订版本只追加 → 程序算统计和显著度
（_vision_stats）→ 够显著的让后台 Claude 写解读卡 → 程序校验（字数、术语、数字对账、链接可开、可对账的预测）
→ 另一个 Claude 审稿（四条标准）→ 通过才展示；预测到期由程序拿真实数据对账。
指标清单见 vision_series.json（status：ok 已接入 / todo 待验 / extract 需抽取 / existing 平台已有）。
设计稿：docs/designs/2026-11-08-vision-design.html。
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from datetime import date, timedelta
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException

from .. import db, jobs, notify
from . import _vision_cards as vc
from . import _vision_sources as src
from . import _vision_stats as vs
from ._feed_sources import BROWSER_UA

log = logging.getLogger(__name__)

TITLE = "视野"
ORDER = 36
SCHEMA = """
CREATE TABLE IF NOT EXISTS vision_points (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    series_id   TEXT NOT NULL,
    period      TEXT NOT NULL,
    value       REAL NOT NULL,
    revision    INTEGER DEFAULT 0,           -- 统计局会修订历史数：值变了就追加一版，不覆盖
    fetched_at  TEXT,
    UNIQUE(series_id, period, revision)
);
CREATE TABLE IF NOT EXISTS vision_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    day         TEXT,
    status      TEXT,                        -- running / done / failed
    results     TEXT DEFAULT '{}',           -- {series_id: {added, revised, error}}
    cards       TEXT DEFAULT '[]',
    started_at  TEXT,
    finished_at TEXT
);
CREATE TABLE IF NOT EXISTS vision_cards (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    series_id   TEXT NOT NULL,
    period      TEXT NOT NULL,
    attempt     INTEGER DEFAULT 1,
    score       REAL DEFAULT 0,
    signals     TEXT DEFAULT '{}',
    summary     TEXT DEFAULT '{}',
    body        TEXT DEFAULT '{}',
    checks      TEXT DEFAULT '{}',
    review      TEXT DEFAULT '{}',
    feedback    TEXT DEFAULT '',
    status      TEXT DEFAULT 'running',      -- running / reviewing / done / rejected / failed
    job_id      INTEGER,
    review_job_id INTEGER,
    created_at  TEXT,
    updated_at  TEXT
);
CREATE TABLE IF NOT EXISTS vision_predictions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    card_id     INTEGER,
    series_id   TEXT,
    due_date    TEXT,
    op          TEXT,
    target      REAL,
    confidence  TEXT,
    text        TEXT DEFAULT '',
    created_at  TEXT
);
CREATE TABLE IF NOT EXISTS vision_verdicts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    prediction_id INTEGER UNIQUE,
    period        TEXT,
    actual        REAL,
    hit           INTEGER,                   -- 1 中 / 0 没中 / NULL 过期没等到数据
    checked_at    TEXT
);
"""

SERIES: list[dict] = json.loads((Path(__file__).parent / "vision_series.json").read_text())
BY_ID = {s["id"]: s for s in SERIES}
THEMES = [("ai", "AI 发展"), ("fun", "吃喝玩乐"), ("life", "生活"), ("learn", "学习"), ("macro", "国家宏观与行业")]
CARDS_PER_DAY = 6
MAX_ATTEMPTS = 3
EXPIRE_DAYS = 120

router = APIRouter()
_lock = threading.Lock()


def enabled() -> list[dict]:
    return [s for s in SERIES if s["status"] == "ok"]


def _j(v, default):
    try:
        return json.loads(v) if isinstance(v, str) else (v if v is not None else default)
    except json.JSONDecodeError:
        return default


# ---------- 数据点 ----------

def points(series_id: str) -> list[tuple[str, float]]:
    rows = db.rows("SELECT period, value FROM vision_points p WHERE series_id=? AND revision="
                   "(SELECT max(revision) FROM vision_points q WHERE q.series_id=p.series_id AND q.period=p.period) "
                   "ORDER BY period", [series_id])
    return [(r["period"], r["value"]) for r in rows]


def save_points(series_id: str, pts: list[tuple[str, float]]) -> dict:
    latest = {r["period"]: r for r in db.rows(
        "SELECT period, value, revision FROM vision_points p WHERE series_id=? AND revision="
        "(SELECT max(revision) FROM vision_points q WHERE q.series_id=p.series_id AND q.period=p.period)", [series_id])}
    added = revised = 0
    now = db.now()
    for p, v in pts:
        if p not in latest:
            db.insert("vision_points", {"series_id": series_id, "period": p, "value": v, "revision": 0, "fetched_at": now})
            added += 1
        elif abs(latest[p]["value"] - v) > 1e-9 * max(1.0, abs(v)):
            db.insert("vision_points", {"series_id": series_id, "period": p, "value": v,
                                        "revision": latest[p]["revision"] + 1, "fetched_at": now})
            revised += 1
    return {"added": added, "revised": revised}


def refresh_series(cfg: dict, cache: dict) -> dict:
    have = {p for p, _ in points(cfg["id"])} if cfg["source"] == "ak_boxoffice" else None
    return save_points(cfg["id"], src.fetch(cfg, cache, have))


# ---------- 统计与解读卡 ----------

def _stat_period(cfg: dict, pts: list[tuple[str, float]]) -> str:
    return vs.stat_points(cfg, pts)[-1][0]


def _related(cfg: dict) -> list[dict]:
    out = []
    for s in enabled():
        if s["id"] != cfg["id"] and (s["grp"] == cfg["grp"] or s["theme"] == cfg["theme"] == "ai" and s["grp"] in ("AI 与就业", "能力前沿")):
            if pts := points(s["id"]):
                out.append({**s, "period": pts[-1][0], "value": pts[-1][1]})
    return out[:16]


def _track(cfg: dict) -> list[dict]:
    """这个指标自己的判断，加上别的指标最近对过账的判断。"""
    return db.rows("SELECT p.*, v.actual, v.hit FROM vision_predictions p LEFT JOIN vision_verdicts v ON v.prediction_id=p.id "
                   "WHERE p.series_id=? ORDER BY p.id DESC LIMIT 12", [cfg["id"]]) + db.rows(
        "SELECT p.*, v.actual, v.hit FROM vision_predictions p JOIN vision_verdicts v ON v.prediction_id=p.id "
        "WHERE p.series_id!=? AND v.hit IS NOT NULL ORDER BY v.id DESC LIMIT 8", [cfg["id"]])


def start_card(series_id: str, *, feedback: str = "", attempt: int = 1, force: bool = False) -> int:
    cfg = BY_ID[series_id]
    pts = points(series_id)
    if not pts:
        raise ValueError("这个指标还没有数据")
    sig = vs.signals(cfg, pts)
    if force and not sig["reasons"]:
        sig["reasons"] = ["手动要求出卡"]
    summary = vs.summary(cfg, pts)
    cid = db.insert("vision_cards", {"series_id": series_id, "period": _stat_period(cfg, pts), "attempt": attempt,
                                     "score": sig["score"], "signals": sig, "summary": summary, "feedback": feedback,
                                     "status": "running", "created_at": db.now(), "updated_at": db.now()})
    prompt = vc.card_prompt(cfg, vs.stat_points(cfg, pts), summary, sig, _related(cfg), _track(cfg), feedback)
    jid = jobs.submit("vision", prompt, ref=f"vision:card:{cid}", tier="standard")
    db.update("vision_cards", cid, {"job_id": jid})
    return cid


def _fetch_text(url: str) -> tuple[int, str]:
    try:
        r = httpx.get(url, headers={"User-Agent": BROWSER_UA}, timeout=httpx.Timeout(25.0, connect=10.0), follow_redirects=True)
        return r.status_code, re.sub(r"<[^>]+>", " ", r.text)
    except httpx.HTTPError as e:
        return 0, str(e)


def _facts(card_row: dict) -> list[float]:
    cfg = BY_ID[card_row["series_id"]]
    by = {cfg["id"]: vs.stat_points(cfg, points(cfg["id"]))}
    for r in _related(cfg):
        by[r["id"]] = vs.stat_points(r, points(r["id"]))
    return vc.fact_numbers(by, _j(card_row["summary"], {}))


def _reject(c: dict, problems: list[str], **patch) -> None:
    db.update("vision_cards", c["id"], {"status": "rejected", "updated_at": db.now(), **patch})
    if c["attempt"] < MAX_ATTEMPTS:
        start_card(c["series_id"], feedback="\n".join(f"- {p}" for p in problems), attempt=c["attempt"] + 1)


def on_card_done(c: dict, job: dict) -> None:
    if job.get("status") != "done":
        db.update("vision_cards", c["id"], {"status": "failed", "updated_at": db.now()})
        return
    body = vc.parse_json(job.get("output") or "")
    if body is None:
        return _reject(c, ["输出不是 JSON 对象"], checks={"ok": False, "problems": ["输出不是 JSON 对象"]})
    res = vc.check(body, _facts(c), {s["id"] for s in enabled()}, _fetch_text)
    if not res["ok"]:
        return _reject(c, res["problems"], body=body, checks=res)
    rid = jobs.submit("vision", vc.review_prompt(BY_ID[c["series_id"]], body), ref=f"vision:review:{c['id']}", tier="standard")
    db.update("vision_cards", c["id"], {"body": body, "checks": res, "status": "reviewing", "review_job_id": rid, "updated_at": db.now()})


def on_review_done(c: dict, job: dict) -> None:
    if job.get("status") != "done":
        db.update("vision_cards", c["id"], {"status": "failed", "updated_at": db.now()})
        return
    rv = vc.parse_json(job.get("output") or "") or {"pass": False, "reason": "审稿输出不是 JSON"}
    if not rv.get("pass"):
        return _reject(c, ["审稿没通过：" + str(rv.get("reason") or "")], review=rv)
    db.update("vision_cards", c["id"], {"status": "done", "review": rv, "updated_at": db.now()})
    body = _j(c["body"], {})
    for p in body.get("predictions") or []:
        db.insert("vision_predictions", {"card_id": c["id"], "series_id": p["series_id"], "due_date": p["due"], "op": p["op"],
                                         "target": p["target"], "confidence": p["confidence"], "text": p.get("text", ""),
                                         "created_at": db.now()})
    cfg = BY_ID[c["series_id"]]
    if vs.should_notify(cfg, _j(c["signals"], {})):
        notify.notify("vision", body.get("title") or cfg["name"], body.get("plain", ""), _j(c["signals"], {}).get("reasons"),
                      link=f"#vision/{cfg['id']}", kind="card")


def on_job_done(job: dict) -> None:
    m = re.fullmatch(r"vision:(card|review):(\d+)", job.get("ref") or "")
    if not m:
        return
    c = db.row("SELECT * FROM vision_cards WHERE id=?", [int(m[2])])
    if c:
        (on_card_done if m[1] == "card" else on_review_done)(c, job)


def candidates() -> list[dict]:
    """每个指标只看最新一期：够显著、这一期还没出过卡（含进行中），按显著度排序。"""
    made = {(r["series_id"], r["period"]) for r in db.rows("SELECT DISTINCT series_id, period FROM vision_cards")}
    out = []
    for cfg in enabled():
        pts = points(cfg["id"])
        if len(pts) < 3:
            continue
        sig = vs.signals(cfg, pts)
        if sig["score"] > 0 and (cfg["id"], _stat_period(cfg, pts)) not in made:
            out.append({"series_id": cfg["id"], "score": sig["score"], "reasons": sig["reasons"]})
    return sorted(out, key=lambda x: -x["score"])


def verify_predictions(today: date | None = None) -> int:
    today = today or date.today()
    n = 0
    for p in db.rows("SELECT p.* FROM vision_predictions p LEFT JOIN vision_verdicts v ON v.prediction_id=p.id "
                     "WHERE v.id IS NULL AND p.due_date<=?", [today.isoformat()]):
        cfg = BY_ID.get(p["series_id"])
        due = date.fromisoformat(p["due_date"])
        after = [(q, v) for q, v in vs.stat_points(cfg, points(p["series_id"])) if vs.period_start(q) >= due] if cfg else []
        if after:
            q, v = after[0]
            db.insert("vision_verdicts", {"prediction_id": p["id"], "period": q, "actual": v,
                                          "hit": int(vs.judge(p["op"], v, p["target"])), "checked_at": db.now()})
            n += 1
        elif (today - due).days > EXPIRE_DAYS:
            db.insert("vision_verdicts", {"prediction_id": p["id"], "period": "", "actual": None, "hit": None, "checked_at": db.now()})
            n += 1
    return n


def run_daily(*, make_cards: bool = True) -> int:
    if not _lock.acquire(blocking=False):
        return 0
    try:
        rid = db.insert("vision_runs", {"day": db.today(), "status": "running", "started_at": db.now()})
        results, cache = {}, {}
        for cfg in enabled():
            try:
                results[cfg["id"]] = refresh_series(cfg, cache)
            except Exception as e:  # noqa: BLE001
                log.warning("vision fetch %s failed: %s", cfg["id"], e)
                results[cfg["id"]] = {"error": f"{type(e).__name__}: {str(e)[:200]}"}
        made = []
        if make_cards:
            today_n = db.row("SELECT count(*) AS n FROM vision_cards WHERE attempt=1 AND created_at>=?", [db.today()])["n"]
            for c in candidates()[:max(0, CARDS_PER_DAY - today_n)]:
                made.append(start_card(c["series_id"]))
        verify_predictions()
        db.update("vision_runs", rid, {"status": "done", "results": results, "cards": made, "finished_at": db.now()})
        return rid
    finally:
        _lock.release()


def _loop():
    time.sleep(180)
    while True:
        try:
            if not db.row("SELECT id FROM vision_runs WHERE day=? AND status='done'", [db.today()]):
                run_daily()
        except Exception:  # noqa: BLE001
            log.exception("vision daily run failed")
        time.sleep(1800)


def on_startup():
    if os.environ.get("SELF_STARTUP_NO_AUTOREFRESH"):
        return
    threading.Thread(target=_loop, daemon=True, name="vision-loop").start()


# ---------- 接口 ----------

def _card(c: dict) -> dict:
    return {**c, **{k: _j(c[k], {}) for k in ("signals", "summary", "body", "checks", "review")}}


def _series_view(cfg: dict, spark: int = 60) -> dict:
    pts = points(cfg["id"]) if cfg["status"] == "ok" else []
    sp = vs.stat_points(cfg, pts) if pts else []
    return {**cfg, "summary": vs.summary(cfg, pts) if pts else {}, "spark": sp[-spark:],
            "signals": vs.signals(cfg, pts) if len(pts) >= 3 else None}


def _hits() -> dict:
    out: dict = {}
    for r in db.rows("SELECT p.series_id, p.confidence, v.hit FROM vision_verdicts v JOIN vision_predictions p ON p.id=v.prediction_id "
                     "WHERE v.hit IS NOT NULL"):
        theme = BY_ID.get(r["series_id"], {}).get("theme", "")
        for k in (theme, f"conf:{r['confidence']}", "all"):
            o = out.setdefault(k, {"n": 0, "hits": 0})
            o["n"] += 1
            o["hits"] += r["hit"]
    return out


@router.get("/overview")
def overview():
    since = (date.today() - timedelta(days=30)).isoformat()
    cards = [_card(c) for c in db.rows("SELECT * FROM vision_cards WHERE status='done' AND created_at>=? ORDER BY score DESC, id DESC", [since])]
    pending = db.rows("SELECT p.*, v.actual, v.hit FROM vision_predictions p LEFT JOIN vision_verdicts v ON v.prediction_id=p.id "
                      "ORDER BY p.due_date LIMIT 50")
    return {"themes": [{"id": t, "title": n, "series": [_series_view(s) for s in SERIES if s["theme"] == t]} for t, n in THEMES],
            "cards": cards, "predictions": pending, "hits": _hits(), "status": status()}


@router.get("/series/{sid}")
def series(sid: str):
    cfg = BY_ID.get(sid)
    if not cfg:
        raise HTTPException(404, "没有这个指标")
    revisions = db.rows("SELECT period, value, revision, fetched_at FROM vision_points WHERE series_id=? AND revision>0 ORDER BY period DESC", [sid])
    cards = [_card(c) for c in db.rows("SELECT * FROM vision_cards WHERE series_id=? ORDER BY id DESC", [sid])]
    preds = db.rows("SELECT p.*, v.actual, v.hit, v.period AS verdict_period FROM vision_predictions p "
                    "LEFT JOIN vision_verdicts v ON v.prediction_id=p.id WHERE p.series_id=? ORDER BY p.id DESC", [sid])
    return {**_series_view(cfg, spark=100000), "points": points(sid), "revisions": revisions, "cards": cards, "predictions": preds}


@router.post("/refresh")
def refresh():
    threading.Thread(target=run_daily, daemon=True, name="vision-run").start()
    return {"ok": True}


@router.post("/series/{sid}/card")
def force_card(sid: str):
    if sid not in BY_ID:
        raise HTTPException(404, "没有这个指标")
    try:
        return {"card_id": start_card(sid, force=True)}
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.get("/status")
def status():
    run = db.row("SELECT * FROM vision_runs ORDER BY id DESC LIMIT 1")
    if run:
        run = {**run, "results": _j(run["results"], {}), "cards": _j(run["cards"], [])}
    counts = {r["status"]: r["n"] for r in db.rows("SELECT status, count(*) AS n FROM vision_cards GROUP BY status")}
    return {"run": run, "cards": counts, "series": {k: sum(s["status"] == k for s in SERIES) for k in ("ok", "todo", "extract", "existing")}}


def agent_context(ref: str) -> str:
    lines = ["视野板块当前指标快照（指标 id｜名称：最新期 = 值，单位）："]
    for cfg in enabled():
        if pts := points(cfg["id"]):
            lines.append(f"- {cfg['id']}｜{cfg['name']}：{pts[-1][0]} = {pts[-1][1]:g} {cfg['unit']}")
    for c in db.rows("SELECT * FROM vision_cards WHERE status='done' ORDER BY id DESC LIMIT 8"):
        b = _j(c["body"], {})
        lines.append(f"- 解读卡 {c['created_at'][:10]}：{b.get('title', '')}——{b.get('plain', '')}")
    return "\n".join(lines)
