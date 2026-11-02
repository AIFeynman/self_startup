"""产品雷达 · 每日增长 Case：每天挑 1 个真实的用户增长案例（怎么触达目标用户、拉新、留住），写成「增长 Case 卡」。

纯函数（源名单 / 打分 / 选题 / 提示词 / 校验）；落库和调度在 intel.py。设计稿：docs/designs/2026-11-02-growth-case-daily-design.md。
源的取舍是 2026-11-02 实测的结论：一手 + 带数字的 RevenueCat / Sub Club / Lenny 当主力；X 只看名单账号、只当线索，数字要核验；
Reddit（RSS 限流、几乎全是提问）和 HN（近一年几乎没有增长 Case）不用。范围限 AI 产品 + 订阅 / SaaS / 消费 App。
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

from ._intel_startup import parse_sections

# tier A：一手、有数字、稳定更新；B：补充（方法论多 / 质量参差）。days=0 表示不限日期（存档当候选池，只在首次收录时打一次分）
SOURCES = [
    {"name": "RevenueCat 博客", "url": "https://www.revenuecat.com/blog/rss.xml", "tier": "A", "days": 30, "per_feed": 30},
    {"name": "Sub Club 播客", "url": "https://feeds.transistor.fm/sub-club", "tier": "A", "days": 0, "per_feed": 200},
    {"name": "Lenny's Newsletter", "url": "https://www.lennysnewsletter.com/feed", "tier": "A", "days": 30, "per_feed": 30},
    {"name": "Elena Verna", "url": "https://www.elenaverna.com/feed", "tier": "B", "days": 30, "per_feed": 10},
    {"name": "Andrew Chen", "url": "https://andrewchen.substack.com/feed", "tier": "B", "days": 30, "per_feed": 10},
    {"name": "Aakash Gupta", "url": "https://www.news.aakashg.com/feed", "tier": "B", "days": 30, "per_feed": 15},
    {"name": "人人都是产品经理", "url": "https://www.woshipm.com/feed", "tier": "B", "days": 14, "per_feed": 30},
]
# build in public、常发带数字的增长复盘的创始人 + 写增长拆解的人；可在设置 intel.growth_x_accounts 里改
X_ACCOUNTS = ["tibo_maker", "marc_louvion", "levelsio", "ErnestoSOFTWARE", "IvanLandabaso", "lennysan", "elenaverna",
              "andrewchen", "nikitabier", "aakashgupta", "pierreeliottlal", "romanbuildsaas", "yasser_elsaid_", "dannypostmaa"]

SCORE_KEYS = ("case", "numbers", "actions", "fit", "firsthand")
MIN_CASE, MIN_FIT, MIN_TOTAL = 2, 2, 9

SCORE_SYSTEM = """你在为「每日增长 Case」挑素材。读者是做 AI 产品的创业者，想学怎么把产品送到目标用户面前、拉新、提升留存。
输入 JSON：items：[{id, source, title, summary}]（summary 是 RSS 摘要或推文正文，可能截断）。
对每条按 0–3 打 5 项分，返回 {"items": [{"id": ..., "company": "案例主角公司 / 产品名，没有就空串", "case": n, "numbers": n, "actions": n, "fit": n, "firsthand": n, "one_line": "≤50 字中文：谁用什么动作把什么做到多少"}]}：
- case：是不是某家具体公司 / 产品的增长故事（3 = 完整讲一家怎么长起来；1 = 只顺带提到；0 = 泛泛方法论、行业新闻、招聘、职业建议、工具测评）
- numbers：有没有具体数字（用户数、ARR / MRR、转化率、留存率、CAC、增长倍数）
- actions：有没有讲清楚具体的获客 / 激活 / 留存动作（渠道、素材、定价、产品机制），而不只是结果
- fit：和「AI 产品、订阅 App、SaaS、消费 App」的相关度（游戏、电商、实体店、加密货币、投资理财 = 0）
- firsthand：是不是当事人（创始人 / 增长负责人）亲述或基于一手数据（3），还是转述 / 二手汇编（1），营销引流贴（0）
只根据输入判断，不要编；每条都要返回。"""

CASE_SECTIONS = ["一句话", "背景与数字", "目标用户在哪", "触达动作", "激活与留存", "为什么有效", "反例与风险", "我能怎么用"]

CASE_PROMPT = """你是产品雷达的增长分析员。今天的「每日增长 Case」选中了下面这条素材，请把它拆成一张「增长 Case 卡」，帮我（做 AI 产品的创业者）学会怎么把产品送到目标用户面前、拉新、提升留存。

## 素材
- 标题：{title}
- 来源：{source}（{tier} 档{x_note}）
- 链接：{url}
- 日期：{date}
- 主角：{company}
- 摘要：{summary}

## 平台里已有的数据（TrustMRR 支付渠道验证 = verified；公开报道 = reported；可能为空）
{metrics}

## 要求
先读原文（播客就找节目页 / 文字稿 / YouTube 字幕），再联网找第二来源（官网、创始人 X、采访、TrustMRR、应用商店、新闻）核对关键数字和时间线。
只输出 markdown，**必须**按下面 8 个二级标题、按顺序写，中文：

## 一句话
（谁，用什么动作，在多长时间里，把什么指标从 X 做到 Y）
## 背景与数字
（公司 / 产品 / 目标用户；每个数字标 **verified**（支付渠道 / 官方财报）或 **reported**（自述 / 报道），带出处和日期；两种不要混算）
## 目标用户在哪
（目标用户原本在哪些渠道、什么场景下出现；团队怎么找到他们的）
## 触达动作
（逐条：渠道、具体怎么做（素材、频率、预算、工具、负责人）、时间线；写到我能照着做的粒度）
## 激活与留存
（第一次用到价值的路径、付费墙 / 定价设计、留存 / 复购机制；来源没讲的写「来源没讲」，不要编）
## 为什么有效
（背后的机制：渠道和产品的契合、时机、增长回路；引用方法论（如 Elena Verna、Andrew Chen）时注明出处）
## 反例与风险
（什么条件下不成立、渠道衰退、幸存者偏差、数据口径）
## 我能怎么用
（1 个一周内能跑的小实验：做什么、做多少、看哪个指标、怎么判断成败）

规则：
- 每条事实后面用 [来源名](链接, YYYY-MM-DD) 标出处和日期；
- 推出来的句首标 **【推测】**；查不到的写「未公开」，不要编数字；
- X / 创始人自述的数字一律算 reported，能在 TrustMRR / 官方找到印证的才写 verified；
- 不要写开场白和总结段落，不要输出这 8 节以外的标题。
"""


def total(s: dict) -> int:
    return sum(int(s.get(k) or 0) for k in SCORE_KEYS)


def clamp_scores(x: dict) -> dict:
    """模型返回的分数夹到 0–3；缺的当 0。"""
    out = {}
    for k in SCORE_KEYS:
        try:
            out[k] = max(0, min(3, int(x.get(k) or 0)))
        except (TypeError, ValueError):
            out[k] = 0
    return out


def eligible(s: dict) -> bool:
    return s.get("case", 0) >= MIN_CASE and s.get("fit", 0) >= MIN_FIT and total(s) >= MIN_TOTAL


def score_payload(items: list[dict]) -> dict:
    return {"items": [{"id": it["id"], "source": it["source"], "title": it["title"], "summary": (it.get("summary") or "")[:1200]}
                      for it in items]}


def norm_company(name: str) -> str:
    return re.sub(r"[^a-z0-9一-鿿]+", "", (name or "").lower())


def rank_key(it: dict, today: str) -> float:
    """总分为主；近 30 天 +2、近 90 天 +1（存档也能选，但新的优先）；A 档 +1。"""
    d = (it.get("date") or "")[:10]
    t = datetime.strptime(today, "%Y-%m-%d")
    fresh = 2 if d >= (t - timedelta(days=30)).strftime("%Y-%m-%d") else 1 if d >= (t - timedelta(days=90)).strftime("%Y-%m-%d") else 0
    return it["total"] + fresh + (1 if it.get("tier") == "A" else 0)


def pick(pool: list[dict], used_companies: set[str], today: str) -> dict | None:
    """候选池里挑 1 条：合格（eligible）、主角公司近期没出过卡（同一公司的多条素材也只算一次）、排序分最高。"""
    ok = [it for it in pool if eligible(it["scores"]) and norm_company(it.get("company") or "") not in used_companies]
    ok = [it for it in ok if norm_company(it.get("company") or "")]  # 说不出主角是谁的不算 Case
    return max(ok, key=lambda it: (rank_key(it, today), it.get("date") or ""), default=None)


def case_prompt(item: dict, metrics: str) -> str:
    return CASE_PROMPT.format(title=item["title"], source=item["source"], tier=item.get("tier") or "B",
                              x_note="，X 推文：数字是自述，只当线索" if item["id"].startswith("twitter:") else "",
                              url=item["url"], date=(item.get("date") or "")[:10] or "未知", company=item.get("company") or "未知",
                              summary=(item.get("summary") or "")[:3000] or "（无）", metrics=metrics or "- 无")


def case_quality(text: str) -> dict:
    """G2 / G3：8 节齐全、有带链接的出处、有日期、「背景与数字」里真有数字、「我能怎么用」非空。"""
    secs, missing = parse_sections(text, CASE_SECTIONS)
    links = re.findall(r"\]\((https?://[^)\s,]+)", text or "")
    body = re.sub(r"\]\([^)]*\)|20\d\d-\d\d(-\d\d)?", "", secs.get("背景与数字", ""))  # 出处链接和日期里的数字不算
    has_num = bool(re.search(r"\d", body))
    if secs.get("背景与数字") and not has_num:
        missing.append("背景与数字里的数字")
    return {"sections": secs, "missing": missing, "links": len(links),
            "complete": not missing and bool(links) and bool(re.search(r"20\d\d-\d\d-\d\d", text or ""))}
