"""信息推荐的「中文一句话」：给排在前面的条目生成 ≤40 字的中文概括，让人扫一眼就知道讲什么、值不值得点开。

只给排序前列（全部前 N + 每类前 M）里还没有、或标题 / 简介变了的条目生成；结果写进 feed_items.extra.gist，
gist_src 记下生成时输入的哈希，内容不变就不重复调用。模型走 DeepSeek 官方 API（OpenAI 兼容，.env 的 DEEPSEEK_API_KEY），
失败只记错误，不影响采集和排序。
"""
from __future__ import annotations

import json
import os
import re
from hashlib import sha1

import httpx

BATCH = 20
MAX_CHARS = 90       # 40 个汉字夹着英文专名时约 60–80 个字符；超了在最后一个标点处截断
TIMEOUT = httpx.Timeout(90.0, connect=10.0)
SYSTEM = (
    "你是 AI 资讯编辑。给每条资讯写一句中文概括，帮读者扫一眼判断要不要点开。\n"
    "要求：\n"
    "- 每条一句话，不超过 40 个汉字；先说它是什么（发布了什么 / 提出了什么 / 谁说了什么），再点出最关键的一个信息点。\n"
    "- 只根据给出的标题、简介、来源写，不补充、不猜测给出内容里没有的事实、数字和结论。\n"
    "- 信息太少（比如只有一个链接）就只说它是什么，不要编。\n"
    "- 专有名词（产品名、模型名、公司名、人名）保留原文。不要加「这篇」「该推文」之类的开头，不要评价好坏。\n"
    '输出 JSON：{"items": [{"id": "<原样返回的 id>", "gist": "<一句话>"}]}，每条输入都要有一条输出。'
)


def fit(text: str, limit: int = MAX_CHARS) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    m = max(cut.rfind(p) for p in "，。；、,;")
    return (cut[:m] if m >= limit // 2 else cut.rstrip()) + "…"


def gist_key(it: dict) -> str:
    return sha1(f"{it.get('title', '')}\n{it.get('summary', '')}".encode()).hexdigest()[:12]


def is_chinese(title: str) -> bool:
    """标题本身已经是中文（按「一个汉字 / 一个英文词」计，汉字过半）：一句话只会复述标题，不生成。"""
    body = re.sub(r"^@\w+：", "", title or "")
    zh, en = len(re.findall(r"[一-鿿]", body)), len(re.findall(r"[A-Za-z0-9][\w'.-]*", body))
    return zh > 0 and zh / (zh + en) >= 0.5


def pick(ranked_all: list[dict], ranked_by_type: dict[str, list[dict]], top: int = 60, per_type: int = 10) -> list[dict]:
    """需要（重新）生成的条目：全部前 top 条 + 每类前 per_type 条里，没有 gist 或输入已变的。保持排序顺序、去重。"""
    seen, out = set(), []
    for it in ranked_all[:top] + [x for lst in ranked_by_type.values() for x in lst[:per_type]]:
        if it["id"] in seen:
            continue
        seen.add(it["id"])
        ex = it.get("extra") or {}
        if is_chinese(it.get("title", "")):
            continue
        if not ex.get("gist") or ex.get("gist_src") != gist_key(it):
            out.append(it)
    return out


def _payload(items: list[dict]) -> str:
    rows = [{"id": it["id"], "source": it.get("source_label") or it.get("source", ""),
             "title": it.get("title", "")[:200], "summary": (it.get("summary") or "")[:400]} for it in items]
    return json.dumps(rows, ensure_ascii=False)


def generate(items: list[dict], *, model: str = "deepseek-v4-flash", client: httpx.Client | None = None) -> tuple[dict[str, str], list[str]]:
    """items → ({id: gist}, errors)。按 BATCH 分批，一批失败不影响其它批。"""
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not key:
        return {}, ["未配置 DEEPSEEK_API_KEY（项目根目录 .env），跳过中文一句话"]
    base = os.environ.get("DEEPSEEK_API_BASE", "https://api.deepseek.com").rstrip("/")
    own = client is None
    c = client or httpx.Client(timeout=TIMEOUT)
    out, errors = {}, []
    try:
        for i in range(0, len(items), BATCH):
            batch = items[i:i + BATCH]
            try:
                r = c.post(f"{base}/chat/completions", headers={"Authorization": f"Bearer {key}"}, json={
                    "model": model, "temperature": 0.2, "max_tokens": 4000,
                    "thinking": {"type": "disabled"}, "response_format": {"type": "json_object"},
                    "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": _payload(batch)}]})
                r.raise_for_status()
                rows = json.loads(r.json()["choices"][0]["message"]["content"]).get("items") or []
                ids = {it["id"] for it in batch}
                got = {str(x.get("id")): str(x.get("gist") or "").strip() for x in rows if isinstance(x, dict)}
                out.update({k: fit(v) for k, v in got.items() if k in ids and v})
                if len(got.keys() & ids) < len(ids):
                    errors.append(f"第 {i // BATCH + 1} 批少返回 {len(ids - got.keys())} 条")
            except Exception as e:  # noqa: BLE001
                errors.append(f"第 {i // BATCH + 1} 批：{type(e).__name__}: {str(e)[:120]}")
    finally:
        if own:
            c.close()
    return out, errors
