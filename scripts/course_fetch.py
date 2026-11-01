#!/usr/bin/env python3
"""把课程一讲的原始材料抓成纯文本，给 Haiku 整理素材包用（不调用任何模型）。

用法：
    python3 scripts/course_fetch.py <输出目录> <链接> [<链接> ...]
        PDF（课件 / 讲义 / 作业说明）→ pdftotext；YouTube → yt-dlp 英文字幕（手工字幕优先，没有用自动字幕）；
        其他网页 → 去掉标签的正文。每个链接写一个 <序号>-<类型>.txt，再写 index.json 记下每个链接的结果。
    python3 scripts/course_fetch.py --playlist <YouTube 播放列表 / 频道链接>
        列出播放列表里的视频（标题 + 链接），课程官网是 JS 渲染、抓不到课表时用来补录像链接。

已经抓过的链接（输出文件存在且非空）直接跳过，所以同一讲重复整理不会重复下载。
"""
from __future__ import annotations

import html
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
MAX_CHARS = 120_000  # 单个文件上限：一小时字幕约 6 万字符，再长的截断
TIMEOUT = 60


def kind_of(url: str) -> str:
    u = url.lower()
    if re.search(r"(youtube\.com/watch|youtu\.be/|youtube\.com/live/)", u):
        return "video"
    if u.split("?")[0].endswith(".pdf") or "arxiv.org/pdf/" in u:
        return "pdf"
    m = re.match(r"https://drive\.google\.com/file/d/([^/]+)", url)
    if m:
        return "pdf"
    return "page"


def _direct(url: str) -> str:
    """换成能直接下载文件的地址：Google Drive 预览页 → 下载链接；GitHub 上的 PDF 页面（/blob/）→ 原文件（/raw/）。"""
    m = re.match(r"https://drive\.google\.com/file/d/([^/]+)", url)
    if m:
        return f"https://drive.google.com/uc?export=download&id={m.group(1)}"
    m = re.match(r"(https://github\.com/[^/]+/[^/]+)/blob/(.+\.pdf)$", url, re.I)
    return f"{m.group(1)}/raw/{m.group(2)}" if m else url


def _get(url: str) -> tuple[bytes, str]:
    """用 curl 下载：走本机代理时 Python 自带的 urllib 会 SSL 握手失败，curl 正常。"""
    with tempfile.TemporaryDirectory() as d:
        body = Path(d) / "body"
        r = subprocess.run(["curl", "-sSL", "--max-time", str(TIMEOUT), "-A", UA, "-o", str(body),
                            "-w", "%{http_code}\t%{content_type}", _direct(url)], capture_output=True, timeout=TIMEOUT + 10)
        code, _, ctype = r.stdout.decode("utf-8", "replace").partition("\t")
        if r.returncode or not code.startswith("2"):
            raise RuntimeError(f"下载失败 HTTP {code or '-'}：{r.stderr.decode('utf-8', 'replace')[:200]}")
        return body.read_bytes(), ctype


def pdf_text(data: bytes) -> str:
    if not shutil.which("pdftotext"):
        raise RuntimeError("没有 pdftotext（brew install poppler）")
    with tempfile.TemporaryDirectory() as d:
        src = Path(d) / "in.pdf"
        src.write_bytes(data)
        out = subprocess.run(["pdftotext", "-layout", str(src), "-"], capture_output=True, timeout=120)
        if out.returncode:
            raise RuntimeError(out.stderr.decode("utf-8", "replace")[:300])
        # 课件每页之间用换页符分隔，换成可读的页码标记，方便 Haiku 逐页整理
        pages = out.stdout.decode("utf-8", "replace").split("\f")
        return "\n".join(f"\n===== 第 {i} 页 =====\n{p.strip()}" for i, p in enumerate(pages, 1) if p.strip())


def page_text(data: bytes) -> str:
    t = data.decode("utf-8", "replace")
    t = re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", t)
    # 保留链接地址：课表页的讲义 / 视频链接是要的东西
    t = re.sub(r'(?is)<a\s[^>]*href="([^"]+)"[^>]*>(.*?)</a>', r"\2 (\1)", t)
    t = re.sub(r"(?i)<br\s*/?>|</(p|div|li|tr|h\d)>", "\n", t)
    t = html.unescape(re.sub(r"<[^>]+>", " ", t))
    return "\n".join(line.strip() for line in t.splitlines() if line.strip())


# JS 渲染的课程站（React / Vue 打包）：课表是打包进 JS 的对象字面量，抽出这些键的字符串值，按出现顺序一行一个
JS_KEYS = ("code", "date", "time", "week", "title", "name", "label", "module", "unit", "topic", "speaker",
           "summary", "description", "url", "href", "slides", "recording", "video", "reading")


def js_data(page_url: str, html_text: str) -> str:
    from urllib.parse import urljoin
    lines = []
    for src in re.findall(r'<script[^>]+src="([^"]+)"', html_text)[:5]:
        try:
            data, _ = _get(urljoin(page_url, src))
        except Exception:  # noqa: BLE001
            continue
        js = data.decode("utf-8", "replace")
        for key, val in re.findall(r'\b(%s):"((?:[^"\\]|\\.){2,400})"' % "|".join(JS_KEYS), js):
            if key in ("url", "href") and val.startswith("/"):
                val = urljoin(page_url, val)
            lines.append(f"{key}: {val}")
    return "\n".join(lines)


def _vtt_to_text(vtt: str) -> str:
    """字幕转成按分钟分段的纯文本：自动字幕每行会重复上一行，去重；保留 [mm:ss] 方便回看视频。"""
    out, last, seen_min = [], "", -1
    stamp = ""
    for line in vtt.splitlines():
        m = re.match(r"(\d+):(\d\d):(\d\d)\.\d+ -->", line) or re.match(r"(\d\d):(\d\d)\.\d+ -->", line)
        if m:
            g = [int(x) for x in m.groups()]
            h, mi = (g[0], g[1]) if len(g) == 3 else (0, g[0])
            total = h * 60 + mi
            if total != seen_min:
                seen_min, stamp = total, f"\n[{h:d}:{mi:02d}] " if h else f"\n[{mi:02d}:00] "
            continue
        if not line.strip() or line.startswith(("WEBVTT", "Kind:", "Language:", "NOTE")) or "-->" in line:
            continue
        text = re.sub(r"<[^>]+>", "", line).strip()
        if not text or text == last:
            continue
        last = text
        out.append(stamp + text)
        stamp = ""
    return " ".join(out).strip()


def video_text(url: str) -> str:
    if not shutil.which("yt-dlp"):
        raise RuntimeError("没有 yt-dlp")
    with tempfile.TemporaryDirectory() as d:
        # 新版 yt-dlp 解析 YouTube 要 JS 运行时，默认只认 deno；本机没有 deno 时用 node
        rt = [] if shutil.which("deno") else ["--js-runtimes", "node"] if shutil.which("node") else []
        base = ["yt-dlp", *rt, "--skip-download", "--no-simulate", "--sub-format", "vtt", "-o", f"{d}/v.%(ext)s",
                "--print", "%(title)s\t%(duration_string)s", url]
        # --print 默认只模拟不落盘，要 --no-simulate 才会写字幕文件
        # 先要手工英文字幕（语言代码可能是 en / en-US / en-GB），没有再要英文自动字幕；
        # 一次只要一类：多要几种会多发请求，更容易被字幕接口限流（429）
        tries = [["--write-subs", "--sub-langs", "en.*"], ["--write-auto-subs", "--sub-langs", "en"]]
        subs, err, waited = [], "", False
        while tries and not subs:
            r = subprocess.run(base[:1] + tries[0] + base[1:], capture_output=True, timeout=300)
            subs = sorted(Path(d).glob("*.vtt"))
            err = r.stderr.decode("utf-8", "replace")
            if not subs and "429" in err and not waited:
                waited = True
                time.sleep(30)  # 被限流：等一会儿再试一次，还不行就报失败，素材包只用课件和阅读材料
                continue
            tries.pop(0)
        head = r.stdout.decode("utf-8", "replace").strip().splitlines()
        if not subs:
            why = "字幕接口限流（429），稍后重新整理这一讲可补上" if "429" in err else "没有英文字幕"
            raise RuntimeError(f"{why}：{err[-200:]}")
        title = head[0] if head else ""
        return f"视频：{title}\n链接：{url}\n\n" + _vtt_to_text(subs[0].read_text("utf-8", "replace"))


def playlist(url: str) -> list[dict]:
    rt = [] if shutil.which("deno") else ["--js-runtimes", "node"] if shutil.which("node") else []
    r = subprocess.run(["yt-dlp", *rt, "--flat-playlist", "--print", "%(title)s\t%(url)s\t%(upload_date)s", url],
                       capture_output=True, timeout=300)
    out = []
    for line in r.stdout.decode("utf-8", "replace").splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            out.append({"title": parts[0], "url": parts[1], "date": parts[2] if len(parts) > 2 and parts[2] != "NA" else ""})
    return out


def fetch(out_dir: Path, urls: list[str]) -> list[dict]:
    out_dir.mkdir(parents=True, exist_ok=True)
    idx_path = out_dir / "index.json"
    old = {x["url"]: x for x in json.loads(idx_path.read_text("utf-8"))} if idx_path.is_file() else {}
    index = []
    for i, url in enumerate(urls, 1):
        kind = kind_of(url)
        name = f"{i:02d}-{kind}.txt"
        prev = old.get(url)
        if prev and prev.get("ok") and (out_dir / prev["file"]).is_file() and (out_dir / prev["file"]).stat().st_size:
            index.append(prev)
            continue
        rec = {"url": url, "kind": kind, "file": name, "ok": False}
        try:
            if kind == "video":
                text = video_text(url)
            else:
                data, ctype = _get(url)
                if kind == "pdf" or "pdf" in ctype or data[:5] == b"%PDF-":
                    rec["kind"], text = "pdf", pdf_text(data)
                else:
                    text = page_text(data)
                    if len(text) < 500:  # 正文几乎为空：多半是 JS 渲染的单页应用，去打包的 JS 里找课表数据
                        extra = js_data(url, data.decode("utf-8", "replace"))
                        if extra:
                            text += "\n\n===== 页面是 JS 渲染的，以下是从打包 JS 里抽出的数据（键: 值，按出现顺序）=====\n" + extra
            if len(text) > MAX_CHARS:
                text = text[:MAX_CHARS] + f"\n\n…（截断，原文 {len(text)} 字符）"
            (out_dir / name).write_text(text, "utf-8")
            rec.update(ok=bool(text.strip()), chars=len(text))
            if not text.strip():
                rec["error"] = "抽不出文字（可能是扫描件或 JS 渲染页面）"
        except Exception as e:  # noqa: BLE001 —— 单个链接失败不影响其他链接
            rec["error"] = str(e)[:300]
        index.append(rec)
    idx_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), "utf-8")
    return index


def main(argv: list[str]) -> int:
    if len(argv) == 2 and argv[0] == "--playlist":
        for v in playlist(argv[1]):
            print(f"{v['title']}\t{v['url']}\t{v['date']}")
        return 0
    if len(argv) < 2:
        print(__doc__)
        return 2
    for rec in fetch(Path(argv[0]), argv[1:]):
        status = f"ok {rec.get('chars', 0)} 字符" if rec["ok"] else f"失败：{rec.get('error', '')}"
        print(f"{rec['file']}\t{rec['kind']}\t{status}\t{rec['url']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
