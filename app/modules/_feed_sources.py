"""信息推荐的采集器：每个来源一个函数，返回统一形状的 dict 列表；失败抛异常，由调用方按来源记录。

统一形状：{id: "source:external_id", source, type, title, summary(≤400), url, date, popularity, extra{}}
type: paper / blog / podcast / product / repo / discussion / news
不调 LLM；接口密钥从环境变量读（项目根目录 .env，见 settings.load_env）。
"""
from __future__ import annotations

import html
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from hashlib import sha1
from urllib.parse import urljoin, urlsplit, urlunsplit

import feedparser
import httpx

UA = "self-startup-feed/0.1 (local learning platform)"
TIMEOUT = httpx.Timeout(15.0, connect=8.0)
SUMMARY_MAX = 400

BROWSER_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"
# X 搜索结果不在名单里，要求更强的 AI 词（单个 agent / assistant / model 常是体育经纪人、执法人员之类）
X_SEARCH_RE = re.compile(r"\b(ai|llms?|gpt[\w.-]*|claude|anthropic|openai|codex|gemini|deepseek|qwen|mcp|"
                         r"(ai|coding|llm) agents?|agentic|prompt|fine-?tun\w*|inference|transformers?)\b", re.I)
AI_HINT_RE = re.compile(r"\b(ai|gpt|llms?|agents?|agentic|copilot|assistant|machine learning|generative|chatbot|neural|"
                        r"model|claude|openai|gemini|mcp|rag)\b|人工智能|大模型|智能体|混元|元宝", re.I)


def clean(text, limit: int = SUMMARY_MAX) -> str:
    t = html.unescape(re.sub(r"<[^>]+>", " ", str(text or "")))
    t = re.sub(r"\s+", " ", t).strip()
    return t if len(t) <= limit else t[: limit - 1].rstrip() + "…"


def _client() -> httpx.Client:
    return httpx.Client(timeout=TIMEOUT, headers={"User-Agent": UA}, follow_redirects=True)


def _iso(dt: datetime | None) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds") if dt else ""


def _days_ago(n: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=n)


# ---------- 直连抓取 ----------

def hn_link_summary(h: dict) -> str:
    """链接帖没有正文：给出原文站点和讨论热度，不编造内容。"""
    host = re.sub(r"^www\.", "", urlsplit(h.get("url") or "").netloc)
    parts = [f"链接到 {host}" if host else "HN 讨论帖", f"{h.get('points') or 0} 分"]
    if h.get("num_comments"):
        parts.append(f"{h['num_comments']} 条评论")
    return " · ".join(parts)


HN_ENRICH_MAX = 40   # 每次刷新最多给多少条 HN 链接帖读原文页的简介


def link_description(c: httpx.Client, url: str) -> str:
    """原文页的 og:description / description（只读 meta，不解析正文）。拿不到返回空串。"""
    try:
        r = c.get(url, headers={"User-Agent": BROWSER_UA}, timeout=8)
        if r.status_code != 200 or "html" not in r.headers.get("content-type", ""):
            return ""
        desc = clean(_meta(r.text[:200_000], "og:description", "description", "twitter:description"))
        return "" if re.match(r"^https?://\S+$", desc) else desc      # 有的站把链接本身填进 description
    except Exception:  # noqa: BLE001
        return ""


def fetch_hn(queries: list[str], days: int = 7, min_points: int = 30, per_query: int = 30,
             known_ids: set[str] | frozenset = frozenset()) -> list[dict]:
    """链接帖本身没有正文：按分数从高到低给前 HN_ENRICH_MAX 条（已入库的跳过）读原文页简介当 summary，
    读不到再退回「链接到 xx · 分 · 评论」。"""
    since = int(_days_ago(days).timestamp())
    out: dict[str, dict] = {}
    with _client() as c:
        for q in queries:
            r = c.get("https://hn.algolia.com/api/v1/search", params={
                "query": q, "tags": "story", "hitsPerPage": per_query,
                "numericFilters": f"created_at_i>{since},points>={min_points}"})
            r.raise_for_status()
            for h in r.json().get("hits", []):
                oid = h.get("objectID")
                if not oid or not h.get("title"):
                    continue
                hn_url = f"https://news.ycombinator.com/item?id={oid}"
                out[oid] = {
                    "id": f"hn:{oid}", "source": "hn", "type": "discussion", "title": clean(h["title"], 200),
                    "summary": clean(h.get("story_text") or "") or hn_link_summary(h), "url": h.get("url") or hn_url,
                    "date": h.get("created_at", ""), "popularity": float(h.get("points") or 0),
                    "extra": {"hn_url": hn_url, "comments": h.get("num_comments") or 0, "query": q}}
        todo = [it for it in out.values() if it["id"] not in known_ids and it["url"] != it["extra"]["hn_url"]
                and it["summary"].startswith("链接到")]
        todo = sorted(todo, key=lambda it: -it["popularity"])[:HN_ENRICH_MAX]
        with ThreadPoolExecutor(max_workers=8) as ex:
            for it, desc in zip(todo, ex.map(lambda it: link_description(c, it["url"]), todo)):
                if len(desc) >= 30:
                    it["summary"] = desc
    return list(out.values())


def fetch_hf_papers(limit: int = 50) -> list[dict]:
    with _client() as c:
        r = c.get("https://huggingface.co/api/daily_papers", params={"limit": limit})
        r.raise_for_status()
        data = r.json()
    out = []
    for d in data:
        p = d.get("paper") or {}
        pid = p.get("id")
        if not pid or not (p.get("title") or d.get("title")):
            continue
        out.append({
            "id": f"hf:{pid}", "source": "hf", "type": "paper", "title": clean(p.get("title") or d.get("title"), 200),
            "summary": clean(p.get("ai_summary") or p.get("summary") or d.get("summary")),
            "url": f"https://huggingface.co/papers/{pid}", "date": p.get("publishedAt") or d.get("publishedAt", ""),
            "popularity": float(p.get("upvotes") or 0),
            "extra": {"arxiv_url": f"https://arxiv.org/abs/{pid}", "comments": d.get("numComments") or 0,
                      "keywords": (p.get("ai_keywords") or [])[:6]}})
    return out


def fetch_alphaxiv(days: int = 14, page_size: int = 60) -> list[dict]:
    with _client() as c:
        r = c.get("https://api.alphaxiv.org/papers/v3/feed", params={
            "pageNum": 0, "pageSize": page_size, "sort": "Hot", "interval": "All time", "topics": "[]"})
        r.raise_for_status()
        papers = r.json().get("papers") or []
    cutoff = _iso(_days_ago(days))
    out = []
    for p in papers:
        pid = str(p.get("universal_paper_id") or "").strip()
        date = p.get("first_publication_date") or p.get("publication_date") or ""
        if not pid or not p.get("title") or (date and date < cutoff[:10]):
            continue
        m = p.get("metrics") or {}
        ps = p.get("paper_summary") or {}
        out.append({
            "id": f"arxiv:{pid}", "source": "arxiv", "type": "paper", "title": clean(p["title"], 200),
            "summary": clean(p.get("feed_description") or (ps.get("summary") if isinstance(ps, dict) else "") or p.get("abstract")),
            "url": f"https://arxiv.org/abs/{pid}", "date": date,
            "popularity": float(m.get("public_total_votes") or m.get("total_votes") or 0),
            "extra": {"alphaxiv_url": f"https://www.alphaxiv.org/overview/{pid}", "github_url": p.get("github_url") or "",
                      "visits": (m.get("visits_count") or {}).get("all", 0) if isinstance(m.get("visits_count"), dict) else 0}})
    return out


TRENDING_URL = "https://github.com/trending"


def parse_trending(page: str, since: str = "daily", day: str = "") -> list[dict]:
    """GitHub Trending 页面（没有官方 API，解析 HTML）：仓库、描述、语言、总星数、这段时间新增的星。
    date 记成上榜那天（仓库的创建时间往往是几年前，用它会被当成旧内容）。"""
    day = day or datetime.now(timezone.utc).isoformat(timespec="seconds")
    unit = {"daily": "today", "weekly": "this week", "monthly": "this month"}.get(since, "today")
    out = []
    for row in page.split('class="Box-row"')[1:]:
        m = re.search(r'<h2[^>]*>\s*<a[^>]*href="/([^"/]+/[^"/]+)"', row)
        if not m:
            continue
        name = m[1]
        desc = clean(html.unescape(re.sub(r"<[^>]+>", "", (re.search(r'<p class="[^"]*col-9[^"]*">(.*?)</p>', row, re.S) or [None, ""])[1])))
        lang = (re.search(r'itemprop="programmingLanguage">([^<]+)<', row) or [None, ""])[1].strip()
        num = lambda pat: int((re.search(pat, row, re.S) or [None, "0"])[1].replace(",", ""))  # noqa: E731
        stars = num(r'href="/[^"]+/stargazers"[^>]*>.*?</svg>\s*([\d,]+)')
        gained = num(rf"([\d,]+)\s+stars {unit}")
        short = re.split(r"(?<=[.!?。！？])\s", desc, maxsplit=1)[0][:90].rstrip(" .。")
        out.append({"id": f"github:{name}", "source": "github", "type": "repo",
                    "title": f"{name.split('/', 1)[1]}：{short}" if short else name,
                    "summary": desc, "url": f"https://github.com/{name}", "date": day, "popularity": float(stars),
                    "extra": {"language": lang, "repo": name, "trending": since, "stars_gained": gained,
                              "trending_rank": len(out) + 1}})
    return out


def fetch_github_trending(since: str = "daily", languages: list[str] | None = None) -> list[dict]:
    out: dict[str, dict] = {}
    with _client() as c:
        for lang in languages or [""]:
            r = c.get(f"{TRENDING_URL}/{lang}" if lang else TRENDING_URL, params={"since": since},
                      headers={"User-Agent": "Mozilla/5.0", "Accept": "text/html"})
            r.raise_for_status()
            for it in parse_trending(r.text, since):
                out.setdefault(it["id"], it)
    return list(out.values())


def fetch_github_all(queries: list[str], *, min_stars: int = 100, trending_languages: list[str] | None = None,
                     watch_orgs: list[str] | None = None, watch_min_stars: int = 5) -> tuple[list[dict], list[str]]:
    """项目：GitHub 每日 Trending（成熟的热门项目）+ 按关键词搜最近新建的仓库（新项目）+ 重点机构的新仓库。各路失败互不影响。"""
    items: dict[str, dict] = {}
    errors = []
    for name, fn in (("search", lambda: fetch_github(queries, min_stars=min_stars)),
                     ("orgs", lambda: fetch_github_orgs(watch_orgs or [], min_stars=watch_min_stars)),
                     ("trending", lambda: fetch_github_trending("daily", trending_languages))):
        try:
            for it in fn():
                old = items.get(it["id"])
                # 两路都有：保留搜索的创建时间，叠上 Trending 的标记
                items[it["id"]] = {**old, "extra": {**old["extra"], **it["extra"]}} if old else it
        except Exception as e:  # noqa: BLE001
            errors.append(f"github {name}: {type(e).__name__}: {str(e)[:120]}")
    if errors and not items:
        raise RuntimeError(errors[0])
    return list(items.values()), errors


def _gh_headers() -> dict:
    headers = {"Accept": "application/vnd.github+json"}
    tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    return headers


def _repo_item(it: dict, **extra) -> dict:
    name = it["full_name"]
    desc = clean(it.get("description") or "")
    short = re.split(r"(?<=[.!?。！？])\s", desc, maxsplit=1)[0][:90].rstrip(" .。")
    return {
        # 只有仓库名看不出是什么：标题带上一句话描述
        "id": f"github:{name}", "source": "github", "type": "repo",
        "title": f"{name.split('/', 1)[1]}：{short}" if short else name,
        "summary": desc, "url": it.get("html_url") or f"https://github.com/{name}",
        "date": it.get("created_at", ""), "popularity": float(it.get("stargazers_count") or 0),
        "extra": {"language": it.get("language") or "", "topics": (it.get("topics") or [])[:6], **extra, "repo": name}}


def fetch_github_orgs(orgs: list[str], days: int = 14, min_stars: int = 5) -> list[dict]:
    """重点机构（DeepSeek / OpenAI / Anthropic …）最近新建的公开仓库：关键词搜索靠描述命中，大厂新项目描述常常很短，单独盯。
    min_stars 过滤大厂每天建的内部空仓库（Microsoft 两周十几个，几乎都是 0★）。"""
    cutoff = _days_ago(days)
    out, errors = [], []
    with _client() as c:
        for org in orgs:
            # /users/ 对个人账号和机构都适用（/orgs/ 只认机构），用户关注的个人作者也走这里
            r = c.get(f"https://api.github.com/users/{org}/repos", headers=_gh_headers(),
                      params={"sort": "created", "direction": "desc", "per_page": 30, "type": "owner"})
            if r.status_code != 200:
                errors.append(f"{org}: HTTP {r.status_code}")
                if r.status_code in (403, 429):
                    break   # 限流了，后面的也会失败
                continue
            for it in r.json():
                created = datetime.fromisoformat((it.get("created_at") or "1970-01-01T00:00:00Z").replace("Z", "+00:00"))
                if created < cutoff:
                    break   # 按创建时间倒序，后面的更旧
                if it.get("full_name") and not it.get("fork") and not it.get("archived") \
                        and (it.get("stargazers_count") or 0) >= min_stars:
                    out.append(_repo_item(it, watch_org=org))
    if errors and not out and len(errors) == len(orgs):
        raise RuntimeError("; ".join(errors[:3]))
    return out


def fetch_github(queries: list[str], days: int = 14, min_stars: int = 30, per_query: int = 20) -> list[dict]:
    since = _days_ago(days).strftime("%Y-%m-%d")
    headers = _gh_headers()
    out: dict[str, dict] = {}
    with _client() as c:
        for q in queries:
            r = c.get("https://api.github.com/search/repositories", headers=headers, params={
                "q": f"{q} in:name,description,topics created:>{since} stars:>={min_stars}",
                "sort": "stars", "order": "desc", "per_page": per_query})
            r.raise_for_status()
            for it in r.json().get("items", []):
                if it.get("full_name"):
                    out[it["full_name"]] = _repo_item(it, query=q)
    return list(out.values())


def parse_feed(text: str, feed_url: str = "", source: str = "blog", typ: str = "blog",
               days: int = 30, limit: int = 20) -> list[dict]:
    """解析 RSS/Atom 文本（博客与 Reddit RSS 共用）。"""
    f = feedparser.parse(text)
    feed_title = clean(f.feed.get("title", ""), 80) if getattr(f, "feed", None) else ""
    cutoff = _days_ago(days) if days else None
    out = []
    for e in f.entries[:limit * 2]:
        link, title = e.get("link") or "", e.get("title") or ""
        if not link or not title:
            continue
        tm = e.get("published_parsed") or e.get("updated_parsed")
        dt = datetime(*tm[:6], tzinfo=timezone.utc) if tm else None
        if cutoff and dt and dt < cutoff:
            continue
        body = e.get("summary") or ""
        if not body and e.get("content"):
            body = e["content"][0].get("value", "")
        ext = e.get("id") or link
        out.append({
            "id": f"{source}:{sha1(ext.encode()).hexdigest()[:12]}", "source": source, "type": typ,
            "title": clean(title, 200), "summary": clean(body), "url": link, "date": _iso(dt),
            "popularity": 0.0, "extra": {"feed": feed_title, "feed_url": feed_url, "author": clean(e.get("author") or "", 60)}})
        if len(out) >= limit:
            break
    return out


def fetch_rss(urls: list[str], days: int = 30, per_feed: int = 15, source: str = "blog",
              typ: str = "blog") -> tuple[list[dict], list[str]]:
    """并发抓多个 feed（博客 / 播客共用）；单个 feed 失败只记错误，不影响其它。返回 (items, errors)。"""
    def one(c, u):
        try:
            r = c.get(u)
            r.raise_for_status()
            return parse_feed(r.text, u, source=source, typ=typ, days=days, limit=per_feed), None
        except Exception as e:  # noqa: BLE001
            return [], f"{u}: {type(e).__name__}: {str(e)[:120]}"

    items, errors = [], []
    with _client() as c, ThreadPoolExecutor(max_workers=8) as ex:
        for got, err in ex.map(lambda u: one(c, u), urls):
            items += got
            if err:
                errors.append(err)
    return items, errors


REDDIT_OAUTH = "https://oauth.reddit.com"
REDDIT_RSS = "https://www.reddit.com"
REDDIT_GAP = 3          # 匿名 RSS 请求之间的间隔（秒）：reddit 对匿名请求限流很紧
_reddit_tok: dict = {"token": "", "exp": 0.0}


def _reddit_token(c: httpx.Client) -> str:
    """官方 OAuth（app-only，client_credentials）：.env 配 REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET 才用。
    在 https://www.reddit.com/prefs/apps 建一个 script 类型的 app 即可，免费，每分钟 100 次。没配返回空串。"""
    cid, sec = os.environ.get("REDDIT_CLIENT_ID", "").strip(), os.environ.get("REDDIT_CLIENT_SECRET", "").strip()
    if not (cid and sec):
        return ""
    if _reddit_tok["token"] and _reddit_tok["exp"] > time.time() + 60:
        return _reddit_tok["token"]
    r = c.post("https://www.reddit.com/api/v1/access_token", auth=(cid, sec), data={"grant_type": "client_credentials"})
    r.raise_for_status()
    j = r.json()
    _reddit_tok.update(token=j["access_token"], exp=time.time() + float(j.get("expires_in") or 3600))
    return _reddit_tok["token"]


def _reddit_json_item(d: dict, via: str) -> dict | None:
    if not d.get("id") or d.get("stickied") or d.get("over_18"):
        return None
    link = d.get("url_overridden_by_dest") or ""
    ex = {"subreddit": d.get("subreddit") or "", "comments": d.get("num_comments") or 0, "via": via,
          "flair": d.get("link_flair_text") or "", "upvote_ratio": d.get("upvote_ratio")}
    if link and "reddit.com" not in link and "redd.it" not in link:
        ex["link"] = link
    body = clean(d.get("selftext") or "")
    return {"id": f"reddit:{d['id']}", "source": "reddit", "type": "discussion", "title": clean(d.get("title"), 200),
            "summary": body or reddit_link_summary(link), "url": "https://www.reddit.com" + (d.get("permalink") or ""),
            "date": _iso(datetime.fromtimestamp(d.get("created_utc") or 0, timezone.utc)),
            "popularity": float(d.get("score") or 0), "extra": ex}


def reddit_link_summary(link: str) -> str:
    host = re.sub(r"^www\.", "", urlsplit(link or "").netloc)
    if not host or host.endswith(("reddit.com", "redd.it")):
        return ""
    return f"链接到 {host}"


def parse_reddit_rss(text: str, via: str, limit: int = 25) -> list[dict]:
    """Reddit 的 Atom：正文 HTML 末尾是「submitted by /u/x [link] [comments]」，[link] 指向外链（自贴就是帖子本身）。"""
    f = feedparser.parse(text)
    out = []
    for e in f.entries[:limit]:
        link, title = e.get("link") or "", e.get("title") or ""
        m = re.search(r"/comments/([a-z0-9]+)/", link)
        if not m or not title:
            continue
        raw = (e.get("content") or [{}])[0].get("value", "") or e.get("summary") or ""
        ext = re.search(r'<a href="([^"]+)">\s*\[link\]\s*</a>', raw)
        ext_url = html.unescape(ext.group(1)) if ext else ""
        body = raw.split("submitted by")[0] if "submitted by" in raw else raw
        body = clean(re.sub(r"<table>.*?</table>", " ", body, flags=re.S))
        if re.fullmatch(r"https?://\S+", body):
            body = ""
        tm = e.get("published_parsed") or e.get("updated_parsed")
        sub = next((t.get("term") for t in e.get("tags") or [] if t.get("term")), "") or \
            (re.search(r"/r/(\w+)/", link) or [None, ""])[1]
        ex = {"subreddit": sub, "via": via}
        if ext_url and "reddit.com" not in ext_url and "redd.it" not in ext_url:
            ex["link"] = ext_url
        out.append({"id": f"reddit:{m.group(1)}", "source": "reddit", "type": "discussion", "title": clean(title, 200),
                    "summary": body or reddit_link_summary(ext_url), "url": link,
                    "date": _iso(datetime(*tm[:6], tzinfo=timezone.utc) if tm else None), "popularity": 0.0, "extra": ex})
    return out


def fetch_reddit(subs: list[str], queries: list[str] = (), limit: int = 25) -> tuple[list[dict], list[str]]:
    """每个子版块本周 top + 关键词全站搜索（本周 top）。配了官方 OAuth 走 oauth.reddit.com（有票数、评论数、flair），
    否则走公开 RSS（无票数，按榜单顺序收）。搜索结果不在名单版块里，要求标题像 AI 话题。"""
    items, errors = [], []
    with _client() as c:
        try:
            tok = _reddit_token(c)
        except Exception as e:  # noqa: BLE001
            tok = ""
            errors.append(f"Reddit OAuth 取 token 失败，改走 RSS：{type(e).__name__}: {str(e)[:100]}")
        jobs = [("sub", s) for s in subs] + [("q", q) for q in queries]
        for i, (kind, arg) in enumerate(jobs):
            label = f"r/{arg}" if kind == "sub" else f"搜索「{arg}」"
            try:
                if tok:
                    path, params = (f"/r/{arg}/top", {"t": "week", "limit": limit}) if kind == "sub" else \
                        ("/search", {"q": arg, "sort": "top", "t": "week", "limit": limit, "type": "link"})
                    r = c.get(REDDIT_OAUTH + path, params={**params, "raw_json": 1},
                              headers={"Authorization": f"Bearer {tok}"})
                    r.raise_for_status()
                    got = [x for ch in r.json().get("data", {}).get("children", [])
                           if (x := _reddit_json_item(ch.get("data") or {}, "api"))]
                else:
                    if i:
                        time.sleep(REDDIT_GAP)
                    path, params = (f"/r/{arg}/top/.rss", {"t": "week", "limit": limit}) if kind == "sub" else \
                        ("/search.rss", {"q": arg, "sort": "top", "t": "week", "limit": limit})
                    r = c.get(REDDIT_RSS + path, params=params)
                    if r.status_code == 429:
                        time.sleep(REDDIT_GAP * 3)
                        r = c.get(REDDIT_RSS + path, params=params)
                    r.raise_for_status()
                    got = parse_reddit_rss(r.text, "rss", limit)
                    for n, it in enumerate(got):
                        it["extra"]["top_rank"] = n + 1     # RSS 没票数：记下在本周 top 里的名次
                if kind == "q":
                    got = [it for it in got if X_SEARCH_RE.search(it["title"]) or X_SEARCH_RE.search(it["summary"])]
                    for it in got:
                        it["extra"]["query"] = arg
                items += got
            except Exception as e:  # noqa: BLE001
                errors.append(f"{label}: {type(e).__name__}: {str(e)[:120]}")
    return items, errors


# ---------- X（Twitter）：GetXAPI 优先，twitterapi.io 兜底 ----------
# 两家响应同构（tweets[] + next_cursor，tweet 带 id/text/likeCount/author.userName）；差在路径、参数名和鉴权头。
X_PROVIDERS = [
    {"name": "getxapi", "env": "GETXAPI_KEY", "base": "https://api.getxapi.com",
     "auth": lambda k: {"Authorization": f"Bearer {k}"},
     "timeline": ("/twitter/user/tweets", lambda u: {"userName": u}),
     "search": ("/twitter/tweet/advanced_search", lambda q: {"q": q, "product": "Latest"})},
    {"name": "twitterapi.io", "env": "TWITTER_API_KEY", "base": "https://api.twitterapi.io",
     "auth": lambda k: {"X-API-Key": k},
     "timeline": ("/twitter/user/last_tweets", lambda u: {"userName": u}),
     "search": ("/twitter/tweet/advanced_search", lambda q: {"query": q, "queryType": "Latest"})},
]
_TCO = re.compile(r"\s*https://t\.co/\w+")
_X_ARTICLE = re.compile(r"(?:x|twitter)\.com/i/article/\d+")


def is_x_article(tw: dict) -> bool:
    """X 长文（Article）：twitterapi.io 的链接展开成 x.com/i/article/<id>；GetXAPI 不给展开链接，
    长文推的正文只有一个 t.co 短链（无媒体、无外链）。只做标记，不取正文。"""
    links = " ".join(str(u.get("expanded_url") or "") for u in ((tw.get("entities") or {}).get("urls") or []))
    if _X_ARTICLE.search(links) or _X_ARTICLE.search(tw.get("text") or ""):
        return True
    return bool(re.fullmatch(r"\s*https://t\.co/\w+\s*", tw.get("text") or "")) and not links and not tw.get("media")


def _x_providers() -> list[dict]:
    return [{**p, "key": os.environ[p["env"]].strip()} for p in X_PROVIDERS if os.environ.get(p["env"], "").strip()]


def _x_call(c: httpx.Client, provs: list[dict], kind: str, arg: str) -> list[dict]:
    """按顺序试 provider，第一个成功的为准；全失败抛最后一个错误。"""
    err: Exception | None = None
    for p in provs:
        path, params = p[kind]
        try:
            r = c.get(p["base"] + path, params=params(arg), headers=p["auth"](p["key"]))
            r.raise_for_status()
            j = r.json() or {}
            data = j.get("data") if isinstance(j.get("data"), dict) else {}
            return j.get("tweets") or data.get("tweets") or []
        except Exception as e:  # noqa: BLE001
            err = RuntimeError(f"{p['name']} {path}: {type(e).__name__}: {str(e)[:100]}")
    raise err or RuntimeError("no X provider")


def _x_time(s: str) -> datetime | None:
    try:
        return datetime.strptime(s or "", "%a %b %d %H:%M:%S %z %Y")
    except ValueError:
        return None


def x_item(tw: dict, via: str) -> dict | None:
    """推文 → 统一形状。转推 / 回复 / 拿不到作者的返回 None。"""
    a = tw.get("author") or {}
    user, tid = a.get("userName") or "", str(tw.get("id") or "")
    if not user or not tid or tw.get("retweeted_tweet") or tw.get("isReply"):
        return None
    text = clean(_TCO.sub("", tw.get("text") or ""), 2000)
    links = [u.get("expanded_url") for u in ((tw.get("entities") or {}).get("urls") or []) if u.get("expanded_url")]
    article = is_x_article(tw)
    links = [u for u in links if not _X_ARTICLE.search(u)]
    q = tw.get("quoted_tweet") or {}
    q_article = bool(q) and is_x_article(q)
    head = (text.split(". ")[0] if text else ARTICLE_STUB if article
            else "分享了链接 " + urlsplit(links[0]).netloc if links else "发布了图片 / 视频")
    summary = text
    if q.get("text"):
        qtext = _TCO.sub("", q["text"]).strip() or ("一篇 X 长文" if q_article else "")
        # 引用推的作者：twitterapi.io 放 author.userName，GetXAPI 放 user.screen_name
        qa = (q.get("author") or {}).get("userName") or (q.get("user") or {}).get("screen_name") or ""
        summary += f" ｜ 引用{' @' + qa if qa else ''}：{qtext}"
    return {
        "id": f"twitter:{tid}", "source": "twitter", "type": "discussion",
        "title": clean(f"@{user}：{head}", 140), "summary": clean(summary),
        "url": tw.get("url") or f"https://x.com/{user}/status/{tid}", "date": _iso(_x_time(tw.get("createdAt"))),
        "popularity": float(tw.get("likeCount") or 0),
        "extra": {"author": user, "name": a.get("name") or "", "followers": a.get("followers") or 0,
                  "retweets": tw.get("retweetCount") or 0, "replies": tw.get("replyCount") or 0,
                  "views": tw.get("viewCount") or 0, "links": links[:3], "via": via,
                  **({"x_article": "own" if article else "quoted"} if article or q_article else {})}}


ARTICLE_STUB = "发布了一篇 X 长文"
ARTICLE_MAX = 20     # 每次刷新最多给几篇 X 长文补标题


def _article_head(c: httpx.Client, tid: str) -> dict:
    """X 长文的标题和开头（twitterapi.io /twitter/article）；只取这两项，不存正文。"""
    key = os.environ.get("TWITTER_API_KEY", "").strip()
    if not key:
        return {}
    r = c.get("https://api.twitterapi.io/twitter/article", params={"tweet_id": tid}, headers={"X-API-Key": key})
    r.raise_for_status()
    a = r.json().get("article") or {}
    return {"title": clean(a.get("title"), 160), "preview": clean(a.get("preview_text"))} if a.get("title") else {}


def fetch_x(accounts: list[str], queries: list[str], days: int = 3, min_likes: int = 100,
            per_account: int = 2, known_articles: set[str] | frozenset = frozenset()) -> tuple[list[dict], list[str]]:
    """名单账号：每人最近一页里 days 天内、≥min_likes 赞的原创推文取前 per_account 条；搜索词：days 天内全取。
    每个账号 / 搜索词一次请求（GetXAPI 约 $0.001/次）。
    自己发的 X 长文另调一次 twitterapi.io 补标题和开头（known_articles 里已补过的不再调）；
    搜索来的长文补完标题后再按 AI 词过滤，补不到标题的丢掉。"""
    provs = _x_providers()
    if not provs:
        raise RuntimeError("未配置 GETXAPI_KEY / TWITTER_API_KEY（项目根目录 .env）")
    cutoff = _days_ago(days)
    jobs = [("timeline", u) for u in accounts] + [("search", q) for q in queries]

    def run(c, job):
        kind, arg = job
        try:
            got = [x_item(t, f"@{arg}" if kind == "timeline" else arg) for t in _x_call(c, provs, kind, arg)]
        except Exception as e:  # noqa: BLE001
            return [], f"{kind} {arg}: {e}"
        got = [g for g in got if g and g["date"] and g["date"] >= _iso(cutoff)]
        if kind == "search":
            # 长文推正文只有短链，先放行，补完标题后再判断
            got = [g for g in got if g["extra"].get("x_article") or X_SEARCH_RE.search(f"{g['title']} {g['summary']}")]
        if kind == "timeline":
            got = sorted((g for g in got if g["popularity"] >= min_likes), key=lambda g: -g["popularity"])[:per_account]
        return got, None

    out: dict[str, dict] = {}
    errors = []
    with _client() as c, ThreadPoolExecutor(max_workers=8) as ex:
        for got, err in ex.map(lambda j: run(c, j), jobs):
            for g in got:
                out.setdefault(g["id"], g)
            if err:
                errors.append(err)
        todo = [g for g in out.values() if g["extra"].get("x_article") == "own" and g["id"] not in known_articles]
        todo = sorted(todo, key=lambda g: -g["popularity"])[:ARTICLE_MAX]

        def enrich(g):
            try:
                return g, _article_head(c, g["id"].split(":", 1)[1]), None
            except Exception as e:  # noqa: BLE001
                return g, {}, f"article {g['id']}: {type(e).__name__}: {str(e)[:80]}"

        for g, head, err in ex.map(enrich, todo):
            if head:
                g["title"] = clean(f"@{g['extra']['author']}：{head['title']}", 160)
                g["summary"] = head["preview"]
                g["extra"]["article_title"] = head["title"]
            if err:
                errors.append(err)
    # 搜索来的长文：没补到标题，或补到了但与 AI 无关的，丢掉；名单账号发的保留
    out = {k: g for k, g in out.items() if not (
        g["extra"].get("x_article") == "own" and not g["extra"]["via"].startswith("@") and k not in known_articles
        and not (g["extra"].get("article_title") and X_SEARCH_RE.search(f"{g['title']} {g['summary']}")))}
    if errors and not out:
        raise RuntimeError(errors[0])
    return list(out.values()), errors


# ---------- Product Hunt：官方 GraphQL（client credentials），没密钥时退回公开 Atom feed ----------
PH_GRAPHQL = "https://api.producthunt.com/v2/api/graphql"
PH_QUERY = """query($after: DateTime, $first: Int!) {
  posts(order: VOTES, postedAfter: $after, first: $first) { edges { node {
    id name tagline description url website votesCount commentsCount createdAt
    topics(first: 5) { edges { node { name } } } } } } }"""


def _strip_query(url: str) -> str:
    p = urlsplit(url or "")
    return urlunsplit((p.scheme, p.netloc, p.path, "", "")) if p.netloc else url


def _ph_token(c: httpx.Client) -> str:
    tok = os.environ.get("PRODUCTHUNT_TOKEN", "").strip()
    cid = (os.environ.get("PN_API_KEY") or os.environ.get("PRODUCTHUNT_CLIENT_ID") or "").strip()
    sec = (os.environ.get("PN_API_Secret") or os.environ.get("PN_API_SECRET")
           or os.environ.get("PRODUCTHUNT_CLIENT_SECRET") or "").strip()
    if tok or not (cid and sec):
        return tok
    r = c.post("https://api.producthunt.com/v2/oauth/token",
               json={"client_id": cid, "client_secret": sec, "grant_type": "client_credentials"})
    r.raise_for_status()
    return r.json().get("access_token", "")


def fetch_producthunt(days: int = 2, first: int = 40, ai_only: bool = True) -> list[dict]:
    with _client() as c:
        tok = _ph_token(c)
        if not tok:
            r = c.get("https://www.producthunt.com/feed")
            r.raise_for_status()
            items = parse_feed(r.text, source="producthunt", typ="product", days=days, limit=first)
            return [it for it in items if not ai_only or AI_HINT_RE.search(f"{it['title']} {it['summary']}")]
        r = c.post(PH_GRAPHQL, headers={"Authorization": f"Bearer {tok}"},
                   json={"query": PH_QUERY, "variables": {"after": _iso(_days_ago(days)), "first": first}})
        r.raise_for_status()
        j = r.json()
    if j.get("errors"):
        raise RuntimeError(str(j["errors"])[:200])
    out = []
    for e in ((j.get("data") or {}).get("posts") or {}).get("edges") or []:
        n = e.get("node") or {}
        topics = [t["node"]["name"] for t in (n.get("topics") or {}).get("edges", []) if t.get("node")]
        blob = " ".join([n.get("name") or "", n.get("tagline") or "", n.get("description") or "", *topics])
        if not n.get("id") or not n.get("name") or (ai_only and not AI_HINT_RE.search(blob)):
            continue
        tagline = clean(n.get("tagline"), 160)
        out.append({
            "id": f"producthunt:{n['id']}", "source": "producthunt", "type": "product",
            "title": clean(f"{n['name']}：{tagline}" if tagline else n["name"], 200),
            "summary": clean(n.get("description") or tagline), "url": _strip_query(n.get("url") or ""),
            "date": n.get("createdAt") or "", "popularity": float(n.get("votesCount") or 0),
            "extra": {"comments": n.get("commentsCount") or 0, "topics": topics, "website": n.get("website") or ""}})
    return out


# ---------- Launch YC：列表页内嵌 Algolia 结果（含发布时间、票数、公司标签） ----------
YC_LAUNCHES = "https://www.ycombinator.com/launches"


def parse_yc_launches(page: str) -> list[dict]:
    """列表页里的 {"hits": [...]} → 统一形状（不按日期过滤）。"""
    i = page.find('{"hits"')
    if i < 0:
        return []
    hits = json.JSONDecoder().raw_decode(page[i:])[0].get("hits") or []
    out = []
    for h in hits:
        co = h.get("company") or {}
        if not h.get("id") or not h.get("title") or not h.get("slug"):
            continue
        out.append({
            "id": f"yc:{h['id']}", "source": "yc", "type": "product", "title": clean(h["title"], 200),
            "summary": clean(h.get("tagline")), "url": f"{YC_LAUNCHES}/{h['slug']}", "date": h.get("created_at") or "",
            "popularity": float(h.get("total_vote_count") or 0),
            "extra": {"feed": f"YC {co.get('batch') or ''}".strip(), "company": co.get("name") or "",
                      "website": co.get("url") or "", "topics": co.get("tags") or []}})
    return out


def fetch_yc_launches(days: int = 3, pages: int = 3, ai_only: bool = True) -> list[dict]:
    """YC 公司的产品发布（按时间倒序，每页 20 条）；翻到超出 days 为止。"""
    cutoff, out = _iso(_days_ago(days)), []
    with _client() as c:
        for p in range(1, pages + 1):
            r = c.get(YC_LAUNCHES, params={"page": p} if p > 1 else None, headers={"User-Agent": BROWSER_UA})
            r.raise_for_status()
            got = parse_yc_launches(r.text)
            if not got and p == 1:
                raise RuntimeError("Launch YC 页面里没找到 hits 数据（页面结构变了？）")
            fresh = [it for it in got if it["date"] >= cutoff]
            out += [it for it in fresh if not ai_only or
                    AI_HINT_RE.search(" ".join([it["title"], it["summary"], *it["extra"]["topics"]]))]
            if len(fresh) < len(got) or not got:
                break
    return out


# ---------- TrustMRR：在售产品（收入经支付渠道验证）；列表页 + 详情页的 Next.js RSC 数据 ----------
TRUSTMRR = "https://trustmrr.com"
_RSC_PUSH = re.compile(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)</script>', re.S)


def rsc_objects(page: str, need: str = "slug") -> list[dict]:
    """Next.js 页面内嵌的 RSC 流里所有以 {"_id": 开头、带 need 字段的对象。"""
    s = "".join(json.loads(f'"{c}"') for c in _RSC_PUSH.findall(page))
    dec, out = json.JSONDecoder(), []
    for m in re.finditer(r'\{"_id":"', s):
        try:
            o = dec.raw_decode(s[m.start():])[0]
        except ValueError:
            continue
        if isinstance(o, dict) and o.get(need):
            out.append(o)
    return out


def _usd(v) -> str:
    v = float(v or 0)
    return f"${v / 1e6:.1f}M" if v >= 1e6 else f"${v / 1e3:.1f}k" if v >= 1e4 else f"${v:,.0f}"


def trustmrr_facts(o: dict) -> dict:
    """详情页对象 → 产品分析用的事实（收入数字是支付渠道验证过的，金额单位美元）。"""
    ai = o.get("aiEnrichment") or {}
    slugs = lambda k: [x.get("slug") for x in o.get(k) or [] if isinstance(x, dict) and x.get("slug")]
    f = {"mrr": o.get("currentMrr"), "revenue_30d": o.get("currentLast30DaysRevenue"),
         "total_revenue": o.get("currentTotalRevenue"), "subscriptions": o.get("currentActiveSubscriptions"),
         "profit_margin": o.get("profitMarginLast30Days"), "growth_30d": o.get("cachedGrowth30d"),
         "asking_price": o.get("askingPrice"), "multiple": o.get("cachedMultiple"),
         "traffic_30d": o.get("trafficLast30Days"), "audience": o.get("targetAudience") or ai.get("businessType"),
         "persona": ai.get("targetPersona"), "value_prop": ai.get("valueProposition"),
         "problem": ai.get("problemSolved"), "pricing": ai.get("pricingModel"), "channels": slugs("marketingChannels"),
         "seller_note": clean(o.get("sellerMessage"), 300), "description": clean(o.get("description"), 800),
         "website": o.get("website"), "founded": (o.get("foundedDate") or "")[:10], "country": o.get("country"),
         "payment": o.get("paymentProvider")}
    return {k: v for k, v in f.items() if v not in (None, "", [])}


def revenue_line(f: dict) -> str:
    """TrustMRR 事实 → 一行收入摘要（不经模型，数字原样）。"""
    parts = []
    if f.get("mrr"):
        parts.append(f"MRR {_usd(f['mrr'])}")
    if f.get("revenue_30d") is not None:
        parts.append(f"近 30 天 {_usd(f['revenue_30d'])}")
    if f.get("growth_30d") is not None:
        parts.append(f"环比 {f['growth_30d']:+.0f}%")
    if f.get("profit_margin") is not None:
        parts.append(f"利润率 {f['profit_margin']:.0f}%")
    if f.get("subscriptions"):
        parts.append(f"{f['subscriptions']} 个付费订阅")
    if f.get("total_revenue"):
        parts.append(f"累计 {_usd(f['total_revenue'])}")
    if f.get("asking_price"):
        parts.append(f"要价 {_usd(f['asking_price'])}" + (f"（{f['multiple']:.1f}x 年收入）" if f.get("multiple") else ""))
    return "，".join(parts)


def fetch_trustmrr(days: int = 30, known: dict | None = None, detail_max: int = 30) -> tuple[list[dict], list[str]]:
    """/acquire 列表页的在售产品（最近 days 天挂牌、有收入）；没读过详情的再读 /startup/<slug> 补事实。
    known: {条目 id: 已有 extra}，已有 facts 的不再读详情页。"""
    known, cutoff, errors = known or {}, _iso(_days_ago(days)), []
    with _client() as c:
        c.headers["User-Agent"] = BROWSER_UA
        r = c.get(f"{TRUSTMRR}/acquire")
        r.raise_for_status()
        rows = {o["slug"]: o for o in rsc_objects(r.text) if "askingPrice" in o}
        if not rows:
            raise RuntimeError("acquire 页面里没找到在售产品数据（页面结构变了？）")
        items = []
        for o in rows.values():
            listed = o.get("firstListedForSaleAt") or o.get("createdAt") or ""
            if o.get("stealthMode") or not (o.get("currentLast30DaysRevenue") or 0) > 0 or listed < cutoff:
                continue
            iid, old = f"trustmrr:{o['slug']}", known.get(f"trustmrr:{o['slug']}") or {}
            # 列表页的数字最新、描述截断；读过详情页的保留详情里的完整描述、MRR、价值主张等
            fresh = {k: v for k, v in trustmrr_facts(o).items() if k != "description" or not old.get("facts_full")}
            facts = {**(old.get("facts") or {}), **fresh} if old.get("facts_full") else fresh
            items.append({
                "id": iid, "source": "trustmrr", "type": "product", "title": clean(o.get("name"), 200),
                "summary": clean(facts.get("description") or o.get("description")),
                "url": f"{TRUSTMRR}/startup/{o['slug']}", "date": listed,
                "popularity": float(o.get("currentLast30DaysRevenue") or 0),
                "extra": {"feed": o.get("userCategory") or "TrustMRR", "facts": facts,
                          **({"facts_full": True} if old.get("facts_full") else {})},
                "_detail": not old.get("facts_full")})

        def detail(it):
            slug = it["id"].split(":", 1)[1]
            try:
                obj = next((o for o in rsc_objects(c.get(it["url"]).text) if o.get("slug") == slug and "aiEnrichment" in o), None)
                return it, (trustmrr_facts(obj) if obj else None), None
            except Exception as e:  # noqa: BLE001
                return it, None, f"{slug}: {type(e).__name__}: {str(e)[:80]}"

        todo = [it for it in items if it["_detail"]][:detail_max]
        with ThreadPoolExecutor(max_workers=4) as ex:
            for it, facts, err in ex.map(detail, todo):
                if facts:
                    it["extra"].update(facts=facts, facts_full=True)
                    it["summary"] = clean(facts.get("description") or it["summary"])
                if err:
                    errors.append(err)
    for it in items:
        it.pop("_detail", None)
        it["extra"]["revenue"] = revenue_line(it["extra"]["facts"])
    return items, errors


# ---------- 没有 RSS 的官方站：列表页 → 文章链接 → 文章页 meta ----------

def _meta(page: str, *names: str) -> str:
    for n in names:
        n = re.escape(n)
        m = (re.search(rf'<meta[^>]+(?:property|name|itemprop)=["\']{n}["\'][^>]*content=["\']([^"\']+)', page, re.I)
             or re.search(rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]*(?:property|name|itemprop)=["\']{n}["\']', page, re.I))
        if m:
            return html.unescape(m.group(1)).strip()
    return ""


_MONTHS = "Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec"


def page_date(page: str) -> datetime | None:
    """文章页的发布日期：meta → JSON-LD → <time datetime> → 正文里第一个像日期的串；晚于当前时间的不算（正文里常有活动日期）。
    都没有返回 None。"""
    cands = [_meta(page, "article:published_time", "datePublished", "publish_date", "date", "pubdate")]
    for pat in (r'"datePublished"\s*:\s*"([^"]+)"', r'<time[^>]+datetime=["\']([^"\']+)',
                r'"dateCreated"\s*:\s*"([^"]+)"', r'"dateModified"\s*:\s*"([^"]+)"'):
        m = re.search(pat, page)
        cands.append(m.group(1) if m else "")
    text = re.sub(r"<[^>]+>", " ", re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", page, flags=re.S | re.I))
    m = re.search(rf"\b(20\d\d-\d\d-\d\d)\b|\b(({_MONTHS})[a-z]*\.? \d{{1,2}}, 20\d\d)\b|(20\d\d)年(\d{{1,2}})月(\d{{1,2}})日", text)
    if m:
        cands.append(m.group(1) or m.group(2) or f"{m.group(4)}-{int(m.group(5)):02d}-{int(m.group(6)):02d}")
    latest = datetime.now(timezone.utc) + timedelta(days=1)
    for s in cands:
        s = (s or "").strip()
        if not s:
            continue
        for parse in (lambda v: datetime.fromisoformat(v.replace("Z", "+00:00")),
                      lambda v: datetime.strptime(v[:10], "%Y-%m-%d"),
                      lambda v: datetime.strptime(re.sub(r"(\w{3})\w*\.?", r"\1", v, count=1), "%b %d, %Y")):
            try:
                d = parse(s)
            except ValueError:
                continue
            d = d if d.tzinfo else d.replace(tzinfo=timezone.utc)
            if d <= latest:
                return d
            break
    return None


def fetch_sites(sites: list[dict], known_urls: set[str] | frozenset = frozenset(), days: int = 30,
                per_site: int = 6) -> tuple[list[dict], list[str]]:
    """sites: [{name, url, link_re, ai_only?}]。已入库的文章链接（known_urls）不再读文章页。"""
    cutoff = _days_ago(days)

    def one(c, site):
        r = c.get(site["url"])
        r.raise_for_status()
        links = []
        for href in re.findall(rf"""href\s*=\s*['"]({site['link_re']})['"]""", r.text, re.I):
            u = _strip_query(urljoin(site["url"], html.unescape(href)))
            if u not in links and u.rstrip("/") != site["url"].rstrip("/"):
                links.append(u)
        out = []
        for u in links[:per_site]:
            if u in known_urls:
                continue
            page = c.get(u).text
            d = page_date(page)
            title = _meta(page, "og:title", "twitter:title") or (re.search(r"<title[^>]*>(.*?)</title>", page, re.S) or [None, ""])[1]
            summary = _meta(page, "og:description", "description", "twitter:description")
            if not d or d < cutoff or not title or (site.get("ai_only") and not AI_HINT_RE.search(f"{title} {summary}")):
                continue
            out.append({"id": f"blog:{sha1(u.encode()).hexdigest()[:12]}", "source": "blog", "type": "blog",
                        "title": clean(title, 200), "summary": clean(summary), "url": u, "date": _iso(d),
                        "popularity": 0.0, "extra": {"feed": site["name"], "feed_url": site["url"], "via": "scrape"}})
        return out

    def run(site):
        try:
            with httpx.Client(timeout=TIMEOUT, headers={"User-Agent": BROWSER_UA}, follow_redirects=True) as c:
                return one(c, site), None
        except Exception as e:  # noqa: BLE001
            return [], f"{site.get('name')}: {type(e).__name__}: {str(e)[:120]}"

    items, errors = [], []
    with ThreadPoolExecutor(max_workers=6) as ex:
        for got, err in ex.map(run, sites):
            items += got
            if err:
                errors.append(err)
    return items, errors


# ---------- 小宇宙：节目页内嵌 __NEXT_DATA__（含播放数）直读，失败再走公共 RSSHub ----------
XYZ_ID = re.compile(r"xiaoyuzhoufm\.com/podcast/([0-9a-f]{24})")
RSSHUB_BASES = ["https://rsshub.ktachibana.party", "https://rsshub.app", "https://hub.slarker.me"]


def xyz_items(pod: dict, days: int = 30, limit: int = 5) -> list[dict]:
    """__NEXT_DATA__.props.pageProps.podcast → 统一形状；popularity 取播放数。"""
    cutoff, name, out = _iso(_days_ago(days)), pod.get("title") or "", []
    for e in (pod.get("episodes") or [])[:limit * 2]:
        eid, date = e.get("eid"), _iso(datetime.fromisoformat(e["pubDate"].replace("Z", "+00:00"))) if e.get("pubDate") else ""
        if not eid or not e.get("title") or (days and date and date < cutoff):
            continue
        out.append({"id": f"xiaoyuzhou:{eid}", "source": "xiaoyuzhou", "type": "podcast", "title": clean(e["title"], 200),
                    "summary": clean(e.get("description") or e.get("shownotes")),
                    "url": f"https://www.xiaoyuzhoufm.com/episode/{eid}", "date": date,
                    "popularity": float(e.get("playCount") or 0),
                    "extra": {"feed": name, "comments": int(e.get("commentCount") or 0),
                              "minutes": int(e.get("duration") or 0) // 60}})
        if len(out) >= limit:
            break
    return out


def fetch_xiaoyuzhou(urls: list[str], days: int = 30, per_feed: int = 5,
                     rsshub_bases: list[str] | None = None) -> tuple[list[dict], list[str]]:
    """urls: 小宇宙节目页 https://www.xiaoyuzhoufm.com/podcast/<24 位 id>。"""
    def one(c, u):
        m = XYZ_ID.search(u or "")
        if not m:
            return [], f"{u}: 不是小宇宙节目页链接"
        pid, why = m.group(1), ""
        try:
            page = c.get(f"https://www.xiaoyuzhoufm.com/podcast/{pid}").text
            nd = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', page, re.S)
            pod = json.loads(nd.group(1))["props"]["pageProps"]["podcast"] if nd else {}
            if pod.get("episodes"):
                return xyz_items(pod, days, per_feed), None
            why = "节目页没有 episodes"
        except Exception as e:  # noqa: BLE001
            why = f"{type(e).__name__}: {str(e)[:80]}"
        for base in rsshub_bases or RSSHUB_BASES:    # 公共实例时好时坏，挨个试
            try:
                r = c.get(f"{base.rstrip('/')}/xiaoyuzhou/podcast/{pid}", timeout=10)
                got = parse_feed(r.text, u, source="xiaoyuzhou", typ="podcast", days=days, limit=per_feed) if r.status_code == 200 else []
            except Exception:  # noqa: BLE001
                got = []
            for it in got:
                eid = re.search(r"/episode/([0-9a-f]{24})", it["url"])
                if eid:
                    it["id"] = f"xiaoyuzhou:{eid.group(1)}"
                it["extra"]["via"] = base
            if got:
                return got, None
        return [], f"{u}: 直连失败（{why}），RSSHub 也没取到"

    items, errors = [], []
    with httpx.Client(timeout=TIMEOUT, headers={"User-Agent": BROWSER_UA}, follow_redirects=True) as c, \
            ThreadPoolExecutor(max_workers=4) as ex:
        for got, err in ex.map(lambda u: one(c, u), urls):
            items += got
            if err:
                errors.append(err)
    return items, errors


# ---------- 视频：YouTube 频道 RSS（免 key）+ YouTube Data API 关键词搜索（可选）+ B 站（经 RSSHub） ----------
YT_FEED = "https://www.youtube.com/feeds/videos.xml?channel_id={}"
YT_CHANNEL_RE = re.compile(r"\bUC[\w-]{22}\b")
YT_MIN_SECONDS = 480        # API 搜索：短于 8 分钟的（Shorts、预告、快讯）不收；有知识密度的讲解 / 访谈基本都更长
YT_LANGS = ("en", "zh")     # API 搜索只收这些语言的视频（按音频语言；没标语言的看标题文字）
# 标题里出现这些文字系统就当作不是中英文（没标音频语言时的近似）：韩文、日文假名、天城文、阿拉伯文、泰文、西里尔文
_FOREIGN_SCRIPT_RE = re.compile(r"[\uac00-\ud7af\u3040-\u30ff\u0900-\u097f\u0600-\u06ff\u0e00-\u0e7f\u0400-\u04ff]")


def _yt_item(vid: str, title: str, desc: str, date: str, views: float, channel: str, channel_id: str, via: str,
             **extra) -> dict:
    return {"id": f"youtube:{vid}", "source": "youtube", "type": "video", "title": clean(title, 200), "summary": clean(desc),
            "url": f"https://www.youtube.com/watch?v={vid}", "date": date, "popularity": float(views or 0),
            "extra": {"channel": channel, "channel_id": channel_id, "via": via,
                      "thumb": f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg", **extra}}


def parse_youtube_feed(text: str, days: int = 21, limit: int = 8) -> list[dict]:
    """频道 RSS：最近 15 条，带播放量（media:statistics views）。Shorts 的链接是 /shorts/，不收。"""
    f = feedparser.parse(text)
    channel = clean(f.feed.get("title", ""), 80) if getattr(f, "feed", None) else ""
    cutoff = _days_ago(days) if days else None
    out = []
    for e in f.entries:
        vid = e.get("yt_videoid") or ""
        if not vid or "/shorts/" in (e.get("link") or ""):
            continue
        tm = e.get("published_parsed")
        dt = datetime(*tm[:6], tzinfo=timezone.utc) if tm else None
        if cutoff and dt and dt < cutoff:
            continue
        views = (e.get("media_statistics") or {}).get("views") or 0
        out.append(_yt_item(vid, e.get("title") or "", e.get("media_description") or e.get("summary") or "", _iso(dt),
                            float(views), channel or e.get("author", ""), e.get("yt_channelid", ""), "channel"))
        if len(out) >= limit:
            break
    return out


def _iso_dur(s: str) -> int:
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", s or "")
    if not m:
        return 0
    d, h, mi, se = (int(x or 0) for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + se


def yt_lang_ok(sn: dict, langs=YT_LANGS) -> bool:
    """视频语言是否在 langs 里：先看音频语言，再看元数据语言；都没标就看标题有没有别的文字系统。"""
    lang = (sn.get("defaultAudioLanguage") or sn.get("defaultLanguage") or "").lower()
    if lang:
        return any(lang == l or lang.startswith(l + "-") for l in langs)
    return not _FOREIGN_SCRIPT_RE.search(sn.get("title") or "")


def youtube_search(c: httpx.Client, key: str, queries: list[str], days: int = 7, per_query: int = 10,
                   langs=YT_LANGS) -> list[dict]:
    """YouTube Data API v3：每个关键词取最近 days 天按播放量排的前 per_query 个，再批量补播放量和时长（search 100 配额 / 次，
    videos 1 配额 / 次；默认 4 个词每天跑 4 次 ≈ 1600，免费额度 10000 / 天）。"""
    since = _days_ago(days).strftime("%Y-%m-%dT%H:%M:%SZ")
    found: dict[str, tuple[dict, str]] = {}
    for q in queries:
        r = c.get("https://www.googleapis.com/youtube/v3/search", params={
            "key": key, "part": "snippet", "q": q, "type": "video", "order": "viewCount", "publishedAfter": since,
            "maxResults": per_query})
        r.raise_for_status()
        for it in r.json().get("items", []):
            vid = (it.get("id") or {}).get("videoId")
            if vid and vid not in found:
                found[vid] = (it.get("snippet") or {}, q)
    out = []
    ids = list(found)
    for i in range(0, len(ids), 50):
        r = c.get("https://www.googleapis.com/youtube/v3/videos", params={
            "key": key, "part": "statistics,contentDetails,snippet", "id": ",".join(ids[i:i + 50])})
        r.raise_for_status()
        for v in r.json().get("items", []):
            sn, q = found[v["id"]]
            sn = v.get("snippet") or sn
            secs = _iso_dur((v.get("contentDetails") or {}).get("duration", ""))
            if secs and secs < YT_MIN_SECONDS or langs and not yt_lang_ok(sn, langs):
                continue
            st = v.get("statistics") or {}
            out.append(_yt_item(v["id"], sn.get("title", ""), sn.get("description", ""), sn.get("publishedAt", ""),
                                float(st.get("viewCount") or 0), sn.get("channelTitle", ""), sn.get("channelId", ""),
                                "search", query=q, duration=secs, likes=int(st.get("likeCount") or 0)))
    return out


YT_CATEGORIES = {"28": "科技", "27": "教育"}
# 热门榜 / 排行榜是全站口味（数码开箱、时政历史居多），先按标题 + 简介粗筛技术相关的，再交给价值判断
TECH_TOPIC_RE = re.compile(
    r"\b(?:AI|AGI|LLMs?|GPT|Claude|Gemini|agents?|machine learning|deep learning|neural|transformers?|GPUs?|CUDA|"
    r"algorithms?|programming|coding|code|software|compilers?|math(?:ematics)?|robot(?:s|ics)?|open[- ]source|"
    r"computer science|data science|python|rust)\b"
    r"|人工智能|大模型|模型|智能体|算法|编程|程序员?|代码|计算机|芯片|显卡|机器学习|深度学习|神经网络|数学|机器人|开源|软件|"
    r"量子计算|自动驾驶|具身智能|操作系统", re.I)


def tech_topic(it: dict) -> bool:
    return bool(TECH_TOPIC_RE.search(f"{it.get('title', '')} {(it.get('summary') or '')[:600]}"))
BILI_BOARDS = {"knowledge": "知识区", "tech": "科技区"}


def youtube_trending(c: httpx.Client, key: str, categories=("28", "27"), region: str = "US", per_cat: int = 25,
                     langs=YT_LANGS) -> list[dict]:
    """YouTube 热门榜（videos chart=mostPopular，1 配额 / 次）：按分类取，过滤语言和时长，记下榜上名次。"""
    out = []
    for cat in categories:
        r = c.get("https://www.googleapis.com/youtube/v3/videos", params={
            "key": key, "part": "snippet,statistics,contentDetails", "chart": "mostPopular",
            "videoCategoryId": cat, "regionCode": region, "maxResults": per_cat})
        if r.status_code == 404:   # 该地区没有这个分类的榜
            continue
        r.raise_for_status()
        for n, v in enumerate(r.json().get("items", []), 1):
            sn = v.get("snippet") or {}
            secs = _iso_dur((v.get("contentDetails") or {}).get("duration", ""))
            if secs and secs < YT_MIN_SECONDS or langs and not yt_lang_ok(sn, langs):
                continue
            st = v.get("statistics") or {}
            out.append(_yt_item(v["id"], sn.get("title", ""), sn.get("description", ""), sn.get("publishedAt", ""),
                                float(st.get("viewCount") or 0), sn.get("channelTitle", ""), sn.get("channelId", ""),
                                "trending", board=f"YouTube {YT_CATEGORIES.get(str(cat), cat)}热门", rank=n,
                                duration=secs, likes=int(st.get("likeCount") or 0)))
    return out


def _bili_fix(it: dict, **extra) -> dict:
    if m := re.search(r"(BV\w{10})", it["url"]):
        it["id"], it["url"] = f"bilibili:{m.group(1)}", f"https://www.bilibili.com/video/{m.group(1)}"
    it["extra"] = {**it["extra"], **extra}
    return it


def bilibili_ranking(c: httpx.Client, board: str, bases: list[str], days: int = 21, limit: int = 30) -> list[dict]:
    """B 站分区排行榜（经 RSSHub /bilibili/ranking/:分区）。条目顺序就是名次。"""
    name = f"B 站{BILI_BOARDS.get(board, board)}排行"
    for base in bases:
        try:
            r = c.get(f"{base.rstrip('/')}/bilibili/ranking/{board}", timeout=15)
            got = parse_feed(r.text, source="bilibili", typ="video", days=days, limit=limit) if r.status_code == 200 else []
        except Exception:  # noqa: BLE001
            got = []
        if got:
            return [_bili_fix(it, channel=it["extra"].get("author", ""), via="ranking", board=name, rank=n)
                    for n, it in enumerate(got, 1)]
    raise RuntimeError(f"{name}: RSSHub 各实例都没取到")


ZHIHU_COLUMN_RE = re.compile(r"zhuanlan\.zhihu\.com/(?!p/)([\w-]+)|^([\w-]{3,})$")


def fetch_zhihu(columns: list[str], hot: bool = True, days: int = 14, per_column: int = 8,
                rsshub_bases: list[str] | None = None) -> tuple[list[dict], list[str]]:
    """知乎：专栏文章（RSSHub /zhihu/zhuanlan/:id）+ 热榜里技术相关的问题（/zhihu/hot）。
    知乎直连要登录（403），只走 RSSHub；公共实例对知乎限流很狠，专栏挨个取、不并发。都交给 Jev 判有没有深度。"""
    bases = rsshub_bases or RSSHUB_BASES

    def get(c, path, **kw):
        for base in bases:
            try:
                r = c.get(f"{base.rstrip('/')}{path}", timeout=15)
                got = parse_feed(r.text, source="zhihu", **kw) if r.status_code == 200 else []
            except Exception:  # noqa: BLE001
                got = []
            if got:
                return got
        return None

    items, errors = [], []
    with _client() as c:
        for col in columns:
            got = get(c, f"/zhihu/zhuanlan/{col}", typ="blog", days=days, limit=per_column)
            if got is None:
                errors.append(f"知乎专栏 {col}: RSSHub 各实例都没取到")
                continue
            for it in got:
                if m := re.search(r"zhuanlan\.zhihu\.com/p/(\d+)", it["url"]):
                    it["id"] = f"zhihu:p{m.group(1)}"
                it["extra"] |= {"column": col, "channel": it["extra"].get("feed", "").replace("知乎专栏-", ""), "via": "column"}
            items += got
        if hot:
            got = get(c, "/zhihu/hot", typ="discussion", days=0, limit=50)
            if got is None:
                errors.append("知乎热榜: RSSHub 各实例都没取到")
            for n, it in enumerate(got or [], 1):
                if not tech_topic(it):
                    continue
                if m := re.search(r"zhihu\.com/question/(\d+)", it["url"]):
                    it["id"] = f"zhihu:q{m.group(1)}"
                it["extra"] |= {"via": "hot", "board": "知乎热榜", "rank": n}
                items.append(it)
    return items, errors


def fetch_videos(channels: list[str], queries: list[str] = (), bilibili: list[str] = (), days: int = 21,
                 per_channel: int = 5, rsshub_bases: list[str] | None = None,
                 langs=YT_LANGS, trending=("28", "27"), region: str = "US",
                 bili_boards=("knowledge",)) -> tuple[list[dict], list[str]]:
    """channels：YouTube 频道 id（UC 开头 24 位），关注列表里加 @handle / 频道链接时已解析成 id。
    queries / trending：配了 YOUTUBE_API_KEY 才搜 / 取热门榜（trending 是分类 id，28 科技、27 教育）。
    bilibili：B 站 UP 主 uid，经 RSSHub 取投稿；bili_boards：B 站排行榜分区（knowledge / tech …），也经 RSSHub。"""
    def chan(c, cid):
        try:
            r = c.get(YT_FEED.format(cid))
            r.raise_for_status()
            return parse_youtube_feed(r.text, days, per_channel), None
        except Exception as e:  # noqa: BLE001
            return [], f"YouTube {cid}: {type(e).__name__}: {str(e)[:100]}"

    def bili(c, uid):
        for base in rsshub_bases or RSSHUB_BASES:
            try:
                r = c.get(f"{base.rstrip('/')}/bilibili/user/video/{uid}", timeout=12)
                got = parse_feed(r.text, source="bilibili", typ="video", days=days, limit=per_channel) if r.status_code == 200 else []
            except Exception:  # noqa: BLE001
                got = []
            for it in got:
                _bili_fix(it, channel=it["extra"].get("feed", ""), uid=uid, via="rsshub")
            if got:
                return got, None
        return [], f"B 站 uid {uid}: RSSHub 各实例都没取到"

    items, errors = [], []
    with _client() as c, ThreadPoolExecutor(max_workers=6) as ex:
        for got, err in list(ex.map(lambda x: chan(c, x), channels)) + list(ex.map(lambda x: bili(c, x), bilibili)):
            items += got
            if err:
                errors.append(err)
        key = os.environ.get("YOUTUBE_API_KEY", "").strip()
        if queries and key:
            try:
                items += youtube_search(c, key, list(queries), langs=langs)
            except Exception as e:  # noqa: BLE001
                errors.append(f"YouTube 搜索: {type(e).__name__}: {str(e)[:120]}")
        if trending and key:
            try:
                items += [it for it in youtube_trending(c, key, list(trending), region=region, langs=langs)
                          if tech_topic(it)]
            except Exception as e:  # noqa: BLE001
                errors.append(f"YouTube 热门: {type(e).__name__}: {str(e)[:120]}")
        for board in bili_boards or ():
            try:
                items += [it for it in bilibili_ranking(c, board, rsshub_bases or RSSHUB_BASES, days=days)
                          if tech_topic(it)]
            except Exception as e:  # noqa: BLE001
                errors.append(str(e)[:160])
    return items, errors


def resolve_youtube_channel(text: str) -> tuple[str, str]:
    """@handle / 频道链接 / UC id → (频道 id, 频道名)。只读频道页的 meta，不调 API。"""
    t = text.strip()
    if m := YT_CHANNEL_RE.search(t):
        cid = m.group(0)
        url = YT_FEED.format(cid)
    else:
        h = re.sub(r"^(?:https?://)?(?:www\.|m\.)?youtube\.com/", "", t).strip("/")
        h = h if h.startswith(("@", "c/", "user/")) else "@" + h.lstrip("@")
        url = f"https://www.youtube.com/{h}"
    with httpx.Client(timeout=TIMEOUT, headers={"User-Agent": BROWSER_UA}, follow_redirects=True) as c:
        r = c.get(url)
        r.raise_for_status()
        if "feeds/videos.xml" in url:
            f = feedparser.parse(r.text)
            return cid, clean(f.feed.get("title", ""), 80) if getattr(f, "feed", None) else ""
        m = re.search(r'<meta itemprop="identifier" content="(UC[\w-]{22})"', r.text) or \
            re.search(r'"(?:externalId|channelId)":"(UC[\w-]{22})"', r.text)
        if not m:
            raise ValueError("频道页里没找到频道 id")
        return m.group(1), clean(_meta(r.text[:300_000], "og:title"), 80)
