"""今日精读卡的深度解读：论文、工程实践、新产品这些没有现成分析的卡，按原文补一份解读，先看内容再判断。
按卡缓存在 today_reads，一张只生成一次；页面请求时在后台生成，生成好前先给原文摘要。"""
from __future__ import annotations

import json
import re
import threading

from .. import db

SCHEMA = """
CREATE TABLE IF NOT EXISTS today_reads (key TEXT PRIMARY KEY, data TEXT NOT NULL, created_at TEXT);
"""

SECTIONS = ("核心问题", "怎么做的", "关键结果", "局限与争议", "对你意味着")
BACKGROUND = True
ARXIV = re.compile(r"\b(\d{4}\.\d{4,5})\b")
BULLET = re.compile(r"^\s*(?:[-*·•●]|\d+[.、)])\s*")

SYSTEM = """你是用户的技术与产品解读助手。根据给你的原文材料（标题、摘要、讨论要点），写一份让用户 3 分钟读懂的中文深度解读。
只用材料里有的事实和数字，材料没说的写“原文未提及”，不要编。每段用 2–4 条短的 markdown 列表，专有名词保留英文。
段落：
核心问题（它要解决什么问题，为什么之前没解决好）；
怎么做的（关键做法和机制，讲清楚为什么有效）；
关键结果（数字、对比、证据）；
局限与争议（适用边界、没验证的地方、可能的反对意见）；
对你意味着（结合用户画像：对他学 LLM / Agent、做 AI 知识讲解视频产品、找机会有什么用，给一个能动手验证的小实验）。
输出 JSON：{"核心问题": "", "怎么做的": "", "关键结果": "", "局限与争议": "", "对你意味着": ""}"""

_running: set[str] = set()
_lock = threading.Lock()


def _has(table: str) -> bool:
    return bool(db.row("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", [table]))


def _material(c: dict) -> dict:
    from . import today
    key = c["key"]
    texts: list[str] = []
    if key.startswith("feed:") and _has("feed_items"):
        if r := db.row("SELECT source, summary, url, extra FROM feed_items WHERE id=?", [key[5:]]):
            texts.append(r["summary"] or "")
            if r["source"] == "hn" and (d := today._hn_digest(key[5:])):
                texts.append(json.dumps(d, ensure_ascii=False)[:2500])
            if (m := ARXIV.search(r["url"] or "")) and _has("paper_items"):
                if p := db.row("SELECT abstract, tldr FROM paper_items WHERE arxiv=?", [m.group(1)]):
                    texts += [p["abstract"] or "", p["tldr"] or ""]
    elif key.startswith("xart:") and _has("x_art"):
        if r := db.row("SELECT summary, take, text FROM x_art WHERE id=?", [key[5:]]):
            texts += [r["summary"] or "", r["take"] or "", (r["text"] or "")[:4000]]
    texts = [t.strip() for t in texts if t and t.strip()]
    return {"title": c.get("title", ""), "label": c.get("label", ""), "summary": c.get("summary", ""),
            "takeaway": c.get("takeaway", ""), "material": texts}


def _fallback(c: dict) -> dict:
    m = _material(c)
    text = max([*m["material"], c.get("summary") or ""], key=len)
    return {"原文摘要": text} if text else {}


def _text(v) -> str:
    lines = v if isinstance(v, list) else str(v or "").splitlines()
    lines = [BULLET.sub("", str(x)).strip() for x in lines]
    lines = [x for x in lines if x]
    return "\n".join(f"- {x}" for x in lines) if len(lines) > 1 or isinstance(v, list) else "".join(lines)


def _generate(c: dict) -> None:
    from . import today
    try:
        out = today._llm(SYSTEM, {"profile": today.PROFILE, **_material(c)})
        read = {k: v[:1200] for k in SECTIONS if (v := _text(out.get(k)))}
        if len(read) >= 3:
            db.execute("INSERT OR REPLACE INTO today_reads (key, data, created_at) VALUES (?,?,?)",
                       [c["key"], json.dumps(read, ensure_ascii=False), db.now()])
    except Exception:  # noqa: BLE001  生成失败就继续给原文摘要，下次打开再试
        pass
    finally:
        with _lock:
            _running.discard(c["key"])


def fill(cards: list[dict]) -> None:
    todo = [c for c in cards if not c.get("reveal")]
    if not todo:
        return
    keys = [c["key"] for c in todo]
    cached = {r["key"]: {k: _text(v) for k, v in json.loads(r["data"]).items()} for r in
              db.rows(f"SELECT key, data FROM today_reads WHERE key IN ({','.join('?' * len(keys))})", keys)}
    for c in todo:
        if c["key"] in cached:
            c["reveal"], c["reading"] = cached[c["key"]], False
            continue
        with _lock:
            start = c["key"] not in _running
            _running.add(c["key"])
        if start:
            if BACKGROUND:
                threading.Thread(target=_generate, args=(dict(c),), daemon=True).start()
            else:
                _generate(c)
        got = db.row("SELECT data FROM today_reads WHERE key=?", [c["key"]])
        c["reveal"] = json.loads(got["data"]) if got else _fallback(c)
        with _lock:
            c["reading"] = c["key"] in _running
