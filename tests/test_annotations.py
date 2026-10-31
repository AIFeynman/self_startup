"""阅读批注：划线评论、问 Claude（第一问带全文，追问续接会话）、解决 / 删除、同步进知识库。"""
import time

from app import agent, annotations, db, kb


def _wait_answer(client, aid, timeout=5):
    end = time.time() + timeout
    while time.time() < end:
        a = client.get("/api/annotations", params={"doc": "research:9:synth"}).json()
        t = next(x for x in a if x["id"] == aid)
        if all(m["status"] != "pending" for m in t["msgs"]):
            return t
        time.sleep(0.05)
    raise AssertionError("回答超时")


def test_comment_ask_followup_and_kb(client, monkeypatch):
    calls = []

    def fake_stream(prompt, **kw):
        calls.append((prompt, kw))
        yield {"type": "session", "id": "s-1"}
        yield {"type": "tool", "text": "WebSearch: tau-bench"}
        yield {"type": "text", "text": "τ-bench 测的是多轮工具调用。"}
        yield {"type": "done", "text": "τ-bench 测的是多轮工具调用。", "engine": "claude"}

    monkeypatch.setattr(agent, "run_stream", fake_stream)
    doc = {"doc": "research:9:synth", "title": "Agent 评测 · 综合结论", "link": "#research/r/9"}

    # 只评论：不调用 Claude
    c = client.post("/api/annotations", json={**doc, "quote": "SWE-bench 用真实 issue", "prefix": "其中", "suffix": "来评测",
                                              "text": "这个和我们的场景接近"}).json()
    assert [m["role"] for m in c["msgs"]] == ["user"] and not calls

    # 划线问 Claude（留空 = 解释这段）：第一问带全文和划线
    a = client.post("/api/annotations", json={**doc, "quote": "τ-bench", "ask": True, "source": "# 综合\n…τ-bench…全文"}).json()
    assert a["msgs"][0]["content"] == annotations.DEFAULT_QUESTION and a["msgs"][1]["status"] in ("pending", "done")
    t = _wait_answer(client, a["id"])
    assert t["msgs"][-1]["content"] == "τ-bench 测的是多轮工具调用。" and "WebSearch" in t["msgs"][-1]["log"]
    assert t["engine_session"] == "s-1"
    prompt, kw = calls[0]
    assert "「τ-bench」" in prompt and "…τ-bench…全文" in prompt and kw["session"] == "" and "阅读助手" in kw["system"]

    # 追问：续接会话，不再塞全文
    client.post(f"/api/annotations/{a['id']}/msgs", json={"text": "和 SWE-bench 比呢？", "ask": True, "source": "全文"})
    t = _wait_answer(client, a["id"])
    prompt, kw = calls[1]
    assert kw["session"] == "s-1" and "和 SWE-bench 比呢？" in prompt and "全文" not in prompt
    assert [m["role"] for m in t["msgs"]] == ["user", "assistant", "user", "assistant"]

    # 解决、同步进知识库
    assert client.patch(f"/api/annotations/{c['id']}", json={"status": "resolved"}).json()["status"] == "resolved"
    kb.sync()
    files = list((kb.KB_DIR / "annotations").glob("*.md"))
    text = "\n".join(f.read_text("utf-8") for f in files)
    assert "批注：Agent 评测 · 综合结论" in text and "> SWE-bench 用真实 issue" in text and "（已解决）" in text
    assert "**Claude**" in text and "和 SWE-bench 比呢？" in text

    # 删除
    client.delete(f"/api/annotations/{c['id']}")
    assert [x["id"] for x in client.get("/api/annotations", params={"doc": doc["doc"]}).json()] == [a["id"]]
    assert annotations.active == 0


def test_validation_and_pending_guard(client, monkeypatch):
    assert client.post("/api/annotations", json={"doc": "kb:x.md", "quote": "q"}).status_code == 400
    aid = db.insert("annotations", {"doc": "kb:x.md", "created_at": db.now(), "updated_at": db.now()})
    db.insert("annotation_msgs", {"annotation_id": aid, "role": "assistant", "status": "pending", "created_at": db.now()})
    r = client.post(f"/api/annotations/{aid}/msgs", json={"text": "再问", "ask": True})
    assert r.status_code == 400 and "还在回答" in r.json()["detail"]


def test_failed_answer_is_recorded(client, monkeypatch):
    def broken(prompt, **kw):
        yield {"type": "error", "text": "claude 不可用"}
    monkeypatch.setattr(agent, "run_stream", broken)
    a = client.post("/api/annotations", json={"doc": "research:9:synth", "ask": True}).json()
    t = _wait_answer(client, a["id"])
    assert t["msgs"][-1]["status"] == "failed" and "claude 不可用" in t["msgs"][-1]["content"]
