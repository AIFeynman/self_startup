"""深度读书：一本书（PDF / txt）→ 分章 → 全书导读 + 逐章导读（来龙去脉、精髓、分节导读），全程用轻量模型。

拆章不靠模型（确定性、零成本）：
    1. PDF 自带书签（pypdf 可用时）；
    2. 解析前 40 页里的目录页（「标题 …… 页码」），按标题在正文页首出现的位置求出「书页码 → PDF 页」的偏移，逐条再微调 ±3 页；
    3. 都没有 → 扫正文页首的「Chapter N / 第 N 章」；还没有 → 每 30 页一段。
（目录页解析不出来、但确实有目录时，learn.py 会再派一个轻量 job 让模型读前 25 页抄出目录，回来仍走第 2 步的定位。）
每章正文存成 data/learn/books/<id>/ch/<idx>.txt，导读 prompt 把正文直接放进去（不让模型调工具读文件，省轮次）。
单章太长（> PART_TOKENS）就拆成「(1/2)」「(2/2)」几段，保证每次调用都落在轻量模型的便宜档（≤ 100K token）里。
"""
from __future__ import annotations

import json
import re
import subprocess
import unicodedata
from pathlib import Path

import httpx

PART_TOKENS = 60_000          # 一段正文的估算 token 上限（再加书的地图、前情，一次调用仍在 100K 以内）
TOC_SCAN_PAGES = 40
MATTER = re.compile(r"^(contents|table of contents|list of (illustrations|figures|tables)|words of thanks|acknowledg\w*|"
                    r"notes|bibliography|references|credits|index|copyright|about the author|目录|目次|参考文献|索引|致谢|版权)\b", re.I)
FRONT = re.compile(r"^(overview|preface|foreword|introduction|prologue|前言|序|自序|导论|引言|导读|绪论)", re.I)
PART = re.compile(r"^(part|book|volume)\b|^第\s*\S{1,4}\s*[部篇卷编]", re.I)
ROMAN = re.compile(r"^[ivxlcdm]+$", re.I)
TOC_LINE = re.compile(r"^(\s*)(\S.*?)(?:\s*[.·…_]{2,}\s*|\s{2,}|\s+)(\d{1,4}|[ivxlcdmIVXLCDM]{1,7})\s*$")


# ---------- 取文本 ----------

def fetch(src: str, dest: Path) -> Path:
    """src 是 URL 或本机路径；PDF 存成 dest/book.pdf，文本存成 dest/book.txt。返回存下的文件。"""
    dest.mkdir(parents=True, exist_ok=True)
    p = Path(src).expanduser()
    if p.is_file():
        data = p.read_bytes()
    else:
        with httpx.Client(timeout=httpx.Timeout(120.0, connect=15.0), follow_redirects=True,
                          headers={"User-Agent": "Mozilla/5.0 (self-startup book reader)"}) as c:
            r = c.get(src)
            r.raise_for_status()
            data = r.content
    out = dest / ("book.pdf" if data[:5] == b"%PDF-" else "book.txt")
    out.write_bytes(data)
    return out


def pdf_pages(pdf: Path, layout: bool = False, last: int = 0) -> list[str]:
    cmd = ["pdftotext", "-enc", "UTF-8", *(["-layout"] if layout else []), *(["-l", str(last)] if last else []), str(pdf), "-"]
    out = subprocess.run(cmd, capture_output=True, timeout=600).stdout.decode("utf-8", errors="replace")
    pages = out.split("\f")
    if pages and not pages[-1].strip():
        pages.pop()
    return pages


def text_pages(txt: Path, per: int = 3000) -> list[str]:
    """纯文本书按段落切成约 per 字一「页」，好和 PDF 走同一套流程。"""
    t = txt.read_text("utf-8", errors="replace")
    pages, cur = [], ""
    for para in re.split(r"\n\s*\n", t):
        if cur and len(cur) + len(para) > per:
            pages.append(cur)
            cur = ""
        cur += para.strip() + "\n\n"
    if cur.strip():
        pages.append(cur)
    return pages


def pdf_meta(pdf: Path) -> dict:
    try:
        import pypdf  # noqa: PLC0415 —— 可选依赖
        r = pypdf.PdfReader(str(pdf))
        m = r.metadata or {}
        return {"title": str(m.get("/Title") or ""), "author": str(m.get("/Author") or ""), "outline": _outline(r)}
    except Exception:  # noqa: BLE001 —— 没装 pypdf 或 PDF 坏了：走目录页解析
        return {"title": "", "author": "", "outline": []}


def _outline(r) -> list[dict]:
    out: list[dict] = []

    def walk(items, level):
        for it in items:
            if isinstance(it, list):
                walk(it, level + 1)
                continue
            try:
                out.append({"title": str(it.title).strip(), "page": r.get_destination_page_number(it), "level": level})
            except Exception:  # noqa: BLE001
                pass
    walk(r.outline or [], 0)
    return [o for o in out if o["title"]]


# ---------- 目录页 ----------

def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r"[^0-9a-z一-鿿]+", " ", s.lower()).strip()


def roman(s: str) -> int:
    vals = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100, "d": 500, "m": 1000}
    n = prev = 0
    for ch in reversed(s.lower()):
        v = vals[ch]
        n, prev = (n - v, prev) if v < prev else (n + v, v)
    return n


def toc_pages(layout: list[str]) -> list[int]:
    """前几十页里的目录页：页首有「Contents / 目录」或整页大半是「标题 …… 页码」的行，且连续。"""
    def entries(pg):
        return sum(1 for ln in pg.splitlines() if TOC_LINE.match(ln) and len(ln.strip()) > 6)
    found: list[int] = []
    for i, pg in enumerate(layout[:TOC_SCAN_PAGES]):
        head = _norm(pg[:300])
        n = entries(pg)
        if (re.search(r"\b(contents|table of contents)\b|目\s*录|目\s*次", head) and n >= 3) or (found and found[-1] == i - 1 and n >= 4):
            found.append(i)
        elif found:
            break
    return found


def parse_toc(layout: list[str], pages: list[int]) -> list[dict]:
    """目录行 → [{title, num(书页码 int 或 None), roman, indent, part}]。没页码的行：下一行缩进更深就是标题折行，否则是「部」。"""
    lines: list[str] = []
    for i in pages:
        lines += layout[i].splitlines() + [""]
    out: list[dict] = []
    part, pending, pending_indent = "", "", -1
    for ln in lines:
        if not ln.strip():
            if pending:
                part, pending = pending, ""
            continue
        m = TOC_LINE.match(ln)
        if m and not _norm(m.group(2)) in ("contents", "目录"):
            indent, title, num = len(m.group(1)), m.group(2).strip(), m.group(3)
            if pending and indent > pending_indent and not PART.match(pending) and (title[:1].islower() or not title[:1].isascii()):
                title = f"{pending} {title}"
                indent = pending_indent
            elif pending:
                part = pending
            pending = ""
            title = re.sub(r"\s*[.·…]+$", "", title)
            if not title or len(title) > 160:
                continue
            is_roman = bool(ROMAN.match(num)) and not num.isdigit()
            out.append({"title": title, "num": roman(num) if is_roman else int(num), "roman": is_roman,
                        "indent": indent, "part": part})
        elif len(ln.strip()) < 120 and _norm(ln) not in ("contents", "table of contents", "目录", "目次"):
            if pending:  # 连着两行没页码：前一行当「部」
                part = pending
            pending, pending_indent = ln.strip(), len(ln) - len(ln.lstrip())
    # 页脚（「Contents  II」之类）已在上面滤掉；去掉目录页里重复的条目
    seen, uniq = set(), []
    for e in out:
        k = (e["title"], e["num"])
        if k not in seen:
            seen.add(k)
            uniq.append(e)
    return uniq


def _core(title: str) -> str:
    """「Chapter I: The MU-puzzle」→ 冒号后的部分；中文「第一章 起源」→ 去掉章号。"""
    t = re.sub(r"^(chapter|part|book|section|lecture)\s+[\w.]+\s*[:.\-—]?\s*", "", title, flags=re.I)
    t = re.sub(r"^第\s*[\d一二三四五六七八九十百零〇两]+\s*[章节部篇讲回卷]\s*[:：.、]?\s*", "", t)
    if ":" in t and len(t.split(":", 1)[1].strip()) > 3:
        t = t.split(":", 1)[1]
    return _norm(t)[:60]


def _hit(title: str, page: str) -> bool:
    core = _core(title)
    if len(core) < 3:
        return False
    head = _norm(page[:700])
    return core in head or (len(core) > 24 and core[:24] in head)


def locate(entries: list[dict], pages: list[str], skip: set[int] = frozenset()) -> list[dict]:
    """给每条目录找到 PDF 页（0 起）。阿拉伯页码求一个全局偏移（最多命中者胜）再逐条 ±3 微调；罗马页码在前置页里按标题找。"""
    nums = [e for e in entries if not e["roman"] and e["num"] is not None]
    best_off, best_n = 0, -1
    for off in range(-30, 120):
        n = sum(1 for e in nums if 0 <= e["num"] + off < len(pages) and _hit(e["title"], pages[e["num"] + off]))
        if n > best_n:
            best_off, best_n = off, n
    first_body = min((e["num"] + best_off for e in nums), default=len(pages))
    out = []
    for e in entries:
        idx, ok = None, False
        if e["roman"]:
            for i in range(0, max(0, first_body)):
                if i not in skip and _hit(e["title"], pages[i]):
                    idx, ok = i, True
                    break
        else:
            base = e["num"] + best_off
            for d in (0, 1, -1, 2, -2, 3, -3):
                if 0 <= base + d < len(pages) and _hit(e["title"], pages[base + d]):
                    idx, ok = base + d, True
                    break
            if idx is None and 0 <= base < len(pages):
                idx = base
        if idx is not None:
            out.append({**e, "page": idx, "matched": ok})
    out.sort(key=lambda e: e["page"])
    return out


def scan_headings(pages: list[str]) -> list[dict]:
    """没有目录时：正文页首的「Chapter 3 / CHAPTER III / 第三章」。"""
    out = []
    pat = re.compile(r"^\s*((chapter|part)\s+([0-9]+|[ivxlcdm]+)\b.*|第\s*[\d一二三四五六七八九十百零〇两]+\s*[章部篇])", re.I)
    for i, pg in enumerate(pages):
        head = [ln.strip() for ln in pg.strip().splitlines()[:4] if ln.strip()]
        for j, ln in enumerate(head):
            if pat.match(ln) and len(ln) < 80:
                nxt = head[j + 1] if j + 1 < len(head) and len(head[j + 1]) < 80 else ""
                out.append({"title": f"{ln} {nxt}".strip() if len(ln) < 14 else ln, "page": i, "matched": True, "part": "", "indent": 0})
                break
    return out


# ---------- 拆成章节 ----------

def est_tokens(text: str) -> int:
    cjk = len(re.findall(r"[　-鿿＀-￯]", text))
    return cjk + (len(text) - cjk) // 4


def kind_of(title: str) -> str:
    t = re.sub(r"^\W+", "", title)
    if MATTER.match(t):
        return "matter"
    if FRONT.match(t):
        return "front"
    if re.match(r"^(chapter|第\s*[\d一二三四五六七八九十百零〇两]+\s*章)", t, re.I):
        return "chapter"
    return "section"


def build_chapters(starts: list[dict], pages: list[str]) -> list[dict]:
    """[{title, page, part, indent}] → 章节表：每章 page_start..page_end（0 起，含），过长的拆成几段。
    第一章之前的封面 / 版权页不收；目录页算 matter。"""
    starts = [s for s in starts if 0 <= s["page"] < len(pages)]
    if not starts:
        starts = [{"title": f"第 {k // 30 + 1} 部分（第 {k + 1} 页起）", "page": k, "part": "", "indent": 0}
                  for k in range(0, len(pages), 30)]
    has_chapters = any(kind_of(s["title"]) == "chapter" for s in starts)
    chs: list[dict] = []
    for k, s in enumerate(starts):
        end = (starts[k + 1]["page"] - 1) if k + 1 < len(starts) else len(pages) - 1
        end = max(end, s["page"])
        kind = kind_of(s["title"])
        base = {"title": s["title"], "part": s.get("part", ""), "kind": kind,
                "level": 1 if has_chapters and kind == "section" else 0, "matched": s.get("matched", True)}
        text = "\n".join(pages[s["page"]:end + 1])
        if kind == "matter" or est_tokens(text) <= PART_TOKENS:
            chs.append({**base, "page_start": s["page"], "page_end": end})
            continue
        # 太长：按页累加切段，每段估算不超过 PART_TOKENS（单页本身超了也只能整页成段）
        segs: list[tuple[int, int]] = []
        a, acc = s["page"], 0
        for i in range(s["page"], end + 1):
            t = est_tokens(pages[i])
            if i > a and acc + t > PART_TOKENS:
                segs.append((a, i - 1))
                a, acc = i, 0
            acc += t
        segs.append((a, end))
        for j, (a, b) in enumerate(segs):
            chs.append({**base, "title": f"{s['title']}（{j + 1}/{len(segs)}）", "page_start": a, "page_end": b, "split": True})
    return chs


def detect(pdf_or_txt: Path) -> dict:
    """解析一本书：返回 {pages, chapters, method, title, author, toc_pages}。不调模型。"""
    if pdf_or_txt.suffix == ".pdf":
        pages = pdf_pages(pdf_or_txt)
        meta = pdf_meta(pdf_or_txt)
        layout = pdf_pages(pdf_or_txt, layout=True, last=TOC_SCAN_PAGES)
    else:
        pages, meta, layout = text_pages(pdf_or_txt), {"title": "", "author": "", "outline": []}, []
    method, starts, tp = "", [], []
    outline = [o for o in meta.get("outline", []) if o["level"] <= 1]
    if len(outline) >= 3:
        method = "outline"
        starts = [{"title": o["title"], "page": o["page"], "part": "", "indent": o["level"] * 4, "matched": True} for o in outline]
    if not starts and layout:
        tp = toc_pages(layout)
        ents = parse_toc(layout, tp) if tp else []
        located = locate(ents, pages, set(tp)) if len(ents) >= 3 else []
        if located and sum(e["matched"] for e in located) >= max(3, len(located) // 3):
            method, starts = "toc", located
    if not starts:
        starts = scan_headings(pages)
        method = "headings" if len(starts) >= 3 else ""
    if not method:
        starts, method = [], "fixed"
    return {"pages": pages, "chapters": build_chapters(starts, pages), "method": method, "toc_pages": tp,
            "title": meta.get("title", ""), "author": meta.get("author", "")}


def first_text_pages(pages: list[str], n: int = 25, per: int = 2500) -> str:
    return "\n\n".join(f"=== PDF 第 {i + 1} 页 ===\n{p.strip()[:per]}" for i, p in enumerate(pages[:n]) if p.strip())


# ---------- prompt ----------

RULES = ("不要调用任何工具（不读写文件、不联网），材料都在下面；只输出一个 ```json 代码块，不要别的话。"
         "全部用中文写；人名、术语首次出现写「中文（原文）」；书里的原话保留原文。")


def toc_prompt(title: str, pages_text: str) -> str:
    return (f"下面是一本书（{title or '未知书名'}）PDF 前几页的文字。找出目录，按顺序抄出每一条（含「部」「序」「附录」），"
            f"page 填目录上印的页码（数字照抄；罗马数字页码填字符串如 \"xiv\"；没有页码填 null）。找不到目录就返回空数组。\n"
            f"{RULES}\n输出：```json\n{{\"title\": \"书名\", \"author\": \"作者\", \"toc\": [{{\"title\": \"…\", \"page\": 33, \"part\": \"所属部分或空\"}}]}}\n```\n\n"
            f"{pages_text}")


def overview_prompt(book: dict, toc: str, front: str, openings: str) -> str:
    return f"""你是一位读书导师，要帮一个聪明但时间有限的读者读懂《{book['title']}》{('（' + book['author'] + '）') if book.get('author') else ''}。
先给全书导读：这本书到底在说什么、为什么写、怎么组织、该怎么读。后面每一章会另外写导读，这里要给出全书的「地图」，让每章都能挂上去。
{RULES}

输出格式：
```json
{{
  "title": "规范书名（原文 + 中文译名）",
  "author": "作者",
  "year": "首版年份（材料里没有就凭常识，不确定写空）",
  "one_line": "一句话：这本书的核心主张",
  "essence": ["全书精髓 4-6 条：每条一句结论 + 一句为什么重要"],
  "author_context": "作者是谁、写书时在做什么、为什么写这本书（2-4 句）",
  "era_context": "成书的时代与学术背景：当时在争论什么、这本书回应了谁（2-4 句）",
  "structure": "全书怎么组织：分几部分、各部分的任务、写法上的特点（如对话与章节交替）（3-6 句）",
  "threads": [{{"name": "贯穿全书的主线 / 概念", "desc": "一两句", "chapters": [章节序号]}}],
  "how_to_read": "阅读建议：先读哪些、哪些可以略读、难点在哪、需要什么预备知识（3-5 句）",
  "chapters": [{{"idx": 章节序号, "one_line": "这一章在全书里干什么（一句，≤40 字）"}}]
}}
```
threads 3-6 条；chapters 覆盖下面目录里每个非 matter 的条目，idx 照抄目录里的序号。

## 目录（序号 · 类型 · 标题 · PDF 页）
{toc}

## 前言 / 导论 / 作者自述（节选）
{front or '（无）'}

## 各章开头（每章前几百字）
{openings}
"""


def chapter_prompt(book: dict, ch: dict, book_map: str, prior: str, text: str) -> str:
    seg = "（这是长章节拆出的一段；只讲这一段，开头结尾和前后段接上）" if ch.get("split") else ""
    kind = {"front": "前言 / 导论", "chapter": "正文章节", "section": "篇章（可能是对话、插曲或小节）"}.get(ch["kind"], "篇章")
    return f"""你是一位会讲故事的读书导师，正在陪读者一起读《{book['title']}》。现在读第 {ch['idx']} 篇「{ch['title']}」（{kind}）{seg}。
读者手边就是原文。你的任务是「伴读」：顺着作者原文的推进，一段一段讲给他听——像坐在旁边边翻书边聊，而不是交一份要点提纲。
{RULES}

怎么讲：
- 跟着原文的顺序和逻辑走：作者先抛出什么、怎么举例、在哪转折、最后落到哪。讲作者「为什么这样写」，不只是「写了什么」。
- 口语一点，像跟朋友聊天：可以用「你看」「这里有意思的是」「作者绕了个弯」这类说法；少用排比和条目，用连贯的段落。
- 段与段要有衔接：每段第一句接住上一段（「刚才说到……，那接下来作者就要回答……」），让人读着像一个完整的故事。
- 关键处引一句原文（照抄），再用大白话解释它。背景知识（历史、人物、学科常识）在用到的地方顺手讲，材料没有的可凭常识补，但别编造细节。
- 别注水：每段都要让读者对原文多懂一点。

输出格式：
```json
{{
  "one_line": "一句话：这一章在说什么（≤50 字）",
  "opening": "开场（1-2 段，口语）：上一章说到哪了、这一章要解决什么问题、读之前需要知道的一点背景，自然地引到第一段原文",
  "walk": [{{"title": "这一段的小标题（原书有小标题就用原标题，没有就自拟，短）",
             "anchor": "这一段原文开头的前 6-10 个词（必须逐字照抄正文，用来在原文里定位和切分）",
             "talk": "就着这段原文讲（2-4 个自然段，用 \\n\\n 分段）：第一句承接上一段，然后顺着作者的思路讲清楚",
             "quote": "这一段最值得细品的一句原文（照抄，≤40 词；没有就空）"}}],
  "closing": "收尾（1-2 段，口语）：回头看这一章到底立住了什么，它在全书里起什么作用，再顺势勾一下下一章",
  "essence": [{{"point": "带走的一句话（本章精髓，≤40 字）", "quote": "对应原文短句（可空）"}}],
  "terms": [{{"term": "关键术语（原文）", "explain": "一句话解释"}}],
  "questions": ["读完可以自问的 2-3 个问题（考理解，不考记忆）"],
  "summary_for_next": "给后续章节导读用的本章摘要（3-5 句，写清引入的概念和结论）"
}}
```
walk 按正文顺序 4-8 段，第一段的 anchor 就是正文开头，连起来覆盖全章；essence 恰好 3 条；terms 0-6 个。
对话 / 寓言类篇章：按情节推进分段，边讲情节边点破它在隐喻什么。

## 全书地图
{book_map}

## 前情（前面各章摘要）
{prior or '（这是开篇）'}

## 本章正文（PDF 第 {ch['page_start'] + 1}-{ch['page_end'] + 1} 页）
{text}
"""


def guide_md(g: dict) -> str:
    """单章导读 → markdown（给知识库和对话上下文用；页面直接用 JSON 渲染）。旧版是分节卡片，新版是顺着原文的伴读。"""
    if not g.get("walk"):
        return _guide_md_v1(g)
    lines = [f"> {g.get('one_line', '')}", "", g.get("opening", ""), ""]
    for w in g["walk"]:
        lines += [f"## {w.get('title', '')}", w.get("talk", "")] + ([f"> {w['quote']}"] if w.get("quote") else []) + [""]
    lines += ["## 收尾", g.get("closing", ""), "", "## 带走三句话"]
    lines += [f"{i}. {e.get('point', '')}" for i, e in enumerate(g.get("essence") or [], 1)]
    if g.get("terms"):
        lines += ["", "## 术语"] + [f"- **{t.get('term', '')}**：{t.get('explain', '')}" for t in g["terms"]]
    if g.get("questions"):
        lines += ["", "## 读完自问"] + [f"- {q}" for q in g["questions"]]
    return "\n".join(lines)


def _guide_md_v1(g: dict) -> str:
    c = g.get("context") or {}
    lines = [f"> {g.get('one_line', '')}", "", "## 来龙去脉",
             f"- **为什么在这里**：{c.get('why_here', '')}", f"- **背景**：{c.get('background', '')}", f"- **前置概念**：{c.get('prereq', '')}",
             "", "## 精髓"]
    lines += [f"{i}. **{e.get('point', '')}** —— {e.get('why', '')}" + (f"\n   > {e['quote']}" if e.get("quote") else "")
              for i, e in enumerate(g.get("essence") or [], 1)]
    lines += ["", "## 分节导读"]
    for s in g.get("sections") or []:
        lines += [f"### {s.get('title', '')}", s.get("summary", ""), f"- 来龙去脉：{s.get('origin', '')}", f"- 精髓：{s.get('essence', '')}", ""]
    if g.get("terms"):
        lines += ["## 术语"] + [f"- **{t.get('term', '')}**：{t.get('explain', '')}" for t in g["terms"]] + [""]
    lk = g.get("links") or {}
    if lk:
        lines += ["## 前后呼应", f"- 呼应前文：{lk.get('back', '')}", f"- 伏笔：{lk.get('forward', '')}", ""]
    if g.get("questions"):
        lines += ["## 读完自问"] + [f"- {q}" for q in g["questions"]]
    return "\n".join(lines)


def save_json(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False), "utf-8")
