"""视频没字幕时的转写：Groq 云端优先、失败退回本机 whisper。不触网。"""
import subprocess
from pathlib import Path

from app.modules import _video


class _Client:
    def __init__(self, status=200, body=None):
        self.status, self.body, self.sent = status, body or {}, {}

    def post(self, url, headers, data, files):
        self.sent = {"url": url, "data": data, "file": files["file"][0], "auth": headers["Authorization"]}
        return self

    @property
    def status_code(self):
        return self.status

    @property
    def text(self):
        return "boom"

    def json(self):
        return self.body

    def close(self):
        pass


def _fake_tools(monkeypatch, tmp_path, *, key, local):
    """假的 yt-dlp（写出音频文件）和本机 whisper（写出 vtt）。"""
    calls = []

    def run(cmd, timeout=300):
        calls.append(cmd[0])
        if cmd[0] == "yt-dlp":
            (tmp_path / "audio.mp3").write_bytes(b"x")
        elif cmd[0] == "whisper":
            (tmp_path / "audio.vtt").write_text("WEBVTT\n\n00:00.000 --> 00:02.000\nlocal text\n")
        return subprocess.CompletedProcess(cmd, 0, "", "")
    monkeypatch.setattr(_video, "_run", run)
    monkeypatch.setattr(_video.shutil, "which", lambda n: "whisper" if local and n == "whisper" else None)
    monkeypatch.setattr(_video, "_env", lambda n: key if n == "GROQ_API_KEY" else "")
    return calls


def test_transcribe_prefers_groq_then_falls_back(monkeypatch, tmp_path):
    calls = _fake_tools(monkeypatch, tmp_path, key="k", local=True)
    monkeypatch.setattr(_video, "_groq_stt", lambda *a, **k: ([(0.0, "cloud text")], ""))
    meta = {}
    assert _video._whisper("yt-dlp", "u", tmp_path, {"duration": 600}, meta) == [(0.0, "cloud text")]
    assert meta["track"] == "Groq 云端转写" and "whisper" not in calls and not (tmp_path / "audio.mp3").exists()

    monkeypatch.setattr(_video, "_groq_stt", lambda *a, **k: ([], "HTTP 500：boom"))
    meta = {}
    assert _video._whisper("yt-dlp", "u", tmp_path, {"duration": 600}, meta) == [(0.0, "local text")]
    assert meta["track"] == "本机 whisper 转写" and meta["asr_error"] == "HTTP 500：boom"


def test_transcribe_without_key_or_whisper(monkeypatch, tmp_path):
    _fake_tools(monkeypatch, tmp_path, key="", local=False)
    meta = {}
    assert _video._whisper("yt-dlp", "u", tmp_path, {"duration": 600}, meta) == [] and "GROQ_API_KEY" in meta["error"]
    _fake_tools(monkeypatch, tmp_path, key="k", local=False)
    meta = {}
    assert _video._whisper("yt-dlp", "u", tmp_path, {"duration": 4 * 3600}, meta) == [] and "3 小时" in meta["error"]


def test_env_falls_back_to_dotenv(monkeypatch, tmp_path):
    env = tmp_path / ".env"
    env.write_text("# c\nexport GROQ_API_KEY='abc'\nOTHER=1\n")
    monkeypatch.setattr(_video, "ENV_PATH", Path(env))
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    assert _video._env("GROQ_API_KEY") == "abc" and _video._env("NOPE") == ""


def test_groq_stt_request_and_offsets(monkeypatch, tmp_path):
    audio = tmp_path / "audio.mp3"
    audio.write_bytes(b"x")
    c = _Client(body={"segments": [{"start": 1.5, "text": " Hi there. "}, {"start": 3, "text": " "}]})
    cues, err = _video._groq_stt(audio, {"language": "en-US", "tags": ["Codex"]}, "gsk", client=c)
    assert cues == [(1.5, "Hi there.")] and err == "" and c.sent["url"] == _video.GROQ_STT_URL
    assert c.sent["data"]["language"] == "en" and c.sent["data"]["prompt"] == "Codex"
    assert c.sent["data"]["response_format"] == "verbose_json"
    # 超过单文件上限：切段上传，时间加上前面各段的时长，分段文件用完删掉
    parts = [(tmp_path / "audio_part00.mp3", 0.0), (tmp_path / "audio_part01.mp3", 3600.0)]
    for p, _ in parts:
        p.write_bytes(b"x")
    monkeypatch.setattr(_video, "GROQ_MAX_BYTES", 0)
    monkeypatch.setattr(_video, "_split", lambda a: parts)
    cues, _ = _video._groq_stt(audio, {}, "gsk", client=_Client(body={"segments": [{"start": 2, "text": "a"}]}))
    assert cues == [(2.0, "a"), (3602.0, "a")] and not any(p.exists() for p, _ in parts) and audio.exists()
