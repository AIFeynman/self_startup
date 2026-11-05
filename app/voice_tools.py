"""语音通话的工具权限。接话的实时模型和本机 Claude 能用什么、每样能碰到什么都登记在这里：没登记或没打开的不给。

加新工具：在 GROUPS 登记一组（写清能碰到什么），在 settings 的 voice_rt.permissions 给默认值（默认关），再在 FAST_TOOLS 或 slow_mcp 里接上。
"""
from __future__ import annotations

import sys
from pathlib import Path

from . import agent, settings

GROUPS = {
    "claude_code": {
        "label": "本机 Claude Code",
        "cant": "读用户的资料和认真想问题",
        "tools": agent.READONLY_TOOLS,
        "access": "只读：能读知识库、学习记录和代码，能上网；不能改文件、不能跑命令、不能开子 Agent、只加载下面的搜索",
        "sandbox": lambda: {"工具": agent.READONLY_TOOLS},
    },
    "web_search": {
        "label": "DeepSeek 搜索",
        "cant": "上网查",
        "tools": ["web_search"],
        "access": "只把搜索词发给 DeepSeek，不读本机文件；搜到的原文只留在本机，百炼只拿到念的那句",
        "sandbox": lambda: {"网络": ["DeepSeek 接口"]},
    },
}

FAST_TOOLS = {"think_deep": "claude_code", "web_search": "web_search"}  # 接话的实时模型能用的工具


def enabled(group: str) -> bool:
    return group in GROUPS and settings.get(f"voice_rt.permissions.{group}", False) is True


def fast_allowed(tool: str) -> bool:
    return enabled(FAST_TOOLS.get(tool, ""))


def denied_note() -> str:
    """关掉的工具模型看不到，但提示词还在讲：告诉它别假装。"""
    off = [g["cant"] for key, g in GROUPS.items() if not enabled(key)]
    return f"\n\n这次通话不能{'、'.join(off)}。用户要这些就直说现在做不了，不要假装做了。" if off else ""


def slow_mcp() -> dict:
    """本机 Claude 这次能用的 MCP 服务。密钥靠环境变量传下去，不写进命令行。"""
    if not enabled("web_search"):
        return {}
    root = str(Path(__file__).resolve().parent.parent)
    return {"voice_search": {"command": sys.executable, "args": ["-m", "app.voice_search_mcp"], "env": {"PYTHONPATH": root}}}


def listing() -> list[dict]:
    return [{"key": key, "label": g["label"], "tools": g["tools"], "access": g["access"], "sandbox": g["sandbox"](), "enabled": enabled(key)}
            for key, g in GROUPS.items()]
