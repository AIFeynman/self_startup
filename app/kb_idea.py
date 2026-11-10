"""今日一想：脑爆、思路推演与判断交锋，话题持久保存、随时续聊。"""
from __future__ import annotations

from . import agent, chat_images, db, kb_judge

SCHEMA = """
CREATE TABLE IF NOT EXISTS kb_thinks (             -- 每次想的问题（只追加；judgment_id 记下判断后回填）
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    question TEXT NOT NULL,
    origin_sid TEXT DEFAULT '',                    -- 从哪条判断想起；空 = 自己出的题
    mode TEXT NOT NULL DEFAULT 'judgment',
    stance TEXT DEFAULT '',                        -- 自己出题时一开始的判断
    judgment_id INTEGER,                           -- 想完记下的判断 kb_judgments.id
    done_on TEXT DEFAULT '',                       -- 记下判断的那天
    created_at TEXT
);
"""

MODES = {"brainstorm": "一起脑爆", "idea": "讨论思路", "judgment": "讨论判断"}
MODEL = "claude-opus-5-5"

DIRECTIONS = {
    "brainstorm": "目标：找到有突破、值得继续推演的新方向。先抓目标与最硬约束，首轮只给 2 个机制不同的候选，每个一句话说明如何起作用；推荐一个并点明最关键的代价。用户选中或提出方向后，沿它深挖，不每轮重列点子。",
    "idea": "目标：把一个思路推演到能判断是否值得做。复原它起作用的因果链，找出真正瓶颈、最脆弱前提与失败条件；主动给更强的改法，并设计能区分原方案与改法的最小实验。",
    "judgment": "目标：检验自己的判断是否站得住。先忠实理解主张和依据，再给最强反例与替代解释，划清成立边界，说明你的当前判断及信心、什么证据会让双方改主意。不要为了反对而反对。",
}

PARTNER = """## 今日一想：深入而简练的讨论伙伴
你和用户共同思考，主动提出判断、提供新视角并交锋。不要只当提问教练，也不要迎合用户。
这是对话式分析，不是执行工程任务；不输出完成标准、自主决策、验收汇报，也不替用户选择个人偏好。需要了解用户的目标、判断或理由时可以自然追问。
- 深入指找到决定结果的机制、关键假设、最强反例和可验证的分歧；不以轮数、篇幅或固定五层衡量。
- 每轮紧扣用户刚说的内容，只推进最重要的一处分歧。先给一句有信息量的判断，再用最必要的理由或例子支撑；必要时只问一个能推动讨论的问题。
- 简练是硬约束：除非用户明确要求展开，每轮正文不超过 300 个汉字，优先 150–250 字；只留下最有价值的判断和支撑它的理由。复杂证据先给摘要，附来源供展开。避免铺陈、复述、套话和每轮套同一模板；用户要求详解时按需展开。
- 证据不足就说清不确定性和成立条件；把用户的判断、你的推断、已核实的事实分开。
- 需要用户过往材料时先检索知识库；涉及会影响结论的最新事实、陌生技术或争议证据时主动搜索一手资料，附来源链接与日期。搜索要服务于当前分歧，不堆资料；没搜到不能说已证实。
- 适合量化或检验机制时，可做小规模计算、反例构造或模拟。明确假设、方法和结果；思想实验须标明「假设推演」，没有实际运行不能称为实测；样本量、显著性、成本、提升幅度等定量结论必须有可核对的计算或来源，不凭直觉报数字。脚本只写临时目录，不改项目、配置或业务数据，不启动付费服务。
- 已有可靠结论或明确下一步时及时收束；不要强迫用户继续答题。用户要求整理时，用几句话记录：当前共识、关键分歧、判断变化、最小验证与待查证事项。没有结论也可以保留为开放话题。
- 话题与每轮对话由平台自动保存，不需要用户确认。要把一句判断写入用户的判断台账时，先给用户确认，确认后调用：
  curl -s -X POST {api}/api/kb/think/{tid}/record -H 'Content-Type: application/json' -d '{{"text": "…", "type": "观点", "confidence": "中", "due": ""}}'
  不把 AI 的意见自动记作用户的判断。
"""


def _init() -> None:
    kb_judge._init()
    db.init([SCHEMA])
    columns = {r["name"] for r in db.rows("PRAGMA table_info(kb_thinks)")}
    if "stance" not in columns:
        db.execute("ALTER TABLE kb_thinks ADD COLUMN stance TEXT DEFAULT ''")
    if "mode" not in columns:
        db.execute("ALTER TABLE kb_thinks ADD COLUMN mode TEXT NOT NULL DEFAULT 'judgment'")


def _today() -> str:
    return db.today()


def _out(t: dict) -> dict:
    j = db.row("SELECT * FROM kb_judgments WHERE id=?", [t["judgment_id"]]) if t["judgment_id"] else None
    session = db.row("SELECT id, updated_at FROM chat_sessions WHERE module='kb' AND ref=? ORDER BY updated_at DESC, id DESC LIMIT 1", [f"think:{t['id']}"])
    return {**t, "images": chat_images.of("think", t["id"]), "ref": f"think:{t['id']}", "chatted": bool(session),
            "mode_name": MODES[t["mode"]], "session_id": session["id"] if session else None,
            "updated_at": session["updated_at"] if session else t["created_at"],
            "judgment": {"sid": f"my:{j['id']}", "text": j["text"]} if j else None}


def history(q: str = "", mode: str = "", limit: int = 20, offset: int = 0) -> dict:
    _init()
    where, args = [], []
    if q.strip():
        where.append("(instr(k.question, ?) OR instr(k.stance, ?) OR EXISTS (SELECT 1 FROM chat_sessions s JOIN chat_messages m ON m.session_id=s.id WHERE s.module='kb' AND s.ref='think:' || k.id AND instr(m.content, ?)))")
        args.extend([q.strip()] * 3)
    if mode:
        where.append("k.mode=?")
        args.append(mode)
    clause = " WHERE " + " AND ".join(where) if where else ""
    total = db.row("SELECT count(*) AS n FROM kb_thinks k" + clause, args)["n"]
    rows = db.rows("SELECT k.* FROM kb_thinks k" + clause +
                   " ORDER BY COALESCE((SELECT max(s.updated_at) FROM chat_sessions s WHERE s.module='kb' AND s.ref='think:' || k.id), k.created_at) DESC, k.id DESC LIMIT ? OFFSET ?", [*args, limit, offset])
    return {"items": [_out(t) for t in rows], "total": total}


def _question(c: dict, thread: str = "") -> str:
    if thread:
        return thread
    if c["type"] == "疑问":
        return c["claim"].removeprefix("疑问：")
    if c["due"] and c["due"] <= kb_judge._today():
        return f"「{c['claim']}」现在还成立吗？"
    return f"「{c['claim']}」为什么成立？最脆弱的前提是什么？"


def _create(date: str, question: str, origin: str, stance: str = "", mode: str = "judgment") -> dict:
    tid = db.insert("kb_thinks", {"date": date, "question": question, "origin_sid": origin, "stance": stance, "mode": mode, "created_at": db.now()})
    return db.row("SELECT * FROM kb_thinks WHERE id=?", [tid])


def latest() -> dict | None:
    items = history(limit=1)["items"]
    return items[0] if items else None


def start(sid: str) -> dict | None:
    _init()
    open_ = db.row("SELECT * FROM kb_thinks WHERE origin_sid=? AND judgment_id IS NULL ORDER BY id DESC LIMIT 1", [sid])
    if open_:
        return _out(open_)
    c = next((c for c in kb_judge.ledger(None, {})["cards"] if c["sid"] == sid), None)
    return _out(_create(_today(), _question(c), sid)) if c else None


def ask(question: str, stance: str = "", mode: str = "judgment", images: list[str] | None = None) -> dict:
    _init()
    image_ids = images or []
    chat_images.resolve(image_ids)
    question, stance = question.strip(), stance.strip()
    if (not question and not image_ids) or mode not in MODES:
        raise ValueError("empty")
    t = _create(_today(), question or "围绕图片讨论", "", stance, mode)
    chat_images.attach("think", t["id"], image_ids)
    return _out(t)


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
    parts = [PARTNER.format(api=agent.API_BASE, tid=tid), f"## 讨论方式：{MODES[t['mode']]}\n{DIRECTIONS[t['mode']]}", f"## 今天的问题\n{t['question']}"]
    if t["stance"]:
        parts.append(f"## 我一开始的判断\n{t['stance']}")
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
    return "\n\n".join(parts) + chat_images.prompt(t["images"])
