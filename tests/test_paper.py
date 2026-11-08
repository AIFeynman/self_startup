"""论文脉络库：入库门槛、标注校验 / 重问 / 索引、脉络召回 + 子图 + 成线校验。不联网。"""
import json
import threading
import time
from datetime import datetime, timedelta

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


def test_frontier_slots_go_to_last_12_months_and_must_appear(monkeypatch):
    monkeypatch.setattr(pmap, "NODES", 3)
    monkeypatch.setattr(pmap, "FRONTIER", 1)
    ago = lambda m: (datetime.now() - timedelta(days=30.44 * m)).date().isoformat()  # noqa: E731
    for i in range(3):
        paper(f"OLD{i}", f"Preference optimization classic {i}", 2022, 20000)
    paper("LASTYEAR", "Preference optimization last year", 2025, 900, pub=ago(14))
    paper("NEW", "Preference optimization this year", 2026, 8, pub=ago(2))
    lab.run(call=fake_label())
    g = pmap.subgraph(pmap.recall({"must": ["preference optimization"], "should": [], "domains": ["pref_opt"]}),
                      {"must": ["preference optimization"], "should": [], "domains": ["pref_opt"]})
    assert "NEW" in g["chosen"] and "LASTYEAR" not in g["chosen"]
    assert "NEW" in g["key"] and g["frontier"] == ["NEW"]
    text, back = pmap._node_text(g)
    assert any(json.loads(ln).get("new") for ln in text.splitlines() if back[json.loads(ln)["id"]] == "NEW")


def test_recall_skips_domains_the_topic_barely_touches():
    for i in range(25):                                                          # 大方向：25 篇里只有 1 篇讲主题
        paper(f"A{i}", "Spiking neural network training" if i == 0 else f"Generic architecture {i}", 2020, 5000)
    paper("M", "Mixture of expert routing", 2021, 3000)                          # 主题方向：关键词全命中
    lab.run(call=fake_label())
    db.execute("UPDATE paper_labels SET d='arch' WHERE s2id LIKE 'A%'")
    ids = {r["s2id"]: r["id"] for r in db.rows("SELECT id, s2id FROM paper_items")}
    snn = pmap.recall({"must": ["spiking neural network"], "should": [], "domains": ["arch"]})
    assert set(snn) == {ids["A0"]}                                               # 命中 1/25 < DOM_SHARE：方向分不够单独进
    moe = pmap.recall({"must": ["mixture of expert"], "should": [], "domains": ["moe"]})
    assert set(moe) == {ids["M"]}
    assert pmap._fts_queries("GRPO (group relative policy optimization)") == ['"GRPO"', '"group relative policy optimization"']
    assert set(pmap.recall({"must": ["SNN (spiking neural network)"], "should": [], "domains": []})) == {ids["A0"]}
    paper("T", "A transformer that supports reinforcement learning", 2021, 4000)    # 缩写只是子串，不算命中
    lab.run(call=fake_label())
    assert pmap._fts("ORM") == pmap._fts("PPO") == pmap._fts("REINFORCE") == set()
    assert pmap._fts("transformer") == {db.row("SELECT id FROM paper_items WHERE s2id='T'")["id"]}
    wide = pmap.recall({"must": ["nothing matches"], "should": [], "domains": ["arch"]})
    assert len(wide) == 25                                                       # 关键词全没命中时仍按方向召回


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
    assert got["thin"] is True and got["chosen"] == 2 and got["papers"]["A"]["year"] == 2017 and got["papers"]["A"]["url"].endswith("xA")
    assert client.get("/api/kb/papers").json()["maps"][0]["lines"] == 1


def _wait_map(client, topic):
    for _ in range(100):
        got = client.get("/api/kb/papers/map", params={"topic": topic}).json()
        if not got.get("running"):
            return got
        time.sleep(0.05)
    raise AssertionError("脉络一直没生成完")


def test_kb_papers_map_builds_in_background_with_steps(client, monkeypatch):
    paper("A", "Proximal policy optimization", 2017, 30000)
    paper("B", "Direct preference optimization", 2023, 9000, refs=["A"])
    lab.run(call=fake_label())
    gate = threading.Event()

    def chat(system, user, *a, **kw):
        if "检索意图" in system:
            return json.dumps({"must": ["optimization"], "should": [], "domains": ["pref_opt"]}), 0.001
        gate.wait(5)
        ids = [json.loads(ln)["id"] for ln in user.split("论文：\n")[1].splitlines()]
        return json.dumps({"overview": "o", "lines": [{"name": "L", "summary": "s", "nodes": [{"id": i, "role": "改进", "note": "n"} for i in ids]}],
                           "foundations": [], "surveys": [], "open": []}), 0.002
    monkeypatch.setattr(lab, "chat", chat)
    r = client.post("/api/kb/papers/map", json={"topic": "后训练"}).json()
    assert r["running"] is True
    for _ in range(100):
        r = client.get("/api/kb/papers/map", params={"topic": "后训练"}).json()
        if "模型分线" in r.get("step", ""):
            break
        time.sleep(0.05)
    assert r["running"] is True and "模型分线" in r["step"]
    gate.set()
    got = _wait_map(client, "后训练")
    assert [n["s2id"] for n in got["lines"][0]["nodes"]] == ["A", "B"]
    assert client.post("/api/kb/papers/map", json={"topic": "后训练"}).json()["lines"]       # 有缓存直接返回

    monkeypatch.setattr(lab, "chat", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("Claude 挂了")))
    assert client.post("/api/kb/papers/map", json={"topic": "后训练", "force": True}).json()["running"] is True
    assert "Claude 挂了" in _wait_map(client, "后训练")["error"]
    assert client.get("/api/kb/papers/map", params={"topic": "后训练"}).json()["lines"]      # 失败只报一次，之后回到旧脉络


def test_kb_papers_search_ranks_by_citations_and_marks_deep_reads(client):
    paper("A", "Linear attention is all you need", 2020, 900)
    paper("B", "Gated linear attention transformers", 2024, 300)
    paper("C", "Proximal policy optimization", 2017, 30000)
    lab.run(call=fake_label())
    db.execute("DELETE FROM learn_items")
    db.insert("learn_items", {"kind": "paper", "url": "https://arxiv.org/abs/xB", "status": "done",
                              "title": "GLA", "created_at": db.now(), "updated_at": db.now()})
    got = client.get("/api/kb/papers/search", params={"q": "linear attention"}).json()
    assert [r["title"] for r in got] == ["Linear attention is all you need", "Gated linear attention transformers"]
    assert got[0]["url"] == "https://arxiv.org/abs/xA" and got[0]["year"] == 2020 and "read" not in got[0]
    assert got[1]["read"]["status"] == "done"
    assert client.get("/api/kb/papers/search", params={"q": " "}).json() == []


def test_kb_papers_search_and_lineage_give_summary_and_who_builds_on_whom(client):
    paper("A", "Linear attention is all you need", 2020, 900, abstract="We make attention linear. " * 30)
    paper("B", "Gated linear attention transformers", 2024, 300, refs=["A", "Z"])
    paper("C", "Delta rule linear attention", 2025, 50, refs=["B", "A"])
    db.execute("UPDATE paper_items SET tldr='Adds data-dependent gates to linear attention.', venue='ICML' WHERE s2id='B'")
    lab.run(call=fake_label())
    got = {r["s2id"]: r for r in client.get("/api/kb/papers/search", params={"q": "linear attention"}).json()}
    assert got["B"]["tldr"] == "Adds data-dependent gates to linear attention." and got["B"]["venue"] == "ICML"
    assert got["B"]["pub_date"] == "2024-06-01" and got["A"]["tldr"].startswith("We make attention linear.") and len(got["A"]["tldr"]) <= 301
    lin = client.get("/api/kb/papers/lineage", params={"s2id": "B"}).json()
    assert lin["paper"]["title"] == "Gated linear attention transformers"
    assert [r["s2id"] for r in lin["builds_on"]] == ["A"] and [r["s2id"] for r in lin["followed_by"]] == ["C"]
    assert lin["followed_by"][0]["url"] == "https://arxiv.org/abs/xC"
    assert client.get("/api/kb/papers/lineage", params={"s2id": "nope"}).status_code == 404


def test_kb_papers_read_reuses_and_creates(client, monkeypatch):
    from app import jobs
    from app.modules import kb as kbmod
    subs = []
    monkeypatch.setattr(jobs, "submit", lambda module, prompt, **kw: subs.append(kw.get("ref")) or db.insert(
        "jobs", {"module": module, "ref": kw.get("ref", ""), "engine": "fake", "prompt": prompt, "status": "queued", "created_at": db.now()}))
    db.execute("DELETE FROM learn_items")
    paper("A", "Proximal policy optimization", 2017, 30000, arxiv="1707.0")    # arxiv = 1707.0A 不是合法号也照样拼链接
    paper("B", "Direct preference optimization", 2023, 9000, arxiv="2305.1829")
    paper("C", "No arxiv", 2020, 10, arxiv="")
    db.execute("UPDATE paper_items SET arxiv='' WHERE s2id='C'")
    old = db.insert("learn_items", {"kind": "paper", "url": "https://arxiv.org/pdf/2305.1829Bv2", "status": "done",
                                    "title": "DPO", "created_at": db.now(), "updated_at": db.now()})
    dry = client.post("/api/kb/papers/read", json={"s2ids": ["A", "B", "C"], "dry_run": True}).json()
    assert [x["id"] for x in dry["reuse"]] == [old] and dry["new"] == ["A"] and dry["skip"] == ["C"] and not subs
    got = client.post("/api/kb/papers/read", json={"s2ids": ["A", "B"]}).json()
    assert len(subs) == 1 and got["reuse"][0]["id"] == old
    it = db.row("SELECT * FROM learn_items WHERE id=?", [got["new"][0]["id"]])
    assert it["url"] == "https://arxiv.org/abs/1707.0A" and it["title"] == "Proximal policy optimization" and it["kind"] == "paper"
    assert client.post("/api/kb/papers/read", json={"s2ids": ["A"]}).json()["reuse"][0]["id"] == it["id"] and len(subs) == 1
    reads = pmap.reads(["A", "B", "C"])
    assert set(reads) == {"A", "B"} and reads["B"]["status"] == "done"
    monkeypatch.setattr(kbmod, "PAPER_READ_MAX", 0)
    db.execute("DELETE FROM learn_items WHERE id=?", [it["id"]])
    assert client.post("/api/kb/papers/read", json={"s2ids": ["A"]}).status_code == 400


def test_decide_halves_threshold_for_industry_papers():
    base = {"arxiv": "1", "pub_date": "2023-06-01", "cites": 150, "infl": 0, "title": "Generative retrieval for recsys"}
    assert col.decide(base, TODAY)[0] == "out"
    ind = base | {"abstract": "Deployed at Kuaishou, online A/B tests show +1.2% watch time."}
    st, _, why = col.decide(ind, TODAY)
    assert st == "in" and "工业界" in why
    assert col.decide(base | {"abstract": "We thank Google for compute."}, TODAY)[0] == "out"


# ---------- 论文库补充（_paper_add） ----------

from app.modules import _paper_add as padd  # noqa: E402


def detail(s2id, title, year, cites, arxiv="", refs=(), abstract="", pub=None):
    return {"paperId": s2id, "title": title, "year": year, "publicationDate": pub or f"{year}-06-01", "citationCount": cites,
            "influentialCitationCount": 0, "venue": "", "externalIds": {"ArXiv": arxiv} if arxiv else {},
            "abstract": abstract or title, "tldr": None, "authors": [], "references": [{"paperId": r} for r in refs]}


@pytest.fixture
def labeled(monkeypatch):
    run = lab.run
    monkeypatch.setattr(lab, "run", lambda limit=0, items=None, persist=True, call=None: run(limit, items, persist, fake_label()))


def test_admit_all_keeps_manual_and_classic():
    paper("M", "user picked", 2025, 1, pub="2025-06-01")
    db.execute("UPDATE paper_items SET tier='manual' WHERE s2id='M'")
    col.admit_all(TODAY)
    assert db.row("SELECT status FROM paper_items WHERE s2id='M'")["status"] == "in"


def test_feed_arxiv_ids_reads_hf_and_alphaxiv(client):
    db.execute("DELETE FROM feed_items")
    for i in ("hf:2611.03126", "arxiv:2510.00001v2", "hn:123", "hf:not-an-id"):
        db.execute("INSERT INTO feed_items(id,source,type,title,url,fetched_at) VALUES (?,?,?,?,?,?)",
                   [i, i.split(":")[0], "paper", i, "u", db.now()])
    assert col.feed_arxiv_ids() == {"2611.03126", "2510.00001"}


def test_add_paper_by_link_or_title_bypasses_threshold(client, monkeypatch, labeled):
    paper("A", "Generative retrieval for recommendation", 2023, 900)
    calls = []

    def req(method, path, c, **kw):
        calls.append(path)
        if path == "/paper/search/match":
            if "nothing" in kw["params"]["query"]:
                raise RuntimeError("S2 /paper/search/match 404: no match")
            return {"data": [{"paperId": "ONE", "title": "OneRec"}]}
        assert path in ("/paper/ARXIV:2506.13695", "/paper/ONE")
        return detail("ONE", "OneRec technical report", 2025, 34, arxiv="2506.13695", refs=["A", "Z"], pub="2025-06-16")

    monkeypatch.setattr(col, "_req", req)
    r = client.post("/api/kb/papers/add", json={"text": "https://arxiv.org/abs/2506.13695v2"}).json()
    assert calls == ["/paper/ARXIV:2506.13695"] and r["already"] is False
    row = db.row("SELECT * FROM paper_items WHERE s2id='ONE'")
    assert (row["status"], row["tier"], row["src"]) == ("in", "manual", "user")
    assert r["paper"]["s"] and json.loads(db.row("SELECT builds_on FROM paper_labels WHERE s2id='ONE'")["builds_on"]) == ["A"]
    assert ("ONE", "A") in col.in_corpus_edges()
    col.admit_all(TODAY)                                         # 被引 34 不够门槛，但用户补的不会被判出去
    assert db.row("SELECT status FROM paper_items WHERE s2id='ONE'")["status"] == "in"
    assert client.post("/api/kb/papers/add", json={"text": "OneRec Technical Report"}).json()["already"] is True
    assert client.post("/api/kb/papers/add", json={"text": "nothing like this"}).status_code == 404


def test_topic_preview_then_run(client, monkeypatch, labeled):
    paper("HAVE", "already in", 2023, 900)
    monkeypatch.setattr(pmap, "rewrite", lambda t: ({"must": ["generative recommendation", 'semantic "ID"', "GR", "TIGER"], "should": [],
                                                     "domains": ["rec_gen"]}, 0.001))
    hits = [detail("BIG", "Big rec paper", 2022, 900, arxiv="2201.1"),
            detail("LOW", "Low cited", 2022, 10, arxiv="2201.2"),
            detail("IND", "Kuaishou rec", 2022, 150, arxiv="2201.3"),
            detail("HAVE", "already in", 2023, 900, arxiv="xHAVE")]
    queries = []
    monkeypatch.setattr(col, "search_bulk", lambda q, c, pages=1, year="", min_cites=0: queries.append(q) or [
        {k: v for k, v in h.items() if k not in ("abstract", "references", "tldr", "authors")} for h in hits])
    a = client.post("/api/kb/papers/topic/preview", json={"topic": "生成式推荐"}).json()
    assert queries[0] == '"generative recommendation" | "semantic  ID"'           # 单独的缩写不进检索式
    assert (a["n_new"], a["n_maybe"], a["have"]) == (1, 1, 1) and a["new"][0]["s2id"] == "BIG"
    assert not db.row("SELECT 1 FROM paper_items WHERE s2id='BIG'")             # 预览不写库

    full = {h["paperId"]: h for h in hits} | {"IND": detail("IND", "Kuaishou rec", 2022, 150, arxiv="2201.3",
                                                         abstract="Deployed at Kuaishou, online A/B test", refs=["HAVE"])}
    monkeypatch.setattr(col, "batch", lambda ids, c, fields=col.DETAIL_FIELDS: [full[i] for i in ids])
    monkeypatch.setattr(lab, "judge_recent", lambda: {})
    monkeypatch.setattr(pmap, "build", lambda t, use_cache=True: {"recalled": 7, "cost": 0.002})
    assert client.post(f"/api/kb/papers/topic/{a['id']}/start").status_code == 200
    for _ in range(100):
        got = client.get(f"/api/kb/papers/topic/{a['id']}").json()
        if got["status"] in ("done", "failed"):
            break
        import time; time.sleep(0.05)  # noqa: E702
    assert got["status"] == "done", got["step"]
    assert got["result"]["admitted"] == 2 and got["result"]["labeled"] == 2 and got["result"]["map"] is True
    assert db.row("SELECT why FROM paper_items WHERE s2id='IND'")["why"].startswith("mid：工业界论文")
    assert client.get("/api/kb/papers/adds").json()[0]["id"] == a["id"]


def test_ingest_feed_marks_hot_and_labels(client, monkeypatch, labeled):
    paper("A", "base paper", 2023, 900)
    db.execute("DELETE FROM feed_items")
    db.execute("INSERT INTO feed_items(id,source,type,title,url,fetched_at) VALUES ('hf:2610.00001','hf','paper','t','u',?)", [db.now()])
    db.execute("INSERT INTO feed_items(id,source,type,title,url,fetched_at) VALUES ('hf:2610.00002','hf','paper','t','u',?)", [db.now()])
    new = detail("HOT", "Fresh hot paper", 2026, 0, arxiv="2610.00001", refs=["A"], pub=datetime.now().strftime("%Y-%m-%d"))
    monkeypatch.setattr(col, "batch", lambda ids, c, fields=col.DETAIL_FIELDS: [new if i.endswith("00001") else None for i in ids])
    monkeypatch.setattr(lab, "judge_recent", lambda: {"judged": 0})
    st = padd.ingest_feed()
    assert (st["feed"], st["new"], st["admitted"], st["labeled"]) == (2, 1, 1, 1)
    r = db.row("SELECT * FROM paper_items WHERE s2id='HOT'")
    assert (r["status"], r["tier"], r["hot"], r["src"]) == ("in", "recent", 1, "feed")
    assert padd.ingest_feed()["labeled"] == 0                  # 再跑一次不重复标


# ---------- 论文库维护（_paper_maintain） ----------

from datetime import timedelta  # noqa: E402

from app.modules import _paper_maintain as maint  # noqa: E402


def months_ago(m):
    return (datetime.now() - timedelta(days=m * 30.44)).strftime("%Y-%m-%d")


def test_weekly_refreshes_cites_promotes_and_relabels_citers(client, monkeypatch, labeled):
    maint.init()
    db.execute("DELETE FROM paper_runs")
    paper("A", "base paper", 2023, 900)
    paper("CITER", "a paper that cites both", 2024, 400, refs=["A", "NEW"])
    paper("NEW", "late bloomer", 2025, 30, pub=months_ago(17))
    db.execute("UPDATE paper_items SET status='out', tier='young', detail_at=NULL, refs='[]' WHERE s2id='NEW'")
    paper("AGED", "was recent with a hot signal", 2025, 3, pub=months_ago(12))
    db.execute("UPDATE paper_items SET tier='recent' WHERE s2id='AGED'")
    lab.run()
    old_src = db.row("SELECT label_src FROM paper_labels WHERE s2id='CITER'")["label_src"]
    seen = []

    def batch(ids, c, fields=col.DETAIL_FIELDS):
        seen.append((fields, sorted(ids)))
        if fields == maint.CITE_FIELDS:
            return [{"paperId": s, "citationCount": 80 if s == "NEW" else 3, "influentialCitationCount": 1} for s in ids]
        return [detail(s, "late bloomer", 2025, 80, arxiv="xNEW", refs=["A"], pub=months_ago(17)) for s in ids]

    monkeypatch.setattr(col, "batch", batch)
    monkeypatch.setattr(lab, "judge_recent", lambda: {"judged": 0})
    st = maint.record("weekly", maint.weekly)
    assert seen[0] == (maint.CITE_FIELDS, ["AGED", "NEW"])            # 没入库的 + 入库的近两年论文；A / CITER 太老不刷
    assert (st["admitted"], st["relabel"], st["left"], st["errors"]) == (1, 1, 0, [])
    new = db.row("SELECT * FROM paper_items WHERE s2id='NEW'")
    assert (new["status"], new["tier"], new["cites"], new["title"]) == ("in", "young", 80, "late bloomer")
    assert db.row("SELECT 1 FROM paper_labels WHERE s2id='NEW'")
    assert db.row("SELECT label_src FROM paper_labels WHERE s2id='CITER'")["label_src"] != old_src   # builds_on 重标了
    assert db.row("SELECT status FROM paper_items WHERE s2id='AGED'")["status"] == "in"             # 变老门槛变高也不踢
    col.admit_all()
    assert db.row("SELECT status FROM paper_items WHERE s2id='AGED'")["status"] == "in"
    s = maint.status()
    assert s["weekly"]["status"] == "ok" and s["weekly"]["result"]["admitted"] == 1 and not s["weekly_alert"]
    assert not maint.due() and maint.due(datetime.now() + timedelta(days=8))


def test_weekly_only_refreshes_near_threshold_until_full_due(client, monkeypatch, labeled):
    maint.init()
    db.execute("DELETE FROM paper_runs")
    paper("IN", "in library", 2025, 100, pub=months_ago(12))
    for s2id, cites, title in [("FAR", 5, "far below"), ("CLOSE", 25, "close to sixty"),
                               ("IND", 12, "Google deployed online A/B test")]:   # 工业界门槛 30，12 ≥ 30/3
        paper(s2id, title, 2025, cites, pub=months_ago(12))
        db.execute("UPDATE paper_items SET status='out', tier='young' WHERE s2id=?", [s2id])
    lab.run()
    seen = []
    monkeypatch.setattr(col, "batch", lambda ids, c, fields=col.DETAIL_FIELDS: seen.append(sorted(ids)) or [None] * len(ids))
    st = maint.record("weekly", maint.weekly)
    assert st["full"] and seen[0] == ["CLOSE", "FAR", "IN", "IND"]        # 第一次（没全量过）全刷
    seen.clear()
    st = maint.record("weekly", maint.weekly)
    assert not st["full"] and seen[0] == ["CLOSE", "IND"]                 # 之后每周只刷接近门槛的
    db.execute("UPDATE paper_runs SET started=? WHERE id=(SELECT min(id) FROM paper_runs)",
               [(datetime.now() - timedelta(days=maint.FULL_DAYS + 1)).isoformat(timespec="seconds")])
    assert maint.full_due()


def test_runs_alert_after_two_failures(client):
    maint.init()
    db.execute("DELETE FROM paper_runs")

    def boom(step):
        raise RuntimeError("S2 down")
    for _ in range(2):
        with pytest.raises(RuntimeError):
            maint.record("feed", boom)
    s = maint.status()
    assert s["feed_alert"] and s["feed"]["status"] == "failed" and "S2 down" in s["feed"]["step"]
    maint.record("feed", lambda step: {"admitted": 2, "errors": ["未配置 JEV_API_KEY"]})
    s = maint.status()
    assert not s["feed_alert"] and s["feed"]["status"] == "partial"


def test_map_counts_papers_added_since_built(client, labeled):
    paper("P1", "speculative decoding drafts", 2024, 300)
    lab.run()
    res = {"topic": "推测解码", "intent": {"must": ["speculative decoding"], "should": [], "domains": []}, "created": db.now(),
           "lines": [], "chosen": []}
    db.execute("INSERT INTO paper_maps(topic,result,cost,created) VALUES (?,?,?,?)", ["推测解码", json.dumps(res), 0.01, res["created"]])
    assert [m["new"] for m in pmap.overview()["maps"]] == [0]                # 老脉络没存召回集：拿现在的召回当基线
    assert "pool" in json.loads(db.row("SELECT result FROM paper_maps")["result"])
    paper("P2", "faster speculative decoding", 2025, 100)
    lab.run()
    assert [m["new"] for m in pmap.overview()["maps"]] == [1]
