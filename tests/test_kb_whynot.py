from pathlib import Path

import pytest

from app import db, kb_graph, kb_judge, kb_whynot

ORIG = {"paperId": "P0", "title": "ReAct", "year": 2022, "citationCount": 3000, "externalIds": {"ArXiv": "2210.03629"}}
CITING = [
    {"paperId": "P1", "title": "Plan-and-Solve Prompting", "year": 2023, "abstract": "We plan then execute; compared with ReAct, plan-and-execute improves accuracy.", "externalIds": {"ArXiv": "2305.04091"}},
    {"paperId": "P2", "title": "Unrelated vision paper", "year": 2023, "abstract": "Image segmentation.", "externalIds": {}},
]


@pytest.fixture(autouse=True)
def _wipe_cache():
    kb_whynot._init()
    db.execute("DELETE FROM kb_s2_cache")


def _fake_s2(path, params=None, tries=6):
    if path.startswith("/paper/arXiv:"):
        return ORIG
    if path == "/paper/P0/citations":
        return {"data": [{"citingPaper": p} for p in CITING]}
    if path == "/paper/search":
        return {"data": []}
    raise AssertionError(path)


def _fake_llm(verdict_followup):
    def f(system, payload, max_tokens=6000):
        if system == kb_whynot.PAPER_SYSTEM:
            assert "Thought" in payload["note"]
            return {"verdict": "没回答", "summary": "论文只比了 Act-only 和 CoT。", "quotes": [{"text": "We compare...", "where": "Table 1"}], "hint": "规划的稳定性 vs 交替的纠错"}
        if system == kb_whynot.KW_SYSTEM:
            return {"groups": [["plan-and-execute", "plan then execute"], ["planning"]], "queries": ["plan and execute agent"]}
        if system == kb_whynot.FOLLOW_SYSTEM:
            assert [c["title"] for c in payload["candidates"]] == ["Plan-and-Solve Prompting"]   # 无关论文被关键词粗排筛掉
            assert payload["candidates"][0]["cites_original"]
            return {"verdict": verdict_followup, "summary": "Plan-and-Solve 直接对比过。", "cites": [{"n": 1, "finding": "先规划更准", "strength": "直接对比"}], "next": ""}
        return {}
    return f


def _item(tmp: Path) -> int:
    d = tmp / "1-arxiv-2210.03629"
    d.mkdir()
    (d / "note.md").write_text("# ReAct\n交替 Thought / Action / Observation", "utf-8")
    return db.insert("learn_items", {"kind": "paper", "url": "https://arxiv.org/abs/2210.03629", "title": "ReAct", "status": "done",
                                     "output_path": str(d / "note.md"), "created_at": db.now()})


def test_whynot_two_layers_and_score(client, monkeypatch, tmp_path):
    monkeypatch.setattr(kb_whynot, "s2_get", _fake_s2)
    monkeypatch.setattr(kb_graph, "llm_json", _fake_llm("XX 更好"))
    iid = _item(tmp_path)
    wid = kb_whynot.add(iid, "先整体规划再执行", "更好", "中", "规划能减少来回", check=False)
    kb_whynot.start_check(wid, wait=True)

    [w] = kb_whynot.of_item(iid)
    assert w["paper"]["verdict"] == "没回答" and w["paper"]["detail"]["quotes"][0]["where"] == "Table 1"
    assert w["followup"]["verdict"] == "XX 更好" and w["followup"]["detail"]["cites"][0]["url"] == "https://arxiv.org/abs/2305.04091"
    assert w["followup"]["detail"]["n_citations"] == 2
    assert w["verdict"] == "XX 更好" and w["hit"] == 1.0 and not w["running"]

    # 同时进了判断台账，依据材料是这篇论文
    j = db.row("SELECT * FROM kb_judgments WHERE id=?", [w["judgment_id"]])
    assert "为什么不用先整体规划再执行" in j["text"] and "item:%d" % iid in j["sources"]

    # 重查另起一行，旧结果保留；接口能读
    kb_whynot.start_check(wid, ("paper",), wait=True)
    assert db.row("SELECT COUNT(*) n FROM kb_whynot_checks WHERE wid=?", [wid])["n"] == 3
    o = client.get("/api/kb/whynot").json()
    assert o["stats"]["total"] == 1 and o["stats"]["hit_rate"] == 1.0 and o["items"][0]["item"]["title"] == "ReAct"


def test_whynot_untested_snoozes_judgment(client, monkeypatch, tmp_path):
    monkeypatch.setattr(kb_whynot, "s2_get", _fake_s2)
    monkeypatch.setattr(kb_graph, "llm_json", _fake_llm("还没人做"))
    iid = _item(tmp_path)
    wid = kb_whynot.add(iid, "用树搜索代替线性轨迹", "说不准", check=False)
    kb_whynot.start_check(wid, wait=True)
    [w] = kb_whynot.of_item(iid)
    assert w["verdict"] == "还没人做" and w["hit"] is None
    r = db.row("SELECT * FROM kb_claim_reviews WHERE sid=? ORDER BY id DESC", [w["sid"]])
    assert r["verdict"] == "snooze" and r["due"] == kb_judge._add_days(db.today(), kb_whynot.RECHECK_DAYS)
    assert client.get("/api/kb/whynot").json()["stats"]["untested"] >= 1


def test_whynot_layer_failure_is_recorded(client, monkeypatch, tmp_path):
    def boom(*a, **k):
        raise RuntimeError("S2 down")
    monkeypatch.setattr(kb_whynot, "s2_get", boom)
    monkeypatch.setattr(kb_graph, "llm_json", _fake_llm("XX 更好"))
    iid = _item(tmp_path)
    wid = kb_whynot.add(iid, "别的做法", check=False)
    kb_whynot.start_check(wid, wait=True)
    [w] = kb_whynot.of_item(iid)
    assert w["paper"]["status"] == "done" and w["followup"]["status"] == "failed" and "S2 down" in w["followup"]["summary"]
    assert w["verdict"] == ""
