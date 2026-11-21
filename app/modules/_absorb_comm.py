"""其他社区（Lobsters、官方产品论坛）的评论区提炼试点：只做采集 + 单帖提炼，看效果和成本，不进 HN 吸收的页面、定时和缓存。

复用 _feed_hn 的提示词、逐字原话核对和链接校验；结果存 data/absorb/comm/<来源>/，每帖一个 json，已有的不重跑。

    python -m app.modules._absorb_comm --source lobsters --limit 12
    python -m app.modules._absorb_comm --source openai --limit 6
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor

import httpx

from .. import agent
from ..db import DATA_DIR, ROOT
from . import _absorb_hn as hn
from . import _absorb_run as ar
from . import _feed_hn as hnd

BASE = DATA_DIR / "absorb" / "comm"
UA = {"User-Agent": "Mozilla/5.0 (research pilot)"}
FORUMS = {"openai": "https://community.openai.com", "huggingface": "https://discuss.huggingface.co", "cursor": "https://forum.cursor.com"}
NAMES = {"x": "X（推特）回复区", "xart": "X 长文回复区", "lobsters": "Lobsters", "openai": "OpenAI 开发者社区", "huggingface": "Hugging Face 论坛", "cursor": "Cursor 论坛"}
MIN_COMMENTS = {"lobsters": 8}
MIN_DEFAULT = 15
MAX_POSTS_FETCH = 120
X_TOP_PAGES, X_NEW_PAGES, X_MIN_FAVES, X_MAX_REPLIES = 3, 2, 3, 100   # GetXAPI 每页约 20 条：高赞最多 60 + 最新最多 40
X_ART_MIN_REPLIES = 20
X_BIG = 10_000         # 粉丝 ≥1 万的回复者：Jev 分数放宽到 0.4
Q_REPLY = ("state.items.{k} 是 X 上一条推文下的回复。它是否包含有信息量的内容：具体的观点或判断并说明了理由、亲身使用或做过的经验、"
           "带理由的推荐或质疑、有出处的事实或数据？只有表情、玩笑、顺口附和、@人寒暄、求关注、广告和刷屏、与原推无关的内容否。")


class CRun(ar.Run):
    def __init__(self, source: str, jev_min: float = 0.0):
        self.source, self.topic, self.stage, self.jev_min = source, NAMES[source], "digest", jev_min
        self.dir = BASE / (source + (f"_jev{jev_min}_v2" if jev_min else ""))
        self.dir.mkdir(parents=True, exist_ok=True)
        self.light = agent.tier_model("light") or "claude-haiku-5-5"
        self.cost, self.secs, self.fails = {}, {}, {}
        import threading
        self.lock = threading.Lock()


def system(source: str) -> str:
    return hnd.SYSTEM.replace("Hacker News", NAMES[source])


def get(c: httpx.Client, url: str, **kw):
    r = c.get(url, headers=UA, **kw)
    r.raise_for_status()
    return r.json()


def lobsters_posts(c: httpx.Client, limit: int) -> list[dict]:
    out = []
    for page in (1, 2):
        for s in get(c, "https://lobste.rs/t/ai.json", params={"page": page}):
            if s["comment_count"] >= MIN_COMMENTS["lobsters"]:
                out.append({"id": s["short_id"], "title": s["title"], "url": s["url"], "points": s["score"], "comments": s["comment_count"],
                            "link": s["comments_url"], "ts": dt.datetime.fromisoformat(s["created_at"]).timestamp(), "author": s["submitter_user"]})
    return sorted(out, key=lambda p: -p["comments"])[:limit]


def lobsters_thread(c: httpx.Client, p: dict) -> tuple[str, list[dict]]:
    d = get(c, f"https://lobste.rs/s/{p['id']}.json")
    out = []
    for n, x in enumerate(d["comments"]):
        if x.get("is_deleted") or x.get("is_moderated"):
            continue
        text = hnd.comment_text(x["comment"])
        if text:
            out.append({"id": n + 1, "depth": int(x["depth"]), "author": x["commenting_user"], "text": text[:hnd.MAX_COMMENT], "replies": 0})
    return d.get("submitter_user") or "", out


def forum_posts(c: httpx.Client, source: str, limit: int) -> list[dict]:
    base = FORUMS[source]
    ts = get(c, f"{base}/top.json", params={"period": "monthly"})["topic_list"]["topics"]
    ts = [t for t in ts if t["posts_count"] >= MIN_DEFAULT]
    return [{"id": str(t["id"]), "title": t["title"], "url": f"{base}/t/{t['id']}", "points": t["like_count"], "comments": t["posts_count"],
             "link": f"{base}/t/{t['id']}", "ts": dt.datetime.fromisoformat(t["created_at"].replace("Z", "+00:00")).timestamp(), "author": ""}
            for t in sorted(ts, key=lambda t: -t["posts_count"])[:limit]]


def forum_thread(c: httpx.Client, source: str, p: dict) -> tuple[str, list[dict]]:
    base = FORUMS[source]
    d = get(c, f"{base}/t/{p['id']}.json")
    posts = list(d["post_stream"]["posts"])
    have = {x["id"] for x in posts}
    rest = [i for i in d["post_stream"]["stream"] if i not in have][:MAX_POSTS_FETCH]
    for i in range(0, len(rest), 20):
        posts += get(c, f"{base}/t/{p['id']}/posts.json", params=[("post_ids[]", x) for x in rest[i:i + 20]])["post_stream"]["posts"]
    depth, out = {}, []
    for x in sorted(posts, key=lambda x: x["post_number"]):
        depth[x["post_number"]] = depth.get(x.get("reply_to_post_number"), -1) + 1
        text = hnd.comment_text(x.get("cooked") or "")
        if text:
            out.append({"id": x["post_number"], "depth": min(depth[x["post_number"]], hnd.MAX_DEPTH), "author": x["username"], "text": text[:hnd.MAX_COMMENT], "replies": 0})
    return (out[0]["author"] if out else ""), out


def jev_scores(texts: list[str]) -> list[float]:
    """Jev 逐条给“有信息量”的概率；25 条一批。key 在 .env 里。"""
    hn.load_env()
    key = os.environ.get("JEV_API_KEY", "").strip()
    if not key:
        raise RuntimeError("未配置 JEV_API_KEY")
    out: list[float] = []
    with httpx.Client(timeout=60) as c:
        for i in range(0, len(texts), 25):
            refs = {f"i{n}": t for n, t in enumerate(texts[i:i + 25])}
            res = c.post(hn.JEV_API, headers={"Authorization": f"Bearer {key}"}, json={
                "model": "jev-latest", "state": {"items": {k: {"text": t[:600]} for k, t in refs.items()}},
                "questions": {k: {"type": "noul", "instructions": Q_REPLY.format(k=k)} for k in refs}})
            res.raise_for_status()
            for k in refs:
                v = (res.json().get("answers", {}).get(k) or {}).get("noul")
                if not isinstance(v, (int, float)):
                    raise RuntimeError("Jev 没返回概率")
                out.append(round(float(v), 3))
    return out


def x_posts(limit: int) -> list[dict]:
    db = sqlite3.connect(f"file:{DATA_DIR / 'app.db'}?mode=ro", uri=True)
    rows = db.execute("select id, url, title, extra from feed_items where source='twitter' and fetched_at > strftime('%s','now')-86400*14 "
                      "and json_extract(extra,'$.replies') >= 100 order by json_extract(extra,'$.replies') desc").fetchall()
    out, seen = [], set()
    for rid, url, title, ex in rows:
        e = json.loads(ex)
        if e["author"] in seen:
            continue
        seen.add(e["author"])
        out.append({"id": rid.split(":")[-1], "title": title, "url": url, "points": e.get("followers", 0), "comments": e["replies"], "link": url, "ts": 0, "author": e["author"]})
    return out[:limit]


def _gx(c: httpx.Client, path: str, params: dict) -> dict:
    r = c.get("https://api.getxapi.com" + path, params=params, headers={"Authorization": f"Bearer {os.environ['GETXAPI_KEY'].strip()}"})
    r.raise_for_status()
    return r.json() or {}


def _reply(x: dict) -> dict | None:
    text = re.sub(r"^(@\w+\s+)+", "", hnd.comment_text(x.get("text") or ""))
    a = x.get("author") or {}
    if not text or not a.get("userName"):
        return None
    return {"tid": str(x.get("id")), "depth": 0, "author": a["userName"], "text": text[:hnd.MAX_COMMENT], "replies": 0, "likes": x.get("likeCount") or 0,
            "fol": a.get("followers") or 0}


def x_replies(c: httpx.Client, tid: str, top_pages: int = X_TOP_PAGES, new_pages: int = X_NEW_PAGES) -> list[dict]:
    """高赞回复（搜索 conversation_id + min_faves，Top）在前，再补最新回复；按 id 去重。"""
    hn.load_env()
    got: dict[str, dict] = {}
    cur = ""
    for _ in range(top_pages):
        d = _gx(c, "/twitter/tweet/advanced_search", {"q": f"conversation_id:{tid} min_faves:{X_MIN_FAVES} filter:replies", "product": "Top", "cursor": cur})
        for x in d.get("tweets") or []:
            if (r := _reply(x)):
                got.setdefault(r["tid"], r)
        cur = d.get("next_cursor") or ""
        if not d.get("has_more") or not cur:
            break
    n_top, cur = len(got), ""
    for _ in range(new_pages):
        d = _gx(c, "/twitter/tweet/replies", {"id": tid, "cursor": cur})
        for x in d.get("replies") or []:
            if (r := _reply(x)):
                got.setdefault(r["tid"], r)
        cur = d.get("next_cursor") or ""
        if not d.get("has_more") or not cur:
            break
    out = sorted(got.values(), key=lambda r: -r["likes"])
    return out[:X_MAX_REPLIES]


def dedup_replies(rs: list[dict]) -> list[dict]:
    """同一句话只留一条，同一个人最多留 2 条（刷屏、模板回复）。"""
    seen, per, out = set(), {}, []
    for r in rs:
        k = re.sub(r"\W+", "", r["text"].lower())[:80]
        if k in seen or per.get(r["author"], 0) >= 2:
            continue
        seen.add(k)
        per[r["author"]] = per.get(r["author"], 0) + 1
        out.append(r)
    return out


def x_thread(c: httpx.Client, p: dict) -> tuple[str, list[dict]]:
    rs = dedup_replies(x_replies(c, p["id"]))
    return p["author"], [{**r, "id": n + 1} for n, r in enumerate(rs)]


def xart_posts(limit: int) -> list[dict]:
    db = sqlite3.connect(f"file:{DATA_DIR / 'app.db'}?mode=ro", uri=True)
    rows = db.execute("select id, user, title, summary, likes, views from x_art where stage='scored' order by q desc, likes desc limit 80").fetchall()
    out = []
    with httpx.Client(timeout=30) as c:
        hn.load_env()
        for tid, user, title, summary, likes, views in rows:
            n = _gx(c, "/twitter/tweet/replies", {"id": tid}).get("reply_count") or 0
            if n >= X_ART_MIN_REPLIES:
                out.append({"id": tid, "title": title, "url": f"https://x.com/{user}/status/{tid}", "points": likes, "comments": n, "link": f"https://x.com/{user}/status/{tid}",
                            "ts": 0, "author": user, "summary": summary or ""})
            if len(out) >= limit:
                break
    return out


def digest(r: CRun, p: dict, c: httpx.Client) -> dict | None:
    f = r.dir / f"{p['id']}.json"
    if f.exists():
        return json.loads(f.read_text("utf-8"))
    if r.source in ("x", "xart"):
        op, comments = x_thread(c, p)
        read = len(comments)
        if r.jev_min:
            sc = jev_scores([x["text"] for x in comments])
            keep = [x for x, v in zip(comments, sc) if v >= r.jev_min or (x["fol"] >= X_BIG and v >= 0.4)]
            comments = [{**x, "id": n + 1} for n, x in enumerate(keep)]
    else:
        op, comments = lobsters_thread(c, p) if r.source == "lobsters" else forum_thread(c, r.source, p)
        read = len(comments)
    if len(comments) < 8:
        return None
    text = hnd.render(comments)
    before = r.cost.get("digest", 0.0)
    t0 = time.time()
    raw = r.call(r.light, system(r.source), hnd._payload({"title": p["title"], "url": p["url"], "summary": p.get("summary", ""), "popularity": p["points"]}, text))
    if not isinstance(raw, dict):
        return None
    d = hnd.clean_digest(raw, comments, text, op)
    d["post"] = p
    d["cost"] = round(r.cost.get("digest", 0.0) - before, 4)
    d["secs"] = round(time.time() - t0)
    d["chars"] = len(text)
    d["fetched"] = read
    f.write_text(json.dumps(d, ensure_ascii=False), "utf-8")
    return d


def run(source: str, limit: int, jev_min: float = 0.0) -> list[dict]:
    r = CRun(source, jev_min)
    with httpx.Client(timeout=hnd.TIMEOUT, follow_redirects=True) as c:
        posts = x_posts(limit) if source == "x" else xart_posts(limit) if source == "xart" else lobsters_posts(c, limit) if source == "lobsters" else forum_posts(c, source, limit)
        with ThreadPoolExecutor(hnd.WORKERS) as ex:
            res = list(ex.map(lambda p: digest(r, p, c), posts))
    return [d for d in res if d]


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True, choices=list(NAMES))
    ap.add_argument("--limit", type=int, default=8)
    ap.add_argument("--jev-min", type=float, default=0.0)
    a = ap.parse_args()
    ds = run(a.source, a.limit, a.jev_min)
    print(a.source, len(ds), "帖", "费用 $%.3f" % sum(d["cost"] for d in ds))
