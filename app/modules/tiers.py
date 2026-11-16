"""分级：把信息推荐和产品雷达的内容按 Tier1 / Tier2 重排的独立流水线（验证通过前和现有两个板块并行，只读它们的数据）。
Tier3 不重排，直接回到信息推荐和产品雷达的原列表。规则见 _tiers_rules.py。
按天分级：每天只看当天（本地时区）发布的内容，结果按天存进 tiers_days；近 OPEN_DAYS 天随晚到的内容重算，更早的天算完定稿不再改。
后台每小时跑一次 daily_tick，补齐近 30 天缺的天。"""
import json
import logging
import os
import re
import threading
import time
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter

from .. import db
from . import _feed_rank as rk
from . import _read_log
from . import _tiers_judge as tj
from . import _tiers_rules as tr
from . import feed

TITLE = "分级"
ORDER = 31
SCHEMA = tj.SCHEMA + """
CREATE TABLE IF NOT EXISTS tiers_days (
  day TEXT PRIMARY KEY,
  data TEXT NOT NULL,
  built_at REAL NOT NULL,
  final INTEGER NOT NULL DEFAULT 0
);
"""
router = APIRouter()
log = logging.getLogger(__name__)

RANGES = (1, 7, 14, 30)                   # 页面可选的天数；后台按最长的补齐
T2_LIMIT = 40                             # Tier1 不限条数；Tier2 每天总量上限 40（实际由各类名额决定）
EVENT_SCORE = {"S": 10.0, "A": 8.0, "B": 6.0}
CASE_SCORE = 8.0
CASE_T1_TOTAL = 15                        # 增长案例满分 15 才有资格；进 Tier1 还要 Jev 认可（AI 相关且有可复用做法），其余放 Tier2
T2_PER_CAT = {"*": 3, "launch": 6, "paper": 5, "trending": 4, "author": 6, "interest": 3, "top": 3, "product": 3, "case": 2}   # Tier2 每类上限，硬名额，不回填
T2_ORDER = ["launch", "paper", "trending", "author", "interest", "top", "product", "case"]
T2_DEEP_FLOOR = 0.3                       # Tier2 里已有深读分的卡片，低于它的回到 Tier3
DEEP_CANDIDATES = {"report", "repo", "official", "person", "launch", "author", "interest"}   # 过了规则门槛、交给 Jev 打深读分的类别；论文、产品、案例不打
DEEP_TYPES = {"blog", "podcast", "video", "discussion"}       # 论文、项目、产品不判深读
DEEP_MAX = 150
PICK_MAX = 250
NEWS_SKIP = {"launches", "launch", "introducing", "announces", "released", "release", "with", "from", "that", "this", "available", "adds", "new", "now",
             "openai", "anthropic", "google", "deepmind", "github", "copilot", "perplexity", "deepseek", "microsoft", "nvidia", "claude"}
UPDATE_TYPES = {"launch", "model", "feature", "api", "pricing", "packaging", "deprecation"}
CACHE_S = 60                              # 页面上的今天最多 60 秒重算一次
TICK_S = 3600                             # 后台每小时检查一次：没定稿的天超过 1 小时没算就重算
OPEN_DAYS = 4                             # 今天和前 3 天不定稿：论文、博客常晚一两天才抓到，和原来 3 天窗口能接住的一样
_build_locks: dict[str, threading.Lock] = {}
_tick_lock = threading.Lock()


def _j(s, default):
    try:
        return json.loads(s) if s else default
    except ValueError:
        return default


def _card(it: dict, r: dict) -> dict:
    ex = it.get("extra") or {}
    tier, label = tr.CATS[r["cat"]]
    return {"id": it["id"], "kind": "feed", "tier": r["tier"], "cat": r["cat"], "cat_label": label, "boosted": r["boosted"], "why": r["why"],
            "title": it["title"], "gist": ex.get("gist", ""), "summary": rk.display_summary(it["title"], it["summary"]), "url": it["url"],
            "href": "", "read_ref": it["id"], "date": it.get("date") or "", "source": rk.SOURCE_LABEL.get(it["source"], it["source"]), "score": it.get("score") or 0}


def _event_cards(day: str) -> list[dict]:
    rows = db.rows("SELECT e.id, e.title, e.summary, e.date, e.type, e.level, e.sources, c.name company, c.tier ctier FROM intel_event e "
                   "JOIN intel_company c ON c.id = e.company_id WHERE e.merged_into IS NULL AND e.date = ? AND e.level IN ('S','A','B')", (day,))
    out = []
    for e in rows:
        launch = e["level"] == "S" or (e["level"] == "A" and e["type"] == "launch" and e["ctier"] == 1)
        if not launch and not (e["level"] == "A" and e["type"] in UPDATE_TYPES):
            continue
        srcs = _j(e["sources"], [])
        why = f"{e['company']} · {e['type']} · 雷达 {e['level']} 级"
        out.append({"id": f"event:{e['id']}", "kind": "event", "tier": 2, "cat": "launch", "cat_label": tr.CATS["launch"][1], "read_ref": e["id"],
                    "boosted": False, "why": [why], "title": e["title"], "gist": "", "summary": e["summary"] or "",
                    "url": next((s.get("url") for s in srcs if s.get("official") and s.get("url")), srcs[0].get("url", "") if srcs else ""),
                    "href": f"#intel/e/{e['id']}", "date": e["date"], "source": f"产品雷达 · {e['company']}", "score": EVENT_SCORE[e["level"]]})
    return out


def _tweet(r: dict) -> bool:
    return r["source"] == "twitter" or "x.com/" in (r["url"] or "") or "twitter.com/" in (r["url"] or "")


def _case_cards(day: str) -> list[dict]:
    rows = db.rows("SELECT c.id, c.day, c.company, i.title, i.url, i.one_line, i.source, i.total, c.item_id FROM intel_growth_case c "
                   "JOIN intel_growth_item i ON i.id = c.item_id WHERE c.status = 'done' AND c.complete = 1 AND c.day = ? "
                   "AND c.id IN (SELECT max(id) FROM intel_growth_case GROUP BY item_id)", (day,))
    return [{"id": f"case:{r['id']}", "kind": "case", "tier": 2, "cat": "case", "cat_label": tr.CATS["case"][1], "boosted": False,
             "read_ref": r["item_id"], "why": [f"增长 Case 卡已写完 · 评分 {r['total']}/15"], "title": r["title"], "gist": r["one_line"] or "", "summary": "", "url": r["url"],
             "href": f"#intel/g/{r['id']}", "date": r["day"], "source": f"增长 Case · {r['company'] or r['source']}", "score": CASE_SCORE}
            for r in rows if (r["total"] or 0) >= CASE_T1_TOTAL]


def apply_case(cards: list[dict], scores: dict[str, float]) -> None:
    """增长案例满分后再交给 Jev：AI 相关且有可复用做法的进 Tier1（带分排序），其余留 Tier2。"""
    for c in cards:
        p = scores.get(c["id"])
        if p is None:
            continue
        c["deep"] = p
        if p >= tj.CASE_YES:
            c.update(tier=1, why=[f"Jev 案例 {p:.2f}"] + c["why"], score=c["score"] + 10)
        else:
            c["why"] = [f"Jev 案例 {p:.2f}，不够进 Tier1"] + c["why"]


def balance(cards: list[dict], limit: int, per_cat: int | dict) -> list[dict]:
    """按分数取前 limit 条，每类最多 per_cat 条（可按类给字典，"*" 为默认），防止一类占满。"""
    seen: dict[str, int] = {}
    out = []
    for c in sorted(cards, key=lambda c: -c["score"]):
        seen[c["cat"]] = seen.get(c["cat"], 0) + 1
        if seen[c["cat"]] <= (per_cat if isinstance(per_cat, int) else per_cat.get(c["cat"], per_cat["*"])):
            out.append(c)
    return out[:limit]


def _tokens(title: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9][a-z0-9.\-]+", title.lower()) if len(w) >= 4 and w not in NEWS_SKIP}


def merge_same_news(cards: list[dict]) -> list[dict]:
    """同一件事（标题里至少两个相同的非公司名关键词）只留分最高的一条，其余合并进它的理由。"""
    kept: list[dict] = []
    for c in sorted(cards, key=lambda c: -c["score"]):
        tk = _tokens(c["title"])
        dup = next((k for k in kept if len(tk & k["_tk"]) >= 2), None)
        if dup:
            dup["why"].append(f"合并同类：{c['source']}")
        else:
            kept.append({**c, "_tk": tk, "why": list(c["why"])})
    return [{k: v for k, v in c.items() if k != "_tk"} for c in kept]


def apply_pick(feed_cards: list[dict], scores: dict[str, float]) -> list[dict]:
    """Tier2 的 feed 卡片：有深读分的低于 0.3、有扫读分的低于 0.6 回到 Tier3；留下的按分排序。"""
    out = []
    for c in feed_cards:
        p = scores.get(c["id"])
        if p is not None:
            c["pick"] = p
            c["why"] = [f"Jev 扫读 {p:.2f}"] + c["why"]
            if p < tj.PICK_FLOOR:
                continue
            c["score"] = p * 10
        elif c.get("deep") is not None:
            if c["deep"] < T2_DEEP_FLOOR:
                continue
            c["score"] = c["deep"] * 10
        out.append(c)
    return out


def deep_eligible(it: dict, cat: str) -> bool:
    ex = it.get("extra") or {}
    if cat in ("report", "repo"):
        return True
    if cat not in DEEP_CANDIDATES or it["type"] not in DEEP_TYPES or it["source"] == "zhihu":
        return False
    return it["source"] != "twitter" or bool(ex.get("article_title")) or cat == "person"


def apply_deep(feed_cards: list[dict], scores: dict[str, float]) -> None:
    """规则给候选，Jev 定 Tier1：高分的升上来，规则选了但 Jev 不认的降到 Tier2。"""
    for c in feed_cards:
        p = scores.get(c["id"])
        if p is None or c["cat"] not in DEEP_CANDIDATES:
            continue
        tag = f"Jev {'项目' if c['cat'] == 'repo' else '深读'} {p:.2f}"
        c["deep"] = p
        if c["tier"] == 2 and p >= tj.DEEP_YES:
            c.update(tier=1, cat="deep", cat_label=tr.CATS["deep"][1], why=[tag] + c["why"], score=c["score"] + 10)
        elif c["tier"] == 1 and p < (tj.PICK_FLOOR if c["cat"] == "repo" else tj.DEEP_NO):
            c.update(tier=2, boosted=False, why=[f"{tag}，不适合精读，降到 Tier2"] + c["why"])
        else:
            c["why"] = [tag] + c["why"]


def recent_days(today: str, n: int) -> list[str]:
    """today 往前 n 天（含今天），新的在前。"""
    d = datetime.strptime(today, "%Y-%m-%d")
    return [(d - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(n)]


def build(day: str, now: datetime | None = None) -> dict:
    """只分级 day 当天（本地时区 0 点到 24 点）发布的内容。"""
    now = now or datetime.now(timezone.utc)
    start = datetime.strptime(day, "%Y-%m-%d").astimezone()
    end = (datetime.strptime(day, "%Y-%m-%d") + timedelta(days=1)).astimezone()
    cards = _event_cards(day) + _case_cards(day)
    taken = {rk.norm_url(c["url"]) for c in cards if c["url"]}
    scanned = unranked = 0
    judged: list[dict] = []
    feed_items: list[dict] = []
    for it in feed._scored(False, True):
        t = rk.item_time(it, now) if it.get("date") else _local(it.get("fetched_at"))
        if not t or not start <= t < end or it["norm_url"] in taken:
            continue
        scanned += 1
        r = tr.classify(it)
        if r["tier"] == 3:
            unranked += 1
            continue
        cards.append(_card(it, r))
        feed_items.append(it)
        if deep_eligible(it, r["cat"]):
            judged.append(it)
    judge_errors = []
    case_cards = [c for c in cards if c["kind"] == "case"]
    case_scores, case_errors = tj.scores([{"id": c["id"], "source": "growth", "type": "blog", "title": c["title"], "summary": c["gist"], "url": c["url"],
                                            "extra": {"author": c["source"].split(" · ")[-1]}} for c in case_cards], "case")
    judge_errors += case_errors
    apply_case(case_cards, case_scores)
    if judged:
        judged.sort(key=lambda i: -(i.get("score") or 0))
        top = judged[:DEEP_MAX]
        repo_ids = {c["id"] for c in cards if c["cat"] == "repo"}
        scores, judge_errors = tj.scores([i for i in top if i["id"] not in repo_ids], "deep")
        repo_scores, repo_errors = tj.scores([i for i in top if i["id"] in repo_ids], "pick")
        judge_errors += repo_errors
        apply_deep(cards, scores | repo_scores)
    t1 = sorted((c for c in cards if c["tier"] == 1), key=lambda c: (-c.get("deep", 0), -c["score"]))
    t2_cards = [c for c in cards if c["tier"] == 2]
    plain = [c for c in t2_cards if c["kind"] == "feed" and c.get("deep") is None]
    by_id = {i["id"]: i for i in feed_items}
    picked, pick_errors = tj.scores([by_id[c["id"]] for c in plain[:PICK_MAX]], "pick")
    judge_errors += pick_errors
    t2_cards = [c for c in t2_cards if c["kind"] != "feed"] + apply_pick([c for c in t2_cards if c["kind"] == "feed"], picked)
    t2_cards = [c for c in t2_cards if c["cat"] != "launch"] + merge_same_news([c for c in t2_cards if c["cat"] == "launch"])
    t2 = sorted(t2_cards, key=lambda c: -c["score"])
    t2_shown = sorted(balance(t2, T2_LIMIT, T2_PER_CAT), key=lambda c: (T2_ORDER.index(c["cat"]) if c["cat"] in T2_ORDER else 99, -c["score"]))
    return {"day": day, "generated": now.isoformat(timespec="seconds"), "t2_limit": T2_LIMIT,
            "t1": t1, "t2": t2_shown, "t2_more": max(0, len(t2) - len(t2_shown)),
            "t3": {"count": unranked, "scanned": scanned, "links": [{"label": "信息推荐", "href": "#feed"}, {"label": "产品雷达", "href": "#intel"}]},
            "judge_errors": judge_errors}


def _local(s: str | None) -> datetime | None:
    """db.now() 写的抓取时间是不带时区的本地时间。"""
    try:
        return datetime.fromisoformat(s).astimezone() if s else None
    except ValueError:
        return None


def _stored(day: str) -> dict | None:
    return db.row("SELECT data, built_at, final FROM tiers_days WHERE day=?", (day,))


def _fresh(r: dict | None, max_age: float) -> bool:
    return bool(r) and (bool(r["final"]) or time.time() - r["built_at"] < max_age)


def day_result(day: str, today: str, max_age: float) -> dict:
    """存过且没过期就用存的；否则重算并存下。早于昨天的天算完即定稿（final），之后不再重算，历史结果不会被覆盖。"""
    r = _stored(day)
    if not _fresh(r, max_age):
        with _build_locks.setdefault(day, threading.Lock()):
            r = _stored(day)
            if not _fresh(r, max_age):
                data = build(day)
                db.execute("INSERT OR REPLACE INTO tiers_days(day, data, built_at, final) VALUES (?,?,?,?)",
                           (day, json.dumps(data, ensure_ascii=False), time.time(), int(day < recent_days(today, OPEN_DAYS)[-1])))
                return data
    return json.loads(r["data"])


def daily_tick() -> None:
    today = db.today()
    for day in recent_days(today, max(RANGES)):
        day_result(day, today, TICK_S - 60)


def _tick_bg() -> None:
    def run():
        if not _tick_lock.acquire(blocking=False):
            return
        try:
            daily_tick()
        except Exception as e:  # noqa: BLE001
            log.warning("tiers daily tick failed: %s", e)
        finally:
            _tick_lock.release()
    threading.Thread(target=run, daemon=True, name="tiers-daily").start()


def _loop():
    time.sleep(150)  # 等信息推荐的排序先算好
    while True:
        _tick_bg()
        time.sleep(TICK_S)


def on_startup():
    if os.environ.get("SELF_STARTUP_NO_AUTOREFRESH"):
        return
    threading.Thread(target=_loop, daemon=True, name="tiers-loop").start()


def _marker():
    """已读状态和信息推荐、产品雷达共用 read_log，深读状态取自学习模块，每次返回时现算（分级结果存库，这些不能跟着存）。"""
    refs = {"feed": _read_log.refs("feed"), "event": _read_log.refs("intel_event"), "case": _read_log.refs("growth")}
    urls = _read_log.urls("feed")
    deeps = feed._deep_latest()

    def mark(c):
        d = deeps.get(rk.norm_url(c["url"])) if c["url"] else None
        read = str(c["read_ref"]) in refs[c["kind"]] or (c["kind"] == "feed" and rk.norm_url(c["url"]) in urls) or bool(d and d.get("finished_at"))
        return {**c, "read": read, "deep_read": feed.deep_state(d) if d else None}
    return lambda data: {**data, "t1": [mark(c) for c in data["t1"]], "t2": [mark(c) for c in data["t2"]]}


@router.get("/items")
def items(days: int = 1, refresh: bool = False):
    """days：1 / 7 / 14 / 30，从今天往前每天一组。今天现算（最多 60 秒一次）；过去的天读存好的，还没算的标 pending 并在后台补；
    refresh 重算今天和范围内已存但没定稿的天。"""
    n = days if days in RANGES else 1
    today = db.today()
    mark = _marker()
    out = []
    for day in recent_days(today, n):
        r = None if day == today else _stored(day)
        if day == today or (refresh and r and not r["final"]):
            out.append(mark(day_result(day, today, 0 if refresh else CACHE_S)))
        elif r:
            out.append(mark(json.loads(r["data"])))
        else:
            out.append({"day": day, "pending": True})
    if any(x.get("pending") for x in out):
        _tick_bg()
    return {"range": n, "range_options": list(RANGES), "today": today, "days": out, "interests": list(tr.INTEREST_LINES)}


def agent_context(ref: str) -> str:
    d = day_result(db.today(), db.today(), CACHE_S)
    return f"分级（今天）：Tier1 {len(d['t1'])} 条、Tier2 {len(d['t2'])} 条（另有 {d['t2_more']} 条超出上限）。Tier1：" + "；".join(c["title"] for c in d["t1"][:8])
