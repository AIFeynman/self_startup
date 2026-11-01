"""信息推荐的两个是 / 否判断，交给 Jev（TypeSafe 的判别模型，返回命题概率 noul ∈ [0, 1]）：

- ai：GitHub Trending 上的项目是否与 AI 相关。不相关的不进推荐（Trending 是全站榜，混着 devops 题库、紫微斗数之类）。
- important：官方博客 / 重点机构新仓库是不是实质更新（新模型、产品功能、开源项目、研究、技术文章），而不是客户案例、
  合作签约、营销活动这类 PR 水文。是的话在「全部」里置顶、进今日精选。

结果写进 feed_items.extra 的 judge_ai / judge_important，judge_src 记输入哈希，内容不变不重复问。
没配 TYPESAFE_API_KEY（或 JEV_API_KEY）或调用失败时不写，排序退回 _feed_rank 里的关键词规则。
"""
from __future__ import annotations

import json
import os
from hashlib import sha1

import httpx

API = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-latest"
BATCH = 20
TIMEOUT = httpx.Timeout(60.0, connect=10.0)
Q_AI = ("state.items.{k} 是 GitHub Trending 上的一个开源项目。它是否与人工智能直接相关"
        "（大模型、机器学习、AI 应用、Agent，或者给 AI 开发 / 使用的工具）？")
Q_IMPORTANT = ("state.items.{k} 是 {org} 官方发布的内容。它是否是实质性的更新：新模型、新产品或功能、开源项目、"
               "研究成果、技术或工程深度文章、重要的安全报告？客户案例、合作签约、行业方案推广、营销活动、招聘、"
               "公关表态这类内容回答否。")


def judge_key(it: dict) -> str:
    return sha1(f"{it.get('title', '')}\n{it.get('summary', '')}".encode()).hexdigest()[:12]


def _state(it: dict, org: str) -> dict:
    ex = it.get("extra") or {}
    row = {"title": it.get("title", "")[:200], "summary": (it.get("summary") or "")[:500], "url": it.get("url", "")}
    if it.get("source") == "github":
        row |= {"stars": int(it.get("popularity") or 0), "language": ex.get("language", ""),
                "topics": ex.get("topics") or []}
    if org:
        row["publisher"] = org
    return row


def judge(todo: list[tuple[dict, str, str]], *, client: httpx.Client | None = None) -> tuple[dict[str, dict], list[str]]:
    """todo: [(item, kind, org)]，kind 是 "ai" / "important"。返回 ({id: {"judge_ai"|"judge_important": p}}, errors)。"""
    key = (os.environ.get("TYPESAFE_API_KEY") or os.environ.get("JEV_API_KEY") or "").strip()
    if not key:
        return {}, ["未配置 TYPESAFE_API_KEY（项目根目录 .env），Trending 是否 AI、官方内容是否重要改用关键词规则"]
    own = client is None
    c = client or httpx.Client(timeout=TIMEOUT)
    out: dict[str, dict] = {}
    errors = []
    try:
        for i in range(0, len(todo), BATCH):
            batch = todo[i:i + BATCH]
            refs = {f"i{n}": row for n, row in enumerate(batch)}   # 题目里引用短键，不把条目 id 里的 / : 放进路径
            payload = {"model": MODEL,
                       "state": {"items": {k: _state(it, org) for k, (it, _, org) in refs.items()}},
                       "questions": {f"{k}_{kind}": {"type": "noul", "instructions": (Q_AI if kind == "ai" else Q_IMPORTANT)
                                                     .format(k=k, org=org)} for k, (_, kind, org) in refs.items()}}
            try:
                r = c.post(API, headers={"Authorization": f"Bearer {key}"}, json=payload)
                r.raise_for_status()
                answers = r.json().get("answers") or {}
                for k, (it, kind, _) in refs.items():
                    p = (answers.get(f"{k}_{kind}") or {}).get("noul")
                    if isinstance(p, (int, float)) and 0 <= p <= 1:   # 缺字段不能当 0 分
                        out.setdefault(it["id"], {})[f"judge_{kind}"] = round(float(p), 3)
                missing = len(batch) - sum(1 for it, kind, _ in batch if f"judge_{kind}" in out.get(it["id"], {}))
                if missing:
                    errors.append(f"第 {i // BATCH + 1} 批少返回 {missing} 条")
            except Exception as e:  # noqa: BLE001
                errors.append(f"第 {i // BATCH + 1} 批：{type(e).__name__}: {str(e)[:120]}")
    finally:
        if own:
            c.close()
    return out, errors


def as_json(v: dict) -> str:
    return json.dumps(v, ensure_ascii=False)
