"""复盘 · Agent 效率：解析 Claude Code / Codex 会话日志（只读、逐行流式），统计人工介入。

统一事件模型（按时间排序）：
    human   人发出的消息（kind 由 classify 判定：new_task/correct/approve/interrupt/answer/check）
    auto    非人工的提示（claude -p / codex exec 等脚本化会话）
    agent   Agent 的任何活动（文本、工具调用、工具结果、回合结束）
    notify  后台任务通知等系统消息（不算人工，也不算 Agent 活跃）
指标：
    active  相邻事件间隔里「以 agent 事件结尾」的部分之和（单段封顶 IDLE_CAP）
    wait    Agent 停下到下一条人工消息之间的间隔；≤ WAIT_MAX 计入「等你」（与 Agent 看板 · 时间利用同一口径），更长视为离开
"""
from __future__ import annotations

import json
import re
import statistics
from datetime import date as Date, datetime, timedelta
from pathlib import Path
from typing import Iterable

IDLE_CAP = 15 * 60      # 单段 Agent 活跃时间封顶（秒）：更长视为空闲
WAIT_MAX = 3 * 3600     # 单段等待超过这个视为人离开，不计入「等你」（看板 · 时间利用共用）
TEXT_MAX = 300
VERSION = 2             # 统计口径版本：改了算法就 +1，复盘里旧的效率快照会重扫

KIND_LABELS = {"new_task": "新任务/追加", "correct": "纠正/转向", "approve": "确认/继续",
               "interrupt": "中断", "answer": "回答提问", "check": "询问进度"}

_SKIP_PREFIX = ("<task-notification>", "Another Claude session sent", "This session is being continued",
                "Caveat:", "<system-reminder>", "<local-command-stdout>", "<local-command-stderr>",
                "<environment_context>", "# AGENTS.md", "<user_instructions>",
                "<bash-input>", "<bash-stdout>", "<bash-stderr>")
_APPROVE = re.compile(r"^(继续|好的?|可以|行|嗯|对|是的?|没问题|同意|确认|开始|提交|commit|ok|okay|yes|y|go|continue|proceed|lgtm|sure|do it|build it|"
                      r"go ahead|commit (it|them)|push|merge|就这样|按这个|照做|执行|先这样)\b", re.I)
_CHECK = re.compile(r"(进度|怎么样了|怎样了|好了吗|完成了吗|做完了吗|到哪|status|还在跑|跑完)", re.I)
_CORRECT = re.compile(r"(不对|不是|错了|有误|应该|别|不要|不用|还是|重新|改成|改为|换成|没有|不行|打不开|怎么还|又|报错|失败|不符合|不准|太慢|效率太低|"
                      r"问题|bug|wrong|instead|don't|do not|not what|revert|撤销|回退|丢失)", re.I)
_DENIAL = ("Permission for this", "The user doesn't want to proceed", "was rejected", "requires approval",
           "Blocked:", "permission was denied", "denied by")


def _ts(s) -> datetime | None:
    if not s or not isinstance(s, str):
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone().replace(tzinfo=None)
    except ValueError:
        return None


def _asks(text: str) -> bool:
    tail = (text or "").strip()[-120:]
    return bool(tail) and (tail.endswith(("?", "？")) or "吗？" in tail or "?" in tail[-40:] or "？" in tail[-40:])


def classify(text: str, first: bool, asked: bool) -> str:
    t = (text or "").strip()
    if t.startswith(("[Request interrupted", "[turn_aborted")):
        return "interrupt"
    if first:
        return "new_task"
    if len(t) <= 30 and _APPROVE.search(t):
        return "approve"
    if asked:
        return "answer"
    if len(t) <= 40 and _CHECK.search(t):
        return "check"
    if _CORRECT.search(t):
        return "correct"
    return "new_task"


def _ev(kind: str, ts: datetime, **kw) -> dict:
    return {"kind": kind, "ts": ts, **kw}


# ---------- Claude Code ----------

_CLAUDE_TYPES = ("user", "assistant", "system", "custom-title")


def _claude_text(content) -> str:
    if isinstance(content, str):
        return content
    parts = []
    for b in content or []:
        if isinstance(b, dict) and b.get("type") == "text":
            parts.append(b.get("text", ""))
        elif isinstance(b, dict) and b.get("type") == "image":
            parts.append("[图片]")
    return "\n".join(p for p in parts if p)


def _slash(text: str) -> str:
    m = re.search(r"<command-name>([^<]*)</command-name>", text)
    if not m:
        return text
    a = re.search(r"<command-args>([^<]*)</command-args>", text)
    return f"{m.group(1)} {a.group(1) if a else ''}".strip()


def read_claude(path: Path) -> tuple[dict, list[dict]]:
    meta = {"engine": "claude", "session_id": path.stem, "file": str(path), "cwd": "", "title": "", "sdk": 0, "human": 0}
    events: list[dict] = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            if line.startswith('{"type":"'):
                t = line[9:line.find('"', 9)]
                if t not in _CLAUDE_TYPES:
                    continue
            elif '"type":"user"' not in line and '"type":"assistant"' not in line and '"type":"system"' not in line:
                continue
            try:
                o = json.loads(line)
            except json.JSONDecodeError:
                continue
            t = o.get("type")
            if t == "custom-title":
                meta["title"] = o.get("customTitle") or meta["title"]
                continue
            if o.get("isSidechain"):
                continue
            ts = _ts(o.get("timestamp"))
            if not ts:
                continue
            if not meta["cwd"] and o.get("cwd"):
                meta["cwd"] = o["cwd"]
            msg = o.get("message") or {}
            content = msg.get("content")
            if t == "assistant":
                for b in content or []:
                    if not isinstance(b, dict):
                        continue
                    if b.get("type") == "text":
                        events.append(_ev("agent", ts, asks=_asks(b.get("text", ""))))
                    elif b.get("type") == "tool_use":
                        events.append(_ev("agent", ts, tool=b.get("name", ""), asks=b.get("name") == "AskUserQuestion"))
                    else:
                        events.append(_ev("agent", ts))
            elif t == "system":
                if o.get("subtype") == "api_error":
                    events.append(_ev("agent", ts, api_error=True))
                elif o.get("subtype") in ("stop_hook_summary", "turn_duration"):
                    events.append(_ev("agent", ts, end=True))
            elif t == "user":
                if isinstance(content, list):
                    for b in content:
                        if isinstance(b, dict) and b.get("type") == "tool_result":
                            c = b.get("content")
                            c = c if isinstance(c, str) else json.dumps(c, ensure_ascii=False)[:2000]
                            denied = any(s in c[:500] for s in _DENIAL)
                            events.append(_ev("agent", ts, error=bool(b.get("is_error")), denied=denied))
                text = _claude_text(content).strip()
                if not text or o.get("isMeta"):
                    continue
                if text.startswith("[Request interrupted"):
                    events.append(_ev("human", ts, text=text))
                    continue
                if text.startswith(_SKIP_PREFIX):
                    events.append(_ev("notify", ts))
                    continue
                origin = o.get("origin") if isinstance(o.get("origin"), dict) else {}
                src = origin.get("kind") or o.get("turnOrigin") or ""
                if src and src not in ("human",):
                    if src == "sdk":
                        meta["sdk"] += 1
                        events.append(_ev("auto", ts, text=_slash(text)))
                    else:
                        events.append(_ev("notify", ts))
                    continue
                meta["human"] += 1
                events.append(_ev("human", ts, text=_slash(text)))
    meta["automated"] = meta["sdk"] > 0 and meta["human"] == 0
    return meta, events


# ---------- Codex ----------

_CODEX_SKIP = ('"type":"token_count"', '"type":"world_state"', '"type":"turn_context"', '"type":"reasoning"',
               '"type":"additional_tools"', '"type":"token_usage_record"')


def read_codex(path: Path) -> tuple[dict, list[dict]]:
    meta = {"engine": "codex", "session_id": path.stem, "file": str(path), "cwd": "", "title": "", "automated": False}
    events: list[dict] = []
    um_items: list[dict] = []   # item_completed UserMessage（没有 user_message 事件时的兜底）
    has_user_message = False
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            head = line[:160]
            if any(s in head for s in _CODEX_SKIP):
                continue
            try:
                o = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = _ts(o.get("timestamp"))
            p = o.get("payload") or {}
            if not ts or not isinstance(p, dict):
                continue
            typ, pt = o.get("type"), p.get("type")
            if typ == "session_meta":
                meta["cwd"] = p.get("cwd") or meta["cwd"]
                meta["session_id"] = p.get("id") or meta["session_id"]
                src = p.get("source")
                meta["automated"] = p.get("originator") == "codex_exec" or src == "exec"
                continue
            if typ == "response_item":
                if pt in ("function_call", "custom_tool_call", "local_shell_call", "web_search_call"):
                    events.append(_ev("agent", ts, tool=p.get("name") or pt))
                elif pt in ("function_call_output", "custom_tool_call_output") or (pt == "message" and p.get("role") == "assistant"):
                    # developer / system 消息是每轮开头注入的上下文（和人的消息同一时刻），不是 Agent 在干活
                    events.append(_ev("agent", ts))
                continue
            if typ != "event_msg":
                continue
            if pt == "user_message":
                has_user_message = True
                text = str(p.get("message") or "").strip()
                if text and not text.startswith(_SKIP_PREFIX):
                    events.append(_ev("auto" if meta["automated"] else "human", ts, text=text))
            elif pt == "agent_message":
                events.append(_ev("agent", ts, asks=_asks(str(p.get("message") or ""))))
            elif pt == "task_complete":
                events.append(_ev("agent", ts, end=True, asks=_asks(str(p.get("last_agent_message") or ""))))
            elif pt == "turn_aborted":
                events.append(_ev("human", ts, text=f"[turn_aborted {p.get('reason', '')}]"))
            elif pt in ("exec_approval_request", "apply_patch_approval_request"):
                events.append(_ev("agent", ts, approval=True))
            elif pt == "patch_apply_end":
                events.append(_ev("agent", ts, error=not p.get("success", True)))
            elif pt == "item_completed":
                item = p.get("item") or {}
                it = item.get("type")
                if it == "UserMessage":
                    text = "\n".join(c.get("text", "") for c in item.get("content") or [] if isinstance(c, dict)).strip()
                    if text and not text.startswith(_SKIP_PREFIX):
                        um_items.append(_ev("auto" if meta["automated"] else "human", ts, text=text))
                elif it == "CommandExecution":
                    code = item.get("exit_code")
                    events.append(_ev("agent", ts, error=code not in (None, 0, "0")))
                elif it:
                    events.append(_ev("agent", ts))
    if not has_user_message:
        events.extend(um_items)
    return meta, events


def promote_platform_chat(meta: dict, events: list[dict], chat_ids: set[str]) -> tuple[dict, list[dict]]:
    """平台对话面板走 claude -p / codex exec，日志里像脚本会话；但提示是人在面板里打的字，按人工交互算。"""
    if meta.get("session_id") not in chat_ids:
        return meta, events
    return ({**meta, "automated": False, "platform_chat": True},
            [{**e, "kind": "human"} if e["kind"] == "auto" else e for e in events])


# ---------- 统计 ----------

def summarize(meta: dict, events: list[dict], day: Date) -> dict | None:
    """把一个会话的事件流按某一天统计；当天没有事件返回 None。"""
    events = sorted(events, key=lambda e: e["ts"])
    # 分类要看整段历史（第一条消息、上一条 Agent 是否在提问）
    seen_prompt, asked = False, False
    for e in events:
        if e["kind"] in ("human", "auto"):
            if e["kind"] == "human":
                e["cls"] = classify(e.get("text", ""), not seen_prompt, asked)
            seen_prompt, asked = True, False
        elif e["kind"] == "agent":
            if "asks" in e:
                asked = e["asks"]
    day_ev = [e for e in events if e["ts"].date() == day]
    if not day_ev:
        return None
    active = 0.0
    waits: list[float] = []
    msgs: list[dict] = []
    prev = None
    for e in day_ev:
        if prev is not None:
            dt = (e["ts"] - prev["ts"]).total_seconds()
            if e["kind"] == "agent":
                active += min(dt, IDLE_CAP)
            elif e["kind"] == "human" and prev["kind"] in ("agent", "notify"):
                e["wait"] = dt
                waits.append(dt)
        if e["kind"] == "human":
            msgs.append({"t": e["ts"].strftime("%H:%M"), "kind": e["cls"], "text": e.get("text", "")[:TEXT_MAX],
                         "wait_min": round(e["wait"] / 60, 1) if "wait" in e else None})
        prev = e
    kinds = {k: 0 for k in KIND_LABELS}
    for m in msgs:
        kinds[m["kind"]] += 1
    agent_ev = [e for e in day_ev if e["kind"] == "agent"]
    start, end = day_ev[0]["ts"], day_ev[-1]["ts"]
    cwd = meta.get("cwd") or ""
    return {
        "engine": meta["engine"], "session_id": meta["session_id"], "file": meta["file"],
        "cwd": cwd, "project": Path(cwd).name if cwd else Path(meta["file"]).parent.name,
        "title": meta.get("title", ""), "automated": bool(meta.get("automated")),
        "start": start.isoformat(timespec="seconds"), "end": end.isoformat(timespec="seconds"),
        "wall_min": round((end - start).total_seconds() / 60, 1),
        "active_min": round(active / 60, 1),
        "human_turns": len(msgs), "kinds": kinds,
        "auto_prompts": sum(1 for e in day_ev if e["kind"] == "auto"),
        "wait_total_min": round(sum(w for w in waits if w <= WAIT_MAX) / 60, 1),
        "wait_median_min": round(statistics.median(waits) / 60, 1) if waits else 0,
        "tool_calls": sum(1 for e in agent_ev if e.get("tool")),
        "tool_errors": sum(1 for e in agent_ev if e.get("error")),
        "denials": sum(1 for e in agent_ev if e.get("denied")),
        "approval_requests": sum(1 for e in agent_ev if e.get("approval")),
        "api_errors": sum(1 for e in agent_ev if e.get("api_error")),
        "messages": msgs,
    }


def _claude_files(dirs: Iterable[str], since: float) -> list[Path]:
    out = []
    for d in dirs:
        root = Path(d).expanduser()
        if not root.is_dir():
            continue
        for p in root.glob("*/*.jsonl"):
            try:
                if p.stat().st_mtime >= since:
                    out.append(p)
            except OSError:
                pass
    return out


def _codex_files(dirs: Iterable[str], day: Date, since: float) -> list[Path]:
    out = []
    for d in dirs:
        root = Path(d).expanduser()
        for dd in (day - timedelta(days=1), day):
            sub = root / f"{dd:%Y}" / f"{dd:%m}" / f"{dd:%d}"
            if sub.is_dir():
                out += [p for p in sub.glob("*.jsonl") if p.stat().st_mtime >= since]
    return out


def scan(day: Date, session_dirs: dict, chat_ids: set[str] = frozenset()) -> list[dict]:
    since = datetime.combine(day, datetime.min.time()).timestamp()
    out = []
    jobs = [(read_claude, p) for p in _claude_files(session_dirs.get("claude", []), since)]
    jobs += [(read_codex, p) for p in _codex_files(session_dirs.get("codex", []), day, since)]
    for reader, p in jobs:
        try:
            s = summarize(*promote_platform_chat(*reader(p), chat_ids), day)
        except Exception as e:  # noqa: BLE001  坏文件不影响整体
            s = None
            out.append({"engine": "?", "file": str(p), "error": str(e)[:200]})
        if s:
            out.append(s)
    return sorted([s for s in out if "error" not in s], key=lambda s: s["start"])


def _peak_parallel(sessions: list[dict]) -> int:
    pts = []
    for s in sessions:
        pts += [(s["start"], 1), (s["end"], -1)]
    cur = peak = 0
    for _, d in sorted(pts, key=lambda x: (x[0], -x[1])):
        cur += d
        peak = max(peak, cur)
    return peak


def aggregate(sessions: list[dict]) -> dict:
    inter = [s for s in sessions if not s["automated"]]
    kinds = {k: sum(s["kinds"].get(k, 0) for s in sessions) for k in KIND_LABELS}
    by_project: dict[str, dict] = {}
    for s in sessions:
        p = by_project.setdefault(s["project"], {"sessions": 0, "human_turns": 0, "active_min": 0.0})
        p["sessions"] += 1
        p["human_turns"] += s["human_turns"]
        p["active_min"] = round(p["active_min"] + s["active_min"], 1)
    waits = [m["wait_min"] for s in sessions for m in s["messages"] if m["wait_min"] is not None]
    agg = {
        "v": VERSION, "sessions": len(sessions), "interactive": len(inter), "automated": len(sessions) - len(inter),
        "human_turns": sum(s["human_turns"] for s in sessions), "kinds": kinds,
        "active_min": round(sum(s["active_min"] for s in sessions), 1),
        "active_min_interactive": round(sum(s["active_min"] for s in inter), 1),
        "wall_min": round(sum(s["wall_min"] for s in sessions), 1),
        "wait_total_min": round(sum(s["wait_total_min"] for s in sessions), 1),
        "wait_median_min": round(statistics.median(waits), 1) if waits else 0,
        "tool_calls": sum(s["tool_calls"] for s in sessions),
        "tool_errors": sum(s["tool_errors"] for s in sessions),
        "denials": sum(s["denials"] for s in sessions),
        "approval_requests": sum(s["approval_requests"] for s in sessions),
        "peak_parallel": _peak_parallel(inter),
        "peak_parallel_all": _peak_parallel(sessions),
        "by_project": by_project,
    }
    agg["headline"] = headline(agg)
    return agg


def headline(a: dict) -> str:
    if not a.get("sessions"):
        return "无 Agent 会话"
    k = a.get("kinds", {})
    return (f"交互会话 {a['interactive']}（另自动 {a['automated']}）· 人工介入 {a['human_turns']} 次"
            f"（纠正 {k.get('correct', 0)} / 中断 {k.get('interrupt', 0)} / 确认 {k.get('approve', 0)}）"
            f" · Agent 活跃 {a.get('active_min_interactive', a['active_min']) / 60:.1f}h（含自动 {a['active_min'] / 60:.1f}h）· 等待中位 {a['wait_median_min']} 分"
            + (f" · 等你 {a['wait_wall_min']} 分（墙钟）" if "wait_wall_min" in a else "") + f" · 峰值并行 {a['peak_parallel']}")
