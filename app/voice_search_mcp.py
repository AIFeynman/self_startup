"""语音通话里本机 Claude 用的搜索工具：DeepSeek 搜索包成 MCP 服务（stdio，一行一个 JSON）。Claude 自带的 WebSearch 查国内和当天的事常常查不到（2026-11-04 实测）。"""
from __future__ import annotations

import json
import sys

from . import voice_rt

TOOL = {"name": "web_search", "description": "上网搜公开的最新事实（新闻、天气、价格、发布），返回几条网页摘要和链接。",
        "inputSchema": {"type": "object", "properties": {"query": {"type": "string", "description": "要搜的关键词，只写公开信息，不带用户的个人信息"}},
                        "required": ["query"]}}


def handle(msg: dict) -> dict | None:
    """一条请求的回复；通知不用回。"""
    method, msg_id = msg.get("method"), msg.get("id")
    if msg_id is None:
        return None
    if method == "initialize":
        result = {"protocolVersion": msg["params"]["protocolVersion"], "capabilities": {"tools": {}},
                  "serverInfo": {"name": "voice_search", "version": "1"}}
    elif method == "tools/list":
        result = {"tools": [TOOL]}
    elif method == "tools/call":
        found = voice_rt.web_search(str(msg["params"].get("arguments", {}).get("query", "")))
        result = {"content": [{"type": "text", "text": json.dumps(found, ensure_ascii=False)}], "isError": "error" in found}
    elif method == "ping":
        result = {}
    else:
        return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32601, "message": f"没有这个方法：{method}"}}
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def main() -> None:
    for line in sys.stdin:
        reply = handle(json.loads(line))
        if reply:
            print(json.dumps(reply, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
