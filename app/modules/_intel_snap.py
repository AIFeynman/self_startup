"""产品雷达的快照：抓页面 → 提正文 → 哈希 → 和上一版按行 diff → 新增块变成候选；定价页另做结构化。

纯函数为主（不读写库），intel.py 负责调度和落库；测试直接喂 HTML 文本，不触网。
"""
from __future__ import annotations

import difflib
import html
import json
import os
import re
from datetime import datetime, timedelta, timezone
from hashlib import sha1
from html.parser import HTMLParser

import httpx

from . import _feed_sources as fsrc

MAX_CHARS = 200_000     # 正文上限：changelog 一般最新在前，截前面
MIN_ADDED = 30          # 新增块不到这么多字符的忽略（改个日期、按钮文案之类）
BLOCK_MAX = 1500        # 一个候选最多带多少字正文给分类
FIRST_DAYS = 14         # 首次快照只把最近这么多天的条目当候选
TIMEOUT = httpx.Timeout(25.0, connect=10.0)
LLM_TIMEOUT = httpx.Timeout(120.0, connect=10.0)

SKIP_TAGS = {"script", "style", "noscript", "svg", "nav", "header", "footer", "template", "iframe", "button", "form"}
BLOCK_TAGS = {"p", "div", "section", "article", "main", "li", "ul", "ol", "br", "tr", "table", "h1", "h2", "h3", "h4", "h5", "h6",
              "pre", "blockquote", "dd", "dt", "hr", "summary", "details", "time"}
VOID_TAGS = {"br", "hr", "img", "input", "meta", "link", "source", "wbr", "area", "base", "col", "embed", "param", "track"}


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in VOID_TAGS:
            if tag in BLOCK_TAGS and not self.skip:
                self.out.append("\n")
            return
        if tag in SKIP_TAGS:
            self.skip += 1
        elif tag in BLOCK_TAGS and not self.skip:
            self.out.append("\n" + ("## " if tag in ("h1", "h2", "h3") else "- " if tag == "li" else ""))

    def handle_endtag(self, tag):
        if tag in VOID_TAGS:
            return
        if tag in SKIP_TAGS:
            self.skip = max(0, self.skip - 1)
        elif tag in BLOCK_TAGS and not self.skip:
            self.out.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)


def _main_region(page: str) -> str:
    """有 <main> / <article> 时只取那一块（取最长的那个），去掉站点导航、页脚之类的噪声。"""
    best = ""
    for tag in ("main", "article"):
        for m in re.finditer(rf"<{tag}\b[^>]*>(.*?)</{tag}>", page, re.S | re.I):
            if len(m[1]) > len(best):
                best = m[1]
        if len(best) > 2000:
            return best
    return best if len(best) > 2000 else page


def normalize(text: str) -> str:
    lines = []
    for ln in text.splitlines():
        ln = re.sub(r"[ \t ​]+", " ", ln).strip()
        if ln in ("", "-", "##", "- ##"):
            continue
        if lines and ln == lines[-1]:
            continue
        lines.append(ln)
    return "\n".join(lines)[:MAX_CHARS]


def extract_text(body: str, content_type: str = "", url: str = "") -> str:
    """HTML → 归一化的正文行；markdown / 纯文本原样归一化。"""
    if "html" not in content_type and not re.search(r"<(html|body|div|p)\b", body[:5000], re.I):
        return normalize(body)
    p = _Text()
    p.feed(_main_region(body))
    p.close()
    return normalize(html.unescape("".join(p.out)))


def text_hash(text: str) -> str:
    return sha1(text.encode()).hexdigest()


def fetch(url: str, client: httpx.Client | None = None) -> tuple[int, str, str]:
    """(status, content_type, body)。用浏览器 UA：不少官网对脚本 UA 直接 403。"""
    own = client is None
    c = client or httpx.Client(timeout=TIMEOUT, follow_redirects=True,
                               headers={"User-Agent": fsrc.BROWSER_UA, "Accept-Language": "en-US,en;q=0.9"})
    try:
        r = c.get(url)
        return r.status_code, r.headers.get("content-type", ""), r.text
    finally:
        if own:
            c.close()


# ---------- diff ----------

def added_blocks(old: str, new: str, min_chars: int = MIN_ADDED) -> list[str]:
    """新版里新增 / 改写的连续行块（只看新增，不看删除）；太短的块丢掉。"""
    a, b = old.splitlines(), new.splitlines()
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    out = []
    for op, _i1, _i2, j1, j2 in sm.get_opcodes():
        if op not in ("insert", "replace"):
            continue
        block = "\n".join(b[j1:j2]).strip()
        if len(re.sub(r"\s+", "", block)) >= min_chars:
            out.append(block[:BLOCK_MAX * 2])
    return out


def removed_lines(old: str, new: str) -> list[str]:
    a, b = old.splitlines(), new.splitlines()
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    return [ln for op, i1, i2, _j1, _j2 in sm.get_opcodes() if op in ("delete", "replace") for ln in a[i1:i2]]


def split_entries(block: str) -> list[str]:
    """一个新增块里可能是好几条更新：按日期行 / 二级标题切开；切不开就整块一条。"""
    parts, cur = [], []
    for ln in block.splitlines():
        if cur and (find_date(ln) and len(ln) < 80 or ln.startswith("## ")):
            parts.append("\n".join(cur))
            cur = []
        cur.append(ln)
    if cur:
        parts.append("\n".join(cur))
    parts = [p.strip() for p in parts if len(re.sub(r"\s+", "", p)) >= MIN_ADDED]
    return parts or ([block] if block.strip() else [])


# ---------- 日期 ----------

_MON = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_DATE_RES = [
    re.compile(r"\b(20\d\d)[-/.](\d{1,2})[-/.](\d{1,2})\b"),
    re.compile(r"(20\d\d)年(\d{1,2})月(\d{1,2})日"),
    re.compile(r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(20\d\d)\b", re.I),
    re.compile(r"\b(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?,?\s+(20\d\d)\b", re.I),
]


def find_date(text: str) -> str:
    """文本里第一个像发布日期的日期 → YYYY-MM-DD；没有返回 ''。"""
    for i, rx in enumerate(_DATE_RES):
        m = rx.search(text or "")
        if not m:
            continue
        try:
            if i < 2:
                y, mo, d = int(m[1]), int(m[2]), int(m[3])
            elif i == 2:
                y, mo, d = int(m[3]), _MON[m[1][:3].lower()], int(m[2])
            else:
                y, mo, d = int(m[3]), _MON[m[2][:3].lower()], int(m[1])
            return datetime(y, mo, d).strftime("%Y-%m-%d")
        except (ValueError, KeyError):
            continue
    return ""


def recent_entries(text: str, days: int = FIRST_DAYS, today: datetime | None = None) -> list[str]:
    """首次快照：按日期行把全文切成条目，只留最近 days 天的（没日期的页面一条都不出，只当基线）。"""
    today = today or datetime.now()
    cutoff = (today - timedelta(days=days)).strftime("%Y-%m-%d")
    out, cur, cur_date = [], [], ""
    for ln in text.splitlines():
        d = find_date(ln) if len(ln) < 120 else ""
        if d:
            if cur and cur_date >= cutoff:
                out.append("\n".join(cur))
            cur, cur_date = [ln], d
        elif cur:
            cur.append(ln)
    if cur and cur_date >= cutoff:
        out.append("\n".join(cur))
    return [x[:BLOCK_MAX * 2] for x in out if len(re.sub(r"\s+", "", x)) >= MIN_ADDED]


def entry_title(block: str) -> str:
    """候选标题：第一行像标题的文字（去掉日期行、列表符号）。"""
    lines = [ln.lstrip("#-* ").strip() for ln in block.splitlines() if ln.strip()]
    for ln in lines:
        if len(ln) >= 6 and not (find_date(ln) and len(ln) < 40):
            return ln[:160]
    return (lines[0] if lines else "")[:160]


# ---------- RSS / Atom 源 ----------

PRERELEASE_RE = re.compile(r"\b(alpha|beta|nightly|preview|rc\d*|canary|dev)\b|-(alpha|beta|nightly|preview|rc)", re.I)


def rss_entries(text: str, url: str, days: int = FIRST_DAYS) -> list[dict]:
    """RSS/Atom → 候选（GitHub releases 去掉 alpha / nightly 之类的预发布）。"""
    items = fsrc.parse_feed(text, url, source="intel", typ="release", days=days, limit=30)
    return [it for it in items if not PRERELEASE_RE.search(it["title"])]


# ---------- 定价页结构化（DeepSeek） ----------

PRICE_RE = re.compile(r"(?:[$€£¥￥]\s?\d[\d,]*(?:\.\d+)?|\d[\d,]*(?:\.\d+)?\s?(?:USD|元|美元))")

PRICING_SYSTEM = """你在跟踪一家 AI 公司定价页的变化。输入是 JSON：
- old_structure：上一版定价结构（首次为空）；
- added：新版里新增 / 改写的行；removed：旧版里被删掉 / 改写的行；
- page：新版定价页正文（可能截断）。
输出 JSON 对象：
{"structure": {"plans": [{"name": "套餐名", "price": "价格原文（含币种和周期，如 $20/月）", "audience": "面向谁", "limits": "额度 / 限制要点", "notes": "其它要点"}],
               "usage": [{"item": "按量计费项，如 某模型输入 token", "price": "价格原文"}]},
 "changes": [{"title": "一句话中文标题，如 Pro 套餐从 $20 涨到 $25/月", "summary": "改了什么、前后对比（中文，≤120 字）",
              "scale": "major | normal | minor"}]}
规则：只根据输入里出现的文字，不要补充页面上没有的数字；价格必须照抄原文；只是措辞、排版、按钮变化不算 change；
首次（old_structure 为空）changes 返回空数组。scale：涨降价、新套餐、砍套餐、免费额度大改 = major；限额小调 = normal；文案 = minor。"""


def _deepseek(system: str, payload: dict, *, max_tokens: int = 4000, client: httpx.Client | None = None) -> dict:
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not key:
        raise RuntimeError("未配置 DEEPSEEK_API_KEY（项目根目录 .env）")
    base = os.environ.get("DEEPSEEK_API_BASE", "https://api.deepseek.com").rstrip("/")
    own = client is None
    c = client or httpx.Client(timeout=LLM_TIMEOUT)
    try:
        r = c.post(f"{base}/chat/completions", headers={"Authorization": f"Bearer {key}"}, json={
            "model": "deepseek-v4-flash", "temperature": 0.2, "max_tokens": max_tokens,
            "thinking": {"type": "disabled"}, "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]})
        r.raise_for_status()
        return json.loads(r.json()["choices"][0]["message"]["content"])
    finally:
        if own:
            c.close()


def llm_json(system: str, payload: dict, **kw) -> dict:
    """可在测试里 monkeypatch 的统一入口。"""
    return _deepseek(system, payload, **kw)


def verify_prices(changes: list[dict], new_text: str, old_text: str = "") -> list[dict]:
    """确定性核对：change 里出现的价格数字必须在新旧页面某一版里真的出现过，否则丢掉（防模型编数字）。"""
    pool = re.sub(r"\s", "", new_text + "\n" + old_text)
    ok = []
    for ch in changes:
        prices = PRICE_RE.findall(f"{ch.get('title', '')} {ch.get('summary', '')}")
        if all(re.sub(r"\s", "", p) in pool for p in prices):
            ok.append(ch)
    return ok


def pricing_diff(old_structure: dict | None, old_text: str, new_text: str) -> tuple[dict, list[dict]]:
    """(新结构, 变化列表)。首次只出结构。"""
    payload = {"old_structure": old_structure or {}, "page": new_text[:24000]}
    if old_text:
        payload["added"] = [ln for b in added_blocks(old_text, new_text, min_chars=1) for ln in b.splitlines()][:300]
        payload["removed"] = removed_lines(old_text, new_text)[:300]
    out = llm_json(PRICING_SYSTEM, payload)
    structure = out.get("structure") if isinstance(out.get("structure"), dict) else {}
    changes = [c for c in (out.get("changes") or []) if isinstance(c, dict) and c.get("title")] if old_text else []
    return structure, verify_prices(changes, new_text, old_text)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
