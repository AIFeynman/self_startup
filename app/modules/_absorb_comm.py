"""其他社区（Lobsters、官方产品论坛）的评论区提炼试点：只做采集 + 单帖提炼，看效果和成本，不进 HN 吸收的页面、定时和缓存。

复用 _feed_hn 的提示词、逐字原话核对和链接校验；结果存 data/absorb/comm/<来源>/，每帖一个 json，已有的不重跑。

    python -m app.modules._absorb_comm --source lobsters --limit 12
    python -m app.modules._absorb_comm --source openai --limit 6
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import time
from concurrent.futures import ThreadPoolExecutor

import httpx

from .. import agent
from ..db import DATA_DIR
from . import _absorb_run as ar
from . import _feed_hn as hnd

BASE = DATA_DIR / "absorb" / "comm"
UA = {"User-Agent": "Mozilla/5.0 (research pilot)"}
FORUMS = {"openai": "https://community.openai.com", "huggingface": "https://discuss.huggingface.co", "cursor": "https://forum.cursor.com"}
NAMES = {"lobsters": "Lobsters", "openai": "OpenAI 开发者社区", "huggingface": "Hugging Face 论坛", "cursor": "Cursor 论坛"}
MIN_COMMENTS = {"lobsters": 8}
MIN_DEFAULT = 15
MAX_POSTS_FETCH = 120


class CRun(ar.Run):
    def __init__(self, source: str):
        self.source, self.topic, self.stage = source, NAMES[source], "digest"
        self.dir = BASE / source
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


def digest(r: CRun, p: dict, c: httpx.Client) -> dict | None:
    f = r.dir / f"{p['id']}.json"
    if f.exists():
        return json.loads(f.read_text("utf-8"))
    op, comments = lobsters_thread(c, p) if r.source == "lobsters" else forum_thread(c, r.source, p)
    if len(comments) < 8:
        return None
    text = hnd.render(comments)
    before = r.cost.get("digest", 0.0)
    t0 = time.time()
    raw = r.call(r.light, system(r.source), hnd._payload({"title": p["title"], "url": p["url"], "popularity": p["points"]}, text))
    if not isinstance(raw, dict):
        return None
    d = hnd.clean_digest(raw, comments, text, op)
    d["post"] = p
    d["cost"] = round(r.cost.get("digest", 0.0) - before, 4)
    d["secs"] = round(time.time() - t0)
    d["chars"] = len(text)
    f.write_text(json.dumps(d, ensure_ascii=False), "utf-8")
    return d


def run(source: str, limit: int) -> list[dict]:
    r = CRun(source)
    with httpx.Client(timeout=hnd.TIMEOUT, follow_redirects=True) as c:
        posts = lobsters_posts(c, limit) if source == "lobsters" else forum_posts(c, source, limit)
        with ThreadPoolExecutor(hnd.WORKERS) as ex:
            res = list(ex.map(lambda p: digest(r, p, c), posts))
    return [d for d in res if d]


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True, choices=list(NAMES))
    ap.add_argument("--limit", type=int, default=8)
    a = ap.parse_args()
    ds = run(a.source, a.limit)
    print(a.source, len(ds), "帖", "费用 $%.3f" % sum(d["cost"] for d in ds))
