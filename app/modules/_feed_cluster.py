"""X 讨论的事件聚合：同一件事（比如某个模型发布）一天能有几十条推文，把它们并成一条，其余折叠在下面。

分组交给本机 Claude Code 的 haiku（低强度活）：一次看一批推文，只把「说同一件具体事」的归成一组，凑不满 MIN_GROUP 条的不分。
分组结果写在条目 extra.event / extra.event_title，列表输出时 collapse 把每组并成综合分最高的一条（lead）。
"""
from __future__ import annotations

import json
import re
from hashlib import sha1

MIN_GROUP = 3
BATCH_MAX = 150
SYSTEM = (
    "你是 AI 资讯编辑。下面是一批推文（id + 正文）。把「在说同一件具体事」的推文归成一组：同一个模型 / 产品发布、同一次融资 / 事故 / 争议、"
    "同一份报告或评测；围绕同一个模型 / 产品的发布、评测成绩、实测演示、选型讨论算同一件事，并成一组。只是话题相近（都提到 Claude、都讲 Agent）不算同一件事。\n"
    f"要求：每组至少 {MIN_GROUP} 条；不属于任何组的推文不要输出；一条推文只能在一个组里；组标题是中文，不超过 20 个字，说清是哪件事。\n"
    '只输出 JSON，不要任何别的文字：{"events": [{"title": "<组标题>", "ids": ["<原样返回的 id>"]}]}'
)


def _payload(items: list[dict]) -> str:
    return json.dumps([{"id": it["id"], "text": (it.get("title") or "")[:160]} for it in items], ensure_ascii=False)


def group(items: list[dict], *, run, model: str = "claude-haiku-5-5") -> list[dict]:
    """items → [{key, title, ids}]；只留 ids 都在输入里、不少于 MIN_GROUP 条的组。"""
    items = items[:BATCH_MAX]
    if len(items) < MIN_GROUP:
        return []
    text = run(_payload(items), system=SYSTEM, model=model)["text"]
    m = re.search(r"\{.*\}", text or "", re.S)
    rows = (json.loads(m.group(0)).get("events") or []) if m else []
    valid, taken, out = {it["id"] for it in items}, set(), []
    for r in rows:
        title = str(r.get("title") or "").strip()
        ids = [i for i in dict.fromkeys(map(str, r.get("ids") or [])) if i in valid and i not in taken]
        if title and len(ids) >= MIN_GROUP:
            taken.update(ids)
            out.append({"key": sha1(title.encode()).hexdigest()[:8], "title": title, "ids": ids})
    return out


def collapse(items: list[dict]) -> list[dict]:
    """排好序的条目里，同一事件只留第一条（综合分最高），挂上 event = {key, title, n, items: 被折叠的其余条目}。"""
    leads: dict[str, dict] = {}
    out = []
    for x in items:
        ex = x.get("extra") or {}
        key = ex.get("event") if x.get("source") == "twitter" else ""
        if not key:
            out.append(x)
        elif key in leads:
            leads[key]["event"]["items"].append({k: x.get(k) for k in ("id", "title", "url", "date")} | {"gist": ex.get("gist", "")})
        else:
            lead = {**x, "event": {"key": key, "title": ex.get("event_title", ""), "items": []}}
            leads[key] = lead
            out.append(lead)
    for lead in leads.values():
        lead["event"]["n"] = len(lead["event"]["items"]) + 1
    return out
