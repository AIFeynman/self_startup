"""论文机构：从 OpenAlex 按 arXiv 号批量取作者机构（S2 的机构字段太稀），存 paper_orgs；页面按机构筛选用。
OpenAlex 单条按 arXiv DOI 查（批量 filter 查不到发表后换了 DOI 的论文）；对刚发的论文有收录延迟：14 天内查不到的不记「已查」，下次再试。"""
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
    checked TEXT
);
"""
OA = "https://api.openalex.org/works"
MAX_ORGS = 8
COUNTRY = re.compile(r"\s*\([^()]*\)\s*$")


def init() -> None:
    db.init([SCHEMA])


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
                   "AND s2id NOT IN (SELECT s2id FROM paper_orgs) ORDER BY cites DESC" + (f" LIMIT {limit}" if limit else ""))
    young = (datetime.now() - timedelta(days=14)).strftime("%Y-%m-%d")
    stat = {"todo": len(rows), "found": 0, "empty": 0, "errors": 0}

    def work(r):
        orgs = _one(c, r["arxiv"])
        if orgs is None:
            stat["errors"] += 1
        elif not orgs and (r["pub_date"] or "") >= young:
            stat["empty"] += 1
        else:
            db.execute("INSERT OR REPLACE INTO paper_orgs (s2id, orgs, checked) VALUES (?,?,?)", [r["s2id"], json.dumps(orgs, ensure_ascii=False), db.now()])
            stat["found" if orgs else "empty"] += 1

    with httpx.Client(timeout=30) as c, ThreadPoolExecutor(workers) as ex:
        list(ex.map(work, rows))
    return stat
