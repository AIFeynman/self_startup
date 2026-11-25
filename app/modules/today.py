"""今日：每天 3 张精读 + 约 5 张速览 + 开奖。

只读复用现有栏目的产物（产品雷达解读卡、增长 Case、信息推荐的论文和 HN、X 长文），不改它们；
判断写进现有判断台账（kb_judge.add），其余记录（精读做没做、没增量、机会卡）存在本板块自己的表里。
当天的选卡第一次打开时定下来存进 today_days，当天再开不变；看过的条目以后不再出现。
设计稿：docs/designs/2026-11-25-daily-learning-system.html。
"""
from __future__ import annotations

import json
import re
from datetime import date, timedelta

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import db, kb_judge

TITLE = "今日"
ORDER = 6
SCHEMA = """
CREATE TABLE IF NOT EXISTS today_days (day TEXT PRIMARY KEY, payload TEXT DEFAULT '{}', created_at TEXT);
CREATE TABLE IF NOT EXISTS today_marks (
    id INTEGER PRIMARY KEY AUTOINCREMENT, key TEXT NOT NULL, day TEXT NOT NULL,
    action TEXT NOT NULL,                       -- judge / guess / read
    note TEXT DEFAULT '', created_at TEXT
);
CREATE TABLE IF NOT EXISTS today_feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT, key TEXT NOT NULL, day TEXT NOT NULL,
    value TEXT NOT NULL,                        -- no_gain / useful
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS today_opps (           -- 机会卡：想到 → 写透 → 验证过 → 放弃 / 推进
    id INTEGER PRIMARY KEY AUTOINCREMENT, key TEXT DEFAULT '', day TEXT DEFAULT '',
    title TEXT NOT NULL, change TEXT DEFAULT '', pain TEXT DEFAULT '', who TEXT DEFAULT '',
    why_now TEXT DEFAULT '', fit TEXT DEFAULT '', test TEXT DEFAULT '', prob INTEGER,
    status TEXT DEFAULT 'idea', note TEXT DEFAULT '', created_at TEXT, updated_at TEXT
);
"""
router = APIRouter()

DEEP_N, QUICK_MAX, WINDOW_DAYS = 3, 9, 3
QUICK_QUOTA = {"product": 2, "tech": 2, "eng": 2}
BROKEN = re.compile(r"weekly limit|hit your .{0,20}limit|不是我这次改的|我保留不动|rate limit|traceback", re.I)
LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
RELATES = [
    ("你的讲解视频产品", re.compile(r"视频|讲解|动效|剪辑|创作者|知识类|video|creator", re.I)),
    ("AI teams / 学习平台", re.compile(r"harness|多 ?agent|multi-agent|子 ?agent|subagent|记忆|memory|评测|\beval|skill|技能|mcp|"
                                       r"claude code|codex|coding agent|编码 ?agent|插件", re.I)),
    ("基座机制", re.compile(r"attention|注意力|\bmoe\b|量化|quantiz|强化学习|\brl\b|蒸馏|distill|预训练|pretrain|kv ?cache|"
                          r"投机解码|speculative|loop transformer|scaling law", re.I)),
    ("增长", re.compile(r"增长|拉新|留存|获客|投放|growth|retention|onboarding|funnel|acquisition", re.I)),
]
QUICK_S_MAX = 5
TECH_HINT = re.compile(r"agent|harness|memory|eval|benchmark|reasoning|\brl\b|reinforcement|attention|moe|distill|coding|tool", re.I)


def _has(table: str) -> bool:
    return bool(db.row("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", [table]))


def _plain(text: str, limit: int = 0) -> str:
    t = LINK.sub(r"\1", text or "")
    t = re.sub(r"\*\*【推测】\*\*|\*\*", "", t).strip()
    return t if not limit or len(t) <= limit else t[: limit - 1].rstrip() + "…"


def _first_bullet(text: str) -> str:
    for line in (text or "").splitlines():
        line = line.strip().lstrip("-0123456789.、 ").strip()
        if line:
            return _plain(line, 140)
    return ""


def _md_sections(content: str) -> dict:
    out, cur = {}, None
    for line in (content or "").splitlines():
        if line.startswith("## "):
            cur = line[3:].strip()
            out[cur] = []
        elif cur:
            out[cur].append(line)
    return {k: "\n".join(v).strip() for k, v in out.items()}


def _relates(*texts: str) -> list[str]:
    blob = " ".join(t or "" for t in texts)
    return [name for name, rx in RELATES if rx.search(blob)]


def _uniq(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


def _prediction(so_what: str) -> str:
    m = re.search(r"可验证预测\*{0,2}[：:]\s*(.+)", so_what or "")
    return _plain(m.group(1), 300) if m else ""


def _good_card(content: str, sections: dict, complete) -> bool:
    return bool(complete) and len(content or "") >= 500 and bool(sections.get("变了什么")) and not BROKEN.search(content or "")


# ---------- 候选池：只读现有栏目 ----------

def _products(day: str) -> list[dict]:
    if not (_has("intel_event") and _has("intel_analysis")):
        return []
    since = (date.fromisoformat(day) - timedelta(days=WINDOW_DAYS)).isoformat()
    rows = db.rows(
        "SELECT e.id, e.title, e.level, e.date, c.name company, a.content, a.sections, a.complete FROM intel_event e "
        "JOIN intel_analysis a ON a.id=(SELECT MAX(id) FROM intel_analysis WHERE event_id=e.id) "
        "LEFT JOIN intel_company c ON c.id=e.company_id "
        "WHERE e.level IN ('S','A') AND e.merged_into IS NULL AND e.date>=? AND e.date<=? "
        "ORDER BY CASE e.level WHEN 'S' THEN 0 ELSE 1 END, e.date DESC, e.id DESC", [since, day])
    out = []
    for r in rows:
        try:
            sec = json.loads(r["sections"] or "{}")
        except ValueError:
            sec = {}
        if not _good_card(r["content"], sec, r["complete"]):
            continue
        pred = _prediction(sec.get("所以呢", ""))
        due = (DATE.search(pred).group(0) if pred and DATE.search(pred) else
               (date.fromisoformat(day) + timedelta(days=90)).isoformat())
        out.append({
            "key": f"intel:{r['id']}", "kind": "product", "label": f"产品 · {r['level']} 级", "level": r["level"],
            "title": r["title"], "company": r["company"] or "", "date": r["date"],
            "summary": _first_bullet(sec.get("变了什么", "")), "prediction": pred, "due": due,
            "question": "这条预测会兑现吗？" if pred else "这件事对你重要吗？30 天内会有别家跟进吗？",
            "reveal": {k: _plain(sec[k], 900) for k in ("用户问题", "产品逻辑", "商业逻辑", "所以呢") if sec.get(k)},
            "relates": _relates(r["title"], sec.get("变了什么", ""), sec.get("用户问题", "")),
            "link": f"#intel/e/{r['id']}",
        })
    return out


def _growth(day: str) -> list[dict]:
    if not _has("intel_growth_case"):
        return []
    rows = db.rows(
        "SELECT c.id, c.item_id, c.day, c.company, c.content, i.title FROM intel_growth_case c "
        "LEFT JOIN intel_growth_item i ON i.id=c.item_id "
        "WHERE c.status='done' AND c.complete=1 AND c.day<=? AND c.id=(SELECT MAX(id) FROM intel_growth_case WHERE item_id=c.item_id) "
        "ORDER BY c.day DESC, c.id DESC LIMIT 30", [day])
    out = []
    for r in rows:
        sec = _md_sections(r["content"])
        if not sec.get("一句话") or BROKEN.search(r["content"] or ""):
            continue
        out.append({
            "key": f"growth:{r['item_id']}", "kind": "growth", "label": "增长 Case", "title": r["title"] or r["company"],
            "company": r["company"] or "", "date": r["day"], "summary": "",
            "question": "先猜：它主要靠哪个动作起效？大概做到了什么量级？",
            "reveal": {k: _plain(sec[k], 900) for k in ("一句话", "背景与数字", "触达动作", "我能怎么用") if sec.get(k)},
            "relates": _uniq(["增长"] + _relates(r["title"] or "", sec.get("一句话", ""))),
            "link": f"#intel/g/{r['id']}",
        })
    return out


def _papers(day: str) -> list[dict]:
    if not _has("feed_items"):
        return []
    since = (date.fromisoformat(day) - timedelta(days=WINDOW_DAYS)).isoformat()
    rows = db.rows("SELECT id, title, summary, url, date, popularity, extra FROM feed_items "
                   "WHERE source IN ('hf','alphaxiv','arxiv') AND substr(date,1,10)>=? AND substr(date,1,10)<=?", [since, day])
    out = []
    for r in rows:
        try:
            ex = json.loads(r["extra"] or "{}")
        except ValueError:
            ex = {}
        gist = ex.get("gist") or ""
        score = (r["popularity"] or 0) + (30 if TECH_HINT.search(f"{r['title']} {r['summary']}") else 0) + (10 if gist else 0)
        out.append({
            "key": f"feed:{r['id']}", "kind": "tech", "label": "论文", "title": r["title"], "date": (r["date"] or "")[:10],
            "summary": gist or _plain(r["summary"], 160), "score": score, "url": r["url"],
            "question": "值得深读吗？如果是你，会换成什么做法（为什么不 XX）？",
            "reveal": {}, "relates": _relates(r["title"], r["summary"], gist), "link": r["url"],
        })
    out.sort(key=lambda c: -c["score"])
    return out


def _engineering(day: str) -> list[dict]:
    since = (date.fromisoformat(day) - timedelta(days=WINDOW_DAYS)).isoformat()
    out = []
    if _has("x_art"):
        for r in db.rows("SELECT id, user, title, summary, take, day FROM x_art WHERE q>=4 AND day>=? AND day<=? "
                         "ORDER BY q DESC, views DESC LIMIT 20", [since, day]):
            out.append({"key": f"xart:{r['id']}", "kind": "eng", "label": "工程实践 · X 长文", "title": r["title"] or r["summary"][:60],
                        "date": r["day"], "summary": _plain(r["summary"], 160), "takeaway": _plain(r["take"], 160),
                        "reveal": {}, "relates": _relates(r["title"], r["summary"], r["take"]), "link": "#kb/xart"})
    if _has("feed_items"):
        for r in db.rows("SELECT id, title, url, date, popularity, extra FROM feed_items WHERE source='hn' AND popularity>=100 "
                         "AND substr(date,1,10)>=? AND substr(date,1,10)<=? ORDER BY popularity DESC LIMIT 20", [since, day]):
            gist = (json.loads(r["extra"] or "{}") or {}).get("gist") or ""
            if gist:
                out.append({"key": f"feed:{r['id']}", "kind": "eng", "label": "工程实践 · HN", "title": r["title"],
                            "date": (r["date"] or "")[:10], "summary": gist, "reveal": {}, "relates": _relates(r["title"], gist),
                            "link": r["url"]})
    return out


# ---------- 选卡 ----------

def _seen_before(day: str) -> set[str]:
    keys = set()
    for r in db.rows("SELECT payload FROM today_days WHERE day<?", [day]):
        p = json.loads(r["payload"] or "{}")
        keys.update(c["key"] for c in p.get("deep", []) + p.get("quick", []))
    for t in ("today_marks", "today_feedback"):
        keys.update(r["key"] for r in db.rows(f"SELECT key FROM {t} WHERE day<?", [day]))
    return keys


def pick(day: str) -> dict:
    seen = _seen_before(day)
    pools = {k: [c for c in f(day) if c["key"] not in seen] for k, f in
             (("product", _products), ("growth", _growth), ("tech", _papers), ("eng", _engineering))}
    deep = [pools[k].pop(0) for k in ("product", "tech", "growth") if pools[k]][:DEEP_N]
    s_level = [c for c in pools["product"] if c["level"] == "S"][:QUICK_S_MAX]
    others = pools["tech"][:QUICK_QUOTA["tech"]] + pools["eng"][:QUICK_QUOTA["eng"]]
    a_level = [c for c in pools["product"] if c["level"] != "S"][:QUICK_QUOTA["product"]]
    quick = (s_level + others + a_level)[:QUICK_MAX]
    return {"deep": deep, "quick": quick}


def _payload(day: str, refresh: bool = False) -> dict:
    r = db.row("SELECT payload FROM today_days WHERE day=?", [day])
    if r and not refresh:
        return json.loads(r["payload"])
    p = pick(day)
    db.execute("INSERT OR REPLACE INTO today_days (day, payload, created_at) VALUES (?,?,?)",
               [day, json.dumps(p, ensure_ascii=False), db.now()])
    return p


def _card(key: str) -> dict:
    for r in db.rows("SELECT payload FROM today_days ORDER BY day DESC"):
        p = json.loads(r["payload"] or "{}")
        for c in p.get("deep", []) + p.get("quick", []):
            if c["key"] == key:
                return c
    raise HTTPException(404, "card not found")


def _due() -> list[dict]:
    try:
        due = kb_judge.ledger_json().get("due", [])
    except Exception:  # noqa: BLE001  台账依赖概念图谱，出错时只用直接记的判断，不挡今日卡
        due = []
    out = [{k: c.get(k) for k in ("sid", "title", "claim", "due", "type", "link")} for c in due]
    have = {c["sid"] for c in out}
    if _has("kb_judgments"):   # 刚记的判断要等概念图谱整理后才进台账，到期的直接补上
        reviewed = {r["sid"] for r in db.rows("SELECT DISTINCT sid FROM kb_claim_reviews")} if _has("kb_claim_reviews") else set()
        for r in db.rows("SELECT id, text, type, due FROM kb_judgments WHERE due!='' AND due<=? ORDER BY due", [db.today()]):
            sid = f"my:{r['id']}"
            if sid not in have and sid not in reviewed:
                out.append({"sid": sid, "title": _plain(r["text"], 60), "claim": r["text"], "due": r["due"], "type": r["type"], "link": "#kb"})
    return sorted(out, key=lambda c: c["due"] or "")[:10]


@router.get("")
def today(day: str = "", refresh: int = 0, due: int = 1):
    day = (day or db.today())[:10]
    p = _payload(day, bool(refresh))
    marks = {r["key"]: r for r in db.rows("SELECT key, action, note FROM today_marks WHERE day=? ORDER BY id", [day])}
    fb = {r["key"]: r["value"] for r in db.rows("SELECT key, value FROM today_feedback WHERE day=? ORDER BY id", [day])}
    for c in p["deep"] + p["quick"]:
        m = marks.get(c["key"])
        c["done"] = bool(m)
        c["guess"] = m["note"] if m and m["action"] == "guess" else ""
        c["feedback"] = fb.get(c["key"], "")
    due = _due() if due else None   # 开奖要算整本台账（约 1.5 秒），卡片上的操作刷新时不重算
    return {
        "day": day, "deep": p["deep"], "quick": p["quick"], "all": p["deep"] + p["quick"], "due": due,
        "progress": {"deep_total": len(p["deep"]), "deep_done": sum(c["done"] for c in p["deep"]),
                     "quick_total": len(p["quick"]), "due": len(due) if due is not None else None,
                     "no_gain": sum(v == "no_gain" for v in fb.values()),
                     "opps": db.row("SELECT COUNT(*) n FROM today_opps WHERE day=?", [day])["n"]},
    }


class JudgeIn(BaseModel):
    key: str
    text: str
    prob: int | None = None
    reason: str = ""
    due: str = ""
    day: str = ""


@router.post("/judge")
def judge(body: JudgeIn):
    c = _card(body.key)
    prob = None if body.prob is None else max(0, min(100, body.prob))
    conf = "" if prob is None else ("高" if prob >= 70 or prob <= 30 else "中")
    note = "今日卡" + (f" · 概率 {prob}%" if prob is not None else "") + (f" · 理由：{body.reason.strip()}" if body.reason.strip() else "")
    try:
        jid = kb_judge.add(body.text, "预测" if prob is not None else "观点", conf, body.due or c.get("due", ""), note,
                           [{"title": c["title"], "link": c["link"]} if c["link"].startswith("#") else {"title": c["title"], "url": c["link"]}])
    except ValueError:
        raise HTTPException(400, "empty")
    try:
        from .. import kb_graph
        kb_graph.schedule_refresh()
    except Exception:  # noqa: BLE001
        pass
    db.insert("today_marks", {"key": body.key, "day": (body.day or db.today())[:10], "action": "judge",
                              "note": f"my:{jid}", "created_at": db.now()})
    return {"ok": True, "sid": f"my:{jid}"}


class GuessIn(BaseModel):
    key: str
    text: str = ""
    action: str = "guess"
    day: str = ""


@router.post("/guess")
def guess(body: GuessIn):
    _card(body.key)
    db.insert("today_marks", {"key": body.key, "day": (body.day or db.today())[:10],
                              "action": body.action if body.action in ("guess", "read") else "guess",
                              "note": body.text.strip()[:500], "created_at": db.now()})
    return {"ok": True}


class FeedbackIn(BaseModel):
    key: str
    value: str
    day: str = ""


@router.post("/feedback")
def feedback(body: FeedbackIn):
    if body.value not in ("no_gain", "useful"):
        raise HTTPException(400, "value")
    db.insert("today_feedback", {"key": body.key, "day": (body.day or db.today())[:10], "value": body.value, "created_at": db.now()})
    return {"ok": True}


class OppIn(BaseModel):
    key: str = ""
    title: str
    change: str = ""
    pain: str = ""
    who: str = ""
    why_now: str = ""
    fit: str = ""
    test: str = ""
    prob: int | None = None
    day: str = ""


@router.post("/opps")
def add_opp(body: OppIn):
    if not body.title.strip():
        raise HTTPException(400, "title")
    data = body.model_dump()
    data["day"] = (body.day or db.today())[:10]
    data["title"] = body.title.strip()
    oid = db.insert("today_opps", {**data, "status": "idea", "created_at": db.now(), "updated_at": db.now()})
    return {"ok": True, "id": oid}


@router.get("/opps")
def opps():
    return db.rows("SELECT * FROM today_opps ORDER BY id DESC")


def agent_context(ref: str) -> str:
    try:
        p = _payload(db.today())
    except Exception:  # noqa: BLE001
        return ""
    return "今日精读：" + "；".join(c["title"] for c in p["deep"]) + "。速览：" + "；".join(c["title"] for c in p["quick"])
