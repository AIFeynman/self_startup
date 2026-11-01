"""视频深读的素材准备：用 yt-dlp 取元数据和一条字幕（YouTube / B 站等 yt-dlp 支持的站点），转成带时间点的文字稿。

不下载视频；没有字幕时可选用本机 whisper 转写音频（慢，按需开）。不依赖 app 包，深读 Agent 直接这样跑：
    python app/modules/_video.py <视频链接> <输出目录> [--whisper]
产物：<输出目录>/transcript.md（按 ~45 秒分段、每段带 [hh:mm:ss] 跳转链接）与 video.json（标题、频道、时长、章节、字幕来源）。
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

YT_ID_RE = re.compile(r"(?:youtube\.com/(?:watch\?(?:.*&)?v=|shorts/|live/|embed/)|youtu\.be/)([\w-]{11})")
BILI_RE = re.compile(r"bilibili\.com/video/(BV\w{10}|av\d+)", re.I)
VIDEO_URL_RE = re.compile(r"(youtube\.com/(watch|shorts/|live/)|youtu\.be/|bilibili\.com/video/|b23\.tv/)", re.I)
# 字幕语言优先级：人工字幕优先于自动字幕；同一类里原声语言优先，其次英文、中文。自动翻译的轨道（会 429，也不准）不要
LANG_PREF = ("en", "en-US", "en-GB", "zh-Hans", "zh-CN", "zh", "zh-Hant", "zh-TW")
SEG_SECONDS = 45
WHISPER_MAX_SECONDS = 3 * 3600


def is_video_url(url: str) -> bool:
    return bool(VIDEO_URL_RE.search(url or ""))


def youtube_id(url: str) -> str:
    m = YT_ID_RE.search(url or "")
    return m.group(1) if m else ""


def canonical_url(url: str) -> str:
    """去掉播放列表 / 时间点等参数，同一个视频只算一条。"""
    if vid := youtube_id(url):
        return f"https://www.youtube.com/watch?v={vid}"
    if m := BILI_RE.search(url or ""):
        p = parse_qs(urlsplit(url).query).get("p", [""])[0]
        return f"https://www.bilibili.com/video/{m.group(1)}" + (f"?p={p}" if p and p != "1" else "")
    return url


def at_url(url: str, sec: float) -> str:
    """跳到某个时间点的链接。"""
    s = max(0, int(sec))
    if vid := youtube_id(url):
        return f"https://www.youtube.com/watch?v={vid}&t={s}s"
    base = canonical_url(url)
    return f"{base}{'&' if '?' in base else '?'}t={s}"


def hms(sec: float) -> str:
    s = max(0, int(sec))
    return f"{s // 3600:d}:{s // 60 % 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60:02d}:{s % 60:02d}"


def pick_track(info: dict) -> tuple[str, str] | None:
    """(语言, "manual"|"auto")。人工字幕任意语言都比自动字幕好；自动字幕只要原声轨（-orig 或视频本身语言）。"""
    manual = {k: v for k, v in (info.get("subtitles") or {}).items() if k != "live_chat" and v}
    auto = {k: v for k, v in (info.get("automatic_captions") or {}).items() if v}
    lang = (info.get("language") or "").split("-")[0]

    if manual:
        keys = sorted(manual)
        same = [k for k in keys if lang and k.split("-")[0] == lang]
        pref = [p for p in LANG_PREF if p in manual]
        return (same or pref or keys)[0], "manual"
    orig = [k for k in auto if k.endswith("-orig")]
    if orig:
        return orig[0], "auto"
    if lang and lang in auto:
        return lang, "auto"
    for k in ("en", "zh-Hans", "zh"):
        if k in auto:
            return k, "auto"
    return None


_TS = re.compile(r"(\d+):(\d{2}):(\d{2})[.,](\d{3})|(\d{2}):(\d{2})[.,](\d{3})")


def _sec(t: str) -> float:
    m = _TS.fullmatch(t.strip())
    if not m:
        return 0.0
    if m.group(1):
        return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3)) + int(m.group(4)) / 1000
    return int(m.group(5)) * 60 + int(m.group(6)) + int(m.group(7)) / 1000


def parse_vtt(text: str) -> list[tuple[float, str]]:
    """VTT / SRT → [(开始秒, 文本)]。YouTube 自动字幕是滚动式的（每个 cue 重复上一行），按行去重。"""
    cues: list[tuple[float, str]] = []
    seen_last = ""
    for block in re.split(r"\n\s*\n", text.replace("\r", "")):
        lines = [ln for ln in block.split("\n") if ln.strip()]
        ti = next((i for i, ln in enumerate(lines) if "-->" in ln), -1)
        if ti < 0:
            continue
        start = _sec(lines[ti].split("-->")[0])
        for ln in lines[ti + 1:]:
            t = re.sub(r"<[^>]+>", "", ln)
            t = re.sub(r"&nbsp;", " ", t).replace("&amp;", "&").replace("&gt;", ">").replace("&lt;", "<")
            t = re.sub(r"\s+", " ", t).strip()
            if not t or t == seen_last or t in ("[Music]", "[音乐]"):
                continue
            seen_last = t
            cues.append((start, t))
    return cues


def segments(cues: list[tuple[float, str]], seconds: int = SEG_SECONDS) -> list[tuple[float, str]]:
    """把短 cue 合成 ~seconds 秒一段，尽量在句末断开。"""
    out: list[tuple[float, str]] = []
    cur_start, buf = None, []
    for start, t in cues:
        if cur_start is None:
            cur_start = start
        buf.append(t)
        joined = " ".join(buf)
        if start - cur_start >= seconds and re.search(r"[.!?。！？]$", t) or start - cur_start >= seconds * 1.6:
            out.append((cur_start, joined))
            cur_start, buf = None, []
    if buf:
        out.append((cur_start or 0.0, " ".join(buf)))
    return out


def render(info: dict, url: str, segs: list[tuple[float, str]], track: str) -> str:
    ch = info.get("chapters") or []
    head = [f"# {info.get('title') or url}", "",
            f"- 频道：{info.get('channel') or info.get('uploader') or ''}",
            f"- 发布：{info.get('upload_date') or ''} · 时长：{hms(info.get('duration') or 0)} · 字幕：{track}",
            f"- 链接：{canonical_url(url)}", ""]
    if ch:
        head += ["## 作者章节", ""] + [f"- [{hms(c.get('start_time') or 0)}]({at_url(url, c.get('start_time') or 0)}) "
                                      f"{c.get('title') or ''}" for c in ch] + [""]
    desc = (info.get("description") or "").strip()
    if desc:
        head += ["## 视频简介", "", desc[:3000], ""]
    body = ["## 文字稿", ""] + [f"[{hms(s)}]({at_url(url, s)}) {t}\n" for s, t in segs]
    return "\n".join(head + body)


def _run(cmd: list[str], timeout: int = 300) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def fetch(url: str, out: Path, whisper: bool = False) -> dict:
    """取元数据 + 一条字幕，写 transcript.md / video.json。返回 video.json 的内容；失败时 error 字段说明原因。"""
    out.mkdir(parents=True, exist_ok=True)
    ytdlp = shutil.which("yt-dlp")
    if not ytdlp:
        return {"error": "本机没有 yt-dlp（brew install yt-dlp 或 pip install yt-dlp）"}
    r = _run([ytdlp, "-J", "--skip-download", "--no-playlist", url], timeout=120)
    if r.returncode != 0:
        return {"error": f"yt-dlp 取元数据失败：{r.stderr.strip()[-400:]}"}
    info = json.loads(r.stdout)
    meta = {"title": info.get("title"), "channel": info.get("channel") or info.get("uploader"),
            "upload_date": info.get("upload_date"), "duration": info.get("duration"),
            "url": canonical_url(url), "language": info.get("language"),
            "chapters": [{"start": c.get("start_time"), "title": c.get("title")} for c in info.get("chapters") or []]}
    cues: list[tuple[float, str]] = []
    track = pick_track(info)
    if track:
        lang, kind = track
        r = _run([ytdlp, "--skip-download", "--no-playlist", "--write-subs" if kind == "manual" else "--write-auto-subs",
                  "--sub-langs", lang, "--sub-format", "vtt/srt/best", "-o", str(out / "sub.%(ext)s"), url], timeout=180)
        files = sorted(out.glob("sub.*.vtt")) + sorted(out.glob("sub.*.srt"))
        if files:
            cues = parse_vtt(files[0].read_text("utf-8", errors="replace"))
            meta["track"] = f"{'人工字幕' if kind == 'manual' else '自动字幕'} {lang}"
        else:
            meta["track_error"] = r.stderr.strip()[-300:]
    if not cues and whisper:
        cues = _whisper(ytdlp, url, out, info, meta)
    if not cues:
        meta["error"] = meta.get("error") or "没有可用字幕" + ("" if whisper else "（可加 --whisper 用本机 whisper 转写音频）")
    meta["segments"] = len(cues)
    (out / "video.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), "utf-8")
    if cues:
        (out / "transcript.md").write_text(render(info, url, segments(cues), meta.get("track", "")), "utf-8")
    return meta


def _whisper(ytdlp: str, url: str, out: Path, info: dict, meta: dict) -> list[tuple[float, str]]:
    exe = shutil.which("whisper")
    if not exe:
        meta["error"] = "没有字幕，本机也没有 whisper"
        return []
    if (info.get("duration") or 0) > WHISPER_MAX_SECONDS:
        meta["error"] = "没有字幕，视频超过 3 小时，不做本机转写"
        return []
    r = _run([ytdlp, "-f", "bestaudio", "-x", "--audio-format", "m4a", "--no-playlist", "-o", str(out / "audio.%(ext)s"), url],
             timeout=900)
    audio = next(iter(sorted(out.glob("audio.*"))), None)
    if not audio:
        meta["error"] = f"音频下载失败：{r.stderr.strip()[-300:]}"
        return []
    r = _run([exe, str(audio), "--model", "base", "--output_format", "vtt", "--output_dir", str(out)], timeout=3 * 3600)
    vtt = out / (audio.stem + ".vtt")
    audio.unlink(missing_ok=True)
    if not vtt.is_file():
        meta["error"] = f"whisper 转写失败：{r.stderr.strip()[-300:]}"
        return []
    meta["track"] = "本机 whisper 转写"
    return parse_vtt(vtt.read_text("utf-8", errors="replace"))


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 2:
        sys.exit("用法：python _video.py <视频链接> <输出目录> [--whisper]")
    res = fetch(args[0], Path(args[1]).expanduser(), whisper="--whisper" in sys.argv)
    print(json.dumps({k: v for k, v in res.items() if k != "chapters"}, ensure_ascii=False))
    sys.exit(1 if res.get("error") else 0)
