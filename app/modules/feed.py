"""信息推荐：从 HN/HF/AlphaXiv/GitHub/博客 RSS 与官方站/播客/Reddit/X/Product Hunt/YouTube 与 B 站视频收集 AI 相关内容，按热度/新鲜度/兴趣/反馈排序。

不做逐条提炼：只展示标题 + 简介 + 链接 + 「为什么推荐」。排序逻辑见 _feed_rank.py，采集见 _feed_sources.py。
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import db, settings
from . import _feed_follow as follow
from . import _feed_gist as gist
from . import _feed_product as pa
from . import _feed_judge as judge
from . import _feed_rank as rk
from . import _feed_sources as src

log = logging.getLogger(__name__)

TITLE = "信息推荐"
ORDER = 30
SCHEMA = """
CREATE TABLE IF NOT EXISTS feed_items (
    id          TEXT PRIMARY KEY,          -- source:external_id，稳定去重键
    source      TEXT NOT NULL,             -- hn / hf / arxiv / github / blog / reddit / producthunt / twitter ...
    type        TEXT NOT NULL,             -- paper / blog / product / repo / discussion / news
    title       TEXT NOT NULL,
    summary     TEXT DEFAULT '',           -- ≤400 字
    url         TEXT DEFAULT '',
    date        TEXT DEFAULT '',
    popularity  REAL DEFAULT 0,            -- 来源热度：points / stars / likes / upvotes
    extra       TEXT DEFAULT '{}',
    fetched_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_feed_items_fetched ON feed_items(fetched_at);
CREATE TABLE IF NOT EXISTS feed_feedback (
    item_id     TEXT PRIMARY KEY,
    vote        INTEGER DEFAULT 0,         -- 1 赞 / -1 踩 / 0 无
    saved       INTEGER DEFAULT 0,
    hidden      INTEGER DEFAULT 0,
    updated_at  TEXT
);
"""

# settings.feed 之外的旋钮的缺省值（可在 data/settings.json 的 feed 下覆盖）
CFG_DEFAULTS = {
    "half_life_hours": 72,
    "auto_refresh_hours": 6,      # 数据超过这么久自动后台刷新；0 = 关闭
    "stale_source_days": 7,       # 某来源最新条目早于这么多天，status 里标为停更
    "hn_queries": ["LLM", "AI agent", "Claude", "OpenAI", "GPT", "coding agent"],
    "github_queries": ["llm", "ai agent", "mcp", "claude code"],
    "github_min_stars": 100,      # 搜索新建仓库时的最低星数（太低全是刚建的小项目）
    "github_trending_languages": [""],  # 每日 Trending 看哪些语言："" = 全部语言，可加 "python" "typescript"
    # 重点机构的新仓库：和官方博客一样加「官方」分；机构名对照见 _feed_rank.GITHUB_ORGS，不在里面的显示 GitHub 账号名
    "github_watch_orgs": ["deepseek-ai", "openai", "anthropics", "google", "google-deepmind", "google-research",
                          "meta-llama", "facebookresearch", "microsoft"],
    "github_watch_min_stars": 5,  # 重点机构新仓库的最低星数：滤掉大厂每天建的内部空仓库
    # Reddit：实践经验和前沿讨论最集中的版块；.env 配 REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET 走官方 API（有票数），否则走 RSS
    "reddit": ["LocalLLaMA", "ClaudeAI", "ClaudeCode", "MachineLearning", "LLMDevs", "AI_Agents", "ChatGPTCoding", "mcp"],
    "reddit_queries": ["claude code", "coding agent", "mcp server"],   # 全站搜本周 top，补名单版块之外的讨论
    # 视频：YouTube 频道 id（UC 开头；显示名见 _feed_follow.KNOWN_NAMES，「关注源」里可用 @handle 添加）
    "youtube_channels": ["UCXUPKJO5MZQN11PqgIvyuvQ", "UCbfYPyITQ-7l4upoX8nvctg", "UCZHmQk67mSJgfCCTn7xBfew",
                         "UCNJ1Ymd5yFuUPtn21xtRbbw", "UCXl4i9dYBrFOabk0xGmbkRA", "UCMLtBahI5DMrt0NPvDSoIRQ",
                         "UCrDwWp7EBBv4NwvScIpBDOA", "UCXZCJLdBC09xxGZ6gcdrc6A", "UCP7jMXSY2xbc3KCAE0MHQ-A",
                         "UCLKPca3kwwd-B59HNr-_lvA", "UCxBcwypKK-W3GHd_RZ9FZrQ", "UC2ggjtuuWvxrHHHiaDH1dlQ",
                         "UCYO_jab_esuFRV4b17AJtAw", "UCSHZKyawb77ixDdsGog4iWA", "UCcefcZRL2oaA_uBNeo5UOWg",
                         "UCtAcpQcYerN8xxZJYTfWBMw", "UCBa5G_ESCn8Yd4vw5U-gIcg",
                         # 创投 / 创业访谈：a16z、Sequoia、Every、Cognitive Revolution、20VC
                         "UC9cn0TuPq4dnbTY-CBsm8XA", "UCWrF0oN6unbXrWsTN7RctTw", "UCjIMtrzxYc0lblGhmOgC_CA",
                         "UCjNRVMBVI30Sak_p6HRWhIA", "UCf0PBRjhf0rF8fWBIxTuoWA"],
    "youtube_queries": ["claude code", "AI agents", "LLM explained", "AI engineering"],   # 只在 .env 有 YOUTUBE_API_KEY 时搜
    "bilibili": ["1567748478"],   # B 站 UP 主 uid（经 RSSHub，公共实例不稳）
    "video_days": 21,
    "x_days": 3,                  # X：只要最近几天的推文
    "x_min_likes": 100,           # X 名单账号：低于这个赞数的推文不收
    "x_per_account": 2,           # X 名单账号：每人每次最多收几条
    "producthunt_days": 2,
    "yc_days": 3,                 # Launch YC：只要最近几天的产品发布（只留 AI 相关）
    "gist_enabled": True,         # 完整刷新后给排序前列生成中文一句话（DeepSeek，.env 的 DEEPSEEK_API_KEY）
    "gist_top": 60,               # 「全部」前多少条
    "gist_per_type": 10,          # 每个分类前多少条
    "gist_model": "deepseek-v4-flash",
    "product_analysis_top": 20,   # 「产品」分类前多少条生成产品分析（收入 / 商业模式 / 定位 / 价值 / 痛点）
    "trustmrr_days": 30,          # TrustMRR：只要最近几天挂牌出售的产品
    "judge_enabled": True,        # 每次刷新后用 Jev 判：Trending 项目是否 AI、官方内容是否重要（.env 的 TYPESAFE_API_KEY / JEV_API_KEY）
    "sources": ["hn", "hf", "alphaxiv", "github", "rss", "sites", "podcast", "xiaoyuzhou", "reddit", "x", "producthunt",
                "yc", "trustmrr", "analysis", "video"],
}
# 分类 → 采集器：分类页上的「刷新」只跑这些来源
TYPE_SOURCES = {"paper": ["hf", "alphaxiv"], "blog": ["rss", "sites"], "podcast": ["podcast", "xiaoyuzhou"],
                "product": ["producthunt", "yc", "trustmrr", "analysis"], "repo": ["github"], "discussion": ["hn", "reddit", "x"],
                "x_article": ["x"], "video": ["video"]}
TYPES = {"paper": "论文", "blog": "博客", "podcast": "播客", "product": "产品", "repo": "项目", "discussion": "讨论",
         "video": "视频", "news": "资讯"}

router = APIRouter()
_state: dict = {"running": False, "started_at": "", "started_utc": "", "finished_at": "", "results": {}, "scope": ""}
_state_lock = threading.Lock()


def cfg(key: str):
    v = settings.get(f"feed.{key}")
    return CFG_DEFAULTS.get(key) if v is None else v


# ---------- 存储 ----------

_cols_ok = False


def _ensure_cols() -> None:
    """feed_feedback 后加的点击列（老库迁移）。"""
    global _cols_ok
    if _cols_ok:
        return
    cols = {r["name"] for r in db.rows("PRAGMA table_info(feed_feedback)")}
    if "clicks" not in cols:
        db.execute("ALTER TABLE feed_feedback ADD COLUMN clicks INTEGER DEFAULT 0")
    if "last_click" not in cols:
        db.execute("ALTER TABLE feed_feedback ADD COLUMN last_click TEXT DEFAULT ''")
    if "verdict" not in cols:  # 读完论文写的一句话判断（每日论文习惯，进知识库）
        db.execute("ALTER TABLE feed_feedback ADD COLUMN verdict TEXT DEFAULT ''")
    if "verdict_at" not in cols:
        db.execute("ALTER TABLE feed_feedback ADD COLUMN verdict_at TEXT DEFAULT ''")
    _cols_ok = True


def norm_date(s: str) -> str:
    """各来源日期格式不一（2026-06-10 / ...000Z / +00:00），统一成 ISO UTC 秒级；解析不了原样保留。"""
    d = rk._parse_dt(s or "")
    return _iso(d) if d else (s or "")


def _iso(d: datetime) -> str:
    return d.astimezone(timezone.utc).isoformat(timespec="seconds")

def upsert(items: list[dict]) -> int:
    return _upsert(items)[0]


def _upsert(items: list[dict]) -> tuple[int, int]:
    """写入/合并：新值非空才覆盖；extra 合并（保留旧条目已有的字段）。同一条（id 相同）再抓到只更新不重复入库。
    返回 (写入条数, 其中新增条数)。"""
    n = new = 0
    ts = db.now()
    for it in items:
        if not it.get("id") or not it.get("title"):
            continue
        old = db.row("SELECT * FROM feed_items WHERE id=?", [it["id"]])
        it = {**it, "date": norm_date(it.get("date") or "")}
        extra = dict(it.get("extra") or {})
        if old:
            merged = {**_extra(old), **{k: v for k, v in extra.items() if v not in ("", None, [], {})}}
            merged.setdefault("first_seen", rk.FIRST_SEEN_LEGACY)
            if merged.get("article_title") and not extra.get("article_title"):
                it = {**it, "title": old["title"], "summary": old["summary"]}   # X 长文已补过标题，别被占位文案盖掉
            if (it.get("summary") or "").startswith("链接到") and old["summary"] and not old["summary"].startswith("链接到"):
                it = {**it, "summary": old["summary"]}     # HN 已读到原文简介，别被占位文案盖掉
            db.execute("UPDATE feed_items SET source=?, type=?, title=?, summary=?, url=?, date=?, popularity=?, extra=?, "
                       "fetched_at=? WHERE id=?",
                       [it["source"], it["type"], it["title"], it.get("summary") or old["summary"],
                        it.get("url") or old["url"], it.get("date") or old["date"],
                        max(float(it.get("popularity") or 0), float(old["popularity"] or 0))
                        if it["source"] == old["source"] else float(it.get("popularity") or 0),
                        json.dumps(merged, ensure_ascii=False), ts, it["id"]])
        else:
            extra.setdefault("first_seen", datetime.now(timezone.utc).isoformat(timespec="seconds"))   # 新增标识用；更新时 merged 保留旧值
            db.insert("feed_items", {"id": it["id"], "source": it["source"], "type": it["type"], "title": it["title"],
                                     "summary": it.get("summary") or "", "url": it.get("url") or "",
                                     "date": it.get("date") or "", "popularity": float(it.get("popularity") or 0),
                                     "extra": extra, "fetched_at": ts})
            new += 1
        n += 1
    return n, new


def _extra(r: dict) -> dict:
    try:
        return json.loads(r.get("extra") or "{}") if isinstance(r.get("extra"), str) else (r.get("extra") or {})
    except ValueError:
        return {}


def _load_items(limit: int = 5000) -> list[dict]:
    rows = db.rows("SELECT * FROM feed_items ORDER BY fetched_at DESC LIMIT ?", [limit])
    for r in rows:
        r["extra"] = _extra(r)
    return rows


def _feedback() -> dict[str, dict]:
    _ensure_cols()
    return {r["item_id"]: {"vote": r["vote"], "saved": r["saved"], "hidden": r["hidden"], "verdict": r.get("verdict") or "",
                           "verdict_at": r.get("verdict_at") or ""}
            for r in db.rows("SELECT * FROM feed_feedback")}


def _examples(items: list[dict], fb: dict[str, dict]) -> list[dict]:
    """亲和度样本：本平台的赞/收藏（+）与踩（-）；早先从 learn_evolve 导入的条目，其 star/good（+）与 bad（-）评分也算。"""
    ex = []
    for it in items:
        f = fb.get(it["id"], {})
        pol = 1 if (f.get("vote", 0) > 0 or f.get("saved")) else (-1 if f.get("vote", 0) < 0 else 0)
        if not pol:
            pol = {"star": 1, "good": 1, "bad": -1}.get(it["extra"].get("le_rating", ""), 0)
        if pol:
            ex.append({"id": it["id"], "title": it["title"], "summary": it.get("summary", ""), "source": it["source"], "polarity": pol})
    return ex


def _mark_gone(items: list[dict]) -> None:
    """直连 GitHub 来源：最近一次抓取里没再出现、但仍在抓取窗口内的仓库，多半已删除或刷星后掉榜。"""
    gh = [it for it in items if it["source"] == "github" and it["extra"].get("query")]
    if not gh:
        return
    last = max(it["fetched_at"] or "" for it in gh)
    cutoff = (rk._parse_dt(last) or datetime.now(timezone.utc)).timestamp() - 3600
    window = datetime.now(timezone.utc).timestamp() - 13 * 86400   # 抓取窗口 14 天，留 1 天余量：过窗口的只是变旧
    for it in gh:
        d, pub = rk._parse_dt(it["fetched_at"] or ""), rk._parse_dt(it.get("date") or "")
        if d and d.timestamp() < cutoff and pub and pub.timestamp() > window:
            it["extra"]["gone"] = True


def ranked(type_: str = "", saved: bool = False, q: str = "", now: datetime | None = None, days: float = 0,
           sort: str = "score") -> list[dict]:
    """days: 只要最近 N 天发布的（0 = 不限）；sort: score 综合 / new 最新 / hot 最热（同源热度百分位）。
    只有「全部 + 综合 + 不限时间 + 无筛选」时做类型 / 来源多样化（今日精选就取这个列表的前 5 条）。"""
    now = now or datetime.now(timezone.utc)
    items = _load_items()
    _mark_gone(items)
    fb = _feedback()
    out = rk.rank(items, now=now, half_life_h=float(cfg("half_life_hours")),
                  interests=list(cfg("interests") or []), feedback=fb, examples=_examples(items, fb),
                  include_hidden=saved)
    if saved:
        out = [x for x in out if x["feedback"].get("saved")]
    if type_ == "x_article":  # 「X 长文」标签页：自己发的长文 + 引用了长文的推文
        out = [x for x in out if x["extra"].get("x_article")]
    elif type_:
        out = [x for x in out if x["type"] == type_]
    if q:
        ql = q.lower()
        out = [x for x in out if ql in f"{x['title']} {x['summary']} {x['extra'].get('gist', '')}".lower()]
    out = rk.within_days(out, days, now)
    if sort in ("new", "hot"):
        return rk.sort_items(out, sort, now)
    if not (type_ or saved or q or days):
        out = rk.diversify(out)
    return out


# ---------- 采集 ----------

def follow_cfg() -> dict:
    return settings.get("feed.follow", {}) or {}


def src_list(lst: str) -> list:
    """某个关注列表的实际内容：默认名单 + 用户加的 − 用户删的。"""
    return follow.effective(list(cfg(lst) or []), follow_cfg(), lst)


def _collectors() -> dict:
    fc = settings.get("feed", {}) or {}
    return {
        "hn": lambda: src.fetch_hn(list(cfg("hn_queries")), known_ids=_enriched_hn()),
        "hf": lambda: src.fetch_hf_papers(),
        "alphaxiv": lambda: src.fetch_alphaxiv(),
        "github": lambda: src.fetch_github_all(list(cfg("github_queries")), min_stars=int(cfg("github_min_stars")),
                                               trending_languages=list(cfg("github_trending_languages")),
                                               watch_orgs=src_list("github_watch_orgs"),
                                               watch_min_stars=int(cfg("github_watch_min_stars"))),
        "rss": lambda: src.fetch_rss(src_list("rss")),
        "sites": lambda: src.fetch_sites(src_list("sites"), known_urls=_known_urls("blog")),
        "podcast": lambda: src.fetch_rss(src_list("podcasts"), per_feed=5, source="podcast", typ="podcast"),
        "xiaoyuzhou": lambda: src.fetch_xiaoyuzhou(src_list("xiaoyuzhou"),
                                                   rsshub_bases=list(fc.get("rsshub_bases") or []) or None),
        "reddit": lambda: src.fetch_reddit(src_list("reddit"), list(cfg("reddit_queries") or [])),
        "video": lambda: src.fetch_videos(src_list("youtube_channels"), list(cfg("youtube_queries") or []),
                                          bilibili=src_list("bilibili"), days=int(cfg("video_days")),
                                          rsshub_bases=list(fc.get("rsshub_bases") or []) or None),
        "x": lambda: src.fetch_x(src_list("x_accounts"), list(fc.get("x_queries") or []),
                                 days=int(cfg("x_days")), min_likes=int(cfg("x_min_likes")),
                                 per_account=int(cfg("x_per_account")), known_articles=_known_articles()),
        "producthunt": lambda: src.fetch_producthunt(days=int(cfg("producthunt_days"))),
        "yc": lambda: src.fetch_yc_launches(days=int(cfg("yc_days"))),
        "trustmrr": lambda: src.fetch_trustmrr(days=int(cfg("trustmrr_days")), known=_known_extra("trustmrr")),
        "analysis": lambda: src.fetch_rss([_url_of(v) for v in src_list("product_rss")], per_feed=10,
                                          source="analysis", typ="product"),
    }


def _url_of(v) -> str:
    return v.get("url", "") if isinstance(v, dict) else str(v)


def _enriched_hn() -> set[str]:
    """已经有原文简介的 HN 条目（summary 不再是「链接到 …」占位），刷新时不再读原文页。"""
    return {r["id"] for r in db.rows("SELECT id FROM feed_items WHERE source='hn' AND summary NOT LIKE '链接到%'")}


def _known_articles() -> set[str]:
    """已补过标题的 X 长文（标题不再是占位文案），刷新时不再调 twitterapi.io。"""
    return {r["id"] for r in db.rows("SELECT id FROM feed_items WHERE source='twitter' AND extra LIKE '%article_title%'")}


def _known_extra(source: str) -> dict[str, dict]:
    return {r["id"]: _extra(r) for r in db.rows("SELECT id, extra FROM feed_items WHERE source=?", [source])}


def _known_urls(source: str) -> set[str]:
    return {r["url"] for r in db.rows("SELECT url FROM feed_items WHERE source=?", [source])}


def refresh_sync(only: list[str] | None = None, gists: bool | None = None) -> dict:
    """跑一遍采集；每个来源独立 fail-soft。返回 {source: {count, new, errors}}。
    gists：是否补中文一句话，默认只在全量刷新时补（分类页手动刷新也补，新抓的要能看懂）。"""
    cols = _collectors()
    names = [n for n in (only or cfg("sources")) if n in cols]
    results: dict = {}

    def run(name):
        try:
            got = cols[name]()
            items, errs = got if isinstance(got, tuple) else (got, [])
            n, new = _upsert(items)
            return name, {"count": n, "new": new, "errors": errs}
        except Exception as e:  # noqa: BLE001
            log.warning("feed source %s failed: %s", name, e)
            return name, {"count": 0, "errors": [f"{type(e).__name__}: {str(e)[:200]}"]}

    with ThreadPoolExecutor(max_workers=6) as ex:
        for name, res in ex.map(run, names):
            results[name] = res
    if cfg("judge_enabled"):    # 判断决定过滤和置顶，刷了哪个来源都跑；只问新的或内容变了的，量很小
        results["judge"] = run_judge()
    if (not only if gists is None else gists) and cfg("gist_enabled"):       # 只刷部分来源时不跑，避免每次小刷新都调模型
        results["gist"] = run_gists()
        results["product_analysis"] = run_product_analysis()
    return results


def run_judge(now: datetime | None = None) -> dict:
    """给最近的 Trending 仓库（是否 AI）、官方内容（是否重要）、Reddit / 视频搜索结果（有没有干货）补 Jev 判断，写回 extra。没判过的排序时走关键词规则。"""
    now = now or datetime.now(timezone.utc)
    todo = []
    for it in _load_items():
        ex = it["extra"]
        if ex.get("judge_src") == judge.judge_key(it):
            continue
        d = rk.item_time(it, now)
        if not d or (now - d).total_seconds() > rk.PIN_DAYS * 86400:
            continue
        if rk.trending_only(it):
            todo.append((it, "ai", ""))
        elif org := rk.official_org(it):
            todo.append((it, "important", org))
        elif rk.needs_value(it):
            todo.append((it, "value", ""))
    if not todo:
        return {"count": 0, "errors": []}
    got, errors = judge.judge(todo)
    for it, _, _ in todo:
        if it["id"] in got:
            row = db.row("SELECT extra FROM feed_items WHERE id=?", [it["id"]])
            ex = {**_extra(row or {}), **got[it["id"]], "judge_src": judge.judge_key(it)}
            db.execute("UPDATE feed_items SET extra=? WHERE id=?", [json.dumps(ex, ensure_ascii=False), it["id"]])
    return {"count": len(got), "errors": errors}


def run_gists() -> dict:
    """给排序前列里缺中文一句话（或标题 / 简介变了）的条目生成，写回 extra.gist。"""
    try:
        # 每个标签页的前列都要有：分类之外还有「X 长文」页
        tabs = {t: ranked(type_=t) for t in [*TYPES, "x_article"]}
        todo = gist.pick(ranked(), tabs, int(cfg("gist_top")), int(cfg("gist_per_type")))
        if not todo:
            return {"count": 0, "errors": []}
        got, errors = gist.generate(todo, model=str(cfg("gist_model")))
        for it in todo:
            if it["id"] in got:
                row = db.row("SELECT extra FROM feed_items WHERE id=?", [it["id"]])
                ex = {**_extra(row or {}), "gist": got[it["id"]], "gist_src": gist.gist_key(it)}
                db.execute("UPDATE feed_items SET extra=? WHERE id=?", [json.dumps(ex, ensure_ascii=False), it["id"]])
        return {"count": len(got), "errors": errors}
    except Exception as e:  # noqa: BLE001
        log.warning("feed gist failed: %s", e)
        return {"count": 0, "errors": [f"{type(e).__name__}: {str(e)[:200]}"]}


def run_product_analysis() -> dict:
    """给「产品」分类前列生成产品分析，写回 extra.pa。"""
    try:
        todo = pa.pick(ranked(type_="product"), int(cfg("product_analysis_top")))
        if not todo:
            return {"count": 0, "errors": []}
        got, errors = pa.generate(todo, model=str(cfg("gist_model")))
        for it in todo:
            if it["id"] in got:
                row = db.row("SELECT extra FROM feed_items WHERE id=?", [it["id"]])
                ex = {**_extra(row or {}), "pa": got[it["id"]], "pa_src": pa.pa_key(it)}
                db.execute("UPDATE feed_items SET extra=? WHERE id=?", [json.dumps(ex, ensure_ascii=False), it["id"]])
        return {"count": len(got), "errors": errors}
    except Exception as e:  # noqa: BLE001
        log.warning("feed product analysis failed: %s", e)
        return {"count": 0, "errors": [f"{type(e).__name__}: {str(e)[:200]}"]}


def _bg(only, gists=None):
    try:
        res = refresh_sync(only, gists)
    except Exception as e:  # noqa: BLE001
        res = {"_": {"count": 0, "errors": [str(e)]}}
    with _state_lock:
        _state.update(running=False, finished_at=db.now(), results=res)


class RefreshIn(BaseModel):
    sources: list[str] = []      # 空 = 全部
    type: str = ""               # 只刷这个分类的来源（TYPE_SOURCES），和 sources 二选一
    wait: bool = False           # true = 同步等结果（CLI / Agent 用）


@router.post("/gist")
def gist_now():
    """手动补一次中文一句话（不抓取），同步返回 {count, errors}。"""
    return run_gists()


@router.post("/refresh")
def refresh(body: RefreshIn | None = None):
    body = body or RefreshIn()
    if body.type and body.type not in TYPE_SOURCES:
        raise HTTPException(400, f"未知分类：{body.type}")
    only = TYPE_SOURCES[body.type] if body.type else (body.sources or None)
    gists = True if body.type else None
    if body.wait:
        res = refresh_sync(only, gists)
        with _state_lock:
            _state.update(finished_at=db.now(), results=res, scope=body.type)
        return status()
    start_refresh(only, gists, scope=body.type)
    return status()


def start_refresh(only=None, gists=None, scope: str = "") -> bool:
    """后台刷新；已有刷新在跑时不重复起（返回 False）。scope 记下这次刷的是哪个分类，页面据此显示。"""
    with _state_lock:
        if _state["running"]:
            return False
        _state.update(running=True, started_at=db.now(), results={}, scope=scope,
                      started_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"))   # 和 first_seen 同口径，列表置顶本次新增用
    threading.Thread(target=_bg, args=(only, gists), daemon=True).start()
    return True


# ---------- 关注源 ----------

def follow_groups() -> list[dict]:
    fc = follow_cfg()
    names = fc.get("names") or {}
    added = {lst: {follow.entry_key(lst, v) for v in vs} for lst, vs in (fc.get("add") or {}).items()}
    out = []
    for gid, g in follow.GROUPS.items():
        items = [{"list": lst, "key": follow.entry_key(lst, v), "label": follow.label(lst, v, names),
                  "custom": follow.entry_key(lst, v) in added.get(lst, set()),
                  "url": v.get("url") if isinstance(v, dict) else (v if lst in follow.URL_LISTS else "")}
                 for lst in g["lists"] for v in src_list(lst)]
        out.append({"id": gid, "label": g["label"], "hint": g["hint"], "items": items})
    return out


class FollowIn(BaseModel):
    group: str
    value: str


class UnfollowIn(BaseModel):
    list: str
    key: str


def _save_follow(fc: dict) -> None:
    settings.save({"feed": {"follow": fc}})


@router.get("/sources")
def sources():
    return {"groups": follow_groups()}


@router.post("/sources")
def add_source(body: FollowIn):
    """加关注源：解析输入（可能联网验证）→ 记进 feed.follow → 后台只刷这个来源。"""
    if body.group not in follow.GROUPS:
        raise HTTPException(400, f"未知类别：{body.group}")
    try:
        lst, entry, name = follow.resolve(body.group, body.value)
    except follow.FollowError as e:
        raise HTTPException(400, str(e)) from e
    except httpx.HTTPError as e:
        raise HTTPException(400, f"网络错误：{type(e).__name__}") from e
    key = follow.entry_key(lst, entry)
    exists = key in {follow.entry_key(lst, v) for v in src_list(lst)}
    fc = follow_cfg()
    rm = [k for k in (fc.get("remove") or {}).get(lst) or [] if k != key]
    patch: dict = {"remove": {lst: rm}, "names": {key: name}}
    if not exists and key not in {follow.entry_key(lst, v) for v in cfg(lst) or []}:
        patch["add"] = {lst: [*((fc.get("add") or {}).get(lst) or []), entry]}
    _save_follow(patch)
    started = start_refresh([follow.LIST_COLLECTOR[lst]], gists=True, scope=f"source:{lst}") if not exists else False
    return {"ok": True, "exists": exists, "list": lst, "key": key, "label": name, "refreshing": started,
            "groups": follow_groups()}


@router.post("/sources/remove")
def remove_source(body: UnfollowIn):
    """取消关注：自己加的直接删；默认名单里的记进 remove。已经抓到的条目留着，随时间自然沉下去。"""
    fc = follow_cfg()
    add = (fc.get("add") or {}).get(body.list) or []
    patch: dict = {}
    if any(follow.entry_key(body.list, v) == body.key for v in add):
        patch["add"] = {body.list: [v for v in add if follow.entry_key(body.list, v) != body.key]}
    if body.key in {follow.entry_key(body.list, v) for v in cfg(body.list) or []}:
        patch["remove"] = {body.list: sorted({*((fc.get("remove") or {}).get(body.list) or []), body.key})}
    if not patch:
        raise HTTPException(404, "没有这个关注源")
    _save_follow(patch)
    return {"ok": True, "groups": follow_groups()}


@router.get("/status")
def status():
    with _state_lock:
        st = json.loads(json.dumps(_state))
    st["total"] = (db.row("SELECT count(*) n FROM feed_items") or {}).get("n", 0)
    st["by_source"] = {r["source"]: r["n"] for r in db.rows("SELECT source, count(*) n FROM feed_items GROUP BY source")}
    st["last_fetched"] = (db.row("SELECT max(fetched_at) t FROM feed_items") or {}).get("t") or ""
    st["sources"] = source_health()
    st["auto_refresh_hours"] = cfg("auto_refresh_hours")
    st["feedback"] = feedback_stats()
    return st


def source_health() -> dict:
    """各来源：条数、最新发布日期、最近抓取时间、是否停更（最新条目早于 stale_source_days 天）。"""
    now = datetime.now(timezone.utc)
    out = {}
    for r in db.rows("SELECT source, count(*) n, max(date) latest, max(fetched_at) fetched FROM feed_items GROUP BY source"):
        d = rk._parse_dt(r["latest"] or "")
        age = (now - d).days if d else None
        out[r["source"]] = {"count": r["n"], "latest": r["latest"] or "", "fetched": r["fetched"] or "",
                            "latest_age_days": age, "stale": age is None or age > int(cfg("stale_source_days"))}
    return out


# ---------- 列表与反馈 ----------

def _public(x: dict) -> dict:
    return {k: x[k] for k in ("id", "source", "type", "title", "url", "date", "popularity", "score",
                              "why", "feedback", "also")} | {k: x.get(k) for k in ("new", "seen_days")} | {"summary": rk.display_summary(x["title"], x["summary"]),
                                                              "gist": (x.get("extra") or {}).get("gist", ""),
                                                              "extra": x.get("extra", {}),
                                                              "source_label": rk.SOURCE_LABEL.get(x["source"], x["source"])}


@router.get("/items")
def items(type: str = "", saved: bool = False, q: str = "", limit: int = 60, offset: int = 0, days: float = 0,
          sort: str = "score", since: str = ""):
    """since：刷新开始时间（status.started_utc），这之后第一次收进来的条目排到最前（刷完让人一眼看到新增）。"""
    if sort not in ("score", "new", "hot"):
        raise HTTPException(400, "sort 只能是 score / new / hot")
    out = ranked(type, saved, q, days=days, sort=sort)
    if t0 := rk._parse_dt(since):
        fresh = lambda x: (rk._parse_dt((x.get("extra") or {}).get("first_seen") or "") or datetime.min.replace(tzinfo=timezone.utc)) >= t0
        out = [x for x in out if fresh(x)] + [x for x in out if not fresh(x)]
    return {"total": len(out), "items": [_public(x) for x in out[offset: offset + limit]]}


class FeedbackIn(BaseModel):
    id: str
    vote: int | None = None      # 1 / -1 / 0
    saved: bool | None = None
    hidden: bool | None = None


@router.post("/feedback")
def feedback(body: FeedbackIn):
    if not db.row("SELECT id FROM feed_items WHERE id=?", [body.id]):
        raise HTTPException(404, "条目不存在")
    cur = db.row("SELECT * FROM feed_feedback WHERE item_id=?", [body.id]) or {"vote": 0, "saved": 0, "hidden": 0}
    new = {"vote": max(-1, min(1, body.vote)) if body.vote is not None else cur["vote"],
           "saved": int(body.saved) if body.saved is not None else cur["saved"],
           "hidden": int(body.hidden) if body.hidden is not None else cur["hidden"]}
    db.execute("INSERT INTO feed_feedback (item_id, vote, saved, hidden, updated_at) VALUES (?,?,?,?,?) "
               "ON CONFLICT(item_id) DO UPDATE SET vote=excluded.vote, saved=excluded.saved, hidden=excluded.hidden, "
               "updated_at=excluded.updated_at", [body.id, new["vote"], new["saved"], new["hidden"], db.now()])
    return {"id": body.id, **new}


class VerdictIn(BaseModel):
    id: str
    text: str = ""


@router.post("/verdict")
def verdict(body: VerdictIn):
    """读完一篇写一句话判断（值不值得跟、增量在哪、证据可不可信）；空字符串 = 删掉。当天的判断汇成知识库里的论文笔记。"""
    _ensure_cols()
    if not db.row("SELECT id FROM feed_items WHERE id=?", [body.id]):
        raise HTTPException(404, "条目不存在")
    text = body.text.strip()[:500]
    at = db.now() if text else ""
    db.execute("INSERT INTO feed_feedback (item_id, verdict, verdict_at, updated_at) VALUES (?,?,?,?) "
               "ON CONFLICT(item_id) DO UPDATE SET verdict=excluded.verdict, verdict_at=excluded.verdict_at, "
               "updated_at=excluded.updated_at", [body.id, text, at, db.now()])
    try:
        from .. import kb
        from . import _habits
        _habits.sync_paper_task(db.today())
        kb.schedule_sync()
    except Exception:  # noqa: BLE001
        pass
    return {"id": body.id, "verdict": text, "verdict_at": at}


def paper_notes(date: str) -> list[dict]:
    """某天写了一句话判断的条目（每日论文习惯的证据）。"""
    _ensure_cols()
    return db.rows("SELECT i.id, i.type, i.title, i.url, i.source, i.date, f.verdict, f.verdict_at FROM feed_feedback f "
                   "JOIN feed_items i ON i.id=f.item_id WHERE f.verdict<>'' AND substr(f.verdict_at,1,10)=? ORDER BY f.verdict_at", [date])


class ClickIn(BaseModel):
    id: str


@router.post("/click")
def click(body: ClickIn):
    """打开原文链接时前端上报一次；只做统计（转化漏斗），不参与排序。"""
    _ensure_cols()
    if not db.row("SELECT id FROM feed_items WHERE id=?", [body.id]):
        raise HTTPException(404, "条目不存在")
    db.execute("INSERT INTO feed_feedback (item_id, clicks, last_click, updated_at) VALUES (?,1,?,?) "
               "ON CONFLICT(item_id) DO UPDATE SET clicks=coalesce(clicks,0)+1, last_click=excluded.last_click",
               [body.id, db.now(), db.now()])
    return {"id": body.id, "ok": True}


def feedback_stats() -> dict:
    _ensure_cols()
    r = db.row("SELECT sum(vote>0) likes, sum(vote<0) dislikes, sum(saved) saved, sum(hidden) hidden, "
               "sum(coalesce(clicks,0)) clicks, sum(coalesce(clicks,0)>0) clicked_items FROM feed_feedback") or {}
    out = {k: int(r.get(k) or 0) for k in ("likes", "dislikes", "saved", "hidden", "clicks", "clicked_items")}
    out["deep_reads"] = deep_reads()
    return out


def deep_reads() -> int:
    """从推荐进了深读的条目数：learn_items 的 url 与 feed 条目（或其 arXiv id）一致。"""
    try:
        urls = {rk.norm_url(r["url"]) for r in db.rows("SELECT url FROM learn_items")}
    except Exception:  # noqa: BLE001  学习模块不存在
        return 0
    urls.discard("")
    if not urls:
        return 0
    return sum(1 for r in db.rows("SELECT url FROM feed_items") if rk.norm_url(r["url"]) in urls)


@router.get("/config")
def config():
    return {k: cfg(k) for k in ("interests", "half_life_hours", "hn_queries", "github_queries", "reddit", "x_days",
                                "x_min_likes", "x_per_account", "producthunt_days", "yc_days", "trustmrr_days", "sources", "github_min_stars",
                                "github_trending_languages", "github_watch_orgs", "github_watch_min_stars",
                                "reddit_queries", "youtube_channels", "youtube_queries", "bilibili", "video_days")} | {
        k: settings.get(f"feed.{k}", []) for k in ("rss", "sites", "podcasts", "xiaoyuzhou", "product_rss", "rsshub_bases", "x_accounts", "x_queries")} | {"types": TYPES}


# ---------- 定时刷新 ----------

def _stale_hours() -> float:
    """距上次抓取的小时数；fetched_at 是 db.now() 写的本地时间（不带时区）。"""
    last = (db.row("SELECT max(fetched_at) t FROM feed_items") or {}).get("t") or ""
    try:
        d = datetime.fromisoformat(last)
    except ValueError:
        return float("inf")
    now = datetime.now(d.tzinfo) if d.tzinfo else datetime.now()
    return (now - d).total_seconds() / 3600


def maybe_auto_refresh() -> bool:
    """数据超过 auto_refresh_hours 就起一次后台刷新；返回是否启动了。"""
    hours = float(cfg("auto_refresh_hours") or 0)
    if hours <= 0 or _stale_hours() < hours:
        return False
    if not start_refresh():
        return False
    log.info("feed auto refresh started (data older than %sh)", hours)
    return True


def _auto_loop():
    time.sleep(90)  # 启动后先等一会儿，别和服务启动抢资源
    while True:
        try:
            maybe_auto_refresh()
        except Exception as e:  # noqa: BLE001
            log.warning("feed auto refresh check failed: %s", e)
        time.sleep(600)


def on_startup():
    if os.environ.get("SELF_STARTUP_NO_AUTOREFRESH"):
        return
    threading.Thread(target=_auto_loop, daemon=True, name="feed-auto-refresh").start()


# ---------- Agent ----------

def agent_context(ref: str) -> str:
    top = ranked()[:30]
    lines = [f"兴趣词：{', '.join(cfg('interests') or [])}",
             f"反馈统计（clicks=打开原文次数，deep_reads=进了深读的条目）：{json.dumps(feedback_stats(), ensure_ascii=False)}；"
             f"库内共 {status()['total']} 条",
             "停更的来源：" + ("、".join(f"{k}（最新 {v['latest'][:10] or '无日期'}）" for k, v in source_health().items()
                                     if v["stale"]) or "无"),
             "", "## 当前排序前 30（标题 | 类型 | 推荐理由 | 链接 | 简介）"]
    for i, x in enumerate(top, 1):
        lines.append(f"{i}. [{x['id']}] {x['title']} | {TYPES.get(x['type'], x['type'])} | {x['why'] or '-'} | "
                     f"{x['url']} | {src.clean(x['summary'], 120)}")
    return "\n".join(lines)
