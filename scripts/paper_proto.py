"""论文脉络库原型：后训练 / RAG / MoE 三个主题跑通 采集 → 门槛 → Jev → 标注 → 脉络 → 评测（设计稿 §8 P0）。

用法（数据写到 SELF_STARTUP_DATA 指向的目录，不碰正式库）：
    SELF_STARTUP_DATA=<目录> uv run python -m scripts.paper_proto collect
    ... judge | label | map | eval | all
每一步都能单独重跑，已经做过的会跳过；结果和花费记到 <目录>/paper_proto.json。
"""
from __future__ import annotations

import json
import logging
import random
import sqlite3
import sys
import time
from pathlib import Path

from app import db
from app.modules import _paper_collect as col, _paper_label as lab, _paper_map as pmap

TOPICS = {
    "posttrain": [
        '"reinforcement learning from human feedback" | RLHF | "human feedback" | "human preferences"',
        '"preference optimization" | "preference learning" | "reward model" | "reward modeling"',
        '"instruction tuning" | "instruction-tuned" | "instruction following" | "supervised fine-tuning"',
        '"parameter-efficient fine-tuning" | "low-rank adaptation" | LoRA | "prompt tuning"',
        '("reinforcement learning" + reasoning + "language models") | "verifiable rewards" | GRPO',
        '("knowledge distillation" + "language models") | "constitutional ai" | RLAIF | ("alignment" + "language models")',
    ],
    "rag": [
        '"retrieval-augmented" | "retrieval augmented generation" | "retrieval-enhanced"',
        '"dense retrieval" | "dense passage retrieval" | "neural retrieval" | "late interaction"',
        '"open-domain question answering" | "text embeddings" | "sentence embeddings"',
    ],
    "moe": [
        '"mixture of experts" | "mixture-of-experts" | MoE',
        '"sparse expert" | "sparsely-gated" | "conditional computation" | "expert routing"',
    ],
}

# 主题 → (脉络问法, 综述里公认的里程碑 arXiv id)。评测：这些论文在 候选 / 入库 / 召回 / 脉络输出 各阶段的命中率。
GOLD = {
    "posttrain": ("后训练", ["1706.03741", "2009.01325", "2203.02155", "1707.06347", "2204.05862", "2212.08073",
                           "2109.01652", "2212.10560", "2305.18290", "2305.11206", "2402.03300", "2501.12948",
                           "2405.14734", "2402.01306", "2411.15124", "2106.09685"]),
    "rag": ("检索增强生成 RAG", ["2005.11401", "2002.08909", "2004.04906", "2007.01282", "2112.04426", "2208.03299",
                              "2310.11511", "2212.10496", "2004.12832", "2312.10997", "2404.16130", "2307.03172",
                              "2112.09118"]),
    "moe": ("混合专家 MoE", ["1701.06538", "2006.16668", "2101.03961", "2112.06905", "2202.08906", "2401.04088",
                           "2401.06066", "2202.09368", "2405.04434", "2211.15841", "2103.16716", "2308.00951"]),
}
CONSIST_N = 400

OUT = db.DATA_DIR / "paper_proto.json"
MAIN_DB = Path(__file__).resolve().parents[1].parent / "self_startup" / "data" / "app.db"


def _load() -> dict:
    return json.loads(OUT.read_text()) if OUT.exists() else {}


def _save(k: str, v) -> None:
    d = _load()
    d[k] = v
    OUT.write_text(json.dumps(d, ensure_ascii=False, indent=1))


def _copy_feed() -> int:
    """把正式库的信息推荐论文（只读）抄进原型库，给近期论文当热度信号。"""
    if db.row("SELECT name FROM sqlite_master WHERE name='feed_items'"):
        return 0
    src = sqlite3.connect(f"file:{MAIN_DB}?mode=ro", uri=True)
    ids = [r[0] for r in src.execute("SELECT id FROM feed_items WHERE id LIKE 'arxiv:%'")]
    db.execute("CREATE TABLE feed_items (id TEXT PRIMARY KEY)")
    for i in ids:
        db.execute("INSERT OR IGNORE INTO feed_items(id) VALUES (?)", [i])
    return len(ids)


def collect() -> None:
    t0 = time.time()
    feed = _copy_feed()
    c = col.client()
    done = _load().get("collect_done", [])
    for name, qs in TOPICS.items():
        if name in done:
            continue
        n = col.collect_topic(name, qs, c)
        done.append(name)
        _save("collect_done", done)
        logging.info("%s：%d 条候选，S2 %s", name, n, col.usage)
    col.mark_hot()
    logging.info("门槛：%s", col.admit_all())
    col.fetch_details(c, on_page=lambda i, n: logging.info("详情 %d/%d", i, n))
    got = col.pull_classics(c)
    logging.info("经典回拉 %d 篇", len(got))
    col.fetch_details(c)
    _save("collect", {"feed_papers": feed, "seconds": round(time.time() - t0), **col.stats()})
    logging.info("采集完成 %s", col.stats())


def judge() -> None:
    t0 = time.time()
    st = lab.judge_recent()
    st["admit"] = col.admit_all()
    st["seconds"] = round(time.time() - t0)
    _save("judge", st)
    logging.info("Jev %s", st)


def label() -> None:
    t0 = time.time()
    st = lab.run()
    st["seconds"] = round(time.time() - t0)
    st.pop("labels")
    _save("label", st)
    logging.info("标注 %s", st)


def build_maps() -> None:
    out = {}
    for name, (topic, _) in GOLD.items():
        t0 = time.time()
        res = pmap.build(topic, use_cache=False)
        md = pmap.render(res)
        (db.DATA_DIR / f"map_{name}.md").write_text(md)
        out[name] = {"cost": res["cost"], "seconds": round(time.time() - t0), "recalled": res["recalled"],
                     "chosen": len(res["chosen"]), "lines": [ln["name"] for ln in res["lines"]]}
        logging.info("脉络 %s %s", name, out[name])
    _save("map", out)


def _consistency() -> dict:
    """抽 CONSIST_N 篇已标注的，打乱批次重标一遍（不落库），比类型 / 主方向。"""
    labs = {r["s2id"]: r for r in db.rows("SELECT s2id, k, d FROM paper_labels")}
    corpus = lab._corpus()
    rows = [r for r in db.rows("SELECT * FROM paper_items WHERE status='in'") if r["s2id"] in labs]
    random.Random(7).shuffle(rows)
    items = [(r, lab.refs_of(r, corpus)) for r in rows[:CONSIST_N]]
    st = lab.run(items=items, persist=False)
    got = st["labels"]
    same = lambda f: sum(got[s][f] == labs[s][f] for s in got) / max(1, len(got))  # noqa: E731
    top = lambda d: next((x["code"] for x in lab.taxonomy()["domains"]  # noqa: E731
                          if d in {c["code"] for c in x["children"]}), d)
    d1 = sum(top(got[s]["d"]) == top(labs[s]["d"]) for s in got) / max(1, len(got))
    return {"n": len(got), "kind": round(same("k"), 3), "domain2": round(same("d"), 3),
            "domain1": round(d1, 3), "cost": st["cost"]}


def _milestones() -> dict:
    by_ax = {r["arxiv"]: r for r in db.rows("SELECT id, s2id, arxiv, status FROM paper_items WHERE arxiv!=''")}
    out = {}
    for name, (topic, gold) in GOLD.items():
        res = pmap.build(topic)
        rel = pmap.recall(res["intent"])
        shown = {n["s2id"] for ln in res["lines"] for n in ln["nodes"]} | set(res["foundations"]) | set(res["surveys"])
        stage = {"cand": [], "in": [], "recall": [], "chosen": [], "shown": []}
        for a in gold:
            r = by_ax.get(a)
            if not r:
                continue
            stage["cand"].append(a)
            if r["status"] == "in":
                stage["in"].append(a)
            if r["id"] in rel or r["s2id"] in res["ancestors"]:
                stage["recall"].append(a)
            if r["s2id"] in res["chosen"]:
                stage["chosen"].append(a)
            if r["s2id"] in shown:
                stage["shown"].append(a)
        out[name] = {k: f"{len(v)}/{len(gold)}" for k, v in stage.items()} | {
            "shown_rate": round(len(stage["shown"]) / len(gold), 3),
            "missing": [a for a in gold if a not in stage["shown"]]}
    return out


def evaluate() -> None:
    res = {"milestones": _milestones(), "consistency": _consistency()}
    d = _load()
    res["cost_total"] = round(sum((d.get(k) or {}).get("cost", 0) for k in ("label",)) +
                              sum(v["cost"] for v in (d.get("map") or {}).values()) + res["consistency"]["cost"], 4)
    _save("eval", res)
    logging.info("评测 %s", json.dumps(res, ensure_ascii=False))


STEPS = {"collect": collect, "judge": judge, "label": label, "map": build_maps, "eval": evaluate}


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    db.init([col.SCHEMA])
    for step in (list(STEPS) if sys.argv[1] == "all" else sys.argv[1:]):
        STEPS[step]()


if __name__ == "__main__":
    main()
