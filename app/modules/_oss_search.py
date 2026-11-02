"""开源雷达的按功能检索（设计稿 §5）：改写 → 多路召回 → 特征打分 → LLM 精排 → 缓存。

- 改写：DeepSeek 把「我想做 PDF 解析」改成 {must, should, not, domains, kinds}（中英文多种说法）。
- 召回：FTS5 trigram 短语命中、原子词命中（≥2 个不同原子词）、领域命中三路合并；2 字中文词 trigram 查不了，退回 LIKE。
- 打分：短语 / 原子词 / 领域 / 形态 / 排除词加权；相关性模式再加一点 log(star)。
- 精排：前 40 交给 DeepSeek 打 0-3 分并给一句理由；按 star 排时只留 ≥2 分的。
- 缓存：同一个查询 7 天内直接用改写和精排结果（排序方式、筛选不影响缓存）。
没配 DEEPSEEK_API_KEY 时退化成原文切词 + 打分，不精排。DeepSeek 的调用方式同 _feed_product / _feed_gist。
"""
from __future__ import annotations

import json
import math
import os
import re
import sqlite3
from datetime import datetime, timedelta

import httpx

from .. import db
from . import _oss_label as lab

TIMEOUT = httpx.Timeout(60.0, connect=10.0)
MODEL = "deepseek-v4-flash"
CACHE_DAYS = 7
RERANK_TOP = 40
ATOM_MAX_HITS = 400   # 拆出的单词命中超过这么多仓库就当泛词，不参与「命中 2 个词以上」的召回和加分
W = (0.5, 1.0, 1.2, 0.8, 0.8)   # bm25 列权重：name s t descr topics

REWRITE = """你把开发者的「找开源项目」需求改写成检索意图。领域 code（二级）：{doms}
形态 kind：{kinds}
只输出 JSON：{{"must":[核心功能的说法，中英文各写几种，2-6 个],"should":[相关的技术词 / 常见库名 / 子功能，0-8 个],
"not":[容易混淆但不是用户要的功能，0-4 个],"domains":[最相关的领域 code，1-3 个，最主要的放第一个],"kinds":[用户明确要的形态，没说就空]}}"""

RERANK = ("你是开源项目检索的重排器。给定用户需求和候选仓库（summary/tags），判断每个仓库能否直接满足需求："
          "3=正是要找的，2=能用来做（主要功能之一），1=沾边但不是主要用途，0=无关或是要排除的相反功能。"
          '只输出 JSON：{"<序号>":[分数,"≤20字中文理由，说它能怎么满足需求；0-1 分写空串"],...}，覆盖全部候选。')


def norm(q: str) -> str:
    return re.sub(r"\s+", " ", (q or "").strip().lower())


# ---------- DeepSeek ----------

def _chat(system: str, user: str, max_tokens: int = 2000, client: httpx.Client | None = None) -> dict:
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not key:
        raise RuntimeError("未配置 DEEPSEEK_API_KEY")
    base = os.environ.get("DEEPSEEK_API_BASE", "https://api.deepseek.com").rstrip("/")
    c = client or httpx.Client(timeout=TIMEOUT)
    try:
        r = c.post(f"{base}/chat/completions", headers={"Authorization": f"Bearer {key}"}, json={
            "model": MODEL, "temperature": 0.1, "max_tokens": max_tokens,
            "thinking": {"type": "disabled"}, "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]})
        r.raise_for_status()
        return json.loads(r.json()["choices"][0]["message"]["content"])
    finally:
        if client is None:
            c.close()


def fallback_intent(q: str) -> dict:
    words = [w for w in re.split(r"[\s,，、/]+", re.sub(r"^(我想|我要|想要|帮我|找一?个?)(做|找|用)?", "", q.strip())) if w]
    return {"must": words or [q], "should": [], "not": [], "domains": [], "kinds": []}


def rewrite(q: str, chat=None) -> dict:
    tax = lab.taxonomy()
    doms = "；".join(f"{c['code']}={c['name']}" for d in tax["domains"] for c in d["children"])
    kinds = "；".join(f"{k['code']}={k['name']}" for k in tax["kinds"])
    x = (chat or _chat)(REWRITE.format(doms=doms, kinds=kinds), q)
    cs = lab.codes()
    it = {k: [str(v).strip() for v in (x.get(k) or []) if str(v).strip()] for k in ("must", "should", "not", "domains", "kinds")}
    it["domains"] = [d for d in it["domains"] if d in cs["d"]][:3]
    it["kinds"] = [k for k in it["kinds"] if k in cs["k"]]
    if not it["must"]:
        it["must"] = fallback_intent(q)["must"]
    return it


def rerank(q: str, cands: list[dict], chat=None) -> dict[str, list]:
    """候选 → {name: [分数, 理由]}。"""
    rows = "\n".join(json.dumps({"i": n, "name": c["name"], "summary": c["s"], "tags": c["t"]}, ensure_ascii=False)
                     for n, c in enumerate(cands))
    x = (chat or _chat)(RERANK, f"需求：{q}\n候选：\n{rows}", 4000)
    out = {}
    for k, v in x.items():
        try:
            c = cands[int(k)]
        except (ValueError, IndexError):
            continue
        sc, why = (v[0], v[1] if len(v) > 1 else "") if isinstance(v, list) else (v, "")
        try:
            out[c["name"]] = [max(0, min(3, int(sc))), str(why or "")[:40]]
        except (TypeError, ValueError):
            continue
    return out


# ---------- 召回与打分 ----------

def hits(term: str, cols: list[str] | None = None) -> dict[int, float]:
    """一个词命中的 rowid → bm25 分（越大越相关）；2 字词退回 LIKE（命中记 1 分）。
    中英文交界没空格的（「DNA语言模型」）同时查加空格的写法（标签里多写成「DNA 语言模型」）。"""
    t = term.lower().strip()
    spaced = re.sub(r"(?<=[a-z0-9])(?=[\u4e00-\u9fff])|(?<=[\u4e00-\u9fff])(?=[a-z0-9])", " ", t)
    if spaced != t:
        return {**_hits(spaced, cols), **_hits(t, cols)}
    return _hits(t, cols)


def _hits(t: str, cols: list[str] | None) -> dict[int, float]:
    if len(t) < 2:
        return {}
    if len(t) >= 3:
        q = '"' + t.replace('"', "") + '"'
        if cols:
            q = "{" + " ".join(cols) + "}: " + q
        try:
            return {r["rowid"]: -r["b"] for r in db.rows(
                f"SELECT rowid, bm25(oss_fts,{','.join(map(str, W))}) AS b FROM oss_fts WHERE oss_fts MATCH ? LIMIT 3000", [q])}
        except sqlite3.OperationalError:
            return {}
    cs = cols or ["name", "s", "t", "descr", "topics"]
    like = f"%{t}%"
    return {r["rowid"]: 1.0 for r in db.rows(
        "SELECT rowid FROM oss_fts WHERE " + " OR ".join(f"lower({c}) LIKE ?" for c in cs) + " LIMIT 3000", [like] * len(cs))}


def atoms_of(it: dict) -> list[str]:
    return sorted({a for t in it["must"] + it["should"] for a in re.split(r"[\s/，,]+", t.lower()) if len(a) >= 2})


def _docs(ids: set[int]) -> dict[int, dict]:
    out = {}
    ids_l = list(ids)
    for i in range(0, len(ids_l), 900):
        part = ids_l[i:i + 900]
        for r in db.rows("SELECT r.id, r.name, r.stars, r.lang, r.pushed, r.archived, r.descr, r.topics, "
                         "l.k, l.d, l.d2, l.ai, l.t, l.s FROM oss_repos r JOIN oss_labels l ON l.name=r.name "
                         f"WHERE r.id IN ({','.join('?' * len(part))}) AND r.status='ok' AND r.stars>=900", part):
            r["t"], r["d2"], r["topics"] = json.loads(r["t"] or "[]"), json.loads(r["d2"] or "[]"), json.loads(r["topics"] or "[]")
            out[r["id"]] = r
    return out


def recall(it: dict) -> list[dict]:
    """三路召回 + 特征打分；返回带 rel 的候选（未排序）。"""
    must = [hits(t) for t in it["must"]]
    should = [hits(t) for t in it["should"]]
    neg = [hits(t, ["s", "t"]) for t in it.get("not") or []]
    acnt: dict[int, int] = {}
    for h in (hits(a, ["name", "s", "t", "topics"]) for a in atoms_of(it)):
        if len(h) > ATOM_MAX_HITS:   # language / model / 预训练 这种泛词命中上千个，计数只会把通用项目顶上来
            continue
        for i in h:
            acnt[i] = acnt.get(i, 0) + 1
    cand = set().union(*must, *should) | {i for i, c in acnt.items() if c >= 2}
    if it["domains"]:
        cand |= {r["id"] for r in db.rows(
            f"SELECT r.id FROM oss_labels l JOIN oss_repos r ON r.name=l.name WHERE l.d IN ({','.join('?' * len(it['domains']))}) "
            "ORDER BY r.stars DESC LIMIT 500", it["domains"])}
    docs = _docs(cand)
    out = []
    for i, d in docs.items():
        m = max((h.get(i, 0) for h in must), default=0)
        s = sum(1 for h in should if i in h)
        rel = (1.0 if m else 0) + 0.15 * min(m, 3) + 0.3 * min(s, 3) / 3 + 0.15 * min(acnt.get(i, 0), 5)
        # 主领域（改写给的第一个）加满分，其余相关领域减半：「基因组大模型」不该让 llm 领域的通用教程和 ai4science 同分
        doms = it["domains"]
        rel += 0.5 if doms and d["d"] == doms[0] else (0.25 if d["d"] in doms or set(d["d2"]) & set(doms) else 0)
        if it["kinds"]:
            rel += 0.4 if d["k"] in it["kinds"] else -0.3
        if any(i in h for h in neg) and not m:
            rel -= 0.8
        d["rel"] = round(rel, 3)
        out.append(d)
    return out


def _lstar(d: dict) -> float:
    return math.log10(max(d["stars"], 1))


# ---------- 对外 ----------

def _cached(key: str) -> dict | None:
    r = db.row("SELECT * FROM oss_query_cache WHERE key=?", [key])
    if not r:
        return None
    if r["created"] < (datetime.now() - timedelta(days=CACHE_DAYS)).isoformat(timespec="seconds"):
        return None
    return {"intent": json.loads(r["intent"]), "scores": json.loads(r["scores"])}


def search(q: str, by: str = "rel", kind: str = "", domain: str = "", lang: str = "", active_days: int = 0,
           k: int = 30, chat=None, use_cache: bool = True) -> dict:
    """返回 {intent, results:[...], reranked, errors}。results 每项带 name/stars/s/t/d/k/ai/score/why。"""
    key = norm(q)
    errors: list[str] = []
    c = _cached(key) if use_cache else None
    if c:
        it, scores = c["intent"], c["scores"]
    else:
        try:
            it = rewrite(q, chat)
        except Exception as e:  # noqa: BLE001
            it = fallback_intent(q)
            errors.append(f"改写失败，按原文检索：{type(e).__name__}: {str(e)[:80]}")
        scores = None
    cands = recall(it)
    cands.sort(key=lambda d: -(d["rel"] + 0.12 * _lstar(d)))
    if scores is None:
        scores = {}
        top = cands[:RERANK_TOP]
        if top and not errors:
            try:
                scores = rerank(q, top, chat)
            except Exception as e:  # noqa: BLE001
                errors.append(f"精排失败，只按召回打分：{type(e).__name__}: {str(e)[:80]}")
        if not errors:
            db.execute("INSERT OR REPLACE INTO oss_query_cache (key,intent,scores,created) VALUES (?,?,?,?)",
                       [key, json.dumps(it, ensure_ascii=False), json.dumps(scores, ensure_ascii=False), db.now()])
    reranked = bool(scores)
    for d in cands:
        sc, why = scores.get(d["name"], [None, ""])
        d["rr"], d["why"] = sc, why
        d["score"] = round((sc if sc is not None else 0) + 0.3 * d["rel"] + 0.12 * _lstar(d), 3) if reranked \
            else round(d["rel"] + 0.12 * _lstar(d), 3)
    if reranked:   # 精排过的只留前 40 里的（后面的没被模型看过，混进来会冲淡结果）
        cands = [d for d in cands if d["rr"] is not None]
    cands = filt(cands, kind, domain, lang, active_days)
    if by == "stars":
        cands = [d for d in cands if (d["rr"] or 0) >= 2] if reranked else [d for d in cands if d["rel"] >= 1.0]
        cands.sort(key=lambda d: -d["stars"])
    else:
        cands.sort(key=lambda d: -d["score"])
    return {"intent": it, "results": [public(d) for d in cands[:k]], "reranked": reranked, "errors": errors}


def filt(cands: list[dict], kind: str = "", domain: str = "", lang: str = "", active_days: int = 0) -> list[dict]:
    if kind:
        cands = [d for d in cands if d["k"] == kind]
    if domain:
        cands = [d for d in cands if d["d"] == domain or domain in d["d2"]]
    if lang:
        cands = [d for d in cands if (d["lang"] or "").lower() == lang.lower()]
    if active_days:
        cut = (datetime.now() - timedelta(days=active_days)).strftime("%Y-%m-%d")
        cands = [d for d in cands if (d["pushed"] or "")[:10] >= cut and not d["archived"]]
    return cands


def public(d: dict) -> dict:
    return {key: d.get(key) for key in ("name", "stars", "lang", "pushed", "archived", "descr", "k", "d", "d2", "ai", "t", "s",
                                        "rel", "rr", "why", "score")}


def browse(domain: str = "", kind: str = "", lang: str = "", active_days: int = 0, offset: int = 0, k: int = 30) -> dict:
    """没输入时按领域浏览：按 star 倒序。"""
    where, args = ["r.status='ok'", "r.stars>=900"], []
    if domain:
        where.append("(l.d=? OR l.d2 LIKE ?)")
        args += [domain, f'%"{domain}"%']
    if kind:
        where.append("l.k=?")
        args.append(kind)
    if lang:
        where.append("lower(r.lang)=lower(?)")
        args.append(lang)
    if active_days:
        where.append("substr(r.pushed,1,10)>=? AND r.archived=0")
        args.append((datetime.now() - timedelta(days=active_days)).strftime("%Y-%m-%d"))
    sql = (" FROM oss_repos r JOIN oss_labels l ON l.name=r.name WHERE " + " AND ".join(where))
    total = db.row("SELECT count(*) AS n" + sql, args)["n"]
    rows = db.rows("SELECT r.name, r.stars, r.lang, r.pushed, r.archived, r.descr, l.k, l.d, l.d2, l.ai, l.t, l.s" + sql +
                   " ORDER BY r.stars DESC LIMIT ? OFFSET ?", args + [k, offset])
    for r in rows:
        r["t"], r["d2"] = json.loads(r["t"] or "[]"), json.loads(r["d2"] or "[]")
    return {"total": total, "results": rows}
