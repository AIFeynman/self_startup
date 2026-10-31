"""信息推荐的排序：纯函数、确定性，方便单测。

score = 热度(同源近 30 天内的百分位) + 新鲜度(按类型的半衰期衰减) + 兴趣词命中 + 反馈亲和(赞/踩过的相似词与来源)
        + 关注名单 / 多源印证加分 + learn_evolve 评分先验 + 本条自身反馈
每条返回 why 字符串，解释分数从哪来。
"""
from __future__ import annotations

import bisect
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit

W = {"pop": 1.0, "fresh": 2.0, "interest": 0.45, "interest_max": 3, "token": 0.2, "token_cap": 4,
     "source": 0.6, "self_like": 1.0, "self_dislike": -2.0, "stale": -0.8, "gone": -1.5,
     "follow": 0.3, "also": 0.25, "also_max": 2}
# 新鲜度半衰期 = 基准（settings feed.half_life_hours，默认 72h）× 类型系数：
# 讨论 / 产品一两天就过气；论文、项目、播客的价值衰减慢，且论文日期只精确到天
TYPE_HALF_LIFE = {"discussion": 0.5, "product": 0.67, "blog": 1.0, "news": 1.0, "repo": 1.67, "paper": 1.67,
                  "podcast": 2.33}
POP_WINDOW_DAYS = 30        # 热度百分位只和同源最近 30 天的条目比，避免历史爆款把新条目都压成低热度
SRC_MIN_EXAMPLES = 5        # 某来源的反馈样本少于这个数时不算「你常赞 X」
PICKS_N, PICKS_PER_SOURCE, PICKS_PER_TYPE = 5, 1, 2     # 今日精选：每个来源最多 1 条、每类最多 2 条
SOURCE_SHARE = 0.2          # diversify：前 N 条里同一来源最多占的比例
STALE_DAYS = 14             # 发布超过这么多天算「旧」：在推荐里降权，避免几个月前的高赞条目霸榜
TYPE_SHARE = 0.4            # diversify：前 N 条里同一类型最多占的比例
NO_POP_BASE = 0.35          # 整个来源都没有热度数据（博客 RSS 等）时的中性热度分
LE_PRIOR = {"star": 0.5, "good": 0.3, "skip": -0.3, "bad": -0.6}
LE_LABEL = {"star": "learn_evolve 标星", "good": "learn_evolve 好评", "skip": "learn_evolve 跳过", "bad": "learn_evolve 差评"}
SOURCE_LABEL = {"hn": "HN", "github": "GitHub", "hf": "HF Papers", "arxiv": "AlphaXiv", "reddit": "Reddit",
                "blog": "博客", "producthunt": "Product Hunt", "twitter": "X", "podcast": "播客", "xiaoyuzhou": "小宇宙",
                "openrouter": "OpenRouter", "youtube": "YouTube", "yc": "YC", "huggingface": "HF"}
POP_UNIT = {"hn": "分", "github": "★", "hf": "赞", "arxiv": "赞", "reddit": "赞", "producthunt": "票",
            "twitter": "赞", "huggingface": "赞",
            "xiaoyuzhou": "播放"}

_STOP = set("""the and for with from that this into your you are was were has have how what why when who our its
not but can will all new using use via over about than more most best just get make made like vs based
show ask tell hn pdf video paper towards toward their them they his her out one two own
don doesn didn isn aren won can't need needs only today now here there some any every very really much many
still also even ever let lets want wants know think thing things way ways day days year years time first last
next back good great big little long people world help really should would could been being does doing
""".split())
_TOKEN_RE = re.compile(r"[a-z][a-z0-9+#.\-]{2,}|[一-鿿]{2,}")


def tokens(text: str) -> set[str]:
    return {t.strip(".-") for t in _TOKEN_RE.findall((text or "").lower()) if t.strip(".-") not in _STOP}


def norm_url(url: str) -> str:
    """去协议/www/尾斜线/追踪参数/fragment；arXiv abs/pdf/hf papers 统一成 arxiv:<id>。"""
    if not url:
        return ""
    m = re.search(r"(?:arxiv\.org/(?:abs|pdf)|huggingface\.co/papers|alphaxiv\.org/(?:abs|overview))/(\d{4}\.\d{4,5})", url)
    if m:
        return "arxiv:" + m.group(1)
    p = urlsplit(url.strip())
    host = p.netloc.lower().removeprefix("www.")
    q = [(k, v) for k, v in parse_qsl(p.query) if not k.lower().startswith(("utm_", "ref", "source"))]
    return f"{host}{p.path.rstrip('/').lower()}" + (f"?{urlencode(sorted(q))}" if q else "")


def norm_title(title: str) -> str:
    return re.sub(r"[^a-z0-9一-鿿]+", "", (title or "").lower())


def _date_only(s: str) -> bool:
    """只有日期没有时刻（2026-10-29 / ...T00:00:00…）：HF / arXiv / 部分博客。"""
    return bool(re.match(r"^\d{4}-\d{2}-\d{2}(?:[T ]00:00(?::00(?:\.0+)?)?(?:Z|[+-]00:?00)?)?$", (s or "").strip()))


def item_time(it: dict, now: datetime) -> datetime | None:
    """排序 / 时间筛选用的发布时间：只精确到天的按当天中午算（不晚于现在），没日期的用抓取时间。"""
    s = it.get("date") or ""
    d = _parse_dt(s)
    if d and _date_only(s):
        d = min(d + timedelta(hours=12), now)
    return d or _parse_dt(it.get("fetched_at") or "")


def _parse_dt(s: str) -> datetime | None:
    if not s:
        return None
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        try:
            d = datetime.strptime(s[:10], "%Y-%m-%d")
        except ValueError:
            return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _interest_re(term: str) -> re.Pattern:
    t = re.escape(term.lower().strip())
    # 英文词按词边界匹配（避免 rl 命中 world），中文直接子串
    return re.compile(rf"(?<![a-z0-9]){t}(?![a-z0-9])" if re.match(r"^[\x00-\x7f]+$", term) else t)


def fmt_pop(source: str, pop: float) -> str:
    if not pop:
        return ""
    v = f"{pop / 1000:.1f}k" if pop >= 1000 else str(int(pop))
    return f"{SOURCE_LABEL.get(source, source)} {v}{POP_UNIT.get(source, '')}"


def build_affinity(examples: list[dict]) -> dict:
    """examples: [{title, summary, source, polarity:+1/-1}] → 词与来源的净偏好计数。"""
    tok, src, own = Counter(), Counter(), {}
    for e in examples:
        pol = 1 if e.get("polarity", 0) > 0 else -1
        ts = tokens(e.get("title", ""))
        for t in ts:
            tok[t] += pol
        src[e.get("source", "")] += pol
        if e.get("id"):
            own[e["id"]] = (ts, pol)
    n_src = Counter(e.get("source", "") for e in examples)
    return {"tok": tok, "src": src, "n_src": n_src, "own": own}


def _leave_one_out(aff: dict, it: dict) -> dict:
    """条目自己就是训练样本时，扣掉它自己的贡献，避免「你赞过相似内容」指的是它自己。"""
    if it.get("id") not in aff.get("own", {}):
        return aff
    ts, pol = aff["own"][it["id"]]
    tok = aff["tok"].copy()
    for t in ts:
        tok[t] -= pol
    src, n_src = aff["src"].copy(), aff["n_src"].copy()
    src[it.get("source", "")] -= pol
    n_src[it.get("source", "")] -= 1
    return {"tok": tok, "src": src, "n_src": n_src}


def score_item(it: dict, *, pop_norm: float, now: datetime, half_life_h: float, interests: list[str],
               aff: dict | None = None, fb: dict | None = None) -> tuple[float, list[str]]:
    why: list[str] = []
    s = W["pop"] * pop_norm
    pl = fmt_pop(it.get("source", ""), it.get("popularity") or 0)
    if pl:
        why.append(pl)

    d = item_time(it, now)
    age_h = max(0.0, (now - d).total_seconds() / 3600) if d else 24 * 30
    fresh = 0.5 ** (age_h / max(half_life_h * TYPE_HALF_LIFE.get(it.get("type", ""), 1.0), 1))
    s += W["fresh"] * fresh
    if age_h < 24:
        why.append("24 小时内")
    elif age_h > STALE_DAYS * 24:
        s += W["stale"]
        why.append(f"{int(age_h // 24)} 天前")
    if (it.get("extra") or {}).get("gone"):
        s += W["gone"]
        why.append("最近一次抓取未再出现（可能已删除或掉出搜索前列）")
    if str((it.get("extra") or {}).get("via") or "").startswith("@"):
        s += W["follow"]
        why.append("关注账号")

    text = f"{it.get('title', '')} {it.get('summary', '')}".lower()
    hits = [t for t in interests if t and _interest_re(t).search(text)]
    if hits:
        s += W["interest"] * min(len(hits), W["interest_max"])
        why.append("命中 " + "、".join(hits[:3]))

    if aff:
        aff = _leave_one_out(aff, it)
        toks = tokens(it.get("title", ""))
        tok_s = sum(max(-2, min(2, aff["tok"].get(t, 0))) for t in toks)
        tok_s = max(-W["token_cap"], min(W["token_cap"], tok_s))
        src = it.get("source", "")
        n = aff["n_src"].get(src, 0)
        src_s = aff["src"].get(src, 0) / (n + 5) if n >= SRC_MIN_EXAMPLES else 0.0
        s += W["token"] * tok_s + W["source"] * src_s
        if tok_s >= 1:
            liked = sorted((t for t in toks if aff["tok"].get(t, 0) > 0), key=lambda t: -aff["tok"][t])[:2]
            why.append("你赞过相似内容（" + "、".join(liked) + "）")
        elif tok_s <= -1:
            why.append("与你踩过的内容相似")
        if src_s >= 0.3:
            why.append(f"你常赞 {SOURCE_LABEL.get(src, src)}")

    rating = (it.get("extra") or {}).get("le_rating") or ""
    if rating in LE_PRIOR:
        s += LE_PRIOR[rating]
        why.append(LE_LABEL[rating])

    fb = fb or {}
    if fb.get("vote", 0) > 0:
        s += W["self_like"]
        why.append("你赞过")
    elif fb.get("vote", 0) < 0:
        s += W["self_dislike"]
        why.append("你踩过")
    return s, why


def rank(items: list[dict], *, now: datetime | None = None, half_life_h: float = 72, interests: list[str] = (),
         feedback: dict[str, dict] | None = None, examples: list[dict] | None = None,
         include_hidden: bool = False) -> list[dict]:
    """items: feed_items 行（extra 已解析成 dict）。feedback: {item_id: {vote, saved, hidden}}。
    examples: 训练亲和度的样本（赞/踩/收藏 + learn_evolve 评分）。返回去重后按分数降序的新列表。"""
    now = now or datetime.now(timezone.utc)
    feedback = feedback or {}
    aff = build_affinity(examples) if examples else None
    pops = pop_index(items, now)

    scored = []
    for it in items:
        fb = feedback.get(it["id"], {})
        if fb.get("hidden") and not include_hidden:
            continue
        pn = pop_norm(pops, it)
        s, why = score_item(it, pop_norm=pn, now=now, half_life_h=half_life_h, interests=list(interests),
                            aff=aff, fb=fb)
        scored.append({**it, "score": round(s, 3), "pop_norm": round(pn, 3), "why": " · ".join(why), "feedback": fb})
    scored.sort(key=lambda x: (-x["score"], x["id"]))

    out, seen_url, seen_title = [], {}, {}
    for it in scored:
        u, t = norm_url(it.get("url", "")), norm_title(it.get("title", ""))
        dup = seen_url.get(u) if u else None
        dup = dup or (seen_title.get(t) if len(t) >= 12 else None)
        if dup:
            label = SOURCE_LABEL.get(it["source"], it["source"])
            if label not in dup["also"]:
                dup["also"].append(label)
            continue
        it["also"] = []
        out.append(it)
        if u:
            seen_url[u] = it
        if len(t) >= 12:
            seen_title[t] = it
    for it in out:
        if it["also"]:
            # 多个来源都收了同一条 = 互相印证，加一点分
            it["score"] = round(it["score"] + W["also"] * min(len(it["also"]), W["also_max"]), 3)
            it["why"] = (it["why"] + " · " if it["why"] else "") + "也见于 " + "、".join(it["also"])
    out.sort(key=lambda x: (-x["score"], x["id"]))
    return out


def pop_index(items: list[dict], now: datetime) -> dict[str, list[float]]:
    """每个来源最近 POP_WINDOW_DAYS 天的热度（升序），供百分位用；窗口内没有条目的来源退回用全部。"""
    recent, every = {}, {}
    cutoff = now - timedelta(days=POP_WINDOW_DAYS)
    for it in items:
        p = float(it.get("popularity") or 0)
        every.setdefault(it["source"], []).append(p)
        d = item_time(it, now)
        if d and d >= cutoff:
            recent.setdefault(it["source"], []).append(p)
    return {s: sorted(recent.get(s) or v) for s, v in every.items()}


def pop_norm(pops: dict[str, list[float]], it: dict) -> float:
    """同源百分位（0–1）；整源没有热度数据时给中性分 NO_POP_BASE，有数据但本条为 0 给 0。"""
    arr = pops.get(it["source"]) or []
    if not arr or arr[-1] <= 0:
        return NO_POP_BASE
    p = float(it.get("popularity") or 0)
    if p <= 0:
        return 0.0
    return bisect.bisect_right(arr, p) / len(arr)


def sort_items(items: list[dict], sort: str, now: datetime) -> list[dict]:
    """sort: score（综合，默认）/ new（按发布时间）/ hot（按同源热度百分位，热度相同按综合分）。"""
    if sort == "new":
        far = datetime.min.replace(tzinfo=timezone.utc)
        return sorted(items, key=lambda x: (item_time(x, now) or far, x["score"]), reverse=True)
    if sort == "hot":
        return sorted(items, key=lambda x: (x.get("pop_norm", 0), x["score"]), reverse=True)
    return items


def within_days(items: list[dict], days: float, now: datetime) -> list[dict]:
    if not days:
        return items
    cutoff = now - timedelta(days=days)
    return [x for x in items if (item_time(x, now) or cutoff) > cutoff]


def _take(items: list[dict], k: int, type_cap: int, src_cap: int, nt: Counter | None = None,
          ns: Counter | None = None) -> tuple[list[dict], list[dict]]:
    """按顺序取至多 k 条，每类 / 每个来源不超过上限（nt / ns 是已占用的计数，会被更新）；其余原序放进 rest。"""
    nt, ns = (nt if nt is not None else Counter()), (ns if ns is not None else Counter())
    head, rest = [], []
    for it in items:
        if len(head) < k and nt[it.get("type")] < type_cap and ns[it.get("source")] < src_cap:
            head.append(it)
            nt[it.get("type")] += 1
            ns[it.get("source")] += 1
        else:
            rest.append(it)
    return head, rest


def diversify(items: list[dict], top: int = 30, max_share: float = TYPE_SHARE,
              src_share: float = SOURCE_SHARE) -> list[dict]:
    """前 PICKS_N 条（今日精选）每个来源最多 1 条、每类最多 2 条；前 top 条里同一类型不超过 max_share、
    同一来源不超过 src_share（各至少 2 条）。超出的顺延到后面，相对顺序不变；凑不满就放宽，不丢条目。"""
    nt, ns = Counter(), Counter()
    picks, rest = _take(items, PICKS_N, PICKS_PER_TYPE, PICKS_PER_SOURCE, nt, ns)
    if len(picks) < PICKS_N:                       # 来源 / 类型太少时放宽，保证精选凑满
        more, rest = _take(rest, PICKS_N - len(picks), PICKS_N, PICKS_N, nt, ns)
        picks += more
    body, tail = _take(rest, max(0, top - len(picks)), max(2, int(top * max_share)), max(2, int(top * src_share)), nt, ns)
    return picks + body + tail
