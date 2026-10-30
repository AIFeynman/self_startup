"""今日已交付 · 从 Claude Code / Codex 会话日志里找「有交付物」的事：推送、部署、PR、发布、文档材料。

口径（「已交付」= 有交付物，且之后没再改代码、会话也不在跑）：
    delivered     有成功的 push / 部署 / PR / 发布，且之后没再改代码；或只产出了文档材料（没改代码）
    changed_after 交付过，但之后又改了代码（还在修改中）
    committed     只 commit 了没推送
平台自己的后台任务（调研报告、深读笔记）完成即算交付，见 agents.deliveries()。
解析结果按 (路径, mtime, 大小) 缓存。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import date as Date, datetime
from pathlib import Path

from ._agents_scan import _clip, _files, classify, _parse, read_claude, read_codex
from ._review_sessions import _ts

_GIT = r"\bgit\s+(?:-C\s+\S+\s+|-c\s+\S+\s+)*"
KINDS = [  # (kind, 中文, 正则) —— 顺序即优先级
    ("push", "推送", re.compile(_GIT + r"push\b(?!.*--dry-run)")),
    ("deploy", "部署", re.compile(
        r"\b(?:vercel(?:\s+deploy|\s+--prod)|netlify\s+deploy|fly(?:ctl)?\s+deploy|wrangler\s+(?:pages\s+)?deploy|firebase\s+deploy"
        r"|kubectl\s+(?:apply|rollout)|helm\s+(?:upgrade|install)|docker\s+push|gcloud\s+\S+(?:\s+\S+)*\s+deploy|railway\s+up"
        r"|(?:serverless|sls)\s+deploy|terraform\s+apply|make\s+deploy|(?:npm|pnpm|yarn)\s+(?:run\s+)?deploy\S*)\b"
        r"|\S*deploy\S*\.sh\b|\b(?:rsync|scp)\b.*\s\S+@[\w.-]+:")),
    ("pr", "PR", re.compile(r"\bgh\s+pr\s+(?:create|merge)\b")),
    ("release", "发布", re.compile(r"\bgh\s+release\s+create\b|\b(?:npm|cargo|uv|poetry)\s+publish\b|\btwine\s+upload\b")),
    ("commit", "提交", re.compile(_GIT + r"commit\b")),
]
STRONG = {"push", "deploy", "pr", "release", "publish"}
LABEL = {k: l for k, l, _ in KINDS} | {"publish": "发布页面", "doc": "文档材料"}
DOC_EXT = {".md", ".mdx", ".html", ".htm", ".pdf", ".docx", ".pptx", ".xlsx", ".csv", ".ipynb", ".png", ".jpg", ".jpeg", ".svg", ".webp"}
_FAIL = re.compile(r"\brejected\b|^fatal:|^error:|failed to push|Permission denied|Authentication failed", re.I | re.M)
_READONLY = re.compile(r"^\s*(?:grep|rg|cat|echo|sed|head|tail|less|man|which|type)\b")

_cache: dict[str, tuple[tuple, list]] = {}


def classify_cmd(cmd: str) -> str:
    """一条 shell 命令里最重要的交付动作，没有返回 ''。"""
    found = [kind for part in re.split(r"&&|\|\||;|\n", cmd or "") if not _READONLY.match(part)
             for kind, _, rx in KINDS if rx.search(part)]
    return _best(found)


ORDER = ["push", "deploy", "pr", "release", "publish", "commit"]


def _best(kinds: list[str]) -> str:
    return min(kinds, key=ORDER.index) if kinds else ""


def _file_kind(path: str) -> str:
    return "doc" if Path(path).suffix.lower() in DOC_EXT else "code"


def _out_text(content) -> str:
    if isinstance(content, str):
        return content
    return "\n".join(b.get("text", "") for b in content or [] if isinstance(b, dict))


def _ok(kind: str, failed: bool, out: str) -> bool:
    return not failed and not (kind in STRONG | {"commit"} and _FAIL.search(out or ""))


# ---------- 读事件 ----------

def actions_claude(path: Path) -> list[dict]:
    """[{ts, kind, ok, detail}]；kind ∈ push/deploy/pr/release/commit/publish/doc/code。"""
    pending: dict[str, dict] = {}
    out: list[dict] = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            if '"tool_use"' not in line and '"tool_result"' not in line:
                continue
            try:
                o = json.loads(line)
            except json.JSONDecodeError:
                continue
            if o.get("isSidechain"):
                continue
            ts = _ts(o.get("timestamp"))
            for b in (o.get("message") or {}).get("content") or []:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "tool_use":
                    name, inp = b.get("name", ""), b.get("input") or {}
                    a = None
                    if name == "Bash":
                        cmd = str(inp.get("command") or "")
                        k = classify_cmd(cmd)
                        a = {"kind": k, "detail": _clip(cmd, 160)} if k else None
                    elif name in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
                        p = str(inp.get("file_path") or inp.get("notebook_path") or "")
                        a = {"kind": _file_kind(p), "detail": p} if p else None
                    elif name == "Artifact" and (inp.get("action") or "publish") == "publish" and not inp.get("asset"):
                        a = {"kind": "publish", "detail": str(inp.get("file_path") or inp.get("url") or "")}
                    if a:
                        a.update(ts=ts, ok=True)
                        pending[b.get("id", "")] = a
                        out.append(a)
                elif b.get("type") == "tool_result" and b.get("tool_use_id") in pending:
                    a = pending.pop(b["tool_use_id"])
                    a["ok"] = _ok(a["kind"], bool(b.get("is_error")), _out_text(b.get("content")))
    return out


def actions_codex(path: Path) -> list[dict]:
    out: list[dict] = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            if '"item_completed"' not in line or ('"CommandExecution"' not in line and '"FileChange"' not in line):
                continue
            try:
                o = json.loads(line)
            except json.JSONDecodeError:
                continue
            it = (o.get("payload") or {}).get("item") or {}
            ts = _ts(o.get("timestamp"))
            if it.get("type") == "CommandExecution":
                cmd = it.get("command")
                cmd = cmd[-1] if isinstance(cmd, list) and cmd else str(cmd or "")
                k = classify_cmd(cmd)
                if k:
                    failed = it.get("status") == "failed" or (it.get("exit_code") not in (0, None))
                    out.append({"ts": ts, "kind": k, "detail": _clip(cmd, 160),
                                "ok": _ok(k, failed, str(it.get("aggregated_output") or ""))})
            elif it.get("type") == "FileChange" and it.get("status") != "failed":
                for p in (it.get("changes") or {}):
                    out.append({"ts": ts, "kind": _file_kind(p), "detail": p, "ok": True})
    return out


def _actions(path: Path, engine: str) -> list[dict]:
    try:
        st = path.stat()
    except OSError:
        return []
    key = (st.st_mtime, st.st_size)
    hit = _cache.get(str(path))
    if hit and hit[0] == key:
        return hit[1]
    try:
        acts = (actions_claude if engine == "claude" else actions_codex)(path)
    except Exception:  # noqa: BLE001
        acts = []
    _cache[str(path)] = (key, acts)
    return acts


# ---------- 判定 ----------

def judge(acts: list[dict]) -> dict | None:
    """一个会话当天的动作 → 交付结论；没有交付迹象返回 None。"""
    ok = [a for a in acts if a["ok"] and a["ts"]]
    code = [a["ts"] for a in ok if a["kind"] == "code"]
    strong = [a for a in ok if a["kind"] in STRONG]
    commits = [a for a in ok if a["kind"] == "commit"]
    docs = [a for a in ok if a["kind"] == "doc"]
    last_code = max(code) if code else None
    if strong:
        last = max(a["ts"] for a in strong)
        status = "delivered" if not last_code or last >= last_code else "changed_after"
        kind = _best([a["kind"] for a in strong])
    elif commits and (not last_code or max(a["ts"] for a in commits) >= last_code):
        status, kind, last = "committed", "commit", max(a["ts"] for a in commits)
    elif docs and not code:
        status, kind, last = "delivered", "doc", max(a["ts"] for a in docs)
    else:
        return None
    kinds = sorted({a["kind"] for a in strong + commits}, key=ORDER.index)
    files = list(dict.fromkeys(a["detail"] for a in docs))
    return {"status": status, "kind": kind, "kinds": kinds, "labels": [LABEL.get(k, k) for k in kinds or [kind]],
            "at": last.strftime("%H:%M"), "last_code": last_code.strftime("%H:%M") if last_code else "",
            "commands": [a["detail"] for a in strong + commits][-4:],
            "docs": [p for p in files if os.path.exists(p)][:8], "docs_total": len(files),
            "code_edits": len(code)}


def _dirty(cwd: str, memo: dict) -> int | None:
    """仓库现在还有几个未提交改动（None = 不是 git 仓库 / 读不到）。"""
    if not cwd or not os.path.isdir(cwd):
        return None
    if cwd not in memo:
        try:
            r = subprocess.run(["git", "-C", cwd, "status", "--porcelain"], capture_output=True, text=True, timeout=3)
            memo[cwd] = len([ln for ln in r.stdout.splitlines() if ln.strip()]) if r.returncode == 0 else None
        except (OSError, subprocess.SubprocessError):
            memo[cwd] = None
    return memo[cwd]


def scan(session_dirs: dict, day: Date, skip_cwd: str = "", now: datetime | None = None) -> list[dict]:
    """当天有交付迹象的会话，按交付时间倒序。skip_cwd：平台自己跑 Agent 的目录（那些算平台任务）。"""
    now = now or datetime.now()
    start = datetime.combine(day, datetime.min.time())
    seen, out, memo = set(), [], {}
    for path, reader in _files(session_dirs, start):
        engine = "claude" if reader is read_claude else "codex"
        s = _parse(path, reader)
        if not s or not s["last"] or s["session_id"] in seen or s["last"] < start:
            continue
        if skip_cwd and (s["cwd"] or "").startswith(skip_cwd):
            continue
        seen.add(s["session_id"])
        acts = [a for a in _actions(path, engine) if a["ts"] and a["ts"].date() == day]
        j = judge(acts)
        if not j:
            continue
        state, reason = classify(s, now)
        if state == "running" and j["status"] == "delivered":
            j["status"] = "changed_after"  # 还在跑，不算交付完
        j.update(key=f"{engine}:{s['session_id']}", engine=engine, session_id=s["session_id"], automated=s["automated"],
                 project=os.path.basename(s["cwd"].rstrip("/")) or "?", cwd=s["cwd"], branch=s["branch"],
                 title=_clip(s["title"] or s["first_human"] or "（无标题）", 80), summary=_clip(s["last_agent"], 300),
                 state=state, reason=reason)
        if j["kind"] in STRONG | {"commit"}:
            j["dirty"] = _dirty(s["cwd"], memo)
        out.append(j)
    out.sort(key=lambda x: x["at"], reverse=True)
    return out
