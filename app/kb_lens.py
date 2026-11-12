"""判断卡（讨论的框架库）：各领域关键问题从哪些角度看、有哪些手段、空间多大、怎么算做得好。讨论时 Agent 自己挑合适的卡（见 app/modules/talk.py）。"""
from __future__ import annotations

import json
from pathlib import Path

DOMAINS = ["产品", "设计", "运营", "工程", "算法", "增长"]
SECTIONS = [("goal", "目标函数"), ("lenses", "看问题的角度"), ("levers", "手段谱系"),
            ("headroom", "空间判断"), ("quality", "好坏标准"), ("pitfalls", "常见反模式")]

def cards() -> list[dict]:
    return json.loads(Path(__file__).with_name("kb_lens.json").read_text(encoding="utf-8"))


def overview() -> dict:
    cs = cards()
    return {"sections": [{"key": k, "name": n} for k, n in SECTIONS],
            "domains": [{"name": d, "cards": [c for c in cs if c["domain"] == d]} for d in DOMAINS]}


def get(cid: str) -> dict | None:
    return next((c for c in cards() if c["id"] == cid), None)


def card_md(c: dict) -> str:
    lines = [f"# 判断卡 · {c['domain']} · {c['title']}", f"## 目标函数\n{c['goal']}"]
    for key, name in SECTIONS[1:]:
        items = [f"- {x['name']}：{x['how']}" for x in c[key]] if key == "levers" else [f"- {x}" for x in c[key]]
        lines.append(f"## {name}\n" + "\n".join(items))
    lines.append("## 参考\n" + "；".join(c["sources"]))
    lines.append(f"## 练习题\n{c['drill']}")
    return "\n\n".join(lines)


def index() -> str:
    """讨论时给 Agent 的框架库目录：每张卡一行，带 id、目标和看问题的角度，够它挑卡，又不占太多上下文。"""
    return "\n".join(f"- {c['id']}｜{c['domain']}｜{c['title']}：{c['goal']} 角度：" + "；".join(c["lenses"][:4]) for c in cards())
