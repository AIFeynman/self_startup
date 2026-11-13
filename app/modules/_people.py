"""人物发声：按 people.json 里的人，在 X / YouTube / 播客 / 论文 / 新闻 / B站 搜最近的发声，按人归并、汇总提醒。
只收标题、简介、链接，不转写；点「深读」时走深度学习条目（视频会取字幕或转写）。"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from functools import cache
from pathlib import Path
from urllib.parse import quote

import feedparser
import httpx

from .. import db, notify
from . import _feed_sources as src
from . import _reads

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS people_items (
    id TEXT PRIMARY KEY,
    channel TEXT NOT NULL,
    people TEXT NOT NULL,             -- JSON 数组：人物 id
    title TEXT NOT NULL,
    summary TEXT DEFAULT '',
    url TEXT DEFAULT '',
    date TEXT DEFAULT '',
    popularity REAL DEFAULT 0,
    extra TEXT DEFAULT '{}',
    first_seen TEXT,
    notified INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_people_items_seen ON people_items(first_seen);
CREATE TABLE IF NOT EXISTS people_rejected (      -- 判过「不是本人发声」的，回看窗口内不再重判
    id TEXT PRIMARY KEY,
    at TEXT
);
CREATE TABLE IF NOT EXISTS people_runs (
    channel TEXT PRIMARY KEY,
    at TEXT,
    count INTEGER DEFAULT 0,
    new INTEGER DEFAULT 0,
    errors TEXT DEFAULT '[]'
);
"""

# 渠道：名称、多少小时跑一次（YouTube 搜索 100 配额 / 次，一轮约 2000 配额，8 小时一轮；iTunes 每人一次请求，半天一轮）
CHANNELS = {"x": ("X", 3), "blog": ("博客", 6), "news": ("新闻", 6), "youtube": ("YouTube", 8), "podcast": ("播客", 12),
            "paper": ("论文", 12), "bili": ("B站", 12)}
LOOKBACK_DAYS = {"x": 2, "blog": 4, "news": 2, "youtube": 3, "podcast": 4, "paper": 5, "bili": 4}
X_CHUNK, YT_CHUNK, ARXIV_CHUNK = 6, 10, 10
# 发帖量大的账号单独一组搜：一次请求只有一页（约 20 条），同组发得多的会把别人挤掉
X_SOLO = {"musk", "marcus", "mollick", "altman", "aravind", "wang", "simonw", "lambert", "raschka", "pmarca", "clem", "amasad"}

_lock = threading.Lock()
_state: dict = {"running": False, "channels": [], "started": ""}


@cache
def people() -> list[dict]:
    return json.loads(Path(__file__).with_name("people.json").read_text(encoding="utf-8"))


def by_id() -> dict[str, dict]:
    return {p["id"]: p for p in people()}


def _init() -> None:
    db.init([SCHEMA])


def search_names(p: dict) -> list[str]:
    return list(dict.fromkeys(n for n in [p["name"], p.get("zh", "")] if n))


def is_zh(name: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", name))


@cache
def _name_res(pid: str) -> list[re.Pattern]:
    p = by_id()[pid]
    out = []
    for n in [p["name"], p.get("zh", ""), *p.get("aliases", [])]:
        if not n:
            continue
        if re.search(r"[一-鿿]", n):
            out.append(re.compile(re.escape(n)))
        else:
            out.append(re.compile(r"(?<![A-Za-z])" + re.escape(n).replace(r"\ ", r"[\s\-]+") + r"(?![A-Za-z])", re.I))
    return out


@cache
def _title_res(pid: str) -> list[re.Pattern]:
    return [re.compile(re.escape(t).replace(r"\ ", r"\s*"), re.I) for t in by_id()[pid].get("titles", [])]


def mentions(p: dict, text: str) -> bool:
    """文本里出现了这个人：名字（中英文、别名）命中，常见名还要求同时出现他的机构词；
    或者出现了只指向他的头衔（如 Anthropic CEO）。"""
    if any(r.search(text) for r in _title_res(p["id"])):
        return True
    if not any(r.search(text) for r in _name_res(p["id"])):
        return False
    if p.get("strict"):
        low = text.lower()
        return any(o.lower() in low for o in p.get("orgs", []))
    return True


def match_people(text: str, pool: list[dict] | None = None) -> list[str]:
    return [p["id"] for p in (pool or people()) if mentions(p, text)]


def _cutoff(channel: str, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    return (now - timedelta(days=LOOKBACK_DAYS[channel])).strftime("%Y-%m-%dT%H:%M:%S")


def _item(iid: str, channel: str, pids: list[str], title: str, url: str, date: str, summary: str = "",
          popularity: float = 0, **extra) -> dict:
    return {"id": iid, "channel": channel, "people": pids, "title": src.clean(title, 200), "summary": src.clean(summary),
            "url": url, "date": date, "popularity": float(popularity or 0), "extra": extra}


def _chunks(xs: list, n: int) -> list[list]:
    return [xs[i:i + n] for i in range(0, len(xs), n)]


# ---------- X：名单账号拼成 from:a OR from:b 的高级搜索，每块一次请求 ----------
X_MIN_WEIGHT = 20     # 去掉链接和 @ 后的正文长度（汉字算 2）低于这个、又没带链接的推文不收：nice、great、一个词的回复


def x_substantive(text: str, links: list[str]) -> bool:
    if links:
        return True
    body = re.sub(r"https?://\S+|@\w+", " ", text or "")
    body = re.sub(r"\s+", " ", body).strip()
    return sum(2 if is_zh(ch) else 1 for ch in body) >= X_MIN_WEIGHT
def fetch_x(pool: list[dict]) -> tuple[list[dict], list[str]]:
    provs = src._x_providers()
    if not provs:
        raise RuntimeError("未配置 GETXAPI_KEY / TWITTER_API_KEY")
    handle = {p["x"].lower(): p["id"] for p in pool if p.get("x")}
    since = _cutoff("x")
    out, errs = [], []
    loud = [h for h in sorted(handle) if handle[h] in X_SOLO]
    chunks = [[h] for h in loud] + _chunks([h for h in sorted(handle) if h not in loud], X_CHUNK)
    with src._client() as c:
        def one(hs):
            q = "(" + " OR ".join(f"from:{h}" for h in hs) + f") since:{since[:10]} -filter:replies"
            try:
                return src._x_call(c, provs, "search", q), None
            except Exception as e:  # noqa: BLE001
                return [], f"X {hs[0]}…: {e}"
        with ThreadPoolExecutor(4) as ex:
            for tweets, err in ex.map(one, chunks):
                if err:
                    errs.append(err)
                for t in tweets:
                    it = src.x_item(t, "people")
                    pid = handle.get(((t.get("author") or {}).get("userName") or "").lower())
                    if not it or not pid or (it["date"] or "") < since:
                        continue
                    if not it["extra"].get("x_article") and not x_substantive(t.get("text") or "", it["extra"].get("links") or []):
                        continue
                    out.append(_item(it["id"], "x", [pid], it["title"], it["url"], it["date"], it["summary"],
                                     it["popularity"], author=it["extra"].get("author"), links=it["extra"].get("links", []),
                                     x_article=it["extra"].get("x_article", "")))
    return out, errs


# ---------- YouTube：人名用 "A"|"B" 合并搜索，按发布时间取最近的；只留本人出镜的访谈 / 演讲 ----------
# 人物发声要收新闻台、节目方剪出的几分钟访谈片段，下限比信息推荐（8 分钟）低，只挡 Shorts；是不是本人在说交给后面的判断
MIN_SECONDS = 90
VIDEO_JUNK_RE = re.compile(r"#shorts|\bshorts?\b|AI短片|\breacts?\b|\breaction\b|compilation|\bmeme|婚外情|出轨", re.I)


# 搜索量太大的名字单独一组搜，免得把同组其他人挤出 50 条结果
SOLO = {"musk", "altman", "dario", "wang", "zuck", "jensen", "sundar", "nadella", "hinton", "feifei", "ng", "lecun"}


def yt_chunks(pool: list[dict]) -> list[list[tuple[str, dict]]]:
    solo = [[(n, p)] for p in pool if p["id"] in SOLO for n in search_names(p)]
    rest = [(n, p) for p in pool if p["id"] not in SOLO for n in search_names(p)]
    return solo + _chunks(rest, YT_CHUNK)


def trusted_channels() -> set[str]:
    from .feed import cfg
    return set(cfg("youtube_channels") or [])


def video_ok(sn: dict, secs: int, pids_in_title: list[str], trusted: set[str]) -> bool:
    title = sn.get("title") or ""
    if VIDEO_JUNK_RE.search(title) or (secs and secs < MIN_SECONDS) or not src.yt_lang_ok(sn):
        return False
    if sn.get("channelId") in trusted:
        return True
    return bool(pids_in_title)


def fetch_youtube(pool: list[dict], key: str = "") -> tuple[list[dict], list[str]]:
    key = key or src.os.environ.get("YOUTUBE_API_KEY", "").strip()
    if not key:
        raise RuntimeError("未配置 YOUTUBE_API_KEY")
    since = _cutoff("youtube") + "Z"
    cand: dict[str, tuple[dict, list[dict]]] = {}
    errs = []
    trusted = trusted_channels()
    with src._client() as c:
        for chunk in yt_chunks(pool):
            q = "|".join(f'"{n}"' for n, _ in chunk)
            try:
                for attempt in range(2):
                    r = c.get("https://www.googleapis.com/youtube/v3/search", params={
                        "key": key, "part": "snippet", "q": q, "type": "video", "order": "date", "publishedAfter": since,
                        "maxResults": 50})
                    if r.status_code != 429 or attempt:
                        break
                    time.sleep(5)
                r.raise_for_status()
            except httpx.HTTPError as e:
                errs.append(f"YouTube {chunk[0][0]}…: {type(e).__name__} {getattr(getattr(e, 'response', None), 'status_code', '')}")
                continue
            for v in r.json().get("items", []):
                vid = (v.get("id") or {}).get("videoId")
                if vid:
                    cand.setdefault(vid, (v.get("snippet") or {}, []))[1].extend(p for _, p in chunk)
        found = []
        ids = list(cand)
        for i in range(0, len(ids), 50):
            try:
                r = c.get("https://www.googleapis.com/youtube/v3/videos", params={
                    "key": key, "part": "snippet,contentDetails,statistics", "id": ",".join(ids[i:i + 50])})
                r.raise_for_status()
            except httpx.HTTPError as e:
                errs.append(f"YouTube videos: {type(e).__name__}")
                continue
            for v in r.json().get("items", []):
                sn = v.get("snippet") or cand[v["id"]][0]
                pool_here = list({p["id"]: p for p in cand[v["id"]][1]}.values())
                in_title = match_people(sn.get("title", ""), pool_here)
                pids = in_title or match_people(f"{sn.get('title', '')} {sn.get('description', '')}", pool_here)
                secs = src._iso_dur((v.get("contentDetails") or {}).get("duration", ""))
                if not pids or not video_ok(sn, secs, in_title, trusted):
                    continue
                found.append(_item(f"youtube:{v['id']}", "youtube", pids, sn.get("title", ""),
                                   f"https://www.youtube.com/watch?v={v['id']}", (sn.get("publishedAt") or "")[:19],
                                   sn.get("description", ""), float((v.get("statistics") or {}).get("viewCount") or 0),
                                   uploader=sn.get("channelTitle", ""), seconds=secs,
                                   thumb=f"https://i.ytimg.com/vi/{v['id']}/mqdefault.jpg"))
    return found, errs


# ---------- 播客：iTunes 按人名搜单集（免费、无密钥），只要最近几天发布、标题或简介里出现这个人的 ----------
def fetch_podcast(pool: list[dict], pause: float = 2.5) -> tuple[list[dict], list[str]]:
    since = _cutoff("podcast")
    found: dict[str, dict] = {}
    errs = []
    with src._client() as c:
        for i, (p, term) in enumerate((p, n) for p in pool for n in search_names(p)):
            if i and pause:
                time.sleep(pause)
            try:
                r = c.get("https://itunes.apple.com/search", params={
                    "term": term, "entity": "podcastEpisode", "limit": 200, "country": "cn" if is_zh(term) else "us"})
                r.raise_for_status()
                res = r.json().get("results", [])
            except (httpx.HTTPError, ValueError) as e:
                errs.append(f"iTunes {term}: {type(e).__name__}")
                continue
            for e in res:
                date = (e.get("releaseDate") or "")[:19]
                text = f"{e.get('trackName', '')} {e.get('description') or e.get('shortDescription') or ''}"
                if date < since or not mentions(p, text):
                    continue
                tid = e.get("trackId")
                hit = found.setdefault(f"podcast:{tid}", _item(
                    f"podcast:{tid}", "podcast", [], e.get("trackName", ""), e.get("trackViewUrl") or e.get("episodeUrl", ""),
                    date, e.get("description") or e.get("shortDescription") or "", show=e.get("collectionName", ""),
                    audio=e.get("episodeUrl", ""), seconds=int((e.get("trackTimeMillis") or 0) / 1000)))
                hit["people"] = sorted(set(hit["people"]) | {p["id"]})
    return list(found.values()), errs


# ---------- 论文：arXiv 按作者名合并查询，作者名精确对上才算 ----------
def fetch_paper(pool: list[dict], pause: float = 3.0) -> tuple[list[dict], list[str]]:
    since = _cutoff("paper")[:10]
    authors = [p for p in pool if p.get("papers") and p["name"]]
    found: dict[str, dict] = {}
    errs = []
    with src._client() as c:
        for i, chunk in enumerate(_chunks(authors, ARXIV_CHUNK)):
            if i and pause:
                time.sleep(pause)
            q = " OR ".join(f'au:"{p["name"]}"' for p in chunk)
            r = None
            for attempt in range(3):
                try:
                    r = c.get("https://export.arxiv.org/api/query", timeout=60, params={
                        "search_query": q, "sortBy": "submittedDate", "sortOrder": "descending", "max_results": 50})
                    r.raise_for_status()
                    break
                except httpx.HTTPError as e:
                    code = getattr(getattr(e, "response", None), "status_code", "")
                    r = None
                    if attempt == 2:
                        errs.append(f"arXiv {chunk[0]['name']}…: {type(e).__name__} {code}".strip())
                    elif pause:
                        time.sleep(pause * 3 * (attempt + 1))
            if r is None:
                continue
            for e in feedparser.parse(r.text).entries:
                m = re.search(r"arxiv\.org/abs/([^v\s]+)", e.get("id", ""))
                date = (e.get("published") or "")[:19]
                if not m or date[:10] < since:
                    continue
                names = {a.get("name", "").strip().lower() for a in e.get("authors", [])}
                pids = [p["id"] for p in chunk if p["name"].lower() in names]
                if pids:
                    pid = m.group(1)
                    hit = found.setdefault(pid, _item(f"arxiv:{pid}", "paper", [], e.get("title", ""),
                                                      f"https://arxiv.org/abs/{pid}", date, e.get("summary", ""),
                                                      authors=[a.get("name") for a in e.get("authors", [])][:8]))
                    hit["people"] = sorted(set(hit["people"]) | set(pids))
    return list(found.values()), errs


# ---------- 新闻：Google News RSS 按人名搜最近 1 天，标题里出现本人的都收，是不是本人发声交给 Haiku 判断 ----------
NEWS_WINDOW = "1d"


def news_url(name: str, window: str = "") -> str:
    q = quote(f'"{name}" when:{window or NEWS_WINDOW}')
    if is_zh(name):
        return f"https://news.google.com/rss/search?q={q}&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"
    return f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"


def news_items(p: dict, text: str) -> list[dict]:
    out = []
    since = _cutoff("news")
    for e in feedparser.parse(text).entries:
        title = re.sub(r"\s+-\s+[^-]+$", "", e.get("title", ""))
        tm = e.get("published_parsed")
        date = time.strftime("%Y-%m-%dT%H:%M:%S", tm) if tm else ""
        if (date and date < since) or not mentions(p, title):
            continue
        link = e.get("link", "")
        out.append(_item("news:" + hashlib.sha1(title.lower().encode()).hexdigest()[:16], "news", [p["id"]], title, link, date,
                         outlet=(e.get("source") or {}).get("title", "")))
    return out


def fetch_news(pool: list[dict]) -> tuple[list[dict], list[str]]:
    found: dict[str, dict] = {}
    errs = []
    with src._client() as c:
        def one(job):
            p, name = job
            try:
                r = c.get(news_url(name))
                r.raise_for_status()
                return news_items(p, r.text), None
            except httpx.HTTPError as e:
                return [], f"Google News {name}: {type(e).__name__}"
        with ThreadPoolExecutor(4) as ex:
            for got, err in ex.map(one, [(p, n) for p in pool for n in search_names(p)]):
                if err:
                    errs.append(err)
                for it in got:
                    hit = found.setdefault(it["id"], it)
                    hit["people"] = sorted(set(hit["people"]) | set(it["people"]))
    return list(found.values()), errs


# ---------- 博客：本人的博客 / Substack / 周报 RSS，发的就是本人的话，不用再判断 ----------
def fetch_blog(pool: list[dict]) -> tuple[list[dict], list[str]]:
    since = _cutoff("blog")
    out, errs = [], []
    with src._client() as c:
        def one(p):
            try:
                r = c.get(p["rss"], headers={"User-Agent": src.BROWSER_UA})
                r.raise_for_status()
                return p, r.text, None
            except httpx.HTTPError as e:
                return p, "", f"博客 {p['name']}: {type(e).__name__}"
        with ThreadPoolExecutor(4) as ex:
            for p, text, err in ex.map(one, [p for p in pool if p.get("rss")]):
                if err:
                    errs.append(err)
                for e in feedparser.parse(text).entries:
                    tm = e.get("published_parsed") or e.get("updated_parsed")
                    date = time.strftime("%Y-%m-%dT%H:%M:%S", tm) if tm else ""
                    link = e.get("link", "")
                    if not link or date < since:
                        continue
                    out.append(_item("blog:" + hashlib.sha1(link.encode()).hexdigest()[:16], "blog", [p["id"]], e.get("title", ""),
                                     link, date, re.sub(r"<[^>]+>", " ", e.get("summary", "")), site=p["rss"].split("/")[2]))
    return out, errs


# ---------- B站：经公共 RSSHub 按中文名搜视频（实例常不可用，失败不影响其他渠道） ----------
def fetch_bili(pool: list[dict], bases: list[str] | None = None) -> tuple[list[dict], list[str]]:
    from .feed import cfg
    bases = bases or cfg("rsshub_bases") or src.RSSHUB_BASES
    since = _cutoff("bili")
    found: dict[str, dict] = {}
    errs = []
    zh = [p for p in pool if p.get("zh")]
    with src._client() as c:
        for p in zh:
            text = None
            for b in bases:
                try:
                    r = c.get(f"{b.rstrip('/')}/bilibili/vsearch/{quote(p['zh'])}/pubdate", timeout=15)
                    if r.status_code == 200:
                        text = r.text
                        break
                except httpx.HTTPError:
                    continue
            if text is None:
                errs.append(f"B站 {p['zh']}: RSSHub 实例都不可用")
                if len(errs) >= 3 and not found:
                    errs.append("B站：连续失败，本轮跳过其余人")
                    break
                continue
            for e in feedparser.parse(text).entries:
                tm = e.get("published_parsed")
                date = time.strftime("%Y-%m-%dT%H:%M:%S", tm) if tm else ""
                if (date and date < since) or not mentions(p, f"{e.get('title', '')} {e.get('summary', '')}"):
                    continue
                link = e.get("link", "")
                m = re.search(r"(BV\w{10})", link)
                iid = f"bilibili:{m.group(1)}" if m else "bili:" + hashlib.sha1(link.encode()).hexdigest()[:16]
                hit = found.setdefault(iid, _item(iid, "bili", [], e.get("title", ""), link, date, e.get("summary", "")))
                hit["people"] = sorted(set(hit["people"]) | {p["id"]})
    return list(found.values()), errs


# ---------- 本人发声判断：规则粗筛后，YouTube / 新闻 / 播客 / B站 的新条目交给本机 Haiku 判断是不是本人在说 ----------
JUDGED = {"youtube", "news", "podcast", "bili"}
VOICE_BATCH = 30
VOICE_SYSTEM = (
    "你在帮用户发现 AI 领域人物新的原始发声。每条输入是一条新闻 / 视频 / 播客（channel 标明），以及它关联的人物（带身份）和来源（source）。\n"
    "voice=true：本人新出镜或出声的访谈、演讲、播客、发布会、听证会；本人撰文或署名论文；"
    "报道本人新说了什么、宣布了什么、他的团队新发布了什么的新闻（媒体是谁都可以，channel=news 时这类报道都算）。\n"
    "voice=false：同名的其他人；以他为话题的评论、解读、八卦、丑闻、传记、盘点；股价或公司新闻；"
    "他名下公司的项目、交易、动态（除非报道的是他本人的原话或亲自宣布）；"
    "channel 为 youtube / podcast / bili 时，source 是翻译、解读、搬运、剪辑类频道，或节目语言不是中文或英文的；Shorts、AI 配音；"
    "channel=youtube 时，只有 source 是本人或其机构的频道、请他做客的节目、活动主办方、或报道他新发言的新闻媒体才算，"
    "其他个人、教育、讲座合集、地方台重播等频道上传的演讲 / 路演 / 讲座视频（哪怕是完整原片）都算搬运；"
    "明显是旧内容的重发；多条不相关新闻的合集；只是提到名字。标题里有他的名字不代表是他在说，拿不准时判 false。\n"
    '只输出 JSON：{"items": [{"id": "<原样返回>", "voice": true 或 false}]}，每条输入都要有输出。'
)


_judge_lock = threading.Lock()


def _ask(rows: list[dict] | dict, system: str, run, model: str, retry_wait: float) -> tuple[dict[str, dict], str]:
    """把一批条目交给本机小模型，返回 ({id: 输出}, 错误)。同一时刻只跑一个（本机 Claude 并发时容易返回异常），失败等一会儿重试一次。"""
    last = ""
    for attempt in range(2):
        try:
            with _judge_lock:
                text = run(json.dumps(rows, ensure_ascii=False), system=system, model=model)["text"]
            m = re.search(r"\{.*\}", text or "", re.S)
            got = {str(x.get("id")): x for x in (json.loads(m.group(0)).get("items") or []) if isinstance(x, dict)} if m else {}
            if got:
                return got, ""
            last = f"没有解析出结果：{(text or '')[:80]!r}"
        except Exception as e:  # noqa: BLE001
            last = f"{type(e).__name__}: {str(e)[:100]}"
        if attempt == 0 and retry_wait:
            time.sleep(retry_wait)
    return {}, last


def _rows_for_model(items: list[dict]) -> list[dict]:
    idx = by_id()
    return [{"id": it["id"], "channel": it["channel"],
             "people": [idx[p]["name"] + (f"（{idx[p]['zh']}）" if idx[p].get("zh") else "") + f"，{idx[p]['role']}" for p in it["people"] if p in idx],
             "title": it["title"], "summary": it["summary"][:300],
             "source": it["extra"].get("uploader") or it["extra"].get("outlet") or it["extra"].get("show") or it["extra"].get("site") or ""}
            for it in items]


def voice_filter(items: list[dict], run, model: str = "claude-haiku-5-5", retry_wait: float = 5) -> tuple[list[dict], list[str], list[str]]:
    """返回 (本人发声的条目, 判为不是的 id, 错误)。一批仍失败的这轮不收（还在回看窗口里，下一轮会重新抓、重新判断）。"""
    keep, rejected, errs = [], [], []
    for i in range(0, len(items), VOICE_BATCH):
        batch = items[i:i + VOICE_BATCH]
        got, err = _ask(_rows_for_model(batch), VOICE_SYSTEM, run, model, retry_wait)
        if not got:
            errs.append(f"本人发声判断第 {i // VOICE_BATCH + 1} 批（{len(batch)} 条，下轮重判）：{err}")
            continue
        keep += [it for it in batch if (got.get(it["id"]) or {}).get("voice")]
        rejected += [it["id"] for it in batch if it["id"] in got and got[it["id"]].get("voice") is False]
    return keep, rejected, errs


# ---------- 新闻再筛一道：同一件事多家媒体报道只留最早一条；和 AI 认知无关的（八卦、私事、汽车销量、客套话）不收 ----------
NEWS_RECENT_DAYS = 2
NEWS_RECENT_MAX = 80
NEWS_SYSTEM = (
    "你在帮用户筛 AI 名人的新闻。输入 JSON 里 recent 是最近已经收下的新闻，items 是这一轮新来的（按时间从早到晚）。对 items 里每条给两个判断：\n"
    "worth：对理解 AI 有没有分量。true：本人关于 AI、模型、算力、科研、AI 产业和社会影响的观点、预测、判断、警告；本人宣布或确认的模型、产品、研究、合作、战略。"
    "false：私生活、婚外情、丑闻、官司、政治和社会争议表态；对某个人的客套、玩笑、夸赞或招揽（比如说请某人来工作是荣幸）；"
    "身价、股价、薪酬；和 AI 无关的业务（汽车交付与订单、火箭、社交平台运营等）；只是转述别人观点的评论文章。拿不准时判 false。\n"
    "dup_of：如果这条和 recent 里或 items 里更早的某条讲的是同一件事（同一次讲话、同一个发布、同一个表态，换了媒体、换了语言、换了标题角度都算），"
    "给出那条的 id；不是重复给 null。只能指向 recent 或本批更早的条目。\n"
    '只输出 JSON：{"items": [{"id": "<原样返回>", "worth": true 或 false, "dup_of": "<id>" 或 null}]}，每条 items 都要有输出。'
)


def _recent_news() -> list[dict]:
    since = (datetime.now() - timedelta(days=NEWS_RECENT_DAYS)).strftime("%Y-%m-%dT%H:%M:%S")
    rows = db.rows("SELECT id, title, extra FROM people_items WHERE channel='news' AND first_seen>=? AND json_extract(extra, '$.low') IS NULL "
                   "ORDER BY first_seen DESC LIMIT ?", [since, NEWS_RECENT_MAX])
    return [{"id": r["id"], "title": r["title"], "gist": json.loads(r["extra"] or "{}").get("gist", "")} for r in reversed(rows)]


def news_triage(items: list[dict], run, model: str = "claude-haiku-5-5", retry_wait: float = 5) -> tuple[list[dict], list[str], list[str]]:
    """返回 (留下的新闻, 不收的 id, 错误)。一批失败的这轮不收也不记拒绝，下一轮重判。"""
    items = sorted(items, key=lambda it: it["date"] or "")
    recent = _recent_news()
    known = {r["id"] for r in recent}
    keep, drop, errs = [], [], []
    for i in range(0, len(items), VOICE_BATCH):
        batch = items[i:i + VOICE_BATCH]
        rows = [{**r, "date": it["date"]} for r, it in zip(_rows_for_model(batch), batch)]
        got, err = _ask({"recent": recent, "items": rows}, NEWS_SYSTEM, run, model, retry_wait)
        if not got:
            errs.append(f"新闻去重第 {i // VOICE_BATCH + 1} 批（{len(batch)} 条，下轮重判）：{err}")
            continue
        for it in batch:
            x = got.get(it["id"])
            if x is None:
                continue
            if x.get("worth") is False or str(x.get("dup_of") or "") in known:
                drop.append(it["id"])
            else:
                keep.append(it)
                known.add(it["id"])
                recent.append({"id": it["id"], "title": it["title"], "gist": ""})
    return keep, drop, errs


GIST_SYSTEM = (
    "你是 AI 资讯编辑，帮读者扫一眼就知道 AI 名人这条发声讲了什么。每条输入是一条推文 / 博客 / 新闻 / 视频 / 播客 / 论文，带关联人物。\n"
    "gist：一句中文介绍，不超过 40 个汉字。先说是谁、在哪、做了什么（发帖 / 撰文 / 访谈 / 演讲 / 论文），再点出最关键的一个观点或信息；"
    "只根据给出的标题、简介、来源写，不补充、不猜测没给出的事实和数字；专有名词保留原文；不要「这条」「该推文」开头，不评价好坏。\n"
    '只输出 JSON：{"items": [{"id": "<原样返回>", "gist": "<一句话>"}]}，每条输入都要有输出。'
)
VALUE_MIN = 0.35
X_PER_PERSON_DAY = 3


def annotate(items: list[dict], run, model: str = "claude-haiku-5-5", retry_wait: float = 5) -> tuple[dict[str, str], list[str]]:
    """返回 ({id: 中文一句话}, 错误)。失败的批次这轮不写，之后补写。"""
    gists, errs = {}, []
    for i in range(0, len(items), VOICE_BATCH):
        batch = items[i:i + VOICE_BATCH]
        got, err = _ask(_rows_for_model(batch), GIST_SYSTEM, run, model, retry_wait)
        if not got:
            errs.append(f"中文一句话第 {i // VOICE_BATCH + 1} 批（{len(batch)} 条，之后补写）：{err}")
            continue
        for it in batch:
            x = got.get(it["id"]) or {}
            if str(x.get("gist") or "").strip():
                gists[it["id"]] = gist_fit(str(x["gist"]))
    return gists, errs


def screen(items: list[dict]) -> tuple[dict[str, float], list[str]]:
    """Jev 判每条是不是干货，返回 ({id: 概率}, 错误)。没配 key 或失败的不打分（照常显示）。"""
    from . import _feed_judge as J
    idx = by_id()
    who = lambda it: "；".join(f"{idx[p]['name']}，{idx[p]['role']}" for p in it["people"] if p in idx) + f" · channel={it['channel']}"
    todo = [({"id": it["id"], "source": "people", "title": it["title"], "summary": it["summary"], "url": it["url"]}, "value", who(it)) for it in items]
    got, errs = J.judge(todo)
    return {i: v["judge_value"] for i, v in got.items() if "judge_value" in v}, errs


def low_ids(items: list[dict], scores: dict[str, float], taken: dict[tuple[str, str], int] | None = None, day=lambda it: db.today()) -> set[str]:
    """分量不够的，加上推特里同一人同一天超过前几条的（按分量、热度挑）。taken 是这些人当天已经显示的推特条数。"""
    low = {it["id"] for it in items if scores.get(it["id"], 1) < VALUE_MIN}
    taken = dict(taken or {})
    xs = sorted((it for it in items if it["channel"] == "x" and it["id"] not in low),
                key=lambda it: (scores.get(it["id"], VALUE_MIN), it["popularity"]), reverse=True)
    for it in xs:
        keys = [(p, day(it)) for p in it["people"]] or [("", day(it))]
        if all(taken.get(k, 0) >= X_PER_PERSON_DAY for k in keys):
            low.add(it["id"])
            continue
        for k in keys:
            taken[k] = taken.get(k, 0) + 1
    return low


def _x_taken_today() -> dict[tuple[str, str], int]:
    today = db.today()
    taken: dict[tuple[str, str], int] = {}
    for r in db.rows("SELECT people FROM people_items WHERE channel='x' AND first_seen>=? AND json_extract(extra, '$.low') IS NULL", [today]):
        for p in json.loads(r["people"]):
            taken[(p, today)] = taken.get((p, today), 0) + 1
    return taken


def _hide(ids) -> None:
    for r in db.rows(f"SELECT id, extra FROM people_items WHERE id IN ({','.join('?' * len(ids))})", list(ids)) if ids else []:
        db.execute("UPDATE people_items SET extra=? WHERE id=?", [json.dumps({**json.loads(r["extra"] or "{}"), "low": 1}, ensure_ascii=False), r["id"]])


def rescreen(days: float = 2) -> tuple[list[str], list[str]]:
    """按现在的标准重判最近 days 天还在显示的条目，不够格的标记隐藏（不删）。返回 (隐藏的 id, 错误)。"""
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
    items = [_row(r) for r in db.rows("SELECT * FROM people_items WHERE first_seen>=? AND json_extract(extra, '$.low') IS NULL "
                                       "ORDER BY first_seen", [since])]
    scores, errs = screen(items)
    low = low_ids(items, scores, day=lambda it: it["first_seen"][:10])
    hidden = [it["id"] for it in items if it["id"] in low]
    _hide(hidden)
    return hidden, errs


def gist_fit(text: str) -> str:
    from ._feed_gist import fit
    return fit(text)


BACKFILL_MAX = 90


def backfill(run, model: str) -> list[str]:
    """给还没有中文一句话的条目补写；是不是干货由 Jev 在入库时判。"""
    rows = db.rows("SELECT * FROM people_items WHERE json_extract(extra, '$.gist') IS NULL AND json_extract(extra, '$.low') IS NULL "
                   "AND json_extract(extra, '$.gist_tried') IS NULL "
                   "ORDER BY first_seen DESC LIMIT ?", [BACKFILL_MAX])
    if not rows:
        return []
    items = [_row(r) for r in rows]
    gists, errs = annotate(items, run, model)
    for it in items:
        extra = dict(it["extra"])
        if it["id"] in gists:
            extra["gist"] = gists[it["id"]]
        elif not errs:
            extra["gist_tried"] = 1
        if extra != it["extra"]:
            db.execute("UPDATE people_items SET extra=? WHERE id=?", [json.dumps(extra, ensure_ascii=False), it["id"]])
    return errs


def _haiku_runner():
    from .feed import _haiku, cfg
    return _haiku, str(cfg("local_model"))


FETCHERS = {"x": fetch_x, "blog": fetch_blog, "youtube": fetch_youtube, "podcast": fetch_podcast, "paper": fetch_paper,
            "news": fetch_news, "bili": fetch_bili}


# ---------- 入库、调度、提醒 ----------
def upsert(items: list[dict]) -> list[str]:
    """同一条（同 id）合并人物；返回新出现的 id。"""
    new = []
    now = db.now()
    with db._lock:
        for it in items:
            old = db.row("SELECT people, popularity FROM people_items WHERE id=?", [it["id"]])
            if old:
                ps = sorted(set(json.loads(old["people"])) | set(it["people"]))
                db.execute("UPDATE people_items SET people=?, popularity=? WHERE id=?",
                           [json.dumps(ps), max(old["popularity"] or 0, it["popularity"]), it["id"]])
                continue
            db.insert("people_items", {"id": it["id"], "channel": it["channel"], "people": json.dumps(it["people"]),
                                       "title": it["title"], "summary": it["summary"], "url": it["url"], "date": it["date"],
                                       "popularity": it["popularity"], "extra": json.dumps(it["extra"], ensure_ascii=False),
                                       "first_seen": now, "notified": 0})
            new.append(it["id"])
    return new


def due(now: datetime | None = None) -> list[str]:
    now = now or datetime.now()
    last = {r["channel"]: r["at"] for r in db.rows("SELECT channel, at FROM people_runs")}
    out = []
    for ch, (_, hours) in CHANNELS.items():
        at = last.get(ch)
        if not at or now - datetime.fromisoformat(at[:19]) >= timedelta(hours=hours) - timedelta(minutes=5):
            out.append(ch)
    return out


# 手动「立即搜一轮」：刚跑过的渠道不重复跑；YouTube 搜索很费配额（和信息推荐共用每天 1 万），至少隔 2 小时
MANUAL_GAP_HOURS = {"youtube": 2.0}
MANUAL_GAP_DEFAULT = 0.5


def manual_channels(now: datetime | None = None) -> list[str]:
    now = now or datetime.now()
    last = {r["channel"]: r["at"] for r in db.rows("SELECT channel, at FROM people_runs")}
    return [ch for ch in CHANNELS if not last.get(ch) or now - datetime.fromisoformat(last[ch][:19])
            >= timedelta(hours=MANUAL_GAP_HOURS.get(ch, MANUAL_GAP_DEFAULT))]


def run(channels: list[str] | None = None, judge=None) -> dict:
    """跑指定渠道（默认到期的），入库，汇总提醒。返回每个渠道的 {count, new, errors}。"""
    _init()
    chans = [c for c in (channels or due()) if c in FETCHERS]
    pool = people()
    results = {}

    def one(ch):
        try:
            items, errs = FETCHERS[ch](pool)
        except Exception as e:  # noqa: BLE001
            items, errs = [], [f"{type(e).__name__}: {str(e)[:160]}"]
        items = [it for it in items if not is_translation(it)]
        if ch in JUDGED and items:
            marks = ",".join("?" * len(items))
            ids = [it["id"] for it in items]
            seen = {r["id"] for r in db.rows(f"SELECT id FROM people_items WHERE id IN ({marks})", ids)}
            rejected = {r["id"] for r in db.rows(f"SELECT id FROM people_rejected WHERE id IN ({marks})", ids)}
            fresh = [it for it in items if it["id"] not in seen | rejected]
            runner, model = judge or _haiku_runner()
            kept, rejected_now, verrs = voice_filter(fresh, runner, model)
            if ch == "news" and kept:
                kept, dropped, nerrs = news_triage(kept, runner, model)
                rejected_now, verrs = rejected_now + dropped, verrs + nerrs
            now = db.now()
            for iid in rejected_now:
                db.execute("INSERT OR REPLACE INTO people_rejected(id, at) VALUES(?, ?)", [iid, now])
            items = [it for it in items if it["id"] in seen] + kept
            errs = errs + verrs
        if items:
            stored = {r["id"] for r in db.rows(f"SELECT id FROM people_items WHERE id IN ({','.join('?' * len(items))})",
                                               [it["id"] for it in items])}
            fresh = [it for it in items if it["id"] not in stored]
            runner, model = judge or _haiku_runner()
            gists, gerrs = annotate(fresh, runner, model)
            scores, jerrs = screen(fresh)
            low = low_ids(fresh, scores, _x_taken_today() if ch == "x" else None)
            for it in fresh:
                if it["id"] in gists:
                    it["extra"]["gist"] = gists[it["id"]]
                if it["id"] in low:
                    it["extra"]["low"] = 1
            errs = errs + gerrs + [f"Jev 干货判断：{e}" for e in jerrs]
        new = upsert(items)
        db.execute("INSERT INTO people_runs(channel, at, count, new, errors) VALUES(?,?,?,?,?) "
                   "ON CONFLICT(channel) DO UPDATE SET at=excluded.at, count=excluded.count, new=excluded.new, errors=excluded.errors",
                   [ch, db.now(), len(items), len(new), json.dumps(errs[:20], ensure_ascii=False)])
        return ch, {"count": len(items), "new": len(new), "errors": errs[:20]}

    with ThreadPoolExecutor(max(1, len(chans))) as ex:
        results = dict(ex.map(one, chans))
    db.execute("DELETE FROM people_rejected WHERE at < ?", [(datetime.now() - timedelta(days=14)).isoformat(timespec="seconds")])
    runner, model = judge or _haiku_runner()
    for e in backfill(runner, model):
        log.warning("people backfill: %s", e)
    summarize_and_notify()
    return results


def summarize_and_notify() -> int:
    """把还没提醒过的新发声汇总成一条提醒：按人列出各渠道条数，Tier1 在前。"""
    rows = db.rows("SELECT id, channel, people FROM people_items WHERE notified=0 AND json_extract(extra, '$.low') IS NULL")
    if not rows:
        return 0
    idx = by_id()
    per: dict[str, dict[str, int]] = {}
    for r in rows:
        for pid in json.loads(r["people"]):
            per.setdefault(pid, {}).setdefault(r["channel"], 0)
            per[pid][r["channel"]] += 1
    order = sorted(per, key=lambda pid: (idx.get(pid, {}).get("tier", 3), -sum(per[pid].values())))
    def line(pid):
        p = idx.get(pid, {"name": pid})
        return f"{p.get('zh') or p['name']}：" + "、".join(f"{CHANNELS[c][0]} {n}" for c, n in per[pid].items())
    body = "；".join(line(pid) for pid in order[:6]) + (f" 等 {len(order)} 人" if len(order) > 6 else "")
    batch = (db.row("SELECT MAX(notified) AS n FROM people_items")["n"] or 0) + 1
    notify.notify("feed", f"名人新发声 {len(rows)} 条", body, link=f"#feed/people/batch/{batch}", kind="people")
    db.execute(f"UPDATE people_items SET notified=? WHERE id IN ({','.join('?' * len(rows))})", [batch] + [r["id"] for r in rows])
    return len(rows)


def start(channels: list[str] | None = None) -> bool:
    with _lock:
        if _state["running"]:
            return False
        chans = channels or due()
        if not chans:
            return False
        _state.update(running=True, channels=chans, started=db.now())

    def bg():
        try:
            _state["results"] = run(chans)
        except Exception:  # noqa: BLE001
            log.exception("people run")
        finally:
            _state["running"] = False
    threading.Thread(target=bg, daemon=True, name="feed-people").start()
    return True


def status() -> dict:
    _init()
    runs = {r["channel"]: {**r, "errors": json.loads(r["errors"] or "[]")} for r in db.rows("SELECT * FROM people_runs")}
    return {"running": _state["running"], "channels": [{"id": ch, "name": n, "hours": h, **(runs.get(ch) or {})}
                                                       for ch, (n, h) in CHANNELS.items()]}


def _row(r: dict) -> dict:
    return {**r, "people": json.loads(r["people"]), "extra": json.loads(r["extra"] or "{}")}


TRANSLATED = {"podcast", "youtube", "bili"}


def is_translation(it: dict) -> bool:
    """中文标题的播客 / 视频，关联人物里却没有中文母语者：基本是翻译、搬运版（新闻不算，中文媒体报道本人表态照收）。"""
    from ._feed_gist import is_chinese
    if it["channel"] not in TRANSLATED or not is_chinese(it["title"]):
        return False
    idx = by_id()
    return not any(idx.get(p, {}).get("native_zh") for p in it["people"])


PIN_MAX, PIN_MIN_VIDEO = 12, 600


def is_core(it: dict) -> bool:
    """核心长文和视频：本人博客、X 长文、论文、本人出镜的播客和视频（已知时长的要 ≥10 分钟）。"""
    ch, extra = it["channel"], it["extra"]
    if ch in ("blog", "paper", "podcast"):
        return True
    if ch in ("youtube", "bili"):
        return not extra.get("seconds") or extra["seconds"] >= PIN_MIN_VIDEO
    return ch == "x" and extra.get("x_article") == "own"


def pinned(idx: dict, days: int) -> list[dict]:
    """所选天数内发布的核心内容（没有发布时间的按发现时间）：晚抓到的旧内容不算进「今天」。"""
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
    rs = [_row(r) for r in db.rows("SELECT * FROM people_items WHERE first_seen>=? AND COALESCE(NULLIF(date,''), first_seen)>=? "
                                    "AND json_extract(extra, '$.low') IS NULL "
                                    "AND channel IN ('blog', 'paper', 'podcast', 'youtube', 'bili', 'x')", [since, since])]
    core = [r for r in rs if is_core(r) and not is_translation(r)]
    tier = lambda r: min((idx.get(p, {}).get("tier", 3) for p in r["people"]), default=3)
    core.sort(key=lambda r: r["date"] or r["first_seen"] or "", reverse=True)
    core.sort(key=tier)
    return core[:PIN_MAX]


def deep_url(it: dict) -> str:
    """深读用的链接：播客走音频直链，其他用原链接（和前端「深读」按钮一致）。"""
    return it["extra"].get("audio") or it["url"] if it["channel"] == "podcast" else it["url"]


def with_learn(items: list[dict]) -> list[dict]:
    """已经点过深读的条目带上深读条目的 id 和状态，前端据此显示「解析中 / 看笔记」。"""
    learned = db.rows("SELECT id, url, status FROM learn_items WHERE status!='failed' ORDER BY id DESC")
    for it in items:
        url = deep_url(it)
        if old := next((r for r in learned if _reads._same(r["url"], url)), None):
            it["learn"] = {"id": old["id"], "status": old["status"]}
    return items


def view(days: int = 1, person: str = "", batch: int = 0, limit: int = 300) -> dict:
    """days 天内新发现的发声，按人归组；person 给定时返回这个人的全部时间线；batch 给定时返回那一条提醒里的发声。"""
    _init()
    idx = by_id()
    if person:
        rs = db.rows("SELECT * FROM people_items WHERE people LIKE ? AND json_extract(extra, '$.low') IS NULL ORDER BY COALESCE(NULLIF(date,''), first_seen) DESC LIMIT ?",
                     [f'%"{person}"%', limit])
        return {"person": idx.get(person), "items": with_learn([it for it in map(_row, rs) if not is_translation(it)]), **status()}
    if batch:
        rs = [it for it in map(_row, db.rows("SELECT * FROM people_items WHERE notified=? AND json_extract(extra, '$.low') IS NULL "
                                              "ORDER BY COALESCE(NULLIF(date,''), first_seen) DESC", [batch])) if not is_translation(it)]
        rs.sort(key=lambda it: min((idx.get(p, {}).get("tier", 3) for p in it["people"]), default=3))
        return {"batch": with_learn(rs), "people": people(), **status()}
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
    rs = [_row(r) for r in db.rows("SELECT * FROM people_items WHERE first_seen>=? AND json_extract(extra, '$.low') IS NULL ORDER BY COALESCE(NULLIF(date,''), first_seen) DESC LIMIT ?",
                                    [since, limit])]
    pins = pinned(idx, days)
    pin_ids = {r["id"] for r in pins}
    groups: dict[str, list] = {}
    for r in rs:
        if r["id"] in pin_ids or is_translation(r):
            continue
        for pid in r["people"]:
            groups.setdefault(pid, []).append(r)
    counts = {r["pid"]: r["n"] for r in db.rows(
        "SELECT j.value AS pid, COUNT(*) AS n FROM people_items, json_each(people_items.people) j GROUP BY j.value")}
    def rank(pid):
        long_form = sum(1 for r in groups[pid] if r["channel"] != "x")
        return (idx.get(pid, {}).get("tier", 3), -long_form, -len(groups[pid]))
    order = sorted(groups, key=rank)
    with_learn(pins + rs)
    return {"pinned": pins, "groups": [{"person": idx.get(pid) or {"id": pid, "name": pid}, "items": groups[pid]} for pid in order],
            "people": [{**p, "total": counts.get(p["id"], 0)} for p in people()], **status()}
