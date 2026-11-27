"""产品需求 · 关键链路体检：图谱的痛点节点是从收录的产品里归纳出来的，产品没收到的环节（如视频的选题与爆款预估）整段看不见。
这里按「用户完成这件事的完整链路」逐个场景列关键环节，对照已有痛点节点标出覆盖情况；没覆盖的环节加成新的痛点节点（chain=True），
再联网找这一环的 AI 产品（大中小都要），出卡后直接归进这个节点。另有一步查整个场景层面的缺口（如法律、医疗临床），补成新场景。
体检结果存 data/demand/chain.json，页面场景栏顶部的「关键链路」里看。"""
from __future__ import annotations

import json
import time

from . import _demand_mid as mid
from . import _demand_run as dr

SOURCE = "赛道补漏"
REFRESH_DAYS = 30
SCENE_K = 3
MAX_SCENES = 6

P_CHAIN = """你在检查一张「AI 产品需求图谱」有没有漏掉关键赛道。输入是一个用户场景、它下面已有的痛点节点（编号、名称、痛点）和已收录的部分产品。
先按用户完成这件事的完整链路（从起意、准备、制作 / 执行、交付 / 分发，到复盘、变现）列出 6–12 个关键环节，每个环节写这一环 AI 产品在解决什么；
再逐个对照已有痛点节点：已覆盖的写出覆盖它的节点编号；没覆盖、但确实有 AI 产品在做（含知名独立工具和大厂产品）的环节，写成一个新痛点节点。
没有 AI 产品在做的环节不要写成缺口。只输出 JSON：
{"links":[{"name":"环节名，≤10 字","job":"这一环 AI 产品在解决什么，≤40 字","covered":["已覆盖它的节点编号"],
"pain":"没覆盖时才写：这一环用户卡在哪，≤30 字，写法像已有痛点节点","examples":["你确知的代表产品，最多 5 个"],"query":"没覆盖时才写：联网找这类产品的英文检索词，≤12 个词"}]}"""

P_SCENES = """你在检查一张「AI 产品需求图谱」有没有漏掉整块的用户场景。输入是现有的领域和场景。
列出 AI 产品已经形成明显赛道、有多家融过资或有收入的公司，但图谱里完全没有对应场景的方向（如某个行业的专业工作流）。已有场景能装下的不要写。最多 {k} 个。
只输出 JSON：{"scenes":[{"domain":"归到哪个现有领域（逐字一致），都不合适写「行业与专业工作流」","name":"场景名，≤12 字","desc":"一句话，≤30 字","examples":["代表产品，最多 5 个"]}]}"""

P_FIND = mid.P_DISCOVER.replace(
    "用 WebSearch 按给你的检索方向找「中型 AI 创业公司」：已融到 A、B 或 C 轮，或年收入（ARR）在 $1M–$100M 之间的 AI 产品公司。",
    "我们的 AI 产品需求图谱漏了一个赛道环节。用 WebSearch 找正在做这一环的 AI 产品公司，大中小都要：独立小工具、融过资的创业公司、大厂的产品线都算，按影响力排。").replace(
    "不要：大厂和年收入超过 $100M 或已到 D 轮以后的公司、还没融资也没收入的早期项目、只是榜单名字查不到任何信息的公司。",
    "不要：查不到任何信息的名字、和这一环无关的通用 AI 产品、「已收录」里的公司。上市公司或大厂的产品线，stage 写「上市」。").replace("一次最多 12 家。", "一次最多 8 家。")


def _subs_text(sc: dict) -> str:
    return "\n".join(f"{sb['id']} {sb['name']}：{sb.get('pain', '')}" for sb in sc.get("subs") or [])


def _next_id(graph: dict) -> int:
    ids = [int(sb["id"][1:]) for sc in graph["scenes"] for sb in sc.get("subs") or [] if sb.get("id", "")[1:].isdigit()]
    return max(ids, default=0) + 1


def due(graph: dict, store: dict, today: str, k: int = SCENE_K, days: int = REFRESH_DAYS) -> list[str]:
    cut = time.strftime("%Y-%m-%d", time.localtime(time.mktime(time.strptime(today, "%Y-%m-%d")) - days * 86400))
    ids = [i for sc in graph.get("scenes") or [] if (i := sc.get("id")) and (not store.get(i) or store[i].get("date", "") <= cut)]
    return sorted(ids, key=lambda i: (store.get(i) or {}).get("date", ""))[:k]


def audit(ctx, graph: dict, cards: dict, scene_ids: list[str]) -> list[dict]:
    """体检这些场景；没覆盖的环节加成新痛点节点（同名不重复加）。返回要去找公司的缺口。"""
    store = dr._load("chain.json", {})
    gaps = []
    for sc in [s for s in graph["scenes"] if s.get("id") in scene_ids]:
        names = [cards[p]["name"] for sb in sc.get("subs") or [] for p in sb.get("products") or [] if p in cards][:60]
        o = ctx.call(ctx.strong, P_CHAIN, json.dumps({"场景": sc["name"], "说明": sc.get("desc", ""), "痛点节点": _subs_text(sc), "已收录": names}, ensure_ascii=False))
        ids = {sb["id"] for sb in sc.get("subs") or []}
        by_name = {sb["name"]: sb for sb in sc.get("subs") or []}
        links = []
        for x in (o or {}).get("links") or []:
            if not isinstance(x, dict) or not (name := str(x.get("name") or "").strip()[:16]):
                continue
            cov = [i for i in x.get("covered") or [] if i in ids]
            ex = [str(e)[:40] for e in (x.get("examples") or [])[:5] if e]
            sub = cov[0] if cov else ""
            pain = str(x.get("pain") or "").strip()[:60]
            if not sub and pain:
                if name in by_name:
                    sub = by_name[name]["id"]
                else:
                    sub = f"S{_next_id(graph)}"
                    node = {"id": sub, "name": name, "pain": pain, "growth": "", "products": [], "chain": True}
                    sc["subs"].append(node)
                    by_name[name] = node
                    gaps.append({"sub": sub, "scene": sc["name"], "link": name, "query": str(x.get("query") or "")[:120], "examples": ex})
            links.append({"name": name, "job": str(x.get("job") or "")[:60], "sub": sub, "added": bool(sub and sub not in ids), "examples": ex})
        if links:
            store[sc["id"]] = {"date": time.strftime("%Y-%m-%d"), "links": links}
    dr._save("chain.json", store)
    if gaps:
        dr._save("graph.json", graph)
    return gaps


def missing_scenes(ctx, graph: dict, k: int = MAX_SCENES) -> list[str]:
    """查整块缺的场景，补成空场景（痛点节点由随后的 audit 补）。返回新场景编号。"""
    doms = graph.setdefault("domains", [])
    have = {sc["name"] for sc in graph["scenes"]}
    inp = [{"领域": d["name"], "场景": [sc["name"] for sc in graph["scenes"] if sc["id"] in d.get("scenes", [])]} for d in doms]
    o = ctx.call(ctx.strong, P_SCENES.replace("{k}", str(k)), json.dumps(inp, ensure_ascii=False))
    new = []
    for x in ((o or {}).get("scenes") or [])[:k]:
        if not isinstance(x, dict) or not (name := str(x.get("name") or "").strip()[:16]) or name in have:
            continue
        sid = f"G{max([int(s['id'][1:]) for s in graph['scenes'] if s['id'][1:].isdigit()], default=0) + 1}"
        graph["scenes"].append({"id": sid, "name": name, "desc": str(x.get("desc") or "")[:40], "summary": "", "subs": [], "chain": True})
        dn = str(x.get("domain") or "").strip() or "行业与专业工作流"
        d = next((d for d in doms if d["name"] == dn), None)
        if not d:
            d = {"id": f"D{len(doms) + 1}", "name": dn, "desc": "", "scenes": []}
            doms.append(d)
        d["scenes"].append(sid)
        have.add(name)
        new.append(sid)
    store = dr._load("chain.json", {})
    store["_scenes"] = {"date": time.strftime("%Y-%m-%d"), "added": new}
    dr._save("chain.json", store)
    if new:
        dr._save("graph.json", graph)
    return new


def find(ctx, gaps: list[dict], known: dict) -> list[str]:
    """联网找每个缺口环节的公司，写进 mid.json（来源「赛道补漏」、钉到缺口节点）。返回新候选的 key。"""
    if not gaps:
        return []
    before = set(dr._load("mid.json", {}))
    asks = [(f"补漏：{g['scene']} / {g['link']}", P_FIND, {"环节": f"{g['scene']} · {g['link']}", "检索方向": g["query"], "代表产品": g["examples"]}) for g in gaps]
    pin = [{"source": SOURCE, "sub": g["sub"]} for g in gaps]
    found = mid.discover_asks(ctx, asks, known, keep=lambda k, x: k not in known, pin=pin)
    return [k for k in found if k not in before]
