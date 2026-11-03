"""论文脉络：一句话主题 → 几条按时间演进的研究线（设计稿 §5）。

① 改写：DeepSeek 把「后训练」改成 {must, should, domains}（中英文多种说法 + 分类体系的二级方向），改写两次取并集。
② 召回：FTS5 trigram 短语命中（标题 / 一句话 / 标签 / 摘要）+ 方向命中（主方向命中主题首要方向 1.2、其它方向 1.0，副方向 0.5）。
③ 子图：召回集合内的库内引用边；被 ≥ ANCESTOR_SHARE 的召回论文引用的库内论文作为「前置基础」拉进来（如 PPO 之于 RLHF）。
④ 选点：PageRank（引用方 → 被引方）+ 主题内被引次数 + 年均被引 + 相关度的分位加权（0.3 / 0.3 / 0.3 / 0.1），按子方向分名额（∝ √该方向里关键词命中的篇数）取 NODES 篇，再给近 2 年的论文留 FRONTIER 个位置；
   分数最高的 KEY 篇 + 每个子方向的前 LEAD 名必须出现在结果里，漏了补问一次；还漏就按引用边挂到最相关的线上。
⑤ 成线：把选出的论文（含 builds_on 和子图里的引用关系）交给模型分成 3–7 条线，每个节点写「相比前一步解决了什么」；
   只能用给定的论文编号，校验后落库缓存。
"""
from __future__ import annotations

import json
import re
from datetime import datetime

import httpx

from .. import db
from . import _paper_collect as col, _paper_label as lab

NODES, FRONTIER, ANCESTOR_SHARE, ANCESTOR_MAX = 80, 12, 0.08, 8
OTHER = "_other"
REWRITE_N = 2
KEY, LEAD = 50, 3          # 分数最高的这些标 key，成线时必须出现，漏了补问一次
RECALL_CAP = 2000

REWRITE = """你把用户想了解的 AI 研究主题改写成论文检索意图。方向 code（二级）：{doms}
只输出 JSON：{{"must":[这个主题的核心说法，英文为主（论文是英文），含常见缩写和同义说法，4-10 个],
"should":[主题下的代表性方法 / 子方向名，0-12 个],"domains":[属于这个主题的二级方向 code，1-6 个，最主要的放第一个；主题是一级大类时把它下面相关的二级都列上]}}"""

LINES = """你是 AI 研究脉络的梳理者。给定一个主题和一批已选好的论文（编号 p0..，含年份、类型、方向、一句话、要解决的问题、方法、
on=它引用或直接改进的库内论文编号），把它们整理成研究脉络。只输出 JSON：
{"overview":"80-150 字，这个主题要解决什么、经历了哪几个阶段",
 "foundations":[前置基础论文编号，不属于本主题但被大量引用，0-6 个],
 "lines":[{"name":"研究线名（≤12 字）","summary":"60-120 字：这条线在解决什么问题、怎么一步步演进",
           "nodes":[{"id":"p3","role":"起点|里程碑|改进|变体|最新","note":"≤40 字：相比前一步解决了什么 / 带来了什么"}]}],
 "surveys":[综述论文编号],
 "open":["2-4 条仍未解决的问题（≤30 字）"]}
规则：
- lines 3-7 条，按这个主题里真实存在的技术路线分（不要按年份或论文类型分）；每条 3-14 个节点，按年份排。
- 只能用给出的编号；同一篇最多出现在 2 条线里；「必须出现」列出的每个编号都要出现（放进某条线，或 foundations / surveys），输出前逐个核对。
- note 要说清「解决了前者的什么问题」，依据给出的 problem / method / on 关系，不要编造论文里没有的内容。"""


def norm(q: str) -> str:
    return re.sub(r"\s+", " ", (q or "").strip().lower())


def rewrite(topic: str) -> tuple[dict, float]:
    """改写 REWRITE_N 次取并集：单次改写列哪些方向有随机性（「后训练」时有时没有 peft / alignment），并集更稳。"""
    doms = "；".join(f"{c}={n}" for c, n in lab.domain_names().items())
    ok = lab.codes()["d"]
    out: dict[str, list[str]] = {"must": [], "should": [], "domains": []}
    cost = 0.0
    for i in range(REWRITE_N):
        try:
            text, c = lab.chat(REWRITE.format(doms=doms), topic, max_tokens=1200, json_mode=True)
        except httpx.HTTPError:
            if i == REWRITE_N - 1 and not out["must"]:       # 一次都没成才报错；成了一次就用已有的并集
                raise
            continue
        cost += c
        x = json.loads(text)
        out["must"] += [str(t) for t in x.get("must") or [] if str(t).strip()][:10]
        out["should"] += [str(t) for t in x.get("should") or [] if str(t).strip()][:12]
        out["domains"] += [d for d in x.get("domains") or [] if d in ok][:6]
    return {k: list(dict.fromkeys(v))[:8] if k == "domains" else list(dict.fromkeys(v)) for k, v in out.items()}, cost


def _fts(term: str) -> set[int]:
    t = term.replace('"', " ").strip()
    if len(t) < 3:
        return set()
    try:
        return {r["rowid"] for r in db.rows("SELECT rowid FROM paper_fts WHERE paper_fts MATCH ?", [f'"{t}"'])}
    except Exception:  # noqa: BLE001
        return set()


def _kw(intent: dict) -> dict[int, float]:
    """只算关键词：must 每个 1 分、should 每个 0.4 分。"""
    score: dict[int, float] = {}
    for t, w in [(t, 1.0) for t in intent["must"]] + [(t, 0.4) for t in intent["should"]]:
        for i in _fts(t):
            score[i] = score.get(i, 0) + w
    return score


def recall(intent: dict) -> dict[int, float]:
    """paper_items.id → 相关度（关键词 + 方向）。"""
    score = _kw(intent)
    doms = intent["domains"]
    for r in db.rows("SELECT p.id, l.d, l.d2 FROM paper_labels l JOIN paper_items p ON p.s2id=l.s2id WHERE p.status='in'"):
        if r["d"] in doms:
            score[r["id"]] = score.get(r["id"], 0) + (1.2 if r["d"] == doms[0] else 1.0)
        elif set(json.loads(r["d2"] or "[]")) & set(doms):
            score[r["id"]] = score.get(r["id"], 0) + 0.5
    return {i: s for i, s in score.items() if s >= 1.0}


def _pagerank(nodes: list[str], edges: list[tuple[str, str]], it: int = 40, d: float = 0.85) -> dict[str, float]:
    n = len(nodes)
    out: dict[str, list[str]] = {v: [] for v in nodes}
    for a, b in edges:
        out[a].append(b)
    pr = {v: 1 / n for v in nodes}
    for _ in range(it):
        nxt = {v: (1 - d) / n for v in nodes}
        dangling = sum(pr[v] for v in nodes if not out[v])
        for v in nodes:
            for w in out[v]:
                nxt[w] += d * pr[v] / len(out[v])
        pr = {v: nxt[v] + d * dangling / n for v in nodes}
    return pr


def _pct(vals: dict[str, float]) -> dict[str, float]:
    order = sorted(vals, key=lambda k: vals[k])
    return {k: i / max(1, len(order) - 1) for i, k in enumerate(order)}


def _pick(score: dict[str, float], group: dict[str, str], n: int, on_topic: set[str] = frozenset()) -> list[str]:
    """按子方向分名额再按分数取，避免一个大子方向挤掉其它子方向的里程碑；没用完的名额按全局分数补。
    名额 ∝ √(该方向里关键词命中主题的篇数)：MoE 主题下「架构」方向只有讲 MoE 的那部分算数，不会把整个架构方向的名额摊进来；
    改写没列出的方向合成一组（OTHER），权重取 √篇数 和最大主题方向权重的较小者再减半：召回放宽后 OTHER 动辄上千篇，不封顶会挤掉主题方向的名额。"""
    by: dict[str, list[str]] = {}
    for s in sorted(score, key=lambda s: -score[s]):
        by.setdefault(group[s], []).append(s)
    w = {g: (sum(s in on_topic for s in v) if on_topic else len(v)) ** 0.5 for g, v in by.items()}
    if OTHER in w:
        w[OTHER] = 0.5 * min(w[OTHER], max((x for g, x in w.items() if g != OTHER), default=w[OTHER]))
    tot = sum(w.values()) or 1
    pick = [s for g, v in by.items() for s in v[:max(1, round(n * w[g] / tot))]]
    pick = sorted(pick, key=lambda s: -score[s])[:n]
    rest = [s for s in sorted(score, key=lambda s: -score[s]) if s not in set(pick)]
    return pick + rest[:n - len(pick)]


def _rate(r: dict) -> float:
    """年均被引（对数）：新论文不因为发表时间短吃亏。"""
    return col.log10p((r["cites"] or 0) / max(1, datetime.now().year - (r["year"] or 2000) + 1))


def subgraph(rel: dict[int, float], intent: dict | None = None) -> dict:
    """召回结果 → 选好的节点、边、前置基础。"""
    items = {r["id"]: r for r in db.rows("SELECT p.*, l.k, l.d, l.d2, l.problem, l.method, l.builds_on, l.s "
                                          "FROM paper_items p LEFT JOIN paper_labels l ON l.s2id=p.s2id WHERE p.status='in'")}
    by_s2 = {r["s2id"]: r for r in items.values()}
    top = sorted(rel, key=lambda i: -(rel[i] + 0.25 * _rate(items[i])) if i in items else 0)[:RECALL_CAP]
    core = {items[i]["s2id"] for i in top if i in items}
    cnt: dict[str, int] = {}
    for s in core:
        for t in set(json.loads(by_s2[s]["refs"] or "[]")):
            if t in by_s2 and t not in core:
                cnt[t] = cnt.get(t, 0) + 1
    need = max(3, ANCESTOR_SHARE * len(core))
    ancestors = sorted([t for t, k in cnt.items() if k >= need], key=lambda t: -cnt[t])[:ANCESTOR_MAX]
    nodes = list(core) + ancestors
    ns = set(nodes)
    edges = [(s, t) for s in nodes for t in set(json.loads(by_s2[s]["refs"] or "[]")) if t in ns and t != s]
    pr = _pagerank(nodes, edges)
    relv = {s: rel.get(by_s2[s]["id"], 0.5) for s in nodes}
    p_pr, p_c, p_r = _pct(pr), _pct({s: _rate(by_s2[s]) for s in nodes}), _pct(relv)
    indeg = {s: 0 for s in nodes}
    for _, t in edges:
        indeg[t] += 1
    p_in = _pct({s: indeg[s] + 1e-6 * (by_s2[s]["cites"] or 0) for s in nodes})
    score = {s: 0.3 * p_pr[s] + 0.3 * p_c[s] + 0.1 * p_r[s] + 0.3 * p_in[s] for s in core}
    kw = {items[i]["s2id"] for i in _kw(intent) if i in items} if intent else set()     # 索引里可能还有后来没过门槛的
    doms = set(intent["domains"]) if intent else set()
    grp = {s: d if (d := by_s2[s].get("d")) in doms else OTHER for s in core}
    pick = _pick(score, grp, NODES - FRONTIER, kw & core)
    yr = datetime.now().year
    fresh = sorted([s for s in core if s not in pick and (by_s2[s]["year"] or 0) >= yr - 1],
                   key=lambda s: -(col.log10p(by_s2[s]["cites"]) + by_s2[s]["hot"] + relv[s]))[:FRONTIER]
    chosen = pick + fresh + [a for a in ancestors if a not in pick]
    lead = {s for g in set(grp.values()) - {OTHER}
            for s in sorted((s for s in chosen if grp.get(s) == g), key=lambda s: -score[s])[:LEAD]}   # 每个子方向前几名
    key = set(sorted([s for s in chosen if s in score], key=lambda s: -score[s])[:KEY]) | set(ancestors[:3]) | lead
    return {"chosen": chosen, "key": key, "by_s2": by_s2, "edges": edges, "pr": pr, "ancestors": ancestors,
            "core": len(core), "anc_counts": {a: cnt[a] for a in ancestors}}


def _node_text(g: dict) -> tuple[str, dict[str, str]]:
    ids = {s: f"p{n}" for n, s in enumerate(g["chosen"])}
    cited: dict[str, list[str]] = {}
    for a, b in g["edges"]:
        if a in ids and b in ids:
            cited.setdefault(a, []).append(b)
    lines = []
    for s, pid in ids.items():
        r = g["by_s2"][s]
        on = list(dict.fromkeys([b for b in json.loads(r.get("builds_on") or "[]") if b in ids] +
                                sorted(cited.get(s, []), key=lambda b: -g["pr"].get(b, 0))))[:6]
        lines.append(json.dumps({"id": pid, "y": r["year"], "t": r["title"][:120], "k": r.get("k") or "", "d": r.get("d") or "",
                                 "cites": r["cites"], "s": r.get("s") or (r.get("tldr") or "")[:120],
                                 "pb": json.loads(r.get("problem") or "[]"), "m": json.loads(r.get("method") or "[]"),
                                 "on": [ids[b] for b in on]} | ({"key": True} if s in g["key"] else {}),
                                ensure_ascii=False))
    return "\n".join(lines), {v: k for k, v in ids.items()}


def _clean(x: dict, back: dict[str, str]) -> dict:
    ok = lambda i: i in back  # noqa: E731
    lines = []
    for ln in x.get("lines") or []:
        nodes = [{"s2id": back[n["id"]], "role": str(n.get("role") or ""), "note": str(n.get("note") or "")[:80]}
                 for n in ln.get("nodes") or [] if isinstance(n, dict) and ok(n.get("id"))]
        if nodes:
            lines.append({"name": str(ln.get("name") or "")[:30], "summary": str(ln.get("summary") or "")[:300], "nodes": nodes})
    return {"overview": str(x.get("overview") or "")[:400], "lines": lines,
            "foundations": [back[i] for i in x.get("foundations") or [] if ok(i)],
            "surveys": [back[i] for i in x.get("surveys") or [] if ok(i)],
            "open": [str(o)[:60] for o in x.get("open") or []][:4]}


def _shown(res: dict) -> set[str]:
    return {n["s2id"] for ln in res["lines"] for n in ln["nodes"]} | set(res["foundations"]) | set(res["surveys"])


def _attach(res: dict, miss: list[str], g: dict) -> dict:
    """补问后仍漏掉的 key 论文：按引用边挂到关联最多的研究线（按年份插入），一条都不沾的放进「其它重要工作」。"""
    nb: dict[str, set[str]] = {}
    for a, b in g["edges"]:
        nb.setdefault(a, set()).add(b)
        nb.setdefault(b, set()).add(a)
    yr = lambda s: g["by_s2"][s]["year"] or 0  # noqa: E731
    extra = []
    for m in miss:
        node = {"s2id": m, "role": "相关", "note": str(g["by_s2"][m].get("s") or "")[:80]}
        hits = [len(nb.get(m, set()) & {n["s2id"] for n in ln["nodes"]}) for ln in res["lines"]]
        if hits and max(hits):
            ln = res["lines"][hits.index(max(hits))]
            ln["nodes"] = sorted(ln["nodes"] + [node], key=lambda n: yr(n["s2id"]))
        else:
            extra.append(node)
    if extra:
        res["lines"].append({"name": "其它重要工作", "summary": "", "nodes": sorted(extra, key=lambda n: yr(n["s2id"]))})
    return res


def build(topic: str, use_cache: bool = True) -> dict:
    key = norm(topic)
    if use_cache and (c := db.row("SELECT result FROM paper_maps WHERE topic=?", [key])):
        return json.loads(c["result"])
    intent, c1 = rewrite(topic)
    rel = recall(intent)
    g = subgraph(rel, intent)
    text, back = _node_text(g)
    must = ", ".join(sorted((fwd := {v: k for k, v in back.items()})[s] for s in g["key"]))
    user = f"主题：{topic}\n必须出现：{must}\n论文：\n{text}"
    raw, c2 = lab.chat(LINES, user, max_tokens=6000, json_mode=True)
    res = _clean(json.loads(raw), back)
    if miss := [fwd[s] for s in g["key"] if s not in _shown(res)]:
        raw, c3 = lab.chat(LINES, f"{user}\n\n上一版结果：{raw}\n\n上一版漏了这些 key 论文：{', '.join(miss)}。"
                                  "把它们放进合适的线（或 foundations / surveys），输出完整的新 JSON。",
                           max_tokens=6000, json_mode=True)
        c2 += c3
        res = _clean(json.loads(raw), back)
        res = _attach(res, [s for s in g["key"] if s not in _shown(res)], g)
    res = res | {
        "topic": topic, "intent": intent, "recalled": len(rel), "core": g["core"], "chosen": g["chosen"], "key": sorted(g["key"]),
        "ancestors": g["ancestors"], "cost": round(c1 + c2, 4), "created": db.now()}
    db.execute("INSERT OR REPLACE INTO paper_maps(topic,result,cost,created) VALUES (?,?,?,?)",
               [key, json.dumps(res, ensure_ascii=False), res["cost"], res["created"]])
    return res


def render(res: dict) -> str:
    """脉络 → markdown（arXiv 链接 + 年份 + 被引）。"""
    info = {r["s2id"]: r for r in db.rows("SELECT s2id, arxiv, title, year, cites FROM paper_items")}

    def ref(s: str) -> str:
        r = info.get(s) or {}
        url = f"https://arxiv.org/abs/{r['arxiv']}" if r.get("arxiv") else f"https://www.semanticscholar.org/paper/{s}"
        return f"[{r.get('title', s)}]({url})（{r.get('year')}，被引 {r.get('cites', 0):,}）"

    out = [f"# {res['topic']} 研究脉络", "", res["overview"], ""]
    if res["foundations"]:
        out += ["**前置基础**：" + "；".join(ref(s) for s in res["foundations"]), ""]
    for ln in res["lines"]:
        out += [f"## {ln['name']}", "", ln["summary"], ""]
        out += [f"- **{n['role']}** {ref(n['s2id'])}：{n['note']}" for n in ln["nodes"]]
        out.append("")
    if res["surveys"]:
        out += ["## 推荐综述", ""] + [f"- {ref(s)}" for s in res["surveys"]] + [""]
    if res["open"]:
        out += ["## 仍未解决", ""] + [f"- {o}" for o in res["open"]] + [""]
    out.append(f"<sub>召回 {res['recalled']} 篇 → 子图 {res['core']} 篇 → 选 {len(res['chosen'])} 篇成线；花费 ${res['cost']}</sub>")
    return "\n".join(out)



# ---------- 知识库「论文脉络」标签页用 ----------

def _init() -> None:
    db.init([col.SCHEMA])


def overview() -> dict:
    """库里有多少论文（按入库档位）、标注了多少、已经生成过哪些主题的脉络。"""
    _init()
    tiers = {r["tier"]: r["n"] for r in db.rows("SELECT tier, count(*) n FROM paper_items WHERE status='in' GROUP BY tier")}
    labeled = db.row("SELECT count(*) n FROM paper_labels l JOIN paper_items p ON p.s2id=l.s2id WHERE p.status='in'")["n"]
    maps = db.rows("SELECT json_extract(result,'$.topic') topic, json_array_length(result,'$.lines') lines, "
                   "json_array_length(result,'$.chosen') chosen, cost, created FROM paper_maps ORDER BY created DESC")
    return {"total": sum(tiers.values()), "tiers": tiers, "labeled": labeled, "maps": maps}


def view(res: dict) -> dict:
    """脉络 JSON + 里面出现的每篇论文的元信息（标题、链接、年份、被引、类型 / 方向名、一句话）。"""
    t = lab.taxonomy()
    kinds = {x["code"]: x["name"] for x in t["kinds"]}
    doms = {c["code"]: c["name"] for d in t["domains"] for c in d["children"]}
    ids = list(_shown(res))
    rows = db.rows(f"SELECT p.s2id, p.arxiv, p.title, p.year, p.cites, p.tier, l.k, l.d, l.s FROM paper_items p "
                   f"LEFT JOIN paper_labels l ON l.s2id=p.s2id WHERE p.s2id IN ({','.join('?' * len(ids))})", ids) if ids else []
    papers = {r["s2id"]: {"title": r["title"], "year": r["year"], "cites": r["cites"] or 0, "classic": r["tier"] == "classic",
                          "url": f"https://arxiv.org/abs/{r['arxiv']}" if r["arxiv"] else f"https://www.semanticscholar.org/paper/{r['s2id']}",
                          "kind": kinds.get(r["k"] or "", ""), "domain": doms.get(r["d"] or "", ""), "s": r["s"] or ""} for r in rows}
    yr = lambda n: papers.get(n["s2id"], {}).get("year") or 0
    lines = [{**ln, "nodes": sorted(ln["nodes"], key=yr)} for ln in res.get("lines") or []]   # 模型给的顺序偶尔不按年份
    keep = ("topic", "overview", "foundations", "surveys", "open", "recalled", "core", "cost", "created")
    return {k: res.get(k) for k in keep} | {"lines": lines, "chosen": len(res.get("chosen") or []), "papers": papers}
