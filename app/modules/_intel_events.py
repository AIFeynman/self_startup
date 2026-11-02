"""产品雷达的识别层：候选 → 认公司（实体链接）→ 分类 + 跨源去重（DeepSeek，按公司分批）→ 分级（代码规则）→ 解读卡。

纯函数为主；落库在 intel.py。
"""
from __future__ import annotations

import json
import re
from urllib.parse import urlsplit

from . import _intel_snap as snap

# ---------- 实体链接：信息推荐里的条目 → 公司 ----------

HN_MIN_POINTS = 100


def host(url: str) -> str:
    return re.sub(r"^www\.", "", urlsplit(url or "").netloc.lower())


def _host_in(h: str, domains: list[str]) -> bool:
    return any(h == d or h.endswith("." + d) for d in domains)


def alias_re(company: dict) -> re.Pattern | None:
    names = [a for a in (company.get("aliases") or []) + [company.get("name", "")] if a and len(a) >= 3]
    if not names:
        return None
    parts = [re.escape(a) if re.search(r"[一-鿿]", a) else rf"\b{re.escape(a)}\b" for a in sorted(set(names), key=len, reverse=True)]
    return re.compile("|".join(parts), re.I)


def match_feed_item(it: dict, companies: list[dict]) -> tuple[dict | None, bool]:
    """(公司, 是否官方)。官方：公司域名的博客 / 公司 X 账号 / 公司 GitHub 组织 / 公司专属 RSS；
    第三方：HN ≥100 分、其它博客 / 新闻、Product Hunt 里标题命中别名的——只用来并入已有事件。"""
    ex = it.get("extra") or {}
    src, url = it.get("source", ""), it.get("url", "")
    h = host(url)
    for c in companies:
        if src == "twitter":
            author = str(ex.get("author") or "").lower()
            if author and author in {x.lower() for x in c.get("x") or []}:
                return c, True
        elif src == "github":
            m = re.match(r"https?://github\.com/([^/]+)/", url + "/")
            if m and m[1].lower() in {g.lower() for g in c.get("github") or []}:
                return c, True
        elif src == "blog":
            if ex.get("feed_url") and ex["feed_url"] in (c.get("feed_urls") or []):
                return c, True
            if _host_in(h, c.get("domains") or []):
                return c, True
    if src == "hn" and float(it.get("popularity") or 0) < HN_MIN_POINTS:
        return None, False
    if src not in ("hn", "blog", "producthunt", "twitter"):
        return None, False
    if src == "twitter":  # 非官方推文噪声太大，不当第三方佐证
        return None, False
    text = f"{it.get('title', '')}"
    for c in companies:
        rx = alias_re(c)
        if rx and rx.search(text):
            return c, False
    return None, False


# ---------- 分类 + 去重（DeepSeek） ----------

TYPES = {"launch": "新产品", "model": "新模型", "feature": "新功能", "api": "API / 开发者", "pricing": "定价",
         "packaging": "套餐 / 打包", "deprecation": "下线 / 弃用", "funding": "融资", "people": "人事",
         "partnership": "合作", "policy": "政策 / 条款", "research": "研究", "other": "其它",
         "revenue": "收入异动", "listing": "挂牌出售"}  # 后两种来自创业公司收入快照 / 公开报道，不走分类

CLASSIFY_SYSTEM = """你在为一个 AI 产品雷达识别「产品变化事件」。输入 JSON：
- company：公司名；
- events：这家公司最近 7 天已有的事件 [{id: "e12", title, summary, date}]；
- candidates：新收到的候选 [{id: "c34", official: 是否官方来源, source, title, text, date}]。
对每个候选输出一项，返回 {"items": [...]}，每项：
{"id": "c34",
 "is_change": true/false,          // 是不是这家公司产品 / 商业上的真实变化（发布、功能、定价、模型、API、下线、融资、人事、合作、政策）；
                                   // 营销软文、教程、案例故事、招聘、活动预告、纯观点、bug 修复小版本、文档措辞调整 → false
 "merge_into": "e12" 或 "c30" 或 null,  // 和已有事件或本批更早的候选说的是同一件事时填它的 id（跨源去重：官方博客 + X + changelog 同一发布只留一个事件）
 "type": "launch|model|feature|api|pricing|packaging|deprecation|funding|people|partnership|policy|research|other",
 "product": "涉及的具体产品名（如 Claude Code、ChatGPT、Gemini API）",
 "title": "中文标题，≤30 字，说清楚谁做了什么",
 "summary": "中文，≤120 字，只写输入里有的事实",
 "scale": "major | normal | minor"}  // major：新产品 / 新旗舰模型 / 定价大改 / 战略级合作或融资；minor：小改进、小版本；其它 normal
只根据输入判断，不要补充外部事实。"""

BATCH = 15

DEDUP_SYSTEM = """你在给 AI 产品雷达去重。输入 JSON：company；events：这家公司近 7 天的事件 [{id, title, summary, product, date}]；
new：本轮新建的事件 id。找出说的是**同一次发布 / 同一件事**的事件（同一模型 / 产品 / 定价调整被博客、X、changelog、媒体分别报道），
返回 {"groups": [["e12", "e15"], ...]}，每组至少 2 个 id 且至少含一个 new 里的 id。
同一产品的两个不同功能、同一天的两次不同发布不算同一件事；拿不准就不分组。没有就返回 {"groups": []}。"""


def classify(company: dict, events: list[dict], cands: list[dict]) -> tuple[dict[int, dict], list[str]]:
    """{candidate_id: 结果}，errors。按 BATCH 分批，单批失败只记错误、候选留待下轮。"""
    out, errors = {}, []
    evs = [{"id": f"e{e['id']}", "title": e["title"], "summary": (e.get("summary") or "")[:200], "date": (e.get("date") or "")[:10]}
           for e in events][:40]
    for i in range(0, len(cands), BATCH):
        batch = cands[i:i + BATCH]
        payload = {"company": company["name"], "events": evs,
                   "candidates": [{"id": f"c{c['id']}", "official": bool(c.get("official")), "source": c.get("source_label", ""),
                                   "title": c.get("title", "")[:200], "text": (c.get("text") or "")[:snap.BLOCK_MAX],
                                   "date": (c.get("date") or "")[:10]} for c in batch]}
        try:
            res = snap.llm_json(CLASSIFY_SYSTEM, payload, max_tokens=6000)
        except Exception as e:  # noqa: BLE001
            errors.append(f"{company['name']} 第 {i // BATCH + 1} 批：{type(e).__name__}: {str(e)[:160]}")
            continue
        ids = {c["id"] for c in batch}
        for x in res.get("items") or []:
            if not isinstance(x, dict):
                continue
            m = re.fullmatch(r"c?(\d+)", str(x.get("id", "")))
            if m and int(m[1]) in ids:
                out[int(m[1])] = x
        # 本批里已建的事件也给下一批看，便于跨批去重
        evs += [{"id": f"c{k}", "title": v.get("title", ""), "summary": v.get("summary", ""), "date": ""}
                for k, v in out.items() if v.get("is_change") and not v.get("merge_into")]
    return out, errors


# ---------- 分级（确定性规则） ----------

LEVELS = ["S", "A", "B", "C"]


def auto_level(type_: str, scale: str, tier: int) -> str:
    """S：必看、先判断；A：值得解读；B：出解读卡；C：只进时间线。"""
    major, minor = scale == "major", scale == "minor"
    if type_ in ("pricing", "packaging"):
        return "S" if tier == 1 and not minor else "A" if not minor else "B"
    if type_ in ("launch", "model"):
        return "S" if tier == 1 and major else "A" if not minor else "B"
    if type_ in ("funding", "people", "partnership", "policy"):
        return "A" if major else "C" if minor else "B"
    if type_ in ("feature", "api", "deprecation"):
        return "A" if major and tier <= 2 else "B" if not minor else "C"
    return "B" if major else "C"


def needs_card(level: str) -> bool:
    return level in ("S", "A", "B")


# ---------- 解读卡 ----------

SECTIONS = ["变了什么", "用户问题", "产品逻辑", "技术逻辑", "商业逻辑", "所以呢"]

CARD_PROMPT = """你是产品雷达的分析员。为下面这条 AI 产品变化写一张「五层解读卡」，帮我（AI 产品 / 创业者）提升商业战略判断力。

## 事件
- 公司：{company}（{tier_name}，{category}）
- 产品：{product}
- 类型：{type_name} · 级别 {level} · 日期 {date}
- 标题：{title}
- 摘要：{summary}

## 来源（先读这些原文；必要时再联网查官方文档 / 定价页 / 可信媒体补充）
{sources}

## 这家公司最近的其它变化（看连续动作，不要孤立地解读）
{timeline}

## 输出要求
只输出 markdown，**必须**按下面 6 个二级标题、按顺序写，每节 2–6 条要点，中文：

## 变了什么
（具体改了哪些功能 / 价格 / 限制，前后对比；可量化就量化）
## 用户问题
（解决谁的什么痛点、在什么场景、之前怎么凑合的）
## 产品逻辑
（为什么现在做、在产品线里的位置、和竞品同类功能怎么比）
## 技术逻辑
（背后依赖的模型 / 工程能力，实现难点，是否容易被复制）
## 商业逻辑
（怎么赚钱 / 拉留存 / 抢生态，对定价、渠道、竞争格局的影响）
## 所以呢
（对我的启发：1 条可验证的预测（写清楚时间和判断标准）、1 个值得亲手试的点、1 个反方观点）

规则：
- 每条事实后面用 [来源名](链接, YYYY-MM-DD) 标出处和日期；
- 不是来源里直接写的、而是你推出来的，句首标 **【推测】**；
- 查不到的写「未公开」，不要编数字；
- 不要写开场白和总结段落，不要输出这 6 节以外的标题。
"""


def card_prompt(ev: dict, company: dict, timeline: list[dict]) -> str:
    srcs = "\n".join(f"- {'官方' if s.get('official') else '第三方'} · {s.get('label', '')} · {(s.get('date') or '')[:10]} · {s.get('url', '')}"
                     for s in ev.get("sources") or []) or "- （无链接，只有摘要）"
    tl = "\n".join(f"- {(e.get('date') or '')[:10]} [{e['level']}] {e['title']}" for e in timeline if e["id"] != ev["id"])[:3000] or "- 无"
    return CARD_PROMPT.format(company=company["name"], tier_name={1: "T1 大公司 / 头部模型厂", 2: "T2 明星 AI native"}.get(company["tier"], "T3 观察中"),
                              category=company.get("category") or "-", product=ev.get("product") or "-",
                              type_name=TYPES.get(ev.get("type"), ev.get("type") or "-"), level=ev["level"],
                              date=(ev.get("date") or "")[:10], title=ev["title"], summary=ev.get("summary") or "-",
                              sources=srcs, timeline=tl)


def parse_card(text: str) -> tuple[dict[str, str], list[str]]:
    """({节名: 内容}, 缺的节)。容忍「## 1. 变了什么」「## 变了什么（What）」这类写法。"""
    secs: dict[str, str] = {}
    cur, buf = None, []
    for ln in (text or "").splitlines():
        m = re.match(r"^#{2,3}\s*(?:\d+[.、]\s*)?(.+?)\s*$", ln)
        name = next((s for s in SECTIONS if m and m[1].startswith(s)), None) if m else None
        if name:
            if cur:
                secs[cur] = "\n".join(buf).strip()
            cur, buf = name, []
        elif cur:
            buf.append(ln)
    if cur:
        secs[cur] = "\n".join(buf).strip()
    missing = [s for s in SECTIONS if not secs.get(s)]
    return secs, missing


def card_quality(text: str) -> dict:
    """C2 的可检查项：五层（6 节）齐全、有带链接的出处、有日期、推测有标注。"""
    secs, missing = parse_card(text)
    links = re.findall(r"\]\((https?://[^)\s,]+)", text or "")
    dates = re.findall(r"20\d\d-\d\d-\d\d", text or "")
    return {"sections": secs, "missing": missing, "links": len(links), "dates": len(dates),
            "speculation": len(re.findall(r"【推测】", text or "")),
            "complete": not missing and bool(links) and bool(dates)}


def merge_sources(old: list[dict], new: dict) -> list[dict]:
    if any(s.get("url") and s.get("url") == new.get("url") for s in old):
        return old
    return [*old, new]


def dumps(v) -> str:
    return json.dumps(v, ensure_ascii=False)
