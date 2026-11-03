"""论文脉络库的标注（设计稿 §4）：DeepSeek 一次标 25 篇，Jev 只判近 6 个月论文是不是水文。

- 输入：标题、年份、发表处、摘要（没有摘要用 S2 的 TLDR），加上它的库内参考文献（按被引取前 15 篇，编号 r0..）。
- 输出（JSON Lines）：类型 k、主方向 d、副方向 d2、problem / method / bench / base 标签、中文一句话 s、
  builds_on（只能填参考文献编号，避免模型编造「在谁的基础上改进」）。
- 校验同开源雷达：code 必须在分类体系里，标签和一句话不能空；不合格 / 漏掉的再单独问一次（放宽 code）。
- label_src = 标题 + 摘要 + 库内参考文献的哈希，内容不变不重复问。
"""
from __future__ import annotations

import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from hashlib import sha1
from pathlib import Path

import httpx

from .. import db
from . import _paper_collect as col
from ._feed_judge import API as JEV_API, MODEL as JEV_MODEL
from ._oss_label import DEEPSEEK_MODEL, DEEPSEEK_PRICE

log = logging.getLogger(__name__)

TAXONOMY_PATH = Path(__file__).with_name("paper_taxonomy.json")
BATCH, PARALLEL, REFS_SHOWN = 25, 8, 15
JEV_BATCH = 20
TIMEOUT = 600

SYSTEM = """你在给 AI 论文做分类和检索标签，用来回答「X 方向有哪些研究脉络、某个问题有哪些解法」。分类体系：
{tax}

对每篇论文输出一行 JSON（JSON Lines，不要代码块、不要解释），字段：
{{"i":序号,"k":类型code,"d":主方向二级code,"d2":[副方向二级code，0-2个],"problem":[它要解决的问题，2-4个],"method":[方法与术语，2-5个],
"bench":[用到的评测集，0-5个],"base":[用到的基座模型，0-3个],"builds_on":[直接改进或沿用的参考文献编号如"r3"，0-3个],"s":"中文一句话"}}
规则：
- 每篇都必须输出一行，i 从 0 到最后一个，不能跳。
- k 只能填类型 code；技术报告里带新方法的记 model，方法写进 method；「提出评测并评一批模型」记 benchmark；没有新方法、靠实验得出发现的记 empirical。
- d 按论文最核心的贡献选，不按应用场景选：用 RLHF 训练的对话模型如果贡献在对齐方法上，d=pref_opt。
- problem 写「什么问题」（如「RLHF 训练不稳定」「检索结果和生成脱节」「专家负载不均衡」），不写泛词（「提升性能」「效率」）。
- method / bench / base 用论文里的原名（英文专有名词保留英文，如 DPO、GRPO、GSM8K、Llama-2-7B），没有就空数组。
- builds_on 只能从这篇论文给出的 refs 里选它**直接改进或沿用**的工作，只是被比较或顺带引用的不算；refs 为空或都不是就填 []。
- s 30-50 字：做了什么 + 核心做法 + 关键结论或数字。
"""

JEV_Q = ("state.items.{k} 是一篇 arXiv 上的 AI 论文（标题 + 摘要）。读者是想跟踪 AI 研究脉络的工程师。它是不是低价值的水文？"
         "以下回答是：把现成大模型或方法套到某个行业 / 小任务上测一遍、换个数据集重跑已有方法、堆提示词技巧、"
         "结论只是「GPT-4 在 X 上表现如何」、没有新意的综述、标题夸大而内容单薄。"
         "以下回答否：提出新方法 / 新架构 / 新训练范式、发布有影响的模型或数据集、有扎实实验支撑的新发现、"
         "有分量的评测基准、系统梳理一个方向的综述。")


@lru_cache(maxsize=1)
def taxonomy() -> dict:
    return json.loads(TAXONOMY_PATH.read_text())


def codes() -> dict[str, set[str]]:
    t = taxonomy()
    return {"k": {x["code"] for x in t["kinds"]}, "d": {c["code"] for d in t["domains"] for c in d["children"]}}


def domain_names() -> dict[str, str]:
    return {c["code"]: f"{d['name']} / {c['name']}" for d in taxonomy()["domains"] for c in d["children"]}


def tax_text() -> str:
    t = taxonomy()
    lines = ["类型 k（单选）：" + "；".join(f"{k['code']}={k['name']}（{k['desc']}）" for k in t["kinds"]), "方向（填二级 code）："]
    for d in t["domains"]:
        lines.append(f"[{d['name']}] " + "；".join(f"{c['code']}={c['name']}" + (f"（{'/'.join(c['eg'])}）" if c["eg"] else "")
                                                   for c in d["children"]))
    return "\n".join(lines)


# ---------- 模型调用 ----------

def chat(system: str, user: str, max_tokens: int = 16000, json_mode: bool = False) -> tuple[str, float]:
    """DeepSeek flash（关思考）→ (内容, 美元)。"""
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not key:
        raise RuntimeError("未配置 DEEPSEEK_API_KEY（项目根目录 .env）")
    base = os.environ.get("DEEPSEEK_API_BASE", "https://api.deepseek.com").rstrip("/")
    body = {"model": DEEPSEEK_MODEL, "temperature": 0.1, "max_tokens": max_tokens, "thinking": {"type": "disabled"},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    r = httpx.post(f"{base}/chat/completions", timeout=TIMEOUT, headers={"Authorization": f"Bearer {key}"}, json=body)
    r.raise_for_status()
    j = r.json()
    u = j.get("usage") or {}
    hit = u.get("prompt_cache_hit_tokens", 0)
    miss = u.get("prompt_cache_miss_tokens", u.get("prompt_tokens", 0) - hit)
    hit_p, miss_p, out_p = DEEPSEEK_PRICE
    return j["choices"][0]["message"]["content"], hit * hit_p + miss * miss_p + u.get("completion_tokens", 0) * out_p


# ---------- 标注 ----------

def _corpus() -> dict[str, dict]:
    return {r["s2id"]: r for r in db.rows("SELECT s2id, title, year, cites FROM paper_items WHERE status='in'")}


def refs_of(r: dict, corpus: dict[str, dict]) -> list[dict]:
    """库内参考文献，按被引取前 REFS_SHOWN 篇。"""
    rs = [corpus[s] for s in dict.fromkeys(json.loads(r.get("refs") or "[]")) if s in corpus and s != r["s2id"]]
    return sorted(rs, key=lambda x: -(x["cites"] or 0))[:REFS_SHOWN]


def label_src(r: dict, refs: list[dict]) -> str:
    return sha1(json.dumps([r["title"], r.get("abstract") or r.get("tldr") or "", [x["s2id"] for x in refs]]).encode()).hexdigest()[:16]


def _row(n: int, r: dict, refs: list[dict]) -> str:
    x = {"i": n, "title": r["title"], "year": r["year"], "venue": r.get("venue") or "",
         "abstract": (r.get("abstract") or r.get("tldr") or "")[:1600],
         "refs": [{"r": f"r{j}", "t": f["title"][:90], "y": f["year"]} for j, f in enumerate(refs)]}
    return json.dumps(x, ensure_ascii=False)


def _tags(v, n: int, w: int = 40) -> list[str]:
    return [str(t).strip()[:w] for t in (v or []) if str(t).strip()][:n]


def validate(x: dict, refs: list[dict], lenient: bool = False) -> dict | None:
    cs = codes()
    try:
        k, d = str(x.get("k")), str(x.get("d"))
        d2 = [str(v) for v in (x.get("d2") or []) if str(v) in cs["d"]]
        s = str(x.get("s") or "").strip()[:120]
        problem, method = _tags(x.get("problem"), 4), _tags(x.get("method"), 5)
        b_on = []
        for v in x.get("builds_on") or []:
            v = str(v).strip().lstrip("r")
            if v.isdigit() and int(v) < len(refs):
                b_on.append(refs[int(v)]["s2id"])
    except Exception:  # noqa: BLE001
        return None
    if lenient and k not in cs["k"]:
        k = "method"
    if lenient and d not in cs["d"]:
        d = d2[0] if d2 else "other"
    d2 = [v for v in dict.fromkeys(d2) if v != d][:2]
    if k not in cs["k"] or d not in cs["d"] or not s or not (problem or method):
        return None
    return {"k": k, "d": d, "d2": d2, "problem": problem, "method": method, "bench": _tags(x.get("bench"), 5),
            "base": _tags(x.get("base"), 3), "builds_on": list(dict.fromkeys(b_on))[:3], "s": s}


def ask(chunk: list[tuple[dict, list[dict]]], lenient: bool = False, call=chat) -> tuple[dict[str, dict], float]:
    text, cost = call(SYSTEM.format(tax=tax_text()), "论文：\n" + "\n".join(_row(n, r, f) for n, (r, f) in enumerate(chunk)))
    out = {}
    for line in text.splitlines():
        line = line.strip().strip(",")
        if not line.startswith("{"):
            continue
        try:
            x = json.loads(line)
            i = int(x["i"])
        except Exception:  # noqa: BLE001
            continue
        if 0 <= i < len(chunk) and (lab := validate(x, chunk[i][1], lenient)):
            out[chunk[i][0]["s2id"]] = lab
    return out, cost


def label_batch(chunk: list[tuple[dict, list[dict]]], call=chat) -> tuple[dict[str, dict], float, list[str]]:
    errors, cost = [], 0.0
    try:
        got, cost = ask(chunk, call=call)
    except Exception as e:  # noqa: BLE001
        got = {}
        errors.append(f"{type(e).__name__}: {str(e)[:160]}")
    miss = [x for x in chunk if x[0]["s2id"] not in got]
    if miss:
        try:
            more, c2 = ask(miss, lenient=True, call=call)
            got.update(more)
            cost += c2
        except Exception as e:  # noqa: BLE001
            errors.append(f"重问：{type(e).__name__}: {str(e)[:160]}")
    return got, cost, errors


def save(chunk: list[tuple[dict, list[dict]]], got: dict[str, dict]) -> int:
    ver, now = taxonomy()["version"], db.now()
    for r, refs in chunk:
        lab = got.get(r["s2id"])
        if not lab:
            continue
        db.execute("INSERT OR REPLACE INTO paper_labels (s2id,k,d,d2,problem,method,bench,base,builds_on,s,tax_ver,label_src,labeled_at) "
                   "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   [r["s2id"], lab["k"], lab["d"], *(json.dumps(lab[f], ensure_ascii=False) for f in
                                                     ("d2", "problem", "method", "bench", "base", "builds_on")),
                    lab["s"], ver, label_src(r, refs), now])
        index(r, lab)
    return len(got)


def index(r: dict, lab: dict) -> None:
    db.execute("DELETE FROM paper_fts WHERE rowid=?", [r["id"]])
    tags = " | ".join(lab["problem"] + lab["method"] + lab["bench"] + lab["base"])
    db.execute("INSERT INTO paper_fts(rowid,title,s,tags,abstract) VALUES (?,?,?,?,?)",
               [r["id"], r["title"], lab["s"], tags, (r.get("abstract") or r.get("tldr") or "")[:2000]])


def todo(limit: int = 0) -> list[tuple[dict, list[dict]]]:
    corpus, ver = _corpus(), taxonomy()["version"]
    labs = {r["s2id"]: r for r in db.rows("SELECT s2id, label_src, tax_ver FROM paper_labels")}
    out = []
    for r in db.rows("SELECT * FROM paper_items WHERE status='in' AND detail_at IS NOT NULL ORDER BY cites DESC"):
        refs = refs_of(r, corpus)
        old = labs.get(r["s2id"])
        if not old or old["tax_ver"] != ver or old["label_src"] != label_src(r, refs):
            out.append((r, refs))
            if limit and len(out) >= limit:
                break
    return out


def run(limit: int = 0, items: list | None = None, persist: bool = True, call=chat) -> dict:
    """标注队列（或传入的 items）。persist=False 只返回标签不落库（一致性测试用）。"""
    rows = items if items is not None else todo(limit)
    chunks = [rows[i:i + BATCH] for i in range(0, len(rows), BATCH)]
    stat = {"labeled": 0, "todo": len(rows), "cost": 0.0, "errors": [], "labels": {}}
    with ThreadPoolExecutor(PARALLEL) as ex:
        for chunk, (got, cost, errs) in zip(chunks, ex.map(lambda c: label_batch(c, call), chunks)):
            stat["labeled"] += save(chunk, got) if persist else len(got)
            if not persist:
                stat["labels"].update(got)
            stat["cost"] = round(stat["cost"] + cost, 4)
            stat["errors"] = (stat["errors"] + errs)[-20:]
    return stat


# ---------- Jev：近期论文是不是水文 ----------

def judge_recent(client: httpx.Client | None = None) -> dict:
    """给近 6 个月、有早期信号、还没判过的论文问 Jev，写 paper_items.junk，然后重新过门槛。"""
    key = (os.environ.get("TYPESAFE_API_KEY") or os.environ.get("JEV_API_KEY") or "").strip()
    rows = [r for r in db.rows("SELECT * FROM paper_items WHERE tier='recent' AND junk IS NULL AND arxiv!=''")
            if col.decide(r)[0] == "in"]
    stat = {"todo": len(rows), "judged": 0, "errors": []}
    if not key or not rows:
        stat["errors"] += [] if key else ["未配置 JEV_API_KEY"]
        return stat
    c = client or httpx.Client(timeout=httpx.Timeout(90.0, connect=10.0))
    for i in range(0, len(rows), JEV_BATCH):
        part = rows[i:i + JEV_BATCH]
        refs = {f"i{n}": r for n, r in enumerate(part)}
        payload = {"model": JEV_MODEL,
                   "state": {"items": {k: {"title": r["title"], "abstract": (r["abstract"] or r["tldr"] or "")[:1200],
                                           "venue": r["venue"] or "arXiv"} for k, r in refs.items()}},
                   "questions": {f"{k}_junk": {"type": "noul", "instructions": JEV_Q.format(k=k)} for k in refs}}
        try:
            resp = c.post(JEV_API, headers={"Authorization": f"Bearer {key}"}, json=payload)
            resp.raise_for_status()
            ans = resp.json().get("answers") or {}
            for k, r in refs.items():
                p = (ans.get(f"{k}_junk") or {}).get("noul")
                if isinstance(p, (int, float)) and 0 <= p <= 1:
                    db.execute("UPDATE paper_items SET junk=? WHERE id=?", [round(float(p), 3), r["id"]])
                    stat["judged"] += 1
        except Exception as e:  # noqa: BLE001
            stat["errors"].append(f"{type(e).__name__}: {str(e)[:120]}")
    stat["admit"] = col.admit_all()
    return stat
