"""信息推荐「HN 精读」：读 HN 帖子的评论区，提炼成可累计的经验。

每帖提炼（写进 feed_items.extra.hn）：
- tldr：讨论一句话（大家怎么看、争议在哪）
- links：评论里推荐 / 引用的网址（博客、视频、仓库、产品、论文…），只保留评论原文里真出现过的 URL，提及次数按原文数
- entities：提到的技术 / 产品 / 公司 / 工具，及评论对它的评价倾向（pos / neg / mixed / neutral）
- opinions：主要观点和判断（主流 / 反对 / 少数 / 补充），大约几条评论持这个观点
- experiences：亲身经验（谁、做了什么、结果或教训）
每条都带来源评论 id（cids），页面上能点回原评论。

只给评论数 ≥ min_comments 的帖子按分数从高到低每次最多 top 帖；已提炼过且评论没明显变多的跳过（hn_src 记提炼时的评论数）。
评论走 HN Algolia items 接口（一次拿整棵树），顶层顺序用官方 Firebase 接口的 kids（HN 自己的排序）。
模型走 DeepSeek（同 _feed_gist），失败只记错误，不影响采集和排序。
"""
from __future__ import annotations

import html
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

import httpx

from ._feed_gist import fit

ALGOLIA = "https://hn.algolia.com/api/v1/items/{}"
FIREBASE = "https://hacker-news.firebaseio.com/v0/item/{}.json"
TIMEOUT = httpx.Timeout(120.0, connect=10.0)
MAX_INPUT = 80_000       # 喂给模型的评论总字符数（约 2 万 token）；按 HN 排序先放靠前的讨论串
MAX_COMMENT = 1_200      # 单条评论截断
MAX_DEPTH = 4            # 讨论串最多读几层
WORKERS = 4
LINK_KINDS = ("博客", "视频", "仓库", "产品", "论文", "文档", "讨论", "其他")
ENTITY_KINDS = ("技术", "产品", "公司", "工具", "其他")
SENTIMENTS = ("pos", "neg", "mixed", "neutral")
STANCES = ("主流", "反对", "少数", "补充")
SKIP_HOSTS = ("news.ycombinator.com",)   # 指回 HN 自己的链接不算推荐

SYSTEM = (
    "你是技术社区编辑，帮读者从 Hacker News 评论区里提炼可积累的经验。给你一个帖子和它的评论（每条带 [c<id>] 编号），"
    "用中文输出 JSON：\n"
    "{\n"
    '  "tldr": "讨论一句话：大家主要怎么看、分歧在哪（≤80 字）",\n'
    '  "links": [{"url": "评论原文里出现的完整 URL", "kind": "博客|视频|仓库|产品|论文|文档|讨论|其他", '
    '"title": "它是什么（≤20 字）", "why": "评论为什么提到 / 推荐它（≤40 字）", "cids": [评论 id]}],\n'
    '  "entities": [{"name": "技术 / 产品名，保留原文", "kind": "技术|产品|公司|工具|其他", '
    '"sentiment": "pos|neg|mixed|neutral", "note": "评论对它的评价要点（≤40 字）", "cids": [评论 id]}],\n'
    '  "opinions": [{"stance": "主流|反对|少数|补充", "claim": "观点或判断（≤60 字）", '
    '"n": 大约几条评论持这个观点（整数）, "cids": [代表性评论 id]}],\n'
    '  "experiences": [{"who": "评论者身份或背景，看不出写「评论者」", "did": "做了什么（≤50 字）", '
    '"result": "结果或教训（≤60 字）", "cids": [评论 id]}]\n'
    "}\n"
    "要求：\n"
    "- 只根据给出的评论写，不补充评论里没有的事实；links 的 url 必须是评论原文里出现过的，不要自己拼。\n"
    "- links 只收有参考价值的（推荐的文章、视频、工具、仓库、论文、产品官网等），最多 12 条；entities 最多 15 个，只收被实际讨论或评价过的；"
    "opinions 3–6 条，按支持人数从多到少；experiences 只收亲身做过的事（「我们 / 我在 X 用了 Y」），最多 8 条，没有就给空数组。\n"
    "- 专有名词保留原文，不写空话套话，不评价帖子本身好坏。"
)


# ---------- 评论 ----------

def comment_text(raw: str) -> str:
    """HN 评论的 HTML → 纯文本；<a href> 换成完整 URL（HN 会把长链接显示截断），段落换成空格。"""
    t = re.sub(r'<a\s+[^>]*href="([^"]+)"[^>]*>.*?</a>', lambda m: " " + html.unescape(m.group(1)) + " ", raw or "", flags=re.S | re.I)
    t = re.sub(r"<p>|<br\s*/?>", " ", t, flags=re.I)
    t = html.unescape(re.sub(r"<[^>]+>", "", t))
    return re.sub(r"\s+", " ", t).strip()


URL_RE = re.compile(r"https?://[^\s<>\"'()\[\]]+")


def urls_in(text: str) -> list[str]:
    out = []
    for u in URL_RE.findall(text or ""):
        u = u.rstrip(".,;:!?")
        if urlsplit(u).netloc and not any(h in u for h in SKIP_HOSTS):
            out.append(u)
    return out


def _size(node: dict) -> int:
    return 1 + sum(_size(c) for c in node.get("children") or [])


def flatten(tree: dict, top_order: list[int] | None = None) -> list[dict]:
    """评论树 → 按讨论串展开的列表 [{id, depth, author, text, replies}]。顶层按 HN 排序（top_order），
    没有时按回复数；楼中楼按回复数。删掉的 / 空的跳过（其子评论仍保留）。"""
    rank = {cid: i for i, cid in enumerate(top_order or [])}
    out: list[dict] = []

    def walk(node: dict, depth: int):
        if depth > MAX_DEPTH:
            return
        text = comment_text(node.get("text") or "")
        if text:
            out.append({"id": node.get("id"), "depth": depth, "author": node.get("author") or "",
                        "text": text[:MAX_COMMENT], "replies": _size(node) - 1})
        kids = sorted(node.get("children") or [], key=lambda c: -_size(c))
        for c in kids:
            walk(c, depth + 1)

    tops = sorted(tree.get("children") or [], key=lambda c: (rank.get(c.get("id"), len(rank)), -_size(c)))
    for c in tops:
        walk(c, 0)
    return out


def fetch_comments(oid: str, c: httpx.Client) -> list[dict]:
    r = c.get(ALGOLIA.format(oid))
    r.raise_for_status()
    tree = r.json()
    try:
        order = (c.get(FIREBASE.format(oid), timeout=10).json() or {}).get("kids") or []
    except Exception:  # noqa: BLE001  拿不到 HN 排序就按回复数
        order = []
    return flatten(tree, order)


def render(comments: list[dict], limit: int = MAX_INPUT) -> str:
    """按顺序拼成 `[c<id>] <缩进>作者：正文`，到 limit 截止。"""
    lines, n = [], 0
    for x in comments:
        ln = f"[c{x['id']}] {'  ' * x['depth']}{x['author']}：{x['text']}"
        if n + len(ln) > limit:
            break
        lines.append(ln)
        n += len(ln) + 1
    return "\n".join(lines)


# ---------- 选帖 ----------

def oid_of(it: dict) -> str:
    return str(it["id"]).split(":", 1)[-1]


def comments_of(it: dict) -> int:
    return int((it.get("extra") or {}).get("comments") or 0)


def needs(it: dict, min_comments: int = 30) -> bool:
    """评论够多、还没提炼，或提炼后评论数涨了一半以上（且至少多 30 条）。"""
    n = comments_of(it)
    if n < min_comments:
        return False
    ex = it.get("extra") or {}
    if not ex.get("hn"):
        return True
    old = int(ex.get("hn_src") or 0)
    return n >= old * 1.5 and n - old >= 30


def pick(items: list[dict], top: int = 30, min_comments: int = 30) -> list[dict]:
    hn = [it for it in items if it.get("source") == "hn" and needs(it, min_comments)]
    return sorted(hn, key=lambda it: -float(it.get("popularity") or 0))[:top]


# ---------- 提炼 ----------

def _ids(v, valid: set[int]) -> list[int]:
    out = []
    for x in v if isinstance(v, list) else [v]:
        try:
            i = int(str(x).lstrip("c"))
        except (TypeError, ValueError):
            continue
        if i in valid and i not in out:
            out.append(i)
    return out[:6]


def _norm_url(u: str) -> str:
    return re.sub(r"/+$", "", re.sub(r"^https?://(www\.)?", "", (u or "").strip())).lower()


def clean_digest(raw: dict, comments: list[dict], text: str) -> dict:
    """校验模型输出：URL 必须在评论原文里出现过（提及次数按原文数），cids 必须是真评论，枚举值不合法归到「其他」。"""
    valid = {x["id"] for x in comments}
    seen_urls: dict[str, tuple[str, int]] = {}
    for x in comments:
        for u in urls_in(x["text"]):
            k = _norm_url(u)
            url, cnt = seen_urls.get(k, (u, 0))
            seen_urls[k] = (url, cnt + 1)
    links, used = [], set()
    for l in raw.get("links") or []:
        k = _norm_url((l or {}).get("url", ""))
        if not k or k in used or k not in seen_urls:
            continue
        used.add(k)
        url, cnt = seen_urls[k]
        links.append({"url": url, "kind": l.get("kind") if l.get("kind") in LINK_KINDS else "其他",
                      "title": fit(str(l.get("title") or ""), 40), "why": fit(str(l.get("why") or ""), 80),
                      "mentions": cnt, "cids": _ids(l.get("cids"), valid)})
    ents = []
    for e in raw.get("entities") or []:
        name = str((e or {}).get("name") or "").strip()[:60]
        if not name:
            continue
        ents.append({"name": name, "kind": e.get("kind") if e.get("kind") in ENTITY_KINDS else "其他",
                     "sentiment": e.get("sentiment") if e.get("sentiment") in SENTIMENTS else "neutral",
                     "note": fit(str(e.get("note") or ""), 80), "cids": _ids(e.get("cids"), valid)})
    ops = []
    for o in raw.get("opinions") or []:
        claim = fit(str((o or {}).get("claim") or ""), 120)
        if not claim:
            continue
        try:
            n = max(0, int(o.get("n") or 0))
        except (TypeError, ValueError):
            n = 0
        ops.append({"stance": o.get("stance") if o.get("stance") in STANCES else "补充", "claim": claim, "n": n,
                    "cids": _ids(o.get("cids"), valid)})
    exps = []
    for x in raw.get("experiences") or []:
        did = fit(str((x or {}).get("did") or ""), 100)
        if not did:
            continue
        exps.append({"who": fit(str(x.get("who") or "评论者"), 40), "did": did,
                     "result": fit(str(x.get("result") or ""), 120), "cids": _ids(x.get("cids"), valid)})
    return {"tldr": fit(str(raw.get("tldr") or ""), 160), "links": links[:12], "entities": ents[:15],
            "opinions": ops[:6], "experiences": exps[:8], "read": len(text.splitlines()), "total": len(comments)}


def _payload(it: dict, text: str) -> str:
    return json.dumps({"title": it.get("title", ""), "url": it.get("url", ""), "summary": (it.get("summary") or "")[:400],
                       "points": int(float(it.get("popularity") or 0)), "comments": text}, ensure_ascii=False)


def digest_one(it: dict, *, model: str, key: str, base: str, c: httpx.Client) -> dict:
    comments = fetch_comments(oid_of(it), c)
    if not comments:
        raise ValueError("没有可读的评论")
    text = render(comments)
    r = c.post(f"{base}/chat/completions", headers={"Authorization": f"Bearer {key}"}, json={
        "model": model, "temperature": 0.2, "max_tokens": 6000,
        "thinking": {"type": "disabled"}, "response_format": {"type": "json_object"},
        "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": _payload(it, text)}]})
    r.raise_for_status()
    raw = json.loads(r.json()["choices"][0]["message"]["content"])
    return clean_digest(raw if isinstance(raw, dict) else {}, comments, text)


def generate(items: list[dict], *, model: str = "deepseek-v4-flash",
             client: httpx.Client | None = None) -> tuple[dict[str, dict], list[str]]:
    """items → ({id: digest}, errors)。每帖一次请求，并发 WORKERS，一帖失败不影响其它。"""
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not key:
        return {}, ["未配置 DEEPSEEK_API_KEY（项目根目录 .env），跳过 HN 评论提炼"]
    base = os.environ.get("DEEPSEEK_API_BASE", "https://api.deepseek.com").rstrip("/")
    own = client is None
    c = client or httpx.Client(timeout=TIMEOUT, follow_redirects=True)
    out, errors = {}, []

    def run(it):
        try:
            return it, digest_one(it, model=model, key=key, base=base, c=c), ""
        except Exception as e:  # noqa: BLE001
            return it, None, f"{it['id']}：{type(e).__name__}: {str(e)[:120]}"

    try:
        with ThreadPoolExecutor(max_workers=WORKERS) as ex:
            for it, d, err in ex.map(run, items):
                if d:
                    out[it["id"]] = d
                if err:
                    errors.append(err)
    finally:
        if own:
            c.close()
    return out, errors


# ---------- 经验库：跨帖累计 ----------

def _ent_key(name: str) -> str:
    return re.sub(r"[\s._-]+", "", name.lower())


def library(items: list[dict], q: str = "") -> dict:
    """已提炼的 HN 帖子 → 跨帖累计：技术与产品口碑、被反复推荐的链接、经验卡片。
    items 需带 id / title / date / extra.hn / extra.hn_url。q 过滤（名称、说明、帖子标题里含）。"""
    ents: dict[str, dict] = {}
    links: dict[str, dict] = {}
    exps: list[dict] = []
    ql = (q or "").lower().strip()
    posts = [it for it in items if (it.get("extra") or {}).get("hn")]
    for it in sorted(posts, key=lambda x: x.get("date") or "", reverse=True):
        d, hn_url = it["extra"]["hn"], it["extra"].get("hn_url", "")
        post = {"id": it["id"], "title": it["title"], "hn_url": hn_url, "date": (it.get("date") or "")[:10]}
        for e in d.get("entities") or []:
            g = ents.setdefault(_ent_key(e["name"]), {"name": e["name"], "kind": e["kind"], "posts": 0,
                                                       "pos": 0, "neg": 0, "mixed": 0, "neutral": 0, "notes": []})
            g["posts"] += 1
            g[e["sentiment"]] += 1
            g["notes"].append({**post, "sentiment": e["sentiment"], "note": e["note"], "cids": e.get("cids") or []})
        for l in d.get("links") or []:
            g = links.setdefault(_norm_url(l["url"]), {"url": l["url"], "kind": l["kind"], "title": l["title"],
                                                        "posts": 0, "mentions": 0, "whys": []})
            g["posts"] += 1
            g["mentions"] += int(l.get("mentions") or 1)
            g["whys"].append({**post, "why": l["why"], "cids": l.get("cids") or []})
        for x in d.get("experiences") or []:
            exps.append({**x, "post": post})

    def hit(*texts) -> bool:
        return not ql or any(ql in (t or "").lower() for t in texts)

    ent_list = [g for g in ents.values() if hit(g["name"], *[n["note"] for n in g["notes"]], *[n["title"] for n in g["notes"]])]
    link_list = [g for g in links.values() if hit(g["url"], g["title"], *[w["why"] for w in g["whys"]], *[w["title"] for w in g["whys"]])]
    exp_list = [x for x in exps if hit(x["who"], x["did"], x["result"], x["post"]["title"])]
    ent_list.sort(key=lambda g: (-g["posts"], -(g["pos"] + g["neg"] + g["mixed"]), g["name"].lower()))
    link_list.sort(key=lambda g: (-g["posts"], -g["mentions"]))
    return {"posts": len(posts), "entities": ent_list, "links": link_list, "experiences": exp_list}
