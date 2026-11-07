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
                               "tier": 75, "feedback": 1.4, "value": "核心", "why": "有测试"},
                              {"title": "u", "scale": 1, "uncertainty": 1, "verify": 1, "cycle": 1,
                               "tier": 100, "feedback": 0.2, "value": "低"}],
         "avoidable": {"推进下一步": 3, "催进度": 3}, "necessary": {"定目标": 1}},
        {"id": "ghost", "tasks": []},
        {"id": "c", "abandoned": True},
    ])
    by = score.parse(out, SESS)
    assert set(by) == {"a", "c"}
    t = by["a"]["tasks"][0]
    assert (t["scale"], t["uncertainty"], t["verify"]) == (3, 1, 2)
    assert (t["tier"], t["feedback"], t["value"]) == (70, 1.0, "中")       # 档位就低取整，系数截到 0.5–1.0，不认识的价值按中
    u = by["a"]["tasks"][1]
    assert (u["tier"], u["feedback"], u["value"]) == (100, 0.5, "低")
    assert sum(by["a"]["avoidable"].values()) == 4 and by["a"]["avoidable"]["推进下一步"] == 3   # 从后往前扣
    assert by["c"]["abandoned"]
    assert score.parse("没有 json", SESS) == {}


def test_compute_core_metrics():
    by = score.parse(_out([
        {"id": "a", "tasks": [{"scale": 2, "uncertainty": 2, "verify": 2, "cycle": 2, "tier": 70, "feedback": 0.9, "value": "高"}],
         "avoidable": {"催进度": 1}},
        {"id": "b", "tasks": [{"scale": 1, "uncertainty": 1, "verify": 1, "cycle": 1, "tier": 100, "feedback": 1, "value": "低"},
                              {"scale": 1, "uncertainty": 1, "verify": 1, "cycle": 1, "tier": 20, "feedback": 1, "value": "中"}],
         "avoidable": {"形式反复": 2}},
    ]), SESS)
    r = score.compute(by, SESS)
    a, b = {x["session_id"]: x for x in r["sessions"]}.values()
    assert (a["result"], a["difficulty"], a["output_h"], a["value_score"], a["status"]) == (63, 8, 1.23, 100, "🟡")
    assert [t["output_h"] for t in b["tasks"]] == [0.12, 0]                 # 未提交的任务产出记 0
    assert (b["result"], b["value_score"], b["status"], b["avoidable_pct"]) == (60, 50, "🟡", 100)
    c = r["core"]
    out = 1.3 * 0.63 * 1.5 + 0.25 * 0.5
    assert r["output_h"] == round(out, 2)
    assert c["result"] == round((1.3 * 63 + 0.25 * 100 + 0.25 * 20) / 1.8)
    assert c["throughput"] == round(out / 1.5, 2)
    assert r["value_score"] == round((1.3 * 100 + 0.25 * 33 + 0.25 * 67) / 1.8)
    assert c["leverage"] == round(100 / 7, 1)            # 脚本会话不计，未评分的 c 也算杠杆
    assert c["avoidable_pct"] == 50                      # 3 / 6
    assert r["scored"] == 2 and r["scorable"] == 3 and r["avoidable_by_type"]["形式反复"] == 2
    empty = score.compute({}, SESS)["core"]
    assert empty["result"] is None and empty["leverage"] == c["leverage"]


def test_scores_from_old_rubric_count_as_unscored():
    old = {"by_session": {"a": {"abandoned": False, "tasks": [{"scale": 2, "uncertainty": 2, "verify": 2, "cycle": 2,
                                                               "done": 50, "quality": 30, "evidence": 20}],
                                "avoidable": {}, "necessary": {}, "note": ""}}}
    r = score.compute(score.current(old), SESS)
    assert r["scored"] == 0 and r["core"]["result"] is None


def test_prompt_lists_only_interactive_sessions():
    p = score.build_prompt("2026-11-01", SESS)
    assert "id=a" in p and "id=bot" not in p and "```json" in p
    assert "交付档" in p and "价值" in p and "完成度" not in p
