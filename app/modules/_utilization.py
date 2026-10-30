"""时间利用分析：把 Claude Code / Codex 会话的真实事件铺到一天的时间轴上，回答三个问题——
1. Agent 有没有跑满？（每个时间片有几个 Agent 在真正干活；空档在哪）
2. 人工交互发生在什么时候？（专注时间内 / 外；什么类型）
3. Agent 在等人的时间有多少、在哪？（Agent 停下到你回复之间）

事件来自 _review_sessions 的统一事件流（与「复盘 · Agent 效率」口径一致）：
    active：相邻两个 Agent 事件间隔 ≤ WORK_GAP 视为在干活；上一个事件是工具调用时放宽到 TOOL_GAP（长命令/构建）
    wait：Agent 回合结束（或最后一个 Agent 事件）到下一条人工消息之间，≤ WAIT_MAX 计为「等你」
    human：人工消息，按 classify 分类（新任务 / 纠正 / 确认 / 中断 / 回答 / 询问进度）

汇总口径（用精确区间算，不用 10 分钟时间片取整；时间片只用于画图和找空档）：
    统计时段 = 已过去的工作时间（day_start–day_end）∪ Agent 在干活 ∪ Agent 在等你 ∪ 人工交互后的一个时间片
               ——凌晨 / 工作时间前后真实在用的时间也算进来，否则会出现「覆盖 0% 却等你 400 分钟」
    coverage_pct       统计时段里至少有一个 Agent 在干活的比例（coverage_work_pct：只看工作时间）
    capacity_pct       ∫min(在跑的 Agent 数, 并发上限) / (并发上限 × 统计时段)
    wait_wall_min      至少有一个 Agent 在等你的墙钟分钟（人真正拖住 Agent 的时长）
    wait_total_min     按会话累加的等待（Agent·分钟；多个会话同时等会叠加，可能超过墙钟时长）
"""
from __future__ import annotations

import time
from datetime import date as Date, datetime, timedelta
from pathlib import Path

from . import _review_sessions as rs

SLOT_MIN = 10
WORK_GAP = 10 * 60
TOOL_GAP = 45 * 60
WAIT_MAX = rs.WAIT_MAX
VERSION = 3               # 口径版本：改了算法就 +1，旧快照会被重算
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


def _union(iv) -> list[tuple]:
    out: list[list] = []
    for s, e in sorted(iv):
        if e <= s:
            continue
        if out and s <= out[-1][1]:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return [(s, e) for s, e in out]


def _minutes(iv, lo=None, hi=None) -> float:
    return sum(max(0.0, ((min(b, hi) if hi else b) - (max(a, lo) if lo else a)).total_seconds()) for a, b in iv) / 60


def _sweep(per_session: list[list[tuple]], cap: int) -> tuple[float, int]:
    """各会话（已合并）的活跃区间 → (∫min(并发, cap) 分钟, 峰值并发)。"""
    pts = sorted([(a, 1) for iv in per_session for a, _ in iv] + [(b, -1) for iv in per_session for _, b in iv],
                 key=lambda x: (x[0], x[1]))
    used, cur, peak, last = 0.0, 0, 0, None
    for t, d in pts:
        if last is not None and cur:
            used += min(cur, cap) * (t - last).total_seconds() / 60
        cur += d
        peak = max(peak, cur)
        last = t
    return used, peak


def analyze(day: Date, session_dirs: dict, focus_windows: list[dict], day_start: str = "08:30",
            day_end: str = "23:00", concurrency: int = 3, now: datetime | None = None,
            chat_ids: set[str] = frozenset()) -> dict:
    now = now or datetime.now()
    sessions = []
    for path, reader in _files(session_dirs, day):
        try:
            t = session_timeline(*rs.promote_platform_chat(*_read(path, reader), chat_ids), day)
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

    # 精确区间口径（见模块说明）
    lo, hi = base, min(base + timedelta(days=1), now)
    clip = lambda iv: [(max(a, lo), min(b, hi)) for a, b in iv if b > lo and a < hi]  # noqa: E731
    act_by = [clip(x["active"]) for x in sessions]
    act_u = _union([iv for a in act_by for iv in a])
    wait_u = _union(clip([iv for x in sessions if not x["automated"] for iv in x["waits"]]))
    w0, w1 = base + timedelta(minutes=_hm(day_start)), min(base + timedelta(minutes=_hm(day_end)), hi)
    work_iv = [(w0, w1)] if w1 > w0 else []
    human_iv = clip([(h["ts"], h["ts"] + step) for h in humans])
    span = _union(work_iv + act_u + wait_u + human_iv)
    span_min, work_min = _minutes(span), _minutes(work_iv)
    cap_used, peak = _sweep(act_by, concurrency)
    focus_wait = sum(_minutes(wait_u, a, b) for a, b in focus)

    summary = {
        "v": VERSION, "day": day.isoformat(), "sessions": len(sessions), "interactive": sum(not x["automated"] for x in sessions),
        "elapsed_min": round(span_min), "work_elapsed_min": round(work_min),
        "coverage_pct": round(100 * _minutes(act_u) / span_min) if span_min else 0,
        "coverage_work_pct": round(100 * sum(_minutes(act_u, a, b) for a, b in work_iv) / work_min) if work_min else 0,
        "capacity_pct": round(100 * cap_used / (concurrency * span_min)) if span_min else 0, "concurrency": concurrency,
        "agent_active_min": round(sum(_minutes(a) for a in act_by)), "agent_active_wall_min": round(_minutes(act_u)),
        "idle_min": sum(g["minutes"] for g in gaps), "idle_focus_min": sum(g["in_focus"] for g in gaps),
        "human_total": len(humans), "human_out_focus": len(out_focus), "human_kinds": by_kind,
        "human_in_work": sum(1 for h in humans if _hm(day_start) <= h["ts"].hour * 60 + h["ts"].minute < _hm(day_end)),
        "tz": time.tzname[0], "wait_total_min": round(wait_total), "wait_wall_min": round(_minutes(wait_u)), "wait_focus_min": round(focus_wait),
        "peak_parallel": peak,
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
    if s["human_total"] >= 20 and s.get("human_in_work", s["human_total"]) / s["human_total"] < 0.5:
        out.append(f"只有 {round(100 * s['human_in_work'] / s['human_total'])}% 的人工交互落在工作时间内（按 {s.get('tz', '系统')} 时区算）。"
                   "如果你不在这个时区，专注时间、空档和日期边界都会整体错位：在「设置」里把时区改成你所在的时区（如 Asia/Shanghai）。")
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
        out.append(f"Agent 等你 {s.get('wait_wall_min', s['wait_total_min'])} 分钟（墙钟；各会话累加 {s['wait_total_min']} Agent·分钟），其中 {len(long_waits)} 次超过 30 分钟（最长：{w['project']} 在 "
                   f"{w['start']:%H:%M} 等了 {round(w['minutes'])} 分钟）。离开前给长任务留足指令，或改成在专注时间集中回复。")
    if s["idle_focus_min"] >= 30:
        out.append(f"专注时间里有 {s['idle_focus_min']} 分钟没有 Agent 在跑。人专注时，可以在后台并行跑一个自动任务。")
    return out or ["今天的利用率不错，没有明显的空档或错位。"]
