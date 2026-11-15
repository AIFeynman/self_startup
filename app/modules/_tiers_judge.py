"""Tier1 的深读判断：规则只负责筛候选，值不值得精读交给 Jev（_feed_judge 的 "deep" 题）。
结果按内容哈希存 tiers_judge 表，同一条不重复问；没配 key 或调用失败时返回空，build 退回纯规则。"""
from __future__ import annotations

import time
from hashlib import sha1

from .. import db
from . import _feed_judge as fj
from . import _feed_rank as rk

SCHEMA = """
CREATE TABLE IF NOT EXISTS tiers_judge (
  item_id TEXT PRIMARY KEY,
  jkey TEXT NOT NULL,
  p REAL NOT NULL,
  at REAL NOT NULL
);
"""
DEEP_YES, DEEP_NO = 0.65, 0.5    # 概率 ≥0.65 进 Tier1；规则判 Tier1 但 <0.5 的降到 Tier2；中间保持规则结果


def deep_scores(items: list[dict], *, client=None) -> tuple[dict[str, float], list[str]]:
    if not items:
        return {}, []
    qv = sha1(fj.Q_DEEP.encode()).hexdigest()[:6]
    keys = {it["id"]: f"{fj.judge_key(it)}{qv}" for it in items}
    ids = list(keys)
    cached = {r["item_id"]: r for r in db.rows(f"SELECT item_id, jkey, p FROM tiers_judge WHERE item_id IN ({','.join('?' * len(ids))})", ids)}
    scores = {i: r["p"] for i, r in cached.items() if r["jkey"] == keys[i]}
    todo = [(it, "deep", rk.official_org(it)) for it in items if it["id"] not in scores]
    errors: list[str] = []
    if todo:
        got, errors = fj.judge(todo, client=client)
        for i, v in got.items():
            scores[i] = v["judge_deep"]
            db.execute("INSERT OR REPLACE INTO tiers_judge(item_id, jkey, p, at) VALUES (?,?,?,?)", (i, keys[i], v["judge_deep"], time.time()))
    return {i: p for i, p in scores.items() if i in keys}, errors
