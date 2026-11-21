"""高人方法：名人名单里的人提出、推荐或亲身采用的个人做法（怎么提升判断力、怎么组织知识、怎么用 AI 干活），带署名、原话和原始出处。

collect 采三类材料 → extract 逐段抽方法（引文逐字核对）→ merge 按人归并同一方法 → page 生成页面数据。
- own：本人高赞推文（X 按点赞门槛分几档搜，老的经典帖也能拿到）
- retell：长文库里点名这个人的文章，只取名字前后的片段
- link：手动加的链接（访谈、博客），抓正文
结果存 data/people_methods/，抽取结果按材料缓存，重跑只处理新材料。页面读 page.json（接口见 feed.py）。

    python -m app.modules._people_methods --people karpathy,dean
"""
from __future__ import annotations

import argparse
import datetime
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

from .. import agent
from ..db import DATA_DIR, DB_PATH, ROOT
from . import _absorb_run as ar
from . import _feed_sources as src
from . import _intel_snap as snap
from . import _people as P

BASE = DATA_DIR / "people_methods"
LINKS = BASE / "links.json"
STAGES = ["collect", "extract", "merge", "page"]
STAGE_NAME = {"collect": "采集材料", "extract": "逐段抽方法", "merge": "按人归并", "page": "生成页面数据"}
FAVES = (300, 3000, 20000)
QUARTERS = 4
PAGE_FULL = 18     # 一页约 20 条，接近满页说明窗口里还有更多
SNIP_WIDTH = 700
SNIP_MAX = 3000
LINK_MAX = 20000    # 手动加的链接本来就是讲这个人的访谈 / 报道，整篇给模型
SURNAME_MIN = 6     # 只写姓的提法（“Karpathy 说”）也算点名；Dean、Musk 这类短姓太常见，要全名
BATCH = 6

P_EXTRACT = """你从材料里找出“某位名人提出、推荐或亲身采用的个人方法”，供读者照着试。
方法 = 一个人可以照着做的做事、思考、学习、决策、管理知识、用 AI 工作的具体做法或习惯。
例：“写下未来一年可能重要的 10 件事，一年后回看哪些真的重要了，借此校准判断力”；“把资料放进 raw/，让 LLM 编译成互相链接的 wiki 并定期 lint，而不是每次重新检索”。
不算：对行业、公司、模型的预测和评论；产品发布、新闻、融资、人事；技术事实；只有观点没有做法；名人做的产品本身（除非讲了他怎么用它干活）；文章作者自己的方法（只是顺带提到名人）。
必须是材料明确归到这个人名下：他说的、他写的、他推荐的、他这样做的。拿不准不收；转述者夸张演绎、编造收入的不收。
输入是多段材料，每段开头 [S编号] 人物id | 来源类型 | 正文。来源类型 own = 本人发的推文或文章，retell = 别人写的文章或推文，link = 访谈、报道。
每条方法给：
- s：材料编号；person：人物 id，照抄；
- name：方法名 ≤14 字；
- how：具体怎么做 ≤80 字，写动作和步骤，读者看完就能照做；
- why：为什么有效 ≤50 字，按材料写，材料没讲写空串；
- try：读者今天就能做的最小一步 ≤40 字；
- quote：材料里逐字连续摘录的一句 ≤200 字符，要能证明这是这个人的方法，保持原语言，不改写、不拼接；
- said：原话（材料是本人写的，或直接引用了本人的话）| 转述。
用中文写 name / how / why / try。只输出 JSON：{"r":[{"s":"S1","person":"…","name":"…","how":"…","why":"…","try":"…","quote":"…","said":"原话|转述"}]}，没有就给 {"r":[]}。"""

P_MERGE = """下面是从不同材料里抽出的、同一个人（{who}）的个人方法，每行“编号 | 方法名 | 做法”。
把讲同一个做法的归成一组（换说法、详略不同、不同人转述的都算同一个）；不同做法不要硬合并。
每组写：name 方法名 ≤14 字；how 具体怎么做 ≤80 字；why 为什么有效 ≤50 字（没有写空串）；try 今天就能做的最小一步 ≤40 字；refs 组内编号。
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
            if not refs:
                continue
            srcs = [sources[units[u]["sid"]] for u in refs]
            own = [sources[units[u]["sid"]] for u in refs if sources[units[u]["sid"]]["kind"] == "own"
                   or (sources[units[u]["sid"]]["kind"] == "link" and units[u].get("said") == "原话")]
            origin = min(own or srcs, key=lambda s: s.get("date") or "9")
            evid = []
            for u in refs:
                s = sources[units[u]["sid"]]
                evid.append({"kind": s["kind"], "author": s["author"], "url": s["url"], "date": s.get("date", ""), "title": s.get("title", ""),
                             "quote": units[u]["quote"], "said": units[u].get("said", "")})
            evid.sort(key=lambda e: (e["kind"] != "own", e["kind"] != "link", e["date"] or ""))
            cards.append({"person": pid, "name": g["name"], "how": g.get("how", ""), "why": g.get("why", ""), "try": g.get("try", ""),
                          "own": bool(own), "origin": {"url": origin["url"], "date": origin.get("date", ""), "author": origin["author"], "kind": origin["kind"]},
                          "retellers": len({s["author"].lower() for s in srcs if s["kind"] == "retell"}), "evidence": evid})
    return cards


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
        (self.dir / "extract").mkdir(exist_ok=True)
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


def own_x(pool: list[dict]) -> list[dict]:
    provs = src._x_providers()
    if not provs:
        raise RuntimeError("未配置 GETXAPI_KEY / TWITTER_API_KEY")
    wins = windows(datetime.date.today().isoformat())
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
            return p, own_queries(p["x"], wins, search)
        with ThreadPoolExecutor(4) as ex:
            for p, tweets in ex.map(one, [p for p in pool if p.get("x")]):
                for t in tweets:
                    it = src.x_item(t, "people")
                    if not it or (it["extra"].get("author") or "").lower() != p["x"].lower():
                        continue
                    out[it["id"]] = {"id": it["id"], "kind": "own", "person": p["id"], "author": p["x"], "url": it["url"], "date": it["date"][:10],
                                     "title": it["title"], "likes": it["popularity"], "text": src.clean(t.get("text"), SNIP_MAX * 4)}
    return list(out.values())


def retell_x_art(pool: list[dict]) -> list[dict]:
    pre = re.compile("|".join(r.pattern for p in pool for r in name_res(p["id"])), re.I)
    out = []
    c = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    for aid, user, title, day, text in c.execute("select id, user, title, day, text from x_art where text!='' and stage not in ('drop_dup')"):
        if not pre.search(text):
            continue
        for p in pool:
            if not named(p, text):
                continue
            parts = snippets(text, p["id"])
            if not parts:
                continue
            kind = "own" if (user or "").lower() == (p.get("x") or "").lower() else "retell"
            out.append({"id": f"xart:{aid}:{p['id']}", "kind": kind, "person": p["id"], "author": user, "url": f"https://x.com/{user}/status/{aid}",
                        "date": day, "title": title, "text": parts[0] if kind == "retell" else text[:SNIP_MAX]})
    return out


def link_sources(pool: list[dict]) -> list[dict]:
    ids = {p["id"] for p in pool}
    out = []
    for x in links():
        if x["person"] not in ids:
            continue
        try:
            code, ct, body = snap.fetch_retry(x["url"])
            text = snap.extract_text(body, ct, x["url"]) if code < 400 else ""
            if len(text) < 500:
                code, ct, body = snap.jina_fetch(x["url"])
                text = snap.normalize(body) if code < 400 else ""
        except Exception:  # noqa: BLE001
            continue
        if not text:
            continue
        host = re.sub(r"^www\.", "", re.sub(r"^https?://([^/]+).*", r"\1", x["url"]))
        out.append({"id": f"link:{x['url']}", "kind": "link", "person": x["person"], "author": host, "url": x["url"],
                    "date": "", "title": text.splitlines()[0][:80], "text": text[:LINK_MAX]})
    return out


def s_collect(r: MRun) -> list:
    pool = [P.by_id()[i] for i in r.pids]
    return own_x(pool) + retell_x_art(pool) + link_sources(pool)


# ---------- 2 抽取 ----------

def _cache_name(sid: str) -> str:
    return re.sub(r"[^0-9A-Za-z_.-]+", "_", sid)[:150] + ".json"


def s_extract(r: MRun) -> dict:
    sources = r.load("collect.json")
    todo = [s for s in sources if not (r.dir / "extract" / _cache_name(s["id"])).exists()]

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
            if 0 <= k < len(batch) and u.get("name") and u.get("person") == batch[k]["person"] and quote_ok(u.get("quote", ""), batch[k]["text"]):
                got.setdefault(k, []).append({kk: u.get(kk, "") for kk in ("name", "how", "why", "try", "quote", "said")})
        for k, s in enumerate(batch):
            (r.dir / "extract" / _cache_name(s["id"])).write_text(json.dumps(got.get(k, []), ensure_ascii=False), "utf-8")
    ar._pmap(run, [todo[i:i + BATCH] for i in range(0, len(todo), BATCH)], 8)
    units, n = {}, 0
    for s in sources:
        f = r.dir / "extract" / _cache_name(s["id"])
        for u in (json.loads(f.read_text("utf-8")) if f.exists() else []):
            n += 1
            units[f"u{n}"] = {**u, "sid": s["id"], "person": s["person"]}
    return {"sources": len(sources), "new": len(todo), "units": units}


# ---------- 3 归并 ----------

def s_merge(r: MRun) -> dict:
    units = r.load("extract.json")["units"]
    by: dict[str, list[str]] = {}
    for k, u in units.items():
        by.setdefault(u["person"], []).append(k)
    idx = P.by_id()

    def run(pid):
        ks = by[pid]
        if len(ks) == 1:
            u = units[ks[0]]
            return pid, [{"name": u["name"], "how": u["how"], "why": u["why"], "try": u["try"], "refs": ks}]
        o = r.call(r.strong, P_MERGE.format(who=idx[pid]["name"]), "\n".join(f"{k} | {units[k]['name']} | {units[k]['how']}" for k in ks))
        return pid, [g for g in (o or {}).get("g", []) if g.get("name") and g.get("refs")]
    return dict(ar._pmap(run, list(by), 6))


# ---------- 4 页面 ----------

def s_page(r: MRun) -> dict:
    sources = {s["id"]: s for s in r.load("collect.json")}
    cards = assemble(r.load("merge.json"), r.load("extract.json")["units"], sources)
    idx = P.by_id()
    people = []
    for pid in dict.fromkeys(c["person"] for c in cards):
        p = idx[pid]
        mine = [c for c in cards if c["person"] == pid]
        mine.sort(key=lambda c: (not c["own"], -len(c["evidence"])))
        people.append({"person": {k: p.get(k) for k in ("id", "name", "zh", "x", "tier", "role", "group")}, "methods": mine})
    people.sort(key=lambda g: (g["person"]["tier"], -sum(c["own"] for c in g["methods"]), -len(g["methods"])))
    return {"built": time.time(), "people": people, "n": len(cards),
            "sources": {k: sum(s["kind"] == k for s in sources.values()) for k in ("own", "retell", "link")}}


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
    return {"data": _read("page.json", None), "links": links(), **state()}


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


FUNCS = {"collect": s_collect, "extract": s_extract, "merge": s_merge, "page": s_page}


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
