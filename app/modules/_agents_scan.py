"""Agent 看板 · 读取本地 Claude Code / Codex 会话日志，判断每个会话现在处于什么状态。

只读、按 (路径, mtime, 大小) 缓存解析结果；看板每 10 秒刷新也只重读有变化的文件。
每个会话产出一张卡片：
    title        自定义标题，否则第一条人工消息
    last_human   最近一条人工消息；last_agent 最近一段 Agent 文本（最终回答优先）
    plan         最近的计划/待办（Claude: TodoWrite / update_plan；Codex: update_plan），[{text, status}]
    state        running 运行中 / attention 等你处理 / review 待验收
    reason       状态原因：执行中 / 等你回复 / 等待批准？ / 可能卡住 / 已中断 / 出错 / 已完成
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path

from ._review_sessions import _SKIP_PREFIX, _asks, _claude_text, _slash, _ts

FRESH = 120          # 秒：日志在这段时间内有写入，视为正在跑
STUCK = 20 * 60      # 秒：回合未结束但这么久没动静，视为可能卡住 / 等批准
TEXT_MAX = 400

_cache: dict[str, tuple[tuple, dict]] = {}


def _clip(s: str, n: int = TEXT_MAX) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else s[:n] + "…"


# ---------- 计划 / 待办 ----------

def _norm_status(s: str) -> str:
    s = (s or "").lower()
    return "done" if s in ("completed", "done") else "doing" if s in ("in_progress", "doing", "active") else "todo"


def _apply_update_plan(plan: list[dict], inp: dict) -> list[dict]:
    """Claude 桌面版 update_plan：items 全量替换；advance / done / start 增量更新。"""
    if isinstance(inp.get("items"), list):
        return [{"text": str(i.get("content") or i.get("step") or ""), "status": _norm_status(i.get("status"))} for i in inp["items"]]
    plan = [dict(p) for p in plan]
    if inp.get("advance"):
        for p in plan:
            if p["status"] == "doing":
                p["status"] = "done"
                break
        for p in plan:
            if p["status"] == "todo":
                p["status"] = "doing"
                break
    for i in inp.get("done") or []:
        if 0 < int(i) <= len(plan):
            plan[int(i) - 1]["status"] = "done"
    if inp.get("start") and 0 < int(inp["start"]) <= len(plan):
        for p in plan:
            if p["status"] == "doing":
                p["status"] = "todo"
        plan[int(inp["start"]) - 1]["status"] = "doing"
    return plan


def _plan_from_tool(name: str, inp, plan: list[dict]) -> list[dict] | None:
    if isinstance(inp, str):
        try:
            inp = json.loads(inp)
        except json.JSONDecodeError:
            return None
    if not isinstance(inp, dict):
        return None
    if name == "TodoWrite" and isinstance(inp.get("todos"), list):
        return [{"text": str(t.get("content") or ""), "status": _norm_status(t.get("status"))} for t in inp["todos"]]
    if name.endswith("update_plan"):
        if isinstance(inp.get("plan"), list):  # Codex
            return [{"text": str(p.get("step") or ""), "status": _norm_status(p.get("status"))} for p in inp["plan"]]
        return _apply_update_plan(plan, inp)
    return None


# ---------- Claude Code ----------

def read_claude(path: Path) -> dict:
    s = {"engine": "claude", "session_id": path.stem, "file": str(path), "cwd": "", "title": "", "branch": "",
         "first_human": "", "last_human": "", "last_agent": "", "plan": [], "humans": 0, "sdk": 0, "tools": 0,
         "start": None, "last": None, "open": False, "pending_tool": False, "interrupted": False, "error": "", "asks": False}
    pending: set[str] = set()
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            if '"type":"user"' not in line and '"type":"assistant"' not in line and '"custom-title"' not in line:
                continue
            try:
                o = json.loads(line)
            except json.JSONDecodeError:
                continue
            t = o.get("type")
            if t == "custom-title":
                s["title"] = o.get("customTitle") or s["title"]
                continue
            if o.get("isSidechain") or t not in ("user", "assistant"):
                continue
            ts = _ts(o.get("timestamp"))
            if not ts:
                continue
            s["start"] = s["start"] or ts
            s["last"] = ts
            s["cwd"] = s["cwd"] or o.get("cwd") or ""
            s["branch"] = o.get("gitBranch") or s["branch"]
            msg = o.get("message") or {}
            content = msg.get("content")
            if t == "assistant":
                if msg.get("model") == "<synthetic>" and o.get("isApiErrorMessage"):
                    s["error"] = _clip(_claude_text(content), 160)
                for b in content or []:
                    if not isinstance(b, dict):
                        continue
                    if b.get("type") == "text" and b.get("text", "").strip():
                        s["last_agent"] = b["text"]
                    elif b.get("type") == "tool_use":
                        s["tools"] += 1
                        pending.add(b.get("id", ""))
                        p = _plan_from_tool(b.get("name", ""), b.get("input"), s["plan"])
                        if p is not None:
                            s["plan"] = p
                stop = msg.get("stop_reason")
                if stop == "end_turn":
                    s["open"] = False
                    s["asks"] = _asks(s["last_agent"])
                elif stop:
                    s["open"] = True
                continue
            # user
            if isinstance(content, list):
                for b in content:
                    if isinstance(b, dict) and b.get("type") == "tool_result":
                        pending.discard(b.get("tool_use_id", ""))
            text = _claude_text(content).strip()
            if not text or o.get("isMeta") or text.startswith(_SKIP_PREFIX):
                continue
            origin = o.get("origin") if isinstance(o.get("origin"), dict) else {}
            src = origin.get("kind") or o.get("turnOrigin") or ""
            if src == "sdk":
                s["sdk"] += 1
            elif src and src != "human":
                continue
            if text.startswith("[Request interrupted"):
                s["interrupted"], s["open"] = True, False
                continue
            text = _slash(text)
            s["humans"] += 0 if src == "sdk" else 1
            s["first_human"] = s["first_human"] or text
            s["last_human"] = text
            s["interrupted"], s["open"], s["error"], s["asks"] = False, True, "", False
    s["pending_tool"] = bool(pending) and s["open"]
    s["automated"] = s["sdk"] > 0 and s["humans"] == 0
    return s


# ---------- Codex ----------

def read_codex(path: Path) -> dict:
    s = {"engine": "codex", "session_id": path.stem, "file": str(path), "cwd": "", "title": "", "branch": "",
         "first_human": "", "last_human": "", "last_agent": "", "plan": [], "humans": 0, "tools": 0, "automated": False,
         "start": None, "last": None, "open": False, "pending_tool": False, "interrupted": False, "error": "", "asks": False}
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            head = line[:200]
            if '"token_count"' in head or '"Reasoning"' in line[:400]:
                continue
            try:
                o = json.loads(line)
            except json.JSONDecodeError:
                continue
            p = o.get("payload") or {}
            ts = _ts(o.get("timestamp"))
            if not isinstance(p, dict) or not ts:
                continue
            typ, pt = o.get("type"), p.get("type")
            if typ == "session_meta":
                s["cwd"] = p.get("cwd") or s["cwd"]
                s["session_id"] = p.get("id") or s["session_id"]
                s["automated"] = p.get("originator") == "codex_exec" or p.get("source") == "exec"
                s["branch"] = (p.get("git") or {}).get("branch") or ""
                continue
            s["start"] = s["start"] or ts
            s["last"] = ts
            if typ == "response_item" and pt in ("function_call", "custom_tool_call"):
                s["tools"] += 1
                plan = _plan_from_tool(p.get("name", ""), p.get("arguments") or p.get("input"), s["plan"])
                if plan is not None:
                    s["plan"] = plan
                continue
            if typ != "event_msg":
                continue
            text = ""
            if pt == "user_message":
                text = str(p.get("message") or "")
            elif pt == "item_completed":
                item = p.get("item") or {}
                it = item.get("type")
                if it == "UserMessage" and not s.get("_um"):
                    text = "\n".join(c.get("text", "") for c in item.get("content") or [] if isinstance(c, dict))
                elif it == "AgentMessage":
                    msg = "\n".join(c.get("text", "") for c in item.get("content") or [] if isinstance(c, dict))
                    if msg.strip():
                        s["last_agent"] = msg
                elif it in ("CommandExecution", "McpToolCall", "FileChange", "Extension"):
                    s["tools"] += 1
            elif pt == "agent_message":
                s["last_agent"] = str(p.get("message") or "") or s["last_agent"]
            elif pt == "task_started":
                s["open"], s["interrupted"], s["error"] = True, False, ""
            elif pt == "task_complete":
                s["open"] = False
                s["last_agent"] = str(p.get("last_agent_message") or "") or s["last_agent"]
                s["asks"] = _asks(s["last_agent"])
            elif pt == "turn_aborted":
                s["open"], s["interrupted"] = False, True
            elif pt in ("exec_approval_request", "apply_patch_approval_request"):
                s["pending_tool"] = True
            elif pt in ("exec_command_begin", "exec_command_end", "patch_apply_end"):
                s["pending_tool"] = False
            elif pt == "error":
                s["error"] = _clip(str(p.get("message") or ""), 160)
            if pt == "user_message":
                s["_um"] = True
            text = text.strip()
            if text and not text.startswith(_SKIP_PREFIX):
                s["humans"] += 0 if s["automated"] else 1
                s["first_human"] = s["first_human"] or text
                s["last_human"] = text
                s["open"] = True
    s.pop("_um", None)
    return s


# ---------- 状态与扫描 ----------

def classify(s: dict, now: datetime) -> tuple[str, str]:
    """返回 (state, reason)。"""
    idle = (now - s["last"]).total_seconds() if s["last"] else 1e9
    if s["error"] and not s["open"]:
        return "attention", "出错"
    if s["interrupted"]:
        return "attention", "已中断"
    if s["open"]:
        if idle < FRESH:
            return "running", "执行中"
        if s["pending_tool"]:
            return "attention", "等待批准？"
        if idle < STUCK:
            return "running", "执行中（较久未输出）"
        return "attention", "可能卡住"
    if s["asks"]:
        return "attention", "等你回复"
    left = sum(p["status"] != "done" for p in s["plan"])
    if left and s["plan"]:
        return "review", f"已停 · 计划 {len(s['plan']) - left}/{len(s['plan'])}"
    return "review", "已完成"


def _parse(path: Path, reader) -> dict | None:
    try:
        st = path.stat()
    except OSError:
        return None
    key = (st.st_mtime, st.st_size)
    hit = _cache.get(str(path))
    if hit and hit[0] == key:
        return hit[1]
    try:
        s = reader(path)
    except Exception:  # noqa: BLE001 —— 坏文件跳过
        return None
    s["mtime"] = st.st_mtime
    _cache[str(path)] = (key, s)
    return s


def _files(session_dirs: dict, since: datetime) -> list[tuple[Path, object]]:
    ts = since.timestamp()
    out = []
    for d in session_dirs.get("claude", []):
        root = Path(d).expanduser()
        if root.is_dir():
            for p in root.glob("*/*.jsonl"):
                try:
                    if p.stat().st_mtime >= ts:
                        out.append((p, read_claude))
                except OSError:
                    pass
    for d in session_dirs.get("codex", []):
        root = Path(d).expanduser()
        day = since.date()
        while day <= datetime.now().date():
            sub = root / f"{day:%Y}" / f"{day:%m}" / f"{day:%d}"
            if sub.is_dir():
                out += [(p, read_codex) for p in sub.glob("*.jsonl") if p.stat().st_mtime >= ts]
            day += timedelta(days=1)
    return out


def scan(session_dirs: dict, hours: float = 24, now: datetime | None = None) -> list[dict]:
    now = now or datetime.now()
    since = now - timedelta(hours=hours)
    seen, cards = set(), []
    for path, reader in _files(session_dirs, since):
        s = _parse(path, reader)
        if not s or not s["last"] or s["session_id"] in seen:
            continue
        seen.add(s["session_id"])
        state, reason = classify(s, now)
        plan = s["plan"]
        cards.append({
            "key": f"{s['engine']}:{s['session_id']}", "engine": s["engine"], "session_id": s["session_id"],
            "project": os.path.basename(s["cwd"].rstrip("/")) or "?", "cwd": s["cwd"], "branch": s["branch"],
            "title": _clip(s["title"] or s["first_human"] or "（无标题）", 80),
            "last_human": _clip(s["last_human"], 240), "last_agent": _clip(s["last_agent"]),
            "plan": plan, "plan_done": sum(p["status"] == "done" for p in plan),
            "plan_current": next((p["text"] for p in plan if p["status"] == "doing"), ""),
            "humans": s["humans"], "tools": s["tools"], "automated": s["automated"],
            "start": s["start"].isoformat(timespec="seconds") if s["start"] else "",
            "last": s["last"].isoformat(timespec="seconds"), "idle_min": round((now - s["last"]).total_seconds() / 60, 1),
            "state": state, "reason": reason, "error": s["error"], "file": s["file"],
        })
    cards.sort(key=lambda c: c["last"], reverse=True)
    return cards
