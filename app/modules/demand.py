"""需求图谱：把产品雷达里的创业公司 / PH 日榜 / 增长 Case 逐产品抽成需求卡（目标用户、场景、痛点、产品、增长手段），按场景大小聚成知识图谱。
流水线在 _demand_run.py，作为独立进程跑；这里只负责发起、报进度、读结果。结果在 data/demand/。"""
import json
import os
import subprocess
import sys

from fastapi import APIRouter, HTTPException

from .. import agent
from ..db import ROOT
from . import _demand_run as dr

TITLE = "需求图谱"
PAGE = "intel/demand"
router = APIRouter()
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
            "cards": {k: v for k, v in cards.items() if not v.get("skip")} if g else {}, "n_cards": sum(not v.get("skip") for v in cards.values())}


def start(graph_only: bool = False, max_new: int = 0) -> bool:
    st = dr._load("status.json", {})
    if not st.get("finished", True) and _alive(st.get("pid")):
        return False
    dr.BASE.mkdir(parents=True, exist_ok=True)
    args = (["--graph-only"] if graph_only else []) + (["--max-new", str(max_new)] if max_new else [])
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
        return "需求图谱还没生成。"
    cards = dr._load("cards.json", {})
    return json.dumps([{"大场景": sc["name"], "总结": sc["summary"], "子场景": [{"name": sb["name"], "痛点": sb["pain"], "产品": [
        {k: cards[p].get(k) for k in ("name", "user", "scene", "pain", "growth", "tactics")} for p in sb["products"]]} for sb in sc["subs"]]} for sc in g["scenes"]], ensure_ascii=False)[:60000]
