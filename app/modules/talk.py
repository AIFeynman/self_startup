"""讨论：语音或打字直接聊，脑暴、理思路、做判断都行，不用选类型。对话走 /api/chat/talk（只读），Agent 自己判断是在发散还是在做判断，
做判断时套用框架库（判断卡，见 app/kb_lens.py）里合适的那张。
聊完闲置 IDLE_MIN 分钟，后台把这次讨论整理成一张「议题卡」（目标、角度、方案、空间、好坏标准、风险 + 结论 / 待定 / 下一步），
直接存进讨论列表和知识库；结论记进判断台账（app/kb_judge.py）、下一步加到今天的事项，都由人点。接着聊会更新同一张卡。
原「今日一想」（知识库 · 判断）并入这里：台账里的判断点「接着想」会开一段带着这条判断的讨论（ref judge:<sid>）。"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import agent, db, kb_graph, kb_judge, kb_lens, tasks
from . import review

log = logging.getLogger(__name__)

TITLE = "讨论"
ORDER = 7
CHAT_READONLY = True  # 语音可能听错，讨论时 Agent 只能读；写入只走整理和人点的「加到事项」
IDLE_MIN = 5          # 最后一句话之后这么久没动静，就算聊完了，开始整理
SWEEP_S = 120
SWEEP_MAX = 3         # 每轮最多整理几次讨论，别一下占满模型
SWEEP_DAYS = 2        # 只自动整理最近的讨论；更早的（含上线前的旧讨论）在页面上点「现在整理」
_busy: set[int] = set()
_failed: dict[int, str] = {}  # 整理失败的会话 → 当时最后一句的时间；有新话再试，不每轮重试
_lock = threading.Lock()
SCHEMA = """
CREATE TABLE IF NOT EXISTS talk_topics (
  id INTEGER PRIMARY KEY AUTOINCREMENT, session_id INTEGER UNIQUE, title TEXT, card TEXT, note_id INTEGER,
  judgments TEXT DEFAULT '[]', task_ids TEXT DEFAULT '[]', created_at TEXT, updated_at TEXT
);
"""
router = APIRouter()

CARD_KEYS = ("goal", "lenses", "options", "headroom", "quality", "risks", "conclusions", "open_questions", "next_steps")
SECTIONS = [("goal", "目标"), ("lenses", "看问题的角度"), ("options", "可选方案"), ("headroom", "空间判断"), ("quality", "怎么算做好"),
            ("risks", "风险和反模式"), ("conclusions", "结论"), ("open_questions", "待定问题"), ("next_steps", "下一步")]

TOPIC_PROMPT = """下面是用户和你的一次讨论记录（用户的话可能来自语音转写，有错字）。把它整理成一张「议题卡」，只输出一个 JSON 对象，不要别的文字：
{{"title": "这次讨论的议题，20 字内，写成一个问题或主题",
  "mode": "脑暴 / 理思路 / 判断 三选一：发散想点子是脑暴，梳理想法是理思路，要做取舍或评估是判断",
  "frame": "讨论套用的判断卡 id（见下面的框架库），没用到就给空字符串",
  "goal": "这件事真正要达成什么、约束是什么，一两句",
  "lenses": ["看这个问题的角度"], "options": [{{"name": "方案或手段", "how": "怎么做、适合什么情况"}}],
  "headroom": ["还有多大空间、怎么估"], "quality": ["怎么判断做得好"], "risks": ["风险和要避免的做法"],
  "conclusions": ["已经想清楚的结论，一条一句，能单独成立"], "open_questions": ["还没想清楚的问题"],
  "next_steps": ["下一步要做的事，动词开头，30 字内"]}}
只写讨论里出现过的内容，不要补充新观点；没聊到的字段给空字符串或空数组（脑暴类讨论通常只有方案、结论和待定问题）。中文用全角标点。

框架库：
{frames}

讨论记录：
{transcript}"""


def _transcript(sid: int) -> str:
    msgs = db.rows("SELECT role,content FROM chat_messages WHERE session_id=? AND role IN ('user','assistant','fast') ORDER BY id", [sid])
    return "\n\n".join(("用户：" if m["role"] == "user" else "你：") + m["content"] for m in msgs)


def _strs(v) -> list[str]:
    return [str(x).strip() for x in v if str(x).strip()] if isinstance(v, list) else []


def _parse_card(text: str) -> dict:
    m = re.search(r"\{.*\}", text or "", re.S)
    try:
        d = json.loads(m.group(0)) if m else None
    except json.JSONDecodeError:
        d = None
    if not isinstance(d, dict) or not d.get("title"):
        raise HTTPException(502, "整理结果解析失败，再试一次")
    card = {k: _strs(d.get(k)) for k in CARD_KEYS if k not in ("goal", "options")}
    card["goal"] = str(d.get("goal") or "").strip()
    card["options"] = [{"name": str(o.get("name") or "").strip(), "how": str(o.get("how") or "").strip()}
                       for o in d.get("options") or [] if isinstance(o, dict) and o.get("name")]
    card["mode"] = str(d.get("mode") or "").strip()[:6]
    card["frame"] = d.get("frame") if kb_lens.get(str(d.get("frame") or "")) else ""
    return {"title": str(d["title"]).strip()[:60], "card": card}


def card_md(title: str, card: dict) -> str:
    lines = [f"# 议题：{title}", f"类型：{card.get('mode') or '讨论'}"]
    if (f := kb_lens.get(card.get("frame") or "")):
        lines[-1] += f" · 框架：{f['domain']} · {f['title']}"
    for key, name in SECTIONS:
        v = card.get(key)
        if key == "goal" and v:
            lines.append(f"## {name}\n{v}")
        elif key == "options" and v:
            lines.append(f"## {name}\n" + "\n".join(f"- {o['name']}" + (f"：{o['how']}" if o["how"] else "") for o in v))
        elif v and key != "goal":
            lines.append(f"## {name}\n" + "\n".join(f"- {x}" for x in v))
    return "\n\n".join(lines)


def _row(r: dict | None) -> dict | None:
    if not r:
        return None
    card = json.loads(r["card"] or "{}")
    f = kb_lens.get(card.get("frame") or "")
    return {**r, "card": card, "judgments": json.loads(r["judgments"] or "[]"), "task_ids": json.loads(r["task_ids"] or "[]"),
            "frame": {"id": f["id"], "title": f["title"]} if f else None}


def _archive(title: str, card: dict, old: dict | None) -> int:
    """存进知识库：一条洞察，再整理时改写同一条。结论要不要记进判断台账由人点（台账只收用户自己的判断）。"""
    content = card_md(title, card)
    if old and old.get("note_id") and db.row("SELECT id FROM review_notes WHERE id=?", [old["note_id"]]):
        db.update("review_notes", old["note_id"], {"title": title, "content": content, "updated_at": db.now()})
        return old["note_id"]
    return review.api_add_note(review.NoteIn(kind="insight", title=title, content=content, tags="讨论"))["id"]


def _last_said(session_id: int) -> str:
    return (db.row("SELECT MAX(created_at) AS t FROM chat_messages WHERE session_id=? AND role IN ('user','assistant','fast')",
                   [session_id]) or {}).get("t") or ""


def organize(session_id: int) -> dict:
    """把一次讨论整理成议题卡并存档；同一次讨论再整理就更新原来那张。
    卡片的 updated_at 记成整理时最后一句话的时间：整理期间又说的话比它新，下一轮还会再整理。"""
    with _lock:
        if session_id in _busy:
            raise HTTPException(409, "这次讨论正在整理，稍等一下")
        _busy.add(session_id)
    try:
        return _organize(session_id)
    finally:
        with _lock:
            _busy.discard(session_id)


def _organize(session_id: int) -> dict:
    last = _last_said(session_id)
    transcript = _transcript(session_id)
    if not transcript:
        raise HTTPException(400, "这个讨论还没有内容")
    r = agent.run_once(TOPIC_PROMPT.format(frames=kb_lens.index(), transcript=transcript), readonly=True, model=agent.module_model("talk"))
    d = _parse_card(r["text"])
    old = _row(db.row("SELECT * FROM talk_topics WHERE session_id=?", [session_id]))
    tid = old["id"] if old else db.insert("talk_topics", {"session_id": session_id, "created_at": db.now()})
    db.update("talk_topics", tid, {"title": d["title"], "card": json.dumps(d["card"], ensure_ascii=False), "updated_at": last,
                                   "note_id": _archive(d["title"], d["card"], old)})
    db.update("chat_sessions", session_id, {"title": d["title"]})
    return _row(db.row("SELECT * FROM talk_topics WHERE id=?", [tid]))


def sweep() -> list[int]:
    """聊完（最后一句之后闲置 IDLE_MIN 分钟）且有新内容的讨论，整理成议题卡。返回整理了的会话。"""
    cutoff = (datetime.now() - timedelta(minutes=IDLE_MIN)).strftime("%Y-%m-%dT%H:%M:%S")
    since = (datetime.now() - timedelta(days=SWEEP_DAYS)).strftime("%Y-%m-%dT%H:%M:%S")
    rows = db.rows("SELECT s.id, MAX(m.created_at) AS last, t.updated_at AS done FROM chat_sessions s "
                   "JOIN chat_messages m ON m.session_id=s.id AND m.role IN ('user','assistant','fast') "
                   "LEFT JOIN talk_topics t ON t.session_id=s.id WHERE s.module='talk' GROUP BY s.id "
                   "HAVING last<=? AND last>=? AND (done IS NULL OR last>done) ORDER BY last DESC", [cutoff, since])
    done = []
    for r in [r for r in rows if _failed.get(r["id"]) != r["last"]][:SWEEP_MAX]:
        try:
            organize(r["id"])
            done.append(r["id"])
            _failed.pop(r["id"], None)
        except Exception:  # noqa: BLE001
            _failed[r["id"]] = r["last"]
            log.warning("讨论 %s 整理失败", r["id"], exc_info=True)
    return done


def _sweep_loop() -> None:
    while True:
        time.sleep(SWEEP_S)
        try:
            sweep()
        except Exception:  # noqa: BLE001
            log.warning("讨论整理轮询失败", exc_info=True)


def on_startup() -> None:
    adopt_thinks()
    if os.environ.get("SELF_STARTUP_NO_AUTOREFRESH"):
        return
    threading.Thread(target=_sweep_loop, daemon=True, name="talk-topics").start()


@router.get("/topics")
def topics(limit: int = 50):
    return [_row(r) for r in db.rows("SELECT * FROM talk_topics ORDER BY updated_at DESC LIMIT ?", [min(limit, 200)])]


@router.get("/topics/{tid}")
def topic(tid: int):
    if not (t := _row(db.row("SELECT * FROM talk_topics WHERE id=?", [tid]))):
        raise HTTPException(404)
    return t


class RefreshIn(BaseModel):
    session_id: int


@router.post("/topics/refresh")
def refresh(body: RefreshIn):
    return organize(body.session_id)


class StepsIn(BaseModel):
    next_steps: list[str]


@router.post("/topics/{tid}/tasks")
def add_tasks(tid: int, body: StepsIn):
    """人勾选的下一步加到今天的事项；加过的不重复加。"""
    t = topic(tid)
    added = {x["title"] for x in db.rows(f"SELECT title FROM tasks WHERE id IN ({','.join('?' * len(t['task_ids'])) or 'NULL'})", t["task_ids"])}
    ids = t["task_ids"] + [tasks.create({"title": s.strip()})["id"] for s in dict.fromkeys(body.next_steps) if s.strip() and s.strip() not in added]
    db.update("talk_topics", tid, {"task_ids": json.dumps(ids)})
    return topic(tid)


class JudgeIn(BaseModel):
    text: str


@router.post("/topics/{tid}/judgments")
def add_judgment(tid: int, body: JudgeIn):
    """人点了「记进台账」的结论，作为自己的判断记下；同一句只记一次。"""
    t = topic(tid)
    text = body.text.strip()
    if not text:
        raise HTTPException(400, "empty")
    if text not in {j["text"] for j in t["judgments"]}:
        jid = kb_judge.add(text, note=f"讨论议题《{t['title']}》里的结论", sources=[{"title": f"讨论：{t['title']}", "link": f"#talk/t/{tid}"}])
        db.update("talk_topics", tid, {"judgments": json.dumps(t["judgments"] + [{"id": jid, "text": text}], ensure_ascii=False)})
        kb_graph.schedule_refresh()
    return topic(tid)


@router.get("/frames")
def frames():
    return kb_lens.overview()


GUIDE = """## 讨论：深入而简练的讨论伙伴
用户来聊想法，不会告诉你这是哪种讨论，你自己判断，中途变了就跟着变：
- 脑暴（想点子、找方向）：先抓目标和最硬的约束，首轮只给 2 个机制不同的候选，每个一句话说清怎么起作用；推荐一个并点明最关键的代价。用户选中后沿它深挖，不每轮重列点子。
- 理思路（有个想法、卡住了）：复原它起作用的因果链，找出真正的瓶颈、最脆弱的前提和失败条件；主动给更强的改法，并设计能区分原方案和改法的最小实验。
- 判断（要取舍、评估值不值、估空间、检验观点）：先忠实理解主张和依据，从框架库里挑最贴近的判断卡，按「目标 → 角度 → 手段 → 空间 → 好坏标准 → 反模式」推进；
  给最强反例和替代解释，划清成立边界，说明你的判断和信心、什么证据会让双方改主意。不为反对而反对，都不贴切就按同样的结构临时搭一个。
你和用户共同思考，主动提出判断、给新视角、敢交锋；不只当提问教练，也不迎合。这是对话式分析，不执行工程任务，不输出完成标准、自主决策或验收汇报。
- 每轮紧扣用户刚说的，只推进最重要的一处分歧：先给一句有信息量的判断，再用最必要的理由支撑；必要时只问一个能推动讨论的问题。
- 简练是硬约束：除非用户要求展开，每轮正文不超过 300 个汉字，优先 150–250 字。
- 把用户的判断、你的推断、已核实的事实分开；证据不足就说清不确定性和成立条件。
- 需要用户过往材料时先查知识库；会影响结论的最新事实、陌生技术或争议证据主动搜一手资料，附来源和日期，没搜到不能说已证实。
- 适合量化时可以做小规模计算、反例构造或模拟，写清假设和方法；思想实验标明「假设推演」，没实际运行不能叫实测。
- 有可靠结论或明确下一步时及时收束，不强迫用户继续答。聊完平台会自动整理成议题卡存档，不用提醒用户保存；不把你的意见说成用户的判断。
"""


def _judgment_md(c: dict) -> str:
    e = c.get("eval") or {}
    lines = [f"- {c['date'][:10]} [{c['type']}] {c['claim']}" + (f"（信心{c['confidence']}）" if c.get("confidence") else "")]
    if e:
        lines.append(f"  当时的评价：依据{e.get('strength')}；{e.get('basis')} 反方：{e.get('counter')} 怎么验证：{e.get('verify')}")
    lines += [f"  {r['at'][:10]} 复查 {r['verdict_name']}：{r['note']}" for r in c.get("reviews", []) if r.get("note")]
    return "\n".join(lines)


def _judge_context(sid: str) -> str:
    """从判断台账的某条判断接着想：带上这条判断、同一问题线上的立场变化。"""
    lg = kb_judge.ledger_json()
    cards = {c["sid"]: c for c in [*lg["due"], *lg["open"], *lg["singles"], *(x for th in lg["threads"] for x in th["items"])]}
    c = cards.get(sid)
    if not c:
        return ""
    parts = ["## 用户想接着想的这条判断（来自判断台账）\n" + _judgment_md(c)]
    if (th := next((t for t in lg["threads"] if t["question"] == c.get("thread")), None)):
        parts.append(f"## 同一问题线上用户的判断（立场：{th.get('stance', '')}）\n" + "\n".join(_judgment_md(x) for x in th["items"]))
    return "\n\n".join(parts)


def agent_context(ref: str) -> str:
    """ref：lens:<卡片 id> 从框架库点了某张卡开聊；judge:<判断 sid> 从判断台账接着想；think:<id> 原今日一想的话题。"""
    ts = tasks.list_for(db.today())
    lines = [f"今天 {db.today()}。今天的事项（讨论计划、取舍时参考，别主动念给用户听）："]
    lines += [f"- [{t['status']}] {t['title']}" for t in ts[:15]] or ["（还没有事项）"]
    card = kb_lens.get(ref.removeprefix("lens:")) if ref.startswith("lens:") else None
    parts = [GUIDE, f"## 用户选了这张判断卡来聊\n{kb_lens.card_md(card)}" if card else f"## 框架库（判断卡目录）\n{kb_lens.index()}"]
    if ref.startswith("judge:") and (j := _judge_context(ref.removeprefix("judge:"))):
        parts.append(j)
    if ref.startswith("think:") and (t := _think(ref)):
        parts.append(f"## 这个话题原来的问题\n{t['question']}" + (f"\n用户一开始的判断：{t['stance']}" if t["stance"] else ""))
    return "\n\n".join(parts + ["\n".join(lines)])


def _think(ref: str) -> dict | None:
    if not db.row("SELECT 1 FROM sqlite_master WHERE name='kb_thinks'"):
        return None
    try:
        return db.row("SELECT * FROM kb_thinks WHERE id=?", [int(ref.split(":")[1])])
    except ValueError:
        return None


def adopt_thinks() -> int:
    """原「今日一想」的话题搬进讨论：它们的对话改挂到讨论下（ref 仍是 think:<id>），没聊过的用问题开一段；之后照常整理成议题卡。可重复跑。"""
    if not db.row("SELECT 1 FROM sqlite_master WHERE name='kb_thinks'"):
        return 0
    n = 0
    for t in db.rows("SELECT * FROM kb_thinks ORDER BY id"):
        ref = f"think:{t['id']}"
        moved = db.execute("UPDATE chat_sessions SET module='talk' WHERE module='kb' AND ref=?", [ref])
        if not moved and not db.row("SELECT 1 FROM chat_sessions WHERE module='talk' AND ref=?", [ref]):
            sid = db.insert("chat_sessions", {"module": "talk", "ref": ref, "engine": "", "title": t["question"][:40],
                                              "created_at": t["created_at"], "updated_at": t["created_at"]})
            text = t["question"] + (f"\n我一开始的判断：{t['stance']}" if t["stance"] else "")
            db.insert("chat_messages", {"session_id": sid, "role": "user", "content": text, "created_at": t["created_at"]})
            moved = 1
        n += moved
    return n
