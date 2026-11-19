"""吸收流水线：给一个选题和时间窗，把 X 长文抽成认知、归到问题、合并成卡，对照知识库里“我的判断”，再挂上论文 / 开源项目 / 产品动态 / 讨论四类证据。

每一步的结果存在 data/absorb/<run>/ 下，已有结果的步骤不重跑；页面读最后一步的 cards.json（接口见 absorb.py）。
只读 app.db 和知识库，不写正式库。向量用本机的 Embedding 模型，解释器和模型路径在设置 absorb.* 里。

    python -m app.modules._absorb_run --topic "Agent 评测" --start 2026-11-03 --end 2026-11-16
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
import os
import random
import re
import sqlite3
import subprocess
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from .. import agent, settings
from ..db import DATA_DIR, DB_PATH, ROOT

BASE = DATA_DIR / "absorb"
KB = DATA_DIR / "kb"
STAGES = ["profile", "theme", "extract", "questions", "pools", "compare", "cards", "evidence", "page"]
STAGE_NAME = {"profile": "定选题范围", "theme": "筛选长文", "extract": "抽取认知", "questions": "定问题并归位", "pools": "准备证据池",
              "compare": "问题内比对", "cards": "合并成卡并对照已有判断", "evidence": "挂证据并写现状", "page": "生成页面数据"}
SIM_PAIR = 0.68
SIM_EVID = 0.45
POOL_LABEL = {"papers": "论文", "repos": "开源项目", "intel": "产品动态", "disc": "讨论"}

P_PROFILE = """你为一个选题划定范围，供后面从大量文章、论文、开源项目里筛选材料。
输入有：选题名、用户知识库里这个选题下已有的概念（可能为空）、长文库的领域代码、论文库和开源项目库的二级分类。
输出：
scope：一段话写清这个选题包含什么（列出 6–10 个具体子话题）；
exclude：一句话写清什么不算（容易混进来但不属于这个选题的内容）；
x_domains：长文库里可能出现这个选题文章的领域代码，宁多勿少；
paper_domains / oss_domains：与这个选题直接相关的二级分类代码，各 5–12 个。
只输出 JSON：{"scope":"…","exclude":"…","x_domains":["…"],"paper_domains":["…"],"oss_domains":["…"]}"""

P_THEME = """选题“{topic}”：{scope}
下面每行一篇文章（序号|类型|标题|标签|摘要）。挑出主要内容是在讲这个选题的方法、经验、数据或教训的文章。
不算：{exclude}
只输出 JSON：{{"in":[序号,...]}}"""

P_EXTRACT = """你从一篇X长文里抽取“认知卡”。只收有信息量、值得别人记住并复用的认知，宁缺毋滥。
每条必须同时满足：
1) 有具体信息：数字、条件、机制、步骤、因果或明确取舍，读完能多知道点什么；
2) 可复用：换个场景、过一段时间仍然有用，不是某天某事的流水账；
3) 不是常识、口号、愿景，也不是“某工具可以做某事”这种泛泛能力介绍。
一律不收：奖项荣誉、促销价和折扣、活动日程、公司自夸、导流话术、对未来的空泛展望、单纯罗列功能名。
例外：产品发布或重大变更，只要改变了读者能做什么或该怎么选，就收，并写清变了什么。
做法类要写出关键步骤或参数，不要只写“应该做好X”。
输出严格JSON：{"units":[{"id":"u1","type":"判断|做法|事实|教训|预测|变更","claim":"一句话≤60字，一条命题，带上关键数字或条件","key":"同一命题的英文规范表述≤25词，用于跨语言比对","scope":"成立条件/适用场景≤15字，没有写空串","quote":"原文逐字摘录≤40字","source_kind":"实践者|官方|推广|转述"}]}
type：判断=是什么/好坏；做法=怎么做；事实=数据或已发生的事；教训=踩坑；预测=将会怎样；变更=发布/更新/变动。
source_kind：作者讲亲身做过的=实践者；官方账号发布=官方；带卖货/导流目的=推广；转述他人=转述。
最多25条，不够就少给。只输出JSON。"""

P_QUESTIONS = """你在为选题“{topic}”设计一组长期稳定的“问题”，用来归拢大量零散的认知。问题是做这件事的人反复要回答的决策性问题，答案会随时间变化，问题本身不变。
要求：8–10 个问题；互不重叠；合起来能装下样本里绝大多数说法；每个问题是一句具体的疑问句（不是名词短语），再给一句范围说明（什么算、什么不算）。
只输出 JSON：{{"questions":[{{"id":"Q1","q":"……？","scope":"……"}}]}}"""

P_PAIR = """你严格判断每一对认知的关系。A是新来的，B是库里已有的。默认答“不同”，只有满足下面条件才合并：
重复=A和B表达的是同一个具体结论，换一种说法而已，删掉A不会损失任何信息；
增益=A和B的核心结论完全一致，且A多了B没有的具体数据、条件或场景（A必须包含B的全部核心结论）；
反驳=A明确断言与B相反的结论，或指出B在某场景下不成立。只是侧重点不同、范围不同、互补，一律不算反驳；
不同=其余所有情况，包括同一话题的不同侧面、因果前后关系、上下位关系、互补做法、只是同属一类。
输入每行“编号 | A：… | B：…”。只输出 JSON：{"r":{"编号":{"rel":"重复|增益|反驳|不同","gain":"A相对B新增的内容≤30字，非增益写空串"}}}，每个编号都要有。"""

P_CONFLICT = """逐对判断两条说法是否真的互相矛盾（针对同一件事给出相反结论或相反建议，读者必须二选一）。只是侧重点、范围、条件不同或互补，不算矛盾。
输入每行“编号 | A：… | B：…”。只输出 JSON：{"r":{"编号":{"c":true或false,"point":"矛盾点≤30字，非矛盾写空串"}}}"""

P_JUDG = """用户已有一条自己的判断 J。下面是若干条新进来的说法，逐条判断它和 J 的关系：
一致=说的是同一个结论，支持 J；补充=同一个结论上给了 J 没有的数据、条件或做法；相反=与 J 的结论相反或指出 J 不成立；无关=其余（只是同一话题不算）。
只输出 JSON：{"r":{"编号":"一致|补充|相反|无关"}}"""

P_EVID = """给你一条认知 C 和若干候选材料（论文、开源项目、产品动态、社区讨论）。逐条严格判断：
佐证=材料内容直接支持 C：论文给出相符的数据或结论；项目实现了 C 说的做法；产品按 C 说的方式做了；讨论里有人给出相符的经验。
反对=材料给出与 C 相反的数据、结论或经验。
无关=其余，包括只是同一话题、同一领域。拿不准一律判无关。
只输出 JSON：{"r":{"编号":{"v":"佐证|反对|无关","why":"依据≤25字"}}}"""

P_NOW = """你为一个“问题”写现状综述，材料只有下面这些认知卡（编号、说法、独立作者数、是否有矛盾）。
写 3–5 句：先写多数人的共识，再写分歧点，最后写哪些只有单一来源、还待验证。每句话末尾必须用 [C编号] 标出依据的卡，可多个；不许写卡片里没有的内容。
再给一个状态：共识为主 / 有分歧 / 证据少。
只输出 JSON：{"now":"……[C12]。……[C3][C7]。","status":"共识为主|有分歧|证据少"}"""


def slug(topic: str, start: str, end: str) -> str:
    return f"{re.sub(r'[^0-9A-Za-z一-鿿]+', '-', topic).strip('-')}_{start}_{end}"


def _models() -> tuple[str, str]:
    return agent.tier_model("light") or "claude-haiku-5-5", settings.get("absorb.strong_model") or "claude-opus-5-5"


def _ro() -> sqlite3.Connection:
    return sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)


def _pmap(f, xs, n=8):
    with ThreadPoolExecutor(n) as p:
        return list(p.map(f, xs))


class Run:
    def __init__(self, topic: str, start: str, end: str, min_q: int = 3):
        self.topic, self.start, self.end, self.min_q = topic, start, end, min_q
        self.dir = BASE / slug(topic, start, end)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.light, self.strong = _models()
        self.cost: dict[str, float] = {}
        self.secs: dict[str, float] = {}
        self.fails: dict[str, int] = {}
        self.lock = threading.Lock()
        self.stage = ""
        meta = self.dir / "run.json"
        if not meta.exists():
            meta.write_text(json.dumps({"topic": topic, "start": start, "end": end, "min_q": min_q, "created": time.time()}, ensure_ascii=False), "utf-8")

    def has(self, name: str) -> bool:
        return (self.dir / name).exists()

    def load(self, name: str):
        return json.loads((self.dir / name).read_text("utf-8"))

    def save(self, name: str, obj) -> None:
        tmp = self.dir / (name + ".tmp")
        tmp.write_text(json.dumps(obj, ensure_ascii=False), "utf-8")
        tmp.replace(self.dir / name)

    def status(self, **kw) -> None:
        old = self.load("status.json") if self.has("status.json") else {}
        cost = {**old.get("cost", {}), **self.cost}
        secs = {**old.get("secs", {}), **self.secs}
        fails = {**old.get("fails", {}), **self.fails}
        self.save("status.json", {**old, "pid": os.getpid(), "stage": self.stage, "stage_name": STAGE_NAME.get(self.stage, ""),
                                  "step": STAGES.index(self.stage) + 1 if self.stage in STAGES else 0, "steps": len(STAGES),
                                  "cost": cost, "secs": secs, "fails": fails, "updated": time.time(), **kw})

    def call(self, model: str, system: str, user: str):
        cmd = [settings.get("engines.claude.bin", "claude"), "-p", "--model", model, "--output-format", "json", "--tools", "",
               "--system-prompt", system, "--settings", json.dumps({"disableAllHooks": True})]
        for _ in range(3):
            try:
                p = subprocess.run(cmd, input=user, capture_output=True, text=True, timeout=900, env=agent.clean_env(), cwd=str(self.dir))
                j = json.loads(p.stdout)
                with self.lock:
                    self.cost[self.stage] = self.cost.get(self.stage, 0.0) + float(j.get("total_cost_usd") or 0)
                return json.loads(re.search(r"\{.*\}", (j.get("result") or "").strip(), re.S).group(0))
            except Exception:  # noqa: BLE001
                continue
        with self.lock:
            self.fails[self.stage] = self.fails.get(self.stage, 0) + 1
        return None

    def embed(self, texts: list[str], name: str, max_len: int) -> np.ndarray:
        out = self.dir / name
        if not out.exists():
            src = self.dir / (name + ".texts.json")
            src.write_text(json.dumps(texts, ensure_ascii=False), "utf-8")
            cfg = settings.get("absorb", {}) or {}
            p = subprocess.run([cfg.get("embed_python") or sys.executable, str(ROOT / "scripts" / "absorb_embed.py"), str(src), str(out), str(max_len),
                                cfg.get("embed_model") or "Qwen/Qwen3-Embedding-0.6B", str(BASE / "_emb_cache")], capture_output=True, text=True)
            if p.returncode:
                raise RuntimeError("算向量失败（检查设置 absorb.embed_python 和 absorb.embed_model）：" + p.stderr.strip()[-200:])
            src.unlink()
        return np.load(out)


def s_profile(r: Run) -> dict:
    c = _ro()
    xd = [x[0] for x in c.execute("select domain from x_art where kind!='' and domain!='' group by 1")]
    tax = {k: json.loads((ROOT / "app" / "modules" / f"{k}_taxonomy.json").read_text("utf-8"))["domains"] for k in ("paper", "oss")}
    lst = {k: "；".join(f"{ch['code']}={ch['name']}" for d in v for ch in d["children"]) for k, v in tax.items()}
    page = KB / "topics" / f"{r.topic}.md"
    concepts = "、".join(re.findall(r"\[\[(.+?)\]\]", page.read_text("utf-8"))[:40]) if page.exists() else ""
    o = r.call(r.strong, P_PROFILE, f"选题：{r.topic}\n知识库已有概念：{concepts or '无'}\n长文库领域代码：{'、'.join(xd)}\n论文二级分类：{lst['paper']}\n开源项目二级分类：{lst['oss']}")
    if not o:
        raise RuntimeError("定选题范围失败：模型没有返回结果")
    codes = {k: {ch["code"] for d in v for ch in d["children"]} for k, v in tax.items()}
    return {"scope": o["scope"], "exclude": o.get("exclude", ""), "concepts": concepts, "in_kb": page.exists(),
            "x_domains": [d for d in o.get("x_domains", []) if d in xd] or xd,
            "paper_domains": [d for d in o.get("paper_domains", []) if d in codes["paper"]],
            "oss_domains": [d for d in o.get("oss_domains", []) if d in codes["oss"]]}


def s_theme(r: Run) -> dict:
    pf = r.load("profile.json")
    cols = "id user fol n q kind domain title tags summary posted_at day".split()
    rows = _ro().execute(f"select {','.join(cols)} from x_art where day between ? and ? and kind!='' and domain in ({','.join('?' * len(pf['x_domains']))})",
                         (r.start, r.end, *pf["x_domains"])).fetchall()
    sysm = P_THEME.format(topic=r.topic, scope=pf["scope"], exclude=pf["exclude"])

    def run(b):
        o = r.call(r.light, sysm, "\n".join(f"{i}|{x[5]}|{x[7]}|{x[8]}|{x[9]}" for i, x in enumerate(b)))
        return [b[i] for i in sorted({i for i in (o or {}).get("in", []) if isinstance(i, int) and 0 <= i < len(b)})], o is None
    res = _pmap(run, [rows[i:i + 40] for i in range(0, len(rows), 40)])
    return {"scanned": len(rows), "keep": [dict(zip(cols, x)) for b in res for x in b[0]], "fail": sum(b[1] for b in res)}


def s_extract(r: Run) -> list:
    arts = [a for a in r.load("theme.json")["keep"] if (a["q"] or 0) >= r.min_q]

    def run(a):
        text = _ro().execute("select text from x_art where id=?", (a["id"],)).fetchone()[0] or ""
        ex = r.call(r.light, P_EXTRACT, f"标题：{a['title']}\n\n{text[:14000]}")
        return {**a, "units": (ex or {}).get("units", []), "fail": ex is None}
    return _pmap(run, arts, 10)


def s_questions(r: Run) -> dict:
    def norm(s):
        return re.sub(r"[\W_]+", "", s or "").lower()
    c = _ro()
    units, bad = [], 0
    for a in r.load("extract.json"):
        if not a["units"]:
            continue
        text = norm(c.execute("select text from x_art where id=?", (a["id"],)).fetchone()[0])
        for u in a["units"]:
            if not isinstance(u, dict) or not u.get("claim"):
                continue
            if norm(u.get("quote"))[:60] not in text:
                bad += 1
                continue
            units.append({"aid": a["id"], "user": a["user"], "day": a["day"], "q": a["q"],
                          **{k: str(u.get(k) or "") for k in ("type", "claim", "key", "scope", "quote", "source_kind")}})
    for i, u in enumerate(units):
        u["i"] = i
    if not units:
        raise RuntimeError("这个选题在时间窗内没有抽到认知，换个选题或放宽时间窗")
    pf = r.load("profile.json")
    samp = random.Random(7).sample(units, min(500, len(units)))
    o = r.call(r.strong, P_QUESTIONS.format(topic=r.topic), f"选题范围：{pf['scope']}\n用户知识库里这个选题已有的概念：{pf['concepts'] or '无'}\n\n文章里抽出的说法样本：\n" + "\n".join("- " + u["claim"] for u in samp))
    if not o or not o.get("questions"):
        raise RuntimeError("定问题失败：模型没有返回结果")
    qs = o["questions"]
    sysm = "把每条说法归到最合适的一个问题下。问题列表：\n" + "\n".join(f"{q['id']} {q['q']}（{q['scope']}）" for q in qs) + '\n都不合适就归 X。下面每行“序号|说法”。只输出 JSON：{"a":{"序号":"Q3",...}}，每条都要有。'
    ids = {q["id"] for q in qs}

    def run(b):
        a = (r.call(r.light, sysm, "\n".join(f"{u['i']}|{u['claim']}（{u['scope']}）" for u in b)) or {}).get("a", {})
        for u in b:
            u["qid"] = a.get(str(u["i"])) if a.get(str(u["i"])) in ids else "X"
    _pmap(run, [units[i:i + 50] for i in range(0, len(units), 50)], 10)
    return {"Q": qs, "U": units, "quote_bad": bad}


def s_pools(r: Run) -> dict:
    pf = r.load("profile.json")
    c = _ro()

    def hit(d, d2, codes):
        try:
            l2 = json.loads(d2 or "[]")
        except Exception:  # noqa: BLE001
            l2 = []
        return d in codes or any(x in codes for x in l2)
    papers = [{"title": x[0], "date": x[1] or "", "cites": x[2] or 0, "url": f"https://arxiv.org/abs/{x[3]}" if x[3] else "", "s": x[9] or "",
               "text": f"{x[0]}。{x[9]} 问题：{x[6]} 方法：{x[7]}"[:500]}
              for x in c.execute("select p.title,p.pub_date,p.cites,p.arxiv,l.d,l.d2,l.problem,l.method,l.bench,l.s from paper_labels l join paper_items p on p.s2id=l.s2id")
              if hit(x[4], x[5], set(pf["paper_domains"]))]
    repos = [{"name": x[0], "stars": x[1] or 0, "date": (x[2] or "")[:10], "url": "https://github.com/" + x[0], "s": x[7] or "",
              "text": f"{x[0]}：{x[7]} {x[6]} {(x[3] or '')[:150]}"[:500]}
             for x in c.execute("select r.name,r.stars,r.created,r.descr,l.d,l.d2,l.t,l.s from oss_labels l join oss_repos r on r.name=l.name where r.archived=0 or r.archived is null")
             if hit(x[4], x[5], set(pf["oss_domains"]))]
    repos = sorted(repos, key=lambda x: -x["stars"])[:8000]
    intel = []
    for x in c.execute("select e.title,e.summary,e.date,e.type,e.product,c.name,e.sources from intel_event e left join intel_company c on c.id=e.company_id"):
        try:
            url = json.loads(x[6] or "[]")[0]["url"]
        except Exception:  # noqa: BLE001
            url = ""
        intel.append({"title": x[0], "date": x[2] or "", "type": x[3], "company": x[5] or "", "url": url, "s": x[1] or "", "text": f"{x[5]} {x[4]}：{x[0]}。{x[1]}"[:500]})
    disc = []
    for x in c.execute("select source,title,summary,url,date,popularity,extra from feed_items where type='discussion' and date between ? and ?", (r.start, r.end + "T99")):
        try:
            ex = json.loads(x[6] or "{}")
        except Exception:  # noqa: BLE001
            ex = {}
        g = ex.get("gist") or ""
        disc.append({"source": x[0], "title": x[1], "date": (x[4] or "")[:10], "url": ex.get("hn_url") or x[3], "pop": x[5] or 0, "s": (x[2] or "")[:300],
                     "text": f"{x[1]}。{(x[2] or '')[:300]} {str(g)[:200]}"[:600]})
    judg, seen = [], set()
    for f in sorted(glob.glob(str(KB / "concepts" / "*.md"))):
        t = Path(f).read_text("utf-8")
        if pf["in_kb"] and f'topic: "{r.topic}"' not in t:
            continue
        for m in re.finditer(r"^\d+\. \*\*(.+?)\*\*\s*\n\s+(.+?) · (\d{4}-\d\d-\d\d)", t, re.M):
            s = m.group(1).strip()
            if s in seen or s.startswith(("疑问", "想")) or "？" in s[-2:]:
                continue
            seen.add(s)
            judg.append({"text": s, "concept": Path(f).stem, "kind": m.group(2), "date": m.group(3)})
    return {"papers": papers, "repos": repos, "intel": intel, "disc": disc, "judg": judg}


def _pool_emb(r: Run, pools: dict) -> np.ndarray:
    return r.embed([x["text"] for k in ("papers", "repos", "intel", "disc", "judg") for x in pools[k]], "pool_emb.npy", 160)


def s_compare(r: Run) -> dict:
    units = r.load("questions.json")["U"]
    emb = r.embed([u["key"] or u["claim"] for u in units], "unit_emb.npy", 64)
    _pool_emb(r, r.load("pools.json"))
    byq = collections.defaultdict(list)
    for u in units:
        if u["qid"] != "X":
            byq[u["qid"]].append(u["i"])
    pairs = []
    for ids in byq.values():
        ids.sort(key=lambda i: (units[i]["day"], i))
        m = emb[ids] @ emb[ids].T
        for a in range(1, len(ids)):
            s = m[a, :a].copy()
            for b in range(a):
                if units[ids[b]]["aid"] == units[ids[a]]["aid"]:
                    s[b] = -1
            pairs += [(ids[a], ids[b], float(s[b])) for b in np.argsort(-s)[:3] if s[b] >= SIM_PAIR]

    def line(i):
        return f"{units[i]['claim']}（{units[i]['scope']}）"

    def run(b):
        res = (r.call(r.light, P_PAIR, "\n".join(f"{k} | A：{line(a)} | B：{line(bb)}" for k, (a, bb, _) in enumerate(b))) or {}).get("r", {})
        return [{"a": a, "b": bb, "sim": s, "rel": (res.get(str(k)) or {}).get("rel", "不同"), "gain": (res.get(str(k)) or {}).get("gain", "")} for k, (a, bb, s) in enumerate(b)]
    return {"J": [x for o in _pmap(run, [pairs[i:i + 15] for i in range(0, len(pairs), 15)], 10) for x in o]}


def s_cards(r: Run) -> dict:
    units = r.load("questions.json")["U"]
    links = r.load("compare.json")["J"]
    emb = np.load(r.dir / "unit_emb.npy")
    judg = r.load("pools.json")["judg"]
    par = list(range(len(units)))

    def find(x):
        while par[x] != x:
            par[x] = par[par[x]]
            x = par[x]
        return x
    gain = {}
    for j in links:
        if j["rel"] in ("重复", "增益"):
            par[find(j["a"])] = find(j["b"])
            if j["rel"] == "增益":
                gain[j["a"]] = j["gain"]
    comp = collections.defaultdict(list)
    for u in units:
        if u["qid"] != "X":
            comp[find(u["i"])].append(u["i"])
    cards, u2c = [], {}
    for ms in comp.values():
        ms.sort(key=lambda i: (units[i]["day"], i))
        ok = [i for i in ms if units[i]["source_kind"] != "推广"]
        rep = max(ok or ms, key=lambda i: (units[i]["source_kind"] in ("实践者", "官方"), units[i]["q"], len(units[i]["claim"])))
        c = {"id": len(cards), "qid": units[ms[0]]["qid"], "rep": rep, "claim": units[rep]["claim"], "scope": units[rep]["scope"], "type": units[rep]["type"],
             "members": ms, "authors": sorted({units[i]["user"] for i in ok}), "n_art": len({units[i]["aid"] for i in ms}),
             "gain": {str(i): gain[i] for i in ms if i in gain}, "maxq": max(units[i]["q"] for i in ms), "first": units[ms[0]]["day"], "last": units[ms[-1]]["day"]}
        for i in ms:
            u2c[i] = c["id"]
        cards.append(c)

    def line(i):
        return f"{units[i]['claim']}（{units[i]['scope']}）"
    cp = {}
    for j in links:
        if j["rel"] == "反驳" and u2c[j["a"]] != u2c[j["b"]]:
            a, b = u2c[j["a"]], u2c[j["b"]]
            cp.setdefault((min(a, b), max(a, b)), (j["a"], j["b"]))
    cpl = list(cp.items())

    def run(b):
        res = (r.call(r.strong, P_CONFLICT, "\n".join(f"{k} | A：{line(x)} | B：{line(y)}" for k, (_, (x, y)) in enumerate(b))) or {}).get("r", {})
        return [{"a": ca, "b": cb, "ua": x, "ub": y, "point": res[str(k)].get("point", "")} for k, ((ca, cb), (x, y)) in enumerate(b) if (res.get(str(k)) or {}).get("c")]
    conf = [x for o in _pmap(run, [cpl[i:i + 12] for i in range(0, len(cpl), 12)], 6) for x in o]
    jl = []
    if judg and cards:
        sim = np.load(r.dir / "pool_emb.npy")[-len(judg):] @ np.stack([emb[c["rep"]] for c in cards]).T

        def runj(k):
            idx = [int(i) for i in np.argsort(-sim[k])[:10]]
            res = (r.call(r.light, P_JUDG, f"J：{judg[k]['text']}\n\n" + "\n".join(f"{n} | {cards[i]['claim']}（{cards[i]['scope']}）" for n, i in enumerate(idx))) or {}).get("r", {})
            return [{"j": k, "c": i, "rel": res[str(n)], "sim": float(sim[k, i])} for n, i in enumerate(idx) if res.get(str(n)) in ("一致", "补充", "相反")]
        jl = [x for o in _pmap(runj, range(len(judg)), 8) for x in o]
    return {"C": cards, "conf": conf, "jl": jl, "conf_candidates": len(cpl)}


def s_evidence(r: Run) -> dict:
    qd = r.load("questions.json")
    units, qs = qd["U"], qd["Q"]
    d = r.load("merged.json")
    cards = d["C"]
    pools = r.load("pools.json")
    pe = np.load(r.dir / "pool_emb.npy")
    shown = {c["id"] for c in cards if len(c["authors"]) >= 2} | {x["c"] for x in d["jl"]} | {x["a"] for x in d["conf"]} | {x["b"] for x in d["conf"]}
    for q in qs:
        s = [c for c in cards if c["qid"] == q["id"] and c["id"] not in shown and c["maxq"] >= 4 and units[c["rep"]]["source_kind"] in ("实践者", "官方")]
        s.sort(key=lambda c: (-c["maxq"], -bool(re.search(r"\d", c["claim"])), -len(c["claim"])))
        shown |= {c["id"] for c in s[:3]}
    sh = sorted(shown)
    se = r.embed([f"{cards[i]['claim']}（{cards[i]['scope']}）" for i in sh], "shown_emb.npy", 96)
    names, off, rng = ["papers", "repos", "intel", "disc"], 0, {}
    for n in names:
        rng[n] = (off, off + len(pools[n]))
        off += len(pools[n])

    def run(k):
        cid, cand = sh[k], []
        for n in names:
            a, b = rng[n]
            if a == b:
                continue
            s = pe[a:b] @ se[k]
            cand += [(n, int(i), float(s[i])) for i in np.argsort(-s)[:4] if s[i] >= SIM_EVID]
        if not cand:
            return cid, []
        res = (r.call(r.light, P_EVID, f"C：{cards[cid]['claim']}（{cards[cid]['scope']}）\n\n" + "\n".join(f"{m} | {POOL_LABEL[n]} | {pools[n][i]['text'][:350]}" for m, (n, i, _) in enumerate(cand))) or {}).get("r", {})
        ev = []
        for m, (n, i, s) in enumerate(cand):
            v = res.get(str(m)) or {}
            if v.get("v") in ("佐证", "反对"):
                x = pools[n][i]
                ev.append({"pool": n, "v": v["v"], "why": v.get("why", ""), "sim": s, "title": x.get("title") or x.get("name"), "url": x.get("url", ""), "date": x.get("date", ""),
                           "meta": {"papers": x.get("cites"), "repos": x.get("stars"), "intel": x.get("company"), "disc": x.get("source")}[n]})
        return cid, ev
    evid = dict(_pmap(run, range(len(sh)), 10))

    def runq(q):
        cs = sorted([cards[i] for i in sh if cards[i]["qid"] == q["id"]], key=lambda c: -len(c["authors"]))[:60]
        if not cs:
            return q["id"], {"now": "", "raw": "", "status": "证据少"}
        ids = {c["id"] for c in cs}
        conf = [x for x in d["conf"] if x["a"] in ids or x["b"] in ids]
        o = r.call(r.strong, P_NOW, f"问题：{q['q']}\n\n认知卡：\n" + "\n".join(f"C{c['id']} | {c['claim']}（{c['scope']}）| {len(c['authors'])} 个作者" for c in cs)
                   + "\n\n矛盾：\n" + "\n".join(f"C{x['a']} 与 C{x['b']}：{x['point']}" for x in conf)) or {"now": "", "status": "证据少"}
        keep = [s for s in re.split(r"(?<=\])(?=[^\[])", o.get("now", "")) if (n := re.findall(r"\[C(\d+)\]", s)) and all(int(x) in ids for x in n)]
        return q["id"], {"now": "".join(keep), "raw": o.get("now", ""), "status": o.get("status", "证据少")}
    return {"shown": sh, "ev": {str(k): v for k, v in evid.items()}, "sum": dict(_pmap(runq, qs, 5))}


TAGS = "jcsrn"


def s_page(r: Run) -> dict:
    th, qd, d, e, pools = r.load("theme.json"), r.load("questions.json"), r.load("merged.json"), r.load("evidence.json"), r.load("pools.json")
    units, qs, cards, judg = qd["U"], qd["Q"], d["C"], pools["judg"]
    links = r.load("compare.json")["J"]
    shown = set(e["shown"])
    cj, cc = collections.defaultdict(list), collections.defaultdict(list)
    for x in d["jl"]:
        cj[x["c"]].append({"rel": x["rel"], "text": judg[x["j"]]["text"], "concept": judg[x["j"]]["concept"], "date": judg[x["j"]].get("date", "")})
    for x in d["conf"]:
        cc[x["a"]].append({"o": x["b"], "point": x["point"], "claim": cards[x["b"]]["claim"]})
        cc[x["b"]].append({"o": x["a"], "point": x["point"], "claim": cards[x["a"]]["claim"]})
    out = []
    for i in e["shown"]:
        c, ev, jd, seen, src = cards[i], sorted(e["ev"].get(str(i), []), key=lambda x: -x["sim"]), cj[i], set(), []
        for m in c["members"]:
            u = units[m]
            if u["aid"] in seen:
                continue
            seen.add(u["aid"])
            src.append({"user": u["user"], "url": f"https://x.com/{u['user']}/status/{u['aid']}", "day": u["day"], "kind": u["source_kind"],
                        "gain": c["gain"].get(str(m), ""), "claim": u["claim"], "quote": u["quote"]})
        hard = any(x["v"] == "佐证" and x["pool"] in ("papers", "repos", "intel") for x in ev)
        tag = ("j" if any(j["rel"] == "相反" for j in jd) else "c" if cc[i] or any(x["v"] == "反对" for x in ev)
               else "s" if any(j["rel"] == "一致" for j in jd) and (len(c["authors"]) >= 2 or hard) else "r" if jd else "n")
        jd.sort(key=lambda j: {"相反": 0, "一致": 1}.get(j["rel"], 2))
        out.append({"id": i, "qid": c["qid"], "tag": tag, "claim": c["claim"], "scope": c["scope"], "authors": c["authors"], "ev": ev, "conf": cc[i], "judg": jd, "src": src})
    out.sort(key=lambda c: (TAGS.index(c["tag"]), -len(c["authors"]), -len(c["ev"])))
    qout = []
    for q in qs:
        cs, sc = [c for c in cards if c["qid"] == q["id"]], [c for c in out if c["qid"] == q["id"]]
        s = e["sum"].get(q["id"], {})
        qout.append({"id": q["id"], "q": q["q"], "scope": q.get("scope", ""), "status": s.get("status", "证据少"), "now": s.get("now", ""),
                     "n_units": sum(u["qid"] == q["id"] for u in units), "n_cards": len(cs), "n_shown": len(sc),
                     "n_multi": sum(len(c["authors"]) >= 2 for c in sc), "n_conf": sum(bool(c["conf"]) for c in sc),
                     "ev": dict(collections.Counter(x["pool"] for c in sc for x in c["ev"])),
                     "fold": [[c["claim"], units[c["rep"]]["user"], units[c["rep"]]["aid"]] for c in sorted(cs, key=lambda c: -c["maxq"]) if c["id"] not in shown]})
    st = r.load("status.json")
    cost = st["cost"]
    meta = {"topic": r.topic, "window": f"{r.start} 至 {r.end}", "cost": round(sum(cost.values()), 2), "scanned": th["scanned"], "theme": len(th["keep"]),
            "extracted": len(r.load("extract.json")), "min_q": r.min_q, "units": len(units), "cards": len(cards), "shown": len(out),
            "multi": sum(len(c["authors"]) >= 2 for c in out), "conf": len(d["conf"]), "jrel": sum(bool(c["judg"]) for c in out),
            "evcards": sum(bool(c["ev"]) for c in out), "ratio": round(len(units) / max(1, len(out))), "folded": len(cards) - len(out),
            "unassigned": sum(u["qid"] == "X" for u in units), "quote_bad": qd.get("quote_bad", 0), "pairs": len(links),
            "rel": dict(collections.Counter(j["rel"] for j in links)), "tags": dict(collections.Counter(c["tag"] for c in out)),
            "pools": {k: len(v) for k, v in pools.items()}, "evn": {f"{k[0]}:{k[1]}": v for k, v in collections.Counter((x["pool"], x["v"]) for c in out for x in c["ev"]).items()},
            "judg_scope": "这个选题下概念页" if r.load("profile.json")["in_kb"] else "知识库全部概念页", "minutes": round(sum(st["secs"].values()) / 60), "fails": sum(st.get("fails", {}).values())}
    return {"meta": meta, "profile": r.load("profile.json"), "questions": qout, "cards": out}


OUT = {"profile": "profile.json", "theme": "theme.json", "extract": "extract.json", "questions": "questions.json", "pools": "pools.json",
       "compare": "compare.json", "cards": "merged.json", "evidence": "evidence.json", "page": "cards.json"}
FN = {"profile": s_profile, "theme": s_theme, "extract": s_extract, "questions": s_questions, "pools": s_pools,
      "compare": s_compare, "cards": s_cards, "evidence": s_evidence, "page": s_page}
NPY = {"compare": ["unit_emb.npy", "pool_emb.npy"], "evidence": ["shown_emb.npy"]}


README = """# 吸收的中间结果：{topic}，{start} 至 {end}

由 app/modules/_absorb_run.py 生成，“吸收”板块读 cards.json 和 reactions.json。来源是 data/app.db 和 data/kb 的只读查询。
每一步的结果都留着，后面换提炼方式或呈现方式可以直接复用；删掉某一步的文件再发起同一选题，会从那一步起往后重新算。

| 文件 | 哪一步 | 内容 |
|-|-|-|
| run.json | | 选题、起止日期、文章质量下限 |
| status.json | | 进度、各步花费（美元）、耗时（秒）和模型调用失败次数 |
| profile.json | 1 定选题范围 | scope 算什么、exclude 不算什么、要扫的长文 / 论文 / 开源项目领域、知识库里有没有这个主题 |
| theme.json | 2 筛选长文 | scanned 扫描篇数；keep 判为属于选题的文章（id、作者、质量分、标题、摘要、发布时间） |
| extract.json | 3 抽取认知 | 每篇文章抽出的认知（type、claim、key、scope、quote 原文引文） |
| questions.json | 4 定问题并归位 | Q 问题列表；U 通过引文核对的认知，qid 是归到的问题 |
| pools.json、pool_emb.npy | 5 准备证据池 | papers 论文、repos 开源项目、intel 产品动态、disc 窗口内讨论、judg 知识库里“我的判断”；向量顺序同上 |
| compare.json、unit_emb.npy | 6 问题内比对 | 相近认知两两判 重复 / 增益 / 反驳 / 不同；向量顺序同 questions.json 的 U |
| merged.json | 7 合并成卡 | 合并后的卡、复核过的矛盾、每张卡和已有判断的关系 |
| evidence.json、shown_emb.npy | 8 挂证据并写现状 | 需要看的卡、每张卡挂上的佐证和反对、各问题的现状 |
| cards.json | 9 生成页面数据 | 页面直接用的数据：meta 漏斗数字、questions、cards |
| reactions.json | | 你在页面上的表态（已知 / 采纳 / 不信 / 想试） |
| run.log | | 从页面发起时的运行日志 |

向量缓存在上一级的 _emb_cache/，按文本内容命中，换选题时重复出现的材料不用再算。
"""


def run(topic: str, start: str, end: str, min_q: int = 3) -> Path:
    r = Run(topic, start, end, min_q)
    (r.dir / "README.md").write_text(README.format(topic=topic, start=start, end=end), "utf-8")
    r.status(started=time.time(), done=False, error="")
    try:
        for n, st in enumerate(STAGES):
            r.stage = st
            r.status()
            if not r.has(OUT[st]):
                for later in STAGES[n:]:
                    for name in [OUT[later]] * (later != st) + NPY.get(later, []):
                        (r.dir / name).unlink(missing_ok=True)
                t = time.time()
                r.save(OUT[st], FN[st](r))
                r.secs[st] = time.time() - t
                r.status()
                print(f"{st} {time.time() - t:.0f}s ${r.cost.get(st, 0):.2f}", flush=True)
        r.status(done=True)
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        r.status(done=False, error=str(e)[:300] or type(e).__name__)
        raise
    return r.dir


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--topic", required=True)
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--min-q", type=int, default=3)
    a = ap.parse_args()
    print(run(a.topic, a.start, a.end, a.min_q))
