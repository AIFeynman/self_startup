"""判断台账：把散在复盘、批注、学习作答、深读、信息推荐里的「我的判断」沉淀成可回头检查的条目。

- 每条判断由 LLM 归类（观点 / 预测 / 评价 / 疑问；事实复述不收），并附 Agent 评价：依据强弱、最强反方、怎么验证；
- 同一个问题上的判断串成「问题线」，按时间看我的立场怎么变；
- 复查：预测按它自己的兑现期，观点 / 评价第 30、90 天，之后每半年；到期时 Agent 用之后新增的材料和判断给参考结论；
- 我写下的复查（仍成立 / 修正 / 推翻 / 还看不出 / 已解决 / 改期）和直接记的判断都只追加，重新整理不覆盖；
  修正 / 推翻时写的新看法本身也作为一条判断回流，问题线里就能看到立场变化。
LLM 结果按内容 hash 缓存（kb_claim_cache / kb_llm_cache），在 kb_graph.refresh() 里增量跑。
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import re

from . import db
from .kb_graph import SUB_NAMES, _clip, _h, _j, _sig, _sig_hash, _sig_out, _src_link, fname, wl

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS kb_claim_cache (sid TEXT PRIMARY KEY, hash TEXT, data TEXT, at TEXT);
CREATE TABLE IF NOT EXISTS kb_judgments (          -- 我直接记的判断 / 预测（只追加）
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    type TEXT DEFAULT '',                          -- 观点 / 预测 / 评价；空 = 让 LLM 判断
    confidence TEXT DEFAULT '',
    due TEXT DEFAULT '',                           -- 我指定的复查日
    note TEXT DEFAULT '',
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS kb_claim_reviews (      -- 复查记录（只追加）
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sid TEXT NOT NULL,
    verdict TEXT NOT NULL,                         -- holds / revised / overturned / pending / resolved / snooze
    note TEXT DEFAULT '',
    due TEXT DEFAULT '',                           -- 指定下次复查日（改期，或复查时顺手定）
    agent TEXT DEFAULT '',                         -- 复查时看到的 Agent 参考结论（留档）
    at TEXT
);
CREATE INDEX IF NOT EXISTS idx_kb_claim_reviews_sid ON kb_claim_reviews(sid);
"""

TYPES = ["观点", "预测", "评价", "疑问"]
VERDICTS = {"holds": "仍成立", "revised": "修正", "overturned": "推翻", "pending": "还看不出", "resolved": "已解决", "snooze": "改期"}
INTERVALS = [30, 90, 180]       # 观点 / 评价：第几次复查前隔多少天，之后都按最后一个
PRED_DEFAULT = 90               # 预测没估出兑现期时
CLASSIFY_V = 2
MAX_RECHECK = 15                # 每次整理最多给几条到期判断写参考结论


def llm_json(system: str, payload: dict, max_tokens: int = 6000) -> dict:
    from . import kb_graph      # 运行时取，测试里 monkeypatch kb_graph.llm_json 一处即可
    return kb_graph.llm_json(system, payload, max_tokens)


def _init() -> None:
    db.init([SCHEMA])


def _has(table: str) -> bool:
    return bool(db.row("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", [table]))


def _today() -> str:
    return db.today()


def _add_days(d: str, n: int) -> str:
    try:
        return (dt.date.fromisoformat(d[:10]) + dt.timedelta(days=n)).isoformat()
    except ValueError:
        return ""


# ---------- 信号：我直接记的判断 + 复查时写的新看法（kb_graph.signals 调用） ----------

def signals() -> list[dict]:
    out = []
    if _has("kb_judgments"):
        for r in db.rows("SELECT * FROM kb_judgments ORDER BY id"):
            out.append(_sig(f"my:{r['id']}", "judgment", "mine", _clip(r["text"], 40), mine=r["text"],
                            context=r["note"] or "", date=r["created_at"], link="#kb"))
    if _has("kb_claim_reviews"):
        for r in db.rows("SELECT * FROM kb_claim_reviews WHERE verdict IN ('revised','overturned') AND trim(note)!='' ORDER BY id"):
            out.append(_sig(f"rev:{r['id']}", "judgment", "revise", f"{VERDICTS[r['verdict']]}：{_clip(r['note'], 30)}",
                            mine=r["note"], context=f"复查时{VERDICTS[r['verdict']]}了之前的判断（{r['sid']}）", date=r["at"], link="#kb"))
    return out


# ---------- LLM：归类 + Agent 评价 / 问题线 / 到期参考结论 ----------

CLASSIFY_SYSTEM = """你在帮用户整理「判断台账」：把用户自己说过的话沉淀成以后能回头检查的判断。
输入是一批记录：mine 是用户原话，context 是它针对的问题 / 材料（可能含 Agent 当时的点评），claim 是已有的一句话浓缩。
逐条判断它属于哪一类：
- 观点：对某件事「应该 / 是 / 不是 / 更好」的主张或结论（包括做法上的经验结论）；
- 预测：对未来会发生什么的判断（会 / 将 / 未来 / 迟早 / 趋势），能在某个时间点被验证；
- 评价：对具体产品、论文、项目、方法、人的好坏 / 可信度 / 价值的判断；
- 疑问：用户提出的、还没有答案的问题，还没想清楚的地方（复盘里的「【问题】」是遇到的麻烦，写了原因 / 对策 / 结论的算观点）；
- 事实：只是复述材料内容、记住了某个事实、答题时复述要点，没有用户自己的立场；
- 其他：附和、闲聊、太碎无法检查。
对观点 / 预测 / 评价 / 疑问：
- claim：第一人称一句话（≤50 字），只依据 mine，不得加入 mine 没表达的观点；已有 claim 合适就沿用；
- confidence：从措辞看用户有多确定：高 / 中 / 低；
- horizon_days：仅预测填，从记录日期起大约多少天后能验证（30–720），其他填 null；
- eval（疑问填 null）：以严格但公正的评审身份写，每项一句话：
  strength 依据强弱（强 / 中 / 弱），basis 用户的依据是什么，counter 最有力的反方观点或反例，verify 以后看什么信号 / 做什么实验能验证或推翻。
输出 JSON：{"items": [{"sid": "原样返回", "type": "观点", "claim": "…", "confidence": "中", "horizon_days": null,
"eval": {"strength": "中", "basis": "…", "counter": "…", "verify": "…"}}]}"""

THREAD_SYSTEM = """下面是用户的判断台账（编号 sid、日期、类型、一句话判断、相关概念）。请把讨论同一个问题的判断串成「问题线」，用来看用户的立场如何随时间变化：
- question：这条线在回答的问题，≤25 字，用问句（如「Agent 评测该不该用 LLM 当评审？」）；
- 一条线至少 2 条判断，每条判断最多属于一条线；只把真正在回答同一个问题的放一起，宁缺毋滥；
- stance：用户目前（最新判断）的立场，第一人称一句话；
- shift：按时间看立场有没有变化：变了就写「从……到……」，只是补充细化写「细化：……」，没变化留空；
- previous 里有上次的问题线时尽量沿用原问题文字。
输出 JSON：{"threads": [{"question": "…？", "sids": ["…"], "stance": "…", "shift": ""}]}"""

RECHECK_SYSTEM = """用户在复查自己过去的一条判断。输入：这条判断（日期、类型、原话、当时 Agent 的评价、以往复查记录），
以及之后用户新增的相关判断和看过的材料（evidence，带 sid）。请给一个参考结论帮用户复查：
- suggest：仍成立 / 需修正 / 被推翻 / 证据不足 四选一；evidence 里没有能说明问题的内容就选「证据不足」，不要凭常识硬下结论；
- why：一两句话说明理由，引用依据时写 [sid]；
- ask：建议用户复查时问自己的一个问题。
输出 JSON：{"suggest": "仍成立", "why": "…", "ask": "…", "cites": ["sid"]}"""


def _cls_hash(s: dict) -> str:
    return _h(CLASSIFY_V, _sig_hash(s), s.get("claim", ""))


def classify(sigs: list[dict]) -> int:
    """给还没归类 / 内容变了的判断归类并写 Agent 评价。"""
    _init()
    cache = {r["sid"]: r["hash"] for r in db.rows("SELECT sid, hash FROM kb_claim_cache")}
    todo = [s for s in sigs if s["kind"] == "judgment" and cache.get(s["sid"]) != _cls_hash(s)]
    manual = {f"my:{r['id']}": r for r in db.rows("SELECT * FROM kb_judgments")}
    done = 0
    for i in range(0, len(todo), 15):
        batch = todo[i:i + 15]
        res = llm_json(CLASSIFY_SYSTEM, {"items": [
            {"sid": s["sid"], "source": SUB_NAMES.get(s["sub"], s["sub"]), "date": s["date"], "mine": _clip(s["mine"], 600),
             "context": _clip(s["context"], 400), "claim": s.get("claim", "")} for s in batch]})
        got = {str(x.get("sid")): x for x in res.get("items") or [] if isinstance(x, dict)}
        for s in batch:
            x = got.get(s["sid"])
            if not x:
                continue
            t = x.get("type") if x.get("type") in TYPES + ["事实", "其他"] else "其他"
            mr = manual.get(s["sid"])
            if mr and mr["type"] in TYPES:      # 我手动记的以我选的类型 / 信心为准
                t = mr["type"]
            ev = x.get("eval") if isinstance(x.get("eval"), dict) else None
            hd = x.get("horizon_days")
            data = {"type": t, "claim": _clip(x.get("claim") or s.get("claim") or s["mine"], 80),
                    "confidence": (mr or {}).get("confidence") or (x.get("confidence") if x.get("confidence") in ("高", "中", "低") else "中"),
                    "horizon_days": int(hd) if t == "预测" and isinstance(hd, (int, float)) and hd > 0 else None,
                    "eval": {k: _clip(str(ev.get(k) or ""), 120) for k in ("strength", "basis", "counter", "verify")} if ev and t != "疑问" else None}
            db.execute("INSERT INTO kb_claim_cache(sid, hash, data, at) VALUES (?,?,?,?) ON CONFLICT(sid) DO UPDATE SET "
                       "hash=excluded.hash, data=excluded.data, at=excluded.at",
                       [s["sid"], _cls_hash(s), json.dumps(data, ensure_ascii=False), db.now()])
            done += 1
    return done


def _cls_all() -> dict[str, dict]:
    if not _has("kb_claim_cache"):
        return {}
    return {r["sid"]: _j(r["data"], {}) for r in db.rows("SELECT sid, data FROM kb_claim_cache")}


def _thread_input(m: dict, cls: dict) -> list[dict]:
    items = [s for s in m["sigs"].values() if s["kind"] == "judgment" and (cls.get(s["sid"]) or {}).get("type") in TYPES]
    items.sort(key=lambda s: s["date"])
    return [{"sid": s["sid"], "date": s["date"], "type": cls[s["sid"]]["type"], "claim": cls[s["sid"]]["claim"],
             "concepts": s.get("concepts", [])} for s in items[-250:]]


def build_threads(m: dict) -> None:
    items = _thread_input(m, _cls_all())
    if len(items) < 2:
        return
    h = _h(items)
    r = db.row("SELECT hash, data FROM kb_llm_cache WHERE key='threads'")
    if r and r["hash"] == h:
        return
    prev = [{"question": t["question"]} for t in (_j(r["data"], {}) if r else {}).get("threads", [])]
    res = llm_json(THREAD_SYSTEM, {"previous": prev, "items": items}, max_tokens=8000)
    valid, used, out = {i["sid"] for i in items}, set(), []
    for t in res.get("threads") or []:
        if not isinstance(t, dict) or not t.get("question"):
            continue
        sids = [x for x in t.get("sids") or [] if x in valid and x not in used]
        if len(sids) < 2:
            continue
        used.update(sids)
        out.append({"question": _clip(t["question"], 40), "sids": sids, "stance": _clip(t.get("stance") or "", 100),
                    "shift": _clip(t.get("shift") or "", 120)})
    db.execute("INSERT INTO kb_llm_cache(key, hash, data, at) VALUES ('threads',?,?,?) ON CONFLICT(key) DO UPDATE SET "
               "hash=excluded.hash, data=excluded.data, at=excluded.at", [h, json.dumps({"threads": out}, ensure_ascii=False), db.now()])


def _threads() -> list[dict]:
    r = db.row("SELECT data FROM kb_llm_cache WHERE key='threads'") if _has("kb_llm_cache") else None
    return (_j(r["data"], {}) if r else {}).get("threads", [])


def _evidence(s: dict, m: dict, cls: dict) -> list[dict]:
    cs = set(s.get("concepts") or [])
    if not cs:
        return []
    ev = [x for x in m["sigs"].values() if x["sid"] != s["sid"] and x["date"] >= s["date"] and cs & set(x.get("concepts") or [])]
    ev.sort(key=lambda x: x["date"], reverse=True)
    return [{"sid": x["sid"], "date": x["date"], "kind": "我的判断" if x["kind"] == "judgment" else "看过的材料",
             "source": SUB_NAMES.get(x["sub"], x["sub"]), "title": _clip(x["title"], 60),
             "text": _clip((cls.get(x["sid"]) or {}).get("claim") or x.get("claim") or x["mine"] or x["context"], 160)} for x in ev[:15]]


def _recheck_payload(s: dict, c: dict, m: dict, cls: dict, reviews: list[dict]) -> dict:
    return {"judgment": {"date": s["date"], "type": c.get("type"), "claim": c.get("claim"), "mine": _clip(s["mine"], 400),
                         "eval": c.get("eval")},
            "reviews": [{"at": r["at"][:10], "verdict": VERDICTS.get(r["verdict"], r["verdict"]), "note": r["note"]} for r in reviews],
            "evidence": _evidence(s, m, cls)}


def recheck(sid: str, m: dict | None = None, *, force: bool = False) -> dict | None:
    """到期判断的 Agent 参考结论（按输入 hash 缓存；新证据进来才重算）。"""
    from . import kb_graph
    m = m or kb_graph.model()
    s = m["sigs"].get(sid)
    cls = _cls_all()
    c = cls.get(sid)
    if not s or not c or c.get("type") not in TYPES:
        return None
    p = _recheck_payload(s, c, m, cls, _reviews().get(sid, []))
    key, h = f"recheck:{sid}", _h(p)
    if not force:
        hit = kb_graph._cache_get(key, h)
        if hit is not None:
            return hit
    res = llm_json(RECHECK_SYSTEM, p, max_tokens=1500)
    out = {"suggest": res.get("suggest") if res.get("suggest") in ("仍成立", "需修正", "被推翻", "证据不足") else "证据不足",
           "why": _clip(res.get("why") or "", 240), "ask": _clip(res.get("ask") or "", 120),
           "cites": [x for x in res.get("cites") or [] if x in m["sigs"]], "n_evidence": len(p["evidence"]), "at": db.now()}
    kb_graph._cache_put(key, h, out)
    return out


def _agent_cached(sid: str, m: dict, cls: dict, reviews: list[dict]) -> dict | None:
    from . import kb_graph
    s, c = m["sigs"].get(sid), cls.get(sid)
    if not s or not c:
        return None
    hit = kb_graph._cache_get(f"recheck:{sid}", _h(_recheck_payload(s, c, m, cls, reviews)))
    if hit is not None:
        return hit
    r = db.row("SELECT data FROM kb_llm_cache WHERE key=?", [f"recheck:{sid}"])   # 证据变了：先给旧结论，标记过期
    return {**_j(r["data"], {}), "stale": True} if r else None


def refresh_llm(m: dict, status: dict | None = None) -> str:
    """kb_graph.refresh() 里调用：归类 → 问题线 → 到期判断的参考结论。返回一句进度说明。"""
    _init()
    st = status if status is not None else {}
    st["msg"] = "整理判断台账…"
    n = classify(list(m["sigs"].values()))
    st["msg"] = "串问题线…"
    try:
        build_threads(m)
    except Exception:  # noqa: BLE001
        log.exception("kb_judge threads")
    st["msg"] = "给到期判断写参考结论…"
    soon = _add_days(_today(), 3)
    rc = 0
    for card in ledger(m)["cards"]:
        if rc >= MAX_RECHECK:
            break
        if card["due"] and card["due"] <= soon and not (card["agent"] and not card["agent"].get("stale")):
            try:
                recheck(card["sid"], m)
                rc += 1
            except Exception:  # noqa: BLE001
                log.exception("kb_judge recheck %s", card["sid"])
    return f"判断台账：新归类 {n} 条，参考结论 {rc} 条"


# ---------- 复查节奏与台账 ----------

def _reviews() -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    if _has("kb_claim_reviews"):
        for r in db.rows("SELECT * FROM kb_claim_reviews ORDER BY id"):
            out.setdefault(r["sid"], []).append(r)
    return out


def schedule(s: dict, c: dict, reviews: list[dict], manual_due: str = "") -> tuple[str, str]:
    """(状态, 下次复查日)。状态：open 未复查 / holds / revised / overturned / pending / resolved。"""
    t = c.get("type")
    real = [r for r in reviews if r["verdict"] != "snooze"]
    status = real[-1]["verdict"] if real else "open"
    if t not in TYPES:
        return status, ""
    override = manual_due
    for r in reviews:              # 最近一次复查 / 改期指定的日子优先；之后又复查过、没指定就回到默认节奏
        override = r["due"]
    if status in ("overturned", "resolved") or (t == "预测" and status == "holds"):
        return status, ""          # 推翻了、疑问解决了、预测兑现了：不再复查
    if override:
        return status, override
    if t == "疑问":
        return status, ""
    if status == "pending":
        return status, _add_days(real[-1]["at"], 30)
    if t == "预测":
        return status, _add_days(real[-1]["at"], PRED_DEFAULT) if real else _add_days(s["date"], c.get("horizon_days") or PRED_DEFAULT)
    base = real[-1]["at"] if real else s["date"]
    return status, _add_days(base, INTERVALS[min(len(real), len(INTERVALS) - 1)])


def ledger(m: dict | None = None, paths: dict[str, str] | None = None) -> dict:
    """台账全量：cards（每条判断）+ threads。只读缓存，不调 LLM。"""
    from . import kb_graph
    m = m or kb_graph.model()
    paths = paths if paths is not None else {}
    cls, revs = _cls_all(), _reviews()
    manual = {f"my:{r['id']}": r for r in db.rows("SELECT * FROM kb_judgments")} if _has("kb_judgments") else {}
    threads = _threads()
    t_of = {sid: t["question"] for t in threads for sid in t["sids"]}
    cards, pending = [], 0
    for s in m["sigs"].values():
        if s["kind"] != "judgment":
            continue
        c = cls.get(s["sid"])
        if not c:
            pending += 1
            continue
        if c.get("type") not in TYPES:
            continue
        rs = revs.get(s["sid"], [])
        status, due = schedule(s, c, rs, (manual.get(s["sid"]) or {}).get("due") or "")
        cards.append({**_sig_out(s, paths), "doc": s["doc"], "type": c["type"], "claim": c["claim"], "confidence": c.get("confidence", ""),
                      "horizon_days": c.get("horizon_days"), "eval": c.get("eval"), "status": status, "due": due,
                      "reviews": [{"id": r["id"], "verdict": r["verdict"], "verdict_name": VERDICTS.get(r["verdict"], r["verdict"]),
                                   "note": r["note"], "due": r["due"], "at": r["at"]} for r in rs],
                      "agent": _agent_cached(s["sid"], m, cls, rs) if due else None, "thread": t_of.get(s["sid"], "")})
    cards.sort(key=lambda x: x["date"], reverse=True)
    return {"cards": cards, "threads": threads, "pending": pending}


def ledger_json() -> dict:
    from . import kb_graph
    m = kb_graph.model()
    lg = ledger(m, kb_graph._paths())
    cards, today = lg["cards"], _today()
    by = {c["sid"]: c for c in cards}
    threads = []
    for t in lg["threads"]:
        items = sorted((by[x] for x in t["sids"] if x in by), key=lambda c: c["date"])
        if len(items) >= 2:
            threads.append({**t, "items": items, "last": items[-1]["date"],
                            "changed": bool(t.get("shift")) and not t["shift"].startswith("细化")})
    threads.sort(key=lambda t: t["last"], reverse=True)
    cnt = {k: sum(c["type"] == k for c in cards) for k in TYPES}
    rv = [c for c in cards if c["status"] in ("holds", "revised", "overturned")]
    return {
        "stats": {"total": len(cards), "by_type": cnt, "due": sum(bool(c["due"]) and c["due"] <= today for c in cards),
                  "reviewed": len(rv), "verdicts": {k: sum(c["status"] == k for c in rv) for k in ("holds", "revised", "overturned")},
                  "threads": len(threads), "changed": sum(t["changed"] for t in threads), "pending": lg["pending"]},
        "today": today,
        "due": sorted((c for c in cards if c["due"] and c["due"] <= today), key=lambda c: c["due"]),
        "upcoming": sorted((c for c in cards if c["due"] and c["due"] > today), key=lambda c: c["due"])[:8],
        "threads": threads,
        "open": [c for c in cards if c["type"] == "疑问" and c["status"] != "resolved" and not c["thread"]],
        "singles": [c for c in cards if not c["thread"] and c["type"] != "疑问"],
        "verdicts": VERDICTS, "types": TYPES,
    }


# ---------- 写入（只追加） ----------

def add(text: str, type_: str = "", confidence: str = "", due: str = "", note: str = "") -> int:
    _init()
    text = text.strip()
    if not text:
        raise ValueError("empty")
    return db.insert("kb_judgments", {"text": text, "type": type_ if type_ in TYPES else "",
                                      "confidence": confidence if confidence in ("高", "中", "低") else "",
                                      "due": due[:10], "note": note.strip(), "created_at": db.now()})


def review(sid: str, verdict: str, note: str = "", due: str = "") -> int:
    _init()
    if verdict not in VERDICTS or not sid:
        raise ValueError("bad verdict")
    if verdict == "snooze" and not due:
        raise ValueError("snooze needs due")
    r = db.row("SELECT data FROM kb_llm_cache WHERE key=?", [f"recheck:{sid}"]) if _has("kb_llm_cache") else None
    return db.insert("kb_claim_reviews", {"sid": sid, "verdict": verdict, "note": note.strip(), "due": due[:10],
                                          "agent": r["data"] if r else "", "at": db.now()})


# ---------- Obsidian：JUDGMENTS.md + judgments/<问题>.md ----------

def _line(c: dict, paths: dict[str, str]) -> str:
    src = _src_link({"doc": c["doc"], "title": c["title"], "url": c["url"]}, paths)
    st = "未复查" if c["status"] == "open" else VERDICTS.get(c["status"], c["status"])
    return (f"- {c['date']} · {c['type']} · **{c['claim']}**（信心{c['confidence'] or '中'} · {st}"
            + (f" · 下次复查 {c['due']}" if c["due"] else "") + f"） · {c['sub_name']}：{src}")


def files(m: dict, paths: dict[str, str]) -> dict[str, str]:
    lj = ledger(m, paths)
    cards, today = lj["cards"], _today()
    if not cards:
        return {}
    by = {c["sid"]: c for c in cards}
    out: dict[str, str] = {}
    g = ["---", "type: judgments", "tags: [判断台账]", "---", "", "# 我的判断台账", "",
         f"{len(cards)} 条判断：" + " · ".join(f"{t} {sum(c['type'] == t for c in cards)}" for t in TYPES)
         + "。每条附 Agent 评价，到期复查；复查记录只追加。", ""]
    due = sorted((c for c in cards if c["due"] and c["due"] <= today), key=lambda c: c["due"])
    if due:
        g += ["## 待复查", *[_line(c, paths) for c in due], ""]
    g.append("## 问题线")
    for t in lj["threads"]:
        items = sorted((by[x] for x in t["sids"] if x in by), key=lambda c: c["date"])
        if len(items) < 2:
            continue
        g.append(f"- {wl(t['question'], 'judgments/')}（{len(items)} 条）— 现在：{t['stance']}" + (f"；{t['shift']}" if t["shift"] else ""))
        page = ["---", "type: thread", "tags: [问题线]", "---", "", f"# {t['question']}", "", f"**现在的立场：** {t['stance']}", ""]
        if t["shift"]:
            page += [f"**变化：** {t['shift']}", ""]
        page.append("## 时间线")
        for c in items:
            page.append(_line(c, paths))
            if c["eval"]:
                e = c["eval"]
                page.append(f"  > Agent 评价：依据{e['strength']}。{e['basis']}  反方：{e['counter']}  验证：{e['verify']}")
            page += [f"  > {r['at'][:10]} 复查：{r['verdict_name']}" + (f" — {r['note']}" if r["note"] else "") for r in c["reviews"]]
            if c["concepts"]:
                page.append("  概念：" + " · ".join(wl(x) for x in c["concepts"]))
        out[f"judgments/{fname(t['question'])}.md"] = "\n".join(page) + "\n"
    g.append("")
    opens = [c for c in cards if c["type"] == "疑问" and c["status"] != "resolved"]
    if opens:
        g += ["## 开放问题", *[_line(c, paths) for c in opens], ""]
    for t in ("预测", "观点", "评价"):
        cs = [c for c in cards if c["type"] == t and not c["thread"]]
        if cs:
            g += [f"## 其他{t}", *[_line(c, paths) for c in cs], ""]
    out["JUDGMENTS.md"] = "\n".join(g) + "\n"
    return out


def fts_rows(gfiles: dict[str, str]) -> list[dict]:
    rows = []
    for p, body in gfiles.items():
        if p.startswith("judgments/"):
            title = re.search(r"^# (.+)$", body, re.M)
            rows.append({"path": p, "type": "thread", "title": title.group(1) if title else p, "tags": ["问题线"], "date": "",
                         "summary": _clip((re.search(r"^\*\*现在的立场：\*\* (.+)$", body, re.M) or [None, ""])[1], 100), "body": body})
    return rows
