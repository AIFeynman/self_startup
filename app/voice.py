"""语音转文字：浏览器录的音频 → ffmpeg 转 16k wav → 本机 whisper.cpp。音频不出本机，转完即删，只返回文字。"""
from __future__ import annotations

import array
import json
import logging
import math
import re
import shutil
import subprocess
import tempfile
import threading
import time
import wave
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from . import settings

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/voice", tags=["voice"])

MAX_BYTES = 50 * 1024 * 1024
TIMEOUT_S = 300
_FRAME = 480            # 16k 采样下 30ms 一帧
_MIN_RMS = 100          # 再轻就当没声音
_MIN_SPEECH_S = 0.3
_MIN_CONFIDENCE = 0.45
_CHUNK_MIN, _CHUNK_MAX = 500, 933  # 长录音切段：15–28 秒之间找最安静的一帧（whisper 一个窗口 30 秒）
# whisper 对短促杂音爱编的训练集字幕腔：整段很短又命中才丢，正常说话提到这些词不受影响
_HALLUCINATION = re.compile(r"明镜|点点栏目|不吝点赞|字幕[由by]|谢谢观看|请订阅")
_lock = threading.Lock()  # 模型吃显存，一次转一段


def _levels(pcm: array.array) -> list[float]:
    return [math.sqrt(sum(x * x for x in pcm[i:i + _FRAME]) / _FRAME) for i in range(0, len(pcm) - _FRAME, _FRAME)]


def _threshold(levels: list[float]) -> float:
    return max(_MIN_RMS, 3 * sorted(levels)[len(levels) // 10])


def _voiced(levels: list[float], threshold: float) -> bool:
    return sum(v > threshold for v in levels) * _FRAME / 16000 >= _MIN_SPEECH_S


def has_speech(wav_path: Path) -> bool:
    """按帧能量判断有没有人说话：比环境底噪响出一截的帧够多才算。whisper 碰到静音和持续噪音会编句子，要先拦住。"""
    with wave.open(str(wav_path)) as w:
        levels = _levels(array.array("h", w.readframes(w.getnframes())))
    return bool(levels) and _voiced(levels, _threshold(levels))


def split_at_pauses(wav_path: Path, out_dir: Path) -> list[Path]:
    """长录音在说话停顿处切成不超过 28 秒的段，没声音的段不要。
    whisper 连续解码长音频会把前文带进去，一旦重复就停不下来，后面整段都是编的；一段一段独立转就不会传染。"""
    with wave.open(str(wav_path)) as w:
        pcm = array.array("h", w.readframes(w.getnframes()))
    levels = _levels(pcm)
    if not levels:
        return []
    threshold, parts, start = _threshold(levels), [], 0
    while start < len(levels):
        end = len(levels)
        if end - start > _CHUNK_MAX:
            window = levels[start + _CHUNK_MIN:start + _CHUNK_MAX]
            end = start + _CHUNK_MIN + window.index(min(window))
        if _voiced(levels[start:end], threshold):
            parts.append(out_dir / f"part{len(parts):03d}.wav")
            with wave.open(str(parts[-1]), "wb") as w:
                w.setnchannels(1), w.setsampwidth(2), w.setframerate(16000)
                w.writeframes(pcm[start * _FRAME:end * _FRAME].tobytes())
        start = end
    return parts


def _clean(text: str) -> str:
    """半角标点挨着中文时换成全角。"""
    cjk = r"[一-鿿]"
    for half, full in ((",", "，"), ("?", "？"), ("!", "！"), (":", "：")):
        text = re.sub(rf"(?<={cjk}){re.escape(half)}\s*|{re.escape(half)}\s*(?={cjk})", full, text)
    return text.strip()


def _parse(result: dict) -> tuple[str, float]:
    """whisper-cli -ojf 的结果 → (文字, 平均置信度)。"""
    segs = result.get("transcription") or []
    probs = [t.get("p", 0) for s in segs for t in s.get("tokens", []) if not t.get("text", "").startswith("[_")]
    return "".join(s.get("text", "") for s in segs).strip(), sum(probs) / len(probs) if probs else 0.0


def _keep(parsed: tuple[str, float]) -> str:
    """一段转写结果，疑似杂音编出来的返回空。"""
    text, confidence = parsed
    if confidence < _MIN_CONFIDENCE or (len(text) < 40 and _HALLUCINATION.search(text)):
        log.info("丢弃疑似杂音的转写（置信度 %.2f）：%s", confidence, text[:40])
        return ""
    return text


def _join(parts: list[str]) -> str:
    """切开的地方是停顿，段尾没标点就补个逗号。"""
    parts = [t for t in parts if t]
    return "".join(t if i == len(parts) - 1 or not t[-1].isalnum() else t + "，" for i, t in enumerate(parts))


def _run(cmd: list[str]) -> None:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT_S)
    except subprocess.TimeoutExpired as e:
        raise HTTPException(504, "转写超时") from e
    if r.returncode != 0:
        log.error("%s 失败：%s", cmd[0], r.stderr[-500:])
        raise HTTPException(500, f"{Path(cmd[0]).name} 失败：{r.stderr.strip()[-200:]}")


def transcribe(audio: bytes) -> dict:
    cfg = settings.get("voice", {})
    binary, model = shutil.which(cfg.get("bin", "whisper-cli")), Path(cfg.get("model", "")).expanduser()
    if not binary or not shutil.which("ffmpeg"):
        raise HTTPException(503, "本机没有 whisper-cli 或 ffmpeg，语音输入用不了")
    if not model.is_file():
        raise HTTPException(503, f"找不到语音模型 {model}，在设置 voice.model 里改路径")
    started = time.time()
    with tempfile.TemporaryDirectory(prefix="ss-voice-") as tmp:  # 退出即删，录音不落盘保留
        src, wav_path = Path(tmp, "in"), Path(tmp, "in.wav")
        src.write_bytes(audio)
        _run(["ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-i", str(src), "-ar", "16000", "-ac", "1", str(wav_path)])
        with wave.open(str(wav_path)) as w:
            seconds = round(w.getnframes() / 16000, 1)
        parts = split_at_pauses(wav_path, Path(tmp))
        if not parts:
            return {"text": "", "reason": "no_speech", "seconds": seconds, "ms": int((time.time() - started) * 1000)}
        with _lock:
            _run([binary, "-m", str(model), *(x for f in parts for x in ("-f", str(f))), "-l", cfg.get("language", "zh"),
                  "--prompt", cfg.get("prompt", ""), "-ojf", "-nt", "-np"])
        kept = [_keep(_parse(json.loads(Path(f"{f}.json").read_text("utf-8", errors="replace")))) for f in parts]
    text = _join(kept)
    return {"text": _clean(text), "reason": "" if text else "no_speech", "seconds": seconds, "ms": int((time.time() - started) * 1000)}


@router.post("/transcribe")
async def api_transcribe(request: Request):
    """请求体就是录音本身（webm / wav…，ffmpeg 能读的都行）。"""
    audio = await request.body()
    if not audio:
        raise HTTPException(400, "没收到录音")
    if len(audio) > MAX_BYTES:
        raise HTTPException(413, "录音太大")
    return await run_in_threadpool(transcribe, audio)
