"""学习习惯三项（2026-10-31 定）：每项都有可检验的指标，学习页和复盘共用。

1. 「停一下」按固定格式作答：结论 + 为什么（机制）+ 一个例子 + 在我项目里怎么用。指标：近 7 天平均分 ≥ 65%。
2. 学完一章当天就在一个项目里用一次。指标：当天学完的每一章，都有一条项目会话 / 文档 / 提交引用到它，或手动记了应用。
3. 每天单独排 30 分钟读 1–2 篇前沿论文，在信息推荐里挑，写一句话判断。指标：知识库里当天有论文笔记。
"""
from __future__ import annotations

import json
import re
import subprocess
from datetime import date as Date, timedelta
from pathlib import Path

from .. import db, settings, tasks

PAPER_TAG = "habit:paper"
DEFAULTS = {"paper_task": True, "paper_minutes": 30, "paper_per_day": 2}


def cfg() -> dict:
    return {**DEFAULTS, **(settings.load().get("habits") or {})}


# ---------- 3. 每日论文 ----------

def paper_task(date: str) -> dict | None:
    return db.row("SELECT * FROM tasks WHERE date=? AND notes LIKE ? ORDER BY id LIMIT 1", [date, f"%{PAPER_TAG}%"])


def ensure_paper_task(date: str) -> dict | None:
    """今天还没有「读前沿论文」事项就加一条（学习块，规划排程时放进非专注时间）；只给今天加，关掉设置就不加。"""
    c = cfg()
    if not c["paper_task"] or date != db.today():
        return None
    t = paper_task(date)
    if t:
        return t
    return tasks.create({"date": date, "title": f"读前沿论文 1–{c['paper_per_day']} 篇", "kind": "learning",
                         "est_minutes": int(c["paper_minutes"]), "priority": 3, "human_level": "medium",
                         "goal": "在「信息推荐 · 论文」里挑 1–2 篇读，每篇写一句话判断（增量在哪、证据可不可信、值不值得跟），自动存进知识库的论文笔记",
                         "notes": f"{PAPER_TAG} #feed"})


def sync_paper_task(date: str) -> None:
    """写了一句话判断后更新当天的论文事项：写满目标篇数算完成，写了一篇算进行中。"""
    t = paper_task(date)
    if not t or t["status"] == "dropped":
        return
    from . import feed
    n, goal = len(feed.paper_notes(date)), max(1, int(cfg()["paper_per_day"]))
    if n:
        tasks.patch(t["id"], {"progress": min(100, round(100 * n / goal)), "status": "done" if n >= 1 else t["status"]})


def paper_status(date: str) -> dict:
    from . import feed
    notes = feed.paper_notes(date)
    t = paper_task(date)
    return {"done": bool(notes), "count": len(notes), "goal": int(cfg()["paper_per_day"]), "minutes": int(cfg()["paper_minutes"]),
            "kb_path": f"learn/paper-notes/{date}.md" if notes else "", "task_id": t["id"] if t else None,
            "notes": [{"id": n["id"], "title": n["title"], "url": n["url"], "verdict": n["verdict"], "at": n["verdict_at"][11:16]} for n in notes]}


# ---------- 2. 学完当天用到项目 ----------

def learned_steps(date: str) -> list[dict]:
    """当天学完的章节：当天标完成，或当天交了章末测试。"""
    ids = {r["id"] for r in db.rows("SELECT id FROM learn_steps WHERE substr(done_at,1,10)=?", [date])}
    ids |= {r["step_id"] for r in db.rows("SELECT DISTINCT step_id FROM learn_events WHERE kind='quiz' AND substr(created_at,1,10)=?", [date])
            if r["step_id"]}
    if not ids:
        return []
    return db.rows(f"SELECT s.id, s.plan_id, s.title, s.cards, s.status, p.topic FROM learn_steps s LEFT JOIN learn_plans p ON p.id=s.plan_id "
                   f"WHERE s.id IN ({','.join('?' * len(ids))}) ORDER BY s.id", list(ids))


_SPLIT = re.compile(r"[：:·—|，,、（）()「」《》/&]+")


def _uniq(xs: list[str]) -> list[str]:
    out = []
    for t in xs:
        if t and t not in out:
            out.append(t)
    return out


def chapter_match(s: dict) -> tuple[list[str], list[str]]:
    """判断「引用到这一章」用的词，分两档：
    强词（出现一个就算）：完整章名、章节目录名 step-<id>、知识卡标题；
    弱词（章名里的片段，如「底层逻辑」，太泛，同一处要出现两个不同的才算）。"""
    title = (s.get("title") or "").strip()
    try:
        cards = json.loads(s.get("cards") or "[]") if isinstance(s.get("cards"), str) else (s.get("cards") or [])
    except ValueError:
        cards = []
    strong = _uniq([title, f"step-{s['id']}"] + [str(c.get("front") or "").strip() for c in cards[:8] if len(str(c.get("front") or "").strip()) >= 6])
    weak = _uniq([x.strip() for x in _SPLIT.split(title) if len(x.strip()) >= 4 and x.strip() != title and x.strip() not in strong])
    return strong, weak


def chapter_terms(s: dict) -> list[str]:
    strong, weak = chapter_match(s)
    return strong + weak


def _hit(text: str, terms: tuple[list[str], list[str]]) -> str:
    low = text.lower()
    strong, weak = terms
    t = next((t for t in strong if t.lower() in low), "")
    if t:
        return t
    ws = [w for w in weak if w.lower() in low]
    return " + ".join(ws[:2]) if len(ws) >= 2 else ""


# 生成产物和平台自己的提示词模板不算「用到项目」：只看人写 / 人让 Agent 写的项目文档
_GEN_DIRS = {"output", "outputs", "diagnostics", "logs", "log", "tmp", "cache", "dist", "build", "site-packages", "node_modules"}


def _generated(d: str, rel: str) -> bool:
    parts = Path(rel).parts[:-1]
    if any(x.lower() in _GEN_DIRS for x in parts):
        return True
    # 平台仓库（含它的其它 checkout / worktree）里的 skills/ 是出章节用的提示词，不是应用
    return parts[:1] == ("skills",) and (Path(d) / "app" / "modules" / "_habits.py").exists()


def _day_sessions(date: str, scan: bool = True) -> list[dict]:
    try:
        from . import review
        eff = review.get_efficiency(date, scan_if_missing=scan) or {}
    except Exception:  # noqa: BLE001  扫描失败不影响其它两项
        return []
    data_dir = str(db.DATA_DIR)
    # 只看人在项目里的会话：后台任务（章节生成、点评）和平台里的学习对话本来就围着这一章，不算「用到项目」
    return [s for s in eff.get("sessions") or [] if not s.get("automated") and not s.get("platform_chat")
            and not (s.get("cwd") or "").startswith(data_dir)]


def _day_dirs(date: str, sessions: list[dict]) -> list[str]:
    from . import review
    dirs = review.repo_dirs(date)
    for s in sessions:
        d = s.get("cwd") or ""
        if d and d not in dirs and Path(d).is_dir():
            dirs.append(d)
    return dirs[:12]


def _doc_hits(d: str, date: str, terms: tuple[list[str], list[str]]) -> list[dict]:
    from . import review
    out = []
    for line in review.recent_docs(d, date, limit=40):
        rel = line.split(" ", 1)[1]
        if _generated(d, rel):
            continue
        try:
            text = (Path(d) / rel).read_text(errors="ignore")[:200_000]
        except OSError:
            continue
        t = _hit(text, terms)
        if t:
            out.append({"kind": "doc", "where": f"{Path(d).name}/{rel}", "term": t})
    nxt = (Date.fromisoformat(date) + timedelta(days=1)).isoformat()
    try:
        r = subprocess.run(["git", "-C", d, "log", "--all", f"--since={date} 00:00", f"--until={nxt} 00:00", "--format=%h%x09%s%x09%b%x1e"],
                           capture_output=True, text=True, timeout=20)
        logs = r.stdout if r.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        logs = ""
    for rec in logs.split("\x1e"):
        parts = rec.strip().split("\t", 2)
        if len(parts) >= 2:
            t = _hit(" ".join(parts[1:]), terms)
            if t:
                out.append({"kind": "commit", "where": f"{Path(d).name}@{parts[0]} {parts[1][:60]}", "term": t})
    return out


def apply_status(date: str, scan: bool = True) -> dict:
    """当天学完的每一章：有没有手动记的应用、有没有项目会话 / 文档 / 提交引用到它。"""
    steps = learned_steps(date)
    if not steps:
        return {"learned": [], "applied": 0, "total": 0, "rate": None}
    manual: dict[int, list[dict]] = {}
    for e in db.rows("SELECT step_id, data, created_at FROM learn_events WHERE kind='apply' AND substr(created_at,1,10)=?", [date]):
        d = json.loads(e["data"] or "{}")
        manual.setdefault(e["step_id"], []).append({"kind": "manual", "where": d.get("project", ""), "term": d.get("what", "")[:80],
                                                    "evidence": d.get("evidence", ""), "at": e["created_at"][11:16]})
    sessions = _day_sessions(date, scan)
    dirs = _day_dirs(date, sessions)
    out = []
    for s in steps:
        terms = chapter_match(s)
        refs = list(manual.get(s["id"], []))
        for ss in sessions:
            for m in ss.get("messages") or []:
                t = _hit(m.get("text") or "", terms)
                if t:
                    refs.append({"kind": "session", "where": f"{ss.get('project')} · {ss.get('title') or ss.get('engine')} {m.get('t', '')}", "term": t})
                    break
        for d in dirs:
            refs += _doc_hits(d, date, terms)
        out.append({"step_id": s["id"], "plan_id": s["plan_id"], "title": s["title"], "topic": s.get("topic") or "",
                    "applied": bool(refs), "refs": refs[:6]})
    n = sum(x["applied"] for x in out)
    return {"learned": out, "applied": n, "total": len(out), "rate": round(100 * n / len(out))}


# ---------- 汇总 ----------

def status(date: str, with_apply: bool = True, scan: bool = True) -> dict:
    from . import learn
    reviews = [e for e in learn.events_of() if e["kind"] == "check_review"]
    return {"date": date, "check": learn.check_stats(reviews), "paper": paper_status(date),
            "apply": apply_status(date, scan) if with_apply else None}


def lines(date: str) -> list[str]:
    """给复盘用的三行（不触发会话重扫，用复盘已有的扫描结果）。"""
    h = status(date, scan=False)
    k, p, a = h["check"], h["paper"], h["apply"]
    out = []
    if k["avg"] is not None:
        out.append(f"停一下：近 {k['days']} 天平均 {k['recent_avg'] if k['recent_avg'] is not None else '—'}%（{k['recent_n']} 次，目标 ≥ {k['target']}%）"
                   + (f"；四栏 " + "、".join(f"{x}{v}%" for x, v in k["parts"].items()) + f"，最弱：{k['weakest']}" if k["parts"] else ""))
    if a and a["total"]:
        miss = [x["title"] for x in a["learned"] if not x["applied"]]
        out.append(f"学完当天用到项目：{a['applied']}/{a['total']} 章" + (f"；还没用：{'、'.join(miss)[:120]}" if miss else ""))
    out.append(f"每日论文：{'已写 ' + str(p['count']) + ' 篇论文笔记（' + p['kb_path'] + '）' if p['done'] else '今天还没有论文笔记'}")
    return out
