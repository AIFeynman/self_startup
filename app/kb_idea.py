"""今日一想：每天从判断台账挑一个问题，或自己写下问题和判断，和知识库对话 Agent（批判者）一层层往下挖到第 5 层，再由 Agent 把我的判断记进台账。"""
from __future__ import annotations

import re

from . import agent, db, kb_judge

SCHEMA = """
CREATE TABLE IF NOT EXISTS kb_thinks (             -- 每次想的问题（只追加；judgment_id 记下判断后回填）
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    question TEXT NOT NULL,
    origin_sid TEXT DEFAULT '',                    -- 从哪条判断想起；空 = 自己出的题
    stance TEXT DEFAULT '',                        -- 自己出题时一开始的判断
    judgment_id INTEGER,                           -- 想完记下的判断 kb_judgments.id
    done_on TEXT DEFAULT '',                       -- 记下判断的那天
    created_at TEXT
);
"""

MAX_DEPTH = 5
LAYER_TAG = re.compile(r"〔第\s*([1-5])\s*/\s*5\s*层〕")
BOTTOM_TAG = "〔5 层到底〕"

CRITIC = """## 你现在是「今日一想」的批判者
用户在想一个问题，你帮用户一层层往下想，一共挖 5 层，答案由用户自己给。规矩：
- 每一轮回复第一行只写层标记 `〔第 N / 5 层〕`，N 是这一轮追问所在的层，第一轮是第 1 层。
- 每层的默认方向（按用户的回答灵活调整，但不要跳过）：
  1. 澄清主张：用户到底在断言什么？概念的边界、适用范围、「更好」按什么标准算。
  2. 依据：凭什么这么想？证据是亲眼看到的、读到的、还是推出来的，样本有多大。
  3. 隐含前提：这个理由要成立，背后默认了哪些没说出口的条件？挑最脆弱的一个。
  4. 反例与替代解释：在什么情况下会不成立？同样的现象还能怎么解释？有没有人反着做也成了。
  5. 可检验：看到什么证据会让用户改主意？能不能写成一个有日期、可检查的预测或小实验。
- 每一层的追问必须咬住用户上一轮刚给出的理由本身，追问「这个理由为什么成立 / 它依赖什么」，不另起话题、不泛泛而谈。
- 每一轮只给三样，各一两句：
  1. **一个认知**：被忽略的视角、反例或隐含前提。只指出，不说「所以你对 / 错了」。
  2. **一个引导问题**：指向这一层里用户推理最薄弱的一环，具体到能回答、能去求证。
  3. **去哪求证**：先从下面列的用户看过的材料、知识库里挑；没有就给该搜的方向或能做的小实验。
- 进层标准要严：用户给出了新的理由、证据、机制或修正，才算接住了，N 加 1；复述、「嗯 / 对 / 应该是」、换个说法重复、只表态不讲为什么，都不算，N 不变，换个角度继续逼问这一层，并点明哪里还没答到。
- 不替用户写答案，不改写用户的主张，不给结论（不给结论是硬规矩）。用户问「那答案是什么」时，只再给一条线索。
- 用户接住了第 5 层：第一行写 `〔5 层到底〕`，不再追问。按层列出用户每层给出的理由（用用户自己的话），指出和一开始的判断相比哪里变了、哪里还站不住，然后进入「记下来」。
- 记下来（挖到底或用户说想清楚了）：用用户自己的话整理成一句可检查的判断（再标类型 观点 / 预测 / 评价 / 疑问、信心 高 / 中 / 低，预测写兑现日期），
  先给用户确认；确认后再记，命令：
  curl -s -X POST {api}/api/kb/think/{tid}/record -H 'Content-Type: application/json' -d '{{"text": "…", "type": "观点", "confidence": "中", "due": ""}}'
  记完一句话告诉用户记下了，明天的问题会接着这里想。没确认不要记。"""


def _init() -> None:
    db.init([SCHEMA])
    if "stance" not in {r["name"] for r in db.rows("PRAGMA table_info(kb_thinks)")}:
        db.execute("ALTER TABLE kb_thinks ADD COLUMN stance TEXT DEFAULT ''")


def _today() -> str:
    return db.today()


def _depth(tid: int) -> tuple[int, bool]:
    said = [m["content"] for m in db.rows(
        "SELECT m.content FROM chat_messages m JOIN chat_sessions s ON s.id=m.session_id "
        "WHERE s.module='kb' AND s.ref=? AND m.role='assistant'", [f"think:{tid}"])]
    if any(BOTTOM_TAG in c for c in said):
        return MAX_DEPTH, True
    return max((int(n) for c in said for n in LAYER_TAG.findall(c)), default=0), False


def _out(t: dict) -> dict:
    j = db.row("SELECT * FROM kb_judgments WHERE id=?", [t["judgment_id"]]) if t["judgment_id"] else None
    chatted = db.row("SELECT 1 FROM chat_sessions WHERE module='kb' AND ref=?", [f"think:{t['id']}"])
    depth, bottomed = _depth(t["id"])
    return {**t, "ref": f"think:{t['id']}", "chatted": bool(chatted), "depth": depth, "max_depth": MAX_DEPTH, "bottomed": bottomed,
            "judgment": {"sid": f"my:{j['id']}", "text": j["text"]} if j else None}


def _question(c: dict, thread: str = "") -> str:
    if thread:
        return thread
    if c["type"] == "疑问":
        return c["claim"].removeprefix("疑问：")
    if c["due"] and c["due"] <= kb_judge._today():
        return f"「{c['claim']}」现在还成立吗？"
    return f"「{c['claim']}」为什么成立？最脆弱的前提是什么？"


def _candidates(lg: dict) -> list[tuple[dict, str]]:
    latest = [(t["items"][-1], t["question"]) for t in lg["threads"]]
    return [*((c, "") for c in lg["due"]), *((c, "") for c in lg["open"]), *latest, *((c, "") for c in lg["singles"])]


def _create(date: str, question: str, origin: str, stance: str = "") -> dict:
    tid = db.insert("kb_thinks", {"date": date, "question": question, "origin_sid": origin, "stance": stance, "created_at": db.now()})
    return db.row("SELECT * FROM kb_thinks WHERE id=?", [tid])


def today() -> dict | None:
    _init()
    last = db.row("SELECT * FROM kb_thinks ORDER BY id DESC LIMIT 1")
    if last and (not last["judgment_id"] or _today() in (last["date"], last["done_on"])):
        return _out(last)
    done = {r["origin_sid"] for r in db.rows("SELECT origin_sid FROM kb_thinks WHERE origin_sid!=''")}
    for c, thread in _candidates(kb_judge.ledger_json()):
        if c["sid"] not in done:
            return _out(_create(_today(), _question(c, thread), c["sid"]))
    return None


def start(sid: str) -> dict | None:
    _init()
    open_ = db.row("SELECT * FROM kb_thinks WHERE origin_sid=? AND judgment_id IS NULL ORDER BY id DESC LIMIT 1", [sid])
    if open_:
        return _out(open_)
    c = next((c for c in kb_judge.ledger(None, {})["cards"] if c["sid"] == sid), None)
    return _out(_create(_today(), _question(c), sid)) if c else None


def ask(question: str, stance: str) -> dict:
    _init()
    question, stance = question.strip(), stance.strip()
    if not question or not stance:
        raise ValueError("empty")
    return _out(_create(_today(), question, "", stance))


def get(tid: int) -> dict | None:
    _init()
    t = db.row("SELECT * FROM kb_thinks WHERE id=?", [tid])
    return _out(t) if t else None


def record(tid: int, text: str, type_: str = "", confidence: str = "", due: str = "") -> dict | None:
    t = get(tid)
    if not t:
        return None
    note = f"和批判者一起想：{t['question']}" + (f"；一开始的判断：{t['stance']}" if t["stance"] else "")
    jid = kb_judge.add(text, type_, confidence, due, note=note)
    db.execute("UPDATE kb_thinks SET judgment_id=?, done_on=? WHERE id=?", [jid, _today(), tid])
    return get(tid)


def _card_text(c: dict) -> str:
    e = c.get("eval") or {}
    lines = [f"- {c['date'][:10]} [{c['type']}] {c['claim']}" + (f"（信心{c['confidence']}）" if c.get("confidence") else "")]
    if c.get("mine") and c["mine"] != c["claim"]:
        lines.append(f"  原话：{c['mine'][:300]}")
    if e:
        lines.append(f"  当时的评价：依据{e.get('strength')}；{e.get('basis')} 反方：{e.get('counter')} 怎么验证：{e.get('verify')}")
    lines += [f"  {r['at'][:10]} 复查 {r['verdict_name']}：{r['note']}" for r in c.get("reviews", []) if r.get("note")]
    return "\n".join(lines)


def context(tid: int) -> str:
    t = get(tid)
    if not t:
        return ""
    lg = kb_judge.ledger_json()
    cards = {c["sid"]: c for c in [*lg["due"], *lg["open"], *lg["singles"], *(x for th in lg["threads"] for x in th["items"])]}
    origin = cards.get(t["origin_sid"])
    thread = next((th for th in lg["threads"] if origin and th["question"] == origin.get("thread")), None)
    parts = [CRITIC.format(api=agent.API_BASE, tid=tid), f"## 今天的问题\n{t['question']}"]
    if t["stance"]:
        parts.append(f"## 我一开始的判断\n{t['stance']}")
    parts.append("## 现在的深度\n" + ("5 层已经挖到底，接下来只做整理和记下来。" if t["bottomed"]
                                     else f"已经挖到第 {t['depth']} 层（共 5 层）。" if t["depth"] else "还没开始挖，这一轮从第 1 层开始。"))
    if origin:
        parts.append("## 这个问题从这条判断来\n" + _card_text(origin))
    if thread:
        parts.append(f"## 同一问题线上我的判断（立场：{thread.get('stance', '')}）\n" + "\n".join(_card_text(c) for c in thread["items"]))
    if origin and origin.get("concepts"):
        ms = [m for q in origin["concepts"][:3] for m in kb_judge.materials(q, 3)]
        if ms:
            parts.append("## 我看过的相关材料\n" + "\n".join(f"- {m['sub_name']}·{m['title']}（{m['date'][:10]}）{m['url'] or m['link']}" for m in ms))
    prev = db.rows("SELECT k.question, k.date, j.text FROM kb_thinks k JOIN kb_judgments j ON j.id=k.judgment_id "
                   "WHERE k.id!=? ORDER BY k.id DESC LIMIT 5", [tid])
    if prev:
        parts.append("## 之前几天想出来的判断（可以接着往下想）\n" + "\n".join(f"- {p['date']} 想「{p['question']}」→ {p['text']}" for p in prev))
    return "\n\n".join(parts)
