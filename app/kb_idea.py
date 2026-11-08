"""今日一想：每天从判断台账挑一个问题，和知识库对话 Agent（批判者）聊透，再由 Agent 把我的判断记进台账。"""
from __future__ import annotations

from . import agent, db, kb_judge

SCHEMA = """
CREATE TABLE IF NOT EXISTS kb_thinks (             -- 每次想的问题（只追加；judgment_id 记下判断后回填）
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    question TEXT NOT NULL,
    origin_sid TEXT DEFAULT '',                    -- 从哪条判断想起
    judgment_id INTEGER,                           -- 想完记下的判断 kb_judgments.id
    done_on TEXT DEFAULT '',                       -- 记下判断的那天
    created_at TEXT
);
"""

CRITIC = """## 你现在是「今日一想」的批判者
用户在想一个问题，你帮用户想得更深，但答案由用户自己给。规矩：
- 每一轮只给三样，各一两句：
  1. **一个认知**：被忽略的视角、反例或隐含前提。只指出，不说「所以你对 / 错了」。
  2. **一个引导问题**：指向用户推理里最薄弱的一环，具体到能去求证。
  3. **去哪求证**：先从下面列的用户看过的材料、知识库里挑；没有就给该搜的方向或能做的小实验。
- 不替用户写答案，不改写用户的主张，不给结论（不给结论是硬规矩）。用户问「那答案是什么」时，只再给一条线索。
- 用户回应后，看有没有接住上一轮的质疑：接住了就换下一个薄弱处；回避了就继续追问这一处。
- 用户说想清楚了、要记下来时：用用户自己的话整理成一句可检查的判断（再标类型 观点 / 预测 / 评价 / 疑问、信心 高 / 中 / 低，预测写兑现日期），
  先给用户确认；确认后再记，命令：
  curl -s -X POST {api}/api/kb/think/{tid}/record -H 'Content-Type: application/json' -d '{{"text": "…", "type": "观点", "confidence": "中", "due": ""}}'
  记完一句话告诉用户记下了，明天的问题会接着这里想。没确认不要记。"""


def _init() -> None:
    db.init([SCHEMA])


def _today() -> str:
    return db.today()


def _out(t: dict) -> dict:
    j = db.row("SELECT * FROM kb_judgments WHERE id=?", [t["judgment_id"]]) if t["judgment_id"] else None
    chatted = db.row("SELECT 1 FROM chat_sessions WHERE module='kb' AND ref=?", [f"think:{t['id']}"])
    return {**t, "ref": f"think:{t['id']}", "chatted": bool(chatted),
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


def _create(date: str, question: str, origin: str) -> dict:
    tid = db.insert("kb_thinks", {"date": date, "question": question, "origin_sid": origin, "created_at": db.now()})
    return db.row("SELECT * FROM kb_thinks WHERE id=?", [tid])


def today() -> dict | None:
    _init()
    last = db.row("SELECT * FROM kb_thinks ORDER BY id DESC LIMIT 1")
    if last and (not last["judgment_id"] or _today() in (last["date"], last["done_on"])):
        return _out(last)
    done = {r["origin_sid"] for r in db.rows("SELECT origin_sid FROM kb_thinks")}
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


def get(tid: int) -> dict | None:
    _init()
    t = db.row("SELECT * FROM kb_thinks WHERE id=?", [tid])
    return _out(t) if t else None


def record(tid: int, text: str, type_: str = "", confidence: str = "", due: str = "") -> dict | None:
    t = get(tid)
    if not t:
        return None
    jid = kb_judge.add(text, type_, confidence, due, note=f"和批判者一起想：{t['question']}")
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
