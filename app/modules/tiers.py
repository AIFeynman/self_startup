"""分级：把信息推荐和产品雷达的内容按 Tier1 / Tier2 重排的独立流水线（验证通过前和现有两个板块并行，只读它们的数据）。
Tier3 不重排，直接回到信息推荐和产品雷达的原列表。规则见 _tiers_rules.py。"""
import json
import time
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter

from .. import db
from . import _feed_rank as rk
from . import _tiers_judge as tj
from . import _tiers_rules as tr
from . import feed

TITLE = "分级"
ORDER = 31
SCHEMA = tj.SCHEMA
router = APIRouter()

T1_DAYS, T2_DAYS, T2_LIMIT = 3, 3, 60     # Tier1 不限条数；Tier2 总量上限 60（实际由各类名额决定）；论文日期只到天，窗口都按 3 天
EVENT_SCORE = {"S": 10.0, "A": 8.0, "B": 6.0}
CASE_SCORE = 8.0
CASE_T1_TOTAL = 15                        # 增长案例满分 15；只有满分且和 AI 相关才进 Tier1，其余放 Tier2
T2_PER_CAT = {"*": 5, "paper": 10, "trending": 8, "author": 10, "launch": 4, "update": 4, "case": 3}   # Tier2 每类上限，硬名额，不回填
DEEP_CANDIDATES = {"report", "repo", "official", "person", "update", "author", "interest"}   # 过了规则门槛、交给 Jev 打深读分的类别；论文、产品、案例不打
DEEP_TYPES = {"blog", "podcast", "video", "discussion"}       # 论文、项目、产品不判深读
DEEP_MAX = 150
UPDATE_TYPES = {"launch", "model", "feature", "api", "pricing", "packaging", "deprecation"}
CACHE_S = 60
_cache: dict = {}


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
            "href": "", "date": it.get("date") or "", "source": rk.SOURCE_LABEL.get(it["source"], it["source"]), "score": it.get("score") or 0}


def _event_cards(now: datetime) -> list[dict]:
    since = (now - timedelta(days=T1_DAYS)).strftime("%Y-%m-%d")
    rows = db.rows("SELECT e.id, e.title, e.summary, e.date, e.type, e.level, e.sources, c.name company, c.tier ctier FROM intel_event e "
                   "JOIN intel_company c ON c.id = e.company_id WHERE e.merged_into IS NULL AND e.date >= ? AND e.level IN ('S','A','B')", (since,))
    out = []
    for e in rows:
        launch = e["level"] == "S" or (e["level"] == "A" and e["type"] == "launch" and e["ctier"] == 1)
        if not launch and not (e["level"] == "A" and e["type"] in UPDATE_TYPES):
            continue
        srcs = _j(e["sources"], [])
        why = f"{e['company']} · {e['type']} · 雷达 {e['level']} 级"
        cat = "launch" if launch else "update"
        out.append({"id": f"event:{e['id']}", "kind": "event", "tier": 2, "cat": cat, "cat_label": tr.CATS[cat][1],
                    "boosted": False, "why": [why], "title": e["title"], "gist": "", "summary": e["summary"] or "",
                    "url": next((s.get("url") for s in srcs if s.get("official") and s.get("url")), srcs[0].get("url", "") if srcs else ""),
                    "href": f"#intel/e/{e['id']}", "date": e["date"], "source": f"产品雷达 · {e['company']}", "score": EVENT_SCORE[e["level"]]})
    return out


def case_tier(total: int, text: str) -> int:
    return 1 if (total or 0) >= CASE_T1_TOTAL and tr.AI_CASE.search(text) else 2


def _case_cards(now: datetime) -> list[dict]:
    since = (now - timedelta(days=T1_DAYS)).strftime("%Y-%m-%d")
    rows = db.rows("SELECT c.id, c.day, c.company, i.title, i.url, i.one_line, i.source, i.total FROM intel_growth_case c "
                   "JOIN intel_growth_item i ON i.id = c.item_id WHERE c.status = 'done' AND c.complete = 1 AND c.day >= ? "
                   "AND c.id IN (SELECT max(id) FROM intel_growth_case GROUP BY item_id)", (since,))
    return [{"id": f"case:{r['id']}", "kind": "case", "tier": case_tier(r["total"], f"{r['title']} {r['one_line'] or ''}"), "cat": "case", "cat_label": tr.CATS["case"][1], "boosted": False,
             "why": ["增长 Case 卡已写完"], "title": r["title"], "gist": r["one_line"] or "", "summary": "", "url": r["url"],
             "href": f"#intel/g/{r['id']}", "date": r["day"], "source": f"增长 Case · {r['company'] or r['source']}", "score": CASE_SCORE}
            for r in rows]


def balance(cards: list[dict], limit: int, per_cat: int | dict) -> list[dict]:
    """按分数取前 limit 条，每类最多 per_cat 条（可按类给字典，"*" 为默认），防止一类占满。"""
    seen: dict[str, int] = {}
    out = []
    for c in sorted(cards, key=lambda c: -c["score"]):
        seen[c["cat"]] = seen.get(c["cat"], 0) + 1
        if seen[c["cat"]] <= (per_cat if isinstance(per_cat, int) else per_cat.get(c["cat"], per_cat["*"])):
            out.append(c)
    return out[:limit]


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
        tag = f"Jev 深读 {p:.2f}"
        c["deep"] = p
        if c["tier"] == 2 and p >= tj.DEEP_YES:
            c.update(tier=1, cat="deep", cat_label=tr.CATS["deep"][1], why=[tag] + c["why"], score=c["score"] + 10)
        elif c["tier"] == 1 and p < tj.DEEP_NO:
            c.update(tier=2, boosted=False, why=[f"{tag}，不适合精读，降到 Tier2"] + c["why"])
        else:
            c["why"] = [tag] + c["why"]


def build(now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    cards = _event_cards(now) + _case_cards(now)
    taken = {rk.norm_url(c["url"]) for c in cards if c["url"]}
    t2_cut = now - timedelta(days=T2_DAYS)
    t1_cut = now - timedelta(days=T1_DAYS)
    scanned = unranked = 0
    judged: list[dict] = []
    for it in feed._scored(False, True):
        t = rk.item_time(it, now)
        if not t or t <= t1_cut or it["norm_url"] in taken:
            continue
        scanned += 1
        r = tr.classify(it)
        if r["tier"] == 3 or (r["tier"] == 2 and t <= t2_cut):
            unranked += 1
            continue
        cards.append(_card(it, r))
        if deep_eligible(it, r["cat"]):
            judged.append(it)
    judge_errors = []
    if judged:
        judged.sort(key=lambda i: -(i.get("score") or 0))
        scores, judge_errors = tj.deep_scores(judged[:DEEP_MAX])
        apply_deep(cards, scores)
    t1 = sorted((c for c in cards if c["tier"] == 1), key=lambda c: (-c.get("deep", 0), -c["score"]))
    t2 = sorted((c for c in cards if c["tier"] == 2), key=lambda c: -c["score"])
    t2_shown = balance(t2, T2_LIMIT, T2_PER_CAT)
    return {"generated": now.isoformat(timespec="seconds"), "windows": {"t1_days": T1_DAYS, "t2_days": T2_DAYS, "t2_limit": T2_LIMIT},
            "t1": t1, "t2": t2_shown, "t2_more": max(0, len(t2) - len(t2_shown)),
            "t3": {"count": unranked, "scanned": scanned, "links": [{"label": "信息推荐", "href": "#feed"}, {"label": "产品雷达", "href": "#intel"}]},
            "interests": list(tr.INTEREST_LINES), "judge_errors": judge_errors}


@router.get("/items")
def items(refresh: bool = False):
    if refresh or not _cache or time.monotonic() - _cache["at"] > CACHE_S:
        _cache.update(at=time.monotonic(), data=build())
    return _cache["data"]


def agent_context(ref: str) -> str:
    d = items()
    return f"分级：Tier1 {len(d['t1'])} 条、Tier2 {len(d['t2'])} 条（另有 {d['t2_more']} 条超出上限）。Tier1：" + "；".join(c["title"] for c in d["t1"][:8])
