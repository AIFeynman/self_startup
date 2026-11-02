"""开源雷达的采集：stars ≥ 1000 的 GitHub 仓库全量库（设计稿 docs/designs/2026-11-01-oss-radar-design.md §2、§2.1、§7.1）。

- 全量：按 star 区间切片走 Search API（每个查询最多 1000 条，超了就把区间对半切）。
- 每天新增：门槛段 1000..1100 做差 + 最近 7 天新建的高星 + 信息推荐 feed_items 里 ≥1000★ 的仓库（第三路，免费补充）。
- 每周刷新：GraphQL 按 node_id 批量查 star / push / 归档 / 改名，查不到的标「已失效」，30 天后清掉。
- README 摘录：GraphQL 批量取，清掉徽章 / 图片 / HTML，留前 1500 字给标注用。

GitHub 请求头、HTTP 客户端、文本清洗、字段映射从信息推荐的 _feed_sources 直接 import，不复制。
"""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timedelta

import httpx

from .. import db
from ._feed_sources import _client, _days_ago, clean, gh_headers, repo_base

log = logging.getLogger(__name__)

MIN_STARS = 1000          # 入库门槛
KEEP_STARS = 900          # 已在库的跌破这个才移出检索（避免门槛附近来回进出）
README_MAX = 1500
GONE_PURGE_DAYS = 30
SEARCH_CAP = 1000         # Search API 单个查询最多翻到 1000 条
GQL_BATCH = 50

SCHEMA = """
CREATE TABLE IF NOT EXISTS oss_repos (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,   -- 也是 oss_fts 的 rowid
    name        TEXT UNIQUE NOT NULL,                -- owner/repo（和 feed_items 的 github:owner/repo 互相引用）
    node_id     TEXT DEFAULT '',
    stars       INTEGER DEFAULT 0,
    lang        TEXT DEFAULT '',
    topics      TEXT DEFAULT '[]',
    descr       TEXT DEFAULT '',
    readme      TEXT DEFAULT '',                     -- 清洗后的 README 前 1500 字
    readme_oid  TEXT,                                -- NULL = 还没取过；'' = 没有 README
    created     TEXT DEFAULT '',
    pushed      TEXT DEFAULT '',
    archived    INTEGER DEFAULT 0,
    status      TEXT DEFAULT 'ok',                   -- ok / gone（GitHub 上查不到了）
    gone_at     TEXT DEFAULT '',
    src         TEXT DEFAULT '',                     -- slice / new / feed
    first_seen  TEXT,
    updated     TEXT
);
CREATE INDEX IF NOT EXISTS idx_oss_repos_stars ON oss_repos(stars);
CREATE TABLE IF NOT EXISTS oss_labels (
    name        TEXT PRIMARY KEY,
    k           TEXT, d TEXT, d2 TEXT DEFAULT '[]', ai TEXT,
    t           TEXT DEFAULT '[]',                   -- 功能标签
    s           TEXT DEFAULT '',                     -- 中文一句话
    tax_ver     TEXT, label_src TEXT,                -- 分类体系版本、输入哈希（内容不变不重复问）
    readme_oid  TEXT DEFAULT '', stars_at TEXT DEFAULT '0',
    labeled_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_oss_labels_d ON oss_labels(d);
CREATE VIRTUAL TABLE IF NOT EXISTS oss_fts USING fts5(name, s, t, descr, topics, tokenize='trigram');
CREATE TABLE IF NOT EXISTS oss_query_cache (
    key         TEXT PRIMARY KEY,                    -- 规范化后的查询
    intent      TEXT DEFAULT '{}',
    scores      TEXT DEFAULT '{}',                   -- {name: [精排分, 理由]}
    created     TEXT
);
-- 长任务（全量采集 / 标注 / 每日 / 每周）：在独立进程里跑，状态写这里，页面轮询
CREATE TABLE IF NOT EXISTS oss_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task        TEXT NOT NULL,
    status      TEXT DEFAULT 'running',              -- running / done / failed / stopped
    pid         INTEGER,
    progress    TEXT DEFAULT '{}',
    log         TEXT DEFAULT '',
    started     TEXT, finished TEXT
);
"""


# ---------- 入库 ----------

def upsert(raws: list[dict], src: str) -> list[str]:
    """REST 仓库对象写进 oss_repos，返回新入库的名字。fork 和低于门槛的新仓库不收。"""
    new = []
    now = db.now()
    for it in raws:
        if not it or not it.get("full_name"):
            continue
        b = repo_base(it)
        old = db.row("SELECT id, name FROM oss_repos WHERE name=? OR (node_id!='' AND node_id=?)", [b["name"], b["node_id"]])
        if old:
            db.execute("UPDATE oss_repos SET name=?, node_id=?, stars=?, lang=?, topics=?, descr=?, pushed=?, archived=?, "
                       "status='ok', gone_at='', updated=? WHERE id=?",
                       [b["name"], b["node_id"], b["stars"], b["lang"], json.dumps(b["topics"], ensure_ascii=False), b["desc"],
                        b["pushed"], int(b["archived"]), now, old["id"]])
            continue
        if b["fork"] or b["stars"] < MIN_STARS:
            continue
        db.insert("oss_repos", {"name": b["name"], "node_id": b["node_id"], "stars": b["stars"], "lang": b["lang"],
                                "topics": b["topics"], "descr": b["desc"], "created": b["created"], "pushed": b["pushed"],
                                "archived": int(b["archived"]), "src": src, "first_seen": now, "updated": now})
        new.append(b["name"])
    return new


# ---------- Search API 切片 ----------

def _search(c: httpx.Client, q: str, page: int) -> dict:
    for attempt in range(4):
        r = c.get("https://api.github.com/search/repositories", headers=gh_headers(),
                  params={"q": q, "sort": "stars", "order": "desc", "per_page": 100, "page": page})
        if r.status_code in (403, 429):    # 限流：搜索接口 30 次/分钟
            wait = int(r.headers.get("retry-after") or 0) or max(5, int(r.headers.get("x-ratelimit-reset", 0)) - int(time.time()) + 1)
            time.sleep(min(wait, 70))
            continue
        if r.status_code == 422:            # 第 11 页以后
            return {"total_count": 0, "items": []}
        r.raise_for_status()
        return r.json()
    raise RuntimeError(f"GitHub 搜索一直被限流：{q}")


def fetch_range(c: httpx.Client, lo: int, hi: int | None, extra: str = "", on_page=None) -> list[dict]:
    """拉 stars 在 [lo, hi] 的仓库；结果超过 1000 条就对半切区间递归。hi=None 表示不设上限。"""
    rng = f"{lo}..{hi}" if hi is not None else f">={lo}"
    q = f"stars:{rng} fork:false {extra}".strip()
    first = _search(c, q, 1)
    total = first.get("total_count", 0)
    if total > SEARCH_CAP and (hi is None or hi > lo):
        if hi is None:
            # 不设上限的那段：以第一页最低 star 附近为界先拆出头部
            top = max(lo + 1, min(int(x.get("stargazers_count") or 0) for x in first["items"]) if first.get("items") else lo * 2)
            return fetch_range(c, lo, top - 1, extra, on_page) + fetch_range(c, top, None, extra, on_page)
        mid = (lo + hi) // 2
        return fetch_range(c, lo, mid, extra, on_page) + fetch_range(c, mid + 1, hi, extra, on_page)
    items = list(first.get("items") or [])
    page = 2
    while len(items) < min(total, SEARCH_CAP):
        got = _search(c, q, page).get("items") or []
        if not got:
            break
        items += got
        page += 1
    if on_page:
        on_page(rng, len(items))
    return items


def collect_all(on_page=None) -> dict:
    """全量：stars ≥ 1000 全部拉一遍入库。约 6.6 万个，几百次搜索，受 30 次/分钟限流，约 20-40 分钟。"""
    n_new = n_seen = 0
    with _client() as c:
        # 分段从低到高，每段拉完就入库（中途断了已入库的不白拉）
        bounds = [1000, 1100, 1200, 1350, 1500, 1700, 2000, 2400, 3000, 4000, 6000, 10000, 20000, None]
        for lo, hi in zip(bounds, bounds[1:] + [None]):
            if lo is None:
                break
            raws = fetch_range(c, lo, (hi - 1) if hi else None, on_page=on_page)
            n_seen += len(raws)
            n_new += len(upsert(raws, "slice"))
    return {"seen": n_seen, "new": n_new}


def collect_new(on_page=None) -> dict:
    """每天新增：门槛段做差、最近 7 天新建的高星、信息推荐里抓到的高星仓库。"""
    out = {}
    with _client() as c:
        raws = fetch_range(c, MIN_STARS, 1100, on_page=on_page)
        out["threshold"] = len(upsert(raws, "new"))
        since = _days_ago(7).strftime("%Y-%m-%d")
        out["created_7d"] = len(upsert(fetch_range(c, MIN_STARS, None, f"created:>={since}", on_page), "new"))
        out["feed"] = len(upsert(_from_feed(c), "feed"))
    return out


def _from_feed(c: httpx.Client) -> list[dict]:
    """信息推荐 feed_items 里 source=github、≥1000★、雷达库里还没有的仓库。"""
    try:
        rows = db.rows("SELECT id FROM feed_items WHERE source='github' AND popularity>=?", [MIN_STARS])
    except Exception:  # noqa: BLE001  信息推荐的表不在（单独测试时）
        return []
    have = {r["name"] for r in db.rows("SELECT name FROM oss_repos")}
    out = []
    for r in rows:
        name = r["id"].split(":", 1)[1]
        if name in have:
            continue
        resp = c.get(f"https://api.github.com/repos/{name}", headers=gh_headers())
        if resp.status_code == 200:
            out.append(resp.json())
    return out


# ---------- GraphQL：README、刷新 ----------

README_PATHS = ("README.md", "readme.md", "README.rst", "README", "Readme.md", "README.markdown")
_REPO_FIELDS = """id nameWithOwner stargazerCount pushedAt isArchived isFork description
  primaryLanguage { name } repositoryTopics(first: 20) { nodes { topic { name } } }"""


def _readme_fields(with_text: bool) -> str:
    body = "oid text" if with_text else "oid"
    return " ".join(f'r{i}: object(expression: "HEAD:{p}") {{ ... on Blob {{ {body} }} }}' for i, p in enumerate(README_PATHS))


class GqlTimeout(RuntimeError):
    """GitHub 算不完返回 502 / 504：多半是一次查的仓库太多，拆小了再查。"""


def _gql(c: httpx.Client, query: str, variables: dict) -> dict:
    h = gh_headers()
    if "Authorization" not in h:
        raise RuntimeError("GraphQL 需要 GITHUB_TOKEN（项目根目录 .env）")
    for attempt in range(4):
        r = c.post("https://api.github.com/graphql", headers=h, json={"query": query, "variables": variables})
        if r.status_code in (502, 504):
            if attempt >= 1:
                raise GqlTimeout(f"GraphQL {r.status_code}")
            time.sleep(5)
            continue
        if r.status_code in (403, 429):
            time.sleep(10 * (attempt + 1))
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError("GraphQL 一直失败")


def gql_nodes(c: httpx.Client, node_ids: list[str], with_text: bool) -> dict[str, dict | None]:
    """node_id → 仓库信息（含 README oid / 文本）；查不到的（删了 / 转私有）值为 None。GitHub 超时就对半拆开再查。"""
    q = f"query($ids: [ID!]!) {{ nodes(ids: $ids) {{ ... on Repository {{ {_REPO_FIELDS} {_readme_fields(with_text)} }} }} }}"
    try:
        data = _gql(c, q, {"ids": node_ids})
    except GqlTimeout:
        if len(node_ids) <= 5:
            raise
        mid = len(node_ids) // 2
        return {**gql_nodes(c, node_ids[:mid], with_text), **gql_nodes(c, node_ids[mid:], with_text)}
    nodes = (data.get("data") or {}).get("nodes") or [None] * len(node_ids)
    return {nid: (n or None) for nid, n in zip(node_ids, nodes)}


def _readme_of(n: dict) -> tuple[str, str]:
    for i in range(len(README_PATHS)):
        blob = n.get(f"r{i}")
        if blob and blob.get("oid"):
            return blob["oid"], blob.get("text") or ""
    return "", ""


def clean_readme(md: str, limit: int = README_MAX) -> str:
    """去掉徽章、图片、HTML、代码块、链接地址，只留能看出用途的文字。"""
    t = re.sub(r"```.*?```", " ", md or "", flags=re.S)
    t = re.sub(r"<!--.*?-->", " ", t, flags=re.S)
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", t)                 # 图片 / 徽章
    t = re.sub(r"\[!\[[^\]]*\]\([^)]*\)\]\([^)]*\)", " ", t)    # 带链接的徽章
    t = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", t)              # 链接留文字
    t = re.sub(r"<[^>]+>", " ", t)
    t = re.sub(r"^\s*[#>*\-|=]+", " ", t, flags=re.M)
    t = re.sub(r"https?://\S+", " ", t)
    return clean(t, limit)


def fetch_readmes(names: list[str] | None = None, limit: int = 2000) -> dict:
    """给还没取过 README 的仓库补 README 摘录（标注前跑）。"""
    if names:
        rows = db.rows(f"SELECT id, name, node_id FROM oss_repos WHERE name IN ({','.join('?' * len(names))}) AND node_id!=''", names)
    else:
        rows = db.rows("SELECT id, name, node_id FROM oss_repos WHERE readme_oid IS NULL AND node_id!='' AND status='ok' "
                       "ORDER BY stars DESC LIMIT ?", [limit])
    done = errors = 0
    with _client() as c:
        for i in range(0, len(rows), GQL_BATCH):
            batch = rows[i:i + GQL_BATCH]
            try:
                got = gql_nodes(c, [r["node_id"] for r in batch], with_text=True)
            except Exception as e:  # noqa: BLE001
                errors += 1
                log.warning("oss readme batch failed: %s", e)
                continue
            for r in batch:
                n = got.get(r["node_id"])
                if n is None:
                    continue
                oid, text = _readme_of(n)
                db.execute("UPDATE oss_repos SET readme=?, readme_oid=? WHERE id=?", [clean_readme(text), oid, r["id"]])
                done += 1
    return {"readme": done, "errors": errors}


def refresh(on_batch=None) -> dict:
    """每周：按 node_id 批量刷新 star / push / 归档 / 改名 / README oid；查不到的标 gone，gone 超过 30 天的删掉。"""
    rows = db.rows("SELECT id, name, node_id FROM oss_repos WHERE node_id!=''")
    upd = gone = renamed = 0
    now = db.now()
    with _client() as c:
        for i in range(0, len(rows), GQL_BATCH * 2):
            batch = rows[i:i + GQL_BATCH * 2]
            got = gql_nodes(c, [r["node_id"] for r in batch], with_text=False)
            for r in batch:
                n = got.get(r["node_id"])
                if n is None:
                    db.execute("UPDATE oss_repos SET status='gone', gone_at=CASE WHEN gone_at='' THEN ? ELSE gone_at END WHERE id=?",
                               [now, r["id"]])
                    gone += 1
                    continue
                oid, _ = _readme_of(n)
                name = n.get("nameWithOwner") or r["name"]
                if name != r["name"]:
                    renamed += 1
                    db.execute("UPDATE oss_labels SET name=? WHERE name=?", [name, r["name"]])
                topics = [x["topic"]["name"] for x in ((n.get("repositoryTopics") or {}).get("nodes") or [])]
                db.execute("UPDATE oss_repos SET name=?, stars=?, pushed=?, archived=?, descr=?, lang=?, topics=?, "
                           "readme_oid=CASE WHEN readme_oid IS NULL THEN NULL WHEN readme_oid!=? THEN ? ELSE readme_oid END, "
                           "status='ok', gone_at='', updated=? WHERE id=?",
                           [name, int(n.get("stargazerCount") or 0), n.get("pushedAt") or "", int(bool(n.get("isArchived"))),
                            clean(n.get("description") or ""), (n.get("primaryLanguage") or {}).get("name") or "",
                            json.dumps(topics, ensure_ascii=False), oid, oid, now, r["id"]])
                upd += 1
            if on_batch:
                on_batch(i + len(batch), len(rows))
    cutoff = (datetime.now() - timedelta(days=GONE_PURGE_DAYS)).isoformat(timespec="seconds")
    purged = [r["name"] for r in db.rows("SELECT name FROM oss_repos WHERE status='gone' AND gone_at!='' AND gone_at<?", [cutoff])]
    for name in purged:
        drop(name)
    return {"updated": upd, "gone": gone, "renamed": renamed, "purged": len(purged)}


def drop(name: str) -> None:
    r = db.row("SELECT id FROM oss_repos WHERE name=?", [name])
    if r:
        db.execute("DELETE FROM oss_fts WHERE rowid=?", [r["id"]])
        db.execute("DELETE FROM oss_repos WHERE id=?", [r["id"]])
    db.execute("DELETE FROM oss_labels WHERE name=?", [name])
