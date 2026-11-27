"""产品需求（原需求图谱）：把产品雷达里的创业公司 / PH 日榜 / 增长 Case 逐产品抽成需求卡（目标用户、场景、痛点、产品、增长手段），按场景大小聚成知识图谱。
流水线在 _demand_run.py，作为独立进程跑；这里只负责发起、报进度、读结果。结果在 data/demand/。"""
import json
import os
import subprocess
import sys

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import agent, db
from ..db import ROOT
from . import _demand_mid, _demand_run as dr, _read_log

TITLE = "产品需求"
PAGE = "kb/demand"  # 没有自己的侧边栏入口，是知识库里的一个标签页
router = APIRouter()
SCHEMA = """
CREATE TABLE IF NOT EXISTS demand_seen (k TEXT PRIMARY KEY, name TEXT DEFAULT '', at TEXT NOT NULL);
"""
PROC: list[subprocess.Popen] = []


def _alive(pid) -> bool:
    if PROC and PROC[0].pid == pid and PROC[0].poll() is not None:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, TypeError, ValueError):
        return False


@router.get("/graph")
def graph():
    st = dr._load("status.json", {})
    g = dr._load("graph.json", None)
    cards = dr._load("cards.json", {})
    running = not st.get("finished", True) and _alive(st.get("pid"))
    pending = len([k for k in dr.collect() if k not in cards]) if g else 0
    return {"pending": pending, "status": {**st, "running": running, "error": "" if running else st.get("error", "")}, "graph": g,
            "watch": {"logs": dr._load("watch_log.json", [])[-4:], "sources": list(dr._load("sources.json", {}).values())},
            "chain": dr._load("chain.json", {}),
            "cards": {k: {**v, "tier": _demand_mid.tier(v)} for k, v in cards.items() if not v.get("skip")} if g else {}, "n_cards": sum(not v.get("skip") for v in cards.values())}


def start(graph_only: bool = False, max_new: int = 0, enrich: int = 0, watch: float = 0, deep: float = 0) -> bool:
    st = dr._load("status.json", {})
    if not st.get("finished", True) and _alive(st.get("pid")):
        return False
    dr.BASE.mkdir(parents=True, exist_ok=True)
    args = (["--graph-only"] if graph_only else []) + (["--max-new", str(max_new)] if max_new else []) + (["--enrich", str(enrich)] if enrich else []) + (["--watch", str(watch)] if watch else []) + (["--deep", str(deep)] if deep else [])
    with open(dr.BASE / "run.log", "a") as log:
        p = subprocess.Popen([sys.executable, "-m", "app.modules._demand_run", *args], cwd=str(ROOT), env=agent.clean_env(), stdout=log, stderr=log, start_new_session=True)
    PROC[:] = [p]
    dr._save("status.json", {**st, "pid": p.pid, "finished": False, "error": "", "stage": "start"})
    return True


@router.post("/run")
def run(graph_only: bool = False):
    if not start(graph_only):
        raise HTTPException(409, "正在跑")
    return {"ok": True}


def agent_context(ref: str) -> str:
    g = dr._load("graph.json", None)
    if not g:
        return "产品需求还没生成。"
    cards = dr._load("cards.json", {})
    return json.dumps([{"大场景": sc["name"], "总结": sc["summary"], "子场景": [{"name": sb["name"], "痛点": sb["pain"], "产品": [
        {k: cards[p].get(k) for k in ("name", "user", "scene", "pain", "growth", "tactics")} for p in sb["products"]]} for sb in sc["subs"]]} for sc in g["scenes"]], ensure_ascii=False)[:60000]


class SeenIn(BaseModel):
    seen: bool
    name: str = ""


@router.put("/seen/{k}")
def mark_seen(k: str, body: SeenIn):
    """全貌面板里标「看过」；第一次标时记一条已读（进复盘时间线）。取消只删标记，已读历史保留。"""
    if not body.seen:
        db.execute("DELETE FROM demand_seen WHERE k=?", [k])
        return {"ok": True}
    if not db.row("SELECT 1 FROM demand_seen WHERE k=?", [k]):
        db.execute("INSERT INTO demand_seen (k, name, at) VALUES (?, ?, ?)", [k, body.name, db.now()])
        _read_log.log("demand", k, body.name, f"#kb/demand/{body.name}", "产品需求")
    return {"ok": True}


@router.get("/activity")
def activity():
    """每家公司的看过时间，和评论 / 问 Claude 的记录数（批注 doc = demand:<key>）。"""
    seen = {r["k"]: r["at"] for r in db.rows("SELECT k, at FROM demand_seen")}
    notes = {}
    for r in db.rows("SELECT a.doc, count(DISTINCT a.id) threads, max(a.updated_at) last, "
                     "(SELECT count(*) FROM annotation_msgs m JOIN annotations b ON b.id=m.annotation_id WHERE b.doc=a.doc AND m.role='assistant') asks "
                     "FROM annotations a WHERE a.doc LIKE 'demand:%' GROUP BY a.doc"):
        notes[r["doc"].removeprefix("demand:")] = {"threads": r["threads"], "asks": r["asks"], "last": r["last"]}
    return {"seen": seen, "notes": notes}
