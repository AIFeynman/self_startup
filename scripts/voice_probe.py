#!/usr/bin/env python3
"""快慢思考语音通话阶段 0：把固定录音发给百炼实时模型，自动测延迟、路由、转写、照念保真度和打断。

    python scripts/voice_probe.py gen                     # 用本机 Kokoro 生成录音（不联网）
    python scripts/voice_probe.py smoke                   # 2 条样例 + 连接检查
    python scripts/voice_probe.py run --model flash plus  # 全部样例，结果写到 data/voice_eval/
    python scripts/voice_probe.py voices 音色1 音色2       # 每个音色说同一句，存 wav 试听

要 DASHSCOPE_API_KEY 和 DASHSCOPE_WORKSPACE_ID。音频会发给百炼，只跑 tests/voice_eval 里的固定样例。
也可以把真人录音（16k 单声道 wav，文件名同样例 id）放到 --audio 目录替换合成录音。
"""
import argparse
import asyncio
import base64
import difflib
import json
import re
import statistics
import sys
import time
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app import settings, voice_rt  # noqa: E402

CASES = ROOT / "tests/voice_eval/cases.json"
OUT = ROOT / "data/voice_eval"
MODELS = {"flash": "qwen-audio-3.1-realtime-flash", "plus": "qwen-audio-3.1-realtime-plus"}
FRAME_S = 0.04
RATE = 16000
SETTLE_S = 15.0  # 说完这么久还没动静，就算没有回应
LISTEN_S = 1.5  # 打断测试里，用户听了多久才开口
SPEAKERS = [3, 5, 58, 60]  # 轮流用几个声音，别只对一个声音调通


def norm(s: str) -> str:
    return re.sub(r"\W+", "", s).lower()


def similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, norm(a), norm(b)).ratio()


def keep_rate(keep: list[str], text: str) -> float:
    """keep 里每项可用 | 写多种说法（数字可能被转写成汉字或阿拉伯数字）。"""
    if not keep:
        return 1.0
    t = norm(text)
    return sum(any(norm(alt) in t for alt in k.split("|")) for k in keep) / len(keep)


def percentile(xs: list[float], p: float) -> float | None:
    if not xs:
        return None
    xs = sorted(xs)
    return xs[min(len(xs) - 1, round(p / 100 * (len(xs) - 1)))]


def route_of(calls: list[dict], spoke: bool) -> str:
    return calls[0]["name"] if calls else ("fast" if spoke else "silent")


def route_ok(expect: str, route: str) -> bool:
    return expect == "any" or expect == route


# 没转交却说得像查过：资料类问题上这就是编答案
_CLAIMS = re.compile(r"(我查了|我看了|你的记录|知识库里|你之前|你上次|你上周|根据你的|第.{1,3}章)")


def invented(case: dict, calls: list[dict], reply: str) -> bool:
    return bool(case.get("must_not_invent")) and not calls and bool(_CLAIMS.search(reply))


class Conn:
    """一条连接：收事件时打时间戳；要等什么就查 events。"""

    def __init__(self, ws):
        self.ws, self.events, self.audio = ws, [], bytearray()
        self._new = asyncio.Event()
        self._reader = asyncio.create_task(self._read())

    async def _read(self):
        try:
            async for raw in self.ws:
                ev = json.loads(raw)
                ev["_t"] = time.monotonic()
                if ev.get("type") == "response.audio.delta":
                    self.audio += base64.b64decode(ev.pop("delta", ""))
                self.events.append(ev)
                self._new.set()
        except Exception as e:  # 连接断了也记成事件，由调用方判断
            self.events.append({"type": "_closed", "error": str(e), "_t": time.monotonic()})
            self._new.set()

    async def send(self, ev: dict):
        await self.ws.send(json.dumps(ev, ensure_ascii=False))

    def of(self, *types: str, after: float = 0.0) -> list[dict]:
        return [e for e in self.events if e["type"] in types and e["_t"] >= after]

    async def wait(self, *types: str, after: float = 0.0, timeout: float = SETTLE_S) -> dict | None:
        end = time.monotonic() + timeout
        while True:
            found = self.of(*types, after=after) or self.of("_closed")
            if found:
                return found[0]
            left = end - time.monotonic()
            if left <= 0:
                return None
            self._new.clear()
            try:
                await asyncio.wait_for(self._new.wait(), left)
            except asyncio.TimeoutError:
                return None

    async def inject(self, text: str):
        await self.send({"type": "conversation.item.create",
                         "item": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": text}]}})


async def stream_audio(conn: Conn, pcm: bytes) -> float:
    """按真实语速发音频，返回说完的时刻。"""
    n = int(RATE * FRAME_S) * 2
    start = time.monotonic()
    for i, off in enumerate(range(0, len(pcm), n)):
        await conn.send({"type": "input_audio_buffer.append", "audio": base64.b64encode(pcm[off:off + n]).decode()})
        await asyncio.sleep(max(0, start + (i + 1) * FRAME_S - time.monotonic()))
    return time.monotonic()


async def keep_silence(conn: Conn):
    """说完继续发静音，服务端要靠它判断这句话结束。"""
    n = int(RATE * FRAME_S) * 2
    frame = base64.b64encode(bytes(n)).decode()
    while True:
        await conn.send({"type": "input_audio_buffer.append", "audio": frame})
        await asyncio.sleep(FRAME_S)


async def connect(model: str, url: str | None, **cfg):
    import websockets
    ws = await websockets.connect(url or voice_rt.endpoint(model), additional_headers={} if url else voice_rt.headers(),
                                  proxy=None, max_size=None)
    conn = Conn(ws)
    t0 = time.monotonic()
    await conn.send({"type": "session.update", "session": voice_rt.session_config(**cfg)})
    got = await conn.wait("session.updated", "error", timeout=8)
    if not got or got["type"] != "session.updated":
        await ws.close()
        raise RuntimeError(f"会话配置失败：{got}")
    return conn, time.monotonic() - t0


async def _finish_tools(conn: Conn, calls: list[dict]) -> None:
    """工具一律立即答「已受理」，再触发一轮，看它接话要多久。"""
    for c in calls:
        await conn.send({"type": "conversation.item.create",
                         "item": {"type": "function_call_output", "call_id": c["call_id"], "output": json.dumps({"status": "accepted"})}})
    await conn.send({"type": "response.create", "response": {"modalities": ["audio", "text"]}})


async def run_case(model: str, case: dict, pcm: bytes, url: str | None = None) -> dict:
    conn, setup_s = await connect(model, url)
    silence = None
    try:
        for c in case.get("context", []):
            await conn.inject(c)
        end = await stream_audio(conn, pcm)
        silence = asyncio.create_task(keep_silence(conn))
        first_done = await conn.wait("response.done", after=end - len(pcm) / 2 / RATE, timeout=SETTLE_S)
        t_audio = conn.of("response.audio.delta")
        calls = [{"name": e.get("name"), "call_id": e.get("call_id"), "arguments": e.get("arguments", "")}
                 for e in conn.of("response.function_call_arguments.done")]
        first_audio_before_tool = bool(t_audio)
        order = [e.get("item", {}).get("type") for e in conn.of("response.output_item.added")]
        tool_at = conn.of("response.function_call_arguments.done")
        if calls and first_done and first_done["type"] == "response.done":
            mark = time.monotonic()
            await _finish_tools(conn, calls)
            await conn.wait("response.done", after=mark, timeout=SETTLE_S)
        t_audio = conn.of("response.audio.delta")
        reply = " ".join(e.get("transcript", "") for e in conn.of("response.audio_transcript.done"))
        heard = " ".join(e.get("transcript", "") for e in conn.of("conversation.item.input_audio_transcription.completed"))
        started = conn.of("input_audio_buffer.speech_started")
        return {
            "id": case["id"], "kind": case["kind"], "model": model, "text": case["text"], "expect": case["expect"],
            "setup_s": round(setup_s, 3),
            "first_audio_s": round(t_audio[0]["_t"] - end, 3) if t_audio else None,
            "tool_s": round(tool_at[0]["_t"] - end, 3) if tool_at else None,
            "spoke_before_tool": first_audio_before_tool and bool(calls),
            "order": order, "calls": calls, "route": route_of(calls, bool(t_audio)),
            "route_ok": route_ok(case["expect"], route_of(calls, bool(t_audio))),
            "invented": invented(case, calls, reply),
            "heard": heard, "heard_sim": round(similarity(heard, case["text"]), 3),
            "terms_kept": keep_rate(case.get("terms", []), heard),
            "objective_kept": keep_rate(case.get("keep", []), " ".join(c["arguments"] for c in calls)),
            "reply": reply, "speech_started": bool(started),
            "errors": [e.get("error") for e in conn.of("error")],
            "closed": bool(conn.of("_closed")),
        }
    finally:
        if silence:
            silence.cancel()
        conn._reader.cancel()
        await conn.ws.close()


async def run_spoken(model: str, item: dict, url: str | None = None) -> dict:
    """慢思考结果送回去，模型说出来的和原文差多少。"""
    conn, _ = await connect(model, url)
    try:
        t0 = time.monotonic()
        await conn.inject(f"【慢思考结果】{item['text']}")
        await conn.send({"type": "response.create", "response": {"modalities": ["audio", "text"]}})
        await conn.wait("response.done", after=t0, timeout=SETTLE_S)
        audio = conn.of("response.audio.delta")
        said = " ".join(e.get("transcript", "") for e in conn.of("response.audio_transcript.done"))
        return {"id": item["id"], "model": model, "text": item["text"], "said": said,
                "first_audio_s": round(audio[0]["_t"] - t0, 3) if audio else None,
                "similarity": round(similarity(said, item["text"]), 3), "keep": keep_rate(item.get("keep", []), said),
                "errors": [e.get("error") for e in conn.of("error")]}
    finally:
        conn._reader.cancel()
        await conn.ws.close()


async def run_barge(model: str, pcm_cut: bytes, url: str | None = None) -> dict:
    """模型说到一半开口：多久检测到、取消后还会不会来音频、云端记下的是说了多少。"""
    conn, _ = await connect(model, url)
    silence = None
    try:
        await conn.inject("【慢思考结果】我建议分三步。第一步先把中转做好，第二步接上工具，第三步跑评测。每一步都要有验收线，做完再进下一步。")
        t0 = time.monotonic()
        await conn.send({"type": "response.create", "response": {"modalities": ["audio", "text"]}})
        first = await conn.wait("response.audio.delta", after=t0, timeout=SETTLE_S)
        if not first or first["type"] != "response.audio.delta":
            return {"model": model, "error": f"没等到音频：{first}"}
        silence = asyncio.create_task(keep_silence(conn))
        await asyncio.sleep(LISTEN_S)  # 听了一会才开口；服务端发音频比播放快，发来的不等于听到的
        silence.cancel()
        received_bytes = len(conn.audio)
        cut_at = time.monotonic()
        speaking = asyncio.create_task(stream_audio(conn, pcm_cut))
        started = await conn.wait("input_audio_buffer.speech_started", after=cut_at, timeout=6)
        cancel_at = time.monotonic()
        await conn.send({"type": "response.cancel"})
        done = await conn.wait("response.done", after=t0, timeout=6)
        await speaking
        late = [e for e in conn.of("response.audio.delta", after=(done or {}).get("_t", time.monotonic()))]
        item_id = next((e.get("item", {}).get("id") for e in conn.of("response.output_item.added")), None)
        kept = None
        if item_id:
            mark = time.monotonic()
            await conn.send({"type": "conversation.item.retrieve", "item_id": item_id})
            got = await conn.wait("conversation.item.retrieved", "error", after=mark, timeout=4)
            kept = (got or {}).get("item")
        return {"model": model,
                "detect_s": round(started["_t"] - cut_at, 3) if started and started["type"] != "_closed" else None,
                "cancel_done_s": round(done["_t"] - cancel_at, 3) if done and done["type"] == "response.done" else None,
                "status": (done or {}).get("response", {}).get("status"),
                "audio_after_done": len(late), "listened_s": LISTEN_S, "received_s": round(received_bytes / 2 / 24000, 2),
                "kept_item": kept, "errors": [e.get("error") for e in conn.of("error")]}
    finally:
        if silence:
            silence.cancel()
        conn._reader.cancel()
        await conn.ws.close()


def wav_pcm(path: Path) -> bytes:
    with wave.open(str(path)) as w:
        if (w.getframerate(), w.getnchannels(), w.getsampwidth()) != (RATE, 1, 2):
            raise ValueError(f"{path} 要 16k 单声道 16bit")
        return w.readframes(w.getnframes())


def save_wav(path: Path, pcm: bytes, rate: int = 24000) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)


def _resample(samples, src: int):
    import numpy as np
    x = np.arange(0, len(samples), src / RATE)
    return np.interp(x, np.arange(len(samples)), samples)


def generate(audio: Path) -> int:
    """合成录音：首尾带一点静音，噪声和旁人说话的样例加混音。"""
    import numpy as np

    from app import voice
    data = json.loads(CASES.read_text("utf-8"))
    audio.mkdir(parents=True, exist_ok=True)
    tts = voice._load_kokoro()
    rng = np.random.default_rng(7)
    made = 0
    extras = [{"id": "barge-cut", "text": "等等，第一步为什么放最前面？", "kind": ""}]
    for i, c in enumerate(data["cases"] + extras):
        path = audio / f"{c['id']}.wav"
        if path.exists():
            continue
        out = tts.generate(c["text"], sid=SPEAKERS[i % len(SPEAKERS)], speed=1.0)
        x = _resample(np.asarray(out.samples, dtype=np.float32), out.sample_rate)
        pad = np.zeros(int(RATE * 0.3))
        x = np.concatenate([pad, x, pad])
        if c.get("mix") == "noise":  # 约 15 dB 信噪比的白噪声
            x = x + rng.normal(0, np.sqrt(np.mean(x ** 2)) / 5.6, len(x))
        elif c.get("mix") == "faint":  # 旁人离麦克风远
            x = x * 0.12
        pcm = np.clip(x * 32767, -32768, 32767).astype(np.int16).tobytes()
        save_wav(path, pcm, RATE)
        made += 1
    return made


def summarize(rows: list[dict], spoken: list[dict], barge: list[dict]) -> dict:
    out = {}
    for model in sorted({r["model"] for r in rows}):
        rs = [r for r in rows if r["model"] == model and not r.get("failed")]
        lat = [r["first_audio_s"] for r in rs if r["first_audio_s"] is not None]
        tool = [r for r in rs if r["calls"]]
        sp = [s for s in spoken if s["model"] == model]
        by_kind: dict[str, list[int]] = {}
        for r in rs:
            k = by_kind.setdefault(r["kind"], [0, 0])
            k[0] += r["route_ok"]
            k[1] += 1
        out[model] = {
            "cases": len(rs), "failed": sum(1 for r in rows if r["model"] == model and r.get("failed")),
            "first_audio_p50": percentile(lat, 50), "first_audio_p95": percentile(lat, 95),
            "first_audio_direct_p50": percentile([r["first_audio_s"] for r in rs if not r["calls"] and r["first_audio_s"] is not None], 50),
            "first_audio_tool_p50": percentile([r["first_audio_s"] for r in tool if r["first_audio_s"] is not None], 50),
            "tool_p50": percentile([r["tool_s"] for r in tool if r["tool_s"] is not None], 50),
            "spoke_before_tool": sum(r["spoke_before_tool"] for r in tool), "tool_cases": len(tool),
            "route_acc": round(sum(r["route_ok"] for r in rs) / len(rs), 3) if rs else None,
            "route_by_kind": by_kind, "invented": [r["id"] for r in rs if r["invented"]],
            "heard_sim_mean": round(statistics.mean(r["heard_sim"] for r in rs), 3) if rs else None,
            "terms_kept_mean": round(statistics.mean(r["terms_kept"] for r in rs if r["kind"] in ("术语", "常识")), 3) if any(r["kind"] in ("术语", "常识") for r in rs) else None,
            "objective_kept_mean": round(statistics.mean(r["objective_kept"] for r in rs if r["calls"]), 3) if tool else None,
            "spoken_sim_mean": round(statistics.mean(s["similarity"] for s in sp), 3) if sp else None,
            "spoken_keep_mean": round(statistics.mean(s["keep"] for s in sp), 3) if sp else None,
            "spoken_first_audio_p50": percentile([s["first_audio_s"] for s in sp if s["first_audio_s"] is not None], 50),
            "barge": next((b for b in barge if b["model"] == model), None),
        }
    return out


async def run_all(models: list[str], audio: Path, out: Path, url: str | None = None, limit: int = 0) -> dict:
    data = json.loads(CASES.read_text("utf-8"))
    cases = data["cases"][:limit] if limit else data["cases"]
    rows, spoken, barge = [], [], []
    out.mkdir(parents=True, exist_ok=True)
    log = (out / "rows.jsonl").open("a", encoding="utf-8")
    for model in models:
        recent: list[bool] = []
        for case in cases:
            try:
                r = await run_case(model, case, wav_pcm(audio / f"{case['id']}.wav"), url)
                recent.append(r["closed"] or bool(r["errors"]))
            except Exception as e:
                r = {"id": case["id"], "kind": case["kind"], "model": model, "failed": str(e)}
                recent.append(True)
            rows.append(r)
            log.write(json.dumps(r, ensure_ascii=False) + "\n")
            log.flush()
            print(f"{model} {case['id']}: {r.get('failed') or (r['route'], r['first_audio_s'], r['heard'])}", flush=True)
            if len(recent) >= 5 and sum(recent[-5:]) >= 4:  # 失败率突然升高：先停，分清环境还是产品
                print("最近 5 条至少 4 条出错，暂停：先查网络、额度和配置，这批结果不算数", flush=True)
                return {"paused": True, "rows": rows}
        if not limit:
            for item in data["spoken"]:
                try:
                    s = await run_spoken(model, item, url)
                except Exception as e:
                    s = {"id": item["id"], "model": model, "text": item["text"], "said": "", "first_audio_s": None,
                         "similarity": 0.0, "keep": 0.0, "errors": [str(e)]}
                spoken.append(s)
                print(f"{model} {item['id']}: {s['similarity']} {s['said']}", flush=True)
            barge.append(await run_barge(model, wav_pcm(audio / "barge-cut.wav"), url))
            print(f"{model} 打断: {barge[-1]}", flush=True)
    summary = summarize(rows, spoken, barge)
    (out / "result.json").write_text(json.dumps({"summary": summary, "rows": rows, "spoken": spoken, "barge": barge},
                                                ensure_ascii=False, indent=1), "utf-8")
    return {"summary": summary}


async def run_voices(model: str, voices: list[str], out: Path, url: str | None = None) -> None:
    line = json.loads(CASES.read_text("utf-8"))["voice_line"]
    out.mkdir(parents=True, exist_ok=True)
    for v in voices:
        conn, _ = await connect(model, url, voice=v)
        try:
            t0 = time.monotonic()
            await conn.inject(f"【慢思考结果】{line}")
            await conn.send({"type": "response.create", "response": {"modalities": ["audio", "text"]}})
            await conn.wait("response.done", after=t0, timeout=SETTLE_S)
            save_wav(out / f"{v}.wav", bytes(conn.audio))
            print(v, round(len(conn.audio) / 2 / 24000, 1), "秒", [e.get("error") for e in conn.of("error")], flush=True)
        finally:
            conn._reader.cancel()
            await conn.ws.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["gen", "smoke", "run", "voices"])
    ap.add_argument("args", nargs="*")
    ap.add_argument("--model", nargs="+", default=["flash"])
    ap.add_argument("--audio", type=Path, default=OUT / "audio")
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--url", help="连到假服务做自测，不走百炼")
    ap.add_argument("--env", type=Path, default=settings.ENV_PATH, help="密钥文件；在 worktree 里跑时指向主目录的 .env")
    a = ap.parse_args()
    settings.load_env(a.env)
    if a.cmd == "gen":
        print("新生成", generate(a.audio), "条，在", a.audio)
        return 0
    models = [MODELS.get(m, m) for m in a.model]
    if not a.url:
        try:  # 没配密钥就别往下跑，否则每条样例都记成失败
            voice_rt.endpoint(models[0]), voice_rt.headers()
        except RuntimeError as e:
            print(f"{e}：写到 {a.env}，或在设置里配置")
            return 1
    if a.cmd == "voices":
        asyncio.run(run_voices(models[0], a.args, a.out / "voices", a.url))
        return 0
    res = asyncio.run(run_all(models, a.audio, a.out / a.cmd, a.url, limit=2 if a.cmd == "smoke" else 0))
    print(json.dumps(res.get("summary", res.get("paused")), ensure_ascii=False, indent=1))
    return 2 if res.get("paused") else 0


if __name__ == "__main__":
    raise SystemExit(main())
