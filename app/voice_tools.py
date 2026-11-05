"""语音通话的工具权限。本机 Claude 能用什么、每样能碰到什么都登记在这里：没登记或没打开的不给它。

加新工具：在 GROUPS 登记一组（写清能碰到什么），在 settings 的 voice_rt.permissions 给默认值（默认关），再在 slow_mcp 里接上。
"""
from __future__ import annotations

import sys
from pathlib import Path

from . import agent, settings

GROUPS = {
    "claude_code": {
        "label": "本机 Claude Code",
        "tools": agent.READONLY_TOOLS,
        "access": "只读：能读知识库、学习记录和代码，能上网；不能改文件、不能跑命令、不能开子 Agent、只加载下面的搜索",
        "sandbox": lambda: {"工具": agent.READONLY_TOOLS},
    },
    "web_search": {
        "label": "DeepSeek 搜索",
        "tools": ["web_search"],
        "access": "只把搜索词发给 DeepSeek，不读本机文件；搜到的原文只给本机 Claude，不发给百炼",
        "sandbox": lambda: {"网络": ["DeepSeek 接口"]},
    },
}


def enabled(group: str) -> bool:
    return group in GROUPS and settings.get(f"voice_rt.permissions.{group}", False) is True


def slow_mcp() -> dict:
    """本机 Claude 这次能用的 MCP 服务。密钥靠环境变量传下去，不写进命令行。"""
    if not enabled("web_search"):
        return {}
    root = str(Path(__file__).resolve().parent.parent)
    return {"voice_search": {"command": sys.executable, "args": ["-m", "app.voice_search_mcp"], "env": {"PYTHONPATH": root}}}


def listing() -> list[dict]:
    return [{"key": key, "label": g["label"], "tools": g["tools"], "access": g["access"], "sandbox": g["sandbox"](), "enabled": enabled(key)}
            for key, g in GROUPS.items()]
