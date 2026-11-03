"""论文库补充（设计稿 §8）：用户按需补具体论文 / 补一个方向，以及每天把信息推荐里的论文送进库。

- 补具体论文：arXiv 编号 / arXiv·HF·AlphaXiv·S2 链接 / 论文标题（S2 标题匹配）→ 取详情 → 直接入库（tier=manual，不看门槛，
  admit_all 不会再把它判出去）→ 马上标注。它和库内论文的引用关系靠 refs 自动连上。
- 补一个方向：模型把主题改写成英文说法（复用脉络的 rewrite）→ 拼成 S2 检索式按年龄段检索 → 按正常门槛（含工业界对折）预览
  「将新增 N 篇」→ 用户确认后后台入库：补详情 → 重新过门槛 → Jev → 标注 → 重新生成这个主题的脉络。预览不写库。
- 每日热门：信息推荐刷新后，把最近的 HF 每日论文 / AlphaXiv 论文按 arXiv 编号取 S2 详情，记 hot，按近期论文规则过门槛并标注。
  S2 收录新论文有一两天延迟，没查到的下次刷新再试。
新入库论文只标它自己；引用它的库内论文的 builds_on 要等下次全量标注（label_src 变了会自动进队列）。
"""
from __future__ import annotations

import json
import logging
import re
import threading

from .. import db
from . import _paper_collect as col, _paper_label as lab

log = logging.getLogger(__name__)

S2_URL = re.compile(r"semanticscholar\.org/paper/(?:[^/\s]+/)?([0-9a-f]{40})", re.I)
PREVIEW_SHOW = 40          # 预览列出被引最高的这些篇
TOPIC_TERMS = 10           # 检索式最多用几个改写出来的说法
FEED_DAYS = 14             # 每日热门只看最近这么多天进信息推荐的论文（S2 一直查不到的不无限重试）

SCHEMA = """
CREATE TABLE IF NOT EXISTS paper_adds (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    topic    TEXT,
    query    TEXT,                -- 发给 S2 的检索式
    preview  TEXT,                -- {"new": [...], "maybe": [...], "have": n}；new / maybe 里是精简过的 S2 检索结果
    status   TEXT DEFAULT 'preview',   -- preview / running / done / failed
    step     TEXT DEFAULT '',
    result   TEXT DEFAULT '{}',
    created  TEXT, updated TEXT
);
"""
_lock = threading.Lock()


def init() -> None:
    db.init([col.SCHEMA, SCHEMA])
    if _lock.locked():
        return
    # 本进程没在跑却有 running 的：服务重启打断了后台补充。步骤都能重跑，标成失败让用户重试
    db.execute("UPDATE paper_adds SET status='failed', step='服务重启中断，可以重新确认' WHERE status='running'")


def _paper_id(text: str, c) -> str | None:
    t = text.strip()
    if m := S2_URL.search(t):
        return m[1]
    if m := col.ARXIV_ID.search(t):
        return f"ARXIV:{m[1]}"
    try:
        hits = col._req("GET", "/paper/search/match", c, params={"query": t[:300], "fields": "title"}).get("data") or []
    except RuntimeError as e:
        if " 404" in str(e):
            return None
        raise
    return hits[0]["paperId"] if hits else None


def _get(pid: str, c) -> dict | None:
    try:
        return col._req("GET", f"/paper/{pid}", c, params={"fields": col.DETAIL_FIELDS})
    except RuntimeError as e:
        if " 404" in str(e):
            return None
        raise


def label_ids(s2ids: list[str]) -> dict:
    """只标这几篇（入库、有详情、标签过期的）。"""
    if not s2ids:
        return {"labeled": 0, "todo": 0, "cost": 0.0, "errors": []}
    corpus, ver = lab._corpus(), lab.taxonomy()["version"]
    rows = db.rows(f"SELECT * FROM paper_items WHERE status='in' AND detail_at IS NOT NULL AND s2id IN ({','.join('?' * len(s2ids))})", s2ids)
    old = {r["s2id"]: r for r in db.rows(f"SELECT s2id, label_src, tax_ver FROM paper_labels WHERE s2id IN ({','.join('?' * len(s2ids))})", s2ids)}
    items = [(r, lab.refs_of(r, corpus)) for r in rows]
    items = [(r, refs) for r, refs in items
             if not (o := old.get(r["s2id"])) or o["tax_ver"] != ver or o["label_src"] != lab.label_src(r, refs)]
    st = lab.run(items=items)
    st.pop("labels", None)
    return st


def _brief(s2id: str) -> dict:
    r = db.row("SELECT p.s2id, p.arxiv, p.title, p.year, p.cites, p.status, p.tier, p.why, l.d, l.s FROM paper_items p "
               "LEFT JOIN paper_labels l ON l.s2id=p.s2id WHERE p.s2id=?", [s2id]) or {}
    doms = {c["code"]: c["name"] for d in lab.taxonomy()["domains"] for c in d["children"]}
    return r | {"domain": doms.get(r.get("d") or "", ""),
                "url": f"https://arxiv.org/abs/{r['arxiv']}" if r.get("arxiv") else f"https://www.semanticscholar.org/paper/{s2id}"}


# ---------- 补具体论文 ----------

def add_paper(text: str) -> dict:
    """一篇论文直接入库并标注，返回它的信息；找不到抛 LookupError。"""
    init()
    with col.client() as c:
        pid = _paper_id(text, c)
        p = _get(pid, c) if pid else None
    if not p or not p.get("paperId"):
        raise LookupError("Semantic Scholar 里没找到这篇论文，换成 arXiv 编号或链接试试")
    col.upsert(p, "user")
    r = db.row("SELECT id, status FROM paper_items WHERE s2id=?", [p["paperId"]])
    already = r["status"] == "in"
    if not already:
        db.execute("UPDATE paper_items SET status='in', tier='manual', why='用户补充' WHERE id=?", [r["id"]])
    st = label_ids([p["paperId"]])
    return {"already": already, "paper": _brief(p["paperId"]), "label": st}


# ---------- 补一个方向 ----------

ABBR = re.compile(r"[A-Za-z0-9-]{1,6}")


def topic_query(intent: dict) -> str:
    """改写出的说法拼成 S2 检索式。单独的缩写（SNN、RAG、MoE）在全库里撞名太多（SNN 也是 Siamese network），不进检索式。"""
    terms = [t for t in (re.sub(r"[\"()|+]", " ", t).strip() for t in intent["must"]) if len(t) >= 2 and not
             (ABBR.fullmatch(t) and any(ch.isupper() for ch in t[1:]))]
    return " | ".join(f'"{t}"' for t in terms[:TOPIC_TERMS])


def _slim(p: dict) -> dict:
    return {k: p.get(k) for k in ("paperId", "title", "year", "publicationDate", "citationCount", "influentialCitationCount",
                                  "venue", "externalIds")}


def _as_row(p: dict) -> dict:
    return {"arxiv": col._arxiv(p), "title": p.get("title") or "", "pub_date": p.get("publicationDate") or
            (f"{p['year']}-07-01" if p.get("year") else ""), "cites": p.get("citationCount") or 0,
            "infl": p.get("influentialCitationCount") or 0}


def preview_topic(topic: str) -> dict:
    """改写 + 检索 + 按门槛预判，不写 paper_items。返回 {id, topic, query, new, maybe, have, n_new, n_maybe}。"""
    from . import _paper_map as pmap
    init()
    intent, cost = pmap.rewrite(topic)
    q = topic_query(intent)
    if not q:
        raise LookupError("没能把这个主题改写成检索词，换个说法试试")
    have = {r["s2id"]: r for r in db.rows("SELECT s2id, status, hot, junk FROM paper_items")}
    seen, new, maybe, n_have = set(), [], [], 0
    need = {t: n for _, t, n in col.TIERS if n}
    with col.client() as c:
        for _, year, mc, pages in col.slices(pages=1):
            for p in col.search_bulk(q, c, pages=pages, year=year, min_cites=mc):
                if not p.get("paperId") or p["paperId"] in seen:
                    continue
                seen.add(p["paperId"])
                old = have.get(p["paperId"]) or {}
                if old.get("status") == "in":
                    n_have += 1
                    continue
                r = _as_row(p) | {"hot": old.get("hot") or 0, "junk": old.get("junk")}
                st, tier, why = col.decide(r)
                if st == "in":
                    new.append(_slim(p) | {"why": why})
                elif r["arxiv"] and tier in need and r["cites"] >= need[tier] * col.INDUSTRY_FACTOR:
                    maybe.append(_slim(p) | {"why": "被引够工业界门槛，取摘要后判断"})
    key = lambda x: -(x.get("citationCount") or 0)
    new.sort(key=key)
    maybe.sort(key=key)
    prev = {"new": new, "maybe": maybe, "have": n_have, "intent": intent, "cost": cost}
    now = db.now()
    aid = db.insert("paper_adds", {"topic": topic.strip(), "query": q, "preview": json.dumps(prev, ensure_ascii=False),
                                   "status": "preview", "created": now, "updated": now})
    return adds_view(db.row("SELECT * FROM paper_adds WHERE id=?", [aid]))


def adds_view(a: dict, full: bool = False) -> dict:
    prev = json.loads(a.get("preview") or "{}")
    show = lambda xs: [{"s2id": x["paperId"], "title": x["title"], "year": x.get("year"), "cites": x.get("citationCount") or 0,
                        "arxiv": (x.get("externalIds") or {}).get("ArXiv") or "", "why": x.get("why", "")}
                       for x in (xs if full else xs[:PREVIEW_SHOW])]
    return {"id": a["id"], "topic": a["topic"], "query": a["query"], "status": a["status"], "step": a["step"],
            "result": json.loads(a.get("result") or "{}"), "created": a["created"], "updated": a["updated"],
            "n_new": len(prev.get("new") or []), "n_maybe": len(prev.get("maybe") or []), "have": prev.get("have", 0),
            "new": show(prev.get("new") or []), "maybe": show(prev.get("maybe") or [])}


def _step(aid: int, step: str, **kw) -> None:
    f = {"step": step, "updated": db.now(), **{k: json.dumps(v, ensure_ascii=False) if k == "result" else v for k, v in kw.items()}}
    db.execute(f"UPDATE paper_adds SET {','.join(k + '=?' for k in f)} WHERE id=?", [*f.values(), aid])
    log.info("论文补充 #%s：%s", aid, step)


def start_topic(aid: int) -> bool:
    """确认预览，后台入库；已有补充在跑返回 False。"""
    init()
    a = db.row("SELECT * FROM paper_adds WHERE id=?", [aid])
    if not a:
        raise LookupError("没有这个预览")
    if not _lock.acquire(blocking=False):
        return False
    db.execute("UPDATE paper_adds SET status='running', step='排队', updated=? WHERE id=?", [db.now(), aid])
    threading.Thread(target=_run_topic, args=(aid,), daemon=True, name=f"paper-add-{aid}").start()
    return True


def _run_topic(aid: int) -> None:
    from . import _paper_map as pmap
    try:
        a = db.row("SELECT * FROM paper_adds WHERE id=?", [aid])
        prev = json.loads(a["preview"])
        cands = prev["new"] + prev["maybe"]
        ids = [p["paperId"] for p in cands]
        src = "add:" + pmap.norm(a["topic"])[:40]
        for p in cands:
            col.upsert(p, src)
        with col.client() as c:
            col.fetch_details(c, ids=ids, on_page=lambda i, n: _step(aid, f"补摘要和参考文献 {i}/{n}"))
        _step(aid, "过门槛")
        admitted = []
        for r in db.rows(f"SELECT * FROM paper_items WHERE s2id IN ({','.join('?' * len(ids))})", ids) if ids else []:
            if r["status"] == "in":                       # 预览之后别处已经收进来了（或经典 / 用户补充）
                admitted.append(r["s2id"])
                continue
            st, tier, why = col.decide(r)
            db.execute("UPDATE paper_items SET status=?, tier=?, why=? WHERE id=?", [st, tier, why, r["id"]])
            if st == "in":
                admitted.append(r["s2id"])
        if any((db.row("SELECT tier FROM paper_items WHERE s2id=?", [s]) or {}).get("tier") == "recent" for s in admitted):
            _step(aid, "Jev 判近期论文是不是水文")
            lab.judge_recent()
            admitted = [s for s in admitted if (db.row("SELECT status FROM paper_items WHERE s2id=?", [s]) or {}).get("status") == "in"]
        _step(aid, f"标注 {len(admitted)} 篇")
        st = label_ids(admitted)
        res = {"admitted": len(admitted), "labeled": st["labeled"], "cost": st["cost"], "errors": st["errors"][-5:]}
        _step(aid, "重新生成脉络", result=res)
        try:
            m = pmap.build(a["topic"], use_cache=False)
            res |= {"map": True, "recalled": m["recalled"], "cost": round(res["cost"] + m["cost"], 4)}
        except Exception as e:  # noqa: BLE001  入库已完成，脉络失败不算整体失败
            res |= {"map": False, "map_error": f"{type(e).__name__}: {str(e)[:160]}"}
        db.execute("UPDATE paper_adds SET status='done' WHERE id=?", [aid])
        _step(aid, "完成", result=res)
    except Exception as e:  # noqa: BLE001
        log.exception("论文补充 #%s 失败", aid)
        db.execute("UPDATE paper_adds SET status='failed' WHERE id=?", [aid])
        _step(aid, f"失败：{type(e).__name__}: {str(e)[:200]}")
    finally:
        _lock.release()


def adds(limit: int = 10) -> list[dict]:
    init()
    return [adds_view(a) | {"new": [], "maybe": []} for a in db.rows(
        "SELECT * FROM paper_adds WHERE status!='preview' ORDER BY id DESC LIMIT ?", [limit])]


# ---------- 每日热门（信息推荐刷新后） ----------

def ingest_feed(days: float = FEED_DAYS) -> dict:
    """信息推荐里最近的论文 → S2 详情 → 记 hot → 按近期规则过门槛 → Jev → 标注。库是空的（没跑过采集）就跳过。"""
    init()
    stat = {"feed": 0, "new": 0, "admitted": 0, "labeled": 0, "cost": 0.0, "errors": []}
    if not db.row("SELECT 1 FROM paper_items WHERE status='in' LIMIT 1"):
        return stat | {"skipped": "论文库还是空的"}
    ids = col.feed_arxiv_ids(days)
    stat["feed"] = len(ids)
    known = {r["arxiv"]: r for r in db.rows("SELECT s2id, arxiv, detail_at FROM paper_items WHERE arxiv!=''")}
    have = {r["s2id"] for r in known.values()}
    fetch = [a for a in ids if a not in known or known[a]["detail_at"] is None]
    with col.client() as c:
        for i in range(0, len(fetch), col.DETAIL_BATCH):
            for p in col.batch([f"ARXIV:{a}" for a in fetch[i:i + col.DETAIL_BATCH]], c):
                if p and p.get("paperId"):
                    stat["new"] += p["paperId"] not in have
                    col.upsert(p, "feed")
    rows = db.rows(f"SELECT * FROM paper_items WHERE arxiv IN ({','.join('?' * len(ids))})", list(ids)) if ids else []
    for r in rows:
        if not r["hot"]:
            db.execute("UPDATE paper_items SET hot=1 WHERE id=?", [r["id"]])
        if r["status"] != "in" and (r["tier"] or "") not in ("classic", "manual"):
            st, tier, why = col.decide(r | {"hot": 1})
            db.execute("UPDATE paper_items SET status=?, tier=?, why=? WHERE id=?", [st, tier, why, r["id"]])
    try:
        stat["jev"] = {k: v for k, v in lab.judge_recent().items() if k != "admit"}
    except Exception as e:  # noqa: BLE001
        stat["errors"].append(f"Jev：{type(e).__name__}: {str(e)[:120]}")
    s2ids = [r["s2id"] for r in db.rows(f"SELECT s2id FROM paper_items WHERE status='in' AND arxiv IN ({','.join('?' * len(ids))})",
                                        list(ids))] if ids else []
    stat["admitted"] = len(s2ids)
    st = label_ids(s2ids)
    stat |= {"labeled": st["labeled"], "cost": st["cost"], "errors": stat["errors"] + st["errors"][-5:]}
    return stat
