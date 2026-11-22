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


class _FakeRun:
    def __init__(self, d, outs):
        self.dir, self.topic, self.strong, self.light, self.outs, self.calls = d, "Agent 自进化", "s", "l", outs, []

    def has(self, name):
        return (self.dir / name).exists()

    def load(self, name):
        return json.loads((self.dir / name).read_text("utf-8"))

    def call(self, model, system, user):
        self.calls.append(system)
        return self.outs["g" if "骨架" in system else "q"]


def _unit(i, qid, user, kind="实践者", q=4, w=2):
    return {"i": i, "qid": qid, "user": user, "aid": f"10{i}", "day": "2026-11-0" + str(i % 9 + 1), "q": q, "w": w, "type": "经验",
            "claim": f"说法{i}", "key": "", "scope": "", "quote": "", "thesis": "", "source_kind": kind}


def _seed(d):
    units = [_unit(0, "Q1", "alice"), _unit(1, "Q1", "bob"), _unit(2, "Q2", "alice", q=5), _unit(3, "Q2", "carol", kind="推广")]
    cards = [{"id": i, "qid": u["qid"], "rep": i, "claim": u["claim"], "scope": "", "authors": [u["user"]], "maxq": u["q"], "members": [i]} for i, u in enumerate(units)]
    (d / "questions.json").write_text(json.dumps({"Q": [{"id": "Q1", "q": "信号从哪来？", "scope": ""}, {"id": "Q2", "q": "改哪一层？", "scope": ""}], "U": units}))
    (d / "merged.json").write_text(json.dumps({"C": cards, "conf": [{"a": 0, "b": 1, "point": "要不要人审"}]}))
    (d / "evidence.json").write_text(json.dumps({"shown": [0, 2], "ev": {}, "sum": {"Q1": {"now": "现状", "status": "有分歧"}}}))
    return units, cards


def test_synth_keeps_only_items_backed_by_real_cards(tmp_path):
    _seed(tmp_path)
    outs = {"q": {"do": [{"t": "读前三十条 trace", "c": [0, "C1", 99]}, {"t": "没有出处的做法", "c": [77]}, {"t": "", "c": [0]}],
                  "fail": [{"t": "改测试换绿灯", "c": ["1"]}]},
            "g": {"line": "一句话", "structure": [{"name": "信号", "what": "trace", "pitfall": "只看结果", "q": ["Q1", "Q9"]}, {"name": "", "q": ["Q1"]}],
                  "flow": [{"name": "采信号", "what": "记全", "q": ["Q1"]}], "levels": [{"name": "L1", "how": "纠正即写回", "needs": "", "example": "", "risk": ""}],
                  "disputes": [{"t": "人审", "a": "每次", "b": "攒批", "cond": "看作用域", "c": [0, 1]}, {"t": "编的", "a": "x", "b": "y", "cond": "z", "c": [55]}],
                  "failures": [{"name": "规则膨胀", "looks": "只加不删", "q": ["Q2", "QX"]}], "gaps": ["怎么退役", ""]}}
    r = _FakeRun(tmp_path, outs)
    s = ar.s_synth(r)
    assert s["q"]["Q1"]["do"] == [{"t": "读前三十条 trace", "c": [0, 1]}]          # 编造的编号丢掉，"C1" 这种写法认
    assert s["q"]["Q1"]["fail"] == [{"t": "改测试换绿灯", "c": [1]}]
    assert s["line"] == "一句话" and [x["q"] for x in s["structure"]] == [["Q1"]]    # 不存在的问题编号丢掉，没名字的块丢掉
    assert [x["t"] for x in s["disputes"]] == ["人审"] and s["failures"][0]["q"] == ["Q2"] and s["gaps"] == ["怎么退役"]
    assert len(r.calls) == 3                                                           # 每个问题一次，全局一次


def test_synth_refs_and_people(tmp_path):
    units, cards = _seed(tmp_path)
    syn = {"q": {"Q1": {"do": [{"t": "a", "c": [0, 1]}], "fail": []}}, "disputes": [{"t": "x", "c": [2]}]}
    refs = ar.synth_refs(syn, cards, units, {0, 2})
    assert refs["0"]["shown"] and not refs["1"]["shown"] and refs["1"]["url"] == "https://x.com/bob/status/101" and set(refs) == {"0", "1", "2"}
    ppl = ar.people(units)
    assert [p["user"] for p in ppl] == ["alice", "bob"]                              # 推广不算；按文章数、质量排
    assert ppl[0]["arts"] == 2 and ppl[0]["qs"] == ["Q1", "Q2"] and ppl[0]["best"] == "说法2"


def test_run_adds_synth_to_finished_topic_without_redoing_earlier_steps(tmp_path, monkeypatch):
    monkeypatch.setattr(ar, "BASE", tmp_path)
    monkeypatch.setattr(ar, "_models", lambda: ("l", "s"))
    d = tmp_path / ar.slug("T", "2026-11-01", "2026-11-02")
    d.mkdir()
    for st in ar.STAGES:
        if st != "synth":
            (d / ar.OUT[st]).write_text("{}")
    ran = []
    monkeypatch.setattr(ar, "FN", {st: (lambda r, st=st: ran.append(st) or {"st": st}) for st in ar.STAGES})
    ar.run("T", "2026-11-01", "2026-11-02")
    assert ran == ["synth", "page"]
    assert ar.STAGES.index("synth") == ar.STAGES.index("evidence") + 1
    assert json.loads((d / "status.json").read_text())["done"] is True
