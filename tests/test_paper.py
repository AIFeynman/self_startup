"""论文脉络库：入库门槛、标注校验 / 重问 / 索引、脉络召回 + 子图 + 成线校验。不联网。"""
import json
from datetime import datetime

import pytest

from app import db
from app.modules import _paper_collect as col, _paper_label as lab, _paper_map as pmap

TODAY = datetime(2026, 11, 2)


@pytest.fixture(autouse=True)
def _clean(client):
    db.init([col.SCHEMA])
    for t in ("paper_items", "paper_labels", "paper_fts", "paper_maps"):
        db.execute(f"DELETE FROM {t}")


def paper(s2id, title, year, cites, refs=(), arxiv="x", abstract="", pub=None):
    db.execute("INSERT INTO paper_items(s2id,arxiv,title,abstract,year,pub_date,cites,infl,refs,status,src,detail_at,first_seen,updated) "
               "VALUES (?,?,?,?,?,?,?,?,?,'in','t',?,?,?)",
               [s2id, f"{arxiv}{s2id}", title, abstract or title, year, pub or f"{year}-06-01", cites, 0,
                json.dumps(list(refs)), db.now(), db.now(), db.now()])
    return db.row("SELECT * FROM paper_items WHERE s2id=?", [s2id])


@pytest.mark.parametrize("pub,cites,extra,want", [
    ("2026-09-01", 3, {}, ("out", "recent")),               # 近期无信号
    ("2026-09-01", 20, {}, ("in", "recent")),               # 近期被引够
    ("2026-09-01", 0, {"hot": 1}, ("in", "recent")),        # 信息推荐热门
    ("2026-09-01", 20, {"junk": 0.8}, ("out", "recent")),   # Jev 判水文
    ("2025-11-01", 59, {}, ("out", "young")),
    ("2025-11-01", 60, {}, ("in", "young")),
    ("2023-01-01", 249, {}, ("out", "mid")),
    ("2023-01-01", 210, {"infl": 35}, ("in", "mid")),      # 接近门槛且高影响力引用占比高
    ("2023-01-01", 210, {"infl": 20}, ("out", "mid")),
    ("2018-01-01", 999, {}, ("out", "old")),
    ("2018-01-01", 1000, {}, ("in", "old")),
])
def test_decide_tightens_with_age(pub, cites, extra, want):
    st, tier, why = col.decide({"arxiv": "1", "pub_date": pub, "cites": cites, "infl": 0, **extra}, TODAY)
    assert (st, tier) == want and why


def test_decide_requires_arxiv():
    assert col.decide({"arxiv": "", "pub_date": "2018-01-01", "cites": 99999}, TODAY)[0] == "out"


def test_pull_classics_counts_only_non_classic_citers(monkeypatch):
    for i in range(8):
        paper(f"N{i}", f"paper {i}", 2023, 500, refs=["C1"])
    paper("OLDC", "second generation classic", 2010, 900, arxiv="")       # 上一轮被经典自己的参考文献拉进来的
    db.execute("UPDATE paper_items SET tier='classic', refs=? WHERE s2id='C1'", ['[]'])
    db.execute("UPDATE paper_items SET tier='classic' WHERE s2id='OLDC'")
    monkeypatch.setattr(col, "batch", lambda ids, c: [{"paperId": s, "title": s, "year": 2014, "citationCount": 5000,
                                                       "externalIds": {}, "references": [{"paperId": "OLDC"}]} for s in ids])
    assert col.pull_classics(None) == ["C1"]
    assert db.row("SELECT status FROM paper_items WHERE s2id='OLDC'")["status"] == "out"
    assert col.pull_classics(None) == []                     # 再跑一次不会滚雪球（C1 自己引 OLDC 不算）


def test_validate_maps_refs_and_rejects_bad_codes():
    refs = [{"s2id": "S_A", "title": "A", "year": 2020}, {"s2id": "S_B", "title": "B", "year": 2021}]
    x = {"k": "method", "d": "pref_opt", "d2": ["reward_model", "nope", "pref_opt"], "s": "直接偏好优化",
         "problem": ["RLHF 不稳定"], "method": ["DPO"], "builds_on": ["r1", "r9", "x"]}
    got = lab.validate(x, refs)
    assert got["builds_on"] == ["S_B"] and got["d2"] == ["reward_model"]
    assert lab.validate({**x, "d": "bogus"}, refs) is None
    assert lab.validate({**x, "d": "bogus"}, refs, lenient=True)["d"] == "reward_model"


def fake_label(drop_first=()):
    seen = set()

    def call(system, user, *a, **kw):
        out = []
        for line in user.splitlines()[1:]:
            x = json.loads(line)
            if x["title"] in drop_first and x["title"] not in seen:
                seen.add(x["title"])
                continue
            dom = "moe" if "expert" in x["title"].lower() else "pref_opt"
            out.append(json.dumps({"i": x["i"], "k": "method", "d": dom, "d2": [], "s": "一句话 " + x["title"],
                                   "problem": ["p"], "method": [x["title"]],
                                   "builds_on": [r["r"] for r in x["refs"]][:1]}))
        return "\n".join(out), 0.001
    return call


def test_label_run_retries_missing_and_indexes():
    a = paper("A", "Proximal policy optimization", 2017, 30000)
    paper("B", "Direct preference optimization", 2023, 9000, refs=["A"])
    st = lab.run(call=fake_label(drop_first={"Direct preference optimization"}))
    assert st["labeled"] == 2 and st["errors"] == []
    b = db.row("SELECT * FROM paper_labels WHERE s2id='B'")
    assert json.loads(b["builds_on"]) == ["A"]
    assert db.rows("SELECT rowid FROM paper_fts WHERE paper_fts MATCH ?", ['"preference"'])
    assert lab.todo() == []                 # 内容没变不重标
    db.execute("UPDATE paper_items SET abstract='changed' WHERE id=?", [a["id"]])
    assert [r["s2id"] for r, _ in lab.todo()] == ["A"]


def test_run_without_persist_returns_labels_only():
    paper("A", "Proximal policy optimization", 2017, 30000)
    st = lab.run(call=fake_label(), persist=False)
    assert set(st["labels"]) == {"A"} and not db.rows("SELECT * FROM paper_labels")


def test_pagerank_favors_cited():
    pr = pmap._pagerank(["a", "b", "c"], [("b", "a"), ("c", "a"), ("c", "b")])
    assert pr["a"] > pr["b"] > pr["c"]


def test_build_map_recalls_pulls_ancestor_and_validates_ids(monkeypatch):
    paper("PPO", "Proximal policy optimization", 2017, 30000)          # 前置基础：不是主题词命中，但被大量引用
    paper("RLHF", "Learning from human preferences", 2017, 3000, refs=["PPO"])
    paper("IGPT", "Training with human preferences feedback", 2022, 20000, refs=["RLHF", "PPO"])
    paper("DPO", "Direct preference optimization", 2023, 9000, refs=["IGPT", "RLHF", "PPO"])
    paper("MOE", "Sparsely gated mixture of experts", 2017, 5000)
    paper("OUT", "Human preferences, revisited", 2025, 5)                        # 标注后没过门槛，全文索引里还在
    lab.run(call=fake_label())
    db.execute("UPDATE paper_items SET status='out' WHERE s2id='OUT'")
    db.execute("UPDATE paper_labels SET d='rl' WHERE s2id='PPO'")
    calls = []

    def chat(system, user, *a, **kw):
        if "检索意图" in system:                                                    # 改写（跑 REWRITE_N 次）
            return json.dumps({"must": ["human preferences", "preference optimization"], "should": [], "domains": ["pref_opt"]}), 0.001
        calls.append(user)
        ids = {json.loads(ln)["t"]: json.loads(ln)["id"] for ln in user.split("论文：\n")[1].splitlines() if ln.startswith('{"id"')}
        return json.dumps({"overview": "o", "foundations": [ids["Proximal policy optimization"]], "surveys": [],
                           "lines": [{"name": "RLHF", "summary": "s", "nodes": [
                               {"id": ids["Learning from human preferences"], "role": "起点", "note": "n"},
                               {"id": ids["Direct preference optimization"], "role": "改进", "note": "n"},
                               {"id": "p99", "role": "编造", "note": "x"}]}],
                           "open": ["q"]}), 0.002
    monkeypatch.setattr(lab, "chat", chat)
    res = pmap.build("后训练")
    assert "MOE" not in res["chosen"] and "PPO" in res["chosen"]
    # 编造的 p99 被丢掉；补问后仍漏的 key 论文 IGPT 按引用边挂到这条线、按年份插入
    assert [(n["s2id"], n["role"]) for n in res["lines"][0]["nodes"]] == [("RLHF", "起点"), ("IGPT", "相关"), ("DPO", "改进")]
    assert res["foundations"] == ["PPO"]
    assert "漏了这些 key 论文" in calls[1] and res["cost"] == 0.006                 # 高分的 IGPT 没进线 → 补问一次
    assert "arxiv.org/abs/xDPO" in pmap.render(res)
    assert pmap.build("后训练 ") == res and len(calls) == 2                       # 命中缓存


def test_kb_papers_endpoints(client):
    paper("A", "Proximal policy optimization", 2017, 30000)
    paper("B", "Direct preference optimization", 2023, 9000)
    lab.run(call=fake_label())
    ov = client.get("/api/kb/papers").json()
    assert ov["total"] == 2 and ov["labeled"] == 2 and ov["maps"] == []
    assert client.get("/api/kb/papers/map", params={"topic": "后训练"}).status_code == 404
    assert client.post("/api/kb/papers/map", json={"topic": " "}).status_code == 400
    res = {"topic": "后训练", "overview": "o", "lines": [{"name": "L", "summary": "s", "nodes": [{"s2id": "B", "role": "改进", "note": "n"},
                                                                {"s2id": "A", "role": "起点", "note": "n"}]}],
           "foundations": [], "surveys": [], "open": [], "recalled": 1, "core": 1, "chosen": ["A", "B"], "key": [], "ancestors": [],
           "cost": 0.004, "created": "2026-11-03T10:00:00"}
    db.execute("INSERT INTO paper_maps(topic, result, cost, created) VALUES (?,?,?,?)",
               ["后训练", json.dumps(res, ensure_ascii=False), 0.004, res["created"]])
    got = client.get("/api/kb/papers/map", params={"topic": "后训练"}).json()
    assert [n["s2id"] for n in got["lines"][0]["nodes"]] == ["A", "B"]        # 按年份排
    assert got["chosen"] == 2 and got["papers"]["A"]["year"] == 2017 and got["papers"]["A"]["url"].endswith("xA")
    assert client.get("/api/kb/papers").json()["maps"][0]["lines"] == 1
