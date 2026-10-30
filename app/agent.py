"""调用本地 Agent CLI：Claude Code（默认）/ Codex（备选）。

run_stream() 产出统一事件：
    {"type": "session", "id": "..."}      引擎侧会话 id（用于续聊）
    {"type": "text", "text": "..."}       助手文本（整段）
    {"type": "tool", "text": "..."}       工具调用摘要
    {"type": "error", "text": "..."}
    {"type": "done", "text": 最终文本, "engine": "claude|codex"}
Claude 启动失败或报错时自动回退到 Codex（仅新会话）。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Iterator

from . import settings
from .db import DATA_DIR, ROOT

API_BASE = os.environ.get("SELF_STARTUP_API") or f"http://127.0.0.1:{os.environ.get('PORT', '8780')}"

PLATFORM_GUIDE = f"""
你运行在「本地学习平台」中，作为某个板块的对话 Agent。平台 HTTP API：{API_BASE}
- 读写平台数据用 curl 调 API（JSON），例如：curl -s {API_BASE}/api/plan/day
- 所有接口列表：curl -s {API_BASE}/openapi.json | python3 -c 'import json,sys;[print(m.upper(),p) for p,v in json.load(sys.stdin)["paths"].items() for m in v]'
- 用户要求修改数据时直接调用接口完成并简述结果；只是讨论时不要写数据。
- 本地知识库（只读 markdown，自动同步）：{DATA_DIR / "kb"}。先读 INDEX.md；按日期看 daily/、按主题看 tags/；
  关键词检索用 curl -s "{API_BASE}/api/kb/search?q=关键词" 或 rg；先看 frontmatter 的 summary 再决定读哪几个文件，引用时给路径。
  回答涉及用户过往记录、学习、调研时，先查知识库。
- 默认中文回答，简洁、具体，不要过度设计。
""".strip()


def _skill_text(module: str) -> str:
    p = ROOT / "skills" / module / "SKILL.md"
    return p.read_text("utf-8") if p.exists() else ""


def build_system(module: str, context: str = "") -> str:
    parts = [PLATFORM_GUIDE, _skill_text(module)]
    if context:
        parts.append("## 当前数据快照\n" + context)
    return "\n\n".join(p for p in parts if p)


def available(engine: str) -> bool:
    cfg = settings.get(f"engines.{engine}", {}) or {}
    return bool(shutil.which(cfg.get("bin", engine)))


def _claude_cmd(prompt: str, system: str, session: str, add_dirs: list[str]) -> list[str]:
    cfg = settings.get("engines.claude", {})
    cmd = [cfg.get("bin", "claude"), "-p", prompt, "--output-format", "stream-json", "--verbose"]
    if session:
        cmd += ["--resume", session]
    if system:
        cmd += ["--append-system-prompt", system]
    if cfg.get("model"):
        cmd += ["--model", cfg["model"]]
    if cfg.get("permission_mode"):
        cmd += ["--permission-mode", cfg["permission_mode"]]
    if cfg.get("allowed_tools"):
        cmd += ["--allowedTools", *cfg["allowed_tools"]]
    for d in add_dirs:
        cmd += ["--add-dir", d]
    return cmd


def _codex_cmd(prompt: str, system: str, session: str, add_dirs: list[str], cwd: str) -> list[str]:
    cfg = settings.get("engines.codex", {})
    common = ["--json", "--skip-git-repo-check",
              "-c", "sandbox_workspace_write.network_access=true"]
    if cfg.get("model"):
        common += ["-m", cfg["model"]]
    if session:
        return [cfg.get("bin", "codex"), "exec", "resume", *common, session, prompt]
    full = f"{system}\n\n---\n\n{prompt}" if system else prompt
    cmd = [cfg.get("bin", "codex"), "exec", *common, "-s", cfg.get("sandbox", "workspace-write"), "-C", cwd]
    for d in add_dirs:
        cmd += ["--add-dir", d]
    return cmd + [full]


def _parse_claude(obj: dict) -> list[dict]:
    t = obj.get("type")
    out: list[dict] = []
    if t == "system" and obj.get("subtype") == "init":
        out.append({"type": "session", "id": obj.get("session_id", "")})
    elif t == "assistant":
        for block in obj.get("message", {}).get("content", []):
            if block.get("type") == "text" and block.get("text"):
                out.append({"type": "text", "text": block["text"]})
            elif block.get("type") == "tool_use":
                inp = block.get("input", {})
                brief = inp.get("command") or inp.get("file_path") or inp.get("pattern") or inp.get("url") or inp.get("query") or ""
                out.append({"type": "tool", "text": f"{block.get('name')}: {str(brief)[:200]}"})
    elif t == "result":
        if obj.get("is_error"):
            out.append({"type": "error", "text": str(obj.get("result") or obj.get("subtype"))})
        out.append({"type": "result", "text": obj.get("result") or "", "session": obj.get("session_id", "")})
    return out


def _parse_codex(obj: dict) -> list[dict]:
    t = obj.get("type")
    if t == "thread.started":
        return [{"type": "session", "id": obj.get("thread_id", "")}]
    if t == "item.completed":
        item = obj.get("item", {})
        it = item.get("type")
        if it in ("agent_message", "assistant_message") and item.get("text"):
            return [{"type": "text", "text": item["text"]}]
        if it in ("command_execution", "local_shell_call"):
            return [{"type": "tool", "text": f"shell: {str(item.get('command', ''))[:200]}"}]
        if it in ("web_search", "file_change", "mcp_tool_call"):
            return [{"type": "tool", "text": f"{it}: {json.dumps(item, ensure_ascii=False)[:200]}"}]
    if t in ("turn.failed", "error"):
        msg = obj.get("error", {}).get("message") if isinstance(obj.get("error"), dict) else obj.get("message")
        return [{"type": "error", "text": str(msg)[:1000]}]
    return []


def _child_env() -> dict:
    # 子进程不继承数据目录，避免 Agent 在项目里跑测试/服务时写进真实数据库
    env = {k: v for k, v in os.environ.items() if k != "SELF_STARTUP_DATA"}
    env["SELF_STARTUP_API"] = API_BASE
    return env


def _run(engine: str, cmd: list[str], cwd: str) -> Iterator[dict]:
    parse = _parse_claude if engine == "claude" else _parse_codex
    try:
        proc = subprocess.Popen(cmd, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, bufsize=1,
                                env=_child_env())
    except FileNotFoundError as e:
        yield {"type": "error", "text": f"{engine} 未安装: {e}", "fatal": True}
        return
    texts: list[str] = []
    final = ""  # Claude 的 result 只含最终回答，不含过程中的旁白
    errored = False
    assert proc.stdout
    for line in proc.stdout:
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        for ev in parse(obj):
            if ev["type"] == "text":
                texts.append(ev["text"])
            if ev["type"] == "error":
                errored = True
            if ev["type"] == "result":
                final = ev["text"]
                continue
            yield ev
    proc.wait()
    if proc.returncode != 0 and not texts:
        err = (proc.stderr.read() if proc.stderr else "")[-1500:]
        yield {"type": "error", "text": f"{engine} 退出码 {proc.returncode}: {err}", "fatal": True}
        return
    if not final and texts:
        # Codex 的最后一条 agent_message 是最终回答
        final = texts[-1] if engine == "codex" else "\n\n".join(texts)
    yield {"type": "done", "text": final, "engine": engine, "errored": errored and not texts}


def run_stream(prompt: str, *, engine: str = "", system: str = "", session: str = "",
               cwd: str | None = None, add_dirs: list[str] | None = None,
               fallback: bool = True) -> Iterator[dict]:
    engine = engine or settings.get("engines.default", "claude")
    # 默认不在项目目录里跑（acceptEdits 下可写文件），放到 data/workspace
    if not cwd:
        ws = DATA_DIR / "workspace"
        ws.mkdir(parents=True, exist_ok=True)
        cwd = str(ws)
    add_dirs = [d for d in (add_dirs or []) if d and Path(d).expanduser().exists()]
    order = [engine]
    if fallback and not session:
        order += [e for e in ("claude", "codex") if e != engine]
    for i, eng in enumerate(order):
        if not available(eng):
            yield {"type": "error", "text": f"{eng} 不可用，尝试备选" if i + 1 < len(order) else f"{eng} 不可用"}
            continue
        cmd = _claude_cmd(prompt, system, session, add_dirs) if eng == "claude" \
            else _codex_cmd(prompt, system, session, add_dirs, cwd)
        failed = False
        for ev in _run(eng, cmd, cwd):
            if ev["type"] == "done" and ev.get("errored") and i + 1 < len(order):
                failed = True
                break
            if ev.get("fatal") and i + 1 < len(order):
                failed = True
                yield {"type": "error", "text": ev["text"] + "；回退到备选引擎"}
                break
            yield ev
        if not failed:
            return
        yield {"type": "engine", "text": f"切换到 {order[i + 1]}"}


def run_once(prompt: str, **kw) -> dict:
    """阻塞执行，返回 {text, session, engine, log}。"""
    text, session, eng, log = "", "", kw.get("engine", ""), []
    for ev in run_stream(prompt, **kw):
        if ev["type"] == "session":
            session = ev["id"]
        elif ev["type"] == "done":
            text, eng = ev["text"], ev["engine"]
        elif ev["type"] in ("tool", "error", "engine"):
            log.append(f"[{ev['type']}] {ev['text']}")
    return {"text": text, "session": session, "engine": eng, "log": "\n".join(log)}
