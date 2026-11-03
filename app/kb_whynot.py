"""论文「为什么不 XX」：读论文时先写下自己会怎么做不同的选择，再分两层对答案，练算法判断力。

- 写：在深读条目页写替代方案 XX + 我猜它比论文做法 更好 / 差不多 / 更差 / 说不准 + 信心 + 理由。
  同时作为一条判断进台账（kb_judgments，依据材料 = 这篇论文），归类、问题线、复查都走判断台账那套。
- 第一层「论文自己」：论文全文（PDF 转文字）+ 深读笔记，看消融 / 讨论 / 附录里有没有回答 XX。
- 第二层「后续论文」：Semantic Scholar 取这篇的引用论文（最多 2000 篇）+ 关键词检索补充 → 按关键词命中粗排 →
  LLM 读前 40 篇摘要，判断有没有人验证过 XX、结论是什么，带引用。没人做过 → 90 天后再查（写一条改期复查）。
- 计分：猜测和核验结论一致算命中（「有条件」算半个）；「还没人做」后来被验证的算「先想到」。
核验结果只追加（kb_whynot_checks），重查另起一行；Agent 的结论只作参考，台账里的复查结论仍由我来写。
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import math
import os
import random
import re
import subprocess
import threading
import time
from pathlib import Path

import httpx

from . import db, kb_judge
from .kb_graph import _clip, _j

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS kb_whynot (               -- 我写的「为什么不」（只追加）
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id INTEGER NOT NULL,                        -- learn_items.id
    judgment_id INTEGER,                             -- 同时记进判断台账的 kb_judgments.id
    alt TEXT NOT NULL,                               -- 替代方案 XX
    guess TEXT DEFAULT '说不准',                      -- 我猜 XX 比论文做法：更好 / 差不多 / 更差 / 说不准
    confidence TEXT DEFAULT '',
    reason TEXT DEFAULT '',
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS kb_whynot_checks (        -- 核验记录（只追加；重查另起一行）
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    wid INTEGER NOT NULL,
    layer TEXT NOT NULL,                             -- paper 论文自己 / followup 后续论文
    status TEXT DEFAULT 'running',                   -- running / done / failed
    verdict TEXT DEFAULT '',                         -- 见 VERDICTS
    summary TEXT DEFAULT '',
    detail TEXT DEFAULT '{}',                        -- {cites:[{title,year,url,finding,cites_original}], n_candidates, ...}
    secs REAL DEFAULT 0,
    at TEXT
);
CREATE INDEX IF NOT EXISTS idx_kb_whynot_item ON kb_whynot(item_id);
CREATE INDEX IF NOT EXISTS idx_kb_whynot_checks_wid ON kb_whynot_checks(wid);
CREATE TABLE IF NOT EXISTS kb_s2_cache (key TEXT PRIMARY KEY, data TEXT, at TEXT);
"""

GUESSES = ["更好", "差不多", "更差", "说不准"]
VERDICTS = ["XX 更好", "差不多", "XX 更差", "有条件", "没回答", "还没人做"]   # 前四个是有结论
RECHECK_DAYS = 90
MAX_CITATIONS = 2000
TOP_CANDIDATES = 40
S2 = "https://api.semanticscholar.org/graph/v1"
S2_FIELDS = "title,abstract,year,citationCount,externalIds,publicationDate"
STALE_MIN = 20                                       # running 超过这么久（多半服务重启了）当失败
_s2_lock = threading.Lock()
_s2_last = [0.0]


def _init() -> None:
    kb_judge._init()
    db.init([SCHEMA])


def llm_json(system: str, payload: dict, max_tokens: int = 4000) -> dict:
    from . import kb_graph      # 运行时取，测试里 monkeypatch kb_graph.llm_json 一处即可
    return kb_graph.llm_json(system, payload, max_tokens)


# ---------- 论文材料 ----------

def _item(item_id: int) -> dict:
    it = db.row("SELECT * FROM learn_items WHERE id=?", [item_id])
    if not it:
        raise ValueError("no item")
    return it


def arxiv_id(url: str) -> str:
    m = re.search(r"(\d{4}\.\d{4,5})(v\d+)?", url or "")
    return m.group(1) if m else ""


def paper_text(it: dict, limit: int = 60000) -> tuple[str, str]:
    """(深读笔记, 全文)。全文取条目目录里的 PDF（pdftotext，结果缓存在库里，不往条目目录写文件），没有就空。"""
    d = Path(it["output_path"]).parent if it.get("output_path") else None
    if not (d and d.is_dir()):
        return "", ""
    p = d / "note.md"
    note = p.read_text("utf-8", errors="ignore") if p.exists() else ""

    def pdf_text() -> str:
        for pdf in sorted(d.glob("*.pdf")):
            try:
                t = subprocess.run(["pdftotext", "-enc", "UTF-8", str(pdf), "-"], capture_output=True, text=True, timeout=60).stdout
            except (OSError, subprocess.TimeoutExpired):
                t = ""
            if t.strip():
                return t
        return ""
    full = _cached(f"fulltext:{d}", 365, pdf_text) or ""
    return _clip(note, 12000), _clip(full, limit)


# ---------- Semantic Scholar ----------

def _s2_headers() -> dict:
    key = (os.environ.get("SEMANTIC_SCHOLAR_API_KEY") or os.environ.get("S2_API_KEY") or "").strip()
    return {"x-api-key": key} if key else {}


def s2_get(path: str, params: dict | None = None, tries: int = 6) -> dict:
    """限速（有 key 每秒 1 次）+ 429 / 5xx 退避重试。"""
    gap = 1.05 if _s2_headers() else 0.5
    with httpx.Client(timeout=httpx.Timeout(60.0, connect=15.0)) as c:
        for n in range(tries):
            with _s2_lock:
                wait = _s2_last[0] + gap - time.monotonic()
                if wait > 0:
                    time.sleep(wait)
                _s2_last[0] = time.monotonic()
            try:
                r = c.get(S2 + path, params=params, headers=_s2_headers())
            except httpx.HTTPError:
                r = None
            if r is not None and r.status_code == 200:
                return r.json()
            if r is not None and r.status_code == 404:
                return {}
            if r is not None and r.status_code not in (429, 500, 502, 503, 504):
                raise RuntimeError(f"S2 {path} {r.status_code}: {r.text[:200]}")
            time.sleep(min(30, 1.5 * 1.6 ** n) + random.random())
    raise RuntimeError(f"S2 {path} 重试 {tries} 次仍失败")


def _cached(key: str, days: int, fn):
    r = db.row("SELECT data, at FROM kb_s2_cache WHERE key=?", [key])
    if r and r["at"][:10] >= kb_judge._add_days(db.today(), -days):
        return _j(r["data"], None)
    data = fn()
    db.execute("INSERT INTO kb_s2_cache(key, data, at) VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET data=excluded.data, at=excluded.at",
               [key, json.dumps(data, ensure_ascii=False), db.now()])
    return data


def s2_paper(it: dict) -> dict:
    """条目对应的 S2 论文：有 arXiv 号直接查，否则按标题匹配。"""
    ax = arxiv_id(it["url"])
    key = f"paper:{ax or it['title']}"
    def fetch():
        if ax:
            return s2_get(f"/paper/arXiv:{ax}", {"fields": "paperId," + S2_FIELDS})
        res = s2_get("/paper/search/match", {"query": it["title"], "fields": "paperId," + S2_FIELDS})
        return (res.get("data") or [{}])[0]
    return _cached(key, 30, fetch) or {}


def citations(pid: str) -> list[dict]:
    def fetch():
        out, off = [], 0
        while off < MAX_CITATIONS:
            res = s2_get(f"/paper/{pid}/citations", {"fields": S2_FIELDS, "limit": 1000, "offset": off})
            batch = [x["citingPaper"] for x in res.get("data") or [] if x.get("citingPaper", {}).get("title")]
            out += batch
            if res.get("next") is None or not batch:
                break
            off = res["next"]
        return out
    return _cached(f"cites:{pid}", 7, fetch) or []


def search(query: str, year: int) -> list[dict]:
    res = _cached(f"search:{query}:{year}", 7,
                  lambda: s2_get("/paper/search", {"query": query, "fields": S2_FIELDS, "limit": 40, "year": f"{year}-" if year else None}))
    return (res or {}).get("data") or []


def _url(p: dict) -> str:
    ax = (p.get("externalIds") or {}).get("ArXiv")
    return f"https://arxiv.org/abs/{ax}" if ax else f"https://www.semanticscholar.org/paper/{p.get('paperId', '')}"


def rank(cands: list[dict], kw: list[list[str]]) -> list[dict]:
    """关键词组命中粗排：每组（同义词）命中一次记 1 分，标题命中额外 +0.5；再按引用数微调。"""
    def score(p):
        t, a = (p.get("title") or "").lower(), (p.get("abstract") or "").lower()
        s = 0.0
        for group in kw:
            if any(w.lower() in t for w in group):
                s += 1.5
            elif any(w.lower() in a for w in group):
                s += 1
        return s + math.log10(1 + (p.get("citationCount") or 0)) * 0.15
    seen, out = set(), []
    for p in cands:
        k = p.get("paperId") or p.get("title")
        if k in seen or not p.get("abstract"):
            continue
        seen.add(k)
        p["_score"] = score(p)
        out.append(p)
    out.sort(key=lambda p: p["_score"], reverse=True)
    return [p for p in out if p["_score"] >= 1][:TOP_CANDIDATES]


# ---------- 两层核验 ----------

PAPER_SYSTEM = """用户读一篇论文时提出了「为什么不用 XX（替代方案）」，并猜了 XX 比论文做法更好 / 差不多 / 更差。
请只依据论文原文（fulltext，可能截断）和深读笔记（note），看论文自己有没有回答这个问题：消融实验、对比基线、讨论、局限、附录都算。
- verdict：论文给出的证据说明 XX 相对论文做法「XX 更好 / 差不多 / XX 更差 / 有条件」；论文没有正面回答写「没回答」。不要凭常识补结论。
- summary：两三句话说清论文怎么回答的（引用实验名 / 表号 / 数字），没回答就说论文最接近的相关内容是什么、为什么不算回答。
- quotes：最多 3 句原文关键句（英文原样，每句 ≤ 40 词），注明出处（如 Table 3 / Sec 4.2）。
- hint：给用户的一句提示：这个问题背后真正要权衡的是什么（不要直接宣布谁对）。
输出 JSON：{"verdict": "没回答", "summary": "…", "quotes": [{"text": "…", "where": "…"}], "hint": "…"}"""

KW_SYSTEM = """为了在后续论文里查「有没有人验证过某个替代方案」，请把替代方案 XX 拆成英文检索词。
- groups：3–5 组关键词，每组是同一个概念的 2–5 个英文同义说法（小写，短语即可），要能在论文标题 / 摘要里字面命中；
  不要放原论文本身就有的通用词（如 language model / agent），要抓住 XX 区别于原论文做法的那个点；
- queries：2–3 条给 Semantic Scholar 关键词检索用的英文短查询（3–6 个词）。
输出 JSON：{"groups": [["plan-and-execute", "plan then execute"], ["…"]], "queries": ["…"]}"""

FOLLOW_SYSTEM = """用户读论文 paper 时提出「为什么不用 XX」。下面是这篇论文之后发表的候选论文（candidates，带编号 n、年份、摘要、是否引用了原论文）。
请判断有没有论文实际验证了 XX（把 XX 或本质相同的做法和原论文做法 / 同类做法做了对比实验），结论是什么：
- verdict：综合这些论文，XX 相对原论文做法「XX 更好 / 差不多 / XX 更差 / 有条件」；没有任何论文真正做过这个对比写「还没人做」。
  只看摘要能确认的内容，摘要没说清的不算验证；宁可「还没人做」也不要硬凑。
- summary：两三句话：谁做了、怎么比的、结论；有条件就说清条件。
- cites：直接相关的论文（最多 6 篇）：n、finding（这篇在 XX 上的发现，一句话）、strength（直接对比 / 间接相关）。
- next：如果「还没人做」或证据不足，最值得看的下一步（一句话：找什么实验、或自己能做的最小实验）。
输出 JSON：{"verdict": "还没人做", "summary": "…", "cites": [{"n": 1, "finding": "…", "strength": "直接对比"}], "next": "…"}"""


def _payload_base(w: dict, it: dict) -> dict:
    return {"paper": {"title": it["title"], "url": it["url"]}, "XX": w["alt"],
            "user_guess": f"XX 比论文做法{w['guess']}", "user_reason": w["reason"]}


def check_paper(w: dict, it: dict) -> dict:
    note, full = paper_text(it)
    res = llm_json(PAPER_SYSTEM, {**_payload_base(w, it), "note": note, "fulltext": full}, max_tokens=2500)
    v = res.get("verdict") if res.get("verdict") in VERDICTS[:5] else "没回答"
    return {"verdict": v, "summary": _clip(res.get("summary") or "", 600),
            "detail": {"quotes": [q for q in res.get("quotes") or [] if isinstance(q, dict)][:3], "hint": _clip(res.get("hint") or "", 200),
                       "fulltext": bool(full)}}


def check_followup(w: dict, it: dict) -> dict:
    sp = s2_paper(it)
    if not sp.get("paperId"):
        return {"verdict": "", "summary": "在 Semantic Scholar 上没找到这篇论文，没法沿引用链查。", "detail": {}, "failed": True}
    kw = llm_json(KW_SYSTEM, _payload_base(w, it), max_tokens=800)
    groups = [[str(x) for x in g if x] for g in kw.get("groups") or [] if isinstance(g, list)][:5]
    year = sp.get("year") or 0
    cites = citations(sp["paperId"])
    cite_ids = {p.get("paperId") for p in cites}
    pool = list(cites)
    for q in (kw.get("queries") or [])[:3]:
        pool += search(str(q), year)
    cands = rank(pool, groups)
    detail = {"s2": {"title": sp.get("title"), "year": year, "citations": sp.get("citationCount")},
              "n_citations": len(cites), "n_candidates": len(cands), "keywords": groups}
    if not cands:
        return {"verdict": "还没人做", "summary": f"引用这篇的 {len(cites)} 篇论文和关键词检索里，没有摘要提到这个替代方案。",
                "detail": {**detail, "cites": []}}
    items = [{"n": i + 1, "title": p["title"], "year": p.get("year"), "cites_original": p.get("paperId") in cite_ids,
              "abstract": _clip(p.get("abstract") or "", 900)} for i, p in enumerate(cands)]
    res = llm_json(FOLLOW_SYSTEM, {**_payload_base(w, it), "candidates": items}, max_tokens=2500)
    v = res.get("verdict") if res.get("verdict") in ("XX 更好", "差不多", "XX 更差", "有条件", "还没人做") else "还没人做"
    out_cites = []
    for c in res.get("cites") or []:
        n = c.get("n") if isinstance(c, dict) else None
        if isinstance(n, int) and 1 <= n <= len(cands):
            p = cands[n - 1]
            out_cites.append({"title": p["title"], "year": p.get("year"), "url": _url(p), "cites_original": p.get("paperId") in cite_ids,
                              "finding": _clip(c.get("finding") or "", 240), "strength": c.get("strength") or ""})
    return {"verdict": v, "summary": _clip(res.get("summary") or "", 600),
            "detail": {**detail, "cites": out_cites[:6], "next": _clip(res.get("next") or "", 240)}}


def _run(wid: int, layers: tuple[str, ...]) -> None:
    w = db.row("SELECT * FROM kb_whynot WHERE id=?", [wid])
    it = _item(w["item_id"])
    for layer in layers:
        cid = db.insert("kb_whynot_checks", {"wid": wid, "layer": layer, "status": "running", "at": db.now()})
        t0 = time.monotonic()
        try:
            r = (check_paper if layer == "paper" else check_followup)(w, it)
            db.execute("UPDATE kb_whynot_checks SET status=?, verdict=?, summary=?, detail=?, secs=? WHERE id=?",
                       ["failed" if r.get("failed") else "done", r["verdict"], r["summary"],
                        json.dumps(r["detail"], ensure_ascii=False), round(time.monotonic() - t0, 1), cid])
            if layer == "followup" and r["verdict"] == "还没人做" and w.get("judgment_id"):
                kb_judge.review(f"my:{w['judgment_id']}", "snooze", f"联网核验：后续论文里还没人做过，{RECHECK_DAYS} 天后再查",
                                kb_judge._add_days(db.today(), RECHECK_DAYS))
        except Exception as e:  # noqa: BLE001 —— 一层失败不影响另一层，记下原因可重试
            log.exception("whynot %s %s", wid, layer)
            db.execute("UPDATE kb_whynot_checks SET status='failed', summary=?, secs=? WHERE id=?",
                       [_clip(str(e), 300), round(time.monotonic() - t0, 1), cid])


def start_check(wid: int, layers: tuple[str, ...] = ("paper", "followup"), wait: bool = False) -> None:
    if wait:
        _run(wid, layers)
    else:
        threading.Thread(target=_run, args=(wid, layers), daemon=True).start()


# ---------- 写入 / 读取 ----------

def add(item_id: int, alt: str, guess: str = "说不准", confidence: str = "", reason: str = "", *, check: bool = True) -> int:
    _init()
    alt = alt.strip()
    if not alt:
        raise ValueError("empty")
    it = _item(item_id)
    guess = guess if guess in GUESSES else "说不准"
    title = it["title"] or it["url"]
    text = f"《{_clip(title, 60)}》为什么不{alt if alt.startswith(('用', '做', '把', '让')) else '用' + alt}？" \
           + ("我猜效果说不准。" if guess == "说不准" else f"我猜它比论文的做法{guess}。")
    jid = kb_judge.add(text, "", confidence, "", reason,
                       [{"sid": f"item:{it['id']}", "title": title, "url": it["url"], "link": f"#learn/item/{it['id']}", "sub": "paper"}])
    wid = db.insert("kb_whynot", {"item_id": item_id, "judgment_id": jid, "alt": alt, "guess": guess,
                                  "confidence": confidence if confidence in ("高", "中", "低") else "",
                                  "reason": reason.strip(), "created_at": db.now()})
    if check:
        start_check(wid)
    return wid


def _hit(guess: str, verdict: str) -> float | None:
    """猜测和结论一致 1 分，「有条件」半分；说不准、没结论不计。"""
    want = {"更好": "XX 更好", "差不多": "差不多", "更差": "XX 更差"}.get(guess)
    if not want or verdict not in ("XX 更好", "差不多", "XX 更差", "有条件"):
        return None
    return 0.5 if verdict == "有条件" else float(want == verdict)


def _latest(checks: list[dict], layer: str) -> dict | None:
    xs = [c for c in checks if c["layer"] == layer]
    if not xs:
        return None
    c = dict(xs[-1])
    if c["status"] == "running" and (time.time() - _ts(c["at"])) > STALE_MIN * 60:
        c.update(status="failed", summary="核验中断了（服务重启？），点重查")
    c["detail"] = _j(c["detail"], {})
    return c


def _ts(at: str) -> float:
    try:
        return dt.datetime.fromisoformat(at).timestamp()
    except ValueError:
        return 0.0


def _out(w: dict, checks: list[dict], it: dict | None = None) -> dict:
    p, f = _latest(checks, "paper"), _latest(checks, "followup")
    final = f["verdict"] if f and f["status"] == "done" and f["verdict"] and f["verdict"] != "还没人做" else \
        (p["verdict"] if p and p["status"] == "done" and p["verdict"] != "没回答" else (f or {}).get("verdict", ""))
    return {**{k: w[k] for k in ("id", "item_id", "judgment_id", "alt", "guess", "confidence", "reason", "created_at")},
            "sid": f"my:{w['judgment_id']}" if w.get("judgment_id") else "",
            "item": {"title": it["title"], "url": it["url"]} if it else None,
            "paper": p, "followup": f, "verdict": final, "hit": _hit(w["guess"], final),
            "running": any(c and c["status"] == "running" for c in (p, f)),
            "history": len(checks)}


def _checks_of(wids: list[int]) -> dict[int, list[dict]]:
    out: dict[int, list[dict]] = {}
    if wids:
        for c in db.rows(f"SELECT * FROM kb_whynot_checks WHERE wid IN ({','.join('?' * len(wids))}) ORDER BY id", wids):
            out.setdefault(c["wid"], []).append(c)
    return out


def of_item(item_id: int) -> list[dict]:
    _init()
    ws = db.rows("SELECT * FROM kb_whynot WHERE item_id=? ORDER BY id DESC", [item_id])
    cs = _checks_of([w["id"] for w in ws])
    return [_out(w, cs.get(w["id"], [])) for w in ws]


def overview(limit: int = 30) -> dict:
    """判断页用：计分 + 最近的「为什么不」。"""
    _init()
    ws = db.rows("SELECT w.*, i.title AS it_title, i.url AS it_url FROM kb_whynot w LEFT JOIN learn_items i ON i.id=w.item_id ORDER BY w.id DESC")
    cs = _checks_of([w["id"] for w in ws])
    rows = [_out(w, cs.get(w["id"], []), {"title": w["it_title"] or "", "url": w["it_url"] or ""}) for w in ws]
    scored = [r["hit"] for r in rows if r["hit"] is not None]
    return {"stats": {"total": len(rows), "papers": len({r["item_id"] for r in rows}),
                      "answered": sum(bool(r["verdict"]) and r["verdict"] not in ("没回答", "还没人做") for r in rows),
                      "scored": len(scored), "hit_rate": round(sum(scored) / len(scored), 2) if scored else None,
                      "untested": sum(r["verdict"] == "还没人做" for r in rows)},
            "items": rows[:limit]}
