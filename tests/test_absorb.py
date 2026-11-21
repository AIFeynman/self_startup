"""选题吸收：认知卡表态（受用程度 + 星级）的接口。不调 LLM。"""
import json

from app.modules import _absorb_run as ar
from app.modules import absorb


def test_api_card_react_with_stars(client, tmp_path, monkeypatch):
    monkeypatch.setattr(ar, "BASE", tmp_path)
    monkeypatch.setattr(absorb, "FB", tmp_path / "fb.jsonl")
    d = tmp_path / "Agent-评测_2026-11-03_2026-11-16"
    d.mkdir()
    (d / "run.json").write_text(json.dumps({"topic": "Agent 评测", "start": "2026-11-03", "end": "2026-11-16"}))
    (d / "status.json").write_text(json.dumps({"done": True, "pid": 0}))
    (d / "cards.json").write_text(json.dumps({"cards": [{"id": 3, "claim": "结论", "tag": "h", "qid": "Q1", "type": "结论", "w": 3, "conf": {}}],
                                              "questions": [{"id": "Q1", "q": "问题？"}]}))
    rid = d.name
    url = f"/api/absorb/runs/{rid}/react"
    assert client.post(url, json={"card": 3, "act": "很受用", "stars": 4}).status_code == 200
    assert client.get(f"/api/absorb/runs/{rid}").json()["reactions"]["3"] | {"at": 0} == {"act": "很受用", "stars": 4, "at": 0}
    assert client.post(url, json={"card": 3, "stars": 5}).status_code == 200          # 只打星也算
    assert client.get(f"/api/absorb/runs/{rid}").json()["reactions"]["3"]["stars"] == 5
    assert client.post(url, json={"card": 3, "stars": 6}).status_code == 400
    assert client.post(url, json={"card": 3}).status_code == 200
    assert client.get(f"/api/absorb/runs/{rid}").json()["reactions"] == {}
    ev = [json.loads(x) for x in (tmp_path / "fb.jsonl").read_text().splitlines()]
    assert ev[0]["stars"] == 4 and ev[1]["stars"] == 5 and ev[1]["act"] == ""
