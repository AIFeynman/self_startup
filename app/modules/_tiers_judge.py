"""分级的 Jev 打分：规则只出候选和门槛，值不值得精读（deep）、值不值得扫一眼（pick）交给 Jev（_feed_judge）。
结果按内容 + 题目哈希存 tiers_scores 表，同一条不重复问；没配 key 或调用失败时返回空，build 退回纯规则。"""
from __future__ import annotations

import time
from hashlib import sha1

from .. import db
from . import _feed_judge as fj
from . import _feed_rank as rk

SCHEMA = """
CREATE TABLE IF NOT EXISTS tiers_scores (
  item_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  jkey TEXT NOT NULL,
  p REAL NOT NULL,
  at REAL NOT NULL,
  PRIMARY KEY (item_id, kind)
);
"""
DEEP_YES, DEEP_NO = 0.62, 0.5    # 深读分 ≥0.62 进 Tier1；规则判 Tier1 但 <0.5 的降到 Tier2；中间保持规则结果
PICK_FLOOR = 0.6                 # Tier2 的扫一眼分低于它的不进 Tier2（回到 Tier3）


def _qhash(kind: str) -> str:
    q = fj.Q_DEEP if kind == "deep" else "".join(fj.Q_PICK.values())
    return sha1(q.encode()).hexdigest()[:6]


def scores(items: list[dict], kind: str, *, client=None) -> tuple[dict[str, float], list[str]]:
    if not items:
        return {}, []
    qv = _qhash(kind)
    keys = {it["id"]: f"{fj.judge_key(it)}{qv}" for it in items}
    ids = list(keys)
    cached = db.rows(f"SELECT item_id, jkey, p FROM tiers_scores WHERE kind=? AND item_id IN ({','.join('?' * len(ids))})", [kind, *ids])
    out = {r["item_id"]: r["p"] for r in cached if r["jkey"] == keys[r["item_id"]]}
    todo = [(it, kind, rk.official_org(it)) for it in items if it["id"] not in out]
    errors: list[str] = []
    if todo:
        got, errors = fj.judge(todo, client=client)
        for i, v in got.items():
            out[i] = v[f"judge_{kind}"]
            db.execute("INSERT OR REPLACE INTO tiers_scores(item_id, kind, jkey, p, at) VALUES (?,?,?,?,?)", (i, kind, keys[i], out[i], time.time()))
    return out, errors
