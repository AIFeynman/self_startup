"""吸收：按选题把一段时间的 X 长文压成认知卡，对照论文 / 开源项目 / 产品动态 / 讨论，按独立来源的人数和佐证给出每条认知的置信度，标出有争议的。
流水线在 _absorb_run.py，作为独立进程跑，每个选题一个目录 data/absorb/<选题>_<起>_<止>/；这里只负责发起、报进度、读结果、存表态。
表态存在该目录的 reactions.json（页面状态），同时追加到 data/absorb/_feedback.jsonl（带卡片快照，换选题、重跑、删目录都不丢），供“反馈”页按提炼角度分析哪类认知对你有用，不进 app.db。"""
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

ACTS = ("没增量", "有收获", "很受用", "会用上")
BENEFIT = {a: i for i, a in enumerate(ACTS)}
FB = ar.BASE / "_feedback.jsonl"
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


def _snap(d, rid: str, card: int) -> dict:
    cards = _read(d / "cards.json", {}).get("cards", [])
    c = next((x for x in cards if x["id"] == card), None)
    if not c:
        return {}
    t, w = c.get("type"), c.get("w")
    if not t or not w:
        merged, qd = _read(d / "merged.json", {}), _read(d / "questions.json", {})
        try:
            u = qd["U"][merged["C"][card]["rep"]]
            t, w = t or u["type"], w or u.get("w", 0)
        except (KeyError, IndexError):
            t, w = t or "", w or 0
    g = c.get("conf") or {}
    q = next((x["q"] for x in _read(d / "cards.json", {}).get("questions", []) if x["id"] == c["qid"]), "")
    return {"run": rid, "topic": _read(d / "run.json", {}).get("topic", ""), "card": card, "claim": c["claim"], "type": t, "tag": c["tag"], "level": g.get("level", ""),
            "authors": len(c.get("authors", [])), "first": g.get("first", 0), "hard": g.get("papers", 0) + g.get("repos", 0) + g.get("intel", 0), "disc": g.get("disc", 0),
            "against": g.get("against", 0), "has_num": bool(re.search(r"\d", c["claim"])), "w": w,
            "len": len(c["claim"]), "qid": c["qid"], "question": q}


def _log(ev: dict) -> None:
    with open(FB, "a", encoding="utf-8") as f:
        f.write(json.dumps(ev, ensure_ascii=False) + "\n")


class ReactIn(BaseModel):
    card: int
    act: str = ""


@router.post("/runs/{rid}/react")
def react(rid: str, body: ReactIn):
    d = _dir(rid)
    if body.act and body.act not in ACTS:
        raise HTTPException(400, "表态只能是：" + " / ".join(ACTS))
    r = _read(d / "reactions.json", {})
    snap = _snap(d, rid, body.card)
    if snap:
        _log({**snap, "act": body.act, "at": time.time()})
    if body.act:
        r[str(body.card)] = {"act": body.act, "at": time.time()}
    else:
        r.pop(str(body.card), None)
    tmp = d / "reactions.json.tmp"
    tmp.write_text(json.dumps(r, ensure_ascii=False), "utf-8")
    tmp.replace(d / "reactions.json")
    return {"ok": True}


def _latest() -> list[dict]:
    last = {}
    if FB.exists():
        for line in FB.read_text("utf-8").splitlines():
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            last[(e.get("run"), e.get("claim"))] = e
    return [e for e in last.values() if e.get("act") in ACTS]


DIMS = [("type", "认知类型", lambda e: e.get("type") or "未知"),
        ("level", "置信度", lambda e: {"h": "高", "m": "中", "l": "低"}.get(e.get("level"), "—") + ("（有争议）" if e.get("tag") == "c" else "")),
        ("authors", "独立作者数", lambda e: "1 位" if e.get("authors", 0) <= 1 else "2 位及以上"),
        ("hard", "有论文 / 项目 / 产品佐证", lambda e: "有" if e.get("hard") else "没有"),
        ("has_num", "结论里带数字", lambda e: "带" if e.get("has_num") else "不带"),
        ("w", "重要度", lambda e: {3: "文章核心主张", 2: "重要结论"}.get(e.get("w"), "未标注")),
        ("len", "结论长度", lambda e: "≤40 字" if e.get("len", 0) <= 40 else "41–70 字" if e.get("len", 0) <= 70 else "70 字以上"),
        ("topic", "选题", lambda e: e.get("topic") or "—")]


@router.get("/feedback")
def feedback():
    ev = _latest()
    dims = []
    for key, name, f in DIMS:
        b: dict[str, dict] = {}
        for e in ev:
            x = b.setdefault(f(e), {"n": 0, **{a: 0 for a in ACTS}})
            x["n"] += 1
            x[e["act"]] += 1
        rows = [{"v": v, **x, "gain": round(sum(BENEFIT[a] * x[a] for a in ACTS) / x["n"], 2), "useful": round((x["很受用"] + x["会用上"]) / x["n"], 2),
                 "try": round(x["会用上"] / x["n"], 2), "none": round(x["没增量"] / x["n"], 2)} for v, x in b.items()]
        dims.append({"key": key, "name": name, "rows": sorted(rows, key=lambda r: -r["n"])})
    pick = lambda act: [{"claim": e["claim"], "type": e.get("type", ""), "topic": e.get("topic", "")} for e in sorted(ev, key=lambda e: -e["at"]) if e["act"] == act][:8]
    return {"n": len(ev), "acts": {a: sum(e["act"] == a for e in ev) for a in ACTS}, "dims": dims, "try": pick("会用上"), "none": pick("没增量")}
