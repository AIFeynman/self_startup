"""青少年：每天两个题材（一个时事、一个往事），从现象看到背后的问题，练思辨和感同身受。

链路：每天一轮 → 后台 Claude 查权威来源、出题（提示词里带最近题材和孩子的作答反馈）→ 程序校验
（结构、来源链接可开、时事日期、题数和层级）→ 通过才展示；不通过带原因重出，最多 3 次。
作答、想法、改进意见都只追加不覆盖。
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import db, jobs
from . import _teen as tn
from . import _vision_sources as src
from ._feed_sources import BROWSER_UA

log = logging.getLogger(__name__)

TITLE = "青少年"
ORDER = 37
PAGE = "vision/teen"  # 没有自己的侧边栏入口，是视野里的一个标签页
SCHEMA = """
CREATE TABLE IF NOT EXISTS teen_days (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    day         TEXT,
    attempt     INTEGER DEFAULT 1,
    status      TEXT DEFAULT 'running',      -- running / done / rejected / failed
    problems    TEXT DEFAULT '[]',
    job_id      INTEGER,
    created_at  TEXT,
    updated_at  TEXT
);
CREATE TABLE IF NOT EXISTS teen_items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    day_id      INTEGER,
    day         TEXT,
    idx         INTEGER,
    kind        TEXT,
    domain      TEXT,
    headline    TEXT,
    body        TEXT DEFAULT '{}',
    created_at  TEXT
);
CREATE TABLE IF NOT EXISTS teen_replies (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id     INTEGER,
    qidx        INTEGER,                     -- 第几题（0 起）；-1 = 整个题材
    kind        TEXT,                        -- answer 我的作答 / thought 我想到了 / improve 改进意见
    content     TEXT,
    self_score  INTEGER,                     -- 自评：0 没想到 / 1 想到一部分 / 2 想全了（只有 answer 有）
    created_at  TEXT
);
"""
MAX_ATTEMPTS = 3
REPLY_KINDS = ("answer", "thought", "improve")

router = APIRouter()
_lock = threading.Lock()


def _j(v, default):
    try:
        return json.loads(v) if isinstance(v, str) else (v if v is not None else default)
    except json.JSONDecodeError:
        return default


def _fetch_text(url: str) -> tuple[int, str]:
    # 维基媒体的 UA 政策拒绝伪装成浏览器的程序请求，要带联系方式的 UA
    ua = src.UA if re.search(r"(^|\.)(wikipedia|wikimedia)\.org$", httpx.URL(url).host) else BROWSER_UA
    try:
        r = httpx.get(url, headers={"User-Agent": ua}, timeout=httpx.Timeout(25.0, connect=10.0), follow_redirects=True)
        return r.status_code, re.sub(r"<[^>]+>", " ", r.text)
    except httpx.HTTPError as e:
        return 0, str(e)


def _recent_items(limit: int = 24) -> list[dict]:
    return db.rows("SELECT i.day, i.kind, i.domain, i.headline FROM teen_items i JOIN teen_days d ON d.id=i.day_id "
                   "WHERE d.status='done' ORDER BY i.id DESC LIMIT ?", [limit])


def feedback_digest() -> dict:
    scores: dict = {}
    for r in db.rows("SELECT i.body, r.qidx, r.self_score FROM teen_replies r JOIN teen_items i ON i.id=r.item_id "
                     "WHERE r.kind='answer' AND r.self_score IS NOT NULL ORDER BY r.id DESC LIMIT 200"):
        qs = _j(r["body"], {}).get("questions") or []
        if 0 <= r["qidx"] < len(qs):
            o = scores.setdefault((qs[r["qidx"]]["level"], qs[r["qidx"]]["ability"]), {"sum": 0, "n": 0})
            o["sum"] += r["self_score"]
            o["n"] += 1
    scores = {k: {"avg": v["sum"] / v["n"], "n": v["n"]} for k, v in sorted(scores.items())}
    pick = lambda kind: [r["content"][:200] for r in db.rows(  # noqa: E731
        "SELECT content FROM teen_replies WHERE kind=? AND content!='' ORDER BY id DESC LIMIT 8", [kind])]
    return {"scores": scores, "improve": pick("improve"), "thoughts": pick("thought")}


def start_day(*, redo: str = "", attempt: int = 1, day: str | None = None) -> int:
    day = day or db.today()
    did = db.insert("teen_days", {"day": day, "attempt": attempt, "status": "running", "created_at": db.now(), "updated_at": db.now()})
    jid = jobs.submit("teen", tn.day_prompt(_recent_items(), feedback_digest(), redo), ref=f"teen:day:{did}", tier="standard")
    db.update("teen_days", did, {"job_id": jid})
    return did


def on_job_done(job: dict) -> None:
    m = re.fullmatch(r"teen:day:(\d+)", job.get("ref") or "")
    d = m and db.row("SELECT * FROM teen_days WHERE id=?", [int(m[1])])
    if not d:
        return
    if job.get("status") != "done":
        return db.update("teen_days", d["id"], {"status": "failed", "updated_at": db.now()})
    out = tn.parse(job.get("output") or "")
    res = tn.check(out, _fetch_text) if out else {"ok": False, "problems": ["输出不是 JSON 对象"]}
    if not res["ok"]:
        db.update("teen_days", d["id"], {"status": "rejected", "problems": res["problems"], "updated_at": db.now()})
        if d["attempt"] < MAX_ATTEMPTS:
            start_day(redo="\n".join(f"- {p}" for p in res["problems"]), attempt=d["attempt"] + 1, day=d["day"])
        return
    for n, it in enumerate(out["items"]):
        db.insert("teen_items", {"day_id": d["id"], "day": d["day"], "idx": n, "kind": it["kind"], "domain": it["domain"],
                                 "headline": it["headline"], "body": it, "created_at": db.now()})
    db.update("teen_days", d["id"], {"status": "done", "updated_at": db.now()})


def today_ready() -> bool:
    return bool(db.row("SELECT id FROM teen_days WHERE day=? AND status IN ('done','running')", [db.today()])) or bool(
        db.row("SELECT count(*) n FROM teen_days WHERE day=? AND status IN ('rejected','failed') HAVING n>=?", [db.today(), MAX_ATTEMPTS]))


def _loop():
    time.sleep(240)
    while True:
        try:
            if not today_ready():
                start_day()
        except Exception:  # noqa: BLE001
            log.exception("teen daily run failed")
        time.sleep(1800)


def on_startup():
    if os.environ.get("SELF_STARTUP_NO_AUTOREFRESH"):
        return
    threading.Thread(target=_loop, daemon=True, name="teen-loop").start()


# ---------- 接口 ----------

def _item(r: dict) -> dict:
    return {**r, "body": _j(r["body"], {}),
            "replies": db.rows("SELECT * FROM teen_replies WHERE item_id=? ORDER BY id", [r["id"]])}


@router.get("/overview")
def overview(days: int = 14):
    ds = db.rows("SELECT DISTINCT day FROM teen_days WHERE status='done' ORDER BY day DESC LIMIT ?", [max(1, min(days, 60))])
    out = []
    for d in ds:
        did = db.row("SELECT id FROM teen_days WHERE day=? AND status='done' ORDER BY id DESC", [d["day"]])["id"]
        out.append({"day": d["day"], "items": [_item(r) for r in db.rows("SELECT * FROM teen_items WHERE day_id=? ORDER BY idx", [did])]})
    last = db.row("SELECT * FROM teen_days ORDER BY id DESC")
    if last:
        last = {**last, "problems": _j(last["problems"], [])}
    fb = feedback_digest()
    return {"days": out, "last": last, "today": db.today(),
            "scores": [{"level": k[0], "ability": k[1], **v} for k, v in fb["scores"].items()]}


class Reply(BaseModel):
    qidx: int = -1
    kind: str
    content: str = ""
    self_score: int | None = None


@router.post("/items/{iid}/reply")
def reply(iid: int, body: Reply):
    it = db.row("SELECT id FROM teen_items WHERE id=?", [iid])
    if not it:
        raise HTTPException(404, "没有这个题材")
    if body.kind not in REPLY_KINDS or (body.self_score is not None and body.self_score not in (0, 1, 2)):
        raise HTTPException(400, "类型或自评不对")
    if not body.content.strip() and body.self_score is None:
        raise HTTPException(400, "没有内容")
    rid = db.insert("teen_replies", {"item_id": iid, "qidx": body.qidx, "kind": body.kind, "content": body.content.strip(),
                                     "self_score": body.self_score, "created_at": db.now()})
    return {"id": rid}


@router.post("/refresh")
def refresh():
    if not _lock.acquire(blocking=False):
        return {"ok": False}
    try:
        if db.row("SELECT id FROM teen_days WHERE day=? AND status='running'", [db.today()]):
            return {"ok": False, "reason": "正在出题"}
        return {"ok": True, "id": start_day()}
    finally:
        _lock.release()


def agent_context(ref: str) -> str:
    lines = ["青少年板块最近的题材："]
    for r in _recent_items(8):
        lines.append(f"- {r['day']} {r['kind']}｜{r['domain']}｜{r['headline']}")
    return "\n".join(lines)
