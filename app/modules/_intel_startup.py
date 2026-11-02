"""产品雷达 · 创业公司：TrustMRR 收入快照 → 指标 → 收入异动；赛道归类；生意拆解卡；Product Hunt 日榜解读；公开 ARR 抽取。

纯函数为主（抓取 / 解析 / 规则 / 提示词）；落库和调度在 intel.py。设计稿：docs/designs/2026-11-01-startup-intel-design.md。
收入口径：TrustMRR 的数字经支付渠道验证 → grade=verified；新闻 / 推文里公司自己说的 ARR → grade=reported，两种分开显示、不混算。
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor

import httpx

from . import _intel_snap as snap
from ._feed_sources import AI_HINT_RE, BROWSER_UA, TRUSTMRR, rsc_objects

# ---------- 赛道（固定 16 个；页面上可改公司归属） ----------

TRACKS = [
    ("coding", "编码 Agent / AI 编程工具", "代码补全、编码 Agent、AI IDE、代码审查、测试生成"),
    ("design", "设计与 UI 生成", "UI / 网页 / 原型生成、设计稿、Logo、室内 / 建筑设计"),
    ("image", "图像生成", "文生图、修图、头像、商品图、照片增强"),
    ("video", "视频生成与剪辑", "文生视频、数字人、口型同步、剪辑、字幕、短视频"),
    ("audio", "语音 / 音乐", "TTS、语音克隆、转写、播客、音乐生成"),
    ("writing", "写作与内容", "写作助手、SEO 文章、改写、简历、文案"),
    ("social", "社媒运营与营销", "社媒排期、增长、广告、SEO / AEO、网红营销"),
    ("sales", "销售与 GTM", "线索挖掘、外联、CRM、LinkedIn 自动化、销售助理"),
    ("support", "客服与对话", "客服机器人、聊天组件、电话 Agent、工单"),
    ("agent", "通用 Agent / 自动化", "通用 Agent、工作流自动化、浏览器 Agent、RPA"),
    ("knowledge", "知识与研究", "搜索、文档问答、笔记、研究助手、会议纪要"),
    ("education", "教育与学习", "学习 / 刷题 / 语言学习、课程、辅导"),
    ("ecommerce", "电商工具", "店铺运营、商品上架、选品、电商广告"),
    ("devinfra", "开发者基础设施", "LLM 网关、API、模型托管、可观测性、向量库、MCP"),
    ("vertical", "垂直行业", "法律、医疗、金融、地产、合规、招聘等行业 AI"),
    ("consumer", "消费娱乐", "陪伴、占卜、社交、游戏、健身、生活方式"),
]
TRACK_NAMES = {s: n for s, n, _ in TRACKS}

# ---------- TrustMRR 抓取 ----------

AI_CATEGORY = re.compile(r"artificial intelligence|^ai$", re.I)
BOARD_PAGES = ("/", "/category/ai", "/acquire")   # 首页：收入最高的几百家（含 MRR / 增长）；AI 分类页；在售列表
# 其它分类页各给收入最高的 30 家：营销 / 销售 / 内容等分类里也有不少 AI 产品（不翻页，?page= 无效）
CATEGORY_SLUGS = ("saas", "developer-tools", "fintech", "marketing", "ecommerce", "productivity", "design-tools", "no-code",
                  "analytics", "crypto-web3", "education", "health-fitness", "social-media", "content-creation", "sales",
                  "customer-support", "recruiting", "real-estate", "travel", "legal", "security", "iot-hardware", "green-tech",
                  "entertainment", "games", "community", "news-magazines", "utilities", "marketplace", "mobile-apps")
API_URL = TRUSTMRR + "/api/v1/startups"
API_MAX_PAGES = 1500  # 每页最多 10 家；AI 分类约 4–5k 家，有收入的更少


def _client() -> httpx.Client:
    return httpx.Client(timeout=30, follow_redirects=True, headers={"User-Agent": BROWSER_UA})


def parse_board(pages: dict[str, str]) -> dict[str, dict]:
    """{路径: html} → {slug: 合并后的对象}。只要有收入、非隐身的；ai_hint：名字 / 描述 / 分类像 AI 产品。"""
    out: dict[str, dict] = {}
    for path, html in pages.items():
        for o in rsc_objects(html):
            cur = out.setdefault(o["slug"], {})
            cur.update({k: v for k, v in o.items() if v is not None})
            if path == "/category/ai":
                cur["_ai_cat"] = True
    keep = {}
    for slug, o in out.items():
        if o.get("stealthMode") or not (o.get("currentLast30DaysRevenue") or o.get("currentMrr") or 0) > 0:
            continue
        o["_ai_hint"] = bool(o.get("_ai_cat") or AI_CATEGORY.search(o.get("userCategory") or "")
                             or AI_HINT_RE.search(f"{o.get('name', '')} {o.get('description', '')}"))
        keep[slug] = o
    return keep


def api_object(x: dict) -> dict:
    """官方 API 的一条（金额是美分）→ 和页面里解析出来的对象同形（美元、同字段名），后面的逻辑不用分两套。"""
    rev = x.get("revenue") or {}

    def usd_(v):
        f = _num(v)
        return None if f is None else f / 100
    o = {"slug": x.get("slug"), "name": x.get("name"), "description": x.get("description"), "website": x.get("website"),
         "currentMrr": usd_(rev.get("mrr")), "currentLast30DaysRevenue": usd_(rev.get("last30Days")),
         "currentTotalRevenue": usd_(rev.get("total")), "cachedGrowth30d": x.get("growth30d"),
         "cachedGrowthMRR30d": x.get("growthMRR30d"), "currentActiveSubscriptions": x.get("activeSubscriptions"),
         "askingPrice": usd_(x.get("askingPrice")), "onSale": x.get("onSale"), "firstListedForSaleAt": x.get("firstListedForSaleAt"),
         "xHandle": x.get("xHandle"), "country": x.get("country"), "targetAudience": x.get("targetAudience"),
         "paymentProvider": x.get("paymentProvider"), "userCategory": x.get("category")}  # 展示名（Sales / Mobile Apps…）；是否 AI 看请求的 category
    return {k: v for k, v in o.items() if v is not None}


def _reset_wait(r) -> float:
    """X-RateLimit-Reset 是毫秒时间戳（也兼容秒）→ 还要等几秒。"""
    v = float((r.headers.get("X-RateLimit-Reset") if r is not None else 0) or 0)
    return max(1.0, (v / 1000 if v > 1e11 else v) - time.time()) if r is not None else 5.0


def fetch_api(key: str, category: str = "ai", sleep=time.sleep) -> tuple[list[dict], list[str]]:
    """官方 API 全量翻页（有收入的）：按响应头限流（标准 key 每分钟 10 次），429 等到窗口重置再试。"""
    out, errors, page = [], [], 1
    with _client() as c:
        while page <= API_MAX_PAGES:
            for attempt in range(4):
                try:
                    r = c.get(API_URL, params={"category": category, "minRevenue": 100, "limit": 10, "page": page,
                                               "sort": "revenue-desc"}, headers={"Authorization": f"Bearer {key}"})
                except httpx.HTTPError as e:
                    r, err = None, f"{type(e).__name__}: {str(e)[:120]}"
                if r is not None and r.status_code != 429:
                    break
                sleep(min(_reset_wait(r), 90))
            else:
                errors.append(f"API 第 {page} 页：{'429 限流' if r is not None else err}，停在这里")
                break
            if r.status_code in (401, 403):
                errors.append(f"API {r.status_code}：key 无效或被停用，改用页面抓取")
                break
            if r.status_code != 200:
                errors.append(f"API 第 {page} 页：HTTP {r.status_code}")
                break
            body = r.json()
            out += [api_object(x) for x in body.get("data") or [] if x.get("slug")]
            if not (body.get("meta") or {}).get("hasMore"):
                break
            page += 1
            if r.headers.get("X-RateLimit-Remaining") == "0":
                sleep(min(_reset_wait(r), 90))
    return out, errors


def fetch_board(api_key: str = "") -> tuple[dict[str, dict], list[str]]:
    """首页 / AI 分类 / 在售 / 其它分类页 → 解析；有 API key 时再用官方 API 把 AI 分类有收入的全量补上。"""
    pages, errors = {}, []
    with _client() as c:
        for p in (*BOARD_PAGES, *(f"/category/{s}" for s in CATEGORY_SLUGS)):
            try:
                r = c.get(TRUSTMRR + p)
                r.raise_for_status()
                pages[p] = r.text
            except Exception as e:  # noqa: BLE001
                errors.append(f"{p}: {type(e).__name__}: {str(e)[:120]}")
    board = parse_board(pages)
    if pages.get("/") and len(board) < 50:
        errors.append(f"首页只解析出 {len(board)} 家公司（页面结构变了？）——本次不写指标")
        return {}, errors
    if api_key:
        got, errs = fetch_api(api_key)
        errors += errs
        for o in got:
            cur = board.setdefault(o["slug"], {})
            cur.update(o)
            cur["_ai_cat"] = cur["_ai_hint"] = True
    return board, errors


def fetch_detail(slug: str) -> dict | None:
    """详情页对象（带 aiEnrichment / marketingChannels / userCategory / website）。"""
    with _client() as c:
        r = c.get(f"{TRUSTMRR}/startup/{slug}")
        r.raise_for_status()
    return next((o for o in rsc_objects(r.text) if o.get("slug") == slug and "aiEnrichment" in o), None)


def _num(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None  # NaN


METRIC_FIELDS = {"mrr": "currentMrr", "revenue_30d": "currentLast30DaysRevenue", "growth_30d": "cachedGrowth30d",
                 "growth_mrr_30d": "cachedGrowthMRR30d", "total_revenue": "currentTotalRevenue",
                 "subscriptions": "currentActiveSubscriptions", "asking_price": "askingPrice"}


def metrics_of(o: dict) -> dict[str, float]:
    """对象 → 当天指标。缺的字段不写（解析失败写 0 会被当成暴跌）。on_sale 用 0/1。"""
    m = {k: _num(o.get(f)) for k, f in METRIC_FIELDS.items()}
    m = {k: v for k, v in m.items() if v is not None and not (k in ("mrr", "revenue_30d", "asking_price", "subscriptions") and v <= 0)}
    if "onSale" in o:
        m["on_sale"] = 1.0 if o.get("onSale") else 0.0
    return m


def detail_ext(o: dict) -> dict:
    """详情页 → 公司档案（ext）里要留的字段。"""
    ai = o.get("aiEnrichment") or {}

    def slugs(k):
        return [x.get("name") or x.get("slug") for x in o.get(k) or [] if isinstance(x, dict) and (x.get("name") or x.get("slug"))]
    f = {"category": o.get("userCategory"), "website": o.get("website"), "description": (o.get("description") or "")[:1200],
         "channels": slugs("marketingChannels"), "audience": o.get("targetAudience") or ai.get("businessType"),
         "persona": ai.get("targetPersona"), "value_prop": ai.get("valueProposition"), "problem": ai.get("problemSolved"),
         "pricing": ai.get("pricingModel"), "founded": (o.get("foundedDate") or "")[:10], "country": o.get("country"),
         "payment": o.get("paymentProvider"), "x": o.get("xHandle") or o.get("twitterHandle"),
         "founder": o.get("xFounderName"), "x_followers": o.get("xFollowerCount"),
         "listed_at": (o.get("firstListedForSaleAt") or "")[:10], "seller_note": (o.get("sellerMessage") or "")[:400]}
    return {k: v for k, v in f.items() if v not in (None, "", [])}


# ---------- 收入异动 → 事件（确定性规则） ----------

MILESTONES = [10_000, 50_000, 100_000, 1_000_000]


def usd(v) -> str:
    v = float(v or 0)
    return f"${v / 1e6:.1f}M" if v >= 1e6 else f"${v / 1e3:.1f}k" if v >= 1e3 else f"${v:,.0f}"


def detect(prev: dict[str, float] | None, cur: dict[str, float], today: str, listed_at: str = "") -> list[dict]:
    """前一次快照 vs 今天 → 收入事件 [{key, type, level, title, summary}]。
    prev 为空（第一次看到这家）只认「最近 7 天挂牌出售」，不追溯里程碑 / 增长，避免首日刷屏。
    key 用来去重：里程碑一个门槛只记一次，暴涨 / 暴跌每月最多一次。"""
    out = []
    month = today[:7]
    mrr = cur.get("mrr") or cur.get("revenue_30d") or 0
    basis = "MRR" if cur.get("mrr") else "近 30 天收入"
    g = cur.get("growth_30d")
    if prev:
        pm = prev.get("mrr") or prev.get("revenue_30d") or 0
        for m in MILESTONES:
            if pm and pm < m <= mrr:
                out.append({"key": f"milestone:{m}", "type": "revenue", "level": "A" if m >= 100_000 else "B",
                            "title": f"{basis}突破 {usd(m)}", "summary": f"{basis}从 {usd(pm)} 到 {usd(mrr)}（TrustMRR 支付渠道验证）"})
        if g is not None and g >= 100 and mrr >= 3_000 and (prev.get("growth_30d") or 0) < 100:
            out.append({"key": f"surge:{month}", "type": "revenue", "level": "A" if mrr >= 30_000 else "B",
                        "title": f"近 30 天收入暴涨 {g:+.0f}%", "summary": f"{basis} {usd(mrr)}，30 天环比 {g:+.0f}%（TrustMRR 支付渠道验证）"})
        if g is not None and g <= -40 and mrr >= 5_000 and (prev.get("growth_30d") or 0) > -40:
            out.append({"key": f"drop:{month}", "type": "revenue", "level": "B",
                        "title": f"近 30 天收入下滑 {g:.0f}%", "summary": f"{basis} {usd(mrr)}，30 天环比 {g:.0f}%（TrustMRR 支付渠道验证）"})
    newly = cur.get("on_sale") == 1 and (prev and prev.get("on_sale") == 0 or not prev and listed_at and listed_at >= _days_before(today, 7))
    if newly:
        ask = cur.get("asking_price")
        out.append({"key": f"listing:{month}", "type": "listing", "level": "B" if mrr >= 10_000 else "C",
                    "title": "挂牌出售" + (f"，要价 {usd(ask)}" if ask else ""),
                    "summary": f"{basis} {usd(mrr)}" + (f"，要价约 {ask / max(mrr * 12, 1):.1f} 倍年收入" if ask and mrr else "")})
    return out


def _days_before(day: str, n: int) -> str:
    from datetime import date, timedelta
    return (date.fromisoformat(day) - timedelta(days=n)).isoformat()


# ---------- 赛道归类（DeepSeek） ----------

TRACK_SYSTEM = """你在给 AI 创业公司 / 产品归赛道。输入 JSON：tracks：[{slug, name, scope}]；items：[{id, name, description, category}]。
对每个 item 输出一项，返回 {"items": [{"id": ..., "ai": true/false, "track": "<slug>", "tracks": ["<slug>", ...], "intro": "..."}]}：
- intro：中文一句话（≤45 字）说清楚「这个产品做什么 + 帮谁解决什么问题」，如「AI 监测 LinkedIn 上的购买信号，帮 B2B 销售找到正在找供应商的潜在客户」；
  不要照抄英文营销语、不要形容词堆砌（最好的、终极的），description 为空时只按名字推不出来就给空字符串；
- ai：产品的核心价值是否依赖 AI（大模型 / 生成式 / 机器学习）。只是「用 AI 写了网站」、普通 SaaS 加了个 AI 按钮 → false；
- track：最主要的一个赛道 slug（必须来自 tracks）；ai=false 时也给最接近的；
- tracks：次要赛道（0–2 个）。只根据输入判断。"""
TRACK_BATCH = 30
TRACK_WORKERS = 6  # 批之间互不依赖，并发跑


def classify_tracks(items: list[dict]) -> tuple[dict[str, dict], list[str]]:
    """{id: {ai, track, tracks, intro}}，errors。"""
    out, errors = {}, []
    tracks = [{"slug": s, "name": n, "scope": d} for s, n, d in TRACKS]
    batches = [items[i:i + TRACK_BATCH] for i in range(0, len(items), TRACK_BATCH)]

    def run(batch):
        try:
            return batch, snap.llm_json(TRACK_SYSTEM, {"tracks": tracks, "items": batch}, max_tokens=6000), None
        except Exception as e:  # noqa: BLE001
            return batch, None, f"{type(e).__name__}: {str(e)[:160]}"
    with ThreadPoolExecutor(max_workers=TRACK_WORKERS) as ex:
        done = list(ex.map(run, batches))
    for n, (batch, res, err) in enumerate(done, 1):
        if err:
            errors.append(f"赛道归类第 {n} 批：{err}")
            continue
        ids = {str(x["id"]) for x in batch}
        for x in res.get("items") or []:
            if not isinstance(x, dict) or str(x.get("id")) not in ids:
                continue
            t = x.get("track") if x.get("track") in TRACK_NAMES else ""
            out[str(x["id"])] = {"ai": bool(x.get("ai")), "track": t,
                                 "tracks": [s for s in (x.get("tracks") or []) if s in TRACK_NAMES and s != t][:2],
                                 "intro": str(x.get("intro") or "").strip()[:80]}
    return out, errors


# ---------- 生意拆解卡（后台 Claude 任务，可联网） ----------

PROFILE_SECTIONS = ["收入", "卖什么", "怎么收钱", "客户从哪来", "做对了什么", "可抄的打法", "风险"]

PROFILE_PROMPT = """你是产品雷达的创业分析员。为下面这家 AI 创业公司写一张「生意拆解卡」，帮我（AI 产品 / 创业者）学会看懂一门小生意怎么赚钱、怎么获客、哪里能抄。

## 公司
- 名称：{name}　网站：{website}　赛道：{track}
- TrustMRR 页面：{url}
- 描述：{description}
- 平台记录的档案：{ext}

## 收入（TrustMRR 支付渠道验证的数字，按日期；reported = 公开报道、公司自述，未验证）
{metrics}

## 近期事件
{events}

## 我手动贴的资料（BizPeel 等，可能为空）
{notes}

## 要求
先读 TrustMRR 页面和官网（定价页、首页、博客），再联网查创始人的 X / Indie Hackers / 采访 / Product Hunt 页面，弄清楚渠道和增长方式。
只输出 markdown，**必须**按下面 7 个二级标题、按顺序写，每节 2–6 条要点，中文：

## 收入
（MRR / 30 天收入 / 增长 / 订阅数，标明 verified 还是 reported；和赛道里同类比处在什么位置）
## 卖什么
（核心功能、目标用户、解决什么具体问题、和替代方案比好在哪）
## 怎么收钱
（定价档位、免费 / 试用策略、按量还是订阅、客单价估算）
## 客户从哪来
（获客渠道逐条列：SEO / 内容、X / Reddit、Product Hunt、联盟 / 推荐、付费广告、应用商店、模板市场…；每条写证据）
## 做对了什么
（为什么这门生意能成：时机、切口、分发、产品体验）
## 可抄的打法
（我能直接借鉴的 2–4 个具体动作，写清楚怎么做、多久能验证）
## 风险
（平台依赖、模型成本、同质化、渠道衰退、数据口径）

规则：
- 每条事实后面用 [来源名](链接, YYYY-MM-DD) 标出处和日期；
- 推出来的句首标 **【推测】**；查不到的写「未公开」，不要编数字；
- 不要写开场白和总结段落，不要输出这 7 节以外的标题。
"""


def profile_inputs_hash(company: dict, metrics: list[dict], notes: str) -> str:
    """输入变化不大（同一个 MRR 量级、同样的笔记）就不重写。"""
    last = metrics[-1] if metrics else {}
    bucket = round((last.get("mrr") or last.get("revenue_30d") or 0) / 5000)
    return hashlib.sha1(json.dumps([company.get("track"), bucket, notes.strip()], ensure_ascii=False).encode()).hexdigest()[:16]


def profile_prompt(company: dict, metrics: list[dict], reported: list[dict], events: list[dict], notes: str) -> str:
    ext = company.get("ext") or {}
    keep = {k: ext[k] for k in ("category", "channels", "audience", "persona", "value_prop", "problem", "pricing", "founded",
                                "country", "payment", "x", "founder", "x_followers", "listed_at", "seller_note", "bizpeel_url") if ext.get(k)}
    def line(m):
        s = f"- {m['date']} · MRR {usd(m['mrr']) if m.get('mrr') else '-'} · 30 天收入 {usd(m['revenue_30d']) if m.get('revenue_30d') else '-'}"
        return s + (f" · 环比 {m['growth_30d']:+.0f}%" if m.get("growth_30d") is not None else "")
    ml = "\n".join(line(m) for m in metrics[-12:])
    ml += "".join(f"\n- {r['date']} · reported {r['metric'].upper()} {usd(r['value'])} · {r.get('source') or ''}" for r in reported[-6:])
    el = "\n".join(f"- {e['date']} [{e['level']}] {e['title']}" for e in events[:10]) or "- 无"
    return PROFILE_PROMPT.format(name=company["name"], website=ext.get("website") or "-",
                                 track=TRACK_NAMES.get(company.get("track") or "", "未归类"),
                                 url=f"{TRUSTMRR}/startup/{ext['trustmrr']}" if ext.get("trustmrr") else "-",
                                 description=(ext.get("description") or company.get("note") or "-")[:1200],
                                 ext=json.dumps(keep, ensure_ascii=False)[:1500] or "-", metrics=ml.strip() or "- 无",
                                 events=el, notes=(notes or "").strip()[:6000] or "（无）")


def parse_sections(text: str, names: list[str]) -> tuple[dict[str, str], list[str]]:
    secs: dict[str, str] = {}
    cur, buf = None, []
    for ln in (text or "").splitlines():
        m = re.match(r"^#{2,3}\s*(?:\d+[.、]\s*)?(.+?)\s*$", ln)
        name = next((s for s in names if m and m[1].startswith(s)), None) if m else None
        if name:
            if cur:
                secs[cur] = "\n".join(buf).strip()
            cur, buf = name, []
        elif cur:
            buf.append(ln)
    if cur:
        secs[cur] = "\n".join(buf).strip()
    return secs, [s for s in names if not secs.get(s)]


def profile_quality(text: str) -> dict:
    secs, missing = parse_sections(text, PROFILE_SECTIONS)
    links = re.findall(r"\]\((https?://[^)\s,]+)", text or "")
    return {"sections": secs, "missing": missing, "links": len(links),
            "complete": not missing and bool(links) and bool(re.search(r"20\d\d-\d\d-\d\d", text or ""))}


# ---------- Product Hunt 日榜解读（DeepSeek） ----------

PH_SYSTEM = """你在为 AI 创业者解读 Product Hunt 当天的 AI 产品榜。输入 JSON：day；tracks：[{slug, name}]；
items：按票数排好的产品 [{id, rank, name, tagline, votes, comments, topics}]。返回：
{"items": [{"id": ..., "track": "<slug>", "why": "≤40 字：它解决什么问题、凭什么上榜"}],
 "summary": "markdown，3–6 条要点：今天哪些赛道扎堆、有什么新切口 / 新形态、和最近趋势的关系、哪个值得亲手试（写清楚为什么）。只根据输入，推测的句首标【推测】"}"""


def ph_payload(day: str, items: list[dict]) -> dict:
    return {"day": day, "tracks": [{"slug": s, "name": n} for s, n, _ in TRACKS],
            "items": [{"id": it["id"], "rank": i + 1, "name": it["title"].split("：")[0][:80], "tagline": it["title"][:200],
                       "votes": int(it.get("popularity") or 0), "comments": (it.get("extra") or {}).get("comments", 0),
                       "topics": (it.get("extra") or {}).get("topics", [])[:5]} for i, it in enumerate(items)]}


# ---------- 公开 ARR 抽取（DeepSeek，数字必须在原文里） ----------

ARR_HINT = re.compile(r"\b(ARR|MRR|annual(?:ized)? recurring revenue|run[- ]rate)\b|年化收入|年经常性收入", re.I)
ARR_SYSTEM = """从新闻 / 推文里抽取「某家公司的 ARR 或 MRR 数字」。输入 JSON：items：[{id, title, text}]。
返回 {"items": [{"id": ..., "company": "公司名（英文原名）", "metric": "arr|mrr", "value_usd": 数字（美元，$100M → 100000000）,
"quote": "原文里包含这个数字的那句话（原样摘抄，≤200 字）"}]}。
只收公司自己或可信媒体说的**当前**收入数字；预测、目标、融资额、估值、市场规模、别家公司的数字都不要。没有就返回空数组。"""


def _value_in_text(value: float, text: str) -> bool:
    """数字必须能在原文里找到（$100M / 100 million / $1.2B / 1 亿美元…），否则当模型编的。"""
    t = (text or "").lower().replace(",", "")
    for m in re.finditer(r"\$?\s?(\d+(?:\.\d+)?)\s*(k|m|b|thousand|million|billion|mn|bn|万|亿)?", t):
        n = float(m[1])
        unit = {"k": 1e3, "thousand": 1e3, "m": 1e6, "mn": 1e6, "million": 1e6, "b": 1e9, "bn": 1e9, "billion": 1e9,
                "万": 1e4, "亿": 1e8}.get(m[2] or "", 1)
        if value and abs(n * unit - value) / value < 0.02:
            return True
    return False


def extract_arr(items: list[dict]) -> tuple[list[dict], list[str]]:
    """[{item_id, company, metric, value, quote}]，errors。"""
    out, errors = [], []
    for i in range(0, len(items), 15):
        batch = items[i:i + 15]
        try:
            res = snap.llm_json(ARR_SYSTEM, {"items": [{"id": it["id"], "title": it["title"][:300], "text": it["text"][:2000]} for it in batch]},
                                max_tokens=3000)
        except Exception as e:  # noqa: BLE001
            errors.append(f"ARR 抽取第 {i // 15 + 1} 批：{type(e).__name__}: {str(e)[:160]}")
            continue
        by = {it["id"]: it for it in batch}
        for x in res.get("items") or []:
            it = by.get(x.get("id")) if isinstance(x, dict) else None
            v = _num(x.get("value_usd")) if it else None
            if not it or not v or v < 1e5 or x.get("metric") not in ("arr", "mrr") or not (x.get("company") or "").strip():
                continue
            if not _value_in_text(v, f"{it['title']} {it['text']}"):
                continue
            out.append({"item_id": it["id"], "company": x["company"].strip()[:80], "metric": x["metric"], "value": v,
                        "quote": (x.get("quote") or "")[:300]})
    return out, errors
