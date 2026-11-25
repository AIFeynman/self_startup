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
CREATE TABLE IF NOT EXISTS today_scores (         -- 值不值得深想：按条目缓存，一条只打一次分
    key TEXT PRIMARY KEY, score INTEGER, why TEXT DEFAULT '', question TEXT DEFAULT '', hit TEXT DEFAULT '', src TEXT DEFAULT '', at TEXT,
    terms TEXT DEFAULT '[]'
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
QUICK_QUOTA = {"product": 1, "new": 2, "tech": 2, "eng": 2}
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
QUICK_S_MAX = 3
TECH_HINT = re.compile(r"agent|harness|memory|eval|benchmark|reasoning|\brl\b|reinforcement|attention|moe|distill|coding|tool", re.I)
DEEP_MIN = 6
TRACK_MIN = 6
SCORE_SRC = "llm2"          # 打分口径变了就改版本号，旧缓存会重打
TRACK_KINDS = ("product", "new", "growth")
NEWS_TYPES = {"pricing", "packaging", "revenue", "funding", "partnership", "deprecation", "people"}
SCORE_POOL = {"product": 12, "new": 8, "tech": 8, "growth": 3}
ANGLE_DAYS = 14
PROFILE = """用户画像（2026-11-25 确认，会随学习更新）：
- M0 发现机会（统领）：看技术和产品是为了找值得自己做的机会：什么之前做不到现在能做，谁有痛点，空白在哪。
- M1 让自己的 AI 知识讲解视频产品跑起来：要能执行、能验证的增长打法和差异化定位。增长方法基础弱。
- M2 系统深入学大模型和 Agent：Agent 工程已到“会判断”，基座机制还在“懂机制”入门；最大短板是应用（给场景做决定、量化、设计验证）。
- M3 用 AI teams（多 Agent 协作、Harness、验收、记忆）把个人产出放大，并在自己的学习平台上落地。
- M4 有自己的判断：会质疑，但常缺结论、数字和验证方法。
- M5 个人品牌和知识内容。"""
SCORE_SYSTEM = """你在为一位用户挑选“今天值得花 5 分钟深想”的 3 条内容。读者画像和他最近亲口问过、还没解决的问题在 profile / open_questions 里。
对 items 里每一条打 0–10 分的“深想价值”，标准：
1. 有东西可想：新的机制、取舍、打法、分歧或反常识的结果，而不只是“发生了什么”。纯新闻（版本号升级、定价调整、套餐变化、融资、人事、合作公告）一律 ≤ 3 分，除非它直接回答了用户的某个开放问题。
   新产品（kind=new，Product Hunt / YC 新上线的）比大公司已有产品的某个功能更新更值得看：新产品看它切了什么人群和痛点、为什么现在能做、有没有空白；大公司的功能更新只有涉及新的交互形态，或直接命中用户问题才给高分。
2. 和用户的动机或开放问题直接相关（能点名是哪一条）。
3. 想完能落到可检验的判断，或能动手验证。
每条输出：score；why（一句话，说清对这位用户为什么值得想，点名动机或问题，≤40 字，不值得就留空）；
question（给他的一个深想问题，要求给场景、要他做决定并说怎么验证，≤60 字；不值得就留空）；
hit（命中的 open_questions 原文，没有就留空）；
terms（2–4 个用来在名人发言、HN、X 上找相关讨论的检索词：产品名、公司名、论文或技术的专有名词，中英文都可，不要泛词）；
track（0–10：和用户自己产品赛道的相关度。用户在做 AI 知识讲解视频产品：同赛道竞品、相邻赛道（AI 视频生成、教育、知识内容和创作者工具）、能直接借鉴到他产品的增长打法给高分，其余给低分）；
track_question（track ≥ 6 时，给一个针对他产品的问题：是威胁还是可借鉴、它的增长靠什么、他该怎么差异化，≤60 字）。
输出 JSON：{"items": [{"key": "原样返回", "score": 0, "why": "", "question": "", "hit": "", "terms": [], "track": 0, "track_question": ""}]}"""


def _llm(system: str, payload: dict) -> dict:
    from ._intel_snap import _deepseek
    return _deepseek(system, payload, max_tokens=4000, module="today")


def _open_questions(limit: int = 40) -> list[str]:
    if not _has("annotation_msgs"):
        return []
    rows = db.rows("SELECT content FROM annotation_msgs WHERE role='user' ORDER BY id DESC LIMIT ?", [limit * 2])
    out = []
    for r in rows:
        q = re.sub(r"\s+", " ", r["content"] or "").strip()
        if len(q) >= 8 and q not in out:
            out.append(q[:120])
    return out[:limit]


def _fallback_score(c: dict) -> int:
    if c["kind"] == "new":
        return DEEP_MIN
    if c["kind"] == "product":
        return 2 if c.get("type") in NEWS_TYPES else DEEP_MIN
    if c["kind"] == "growth":
        return DEEP_MIN + 1
    return DEEP_MIN if TECH_HINT.search(f"{c['title']} {c.get('summary', '')}") else DEEP_MIN - 2


def _scores(cards: list[dict]) -> dict:
    _ensure_cols()
    keys = [c["key"] for c in cards]
    have = {r["key"]: r for r in db.rows(f"SELECT * FROM today_scores WHERE key IN ({','.join('?' * len(keys))})", keys)} if keys else {}
    todo = [c for c in cards if c["key"] not in have or have[c["key"]]["src"] != SCORE_SRC]
    if todo:
        items = [{"key": c["key"], "kind": c["kind"], "type": c.get("type", ""), "title": c["title"], "summary": c.get("summary", ""),
                  "detail": _plain(" ".join((c.get("reveal") or {}).values()), 500)} for c in todo]
        try:
            got = {str(x.get("key")): x for x in _llm(SCORE_SYSTEM, {"profile": PROFILE, "open_questions": _open_questions(),
                                                                      "items": items}).get("items", []) if isinstance(x, dict)}
            src = SCORE_SRC
        except Exception:  # noqa: BLE001  打分失败时按规则：纯新闻不进精读，其余照常
            got, src = {}, "rule"
        for c in todo:
            x = got.get(c["key"])
            terms = [str(t).strip() for t in (x or {}).get("terms") or [] if len(str(t).strip()) >= 3][:4] or _fallback_terms(c)
            row = {"key": c["key"], "score": int(x.get("score") or 0) if x else _fallback_score(c), "terms": json.dumps(terms, ensure_ascii=False),
                   "track": int(x.get("track") or 0) if x else (TRACK_MIN + 1 if "你的讲解视频产品" in c.get("relates", []) else 0),
                   "track_q": str((x or {}).get("track_question") or "")[:120],
                   "why": str((x or {}).get("why") or "")[:80], "question": str((x or {}).get("question") or "")[:120],
                   "hit": str((x or {}).get("hit") or "")[:160], "src": src if x or src == "rule" else "rule", "at": db.now()}
            db.execute("INSERT OR REPLACE INTO today_scores (key, score, why, question, hit, src, at, terms, track, track_q) "
                       "VALUES (?,?,?,?,?,?,?,?,?,?)",
                       [row[k] for k in ("key", "score", "why", "question", "hit", "src", "at", "terms", "track", "track_q")])
            have[c["key"]] = row
    return have


def _ensure_cols() -> None:
    have = {r["name"] for r in db.rows("PRAGMA table_info(today_scores)")}   # 老库补列
    for col, ddl in (("terms", "TEXT DEFAULT '[]'"), ("track", "INTEGER DEFAULT 0"), ("track_q", "TEXT DEFAULT ''")):
        if col not in have:
            db.execute(f"ALTER TABLE today_scores ADD COLUMN {col} {ddl}")


def _fallback_terms(c: dict) -> list[str]:
    words = [c.get("company") or ""] + re.findall(r"[A-Z][\w.\-]+(?: [A-Z][\w.\-]+)?", c["title"])
    return [w for w in dict.fromkeys(w.strip() for w in words) if len(w) >= 3][:3]


# ---------- 不同角度：名人怎么说 / HN 怎么吵 / 实践者经验（只读现有采集） ----------

def _people_names() -> dict:
    try:
        from pathlib import Path
        raw = json.loads((Path(__file__).parent / "people.json").read_text("utf-8"))
        return {p["id"]: p.get("zh") or p["name"] for p in (raw if isinstance(raw, list) else raw.get("people", []))}
    except (OSError, ValueError, KeyError):
        return {}


def _like(terms: list[str], cols: list[str]) -> tuple[str, list]:
    conds, args = [], []
    for t in terms:
        conds.append("(" + " OR ".join(f"{c} LIKE ?" for c in cols) + ")")
        args += [f"%{t}%"] * len(cols)
    return " OR ".join(conds), args


def _hn_digest(hid: str) -> dict:
    try:
        from ._feed_hn import CACHE_DIR
        return (json.loads((CACHE_DIR / f"{hid}.json").read_text("utf-8")) or {}).get("d") or {}
    except (OSError, ValueError, ImportError):
        return {}


def _angles(terms: list[str], day: str) -> list[dict]:
    if not terms:
        return []
    since = (date.fromisoformat(day) - timedelta(days=ANGLE_DAYS)).isoformat()
    out = []
    if _has("people_items"):
        names = _people_names()
        where, args = _like(terms, ["title", "summary"])
        for r in db.rows(f"SELECT people, channel, title, summary, url, date FROM people_items WHERE substr(date,1,10)>=? AND ({where}) "
                         "ORDER BY CASE channel WHEN 'blog' THEN 0 WHEN 'podcast' THEN 0 WHEN 'youtube' THEN 1 WHEN 'x' THEN 2 ELSE 3 END, "
                         "date DESC LIMIT 2", [since, *args]):
            who = "、".join(names.get(p, p) for p in json.loads(r["people"] or "[]"))
            out.append({"kind": "people", "label": "名人怎么说", "who": who, "channel": r["channel"], "title": _plain(r["title"], 120),
                        "summary": _plain(r["summary"], 160), "url": r["url"], "date": (r["date"] or "")[:10]})
    if _has("feed_items"):
        where, args = _like(terms, ["title"])
        for r in db.rows(f"SELECT id, title, url, extra, popularity FROM feed_items WHERE source='hn' AND substr(date,1,10)>=? AND ({where}) "
                         "ORDER BY popularity DESC LIMIT 1", [since, *args]):
            hid = r["id"].split(":", 1)[1]
            dg = _hn_digest(hid)
            ex = json.loads(r["extra"] or "{}")
            out.append({"kind": "hn", "label": "HN 怎么吵", "title": r["title"], "points": int(r["popularity"] or 0),
                        "tldr": _plain(dg.get("tldr", ""), 200),
                        "opinions": [{"stance": o.get("stance", ""), "claim": _plain(o.get("claim", ""), 120), "by": o.get("by", "")}
                                     for o in (dg.get("opinions") or [])[:3]],
                        "url": ex.get("hn_url") or f"https://news.ycombinator.com/item?id={hid}"})
    if _has("x_art"):
        where, args = _like(terms, ["title", "summary"])
        for r in db.rows(f"SELECT user, title, summary, take FROM x_art WHERE q>=3 AND day>=? AND ({where}) ORDER BY q DESC, views DESC LIMIT 1",
                         [since, *args]):
            out.append({"kind": "practice", "label": "实践者经验", "who": "@" + r["user"], "title": _plain(r["title"], 120),
                        "summary": _plain(r["summary"], 160), "takeaway": _plain(r["take"], 160), "url": "#kb/xart"})
    return out


def _new_products(day: str) -> list[dict]:
    since = (date.fromisoformat(day) - timedelta(days=WINDOW_DAYS)).isoformat()
    due = (date.fromisoformat(day) + timedelta(days=180)).isoformat()
    out = []

    def card(key, label, name, title, summary, url, d):
        return {"key": key, "kind": "new", "label": label, "title": title, "company": name, "date": d, "summary": summary,
                "prediction": f"{name} 半年内会有明显起色（融资、收入或持续上榜）", "due": due,
                "question": "它切的是谁的什么痛点？为什么现在才能做？半年后还在吗？", "reveal": {},
                "relates": _relates(title, summary), "link": url, "src_url": url}
    if _has("intel_ph_day"):
        for r in db.rows("SELECT date, items FROM intel_ph_day WHERE date>=? AND date<=? ORDER BY date DESC", [since, day]):
            for it in json.loads(r["items"] or "[]")[:5]:
                out.append(card(f"ph:{it.get('id')}", f"新产品 · PH 第 {it.get('rank')}", it.get("name", ""), it.get("title", ""),
                                _plain(it.get("why", ""), 160), it.get("url", ""), r["date"]))
    if _has("feed_items"):
        for r in db.rows("SELECT id, title, summary, url, date, extra FROM feed_items WHERE source='yc' AND substr(date,1,10)>=? "
                         "AND substr(date,1,10)<=? ORDER BY popularity DESC LIMIT 6", [since, day]):
            ex = json.loads(r["extra"] or "{}")
            out.append(card(f"feed:{r['id']}", "新产品 · YC", ex.get("company") or r["title"].split(":")[0], r["title"],
                            ex.get("gist") or _plain(r["summary"], 160), ex.get("website") or r["url"], (r["date"] or "")[:10]))
    return out


def _has(table: str) -> bool:
    return bool(db.row("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", [table]))


def _plain(text: str, limit: int = 0) -> str:
    t = LINK.sub(r"\1", text or "")
    t = re.sub(r"\*\*【推测】\*\*|\*\*", "", t).strip()
    return t if not limit or len(t) <= limit else t[: limit - 1].rstrip() + "…"


def _src_url(sources: str) -> str:
    try:
        src = [x for x in json.loads(sources or "[]") if isinstance(x, dict) and x.get("url")]
    except ValueError:
        return ""
    src.sort(key=lambda x: not x.get("official"))
    return src[0]["url"] if src else ""


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
        "SELECT e.id, e.title, e.level, e.type, e.date, e.sources, c.name company, a.content, a.sections, a.complete FROM intel_event e "
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
            "key": f"intel:{r['id']}", "kind": "product", "label": f"产品 · {r['level']} 级", "level": r["level"], "type": r["type"] or "",
            "title": r["title"], "company": r["company"] or "", "date": r["date"],
            "summary": _first_bullet(sec.get("变了什么", "")), "prediction": pred, "due": due,
            "question": "这条预测会兑现吗？" if pred else "这件事对你重要吗？30 天内会有别家跟进吗？",
            "reveal": {k: _plain(sec[k], 900) for k in ("用户问题", "产品逻辑", "商业逻辑", "所以呢") if sec.get(k)},
            "relates": _relates(r["title"], sec.get("变了什么", ""), sec.get("用户问题", "")),
            "link": f"#intel/e/{r['id']}", "src_url": _src_url(r["sources"]),
        })
    return out


def _growth(day: str) -> list[dict]:
    if not _has("intel_growth_case"):
        return []
    rows = db.rows(
        "SELECT c.id, c.item_id, c.day, c.company, c.content, i.title, i.url FROM intel_growth_case c "
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
            "link": f"#intel/g/{r['id']}", "src_url": r["url"] or "",
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
            "reveal": {}, "relates": _relates(r["title"], r["summary"], gist), "link": r["url"], "src_url": r["url"],
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
                        "reveal": {}, "relates": _relates(r["title"], r["summary"], r["take"]), "link": "#kb/xart",
                        "src_url": f"https://x.com/{r['user']}/status/{r['id']}"})
    if _has("feed_items"):
        for r in db.rows("SELECT id, title, url, date, popularity, extra FROM feed_items WHERE source='hn' AND popularity>=100 "
                         "AND substr(date,1,10)>=? AND substr(date,1,10)<=? ORDER BY popularity DESC LIMIT 20", [since, day]):
            gist = (json.loads(r["extra"] or "{}") or {}).get("gist") or ""
            if gist:
                out.append({"key": f"feed:{r['id']}", "kind": "eng", "label": "工程实践 · HN", "title": r["title"],
                            "date": (r["date"] or "")[:10], "summary": gist, "reveal": {}, "relates": _relates(r["title"], gist),
                            "link": r["url"], "src_url": r["url"]})
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
             (("product", _products), ("new", _new_products), ("growth", _growth), ("tech", _papers), ("eng", _engineering))}
    cand = [c for k, n in SCORE_POOL.items() for c in pools[k][:n]]
    sc = _scores(cand)
    for c in cand:
        s = sc[c["key"]]
        c.update(depth=s["score"], why=s["why"], hit=s["hit"], terms=json.loads(s.get("terms") or "[]"),
                 track=s.get("track") or 0, track_q=s.get("track_q") or "")
        if s["question"]:
            c["question"] = s["question"]
    ranked = sorted((c for c in cand if c["depth"] >= DEEP_MIN), key=lambda c: -c["depth"])
    deep = []
    for limit in (1, 2):            # 先每类一张，保证不全是同一类；不够再按分数补，每类最多两张
        for c in ranked:
            if len(deep) < DEEP_N and c not in deep and sum(d["kind"] == c["kind"] for d in deep) < limit:
                deep.append(c)
    track = sorted((c for c in cand if c["kind"] in TRACK_KINDS and c["track"] >= TRACK_MIN and (c["depth"] >= 4 or c["track"] >= 8)),
                   key=lambda c: (-c["track"], -c["depth"]))
    if track:                       # 你的赛道：每天固定 1 张同赛道 / 相邻赛道的产品或增长做法；已在精读里就直接标出来
        t = track[0]
        t.update(slot="track", label="你的赛道 · " + t["label"])
        if t["track_q"]:
            t["question"] = t["track_q"]
        if t not in deep:
            deep.append(t)
    for c in deep:
        pools[c["kind"]].remove(c)
        c["angles"] = _angles(c.get("terms") or [], day)
    s_level = [c for c in pools["product"] if c["level"] == "S"][:QUICK_S_MAX]
    others = pools["new"][:QUICK_QUOTA["new"]] + pools["tech"][:QUICK_QUOTA["tech"]] + pools["eng"][:QUICK_QUOTA["eng"]]
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
    marks = {r["key"]: r for r in db.rows("SELECT key, action, note FROM today_marks WHERE day=? AND action!='deepread' ORDER BY id", [day])}
    fb = {r["key"]: r["value"] for r in db.rows("SELECT key, value FROM today_feedback WHERE day=? ORDER BY id", [day])}
    reads = _deepreads([c["key"] for c in p["deep"] + p["quick"]])
    for c in p["deep"] + p["quick"]:
        rs = reads.get(c["key"], [])
        c["deepreads"] = rs
        c["deepread"] = next((x for x in rs if x["url"] == c.get("src_url")), rs[-1] if rs else None)
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


# ---------- 深读：送进深度学习，记进它的深读历史 ----------

def _deepreads(keys: list[str]) -> dict:
    if not keys:
        return {}
    out: dict = {}
    rows = db.rows(f"SELECT key, note FROM today_marks WHERE action='deepread' AND key IN ({','.join('?' * len(keys))}) ORDER BY id", keys)
    ids = [int(r["note"].split("|", 1)[0]) for r in rows if r["note"].split("|", 1)[0].isdigit()]
    st = {r["id"]: r for r in db.rows(f"SELECT id, status, title FROM learn_items WHERE id IN ({','.join('?' * len(ids))})", ids)} if ids else {}
    for r in rows:
        iid, _, url = r["note"].partition("|")
        if iid.isdigit() and int(iid) in st:
            it = st[int(iid)]
            out.setdefault(r["key"], []).append({"id": it["id"], "status": it["status"], "title": it["title"] or "",
                                                 "url": url, "link": f"#learn/item/{it['id']}"})
    return out


class DeepReadIn(BaseModel):
    key: str
    url: str = ""
    day: str = ""


@router.post("/deepread")
def deepread(body: DeepReadIn):
    from . import learn
    c = _card(body.key)
    url = (body.url or c.get("src_url") or (c["link"] if c["link"].startswith("http") else "")).strip()
    if not url:
        raise HTTPException(400, "这张卡没有可深读的原文链接")
    focus = "；".join(x for x in (f"今日卡「{c['title']}」", f"为什么值得想：{c['why']}" if c.get("why") else "",
                                  f"想回答：{c['question']}" if c.get("question") else "") if x)
    it = learn.create_item(learn.ItemIn(url=url, focus=focus, reuse=True))
    db.insert("today_marks", {"key": body.key, "day": (body.day or db.today())[:10], "action": "deepread",
                              "note": f"{it['id']}|{url}", "created_at": db.now()})
    return {"ok": True, "id": it["id"], "status": it["status"], "link": f"#learn/item/{it['id']}"}
