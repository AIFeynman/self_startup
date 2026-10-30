"""全局设置：data/settings.json，缺省值在这里。UI 的「设置」页可改。"""
from __future__ import annotations

import copy
import json
import os
import shutil
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .db import DATA_DIR, ROOT

SETTINGS_PATH = DATA_DIR / "settings.json"
TZ_CACHE = "tz_inferred.json"   # 设置里 timezone 留空时，按作息推断的时区（app/modules/_tzinfer.py 写）

DEFAULTS: dict = {
    # 人重度干预时间窗（专注时间）；其余时间放可自动跑 / 低干预的任务
    "focus_windows": [{"start": "10:00", "end": "11:40"}, {"start": "13:30", "end": "16:50"}],
    "day_start": "08:30",
    # 你所在的时区（IANA 名，如 Asia/Shanghai）；留空 = 按会话作息自动推断（推断不出 / 和系统一致时跟随系统）。所有「几点 / 哪一天」都按它算：
    # 系统时区和你实际作息不一致时（比如系统是 America/Los_Angeles），专注时间窗、工作时间、日期边界都会整体错位
    "timezone": "",
    "day_end": "23:00",
    # 同一时刻最多并行的自动任务数（Claude Code / Codex 并发度）
    "max_agent_concurrency": 3,
    # 规划排好的自动任务（auto + Claude/Codex）到开始时间、依赖完成后自动派发，不用人点
    "plan_auto_dispatch": True,
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
        # 厂商博客 + 一线实践者；anthropic.com 无官方 RSS，用社区镜像（Olshansk/rss-feeds）
        "rss": [
            "https://openai.com/news/rss.xml",
            "https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_anthropic_news.xml",
            "https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_anthropic_engineering.xml",
            "https://deepmind.google/blog/rss.xml",
            "https://huggingface.co/blog/feed.xml",
            "https://simonwillison.net/atom/everything/",
            "https://www.latent.space/feed",
            "https://www.interconnects.ai/feed",
            "https://hamel.dev/index.xml",
            "https://eugeneyan.com/rss/",
            "https://magazine.sebastianraschka.com/feed",
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
    new = {k: v for k, v in new.items() if k != "timezone_effective"}
    merged = _merge(load(), new)
    SETTINGS_PATH.write_text(json.dumps(merged, ensure_ascii=False, indent=2), "utf-8")
    apply_timezone()
    return merged


_SYSTEM_TZ = os.environ.get("TZ")


def apply_timezone(tz: str | None = None) -> str:
    """把进程的本地时区设成设置里的 timezone（datetime.now()、日期边界、会话日志时间都跟着变）；
    留空用按作息推断的时区（data/tz_inferred.json），也没有就恢复系统时区。"""
    tz = load().get("timezone", "") if tz is None else tz
    if not tz:
        try:
            tz = json.loads((DATA_DIR / TZ_CACHE).read_text("utf-8")).get("tz", "")
        except (OSError, ValueError):
            tz = ""
    if tz:
        try:
            ZoneInfo(tz)
        except (ZoneInfoNotFoundError, ValueError):
            tz = ""  # 写错了就跟随系统，不要静默变成 UTC
    if tz:
        os.environ["TZ"] = tz
    elif _SYSTEM_TZ is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = _SYSTEM_TZ
    time.tzset()
    return time.tzname[0]


def system_utc_offset(at: datetime | None = None) -> float:
    """系统时区（不受 apply_timezone 影响）此刻的 UTC 偏移小时。"""
    name = _SYSTEM_TZ or str(Path("/etc/localtime").resolve()).partition("zoneinfo/")[2]
    try:
        z = ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return 0.0
    return (at or datetime.now(z)).astimezone(z).utcoffset().total_seconds() / 3600


def get(path: str, default=None):
    cur = load()
    for p in path.split("."):
        if not isinstance(cur, dict) or p not in cur:
            return default
        cur = cur[p]
    return cur
