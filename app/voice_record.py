"""把每通语音电话留下来，便于反查和回听。只追加，不改不删。

data/voice_calls/<id>/
  events.jsonl  发给百炼和百炼发回的全部非音频事件、工具的输入输出、慢思考的结果，t 是通话开始后的秒数
  mic.pcm / bot.pcm  通话中的原始录音，和通话时间对齐。挂断后转成 call.m4a（混音，回听用）、mic.flac、bot.flac（分轨，分析用）
"""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
import time
from pathlib import Path

from . import db, settings
from .db import DATA_DIR

log = logging.getLogger(__name__)

CALLS_DIR = DATA_DIR / "voice_calls"
MIC_RATE, BOT_RATE = 16000, 24000
SCHEMA = """
CREATE TABLE IF NOT EXISTS voice_calls (
  id INTEGER PRIMARY KEY AUTOINCREMENT, session_id INTEGER, model TEXT, voice TEXT, started_at TEXT, ended_at TEXT,
  duration_s REAL DEFAULT 0, responses INTEGER DEFAULT 0, input_text INTEGER DEFAULT 0, input_audio INTEGER DEFAULT 0,
  output_text INTEGER DEFAULT 0, output_audio INTEGER DEFAULT 0, cost_yuan REAL DEFAULT 0
);
"""
USAGE_FIELDS = ("input_text", "input_audio", "output_text", "output_audio")


def cost_of(tokens: dict, price: dict | None = None) -> float:
    """百炼的单价是元/百万 token，存在设置里。免费额度不算，所以是上限。"""
    price = price if price is not None else settings.get("voice_rt.price", {})
    return sum(tokens.get(f, 0) * float(price.get(f, 0)) for f in USAGE_FIELDS) / 1_000_000


def usage_tokens(usage: dict) -> dict:
    i, o = usage.get("input_tokens_details") or {}, usage.get("output_tokens_details") or {}
    return {"input_text": i.get("text_tokens", 0), "input_audio": i.get("audio_tokens", 0),
            "output_text": o.get("text_tokens", 0), "output_audio": o.get("audio_tokens", 0)}


class Recorder:
    """open() 之前什么都不做。写盘失败只记日志，录音不能把通话带挂。"""

    def __init__(self):
        self.t0 = time.monotonic()
        self.id, self.dir, self.mic_f, self.bot_f, self.events_f = None, None, None, None, None
        self.totals = dict.fromkeys(USAGE_FIELDS, 0)
        self.responses = 0

    def at(self, now: float | None = None) -> float:
        return round((time.monotonic() if now is None else now) - self.t0, 3)

    def open(self, model: str, voice: str) -> None:
        try:
            self.id = db.insert("voice_calls", {"model": model, "voice": voice, "started_at": db.now()})
            self.dir = CALLS_DIR / str(self.id)
            self.dir.mkdir(parents=True, exist_ok=True)
            self.mic_f = (self.dir / "mic.pcm").open("ab")
            self.bot_f = (self.dir / "bot.pcm").open("r+b" if (self.dir / "bot.pcm").exists() else "w+b")
            self.events_f = (self.dir / "events.jsonl").open("a", encoding="utf-8")
        except OSError as e:
            log.warning("通话记录打不开：%s", e)
            self.close_files()

    def link(self, session_id: int) -> None:
        if self.id:
            db.update("voice_calls", self.id, {"session_id": session_id})

    def event(self, kind: str, at: float | None = None, **fields) -> None:
        if not self.events_f:
            return
        try:
            self.events_f.write(json.dumps({"t": self.at() if at is None else at, "kind": kind, **fields}, ensure_ascii=False) + "\n")
            self.events_f.flush()
        except OSError as e:
            log.warning("通话事件写不进去：%s", e)

    def mic(self, pcm: bytes) -> None:
        if self.mic_f:
            self._safely(self.mic_f.write, pcm)

    def bot(self, pcm: bytes, at: float) -> None:
        """机器人的声音写到它开始播放的位置，没声音的地方留空（读出来就是静音）。"""
        if self.bot_f:
            self._safely(lambda: (self.bot_f.seek(int(at * BOT_RATE) * 2), self.bot_f.write(pcm)))

    def cut(self, at: float) -> None:
        """打断后没播出去的不算。"""
        if self.bot_f:
            def do():
                self.bot_f.flush()
                end = int(at * BOT_RATE) * 2
                if self.bot_f.seek(0, 2) > end:
                    self.bot_f.truncate(end)
            self._safely(do)

    def _safely(self, fn, *args) -> None:
        try:
            fn(*args)
        except OSError as e:
            log.warning("通话录音写不进去：%s", e)

    def usage(self, usage: dict) -> None:
        if not self.id or not usage:
            return
        for k, v in usage_tokens(usage).items():
            self.totals[k] += v
        self.responses += 1
        db.update("voice_calls", self.id, {**self.totals, "responses": self.responses, "cost_yuan": round(cost_of(self.totals), 6),
                                           "duration_s": self.at()})

    def close_files(self) -> None:
        for f in (self.mic_f, self.bot_f, self.events_f):
            if f:
                try:
                    f.close()
                except OSError:
                    pass
        self.mic_f = self.bot_f = self.events_f = None

    def close(self) -> None:
        if not self.id:
            return
        db.update("voice_calls", self.id, {"ended_at": db.now(), "duration_s": self.at()})
        self.close_files()


def finish(call_dir: Path) -> bool:
    """原始录音转成能播的文件，成功了才删原始录音。挂断时做一次；进程中途退出的，第一次回听时补做。"""
    mic, bot, mix = call_dir / "mic.pcm", call_dir / "bot.pcm", call_dir / "call.m4a"
    if mix.exists() and not mic.exists():
        return True
    if not mic.exists() or not mic.stat().st_size or not shutil.which("ffmpeg"):
        return False
    tmp = call_dir / "call.tmp.m4a"
    has_bot = bot.exists() and bot.stat().st_size > 0
    inputs = ["-f", "s16le", "-ar", str(MIC_RATE), "-ac", "1", "-i", str(mic)]
    if has_bot:
        inputs += ["-f", "s16le", "-ar", str(BOT_RATE), "-ac", "1", "-i", str(bot)]
        graph = f"[0:a]aresample={BOT_RATE}[m];[m][1:a]amix=inputs=2:duration=longest:normalize=0[a]"
        outs = ["-filter_complex", graph, "-map", "[a]"]
    else:
        outs = ["-map", "0:a"]
    outs += ["-c:a", "aac", "-b:a", "48k", "-movflags", "+faststart", str(tmp), "-map", "0:a", str(call_dir / "mic.flac")]
    if has_bot:
        outs += ["-map", "1:a", str(call_dir / "bot.flac")]
    p = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *inputs, *outs], capture_output=True, text=True, timeout=600)
    done = [tmp, call_dir / "mic.flac", *([call_dir / "bot.flac"] if has_bot else [])]
    if p.returncode or not all(f.exists() and f.stat().st_size for f in done):
        log.warning("通话录音转换失败，原始录音还在 %s：%s", call_dir, p.stderr[-300:])
        return False
    tmp.rename(mix)
    mic.unlink()
    if bot.exists():
        bot.unlink()
    return True


def events(call_id: int) -> list[dict]:
    path = CALLS_DIR / str(call_id) / "events.jsonl"
    if not path.exists():
        return []
    out = []
    for line in path.read_text("utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:  # 进程中途退出时最后一行可能没写完
            pass
    return out
