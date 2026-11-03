"""论文脉络库的采集与入库门槛（设计稿 docs/designs/2026-11-02-paper-map-design.md §2、§3）。

- 数据源：Semantic Scholar（S2）Graph API。OpenAlex 把 arXiv 预印本和会议版拆成两条、且不解析 arXiv 参考文献
  （实测 DPO 被引 293 vs S2 11,470，InstructGPT 参考文献 0 条），只能当补充。
- 候选：按主题的检索式走 S2 bulk search（按引用排序，每页 1000），外加近 6 个月新论文一页、信息推荐里的论文。
- 入库门槛随年龄收紧：≤6 个月看早期信号（引用 / 高影响力引用 / 信息推荐热度）再过 Jev 水文判断；
  6–24 个月引用 ≥ 60；2–5 年 ≥ 250；5 年以上 ≥ 1000。只收 arXiv 论文。
- 工业界论文（摘要里写了大厂名字 + 线上部署 / A/B / 工业场景）门槛打对折：被引天然比学术热点少，但值得收录。
- 经典回拉：被库内论文引用 ≥ CLASSIC_REFS 次、总被引 ≥ CLASSIC_MIN_CITES 的参考文献（含非 arXiv，如 PPO 之前的 RL 经典）也入库。
- 详情（摘要、TLDR、参考文献）只给入库的论文取，S2 batch 100 篇一次。
没有 SEMANTIC_SCHOLAR_API_KEY（或 S2_API_KEY）时走公共限流池（常 429，靠退避重试），有 key 时每秒 1 次。
"""
from __future__ import annotations

import json
import logging
import math
import os
import random
import re
import threading
import time
from datetime import datetime

import httpx

from .. import db

log = logging.getLogger(__name__)

S2 = "https://api.semanticscholar.org/graph/v1"
SEARCH_FIELDS = "title,year,publicationDate,citationCount,influentialCitationCount,venue,externalIds"
DETAIL_FIELDS = ("title,abstract,tldr,venue,year,publicationDate,citationCount,influentialCitationCount,externalIds,"
                 "authors.name,references.paperId")
DETAIL_BATCH = 200
TRIES = 14
TRIES_NO_KEY = 60          # 公共池高峰期可能连续几十分钟 429，没 key 时耐心等
# (年龄上限·月, 引用门槛)；最近一档没有门槛，看早期信号 + Jev
TIERS = [(6, "recent", None), (24, "young", 60), (60, "mid", 250), (10_000, "old", 1000)]
RECENT_MIN_CITES, RECENT_MIN_INFL = 15, 3
JUNK_DROP = 0.5            # Jev 判「水文」概率 ≥ 这个的近期论文不入库
CLASSIC_REFS, CLASSIC_MIN_CITES = 8, 500
NEAR, NEAR_INFL_RATIO = 0.8, 0.15
INDUSTRY_FACTOR = 0.5
COMPANY = re.compile(r"\b(google|deepmind|youtube|meta|facebook|instagram|microsoft|bing|amazon|apple|netflix|linkedin|pinterest|"
                     r"spotify|airbnb|uber|snap|twitter|alibaba|taobao|tmall|alipay|ant group|tencent|wechat|bytedance|douyin|"
                     r"tiktok|kuaishou|meituan|baidu|jd\.com|huawei|xiaohongshu|rednote|shopee|didi|pinduoduo|ele\.me)\b", re.I)
DEPLOY = re.compile(r"deploy|online a/b|a/b test|industrial|in production|production (?:system|environment|traffic)|"
                    r"serv(?:es|ing) (?:hundreds of )?(?:millions|billions)|daily active users|real-world traffic", re.I)   # 被引到门槛 80% 且高影响力引用占比 ≥ 15%（平均约 11%）也收：被引不多但多是实质引用

SCHEMA = """
CREATE TABLE IF NOT EXISTS paper_items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,   -- 也是 paper_fts 的 rowid
    s2id        TEXT UNIQUE NOT NULL,
    arxiv       TEXT DEFAULT '',                     -- 和信息推荐 feed_items 的 arxiv:<id> 互相引用
    title       TEXT DEFAULT '',
    abstract    TEXT DEFAULT '',
    tldr        TEXT DEFAULT '',
    year        INTEGER,
    pub_date    TEXT DEFAULT '',
    venue       TEXT DEFAULT '',
    cites       INTEGER DEFAULT 0,
    infl        INTEGER DEFAULT 0,                   -- S2 高影响力引用
    refs        TEXT DEFAULT '[]',                   -- 参考文献 s2id（全部，库内边在用的时候再过滤）
    authors     TEXT DEFAULT '[]',
    status      TEXT DEFAULT 'cand',                 -- cand 候选 / in 入库 / out 不够门槛
    tier        TEXT DEFAULT '',                     -- recent / young / mid / old / classic
    why         TEXT DEFAULT '',                     -- 入库或落选的原因
    junk        REAL,                                -- Jev：是水文的概率（只问近期论文）
    hot         INTEGER DEFAULT 0,                   -- 信息推荐里出现过（HF / AlphaXiv 热度或用户收藏）
    src         TEXT DEFAULT '',                     -- 哪个主题检索 / ref / feed 进来的
    detail_at   TEXT,                                -- NULL = 还没取详情
    first_seen  TEXT,
    updated     TEXT
);
CREATE INDEX IF NOT EXISTS idx_paper_status ON paper_items(status);
CREATE INDEX IF NOT EXISTS idx_paper_arxiv ON paper_items(arxiv);
CREATE TABLE IF NOT EXISTS paper_labels (
    s2id        TEXT PRIMARY KEY,
    k TEXT, d TEXT, d2 TEXT DEFAULT '[]',
    problem     TEXT DEFAULT '[]',
    method      TEXT DEFAULT '[]',
    bench       TEXT DEFAULT '[]',
    base        TEXT DEFAULT '[]',
    builds_on   TEXT DEFAULT '[]',                   -- s2id，只能是它的库内参考文献
    s           TEXT DEFAULT '',
    tax_ver     TEXT, label_src TEXT, labeled_at TEXT
);
CREATE VIRTUAL TABLE IF NOT EXISTS paper_fts USING fts5(title, s, tags, abstract, tokenize='trigram');
CREATE TABLE IF NOT EXISTS paper_maps (
    topic       TEXT PRIMARY KEY,                    -- 归一化后的主题
    result      TEXT,                                -- 脉络 JSON
    cost        REAL DEFAULT 0,
    created     TEXT
);
"""


# ---------- S2 客户端 ----------

_lock = threading.Lock()
_last = [0.0]
usage = {"calls": 0, "retries": 0}


def _headers() -> dict:
    key = (os.environ.get("SEMANTIC_SCHOLAR_API_KEY") or os.environ.get("S2_API_KEY") or "").strip()
    return {"x-api-key": key} if key else {}


def _req(method: str, path: str, client: httpx.Client, **kw) -> dict | list:
    """限速 + 429 / 5xx 退避重试。有 key 时每秒 1 次；公共池常 429，退避到 60 秒封顶。"""
    gap = 1.05 if _headers() else 0.5
    for n in range(TRIES if _headers() else TRIES_NO_KEY):
        with _lock:
            wait = _last[0] + gap - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            _last[0] = time.monotonic()
        try:
            r = client.request(method, S2 + path, headers=_headers(), **kw)
        except httpx.HTTPError as e:
            log.info("S2 %s 网络错误 %s，重试", path, e)
            r = None
        if r is not None and r.status_code == 200:
            usage["calls"] += 1
            return r.json()
        if r is not None and r.status_code not in (429, 500, 502, 503, 504):
            raise RuntimeError(f"S2 {path} {r.status_code}: {r.text[:200]}")
        usage["retries"] += 1
        time.sleep(min(60, 2 * 1.6 ** n) + random.random() * 2)
    raise RuntimeError(f"S2 {path} 重试 {n + 1} 次仍失败")


def client() -> httpx.Client:
    return httpx.Client(timeout=httpx.Timeout(90.0, connect=15.0))


def search_bulk(query: str, c: httpx.Client, pages: int = 2, year: str = "", min_cites: int = 0) -> list[dict]:
    """S2 bulk search，计算机领域、按引用排序，每页 1000 条。query 用 S2 的布尔语法（| 或、"" 短语）。"""
    params = {"query": query, "fields": SEARCH_FIELDS, "fieldsOfStudy": "Computer Science", "sort": "citationCount:desc"}
    if year:
        params["year"] = year
    if min_cites:
        params["minCitationCount"] = str(min_cites)
    out, token = [], None
    for _ in range(pages):
        if token:
            params["token"] = token
        d = _req("GET", "/paper/search/bulk", c, params=params)
        out += d.get("data") or []
        token = d.get("token")
        if not token:
            break
    return out


def batch(ids: list[str], c: httpx.Client, fields: str = DETAIL_FIELDS) -> list[dict | None]:
    return _req("POST", "/paper/batch", c, params={"fields": fields}, json={"ids": ids})


# ---------- 入库 ----------

def _arxiv(p: dict) -> str:
    return ((p.get("externalIds") or {}).get("ArXiv") or "").strip()


def upsert(p: dict, src: str) -> None:
    """检索结果或详情 → paper_items。已有的只刷新数字和缺的字段，src 追加。"""
    if not p or not p.get("paperId"):
        return
    now = db.now()
    cur = db.row("SELECT id, src FROM paper_items WHERE s2id=?", [p["paperId"]])
    f = {"arxiv": _arxiv(p), "title": (p.get("title") or "")[:300], "year": p.get("year"),
         "pub_date": p.get("publicationDate") or (f"{p['year']}-07-01" if p.get("year") else ""),
         "venue": (p.get("venue") or "")[:120], "cites": p.get("citationCount") or 0,
         "infl": p.get("influentialCitationCount") or 0, "updated": now}
    if "abstract" in p or "references" in p:
        f |= {"abstract": (p.get("abstract") or "")[:3000], "tldr": ((p.get("tldr") or {}).get("text") or "")[:500],
              "refs": json.dumps([r["paperId"] for r in p.get("references") or [] if r and r.get("paperId")]),
              "authors": json.dumps([a.get("name") for a in (p.get("authors") or [])[:6]], ensure_ascii=False),
              "detail_at": now}
    if cur:
        srcs = [s for s in (cur["src"] or "").split(",") if s]
        if src and src not in srcs:
            srcs.append(src)
        f["src"] = ",".join(srcs)
        db.execute(f"UPDATE paper_items SET {','.join(k + '=?' for k in f)} WHERE id=?", [*f.values(), cur["id"]])
    else:
        db.insert("paper_items", f | {"s2id": p["paperId"], "src": src, "first_seen": now})


def age_months(pub_date: str, today: datetime | None = None) -> float:
    try:
        d = datetime.fromisoformat((pub_date or "")[:10])
    except ValueError:
        return 10_000
    return ((today or datetime.now()) - d).days / 30.44


def decide(r: dict, today: datetime | None = None) -> tuple[str, str, str]:
    """一条候选 → (status, tier, why)。不含经典回拉（要看库内引用，见 pull_classics）。"""
    if not r.get("arxiv"):
        return "out", "", "不是 arXiv 论文"
    m = age_months(r.get("pub_date") or "", today)
    for cap, tier, need in TIERS:
        if m <= cap:
            break
    ind = industrial(r)
    if need is None:
        sig = r.get("hot") or (r.get("cites") or 0) >= RECENT_MIN_CITES or (r.get("infl") or 0) >= RECENT_MIN_INFL
        if not sig:
            return "out", tier, "近 6 个月，没有早期信号"
        if r.get("junk") is not None and r["junk"] >= JUNK_DROP:
            return "out", tier, f"Jev 判为水文（{r['junk']:.2f}）"
        return "in", tier, "近 6 个月，有早期信号" + ("（信息推荐热门）" if r.get("hot") else "")
    if (r.get("cites") or 0) >= need:
        return "in", tier, f"{tier}：被引 {r['cites']} ≥ {need}"
    if ind and (r.get("cites") or 0) >= need * INDUSTRY_FACTOR:
        return "in", tier, f"{tier}：工业界论文，被引 {r['cites']} ≥ {int(need * INDUSTRY_FACTOR)}"
    c, infl = r.get("cites") or 0, r.get("infl") or 0
    if c >= NEAR * need and infl >= NEAR_INFL_RATIO * c:
        return "in", tier, f"{tier}：被引 {c} 接近 {need}，高影响力引用占 {infl / c:.0%}"
    return "out", tier, f"{tier}：被引 {r.get('cites') or 0} < {need}"


def industrial(r: dict) -> bool:
    """摘要 / 标题里有大厂名字且写了线上部署、A/B、工业场景。没取过详情（没摘要）的只看标题。"""
    text = f"{r.get('title') or ''} {r.get('abstract') or ''}"
    return bool(COMPANY.search(text) and DEPLOY.search(text)) or "industrial" in (r.get("title") or "").lower()


def admit_all(today: datetime | None = None) -> dict:
    """按门槛重新判全部候选。经典回拉的和用户补充的（tier=manual）不动。
    已入库的只会因为 Jev 判水文被踢出去：论文变老门槛变高（半年内 → 1–2 年要被引 60）不踢，免得脉络里的论文突然消失。"""
    n = {"in": 0, "out": 0}
    for r in db.rows("SELECT * FROM paper_items WHERE COALESCE(tier,'') NOT IN ('classic','manual')"):
        st, tier, why = decide(r, today)
        if r["status"] == "in" and st == "out" and not why.startswith("Jev"):
            n["in"] += 1
            continue
        if (st, tier, why) != (r["status"], r["tier"], r["why"]):
            db.execute("UPDATE paper_items SET status=?, tier=?, why=? WHERE id=?", [st, tier, why, r["id"]])
        n[st] += 1
    return n


ARXIV_ID = re.compile(r"(?<![\d.])(\d{4}\.\d{4,5})(?:v\d+)?(?![\d.])")


def feed_arxiv_ids(days: float = 0) -> set[str]:
    """信息推荐里的论文的 arXiv 编号：AlphaXiv（arxiv:<id>）和 HF 每日论文（hf:<id>，HF 的论文页编号就是 arXiv 编号）。
    days>0 只要最近 days 天进来的。"""
    since = f" AND fetched_at >= datetime('now', '-{float(days)} days')" if days else ""
    try:
        rows = db.rows(f"SELECT id FROM feed_items WHERE (id LIKE 'arxiv:%' OR id LIKE 'hf:%'){since}")
    except Exception:  # noqa: BLE001  原型库里可能没有 feed_items
        return set()
    return {m[1] for r in rows if (m := ARXIV_ID.fullmatch(r["id"].split(":", 1)[1]))}


def mark_hot() -> int:
    """信息推荐里出现过的论文（HF 每日论文 / AlphaXiv / 收藏）记 hot，作为近期论文的早期信号。"""
    ids = feed_arxiv_ids()
    if not ids:
        return 0
    n = 0
    for r in db.rows("SELECT id, arxiv FROM paper_items WHERE arxiv!='' AND hot=0"):
        if r["arxiv"] in ids:
            db.execute("UPDATE paper_items SET hot=1 WHERE id=?", [r["id"]])
            n += 1
    return n


def near_industry() -> list[str]:
    """被引够工业界门槛、但还没取详情（看不到摘要、判不了是不是工业界）的落选 arXiv 论文。"""
    need = {t: n for _, t, n in TIERS if n}
    return [r["s2id"] for r in db.rows("SELECT s2id, tier, cites FROM paper_items WHERE status='out' AND arxiv!='' "
                                       "AND detail_at IS NULL") if r["tier"] in need
            and r["cites"] >= need[r["tier"]] * INDUSTRY_FACTOR]


def fetch_details(c: httpx.Client, on_page=None, ids: list[str] | None = None) -> int:
    """给入库但还没取详情的论文（或传入的 ids）取摘要、TLDR、参考文献。"""
    todo = ids if ids is not None else [
        r["s2id"] for r in db.rows("SELECT s2id FROM paper_items WHERE status='in' AND detail_at IS NULL")]
    for i in range(0, len(todo), DETAIL_BATCH):
        for p in batch(todo[i:i + DETAIL_BATCH], c):
            upsert(p, "")
        if on_page:
            on_page(min(i + DETAIL_BATCH, len(todo)), len(todo))
    return len(todo)


def pull_classics(c: httpx.Client) -> list[str]:
    """被库内论文引用 ≥ CLASSIC_REFS 次的参考文献：总被引够高就作为经典入库（不要求 arXiv）。返回新拉进来的 s2id。
    只数非经典论文的引用：经典自己的参考文献不算，否则每跑一次就多拉一代（滚雪球）；已入库但不再满足的经典退回 out。"""
    cnt: dict[str, int] = {}
    for r in db.rows("SELECT refs FROM paper_items WHERE status='in' AND COALESCE(tier,'')!='classic'"):
        for s in set(json.loads(r["refs"] or "[]")):
            cnt[s] = cnt.get(s, 0) + 1
    for r in db.rows("SELECT * FROM paper_items WHERE status='in' AND tier='classic'"):
        if cnt.get(r["s2id"], 0) < CLASSIC_REFS:      # 撤回经典身份，按普通门槛重判（arXiv 论文被引够也照样入库）
            st, tier, why = decide(r)
            db.execute("UPDATE paper_items SET status=?, tier=?, why=? WHERE id=?", [st, tier, why, r["id"]])
    have = {r["s2id"] for r in db.rows("SELECT s2id FROM paper_items WHERE status='in'")}
    want = [s for s, k in cnt.items() if k >= CLASSIC_REFS and s not in have]
    got = []
    for i in range(0, len(want), DETAIL_BATCH):
        for p in batch(want[i:i + DETAIL_BATCH], c):
            if p and (p.get("citationCount") or 0) >= CLASSIC_MIN_CITES:
                upsert(p, "ref")
                db.execute("UPDATE paper_items SET status='in', tier='classic', why=? WHERE s2id=?",
                           [f"经典回拉：库内 {cnt[p['paperId']]} 篇引用，总被引 {p['citationCount']}", p["paperId"]])
                got.append(p["paperId"])
    return got


def in_corpus_edges() -> list[tuple[str, str]]:
    """库内引用边 (引用方, 被引方)。"""
    have = {r["s2id"] for r in db.rows("SELECT s2id FROM paper_items WHERE status='in'")}
    out = []
    for r in db.rows("SELECT s2id, refs FROM paper_items WHERE status='in'"):
        out += [(r["s2id"], t) for t in json.loads(r["refs"] or "[]") if t in have and t != r["s2id"]]
    return out


def slices(today: datetime | None = None, pages: int = 3) -> list[tuple[str, str, int, int]]:
    """(名字, S2 year 参数, minCitationCount, 页数)：按引用排序时每个年龄段各取一截，避免老论文把新论文挤掉。
    门槛见 TIERS（young ≥60 / mid ≥250 / old ≥1000），按自然年切会有重叠，入库与否由 decide 按发表日期判。"""
    y, f = (today or datetime.now()).year, INDUSTRY_FACTOR     # 检索按工业界门槛（对折）取，入库再由 decide 分
    return [("old", f"-{y - 5}", int(1000 * f), pages), ("mid", f"{y - 5}-{y - 2}", int(250 * f), pages),
            ("young", f"{y - 2}-{y}", int(60 * f), pages), ("recent", f"{y - 1}-", 0, 1)]


def collect_topic(name: str, queries: list[str], c: httpx.Client, pages: int = 2) -> int:
    """一个主题的候选：每个检索式按引用取 pages 页，再取近 6 个月的一页（按引用排序时新论文排不上来）。"""
    n = 0
    recent = str(datetime.now().year - (1 if datetime.now().month <= 6 else 0)) + "-"
    for q in queries:
        for p in search_bulk(q, c, pages=pages):
            upsert(p, name)
            n += 1
        for p in search_bulk(q, c, pages=1, year=recent):
            upsert(p, name)
            n += 1
    return n


def stats() -> dict:
    by = {f"{r['status']}/{r['tier'] or '-'}": r["n"] for r in
          db.rows("SELECT status, tier, COUNT(*) n FROM paper_items GROUP BY status, tier")}
    return {"by": by, "edges": len(in_corpus_edges()), "s2": dict(usage)}


def log10p(x: int) -> float:
    return math.log10(1 + max(0, x or 0))
