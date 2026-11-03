"""论文库维护（设计稿 §11）：每周刷新被引、重判门槛、补标注；每次每日入库 / 每周维护都记一条运行记录，页面能看到状态。

- 刷新被引：没入库的 arXiv 论文（落选时被引不够）和入库的近两年论文，走 S2 batch 只取引用数（500 篇一次）。
- 重判门槛：只看没入库的，够了就收进来；已入库的不往外踢（见 admit_all）。
  新收的补详情 → 近期论文过 Jev → 标注。
- 补标注：新论文入库后，引用它的库内论文参考文献变了（label_src 变），走标注队列重标 builds_on，每次最多 LABEL_CAP 篇，
  剩下的下周接着标。
- 脉络不自动重生成（每个 $0.01–0.02），页面上提示「自生成后新增 N 篇」，用户点重新生成。
同一种运行连续失败 2 次，页面标红。
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timedelta

from .. import db, settings
from . import _paper_collect as col, _paper_label as lab

log = logging.getLogger(__name__)

CITE_BATCH = 500           # S2 batch 只取数字时一次最多 500 篇
CITE_FIELDS = "citationCount,influentialCitationCount"
YOUNG_MONTHS = 24          # 入库论文只刷新这么新的（老论文的被引只影响排序，不影响收不收）
LABEL_CAP = 1000           # 每次维护最多标多少篇（新收的 + 要重标 builds_on 的），约 $1 封顶
ALERT_FAILS = 2

SCHEMA = """
CREATE TABLE IF NOT EXISTS paper_runs (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    kind     TEXT,                     -- feed 每日热门入库 / weekly 每周维护
    status   TEXT DEFAULT 'running',   -- running / ok / partial（有错误但跑完了）/ failed
    step     TEXT DEFAULT '',
    result   TEXT DEFAULT '{}',
    started  TEXT, finished TEXT
);
"""
_lock = threading.Lock()


def init() -> None:
    db.init([col.SCHEMA, SCHEMA])
    if not _lock.locked():   # 本进程没在跑却有 running 的：服务重启打断了
        db.execute("UPDATE paper_runs SET status='failed', step='服务重启中断', finished=? WHERE status='running'", [db.now()])


def record(kind: str, fn) -> dict:
    """跑 fn(on_step) 并记一条运行记录；fn 返回的 errors 非空记 partial，抛异常记 failed（异常照样抛出去）。"""
    init()
    rid = db.insert("paper_runs", {"kind": kind, "started": db.now()})
    try:
        res = fn(lambda s: db.execute("UPDATE paper_runs SET step=? WHERE id=?", [s, rid]))
    except Exception as e:  # noqa: BLE001
        db.execute("UPDATE paper_runs SET status='failed', step=?, finished=? WHERE id=?",
                   [f"{type(e).__name__}: {str(e)[:200]}", db.now(), rid])
        raise
    st = "partial" if res.get("errors") else "ok"
    db.execute("UPDATE paper_runs SET status=?, step='完成', result=?, finished=? WHERE id=?",
               [st, json.dumps(res, ensure_ascii=False), db.now(), rid])
    return res


# ---------- 每周维护 ----------

def targets(today: datetime | None = None) -> list[str]:
    """要刷新被引的：没入库的 arXiv 论文（tier 为空的是非 arXiv，永远进不来），入库的近两年论文（经典和用户补充的除外）。"""
    since = ((today or datetime.now()) - timedelta(days=YOUNG_MONTHS * 30.44)).strftime("%Y-%m-%d")
    return [r["s2id"] for r in db.rows(
        "SELECT s2id FROM paper_items WHERE arxiv!='' AND ((status!='in' AND COALESCE(tier,'')!='') "
        "OR (status='in' AND COALESCE(tier,'') NOT IN ('classic','manual') AND pub_date>=?))", [since])]


def refresh_cites(ids: list[str], c, on_step=None) -> int:
    """只更新 cites / infl（upsert 会用缺的字段覆盖标题等，不能复用）。返回变了的篇数。"""
    now, n = db.now(), 0
    old = {r["s2id"]: (r["cites"], r["infl"]) for r in db.rows("SELECT s2id, cites, infl FROM paper_items WHERE arxiv!=''")}
    for i in range(0, len(ids), CITE_BATCH):
        part = ids[i:i + CITE_BATCH]
        for s, p in zip(part, col.batch(part, c, fields=CITE_FIELDS)):
            if not p:
                continue
            new = (p.get("citationCount") or 0, p.get("influentialCitationCount") or 0)
            if new != old.get(s):
                db.execute("UPDATE paper_items SET cites=?, infl=?, updated=? WHERE s2id=?", [*new, now, s])
                n += 1
        if on_step:
            on_step(f"刷新被引 {min(i + CITE_BATCH, len(ids))}/{len(ids)}")
    return n


def promote(today: datetime | None = None) -> list[str]:
    """没入库的按新被引重判，够门槛的收进来。返回新收的 s2id。"""
    got = []
    for r in db.rows("SELECT * FROM paper_items WHERE status!='in' AND arxiv!='' AND COALESCE(tier,'')!=''"):
        st, tier, why = col.decide(r, today)
        if st == "in":
            db.execute("UPDATE paper_items SET status='in', tier=?, why=? WHERE id=?", [tier, why, r["id"]])
            got.append(r["s2id"])
        elif (tier, why) != (r["tier"], r["why"]):
            db.execute("UPDATE paper_items SET tier=?, why=? WHERE id=?", [tier, why, r["id"]])
    return got


def weekly(on_step=lambda s: None) -> dict:
    """刷新被引 → 重判门槛 → 新收的补详情、过 Jev → 标注队列（新收的 + 要重标 builds_on 的）。"""
    stat = {"checked": 0, "changed": 0, "admitted": 0, "labeled": 0, "relabel": 0, "cost": 0.0, "errors": []}
    if not db.row("SELECT 1 FROM paper_items WHERE status='in' LIMIT 1"):
        return stat | {"skipped": "论文库还是空的"}
    ids = targets()
    stat["checked"] = len(ids)
    with col.client() as c:
        stat["changed"] = refresh_cites(ids, c, on_step)
        on_step("重判门槛")
        new = promote()
        if new:
            on_step(f"补 {len(new)} 篇新论文的摘要和参考文献")
            col.fetch_details(c, ids=new)
    if any((db.row("SELECT tier FROM paper_items WHERE s2id=?", [s]) or {}).get("tier") == "recent" for s in new):
        on_step("Jev 判近期论文是不是水文")
        try:
            lab.judge_recent()
        except Exception as e:  # noqa: BLE001
            stat["errors"].append(f"Jev：{type(e).__name__}: {str(e)[:120]}")
        new = [s for s in new if (db.row("SELECT status FROM paper_items WHERE s2id=?", [s]) or {}).get("status") == "in"]
    stat["admitted"] = len(new)
    queue = lab.todo(LABEL_CAP)          # 新收的 + 参考文献里多了新论文的（builds_on 要重标），按被引排
    fresh = set(new)
    stat["relabel"] = sum(r["s2id"] not in fresh for r, _ in queue)
    on_step(f"标注 {len(queue)} 篇")
    st = lab.run(items=queue)
    stat |= {"labeled": st["labeled"], "cost": st["cost"], "errors": stat["errors"] + st["errors"][-5:],
             "left": len(lab.todo())}       # 没标完的（超了 LABEL_CAP 或失败的）下次接着标
    return stat


def last(kind: str) -> dict | None:
    r = db.row("SELECT * FROM paper_runs WHERE kind=? ORDER BY id DESC LIMIT 1", [kind])
    return r and r | {"result": json.loads(r["result"] or "{}")}


def due(now: datetime | None = None) -> bool:
    days = float(settings.get("paper.maintain_days", 7) or 0)
    if days <= 0 or not db.row("SELECT 1 FROM paper_items WHERE status='in' LIMIT 1"):
        return False
    r = db.row("SELECT started FROM paper_runs WHERE kind='weekly' AND status!='failed' ORDER BY id DESC LIMIT 1")
    if not r:
        return True
    return (now or datetime.now()) - datetime.fromisoformat(r["started"]) >= timedelta(days=days)


def start(force: bool = False) -> bool:
    """后台跑一次每周维护；已在跑返回 False。force=False 时没到期也返回 False。"""
    init()
    if not (force or due()) or not _lock.acquire(blocking=False):
        return False

    def go():
        try:
            record("weekly", weekly)
        except Exception:  # noqa: BLE001  已记在 paper_runs
            log.exception("论文库每周维护失败")
        finally:
            _lock.release()
    threading.Thread(target=go, daemon=True, name="paper-maintain").start()
    return True


def status() -> dict:
    """页面顶部的维护状态：两种运行各自最近一次；同一种最近 ALERT_FAILS 次都失败就 alert。"""
    init()
    out = {"running": _lock.locked()}
    for kind in ("feed", "weekly"):
        rs = db.rows("SELECT status FROM paper_runs WHERE kind=? AND status!='running' ORDER BY id DESC LIMIT ?", [kind, ALERT_FAILS])
        out[kind] = last(kind)
        out[f"{kind}_alert"] = len(rs) == ALERT_FAILS and all(r["status"] == "failed" for r in rs)
    return out
