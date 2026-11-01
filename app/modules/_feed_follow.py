"""信息推荐的关注源：把用户输入（@账号、主页链接、网站地址、播客链接或名字）解析成采集器认识的条目。

关注源按类别分组，每组落到 feed 设置里的一个或两个列表：
- x → x_accounts；github → github_watch_orgs；reddit → reddit
- video → youtube_channels（@handle / 频道链接解析成 UC 开头的频道 id）或 bilibili（B 站 UP 主 uid）
- site → rss（能找到 RSS / Atom）或 sites（没有 RSS 的列表页，自动推断文章链接规则 link_re）
- podcast → podcasts（RSS；Apple Podcasts 链接或节目名经 iTunes 接口换成 RSS）或 xiaoyuzhou（小宇宙节目页）
- product → product_rss（产品分析文章的 RSS / Atom，比如 a16z）
默认名单写在 settings 里，用户增删记在 feed.follow：{"add": {列表: [...]}, "remove": {列表: [键]}, "names": {键: 显示名}}，
默认名单以后更新也不会被冻结。
"""
from __future__ import annotations

import html
import re
from collections import Counter
from urllib.parse import urljoin, urlsplit

import feedparser
import httpx

from . import _feed_sources as src

GROUPS = {
    "x": {"label": "X 作者", "lists": ["x_accounts"], "collector": "x", "hint": "@karpathy 或 x.com/karpathy"},
    "github": {"label": "GitHub 作者 / 机构", "lists": ["github_watch_orgs"], "collector": "github",
               "hint": "deepseek-ai 或 github.com/karpathy（盯他们新建的仓库）"},
    "site": {"label": "网站 / 博客", "lists": ["rss", "sites"], "collector": None,
             "hint": "网站或博客列表页地址，有 RSS 自动用 RSS"},
    "podcast": {"label": "播客", "lists": ["podcasts", "xiaoyuzhou"], "collector": None,
                "hint": "RSS、Apple Podcasts、小宇宙节目页链接，或直接输节目名"},
    "product": {"label": "产品分析", "lists": ["product_rss"], "collector": "analysis",
                "hint": "分析文章的网站或 RSS，比如 a16z.news"},
    "reddit": {"label": "Reddit 版块", "lists": ["reddit"], "collector": "reddit", "hint": "r/LocalLLaMA"},
    "video": {"label": "视频频道", "lists": ["youtube_channels", "bilibili"], "collector": "video",
              "hint": "YouTube @handle / 频道链接，或 B 站 space.bilibili.com/uid"},
}
# 列表 → 采集器（refresh_sync 的来源名）
LIST_COLLECTOR = {"x_accounts": "x", "github_watch_orgs": "github", "rss": "rss", "sites": "sites",
                  "podcasts": "podcast", "xiaoyuzhou": "xiaoyuzhou", "reddit": "reddit",
                  "youtube_channels": "video", "bilibili": "video", "product_rss": "analysis"}
URL_LISTS = ("rss", "podcasts", "xiaoyuzhou", "product_rss")   # 条目本身是地址的列表
CASELESS = {"x_accounts", "github_watch_orgs", "reddit"}


# 默认名单里频道 id 的显示名（用户自己加的，名字记在 feed.follow.names）
KNOWN_NAMES = {
    "UCXUPKJO5MZQN11PqgIvyuvQ": "Andrej Karpathy", "UCYO_jab_esuFRV4b17AJtAw": "3Blue1Brown",
    "UCbfYPyITQ-7l4upoX8nvctg": "Two Minute Papers", "UCZHmQk67mSJgfCCTn7xBfew": "Yannic Kilcher",
    "UCNJ1Ymd5yFuUPtn21xtRbbw": "AI Explained", "UCXl4i9dYBrFOabk0xGmbkRA": "Dwarkesh Patel",
    "UCMLtBahI5DMrt0NPvDSoIRQ": "Machine Learning Street Talk", "UCrDwWp7EBBv4NwvScIpBDOA": "Anthropic",
    "UCXZCJLdBC09xxGZ6gcdrc6A": "OpenAI", "UCP7jMXSY2xbc3KCAE0MHQ-A": "Google DeepMind",
    "UCBa5G_ESCn8Yd4vw5U-gIcg": "Stanford Online", "UCSHZKyawb77ixDdsGog4iWA": "Lex Fridman",
    "UCLKPca3kwwd-B59HNr-_lvA": "AI Engineer", "UCxBcwypKK-W3GHd_RZ9FZrQ": "Latent Space",
    "UC2ggjtuuWvxrHHHiaDH1dlQ": "李宏毅 Hung-yi Lee", "UCcefcZRL2oaA_uBNeo5UOWg": "Y Combinator",
    "UCtAcpQcYerN8xxZJYTfWBMw": "Umar Jamil", "UC55ODQSvARtgSyc8ThfiepQ": "Sam Witteveen",
    "UC9cn0TuPq4dnbTY-CBsm8XA": "a16z", "UCWrF0oN6unbXrWsTN7RctTw": "Sequoia Capital",
    "UCjIMtrzxYc0lblGhmOgC_CA": "Every", "UCjNRVMBVI30Sak_p6HRWhIA": "Cognitive Revolution",
    "UCf0PBRjhf0rF8fWBIxTuoWA": "20VC",
    "UCsBjURrPoezykLs9EqgamOA": "Fireship", "UCgfe2ooZD3VJPB6aJAnuQng": "bycloud",
    "UC9-y-6csu5WGm29I7JiwpnA": "Computerphile", "UCtYLUTtgS3k1Fg4y5tAhLbw": "StatQuest",
    "UCX7Y2qWriXpqocG97SFW2OQ": "Jeremy Howard", "UC_CzsS7UTjcxJ-xXp1ftxtA": "Sebastian Raschka",
    "UCI5dM9hNYAXwuvhQRXwzzww": "hu-po", "UConVfxXodg78Tzh5nNu85Ew": "Welch Labs",
    "UCZgt6AzoyjslHTC9dz0UoTw": "ByteByteGo", "UC1kBxkk2bcG78YBX7LMl9pQ": "code_report",
    "UCbRP3c757lWg9M-U7TyEkXA": "Theo - t3.gg", "UCMwVTLZIRRUyyVrkjDpn4pA": "Cole Medin",
    "UC_x36zCEGilGpB1m-V4gmjg": "IndyDevDan", "UCC-lyoTfSrcJzA1ab3APAgw": "LangChain",
    "UCSI7h9hydQ40K5MJHnCrQvw": "No Priors",
    "1567748478": "B 站 跟李沐学AI",
}


class FollowError(ValueError):
    """输入认不出来或抓不到，消息直接给用户看。"""


def entry_key(lst: str, v) -> str:
    k = v.get("url", "") if isinstance(v, dict) else str(v)
    k = k.strip()
    return k.lower() if lst in CASELESS else k.rstrip("/")


def effective(base: list, follow: dict, lst: str) -> list:
    """默认名单去掉用户删掉的，加上用户加的（去重）。"""
    removed = set((follow.get("remove") or {}).get(lst) or [])
    out, seen = [], set()
    for v in [*(base or []), *((follow.get("add") or {}).get(lst) or [])]:
        k = entry_key(lst, v)
        if k and k not in removed and k not in seen:
            seen.add(k)
            out.append(v)
    return out


def label(lst: str, v, names: dict) -> str:
    k = entry_key(lst, v)
    if isinstance(v, dict):
        return v.get("name") or k
    if names.get(k) or KNOWN_NAMES.get(k):
        return names.get(k) or KNOWN_NAMES[k]
    if lst in ("x_accounts",):
        return "@" + v
    if lst == "reddit":
        return "r/" + v
    if lst == "bilibili":
        return "B 站 " + v
    if lst in URL_LISTS:
        p = urlsplit(v)
        return (p.netloc.removeprefix("www.") + p.path.rstrip("/"))[:60]
    return str(v)


# ---------- 解析输入 ----------

def _client() -> httpx.Client:
    return httpx.Client(timeout=src.TIMEOUT, headers={"User-Agent": src.BROWSER_UA}, follow_redirects=True)


def _url(text: str) -> str:
    t = text.strip()
    if not re.match(r"https?://", t, re.I):
        t = "https://" + t
    p = urlsplit(t)
    if not p.netloc or "." not in p.netloc:
        raise FollowError(f"「{text}」不是网址")
    return t


def resolve(group: str, text: str, client: httpx.Client | None = None) -> tuple[str, object, str]:
    """返回 (列表名, 条目, 显示名)。认不出、抓不到时抛 FollowError。"""
    text = (text or "").strip()
    if not text:
        raise FollowError("输入为空")
    if group == "x":
        m = re.fullmatch(r"(?:https?://)?(?:www\.|mobile\.)?(?:x|twitter)\.com/@?(\w{1,15})(?:[/?#].*)?|@?(\w{1,15})", text, re.I)
        if not m or (m.group(1) or m.group(2)).lower() in ("home", "i", "search", "explore"):
            raise FollowError("X 账号写成 @用户名 或 x.com/用户名")
        h = m.group(1) or m.group(2)
        return "x_accounts", h, "@" + h
    if group == "reddit":
        m = re.fullmatch(r"(?:https?://)?(?:www\.|old\.)?(?:reddit\.com/)?/?(?:r/)?(\w{2,21})/?(?:[?#].*)?", text, re.I)
        if not m:
            raise FollowError("Reddit 版块写成 r/版块名")
        return "reddit", m.group(1), "r/" + m.group(1)
    if group == "video":
        return _video(text)
    own = client is None
    c = client or _client()
    try:
        if group == "github":
            return _github(c, text)
        if group == "site":
            return _site(c, text)
        if group == "podcast":
            return _podcast(c, text)
        if group == "product":
            return _product(c, text)
    finally:
        if own:
            c.close()
    raise FollowError(f"未知类别：{group}")


def _video(text: str):
    if m := re.search(r"(?:space\.bilibili\.com/|^(?:bili(?:bili)?:?\s*))(\d{3,})", text, re.I):
        return "bilibili", m.group(1), "B 站 " + m.group(1)
    if not re.search(r"youtube\.com|youtu\.be|^@[\w.-]{3,}$|^UC[\w-]{22}$", text):
        raise FollowError("视频频道写成 YouTube @handle / 频道链接，或 B 站 space.bilibili.com/uid")
    try:
        cid, name = src.resolve_youtube_channel(text)
    except Exception as e:  # noqa: BLE001
        raise FollowError(f"没找到这个 YouTube 频道：{type(e).__name__}") from e
    return "youtube_channels", cid, name or cid


def _github(c: httpx.Client, text: str):
    m = re.fullmatch(r"(?:https?://)?(?:www\.)?(?:github\.com/)?@?([A-Za-z0-9][A-Za-z0-9-]{0,38})(?:[/?#].*)?", text)
    if not m:
        raise FollowError("GitHub 写成用户名 / 机构名，或 github.com/名字")
    name = m.group(1)
    try:
        r = c.get(f"https://api.github.com/users/{name}", headers=src._gh_headers())
    except httpx.HTTPError:
        return "github_watch_orgs", name, name       # 网络问题不拦，刷新时再看
    if r.status_code == 404:
        raise FollowError(f"GitHub 上没有 {name}")
    j = r.json() if r.status_code == 200 else {}
    return "github_watch_orgs", j.get("login") or name, (j.get("name") or j.get("login") or name)


def _as_feed(text: str):
    f = feedparser.parse(text)
    return f if getattr(f, "entries", None) and (f.get("version") or "").strip() else None


def _feed_links(page_url: str, page: str) -> list[str]:
    out = []
    for tag in re.findall(r"<link\b[^>]*>", page, re.I):
        if re.search(r"""rel\s*=\s*['"]?alternate""", tag, re.I) and re.search(r"(rss|atom)\+xml", tag, re.I):
            m = re.search(r"""href\s*=\s*['"]([^'"]+)['"]""", tag, re.I)
            if m:
                out.append(urljoin(page_url, html.unescape(m.group(1))))
    return out


def _find_feed(c: httpx.Client, url: str) -> tuple[str, str, str]:
    """(feed 地址, feed 标题, 页面 HTML)；页面本身就是 feed 时 HTML 为空。找不到 feed 时 feed 地址为空。"""
    try:
        r = c.get(url)
        r.raise_for_status()
    except httpx.HTTPError as e:
        raise FollowError(f"打不开 {url}：{type(e).__name__}") from e
    if f := _as_feed(r.text):
        return str(r.url), src.clean(f.feed.get("title", ""), 80), ""
    for u in _feed_links(str(r.url), r.text)[:3]:
        try:
            fr = c.get(u)
            if fr.status_code == 200 and (f := _as_feed(fr.text)):
                return str(fr.url), src.clean(f.feed.get("title", ""), 80), r.text
        except httpx.HTTPError:
            continue
    return "", "", r.text


SLUG = r"[a-z0-9][a-z0-9-]+"


def guess_link_re(page_url: str, page: str) -> str:
    """没有 RSS 的列表页：在同站链接里找「同一前缀 + 文章 slug」最多的一组，生成 fetch_sites 用的 link_re。"""
    base = urlsplit(page_url)
    groups: Counter = Counter()
    for href in re.findall(r"""href\s*=\s*['"]([^'"#?]+)['"]""", page, re.I):
        u = urlsplit(urljoin(page_url, html.unescape(href)))
        if u.netloc and u.netloc != base.netloc:
            continue
        parts = [p for p in u.path.split("/") if p]
        if not parts:
            continue
        slug = parts[-1].lower()
        # 文章 slug：带连字符的一串词或较长的 id；导航链接（/about /pricing）一般没有
        if not re.fullmatch(SLUG, slug) or not ("-" in slug or len(slug) >= 12):
            continue
        groups["/" + "/".join(parts[:-1])] += 1
    best = [(p, n) for p, n in groups.most_common() if n >= 3]
    if not best:
        return ""
    prefix = best[0][0].rstrip("/")
    host = re.escape(base.netloc)
    return rf"(?:https?://{host})?{re.escape(prefix)}/{SLUG}/?"


def _site_name(page: str, fallback: str) -> str:
    name = src._meta(page, "og:site_name") or (re.search(r"<title[^>]*>(.*?)</title>", page, re.S | re.I) or [None, ""])[1]
    return src.clean(html.unescape(name), 60) or fallback


def _site(c: httpx.Client, text: str):
    url = _url(text)
    feed, title, page = _find_feed(c, url)
    if feed:
        return "rss", feed, title or urlsplit(url).netloc
    link_re = guess_link_re(url, page)
    if not link_re:
        raise FollowError("没找到 RSS，也认不出文章链接；换成博客 / 新闻的列表页地址（比如 …/blog）再试")
    name = _site_name(page, urlsplit(url).netloc)
    return "sites", {"name": name, "url": url, "link_re": link_re}, name


def _podcast(c: httpx.Client, text: str):
    if m := src.XYZ_ID.search(text):
        url = f"https://www.xiaoyuzhoufm.com/podcast/{m.group(1)}"
        name = ""
        try:
            name = _site_name(c.get(url).text, "")
        except httpx.HTTPError:
            pass
        return "xiaoyuzhou", url, (name.split("|")[0].strip() or "小宇宙节目")
    if m := re.search(r"podcasts\.apple\.com/.*?\bid(\d+)", text):
        hits = c.get("https://itunes.apple.com/lookup", params={"id": m.group(1), "entity": "podcast"}).json().get("results") or []
    elif not re.match(r"https?://|[\w-]+(\.[\w-]+)+/", text):
        # 不是链接：按节目名搜 Apple Podcasts 目录，取第一个
        hits = c.get("https://itunes.apple.com/search", params={"term": text, "media": "podcast", "limit": 1}).json().get("results") or []
        if not hits:
            raise FollowError(f"Apple Podcasts 目录里没搜到「{text}」，贴节目的 RSS 或小宇宙链接试试")
    else:
        feed, title, _ = _find_feed(c, _url(text))
        if not feed:
            raise FollowError("这个页面没有播客 RSS；贴 RSS、Apple Podcasts 或小宇宙节目页链接")
        return "podcasts", feed, title or urlsplit(feed).netloc
    hit = next((h for h in hits if h.get("feedUrl")), None)
    if not hit:
        raise FollowError("这个节目在 Apple Podcasts 上没有公开 RSS")
    return "podcasts", hit["feedUrl"], hit.get("collectionName") or hit["feedUrl"]


def _product(c: httpx.Client, text: str):
    url = _url(text)
    feed, title, _ = _find_feed(c, url)
    if not feed:
        raise FollowError("没找到 RSS / Atom；贴文章站点或它的 RSS 地址")
    name = title or urlsplit(url).netloc
    return "product_rss", {"name": name, "url": feed}, name
