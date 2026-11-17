"""论文机构：从 OpenAlex 按 arXiv 号批量取作者机构（S2 的机构字段太稀），存 paper_orgs；页面按机构筛选用。
OpenAlex 单条按 arXiv DOI 查（批量 filter 查不到发表后换了 DOI 的论文）；对刚发的论文有收录延迟：14 天内查不到的不记「已查」，下次再试。
这段空窗期改从 arXiv HTML 版的作者块取单位，交给小模型归一成机构名，src='arxiv'；OpenAlex 一有数据就覆盖。"""
from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import httpx

from .. import db

SCHEMA = """
CREATE TABLE IF NOT EXISTS paper_orgs (
    s2id    TEXT PRIMARY KEY,
    orgs    TEXT DEFAULT '[]',
    checked TEXT,
    src     TEXT DEFAULT 'oa'
);
"""
OA = "https://api.openalex.org/works"
MAX_ORGS = 8
COUNTRY = re.compile(r"\s*\([^()]*\)\s*$")


def init() -> None:
    db.init([SCHEMA])
    if "src" not in {r["name"] for r in db.rows("PRAGMA table_info(paper_orgs)")}:
        db.execute("ALTER TABLE paper_orgs ADD COLUMN src TEXT DEFAULT 'oa'")


def _orgs(work: dict) -> list[str]:
    seen: list[str] = []
    for a in work.get("authorships") or []:
        for i in a.get("institutions") or []:
            n = COUNTRY.sub("", i.get("display_name") or "").strip()
            if n and n not in seen:
                seen.append(n)
    return seen[:MAX_ORGS]


def _one(c: httpx.Client, arxiv: str) -> list[str] | None:
    for wait in (0, 3, 10):
        time.sleep(wait)
        try:
            r = c.get(f"{OA}/doi:10.48550/arxiv.{arxiv}", params={"select": "authorships"})
        except httpx.HTTPError:
            continue
        if r.status_code == 404:
            return []
        if r.status_code == 200:
            return _orgs(r.json())
    return None


def backfill(limit: int = 0, workers: int = 6) -> dict:
    init()
    rows = db.rows("SELECT s2id, arxiv, pub_date FROM paper_items WHERE status='in' AND arxiv!='' AND arxiv IS NOT NULL "
                   "AND s2id NOT IN (SELECT s2id FROM paper_orgs WHERE src='oa') ORDER BY year DESC, cites DESC" + (f" LIMIT {limit}" if limit else ""))
    young = (datetime.now() - timedelta(days=14)).strftime("%Y-%m-%d")
    stat = {"todo": len(rows), "found": 0, "empty": 0, "errors": 0}

    def work(r):
        orgs = _one(c, r["arxiv"])
        if orgs is None:
            stat["errors"] += 1
        elif not orgs and (r["pub_date"] or "") >= young:
            stat["empty"] += 1
        elif not orgs and db.row("SELECT 1 FROM paper_orgs WHERE s2id=? AND src='arxiv' AND orgs!='[]'", [r["s2id"]]):
            stat["empty"] += 1
        else:
            db.execute("INSERT OR REPLACE INTO paper_orgs (s2id, orgs, checked, src) VALUES (?,?,?,'oa')", [r["s2id"], json.dumps(orgs, ensure_ascii=False), db.now()])
            stat["found" if orgs else "empty"] += 1

    with httpx.Client(timeout=30) as c, ThreadPoolExecutor(workers) as ex:
        list(ex.map(work, rows))
    return stat


ARXIV_HTML = "https://arxiv.org/html/"
AUTHORS = re.compile(r'class="ltx_authors".*?(?=class="ltx_abstract"|<h[12][ >])', re.S)
BATCH = 10
NORMALIZE = ("你收到若干篇论文的作者块文本（含姓名、单位、邮箱、地址）。对每篇只提取作者所属机构，去掉院系、城市、国家、邮箱和作者姓名，"
             "用通用英文机构名（如 Tsinghua University、Google DeepMind、Huawei），同一机构只写一次，最多 8 个。没有机构就给空数组。"
             "只输出 JSON 数组，每项 {\"i\": 编号, \"orgs\": [..]}。")


def _author_text(c: httpx.Client, arxiv: str) -> str | None:
    """作者块纯文本；页面还没生成（404）或取不到返回 None，下次再试；页面在但没有作者块返回空串。"""
    try:
        r = c.get(ARXIV_HTML + arxiv, follow_redirects=True)
    except httpx.HTTPError:
        return None
    if r.status_code != 200:
        return None
    m = AUTHORS.search(r.text)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", m.group(0)))[:1500].strip() if m else ""


def arxiv_fill(limit: int = 200) -> dict:
    """OpenAlex 还没收录的新论文（14 天内、paper_orgs 里没有）从 arXiv HTML 作者块补机构。"""
    from . import _paper_label as lab
    init()
    young = (datetime.now() - timedelta(days=14)).strftime("%Y-%m-%d")
    rows = db.rows("SELECT s2id, arxiv FROM paper_items WHERE status='in' AND arxiv!='' AND arxiv IS NOT NULL AND pub_date>=? "
                   "AND s2id NOT IN (SELECT s2id FROM paper_orgs) ORDER BY pub_date DESC LIMIT ?", [young, limit])
    stat = {"todo": len(rows), "found": 0, "empty": 0, "skipped": 0, "cost": 0.0}
    with httpx.Client(timeout=30) as c:
        texts = {r["s2id"]: _author_text(c, r["arxiv"]) for r in rows}
    got = [(r["s2id"], texts[r["s2id"]]) for r in rows if texts[r["s2id"]] is not None]
    stat["skipped"] = len(rows) - len(got)
    for s2id, t in [x for x in got if not x[1]]:
        db.execute("INSERT OR IGNORE INTO paper_orgs (s2id, orgs, checked, src) VALUES (?,'[]',?,'arxiv')", [s2id, db.now()])
        stat["empty"] += 1
    todo = [x for x in got if x[1]]
    for i in range(0, len(todo), BATCH):
        chunk = todo[i:i + BATCH]
        user = "\n".join(json.dumps({"i": n, "text": t}, ensure_ascii=False) for n, (_, t) in enumerate(chunk))
        try:
            out, cost = lab.chat(NORMALIZE, user, json_mode=True)
            res = {x["i"]: x.get("orgs") or [] for x in json.loads(out)}
        except Exception:  # noqa: BLE001
            stat["skipped"] += len(chunk)
            continue
        stat["cost"] += cost
        for n, (s2id, _) in enumerate(chunk):
            orgs = list(dict.fromkeys(str(o).strip() for o in res.get(n, []) if str(o).strip()))[:MAX_ORGS]
            db.execute("INSERT OR IGNORE INTO paper_orgs (s2id, orgs, checked, src) VALUES (?,?,?,'arxiv')", [s2id, json.dumps(orgs, ensure_ascii=False), db.now()])
            stat["found" if orgs else "empty"] += 1
    return stat
