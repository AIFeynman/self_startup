"""吸收流水线：给一个选题和时间窗，把 X 长文抽成认知、归到问题、合并成卡、标出矛盾，再挂上论文 / 开源项目 / 产品动态 / 讨论四类证据，
最后综合成 know how 地图：每个问题的成功做法和失败教训，以及领域结构、做事流程、成熟度、分歧、失败模式。

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

from .. import agent, settings, usage
from ..db import DATA_DIR, DB_PATH, ROOT

BASE = DATA_DIR / "absorb"
KB = DATA_DIR / "kb"
STAGES = ["profile", "theme", "extract", "questions", "pools", "compare", "cards", "evidence", "synth", "page"]
STAGE_NAME = {"profile": "定选题范围", "theme": "筛选长文", "extract": "抽取认知", "questions": "定问题并归位", "pools": "准备证据池",
              "compare": "问题内比对", "cards": "合并成卡并复核矛盾", "evidence": "挂证据并写现状", "synth": "综合 know how", "page": "生成页面数据"}
SIM_PAIR = 0.68
SIM_EVID = 0.45
POOL_LABEL = {"papers": "论文", "repos": "开源项目", "intel": "产品动态", "disc": "讨论"}
SYN_CARDS = 80

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

P_EXTRACT = """你从一篇X长文里抽取“认知卡”，供读者快速决定要不要采纳。认知卡收的是作者的观点、结论、认知、主张和亲身经验（做了什么、踩过什么坑、得出什么），不是文章里出现过的数字。
步骤：
1) 先用一句话写出这篇文章的主张 thesis：作者想让读者得出什么结论、改变什么做法。写不出来说明文章没有可复用的内容，units 返回空数组。
2) 再列认知。每条给重要度 w：3=文章的核心主张；2=独立成立、换个场景也能用的重要结论或做法；1=附带的数字、细节、轶事、工具功能。只输出 w≥2 的条目。文章里有几个独立成立的观点、结论、认知、主张、经验就收几条，不要为了控制数量把不同的结论合并或舍弃；文章越长、越密，条数越多（短文 2–4 条，长文通常 8–12 条），最多 12 条；每条必须讲的是不同的事，不要同一结论换说法重复。
3) 数字不是结论。实验数字、分数、成本、案例只有在“作者用它证明某个主张”时，才作为依据写进那条主张里，并写清比较对象和条件；孤立的数字、与主张无关的数据一律不收，也不要把某个案例的数字当成普遍结论。
claim 写法：写成一段逻辑连贯、读起来自然的话，像同事口头转述，≤90 字；信息顺序是场景、观点、做法、依据，但不要出现“依据：”“原因：”“场景：”“做法：”等标签，不用分号和冒号堆砌，用“因为”“于是”“结果”等连接词把前后串起来，句子不拗口。内容上要说清：开头用几个字交代“在什么场景、解决什么问题”（如“Agent 长期运行时”“做浏览器自动化时”“评测 Agent 时”），再给观点，再用一两个关键动作说清“具体怎么做到的”（机制或步骤，读者据此判断自己用不用得上），最后给最关键的依据（带数字时写清比较对象）。重点是判断、结论、认知，不是数字。数字只当佐证，最多 1–2 个，并且写成量级感而不是精确值（如“约一万一千个”“数倍”“七成左右”“从三周缩到几天”），不要写小数、百分点差、token 数、日期、样本量、版本号；没有数字也可以，结论本身说清楚比数字重要。写数字时要同时写清靠什么动作取得、取代了原来的什么（如“用仿真取代手写场景和真人试验，一次比较更多方案，每版迭代周期从三周缩到几天”）；原文没讲清怎么做到的，就只写原文给出的机制，不许自己编。观点类没有做法时，说清它为什么成立。读者没看过原文也要看懂。禁止“该”“此”“其”“这个方案”等需要回头找指代的词，工具、方法、数据集第一次出现要写全名。
好例子：“客服 Agent 迭代时，Nubank 上线前先用带不同画像的合成客户做大规模对话仿真，替代手写场景和真人试验，一次就能比较更多提示词和模型组合，于是每个版本的迭代周期从 21 天缩到 4 天。”
好例子：“让 Agent 参与大型代码库开发时，团队禁止了 99% 的注释，因为注释没法强制执行、容易过时，Agent 还会拿它给烂代码找借口，他们改用 lint 来强制约束。”
坏例子：“Agent 反复出错时，把修复做成 lint；依据：规则从 7 条增至 167 条。”（有标签、分号，读着生硬）
坏例子：“注释从 65,824 条降到 1,227 条。”（只有数字，没有观点和原因）
一律不收：奖项荣誉、促销价和折扣、活动日程、公司自夸、导流话术、对未来的空泛展望、单纯罗列功能名、常识和口号。只有产品发布或重大变更改变了读者能做什么或该怎么选时，才收为“变更”，并写清变了什么。
输出严格JSON：{"thesis":"…","units":[{"id":"u1","type":"观点|结论|认知|主张|经验|变更","w":2或3,"claim":"场景+观点+做法+依据，≤90字","key":"同一结论的英文规范表述≤25词，用于跨语言比对","scope":"成立条件/适用场景≤15字，没有写空串","quote":"原文逐字摘录≤40字","source_kind":"实践者|官方|推广|转述"}]}
type：观点=作者对好坏、取舍的看法；结论=作者得出的因果或规律；认知=对某事物如何运作的理解；主张=作者建议该怎么做；经验=亲身做过或踩过的坑及其结果；变更=发布/更新/变动。
source_kind：作者讲亲身做过的=实践者；官方账号发布=官方；带卖货/导流目的=推广；转述他人=转述。
只输出JSON。"""

P_SHORT = """把每条认知压缩成一段连贯自然的话，≤80 字，让读者一眼决策，不出现“依据：”之类的标签，不用分号堆砌。必须依次保留：开头交代场景或问题的几个字、观点、具体怎么做（一两个关键动作）、最有说服力的一个依据；数字最多 1–2 个且写成量级感（约、数倍、上万），重点放在判断和结论上（依据带数字时写清比较对象）；删掉次要细节、修饰语和并列的第二、第三个例子；不许新增原文没有的信息，也不许改变观点的方向。
输入每行“编号 | 原文”。只输出 JSON：{"r":{"编号":"压缩后"}}，每个编号都要有。"""

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

P_EVID = """给你一条认知 C 和若干候选材料（论文、开源项目、产品动态、社区讨论）。逐条严格判断：
佐证=材料内容直接支持 C：论文给出相符的数据或结论；项目实现了 C 说的做法；产品按 C 说的方式做了；讨论里有人给出相符的经验。
反对=材料给出与 C 相反的数据、结论或经验。
无关=其余，包括只是同一话题、同一领域。拿不准一律判无关。
只输出 JSON：{"r":{"编号":{"v":"佐证|反对|无关","why":"依据≤25字"}}}"""

P_NOW = """你为一个“问题”写现状综述，材料只有下面这些认知卡（编号、说法、独立作者数、是否有矛盾）。
写 2–3 句自然连贯的话，总共不超过 150 字，像同事口头汇报：先说多数人的共识，再说分歧或还没验证的地方。不要用分号堆砌，不要罗列做法清单，不要复述卡片原句。
每句话末尾用 [C编号] 标出依据的卡（可多个，只放句末，句中不放编号）；不许写卡片里没有的内容。
不要写具体数字，只说判断和结论，用“明显”“好几倍”“多数”之类的说法。
再给一个状态：共识为主 / 有分歧 / 证据少。
只输出 JSON：{"now":"……[C12]。……[C3][C7]。","status":"共识为主|有分歧|证据少"}"""

P_QSYN = """你在为选题“{topic}”的一个关键问题整理 know how：做过这件事的人总结出来、别人可以照着做或者避开的经验。输入是这个问题下的认知卡，每行“编号 | 说法（适用条件）| 独立作者数 | 来源类型”。
输出两组：
do = 成功做法：被证明有效、可以照做的做法或判断。写清在什么条件下、做什么、效果或依据（有数字就带上，并写清和什么比）。
fail = 失败教训：踩过的坑、做了没用或变差的尝试、看似合理但不成立的做法。写清坑在哪、后果、怎么避免。
要求：
- 只用输入卡片里的信息，不补充事实；每条用 c 列出依据的卡片编号（整数），至少一个。
- 说同一件事的卡合并成一条，引用全部编号；多人印证的、实践者一手的优先。
- do 4–7 条，fail 2–5 条，每条不超过 90 字；输入里没有失败经验就少写，不要把做法改写成反面来凑数。
- 句子像同事口头转述，不用“依据：”之类的标签，不用分号堆砌。
只输出 JSON：{{"do":[{{"t":"……","c":[12,40]}}],"fail":[{{"t":"……","c":[7]}}]}}"""

P_SYN = """你为选题“{topic}”写一份领域 know how 地图的骨架。读者想在十分钟内建立这个领域的体系：它由哪几块组成、做事按什么顺序、团队从手工到成熟分几级、做过的人在哪些地方结论相反、最常见的失败长什么样、哪里还是空白。
输入：每个关键问题的编号、问题、现状、证据状态，以及已整理好的成功做法和失败教训（方括号里是卡片编号）；最后是复核过的矛盾对。
输出 JSON，各字段：
line：一句话总结这个领域的共识、分歧和空白，不超过 150 字；
structure：这个领域由哪几块组成，4–8 块，按从软到硬或从上游到下游排，每块 {{"name":"≤10字","what":"包含什么≤30字","pitfall":"这一块最常见的坑≤30字","q":["相关问题编号"]}}；
flow：做这件事的先后步骤，4–8 步，每步 {{"name":"≤8字","what":"这一步要做对什么≤30字","q":["相关问题编号"]}}；
levels：团队从手工到自动的成熟度，3–5 级，每级 {{"name":"≤10字","how":"这一级怎么做≤30字","needs":"进入这一级的前提≤30字","example":"输入里出现的做法或团队≤30字","risk":"主要风险≤25字"}}；
disputes：做过的人结论相反的地方，3–7 组，每组 {{"t":"分歧点≤16字","a":"一方的做法和理由≤60字","b":"另一方≤60字","cond":"看什么条件选哪边≤50字","c":[依据的卡片编号]}}；
failures：最常见的失败模式，6–12 种，每种 {{"name":"≤12字","looks":"长什么样≤40字","q":["对应问题编号"]}}；
gaps：还没人验证或证据很少的地方，2–5 条，每条不超过 50 字。
要求：只用输入里的信息，不补充事实；问题编号只能用输入里的，卡片编号只能用输入里出现过的；分歧必须是真的结论相反，侧重点不同不算；cond 写你据输入判断的取舍条件。只输出 JSON。"""


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
                usage.record("absorb", usage.from_claude(j), engine="claude")
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


def shorten(r: Run, rows: list[dict], limit: int = 100) -> None:
    long = [u for u in rows if len(u["claim"]) > limit]

    def run(b):
        res = (r.call(r.light, P_SHORT, "\n".join(f"{k} | {u['claim']}" for k, u in enumerate(b))) or {}).get("r", {})
        for k, u in enumerate(b):
            t = str(res.get(str(k)) or "")
            if 0 < len(t) < len(u["claim"]):
                u["claim"] = t
    _pmap(run, [long[i:i + 15] for i in range(0, len(long), 15)], 8)


def s_extract(r: Run) -> list:
    arts = [a for a in r.load("theme.json")["keep"] if (a["q"] or 0) >= r.min_q]

    def run(a):
        text = _ro().execute("select text from x_art where id=?", (a["id"],)).fetchone()[0] or ""
        ex = r.call(r.light, P_EXTRACT, f"标题：{a['title']}\n\n{text[:14000]}")
        units = [u for u in (ex or {}).get("units", []) if isinstance(u, dict) and u.get("w") in (2, 3)]
        return {**a, "thesis": str((ex or {}).get("thesis") or ""), "units": units, "fail": ex is None}
    res = _pmap(run, arts, 10)
    shorten(r, [u for a in res for u in a["units"]])
    return res


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
            units.append({"aid": a["id"], "user": a["user"], "day": a["day"], "q": a["q"], "thesis": a.get("thesis", ""), "w": u["w"],
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
    return {"papers": papers, "repos": repos, "intel": intel, "disc": disc}


def _pool_emb(r: Run, pools: dict) -> np.ndarray:
    return r.embed([x["text"] for k in ("papers", "repos", "intel", "disc") for x in pools[k]], "pool_emb.npy", 160)


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
    return {"C": cards, "conf": conf, "conf_candidates": len(cpl)}


def summarize(r: Run, qs: list, cards: list, sh: list, d: dict) -> dict:
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
    return dict(_pmap(runq, qs, 5))


def s_evidence(r: Run) -> dict:
    qd = r.load("questions.json")
    units, qs = qd["U"], qd["Q"]
    d = r.load("merged.json")
    cards = d["C"]
    pools = r.load("pools.json")
    pe = np.load(r.dir / "pool_emb.npy")
    shown = {c["id"] for c in cards if len(c["authors"]) >= 2} | {x["a"] for x in d["conf"]} | {x["b"] for x in d["conf"]}
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

    return {"shown": sh, "ev": {str(k): v for k, v in evid.items()}, "sum": summarize(r, qs, cards, sh, d)}


def _ids(v, ok: set) -> list[int]:
    out = []
    for x in v or []:
        m = re.search(r"\d+", str(x))
        if m and int(m.group()) in ok and int(m.group()) not in out:
            out.append(int(m.group()))
    return out


def _txt(v, n: int) -> str:
    return str(v or "").strip()[:n]


def _cited(xs, ok: set, n: int) -> list[dict]:
    out = []
    for x in xs or []:
        if isinstance(x, dict) and (t := _txt(x.get("t"), 160)) and (c := _ids(x.get("c"), ok)):
            out.append({"t": t, "c": c})
    return out[:n]


def _rows(xs, keys: tuple, need: str, n: int, qids: set | None = None) -> list[dict]:
    out = []
    for x in xs or []:
        if not isinstance(x, dict) or not _txt(x.get(need), 200):
            continue
        row = {k: _txt(x.get(k), 120) for k in keys}
        if qids is not None:
            row["q"] = [q for q in dict.fromkeys(str(q) for q in x.get("q") or []) if q in qids]
        out.append(row)
    return out[:n]


def s_synth(r: Run) -> dict:
    qd, d, e = r.load("questions.json"), r.load("merged.json"), r.load("evidence.json")
    units, qs, cards = qd["U"], qd["Q"], d["C"]
    shown, now = set(e["shown"]), e.get("sum", {})

    def kinds(c):
        return "、".join(sorted({units[i]["source_kind"] for i in c["members"]} - {""})) or "未知"

    def runq(q):
        cs = sorted((c for c in cards if c["qid"] == q["id"]), reverse=True,
                    key=lambda c: (c["id"] in shown, len(c["authors"]), units[c["rep"]]["source_kind"] in ("实践者", "官方"), c["maxq"], bool(re.search(r"\d", c["claim"]))))[:SYN_CARDS]
        if not cs:
            return q["id"], {"do": [], "fail": []}
        ok = {c["id"] for c in cs}
        o = r.call(r.strong, P_QSYN.format(topic=r.topic), f"关键问题：{q['q']}\n现状：{now.get(q['id'], {}).get('now', '') or '无'}\n\n认知卡：\n"
                   + "\n".join(f"{c['id']} | {c['claim']}（{c['scope'] or '不限'}）| {len(c['authors'])} 位作者 | {kinds(c)}" for c in cs)) or {}
        return q["id"], {"do": _cited(o.get("do"), ok, 8), "fail": _cited(o.get("fail"), ok, 6)}
    per = dict(_pmap(runq, qs, 5))
    qids = {q["id"] for q in qs}
    ok = {i for p in per.values() for k in ("do", "fail") for x in p[k] for i in x["c"]} | {i for x in d["conf"] for i in (x["a"], x["b"])}
    lines = []
    for q in qs:
        s = now.get(q["id"], {})
        lines.append(f"{q['id']} {q['q']}（{s.get('status', '证据少')}）\n现状：{s.get('now', '') or '无'}\n"
                     + "\n".join(f"成功做法：{x['t']} {x['c']}" for x in per[q["id"]]["do"]) + "\n"
                     + "\n".join(f"失败教训：{x['t']} {x['c']}" for x in per[q["id"]]["fail"]))
    conf = [f"[{x['a']}] {cards[x['a']]['claim']} ↔ [{x['b']}] {cards[x['b']]['claim']}（矛盾点：{x['point']}）" for x in d["conf"]]
    g = r.call(r.strong, P_SYN.format(topic=r.topic), "\n\n".join(lines) + "\n\n复核过的矛盾：\n" + ("\n".join(conf) or "无")) or {}
    return {"q": per, "line": _txt(g.get("line"), 300),
            "structure": _rows(g.get("structure"), ("name", "what", "pitfall"), "name", 8, qids),
            "flow": _rows(g.get("flow"), ("name", "what"), "name", 8, qids),
            "levels": _rows(g.get("levels"), ("name", "how", "needs", "example", "risk"), "name", 5),
            "disputes": [{k: _txt(x.get(k), 120) for k in ("t", "a", "b", "cond")} | {"c": c} for x in g.get("disputes") or []
                         if isinstance(x, dict) and _txt(x.get("t"), 120) and (c := _ids(x.get("c"), ok))][:7],
            "failures": _rows(g.get("failures"), ("name", "looks"), "name", 12, qids),
            "gaps": [t for x in g.get("gaps") or [] if (t := _txt(x, 120))][:5]}


def synth_refs(syn: dict, cards: list, units: list, shown: set) -> dict:
    cited = {i for p in syn.get("q", {}).values() for k in ("do", "fail") for x in p.get(k, []) for i in x["c"]} | {i for x in syn.get("disputes", []) for i in x["c"]}
    out = {}
    for i in sorted(cited):
        u = units[cards[i]["rep"]]
        out[str(i)] = {"claim": cards[i]["claim"], "user": u["user"], "url": f"https://x.com/{u['user']}/status/{u['aid']}", "shown": i in shown, "n": len(cards[i]["authors"])}
    return out


def people(units: list, n: int = 12) -> list[dict]:
    by = collections.defaultdict(list)
    for u in units:
        if u["qid"] != "X" and u["source_kind"] in ("实践者", "官方"):
            by[u["user"]].append(u)
    top = sorted(by.items(), key=lambda kv: (-len({u["aid"] for u in kv[1]}), -sum(u["q"] for u in kv[1])))[:n]
    out = []
    for user, us in top:
        best = max(us, key=lambda u: (u["w"], u["q"], len(u["claim"])))
        out.append({"user": user, "arts": len({u["aid"] for u in us}), "units": len(us), "qs": sorted({u["qid"] for u in us}),
                    "best": best["claim"], "url": f"https://x.com/{user}/status/{best['aid']}"})
    return out


TAGS = "chml"


def grade(authors: int, first: int, ev: list, against: int) -> dict:
    n = lambda pools: sum(x["v"] == "佐证" and x["pool"] in pools for x in ev)
    hard, disc = n(("papers", "repos", "intel")), n(("disc",))
    score = min(authors, 3) + (first > 0) + min(hard, 2) + (disc > 0) - 2 * (against > 0)
    return {"level": "h" if score >= 5 else "m" if score >= 3 else "l", "score": score, "authors": authors, "first": first,
            "papers": n(("papers",)), "repos": n(("repos",)), "intel": n(("intel",)), "disc": disc, "against": against}


def s_page(r: Run) -> dict:
    th, qd, d, e, pools = r.load("theme.json"), r.load("questions.json"), r.load("merged.json"), r.load("evidence.json"), r.load("pools.json")
    units, qs, cards = qd["U"], qd["Q"], d["C"]
    links = r.load("compare.json")["J"]
    shown = set(e["shown"])
    cc = collections.defaultdict(list)
    for x in d["conf"]:
        cc[x["a"]].append({"o": x["b"], "point": x["point"], "claim": cards[x["b"]]["claim"]})
        cc[x["b"]].append({"o": x["a"], "point": x["point"], "claim": cards[x["a"]]["claim"]})
    out = []
    for i in e["shown"]:
        c, ev, seen, src = cards[i], sorted(e["ev"].get(str(i), []), key=lambda x: -x["sim"]), set(), []
        for m in c["members"]:
            u = units[m]
            if u["aid"] in seen:
                continue
            seen.add(u["aid"])
            src.append({"user": u["user"], "url": f"https://x.com/{u['user']}/status/{u['aid']}", "day": u["day"], "kind": u["source_kind"],
                        "gain": c["gain"].get(str(m), ""), "claim": u["claim"], "thesis": u["thesis"], "quote": u["quote"]})
        against = len(cc[i]) + sum(x["v"] == "反对" for x in ev)
        g = grade(len(c["authors"]), sum(u["kind"] in ("实践者", "官方") for u in src), ev, against)
        out.append({"id": i, "qid": c["qid"], "type": units[c["rep"]]["type"], "tag": "c" if against else g["level"], "conf": g, "claim": c["claim"], "scope": c["scope"], "authors": c["authors"],
                    "ev": ev, "opp": cc[i], "src": src})
    out.sort(key=lambda c: (TAGS.index(c["tag"]), -c["conf"]["score"], -len(c["ev"])))
    qout = []
    for q in qs:
        cs, sc = [c for c in cards if c["qid"] == q["id"]], [c for c in out if c["qid"] == q["id"]]
        s = e["sum"].get(q["id"], {})
        qout.append({"id": q["id"], "q": q["q"], "scope": q.get("scope", ""), "status": s.get("status", "证据少"), "now": s.get("now", ""),
                     "n_units": sum(u["qid"] == q["id"] for u in units), "n_cards": len(cs), "n_shown": len(sc),
                     "n_multi": sum(len(c["authors"]) >= 2 for c in sc), "n_conf": sum(bool(c["opp"]) for c in sc),
                     "ev": dict(collections.Counter(x["pool"] for c in sc for x in c["ev"])),
                     "fold": [[c["claim"], units[c["rep"]]["user"], units[c["rep"]]["aid"]] for c in sorted(cs, key=lambda c: -c["maxq"]) if c["id"] not in shown]})
    st = r.load("status.json")
    cost = st["cost"]
    meta = {"topic": r.topic, "window": f"{r.start} 至 {r.end}", "cost": round(sum(cost.values()), 2), "scanned": th["scanned"], "theme": len(th["keep"]),
            "extracted": len(r.load("extract.json")), "min_q": r.min_q, "units": len(units), "cards": len(cards), "shown": len(out),
            "multi": sum(len(c["authors"]) >= 2 for c in out), "conf": len(d["conf"]),
            "evcards": sum(bool(c["ev"]) for c in out), "ratio": round(len(units) / max(1, len(out))), "folded": len(cards) - len(out),
            "unassigned": sum(u["qid"] == "X" for u in units), "quote_bad": qd.get("quote_bad", 0), "pairs": len(links),
            "rel": dict(collections.Counter(j["rel"] for j in links)), "tags": dict(collections.Counter(c["tag"] for c in out)),
            "pools": {k: len(v) for k, v in pools.items()}, "evn": {f"{k[0]}:{k[1]}": v for k, v in collections.Counter((x["pool"], x["v"]) for c in out for x in c["ev"]).items()},
            "minutes": round(sum(st["secs"].values()) / 60), "fails": sum(st.get("fails", {}).values())}
    syn = r.load("synth.json") if r.has("synth.json") else None
    return {"meta": meta, "profile": r.load("profile.json"), "questions": qout, "cards": out,
            "synth": syn, "refs": synth_refs(syn, cards, units, shown) if syn else {}, "people": people(units)}


OUT = {"profile": "profile.json", "theme": "theme.json", "extract": "extract.json", "questions": "questions.json", "pools": "pools.json",
       "compare": "compare.json", "cards": "merged.json", "evidence": "evidence.json", "synth": "synth.json", "page": "cards.json"}
FN = {"profile": s_profile, "theme": s_theme, "extract": s_extract, "questions": s_questions, "pools": s_pools,
      "compare": s_compare, "cards": s_cards, "evidence": s_evidence, "synth": s_synth, "page": s_page}
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
| pools.json、pool_emb.npy | 5 准备证据池 | papers 论文、repos 开源项目、intel 产品动态、disc 窗口内讨论；向量顺序同上 |
| compare.json、unit_emb.npy | 6 问题内比对 | 相近认知两两判 重复 / 增益 / 反驳 / 不同；向量顺序同 questions.json 的 U |
| merged.json | 7 合并成卡 | 合并后的卡、复核过的矛盾 |
| evidence.json、shown_emb.npy | 8 挂证据并写现状 | 需要看的卡、每张卡挂上的佐证和反对、各问题的现状 |
| synth.json | 9 综合 know how | 每个问题的成功做法 do 和失败教训 fail（引用卡片编号），领域结构、做事流程、成熟度、分歧、失败模式、空白 |
| cards.json | 10 生成页面数据 | 页面直接用的数据：meta 漏斗数字、questions、cards、synth、refs（地图引用到的卡）、people（该跟的人） |
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
