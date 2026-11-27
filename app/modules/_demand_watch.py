"""产品需求 · 持续更新（每周一次，跟在每天的同步后面）：
1. 找新来源：联网找发布 AI 创业公司收入 / 融资 / 增长数据的新榜单、追踪站、报告，新来源变成检索方向；
2. 融资新闻线索：信息推荐里最近的融资新闻，库里没有的公司去查；
3. 查漏：中型公司少的场景，带着已收录名单去找漏掉的；
4. 老检索方向超过 14 天重跑；
5. 关键链路体检：每周轮 3 个最久没查的场景，缺的环节补成新痛点节点并去找公司（见 _demand_chain）。
每周有预算上限：找公司最多用预算的 6 成，剩下留给找到的公司出卡和联网补全；结果记在 watch_log.json，页面「持续更新」里看。"""
from __future__ import annotations

import json
import re
from datetime import date, timedelta
from urllib.parse import urlsplit

from . import _demand_mid as mid
from . import _demand_run as dr

REFRESH_DAYS = 14
QUERY_K = 8
GAP_K = 4
MIN_MID = 5
LOG_KEEP = 20
DISCOVER_SHARE = 0.6
FUNDING = re.compile(r"\braise[sd]?\b|series\s*[abc]\b|\b[abc]\+?\s*轮|融资|funding round", re.I)
KNOWN_SOURCES = ["Lean AI 榜", "a16z Top 100 Gen AI", "Forbes AI 50", "Sacra", "Lenny's Newsletter", "TrustMRR", "Product Hunt", "AICPB"]

P_SOURCES = """你是创投研究员。用 WebSearch 找「持续发布 AI 创业公司收入、融资或增长数据」的来源：榜单、收入追踪站、VC 年度报告、数据库、newsletter、播客栏目等。
只要能用来发现中型 AI 创业公司（A–C 轮或年收入 $1M–$100M）的来源；已知来源不要重复。没有新的就返回空数组，不许编。
输入 JSON：{"已知来源": [...]}。只输出 JSON：{"sources":[{"name":"来源名","url":"链接","kind":"榜单 / 追踪站 / 报告 / 数据库 / newsletter","query":"用这个来源找中型 AI 创业公司时的英文检索词，≤12 个词"}]}"""

P_LEADS = mid.P_DISCOVER.replace("用 WebSearch 按给你的检索方向找「中型 AI 创业公司」", "下面是最近的新闻标题。挑出其中 AI 创业公司的融资（A、B、C 轮），用 WebSearch 核实并查清这家公司，按「中型 AI 创业公司」").replace(
    "一次最多 12 家。", "不是 AI 创业公司融资的标题跳过。")

P_GAP = mid.P_DISCOVER.replace("用 WebSearch 按给你的检索方向找「中型 AI 创业公司」", "我们在整理某个用户场景下的 AI 产品，怕有遗漏。用 WebSearch 找这个场景里值得关注、但不在「已收录」名单里的「中型 AI 创业公司」").replace(
    "一次最多 12 家。", "已收录名单里的公司不要再给。一次最多 10 家。")


def query_pool(sources: dict) -> list[str]:
    extra = [s["query"] for s in sources.values() if s.get("query")]
    return mid.QUERIES + [q for q in extra if q not in mid.QUERIES]


def stale(pool: list[str], runs: dict, today: date, days: int = REFRESH_DAYS, k: int = QUERY_K) -> list[str]:
    cut = (today - timedelta(days=days)).isoformat()
    due = [q for q in pool if not runs.get(q) or runs[q] <= cut]
    return sorted(due, key=lambda q: runs.get(q, ""))[:k]


def leads(titles: list[str], known: set[str], limit: int = 20) -> list[str]:
    names = [n for n in known if len(n) >= 4]
    out = []
    for t in titles:
        nt = dr.norm(t)
        if FUNDING.search(t) and not any(n in nt for n in names) and t not in out:
            out.append(t)
    return out[:limit]


def thin(graph: dict, cards: dict, k: int = GAP_K, min_mid: int = MIN_MID) -> list[dict]:
    out = []
    for sc in graph.get("scenes") or []:
        keys = [p for sb in sc.get("subs") or [] for p in sb.get("products") or [] if p in cards]
        n = sum(mid.tier(cards[p]) == "mid" for p in keys)
        if n < min_mid:
            out.append((n, {"scene": sc["name"], "known": [cards[p]["name"] for p in keys][:80]}))
    return [g for _, g in sorted(out, key=lambda x: x[0])][:k]


def merge_sources(store: dict, got: list, today: str) -> list[str]:
    new = []
    for s in got or []:
        if not isinstance(s, dict) or not (url := str(s.get("url") or "").strip()):
            continue
        dom = urlsplit(url if "//" in url else "https://" + url).netloc.lower().removeprefix("www.")
        if not dom or dom in store:
            continue
        store[dom] = {"name": str(s.get("name") or dom)[:60], "url": url, "kind": str(s.get("kind") or "")[:20],
                      "query": str(s.get("query") or "").strip()[:120], "found": today}
        new.append(dom)
    return new


def _headlines(days: int = 8) -> list[str]:
    c = dr._ro()
    try:
        return [r["title"] for r in c.execute("SELECT title FROM feed_items WHERE fetched_at >= ? ORDER BY fetched_at DESC LIMIT 2000",
                                              [(date.today() - timedelta(days=days)).isoformat()])]
    except Exception:  # noqa: BLE001  信息推荐表还没建：没有线索
        return []
    finally:
        c.close()


def process(ctx, keys: list[str]) -> None:
    dr.process_mid(ctx, keys)


def run_watch(ctx, budget: float) -> dict:
    today = date.today()
    cards = dr._load("cards.json", {})
    graph = dr._load("graph.json", {}) or {}
    before = set(dr._load("mid.json", {}))
    store = dr._load("sources.json", {})
    log = {"date": today.isoformat(), "new_sources": [], "leads": 0, "gaps": [], "queries": [], "new": [], "stopped": ""}

    o = ctx.call(ctx.light, P_SOURCES, json.dumps({"已知来源": KNOWN_SOURCES + [s["name"] for s in store.values()]}, ensure_ascii=False), web=True)
    log["new_sources"] = merge_sources(store, (o or {}).get("sources") or [], today.isoformat())
    dr._save("sources.json", store)

    asks = []
    titles = leads(_headlines(), set(cards) | before)
    if titles:
        asks.append(("融资新闻", P_LEADS, {"新闻标题": titles}))
        log["leads"] = len(titles)
    gaps = thin(graph, cards)
    asks += [(f"查漏：{g['scene']}", P_GAP, {"场景": g["scene"], "已收录": g["known"]}) for g in gaps]
    runs = dr._load("mid_queries.json", {})
    asks += [(q, mid.P_DISCOVER, {"检索方向": q}) for q in stale(query_pool(store), runs, today)]

    for i in range(0, len(asks), 4):
        if ctx.cost >= budget * DISCOVER_SHARE:
            log["stopped"] = "budget"
            break
        chunk = asks[i:i + 4]
        mid.discover_asks(ctx, chunk, cards)
        for label, system, _ in chunk:
            if system is mid.P_DISCOVER:
                runs[label] = today.isoformat()
                log["queries"].append(label)
            elif system is P_GAP:
                log["gaps"].append(label.removeprefix("查漏："))
        dr._save("mid_queries.json", runs)

    from . import _demand_chain as chain
    gaps = chain.audit(ctx, graph, cards, chain.due(graph, dr._load("chain.json", {}), today.isoformat())) if graph.get("scenes") else []
    log["chain"] = [g["link"] for g in gaps]
    pinned = chain.find(ctx, gaps, cards) if gaps and ctx.cost < budget * DISCOVER_SHARE else []

    found = dr._load("mid.json", {})
    new = [k for k in found if k not in before]
    log["new"] = [found[k]["name"] for k in new]
    if new or pinned:
        process(ctx, list(dict.fromkeys(new + pinned)))
    log["cost"] = round(ctx.cost, 2)
    dr._save("watch_log.json", (dr._load("watch_log.json", []) + [log])[-LOG_KEEP:])
    return log
