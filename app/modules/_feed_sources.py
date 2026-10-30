"""信息推荐的采集器：每个来源一个函数，返回统一形状的 dict 列表；失败抛异常，由调用方按来源记录。

统一形状：{id: "source:external_id", source, type, title, summary(≤400), url, date, popularity, extra{}}
type: paper / blog / product / repo / discussion / news
不调 LLM；learn_evolve 只读打开。
"""
from __future__ import annotations

import html
import json
import os
import re
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from hashlib import sha1
from pathlib import Path

import feedparser
import httpx

UA = "self-startup-feed/0.1 (local learning platform)"
TIMEOUT = httpx.Timeout(15.0, connect=8.0)
SUMMARY_MAX = 400

LE_TYPE = {"arxiv": "paper", "hn": "discussion", "reddit": "discussion", "twitter": "discussion",
           "github": "repo", "producthunt": "product", "openrouter": "product", "yc": "product",
           "huggingface": "repo", "blog": "blog", "podcast": "blog", "youtube": "blog"}
LE_SKIP_SOURCES = {"changelog"}           # llama.cpp 构建日志之类，噪音大


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


# ---------- learn_evolve（只读） ----------

_SUMMARY_KEYS = ("summary", "abstract", "feed_description", "description", "tagline", "selftext", "text", "shownotes")
_POP_KEYS = {"arxiv": ("likes",), "hn": ("points",), "github": ("stars",), "reddit": ("score",)}


def summary_from_payload(p: dict) -> str:
    """从 learn_evolve raw payload 里挑一段简介：优先较长的摘要类字段，再看 article.description/text。"""
    if not isinstance(p, dict):
        return ""
    cands = [p.get(k) for k in _SUMMARY_KEYS]
    art = p.get("article")
    if isinstance(art, dict):
        cands += [art.get("description"), art.get("text")]
    cands = [clean(c) for c in cands if isinstance(c, str) and c.strip()]
    for c in cands:
        if len(c) >= 40:
            return c
    return cands[0] if cands else ""


def _pop_from_payload(source: str, p: dict, fallback: float) -> float:
    for k in _POP_KEYS.get(source, ()):
        if isinstance(p.get(k), (int, float)):
            return float(p[k])
    if source == "producthunt":
        rec = p.get("reception") or {}
        if isinstance(rec, dict) and isinstance(rec.get("votes"), (int, float)):
            return float(rec["votes"])
    if source == "twitter":
        m = p.get("metrics") or {}
        if isinstance(m, dict):
            return float(m.get("like_count") or m.get("likes") or 0)
    return float(fallback or 0) if source not in ("arxiv",) else 0.0  # arxiv 的 score 是复合分，不当热度


def fetch_learn_evolve(db_path: str, days: int = 30, limit: int = 400) -> list[dict]:
    """读 learn_evolve .news.db：最近 days 天（以库里最新日期为锚，避免它停更后什么都读不到）+ 所有有评分的条目。"""
    p = Path(db_path).expanduser()
    if not p.exists():
        raise FileNotFoundError(f"learn_evolve 数据库不存在：{p}")
    root = p.parent
    conn = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        latest = conn.execute("SELECT max(date) FROM items").fetchone()[0] or datetime.now().strftime("%Y-%m-%d")
        anchor = min(latest[:10], datetime.now().strftime("%Y-%m-%d"))
        since = (datetime.strptime(anchor, "%Y-%m-%d") - timedelta(days=days)).strftime("%Y-%m-%d")
        rows = conn.execute(
            "SELECT id, source, content_type, title, url, date, score, raw_path, rating, tags FROM items "
            "WHERE (date >= ? OR rating IN ('star','good','bad','skip')) AND content_type NOT LIKE '%\\_deep' ESCAPE '\\' "
            "ORDER BY (rating IS NOT NULL AND rating != '') DESC, date DESC LIMIT ?", (since, limit)).fetchall()
    finally:
        conn.close()
    out = []
    for r in rows:
        if r["source"] in LE_SKIP_SOURCES or not r["title"]:
            continue
        payload: dict = {}
        if r["raw_path"]:
            try:
                payload = json.loads((root / r["raw_path"]).read_text("utf-8"))
            except (OSError, ValueError):
                payload = {}
        url = r["url"] or ""
        if r["source"] == "hn" and isinstance(payload.get("url"), str) and payload["url"]:
            url = payload["url"]  # 原文链接；HN 讨论页放 extra
        try:
            tags = json.loads(r["tags"] or "[]")
        except ValueError:
            tags = []
        out.append({
            "id": r["id"], "source": r["source"], "type": LE_TYPE.get(r["source"], "news"),
            "title": clean(r["title"], 200), "summary": summary_from_payload(payload), "url": url,
            "date": r["date"] or "", "popularity": _pop_from_payload(r["source"], payload, r["score"]),
            "extra": {"origin": "learn_evolve", "le_rating": r["rating"] or "", "tags": tags[:6],
                      **({"hn_url": payload["hn_url"]} if payload.get("hn_url") else {})},
        })
    return out


# ---------- 直连抓取 ----------

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
                    "summary": clean(h.get("story_text") or ""), "url": h.get("url") or hn_url,
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


def fetch_rss(urls: list[str], days: int = 30, per_feed: int = 15) -> tuple[list[dict], list[str]]:
    """逐个 feed 抓；单个 feed 失败只记错误，不影响其它。返回 (items, errors)。"""
    items, errors = [], []
    with _client() as c:
        for u in urls:
            try:
                r = c.get(u)
                r.raise_for_status()
                got = parse_feed(r.text, u, days=days, limit=per_feed)
                items += got
            except Exception as e:  # noqa: BLE001
                errors.append(f"{u}: {type(e).__name__}: {str(e)[:120]}")
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
