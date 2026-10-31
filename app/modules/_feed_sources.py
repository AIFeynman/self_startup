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


def fetch_hn(queries: list[str], days: int = 7, min_points: int = 30, per_query: int = 30) -> list[dict]:
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


def fetch_github(queries: list[str], days: int = 14, min_stars: int = 30, per_query: int = 20) -> list[dict]:
    since = _days_ago(days).strftime("%Y-%m-%d")
    headers = {"Accept": "application/vnd.github+json"}
    tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    out: dict[str, dict] = {}
    with _client() as c:
        for q in queries:
            r = c.get("https://api.github.com/search/repositories", headers=headers, params={
                "q": f"{q} in:name,description,topics created:>{since} stars:>={min_stars}",
                "sort": "stars", "order": "desc", "per_page": per_query})
            r.raise_for_status()
            for it in r.json().get("items", []):
                name = it.get("full_name")
                if not name:
                    continue
                out[name] = {
                    "id": f"github:{name}", "source": "github", "type": "repo", "title": name,
                    "summary": clean(it.get("description") or ""), "url": it.get("html_url") or f"https://github.com/{name}",
                    "date": it.get("created_at", ""), "popularity": float(it.get("stargazers_count") or 0),
                    "extra": {"language": it.get("language") or "", "topics": (it.get("topics") or [])[:6], "query": q}}
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
            "popularity": 0.0, "extra": {"feed": feed_title, "feed_url": feed_url}})
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


def fetch_reddit(subs: list[str], limit: int = 15) -> tuple[list[dict], list[str]]:
    """每个子版块先试公开 JSON（有票数），被 403 时回退 RSS（无票数）。"""
    items, errors = [], []
    use_json = True
    with _client() as c:
        for i, sub in enumerate(subs):
            if i:
                time.sleep(3)  # reddit 对匿名请求限流很紧
            try:
                r = c.get(f"https://www.reddit.com/r/{sub}/top.json", params={"t": "week", "limit": limit}) if use_json else None
                if r is not None and r.status_code == 403:
                    use_json = False  # 本机 IP 被挡，后面的子版块直接走 RSS，省请求
                if r is not None and r.status_code == 200 and r.headers.get("content-type", "").startswith("application/json"):
                    for ch in r.json().get("data", {}).get("children", []):
                        d = ch.get("data") or {}
                        if not d.get("id") or d.get("stickied"):
                            continue
                        items.append({
                            "id": f"reddit:{d['id']}", "source": "reddit", "type": "discussion",
                            "title": clean(d.get("title"), 200), "summary": clean(d.get("selftext") or ""),
                            "url": "https://www.reddit.com" + (d.get("permalink") or ""),
                            "date": _iso(datetime.fromtimestamp(d.get("created_utc") or 0, timezone.utc)),
                            "popularity": float(d.get("score") or 0),
                            "extra": {"subreddit": sub, "comments": d.get("num_comments") or 0}})
                    continue
                rss_url = f"https://www.reddit.com/r/{sub}/top/.rss"
                r = c.get(rss_url, params={"t": "week", "limit": limit})
                if r.status_code == 429:
                    time.sleep(5)
                    r = c.get(rss_url, params={"t": "week", "limit": limit})
                r.raise_for_status()
                for it in parse_feed(r.text, source="reddit", typ="discussion", days=0, limit=limit):
                    m = re.search(r"/comments/([a-z0-9]+)/", it["url"])
                    if m:
                        it["id"] = f"reddit:{m.group(1)}"
                    # RSS 正文是「submitted by /u/x [link] [comments]」之类，去掉这些尾巴
                    it["summary"] = clean(re.sub(r"submitted by\s+/u/\S+.*$", "", it["summary"]))
                    it["extra"] = {"subreddit": sub, "via": "rss"}
                    items.append(it)
            except Exception as e:  # noqa: BLE001
                errors.append(f"r/{sub}: {type(e).__name__}: {str(e)[:120]}")
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
    head = text.split(". ")[0] if text else ("分享了链接 " + urlsplit(links[0]).netloc if links else "发布了长文 / 媒体")
    summary = text
    q = tw.get("quoted_tweet") or {}
    if q.get("text"):
        summary += f" ｜ 引用 @{(q.get('author') or {}).get('userName', '')}：{_TCO.sub('', q['text'])}"
    return {
        "id": f"twitter:{tid}", "source": "twitter", "type": "discussion",
        "title": clean(f"@{user}：{head}", 140), "summary": clean(summary),
        "url": tw.get("url") or f"https://x.com/{user}/status/{tid}", "date": _iso(_x_time(tw.get("createdAt"))),
        "popularity": float(tw.get("likeCount") or 0),
        "extra": {"author": user, "name": a.get("name") or "", "followers": a.get("followers") or 0,
                  "retweets": tw.get("retweetCount") or 0, "replies": tw.get("replyCount") or 0,
                  "views": tw.get("viewCount") or 0, "links": links[:3], "via": via}}


def fetch_x(accounts: list[str], queries: list[str], days: int = 3, min_likes: int = 100,
            per_account: int = 2) -> tuple[list[dict], list[str]]:
    """名单账号：每人最近一页里 days 天内、≥min_likes 赞的原创推文取前 per_account 条；搜索词：days 天内全取。
    每个账号 / 搜索词一次请求（GetXAPI 约 $0.001/次）。"""
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
            got = [g for g in got if X_SEARCH_RE.search(f"{g['title']} {g['summary']}")]
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
