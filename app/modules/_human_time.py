"""人工耗时 = 有活动记录的分钟（含不超过 10 分钟的空隙）+ 手填的工作时段；碎片率 = 1 − 连续 25 分钟以上做同一项目的分钟 ÷ 人工耗时。"""
from __future__ import annotations

GAP_MAX = 10
WHOLE_MIN = 25
BLANK_MIN = 20
TYPING_CHARS_PER_MIN = 60
TYPING_MAX_MIN = 5
WORK_CATEGORIES = ("开发", "学习", "思考复盘")
CATEGORIES = (*WORK_CATEGORIES, "运动", "吃饭", "睡觉", "其他")
DAY_MIN = 1440


def minute(clock: str) -> int:
    return int(clock[:2]) * 60 + int(clock[3:5])


def clock(m: int) -> str:
    return f"{m // 60:02d}:{m % 60:02d}"


def session_events(sessions: list[dict]) -> list[tuple[int, int, str]]:
    events = []
    for s in sessions:
        if s.get("automated"):
            continue
        for m in s["messages"]:
            end = minute(m["t"])
            typing = max(1, min(TYPING_MAX_MIN, round(len(m.get("text") or "") / TYPING_CHARS_PER_MIN)))
            events.append((end - typing + 1, end, s["project"]))
    return events


def _entry_range(e: dict) -> tuple[int, int]:
    start, end = minute(e["start"]), minute(e["end"])
    return start, DAY_MIN - 1 if end <= start else end - 1


def _covered(ranges) -> set[int]:
    return {m for start, end in ranges for m in range(start, end + 1)}


def _blocks(events: list[tuple[int, int, str]]) -> list[list]:
    blocks: list[list] = []
    for start, end, project in sorted(events):
        if blocks and blocks[-1][2] == project and start - blocks[-1][1] <= GAP_MAX:
            blocks[-1][1] = max(blocks[-1][1], end)
        else:
            blocks.append([start, end, project])
    return blocks


def _blanks(filled: set[int]) -> list[dict]:
    marks = sorted(filled)
    return [{"start": clock(a + 1), "end": clock(b), "minutes": b - a - 1}
            for a, b in zip(marks, marks[1:]) if b - a - 1 >= BLANK_MIN]


def metrics(events: list[tuple[int, int, str]], entries: list[dict]) -> dict:
    work = [(*_entry_range(e), e["category"]) for e in entries if e["category"] in WORK_CATEGORIES]
    timeline = [*events, *work]
    active = _covered((start, end) for start, end, _ in timeline)
    marks = sorted(active)
    active |= {m for a, b in zip(marks, marks[1:]) if b - a - 1 <= GAP_MAX for m in range(a + 1, b)}
    blocks = _blocks(timeline)
    whole = _covered((b[0], b[1]) for b in blocks if b[1] - b[0] + 1 >= WHOLE_MIN) & active
    return {
        "minutes": len(active),
        "whole_min": len(whole),
        "fragment_pct": round(100 * (1 - len(whole) / len(active))) if active else None,
        "blocks": [{"start": clock(s), "end": clock(e + 1), "minutes": e - s + 1, "project": p, "whole": e - s + 1 >= WHOLE_MIN}
                   for s, e, p in blocks],
        "blanks": _blanks(active | _covered(_entry_range(e) for e in entries)),
    }
