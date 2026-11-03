import pytest

from app import db, kb, kb_graph, kb_judge

from test_kb_graph import _fake_llm as _graph_llm

CALLS: list[str] = []


def _fake_llm(system, payload, max_tokens=6000):
    if system == kb_judge.CLASSIFY_SYSTEM:
        CALLS.append("classify")
        out = []
        for it in payload["items"]:
            t = "预测" if "会" in it["mine"] else "疑问" if "？" in it["mine"] else "事实" if "复述" in it["mine"] else "观点"
            out.append({"sid": it["sid"], "type": t, "claim": "我认为" + it["mine"][:20], "confidence": "高",
                        "horizon_days": 60 if t == "预测" else None,
                        "eval": None if t in ("疑问", "事实") else {"strength": "中", "basis": "经验", "counter": "反例", "verify": "看数据"}})
        return {"items": out}
    if system == kb_judge.THREAD_SYSTEM:
        CALLS.append("threads")
        sids = [i["sid"] for i in payload["items"] if "甲概念" in i["concepts"]]
        return {"threads": [{"question": "甲概念该不该先做？", "sids": sids, "stance": "要先做", "shift": "从先做到一起看"}]}
    if system == kb_judge.RECHECK_SYSTEM:
        CALLS.append("recheck")
        return {"suggest": "仍成立", "why": "新材料支持 [x]", "ask": "还成立吗？", "cites": []}
    return _graph_llm(system, payload, max_tokens)


@pytest.fixture(autouse=True)
def _clean():
    """测试共用一个临时库：前后清掉本文件用到的表，不和 test_kb_graph 的数据互相影响。"""
    def wipe():
        for t in ("review_notes", "kb_sig_cache", "kb_llm_cache", "kb_claim_cache", "kb_judgments", "kb_claim_reviews", "kb_concept_edit"):
            if db.row("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", [t]):
                db.execute(f"DELETE FROM {t}")
    wipe()
    yield
    wipe()
    kb.sync(refresh_graph=False)


def _setup(monkeypatch):
    CALLS.clear()
    monkeypatch.setattr(kb_graph, "llm_json", _fake_llm)
    monkeypatch.setattr(kb_graph, "has_llm", lambda: True)
    # 全量跑时别的测试会在共用库里留下学习作答等信号，这里只看本文件写入的复盘和判断
    sigs = kb_graph.signals
    monkeypatch.setattr(kb_graph, "signals", lambda: [s for s in sigs() if s["sid"].split(":")[0] in ("note", "my", "rev")])
    for i, t in enumerate(["甲概念要先做", "甲概念和乙概念要一起看", "乙概念明年会不行", "这里只是复述甲概念", "乙概念到底靠不靠谱？"]):
        db.insert("review_notes", {"date": f"2026-02-0{i + 1}", "kind": "insight", "title": t, "content": t, "tags": ""})
    r = kb_graph.refresh()
    assert r["state"] == "idle", r


def test_ledger_classifies_threads_and_writes_files(client, monkeypatch):
    _setup(monkeypatch)
    j = client.get("/api/kb/judgments").json()
    assert j["stats"]["total"] == 4                      # 事实复述不收
    assert j["stats"]["by_type"] == {"观点": 2, "预测": 1, "评价": 0, "疑问": 1}
    th = j["threads"][0]
    assert th["question"] == "甲概念该不该先做？" and len(th["items"]) == 2 and th["changed"]
    assert th["items"][0]["date"] <= th["items"][1]["date"]
    assert [c["type"] for c in j["open"]] == ["疑问"]
    pred = next(c for c in j["singles"] if c["type"] == "预测")
    assert pred["due"] == "2026-04-04" and pred["eval"]["counter"] == "反例"   # 2/3 + 60 天
    # 历史判断都已过了第一次复查日 → 到期并已有 Agent 参考结论
    assert j["stats"]["due"] == 3 and all(c["agent"]["suggest"] == "仍成立" for c in j["due"])
    page = (kb.KB_DIR / "JUDGMENTS.md").read_text()
    assert "[[judgments/甲概念该不该先做？|甲概念该不该先做？]]" in page and "## 开放问题" in page
    thread_page = (kb.KB_DIR / "judgments/甲概念该不该先做？.md").read_text()
    assert "从先做到一起看" in thread_page and "Agent 评价" in thread_page
    assert any(h["type"] == "thread" for h in client.get("/api/kb/search", params={"q": "甲概念该不该先做"}).json())
    # 概念页的判断卡带复查状态
    c = client.get("/api/kb/concept", params={"name": "甲概念"}).json()
    js = [x for x in c["judgments"] if x.get("type")]
    assert len(js) == 2 and all(x["status"] == "open" and x["thread"] for x in js)
    # 再刷一次：全部命中缓存，不再调 LLM
    CALLS.clear()
    kb_graph.refresh()
    assert CALLS == []


def test_review_is_append_only_and_reschedules(client, monkeypatch):
    _setup(monkeypatch)
    j = client.get("/api/kb/judgments").json()
    op = next(c for c in j["due"] if c["type"] == "观点")
    sid = op["sid"]
    assert client.post("/api/kb/judgments/review", json={"sid": sid, "verdict": "holds", "note": "还对"}).status_code == 200
    c = next(x for x in client.get("/api/kb/judgments").json()["threads"][0]["items"] if x["sid"] == sid)
    assert c["status"] == "holds" and c["due"] == kb_judge._add_days(db.today(), 90)   # 第二次间隔 90 天
    client.post("/api/kb/judgments/review", json={"sid": sid, "verdict": "snooze", "due": "2030-01-01"})
    client.post("/api/kb/judgments/review", json={"sid": sid, "verdict": "revised", "note": "其实要和乙概念一起做"})
    assert client.post("/api/kb/judgments/review", json={"sid": sid, "verdict": "bad"}).status_code == 400
    # 重新整理不丢复查；修正时的新看法回流成一条判断
    kb_graph.refresh()
    j = client.get("/api/kb/judgments").json()
    c = next(x for x in j["threads"][0]["items"] + j["singles"] if x["sid"] == sid)
    assert [r["verdict"] for r in c["reviews"]] == ["holds", "snooze", "revised"] and c["status"] == "revised"
    assert c["reviews"][0]["note"] == "还对"
    assert any(x["sub"] == "revise" for x in j["threads"][0]["items"] + j["singles"])
    assert db.row("SELECT count(*) AS n FROM kb_claim_reviews")["n"] == 3
    assert "复查：修正" in (kb.KB_DIR / "judgments/甲概念该不该先做？.md").read_text()


def test_manual_judgment(client, monkeypatch):
    _setup(monkeypatch)
    monkeypatch.setattr(kb_graph, "schedule_refresh", lambda: None)
    r = client.post("/api/kb/judgments", json={"text": "Agent 框架年底会收敛到两三家", "type": "预测", "confidence": "低", "due": "2026-12-31"})
    assert r.status_code == 200 and r.json()["sid"].startswith("my:")
    assert client.post("/api/kb/judgments", json={"text": "  "}).status_code == 400
    kb_graph.refresh()
    c = next(x for x in client.get("/api/kb/judgments").json()["singles"] if x["sid"] == r.json()["sid"])
    assert c["type"] == "预测" and c["confidence"] == "低" and c["due"] == "2026-12-31" and c["sub_name"] == "我记的判断"


def test_schedule_rules():
    s = {"date": "2026-01-01"}
    rv = lambda v, at, due="": {"verdict": v, "at": at, "due": due}  # noqa: E731
    assert kb_judge.schedule(s, {"type": "观点"}, []) == ("open", "2026-01-31")
    assert kb_judge.schedule(s, {"type": "观点"}, [rv("holds", "2026-02-01")]) == ("holds", "2026-05-02")
    assert kb_judge.schedule(s, {"type": "评价"}, [rv("holds", "2026-02-01"), rv("holds", "2026-05-01")])[1] == "2026-10-28"
    assert kb_judge.schedule(s, {"type": "预测", "horizon_days": 200}, []) == ("open", "2026-07-20")
    assert kb_judge.schedule(s, {"type": "预测"}, [rv("holds", "2026-03-01")]) == ("holds", "")
    assert kb_judge.schedule(s, {"type": "观点"}, [rv("overturned", "2026-03-01")]) == ("overturned", "")
    assert kb_judge.schedule(s, {"type": "观点"}, [rv("pending", "2026-03-01")]) == ("pending", "2026-03-31")
    assert kb_judge.schedule(s, {"type": "观点"}, [rv("snooze", "2026-01-20", "2026-06-01")]) == ("open", "2026-06-01")
    assert kb_judge.schedule(s, {"type": "疑问"}, []) == ("open", "")
    assert kb_judge.schedule(s, {"type": "观点"}, [], "2026-01-10") == ("open", "2026-01-10")
    assert kb_judge.schedule(s, {"type": "事实"}, []) == ("open", "")

