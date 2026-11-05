"""语音通话的前台：百炼实时模型只负责听（转写、判断说完）和念（TTS），答什么全由本机 Claude 定（voice_think）。

提示词只讲念稿：它自己接话常常答错，还会嘴上说搜却不搜（2026-11-04 实测）。
"""
from __future__ import annotations

import os

import httpx

DEFAULT_MODEL = "qwen-audio-3.1-realtime-flash"
DEFAULT_VOICE = "longanqian_v3.1"
SEARCH_TIMEOUT_S = 8
READ_PROMPT = """你是电话里的声音，不回答问题、不思考。每条文字消息都是要念给用户听的稿子，一字不差地念出来，只念稿子本身。听到用户说话不要回答。"""


def read_instructions(text: str) -> str:
    """每次念都点明稿子：刚听完用户说话时，短稿会和用户的话混起来念（「听得到，你说」念成「听得到吗」，2026-11-05 实测）。"""
    return f"{READ_PROMPT}\n这一条的稿子是：{text}\n只念稿子，不管用户说了什么。"


def web_search(query: str, limit: int = 5) -> dict:
    """DeepSeek 搜索，只留用得上的字段。出错也返回结果，让 Claude 能直说搜不到。"""
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not key:
        return {"error": "搜索没有配置"}
    base = os.environ.get("DEEPSEEK_API_BASE", "https://api.deepseek.com").rstrip("/")
    try:
        r = httpx.post(f"{base}/v1/tools/search", headers={"Authorization": f"Bearer {key}"},
                       json={"model": "deepseek-search", "query": query}, timeout=SEARCH_TIMEOUT_S, trust_env=False)
        r.raise_for_status()
        results = r.json().get("results") or []
    except (httpx.HTTPError, ValueError) as e:
        return {"error": f"搜索失败：{type(e).__name__}"}
    return {"results": [{"title": x.get("title", ""), "site": x.get("site_name", ""), "date": (x.get("date") or "")[:10], "url": x.get("url", ""),
                         "summary": (x.get("summary") or x.get("snippet") or "")[:300]} for x in results[:limit]]}


def endpoint(model: str = DEFAULT_MODEL) -> str:
    """百炼北京区地址；没配 Workspace ID 时报错，别连到别人的工作空间。"""
    workspace = os.environ.get("DASHSCOPE_WORKSPACE_ID", "").strip()
    if not workspace:
        raise RuntimeError("没有配置 DASHSCOPE_WORKSPACE_ID")
    # 控制台也会给完整地址（https://ws-xxx.cn-beijing.maas.aliyuncs.com/api/v1），只取其中的 ID
    workspace = workspace.split("://")[-1].split("/")[0].split(".")[0]
    return f"wss://{workspace}.cn-beijing.maas.aliyuncs.com/api-ws/v1/realtime?model={model}"


def headers() -> dict[str, str]:
    key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
    if not key:
        raise RuntimeError("没有配置 DASHSCOPE_API_KEY")
    return {"Authorization": f"Bearer {key}", "x-dashscope-dataInspection": "disable"}


def session_config(voice: str = DEFAULT_VOICE, speech_rate: float = 1.0, max_history_turns: int = 1,
                   turn_detection: dict | None = None) -> dict:
    # 只念稿不用记上下文，上下文在 Claude 那边；历史每轮都算钱
    return {
        "modalities": ["text", "audio"],
        "voice": voice,
        "speech_rate": speech_rate,
        "instructions": READ_PROMPT,
        "input_audio_format": "pcm",
        "output_audio_format": "pcm",
        "input_audio_transcription": {"language": "zh"},
        "max_history_turns": max_history_turns,
        "tools": [],
        "turn_detection": turn_detection or {"type": "smart_turn_v2"},
    }
