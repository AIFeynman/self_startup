#!/usr/bin/env python3
"""真实链路自测：把固定样例的音频发给 /api/voice/rt，程序自动计时、记录结果。会连百炼、DeepSeek 和本机 Claude Code。

  python scripts/voice_rt_e2e.py --url ws://127.0.0.1:8794/api/voice/rt --ids chat-1,search-1,data-1
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import wave
from pathlib import Path

import websockets

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from voice_probe import trailing_silence_s, voice_rt  # noqa: E402

FRAME = 1024
RATE = 16000
OUT_RATE = 24000


def pcm_of(path: Path) -> bytes:
    with wave.open(str(path)) as w:
        return w.readframes(w.getnframes())


async def run_case(url: str, case: dict, audio_dir: Path, slow_wait: float) -> dict:
    """一条样例一通电话。按真实速度发音频，说完继续发静音。"""
    row = {"id": case["id"], "kind": case["kind"], "expect": case["expect"], "text": case["text"]}
    pcm = pcm_of(audio_dir / f"{case['id']}.wav")
    silence = bytes(FRAME * 2)
    tail = trailing_silence_s(pcm)  # 录音末尾自带的静音也算用户说完之后
    needs_slow = case["expect"] == "think_deep"
    async with websockets.connect(url, max_size=None, proxy=None) as ws:
        t_end, first_audio, replies, heard, slow, doing, audio_s = None, None, [], "", None, set(), 0.0
        audio_at = 0.0
        fallback, searching = None, False

        async def send():
            nonlocal t_end
            for i in range(0, len(pcm), FRAME * 2):
                await ws.send(pcm[i:i + FRAME * 2])
                await asyncio.sleep(FRAME / RATE)
            t_end = time.monotonic()
            while True:
                await ws.send(silence)
                await asyncio.sleep(FRAME / RATE)

        sender = None
        deadline = time.monotonic() + 15
        last_activity = None
        try:
            while True:
                now = time.monotonic()
                done_fast = last_activity and now - last_activity > 3 and not needs_slow and not searching
                if now > deadline or done_fast or (needs_slow and slow is not None and last_activity and now - last_activity > 3):
                    break
                try:
                    msg = await asyncio.wait_for(ws.recv(), 0.5)
                except asyncio.TimeoutError:
                    continue
                now = time.monotonic()
                if isinstance(msg, bytes):
                    audio_s += len(msg) / 2 / OUT_RATE
                    last_activity = now
                    if first_audio is None and t_end:
                        first_audio = now - t_end + tail
                        audio_at = now
                    continue
                m = json.loads(msg)
                if m["type"] == "ready":
                    sender = asyncio.create_task(send())
                elif m["type"] == "clear":
                    row["cleared"] = True
                    if audio_at:  # 拦下之前已经放出去多久
                        row["audible_s"] = round(now - audio_at, 3)
                elif m["type"] == "user":
                    heard = m["text"]
                elif m["type"] == "reply":
                    replies.append(m["text"])
                    last_activity = now
                    if needs_slow:
                        deadline = max(deadline, now + slow_wait)
                elif m["type"] == "slow":
                    slow = m["text"]
                    row["slow_s"] = round(now - t_end + tail, 2)
                    deadline, last_activity = now + 15, now  # 念结果的声音还在后面
                elif m["type"] == "status":
                    if searching and not m.get("searching"):
                        last_activity = now  # 搜完还要念
                    searching = bool(m.get("searching"))
                    if m.get("thinking") or searching:
                        doing.add("search" if searching else "think")
                    if m.get("thinking") and needs_slow:
                        deadline = max(deadline, now + slow_wait)
                elif m["type"] == "fallback":
                    fallback = m["reason"]
                    break
        finally:
            if sender:
                sender.cancel()
    row.update(heard=heard, first_audio_s=round(first_audio, 3) if first_audio else None, replies=replies, audio_s=round(audio_s, 1),
               did=sorted(doing), slow_len=len(slow) if slow else 0, fallback=fallback)
    return row


def route_ok(row: dict) -> bool:
    want = {"think_deep": "think", "web_search": "search"}.get(row["expect"])
    if row["expect"] == "silent":  # 说了又被拦下的不算说
        return not row["did"] and not row["replies"]
    return want in row["did"] if want else row["expect"] != "fast" or not row["did"]


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="ws://127.0.0.1:8794/api/voice/rt")
    ap.add_argument("--ids", default="", help="逗号分隔；空 = 全部")
    ap.add_argument("--kinds", default="", help="逗号分隔的类别")
    ap.add_argument("--audio", default=str(ROOT / "data/voice_eval/audio"))
    ap.add_argument("--out", default=str(ROOT / "data/voice_eval/e2e.jsonl"))
    ap.add_argument("--slow-wait", type=float, default=120)
    a = ap.parse_args()
    cases = json.loads((ROOT / "tests/voice_eval/cases.json").read_text("utf-8"))["cases"]
    if a.ids:
        ids = a.ids.split(",")
        cases = [c for c in cases if c["id"] in ids]
    if a.kinds:
        kinds = a.kinds.split(",")
        cases = [c for c in cases if c["kind"] in kinds]
    rows, failed = [], 0
    with open(a.out, "w", encoding="utf-8") as f:
        for c in cases:
            try:
                r = await run_case(a.url, c, Path(a.audio), a.slow_wait)
            except Exception as e:  # noqa: BLE001 —— 一条挂了记下来，继续下一条
                r = {"id": c["id"], "kind": c["kind"], "expect": c["expect"], "error": repr(e), "did": []}
            r["route_ok"] = "error" not in r and route_ok(r)
            failed = failed + 1 if ("error" in r or r.get("fallback")) else 0
            rows.append(r)
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            f.flush()
            print(json.dumps({k: r.get(k) for k in ("id", "expect", "did", "route_ok", "first_audio_s", "slow_s", "heard", "replies", "error", "fallback")}, ensure_ascii=False), flush=True)
            if failed >= 3:
                print("连续失败，先停下", flush=True)
                return 1
    firsts = sorted(r["first_audio_s"] for r in rows if r.get("first_audio_s"))
    print(json.dumps({"cases": len(rows), "route_ok": sum(r["route_ok"] for r in rows),
                      "first_audio_p50": firsts[len(firsts) // 2] if firsts else None,
                      # 只看接话那句：想好的答案是用户的内容，可能本来就讲到「后台」「调用」
                      "leaked": [r["id"] for r in rows if voice_rt.LEAK.search((r.get("replies") or [""])[0])],
                      "slow_s": [r.get("slow_s") for r in rows if r.get("slow_s")]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
