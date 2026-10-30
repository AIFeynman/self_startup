"""时间利用分析：把 Claude Code / Codex 会话的真实事件铺到一天的时间轴上，回答三个问题——
1. Agent 有没有跑满？（每个时间片有几个 Agent 在真正干活；空档在哪）
2. 人工交互发生在什么时候？（专注时间内 / 外；什么类型）
3. Agent 在等人的时间有多少、在哪？（Agent 停下到你回复之间）

事件来自 _review_sessions 的统一事件流（与「复盘 · Agent 效率」口径一致）：
    active：相邻两个 Agent 事件间隔 ≤ WORK_GAP 视为在干活；上一个事件是工具调用时放宽到 TOOL_GAP（长命令/构建）
    wait：Agent 回合结束（或最后一个 Agent 事件）到下一条人工消息之间，≤ WAIT_MAX 计为「等你」
    human：人工消息，按 classify 分类（新任务 / 纠正 / 确认 / 中断 / 回答 / 询问进度）
"""
from __future__ import annotations

from datetime import date as Date, datetime, timedelta
from pathlib import Path

from . import _review_sessions as rs

SLOT_MIN = 10
WORK_GAP = 10 * 60
TOOL_GAP = 45 * 60
WAIT_MAX = 3 * 3600
IDLE_MIN_GAP = 30          # 分钟：工作时间里连续这么久没有 Agent 在跑，算「空档」
_cache: dict[str, tuple[tuple, tuple]] = {}


def _hm(s: str) -> int:
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def _read(path: Path, reader):
    st = path.stat()
    key = (st.st_mtime, st.st_size)
    hit = _cache.get(str(path))
    if hit and hit[0] == key:
        return hit[1]
    res = reader(path)
    _cache[str(path)] = (key, res)
    return res


def _files(session_dirs: dict, day: Date) -> list[tuple[Path, object]]:
    since = datetime.combine(day, datetime.min.time()).timestamp()
    out = [(p, rs.read_claude) for p in rs._claude_files(session_dirs.get("claude", []), since)]
    out += [(p, rs.read_codex) for p in rs._codex_files(session_dirs.get("codex", []), day, since)]
    return out


def session_timeline(meta: dict, events: list[dict], day: Date) -> dict | None:
    """一个会话在某天的 active 区间、wait 区间和人工消息。"""
    events = sorted(events, key=lambda e: e["ts"])
    seen, asked = False, False
    for e in events:  # 分类需要整段历史
        if e["kind"] in ("human", "auto"):
            if e["kind"] == "human":
                e["cls"] = rs.classify(e.get("text", ""), not seen, asked)
            seen, asked = True, False
        elif e["kind"] == "agent" and "asks" in e:
            asked = e["asks"]
    lo = datetime.combine(day, datetime.min.time())
    hi = lo + timedelta(days=1)
    evs = [e for e in events if lo <= e["ts"] < hi]
    if not evs:
        return None
    active, waits, humans = [], [], []
    prev = None
    for e in evs:
        if prev is not None:
            dt = (e["ts"] - prev["ts"]).total_seconds()
            if e["kind"] == "agent" and prev["kind"] in ("agent", "human", "auto"):
                limit = TOOL_GAP if prev.get("tool") else WORK_GAP
                if dt <= limit:
                    active.append((prev["ts"], e["ts"]))
            elif e["kind"] == "human" and prev["kind"] in ("agent", "notify") and dt <= WAIT_MAX:
                waits.append((prev["ts"], e["ts"]))
        if e["kind"] == "human":
            humans.append({"ts": e["ts"], "kind": e.get("cls", "new_task"), "text": (e.get("text") or "")[:160]})
        prev = e
    cwd = meta.get("cwd") or ""
    return {"engine": meta["engine"], "session_id": meta["session_id"], "automated": bool(meta.get("automated")),
            "project": Path(cwd).name if cwd else Path(meta["file"]).parent.name, "title": meta.get("title", ""),
            "active": _merge(active), "waits": waits, "humans": humans}


def _merge(iv: list[tuple]) -> list[tuple]:
    out: list[list] = []
    for s, e in sorted(iv):
        if out and s <= out[-1][1] + timedelta(seconds=60):
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return [(s, e) for s, e in out]


def _overlap(a0, a1, b0, b1) -> float:
    return max(0.0, (min(a1, b1) - max(a0, b0)).total_seconds())


def analyze(day: Date, session_dirs: dict, focus_windows: list[dict], day_start: str = "08:30",
            day_end: str = "23:00", concurrency: int = 3, now: datetime | None = None) -> dict:
    now = now or datetime.now()
    sessions = []
    for path, reader in _files(session_dirs, day):
        try:
            t = session_timeline(*_read(path, reader), day)
        except Exception:  # noqa: BLE001 —— 坏文件跳过
            t = None
        if t and (t["active"] or t["humans"]):
            sessions.append(t)

    base = datetime.combine(day, datetime.min.time())
    t0, t1 = base + timedelta(minutes=_hm(day_start)), base + timedelta(minutes=_hm(day_end))
    # 把实际有活动的时间也纳入（比如凌晨在跑）
    acts = [s for x in sessions for iv in x["active"] for s in iv] + [h["ts"] for x in sessions for h in x["humans"]]
    if acts:
        t0 = min(t0, min(acts).replace(minute=min(acts).minute // SLOT_MIN * SLOT_MIN, second=0, microsecond=0))
        t1 = max(t1, max(acts))
    end = min(t1, now) if day == now.date() else t1
    focus = [(base + timedelta(minutes=_hm(w["start"])), base + timedelta(minutes=_hm(w["end"]))) for w in focus_windows]
    in_focus = lambda ts: any(a <= ts < b for a, b in focus)  # noqa: E731

    slots = []
    t = t0
    step = timedelta(minutes=SLOT_MIN)
    while t < t1:
        u = t + step
        inter = sum(1 for x in sessions if not x["automated"] and any(_overlap(t, u, a, b) >= 120 for a, b in x["active"]))
        auto = sum(1 for x in sessions if x["automated"] and any(_overlap(t, u, a, b) >= 120 for a, b in x["active"]))
        waiting = sum(1 for x in sessions if any(_overlap(t, u, a, b) >= 120 for a, b in x["waits"]))
        hs = [h for x in sessions for h in x["humans"] if t <= h["ts"] < u]
        slots.append({"t": t.strftime("%H:%M"), "interactive": inter, "automated": auto, "waiting": waiting,
                      "humans": len(hs), "focus": in_focus(t), "future": t >= end,
                      "work": _hm(day_start) <= t.hour * 60 + t.minute < _hm(day_end)})
        t = u

    elapsed = [s for s in slots if not s["future"] and s["work"]]
    run = lambda s: s["interactive"] + s["automated"]  # noqa: E731
    covered = sum(1 for s in elapsed if run(s) > 0)
    cap_used = sum(min(run(s), concurrency) for s in elapsed)

    # 空档：工作时间内连续无 Agent 在跑
    gaps, cur = [], []
    for s in elapsed + [{"t": "", "interactive": 1, "automated": 0}]:
        if s["t"] and run(s) == 0:
            cur.append(s)
        else:
            if len(cur) * SLOT_MIN >= IDLE_MIN_GAP:
                st = cur[0]["t"]
                en = (datetime.strptime(cur[-1]["t"], "%H:%M") + step).strftime("%H:%M")
                gaps.append({"start": st, "end": en, "minutes": len(cur) * SLOT_MIN, "in_focus": sum(c["focus"] for c in cur) * SLOT_MIN})
            cur = []

    humans = sorted([{**h, "project": x["project"], "focus": in_focus(h["ts"])} for x in sessions if not x["automated"] for h in x["humans"]],
                    key=lambda h: h["ts"])
    by_kind: dict[str, int] = {}
    for h in humans:
        by_kind[h["kind"]] = by_kind.get(h["kind"], 0) + 1
    out_focus = [h for h in humans if not h["focus"]]

    waits = sorted([{"project": x["project"], "title": x["title"], "start": a, "end": b, "minutes": (b - a).total_seconds() / 60,
                     "focus": in_focus(a)} for x in sessions if not x["automated"] for a, b in x["waits"]], key=lambda w: -w["minutes"])
    wait_total = sum(w["minutes"] for w in waits)
    wait_focus = sum(w["minutes"] for w in waits if w["focus"])

    active_min = sum((b - a).total_seconds() for x in sessions for a, b in x["active"]) / 60
    summary = {
        "day": day.isoformat(), "sessions": len(sessions), "interactive": sum(not x["automated"] for x in sessions),
        "elapsed_min": len(elapsed) * SLOT_MIN, "coverage_pct": round(100 * covered / len(elapsed)) if elapsed else 0,
        "capacity_pct": round(100 * cap_used / (concurrency * len(elapsed))) if elapsed else 0, "concurrency": concurrency,
        "agent_active_min": round(active_min), "idle_min": sum(g["minutes"] for g in gaps),
        "idle_focus_min": sum(g["in_focus"] for g in gaps),
        "human_total": len(humans), "human_out_focus": len(out_focus), "human_kinds": by_kind,
        "wait_total_min": round(wait_total), "wait_focus_min": round(wait_focus),
        "peak_parallel": max((run(s) for s in slots), default=0),
    }
    return {"summary": summary, "slots": slots, "gaps": gaps, "focus": focus_windows,
            "humans": [{"t": h["ts"].strftime("%H:%M"), "kind": h["kind"], "label": rs.KIND_LABELS.get(h["kind"], h["kind"]),
                        "project": h["project"], "focus": h["focus"], "text": h["text"]} for h in humans],
            "top_waits": [{"project": w["project"], "title": w["title"], "start": w["start"].strftime("%H:%M"),
                           "end": w["end"].strftime("%H:%M"), "minutes": round(w["minutes"]), "focus": w["focus"]} for w in waits[:8]],
            "advice": advice(summary, gaps, humans, waits, slots)}


def _hours(hs: list[dict]) -> str:
    cnt: dict[int, int] = {}
    for h in hs:
        cnt[h["ts"].hour] = cnt.get(h["ts"].hour, 0) + 1
    top = sorted(cnt.items(), key=lambda x: -x[1])[:3]
    return "、".join(f"{h}点（{n} 次）" for h, n in sorted(top))


def advice(s: dict, gaps: list[dict], humans: list[dict], waits: list[dict], slots: list[dict]) -> list[str]:
    """确定性的改进建议（可直接喂给规划）。"""
    out = []
    if gaps:
        big = sorted(gaps, key=lambda g: -g["minutes"])[:3]
        out.append("Agent 空档：" + "、".join(f"{g['start']}–{g['end']}（{g['minutes']} 分钟）" for g in big)
                   + "。这些时间可以预先排上能自动跑的任务（批量测试、调研、文档整理、代码审查）。")
    if s["capacity_pct"] < 50 and s["elapsed_min"] >= 120:
        out.append(f"并发容量只用了 {s['capacity_pct']}%（上限 {s['concurrency']} 个）。下班前或专注时间之前，可以一次派出 2–3 个互不依赖的自动任务。")
    if humans:
        pct = round(100 * s["human_out_focus"] / s["human_total"])
        if pct >= 40:
            out.append(f"{pct}% 的人工交互（{s['human_out_focus']}/{s['human_total']} 次）在专注时间外，集中在 {_hours([h for h in humans if not h['focus']])}。"
                       "把需要来回确认的任务挪到专注时间，专注时间外只派发不用盯的任务。")
    corr = s["human_kinds"].get("correct", 0)
    if s["human_total"] and corr / s["human_total"] >= 0.2:
        out.append(f"纠正 / 转向占人工交互的 {round(100 * corr / s['human_total'])}%（{corr} 次）。派任务前先写清完成标准和约束，能少一半来回。")
    appr = s["human_kinds"].get("approve", 0) + s["human_kinds"].get("check", 0)
    if appr >= 5:
        out.append(f"确认 / 询问进度 {appr} 次，基本可以省：放宽权限白名单，或者让 Agent 在关键节点才停。")
    long_waits = [w for w in waits if w["minutes"] >= 30]
    if long_waits:
        w = long_waits[0]
        out.append(f"Agent 等你的时间累计 {s['wait_total_min']} 分钟，其中 {len(long_waits)} 次超过 30 分钟（最长：{w['project']} 在 "
                   f"{w['start']:%H:%M} 等了 {round(w['minutes'])} 分钟）。离开前给长任务留足指令，或改成在专注时间集中回复。")
    if s["idle_focus_min"] >= 30:
        out.append(f"专注时间里有 {s['idle_focus_min']} 分钟没有 Agent 在跑。人专注时，可以在后台并行跑一个自动任务。")
    return out or ["今天的利用率不错，没有明显的空档或错位。"]
