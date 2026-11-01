"""关键词：一份主题表派生各来源的搜索词，按词统计效果，从反馈里推荐候选词。

主题 = {"name", "en": [...], "zh": [...], 可选 "<来源>": [...] 覆盖该来源用的词, 可选 "off": True}。
英文来源（HN / GitHub / Reddit / YouTube / X）用 en，知乎用 zh；某主题写了 "github" 之类的键就只给那个来源用它。
每个来源有词数上限（搜索按次计费 / 限流），效果差的词排到最后、先被截掉。
settings 里显式写了 feed.<来源>_queries（老配置）时，那个来源仍用老列表，不从主题表派生。
不依赖 app 包，feed.py 把条目、反馈传进来。
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone

import httpx

# 来源键 → 用哪种语言的词；键名同条目的 source（X 的条目 source 是 twitter）
LANG = {"hn": "en", "github": "en", "reddit": "en", "youtube": "en", "x": "en", "zhihu": "zh"}
SOURCE_LABEL = {"hn": "HN", "github": "GitHub", "reddit": "Reddit", "youtube": "YouTube", "x": "X", "zhihu": "知乎"}
# 每个来源最多用几个词：YouTube 搜索 100 配额 / 次、知乎走 DeepSeek 搜索按次计、X 是付费接口默认不派生
CAPS = {"hn": 12, "github": 8, "reddit": 6, "youtube": 6, "zhihu": 6, "x": 0}
DEFAULT_TOPICS = [
    {"name": "Coding Agent", "en": ["claude code", "coding agent"], "zh": ["Claude Code"], "github": ["claude code"]},
    {"name": "AI Agent", "en": ["AI agent"], "zh": ["Agent"], "youtube": ["AI agents"], "github": ["ai agent"]},
    {"name": "MCP", "en": ["mcp server"], "github": ["mcp"]},
    {"name": "LLM", "en": ["LLM"], "youtube": ["LLM explained"], "github": ["llm"]},
    {"name": "AI 工程 / Infra", "en": ["AI engineering"], "zh": ["AI Infra", "推理部署"]},
    {"name": "推理与后训练", "zh": ["推理模型", "后训练"]},
    {"name": "模型厂商动态", "hn": ["Claude", "OpenAI", "GPT"]},
]
STATS_DAYS = 30
CJK_RE = re.compile(r"[一-鿿]")


def lang_of(term: str) -> str:
    return "zh" if CJK_RE.search(term) else "en"


def terms_for(topic: dict, source: str) -> list[str]:
    if topic.get("off"):
        return []
    return list(topic.get(source) if source in topic else topic.get(LANG.get(source, "en")) or [])


def _key(t: str) -> str:
    return t.strip().lower()


def queries_for(topics: list[dict], source: str, stats: dict | None = None, cap: int | None = None) -> list[str]:
    """某来源这次要搜的词：按主题表顺序去重；判为「低效 / 没搜到」的排到最后，再截到上限。"""
    seen, out = set(), []
    for tp in topics:
        for t in terms_for(tp, source):
            if t.strip() and _key(t) not in seen:
                seen.add(_key(t))
                out.append(t.strip())
    bad = {k for k, v in (stats or {}).items() if v.get("verdict") in ("低效", "没搜到")}
    out.sort(key=lambda t: f"{source}|{_key(t)}" in bad)   # 稳定排序：好的和没数据的保持原顺序
    n = CAPS.get(source, 6) if cap is None else cap
    return out[:n]


def item_source(it: dict) -> str:
    return "x" if it.get("source") == "twitter" else it.get("source", "")


def item_query(it: dict) -> str:
    """条目是被哪个搜索词搜到的；X 的搜索结果 via 存的是词（账号时间线是 @xxx）。"""
    ex = it.get("extra") or {}
    if ex.get("query"):
        return str(ex["query"])
    if it.get("source") == "twitter" and ex.get("via") and not str(ex["via"]).startswith("@"):
        return str(ex["via"])
    return ""


def term_stats(items: list[dict], feedback: dict[str, dict], deep_urls: set[str], runs: dict[str, dict],
               *, low_value, norm_url, now: datetime | None = None, days: int = STATS_DAYS) -> dict[str, dict]:
    """{"<来源>|<词小写>": {found, kept, judged, liked, saved, clicked, deep, runs, verdict}}，只看近 days 天首次收到的条目。
    kept：没被价值判断丢掉的（没有价值判断的来源 = found）。runs 来自查询日志，没条目但搜过很多次的判「没搜到」。"""
    now = now or datetime.now(timezone.utc)
    since = (now - timedelta(days=days)).isoformat(timespec="seconds")
    out: dict[str, dict] = {}

    def row(k: str) -> dict:
        return out.setdefault(k, {"found": 0, "kept": 0, "judged": 0, "liked": 0, "saved": 0, "clicked": 0, "deep": 0, "runs": 0})

    for it in items:
        q = item_query(it)
        if not q:
            continue
        ex = it.get("extra") or {}
        first = str(ex.get("first_seen") or it.get("fetched_at") or "")
        if first[:19] < since[:19]:   # first_seen 是 UTC ISO；老条目没有时退回 fetched_at（本地时间，差几小时无所谓）
            continue
        r = row(f"{item_source(it)}|{_key(q)}")
        r["found"] += 1
        r["judged"] += ex.get("judge_value") is not None
        r["kept"] += not low_value(it)
        f = feedback.get(it["id"], {})
        r["liked"] += (f.get("vote") or 0) > 0
        r["saved"] += bool(f.get("saved"))
        r["clicked"] += (f.get("clicks") or 0) > 0
        r["deep"] += bool(it.get("url")) and norm_url(it["url"]) in deep_urls
    for k, v in runs.items():
        row(k)["runs"] = int(v.get("runs") or 0)
    for r in out.values():
        r["verdict"] = verdict(r)
    return out


def verdict(r: dict) -> str:
    good = r["liked"] + r["saved"] + r["deep"]
    if r["found"] == 0:
        return "没搜到" if r["runs"] >= 3 else "数据不足"
    if good:
        return "有效"
    if not r["judged"]:   # HN / GitHub / X 没有价值判断，「留下」恒等于搜到，只能看你点没点
        if r["clicked"]:
            return "有效"
        return "低效" if r["found"] >= 20 else "数据不足"
    if r["kept"] >= 3 and r["kept"] >= 0.4 * r["found"]:
        return "有效"
    if r["found"] >= 6 and r["kept"] < 0.2 * r["found"]:
        return "低效"
    return "数据不足"


def normalize(topics) -> list[dict]:
    """接口收到的主题表：去空、去重、每个词列表只留字符串。"""
    out, names = [], set()
    for tp in topics or []:
        if not isinstance(tp, dict) or not str(tp.get("name") or "").strip():
            continue
        name = str(tp["name"]).strip()[:40]
        if name.lower() in names:
            continue
        names.add(name.lower())
        clean = {"name": name}
        for k, v in tp.items():
            if k in ("en", "zh", *LANG) and isinstance(v, list):
                seen, terms = set(), []
                for t in v:
                    t = str(t).strip()[:60]
                    if t and _key(t) not in seen:
                        seen.add(_key(t))
                        terms.append(t)
                clean[k] = terms
        if tp.get("off"):
            clean["off"] = True
        out.append(clean)
    return out


# ---------- 候选词 ----------

SUGGEST_SYSTEM = """你帮一个 AI 从业者维护信息推荐的搜索关键词。给你：他点赞 / 收藏 / 深读过的条目标题，现有主题表，他已经拒绝过的词。
请提出最多 6 个新的搜索主题，要求：
- 具体的技术名词或社区常用说法（如 "KV cache"、"speculative decoding"、"推理部署"），不要「大模型」「AI」「人工智能」这类宽词，不要新闻 / 公司名；
- 现有主题表没覆盖的方向，且能从他的反馈里看出兴趣；
- 每个主题给英文搜索词（HN / Reddit / YouTube / GitHub 用）和中文搜索词（知乎用），各 1-2 个；
- reason 用一句中文说从哪些条目看出来的。
只输出 JSON：{"topics": [{"name": "...", "en": ["..."], "zh": ["..."], "reason": "..."}]}"""


def suggest(liked_titles: list[str], topics: list[dict], dismissed: list[str], *, model: str = "deepseek-v4-flash",
            client: httpx.Client | None = None) -> tuple[list[dict], str]:
    """→ (候选主题, 错误)。候选里已在主题表 / 拒绝过的词会被去掉。"""
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not key:
        return [], "未配置 DEEPSEEK_API_KEY（项目根目录 .env），没法推荐候选词"
    if len(liked_titles) < 3:
        return [], "赞 / 收藏 / 深读过的条目少于 3 条，反馈太少，先多标几条再来"
    base = os.environ.get("DEEPSEEK_API_BASE", "https://api.deepseek.com").rstrip("/")
    have = {_key(t) for tp in topics for k, v in tp.items() if isinstance(v, list) for t in v} | {_key(t) for t in dismissed}
    user = json.dumps({"liked": liked_titles[:60], "topics": [{k: v for k, v in tp.items() if k != "off"} for tp in topics],
                       "dismissed": dismissed[:50]}, ensure_ascii=False)
    own = client is None
    c = client or httpx.Client(timeout=httpx.Timeout(90.0, connect=10.0))
    try:
        r = c.post(f"{base}/chat/completions", headers={"Authorization": f"Bearer {key}"}, json={
            "model": model, "temperature": 0.3, "max_tokens": 2000, "thinking": {"type": "disabled"},
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": SUGGEST_SYSTEM}, {"role": "user", "content": user}]})
        r.raise_for_status()
        rows = json.loads(r.json()["choices"][0]["message"]["content"]).get("topics") or []
    except Exception as e:  # noqa: BLE001
        return [], f"{type(e).__name__}: {str(e)[:160]}"
    finally:
        if own:
            c.close()
    out = []
    for tp in normalize(rows):
        for k in ("en", "zh"):
            tp[k] = [t for t in tp.get(k, []) if _key(t) not in have][:2]
        if tp.get("en") or tp.get("zh"):
            src_row = next((x for x in rows if isinstance(x, dict) and str(x.get("name", "")).strip()[:40] == tp["name"]), {})
            tp["reason"] = str(src_row.get("reason") or "")[:120]
            out.append(tp)
    return out[:6], ""
