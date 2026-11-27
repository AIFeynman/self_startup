"""产品需求 · 深度解读：中型和大公司的卡片只有一句话，联网补一份结构化解读——用户痛点（谁在痛、原来怎么凑合、代价、为什么现在）、
商业模式（谁付钱、具体价格、单位经济、怎么扩收）、壁垒（类别 + 为什么难抄，以及薄弱处）、对手差异、关键数字、风险、出处。
结果写在卡片的 deep 字段，页面卡片里展开看。由 _demand_run 的 --deep 和中型公司出卡流程调用。"""
from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor

from . import _demand_mid as mid
from . import _demand_run as dr

MOATS = ["数据飞轮", "工作流嵌入", "分发渠道", "网络效应", "品牌心智", "技术 / 模型", "合规 / 资质", "供给 / 资源", "规模成本"]
TIERS = ("large", "mid")
PARALLEL = 4

P_DEEP = """你是 AI 产品研究分析师，给做 AI 产品的创业者写一家公司的深度解读。用 WebSearch 查它的官网、定价页、融资报道、创始人访谈、客户案例和第三方评测。
读者要的是能拿来判断机会的信息：痛点到底多痛、钱从谁口袋出、凭什么别人抄不走。每段写成意思完整的 1–3 句，有数字写数字、有例子写例子；
“提升效率”“降本增效”“AI 驱动”这类套话不算答案。只写搜索结果里确有出处的内容，查不到的写空串，不许编，不许猜。
输入 JSON：{"name","已知":{...}}。只输出 JSON：
{"pain":{"who":"谁在痛：具体岗位 / 人群 / 公司规模","before":"没有它时怎么凑合：原来的做法、替代品、外包","cost":"痛的代价：耗多少时间、钱、出错或流失，尽量有数字","why_now":"为什么现在能解决：模型能力、成本、监管或行为变化"},
"model":{"payer":"谁付钱、谁在用（可能不是同一个人）","pricing":"具体怎么收：套餐、单价、计费单位、价格区间","unit":"单位经济：客单价 / ACV、毛利、留存、扩张，有就写","expand":"怎么从一个客户收到更多钱"},
"moat":[{"kind":"壁垒类别，从下面列表选，逐字一致：{moats}","detail":"具体是什么、为什么别人难抄"}],
"weak":"壁垒薄弱处：大厂、开源或模型升级能否轻易替代它",
"rivals":[{"name":"主要对手","diff":"和它差在哪"}],
"facts":[{"k":"指标","v":"数字 + 口径 + 年月"}],
"risks":"主要风险",
"sources":["出处链接"]}
moat 1–3 条，rivals 最多 4 个，facts 最多 5 条，sources 最多 6 条。"""

SECTIONS = {"pain": ("who", "before", "cost", "why_now"), "model": ("payer", "pricing", "unit", "expand")}


def todo(cards: dict, tiers: tuple[str, ...] = TIERS) -> list[str]:
    keys = [k for k, c in cards.items() if not c.get("skip") and not c.get("deep") and mid.tier(c) in tiers]
    return sorted(keys, key=lambda k: -(cards[k].get("arr_v") or 0))


def _s(x, n: int) -> str:
    return str(x or "").strip()[:n]


def clean(o: dict) -> dict | None:
    if not isinstance(o, dict):
        return None
    d = {sec: {f: _s((o.get(sec) or {}).get(f) if isinstance(o.get(sec), dict) else "", 240) for f in fs} for sec, fs in SECTIONS.items()}
    d["moat"] = [{"kind": m["kind"], "detail": _s(m.get("detail"), 240)} for m in (o.get("moat") or [])[:3]
                 if isinstance(m, dict) and m.get("kind") in MOATS and _s(m.get("detail"), 240)]
    d["rivals"] = [{"name": _s(r.get("name"), 40), "diff": _s(r.get("diff"), 160)} for r in (o.get("rivals") or [])[:4] if isinstance(r, dict) and _s(r.get("name"), 40)]
    d["facts"] = [{"k": _s(f.get("k"), 30), "v": _s(f.get("v"), 120)} for f in (o.get("facts") or [])[:5] if isinstance(f, dict) and _s(f.get("v"), 120)]
    d["weak"], d["risks"] = _s(o.get("weak"), 240), _s(o.get("risks"), 240)
    d["sources"] = [_s(u, 300) for u in (o.get("sources") or [])[:6] if _s(u, 300).startswith("http")]
    filled = sum(bool(v) for sec in SECTIONS for v in d[sec].values()) + len(d["moat"])
    if not filled:
        return None
    d["date"] = time.strftime("%Y-%m-%d")
    return d


def fill(ctx, cards: dict, keys: list[str], budget: float = 0) -> int:
    """联网写深度解读，并行 PARALLEL 个；budget>0 时花到预算就不再开新的。返回写成的张数。"""
    system = P_DEEP.replace("{moats}", "、".join(MOATS))
    known = ("user", "scene", "pain", "product", "bm", "arr", "funding", "growth")
    done = [0]
    start = ctx.cost

    def one(k: str) -> None:
        if budget and ctx.cost - start >= budget:
            return
        c = cards[k]
        o = ctx.call(ctx.light, system, json.dumps({"name": c["name"], "已知": {f: c[f] for f in known if c.get(f)}}, ensure_ascii=False), web=True)
        d = clean(o)
        with ctx.lock:
            if d:
                c["deep"] = d
                done[0] += 1
                dr._save("cards.json", cards)
            dr.status(ctx, "deep", done[0], len(keys))

    dr.status(ctx, "deep", 0, len(keys))
    if budget:
        for i in range(0, len(keys), PARALLEL):
            if ctx.cost - start >= budget:
                break
            with ThreadPoolExecutor(PARALLEL) as ex:
                list(ex.map(one, keys[i:i + PARALLEL]))
    else:
        with ThreadPoolExecutor(PARALLEL) as ex:
            list(ex.map(one, keys))
    return done[0]
