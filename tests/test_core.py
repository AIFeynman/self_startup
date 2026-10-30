def test_meta_and_tasks(client):
    assert "modules" in client.get("/api/meta").json()
    t = client.post("/api/tasks", json={"title": "写周报", "priority": 1}).json()
    assert client.patch(f"/api/tasks/{t['id']}", json={"status": "done"}).json()["status"] == "done"
    assert any(x["id"] == t["id"] for x in client.get(f"/api/tasks?date={t['date']}").json())


def test_settings_roundtrip(client):
    s = client.get("/api/settings").json()
    assert s["focus_windows"][0]["start"] == "10:00"
    assert client.put("/api/settings", json={"max_agent_concurrency": 2}).json()["max_agent_concurrency"] == 2
