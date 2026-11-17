"""吸收：按选题把一段时间的 X 长文压成认知卡，对照知识库里“我的判断”和论文 / 开源项目 / 产品动态 / 讨论，标出挑战你判断的、有争议的、印证你判断的、与你判断相关的和新的。
流水线在 _absorb_run.py，作为独立进程跑，每个选题一个目录 data/absorb/<选题>_<起>_<止>/；这里只负责发起、报进度、读结果、存表态。
表态存在该目录的 reactions.json，不进 app.db。"""
import json
import os
import re
import subprocess
import sys
import time

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import agent
from ..db import ROOT
from . import _absorb_run as ar

TITLE = "吸收"
ORDER = 32
router = APIRouter()

ACTS = ("已知", "采纳", "不信", "想试")
PROCS: dict[int, subprocess.Popen] = {}


def _dir(rid: str):
    d = ar.BASE / rid
    if "/" in rid or rid.startswith(".") or not (d / "run.json").exists():
        raise HTTPException(404, "没有这次运行")
    return d


def _read(p, default):
    try:
        return json.loads(p.read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _alive(pid) -> bool:
    p = PROCS.get(pid)
    if p and p.poll() is not None:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, TypeError, ValueError):
        return False


def _state(d) -> dict:
    st = _read(d / "status.json", {})
    done = bool(st.get("done")) and (d / "cards.json").exists()
    running = not done and _alive(st.get("pid"))
    return {"done": done, "running": running, "stage_name": st.get("stage_name", ""), "step": st.get("step", 0), "steps": st.get("steps", len(ar.STAGES)),
            "error": "" if done or running else st.get("error") or "进程中断了，重新发起会从断点接着跑",
            "cost": round(sum((st.get("cost") or {}).values()), 2), "started": st.get("started"), "updated": st.get("updated")}


@router.get("/runs")
def runs():
    out = []
    for f in ar.BASE.glob("*/run.json"):
        out.append({"id": f.parent.name, **_read(f, {}), **_state(f.parent)})
    return sorted(out, key=lambda x: -(x.get("created") or 0))


@router.get("/topics")
def topics():
    return sorted(p.stem for p in (ar.KB / "topics").glob("*.md"))


@router.get("/preflight")
def preflight(start: str, end: str):
    rows = ar._ro().execute("select day, count(*), coalesce(sum(kind!=''), 0) from x_art where day between ? and ? group by day order by day", (start, end)).fetchall()
    return {"total": sum(x[1] for x in rows), "classified": sum(x[2] for x in rows), "gaps": [x[0] for x in rows if x[2] * 20 < x[1]]}


class RunIn(BaseModel):
    topic: str
    start: str
    end: str


@router.post("/runs")
def start(body: RunIn):
    topic = body.topic.strip()
    if not topic or not all(re.fullmatch(r"\d{4}-\d\d-\d\d", x) for x in (body.start, body.end)) or body.start > body.end:
        raise HTTPException(400, "选题和起止日期要填全，开始不能晚于结束")
    d = ar.BASE / ar.slug(topic, body.start, body.end)
    if d.exists() and _state(d)["running"]:
        raise HTTPException(409, "这个选题正在跑")
    r = ar.Run(topic, body.start, body.end)
    with open(d / "run.log", "a") as log:
        p = subprocess.Popen([sys.executable, "-m", "app.modules._absorb_run", f"--topic={topic}", "--start", body.start, "--end", body.end],
                             cwd=str(ROOT), env=agent.clean_env(), stdout=log, stderr=log, start_new_session=True)
    PROCS[p.pid] = p
    r.save("status.json", {**_read(d / "status.json", {}), "pid": p.pid, "steps": len(ar.STAGES), "done": False, "error": ""})
    return {"id": d.name}


@router.get("/runs/{rid}")
def get(rid: str):
    d = _dir(rid)
    st = _state(d)
    data = _read(d / "cards.json", None) if st["done"] else None
    return {"id": rid, **_read(d / "run.json", {}), **st, "data": data, "reactions": _read(d / "reactions.json", {})}


class ReactIn(BaseModel):
    card: int
    act: str = ""


@router.post("/runs/{rid}/react")
def react(rid: str, body: ReactIn):
    d = _dir(rid)
    if body.act and body.act not in ACTS:
        raise HTTPException(400, "表态只能是：" + " / ".join(ACTS))
    r = _read(d / "reactions.json", {})
    if body.act:
        r[str(body.card)] = {"act": body.act, "at": time.time()}
    else:
        r.pop(str(body.card), None)
    tmp = d / "reactions.json.tmp"
    tmp.write_text(json.dumps(r, ensure_ascii=False), "utf-8")
    tmp.replace(d / "reactions.json")
    return {"ok": True}
