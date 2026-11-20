"""需求图谱流水线：把产品雷达里的创业公司 / PH 日榜 / 增长 Case 逐产品抽成「需求卡」（目标用户、场景、痛点、产品、增长手段），
再按场景大小聚成 大场景 → 子场景 → 产品 的图谱。结果在 data/demand/：cards.json（每个产品一张卡，已抽过的不重跑）、graph.json（页面读这个）。
只读 app.db，不写正式库。

    python -m app.modules._demand_run [--limit N] [--only 产品名] [--graph-only]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import subprocess
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor

from .. import agent, settings
from ..db import DATA_DIR, DB_PATH

BASE = DATA_DIR / "demand"
TACTICS = ["内容 / SEO", "付费投放", "创作者 / 达人", "社区 / UGC", "病毒 / 分享机制", "免费增值 / PLG", "嵌入现有产品 / 集成", "渠道 / 联盟合作", "发布平台 / 媒体", "线下 / 活动", "定价 / 订阅机制"]
SOURCES = ("创业公司", "PH 日榜", "增长 Case")
MAT_CHARS = 2600
STATUS = BASE / "status.json"

P_CARD = """你在为产品雷达做「需求卡」：读一个产品的材料，写清它在为谁、哪个具体场景、解决什么痛点，以及怎么增长。读者是做 AI 产品的创业者，想一眼看懂大家在打什么痛点、怎么拉到用户。
只根据材料写，材料没讲的字段写空串或空数组，不许编；增长手段尤其如此，PH 简介一般没讲增长，就返回空。
字段：
user：目标用户，具体到人群和处境（≤30 字，如“正在给宝宝添加辅食的父母”）。
scene：用户在什么时刻想到用它，写成用户心里那句话（≤30 字，如“这个能不能给宝宝吃、怎么切”）。
pain：痛点及为什么痛（决策成本、焦虑、效率、成本等，≤60 字），不是功能罗列。
product：产品是什么、怎么解决（≤40 字）。
tactics：增长核心手段的类别，从下面固定列表选 0–3 个，必须逐字一致：{tactics}
growth：增长核心手段的具体做法和依据（≤80 字，一两句连贯的话，数字只留量级，写清动作和结果；材料没讲就空串）。
输入是 JSON 数组，每个元素 {{"id","name","sources","text"}}。只输出 JSON：{{"cards":[{{"id":..,"user":"","scene":"","pain":"","product":"","tactics":[],"growth":""}}]}}，每个 id 都要有。"""

P_TAX = """下面每行是一个产品的“编号|场景|痛点”。请按场景大小建一棵两层分类：大场景（人在什么大领域里做事，如“育儿与家庭健康”“软件开发”“职场与学习”）8–14 个，每个大场景下 3–8 个子场景（具体到“一类决策或任务”，如“给宝宝加辅食的安全决策”）。
要求：大场景之间不重叠；子场景名用一个短语（≤14 字）；每个大场景给一句话 desc（≤30 字）；不要有“其他”大场景，实在放不进的产品后面会单独处理。
只输出 JSON：{"scenes":[{"name":"","desc":"","subs":[{"name":"","pain":"这个子场景里大家共同在打的痛点，≤40 字"}]}]}"""

P_ASSIGN = """把每个产品归入下面分类里最贴的一个子场景。分类（大场景/子场景，编号 S1、S2…）：
{tax}
输入每行“编号|场景|痛点”。只输出 JSON：{{"r":{{"编号":"S编号"}}}}，每个编号都要有；真的一个都不贴就返回 "S0"。"""

P_SUM = """你在为一个大场景写总结。输入是这个大场景下各子场景的产品（产品名、痛点、增长手段）。
写两句话（总共≤110 字）：第一句说这个大场景里大家共同在打什么痛点；第二句说大家主要靠什么手段增长（只谈材料里有的，样本少或没讲增长就如实说“增长打法材料较少”）。不写具体数字。
只输出 JSON：{"痛点增长":"…"}"""


def _ro() -> sqlite3.Connection:
    c = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    return c


def norm(name: str) -> str:
    return re.sub(r"[^0-9a-z一-鿿]+", "", name.lower())


def collect() -> dict[str, dict]:
    """key（产品名规范化）→ {name, sources, text, links, track, ...}；三个来源同一产品合并成一条。"""
    c = _ro()
    P: dict[str, dict] = {}

    def get(name: str) -> dict:
        return P.setdefault(norm(name), {"name": name.strip(), "sources": [], "parts": [], "links": [], "track": ""})

    def add(p: dict, src: str, part: str, link: tuple[str, str] | None = None, track: str = "") -> None:
        if src not in p["sources"]:
            p["sources"].append(src)
        p["parts"].append(part)
        if link and link not in p["links"]:
            p["links"].append(link)
        p["track"] = p["track"] or track

    for r in c.execute("SELECT c.name, c.slug, c.track, c.ext, p.content FROM intel_profile p JOIN intel_company c ON c.id=p.company_id "
                       "WHERE c.kind='startup' AND p.id IN (SELECT MAX(id) FROM intel_profile GROUP BY company_id) AND p.content!=''"):
        ext = json.loads(r["ext"] or "{}")
        slug = ext.get("trustmrr") or r["slug"]
        add(get(r["name"]), "创业公司", "【生意拆解】\n" + r["content"], ("TrustMRR", f"https://trustmrr.com/startup/{slug}"), r["track"])
    for r in c.execute("SELECT g.company, g.content, i.url, i.source, i.date FROM intel_growth_case g JOIN intel_growth_item i ON i.id=g.item_id "
                       "WHERE g.status='done' AND g.content!='' AND g.id IN (SELECT MAX(id) FROM intel_growth_case WHERE status='done' GROUP BY item_id) AND g.company!=''"):
        add(get(r["company"]), "增长 Case", "【增长 Case】\n" + r["content"], (r["source"] or "来源", r["url"]) if r["url"] else None)
    seen: dict[str, dict] = {}
    for r in c.execute("SELECT date, items FROM intel_ph_day ORDER BY date"):
        for it in json.loads(r["items"] or "[]"):
            if it.get("name"):
                seen[norm(it["name"])] = {**it, "day": r["date"]}
    for k, it in seen.items():
        p = get(it["name"])
        add(p, "PH 日榜", f"【PH {it['day']} 第 {it.get('rank')} 名，{it.get('votes')} 票】\n{it.get('title', '')}\n解读：{it.get('why', '')}\n话题：{'、'.join(it.get('topics') or [])}",
            ("Product Hunt", it.get("url", "")) if it.get("url") else None, it.get("track", ""))
    for k, p in P.items():
        p["text"] = "\n\n".join(p.pop("parts"))[:MAT_CHARS]
        p["rich"] = any(s != "PH 日榜" for s in p["sources"])
    return P


def models() -> tuple[str, str]:
    return agent.tier_model("light") or "claude-haiku-5-5", settings.get("absorb.strong_model") or "claude-opus-5-5"


class Ctx:
    def __init__(self) -> None:
        BASE.mkdir(parents=True, exist_ok=True)
        self.light, self.strong = models()
        self.cost = 0.0
        self.fails = 0
        self.lock = threading.Lock()

    def call(self, model: str, system: str, user: str):
        cmd = [settings.get("engines.claude.bin", "claude"), "-p", "--model", model, "--output-format", "json", "--tools", "",
               "--system-prompt", system, "--settings", json.dumps({"disableAllHooks": True})]
        for _ in range(3):
            try:
                p = subprocess.run(cmd, input=user, capture_output=True, text=True, timeout=900, env=agent.clean_env(), cwd=str(BASE))
                j = json.loads(p.stdout)
                with self.lock:
                    self.cost += float(j.get("total_cost_usd") or 0)
                return json.loads(re.search(r"\{.*\}", (j.get("result") or "").strip(), re.S).group(0))
            except Exception:  # noqa: BLE001
                continue
        with self.lock:
            self.fails += 1
        return None


def _save(name: str, obj) -> None:
    tmp = BASE / (name + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False), "utf-8")
    tmp.replace(BASE / name)


def _load(name: str, default):
    try:
        return json.loads((BASE / name).read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def status(ctx: Ctx, stage: str, done: int = 0, total: int = 0, **kw) -> None:
    _save("status.json", {**_load("status.json", {}), "stage": stage, "done": done, "total": total, "cost": round(ctx.cost, 2), "fails": ctx.fails, "updated": time.time(), **kw})


def _clean(o: dict, p: dict) -> dict | None:
    if not isinstance(o, dict):
        return None
    s = lambda k, n: str(o.get(k) or "").strip()[:n]
    tac = [t for t in (o.get("tactics") or []) if t in TACTICS][:3]
    card = {"name": p["name"], "sources": p["sources"], "links": p["links"], "track": p["track"], "user": s("user", 60), "scene": s("scene", 60),
            "pain": s("pain", 120), "product": s("product", 80), "tactics": tac, "growth": s("growth", 160)}
    return card if card["scene"] and card["pain"] else None


def extract(ctx: Ctx, P: dict, only: list[str]) -> dict:
    cards = _load("cards.json", {})
    todo = [k for k in (only or P) if k in P and k not in cards]
    rich = [k for k in todo if P[k]["rich"]]
    thin = [k for k in todo if not P[k]["rich"]]
    batches = [[k] for k in rich] + [thin[i:i + 8] for i in range(0, len(thin), 8)]
    done = [0]

    def run(b: list[str]) -> None:
        inp = [{"id": k, "name": P[k]["name"], "sources": P[k]["sources"], "text": P[k]["text"]} for k in b]
        o = ctx.call(ctx.light, P_CARD.format(tactics="、".join(TACTICS)), json.dumps(inp, ensure_ascii=False))
        got = {str(x.get("id")): x for x in (o or {}).get("cards", []) if isinstance(x, dict)}
        with ctx.lock:
            for k in b:
                card = _clean(got.get(k), P[k]) if k in got else None
                cards[k] = card or {"name": P[k]["name"], "sources": P[k]["sources"], "skip": True}
            done[0] += len(b)
            _save("cards.json", cards)
            status(ctx, "extract", done[0], len(todo))

    status(ctx, "extract", 0, len(todo))
    with ThreadPoolExecutor(6) as ex:
        list(ex.map(run, batches))
    for k, v in list(cards.items()):
        if k in P and not v.get("skip"):
            v["sources"], v["links"] = P[k]["sources"], P[k]["links"]
    _save("cards.json", cards)
    return cards


def build_graph(ctx: Ctx, cards: dict) -> dict:
    ok = {k: v for k, v in cards.items() if not v.get("skip")}
    keys = list(ok)
    line = lambda k: f"{k}|{ok[k]['scene']}|{ok[k]['pain'][:40]}"
    status(ctx, "taxonomy", 0, len(keys))
    tax = ctx.call(ctx.strong, P_TAX, "\n".join(line(k) for k in keys))
    if not tax or not tax.get("scenes"):
        raise RuntimeError("建场景分类失败：模型没有返回结果")
    subs: list[tuple[str, int, int]] = []
    txt = []
    for i, s in enumerate(tax["scenes"]):
        txt.append(f"{s['name']}")
        for j, sub in enumerate(s["subs"]):
            subs.append((f"S{len(subs) + 1}", i, j))
            txt.append(f"  S{len(subs)} {sub['name']}：{sub.get('pain', '')}")
    sid = {a: (i, j) for a, i, j in subs}
    assign: dict[str, str] = {}
    batches = [keys[i:i + 60] for i in range(0, len(keys), 60)]

    def run(b: list[str]) -> None:
        o = ctx.call(ctx.light, P_ASSIGN.format(tax="\n".join(txt)), "\n".join(line(k) for k in b))
        for k, v in ((o or {}).get("r") or {}).items():
            if k in ok and v in sid:
                assign[k] = v

    status(ctx, "assign", 0, len(keys))
    with ThreadPoolExecutor(6) as ex:
        list(ex.map(run, batches))
    scenes = []
    for i, s in enumerate(tax["scenes"]):
        mine = [(a, j) for a, i2, j in subs if i2 == i]
        scenes.append({"id": f"G{i + 1}", "name": s["name"], "desc": s.get("desc", ""), "summary": "",
                       "subs": [{"id": a, "name": s["subs"][j]["name"], "pain": s["subs"][j].get("pain", ""), "products": []} for a, j in mine]})
    by_sid = {sb["id"]: sb for sc in scenes for sb in sc["subs"]}
    unplaced = []
    for k in keys:
        (by_sid[assign[k]]["products"].append(k) if assign.get(k) in by_sid else unplaced.append(k))
    for sc in scenes:
        sc["subs"] = [sb for sb in sc["subs"] if sb["products"]]
    scenes = [sc for sc in scenes if sc["subs"]]

    def summ(sc: dict) -> None:
        inp = [{"子场景": sb["name"], "痛点": sb["pain"], "产品": [{"name": ok[k]["name"], "growth": ok[k]["growth"], "tactics": ok[k]["tactics"]} for k in sb["products"][:12]]} for sb in sc["subs"]]
        o = ctx.call(ctx.light, P_SUM, json.dumps({"大场景": sc["name"], "子场景": inp}, ensure_ascii=False))
        sc["summary"] = str((o or {}).get("痛点增长") or "")

    status(ctx, "summary", 0, len(scenes))
    with ThreadPoolExecutor(6) as ex:
        list(ex.map(summ, scenes))
    graph = {"updated": time.time(), "n": len(keys), "unplaced": unplaced, "scenes": scenes, "tactics": TACTICS}
    _save("graph.json", graph)
    return graph


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--only", action="append", default=[])
    ap.add_argument("--graph-only", action="store_true")
    a = ap.parse_args()
    ctx = Ctx()
    status(ctx, "start", pid=os.getpid(), error="", finished=False)
    try:
        P = collect()
        only = [norm(x) for x in a.only]
        if a.limit:
            only = (only or sorted(P, key=lambda k: not P[k]["rich"]))[: a.limit]
        cards = _load("cards.json", {}) if a.graph_only else extract(ctx, P, only)
        if not only and not a.limit:
            build_graph(ctx, cards)
        status(ctx, "done", finished=True)
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        status(ctx, "error", error=str(e)[:300], finished=True)
        raise


if __name__ == "__main__":
    main()
