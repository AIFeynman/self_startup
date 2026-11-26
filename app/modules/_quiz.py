"""复盘 · 考题卡：把划词批注、Claude 对话和已读历史变成问答题，按艾宾浩斯间隔复习；答错回到第 1 天，下次换一道同考点的变式题。
由 review.py 挂路由（/api/review/quiz），下划线开头的文件不会被当成独立板块。大模型走 DeepSeek，失败都有兜底。"""
from __future__ import annotations

import json
import threading
from datetime import date, timedelta
from itertools import zip_longest

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import db

SCHEMA = """
CREATE TABLE IF NOT EXISTS quiz_cards (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    src_kind    TEXT NOT NULL,                 -- ann 批注 / chat Claude 对话 / read 已读历史
    src_ref     TEXT NOT NULL,
    src_title   TEXT DEFAULT '',
    src_link    TEXT DEFAULT '',
    point       TEXT DEFAULT '',               -- 考点
    q           TEXT NOT NULL,
    answer      TEXT NOT NULL,                 -- 参考答案
    stage       INTEGER DEFAULT 0,             -- 连续答对次数，对应 INTERVALS 的下标
    due         TEXT NOT NULL,
    status      TEXT DEFAULT 'active',         -- active / mastered
    wrong       INTEGER DEFAULT 0,
    variant     INTEGER DEFAULT 0,             -- 第几道变式
    variant_pending INTEGER DEFAULT 0,         -- 答错了但变式还没出好
    last_at     TEXT DEFAULT '',
    created_at  TEXT,
    UNIQUE (src_kind, src_ref)
);
CREATE TABLE IF NOT EXISTS quiz_attempts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    card_id     INTEGER NOT NULL,
    q           TEXT NOT NULL,
    reply       TEXT DEFAULT '',
    score       INTEGER,
    verdict     TEXT NOT NULL,                 -- right / wrong / pending（判分没成功，等自己判）
    feedback    TEXT DEFAULT '',
    prev        TEXT DEFAULT '{}',             -- 作答前的 stage / due / wrong / status，改判时回退用
    at          TEXT
);
CREATE TABLE IF NOT EXISTS quiz_meta (k TEXT PRIMARY KEY, v TEXT);
"""

router = APIRouter()

INTERVALS = (1, 2, 4, 7, 15, 30)
DAILY = 10
HARVEST_MAX = 20
PASS = 6
BACKGROUND = True
MIN_MATERIAL = 60

CARD_SYSTEM = """你是用户的复习出题人。给你一份用户读过、评论过或问过 Claude 的材料，出 1 道问答题帮他记住最关键的一点。
要求：考理解和应用（为什么、怎么用、和什么不同），不考人名日期这类细节；用户自己的提问和评论最重要，优先考他问过的问题的答案；
题目 ≤60 字，参考答案 ≤200 字、只用材料里的事实；材料没有值得记的知识点时返回 {"skip": true}。
输出 JSON：{"point": "考点，≤15 字", "q": "题目", "answer": "参考答案"}"""

GRADE_SYSTEM = """你在批改一道复习问答题。对照参考答案看用户答到了几成要点，意思对就算，不要求措辞一致。
输出 JSON：{"score": 0-10 的整数, "feedback": "≤80 字：答对了什么、漏了什么"}"""

VARIANT_SYSTEM = """用户上次没答对这道复习题。围绕同一个考点出一道变式题：换一个角度、场景或问法（比如反过来问、放进具体场景、和相近概念对比），
不能只是改几个字，答案仍然只用给你的参考材料。输出 JSON：{"q": "新题目，≤60 字", "answer": "新参考答案，≤200 字"}"""

_lock = threading.Lock()
_busy: set[str] = set()


def _llm(system: str, payload: dict) -> dict:
    from ._intel_snap import _deepseek
    return _deepseek(system, payload, max_tokens=1500, module="quiz")


def _today() -> date:
    return date.fromisoformat(db.today())


def _in(days: int) -> str:
    return (_today() + timedelta(days=days)).isoformat()


def _has(table: str) -> bool:
    return bool(db.row("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", [table]))


def _cut(text: str, n: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= n else text[:n].rstrip() + "…"


# ---------- 素材 ----------

def _annotation_sources() -> list[dict]:
    if not _has("annotations"):
        return []
    from ..annotations import DEFAULT_QUESTION
    out = []
    for a in db.rows("SELECT * FROM annotations ORDER BY updated_at DESC"):
        msgs = db.rows("SELECT role, content, status FROM annotation_msgs WHERE annotation_id=? ORDER BY id", [a["id"]])
        if any(m["role"] == "assistant" and m["status"] == "pending" for m in msgs):
            continue
        asks = [m["content"] for m in msgs if m["role"] == "user" and (m["content"] or "").strip()]
        replies = [m["content"] for m in msgs if m["role"] == "assistant" and (m["content"] or "").strip()]
        if not asks:
            continue
        own = [x for x in asks if x != DEFAULT_QUESTION]
        quote = _cut(a["quote"], 80)
        if replies:
            q = f"关于「{quote}」：{own[0]}" if own and quote else own[0] if own else f"「{quote}」这段在说什么、为什么重要？"
            fb = {"q": _cut(q, 160), "answer": _cut(replies[0], 400)}
        else:
            fb = {"q": f"你在《{_cut(a['title'], 40)}》划线「{quote}」时写过评论，你当时的看法是什么？", "answer": _cut(asks[0], 400)}
        out.append({"kind": "ann", "ref": str(a["id"]), "title": a["title"] or a["doc"], "link": a["link"] or "",
                    "material": {"划线": a["quote"], "我的评论或提问": asks, "Claude 的回答": [_cut(r, 1500) for r in replies]},
                    "fallback": fb})
    return out


def _chat_sources() -> list[dict]:
    if not _has("chat_sessions"):
        return []
    out = []
    for s in db.rows("SELECT id, module, title FROM chat_sessions ORDER BY updated_at DESC"):
        msgs = db.rows("SELECT role, content FROM chat_messages WHERE session_id=? ORDER BY id", [s["id"]])
        asks = [m["content"] for m in msgs if m["role"] == "user" and (m["content"] or "").strip()]
        replies = [m["content"] for m in msgs if m["role"] == "assistant" and (m["content"] or "").strip()]
        if not asks or not replies:
            continue
        out.append({"kind": "chat", "ref": str(s["id"]), "title": s["title"] or "和 Claude 的对话", "link": f"#{s['module']}" if s["module"] else "",
                    "material": {"我的提问": [_cut(x, 600) for x in asks[:6]], "Claude 的回答": [_cut(x, 1500) for x in replies[:4]]},
                    "fallback": {"q": _cut(asks[0], 160), "answer": _cut(replies[0], 400)}})
    return out


def _read_text(kind: str, ref: str) -> str:
    if kind == "feed" and _has("feed_items") and (r := db.row("SELECT summary, extra FROM feed_items WHERE id=?", [ref])):
        try:
            gist = (json.loads(r["extra"] or "{}") or {}).get("gist") or ""
        except ValueError:
            gist = ""
        return "\n".join(x for x in (gist, r["summary"] or "") if x)
    if kind == "growth" and _has("intel_growth_case") and (r := db.row("SELECT content FROM intel_growth_case WHERE item_id=? ORDER BY id DESC", [ref])):
        return r["content"] or ""
    if kind == "intel_event" and _has("intel_analysis") and (r := db.row("SELECT content FROM intel_analysis WHERE event_id=? ORDER BY id DESC", [ref])):
        return r["content"] or ""
    return ""


def _read_sources() -> list[dict]:
    if not _has("read_log"):
        return []
    out = []
    for r in db.rows("SELECT kind, ref, title, url, max(at) at FROM read_log GROUP BY kind, ref ORDER BY max(id) DESC"):
        text = _read_text(r["kind"], r["ref"])
        if len(text) < MIN_MATERIAL:
            continue
        out.append({"kind": "read", "ref": f"{r['kind']}:{r['ref']}", "title": r["title"], "link": r["url"] or "",
                    "material": {"正文": _cut(text, 4000)}, "fallback": None})
    return out


def harvest(limit: int = HARVEST_MAX) -> int:
    have = {(r["src_kind"], r["src_ref"]) for r in db.rows("SELECT src_kind, src_ref FROM quiz_cards")}
    new = 0
    lists = [_annotation_sources(), _chat_sources(), _read_sources()]
    mixed = [x for group in zip_longest(*lists) for x in group if x]
    for src in mixed:
        if new >= limit:
            break
        if (src["kind"], src["ref"]) in have:
            continue
        card = None
        try:
            got = _llm(CARD_SYSTEM, {"来源": src["title"], **src["material"]})
            if not got.get("skip") and str(got.get("q") or "").strip() and str(got.get("answer") or "").strip():
                card = {"point": _cut(str(got.get("point") or ""), 30), "q": _cut(str(got["q"]), 200), "answer": _cut(str(got["answer"]), 600)}
        except Exception:  # noqa: BLE001  出题失败：有现成问答的直接用，没有的下次再试
            card = None
        card = card or ({"point": "", **src["fallback"]} if src["fallback"] else None)
        if not card:
            continue
        db.execute("INSERT OR IGNORE INTO quiz_cards (src_kind, src_ref, src_title, src_link, point, q, answer, due, created_at) "
                   "VALUES (?,?,?,?,?,?,?,?,?)",
                   [src["kind"], src["ref"], _cut(src["title"], 120), src["link"], card["point"], card["q"], card["answer"], _in(1), db.now()])
        have.add((src["kind"], src["ref"]))
        new += 1
    db.execute("INSERT OR REPLACE INTO quiz_meta (k, v) VALUES ('harvest_day', ?)", [db.today()])
    return new


def _run(key: str, fn, *args) -> None:
    with _lock:
        if key in _busy:
            return
        _busy.add(key)

    def go():
        try:
            fn(*args)
        finally:
            with _lock:
                _busy.discard(key)
    if BACKGROUND:
        threading.Thread(target=go, daemon=True, name=f"quiz-{key}").start()
    else:
        go()


# ---------- 排期 ----------

def _schedule(card: dict, verdict: str) -> dict:
    if verdict == "right":
        stage = card["stage"] + 1
        if stage >= len(INTERVALS):
            return {"stage": stage, "status": "mastered", "due": _in(INTERVALS[-1]), "wrong": card["wrong"]}
        return {"stage": stage, "status": "active", "due": _in(INTERVALS[stage]), "wrong": card["wrong"]}
    return {"stage": 0, "status": "active", "due": _in(INTERVALS[0]), "wrong": card["wrong"] + 1}


def _make_variant(cid: int) -> None:
    c = db.row("SELECT * FROM quiz_cards WHERE id=?", [cid])
    if not c or not c["variant_pending"]:
        return
    try:
        got = _llm(VARIANT_SYSTEM, {"考点": c["point"], "原题": c["q"], "参考答案": c["answer"], "来源": c["src_title"]})
        q, ans = str(got.get("q") or "").strip(), str(got.get("answer") or "").strip()
    except Exception:  # noqa: BLE001  变式没出成：保留原题，下次打开页面再试
        return
    if q and ans and q != c["q"]:
        db.execute("UPDATE quiz_cards SET q=?, answer=?, variant=variant+1, variant_pending=0 WHERE id=?",
                   [_cut(q, 200), _cut(ans, 600), cid])


def _apply(card: dict, verdict: str) -> dict:
    nxt = _schedule(card, verdict)
    db.execute("UPDATE quiz_cards SET stage=?, status=?, due=?, wrong=?, last_at=?, variant_pending=? WHERE id=?",
               [nxt["stage"], nxt["status"], nxt["due"], nxt["wrong"], db.now(), 1 if verdict == "wrong" else 0, card["id"]])
    if verdict == "wrong":
        _run(f"variant:{card['id']}", _make_variant, card["id"])
    return nxt


def _public(c: dict) -> dict:
    return {k: c[k] for k in ("id", "q", "point", "src_kind", "src_title", "src_link", "stage", "variant", "wrong", "due", "status")}


@router.get("/quiz")
def quiz():
    today = db.today()
    meta = db.row("SELECT v FROM quiz_meta WHERE k='harvest_day'")
    if not meta or meta["v"] != today:
        _run("harvest", harvest)
    rows = db.rows("SELECT * FROM quiz_cards WHERE status='active' AND due<=? ORDER BY (wrong>0) DESC, wrong DESC, due, id", [today])
    for c in rows[:DAILY]:
        if c["variant_pending"]:
            _run(f"variant:{c['id']}", _make_variant, c["id"])
    n = lambda sql, *a: db.row(f"SELECT count(*) n FROM quiz_cards WHERE {sql}", list(a))["n"]  # noqa: E731
    wrongbook = db.rows("SELECT * FROM quiz_cards WHERE wrong>0 ORDER BY last_at DESC LIMIT 20")
    return {
        "due": [_public(c) for c in rows[:DAILY]],
        "stats": {"due": len(rows), "active": n("status='active'"), "mastered": n("status='mastered'"), "wrongbook": n("wrong>0"),
                  "done_today": db.row("SELECT count(DISTINCT card_id) n FROM quiz_attempts WHERE substr(at,1,10)=? AND verdict!='pending'", [today])["n"],
                  "tomorrow": n("status='active' AND due=?", _in(1))},
        "harvesting": "harvest" in _busy,
        "wrongbook": [{**_public(c), "answer": c["answer"]} for c in wrongbook],
        "intervals": INTERVALS,
    }


@router.post("/quiz/harvest")
def harvest_now():
    return {"new": harvest()}


class AnswerIn(BaseModel):
    answer: str = ""
    dont_know: bool = False


@router.post("/quiz/{cid}/answer")
def answer(cid: int, body: AnswerIn):
    c = db.row("SELECT * FROM quiz_cards WHERE id=?", [cid])
    if not c:
        raise HTTPException(404, "没有这张考题卡")
    reply = body.answer.strip()
    score, feedback = None, ""
    if body.dont_know or not reply:
        verdict, feedback = "wrong", "标了不会"
    else:
        try:
            g = _llm(GRADE_SYSTEM, {"题目": c["q"], "参考答案": c["answer"], "用户的回答": reply})
            score = max(0, min(10, int(g.get("score"))))
            feedback = str(g.get("feedback") or "")
            verdict = "right" if score >= PASS else "wrong"
        except Exception:  # noqa: BLE001  判分没成功：给参考答案，让用户自己判
            verdict, feedback = "pending", "自动判分没成功，对照参考答案自己判一下"
    prev = {k: c[k] for k in ("stage", "due", "wrong", "status")}
    db.insert("quiz_attempts", {"card_id": cid, "q": c["q"], "reply": reply, "score": score, "verdict": verdict,
                                "feedback": feedback, "prev": json.dumps(prev), "at": db.now()})
    nxt = _apply(c, verdict) if verdict != "pending" else None
    return {"verdict": verdict, "score": score, "feedback": feedback, "answer": c["answer"], "point": c["point"],
            "next_due": nxt["due"] if nxt else None, "mastered": bool(nxt and nxt["status"] == "mastered")}


class OverrideIn(BaseModel):
    verdict: str


@router.post("/quiz/{cid}/override")
def override(cid: int, body: OverrideIn):
    if body.verdict not in ("right", "wrong"):
        raise HTTPException(400, "verdict 只能是 right / wrong")
    a = db.row("SELECT * FROM quiz_attempts WHERE card_id=? ORDER BY id DESC", [cid])
    c = db.row("SELECT * FROM quiz_cards WHERE id=?", [cid])
    if not a or not c:
        raise HTTPException(404, "还没作答过")
    before = {**c, **json.loads(a["prev"] or "{}")}
    nxt = _apply(before, body.verdict)
    db.execute("UPDATE quiz_attempts SET verdict=?, feedback=feedback || ? WHERE id=?",
               [body.verdict, "（改判）" if a["verdict"] != "pending" else "（自己判）", a["id"]])
    return {"verdict": body.verdict, "next_due": nxt["due"], "mastered": nxt["status"] == "mastered"}
