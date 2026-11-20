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
MODELS = ["订阅制", "按量付费", "一次性买断", "交易抽佣", "广告变现", "免费增值", "企业销售", "联盟分成", "开源+托管", "未披露"]
SOURCES = ("创业公司", "PH 日榜", "增长 Case", "大公司 / AI native")
ANON = re.compile(r"confidential|anonymous|stealth|unnamed|undisclosed", re.I)
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

P_TAX = """下面每行是一个产品的“编号|场景|痛点”。请建一棵两层分类：第一层「用户场景」（用户在什么大领域里做事，如“育儿与家庭健康”“软件开发”“职场与学习”）{ns} 个，每个给一句话 desc（≤30 字）；第二层「痛点」：该场景下一类用户共同卡住的具体痛点，每个场景 {nb} 个。
痛点名要写成痛点本身，一个短语（≤16 字，如“怕出错不敢开口”“喂辅食怕不安全”“线索响应太慢”），不要写成功能或任务名；pain 用一句话说清为什么痛、现有做法差在哪（≤40 字）。
不同场景的痛点不重叠；不要有“其他”场景，实在放不进的产品后面会单独处理。
只输出 JSON：{{"scenes":[{{"name":"","desc":"","subs":[{{"name":"痛点短语","pain":"为什么痛"}}]}}]}}"""

P_ASSIGN = """把每个产品归入下面分类里最贴的一个痛点。分类（用户场景 / 痛点，编号 S1、S2…）：
{tax}
输入每行“编号|场景|痛点”。只输出 JSON：{{"r":{{"编号":"S编号"}}}}，每个编号都要有；真的一个都不贴就返回 "S0"。"""

P_SUM = """你在为一个用户场景写总结。输入是这个场景下各痛点（编号、名称）及其产品（产品名、增长手段）。
输出两部分：summary：两句话（≤110 字），先说这个场景里大家共同在打什么痛点，再说主要靠什么手段增长；subs：对每个痛点写一句增长方式聚合（≤60 字），概括这个痛点下的产品主要怎么拉到用户，只谈材料里有的，没有增长材料就写空串。不写具体数字。
只输出 JSON：{"summary":"…","subs":{"痛点编号":"…"}}"""


P_DOM = """把下面这些「用户场景」归并成 4–7 个「领域」（更大的一层，如“个人成长与生活”“内容与创作”“获客与增长”“软件与 Agent 开发”“企业运营”），每个场景恰好属于一个领域。
输入每行“编号|场景名|说明”。领域名 ≤10 字，desc 一句话（≤30 字）。
只输出 JSON：{"domains":[{"name":"","desc":"","scenes":["G1","G2"]}]}"""


P_MODEL = """你读一个产品的材料和已抽好的需求卡，写清它怎么赚钱。
model：商业模式一句话（≤40 字）：谁付钱、为什么付、怎么收（订阅 / 按量 / 抽佣 / 买断等），数字只留量级；材料没讲怎么收钱就写“材料未披露收费方式”，不许编。
type：商业模式分类，从固定列表选 1 个，必须逐字一致：{models}。材料没讲收费方式选“未披露”；同时有免费版和付费版选“免费增值”，只有订阅收费选“订阅制”。
输入是 JSON 数组，每个元素 {{"id","name","card","text"}}。只输出 JSON：{{"r":{{"id":{{"model":"","type":""}}}}}}，每个 id 都要有。"""


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
        return P.setdefault(norm(name), {"name": name.strip(), "sources": [], "parts": [], "links": [], "track": "", "date": ""})

    def add(p: dict, src: str, part: str, link: tuple[str, str] | None = None, track: str = "", date: str = "") -> None:
        if date and (not p["date"] or date < p["date"]):
            p["date"] = date[:10]
        if src not in p["sources"]:
            p["sources"].append(src)
        p["parts"].append(part)
        if link and link not in p["links"]:
            p["links"].append(link)
        p["track"] = p["track"] or track

    for r in c.execute("SELECT c.name, c.slug, c.track, c.ext, c.created_at, p.content FROM intel_profile p JOIN intel_company c ON c.id=p.company_id "
                       "WHERE c.kind='startup' AND p.id IN (SELECT MAX(id) FROM intel_profile GROUP BY company_id) AND p.content!=''"):
        ext = json.loads(r["ext"] or "{}")
        slug = ext.get("trustmrr") or r["slug"]
        add(get(r["name"]), "创业公司", "【生意拆解】\n" + r["content"], ("TrustMRR", f"https://trustmrr.com/startup/{slug}"), r["track"], ext.get("listed_at") or r["created_at"] or "")
    had = {norm(r["name"]) for r in c.execute("SELECT c.name FROM intel_profile p JOIN intel_company c ON c.id=p.company_id WHERE p.content!=''")}
    for r in c.execute("SELECT name, slug, track, ext, created_at FROM intel_company WHERE kind='startup' AND enabled=1 AND ai!=0"):
        ext = json.loads(r["ext"] or "{}")
        if norm(r["name"]) in had or ANON.search(r["name"]) or not (ext.get("description") or ext.get("intro_zh")):
            continue
        f = lambda k, lab: f"{lab}：{ext[k]}" if ext.get(k) else ""
        txt = "\n".join(x for x in (f("intro_zh", "一句话"), f("description", "描述")[:760], f("category", "分类"), f("audience", "受众"), f("persona", "用户画像"), f("website", "网站"), f("founded", "成立"), f("country", "国家"), f("payment", "收款渠道")) if x)
        add(get(r["name"]), "创业公司", "【TrustMRR 档案】\n" + txt, ("TrustMRR", f"https://trustmrr.com/startup/{ext.get('trustmrr') or r['slug']}"), r["track"], ext.get("listed_at") or r["created_at"] or "")
    for r in c.execute("SELECT id, name, category, note, created_at FROM intel_company WHERE kind!='startup' AND enabled=1"):
        ev = c.execute("SELECT title, date, summary FROM intel_event WHERE company_id=? AND merged_into IS NULL ORDER BY date DESC LIMIT 8", (r["id"],)).fetchall()
        add(get(r["name"]), "大公司 / AI native", f"【产品雷达】{r['name']}（{r['category']}）{r['note'] or ''}\n" + "\n".join(f"- {e['date']} {e['title']}：{(e['summary'] or '')[:120]}" for e in ev), None, "", r["created_at"] or "")
    for r in c.execute("SELECT g.company, g.content, i.url, i.source, i.date FROM intel_growth_case g JOIN intel_growth_item i ON i.id=g.item_id "
                       "WHERE g.status='done' AND g.content!='' AND g.id IN (SELECT MAX(id) FROM intel_growth_case WHERE status='done' GROUP BY item_id) AND g.company!=''"):
        add(get(r["company"]), "增长 Case", "【增长 Case】\n" + r["content"], (r["source"] or "来源", r["url"]) if r["url"] else None, "", r["date"] or "")
    seen: dict[str, dict] = {}
    for r in c.execute("SELECT date, items FROM intel_ph_day ORDER BY date"):
        for it in json.loads(r["items"] or "[]"):
            if it.get("name"):
                seen[norm(it["name"])] = {**it, "day": r["date"]}
    for k, it in seen.items():
        p = get(it["name"])
        add(p, "PH 日榜", f"【PH {it['day']} 第 {it.get('rank')} 名，{it.get('votes')} 票】\n{it.get('title', '')}\n解读：{it.get('why', '')}\n话题：{'、'.join(it.get('topics') or [])}",
            ("Product Hunt", it.get("url", "")) if it.get("url") else None, it.get("track", ""), it["day"])
    rev: dict[str, dict] = {}
    for r in c.execute("SELECT c.name, m.metric, m.value, m.grade, m.date FROM intel_metric m JOIN intel_company c ON c.id=m.company_id WHERE m.metric IN ('arr','mrr') ORDER BY m.date"):
        rev.setdefault(norm(r["name"]), {})[r["metric"]] = (r["value"], r["grade"], r["date"])
    for k, p in P.items():
        p["rev"] = rev.get(k, {})
        p["text"] = "\n\n".join(p.pop("parts"))[:MAT_CHARS]
        p["rich"] = len(p["text"]) > 1200
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
            "pain": s("pain", 120), "product": s("product", 80), "tactics": tac, "growth": s("growth", 160), "date": p.get("date", "")}
    return card if card["scene"] and card["pain"] else None


def extract(ctx: Ctx, P: dict, only: list[str], max_new: int = 0) -> dict:
    cards = _load("cards.json", {})
    todo = [k for k in (only or P) if k in P and k not in cards]
    if max_new:
        todo = sorted(todo, key=lambda k: P[k]["date"], reverse=True)[:max_new]
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
                if card and (BASE / "graph.json").exists():
                    card["added"] = time.time()
            done[0] += len(b)
            _save("cards.json", cards)
            status(ctx, "extract", done[0], len(todo))

    status(ctx, "extract", 0, len(todo))
    with ThreadPoolExecutor(6) as ex:
        list(ex.map(run, batches))
    for k, v in list(cards.items()):
        if k in P and not v.get("skip"):
            v["sources"], v["links"], v["date"] = P[k]["sources"], P[k]["links"], P[k]["date"]
    _save("cards.json", cards)
    return cards


def fill_model(ctx: Ctx, P: dict, cards: dict) -> None:
    todo = [k for k, v in cards.items() if k in P and not v.get("skip") and not v.get("bm")]
    batches = [[k] for k in todo if P[k]["rich"]] + [t[i:i + 8] for t in [[k for k in todo if not P[k]["rich"]]] for i in range(0, len(t), 8)]
    done = [0]

    def run(b: list[str]) -> None:
        inp = [{"id": k, "name": P[k]["name"], "card": {x: cards[k].get(x) for x in ("user", "scene", "pain", "product", "growth")}, "text": P[k]["text"][:1800]} for k in b]
        o = ctx.call(ctx.light, P_MODEL.format(models="、".join(MODELS)), json.dumps(inp, ensure_ascii=False))
        r = (o or {}).get("r") or {}
        with ctx.lock:
            for k in b:
                x = r.get(k) if isinstance(r.get(k), dict) else None
                if x and x.get("model"):
                    cards[k]["bm"] = str(x["model"]).strip()[:90]
                    cards[k]["bm_type"] = x.get("type") if x.get("type") in MODELS else "未披露"
            done[0] += len(b)
            _save("cards.json", cards)
            status(ctx, "model", done[0], len(todo))

    status(ctx, "model", 0, len(todo))
    with ThreadPoolExecutor(6) as ex:
        list(ex.map(run, batches))


def parse_usd(text: str) -> float:
    """“ARR 约 $50M” / “MRR $55.1k，折合 ARR 约 $661.3k” → 年化美元；MRR 乘 12，取折合后的 ARR。"""
    ms = re.findall(r"(ARR|MRR)?[^$]{0,12}\$\s?([\d,.]+)\s*([kKmMbB]?)", text)
    best = 0.0
    for lab, num, u in ms:
        try:
            v = float(num.replace(",", "").rstrip(".")) * {"": 1, "k": 1e3, "m": 1e6, "b": 1e9}[u.lower()]
        except ValueError:
            continue
        best = max(best, v * (12 if lab == "MRR" and "折合" not in text else 1))
    return best


def usd(v: float) -> str:
    return f"${v / 1e9:.1f}B" if v >= 1e9 else f"${v / 1e6:.1f}M" if v >= 1e6 else f"${v / 1e3:.1f}k" if v >= 1e3 else f"${v:.0f}"


P_ARR = """从每个产品的材料里找它自己的收入规模（ARR、MRR 或年收入）。arr：数字加口径，≤30 字，如“ARR 约 $50M（创始人自述）”“MRR 约 $20k（Stripe 验证）”；只写产品自己的数字，不要写融资额、估值、行业数据；材料里没有明确数字就写空串，不许推算或编。
输入是 JSON 数组 {"id","name","text"}。只输出 JSON：{"r":{"id":"arr 文字或空串"}}，每个 id 都要有。"""


def fill_arr(ctx: Ctx, P: dict, cards: dict) -> None:
    need = []
    for k, v in cards.items():
        if k not in P or v.get("skip"):
            continue
        r = P[k].get("rev", {})
        if "arr" in r:
            v["arr"], v["arr_grade"] = f"ARR 约 {usd(r['arr'][0])}（公开报道 / 自述，{r['arr'][2]}）", "reported"
        elif "mrr" in r and r["mrr"][0] > 0:
            m = r["mrr"][0]
            v["arr"], v["arr_grade"] = f"MRR {usd(m)}，折合 ARR 约 {usd(m * 12)}（TrustMRR 支付渠道验证，{r['mrr'][2]}）", "verified"
        elif "arr" not in v and re.search(r"ARR|MRR|年化|annual recurring|\$\s?\d", P[k]["text"], re.I) and "arr_done" not in v:
            need.append(k)
    batches = [need[i:i + 6] for i in range(0, len(need), 6)]

    def run(b: list[str]) -> None:
        o = ctx.call(ctx.light, P_ARR, json.dumps([{"id": k, "name": P[k]["name"], "text": P[k]["text"]} for k in b], ensure_ascii=False))
        r = (o or {}).get("r") or {}
        with ctx.lock:
            for k in b:
                t = str(r.get(k) or "").strip()[:60]
                cards[k]["arr_done"] = True
                if t:
                    cards[k]["arr"], cards[k]["arr_grade"] = t, "reported"

    for v in cards.values():
        if v.get("arr"):
            v["arr_v"] = parse_usd(v["arr"])
    status(ctx, "arr", 0, len(need))
    with ThreadPoolExecutor(6) as ex:
        list(ex.map(run, batches))
    for v in cards.values():
        if v.get("arr"):
            v["arr_v"] = parse_usd(v["arr"])
    _save("cards.json", cards)


def add_new(ctx: Ctx, graph: dict, cards: dict) -> int:
    """新卡按已有的场景 / 痛点分类归位，不动已有结构。"""
    placed = {k for sc in graph["scenes"] for sb in sc["subs"] for k in sb["products"]} | set(graph.get("unplaced", []))
    new = [k for k, v in cards.items() if not v.get("skip") and k not in placed]
    if not new:
        return 0
    subs = [sb for sc in graph["scenes"] for sb in sc["subs"]]
    txt = []
    for sc in graph["scenes"]:
        txt.append(sc["name"])
        txt.extend(f"  {sb['id']} {sb['name']}：{sb['pain']}" for sb in sc["subs"])
    by = {sb["id"]: sb for sb in subs}
    line = lambda k: f"{k}|{cards[k]['scene']}|{cards[k]['pain'][:40]}"
    status(ctx, "assign", 0, len(new))
    for i in range(0, len(new), 60):
        b = new[i:i + 60]
        o = ctx.call(ctx.light, P_ASSIGN.format(tax="\n".join(txt)), "\n".join(line(k) for k in b))
        for k in b:
            v = ((o or {}).get("r") or {}).get(k)
            (by[v]["products"].append(k) if v in by else graph.setdefault("unplaced", []).append(k))
    graph["n"] = sum(len(sb["products"]) for sb in subs)
    graph["updated"] = time.time()
    _save("graph.json", graph)
    return len(new)


def build_graph(ctx: Ctx, cards: dict) -> dict:
    ok = {k: v for k, v in cards.items() if not v.get("skip")}
    keys = list(ok)
    line = lambda k: f"{k}|{ok[k]['scene']}|{ok[k]['pain'][:40]}"
    status(ctx, "taxonomy", 0, len(keys))
    big = len(keys) > 600
    tax = ctx.call(ctx.strong, P_TAX.format(ns="12–20" if big else "8–14", nb="5–10" if big else "3–8"), "\n".join(line(k) for k in keys))
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
                       "subs": [{"id": a, "name": s["subs"][j]["name"], "pain": s["subs"][j].get("pain", ""), "growth": "", "products": []} for a, j in mine]})
    by_sid = {sb["id"]: sb for sc in scenes for sb in sc["subs"]}
    unplaced = []
    for k in keys:
        (by_sid[assign[k]]["products"].append(k) if assign.get(k) in by_sid else unplaced.append(k))
    for sc in scenes:
        sc["subs"] = [sb for sb in sc["subs"] if sb["products"]]
    scenes = [sc for sc in scenes if sc["subs"]]

    def summ(sc: dict) -> None:
        inp = [{"编号": sb["id"], "痛点": sb["name"], "产品": [{"name": ok[k]["name"], "growth": ok[k]["growth"], "tactics": ok[k]["tactics"]} for k in sb["products"][:12]]} for sb in sc["subs"]]
        o = ctx.call(ctx.light, P_SUM, json.dumps({"场景": sc["name"], "痛点": inp}, ensure_ascii=False))
        sc["summary"] = str((o or {}).get("summary") or "")
        for sb in sc["subs"]:
            sb["growth"] = str(((o or {}).get("subs") or {}).get(sb["id"]) or "")

    status(ctx, "summary", 0, len(scenes))
    with ThreadPoolExecutor(6) as ex:
        list(ex.map(summ, scenes))
    graph = {"updated": time.time(), "n": len(keys), "unplaced": unplaced, "scenes": scenes, "tactics": TACTICS, "models": MODELS}
    group_domains(ctx, graph)
    _save("graph.json", graph)
    return graph


def group_domains(ctx: Ctx, graph: dict) -> None:
    o = ctx.call(ctx.strong, P_DOM, "\n".join(f"{sc['id']}|{sc['name']}|{sc['desc']}" for sc in graph["scenes"]))
    ids = {sc["id"] for sc in graph["scenes"]}
    doms, seen = [], set()
    for i, d in enumerate((o or {}).get("domains") or []):
        mine = [x for x in d.get("scenes", []) if x in ids and x not in seen]
        seen.update(mine)
        if mine:
            doms.append({"id": f"D{i + 1}", "name": str(d.get("name") or "")[:20], "desc": str(d.get("desc") or ""), "scenes": mine})
    rest = [x for x in ids if x not in seen]
    if rest:
        doms.append({"id": "D0", "name": "其他", "desc": "", "scenes": rest})
    graph["domains"] = doms


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--only", action="append", default=[])
    ap.add_argument("--graph-only", action="store_true")
    ap.add_argument("--domains-only", action="store_true")
    ap.add_argument("--rebuild", action="store_true")
    ap.add_argument("--max-new", type=int, default=0)
    a = ap.parse_args()
    ctx = Ctx()
    status(ctx, "start", pid=os.getpid(), error="", finished=False)
    try:
        if a.domains_only:
            g = _load("graph.json", {})
            group_domains(ctx, g)
            _save("graph.json", g)
            return status(ctx, "done", finished=True)
        P = collect()
        only = [norm(x) for x in a.only]
        if a.limit:
            only = (only or sorted(P, key=lambda k: not P[k]["rich"]))[: a.limit]
        cards = _load("cards.json", {}) if a.graph_only else extract(ctx, P, only, a.max_new)
        if not a.graph_only:
            fill_model(ctx, P, cards)
            fill_arr(ctx, P, cards)
        if not only and not a.limit:
            g = _load("graph.json", None)
            if a.graph_only or a.rebuild or not g:
                build_graph(ctx, cards)
            else:
                add_new(ctx, g, cards)
        status(ctx, "done", finished=True)
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        status(ctx, "error", error=str(e)[:300], finished=True)
        raise


if __name__ == "__main__":
    main()
