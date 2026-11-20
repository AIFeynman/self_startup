"""HN 吸收流水线：过去一段时间 HN 上和 AI 相关的帖子，评论区压成话题（阵营、经验）和资源清单。

collect 采帖 → relevance 判是否 AI → digest 单帖提炼（复用 _feed_hn，观点和经验带逐字原话并核对）→ topics 聚成话题 → synth 话题内综合 → page 生成页面数据。
每步结果存在 data/absorb/hn/<起>_<止>/ 下，已有结果的步骤不重跑；只读 app.db 之外的数据，不写正式库。页面读 page.json（接口见 absorb.py）。

    python -m app.modules._absorb_hn --start 2026-11-13 --end 2026-11-19
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import hashlib
import json
import math
import os
import re
import shutil
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

import httpx

from .. import agent
from ..db import DATA_DIR, ROOT
from . import _absorb_run as ar
from . import _feed_hn as hnd

BASE = DATA_DIR / "absorb" / "hn"
CACHE = BASE / "_cache"     # 跨天缓存：每天滚动 7 天，只对新帖和评论涨得多的帖花模型
KB_JUDGMENTS = DATA_DIR / "kb" / "judgments"
STAGES = ["collect", "relevance", "digest", "topics", "synth", "page"]
STAGE_NAME = {"collect": "采集帖子", "relevance": "判断是否 AI 相关", "digest": "单帖提炼评论区", "topics": "聚成话题", "synth": "话题内综合", "page": "生成页面数据"}
QUERIES = ["AI", "LLM", "GPT", "Claude", "OpenAI", "Anthropic", "Gemini", "DeepSeek", "agent", "coding agent", "machine learning", "neural network",
           "Nvidia", "Copilot", "language model", "chatbot", "generative", "MCP"]
MIN_POINTS, MIN_COMMENTS = 50, 40
SHOW_MIN_COMMENTS = 10
DIGEST_MIN = 30
HITS_PAGES = 2
KINDS = ("事件", "议题", "实践")
OUTCOMES = ("成功", "失败", "有条件")
JOBS = 4

P_TOPICS = """你把一周内 Hacker News 上 AI 相关的帖子聚成“话题”，供读者快速判断这周 AI 圈有什么事、社区站哪边。
输入每行：序号|评论数|标题|讨论一句话|被提到的主要对象。
规则：
- 话题 = 一个值得判断的问题，用问句或明确的议题陈述作标题（≤28 字），不要写成某篇文章的标题。
- 类型三选一：事件（一次发布 / 事故 / 新闻，可能散在多帖里）、议题（跨帖的争论或共同现象）、实践（别人怎么做 / 怎么验证 / 怎么用）。
- 同一件事、同一个争论的多帖并入同一话题；评论数很多（≥150）的单帖可以自成话题；其余零散帖放进 tail。
- 话题数 8–12 个，按你判断的重要程度排序；每帖只能属于一个话题或 tail。不要为了凑数把不相干的帖子合并。
只输出 JSON：{"topics":[{"title":"…","kind":"事件|议题|实践","posts":[序号...]}],"tail":[序号...]}"""

P_SYNTH = """你为一个话题写综合，读者要在 30 秒内判断“社区倾向什么、有没有我该参考的做法”。输入是该话题下各帖的观点（o 开头编号，含阵营标签、持该观点的大约评论数、逐字原话）和亲身经验（e 开头编号），以及读者已有判断（可能为空）。
输出 JSON：
{"verdict":"一句话结论 ≤90 字，写社区整体倾向和分歧所在，句末用 [1][2] 引用下面 camps 的序号","camps":[{"claim":"阵营主张 ≤40 字","side":"主流|反对|少数|补充","refs":["观点编号",...]}],
"exps":[{"ref":"经验编号","outcome":"成功|失败|有条件"}],"mine":[{"judgment":"读者判断的标题，原样抄","rel":"印证|相反","why":"≤40 字"}]}
要求：
- 把表达同一立场的观点归并成一个阵营，阵营 3–5 个，refs 只能用输入里出现过的编号，不要编造；只写输入里有的信息，不补充事实。
- exps 只收对读者取舍有参考价值的经验（最多 8 条）；outcome：成功 = 达成了目标，失败 = 出了问题 / 放弃，有条件 = 有但书。
- mine 只在话题明显触及读者某条判断、且是印证或相反时才写，没有就给空数组；不要硬凑。"""


def load_env() -> None:
    f = ROOT / ".env"
    if f.exists():
        for ln in f.read_text("utf-8").splitlines():
            if "=" in ln and not ln.lstrip().startswith("#"):
                k, v = ln.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"\''))


def day_ts(d: str, add: int = 0) -> int:
    return int(dt.datetime.fromisoformat(d).replace(tzinfo=dt.timezone.utc).timestamp()) + add * 86400


class HRun(ar.Run):
    def __init__(self, start: str, end: str):
        self.start, self.end, self.topic = start, end, "HN"
        self.dir = BASE / f"{start}_{end}"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.light, self.strong = agent.tier_model("light") or "claude-haiku-5-5", agent.tier_model("standard") or "claude-sonnet-5-5"
        self.cost, self.secs, self.fails = {}, {}, {}
        import threading
        self.lock = threading.Lock()
        self.stage = ""
        if not self.has("run.json"):
            self.save("run.json", {"start": start, "end": end, "created": time.time()})

    def status(self, **kw) -> None:
        old = self.load("status.json") if self.has("status.json") else {}
        self.save("status.json", {**old, "pid": os.getpid(), "stage": self.stage, "stage_name": STAGE_NAME.get(self.stage, ""),
                                  "step": STAGES.index(self.stage) + 1 if self.stage in STAGES else 0, "steps": len(STAGES),
                                  "cost": {**old.get("cost", {}), **self.cost}, "secs": {**old.get("secs", {}), **self.secs},
                                  "fails": {**old.get("fails", {}), **self.fails}, "updated": time.time(), **kw})


# ---------- 1 采集 ----------

def is_show(title: str) -> bool:
    return bool(re.match(r"\s*(show|launch|ask)\s+hn", title, re.I))


def keep(p: dict) -> bool:
    n, pts = p["comments"], p["points"]
    return pts >= MIN_POINTS or n >= MIN_COMMENTS or (is_show(p["title"]) and n >= SHOW_MIN_COMMENTS)


def s_collect(r: HRun) -> list:
    lo, hi = day_ts(r.start), day_ts(r.end, 1)
    out: dict[str, dict] = {}
    with httpx.Client(timeout=30, follow_redirects=True) as c:
        for q in QUERIES:
            for page in range(HITS_PAGES):
                res = c.get("https://hn.algolia.com/api/v1/search_by_date", params={
                    "query": q, "tags": "story", "hitsPerPage": 100, "page": page,
                    "numericFilters": f"created_at_i>={lo},created_at_i<{hi},points>=10"})
                res.raise_for_status()
                hits = res.json().get("hits") or []
                for h in hits:
                    oid = str(h["objectID"])
                    out.setdefault(oid, {"id": oid, "title": h.get("title") or "", "url": h.get("url") or "", "points": h.get("points") or 0,
                                         "comments": h.get("num_comments") or 0, "author": h.get("author") or "", "ts": h.get("created_at_i") or 0,
                                         "hn_url": f"https://news.ycombinator.com/item?id={oid}"})
                if len(hits) < 100:
                    break
    posts = sorted((p for p in out.values() if keep(p)), key=lambda p: -p["comments"])
    r.save("collected_all.json", {"queried": len(out)})
    return posts


# ---------- 2 相关性 ----------

JEV_API = "https://api.typesafe.ai/v1/systemone"
JEV_MIN, JEV_SURE = 0.3, 0.6      # Jev 给的概率偏低：≥0.3 算 AI 相关（与 Haiku 判断吻合 97%），≥0.6 为明确，其间标“边缘”
Q_AI = ("state.items.{k} 是 Hacker News 上的一个帖子。它是否主要在讨论 AI：大模型 / 模型发布与基准、AI Agent 和编码 Agent、AI 产品与工具、"
        "AI 基础设施与算力（GPU、芯片、数据中心）、AI 对行业 / 工作 / 法律 / 社会的影响、AI 公司的商业动态？"
        "纯编程语言、普通安全事件、与 AI 无关的硬件和产品、只是顺带提到 AI 的回答否。")


def rel_label(p: float) -> str:
    return "ai" if p >= JEV_SURE else "edge" if p >= JEV_MIN else "no"


def s_relevance(r: HRun) -> dict:
    posts = r.load("posts.json")
    key = (os.environ.get("TYPESAFE_API_KEY") or os.environ.get("JEV_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("未配置 JEV_API_KEY（项目根目录 .env）")
    pf = CACHE / "relevance_p.json"
    old = json.loads(pf.read_text("utf-8")) if pf.exists() else {}
    probs: dict[str, float] = {p["id"]: old[p["id"]] for p in posts if p["id"] in old}
    new = [p for p in posts if p["id"] not in old]
    with httpx.Client(timeout=60) as c:
        for i in range(0, len(new), 20):
            refs = {f"i{n}": p for n, p in enumerate(new[i:i + 20])}
            res = c.post(JEV_API, headers={"Authorization": f"Bearer {key}"}, json={
                "model": "jev-latest",
                "state": {"items": {k: {"title": p["title"], "domain": urlsplit(p["url"]).netloc, "points": p["points"], "comments": p["comments"]} for k, p in refs.items()}},
                "questions": {k: {"type": "noul", "instructions": Q_AI.format(k=k)} for k in refs}})
            res.raise_for_status()
            for k, p in refs.items():
                v = (res.json().get("answers", {}).get(k) or {}).get("noul")
                if not isinstance(v, (int, float)) or not 0 <= v <= 1:
                    raise RuntimeError(f"Jev 没返回 {p['id']} 的概率")
                probs[p["id"]] = round(float(v), 3)
    CACHE.mkdir(parents=True, exist_ok=True)
    pf.write_text(json.dumps({**old, **probs}, ensure_ascii=False), "utf-8")
    r.save("relevance_p.json", probs)
    return {i: rel_label(v) for i, v in probs.items()}


# ---------- 3 单帖提炼 ----------

def digest_post(r: HRun, p: dict, c: httpx.Client) -> dict | None:
    hit = hnd.cache_get(p["id"], p["comments"])
    if hit:
        return hit
    it = {"id": f"hn:{p['id']}", "title": p["title"], "url": p["url"], "summary": "", "popularity": p["points"]}
    op, comments = hnd.fetch_thread(p["id"], c)
    if not comments:
        return None
    text = hnd.render(comments)
    raw = r.call(r.light, hnd.SYSTEM, hnd._payload(it, text))
    if not isinstance(raw, dict):
        return None
    d = hnd.clean_digest(raw, comments, text, op)
    hnd.cache_put(p["id"], d, p["comments"])
    return d


def s_digest(r: HRun) -> dict:
    posts, rel = r.load("posts.json"), r.load("relevance.json")
    todo = [p for p in posts if rel.get(p["id"]) in ("ai", "edge") and (p["comments"] >= DIGEST_MIN or (is_show(p["title"]) and p["comments"] >= SHOW_MIN_COMMENTS))]
    done = r.load("digests.json") if r.has("digests.json") else {}
    todo = [p for p in todo if p["id"] not in done]
    errs = []
    with httpx.Client(timeout=hnd.TIMEOUT, follow_redirects=True) as c:
        def one(p):
            try:
                return p["id"], digest_post(r, p, c)
            except Exception as e:  # noqa: BLE001
                return p["id"], f"{type(e).__name__}: {str(e)[:100]}"

        with ThreadPoolExecutor(JOBS) as ex:
            for pid, d in ex.map(one, todo):
                if isinstance(d, dict):
                    done[pid] = d
                    r.save("digests.json", done)
                else:
                    errs.append(f"{pid}：{d or '提炼失败'}")
    r.fails["digest"] = len(errs)
    r.save("digest_errors.json", errs)
    return done


# ---------- 4 话题 ----------

def brief(p: dict, d: dict) -> str:
    ents = "、".join(e["name"] for e in d["entities"][:5])
    return f"|{p['comments']}|{p['title']}|{d['tldr']}|{ents}"


def s_topics(r: HRun) -> dict:
    posts = {p["id"]: p for p in r.load("posts.json")}
    dg = r.load("digests.json")
    ids = sorted(dg, key=lambda i: -posts[i]["comments"])
    user = "\n".join(f"{n}{brief(posts[i], dg[i])}" for n, i in enumerate(ids))
    j = r.call(r.strong, P_TOPICS, user)
    if not j:
        raise RuntimeError("话题聚合失败")
    used, topics = set(), []
    for t in j.get("topics") or []:
        mem = [ids[n] for n in t.get("posts") or [] if isinstance(n, int) and 0 <= n < len(ids) and ids[n] not in used]
        if not mem or not str(t.get("title") or "").strip():
            continue
        used.update(mem)
        topics.append({"title": str(t["title"]).strip()[:60], "kind": t.get("kind") if t.get("kind") in KINDS else "议题", "posts": mem})
    return {"topics": topics, "tail": [i for i in ids if i not in used]}


# ---------- 5 综合 ----------

def judgments() -> list[dict]:
    out = []
    for f in sorted(KB_JUDGMENTS.glob("*.md")):
        m = re.search(r"\*\*现在的立场：\*\*\s*(.+)", f.read_text("utf-8"))
        out.append({"title": f.stem, "stance": (m.group(1).strip() if m else "")[:120]})
    return out


def obs_of(ids: list[str], dg: dict) -> tuple[dict, dict]:
    ops, exps = {}, {}
    for pi, i in enumerate(ids):
        for j, o in enumerate(dg[i]["opinions"]):
            ops[f"p{pi}o{j}"] = {**o, "post": i}
        for j, x in enumerate(dg[i]["experiences"]):
            exps[f"p{pi}e{j}"] = {**x, "post": i}
    return ops, exps


def consensus(camps: list[dict], comments: int) -> str:
    tot = sum(c["n"] for c in camps) or 1
    sh = sorted((c["n"] / tot for c in camps), reverse=True) + [0, 0]
    if comments < 80:
        return "讨论少"
    if sh[0] >= 0.6:
        return "基本共识"
    return "有分歧" if sh[1] >= 0.25 else "基本共识"


def synth_one(r: HRun, t: dict, posts: dict, dg: dict, mine: list[dict]) -> dict:
    ops, exps = obs_of(t["posts"], dg)
    lines = [f"帖子 p{pi}：{posts[i]['title']}（{posts[i]['comments']} 评论）" for pi, i in enumerate(t["posts"])]
    lines += [f"{k} [{o['stance']}·约{o['n']}条] {o['claim']} | 原话：{o['quote']}" for k, o in ops.items()]
    lines += [f"{k} {x['who']}：{x['did']}，结果：{x['result']}" for k, x in exps.items()]
    lines += ["读者已有判断：" + "；".join(f"《{m['title']}》{m['stance']}" for m in mine)]
    j = r.call(r.strong, P_SYNTH, f"话题：{t['title']}\n" + "\n".join(lines)) or {}
    camps = []
    for c in j.get("camps") or []:
        refs = [x for x in c.get("refs") or [] if x in ops]
        if not refs or not str(c.get("claim") or "").strip():
            continue
        best = max(refs, key=lambda x: ops[x]["n"])
        camps.append({"claim": str(c["claim"]).strip()[:80], "side": c.get("side") if c.get("side") in hnd.STANCES else "补充",
                      "n": sum(ops[x]["n"] for x in refs) or len(refs), "quote": ops[best]["quote"], "by": ops[best]["by"], "cid": ops[best]["cids"][0],
                      "post": ops[best]["post"], "refs": len(refs)})
    camps.sort(key=lambda c: -c["n"])
    order = {}
    for c in j.get("camps") or []:
        order[len(order) + 1] = str(c.get("claim") or "").strip()[:80]
    ver = str(j.get("verdict") or "")
    cited = [int(x) for x in re.findall(r"\[(\d+)\]", ver)]
    new_idx = {k: next((n + 1 for n, c in enumerate(camps) if c["claim"] == v), 0) for k, v in order.items()}
    ver = re.sub(r"\[(\d+)\]", lambda m: f"[{new_idx.get(int(m.group(1)), 0)}]" if new_idx.get(int(m.group(1)), 0) else "", ver).strip()
    ok = bool(cited) and bool(re.search(r"\[\d+\]", ver))
    es = []
    for e in j.get("exps") or []:
        x = exps.get(e.get("ref"))
        if x:
            es.append({**x, "outcome": e.get("outcome") if e.get("outcome") in OUTCOMES else "有条件", "post": posts[x["post"]]["title"], "post_id": x["post"]})
    titles = {m["title"] for m in mine}
    mn = [{"judgment": m["judgment"], "rel": m["rel"], "why": str(m.get("why") or "")[:80]} for m in j.get("mine") or []
          if m.get("judgment") in titles and m.get("rel") in ("印证", "相反")]
    return {"verdict": ver if ok else "", "verdict_unchecked": not ok, "camps": camps, "exps": es, "mine": mn, "ok": bool(j)}


def synth_key(t: dict, dg: dict, mine: list[dict]) -> str:
    return hashlib.sha1(json.dumps([[dg[i] for i in sorted(t["posts"])], mine], ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:20]


def s_synth(r: HRun) -> list:
    posts = {p["id"]: p for p in r.load("posts.json")}
    dg, tp = r.load("digests.json"), r.load("topics.json")
    mine = judgments()
    sc = CACHE / "synth"
    sc.mkdir(parents=True, exist_ok=True)

    def one(t):
        f = sc / f"{synth_key(t, dg, mine)}.json"
        if f.exists():
            return json.loads(f.read_text("utf-8"))
        s = synth_one(r, t, posts, dg, mine)
        if s["ok"]:
            f.write_text(json.dumps(s, ensure_ascii=False), "utf-8")
        return s

    res = ar._pmap(one, tp["topics"], JOBS)
    return [{**t, **s} for t, s in zip(tp["topics"], res)]


# ---------- 6 页面 ----------

def res_key(u: str) -> str:
    sp = urlsplit(u)
    q = "&".join(x for x in sp.query.split("&") if x and not x.startswith(("utm_", "ref=", "s=", "a=", "si=")))
    return hnd._norm_url(f"https://{sp.netloc}{sp.path}" + (f"?{q}" if "youtube" in sp.netloc and q else ""))


def s_page(r: HRun) -> dict:
    posts = {p["id"]: p for p in r.load("posts.json")}
    rel, dg, tp, sy = r.load("relevance.json"), r.load("digests.json"), r.load("topics.json"), r.load("synth.json")
    where = {i: n for n, t in enumerate(sy) for i in t["posts"]}
    resources: dict[str, dict] = {}
    for i, d in dg.items():
        for l in d["links"]:
            g = resources.setdefault(res_key(l["url"]), {"url": l["url"], "title": l["title"], "kind": l["kind"], "why": l["why"], "people": set(), "rec": set(),
                                                         "self": 0, "posts": [], "topics": set(), "intents": collections.Counter()})
            g["people"].update(l.get("by") or [])
            if l.get("intent") == "推荐":
                g["rec"].update(a for a in l.get("by") or [] if a != posts[i]["author"])
            g["intents"][l.get("intent") or "佐证"] += 1
            g["self"] += 1 if l.get("self") else 0
            g["posts"].append(i)
            if i in where:
                g["topics"].add(where[i])
    rs = []
    for g in resources.values():
        intent = "推荐" if g["intents"]["推荐"] else "批评" if g["intents"]["批评"] > g["intents"]["佐证"] else "佐证"
        n = len(g["people"])
        rs.append({"url": g["url"], "title": g["title"], "kind": g["kind"], "why": g["why"], "people": n, "rec": len(g["rec"]), "intent": intent, "self": g["self"] > 0,
                   "score": (3 if intent == "推荐" else 0) + len(g["rec"]) + n - 0.5 * (g["self"] > 0),
                   "post": g["posts"][0], "post_title": posts[g["posts"][0]]["title"], "topics": sorted(g["topics"])})
    rs.sort(key=lambda x: -x["score"])
    topics = []
    for n, t in enumerate(sy):
        ps = [posts[i] for i in t["posts"]]
        comments = sum(p["comments"] for p in ps)
        people = len({a for i in t["posts"] for o in dg[i]["opinions"] + dg[i]["experiences"] for a in [o["by"]]})
        topics.append({"id": n, "title": t["title"], "kind": t["kind"], "consensus": consensus(t["camps"], comments),
                       "stats": {"posts": len(ps), "comments": comments, "people": people, "points": sum(p["points"] for p in ps)},
                       "posts": [{"id": p["id"], "title": p["title"], "url": p["url"], "hn_url": p["hn_url"], "points": p["points"], "comments": p["comments"]} for p in ps],
                       "verdict": t["verdict"], "verdict_unchecked": t["verdict_unchecked"], "camps": t["camps"], "exps": t["exps"], "mine": t["mine"],
                       "res": []})
    topics.sort(key=lambda t: -(t["stats"]["comments"]))
    remap = {t["id"]: k for k, t in enumerate(topics)}
    for t in topics:
        t["id"] = remap[t["id"]]
    for x in rs:
        x["topics"] = [remap[k] for k in x["topics"]]
    for t in topics:
        t["res"] = [k for k, x in enumerate(rs) if t["id"] in x["topics"] and x["kind"] not in ("讨论", "其他")]
    tail = [{"title": posts[i]["title"], "hn_url": posts[i]["hn_url"], "url": posts[i]["url"], "comments": posts[i]["comments"], "points": posts[i]["points"],
             "tldr": dg[i]["tldr"] if i in dg else ""} for i in tp["tail"]]
    tail += [{"title": p["title"], "hn_url": p["hn_url"], "url": p["url"], "comments": p["comments"], "points": p["points"], "tldr": ""}
             for i, p in posts.items() if rel.get(i) in ("ai", "edge") and i not in dg]
    kept = sum(len(d["opinions"]) + len(d["experiences"]) for d in dg.values())
    raw = sum(d.get("raw_ops", 0) + d.get("raw_exps", 0) for d in dg.values())
    st = r.load("status.json")
    secs = sum((st.get("secs") or {}).values())
    meta = {"start": r.start, "end": r.end, "queried": r.load("collected_all.json")["queried"], "collected": len(posts),
            "ai": sum(v == "ai" for v in rel.values()), "edge": sum(v == "edge" for v in rel.values()), "digested": len(dg),
            "comments": sum(d["total"] for d in dg.values()), "people": sum(d.get("people", 0) for d in dg.values()),
            "topics": len(topics), "tail": len(tail), "in_topics": sum(len(t["posts"]) for t in topics),
            "quotes_kept": kept, "quotes_raw": raw, "unchecked": sum(t["verdict_unchecked"] for t in topics),
            "resources": len(rs), "recommended": sum(x["intent"] == "推荐" for x in rs), "exps": sum(len(t["exps"]) for t in topics), "minutes": round(secs / 60), "cost": round(sum((st.get("cost") or {}).values()), 2),
            "fails": st.get("fails") or {}, "weights": {"min_points": MIN_POINTS, "min_comments": MIN_COMMENTS, "digest_min": DIGEST_MIN, "jev_min": JEV_MIN},
            "models": {"relevance": "Jev", "digest": r.light, "topics": r.strong}}
    return {"meta": meta, "topics": topics, "resources": rs, "tail": tail}


FILES = {"collect": "posts.json", "relevance": "relevance.json", "digest": "digests.json", "topics": "topics.json", "synth": "synth.json", "page": "page.json"}
FUNCS = {"collect": s_collect, "relevance": s_relevance, "digest": s_digest, "topics": s_topics, "synth": s_synth, "page": s_page}


def daily_window(days: int = 7, today: dt.date | None = None) -> tuple[str, str]:
    """到昨天为止（UTC）的最近 days 天：当天还没过完，不算。"""
    end = (today or dt.datetime.now(dt.timezone.utc).date()) - dt.timedelta(days=1)
    return (end - dt.timedelta(days=days - 1)).isoformat(), end.isoformat()


def prune(keep: int) -> list[str]:
    """只留最近 keep 个结果目录（目录名是 起_止 日期）；缓存和对比结果不动。"""
    runs = sorted((d for d in BASE.iterdir() if d.is_dir() and re.fullmatch(r"\d{4}-\d\d-\d\d_\d{4}-\d\d-\d\d", d.name)), key=lambda d: d.name, reverse=True)
    gone = runs[keep:]
    for d in gone:
        shutil.rmtree(d)
    return [d.name for d in gone]


def run(start: str, end: str) -> None:
    load_env()
    r = HRun(start, end)
    r.status(done=False, error="", started=time.time())
    try:
        for st in STAGES:
            r.stage = st
            if st == "digest" or not r.has(FILES[st]):
                t0 = time.time()
                r.status()
                r.save(FILES[st], FUNCS[st](r))
                r.secs[st] = r.secs.get(st, 0) + time.time() - t0
                r.status()
        r.status(done=True)
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        r.status(done=False, error=f"{type(e).__name__}: {e}")
        raise


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    a = ap.parse_args()
    run(a.start, a.end)
