"""语音通话的工具权限。模型能用什么、每样能碰到什么都登记在这里：没登记或没打开的不告诉模型，调用了也不执行。

加新工具：在 GROUPS 登记一组（写清能碰到什么），在 settings 的 voice_rt.permissions 给默认值（默认关），再在 voice_call._on_tool 里实现。
"""
from __future__ import annotations

from . import agent, settings

GROUPS = {
    "claude_code": {
        "label": "本机 Claude Code",
        "tools": ["think_deep", "update_thinking", "get_thinking_status", "cancel_thinking"],
        "access": "只读：能读知识库、学习记录和代码，能上网；不能改文件、不能跑命令、不能开子 Agent、不加载 MCP",
        "sandbox": lambda: {"工具": agent.READONLY_TOOLS},
        "cant": "读用户资料、认真想问题",
    },
    "web_search": {
        "label": "DeepSeek 搜索",
        "tools": ["web_search"],
        "access": "只把搜索词发给 DeepSeek，整理也在 DeepSeek；不读本机文件，搜到的原文不发给百炼",
        "sandbox": lambda: {"网络": ["DeepSeek 接口"]},
        "cant": "上网搜",
    },
}


def enabled(group: str) -> bool:
    return group in GROUPS and settings.get(f"voice_rt.permissions.{group}", False) is True


def tool_allowed(tool: str) -> bool:
    return any(tool in g["tools"] and enabled(key) for key, g in GROUPS.items())


def denied_note() -> str:
    """关掉的工具模型看不到，但提示词还在讲：告诉它别假装。"""
    off = [g["cant"] for key, g in GROUPS.items() if not enabled(key)]
    return f"\n\n这次通话不能{'、'.join(off)}。用户要这些就直说现在做不了，不要假装做了。" if off else ""


def listing() -> list[dict]:
    return [{"key": key, "label": g["label"], "tools": g["tools"], "access": g["access"], "sandbox": g["sandbox"](), "enabled": enabled(key)}
            for key, g in GROUPS.items()]
