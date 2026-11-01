"""视频没字幕时的转写：xAI 云端优先、失败退回本机 whisper；逐词时间戳拼成句子。不触网。"""
import subprocess
from pathlib import Path

from app.modules import _video


def test_words_to_cues_breaks_on_punct_gap_and_length():
    words = [{"text": "Hello", "start": 0.0, "end": 0.4}, {"text": "world.", "start": 0.4, "end": 0.9},
             {"text": "Next", "start": 1.0, "end": 1.3}, {"text": "part", "start": 1.3, "end": 1.6},
             {"text": "after", "start": 4.0, "end": 4.3}, {"text": "pause", "start": 4.3, "end": 4.6}]
    assert _video.words_to_cues(words) == [(0.0, "Hello world."), (1.0, "Next part"), (4.0, "after pause")]
    long = [{"text": f"w{i}", "start": i * 0.5, "end": i * 0.5 + 0.4} for i in range(40)]
    assert all(len(t.split()) <= 25 for _, t in _video.words_to_cues(long, max_seconds=12))


def test_words_to_cues_joins_cjk_without_spaces():
    words = [{"text": "大", "start": 0, "end": 0.2}, {"text": "模型", "start": 0.2, "end": 0.5},
             {"text": "Agent", "start": 0.5, "end": 0.9}, {"text": "很好。", "start": 0.9, "end": 1.2}]
    assert _video.words_to_cues(words) == [(0, "大模型Agent很好。")]


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


def test_xai_stt_request_and_errors(tmp_path):
    audio = tmp_path / "audio.mp3"
    audio.write_bytes(b"x")
    info = {"language": "en-US", "channel": "Anthropic", "tags": ["Claude Code", "x" * 60, "claude code"]}
    c = _Client(body={"words": [{"text": "Hi.", "start": 1.0, "end": 1.2}]})
    cues, err = _video._xai_stt(audio, info, "k", client=c)
    assert cues == [(1.0, "Hi.")] and err == ""
    assert c.sent["url"] == _video.XAI_STT_URL and c.sent["auth"] == "Bearer k" and c.sent["file"] == "audio.mp3"
    assert c.sent["data"] == {"model": _video.XAI_STT_MODEL, "language": "en",
                              "keyterm": ["Anthropic", "Claude Code"]}                         # 超长、重复的去掉
    _video._xai_stt(audio, {"language": "xx"}, "k", client=(c2 := _Client()))
    assert c2.sent["data"] == {"model": _video.XAI_STT_MODEL}                                  # 不支持的语言、空 keyterm 不传
    assert _video._xai_stt(audio, info, "k", client=_Client(status=401))[1].startswith("HTTP 401")


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
    monkeypatch.setattr(_video, "_env", lambda n: key if n == "GROK_API_KEY" else "")   # 只配了 GROK_API_KEY 也认
    return calls


def test_transcribe_prefers_xai_then_falls_back(monkeypatch, tmp_path):
    calls = _fake_tools(monkeypatch, tmp_path, key="k", local=True)
    monkeypatch.setattr(_video, "_xai_stt", lambda *a, **k: ([(0.0, "cloud text")], ""))
    meta = {}
    assert _video._whisper("yt-dlp", "u", tmp_path, {"duration": 600}, meta) == [(0.0, "cloud text")]
    assert meta["track"] == "xAI 云端转写" and "whisper" not in calls and not (tmp_path / "audio.mp3").exists()

    monkeypatch.setattr(_video, "_xai_stt", lambda *a, **k: ([], "HTTP 500：boom"))
    meta = {}
    assert _video._whisper("yt-dlp", "u", tmp_path, {"duration": 600}, meta) == [(0.0, "local text")]
    assert meta["track"] == "本机 whisper 转写" and meta["asr_error"] == "xAI：HTTP 500：boom"


def test_transcribe_without_key_or_whisper(monkeypatch, tmp_path):
    _fake_tools(monkeypatch, tmp_path, key="", local=False)
    meta = {}
    assert _video._whisper("yt-dlp", "u", tmp_path, {"duration": 600}, meta) == [] and "GROQ_API_KEY" in meta["error"]
    _fake_tools(monkeypatch, tmp_path, key="k", local=False)
    meta = {}
    assert _video._whisper("yt-dlp", "u", tmp_path, {"duration": 4 * 3600}, meta) == [] and "3 小时" in meta["error"]


def test_env_falls_back_to_dotenv(monkeypatch, tmp_path):
    env = tmp_path / ".env"
    env.write_text("# c\nexport XAI_API_KEY='abc'\nOTHER=1\n")
    monkeypatch.setattr(_video, "ENV_PATH", Path(env))
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    assert _video._env("XAI_API_KEY") == "abc" and _video._env("NOPE") == ""


def test_stt_keys_by_prefix(monkeypatch):
    env = {"GROK_API_KEY": "gsk_abc"}
    monkeypatch.setattr(_video, "_env", lambda n: env.get(n, ""))
    assert _video.stt_keys() == [("Groq", "gsk_abc")]          # Groq 的 key 写成 GROK_ 也认得出来
    env = {"GROK_API_KEY": "xai-1", "GROQ_API_KEY": "gsk_2"}
    assert _video.stt_keys() == [("xAI", "xai-1"), ("Groq", "gsk_2")]


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


def test_transcribe_tries_xai_then_groq(monkeypatch, tmp_path):
    _fake_tools(monkeypatch, tmp_path, key="", local=False)
    env = {"XAI_API_KEY": "xai-1", "GROQ_API_KEY": "gsk_2"}
    monkeypatch.setattr(_video, "_env", lambda n: env.get(n, ""))
    monkeypatch.setattr(_video, "_xai_stt", lambda *a, **k: ([], "HTTP 401：bad"))
    monkeypatch.setattr(_video, "_groq_stt", lambda *a, **k: ([(0.0, "groq")], ""))
    meta = {}
    assert _video._whisper("yt-dlp", "u", tmp_path, {"duration": 600}, meta) == [(0.0, "groq")]
    assert meta["track"] == "Groq 云端转写" and meta["asr_error"] == "xAI：HTTP 401：bad"
