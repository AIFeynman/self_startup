import json

from app.modules import _session_score as score


def _s(sid, turns, active, **kw):
    return {"session_id": sid, "engine": "claude", "project": "p", "title": sid, "start": "2026-11-01T09:00:00",
            "end": "2026-11-01T10:00:00", "active_min": active, "human_turns": turns, "automated": False,
            "leverage_min": round(active / turns, 1) if turns else None, "messages": [], **kw}


SESS = [_s("a", 4, 60), _s("b", 2, 30), _s("c", 1, 10), _s("bot", 0, 50, automated=True)]


def _out(rows):
    return "说明几句\n```json\n" + json.dumps({"sessions": rows}, ensure_ascii=False) + "\n```"


def test_parse_clamps_and_caps_avoidable():
    out = _out([
        {"id": "a", "tasks": [{"title": "t", "scale": 9, "uncertainty": 0, "verify": "2", "cycle": 1,
                               "done": 80, "quality": 30, "evidence": 20, "why": "有测试"}],
         "avoidable": {"推进下一步": 3, "催进度": 3}, "necessary": {"定目标": 1}},
        {"id": "ghost", "tasks": []},
        {"id": "c", "abandoned": True},
    ])
    by = score.parse(out, SESS)
    assert set(by) == {"a", "c"}
    t = by["a"]["tasks"][0]
    assert (t["scale"], t["uncertainty"], t["verify"], t["done"]) == (3, 1, 2, 50)
    assert sum(by["a"]["avoidable"].values()) == 4 and by["a"]["avoidable"]["推进下一步"] == 3   # 从后往前扣
    assert by["c"]["abandoned"]
    assert score.parse("没有 json", SESS) == {}


def test_compute_core_metrics():
    by = score.parse(_out([
        {"id": "a", "tasks": [{"scale": 2, "uncertainty": 2, "verify": 2, "cycle": 2, "done": 50, "quality": 30, "evidence": 20}],
         "avoidable": {"催进度": 1}},
        {"id": "b", "tasks": [{"scale": 1, "uncertainty": 1, "verify": 1, "cycle": 1, "done": 25, "quality": 10, "evidence": 15}],
         "avoidable": {"形式反复": 2}},
    ]), SESS)
    r = score.compute(by, SESS)
    a, b = {x["session_id"]: x for x in r["sessions"]}.values()
    assert (a["result"], a["difficulty"], a["output_h"], a["status"]) == (100, 8, 1.3, "✅")
    assert (b["result"], b["output_h"], b["status"], b["avoidable_pct"]) == (50, 0.12, "🟡", 100)
    c = r["core"]
    assert c["result"] == round((1.3 + 0.125) / (1.3 + 0.25) * 100)
    assert c["throughput"] == round(1.425 / 1.5, 2)
    assert c["leverage"] == round(100 / 7, 1)            # 脚本会话不计，未评分的 c 也算杠杆
    assert c["avoidable_pct"] == 50                      # 3 / 6
    assert r["scored"] == 2 and r["scorable"] == 3 and r["avoidable_by_type"]["形式反复"] == 2
    empty = score.compute({}, SESS)["core"]
    assert empty["result"] is None and empty["leverage"] == c["leverage"]


def test_prompt_lists_only_interactive_sessions():
    p = score.build_prompt("2026-11-01", SESS)
    assert "id=a" in p and "id=bot" not in p and "```json" in p
