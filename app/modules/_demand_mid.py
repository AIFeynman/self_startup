"""产品需求 · 中段：联网发现中型 AI 创业公司（A–C 轮，或年收入 $1M–$100M），按需求卡同样的字段出卡、联网补全、归到现有图谱。
候选存 data/demand/mid.json，不进产品雷达名单。由 _demand_run 的 --mid 调用；规模分档 tier() 也给页面筛选用。"""
from __future__ import annotations

import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from . import _demand_run as dr

SOURCE = "中型 AI 创业公司"
LATE = re.compile(r"series\s*[d-h]\b|\b[d-h]\s*轮|pre-ipo|\bipo\b|上市", re.I)
EARLY = re.compile(r"series\s*[abc]\b|\b[abc]\+?\s*轮", re.I)

QUERIES = [
    "Lean AI leaderboard startups ARR team size 2026",
    "a16z top 100 gen AI consumer apps 2026 list",
    "Forbes AI 50 2026 list startups revenue",
    "AI startup Series A raise 2026 ARR growth",
    "AI startup Series B raise 2026 ARR",
    "AI startup Series C 2026 annual recurring revenue",
    "AI startup hits $10M ARR 2026",
    "AI startup $20M ARR in months 2026",
    "AI startup $50M ARR 2026 fastest growing",
    "Sacra AI startup revenue estimate 2026",
    "Lenny's newsletter fastest growing AI products ARR 2026",
    "AI coding agent startup Series A B ARR 2026",
    "AI video generation startup Series A B revenue 2026",
    "AI voice agent startup Series A B ARR 2026",
    "AI SDR sales agent startup Series A B ARR 2026",
    "AI customer support agent startup Series B ARR 2026",
    "AI legal startup Series A B ARR 2026",
    "AI medical scribe startup Series B ARR 2026",
    "AI tutoring education startup Series A B revenue 2026",
    "AI presentation design startup ARR Series A 2026",
    "AI meeting notes startup ARR Series B 2026",
    "AI marketing content startup Series A ARR 2026",
    "AI finance accounting agent startup Series A B ARR 2026",
    "AI recruiting startup Series A B ARR 2026",
    "AI companion app revenue Series A 2026",
    "AI browser agent startup Series A B 2026",
    "AI search research assistant startup Series A B ARR 2026",
    "AI app builder no-code startup ARR Series A B 2026",
    "AI 创业公司 A 轮 B 轮 融资 2026 年收入",
    "出海 AI 应用 年收入 千万美元 2026 融资",
]

P_DISCOVER = """你是创投研究员。用 WebSearch 按给你的检索方向找「中型 AI 创业公司」：已融到 A、B 或 C 轮，或年收入（ARR）在 $1M–$100M 之间的 AI 产品公司。
不要：大厂和年收入超过 $100M 或已到 D 轮以后的公司、还没融资也没收入的早期项目、只是榜单名字查不到任何信息的公司。
每家只写搜索结果里确有出处的内容，没有就写空串，不许编。一次最多 12 家。
只输出 JSON：{"companies":[{"name":"公司或产品名","website":"官网","one_liner":"一句话做什么，≤40 字","users":"目标用户，≤30 字",
"scenario":"用户在什么场景下用，≤40 字","pain":"解决的痛点，≤60 字","pricing":"怎么收费，≤40 字","growth":"靠什么增长，有出处的做法，≤80 字",
"stage":"融资轮次","funding":"最近一轮：轮次、金额、估值、年月，≤50 字","arr":"收入规模：数字加口径和年月，≤40 字","source_url":"最主要的出处链接"}]}"""

P_PROFILE = """你是产品研究员。用 WebSearch 查这家 AI 公司的官网和公开报道，补齐它的产品画像。只写搜索结果里确有出处的内容，没有就写空串，不许编。
输入 JSON：{"name","已知"}。只输出 JSON：{"website":"","one_liner":"一句话做什么，≤40 字","users":"目标用户，≤30 字","scenario":"用户在什么场景下用，≤40 字",
"pain":"解决的痛点，≤60 字","pricing":"怎么收费，≤40 字","growth":"靠什么增长，有出处的做法，≤80 字","funding":"最近一轮融资，≤50 字","arr":"收入规模，≤40 字","source_url":"最主要的出处"}"""

FIELDS = ("website", "one_liner", "users", "scenario", "pain", "pricing", "growth", "stage", "funding", "arr")


def tier(c: dict) -> str:
    v = c.get("arr_v") or 0
    if v >= 1e8:
        return "large"
    if v >= 1e6:
        return "mid"
    if v > 0:
        return "small"
    f = c.get("funding") or ""
    if LATE.search(f):
        return "large"
    if EARLY.search(f):
        return "mid"
    src = c.get("sources") or []
    if "大公司 / AI native" in src:
        return "large"
    return "mid" if SOURCE in src else "small"


def _is_mid(o: dict) -> bool:
    v = dr.parse_usd(str(o.get("arr") or ""))
    if v >= 1e8:
        return False
    if v >= 1e6:
        return True
    money = f"{o.get('stage') or ''} {o.get('funding') or ''}"
    return bool(EARLY.search(money)) and not LATE.search(money)


def discover(ctx, queries: list[str], known: dict) -> dict:
    found = dr._load("mid.json", {})
    ask = lambda q: ctx.call(ctx.light, P_DISCOVER, json.dumps({"检索方向": q}, ensure_ascii=False), web=True)  # noqa: E731
    with ThreadPoolExecutor(4) as ex:
        answers = list(ex.map(ask, queries))
    for q, o in zip(queries, answers):
        for x in (o or {}).get("companies") or []:
            if not isinstance(x, dict) or not (name := str(x.get("name") or "").strip()) or dr.ANON.search(name):
                continue
            k = dr.norm(name)
            if not k or tier(known.get(k) or {}) == "large" or not _is_mid(x):
                continue
            rec = found.setdefault(k, {"name": name, "found": time.strftime("%Y-%m-%d"), "sources": [], "queries": []})
            rec.update({f: str(x[f]).strip()[:160] for f in FIELDS if str(x.get(f) or "").strip()})
            if (u := str(x.get("source_url") or "").strip()) and u not in rec["sources"]:
                rec["sources"].append(u)
            if q not in rec["queries"]:
                rec["queries"].append(q)
        dr._save("mid.json", found)
    return found


def add_to(P: dict, norm) -> None:
    labels = {"one_liner": "一句话", "users": "目标用户", "scenario": "使用场景", "pain": "痛点", "pricing": "收费",
              "growth": "增长做法", "stage": "融资阶段", "funding": "融资", "arr": "收入规模", "website": "官网"}
    for rec in dr._load("mid.json", {}).values():
        p = P.setdefault(norm(rec["name"]), {"name": rec["name"], "sources": [], "parts": [], "links": [], "track": "", "date": ""})
        if SOURCE not in p["sources"]:
            p["sources"].append(SOURCE)
        p["parts"].append("【中型 AI 创业公司 · 联网检索】\n" + "\n".join(f"{lab}：{rec[k]}" for k, lab in labels.items() if rec.get(k)))
        for link in ([("官网", rec["website"])] if rec.get("website") else []) + [("来源", u) for u in rec.get("sources", [])[:3]]:
            if link not in p["links"]:
                p["links"].append(link)
        if rec.get("found") and (not p["date"] or rec["found"] < p["date"]):
            p["date"] = rec["found"]


def fill_profiles(ctx, keys: list[str]) -> int:
    found = dr._load("mid.json", {})
    todo = [k for k in keys if k in found and not all(found[k].get(f) for f in ("users", "scenario", "pain"))]
    lock = threading.Lock()

    def one(k: str) -> None:
        rec = found[k]
        o = ctx.call(ctx.light, P_PROFILE, json.dumps({"name": rec["name"], "已知": {f: rec[f] for f in FIELDS if rec.get(f)}}, ensure_ascii=False), web=True)
        if not isinstance(o, dict):
            return
        with lock:
            rec.update({f: str(o[f]).strip()[:160] for f in FIELDS if str(o.get(f) or "").strip() and not rec.get(f)})
            if (u := str(o.get("source_url") or "").strip()) and u not in rec["sources"]:
                rec["sources"].append(u)
            dr._save("mid.json", found)
    with ThreadPoolExecutor(6) as ex:
        list(ex.map(one, todo))
    return len(todo)
