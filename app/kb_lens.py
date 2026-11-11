"""判断卡：各领域关键问题从哪些角度看、有哪些手段、空间多大、怎么算做得好，可带着自己的场景和 Agent 讨论。"""
from __future__ import annotations

import json
from pathlib import Path

DOMAINS = ["产品", "设计", "运营", "工程", "算法", "增长"]
SECTIONS = [("goal", "目标函数"), ("lenses", "看问题的角度"), ("levers", "手段谱系"),
            ("headroom", "空间判断"), ("quality", "好坏标准"), ("pitfalls", "常见反模式")]

PARTNER = """## 判断卡讨论：帮用户练判断，而不是讲课
用户在用「判断卡」练习某个领域的判断力。卡片是一份看问题的框架，不是标准答案。
- 用户带来具体场景时，先让用户给出自己的判断（往哪看、选什么手段、估计还有多大空间）；用户已经给了，就按卡片的五个部分点评：漏了哪个角度、手段是否对症、空间估算有没有依据、怎么判断做得好，再给你自己的判断和信心。
- 用户没给场景时，用卡片的练习题或出一道贴近用户工作的新题，请用户先作答。
- 卡片不适用或有更好的看法时直接指出，必要时补充卡片外的角度；把通用经验、你的推断和已核实的事实分开。
- 涉及数字的估算写清假设和算法；需要用户过往材料时先查知识库。
- 简练：除非用户要求展开，每轮不超过 300 个汉字，只推进最关键的一处。不执行工程任务，不输出完成标准或验收汇报。
"""


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


def context(cid: str) -> str:
    c = get(cid)
    if c:
        return PARTNER + "\n" + card_md(c)
    cs = cards()
    index = "\n".join(f"- {d}：" + "；".join(f"{c['title']}（{c['id']}）" for c in cs if c["domain"] == d) for d in DOMAINS)
    return PARTNER + "\n用户没有指定卡片。先判断用户的问题属于哪个领域、哪张卡，按那张卡的框架讨论；都不合适就按同样的五个部分临时搭一个框架。\n## 全部判断卡\n" + index
