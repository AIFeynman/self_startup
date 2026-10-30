"""Agent 看板：本地 Claude Code / Codex 会话 + 平台后台任务的进度流转看板（解析在 _agents_scan.py）。

列：running 运行中 → attention 等你处理 → review 待验收 → done 已验收（另有 archived 归档，默认隐藏）。
前三列由日志自动判断；「已验收 / 归档」是用户操作，存在 agent_board 表里。
会话之后又有新活动（比如你续聊了），用户标记自动失效，卡片回到自动判断的列。
"""
from __future__ import annotations

import json
import logging
import re
import shlex
import subprocess
import threading
import time
from datetime import date as Date, datetime, timedelta

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import chat, db, jobs, settings, tasks
from . import _agents_scan as scanner, _deliveries as deliv, _utilization as util

TITLE = "Agent 看板"
ORDER = 8
SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_board (
    key         TEXT PRIMARY KEY,          -- claude:<session> / codex:<session> / job:<id>
    col         TEXT DEFAULT '',           -- done / archived / ''（自动）
    note        TEXT DEFAULT '',
    task_id     INTEGER,                   -- 关联的规划事项；验收时一并标记完成
    updated_at  TEXT
);
-- 每天的时间利用快照（真实事件 → 时间片），供复盘 / 规划 / 知识库使用
-- 每天的交付快照（看板 / 复盘读取时更新），供知识库每日记录使用
CREATE TABLE IF NOT EXISTS agent_delivery (
    date        TEXT PRIMARY KEY,
    data        TEXT DEFAULT '{}',
    updated_at  TEXT
);
CREATE TABLE IF NOT EXISTS agent_util (
    date        TEXT PRIMARY KEY,
    summary     TEXT DEFAULT '{}',
    data        TEXT DEFAULT '{}',          -- slots / gaps / humans / top_waits / advice
    updated_at  TEXT
);
"""
COLUMNS = [("running", "运行中"), ("attention", "等你处理"), ("review", "待验收"), ("done", "已验收")]
OUT_STATUS = {"delivered": "已交付", "changed_after": "交付后仍在改", "committed": "已提交未推送"}
router = APIRouter()


def _job_cards(hours: float) -> list[dict]:
    since = (datetime.now() - timedelta(hours=hours)).isoformat(timespec="seconds")
    out = []
    for j in db.rows("SELECT id,module,ref,engine,status,prompt,output,log,created_at,started_at,finished_at,fallback_from FROM jobs "
                     "WHERE created_at>=? ORDER BY id DESC LIMIT 100", [since]):
        last = j["finished_at"] or j["started_at"] or j["created_at"]
        state, reason = {"queued": ("running", "排队中"), "running": ("running", "执行中"),
                         "done": ("review", "已完成"), "failed": ("attention", "失败")}.get(j["status"], ("review", j["status"]))
        title, link, kind = jobs.describe(j)
        # 跑的过程中 output 还是空的：拿日志最后几步当进展
        steps = [ln.strip() for ln in (j["log"] or "").splitlines() if ln.strip().startswith("[tool]")]
        doing = scanner._clip(steps[-1].removeprefix("[tool]").strip(), 120) if steps else ""
        if j["status"] in ("queued", "running"):
            reason += f" · 已执行 {len(steps)} 步" if steps else ""
        need = jobs.needs_you(j["output"]) if j["status"] == "done" else []
        if need:
            state, reason = "attention", f"待你审批 {len(need)} 项：{need[0][:60]}"
        if j.get("fallback_from"):
            reason += f" · {j['fallback_from']} 未跑通，已由 {j['engine']} 代跑"
        out.append({"key": f"job:{j['id']}", "engine": "platform", "session_id": str(j["id"]), "project": j["module"],
                    "cwd": "", "branch": "", "title": scanner._clip(f"{kind} · {title}", 80), "link": link,
                    "last_human": "", "last_agent": scanner._clip(j["output"] or "") or (f"正在：{doing}" if doing else ""),
                    "plan": [], "plan_done": 0, "plan_current": doing if j["status"] in ("queued", "running") else "", "needs": need,
                    "humans": 0, "tools": 0, "automated": False, "start": j["created_at"], "last": last,
                    "idle_min": round((datetime.now() - datetime.fromisoformat(last)).total_seconds() / 60, 1),
                    "state": state, "reason": reason, "error": "", "file": ""})
    return out


_OUT_CACHE: dict = {"at": 0.0, "days": (), "map": {}}


def _card_outputs(days: tuple[str, ...]) -> dict[str, dict]:
    """会话 key → 产出（推送 / PR / 部署 / 提交 / 文档）。扫描较慢，缓存 60 秒；同一会话取最近一天。"""
    if _OUT_CACHE["days"] == days and time.time() - _OUT_CACHE["at"] < 60:
        return _OUT_CACHE["map"]
    out: dict[str, dict] = {}
    for day in sorted(days):
        try:
            items = deliv.scan(settings.get("session_dirs", {}), Date.fromisoformat(day), skip_cwd=str(db.DATA_DIR)) + _job_deliveries(day)
        except Exception:  # noqa: BLE001
            continue
        for x in items:
            out[x["key"]] = {"status": x["status"], "labels": x["labels"], "at": x["at"], "day": day,
                             "docs_total": x.get("docs_total", 0), "dirty": x.get("dirty"), "link": x.get("link", "")}
    _OUT_CACHE.update(at=time.time(), days=days, map=out)
    return out


def board(hours: float = 24, automated: bool = False) -> dict:
    cards = scanner.scan(settings.get("session_dirs", {}), hours) + _job_cards(hours)
    marks = {r["key"]: r for r in db.rows("SELECT * FROM agent_board")}
    now = datetime.now()
    days = tuple(sorted({(now - timedelta(hours=h)).date().isoformat() for h in (0, min(hours, 24))}))
    outputs = _card_outputs(days)
    hidden_auto, archived = 0, 0
    cols: dict[str, list] = {c: [] for c, _ in COLUMNS}
    for c in cards:
        c["output"] = outputs.get(c["key"])
        m = marks.get(c["key"])
        col = c["state"]
        if m:
            c.update(note=m["note"] or "", task_id=m["task_id"])
            # 用户标记只在会话之后没有新活动时有效
            if m["col"] and (m["updated_at"] or "") >= c["last"]:
                col = m["col"]
        if col == "archived":
            archived += 1
            continue
        if c["automated"] and not automated and col != "done":
            hidden_auto += 1
            continue
        c["column"] = col
        cols.setdefault(col, []).append(c)
    return {"columns": [{"id": k, "title": t, "cards": cols.get(k, [])} for k, t in COLUMNS],
            "hidden_automated": hidden_auto, "archived": archived, "hours": hours, "generated_at": db.now()}


@router.get("/board")
def get_board(hours: float = 24, automated: bool = False):
    return board(hours, automated)


class StateIn(BaseModel):
    key: str
    col: str | None = None      # done / archived / ''（恢复自动）
    note: str | None = None
    task_id: int | None = None


@router.post("/state")
def set_state(body: StateIn):
    if body.col not in (None, "", "done", "archived"):
        raise HTTPException(400, "col must be done / archived / ''")
    cur = db.row("SELECT * FROM agent_board WHERE key=?", [body.key]) or {"key": body.key, "col": "", "note": "", "task_id": None}
    new = {"col": cur["col"] if body.col is None else body.col,
           "note": cur["note"] if body.note is None else body.note,
           "task_id": cur["task_id"] if body.task_id is None else (body.task_id or None)}
    db.execute("INSERT INTO agent_board(key,col,note,task_id,updated_at) VALUES (?,?,?,?,?) "
               "ON CONFLICT(key) DO UPDATE SET col=excluded.col, note=excluded.note, task_id=excluded.task_id, updated_at=excluded.updated_at",
               [body.key, new["col"], new["note"], new["task_id"], db.now()])
    if new["col"] == "done" and new["task_id"]:
        try:
            tasks.patch(int(new["task_id"]), {"status": "done", "progress": 100})
        except HTTPException:
            pass
    return {"key": body.key, **new}


def resume_command(key: str, cwd: str) -> str:
    engine, sid = key.split(":", 1)
    cd = f"cd {shlex.quote(cwd)} && " if cwd else ""
    if engine == "claude":
        return f"{cd}{settings.get('engines.claude.bin', 'claude')} --resume {sid}"
    if engine == "codex":
        return f"{cd}codex resume {sid}"
    raise HTTPException(400, "只有 Claude Code / Codex 会话可以续接")


class OpenIn(BaseModel):
    key: str
    cwd: str = ""


@router.post("/resume-command")
def get_resume_command(body: OpenIn):
    return {"command": resume_command(body.key, body.cwd)}


@router.post("/open")
def open_terminal(body: OpenIn):
    """在 macOS 终端里打开并续接这个会话（用户点击触发）。"""
    cmd = resume_command(body.key, body.cwd)
    script = f'tell application "Terminal" to do script "{cmd.replace(chr(92), chr(92) * 2).replace(chr(34), chr(92) + chr(34))}"'
    try:
        subprocess.run(["osascript", "-e", script, "-e", 'tell application "Terminal" to activate'], check=True,
                       capture_output=True, timeout=10)
    except (subprocess.SubprocessError, FileNotFoundError) as e:
        raise HTTPException(500, f"打开终端失败：{e}")
    return {"ok": True, "command": cmd}


def agent_context(ref: str) -> str:
    b = board(24)
    lines = [f"最近 24 小时（{b['generated_at']}），隐藏脚本会话 {b['hidden_automated']} 个、归档 {b['archived']} 个："]
    for col in b["columns"]:
        lines.append(f"\n## {col['title']}（{len(col['cards'])}）")
        for c in col["cards"][:15]:
            plan = f" · 计划 {c['plan_done']}/{len(c['plan'])} 当前：{c['plan_current']}" if c["plan"] else ""
            o = c.get("output")
            plan += f" · 产出：{OUT_STATUS.get(o['status'], o['status'])} {'/'.join(o['labels'])} {o['at']}" if o else " · 产出：暂无"
            lines.append(f"- [{c['engine']}] {c['project']} · {c['title']} · {c['reason']} · {c['idle_min']} 分钟前{plan}"
                         f" · key={c['key']}\n  最近要求：{c['last_human'][:120]}\n  最近回复：{c['last_agent'][:160]}")
    try:
        lines.append("\n## 今日已交付（推送 / 部署 / PR / 发布 / 文档材料，之后没再改代码）\n" + deliveries_text())
    except Exception:  # noqa: BLE001
        pass
    try:
        lines.append("\n## 时间利用\n" + planning_insights())
    except Exception:  # noqa: BLE001
        pass
    return "\n".join(lines)


# ---------- 今日已交付 ----------

def _job_deliveries(day: str) -> list[dict]:
    """平台后台任务里有交付物的：深读笔记、学习计划、调研报告（完成即交付）。"""
    out, synth = [], set()
    for j in db.rows("SELECT id,module,ref,prompt,finished_at FROM jobs WHERE status='done' AND substr(finished_at,1,10)=? "
                     "AND (ref LIKE 'learn:%' OR ref LIKE 'research:%') ORDER BY id DESC", [day]):
        rid = (re.match(r"research:(\d+):", j["ref"]) or [None, None])[1]
        if rid and (rid in synth or j["ref"].endswith("synth") and synth.add(rid)):
            continue  # 同一调研有综合报告时，只列综合报告
        title, link, label = jobs.describe(j)
        out.append({"key": f"job:{j['id']}", "engine": "platform", "status": "delivered", "kind": "doc",
                    "kinds": [], "labels": [label], "at": (j["finished_at"] or "")[11:16], "project": "学习平台 · " + j["module"],
                    "title": scanner._clip(title, 80), "link": link, "summary": "", "docs": [], "docs_total": 0,
                    "commands": [], "automated": False, "cwd": "", "branch": ""})
    return out


def deliveries(day: str = "", automated: bool = False) -> dict:
    """某天的交付：delivered 已交付 / changed_after 交付后仍有改动 / committed 已提交未推送。"""
    day = day or db.today()
    items = deliv.scan(settings.get("session_dirs", {}), Date.fromisoformat(day), skip_cwd=str(db.DATA_DIR)) + _job_deliveries(day)
    hidden = sum(1 for x in items if x["automated"]) if not automated else 0
    items = [x for x in items if automated or not x["automated"]]
    items.sort(key=lambda x: x["at"], reverse=True)
    groups = {k: [x for x in items if x["status"] == k] for k in ("delivered", "changed_after", "committed")}
    out = {"date": day, **groups, "counts": {k: len(v) for k, v in groups.items()}, "hidden_automated": hidden,
           "generated_at": db.now()}
    keep = ("at", "labels", "project", "title", "docs", "docs_total", "link", "summary")
    db.execute("INSERT INTO agent_delivery(date,data,updated_at) VALUES (?,?,?) ON CONFLICT(date) DO UPDATE SET "
               "data=excluded.data, updated_at=excluded.updated_at",
               [day, json.dumps({k: [{f: x.get(f) for f in keep} for x in groups[k]] for k in groups}, ensure_ascii=False), db.now()])
    return out


def deliveries_text(day: str = "") -> str:
    """给复盘 / 规划 / 知识库用的纯文本。"""
    d = deliveries(day)
    def line(x):
        extra = f" · 文档 {x['docs_total']} 份" if x["docs_total"] else ""
        return f"- {x['at']} [{'/'.join(x['labels'])}] {x['project']} · {x['title']}{extra}"
    parts = []
    for k, t in (("delivered", "已交付"), ("changed_after", "交付后仍有改动（未完）"), ("committed", "已提交未推送")):
        if d[k]:
            parts.append(f"{t}（{len(d[k])}）：\n" + "\n".join(line(x) for x in d[k]))
    return "\n".join(parts) or "当天没有检测到交付（推送 / 部署 / PR / 发布 / 文档材料）。"


@router.get("/deliveries")
def get_deliveries(date: str = "", automated: bool = False):
    return deliveries(date, automated)


# ---------- 时间利用 ----------

def _final(row: dict | None) -> bool:
    """快照是在那天结束之后、用当前口径算的（当天算的快照只是半天的数据；旧口径的快照也要重算）。"""
    return (bool(row) and (row["updated_at"] or "") >= (Date.fromisoformat(row["date"]) + timedelta(days=1)).isoformat()
            and json.loads(row["summary"] or "{}").get("v") == util.VERSION
            and json.loads(row["summary"] or "{}").get("tz") == time.tzname[0])   # 换了时区（含自动推断）要重算


def utilization(day: str = "", refresh: bool = False) -> dict:
    """某天的时间利用分析。今天每次重算（有缓存，很快）；过去的日子在当天结束后算一次存下来。"""
    day = day or db.today()
    row = db.row("SELECT * FROM agent_util WHERE date=?", [day])
    if not refresh and day != db.today() and _final(row):
        return {**json.loads(row["data"]), "summary": json.loads(row["summary"]), "cached": True}
    cfg = settings.load()
    r = util.analyze(Date.fromisoformat(day), cfg.get("session_dirs", {}), cfg["focus_windows"], cfg["day_start"],
                     cfg["day_end"], int(cfg.get("max_agent_concurrency", 3)), chat_ids=chat.engine_sessions())
    db.execute("INSERT INTO agent_util(date,summary,data,updated_at) VALUES (?,?,?,?) ON CONFLICT(date) DO UPDATE SET "
               "summary=excluded.summary, data=excluded.data, updated_at=excluded.updated_at",
               [day, json.dumps(r["summary"], ensure_ascii=False),
                json.dumps({k: v for k, v in r.items() if k != "summary"}, ensure_ascii=False), db.now()])
    return r


_filling = threading.Lock()


def _fill(days: list[str]) -> None:
    if not _filling.acquire(blocking=False):
        return
    try:
        for d in days:
            try:
                utilization(d)
            except Exception:  # noqa: BLE001
                pass
    finally:
        _filling.release()


def patterns(days: int = 7) -> dict:
    """近 N 天的规律：每小时平均有几个 Agent 在跑、人工交互几次、等你几个；反复出现的空档。"""
    today = datetime.now().date()
    want = [(today - timedelta(days=i)).isoformat() for i in range(1, days + 1)]
    have = {r["date"]: r for r in db.rows(f"SELECT * FROM agent_util WHERE date IN ({','.join('?' * len(want))})", want)}
    missing = [d for d in want if not _final(have.get(d))]
    if missing:  # 过去的日子在后台补算，不阻塞页面
        threading.Thread(target=_fill, args=(missing,), daemon=True).start()
    hours = {h: {"agents": 0.0, "humans": 0, "waiting": 0.0, "days": 0} for h in range(24)}
    idle_hours: dict[int, int] = {}
    sums = []
    for d, r in have.items():
        data, summ = json.loads(r["data"]), json.loads(r["summary"])
        if not summ.get("sessions"):
            continue
        sums.append(summ)
        seen = set()
        for sl in data.get("slots", []):
            h = int(sl["t"][:2])
            hours[h]["agents"] += (sl["interactive"] + sl["automated"]) * util.SLOT_MIN / 60
            hours[h]["humans"] += sl["humans"]
            hours[h]["waiting"] += sl["waiting"] * util.SLOT_MIN / 60
            seen.add(h)
        for h in seen:
            hours[h]["days"] += 1
        for g in data.get("gaps", []):
            for h in range(int(g["start"][:2]), int(g["end"][:2]) + (1 if g["end"][3:] != "00" else 0)):
                idle_hours[h] = idle_hours.get(h, 0) + 1
    n = max(1, len(sums))
    hourly = [{"hour": h, "agents": round(v["agents"] / n, 2), "humans": round(v["humans"] / n, 1), "waiting": round(v["waiting"] / n, 2)}
              for h, v in hours.items()]
    avg = lambda k: round(sum(s.get(k, 0) for s in sums) / n, 1) if sums else 0  # noqa: E731
    return {"days": len(sums), "filling": bool(missing), "hourly": hourly,
            "recurring_idle_hours": sorted(h for h, c in idle_hours.items() if c >= max(2, len(sums) // 2)),
            "avg": {k: avg(k) for k in ("coverage_pct", "coverage_work_pct", "capacity_pct", "idle_min", "human_total",
                                        "human_out_focus", "wait_total_min", "wait_wall_min")}}


def planning_insights() -> str:
    """给规划用的一段话：今天到目前的利用情况 + 近 7 天规律。"""
    lines = []
    try:
        t = utilization()
        s = t["summary"]
        lines.append(f"今天到目前（统计 {s['elapsed_min']} 分钟，其中工作时间 {s.get('work_elapsed_min', 0)} 分钟）："
                     f"Agent 覆盖 {s['coverage_pct']}%（工作时间内 {s.get('coverage_work_pct', 0)}%）、并发容量使用 {s['capacity_pct']}%、"
                     f"空档 {s['idle_min']} 分钟；人工交互 {s['human_total']} 次（专注外 {s['human_out_focus']}）；"
                     f"Agent 等你 {s.get('wait_wall_min', s['wait_total_min'])} 分钟（各会话累加 {s['wait_total_min']} Agent·分钟）。")
        lines += [f"- {a}" for a in t["advice"][:4]]
    except Exception:  # noqa: BLE001
        pass
    p = patterns(7)
    if p["days"]:
        a = p["avg"]
        busy_h = sorted(p["hourly"], key=lambda x: -x["humans"])[:3]
        lines.append(f"近 {p['days']} 天平均：覆盖 {a['coverage_pct']}%（工作时间内 {a['coverage_work_pct']}%）、容量 {a['capacity_pct']}%、"
                     f"空档 {a['idle_min']} 分钟/天、Agent 等你 {a['wait_wall_min']} 分钟/天、"
                     f"人工交互 {a['human_total']} 次/天（专注外 {a['human_out_focus']}）。人工交互最多的时段："
                     + "、".join(f"{x['hour']}点" for x in busy_h if x["humans"])
                     + ("；经常空着的时段：" + "、".join(f"{h}点" for h in p["recurring_idle_hours"]) if p["recurring_idle_hours"] else ""))
    return "\n".join(lines)


def on_startup() -> None:
    """设置里没写时区时，按会话作息推断（后台跑，几秒），推断结果变了就切换进程时区。"""
    from . import _tzinfer

    def run():
        try:
            before = time.tzname[0]
            _tzinfer.refresh()
            if settings.apply_timezone() != before:
                logging.getLogger(__name__).info("时区按作息推断为 %s", time.tzname[0])
        except Exception:  # noqa: BLE001
            logging.getLogger(__name__).exception("推断时区失败")
    threading.Thread(target=run, daemon=True, name="tz-infer").start()


@router.get("/utilization")
def get_utilization(date: str = "", refresh: bool = False):
    return utilization(date, refresh)


@router.get("/patterns")
def get_patterns(days: int = 7):
    return patterns(days)


@router.get("/insights")
def get_insights():
    return {"text": planning_insights()}
