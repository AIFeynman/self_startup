"""今日板块的子页：深度 / 动手 / 学 / 台账 / 画像。

只读复用现有栏目（知识库检索、深度学习的深读和计划、调研的产品体验、判断台账），记录存本板块自己的表；
由 today.py 挂路由，下划线开头的文件不会被当成独立板块。大模型统一走 today._llm（测试里替换），失败都有规则兜底。
"""
from __future__ import annotations

import json
import re
from datetime import date, timedelta

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import db, kb_judge

SCHEMA = """
CREATE TABLE IF NOT EXISTS today_topics (         -- 每周的深度主题：候选 / 进行中 / 结束
    id INTEGER PRIMARY KEY AUTOINCREMENT, week TEXT NOT NULL, title TEXT NOT NULL, why TEXT DEFAULT '',
    source TEXT DEFAULT '', status TEXT DEFAULT 'candidate', created_at TEXT
);
CREATE TABLE IF NOT EXISTS today_memos (          -- 思考稿：结论 → 为什么 → 数字 → 怎么验证 → 对我的项目
    id INTEGER PRIMARY KEY AUTOINCREMENT, topic_id INTEGER, day TEXT, conclusion TEXT DEFAULT '', why TEXT DEFAULT '',
    numbers TEXT DEFAULT '', verify TEXT DEFAULT '', transfer TEXT DEFAULT '', critique TEXT DEFAULT '{}', score INTEGER,
    created_at TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS today_trials (         -- 动手：产品亲测 / 开源上手
    id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, key TEXT DEFAULT '', name TEXT NOT NULL, url TEXT DEFAULT '',
    plan TEXT DEFAULT '{}', result TEXT DEFAULT '{}', verdict TEXT DEFAULT '', prob INTEGER, review_due TEXT DEFAULT '',
    status TEXT DEFAULT 'planned', created_at TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS today_kv (key TEXT PRIMARY KEY, value TEXT);
"""
router = APIRouter()

MEMO_FIELDS = ("conclusion", "why", "numbers", "verify", "transfer")
MEMO_DIMS = {"结论先行": 15, "机制": 20, "量化": 20, "验证方法": 20, "反方": 10, "迁移": 15}
OPP_STATUS = ("idea", "written", "tested", "dropped", "pushing")
REVIEW_DAYS = 30
MOTIVATIONS = [
    {"id": "M0", "name": "发现机会", "want": "看技术和产品是为了找值得自己做的机会", "levels": {"机会": "L2–L3"}},
    {"id": "M1", "name": "让自己的产品跑起来", "want": "能执行、能验证的增长打法和差异化定位", "levels": {"增长": "L1–L2", "产品定位": "L3"}},
    {"id": "M2", "name": "系统深入学大模型和 Agent", "want": "一张自己真懂的完整地图", "levels": {"Agent": "L3", "基座": "L2"}},
    {"id": "M3", "name": "用 AI teams 放大个人产出", "want": "一个人干一个团队的活，并且能证明", "levels": {"架构": "L3–L4", "度量": "L2"}},
    {"id": "M4", "name": "有自己的判断", "want": "有依据、能被验证的判断", "levels": {"质疑": "L3", "量化验证": "L1–L2"}},
    {"id": "M5", "name": "个人品牌和知识内容", "want": "把想透的东西变成内容和影响力", "levels": {"内容": "L1–L2"}},
]
Q_LEVELS = [("概念", r"是什么|什么意思|解释|含义|通俗|没懂|没明白"),
            ("机制", r"怎么做到|怎么实现|具体|怎么更新|怎么算|怎么解决|怎么保障|怎么组织|为什么|区别|对比|相比"),
            ("决策", r"有必要|值得|能做成|商业价值|借鉴|优势|是否|能不能|可以用在|定位|差异|有帮助|可信|置信|还成立|还需要")]

TOPIC_SYSTEM = """你在给一位用户挑本周的深度思考主题（每周只钻一个，每天 60 分钟）。画像在 profile；open_questions 是他最近亲口问过、没解决的问题；recent 是他最近在今日卡上判断、深读过的内容。
挑 3 个候选主题：优先来自他自己的问题，能在一周里读透、写出带数字和验证方法的结论；三个尽量覆盖不同动机（大模型和 Agent 学习 / AI teams 和他的平台 / 产品和增长）。
输出 JSON：{"topics": [{"title": "主题，≤24 字", "why": "为什么是它，点名他问过的问题或动机，≤50 字", "track": "M0–M5 之一"}]}"""
CRITIC_SYSTEM = """你是“批判者”：只给追问和评分，不给结论、不替他写答案。
按评分表给思考稿打分（满分 100）：结论先行 15、机制 20、量化 20、验证方法 20、反方 10、迁移 15。他的老毛病是缺结论、缺数字、缺验证方法，这几项从严。
再给 3 个最该追问的问题（每个 ≤40 字，盯最弱的维度）。
输出 JSON：{"score": 0, "dims": {"结论先行": 0, "机制": 0, "量化": 0, "验证方法": 0, "反方": 0, "迁移": 0}, "followups": ["", "", ""]}"""
PLAN_SYSTEM = """给用户写一张动手任务单。kind=product 是产品亲测（25 分钟）；kind=oss 是开源项目上手（约 100 分钟）。画像在 profile，他在做 AI 知识讲解视频产品，也在做 AI teams 学习平台。
product：tasks 是 3 个任务（第 1 个：从空白到第一个有用结果并计时；第 2 个：做一遍它宣传的核心卖点；第 3 个：用他自己工作里的一个难任务），claims 是 1–2 条要验证的宣传说法，guess 是用之前先猜的问题（会不会留下来用、对他产品是威胁还是可借鉴）。
oss：tasks 是 3 个递进练习（跑通官方示例；改一处关键参数或换一个组件并和先猜的对照；接进他自己的项目解决一个真实小问题），claims 是 README 里值得验证的说法，guess 是先猜的问题（核心设计为什么这样、换朴素做法会差多少、要不要自建）。
硬规则：只根据 about 里给出的产品 / 仓库介绍写，不知道的功能不要编；about 为空时，claims 写成“打开官网首页，记下它主打的一句话，验证是否属实”这类不依赖具体功能的说法。
guess 必须是留给他回答的问题（以问号结尾），不能替他回答。任务要贴合产品真实用途，不要硬套到他的产品上。
输出 JSON：{"tasks": ["", "", ""], "claims": [""], "guess": ""}"""


def _t():
    from . import today
    return today


def _week(d: str | None = None) -> str:
    x = date.fromisoformat((d or db.today())[:10])
    return (x - timedelta(days=x.weekday())).isoformat()


def _j(s, default):
    try:
        return json.loads(s) if s else default
    except (TypeError, ValueError):
        return default


# ---------- 深度 ----------

def _recent_cards(limit: int = 10) -> list[str]:
    rows = db.rows("SELECT payload FROM today_days ORDER BY day DESC LIMIT 7")
    acted = {r["key"] for r in db.rows("SELECT key FROM today_marks")}
    out = []
    for r in rows:
        for c in _j(r["payload"], {}).get("deep", []):
            if c["key"] in acted and c["title"] not in out:
                out.append(c["title"])
    return out[:limit]


def _topic_now(week: str) -> dict | None:
    return db.row("SELECT * FROM today_topics WHERE week=? AND status='active' ORDER BY id DESC", [week])


def _materials(title: str) -> list[dict]:
    t = _t()
    words = [w for w in re.split(r"[\s，,、：:（）()/]+", title) if len(w) >= 2][:6]
    out, seen = [], set()

    def add(item):
        if item["link"] not in seen:
            seen.add(item["link"])
            out.append(item)
    if t._has("learn_items") and words:
        where = " OR ".join("title LIKE ? OR summary LIKE ?" for _ in words)
        args = [a for w in words for a in (f"%{w}%", f"%{w}%")]
        for r in db.rows(f"SELECT id, kind, title, summary FROM learn_items WHERE status='done' AND ({where}) ORDER BY updated_at DESC LIMIT 4", args):
            add({"kind": "深读", "title": r["title"], "summary": t._plain(r["summary"] or "", 120), "link": f"#learn/item/{r['id']}"})
    if t._has("learn_steps") and words:
        where = " OR ".join("s.title LIKE ?" for _ in words)
        for r in db.rows(f"SELECT s.id, s.plan_id, s.title, p.topic FROM learn_steps s JOIN learn_plans p ON p.id=s.plan_id "
                         f"WHERE ({where}) ORDER BY s.id DESC LIMIT 3", [f"%{w}%" for w in words]):
            add({"kind": "学习章节", "title": r["title"], "summary": r["topic"], "link": f"#learn/plan/{r['plan_id']}/step/{r['id']}"})
    try:
        from .. import kb
        for r in kb.search(" ".join(words), "", 6):
            add({"kind": {"xarticle": "X 长文", "research": "调研", "paper": "论文"}.get(r["type"], r["type"] or "知识库"),
                 "title": r["title"], "summary": t._plain(r.get("summary") or "", 120), "link": "#kb/doc/" + r["path"]})
    except Exception:  # noqa: BLE001  知识库索引还没建时只用深读和章节
        pass
    return out[:10]


def _memo_out(m: dict) -> dict:
    return {**m, "critique": _j(m["critique"], {})}


@router.get("/deep")
def deep_page():
    week = _week()
    topic = _topic_now(week)
    cands = db.rows("SELECT * FROM today_topics WHERE week=? AND status='candidate' ORDER BY id", [week])
    memos = [_memo_out(m) for m in db.rows("SELECT * FROM today_memos WHERE topic_id=? ORDER BY id DESC", [topic["id"]])] if topic else []
    past = db.rows("SELECT * FROM today_topics WHERE status IN ('active','done') AND week<? ORDER BY week DESC LIMIT 8", [week])
    return {"week": week, "topic": topic, "candidates": cands, "memos": memos,
            "materials": _materials(topic["title"]) if topic else [], "past": past, "dims": MEMO_DIMS}


@router.post("/deep/suggest")
def deep_suggest():
    t = _t()
    week = _week()
    qs = t._open_questions(30)
    try:
        res = t._llm(TOPIC_SYSTEM, {"profile": t.PROFILE, "open_questions": qs, "recent": _recent_cards()})
        topics = [x for x in res.get("topics") or [] if isinstance(x, dict) and str(x.get("title") or "").strip()][:3]
        src = "llm"
    except Exception:  # noqa: BLE001  离线时直接拿你最近问过的问题当候选
        topics = [{"title": t._plain(q, 40), "why": "你最近问过的问题"} for q in qs[:3]]
        src = "rule"
    db.execute("DELETE FROM today_topics WHERE week=? AND status='candidate'", [week])
    for x in topics:
        db.insert("today_topics", {"week": week, "title": str(x["title"]).strip()[:60], "why": str(x.get("why") or "")[:120],
                                   "source": src, "status": "candidate", "created_at": db.now()})
    return {"candidates": db.rows("SELECT * FROM today_topics WHERE week=? AND status='candidate' ORDER BY id", [week])}


class TopicIn(BaseModel):
    title: str = ""
    id: int | None = None


@router.post("/deep/topic")
def deep_topic(body: TopicIn):
    week = _week()
    db.execute("UPDATE today_topics SET status='done' WHERE week=? AND status='active'", [week])
    if body.id:
        if not db.row("SELECT id FROM today_topics WHERE id=?", [body.id]):
            raise HTTPException(404, "topic")
        db.execute("UPDATE today_topics SET status='active' WHERE id=?", [body.id])
        return {"ok": True, "id": body.id}
    if not body.title.strip():
        raise HTTPException(400, "title")
    tid = db.insert("today_topics", {"week": week, "title": body.title.strip()[:60], "source": "mine", "status": "active", "created_at": db.now()})
    return {"ok": True, "id": tid}


class MemoIn(BaseModel):
    topic_id: int
    conclusion: str = ""
    why: str = ""
    numbers: str = ""
    verify: str = ""
    transfer: str = ""
    id: int | None = None


@router.post("/deep/memo")
def deep_memo(body: MemoIn):
    data = {k: getattr(body, k).strip() for k in MEMO_FIELDS}
    if not any(data.values()):
        raise HTTPException(400, "empty")
    if body.id:
        db.update("today_memos", body.id, {**data, "updated_at": db.now()})
        return {"ok": True, "id": body.id}
    mid = db.insert("today_memos", {"topic_id": body.topic_id, "day": db.today(), **data, "created_at": db.now(), "updated_at": db.now()})
    return {"ok": True, "id": mid}


def _rule_critique(m: dict) -> dict:
    dims = {"结论先行": 15 if m["conclusion"] else 0, "机制": 20 if len(m["why"]) >= 30 else (10 if m["why"] else 0),
            "量化": 20 if re.search(r"\d", m["numbers"]) else 0, "验证方法": 20 if m["verify"] else 0, "反方": 0,
            "迁移": 15 if m["transfer"] else 0}
    ups = []
    if not re.search(r"\d", m["numbers"]):
        ups.append("数字呢？给一个估算或对比，哪怕是数量级。")
    if not m["verify"]:
        ups.append("怎么验证？什么实验或数据能证明或推翻它？")
    ups.append("最强的反方是什么？为什么你仍然坚持？")
    if not m["transfer"]:
        ups.append("它对你的哪个项目有用？用在哪、边界在哪？")
    return {"score": sum(dims.values()), "dims": dims, "followups": ups[:3], "src": "rule"}


@router.post("/deep/memo/{mid}/critique")
def deep_critique(mid: int):
    t = _t()
    m = db.row("SELECT m.*, t.title topic FROM today_memos m LEFT JOIN today_topics t ON t.id=m.topic_id WHERE m.id=?", [mid])
    if not m:
        raise HTTPException(404, "memo")
    try:
        res = t._llm(CRITIC_SYSTEM, {"topic": m["topic"], "memo": {k: m[k] for k in MEMO_FIELDS}, "profile": t.PROFILE})
        out = {"score": int(res.get("score") or 0), "dims": res.get("dims") or {}, "followups": [str(x) for x in res.get("followups") or []][:3], "src": "llm"}
    except Exception:  # noqa: BLE001
        out = _rule_critique(m)
    db.update("today_memos", mid, {"critique": json.dumps(out, ensure_ascii=False), "score": out["score"], "updated_at": db.now()})
    return out


# ---------- 动手 ----------

def _hands_candidates() -> list[dict]:
    t = _t()
    out, seen = [], set()
    p = db.row("SELECT payload FROM today_days ORDER BY day DESC LIMIT 1")
    for c in (_j(p["payload"], {}).get("deep", []) + _j(p["payload"], {}).get("quick", [])) if p else []:
        if c["kind"] in ("new", "product") and (c.get("slot") == "track" or c["kind"] == "new"):
            out.append({"kind": "product", "name": c.get("company") or c["title"].split("：")[0], "url": c.get("src_url") or "",
                        "why": c.get("why") or c.get("summary", ""), "key": c["key"], "from": c["label"]})
    if t._has("feed_items"):
        for r in db.rows("SELECT id, title, summary, url, popularity, extra FROM feed_items WHERE source='github' "
                         "ORDER BY substr(date,1,10) DESC, popularity DESC LIMIT 6"):
            gist = _j(r["extra"], {}).get("gist") or t._plain(r["summary"] or "", 120)
            out.append({"kind": "oss", "name": r["title"].split("：")[0], "url": r["url"], "why": gist, "key": f"feed:{r['id']}", "from": "GitHub"})
    done = {r["url"] for r in db.rows("SELECT url FROM today_trials")}
    res = []
    for c in out:
        if c["url"] not in done and c["name"] not in seen:
            seen.add(c["name"])
            res.append(c)
    return res[:10]


def _trial_out(r: dict) -> dict:
    return {**r, "plan": _j(r["plan"], {}), "result": _j(r["result"], {})}


@router.get("/hands")
def hands_page():
    return {"candidates": _hands_candidates(),
            "trials": [_trial_out(r) for r in db.rows("SELECT * FROM today_trials ORDER BY id DESC LIMIT 40")],
            "due_reviews": [_trial_out(r) for r in db.rows("SELECT * FROM today_trials WHERE status='done' AND review_due<=? "
                                                           "AND review_due!='' ORDER BY review_due", [db.today()])]}


class PlanIn(BaseModel):
    kind: str
    name: str
    url: str = ""
    key: str = ""


def _rule_plan(kind: str, name: str) -> dict:
    if kind == "oss":
        return {"tasks": [f"按 README 跑通 {name} 的官方示例，记下踩到的坑", "改一处关键参数或换掉一个组件，看结果怎么变，和你先猜的对照",
                          "在你自己的一个项目里用它解决一个真实的小问题（单独 worktree）"],
                "claims": ["README 里说的核心收益"], "guess": "它的核心设计为什么这样做？换成朴素做法会差多少？你要不要自建？"}
    return {"tasks": [f"从空白到 {name} 给出第一个有用结果，记下用了几分钟", "把它宣传的核心卖点完整做一遍",
                      "拿你自己工作里的一个难任务试一次"],
            "claims": ["官方宣传的上手速度和效果"], "guess": "用之前先猜：你会留下来用吗？它对你的产品是威胁还是可借鉴？"}


@router.post("/hands/plan")
def hands_plan(body: PlanIn):
    t = _t()
    if body.kind not in ("product", "oss") or not body.name.strip():
        raise HTTPException(400, "kind / name")
    about = ""
    if body.key:
        try:
            c = t._card(body.key)
            about = "；".join(x for x in (c.get("title"), c.get("summary"), c.get("why")) if x)
        except HTTPException:
            about = ""
    if not about and body.kind == "oss" and t._has("feed_items"):
        r = db.row("SELECT title, summary FROM feed_items WHERE url=?", [body.url])
        about = "；".join(x for x in (r["title"], r["summary"]) if x) if r else ""
    try:
        res = t._llm(PLAN_SYSTEM, {"kind": body.kind, "name": body.name, "url": body.url, "about": about, "profile": t.PROFILE})
        plan = {"tasks": [str(x) for x in res.get("tasks") or []][:3], "claims": [str(x) for x in res.get("claims") or []][:2],
                "guess": str(res.get("guess") or "")}
        if len(plan["tasks"]) < 3 or not plan["guess"].rstrip().endswith(("？", "?")):
            raise ValueError("short")
    except Exception:  # noqa: BLE001
        plan = _rule_plan(body.kind, body.name.strip())
    tid = db.insert("today_trials", {"kind": body.kind, "key": body.key, "name": body.name.strip(), "url": body.url.strip(),
                                     "plan": json.dumps(plan, ensure_ascii=False), "status": "planned", "created_at": db.now(), "updated_at": db.now()})
    return _trial_out(db.row("SELECT * FROM today_trials WHERE id=?", [tid]))


class RecordIn(BaseModel):
    guess: str = ""
    minutes_to_value: int | None = None
    tasks_done: list[bool] = []
    best: str = ""
    worst: str = ""
    compare: str = ""
    verdict: str = ""        # 产品：会用 / 借鉴 / 不用；开源：采用 / 只借鉴 / 不采用
    keep_using: bool | None = None
    prob: int | None = None
    note: str = ""


@router.post("/hands/{tid}/record")
def hands_record(tid: int, body: RecordIn):
    r = db.row("SELECT * FROM today_trials WHERE id=?", [tid])
    if not r:
        raise HTTPException(404, "trial")
    due = (date.fromisoformat(db.today()) + timedelta(days=REVIEW_DAYS)).isoformat()
    result = body.model_dump()
    db.update("today_trials", tid, {"result": json.dumps(result, ensure_ascii=False), "verdict": body.verdict, "prob": body.prob,
                                    "review_due": due, "status": "done", "updated_at": db.now()})
    if r["kind"] == "product":            # 产品亲测也进调研里的“产品体验”，那边能搜到
        from . import research
        done = sum(bool(x) for x in body.tasks_done)
        exp = "；".join(x for x in (f"首次拿到价值 {body.minutes_to_value} 分钟" if body.minutes_to_value is not None else "",
                                    f"3 个任务完成 {done} 个" if body.tasks_done else "", f"对比：{body.compare}" if body.compare else "",
                                    f"结论：{body.verdict}" if body.verdict else "", body.note) if x)
        research.create_product(research.ProductIn(name=r["name"], url=r["url"], experience=exp, pros=body.best, cons=body.worst,
                                                   rating=4 if body.keep_using else (3 if body.verdict == "借鉴" else 2),
                                                   tags=["今日亲测"], used_at=db.today()))
    if body.prob is not None:
        claim = (f"{r['name']} 半年内会有明显起色（融资、收入或持续上榜）" if r["kind"] == "product"
                 else f"30 天后我还会在项目里用 {r['name']}")
        kb_judge.add(claim, "预测", "高" if body.prob >= 70 or body.prob <= 30 else "中",
                     (date.fromisoformat(db.today()) + timedelta(days=180 if r["kind"] == "product" else REVIEW_DAYS)).isoformat(),
                     f"今日动手 · 概率 {body.prob}%" + (f" · {body.note}" if body.note else ""),
                     [{"title": r["name"], "url": r["url"]}] if r["url"] else [{"title": r["name"]}])
    return _trial_out(db.row("SELECT * FROM today_trials WHERE id=?", [tid]))


# ---------- 学 ----------

def _pins() -> list[int]:
    r = db.row("SELECT value FROM today_kv WHERE key='learn_pins'")
    return [int(x) for x in _j(r["value"], [])] if r else []


@router.get("/learn")
def learn_page():
    t = _t()
    if not t._has("learn_plans"):
        return {"plans": [], "all": []}
    plans = db.rows("SELECT id, topic, method, status FROM learn_plans WHERE status='active' ORDER BY id DESC")
    pins = [p for p in _pins() if any(x["id"] == p for x in plans)]
    if not pins:   # 默认：增长（商业与增长学法）的最新一个 + 你学得最多的一个（基座主线）
        biz = next((p["id"] for p in plans if p["method"] == "business"), None)
        recent = [r["plan_id"] for r in db.rows("SELECT plan_id FROM learn_events GROUP BY plan_id ORDER BY COUNT(*) DESC")] \
            if t._has("learn_events") else []
        for pid in [biz, *recent, *(p["id"] for p in plans)]:
            if pid and pid not in pins and any(x["id"] == pid for x in plans):
                pins.append(pid)
            if len(pins) == 2:
                break
    out = []
    for pid in pins[:2]:
        p = next(x for x in plans if x["id"] == pid)
        steps = db.rows("SELECT id, title, status, stage, ord, est_hours FROM learn_steps WHERE plan_id=? ORDER BY stage, ord, id", [pid])
        nxt = next((s for s in steps if s["status"] not in ("done", "skipped")), None)
        out.append({**p, "done": sum(s["status"] == "done" for s in steps), "total": len(steps),
                    "next": {**nxt, "link": f"#learn/plan/{pid}/step/{nxt['id']}"} if nxt else None, "link": f"#learn/plan/{pid}"})
    return {"plans": out, "all": [{"id": p["id"], "topic": p["topic"]} for p in plans]}


class PinIn(BaseModel):
    plan_ids: list[int]


@router.post("/learn/pin")
def learn_pin(body: PinIn):
    db.execute("INSERT OR REPLACE INTO today_kv (key, value) VALUES ('learn_pins', ?)", [json.dumps(body.plan_ids[:2])])
    return {"ok": True}


# ---------- 台账 ----------

class OppPatch(BaseModel):
    status: str = ""
    note: str = ""


@router.post("/opps/{oid}")
def opp_update(oid: int, body: OppPatch):
    o = db.row("SELECT * FROM today_opps WHERE id=?", [oid])
    if not o:
        raise HTTPException(404, "opp")
    data = {"updated_at": db.now()}
    if body.status:
        if body.status not in OPP_STATUS:
            raise HTTPException(400, "status")
        data["status"] = body.status
    if body.note.strip():
        data["note"] = ((o["note"] or "") + f"\n{db.today()}：{body.note.strip()}").strip()
    db.update("today_opps", oid, data)
    return {"ok": True}


@router.get("/ledger")
def ledger_page():
    t = _t()
    week = _week()
    try:
        upcoming = kb_judge.ledger_json().get("upcoming", [])
    except Exception:  # noqa: BLE001
        upcoming = []
    mine = db.rows("SELECT note, created_at FROM kb_judgments WHERE created_at>=?", [week]) if t._has("kb_judgments") else []
    opps = db.rows("SELECT * FROM today_opps ORDER BY CASE status WHEN 'pushing' THEN 0 WHEN 'tested' THEN 1 WHEN 'written' THEN 2 "
                   "WHEN 'idea' THEN 3 ELSE 4 END, id DESC")
    return {
        "due": t._due(), "upcoming": [{k: c.get(k) for k in ("sid", "title", "claim", "due", "type", "link")} for c in upcoming],
        "opps": opps, "opp_status": OPP_STATUS,
        "stats": {"week": week, "judgments": len(mine), "with_prob": sum("概率" in (m["note"] or "") for m in mine),
                  "memos": db.row("SELECT COUNT(*) n FROM today_memos WHERE day>=?", [week])["n"],
                  "trials": db.row("SELECT COUNT(*) n FROM today_trials WHERE status='done' AND updated_at>=?", [week])["n"],
                  "opps": db.row("SELECT COUNT(*) n FROM today_opps WHERE day>=?", [week])["n"]},
    }


# ---------- 画像 ----------

def _question_signals() -> dict:
    t = _t()
    if not t._has("annotation_msgs"):
        return {}
    out: dict = {}
    for r in db.rows("SELECT a.title, m.content FROM annotation_msgs m JOIN annotations a ON a.id=m.annotation_id WHERE m.role='user'"):
        area = ("基座" if re.search(r"基座|MoE|注意力|训练|量化|Loop|MTP|蒸馏|Chinchilla", r["title"] or "", re.I) else
                "增长 / 商业" if re.search(r"Growth|增长|Revid|Ads|广告|客户", r["title"] or "", re.I) else
                "Agent" if re.search(r"Agent|Harness|skill|MCP|Claude|Codex|评测|Eval|Teams|自进化", r["title"] or "", re.I) else "其他")
        lv = [n for n, p in Q_LEVELS if re.search(p, r["content"] or "")]
        d = out.setdefault(area, {"概念": 0, "机制": 0, "决策": 0, "合计": 0})
        d["合计"] += 1
        if lv:
            d[lv[-1]] += 1
    return out


def _quiz_dims() -> dict:
    t = _t()
    if not t._has("learn_events"):
        return {}
    acc: dict = {}
    for r in db.rows("SELECT data FROM learn_events WHERE kind='quiz'"):
        for k, v in (_j(r["data"], {}).get("dims") or {}).items():
            acc.setdefault(k, []).append(v)
    return {k: round(sum(v) / len(v)) for k, v in acc.items() if v}


@router.get("/profile")
def profile_page():
    return {"motivations": MOTIVATIONS, "ladder": ["L1 知道", "L2 懂机制", "L3 会判断", "L4 做得出", "L5 能预判"],
            "signals": {"questions": _question_signals(), "quiz": _quiz_dims(),
                        "memo_avg": (db.row("SELECT AVG(score) a FROM today_memos WHERE score IS NOT NULL") or {}).get("a"),
                        "trials": db.row("SELECT COUNT(*) n FROM today_trials WHERE status='done'")["n"]}}
