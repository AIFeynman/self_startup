"""大模型用量记账：Claude CLI（json / stream-json 的 result）、Codex（turn.completed）、DeepSeek（usage）、DeepSeek 搜索、
Jev（TypeSafe 判别模型）、百炼实时语音，每次调用一行写进 llm_usage；拿不到 token 的（搜索、Jev 没回 usage 时）也记一行，算调用次数。"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from fastapi import APIRouter

from . import db

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/usage", tags=["usage"])

FIELDS = ("input_tokens", "output_tokens", "cache_read", "cache_write", "cost_usd")
# DeepSeek 美元 / token：缓存命中、未命中、输出（2026-11 官方价）
DEEPSEEK_PRICE = (0.0028e-6, 0.14e-6, 0.28e-6)
USD_PER_CNY = 1 / 7.1   # 百炼按人民币计价，折成美元和其他调用放一起看；汇率取 2026-11 的大致值


def empty() -> dict:
    return {"model": "", **{k: 0 for k in FIELDS}}


def from_claude(obj: dict) -> dict:
    u = obj.get("usage") or {}
    return {"model": ",".join(obj.get("modelUsage") or {}),
            "input_tokens": u.get("input_tokens", 0), "output_tokens": u.get("output_tokens", 0),
            "cache_read": u.get("cache_read_input_tokens", 0), "cache_write": u.get("cache_creation_input_tokens", 0),
            "cost_usd": float(obj.get("total_cost_usd") or 0)}


def from_codex(obj: dict) -> dict:
    u = obj.get("usage") or {}
    cached = u.get("cached_input_tokens", 0)
    return {**empty(), "input_tokens": u.get("input_tokens", 0) - cached, "output_tokens": u.get("output_tokens", 0),
            "cache_read": cached}


def from_deepseek(j: dict) -> dict:
    u = j.get("usage") or {}
    hit = u.get("prompt_cache_hit_tokens", 0)
    miss = u.get("prompt_cache_miss_tokens", u.get("prompt_tokens", 0) - hit)
    out = u.get("completion_tokens", 0)
    hit_p, miss_p, out_p = DEEPSEEK_PRICE
    return {**empty(), "model": j.get("model", ""), "input_tokens": miss, "output_tokens": out, "cache_read": hit,
            "cost_usd": hit * hit_p + miss * miss_p + out * out_p}


def from_jev(j: dict) -> dict:
    u = j.get("usage") or {}
    return {**empty(), "model": j.get("model") or "jev-latest",
            "input_tokens": u.get("input_tokens", u.get("prompt_tokens", 0)), "output_tokens": u.get("output_tokens", u.get("completion_tokens", 0))}


def search(model: str = "deepseek-search") -> dict:
    return {**empty(), "model": model}


def from_bailian(model: str, tokens: dict, cost_yuan: float) -> dict:
    return {**empty(), "model": model, "input_tokens": tokens.get("input_text", 0) + tokens.get("input_audio", 0),
            "output_tokens": tokens.get("output_text", 0) + tokens.get("output_audio", 0), "cost_usd": cost_yuan * USD_PER_CNY}


def add(a: dict, b: dict) -> dict:
    model = a.get("model") or b.get("model") or ""
    return {"model": model, **{k: (a.get(k) or 0) + (b.get(k) or 0) for k in FIELDS}}


def record(module: str, u: dict | None, *, ref: str = "", engine: str = "") -> None:
    if u is None:
        return
    try:
        db.insert("llm_usage", {"at": db.now(), "module": module, "ref": ref, "engine": engine, "model": u.get("model", ""),
                                **{k: u.get(k) or 0 for k in FIELDS}})
    except Exception:  # noqa: BLE001 —— 记账失败不影响调用本身
        log.exception("llm usage record failed")


KIND = ("CASE WHEN ref LIKE 'job:%' THEN 'job' WHEN module LIKE 'chat:%' THEN 'chat' "
        "WHEN engine='deepseek' THEN 'deepseek' WHEN engine IN ('jev','bailian') THEN 'api' ELSE 'light' END")


@router.get("")
def daily(start: str = "", end: str = "") -> dict:
    """[start, end] 每天 × 类型（后台任务 / 讨论 / 本机 Claude 单次调用 / DeepSeek / 其他 API）× 板块的调用数、token 和等价美元。"""
    end = end or datetime.now().strftime("%Y-%m-%d")
    start = start or (datetime.fromisoformat(end) - timedelta(days=29)).strftime("%Y-%m-%d")
    sums = ", ".join(f"SUM({k}) AS {k}" for k in FIELDS)
    rows = db.rows(f"SELECT substr(at,1,10) AS day, {KIND} AS kind, module, COUNT(*) AS calls, {sums} FROM llm_usage "
                   "WHERE at>=? AND at<? GROUP BY day, kind, module ORDER BY day, kind, module",
                   [start, (datetime.fromisoformat(end) + timedelta(days=1)).strftime("%Y-%m-%d")])
    first = db.row("SELECT MIN(at) AS at FROM llm_usage")["at"]
    return {"start": start, "end": end, "since": (first or "")[:10], "rows": rows}
