import base64

from app import chat, db

PNG = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jE7sAAAAASUVORK5CYII="


def test_images_persist_in_discussion_and_reach_model(client, monkeypatch):
    uploaded = client.post("/api/chat/images", json={"name": "test.png", "data": "data:image/png;base64," + PNG})
    assert uploaded.status_code == 200
    img = uploaded.json()
    assert client.get(img["url"]).content == base64.b64decode(PNG)
    calls = []
    def stream(prompt, **kw):
        calls.append(prompt)
        assert img["id"] in prompt and "Read" in prompt
        yield {"type": "done", "text": "图片里的前提值得检验。", "engine": "claude"}
    monkeypatch.setattr(chat.agent, "run_stream", stream)
    client.post("/api/chat/talk", json={"message": "看这张图", "images": [img["id"]]})
    sid = db.row("SELECT id FROM chat_sessions WHERE module='talk' ORDER BY id DESC LIMIT 1")["id"]
    saved = client.get(f"/api/chat/session/{sid}").json()
    assert saved["messages"][0]["images"] == [img]
    assert calls
    assert client.post("/api/chat/images", json={"name": "fake.png", "data": "data:image/png;base64," + base64.b64encode(b"not an image").decode()}).status_code == 400
    assert client.get("/api/chat/images/../../etc/passwd").status_code != 200
    assert client.post("/api/chat/talk", json={"message": "x", "images": ["missing"]}).status_code == 400


def test_image_only_input_and_upload_boundaries(client, monkeypatch):
    from app import chat_images
    img = client.post("/api/chat/images", json={"name": "../photo.png", "data": "data:image/png;base64," + PNG}).json()
    assert img["name"] == "photo.png"
    def stream(prompt, **kw):
        assert img["id"] in prompt
        yield {"type": "done", "text": "我看到了图片。", "engine": "claude"}
    monkeypatch.setattr(chat.agent, "run_stream", stream)
    assert client.post("/api/chat/talk", json={"message": "", "images": [img["id"]]}).status_code == 200
    assert client.post("/api/chat/talk", json={"message": " "}).status_code == 400
    assert client.post("/api/chat/talk", json={"message": "x", "images": [img["id"]] * 5}).status_code == 422
    assert client.post("/api/chat/talk", json={"message": "x", "images": [img["id"]] * 2}).status_code == 400
    monkeypatch.setattr(chat_images, "MAX_BYTES", 16)
    assert client.post("/api/chat/images", json={"name": "big.png", "data": "data:image/png;base64," + PNG}).status_code == 400
    assert client.post("/api/chat/images", json={"name": "a.svg", "data": "data:image/svg+xml;base64," + PNG}).status_code == 400
