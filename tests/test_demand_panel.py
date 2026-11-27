from app import db


def test_mark_seen_toggles_and_logs_read_once(client):
    r = client.put("/api/demand/seen/vidiq", json={"seen": True, "name": "vidIQ"})
    assert r.status_code == 200
    client.put("/api/demand/seen/vidiq", json={"seen": True, "name": "vidIQ"})
    a = client.get("/api/demand/activity").json()
    assert "vidiq" in a["seen"]
    reads = db.rows("SELECT * FROM read_log WHERE kind='demand' AND ref='vidiq'")
    assert len(reads) == 1 and reads[0]["title"] == "vidIQ"
    client.put("/api/demand/seen/vidiq", json={"seen": False})
    assert "vidiq" not in client.get("/api/demand/activity").json()["seen"]


def test_activity_counts_comments_and_claude_answers_per_company(client):
    now = db.now()
    a1 = db.insert("annotations", {"doc": "demand:vidiq", "title": "vidIQ", "quote": "按趋势推荐选题", "created_at": now, "updated_at": now})
    db.insert("annotation_msgs", {"annotation_id": a1, "role": "user", "content": "护城河是什么", "created_at": now})
    db.insert("annotation_msgs", {"annotation_id": a1, "role": "assistant", "content": "数据", "created_at": now})
    a2 = db.insert("annotations", {"doc": "demand:vidiq", "title": "vidIQ", "created_at": now, "updated_at": now})
    db.insert("annotation_msgs", {"annotation_id": a2, "role": "user", "content": "记一笔", "created_at": now})
    db.insert("annotations", {"doc": "research:3", "title": "x", "created_at": now, "updated_at": now})
    n = client.get("/api/demand/activity").json()["notes"]
    assert list(n) == ["vidiq"] and n["vidiq"]["threads"] == 2 and n["vidiq"]["asks"] == 1 and n["vidiq"]["last"] == now
