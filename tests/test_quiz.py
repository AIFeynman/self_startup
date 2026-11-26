"""复盘 · 考题卡：批注 / Claude 对话 / 已读历史出题，艾宾浩斯间隔复习，错题出变式。不触网，大模型全部替换。"""
import json
from datetime import date, timedelta

import pytest

from app import db

TODAY = date.today()


def _d(n: int) -> str:
    return (TODAY + timedelta(days=n)).isoformat()


@pytest.fixture(autouse=True)
def _clean(client, monkeypatch):
    from app.modules import _quiz, _read_log
    _read_log._ensure()
    monkeypatch.setattr(_quiz, "BACKGROUND", False)
    monkeypatch.setattr(_quiz, "_llm", _offline)
    for t in ("annotations", "annotation_msgs", "chat_sessions", "chat_messages", "read_log", "feed_items",
              "quiz_cards", "quiz_attempts", "quiz_meta"):
        db.execute(f"DELETE FROM {t}")
    yield


def _offline(system, payload):
    raise RuntimeError("no llm in tests")


def _ann(question="为什么 harness 要把上下文放到外面管理？", answer="因为模型只需要看到局部熟悉的输入，长任务才能组合泛化。", quote="externalize context"):
    aid = db.insert("annotations", {"doc": "learn:item:1", "title": "Harness 论文深读", "link": "#learn/item/1", "quote": quote,
                                    "prefix": "", "suffix": "", "status": "open", "created_at": db.now(), "updated_at": db.now()})
    db.insert("annotation_msgs", {"annotation_id": aid, "role": "user", "content": question, "created_at": db.now()})
    if answer is not None:
        db.insert("annotation_msgs", {"annotation_id": aid, "role": "assistant", "content": answer, "status": "done", "created_at": db.now()})
    return aid


def _card():
    return db.row("SELECT * FROM quiz_cards")


def test_annotation_question_becomes_card_without_llm(client):
    _ann()
    assert client.post("/api/review/quiz/harvest").json()["new"] == 1
    c = _card()
    assert "为什么 harness 要把上下文放到外面管理" in c["q"] and "组合泛化" in c["answer"]
    assert c["due"] == _d(1) and c["stage"] == 0 and c["src_link"] == "#learn/item/1"
    assert client.post("/api/review/quiz/harvest").json()["new"] == 0


def test_llm_writes_question_for_read_item(client, monkeypatch):
    from app.modules import _quiz
    db.insert("feed_items", {"id": "hn:1", "source": "hn", "type": "discussion", "title": "Harness adapters",
                             "summary": "Train a small adapter so the model fits the agent harness, cutting cost by 40%.", "url": "https://x"})
    db.insert("read_log", {"kind": "feed", "ref": "hn:1", "title": "Harness adapters", "url": "https://x", "source": "HN", "at": db.now()})
    monkeypatch.setattr(_quiz, "_llm", lambda s, p: {"point": "harness adapter", "q": "harness adapter 省钱靠什么？", "answer": "小适配器让模型贴合 harness，成本降 40%"})
    client.post("/api/review/quiz/harvest")
    c = _card()
    assert c["q"] == "harness adapter 省钱靠什么？" and c["point"] == "harness adapter" and c["src_kind"] == "read"


def test_read_item_without_llm_is_skipped(client):
    db.insert("read_log", {"kind": "feed", "ref": "hn:2", "title": "Some post", "url": "https://y", "source": "HN", "at": db.now()})
    assert client.post("/api/review/quiz/harvest").json()["new"] == 0


def _due_card(client):
    _ann()
    client.post("/api/review/quiz/harvest")
    db.execute("UPDATE quiz_cards SET due=?", [TODAY.isoformat()])
    return _card()["id"]


def test_due_list_hides_reference_answer(client):
    cid = _due_card(client)
    r = client.get("/api/review/quiz").json()
    assert [c["id"] for c in r["due"]] == [cid] and "answer" not in r["due"][0]
    assert r["stats"]["due"] == 1


def test_right_answer_moves_along_ebbinghaus_intervals(client, monkeypatch):
    from app.modules import _quiz
    cid = _due_card(client)
    monkeypatch.setattr(_quiz, "_llm", lambda s, p: {"score": 8, "feedback": "抓住了要点"})
    r = client.post(f"/api/review/quiz/{cid}/answer", json={"answer": "让模型只看局部输入"}).json()
    assert r["verdict"] == "right" and r["next_due"] == _d(2) and "组合泛化" in r["answer"]
    for gap in (4, 7, 15, 30):
        db.execute("UPDATE quiz_cards SET due=?", [TODAY.isoformat()])
        assert client.post(f"/api/review/quiz/{cid}/answer", json={"answer": "x"}).json()["next_due"] == _d(gap)
    db.execute("UPDATE quiz_cards SET due=?", [TODAY.isoformat()])
    assert client.post(f"/api/review/quiz/{cid}/answer", json={"answer": "x"}).json()["mastered"]
    assert _card()["status"] == "mastered"


def test_wrong_answer_resets_and_next_time_asks_a_variant(client, monkeypatch):
    from app.modules import _quiz
    cid = _due_card(client)
    old_q = _card()["q"]
    db.execute("UPDATE quiz_cards SET stage=3")

    def llm(system, payload):
        if "variant" in system.lower() or "变式" in system:
            return {"q": "如果把上下文都塞进 prompt，长任务会出什么问题？", "answer": "输入越来越陌生，模型难以泛化。"}
        return {"score": 2, "feedback": "没提到局部输入"}
    monkeypatch.setattr(_quiz, "_llm", llm)
    r = client.post(f"/api/review/quiz/{cid}/answer", json={"answer": "不知道"}).json()
    assert r["verdict"] == "wrong" and r["next_due"] == _d(1)
    c = _card()
    assert c["stage"] == 0 and c["wrong"] == 1 and c["variant"] == 1
    assert c["q"] == "如果把上下文都塞进 prompt，长任务会出什么问题？" and c["q"] != old_q
    assert db.row("SELECT q FROM quiz_attempts")["q"] == old_q


def test_dont_know_counts_wrong_and_shows_answer(client):
    cid = _due_card(client)
    r = client.post(f"/api/review/quiz/{cid}/answer", json={"answer": "", "dont_know": True}).json()
    assert r["verdict"] == "wrong" and "组合泛化" in r["answer"] and _card()["wrong"] == 1


def test_grader_down_lets_user_self_grade(client):
    cid = _due_card(client)
    r = client.post(f"/api/review/quiz/{cid}/answer", json={"answer": "局部输入"}).json()
    assert r["verdict"] == "pending" and _card()["due"] == TODAY.isoformat()
    r = client.post(f"/api/review/quiz/{cid}/override", json={"verdict": "right"}).json()
    assert r["next_due"] == _d(2) and _card()["stage"] == 1


def test_override_reverts_wrong_grade(client, monkeypatch):
    from app.modules import _quiz
    cid = _due_card(client)
    db.execute("UPDATE quiz_cards SET stage=2")
    monkeypatch.setattr(_quiz, "_llm", lambda s, p: {"score": 3, "feedback": "不对"} if "score" in s else {})
    client.post(f"/api/review/quiz/{cid}/answer", json={"answer": "局部输入"})
    r = client.post(f"/api/review/quiz/{cid}/override", json={"verdict": "right"}).json()
    c = _card()
    assert c["stage"] == 3 and c["wrong"] == 0 and r["next_due"] == _d(7)


def test_daily_cap_puts_wrong_cards_first(client):
    for i in range(12):
        _ann(question=f"问题 {i} 是什么意思？", quote=f"q{i}")
    client.post("/api/review/quiz/harvest")
    db.execute("UPDATE quiz_cards SET due=?", [TODAY.isoformat()])
    last = db.row("SELECT max(id) m FROM quiz_cards")["m"]
    db.execute("UPDATE quiz_cards SET wrong=2 WHERE id=?", [last])
    r = client.get("/api/review/quiz").json()
    assert len(r["due"]) == 10 and r["due"][0]["id"] == last and r["stats"]["due"] == 12


def test_chat_session_becomes_card(client):
    sid = db.insert("chat_sessions", {"module": "learn", "ref": "", "engine": "claude", "title": "问 MCP", "created_at": db.now(), "updated_at": db.now()})
    db.insert("chat_messages", {"session_id": sid, "role": "user", "content": "MCP 和 function calling 有什么区别？", "created_at": db.now()})
    db.insert("chat_messages", {"session_id": sid, "role": "assistant", "content": "MCP 是跨应用的工具协议，function calling 是单个模型 API 的能力。", "created_at": db.now()})
    client.post("/api/review/quiz/harvest")
    c = _card()
    assert c["src_kind"] == "chat" and "MCP 和 function calling" in c["q"] and "跨应用" in c["answer"]


def test_harvest_takes_turns_between_sources(client):
    from app.modules import _quiz
    for i in range(3):
        _ann(question=f"问题 {i} 是什么？", quote=f"q{i}")
    sid = db.insert("chat_sessions", {"module": "learn", "ref": "", "engine": "claude", "title": "对话", "created_at": db.now(), "updated_at": db.now()})
    db.insert("chat_messages", {"session_id": sid, "role": "user", "content": "什么是 KV cache？", "created_at": db.now()})
    db.insert("chat_messages", {"session_id": sid, "role": "assistant", "content": "缓存注意力的键值，避免重复计算。", "created_at": db.now()})
    assert _quiz.harvest(limit=2) == 2
    assert {r["src_kind"] for r in db.rows("SELECT src_kind FROM quiz_cards")} == {"ann", "chat"}
