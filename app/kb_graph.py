"""知识图谱：把「我看过、想过、判断过」的内容按概念组织起来（像 Obsidian 的双链笔记）。

和 kb.py 的关系：kb.py 把各板块原样镜像成「来源」文件；这里只挑出带个人信号的内容——
- 判断（judgment）：复盘经验、划线批注里我的评论与追问、学习作答（含点评）、测试薄弱点、步骤反馈、
  深读时的感想与追问、论文一句话判断、产品体验；
- 材料（material）：我发起的调研、我选的深读（论文 / 项目 / 文章 / 书）、学习计划、点赞收藏或点开过的信息。
产品雷达等纯自动抓取、我没互动过的内容不进图谱（仍可在来源库里搜到）。

流程：signals() 收集信号 → DeepSeek 按批给每条信号抽 1–4 个概念（判断另浓缩一句 claim）→ 全部概念名合并同义词、
归类 → 应用我在页面上做的改名 / 合并 / 删除（kb_concept_edit，只追加，重建不覆盖）→ 输出 concepts/<概念>.md
（[[双链]]，Obsidian 可直接打开）和图谱 JSON。LLM 结果按内容 hash 缓存在 SQLite，只有新增 / 改动的信号才重新抽。
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
import time

from . import db

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS kb_sig_cache (sid TEXT PRIMARY KEY, hash TEXT, concepts TEXT DEFAULT '[]', claim TEXT DEFAULT '', at TEXT);
CREATE TABLE IF NOT EXISTS kb_llm_cache (key TEXT PRIMARY KEY, hash TEXT, data TEXT, at TEXT);
CREATE TABLE IF NOT EXISTS kb_concept_edit (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    op   TEXT NOT NULL,              -- rename（目标已存在即合并）/ hide 从图谱删除 / unhide
    src  TEXT NOT NULL,
    dst  TEXT DEFAULT '',
    at   TEXT
);
"""

SUB_NAMES = {
    "note": "复盘经验", "annotation": "批注", "answer": "学习作答", "quiz": "测试反馈", "feedback": "步骤反馈",
    "thought": "感想", "ask": "追问", "verdict": "论文判断", "product": "产品体验", "mynote": "深读笔记",
    "research": "调研", "paper": "论文深读", "repo": "项目解读", "article": "文章深读", "plan": "学习计划",
    "book": "读书", "hn": "HN 讨论", "feed": "看过的信息", "mine": "我记的判断", "revise": "复查时的新看法",
}
CATEGORIES = ["领域", "方法", "产品", "项目", "论文", "数据集", "人物", "公司", "其他"]
MAX_SUMMARIES = 40         # 每次刷新最多重写几个概念的「我的理解」

_lock = threading.Lock()
_running = False
_status = {"state": "idle", "at": "", "msg": ""}


def _init() -> None:
    db.init([SCHEMA])


def _h(*parts) -> str:
    return hashlib.sha1(json.dumps(parts, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]


def _has(table: str) -> bool:
    return bool(db.row("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", [table]))


def _clip(t: str, n: int) -> str:
    t = re.sub(r"\s+", " ", t or "").strip()
    return t if len(t) <= n else t[:n] + "…"


def _j(s, default):
    try:
        return json.loads(s) if s else default
    except (TypeError, ValueError):
        return default


# ---------- 收集个人信号 ----------

def _sig(sid, kind, sub, title, *, mine="", context="", date="", doc="", link="", url="") -> dict:
    return {"sid": sid, "kind": kind, "sub": sub, "title": title or "", "mine": (mine or "").strip(),
            "context": (context or "").strip(), "date": (date or "")[:10], "doc": doc, "link": link, "url": url}


def _item_doc(it: dict) -> str:
    return f"{'repo' if it['kind'] == 'github' else 'paper'}:{it['id']}"


def signals() -> list[dict]:
    out: list[dict] = []
    from . import kb_judge
    for fn in (_s_notes, _s_annotations, _s_learn, _s_items, _s_feed, _s_products, _s_materials, kb_judge.signals):
        try:
            out += fn()
        except Exception:  # noqa: BLE001 —— 单类出错不影响其它
            log.exception("kb_graph signals %s", fn.__name__)
    return out


def _s_notes() -> list[dict]:
    if not _has("review_notes"):
        return []
    kinds = {"problem": "问题", "lesson": "经验", "insight": "洞察", "idea": "想法", "spark": "灵感", "feeling": "感想"}
    return [_sig(f"note:{n['id']}", "judgment", "note", n["title"] or _clip(n["content"], 30),
                 mine=f"【{kinds.get(n['kind'], n['kind'])}】{n['title']}\n{n['content']}", date=n["date"],
                 doc=f"note:{n['id']}", link=f"#review/{n['date']}")
            for n in db.rows("SELECT * FROM review_notes ORDER BY id")]


def _s_annotations() -> list[dict]:
    if not _has("annotations"):
        return []
    from .kb import _slug
    out = []
    for a in db.rows("SELECT * FROM annotations ORDER BY id"):
        mine = [m["content"].strip() for m in db.rows(
            "SELECT content FROM annotation_msgs WHERE annotation_id=? AND role='user' AND status!='pending' ORDER BY id", [a["id"]])]
        if not mine:
            continue
        out.append(_sig(f"ann:{a['id']}", "judgment", "annotation", a["title"] or a["doc"], mine="\n".join(mine),
                        context=a["quote"] or "（针对全文）", date=a["created_at"], doc=f"annotation:{_slug(a['doc'], 30)}",
                        link=a["link"] or ""))
    return out


def _s_learn() -> list[dict]:
    """学习计划里的作答（含点评）、章末测试、步骤反馈。check / check_review 记的是同一题，留带点评的那条。"""
    if not _has("learn_events"):
        return []
    steps = {s["id"]: s for s in db.rows("SELECT id, plan_id, title, feedback, understanding, done_at FROM learn_steps")} \
        if _has("learn_steps") else {}
    plans = {p["id"]: p["topic"] for p in db.rows("SELECT id, topic FROM learn_plans")} if _has("learn_plans") else {}
    items = {i["id"]: i for i in db.rows("SELECT id, kind, title FROM learn_items")} if _has("learn_items") else {}
    best: dict[tuple, dict] = {}
    out = []
    for e in db.rows("SELECT * FROM learn_events WHERE kind IN ('check','check_review','qa','qa_review','quiz') ORDER BY id"):
        d = _j(e["data"], {})
        st = steps.get(e["step_id"]) or {}
        if e["kind"] == "quiz":
            weak = d.get("weak_points") or []
            if not (d.get("summary") or weak):
                continue
            out.append(_sig(f"quiz:{e['id']}", "judgment", "quiz", f"{st.get('title') or plans.get(e['plan_id'], '')} · 测试 {d.get('score', '')} 分",
                            mine=d.get("summary", ""), context="薄弱点：" + "；".join(weak), date=e["created_at"],
                            doc=f"plan:{e['plan_id']}", link=f"#learn/plan/{e['plan_id']}/step/{e['step_id']}"))
            continue
        if not (d.get("answer") or "").strip():
            continue
        rv = d.get("review") or {}
        missing = rv.get("missing") or []
        ctx = f"问：{d.get('q', '')}" + (f"\n要点：{d['points']}" if d.get("points") else "") \
            + (f"\n点评·缺：{'；'.join(missing) if isinstance(missing, list) else missing}" if missing else "")
        if e["kind"].startswith("qa"):
            it = items.get(d.get("item_id")) or {}
            title, doc, link = d.get("title") or it.get("title", ""), _item_doc(it) if it else "", f"#learn/item/{d.get('item_id')}"
        else:
            title, doc, link = st.get("title") or plans.get(e["plan_id"], ""), f"plan:{e['plan_id']}", f"#learn/plan/{e['plan_id']}/step/{e['step_id']}"
        key = (d.get("q", ""), d["answer"].strip())
        s = _sig(f"ans:{e['id']}", "judgment", "answer", title, mine=d["answer"], context=ctx, date=e["created_at"], doc=doc, link=link)
        if key not in best or e["kind"].endswith("review"):
            best[key] = s
    out += best.values()
    for s in steps.values():
        if (s.get("feedback") or "").strip():
            out.append(_sig(f"stepfb:{s['id']}", "judgment", "feedback", s["title"], mine=s["feedback"],
                            context=f"理解度 {s['understanding']}/5" if s.get("understanding") else "", date=s.get("done_at") or "",
                            doc=f"plan:{s['plan_id']}", link=f"#learn/plan/{s['plan_id']}/step/{s['id']}"))
    return out


def _s_items() -> list[dict]:
    """深读条目里我的笔记、对话里的感想 / 追问。追问清单作答已在 learn_events 里，不重复取。"""
    if not _has("learn_items"):
        return []
    from .modules import _reads
    out = []
    for it in db.rows("SELECT * FROM learn_items ORDER BY id"):
        doc, link = _item_doc(it), f"#learn/item/{it['id']}"
        if (it.get("my_notes") or "").strip():
            out.append(_sig(f"mynote:{it['id']}", "judgment", "mynote", it["title"], mine=it["my_notes"],
                            date=it.get("updated_at") or it["created_at"], doc=doc, link=link))
        try:
            lines = _reads.user_lines(it["id"])
        except Exception:  # noqa: BLE001
            lines = []
        for n, x in enumerate(lines):
            out.append(_sig(f"read:{it['id']}:{n}", "judgment", x["kind"], it["title"], mine=x["text"],
                            context=_clip(it.get("summary") or "", 200), date=x["at"], doc=doc, link=link))
    return out


def _s_feed() -> list[dict]:
    """论文一句话判断 = 判断；赞 / 收藏 / 点开过 = 看过的材料。"""
    if not _has("feed_feedback"):
        return []
    cols = {r["name"] for r in db.rows("PRAGMA table_info(feed_feedback)")}
    out = []
    for r in db.rows("SELECT i.*, f.vote, f.saved, f.hidden" + (", f.verdict, f.verdict_at" if "verdict" in cols else "")
                     + (", f.clicks" if "clicks" in cols else "") + " FROM feed_feedback f JOIN feed_items i ON i.id=f.item_id"):
        if r["hidden"] or r["vote"] == -1:
            continue
        if (r.get("verdict") or "").strip():
            out.append(_sig(f"verdict:{r['id']}", "judgment", "verdict", r["title"], mine=r["verdict"], context=_clip(r["summary"], 200),
                            date=r.get("verdict_at") or r["date"], doc=f"papernote:{(r.get('verdict_at') or '')[:10]}", url=r["url"]))
        elif r["vote"] == 1 or r["saved"] or r.get("clicks"):
            oid = r["id"].split(":", 1)[-1]
            hn = r["source"] == "hn" and (r["vote"] == 1 or r["saved"]) and "\"hn\"" in (r.get("extra") or "")
            out.append(_sig(f"feed:{r['id']}", "material", "hn" if hn else "feed", r["title"], context=_clip(r["summary"], 240),
                            date=r["date"], doc=f"feed:hn-{oid}" if hn else ("feed:saved" if r["vote"] == 1 or r["saved"] else ""),
                            url=r["url"]))
    return out


def _s_products() -> list[dict]:
    if not _has("products"):
        return []
    return [_sig(f"product:{p['id']}", "judgment", "product", p["name"],
                 mine="\n".join(x for x in [p.get("experience"), f"优点：{p['pros']}" if p.get("pros") else "",
                                            f"缺点：{p['cons']}" if p.get("cons") else ""] if x),
                 context=f"评分 {p['rating']}/5" if p.get("rating") else "", date=p.get("used_at") or p["created_at"],
                 doc=f"product:{p['id']}", url=p.get("url") or "")
            for p in db.rows("SELECT * FROM products ORDER BY id")]


def _s_materials() -> list[dict]:
    from .kb import _gist
    out = []
    if _has("research_docs"):
        for d in db.rows("SELECT id, research_id, title, content, created_at FROM research_docs ORDER BY id"):
            out.append(_sig(f"research:{d['id']}", "material", "research", d["title"], context=_clip(_gist(d["content"] or "", 3), 300),
                            date=d["created_at"], doc=f"research:{d['id']}",
                            link=f"#research/r/{d['research_id']}" if d.get("research_id") else "#research"))
    if _has("learn_items"):
        for it in db.rows("SELECT * FROM learn_items ORDER BY id"):
            sub = {"github": "repo", "paper": "paper"}.get(it["kind"], "article")
            out.append(_sig(f"item:{it['id']}", "material", sub, it["title"] or it["url"], context=_clip(it.get("summary") or "", 300),
                            date=it["created_at"], doc=_item_doc(it), link=f"#learn/item/{it['id']}", url=it["url"]))
    if _has("learn_plans"):
        for p in db.rows("SELECT id, topic, goal, created_at FROM learn_plans ORDER BY id"):
            steps = [s["title"] for s in db.rows("SELECT title FROM learn_steps WHERE plan_id=? ORDER BY stage, ord, id", [p["id"]])]
            out.append(_sig(f"plan:{p['id']}", "material", "plan", p["topic"], context=_clip(f"{p['goal']}；步骤：{'；'.join(steps)}", 400),
                            date=p["created_at"], doc=f"plan:{p['id']}", link=f"#learn/plan/{p['id']}"))
    if _has("learn_books"):
        for b in db.rows("SELECT id, title, url, overview, created_at FROM learn_books WHERE status='ready'"):
            ov = _j(b["overview"], {}) if (b.get("overview") or "").startswith("{") else {}
            out.append(_sig(f"book:{b['id']}", "material", "book", b["title"] or b["url"], context=ov.get("one_line", ""),
                            date=b["created_at"], doc=f"book:{b['id']}", link=f"#learn/book/{b['id']}", url=b["url"]))
    return out


PROMPT_V = 2   # 改了抽取提示词就 +1，缓存随之失效、重抽


def _sig_hash(s: dict) -> str:
    return _h(PROMPT_V, s["title"], s["mine"], s["context"])


# ---------- LLM ----------

EXTRACT_SYSTEM = """你在帮用户把自己「看过、想过、判断过」的内容整理成个人知识图谱（类似 Obsidian 双链笔记）。
输入是一批记录：kind=judgment 是用户自己的话（mine）以及它针对的上下文（context）；kind=material 是用户读过 / 研究过的材料。
给每条记录抽 1–4 个「概念」作为图谱节点：
- 具体的领域主题、方法、技术、产品、开源项目、论文、数据集 / 评测集、人物、公司；
- 用最常见、最短的规范名：专有名词保留原文（如 SWE-bench、Claude Code、τ-bench、Hamel Husain），通用概念用中文（如 Agent 评测、LLM-as-judge、上下文工程）；
- 优先原样复用 known 里已有的名字，意思相同就不要造新写法；
- 概念要能在别的记录里复用：选「这条记录在讲哪个东西」，而不是把这句话里的说法造成新词
  （如「离开前派活」「评测文档返工」「人工等待时间」都太碎，应归到「Agent 协作流程」「Agent 评测」这类可复用的概念）；
  每条最多 1 个很具体的细节概念；
- 不要过泛（AI、大模型、技术、学习、工具、效率）、不要整句、不要把材料标题原样当概念。
kind=judgment 时另写 claim：用第一人称把「我」在 mine 里的观点 / 结论 / 疑问浓缩成一句（≤40 字）。只能依据 mine，不得加入 mine 没表达的观点；
mine 只是「有道理」「这个挺好」这类附和时，写成「认同：<context 的要点>」；mine 是提问时，写成「疑问：……」。material 的 claim 留空。
输出 JSON：{"items": [{"sid": "原样返回", "concepts": ["..."], "claim": "..."}]}"""

NORMALIZE_SYSTEM = """下面是从用户个人知识库里抽出的概念名及出现次数。请合并同义 / 同指的写法（大小写、中英文、简称全称、单复数），
为每组选一个规范名（选最常用、最短、最通行的写法），并归类到：领域、方法、产品、项目、论文、数据集、人物、公司、其他。
只合并真正同指的，不要把上下位概念（如「Agent 评测」和「SWE-bench」）合并。每个输入名必须出现在且仅出现在一组里。
输出 JSON：{"groups": [{"name": "规范名", "category": "类别", "aliases": ["组内其他写法"]}]}"""

TOPIC_SYSTEM = """下面是用户个人知识图谱里的核心概念（名称、类别、出现次数）。请把它们归入 6–12 个「主题」，主题相当于 Obsidian 里的索引页（MOC）：
- 主题是用户长期关注的领域或问题，如「Agent 评测」「Agent 协作与工作流」「强化学习」「编码 Agent 产品」；名字简短（≤10 字），可以和某个概念同名；
- previous 里有上次的主题时尽量沿用原名，只在确实需要时新增 / 改名；
- 每个概念必须归入且只归入一个主题；desc 用一句话说明这个主题收什么。
输出 JSON：{"topics": [{"name": "主题名", "desc": "一句话", "concepts": ["概念名", "..."]}]}"""

SUMMARY_SYSTEM = """你在为用户的个人知识图谱写某个概念页顶部的「我的理解」。输入是用户关于这个概念的判断（编号、来源、原话）和看过的材料标题。
用第一人称写 2–4 条要点，概括「我」目前对这个概念的看法、结论和还没想清楚的问题；每条末尾用 [编号] 标出依据的判断。
只能依据输入里用户自己的话，不要补充用户没表达过的观点；材料标题只用来理解语境。
输出 JSON：{"points": ["……[1][3]", "……"], "open": ["还没想清楚的问题（可为空数组）"]}"""


def llm_json(system: str, payload: dict, max_tokens: int = 6000) -> dict:
    """统一入口（测试里 monkeypatch）。"""
    from .modules._intel_snap import _deepseek
    for i in range(3):   # 网络抖动 / 偶发截断的 JSON 重试两次
        try:
            return _deepseek(system, payload, max_tokens=max_tokens)
        except Exception:  # noqa: BLE001
            if i == 2:
                raise
            time.sleep(2 * (i + 1))
    return {}


def has_llm() -> bool:
    return bool(os.environ.get("DEEPSEEK_API_KEY", "").strip())


def _cache_get(key: str, h: str):
    r = db.row("SELECT hash, data FROM kb_llm_cache WHERE key=?", [key])
    return _j(r["data"], None) if r and r["hash"] == h else None


def _cache_put(key: str, h: str, data) -> None:
    db.execute("INSERT INTO kb_llm_cache(key, hash, data, at) VALUES (?,?,?,?) ON CONFLICT(key) DO UPDATE SET "
               "hash=excluded.hash, data=excluded.data, at=excluded.at", [key, h, json.dumps(data, ensure_ascii=False), db.now()])


def _extract(sigs: list[dict], known: list[str]) -> int:
    done = 0
    for i in range(0, len(sigs), 20):
        batch = sigs[i:i + 20]
        payload = {"known": known[:300], "items": [
            {"sid": s["sid"], "kind": s["kind"], "type": SUB_NAMES.get(s["sub"], s["sub"]), "title": _clip(s["title"], 120),
             "mine": _clip(s["mine"], 600), "context": _clip(s["context"], 400)} for s in batch]}
        res = llm_json(EXTRACT_SYSTEM, payload)
        got = {str(x.get("sid")): x for x in res.get("items") or [] if isinstance(x, dict)}
        for s in batch:
            x = got.get(s["sid"])
            if not x:
                continue
            cs = [re.sub(r"\s+", " ", str(c)).strip()[:40] for c in x.get("concepts") or [] if str(c).strip()][:4]
            db.execute("INSERT INTO kb_sig_cache(sid, hash, concepts, claim, at) VALUES (?,?,?,?,?) ON CONFLICT(sid) DO UPDATE SET "
                       "hash=excluded.hash, concepts=excluded.concepts, claim=excluded.claim, at=excluded.at",
                       [s["sid"], _sig_hash(s), json.dumps(cs, ensure_ascii=False),
                        _clip(x.get("claim") or "", 80) if s["kind"] == "judgment" else "", db.now()])
            known += [c for c in cs if c not in known]
            done += 1
    return done


def _normalize(counts: dict[str, int]) -> dict:
    """原始概念名 → {name, category}；按名字集合缓存，新增名字时整体重算（几百个名字一次调用）。"""
    names = sorted(counts)
    h = _h(names)
    cached = _cache_get("normalize", h)
    if cached is not None:
        return cached
    groups: dict = {}
    for i in range(0, len(names), 400):
        res = llm_json(NORMALIZE_SYSTEM, {"concepts": [{"name": n, "n": counts[n]} for n in names[i:i + 400]]}, max_tokens=8000)
        for g in res.get("groups") or []:
            if not isinstance(g, dict) or not g.get("name"):
                continue
            cat = g.get("category") if g.get("category") in CATEGORIES else "其他"
            for a in {g["name"], *(g.get("aliases") or [])}:
                if a in counts:
                    groups[a] = {"name": g["name"], "category": cat}
    _cache_put("normalize", h, groups)
    return groups


def _topics(cs: dict[str, dict]) -> dict:
    """概念 → 主题；按概念集合缓存，新增概念时整体重算（沿用上次主题名，保持稳定）。"""
    names = sorted(cs)
    h = _h(names)
    cached = _cache_get("topics", h)
    if cached is not None:
        return cached
    prev = _j((db.row("SELECT data FROM kb_llm_cache WHERE key='topics'") or {}).get("data"), {})
    res = llm_json(TOPIC_SYSTEM, {"previous": [{"name": t, "desc": d} for t, d in (prev.get("desc") or {}).items()],
                                  "concepts": [{"name": n, "category": cs[n]["category"], "n": cs[n]["n"]} for n in names]},
                   max_tokens=12000)
    of, desc = {}, {}
    for t in res.get("topics") or []:
        if not isinstance(t, dict) or not t.get("name"):
            continue
        desc[t["name"]] = t.get("desc", "")
        for n in t.get("concepts") or []:
            if n in cs:
                of.setdefault(n, t["name"])
    out = {"of": of, "desc": desc}
    _cache_put("topics", h, out)
    return out


def topic_map(m: dict | None = None) -> dict:
    """读缓存（不调 LLM）：{of: {概念: 主题}, desc: {主题: 说明}}。改名 / 合并后的概念沿用原名或别名的主题。"""
    t = _j((db.row("SELECT data FROM kb_llm_cache WHERE key='topics'") or {}).get("data"), {}) or {}
    return {"of": t.get("of") or {}, "desc": t.get("desc") or {}}


# ---------- 组装图谱 ----------

def _edits() -> tuple[dict[str, str], set[str]]:
    ren, hidden = {}, set()
    for e in db.rows("SELECT * FROM kb_concept_edit ORDER BY id"):
        if e["op"] == "rename" and e["dst"] and e["dst"] != e["src"]:
            if ren.get(e["dst"]) == e["src"]:  # 改回原名 = 撤销上一次改名
                del ren[e["dst"]]
                continue
            ren[e["src"]] = e["dst"]
            hidden.discard(e["dst"])
        elif e["op"] == "hide":
            hidden.add(e["src"])
        elif e["op"] == "unhide":
            hidden.discard(e["src"])
    return ren, hidden


def _resolve(name: str, ren: dict[str, str]) -> str:
    seen = set()
    while name in ren and name not in seen:
        seen.add(name)
        name = ren[name]
    return name


def model(sigs: list[dict] | None = None) -> dict:
    """{concepts: {name: {...}}, sigs: {sid: sig+claim+concepts}, stale: n}。只读缓存，不调 LLM。"""
    _init()
    sigs = signals() if sigs is None else sigs
    cache = {r["sid"]: r for r in db.rows("SELECT * FROM kb_sig_cache")}
    raw_counts: dict[str, int] = {}
    stale = 0
    for s in sigs:
        c = cache.get(s["sid"])
        s["raw"] = _j(c["concepts"], []) if c else []
        s["claim"] = c["claim"] if c else ""
        if not c or c["hash"] != _sig_hash(s):
            stale += 1
        for n in s["raw"]:
            raw_counts[n] = raw_counts.get(n, 0) + 1
    norm = _cache_get("normalize", _h(sorted(raw_counts))) or {}
    if raw_counts and not norm:
        stale += 1
    ren, hidden = _edits()
    concepts: dict[str, dict] = {}
    for s in sigs:
        names = []
        for n in s["raw"]:
            g = norm.get(n) or {"name": n, "category": "其他"}
            final = _resolve(g["name"], ren)
            if final in hidden or final in names:
                continue
            names.append(final)
            c = concepts.setdefault(final, {"name": final, "category": g["category"], "aliases": set(), "judgments": [], "materials": []})
            if n != final:
                c["aliases"].add(n)
            if g["name"] != final:
                c["aliases"].add(g["name"])
            c["judgments" if s["kind"] == "judgment" else "materials"].append(s["sid"])
        s["concepts"] = names
    # 只有一份材料、没有任何判断的概念不进图谱（多半是材料顺带提到的）
    keep = {k: v for k, v in concepts.items() if v["judgments"] or len(v["materials"]) >= 2}
    for s in sigs:
        s["concepts"] = [n for n in s["concepts"] if n in keep]
    by_sid = {s["sid"]: s for s in sigs}
    for c in keep.values():
        c["aliases"] = sorted(c["aliases"] - {c["name"]})
        dates = [by_sid[x]["date"] for x in c["judgments"] + c["materials"] if by_sid[x]["date"]]
        c["first"], c["last"] = (min(dates), max(dates)) if dates else ("", "")
        c["weight"] = 3 * len(c["judgments"]) + len(c["materials"])
        c["core"] = len(c["judgments"]) + len(c["materials"]) >= 2
    tm = topic_map()
    for c in keep.values():
        c["topic"] = next((tm["of"][n] for n in [c["name"], *c["aliases"]] if n in tm["of"]), "")
    # 只出现一次的概念不单独问 LLM：跟同一条记录里关系最强、已归类的概念走
    nb: dict[str, dict[str, int]] = {}
    for e in edges({"sigs": by_sid}):
        nb.setdefault(e["a"], {})[e["b"]] = e["w"]
        nb.setdefault(e["b"], {})[e["a"]] = e["w"]
    for c in keep.values():
        if not c["topic"]:
            cand = sorted(((w, keep[n]["weight"], n) for n, w in nb.get(c["name"], {}).items() if keep[n]["topic"]), reverse=True)
            c["topic"] = keep[cand[0][2]]["topic"] if cand else "未归类"
    if keep and not any(c["name"] in tm["of"] for c in keep.values()):
        stale += 1
    return {"concepts": keep, "sigs": by_sid, "stale": stale, "topics": tm["desc"]}


def edges(m: dict) -> list[dict]:
    w: dict[tuple, int] = {}
    for s in m["sigs"].values():
        cs = sorted(s["concepts"])
        for i in range(len(cs)):
            for j in range(i + 1, len(cs)):
                w[(cs[i], cs[j])] = w.get((cs[i], cs[j]), 0) + (2 if s["kind"] == "judgment" else 1)
    return [{"a": a, "b": b, "w": v} for (a, b), v in w.items()]


def _summary_payload(c: dict, m: dict) -> dict:
    js = [m["sigs"][x] for x in c["judgments"]]
    js.sort(key=lambda s: s["date"])
    return {"concept": c["name"], "judgments": [
        {"n": i + 1, "type": SUB_NAMES.get(s["sub"], s["sub"]), "date": s["date"], "source": _clip(s["title"], 60),
         "mine": _clip(s["mine"], 400), "context": _clip(s["context"], 160)} for i, s in enumerate(js)],
        "materials": [_clip(m["sigs"][x]["title"], 80) for x in c["materials"][:15]]}


def summary_of(name: str, c: dict, m: dict) -> dict | None:
    p = _summary_payload(c, m)
    return _cache_get(f"summary:{name}", _h(p))


# ---------- 刷新（调 LLM，后台跑） ----------

def refresh(force: bool = False) -> dict:
    """抽取新增 / 改动信号的概念 → 合并同义词 → 重写「我的理解」→ 重新同步 kb 文件。单飞，重复调用直接返回。"""
    global _running
    _init()
    with _lock:
        if _running:
            return {"state": "running"}
        _running = True
    try:
        if not has_llm():
            _status.update(state="error", at=db.now(), msg="未配置 DEEPSEEK_API_KEY，概念抽取跳过")
            return dict(_status)
        _status.update(state="running", at=db.now(), msg="抽取概念…")
        sigs = signals()
        cache = {r["sid"]: r["hash"] for r in db.rows("SELECT sid, hash FROM kb_sig_cache")}
        todo = [s for s in sigs if force or cache.get(s["sid"]) != _sig_hash(s)]
        known = [r["name"] for r in db.rows("SELECT DISTINCT value AS name FROM kb_sig_cache, json_each(kb_sig_cache.concepts)")]
        # 判断先抽，材料后抽：概念名以我自己的话为准
        todo.sort(key=lambda s: s["kind"] != "judgment")
        n = _extract(todo, known) if todo else 0
        live = {s["sid"] for s in sigs}
        for r in db.rows("SELECT sid FROM kb_sig_cache"):
            if r["sid"] not in live:
                db.execute("DELETE FROM kb_sig_cache WHERE sid=?", [r["sid"]])
        _status.update(msg="合并同义概念…")
        counts: dict[str, int] = {}
        for r in db.rows("SELECT value AS name, count(*) AS n FROM kb_sig_cache, json_each(kb_sig_cache.concepts) GROUP BY value"):
            counts[r["name"]] = r["n"]
        if counts:
            _normalize(counts)
        _status.update(msg="归入主题…")
        m = model()
        if m["concepts"]:
            _topics({k: {"category": c["category"], "n": len(c["judgments"]) + len(c["materials"])} for k, c in m["concepts"].items() if c["core"]})
        _status.update(msg="写「我的理解」…")
        m = model()
        cands = sorted((c for c in m["concepts"].values() if len(c["judgments"]) >= 2), key=lambda c: -c["weight"])
        wrote = 0
        for c in cands:
            if wrote >= MAX_SUMMARIES:
                break
            p = _summary_payload(c, m)
            if _cache_get(f"summary:{c['name']}", _h(p)) is not None:
                continue
            try:
                res = llm_json(SUMMARY_SYSTEM, p, max_tokens=1500)
                _cache_put(f"summary:{c['name']}", _h(p), {"points": res.get("points") or [], "open": res.get("open") or []})
                wrote += 1
            except Exception:  # noqa: BLE001
                log.exception("kb_graph summary %s", c["name"])
        from . import kb, kb_judge
        try:
            jmsg = "；" + kb_judge.refresh_llm(model(), _status)
        except Exception:  # noqa: BLE001 —— 判断台账出错不影响概念图谱
            log.exception("kb_judge refresh")
            jmsg = ""
        kb.sync(refresh_graph=False)
        _status.update(state="idle", at=db.now(), msg=f"抽取 {n} 条信号，{len(m['concepts'])} 个概念，更新 {wrote} 段「我的理解」{jmsg}")
        return dict(_status)
    except Exception as e:  # noqa: BLE001
        log.exception("kb_graph refresh")
        _status.update(state="error", at=db.now(), msg=f"刷新失败：{e}")
        return dict(_status)
    finally:
        _running = False


def schedule_refresh() -> None:
    if _running or not has_llm():
        return
    threading.Thread(target=refresh, daemon=True).start()


def status() -> dict:
    return {**_status, "running": _running, "llm": has_llm()}


# ---------- 编辑（只追加） ----------

def edit(op: str, src: str, dst: str = "") -> None:
    _init()
    src, dst = src.strip(), dst.strip()
    if op not in ("rename", "hide", "unhide") or not src or (op == "rename" and not dst):
        raise ValueError("bad edit")
    db.execute("INSERT INTO kb_concept_edit(op, src, dst, at) VALUES (?,?,?,?)", [op, src, dst, db.now()])


# ---------- 输出：markdown（Obsidian）与 JSON ----------

def fname(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|#^\[\]]+', "-", name).strip(" .-") or "untitled"


def wl(name: str, folder: str = "") -> str:
    """Obsidian 双链。主题页和概念可能同名，主题带目录前缀区分。"""
    f = folder + fname(name)
    return f"[[{f}]]" if f == name else f"[[{f}|{name}]]"


def _src_link(s: dict, paths: dict[str, str]) -> str:
    p = paths.get(s["doc"])
    t = _clip(s["title"], 50).replace("|", "-").replace("]", ")").replace("[", "(")
    if p:
        return f"[[{p[:-3]}|{t}]]"
    return f"[{t}]({s['url']})" if s["url"] else t


def files(m: dict, paths: dict[str, str]) -> tuple[dict[str, str], dict[str, list[str]]]:
    """(concepts/*.md + GRAPH.md, {来源文件路径: [概念]}) —— 后者给来源文件追加「关联概念」。"""
    out: dict[str, str] = {}
    by_doc: dict[str, list[str]] = {}
    es = edges(m)
    rel: dict[str, list[tuple[str, int]]] = {}
    for e in es:
        rel.setdefault(e["a"], []).append((e["b"], e["w"]))
        rel.setdefault(e["b"], []).append((e["a"], e["w"]))
    for s in m["sigs"].values():
        p = paths.get(s["doc"])
        if p:
            for c in s["concepts"]:
                if c not in by_doc.setdefault(p, []):
                    by_doc[p].append(c)
    for c in m["concepts"].values():
        js = sorted((m["sigs"][x] for x in c["judgments"]), key=lambda s: s["date"], reverse=True)
        ms = sorted((m["sigs"][x] for x in c["materials"]), key=lambda s: s["date"], reverse=True)
        fm = ["---", "type: concept", f"category: {c['category']}",
              "aliases: [" + ", ".join(json.dumps(a, ensure_ascii=False) for a in c["aliases"]) + "]",
              f"judgments: {len(c['judgments'])}", f"materials: {len(c['materials'])}",
              f"topic: {json.dumps(c['topic'], ensure_ascii=False)}",
              f"first: {c['first']}", f"last: {c['last']}", "tags: [概念, " + json.dumps(c["category"], ensure_ascii=False) + "]", "---", ""]
        body = [f"# {c['name']}", "", f"> 主题 {wl(c['topic'], 'topics/')} · {c['category']} · {len(js)} 条我的判断 · {len(ms)} 份看过的材料"
                f" · {c['first']} → {c['last']}", ""]
        sm = summary_of(c["name"], c, m)
        if sm and sm.get("points"):
            body += ["## 我的理解（AI 据我的判断归纳，编号对应下方判断）", *[f"- {p}" for p in sm["points"]]]
            if sm.get("open"):
                body += ["", "**还没想清楚：**", *[f"- {q}" for q in sm["open"]]]
            body.append("")
        if js:
            body.append("## 我的判断")
            for i, s in enumerate(sorted(js, key=lambda s: s["date"])):
                body += [f"{i + 1}. **{s['claim'] or _clip(s['mine'], 60)}**  ",
                         f"   {SUB_NAMES.get(s['sub'], s['sub'])} · {s['date']} · {_src_link(s, paths)}"]
                body += [f"   > {ln}" for ln in _clip(s["mine"], 400).splitlines()]
                if s["context"]:
                    body.append(f"   > — 针对：{_clip(s['context'], 160)}")
            body.append("")
        if ms:
            body += ["## 看过的材料", *[f"- {SUB_NAMES.get(s['sub'], s['sub'])} · {s['date']} · {_src_link(s, paths)}" for s in ms], ""]
        rs = sorted(rel.get(c["name"], []), key=lambda x: -x[1])[:20]
        if rs:
            body += ["## 相关概念", " · ".join(f"{wl(n)}（{w}）" for n, w in rs), ""]
        out[f"concepts/{fname(c['name'])}.md"] = "\n".join(fm + body) + "\n"
    top = sorted(m["concepts"].values(), key=lambda c: -c["weight"])
    by_topic: dict[str, list[dict]] = {}
    for c in top:
        by_topic.setdefault(c["topic"], []).append(c)
    g = ["# 概念图谱", "", f"共 {len(by_topic)} 个主题、{len(top)} 个概念。括号里是「我的判断数 / 看过的材料数」。"
         "在 Obsidian 里打开 `data/kb` 可看图谱视图。", ""]
    for t, cs in sorted(by_topic.items(), key=lambda x: -sum(c["weight"] for c in x[1])):
        core = [c for c in cs if c["core"]]
        g += [f"## {wl(t, 'topics/')}", m["topics"].get(t, ""), "",
              " · ".join(f"{wl(c['name'])}（{len(c['judgments'])}/{len(c['materials'])}）" for c in core)
              + (f"；另有 {len(cs) - len(core)} 个只出现一次的概念见主题页" if len(cs) > len(core) else ""), ""]
        tb = ["---", "type: topic", "tags: [主题]", "---", "", f"# {t}", "", m["topics"].get(t, ""), "", f"{len(cs)} 个概念：", ""]
        for c in cs:
            js = sorted((m["sigs"][x] for x in c["judgments"]), key=lambda s: s["date"], reverse=True)
            tb.append(f"- {wl(c['name'])} · {c['category']} · {len(c['judgments'])} 条判断 / {len(c['materials'])} 份材料"
                      + (f" — 最近：{_clip(js[0]['claim'] or js[0]['mine'], 50)}" if js else ""))
        out[f"topics/{fname(t)}.md"] = "\n".join(tb) + "\n"
    out["GRAPH.md"] = "\n".join(g) + "\n"
    return out, by_doc


def graph_json() -> dict:
    m = model()
    nodes = [{"id": c["name"], "category": c["category"], "topic": c["topic"], "w": c["weight"], "j": len(c["judgments"]),
              "m": len(c["materials"]), "core": c["core"], "last": c["last"]} for c in m["concepts"].values()]
    tw: dict[str, int] = {}
    for c in m["concepts"].values():
        tw[c["topic"]] = tw.get(c["topic"], 0) + c["weight"]
    topics = [{"name": t, "desc": m["topics"].get(t, ""), "w": w, "n": sum(c["topic"] == t for c in m["concepts"].values())}
              for t, w in sorted(tw.items(), key=lambda x: -x[1])]
    return {"nodes": nodes, "edges": edges(m), "topics": topics, "stale": m["stale"], "status": status(),
            "signals": {"judgment": sum(s["kind"] == "judgment" for s in m["sigs"].values()),
                        "material": sum(s["kind"] == "material" for s in m["sigs"].values())}}


def _sig_out(s: dict, paths: dict[str, str]) -> dict:
    return {"sid": s["sid"], "kind": s["kind"], "sub": s["sub"], "sub_name": SUB_NAMES.get(s["sub"], s["sub"]),
            "title": s["title"], "claim": s.get("claim", ""), "mine": s["mine"], "context": s["context"], "date": s["date"],
            "path": paths.get(s["doc"], ""), "link": s["link"], "url": s["url"], "concepts": s.get("concepts", [])}


def _paths() -> dict[str, str]:
    from . import kb
    return {d["id"]: d["path"] for d in kb.build()}


def concept_json(name: str) -> dict | None:
    m = model()
    ren, _ = _edits()
    name = _resolve(name, ren)
    c = m["concepts"].get(name)
    if not c:
        return None
    paths = _paths()
    rel = sorted(((e["b"] if e["a"] == name else e["a"], e["w"]) for e in edges(m) if name in (e["a"], e["b"])), key=lambda x: -x[1])
    sm = summary_of(name, c, m) or {}
    js = sorted((m["sigs"][x] for x in c["judgments"]), key=lambda s: s["date"])
    from . import kb_judge
    led = {x["sid"]: x for x in kb_judge.ledger(m, paths)["cards"]}
    return {"name": name, "category": c["category"], "topic": c["topic"], "topic_desc": m["topics"].get(c["topic"], ""),
            "aliases": c["aliases"], "first": c["first"], "last": c["last"],
            "summary": sm, "path": f"concepts/{fname(name)}.md",
            "judgments": [{**_sig_out(s, paths), **({k: led[s["sid"]][k] for k in ("type", "status", "due", "thread")} if s["sid"] in led else {})}
                          for s in js],
            "materials": [_sig_out(m["sigs"][x], paths) for x in sorted(c["materials"], key=lambda x: m["sigs"][x]["date"], reverse=True)],
            "related": [{"name": n, "w": w, "category": m["concepts"][n]["category"]} for n, w in rel[:24]]}


def stream_json(limit: int = 60) -> list[dict]:
    """最近的判断（思考流），新的在前。"""
    m = model()
    paths = _paths()
    js = sorted((s for s in m["sigs"].values() if s["kind"] == "judgment"), key=lambda s: s["date"], reverse=True)
    return [_sig_out(s, paths) for s in js[:limit]]
