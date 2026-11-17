"""X 长文库：按时间窗口采集 AI 相关长文，逐层过滤，提炼摘要 / 标签 / 可迁移结论。

漏斗（便宜的在前，每层只处理上一层留下的）：
  found   GetXAPI 搜索 `url:"x.com/i/article"`，窗口撞上单次上限就对半拆（上限约 60 条，实测）
  titled  vxtwitter 免费取标题 + 预览；失败的用 GetXAPI article/get 补（顺带拿到全文）
  rel     本机 Claude 按标题 + 预览判是不是 AI 核心内容
  full    GetXAPI article/get 拉全文（0.001 美元/篇，只拉 AI 核心且过阅读门槛的）
  scored  本机 Claude 严格打分 + 摘要 + 标签 + 可迁移结论
被丢弃的行保留（stage=drop_*），门槛改了可以回捞。
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from .. import db, settings
from . import _paper_label as pl

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS x_art (
  id TEXT PRIMARY KEY, user TEXT DEFAULT '', fol INTEGER DEFAULT 0, likes INTEGER DEFAULT 0, views INTEGER DEFAULT 0,
  posted_at TEXT DEFAULT '', day TEXT DEFAULT '', stage TEXT DEFAULT 'found',
  title TEXT DEFAULT '', preview TEXT DEFAULT '', text TEXT DEFAULT '', n INTEGER DEFAULT 0,
  rel TEXT DEFAULT '', rel_why TEXT DEFAULT '', q INTEGER, mkt INTEGER DEFAULT 0, kind TEXT DEFAULT '', domain TEXT DEFAULT '',
  summary TEXT DEFAULT '', tags TEXT DEFAULT '[]', take TEXT DEFAULT '', why TEXT DEFAULT '',
  tries INTEGER DEFAULT 0, updated TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS x_art_ix_stage ON x_art(stage);
CREATE INDEX IF NOT EXISTS x_art_ix_day ON x_art(day);
CREATE TABLE IF NOT EXISTS x_art_zh (id TEXT PRIMARY KEY, zh TEXT, updated TEXT);
CREATE TABLE IF NOT EXISTS x_art_day (day TEXT PRIMARY KEY, found INTEGER, calls INTEGER, done_at TEXT);
CREATE TABLE IF NOT EXISTS x_art_run (id INTEGER PRIMARY KEY AUTOINCREMENT, day TEXT, status TEXT, calls INTEGER DEFAULT 0, result TEXT DEFAULT '{}', started TEXT, finished TEXT);
"""

API = "https://api.getxapi.com"
VX = "https://api.vxtwitter.com"
SPLIT_AT = 20
MIN_WINDOW = 60
START_STEP = 900
VIEW_GATE = 500
FULL_PER_DAY = 120
TITLE_PER_DAY = 500
GRAB_PER_DAY = 200
VIP_FOL = 500000
FOL_EXCEPTION = 20000
MIN_CHARS = 300
CRAWL_LAG = 2
CATCHUP_DAYS = 3
GRAB_CAP = 800
MONTH_STOP_CALLS = 90000
RUN_HOUR = 4
ALL = 10 ** 6
DOMAINS = {
    "agent": "Agent / 多 Agent / 工作流编排", "coding": "AI 编程工具与实践（Claude Code、Codex、Cursor 等）",
    "prompt": "提示词 / 上下文工程 / Skill / MCP", "model": "模型发布 / 能力评测 / 对比",
    "rag": "检索 / 记忆 / 知识库", "train": "训练 / 微调 / 对齐 / 推理优化", "infra": "部署 / 成本 / 工程基础设施",
    "product": "AI 产品", "startup": "AI 创业 / 商业模式 / 增长", "org": "AI 与组织 / 管理 / 团队协作", "strategy": "AI 战略 / 行业与投资判断", "research": "论文解读 / 研究观点", "other": "其他",
}
KINDS = ("经验", "教程", "观点", "研究", "新闻汇总", "产品介绍", "其他")
MKT = re.compile(r"完全保存版|【保存版】|プロンプト公開|販売|限定|配布|無料プレゼント|収益化|副業|月収|LINE登録|講座|サロン|附.{0,6}提示词|先收藏|公式LINE|マガジン|入群|课程")


def init() -> None:
    db.init([SCHEMA])


def _headers() -> dict:
    return {"Authorization": f"Bearer {os.environ['GETXAPI_KEY']}"}


def _client() -> httpx.Client:
    return httpx.Client(timeout=40, trust_env=False)


def _get(c: httpx.Client, url: str, params: dict, headers: dict | None = None, tries: int = 4) -> dict:
    for i in range(tries):
        try:
            r = c.get(url, params=params, headers=headers or _headers())
            if r.status_code == 200:
                return r.json()
            if r.status_code in (400, 404):
                return {}
        except httpx.HTTPError:
            pass
        time.sleep(1.5 * (i + 1))
    return {}


def _utc(day: str) -> int:
    return int(datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())


def _search(c: httpx.Client, t0: int, t1: int, stat: dict) -> list[dict]:
    out, cur = {}, None
    for _ in range(8 if t1 - t0 <= MIN_WINDOW else 2):
        p = {"q": f'url:"x.com/i/article" since_time:{t0} until_time:{t1}', "product": "Latest"}
        if cur:
            p["cursor"] = cur
        j = _get(c, f"{API}/twitter/tweet/advanced_search", p)
        stat["calls"] += 1
        for t in j.get("tweets") or []:
            out[t["id"]] = t
        if not j.get("has_more") or not j.get("next_cursor"):
            break
        cur = j["next_cursor"]
    return list(out.values())


def search_window(c: httpx.Client, t0: int, t1: int, stat: dict) -> list[dict]:
    got = _search(c, t0, t1, stat)
    if len(got) < SPLIT_AT or t1 - t0 <= MIN_WINDOW:
        return got
    cut = [t0 + (t1 - t0) * i // 3 for i in range(4)]
    merged = {t["id"]: t for i in range(3) for t in search_window(c, cut[i], cut[i + 1], stat)}
    return list(merged.values())


def _save_found(t: dict, day: str) -> bool:
    a = t.get("author") or {}
    return bool(db.execute(
        "INSERT OR IGNORE INTO x_art (id,user,fol,likes,views,posted_at,day,updated) VALUES (?,?,?,?,?,?,?,?)",
        [str(t["id"]), a.get("userName") or "", int(a.get("followers") or 0), int(t.get("likeCount") or 0),
         int(t.get("viewCount") or 0), t.get("createdAt") or "", day, db.now()]))


def heads() -> dict[str, dict]:
    init()
    return {r["id"]: {"title": r["title"], "preview": r["preview"]}
            for r in db.rows("SELECT id,title,preview FROM x_art WHERE title<>''")}


def register(items: list[dict]) -> int:
    """信息推荐抓到的、自己发的 X 长文登记进长文库（已有的不动），后续取全文打分走长文库流水线。"""
    init()
    n = 0
    for it in items:
        ex = it.get("extra") or {}
        if ex.get("x_article") != "own" or not it.get("date"):
            continue
        tid = it["id"].split(":", 1)[1]
        if db.row("SELECT 1 FROM x_art WHERE id=?", [tid]):
            continue
        at = datetime.fromisoformat(it["date"].replace("Z", "+00:00")).astimezone(timezone.utc)
        db.execute(
            "INSERT INTO x_art (id,user,fol,likes,views,posted_at,day,updated) VALUES (?,?,?,?,?,?,?,?)",
            [tid, ex.get("author") or "", int(ex.get("followers") or 0), int(it.get("popularity") or 0),
             int(ex.get("views") or 0), at.strftime("%a %b %d %H:%M:%S +0000 %Y"), at.strftime("%Y-%m-%d"), db.now()])
        n += 1
    return n


def crawl_day(day: str, step: int = START_STEP) -> dict:
    init()
    if db.row("SELECT 1 FROM x_art_day WHERE day=?", [day]):
        return {"day": day, "skipped": True}
    stat, new, seen = {"calls": 0}, 0, set()
    base = _utc(day)
    with _client() as c:
        for s in range(0, 86400, step):
            for t in search_window(c, base + s, base + s + step, stat):
                if t["id"] not in seen:
                    seen.add(t["id"])
                    new += _save_found(t, day)
    db.execute("INSERT OR REPLACE INTO x_art_day (day,found,calls,done_at) VALUES (?,?,?,?)", [day, len(seen), stat["calls"], db.now()])
    return {"day": day, "found": len(seen), "new": new, "calls": stat["calls"]}


def watch() -> list[str]:
    from . import feed
    return [a.lower() for a in feed.x_accounts_to_fetch()]


def gate() -> dict:
    """阅读门槛：未处理的行里，阅读不够又不是大粉账号的标 drop_view（可回捞）。"""
    w = watch()
    n = db.execute(f"UPDATE x_art SET stage='drop_view', updated=? WHERE stage='found' AND views<? AND fol<? AND lower(user) NOT IN ({','.join('?' * len(w))})",
                   [db.now(), VIEW_GATE, FOL_EXCEPTION, *w])
    return {"drop_view": n}


def _vx(c: httpx.Client, row: dict) -> dict:
    try:
        j = _get(c, f"{VX}/{row['user']}/status/{row['id']}", {}, headers={}, tries=3)
    except Exception:  # noqa: BLE001 —— vx 限流返回非 JSON，当作没取到，走重试
        return {"title": "", "preview": ""}
    a = j.get("article") or {}
    return {"title": a.get("title") or "", "preview": a.get("preview_text") or ""}


def _article(c: httpx.Client, tid: str) -> dict:
    j = _get(c, f"{API}/twitter/article/get", {"id": tid})
    return j.get("article") or {}


def _blocks_text(a: dict) -> str:
    cs = a.get("contents") or a.get("content") or []
    if isinstance(cs, str):
        return cs
    lines = [f"![]({b['url']})" if b.get("type") == "image" and b.get("url") else (b.get("text") or "")
             for b in cs if isinstance(b, dict)]
    return "\n".join(lines).strip()


IMG_LINE = re.compile(r"^!\[\]\(https://\S+\)$")
ZH_PROMPT = "把用户给的文章片段翻译成通顺的简体中文。保留原有换行、列表和段落结构；代码、命令、链接、以 ![]( 开头的图片行、@用户名、产品和模型名保持原文；只输出译文，不加解释。"
ZH_CHUNK = 3000


def _chunks(text: str) -> list[str]:
    out, cur = [], ""
    for ln in text.split("\n"):
        if cur and len(cur) + len(ln) > ZH_CHUNK:
            out.append(cur)
            cur = ""
        cur += ln + "\n"
    return out + [cur] if cur.strip() else out


def _zh_chunk(part: str) -> str:
    for _ in range(2):
        t = pl.chat(ZH_PROMPT, part)[0]
        if len(t) >= len(part) * 0.3:
            break
    return t


def translate(aid: str) -> str:
    r = db.row("SELECT zh FROM x_art_zh WHERE id=?", [aid])
    if r:
        return r["zh"]
    a = db.row("SELECT text FROM x_art WHERE id=? AND stage='scored'", [aid])
    if not a:
        raise KeyError(aid)
    parts = _chunks(a["text"])
    todo = [i for i, p in enumerate(parts) if p.strip() and not all(IMG_LINE.match(x) or not x.strip() for x in p.split("\n"))]
    with ThreadPoolExecutor(3) as ex:
        for i, t in zip(todo, ex.map(_zh_chunk, [parts[i] for i in todo])):
            parts[i] = t.strip() + "\n"
    zh = "".join(parts).strip()
    db.execute("INSERT OR REPLACE INTO x_art_zh(id,zh,updated) VALUES(?,?,?)", [aid, zh, db.now()])
    return zh


def backfill_images(workers: int = 8) -> int:
    rows = db.rows("SELECT id FROM x_art WHERE stage='scored' AND mkt=0 AND q>=1 AND text NOT LIKE '%![](%'")
    def one(r):
        with _client() as c:
            return r["id"], _blocks_text(_article(c, r["id"]))
    n = 0
    with ThreadPoolExecutor(workers) as ex:
        for tid, text in ex.map(one, rows):
            if "![](" in text:
                db.execute("UPDATE x_art SET text=?,n=?,updated=? WHERE id=?", [text, len(text), db.now(), tid])
                n += 1
    return n


def audit(limit: int = 0) -> dict:
    """召回抽查：grab 取完前 200 后，found 里每天阅读最高的 30 篇就是原排名 201~230。"""
    return grab(limit=limit, per_day=30)


def titles(limit: int = 0, workers: int = 3) -> dict:
    rows = db.rows("SELECT id,user,tries FROM (SELECT id,user,tries,ROW_NUMBER() OVER (PARTITION BY day ORDER BY views DESC) rk FROM x_art WHERE stage='found') "
                   f"WHERE rk<={TITLE_PER_DAY}" + (f" LIMIT {limit}" if limit else ""))
    stat = {"vx": 0, "fallback": 0, "retry": 0, "drop": 0}

    def one(r):
        with _client() as c:
            time.sleep(0.3)
            v = _vx(c, r)
            if v["title"]:
                db.execute("UPDATE x_art SET title=?,preview=?,stage='titled',updated=? WHERE id=?", [v["title"], v["preview"][:300], db.now(), r["id"]])
                stat["vx"] += 1
                return
            if r["tries"] < 3:
                db.execute("UPDATE x_art SET tries=tries+1 WHERE id=?", [r["id"]])
                stat["retry"] += 1
                return
            a = _article(c, r["id"])
            text = _blocks_text(a)
            if a.get("title"):
                db.execute("UPDATE x_art SET title=?,preview=?,text=?,n=?,stage='titled',updated=? WHERE id=?",
                           [a["title"], (a.get("preview_text") or text[:200]), text, len(text), db.now(), r["id"]])
                stat["fallback"] += 1
            else:
                db.execute("UPDATE x_art SET stage='drop_notitle',updated=? WHERE id=?", [db.now(), r["id"]])
                stat["drop"] += 1

    with ThreadPoolExecutor(workers) as ex:
        list(ex.map(one, rows))
    return {**stat, "todo": len(rows)}


def grab(limit: int = 0, workers: int = 8, per_day: int = 0, min_views: int = 0) -> dict:
    """vx 被限流后的主路径：每天阅读数前 GRAB_PER_DAY 的直接取全文（$0.001/篇），标题预览同时拿到。"""
    w = watch()
    if min_views:
        rows = db.rows("SELECT id FROM x_art WHERE stage='found' AND views>=?" + (f" LIMIT {limit}" if limit else ""), [min_views])
    else:
        rows = db.rows("SELECT id FROM (SELECT id,fol,user,ROW_NUMBER() OVER (PARTITION BY day ORDER BY views DESC) rk FROM x_art WHERE stage='found') "
                       f"WHERE rk<={per_day or GRAB_PER_DAY}" + ("" if per_day else f" OR fol>={VIP_FOL} OR lower(user) IN ({','.join('?' * len(w))})") + (f" LIMIT {limit}" if limit else ""), [] if per_day else w)
    stat = {"ok": 0, "drop": 0}

    def one(r):
        with _client() as c:
            a = _article(c, r["id"])
        text = _blocks_text(a)
        if a.get("title") and text:
            db.execute("UPDATE x_art SET title=?,preview=?,text=?,n=?,stage='titled',updated=? WHERE id=?",
                       [a["title"], (a.get("preview_text") or text[:200]), text, len(text), db.now(), r["id"]])
            stat["ok"] += 1
        else:
            db.execute("UPDATE x_art SET stage='drop_notitle',updated=? WHERE id=?", [db.now(), r["id"]])
            stat["drop"] += 1

    with ThreadPoolExecutor(workers) as ex:
        list(ex.map(one, rows))
    return {**stat, "todo": len(rows)}


REL_PROMPT = """你是 AI 内容库的筛选员。对每篇 X 长文（只给标题和开头预览）判断它与 AI 的关系，只输出 JSON 数组，不要其他文字。
元素: {"id":"...","rel":"core|topic|none","why":"≤20字中文理由"}
- core: 主要讲 AI 模型、Agent、AI 编程工具(Claude Code/Codex/Cursor 等)、提示词/上下文/工作流实践、AI 产品、AI 论文或技术；也包括 AI 战略与行业判断、AI 对组织/管理/团队协作的影响、AI 创业(做 AI 产品或公司的经验、商业模式、增长、融资、市场分析)
- topic: AI 只是话题或噱头(AI 副业赚钱教程、泛 AI 新闻汇总、含 AI 字样的泛生活/营销文、AI 概念股/加密货币行情)
- none: 与 AI 无关(标题含 Claude/Grok 等名字也要看内容是不是真讲 AI)
从严：只有标题或预览明确在讲 AI 本身，或 AI 带来的战略、组织、创业问题，才给 core；拿不准给 topic。
"""


def _json_list(text: str) -> list[dict]:
    m = re.search(r"\[.*\]", text, re.S)
    try:
        return json.loads(m.group(0)) if m else []
    except ValueError:
        return []


def relevance(limit: int = 0, batch: int = 20, workers: int = 4) -> dict:
    rows = db.rows("SELECT id,title,preview FROM x_art WHERE stage='titled'" + (f" LIMIT {limit}" if limit else ""))
    chunks = [rows[i:i + batch] for i in range(0, len(rows), batch)]
    stat = {"core": 0, "topic": 0, "none": 0, "miss": 0}

    def one(ch):
        user = "\n".join(f"### id={r['id']}\n标题: {r['title']}\n预览: {r['preview'][:200]}" for r in ch)
        try:
            txt, _ = pl.chat(REL_PROMPT, user)
        except Exception as e:  # noqa: BLE001
            log.warning("rel batch failed: %s", e)
            return
        got = {str(x.get("id")): x for x in _json_list(txt) if isinstance(x, dict)}
        for r in ch:
            x = got.get(r["id"])
            if not x or x.get("rel") not in ("core", "topic", "none"):
                stat["miss"] += 1
                continue
            stat[x["rel"]] += 1
            stage = "rel" if x["rel"] == "core" else "drop_rel"
            db.execute("UPDATE x_art SET rel=?,rel_why=?,stage=?,updated=? WHERE id=?", [x["rel"], str(x.get("why") or "")[:60], stage, db.now(), r["id"]])

    with ThreadPoolExecutor(workers) as ex:
        list(ex.map(one, chunks))
    return {**stat, "todo": len(rows)}


def fulltext(limit: int = 0, workers: int = 8, per_day: int = FULL_PER_DAY) -> dict:
    rows = db.rows("SELECT id,text FROM (SELECT id,text,ROW_NUMBER() OVER (PARTITION BY day ORDER BY views DESC) rk FROM x_art WHERE stage='rel') "
                   f"WHERE rk<={per_day}" + (f" LIMIT {limit}" if limit else ""))
    stat = {"ok": 0, "short": 0, "failed": 0}

    def one(r):
        text = r["text"]
        if not text:
            with _client() as c:
                text = _blocks_text(_article(c, r["id"]))
        if not text:
            db.execute("UPDATE x_art SET tries=tries+1, stage=CASE WHEN tries>=2 THEN 'drop_nofull' ELSE stage END WHERE id=?", [r["id"]])
            stat["failed"] += 1
        elif len(text) < MIN_CHARS:
            db.execute("UPDATE x_art SET text=?,n=?,stage='drop_short',updated=? WHERE id=?", [text, len(text), db.now(), r["id"]])
            stat["short"] += 1
        else:
            db.execute("UPDATE x_art SET text=?,n=?,stage='full',updated=? WHERE id=?", [text, len(text), db.now(), r["id"]])
            stat["ok"] += 1

    with ThreadPoolExecutor(workers) as ex:
        list(ex.map(one, rows))
    return {**stat, "todo": len(rows)}


SCORE_PROMPT = """你是 AI 内容库的严格评审。对每篇 X 长文打分并提炼，只输出 JSON 数组，不要其他文字。
元素: {"id":"...","q":0-5整数,"mkt":true|false,"kind":"经验|教程|观点|研究|新闻汇总|产品介绍|其他","d":"领域code","sum":"≤60字中文简介","tags":["3-5个中文检索标签，写具体问题/方法/工具名，不写泛词"],"take":"可迁移的结论或机制，≤50字；没有就写空串","why":"≤30字打分理由"}
领域 code 只能从这些里选一个：__DOMAINS__
评分很严格，大多数文章应落在 0-2 分。只看内容价值，不看篇幅；个人经验可以得高分，但必须能让别人学到东西:
0-1 空洞、纯引流、模板化、泛泛而谈
2 只有「我做了什么/工具清单/设置步骤/新闻搬运/观点复述」，没讲为什么，换个场景就用不上
3 个人经验里有可迁移的做法，并说明了原因或适用边界；或观点有自己的论据
4 有机制解释(为什么这样)，加数据、日志、实验或对比，并给出自己的判断与局限
5 深度实践或原创研究：有完整的方法、可复现的证据、对机制的洞察，别人读完能直接改变做法
战略/组织/创业类同样按上面的标准：「机制」指商业或组织机制(为什么这样做有效、适用边界)，有数据、案例、复盘和自己的判断才给 3 分以上；空谈趋势、鸡汤、融资新闻搬运最多 2 分。
单次实测、没有解释原理、没有边界说明的，最多 2 分。take 写不出可迁移内容的，不能超过 2 分。
mkt=true: 主要目的是引流/售卖课程/社群/服务/代币，或软广；教程若信息完整可独立复现则 mkt=false。
"""


def _excerpt(r: dict) -> str:
    t = r["text"]
    m = len(t) // 2
    return f"### id={r['id']} 全文{r['n']}字\n标题: {r['title']}\n开头: {t[:2200]}\n中段: {t[m:m + 600]}\n结尾: {t[-600:]}"


def score(limit: int = 0, batch: int = 3, workers: int = 4, ids: list[str] | None = None) -> dict:
    rows = db.rows("SELECT id,title,text,n FROM x_art WHERE stage='full'" + (f" AND id IN ({','.join('?' * len(ids))})" if ids is not None else "") + (f" LIMIT {limit}" if limit else ""), ids or [])
    chunks = [rows[i:i + batch] for i in range(0, len(rows), batch)]
    system = SCORE_PROMPT.replace("__DOMAINS__", "；".join(f"{k}={v}" for k, v in DOMAINS.items()))
    stat = {"scored": 0, "miss": 0}

    def one(ch):
        try:
            txt, _ = pl.chat(system, "\n".join(_excerpt(r) for r in ch))
        except Exception as e:  # noqa: BLE001
            log.warning("score batch failed: %s", e)
            return
        got = {str(x.get("id")): x for x in _json_list(txt) if isinstance(x, dict)}
        for r in ch:
            x = got.get(r["id"])
            if not x or not isinstance(x.get("q"), int):
                stat["miss"] += 1
                continue
            mkt = int(bool(x.get("mkt")) or bool(MKT.search(r["title"] + r["text"][:300] + r["text"][-300:])) and x["q"] < 4)
            tags = [str(t).strip() for t in (x.get("tags") or []) if str(t).strip()][:5]
            domain = x.get("d") if x.get("d") in DOMAINS else "other"
            kind = x.get("kind") if x.get("kind") in KINDS else "其他"
            db.execute("UPDATE x_art SET q=?,mkt=?,kind=?,domain=?,summary=?,tags=?,take=?,why=?,stage='scored',updated=? WHERE id=?",
                       [max(0, min(5, x["q"])), mkt, kind, domain, str(x.get("sum") or "")[:120], json.dumps(tags, ensure_ascii=False),
                        str(x.get("take") or "")[:120], str(x.get("why") or "")[:80], db.now(), r["id"]])
            stat["scored"] += 1

    with ThreadPoolExecutor(workers) as ex:
        list(ex.map(one, chunks))
    return {**stat, "todo": len(rows)}


def funnel() -> dict:
    init()
    return {r["stage"]: r["n"] for r in db.rows("SELECT stage, COUNT(*) n FROM x_art GROUP BY stage")}


def days(start: str, end: str) -> list[str]:
    d0, d1 = datetime.strptime(start, "%Y-%m-%d"), datetime.strptime(end, "%Y-%m-%d")
    return [(d0 + timedelta(days=i)).strftime("%Y-%m-%d") for i in range((d1 - d0).days + 1)]


ADHOC_PAGES = 6
ADHOC_TOP = 40


def adhoc(query: str, days: int = 30) -> dict:
    """用户指定的 X 搜索（关键词 / from:作者 等 X 搜索语法）：只处理这次搜到的长文，跳过 AI 相关判断和每日名额，直接取全文打分。"""
    init()
    now = int(time.time())
    stat = {"calls": 0}
    found: dict[str, dict] = {}
    with _client() as c:
        cur = None
        for _ in range(ADHOC_PAGES):
            p = {"q": f'url:"x.com/i/article" {query} since_time:{now - days * 86400} until_time:{now}', "product": "Latest"}
            if cur:
                p["cursor"] = cur
            j = _get(c, f"{API}/twitter/tweet/advanced_search", p)
            stat["calls"] += 1
            for t in j.get("tweets") or []:
                found[str(t["id"])] = t
            if not j.get("has_more") or not j.get("next_cursor"):
                break
            cur = j["next_cursor"]
        top = sorted(found.values(), key=lambda t: int(t.get("viewCount") or 0), reverse=True)[:ADHOC_TOP]
        for t in top:
            day = datetime.fromtimestamp(_ts(t.get("createdAt")), timezone.utc).strftime("%Y-%m-%d")
            _save_found(t, day)
        ids, new = [], 0
        for t in top:
            r = db.row("SELECT stage FROM x_art WHERE id=?", [str(t["id"])])
            if r["stage"] == "scored":
                continue
            a = _article(c, str(t["id"]))
            text = _blocks_text(a)
            if not a.get("title") or len(text) < MIN_CHARS:
                db.execute("UPDATE x_art SET stage='drop_short',updated=? WHERE id=?", [db.now(), str(t["id"])])
                continue
            db.execute("UPDATE x_art SET title=?,preview=?,text=?,n=?,rel='core',stage='full',updated=? WHERE id=?",
                       [a["title"], a.get("preview_text") or text[:200], text, len(text), db.now(), str(t["id"])])
            ids.append(str(t["id"]))
            new += 1
    sc = score(ids=ids) if ids else {"scored": 0}
    return {"found": len(found), "taken": len(top), "new": new, "scored": sc["scored"], "calls": stat["calls"] + len(top)}


def _ts(created: str | None) -> float:
    try:
        return datetime.strptime(created or "", "%a %b %d %H:%M:%S %z %Y").timestamp()
    except ValueError:
        return time.time()


def listing(q: str = "", sort: str = "q", q_min: int = 1, limit: int = 100) -> list[dict]:
    init()
    where, args = ["stage='scored'", "mkt=0", "q>=?"], [q_min]
    for w in re.findall(r"[\u4e00-\u9fff]+|[^\s\u4e00-\u9fff]+", q):
        where.append("(title LIKE ? ESCAPE '\\' OR summary LIKE ? ESCAPE '\\' OR tags LIKE ? ESCAPE '\\' OR take LIKE ? ESCAPE '\\' OR user LIKE ? ESCAPE '\\' OR text LIKE ? ESCAPE '\\')")
        args += ["%" + w.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"] * 6
    order = {"date": "day DESC, q DESC", "views": "views DESC, q DESC", "fol": "fol DESC, views DESC"}.get(sort, "q DESC, day DESC, views DESC")
    rows = db.rows(f"SELECT id,user,fol,likes,views,day,title,summary,tags,take,q,kind FROM x_art WHERE {' AND '.join(where)} ORDER BY {order} LIMIT ?", [*args, limit])
    for r in rows:
        r["tags"] = json.loads(r["tags"] or "[]")
        r["url"] = f"https://x.com/{r['user']}/status/{r['id']}"
    return rows


# ---------- 每日定时 ----------

_lock = threading.Lock()


def _month_calls(today: str) -> int:
    return db.row("SELECT COALESCE(SUM(calls),0) n FROM x_art_run WHERE status!='failed' AND substr(day,1,7)=?", [today[:7]])["n"]


def due(now: datetime | None = None) -> bool:
    now = now or datetime.now()
    if not settings.get("xart.daily", True) or now.hour < RUN_HOUR:
        return False
    init()
    return not db.row("SELECT 1 FROM x_art_run WHERE day=? AND status!='failed'", [now.strftime("%Y-%m-%d")])


def daily(now: datetime | None = None) -> dict:
    """每天一轮：补抓到 CRAWL_LAG 天前为止还没抓的日子（让阅读数先涨一涨再过门槛）→ 阅读门槛 → 取全文标题 → 判相关 → 取全文 → 打分。
    关注名单作者自己发的长文由信息推荐刷新随时登记进库，这里一并过同一条流水线。按已用调用数记账，月累计到 MONTH_STOP_CALLS 停。"""
    init()
    now = now or datetime.now()
    today = now.strftime("%Y-%m-%d")
    if _month_calls(today) >= MONTH_STOP_CALLS:
        return {"stopped": "月调用数到上限"}
    rid = db.insert("x_art_run", {"day": today, "status": "running", "started": db.now()})
    try:
        end = (now - timedelta(days=CRAWL_LAG)).strftime("%Y-%m-%d")
        res = {"crawl": [crawl_day(d) for d in days((now - timedelta(days=CRAWL_LAG + CATCHUP_DAYS - 1)).strftime("%Y-%m-%d"), end)]}
        res["gate"] = gate()
        res["grab"] = grab(limit=GRAB_CAP, per_day=ALL)
        res["rel"] = relevance()
        res["full"] = fulltext()
        res["score"] = score()
        calls = sum(c.get("calls", 0) for c in res["crawl"]) + res["grab"]["ok"] + res["grab"]["drop"] + res["full"]["ok"] + res["full"]["short"] + res["full"]["failed"]
    except Exception as e:  # noqa: BLE001
        db.execute("UPDATE x_art_run SET status='failed', result=?, finished=? WHERE id=?", [json.dumps({"error": f"{type(e).__name__}: {str(e)[:200]}"}, ensure_ascii=False), db.now(), rid])
        raise
    db.execute("UPDATE x_art_run SET status='ok', calls=?, result=?, finished=? WHERE id=?", [calls, json.dumps(res, ensure_ascii=False), db.now(), rid])
    return res | {"calls": calls}


def start(force: bool = False) -> bool:
    if not (force or due()) or not _lock.acquire(blocking=False):
        return False

    def go():
        try:
            daily()
            from .. import kb
            kb.schedule_sync()
        except Exception:  # noqa: BLE001  已记在 x_art_run
            log.exception("X 长文每日抓取失败")
        finally:
            _lock.release()
    threading.Thread(target=go, daemon=True, name="xart-daily").start()
    return True
