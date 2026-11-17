"""青少年板块：出题校验、入库、作答反馈只追加。"""
import json
from datetime import date, timedelta

from app import db, main  # noqa: F401
from app.modules import _teen as tn, teen


def _q(level, ability):
    return {"level": level, "ability": ability, "q": f"第{level}题", "answer": "思路……", "points": ["要点"], "hint": ""}


def _item(kind, domain, d):
    return {"kind": kind, "domain": domain, "headline": "某件事", "hook": "居然是这样", "train_focus": "区分事实和观点", "ability": "思辨",
            "why_this": "练分辨事实与说法", "ladder": "先看清，再追问，最后换位", "background": "背" * 160,
            "phenomenon": "现象", "source": {"name": "新华社", "url": "https://example.com/a", "date": d},
            "questions": [_q(1, "思辨"), _q(2, "思辨"), _q(3, "感同身受")]}


def _good():
    d = (date.today() - timedelta(days=1)).isoformat()
    return {"items": [_item("时事", "经济", d), _item("往事", "历史", "")]}


def test_check_accepts_good_day():
    assert tn.check(_good(), lambda u: (200, ""))["ok"]


def test_check_rejects_old_news_dead_link_and_skipped_level():
    out = _good()
    out["items"][0]["source"]["date"] = (date.today() - timedelta(days=30)).isoformat()
    out["items"][1]["questions"][1]["level"] = 3
    problems = tn.check(out, lambda u: (404, ""))["problems"]
    assert any("最近" in p for p in problems) and any("打不开" in p for p in problems) and any("level" in p for p in problems)


def test_job_done_stores_two_items_and_replies_append_only(client, monkeypatch):
    monkeypatch.setattr(teen, "_fetch_text", lambda u: (200, ""))
    did = teen.start_day()
    teen.on_job_done({"status": "done", "ref": f"teen:day:{did}", "output": json.dumps(_good(), ensure_ascii=False)})
    d = client.get("/api/teen/overview").json()
    items = d["days"][0]["items"]
    assert [i["kind"] for i in items] == ["时事", "往事"]
    iid = items[0]["id"]
    for text, sc in (("先写的", 1), ("后来改的", 2)):
        assert client.post(f"/api/teen/items/{iid}/reply", json={"qidx": 0, "kind": "answer", "content": text, "self_score": sc}).status_code == 200
    client.post(f"/api/teen/items/{iid}/reply", json={"kind": "improve", "content": "题再短一点"})
    got = client.get("/api/teen/overview").json()["days"][0]["items"][0]["replies"]
    assert [r["content"] for r in got] == ["先写的", "后来改的", "题再短一点"]
    assert "题再短一点" in teen.feedback_digest()["improve"]


def test_rejected_day_retries_with_reasons(monkeypatch):
    seen = []
    monkeypatch.setattr(teen, "start_day", lambda **kw: seen.append(kw) or 0)
    did = db.insert("teen_days", {"day": db.today(), "attempt": 1, "status": "running", "created_at": db.now()})
    teen.on_job_done({"status": "done", "ref": f"teen:day:{did}", "output": "不是 JSON"})
    assert db.row("SELECT status FROM teen_days WHERE id=?", [did])["status"] == "rejected"
    assert seen and "JSON" in seen[0]["redo"] and seen[0]["attempt"] == 2


def test_check_rejects_long_question():
    out = _good()
    out["items"][0]["questions"][0]["q"] = "问" * 120
    assert any("90 字" in p for p in tn.check(out, lambda u: (200, ""))["problems"])
