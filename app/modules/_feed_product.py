"""信息推荐「产品」分类的产品分析：收入、商业模式、产品定位、给用户的价值、解决的痛点。

只分析真正的产品（Product Hunt / Launch YC / TrustMRR），a16z 之类的分析文章不分析。
给产品分类排序前 N 条里还没有、或输入变了的条目生成，写进 feed_items.extra.pa（{revenue, model, position, value, pain}），
pa_src 记输入哈希。收入：TrustMRR 有支付渠道验证的数字，直接用 _feed_sources.revenue_line 拼，不经模型；
其它来源只有在给出的内容里写明了才填，否则写「未公开」。模型走 DeepSeek（同 _feed_gist），失败只记错误。
"""
from __future__ import annotations

import json
import os
from hashlib import sha1

import httpx

from ._feed_gist import fit

SOURCES = ("producthunt", "yc", "trustmrr")
FIELDS = ("model", "position", "value", "pain")
BATCH = 8
MAX_CHARS = 120
NO_REVENUE = "未公开"
TIMEOUT = httpx.Timeout(120.0, connect=10.0)
SYSTEM = (
    "你是产品分析师，帮读者快速看懂一个产品值不值得研究。对每个产品用中文写五项，每项一句话（不超过 50 个汉字）：\n"
    "- revenue：收入情况。只用给出的数字和事实（facts 里的收入、订阅、利润率、要价等，单位美元）；没有就写「未公开」，绝不估算。\n"
    "- model：商业模式——谁付钱、怎么收费（订阅 / 按量 / 一次性 / 佣金 / 广告…）、主要获客渠道。给出内容没写收费方式时，"
    "按产品形态写「推测：…」。\n"
    "- position：产品定位——给谁用（目标人群 / B2B 或 B2C）、在什么场景、和常见替代方案相比的差异点。\n"
    "- value：给用户带来的价值——用户用了之后得到什么结果（省时间 / 省钱 / 多赚钱 / 做到原来做不到的事）。\n"
    "- pain：解决的痛点——用户原来遇到的具体问题或麻烦。\n"
    "要求：只根据给出的标题、简介、facts 写，不编造数字、客户、融资等事实；专有名词保留原文；不要空话套话。\n"
    '输出 JSON：{"items": [{"id": "<原样返回的 id>", "revenue": "...", "model": "...", "position": "...", '
    '"value": "...", "pain": "..."}]}，每条输入都要有一条输出。'
)


def pa_key(it: dict) -> str:
    ex = it.get("extra") or {}
    facts = {k: v for k, v in (ex.get("facts") or {}).items() if k not in ("growth_30d", "traffic_30d")}  # 天天变的数字不触发重算
    blob = json.dumps([it.get("title", ""), it.get("summary", ""), facts, ex.get("topics") or []], ensure_ascii=False, sort_keys=True)
    return sha1(blob.encode()).hexdigest()[:12]


def pick(ranked_products: list[dict], top: int = 20) -> list[dict]:
    """产品分类前 top 条（只算 SOURCES 来源）加上全部 TrustMRR 在售产品（每次最多几十条）里，没有分析或输入已变的。"""
    prods = [x for x in ranked_products if x.get("source") in SOURCES]
    out = []
    for it in prods[:top] + [x for x in prods[top:] if x.get("source") == "trustmrr"]:
        ex = it.get("extra") or {}
        if not ex.get("pa") or ex.get("pa_src") != pa_key(it):
            out.append(it)
    return out


def _row(it: dict) -> dict:
    ex = it.get("extra") or {}
    row = {"id": it["id"], "source": it.get("source_label") or it.get("source", ""),
           "title": it.get("title", "")[:200], "summary": (it.get("summary") or "")[:800]}
    if ex.get("facts"):
        row["facts"] = ex["facts"]
    if ex.get("topics"):
        row["tags"] = ex["topics"]
    if it.get("source") == "producthunt" and it.get("popularity"):
        row["producthunt_votes"] = int(it["popularity"])
    if it.get("source") == "yc":
        row["yc_batch"] = ex.get("feed", "")
    return row


def generate(items: list[dict], *, model: str = "deepseek-v4-flash",
             client: httpx.Client | None = None) -> tuple[dict[str, dict], list[str]]:
    """items → ({id: {revenue, model, position, value, pain}}, errors)。"""
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not key:
        return {}, ["未配置 DEEPSEEK_API_KEY（项目根目录 .env），跳过产品分析"]
    base = os.environ.get("DEEPSEEK_API_BASE", "https://api.deepseek.com").rstrip("/")
    own = client is None
    c = client or httpx.Client(timeout=TIMEOUT)
    out, errors = {}, []
    try:
        for i in range(0, len(items), BATCH):
            batch = items[i:i + BATCH]
            try:
                r = c.post(f"{base}/chat/completions", headers={"Authorization": f"Bearer {key}"}, json={
                    "model": model, "temperature": 0.2, "max_tokens": 6000,
                    "thinking": {"type": "disabled"}, "response_format": {"type": "json_object"},
                    "messages": [{"role": "system", "content": SYSTEM},
                                 {"role": "user", "content": json.dumps([_row(it) for it in batch], ensure_ascii=False)}]})
                r.raise_for_status()
                rows = json.loads(r.json()["choices"][0]["message"]["content"]).get("items") or []
                by_id = {it["id"]: it for it in batch}
                for x in rows:
                    it = by_id.get(str((x or {}).get("id")))
                    if not it:
                        continue
                    pa = {k: fit(str(x.get(k) or "").strip(), MAX_CHARS) for k in FIELDS}
                    # 收入：有验证数字的直接用，不让模型复述（会抄错）
                    pa["revenue"] = (it.get("extra") or {}).get("revenue") or fit(str(x.get("revenue") or "").strip(), MAX_CHARS) or NO_REVENUE
                    if any(pa[k] for k in FIELDS):
                        out[it["id"]] = pa
                missing = len(by_id.keys() - out.keys())
                if missing:
                    errors.append(f"第 {i // BATCH + 1} 批少返回 {missing} 条")
            except Exception as e:  # noqa: BLE001
                errors.append(f"第 {i // BATCH + 1} 批：{type(e).__name__}: {str(e)[:120]}")
    finally:
        if own:
            c.close()
    return out, errors
