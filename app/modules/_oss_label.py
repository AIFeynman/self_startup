"""开源雷达的打包标注：一次给订阅 Haiku 50 个仓库，按分类体系输出 JSON Lines（设计稿 §4）。

- 走订阅 CLI（settings 里 engines.claude.bin，默认 reclaude）+ model_tiers.light，不按次付费；默认 effort（low 会掉质量）。
- 校验每一行：kind / 领域 / AI 关系必须是分类体系里的 code，标签和一句话不能空；不合格的、漏掉的再单独打包问一次。
- 「内容不变不重复问」：label_src = 描述 + topics 的哈希（同信息推荐 _feed_judge 的输入哈希去重）。
- 重标规则（§2.1）：新仓库；描述 / topics 变了；README 换了且标注超过 90 天；star 翻倍；分类体系版本变了。
"""
from __future__ import annotations

import json
import logging
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from functools import lru_cache
from hashlib import sha1
from pathlib import Path

from .. import db, settings
from ._feed_sources import clean

log = logging.getLogger(__name__)

TAXONOMY_PATH = Path(__file__).with_name("oss_taxonomy.json")
BATCH = 50
PARALLEL = 4
TIMEOUT = 600
README_RELABEL_DAYS = 90

SYSTEM = """你在给 GitHub 仓库做分类，供开发者按功能搜索开源项目（如「我想做 PDF 解析」）。分类体系：
{tax}

对下面每个仓库输出一行 JSON（JSON Lines，不要代码块、不要解释），字段：
{{"i":序号,"k":kind,"d":主领域二级code,"d2":[副领域code，0-2个],"ai":ai关系,"t":[功能标签3-8个，中文为主、专有名词保留英文，写「能用它做什么」，优先用分类体系里 eg 的词],"s":"中文一句话说它能做什么（≤40字）"}}
规则：教程/书/awesome 也按它讲的主题归 domain（如 LLM 教程 → d=llm, k=tutorial）；看不出用途 d=other。readme 是 README 开头的摘录，用来判断用途。
"""


@lru_cache(maxsize=1)
def taxonomy() -> dict:
    return json.loads(TAXONOMY_PATH.read_text())


def codes() -> dict[str, set[str]]:
    t = taxonomy()
    return {"k": {x["code"] for x in t["kinds"]}, "ai": {x["code"] for x in t["ai_relation"]},
            "d": {c["code"] for d in t["domains"] for c in d["children"]}}


def domain_names() -> dict[str, str]:
    """二级 code → 「一级 / 二级」名字。"""
    return {c["code"]: c["name"] for d in taxonomy()["domains"] for c in d["children"]}


def tax_text() -> str:
    t = taxonomy()
    lines = ["形态 kind（单选）：" + "；".join(f"{k['code']}={k['name']}（{k['desc']}）" for k in t["kinds"]),
             "AI 关系 ai（单选）：" + "；".join(f"{a['code']}={a['name']}" + (f"（{a['desc']}）" if a["desc"] else "")
                                           for a in t["ai_relation"]),
             "领域 domain（填二级 code）："]
    for d in t["domains"]:
        lines.append(f"[{d['name']}] " + "；".join(f"{c['code']}={c['name']}（{'/'.join(c['eg'])}）" for c in d["children"]))
    return "\n".join(lines)


def label_src(r: dict) -> str:
    topics = r["topics"] if isinstance(r["topics"], list) else json.loads(r["topics"] or "[]")
    return sha1(json.dumps([r.get("descr") or "", sorted(topics)], ensure_ascii=False).encode()).hexdigest()[:16]


def _row(n: int, r: dict) -> str:
    topics = r["topics"] if isinstance(r["topics"], list) else json.loads(r["topics"] or "[]")
    x = {"i": n, "name": r["name"], "stars": r["stars"], "lang": r.get("lang") or "", "topics": topics[:12],
         "desc": (r.get("descr") or "")[:300]}
    if r.get("readme"):
        x["readme"] = clean(r["readme"], 1500)
    return json.dumps(x, ensure_ascii=False)


def validate(x: dict) -> dict | None:
    """模型输出的一行 → 合格的标签；code 不在分类体系里、标签或一句话为空的返回 None。"""
    cs = codes()
    try:
        k, d, ai = str(x.get("k")), str(x.get("d")), str(x.get("ai"))
        d2 = [str(v) for v in (x.get("d2") or []) if str(v) in cs["d"] and str(v) != d][:2]
        t = [clean(str(v), 30) for v in (x.get("t") or []) if str(v).strip()][:8]
        s = clean(str(x.get("s") or ""), 60)
    except Exception:  # noqa: BLE001
        return None
    if k not in cs["k"] or d not in cs["d"] or ai not in cs["ai"] or not t or not s:
        return None
    return {"k": k, "d": d, "d2": d2, "ai": ai, "t": t, "s": s}


def _cli(prompt: str) -> dict:
    cfg = settings.get("engines.claude", {}) or {}
    model = str((settings.get("model_tiers", {}) or {}).get("light") or "claude-haiku-5-5")
    cmd = [cfg.get("bin", "claude"), "-p", prompt, "--model", model, "--output-format", "json", "--tools", "",
           "--system-prompt", SYSTEM.format(tax=tax_text())]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT)
    try:
        return json.loads(p.stdout)
    except Exception as e:  # noqa: BLE001
        raise RuntimeError((p.stdout + p.stderr)[-300:] or "空输出") from e


def ask(chunk: list[dict], call=None) -> tuple[dict[str, dict], float]:
    """一批仓库 → ({name: 标签}, 花费)。call 可替换（测试用）。"""
    res = (call or _cli)("仓库：\n" + "\n".join(_row(n, r) for n, r in enumerate(chunk)))
    out = {}
    for line in (res.get("result") or "").splitlines():
        line = line.strip().strip(",")
        if not line.startswith("{"):
            continue
        try:
            x = json.loads(line)
            i = int(x["i"])
        except Exception:  # noqa: BLE001
            continue
        if 0 <= i < len(chunk) and (lab := validate(x)):
            out[chunk[i]["name"]] = lab
    return out, float(res.get("total_cost_usd") or 0)


def label_batch(chunk: list[dict], call=None) -> tuple[dict[str, dict], float, list[str]]:
    """问一批；漏掉的 / 不合格的再单独打包问一次。返回 (标签, 花费, 错误)。"""
    errors, cost = [], 0.0
    try:
        got, cost = ask(chunk, call)
    except Exception as e:  # noqa: BLE001
        got = {}
        errors.append(f"{type(e).__name__}: {str(e)[:160]}")
    miss = [r for r in chunk if r["name"] not in got]
    if miss:
        try:
            more, c2 = ask(miss, call)
            got.update(more)
            cost += c2
        except Exception as e:  # noqa: BLE001
            errors.append(f"重问：{type(e).__name__}: {str(e)[:160]}")
    return got, cost, errors


def save(chunk: list[dict], got: dict[str, dict]) -> int:
    ver, now = taxonomy()["version"], db.now()
    for r in chunk:
        lab = got.get(r["name"])
        if not lab:
            continue
        db.execute("INSERT OR REPLACE INTO oss_labels (name,k,d,d2,ai,t,s,tax_ver,label_src,readme_oid,stars_at,labeled_at) "
                   "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                   [r["name"], lab["k"], lab["d"], json.dumps(lab["d2"]), lab["ai"], json.dumps(lab["t"], ensure_ascii=False),
                    lab["s"], ver, label_src(r), r.get("readme_oid") or "", str(r["stars"]), now])
        index(r, lab)
    return len(got)


def index(r: dict, lab: dict) -> None:
    """写检索索引（FTS5 trigram，rowid = oss_repos.id）。"""
    topics = r["topics"] if isinstance(r["topics"], list) else json.loads(r["topics"] or "[]")
    db.execute("DELETE FROM oss_fts WHERE rowid=?", [r["id"]])
    db.execute("INSERT INTO oss_fts(rowid,name,s,t,descr,topics) VALUES (?,?,?,?,?,?)",
               [r["id"], r["name"].replace("/", " "), lab["s"], " | ".join(lab["t"]), r.get("descr") or "", " ".join(topics)])


def todo(limit: int = 0) -> list[dict]:
    """要（重新）标注的仓库，star 高的优先。"""
    ver = taxonomy()["version"]
    old = (datetime.now() - timedelta(days=README_RELABEL_DAYS)).isoformat(timespec="seconds")
    rows = db.rows("SELECT r.*, l.label_src AS l_src, l.tax_ver AS l_ver, l.readme_oid AS l_oid, l.stars_at AS l_stars, "
                   "l.labeled_at AS l_at, l.name AS l_name FROM oss_repos r LEFT JOIN oss_labels l ON l.name=r.name "
                   "WHERE r.status='ok' AND r.stars>=900 ORDER BY r.stars DESC")
    out = []
    for r in rows:
        if r["l_name"] is None or r["l_src"] != label_src(r) or r["l_ver"] != ver \
                or r["stars"] >= 2 * int(r["l_stars"] or 0) \
                or (r["readme_oid"] and r["l_oid"] != r["readme_oid"] and (r["l_at"] or "") < old):
            out.append(r)
            if limit and len(out) >= limit:
                break
    return out


def run(limit: int = 0, batch: int = BATCH, parallel: int = PARALLEL, call=None, on_progress=None) -> dict:
    """标注队列里的仓库：每轮取 batch×parallel×2 个，先补 README（GraphQL），再并行打包问。
    中途停了下次接着跑（已标的 label_src 对得上，不会再进队列）。"""
    from . import _oss_collect as col
    rows = todo(limit)
    stat = {"labeled": 0, "todo": len(rows), "cost": 0.0, "errors": []}
    step = batch * parallel * 2
    with ThreadPoolExecutor(parallel) as ex:
        for start in range(0, len(rows), step):
            group = rows[start:start + step]
            if call is None:   # 真跑时先补 README；测试传了假 call 就不联网
                need = [r["name"] for r in group if r["readme_oid"] is None]
                if need:
                    col.fetch_readmes(need)
                    group = [db.row("SELECT * FROM oss_repos WHERE id=?", [r["id"]]) or r for r in group]
            chunks = [group[i:i + batch] for i in range(0, len(group), batch)]
            for chunk, (got, cost, errs) in zip(chunks, ex.map(lambda c: label_batch(c, call), chunks)):
                stat["labeled"] += save(chunk, got)
                stat["cost"] = round(stat["cost"] + cost, 4)
                stat["errors"] = (stat["errors"] + errs)[-20:]
            if on_progress:
                on_progress(min(start + step, len(rows)), len(rows), stat)
    return stat
