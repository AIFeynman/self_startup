"""全局设置：data/settings.json，缺省值在这里。UI 的「设置」页可改。"""
from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

from .db import DATA_DIR, ROOT

SETTINGS_PATH = DATA_DIR / "settings.json"

DEFAULTS: dict = {
    # 人重度干预时间窗（专注时间）；其余时间放可自动跑 / 低干预的任务
    "focus_windows": [{"start": "10:00", "end": "11:40"}, {"start": "13:30", "end": "16:50"}],
    "day_start": "08:30",
    "day_end": "23:00",
    # 同一时刻最多并行的自动任务数（Claude Code / Codex 并发度）
    "max_agent_concurrency": 3,
    "engines": {
        "default": "claude",            # claude / codex
        "claude": {
            # reclaude = 绑定了本机账号的 Claude Code 启动器（参数与 claude 一致），没有就用 claude
            "bin": "reclaude" if shutil.which("reclaude") else "claude",
            "model": "",
            "permission_mode": "acceptEdits",
            "allowed_tools": [
                "Read", "Glob", "Grep", "Write", "Edit", "WebSearch", "WebFetch",
                "Bash(curl:*)", "Bash(git:*)", "Bash(ls:*)", "Bash(cat:*)", "Bash(python3:*)", "Bash(uv:*)",
            ],
        },
        "codex": {"bin": "codex", "model": "", "sandbox": "workspace-write"},
        # 调研引擎：GrokBot 走 codex skill 里的 webhook 脚本；Muse 是桌面 App，无 CLI，走「复制 brief → 打开 App → 粘贴结果」
        "grokbot": {"script": str(Path.home() / ".codex/skills/grokbot-webhook/scripts/grokbot.py")},
        "muse": {"app": "Muse"},
    },
    # 复盘时分析的代码库 / 文档目录
    "repos": [],
    # Claude Code / Codex 会话日志位置（效率复盘）
    "session_dirs": {
        "claude": [str(Path.home() / ".claude/projects"), str(Path.home() / ".rec/claude/accounts/53616/config/projects")],
        "codex": [str(Path.home() / ".codex/sessions")],
    },
    # 信息收集
    "feed": {
        "learn_evolve_db": str(ROOT.parent / "learn_evolve/.news.db"),
        "interests": ["agent", "llm", "claude code", "codex", "reasoning", "rl", "eval", "coding agent", "mcp"],
        "rss": [
            "https://openai.com/news/rss.xml",
            "https://simonwillison.net/atom/everything/",
            "https://lilianweng.github.io/index.xml",
        ],
    },
    # 深度学习：已有的 codex 解析 skill
    "learn": {
        "paper_skill": str(Path.home() / ".codex/skills/paper-library/SKILL.md"),
        "github_skill": str(Path.home() / ".codex/skills/github-code-walkthrough/SKILL.md"),
        "output_dir": str(DATA_DIR / "learn"),
    },
}


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def load() -> dict:
    over = {}
    if SETTINGS_PATH.exists():
        try:
            over = json.loads(SETTINGS_PATH.read_text("utf-8"))
        except json.JSONDecodeError:
            over = {}
    return _merge(DEFAULTS, over)


def save(new: dict) -> dict:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    merged = _merge(load(), new)
    SETTINGS_PATH.write_text(json.dumps(merged, ensure_ascii=False, indent=2), "utf-8")
    return merged


def get(path: str, default=None):
    cur = load()
    for p in path.split("."):
        if not isinstance(cur, dict) or p not in cur:
            return default
        cur = cur[p]
    return cur
