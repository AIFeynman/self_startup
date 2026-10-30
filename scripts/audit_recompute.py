"""审计用的独立重算：不 import app 代码，自己解析 Claude Code / Codex 会话日志，用连续区间（不是 10 分钟时间片）
重算近 8 天的覆盖率、并发、空档、等你时长、专注内外人工交互，用来和「Agent 看板 · 时间利用」对数。

    TZ=Asia/Shanghai python3 -I scripts/audit_recompute.py [data/settings.json] [out.json]

口径和 app/modules/_utilization.py 模块说明一致；会话目录、专注时间、工作时间读 settings.json（并发上限按 3 算）。
空档是「工作时间内 ≥30 分钟完全没有 Agent 事件」，比看板的时间片口径（片内活跃 <2 分钟也算空）更严，数值会偏小。
"""
import json, glob, os, sys
from datetime import datetime, timedelta
H = os.path.expanduser
_cfg = json.load(open(sys.argv[1])) if len(sys.argv) > 1 and os.path.exists(sys.argv[1]) else {}
_dirs = _cfg.get("session_dirs", {})
CLAUDE = [H(d) for d in _dirs.get("claude", ['~/.claude/projects'])]
CODEX = H((_dirs.get("codex") or ['~/.codex/sessions'])[0])
FOCUS = [(w["start"], w["end"]) for w in _cfg.get("focus_windows", [{"start": "10:00", "end": "11:40"}, {"start": "13:30", "end": "16:50"}])]
DAY0, DAY1 = _cfg.get("day_start", "08:30"), _cfg.get("day_end", "23:00")
SKIP = ("<task-notification>", "This session is being continued", "<system-reminder>", "Caveat:", "<local-command",
        "<environment_context>", "# AGENTS.md", "<user_instructions>", "<bash-", "Another Claude session sent")

def ts(s):
    try: return datetime.fromisoformat(s.replace('Z', '+00:00')).astimezone().replace(tzinfo=None)
    except Exception: return None

def claude(p):
    ev, human, sdk = [], 0, 0
    for l in open(p, errors='replace'):
        if '"timestamp"' not in l: continue
        try: o = json.loads(l)
        except Exception: continue
        if o.get('isSidechain') or o.get('type') not in ('user', 'assistant', 'system'): continue
        t = ts(o.get('timestamp') or '')
        if not t: continue
        if o['type'] == 'assistant':
            c = (o.get('message') or {}).get('content') or []
            ev.append((t, 'a', any(isinstance(b, dict) and b.get('type') == 'tool_use' for b in c)))
        elif o['type'] == 'system':
            if o.get('subtype') in ('turn_duration', 'stop_hook_summary', 'api_error'): ev.append((t, 'a', False))
        else:
            c = (o.get('message') or {}).get('content')
            if isinstance(c, list) and any(isinstance(b, dict) and b.get('type') == 'tool_result' for b in c):
                ev.append((t, 'a', False)); continue
            if isinstance(c, list): c = '\n'.join(b.get('text', '') for b in c if isinstance(b, dict) and b.get('type') == 'text')
            c = (c or '').strip()
            if not c or o.get('isMeta'): continue
            if c.startswith('[Request interrupted'): ev.append((t, 'h', False)); human += 1; continue
            if c.startswith(SKIP): ev.append((t, 'n', False)); continue
            ori = (o.get('origin') or {}).get('kind') if isinstance(o.get('origin'), dict) else None
            src = ori or o.get('turnOrigin') or ''
            if src and src != 'human':
                if src == 'sdk': sdk += 1; ev.append((t, 'u', False))
                else: ev.append((t, 'n', False))
                continue
            human += 1; ev.append((t, 'h', False))
    return ev, (sdk > 0 and human == 0)

def codex(p):
    ev, auto, um, has_um = [], False, [], False
    for l in open(p, errors='replace'):
        try: o = json.loads(l)
        except Exception: continue
        t = ts(o.get('timestamp') or ''); pl = o.get('payload') or {}
        if not t or not isinstance(pl, dict): continue
        ty, pt = o.get('type'), pl.get('type')
        if ty == 'session_meta': auto = pl.get('originator') == 'codex_exec' or pl.get('source') == 'exec'
        elif ty == 'response_item' and pt in ('function_call', 'custom_tool_call', 'local_shell_call', 'web_search_call'): ev.append((t, 'a', True))
        elif ty == 'response_item' and pt in ('function_call_output', 'custom_tool_call_output') : ev.append((t, 'a', False))
        elif ty == 'response_item' and pt == 'message' and pl.get('role') == 'assistant': ev.append((t, 'a', False))
        elif ty == 'event_msg' and pt == 'item_completed' and (pl.get('item') or {}).get('type') == 'UserMessage':
            m = ' '.join(c.get('text', '') for c in pl['item'].get('content') or [] if isinstance(c, dict)).strip()
            if m and not m.startswith(SKIP): um.append((t, 'u' if auto else 'h', False))
        elif ty == 'event_msg' and pt == 'user_message':
            has_um = True
            m = str(pl.get('message') or '').strip()
            if m and not m.startswith(SKIP): ev.append((t, 'u' if auto else 'h', False))
        elif ty == 'event_msg' and pt in ('agent_message', 'task_complete', 'exec_approval_request', 'patch_apply_end'): ev.append((t, 'a', False))
        elif ty == 'event_msg' and pt == 'turn_aborted': ev.append((t, 'h', False))
    return ev + ([] if has_um else um), auto

def sessions(since):
    out = []
    for r in CLAUDE:
        for p in glob.glob(r + '/*/*.jsonl'):
            if os.stat(p).st_mtime >= since: out.append((p, *claude(p)))
    for p in glob.glob(CODEX + '/*/*/*/*.jsonl'):
        if os.stat(p).st_mtime >= since: out.append((p, *codex(p)))
    return out

def merge(iv):
    out = []
    for a, b in sorted(iv):
        if out and a <= out[-1][1]: out[-1][1] = max(out[-1][1], b)
        else: out.append([a, b])
    return out

def ilen(iv, lo, hi): return sum(max(0, (min(b, hi) - max(a, lo)).total_seconds()) for a, b in iv) / 60

def day_metrics(S, d, now):
    base = datetime.combine(d, datetime.min.time()); lo, hi = base, base + timedelta(days=1)
    hm = lambda s: base + timedelta(hours=int(s[:2]), minutes=int(s[3:]))
    w0, w1 = hm(DAY0), min(hm(DAY1), now); foc = [(hm(a), hm(b)) for a, b in FOCUS]
    infoc = lambda t: any(a <= t < b for a, b in foc)
    act_all, act_by, waits, humans, n = [], [], [], [], 0
    for p, ev, auto in S:
        ev = sorted(e for e in ev if lo <= e[0] < hi)
        if not ev: continue
        act, prev = [], None
        for e in ev:
            if prev:
                dt = (e[0] - prev[0]).total_seconds()
                if e[1] == 'a' and prev[1] in 'ahu' and dt <= (2700 if prev[2] else 600): act.append([prev[0], e[0]])
                if e[1] == 'h' and prev[1] in 'an' and dt <= 3 * 3600 and not auto: waits.append((prev[0], e[0]))
            if e[1] == 'h' and not auto: humans.append(e[0])
            prev = e
        act = merge(act)
        if act or any(e[1] == 'h' for e in ev): n += 1
        act_by.append(act); act_all += act
    U = merge(act_all)
    work_min = max(0, (w1 - w0).total_seconds() / 60)
    # 墙钟口径：工作时间 ∪ 有 Agent 活动的时间
    hum_iv = [[h, min(h + timedelta(minutes=10), hi, now)] for h in humans]
    span = merge(([[w0, w1]] if w1 > w0 else []) + [list(x) for x in U] + [list(x) for x in waits] + hum_iv)
    span_min = ilen(span, lo, hi)
    # 峰值并发（区间扫描）
    cap = 0.0
    pts = sorted([(a, 1) for iv in act_by for a, _ in iv] + [(b, -1) for iv in act_by for _, b in iv], key=lambda x: (x[0], x[1]))
    cur = peak = 0
    last = None
    for tt, k in pts:
        if last is not None and cur: cap += min(cur, 3) * (tt - last).total_seconds() / 60
        cur += k; peak = max(peak, cur); last = tt
    # 空档：工作时间内 ≥30 分钟无 Agent
    gaps, t = [], w0
    for a, b in U + [[w1, w1]]:
        if a > t and (min(a, w1) - t).total_seconds() >= 1800 and t < w1: gaps.append((t, min(a, w1)))
        t = max(t, b)
    wsum = sum((b - a).total_seconds() for a, b in waits) / 60
    wwall = ilen(merge([list(x) for x in waits]), lo, hi)
    wwork = ilen(merge([list(x) for x in waits]), w0, w1) if w1 > w0 else 0
    return {"day": str(d), "sessions": n, "work_min": round(work_min), "span_min": round(span_min),
            "cov_work_pct": round(100 * ilen(U, w0, w1) / work_min) if work_min else 0,
            "cov_span_pct": round(100 * ilen(U, lo, hi) / span_min) if span_min else 0,
            "agent_active_union_min": round(ilen(U, lo, hi)), "agent_active_sum_min": round(sum(ilen(i, lo, hi) for i in act_by)),
            "peak": peak, "cap_pct": round(100 * cap / (3 * span_min)) if span_min else 0, "idle_min": round(sum((b - a).total_seconds() for a, b in gaps) / 60),
            "wait_sum_min": round(wsum), "wait_wall_min": round(wwall), "wait_work_wall_min": round(wwork),
            "humans": len(humans), "humans_out_focus": sum(not infoc(h) for h in humans), "humans_in_focus": sum(infoc(h) for h in humans)}

if __name__ == '__main__':
    now = datetime.now(); today = now.date()
    days = [today - timedelta(days=i) for i in range(0, 8)]
    S = sessions(datetime.combine(days[-1], datetime.min.time()).timestamp())
    res = [day_metrics(S, d, now if d == today else datetime.combine(d, datetime.max.time())) for d in days]
    json.dump(res, open(sys.argv[2] if len(sys.argv) > 2 else 'recompute.json', 'w'), ensure_ascii=False, indent=1)
    for r in res: print(r)
