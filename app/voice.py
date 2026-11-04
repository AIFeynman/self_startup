"""语音：本机转文字（whisper.cpp）和本机合成（macOS say）。音频不出本机，处理完即删，只返回结果。
/transcribe 转一整段录音；/live 转说话途中的一段，模型常驻所以约半秒一次，边说边出字靠它。"""
from __future__ import annotations

import array
import io
import json
import logging
import math
import os
import re
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import wave
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from . import agent, settings

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
_SERVER_IDLE_S = 600    # 这么久没人说话就退出常驻的模型，下次用再起
_SERVER_START_S = 30
# 平台退出（包括被强杀）后几秒内跟着退，不留下占显存的孤儿进程
_WATCH_PARENT = 'ppid=$1; shift; "$@" & c=$!; while kill -0 "$ppid" 2>/dev/null && kill -0 "$c" 2>/dev/null; do sleep 5; done; kill "$c" 2>/dev/null'
_server: subprocess.Popen | None = None
_server_url, _server_used = "", 0.0
_server_lock = threading.Lock()


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


# ---------- 边说边转：平台的子进程，第一次用时起，闲置退出，不是单独的服务 ----------
def _reap_when_idle(proc: subprocess.Popen) -> None:
    while proc.poll() is None:
        time.sleep(30)
        if time.time() - _server_used > _SERVER_IDLE_S:
            agent.stop(proc)


def _ensure_server() -> str:
    """返回常驻 whisper-server 的地址，没起就起，只听本机。"""
    global _server, _server_url, _server_used
    with _server_lock:
        _server_used = time.time()
        if _server and _server.poll() is None:
            return _server_url
        cfg = settings.get("voice", {})
        binary, model = shutil.which(cfg.get("server_bin", "whisper-server")), Path(cfg.get("model", "")).expanduser()
        if not binary:
            raise HTTPException(503, "本机没有 whisper-server，语音输入用不了")
        if not model.is_file():
            raise HTTPException(503, f"找不到语音模型 {model}，在设置 voice.model 里改路径")
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        cmd = [binary, "-m", str(model), "-l", cfg.get("language", "zh"), "--host", "127.0.0.1", "--port", str(port)]
        proc = subprocess.Popen(["sh", "-c", _WATCH_PARENT, "sh", str(os.getpid()), *cmd], stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        url = f"http://127.0.0.1:{port}"
        deadline = time.time() + _SERVER_START_S
        while time.time() < deadline and proc.poll() is None:
            try:
                httpx.get(url, timeout=1, trust_env=False)
                _server, _server_url = proc, url
                threading.Thread(target=_reap_when_idle, args=(proc,), daemon=True).start()
                return url
            except httpx.HTTPError:
                time.sleep(0.1)
        agent.stop(proc)
        raise HTTPException(503, "whisper-server 没能启动")


def _parse_server(result: dict) -> tuple[str, float]:
    """whisper-server verbose_json 的结果 → (文字, 平均置信度)。"""
    probs = [w.get("probability", 0) for s in result.get("segments") or [] for w in s.get("words") or []]
    return (result.get("text") or "").strip(), sum(probs) / len(probs) if probs else 0.0


def transcribe_live(audio: bytes) -> dict:
    """转说话途中的一段（16k 单声道 wav）。有没有人说话浏览器已判断过，这里只拦住几乎没声音的。"""
    started = time.time()
    try:
        with wave.open(io.BytesIO(audio)) as w:
            pcm = array.array("h", w.readframes(w.getnframes()))
    except (wave.Error, EOFError) as e:
        raise HTTPException(400, "不是 wav") from e
    if not _voiced(_levels(pcm), _MIN_RMS):
        return {"text": "", "ms": int((time.time() - started) * 1000)}
    url = _ensure_server()
    cfg = settings.get("voice", {})
    try:
        r = httpx.post(f"{url}/inference", files={"file": ("a.wav", audio, "audio/wav")}, timeout=TIMEOUT_S, trust_env=False,
                       data={"response_format": "verbose_json", "prompt": cfg.get("prompt", "")})
        r.raise_for_status()
        text = _keep(_parse_server(r.json()))
    except (httpx.HTTPError, ValueError) as e:  # 常驻进程出问题：这次退回一次性的 whisper-cli，慢但能用
        log.warning("whisper-server 转写失败，改用 whisper-cli：%s", e)
        return transcribe(audio)
    return {"text": _clean(text), "ms": int((time.time() - started) * 1000)}


@router.post("/prepare")
def api_prepare():
    """点麦克风时先把模型加载好，第一句不用等。"""
    _ensure_server()
    return {"ok": True}


@router.post("/live")
async def api_live(request: Request):
    audio = await request.body()
    if not audio:
        raise HTTPException(400, "没收到录音")
    if len(audio) > MAX_BYTES:
        raise HTTPException(413, "录音太大")
    return await run_in_threadpool(transcribe_live, audio)


# ---------- 朗读：放在页面里播，浏览器的回声消除才消得掉，才能边放边听 ----------
class SpeakIn(BaseModel):
    text: str


def synthesize(text: str) -> bytes:
    binary = shutil.which("say")
    if not binary:
        raise HTTPException(503, "本机没有 say，用不了本机朗读")
    with tempfile.TemporaryDirectory(prefix="ss-voice-") as tmp:
        out = Path(tmp, "out.wav")
        try:
            r = subprocess.run([binary, "-v", settings.get("voice", {}).get("tts_voice", "Tingting"), "-o", str(out), "--data-format=LEI16@22050"],
                               input=text, capture_output=True, text=True, timeout=30)
        except subprocess.TimeoutExpired as e:
            raise HTTPException(504, "合成超时") from e
        if r.returncode != 0:
            raise HTTPException(500, f"say 失败：{r.stderr.strip()[-200:]}")
        return out.read_bytes()


@router.post("/speak")
def api_speak(body: SpeakIn):
    text = body.text.strip()[:500]
    if not text:
        raise HTTPException(400, "没有文字")
    return Response(synthesize(text), media_type="audio/wav")
