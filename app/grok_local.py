"""从 Grok Bot 桌面版本机的聊天记录里取回答（只读）。

GrokBot webhook 的正常回传要靠 Grok Bot 在本机执行 reply 命令；命令被审批框拒绝、Mac 掉线或
token 丢了时，回答只留在 Grok Bot 的聊天里。桌面版把每个聊天最近的消息存成 JSON：
<app_data>/*.blob → {"value": {"entries": [{kind, role, requestId, content | message.content, isStreaming}, ...]}}
这里按 request_id 找到提到它的那一轮回复（同一 requestId 的 send-message），取其中的回答正文。
"""
from __future__ import annotations

import json
from pathlib import Path

from . import settings

DEFAULT_DIR = Path.home() / "Library/Application Support/Grok Bot/sand-client-persistence"
MIN_LEN = 200  # 太短的多半只是「回传失败」之类的状态说明，不当回答


def _dir() -> Path:
    return Path(settings.get("engines.grokbot.app_data", "") or DEFAULT_DIR).expanduser()


def _text(e: dict) -> str:
    return str(e.get("content") or (e.get("message") or {}).get("content") or "")


def find_reply(request_id: str) -> str:
    """找到返回回答正文，找不到返回空串。同一轮里优先取不含 request_id 的消息（状态说明通常带着它）。"""
    if not request_id:
        return ""
    best: tuple[float, str] = (0, "")
    for f in _dir().glob("*.blob"):
        try:
            raw = f.read_text("utf-8")
            if request_id not in raw:
                continue
            entries = json.loads(raw)["value"]["entries"]
        except Exception:  # noqa: BLE001
            continue
        for e in entries:
            if request_id not in json.dumps(e, ensure_ascii=False) or not e.get("requestId"):
                continue
            turn = [x for x in entries if x.get("kind") == "send-message" and x.get("requestId") == e["requestId"]]
            if not turn or any(x.get("isStreaming") for x in turn):
                continue
            body = [_text(x) for x in turn if request_id not in _text(x)] or [_text(x) for x in turn]
            ans = "\n\n".join(t.strip() for t in body if t.strip())
            ts = max(x.get("timestampMs") or 0 for x in turn)
            if len(ans) >= MIN_LEN and ts >= best[0]:
                best = (ts, ans)
    return best[1]
