#!/usr/bin/env python3
"""语音讨论真实链路计时：固定音频样例 → /api/voice/transcribe → /api/chat/talk，打印耗时和准确度。

    python scripts/voice_bench.py <样例目录> [--api http://127.0.0.1:8794] [--chat]

样例目录：<名字>.webm / .wav，可带同名 .txt（标准文字，用来算相似度）；没有 .txt 的按「应该转不出字」判。
只在预览实例上跑 --chat，它会写对话记录。
"""
import argparse
import difflib
import json
import re
import time
import urllib.request
from pathlib import Path

opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
_norm = lambda s: re.sub(r"\W+", "", s).lower()  # noqa: E731


def post(url: str, data: bytes, ctype: str):
    return opener.open(urllib.request.Request(url, data=data, headers={"Content-Type": ctype}), timeout=400)


def chat(api: str, text: str, session: int | None) -> tuple[float, float, int | None, list[str]]:
    """→ (首段回复秒数, 总秒数, 会话 id, 回复)"""
    t0, first, sid, texts = time.time(), 0.0, session, []
    body = json.dumps({"message": text, "session_id": session}).encode()
    with post(f"{api}/api/chat/talk", body, "application/json") as r:
        for line in r:
            if not line.startswith(b"data: "):
                continue
            ev = json.loads(line[6:])
            if ev["type"] == "meta":
                sid = ev["session_id"]
            elif ev["type"] in ("text", "delta"):
                first = first or time.time() - t0
                if ev["type"] == "text":
                    texts.append(ev["text"])
    return round(first, 1), round(time.time() - t0, 1), sid, texts


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dir", type=Path)
    ap.add_argument("--api", default="http://127.0.0.1:8794")
    ap.add_argument("--chat", action="store_true")
    a = ap.parse_args()
    ok = True
    said = {}
    for f in sorted(p for p in a.dir.iterdir() if p.suffix in (".webm", ".wav") and not (p.suffix == ".wav" and p.with_suffix(".webm").exists())):
        gold = f.with_suffix(".txt")
        d = json.load(post(f"{a.api}/api/voice/transcribe", f.read_bytes(), "audio/webm"))
        if gold.exists():
            score = difflib.SequenceMatcher(None, _norm(gold.read_text("utf-8")), _norm(d["text"]), autojunk=False).ratio()
            passed = score >= 0.9
            said[f.stem] = d["text"]
        else:
            score, passed = None, not d["text"]
        ok &= passed
        print(f"{'PASS' if passed else 'FAIL'} {f.name:14} 时长 {d['seconds']:>6}s  转写 {d['ms'] / 1000:>5.1f}s  相似度 {score if score is None else round(score, 3)}  {d['text'][:60]!r}")
    if a.chat:
        for name, text in said.items():
            first, total, sid, reply = chat(a.api, text[:800], None)
            print(f"对话 {name:6} 首段回复 {first}s  全部 {total}s  session={sid}  {''.join(reply)[:80]!r}")
            first, total, sid, reply = chat(a.api, "你刚才第一句话说的核心问题是什么？用一句话复述。", sid)
            print(f"追问 {name:6} 首段回复 {first}s  全部 {total}s  {''.join(reply)[:80]!r}")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
