"""高人方法：名人名单里的人提出、推荐或亲身采用的、很有启发的做法和观点（怎么提升判断力、怎么组织知识、怎么用 AI 干活），带署名、原话和原始出处。

collect 采三类材料 → screen Jev 判材料里有没有归到本人的启发性内容，低的不进模型 → extract 逐段抽（引文逐字核对，打启发度）
→ merge 按人归并 → page 只留启发度最高的一档。
- own：本人高赞推文（X 按点赞门槛分几档搜，老的经典帖也能拿到）
- retell：长文库里点名这个人的文章，只取名字前后的片段
- link：手动加的链接（访谈、博客），抓正文
结果存 data/people_methods/，抽取结果按材料缓存，重跑只处理新材料。页面读 page.json（接口见 feed.py）。

    python -m app.modules._people_methods --people karpathy,dean
"""
from __future__ import annotations

import argparse
import collections
import datetime
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from functools import cache
from pathlib import Path

import feedparser
import httpx

from .. import agent, settings, usage
from ..db import DATA_DIR, DB_PATH, ROOT
from . import _absorb_run as ar
from . import _feed_sources as src
from . import _intel_snap as snap
from . import _people as P

BASE = DATA_DIR / "people_methods"
LINKS = BASE / "links.json"
STAGES = ["collect", "screen", "extract", "merge", "page"]
STAGE_NAME = {"collect": "采集材料", "screen": "Jev 筛材料", "extract": "逐段抽方法和观点", "merge": "按人归并", "page": "生成页面数据"}
EXTRACT_DIR = "extract_v2"
JEV_CACHE = "jev.json"
JEV_MIN = 0.8       # 两人试跑校准：留约四成材料、三分之一字符，最终卡片用到的材料保住 25/27
JEV_TEXT = 1500
SPARK_MIN = 3
RATINGS = "ratings.json"  # 你给卡片打的星，和提炼结果分开存，重跑不丢
OWN_STATE = "own.json"   # 每人本人推文抓到哪天；之后只抓这之后的（往回多搭 3 天，晚到的高赞也能补上）
OWN_OVERLAP = 3
WEEK_DAYS = 7
RETRY_S = 3 * 3600
FAVES = (300, 3000, 20000)
QUARTERS = 4
PAGE_FULL = 18     # 一页约 20 条，接近满页说明窗口里还有更多
SNIP_WIDTH = 700
SNIP_MAX = 3000
LINK_MAX = 12000    # 手动加的链接本来就是讲这个人的访谈 / 报道，整篇给模型
LATIN = r"[A-Za-z\u00C0-\u024F]+"   # 拉丁字母含重音（Lütke、François），不吞中文
NOTE_HEAD = 1500    # 深读笔记开头（标题、嘉宾、摘要）里点到名才算是讲这个人的
BLOG_MAX = 20
SURNAME_MIN = 6     # 只写姓的提法（“Karpathy 说”）也算点名；Dean、Musk 这类短姓太常见，要全名
BATCH = 6

P_JEV = ("state.items.{k} 是一段和 {name} 有关的材料（{kind}）。读者是做 AI 产品和 Agent 的工程师，想学高人怎么做事、怎么想问题。"
         "只有当材料里有明确归到 {name} 本人、而且很有启发的内容时回答是：读者可以照着做的做法或习惯（工作流、学习方法、做判断和决策、组织知识、用 AI 干活、带团队），"
         "或者有洞见、反直觉、能改变读者看法的观点判断，并讲了理由或经历。"
         "回答否：发布公告、祝贺感谢、闲聊玩笑和随手转发、新闻人事和公司动态、文章作者自己的观点只是顺带提到他、常识和口号、对他的吹捧、标题党和赚钱话术。")
JEV_KIND = {"own": "本人发的推文或文章", "retell": "别人写的文章里提到他的片段", "link": "关于他的访谈或报道"}

P_EXTRACT = """你从材料里找出某位名人很有启发的“做法”或“观点”，读者是做 AI 产品和 Agent 的工程师，宁缺毋滥。
做法 = 读者可以照着做的做事、思考、学习、决策、管理知识、用 AI 工作、带团队的具体做法或习惯。
例：“写下未来一年可能重要的 10 件事，一年后回看哪些真的重要了，借此校准判断力”；“把资料放进 raw/，让 LLM 编译成互相链接的 wiki 并定期 lint，而不是每次重新检索”。
观点 = 有洞见、反直觉、能改变读者看法的判断，并且材料里讲了理由或经历。
不算：产品发布、新闻、融资、人事；单纯的技术事实；没有理由的表态；名人做的产品本身（除非讲了他怎么用它干活）；文章作者自己的东西（只是顺带提到名人）。
必须是材料明确归到这个人名下：他说的、他写的、他推荐的、他这样做的。拿不准不收；转述者夸张演绎、编造收入的不收。
输入是多段材料，每段开头 [S编号] 人物id（姓名）| 来源类型 | 正文。来源类型 own = 本人发的推文或文章，retell = 别人写的文章或推文，link = 访谈、报道。
每条给：
- s：材料编号；person：人物 id，照抄；kind：做法|观点；
- name：标题 ≤14 字；
- how：做法写具体怎么做（动作和步骤，看完就能照做）；观点写判断本身，说清在什么情况下成立。≤80 字；
- why：为什么有效 / 为什么这么判断 ≤50 字，按材料写，材料没讲写空串；
- try：读者今天就能做的最小一步 ≤40 字；观点类可以写“下次遇到……时先问自己……”，实在没有写空串；
- spark：启发度。3 = 少见、具体，读完会想马上试或会改变看法；2 = 有用但常见，或太依赖他的特殊处境；1 = 常识、口号、泛泛而谈；
- quote：材料里逐字连续摘录的一句 ≤200 字符，要能证明这是这个人的，保持原语言，不改写、不拼接；
- said：原话（材料是本人写的，或直接引用了本人的话）| 转述。
用中文写 name / how / why / try。只输出 JSON：{"r":[{"s":"S1","person":"…","kind":"做法|观点","name":"…","how":"…","why":"…","try":"…","spark":3,"quote":"…","said":"原话|转述"}]}，没有就给 {"r":[]}。"""

P_MERGE = """下面是从不同材料里抽出的、同一个人（{who}）的做法和观点，每行“编号 | 类型 | 标题 | 内容”。
把讲同一件事的归成一组（换说法、详略不同、不同人转述的都算同一个）；不同的不要硬合并。
每组写：name 标题 ≤14 字；how 做法写怎么做、观点写判断本身 ≤80 字；why 为什么 ≤50 字（没有写空串）；try 今天就能做的最小一步 ≤40 字（没有写空串）；refs 组内编号。
按对读者的价值从高到低排。只写输入里有的信息，不补充。
只输出 JSON：{{"g":[{{"name":"…","how":"…","why":"…","try":"…","refs":["u1",...]}}]}}"""


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip().lower()


def quote_ok(quote: str, text: str) -> bool:
    q = _norm(quote).strip("\"'“”‘’ …")
    return len(q) >= 8 and q in _norm(text)


@cache
def name_res(pid: str) -> list[re.Pattern]:
    p = P.by_id()[pid]
    last = p["name"].split()[-1]
    solo = [re.compile(rf"(?<![A-Za-z]){re.escape(last)}(?![A-Za-z])")] if not p.get("strict") and len(last) >= SURNAME_MIN and last.isascii() else []
    return P._name_res(pid) + solo


def named(p: dict, text: str) -> bool:
    return P.mentions(p, text) or any(r.search(text) for r in name_res(p["id"]))


def snippets(text: str, pid: str, width: int = SNIP_WIDTH) -> list[str]:
    spans = sorted((m.start(), m.end()) for r in name_res(pid) for m in r.finditer(text or ""))
    out: list[list[int]] = []
    for a, b in spans:
        lo, hi = max(0, a - width), min(len(text), b + width)
        if out and lo <= out[-1][1]:
            out[-1][1] = max(out[-1][1], hi)
        else:
            out.append([lo, hi])
    parts, total = [], 0
    for lo, hi in out:
        if total >= SNIP_MAX:
            break
        parts.append(text[lo:hi][: SNIP_MAX - total])
        total += len(parts[-1])
    return ["…".join(parts)] if parts else []


def assemble(groups: dict[str, list[dict]], units: dict[str, dict], sources: dict[str, dict]) -> list[dict]:
    cards = []
    for pid, gs in groups.items():
        for g in gs:
            refs = [u for u in g.get("refs", []) if u in units and units[u]["sid"] in sources]
            spark = max((units[u]["spark"] for u in refs), default=0)
            if not refs or spark < SPARK_MIN:
                continue
            srcs = [sources[units[u]["sid"]] for u in refs]
            kinds = collections.Counter(units[u]["kind"] for u in refs)
            own = [sources[units[u]["sid"]] for u in refs if sources[units[u]["sid"]]["kind"] == "own"
                   or (sources[units[u]["sid"]]["kind"] == "link" and units[u].get("said") == "原话")]
            origin = min(own or srcs, key=lambda s: s.get("date") or "9")
            evid = []
            for u in refs:
                s = sources[units[u]["sid"]]
                evid.append({"kind": s["kind"], "author": s["author"], "url": s["url"], "date": s.get("date", ""), "title": s.get("title", ""),
                             "quote": units[u]["quote"], "said": units[u].get("said", "")})
            evid.sort(key=lambda e: (e["kind"] != "own", e["kind"] != "link", e["date"] or ""))
            units_sorted = sorted(refs)
            cards.append({"person": pid, "key": hashlib.sha1("|".join(units_sorted).encode()).hexdigest()[:12], "units": units_sorted,
                          "kind": kinds.most_common(1)[0][0], "spark": spark, "name": g["name"], "how": g.get("how", ""), "why": g.get("why", ""), "try": g.get("try", ""),
                          "own": bool(own), "origin": {"url": origin["url"], "date": origin.get("date", ""), "author": origin["author"], "kind": origin["kind"]},
                          "retellers": len({s["author"].lower() for s in srcs if s["kind"] == "retell"}), "evidence": evid})
    return cards


def attach_ratings(people: list[dict], ratings: dict[str, dict]) -> None:
    """评分按卡片 key 存；重新归并后 key 会变（多了材料或换了分组），就按同一个人、共享条目最多的那条评分认回来。"""
    for g in people:
        mine = [r for r in ratings.values() if r.get("person") == g["person"]["id"]]
        for m in g["methods"]:
            r = ratings.get(m["key"])
            if not r:
                us = set(m["units"])
                best = max(mine, key=lambda x: len(us & set(x["units"])), default=None)
                r = best if best and us & set(best["units"]) else None
            m["stars"] = r["stars"] if r else 0


def rate(key: str, stars: int) -> bool:
    page = _read("page.json", None) or {}
    card = next(((g["person"]["id"], m) for g in page.get("people", []) for m in g["methods"] if m["key"] == key), None)
    if not card:
        return False
    pid, m = card
    ratings = _read(RATINGS, {})
    ratings = {k: v for k, v in ratings.items() if not (v.get("person") == pid and set(v["units"]) & set(m["units"]))}
    if stars:
        ratings[key] = {"stars": stars, "units": m["units"], "person": pid, "name": m["name"], "at": time.time()}
    tmp = BASE / (RATINGS + ".tmp")
    tmp.write_text(json.dumps(ratings, ensure_ascii=False), "utf-8")
    tmp.replace(BASE / RATINGS)
    return True


def links() -> list[dict]:
    try:
        return json.loads(LINKS.read_text("utf-8"))
    except (OSError, ValueError):
        return []


def add_link(url: str, person: str) -> list[dict]:
    BASE.mkdir(parents=True, exist_ok=True)
    xs = [x for x in links() if x["url"] != url] + [{"url": url, "person": person, "at": time.time()}]
    LINKS.write_text(json.dumps(xs, ensure_ascii=False, indent=1), "utf-8")
    return xs


class MRun(ar.Run):
    def __init__(self, pids: list[str]):
        self.topic, self.start, self.end, self.pids = "高人方法", "", "", pids
        self.dir = BASE
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / EXTRACT_DIR).mkdir(exist_ok=True)
        self.light, self.strong = agent.tier_model("standard") or "claude-sonnet-5-5", agent.tier_model("standard") or "claude-sonnet-5-5"
        self.cost, self.secs, self.fails = {}, {}, {}
        self.lock = threading.Lock()
        self.stage = ""

    def status(self, **kw) -> None:
        old = self.load("status.json") if self.has("status.json") else {}
        self.save("status.json", {**old, "pid": os.getpid(), "stage": self.stage, "stage_name": STAGE_NAME.get(self.stage, ""),
                                  "step": STAGES.index(self.stage) + 1 if self.stage in STAGES else 0, "steps": len(STAGES),
                                  "cost": {**old.get("cost", {}), **self.cost}, "secs": {**old.get("secs", {}), **self.secs}, "people": self.pids, "updated": time.time(), **kw})


# ---------- 1 采集 ----------

def _months_back(d: datetime.date, k: int) -> datetime.date:
    m = d.year * 12 + d.month - 1 - k
    return datetime.date(m // 12, m % 12 + 1, min(d.day, 28))


def windows(today: str, n: int = QUARTERS) -> list[tuple[str, str]]:
    t = datetime.date.fromisoformat(today)
    edges = [t + datetime.timedelta(days=1)] + [_months_back(t, 3 * k) for k in range(1, n + 1)]
    return [(edges[i + 1].isoformat(), edges[i].isoformat()) for i in range(n)]


def own_windows(today: str, last: str) -> list[tuple[str, str]]:
    if not last:
        return windows(today)
    lo = datetime.date.fromisoformat(last) - datetime.timedelta(days=OWN_OVERLAP)
    return [(lo.isoformat(), (datetime.date.fromisoformat(today) + datetime.timedelta(days=1)).isoformat())]


def own_queries(handle: str, wins: list[tuple[str, str]], search) -> list[dict]:
    """每个季度窗口先用低门槛搜；返回满一页（说明还有被挤掉的）就抬高门槛再搜，老的高赞帖也拿得到。"""
    out = []
    for lo, hi in wins:
        for f in FAVES:
            got = search(f"from:{handle} min_faves:{f} -filter:replies since:{lo} until:{hi}")
            out += got
            if len(got) < PAGE_FULL:
                break
    return out


def own_x(pool: list[dict], last: dict[str, str]) -> list[dict]:
    provs = src._x_providers()
    if not provs:
        raise RuntimeError("未配置 GETXAPI_KEY / TWITTER_API_KEY")
    today = datetime.date.today().isoformat()
    out: dict[str, dict] = {}
    with src._client() as c:
        def search(q):
            for i in range(3):
                try:
                    return src._x_call(c, provs, "search", q)
                except Exception:  # noqa: BLE001
                    time.sleep(5 * (i + 1))
            return []

        def one(p):
            return p, own_queries(p["x"], own_windows(today, last.get(p["id"], "")), search)
        with ThreadPoolExecutor(4) as ex:
            for p, tweets in ex.map(one, [p for p in pool if p.get("x")]):
                for t in tweets:
                    it = src.x_item(t, "people")
                    if not it or (it["extra"].get("author") or "").lower() != p["x"].lower():
                        continue
                    out[it["id"]] = {"id": it["id"], "kind": "own", "person": p["id"], "author": p["x"], "url": it["url"], "date": it["date"][:10],
                                     "title": it["title"], "likes": it["popularity"], "text": src.clean(t.get("text"), SNIP_MAX * 4)}
    return list(out.values())


def _cheap_keys(p: dict) -> tuple[set[str], list[str]]:
    """粗筛用：英文名拆成小写单词（文章里出现了这些词才可能点名），中文名直接子串。"""
    names = [n for n in [p["name"], p.get("zh", ""), *p.get("aliases", [])] if n]
    words = {w.lower() for n in names if not P.is_zh(n) for w in re.findall(LATIN, n)}
    return words, [n for n in names if P.is_zh(n)]


def retell_x_art(pool: list[dict]) -> list[dict]:
    """先用单词集合和子串粗筛出可能点名的人，再对这几个人跑精确正则（全员逐个跑正则要十几分钟）。"""
    keys = {p["id"]: _cheap_keys(p) for p in pool}
    out = []
    c = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    for aid, user, title, day, text in c.execute("select id, user, title, day, text from x_art where text!='' and stage not in ('drop_dup')"):
        words = set(re.findall(LATIN, text.lower()))
        for p in pool:
            en, zh = keys[p["id"]]
            if not (en & words or any(n in text for n in zh)):
                continue
            parts = snippets(text, p["id"])
            if not parts:
                continue
            kind = "own" if (user or "").lower() == (p.get("x") or "").lower() else "retell"
            out.append({"id": f"xart:{aid}:{p['id']}", "kind": kind, "person": p["id"], "author": user, "url": f"https://x.com/{user}/status/{aid}",
                        "date": day, "title": title, "text": parts[0] if kind == "retell" else text[:SNIP_MAX]})
    return out


def blog_entry(p: dict, e: dict) -> dict:
    html = ((e.get("content") or [{}])[0].get("value") or e.get("summary") or "")
    tm = e.get("published_parsed") or e.get("updated_parsed")
    return {"id": f"blog:{e['link']}", "kind": "own", "person": p["id"], "author": _host(e["link"]), "url": e["link"],
            "date": "%04d-%02d-%02d" % tuple(tm[:3]) if tm else "", "title": e.get("title", ""),
            "text": snap.extract_text(html, "text/html")[:SNIP_MAX * 4]}


def blog_sources(pool: list[dict]) -> list[dict]:
    """本人博客订阅源：全文输出的直接用，只给摘要的再抓正文。"""
    out = []
    with src._client() as c:
        def one(p):
            try:
                r = c.get(p["rss"], headers={"User-Agent": src.BROWSER_UA})
                r.raise_for_status()
                return p, feedparser.parse(r.text).entries
            except Exception:  # noqa: BLE001
                return p, []
        with ThreadPoolExecutor(4) as ex:
            for p, entries in ex.map(one, [p for p in pool if p.get("rss")]):
                for e in entries[:BLOG_MAX]:
                    if not e.get("link"):
                        continue
                    s = blog_entry(p, e)
                    if len(s["text"]) < 1500:
                        s["text"] = (fetch_text(s["url"]) or s["text"])[:SNIP_MAX * 4]
                    out.append(s)
    return out


def chunks(text: str, size: int = LINK_MAX) -> list[str]:
    """长访谈 / 转写按段落切成几块，整篇都读到（只截前一段会漏掉后面讲的方法）。"""
    out, cur = [], ""
    for para in re.split(r"(?<=\n\n)", text):
        while len(para) > size:
            if cur:
                out.append(cur)
                cur = ""
            out.append(para[:size])
            para = para[size:]
        if len(cur) + len(para) > size:
            out.append(cur)
            cur = ""
        cur += para
    return [c for c in out + [cur] if c.strip()]


def fetch_text(url: str) -> str:
    try:
        code, ct, body = snap.fetch_retry(url)
        text = snap.extract_text(body, ct, url) if code < 400 else ""
        if len(text) < 500:
            code, ct, body = snap.jina_fetch(url)
            text = snap.normalize(body) if code < 400 else ""
        return text
    except Exception:  # noqa: BLE001
        return ""


def _host(url: str) -> str:
    return re.sub(r"^www\.", "", re.sub(r"^https?://([^/]+).*", r"\1", url))


def picked_sources(picked: list[dict], prev: dict[str, dict]) -> list[dict]:
    """人挑过的材料（手动链接、深读过的访谈和文章）：已经抓过的沿用，新的才抓正文；长的按段切块。"""
    out = []
    for x in picked:
        old = [s for s in prev.values() if s["url"] == x["url"] and s["person"] == x["person"]]
        if old:
            out += [{**o, "date": x.get("date") or o["date"]} for o in old]
            continue
        text = x.get("text") or fetch_text(x["url"])
        for k, part in enumerate(chunks(text)):
            out.append({"id": f"link:{x['url']}#{k}", "kind": "link", "person": x["person"], "author": x.get("author") or _host(x["url"]),
                        "url": x["url"], "date": x.get("date", ""), "title": x.get("title") or text.splitlines()[0][:80], "text": part})
    return out


def learn_people(title: str, note: str, pool: list[dict]) -> list[str]:
    head = f"{title}\n{note[:NOTE_HEAD]}"
    return [p["id"] for p in pool if any(r.search(head) for r in name_res(p["id"]))]


def upload_day(d: Path) -> str:
    """深读视频的发布日期（video.json 的 upload_date，如 20261110）；文章没有可靠的发布日期，留空。"""
    try:
        u = str(json.loads((d / "video.json").read_text("utf-8")).get("upload_date") or "")
    except (OSError, ValueError):
        return ""
    return f"{u[:4]}-{u[4:6]}-{u[6:8]}" if re.fullmatch(r"\d{8}", u) else ""


def learn_picks(pool: list[dict]) -> list[dict]:
    """深读里讲到名单上的人的访谈 / 演讲 / 文章：视频用本地转写，文章抓原文。"""
    out = []
    c = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    for kind, url, title, path in c.execute("select kind, url, title, output_path from learn_items where status='done' and kind in ('video', 'article')"):
        d = Path(path or "").parent
        note = (d / "note.md").read_text("utf-8", errors="replace") if (d / "note.md").exists() else ""
        tr = d / "transcript.md"
        text = tr.read_text("utf-8", errors="replace") if kind == "video" and tr.exists() else ""
        if kind == "video" and not text:
            continue
        for pid in learn_people(title or "", note, pool):
            out.append({"url": url, "person": pid, "title": title or "", "text": text, "author": "深读" if text else "", "date": upload_day(d)})
    return out


def s_collect(r: MRun) -> list:
    """本人推文、博客增量抓，和上次的合并（订阅源只给最近几篇）；长文库每次重扫；手动链接和深读抓过的沿用。"""
    pool = [P.by_id()[i] for i in r.pids]
    ids = {p["id"] for p in pool}
    last = r.load(OWN_STATE) if r.has(OWN_STATE) else {}
    prev = {s["id"]: s for s in (r.load("collect.json") if r.has("collect.json") else []) if s["person"] in ids}
    tweets = {k: v for k, v in prev.items() if v["kind"] == "own" and not k.startswith("blog:")}
    tweets |= {s["id"]: s for s in own_x(pool, last)}
    r.save(OWN_STATE, {**last, **{p["id"]: datetime.date.today().isoformat() for p in pool if p.get("x")}})
    blogs = {k: v for k, v in prev.items() if k.startswith("blog:")} | {s["id"]: s for s in blog_sources(pool)}
    picked = [x for x in links() if x["person"] in ids] + learn_picks(pool)
    old = {k: v for k, v in prev.items() if v["kind"] == "link"}
    return list(tweets.values()) + list(blogs.values()) + retell_x_art(pool) + picked_sources(picked, old)


# ---------- 2 Jev 筛材料 ----------

def screened(sources: list[dict], scores: dict[str, float]) -> list[dict]:
    """手动加的链接是人挑过的，直接放行；Jev 没打上分的也放行（宁可多花一点，不悄悄丢材料）。"""
    return [s for s in sources if s["kind"] == "link" or scores.get(s["id"], 1.0) >= JEV_MIN]


def _jev_key(s: dict) -> str:
    return hashlib.sha1(s["text"][:JEV_TEXT].encode()).hexdigest()[:12]


def jev(sources: list[dict], cache: dict[str, dict]) -> tuple[dict[str, dict], list[str]]:
    from ._absorb_hn import JEV_API
    key = os.environ.get("JEV_API_KEY", "").strip() or os.environ.get("TYPESAFE_API_KEY", "").strip()
    todo = [s for s in sources if s["kind"] != "link" and (cache.get(s["id"]) or {}).get("h") != _jev_key(s)]
    if not key:
        return cache, ["未配置 JEV_API_KEY，材料不筛，全部进抽取"] if todo else []
    idx, errs = P.by_id(), []
    with httpx.Client(timeout=120) as c:
        for i in range(0, len(todo), 20):
            refs = {f"i{n}": s for n, s in enumerate(todo[i:i + 20])}
            try:
                r = c.post(JEV_API, headers={"Authorization": f"Bearer {key}"}, json={"model": "jev-latest",
                           "state": {"items": {k: {"person": idx[s["person"]]["name"], "text": s["text"][:JEV_TEXT]} for k, s in refs.items()}},
                           "questions": {k: {"type": "noul", "instructions": P_JEV.format(k=k, name=idx[s["person"]]["name"], kind=JEV_KIND[s["kind"]])}
                                         for k, s in refs.items()}})
                r.raise_for_status()
                j = r.json()
                usage.record("people", usage.from_jev(j), engine="jev")
                ans = j.get("answers") or {}
            except Exception as e:  # noqa: BLE001
                errs.append(f"第 {i // 20 + 1} 批：{type(e).__name__}: {str(e)[:100]}")
                continue
            for k, s in refs.items():
                v = (ans.get(k) or {}).get("noul")
                if isinstance(v, (int, float)):
                    cache[s["id"]] = {"h": _jev_key(s), "p": round(float(v), 3)}
    return cache, errs


def s_screen(r: MRun) -> dict:
    sources = r.load("collect.json")
    cache, errs = jev(sources, r.load(JEV_CACHE) if r.has(JEV_CACHE) else {})
    r.save(JEV_CACHE, cache)
    scores = {s["id"]: cache[s["id"]]["p"] for s in sources if s["id"] in cache}
    keep = screened(sources, scores)
    return {"keep": [s["id"] for s in keep], "total": len(sources), "errors": errs,
            "by_kind": {k: [sum(s["kind"] == k for s in sources), sum(s["kind"] == k for s in keep)] for k in JEV_KIND}}


# ---------- 3 抽取 ----------

def _cache_name(sid: str) -> str:
    return re.sub(r"[^0-9A-Za-z_.-]+", "_", sid)[:150] + ".json"


def s_extract(r: MRun) -> dict:
    keep = set(r.load("screen.json")["keep"])
    sources = [s for s in r.load("collect.json") if s["id"] in keep]
    todo = [s for s in sources if not (r.dir / EXTRACT_DIR / _cache_name(s["id"])).exists()]

    def run(batch):
        idx = P.by_id()
        body = "\n\n".join(f"[S{k}] {s['person']}（{idx[s['person']]['name']}）| {s['kind']} | {s['text']}" for k, s in enumerate(batch))
        o = r.call(r.light, P_EXTRACT, body)
        if o is None:
            return
        got: dict[int, list] = {}
        for u in o.get("r", []):
            try:
                k = int(str(u.get("s", "")).lstrip("S"))
            except ValueError:
                continue
            ok = 0 <= k < len(batch) and u.get("name") and u.get("person") == batch[k]["person"] and u.get("kind") in ("做法", "观点") \
                and u.get("spark") in (1, 2, 3) and quote_ok(u.get("quote", ""), batch[k]["text"])
            if ok:
                got.setdefault(k, []).append({kk: u.get(kk, "") for kk in ("kind", "name", "how", "why", "try", "spark", "quote", "said")})
        for k, s in enumerate(batch):
            (r.dir / EXTRACT_DIR / _cache_name(s["id"])).write_text(json.dumps(got.get(k, []), ensure_ascii=False), "utf-8")
    ar._pmap(run, [todo[i:i + BATCH] for i in range(0, len(todo), BATCH)], 8)
    units = {}
    for s in sources:
        f = r.dir / EXTRACT_DIR / _cache_name(s["id"])
        for i, u in enumerate(json.loads(f.read_text("utf-8")) if f.exists() else []):
            units[f"{s['id']}#{i}"] = {**u, "sid": s["id"], "person": s["person"]}
    return {"sources": len(sources), "new": len(todo), "units": units}


# ---------- 4 归并 ----------

def plan_merge(by: dict[str, list[str]], prev: dict[str, dict]) -> tuple[dict[str, dict], list[str]]:
    """材料没变的人沿用上次的归并（省钱，标题也不变）；有新条目的人重新归并。"""
    keep = {pid: prev[pid] for pid, ks in by.items() if pid in prev and sorted(prev[pid]["refs"]) == sorted(ks)}
    return keep, [pid for pid in by if pid not in keep]


def s_merge(r: MRun) -> dict:
    units = r.load("extract.json")["units"]
    by: dict[str, list[str]] = {}
    for k, u in units.items():
        if u["spark"] >= SPARK_MIN:
            by.setdefault(u["person"], []).append(k)
    keep, todo = plan_merge(by, r.load("merge.json") if r.has("merge.json") else {})
    idx = P.by_id()

    def run(pid):
        ks = by[pid]
        if len(ks) == 1:
            u = units[ks[0]]
            return pid, {"refs": ks, "g": [{"name": u["name"], "how": u["how"], "why": u["why"], "try": u["try"], "refs": ks}]}
        lines = "\n".join(f"u{n} | {units[k]['kind']} | {units[k]['name']} | {units[k]['how']}" for n, k in enumerate(ks))
        o = r.call(r.strong, P_MERGE.format(who=idx[pid]["name"]), lines)
        if o is None:
            raise RuntimeError(f"{idx[pid]['name']} 归并失败")
        gs = [{**g, "refs": [ks[int(u[1:])] for u in g["refs"] if re.fullmatch(r"u\d+", str(u)) and int(u[1:]) < len(ks)]}
              for g in o.get("g", []) if g.get("name") and g.get("refs")]
        return pid, {"refs": ks, "g": gs}
    return {**keep, **dict(ar._pmap(run, todo, 6))}


# ---------- 5 页面 ----------

def s_page(r: MRun) -> dict:
    sources = {s["id"]: s for s in r.load("collect.json")}
    cards = assemble({pid: m["g"] for pid, m in r.load("merge.json").items()}, r.load("extract.json")["units"], sources)
    idx = P.by_id()
    people = []
    for pid in dict.fromkeys(c["person"] for c in cards):
        p = idx[pid]
        mine = [c for c in cards if c["person"] == pid]
        mine.sort(key=lambda c: (not c["own"], -len(c["evidence"])))
        people.append({"person": {k: p.get(k) for k in ("id", "name", "zh", "x", "tier", "role", "group")}, "methods": mine})
    people.sort(key=lambda g: (g["person"]["tier"], -sum(c["own"] for c in g["methods"]), -len(g["methods"])))
    return {"built": time.time(), "people": people, "n": len(cards),
            "sources": {"tweet": sum(s["kind"] == "own" and not k.startswith("blog:") for k, s in sources.items()),
                        "blog": sum(k.startswith("blog:") for k in sources), "retell": sum(s["kind"] == "retell" for s in sources.values()),
                        "picked": len({s["url"] for s in sources.values() if s["kind"] == "link"})},
            "screened": len(r.load("screen.json")["keep"])}


def _read(name: str, default):
    try:
        return json.loads((BASE / name).read_text("utf-8"))
    except (OSError, ValueError):
        return default


def _alive(pid) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, TypeError, ValueError):
        return False


def state() -> dict:
    st = _read("status.json", {})
    running = not st.get("done") and not st.get("error") and _alive(st.get("pid"))
    return {"running": running, "stage_name": st.get("stage_name", ""), "step": st.get("step", 0), "steps": len(STAGES),
            "error": "" if running else st.get("error", ""), "cost": round(sum((st.get("cost") or {}).values()), 2), "updated": st.get("updated")}


def view() -> dict:
    page = _read("page.json", None)
    if page:
        attach_ratings(page["people"], _read(RATINGS, {}))
    return {"data": page, "links": links(), **state()}


def due(st: dict, now: float, running: bool = False, days: float = WEEK_DAYS) -> bool:
    if running:
        return False
    if not st:
        return True
    gap = now - float(st.get("updated") or 0)
    return gap >= days * 86400 if st.get("done") else gap >= RETRY_S


def maybe_run(now: float | None = None) -> bool:
    """每周一次增量（信息推荐的定时循环里调）；失败或中断的 3 小时后从断点接着跑。"""
    if not settings.get("people.methods_weekly", True):
        return False
    return due(_read("status.json", {}), now or time.time(), state()["running"]) and start()["started"]


def start(pids: list[str] | None = None) -> dict:
    if state()["running"]:
        return {"started": False, **state()}
    BASE.mkdir(parents=True, exist_ok=True)
    args = [sys.executable, "-m", "app.modules._people_methods"] + ([f"--people={','.join(pids)}"] if pids else [])
    with open(BASE / "run.log", "a") as log:
        p = subprocess.Popen(args, cwd=str(ROOT), env=agent.clean_env(), stdout=log, stderr=log, start_new_session=True)
    st = _read("status.json", {})
    (BASE / "status.json").write_text(json.dumps({**st, "pid": p.pid, "done": False, "error": "", "updated": time.time()}, ensure_ascii=False), "utf-8")
    return {"started": True, **state()}


FUNCS = {"collect": s_collect, "screen": s_screen, "extract": s_extract, "merge": s_merge, "page": s_page}


def main(pids: list[str]) -> None:
    r = MRun(pids)
    r.status(done=False, error="", started=time.time(), cost={})
    try:
        for name in STAGES:
            r.stage = name
            r.status()
            t = time.time()
            r.save(name + ".json", FUNCS[name](r))
            r.secs[name] = round(time.time() - t, 1)
        r.status(done=True)
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        r.status(error=f"{STAGE_NAME.get(r.stage, r.stage)}失败：{e}")


if __name__ == "__main__":
    from ._absorb_hn import load_env
    load_env()
    ap = argparse.ArgumentParser()
    ap.add_argument("--people", default="", help="逗号分隔的人物 id；空 = 名单里全部")
    a = ap.parse_args()
    main([x for x in a.people.split(",") if x] or [p["id"] for p in P.people()])
