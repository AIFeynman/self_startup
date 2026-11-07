"""Agent 核心指标：结果分、吞吐、杠杆、可避免交互占比（口径同 session-report 技能 / 飞书「日开发汇总」）。

杠杆由日志直接算（_review_sessions）；结果分、任务难度、可避免交互要读懂会话，交给一次后台 Agent 评分：
    build_prompt  → 交互会话的素材 + 评分规则，要求输出一个 JSON 块
    parse         → 校验、截断到合法范围
    compute       → 按标准工时 × 结果分 × 价值系数折算产出、吞吐，汇总当天四个核心指标
"""
from __future__ import annotations

import json
import re

STD_HOURS = {4: 0.25, 5: 0.4, 6: 0.6, 7: 0.9, 8: 1.3, 9: 1.8, 10: 2.5, 11: 3.5, 12: 5.0}   # 难度 → 标准工时
TIERS = (20, 40, 60, 70, 85, 100)
VALUE = {"高": (1.5, 100), "中": (1.0, 67), "低": (0.5, 33)}   # 价值档 → (产出系数, 展示分)
RUBRIC_VERSION = 2
AVOIDABLE = ("推进下一步", "催进度", "形式反复", "纠偏返工", "替Agent实测")
NECESSARY = ("定目标", "给约束", "审批", "验收", "只能人做")
CORE = (  # (key, 名称, 单位, 越高越好, 定义)
    ("result", "结果分", "", True, "每个任务 0–100：交付档（未提交 20 / 待合并 40 / 本地 main 60 / push main 70 / dev 85 / 线上 100）× 反馈系数（一次通过 1.0，每多一轮修改 −0.1，最低 0.7，被否定 0.5）；按标准工时加权平均。衡量做得好不好"),
    ("throughput", "吞吐", "", True, "产出 ÷ Agent 活跃小时。产出 = 各任务按难度折算的标准工时 × 结果分 × 价值系数（高 1.5 / 中 1.0 / 低 0.5），未提交记 0；≈1 与基准持平"),
    ("leverage", "杠杆", "分钟", True, "Agent 活跃分钟 ÷ 人工交互次数，即人每交互一次换来 Agent 干多久。越高人越省心"),
    ("avoidable_pct", "可避免交互占比", "%", False, "人工交互中本可由 Agent 自己处理的比例（逐项指挥、催进度、输出形式反复、替 Agent 实测等）。越低越好"),
)

RUBRIC = """## 评分规则
拆任务：会话里人提出的、能独立验收的一件事算一个任务；追问、改格式、换选题不算新任务；同一个交付物不要拆开。
任务难度（四项各 1–3）：
- scale 规模：单文件 / 单个产物 1，多模块或多个产物 2，跨系统或大量用例 3
- uncertainty 不确定性：方案明确 1，要比较几个方案 2，开放问题、要探索、结果难预知 3
- verify 验证难度：自动测试即可 1，要实测 / 渲染 2，要真实链路、长时间运行或人的判断 3
- cycle 运行周期（按任务性质预估，不看实际耗时）：30 分钟内 1，30 分钟–2 小时 2，2 小时以上或多轮迭代 3
结果分 = 交付档 tier × 反馈系数 feedback。每一步都经过人审核才往下走，走得越远分越高；看东西现在落在哪，不看 Agent 说做完了，没有证据按低档。
- tier 交付档（每个任务各判各的，多组提交取必需部分所在的最低档）：
  - 代码任务：20 未提交或找不到产物；40 本地或功能分支提交、待合并（含已推远程分支、PR 未合）；60 合入本地 main；70 push 到远程 main（PR 合并即算）；85 发布 dev；100 发布线上
  - 非代码任务（调研、测试、方案、规则）：20 未落地；40 只在本地文件；60 发了链接或进了仓库文档；100 人已据此决策或对外发出、规则已生效
  - 可以在会话 cwd 下用只读 git / gh 命令（git log、git branch -a --contains、gh pr view）查提交现在的位置，按最新状态判
  - 调研或测试的结论本身是「不可行 / 有问题」不算失败，按结论落到哪一档算
- feedback 反馈系数（只看人对已交付物要求的修改，提新需求不算）：一次通过 1.0；修改 1 轮或部分完成差距在 10% 以内 0.9；修改 2 轮 0.8；3 轮及以上 0.7；人明确否定、回滚或目标没达到 0.5；部分完成差距超过 10% 按完成比例（约六成 0.6）
- value 价值（按任务服务的目标判，同一目标下的任务同一档）：
  - 高：直接构建、保障或度量产品核心能力，包括为它做的测试、评测和调研；关键技术架构
  - 中：普通功能、提效工具、影响核心链路的故障修复
  - 低：小修、一般 BUG、文档和规则、杂项
人工交互逐条分类（数量相加应等于该会话的人工交互数）：
- 必要：定目标、给约束、审批（关键路径）、验收、只能人做（登录、授权、付费）
- 可避免：推进下一步（逐项指挥 /「继续」）、催进度、形式反复（输出形式来回改）、纠偏返工（本可在需求里写清或 Agent 自查发现）、替Agent实测（人替 Agent 观察结果）
中途主动放弃的会话 abandoned=true，不打分（tasks 可为空）。"""

_JSON = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.S)


def _clip(s: str, n: int) -> str:
    s = re.sub(r"\s+", " ", s or "").strip()
    return s if len(s) <= n else s[:n] + "…"


def scorable(sessions: list[dict]) -> list[dict]:
    """有人参与的会话才评分（脚本会话没有人工交互，杠杆和可避免占比无意义）。"""
    return [s for s in sessions if s.get("human_turns") and not s.get("automated")]


def build_prompt(date: str, sessions: list[dict]) -> str:
    blocks = []
    for s in scorable(sessions):
        lines = [f"### id={s['session_id']} [{s['engine']}] {s['project']} {_clip(s.get('title', ''), 40)} cwd={s.get('cwd', '')} "
                 f"{s['start'][11:16]}–{s['end'][11:16]}，Agent 活跃 {s['active_min']} 分，人工交互 {s['human_turns']} 次"]
        msgs = s.get("messages") or []
        for m in msgs[:30]:
            before = f"（Agent 上一句：{_clip(m.get('agent_before', ''), 120)}）" if m.get("agent_before") else ""
            via = {"queued": "插话", "answer": "回答选择题"}.get(m.get("via", ""), "消息")
            wait = f"等 {m['wait_min']} 分后" if m.get("wait_min") is not None else ""
            lines.append(f"- {m['t']} {wait}{via}{before}：{_clip(m['text'], 200)}")
        if len(msgs) > 30:
            lines.append(f"- …另有 {len(msgs) - 30} 条省略（分类时按前面的比例估计）")
        if s.get("commits"):
            lines.append("提交：" + "；".join(s["commits"][:8]))
        if s.get("links"):
            lines.append("链接：" + " ".join(s["links"][:5]))
        if s.get("tool_errors") or s.get("denials"):
            lines.append(f"工具报错 {s.get('tool_errors', 0)} 次，权限拒绝 {s.get('denials', 0)} 次")
        lines.append("Agent 最后一条回复：" + (_clip(s.get("final", ""), 600) or "（无）"))
        blocks.append("\n".join(lines))
    return f"""请给 {date} 的 Claude Code / Codex 交互会话打分，用于 Agent 看板的核心指标。只读分析：不要修改文件或平台数据，不要运行测试或启动服务；除了查交付档的只读 git / gh 命令，只根据下面的素材判断，没有证据的按低档打分，不要推测为完成。

{RUBRIC}

## 会话素材（人工消息：时间、等待、类型、紧挨着的 Agent 上一句、内容；已截断）
{chr(10).join(blocks) or '（无交互会话）'}

## 输出
先用几行文字说明最值得注意的发现（哪类可避免交互最多、哪个会话结果最差及原因），然后**最后**输出一个 ```json 代码块，每个会话一项，id 原样照抄：
```json
{{"sessions": [{{"id": "<会话 id>", "abandoned": false,
  "tasks": [{{"title": "一句话，可独立验收", "scale": 2, "uncertainty": 2, "verify": 2, "cycle": 1,
             "tier": 70, "feedback": 0.9, "value": "中", "why": "一句话：交付档、修改轮次和价值的依据"}}],
  "necessary": {{"定目标": 1, "给约束": 0, "审批": 1, "验收": 1, "只能人做": 0}},
  "avoidable": {{"推进下一步": 1, "催进度": 0, "形式反复": 0, "纠偏返工": 1, "替Agent实测": 0}},
  "note": "一句话：结果如何、最该改进什么"}}]}}
```"""


def _int(v, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(round(float(v)))))
    except (TypeError, ValueError):
        return lo


def _tier(v) -> int:
    n = _int(v, 0, 100)
    return max([t for t in TIERS if t <= n] or [TIERS[0]])


def _feedback(v) -> float:
    try:
        return round(max(0.5, min(1.0, float(v))), 2)
    except (TypeError, ValueError):
        return 0.5


def current(scores: dict) -> dict[str, dict]:
    """存下的评分只认当前评分规则版本；旧规则的评分当作未评分，等重新评分。"""
    return (scores or {}).get("by_session") or {} if (scores or {}).get("rubric") == RUBRIC_VERSION else {}


def parse(text: str, sessions: list[dict]) -> dict[str, dict]:
    """从 Agent 输出里取最后一个 JSON 块，只留认识的会话 id；分数截到合法范围，可避免数不超过人工交互数。"""
    blocks = _JSON.findall(text or "")
    raw = None
    for b in reversed(blocks):
        try:
            raw = json.loads(b)
            break
        except json.JSONDecodeError:
            continue
    if raw is None:
        i, j = (text or "").find("{"), (text or "").rfind("}")
        try:
            raw = json.loads(text[i:j + 1]) if i >= 0 < j else None
        except json.JSONDecodeError:
            raw = None
    if not isinstance(raw, dict):
        return {}
    turns = {s["session_id"]: s.get("human_turns", 0) for s in sessions}
    out: dict[str, dict] = {}
    for x in raw.get("sessions") or []:
        if not isinstance(x, dict) or str(x.get("id")) not in turns:
            continue
        sid = str(x["id"])
        tasks = []
        for t in x.get("tasks") or []:
            if not isinstance(t, dict):
                continue
            d = {k: _int(t.get(k), 1, 3) for k in ("scale", "uncertainty", "verify", "cycle")}
            tasks.append({"title": _clip(str(t.get("title") or ""), 80), **d,
                          "tier": _tier(t.get("tier")), "feedback": _feedback(t.get("feedback")),
                          "value": t.get("value") if t.get("value") in VALUE else "中", "why": _clip(str(t.get("why") or ""), 160)})
        av = {k: _int((x.get("avoidable") or {}).get(k), 0, 999) for k in AVOIDABLE}
        ne = {k: _int((x.get("necessary") or {}).get(k), 0, 999) for k in NECESSARY}
        over = sum(av.values()) - turns[sid]
        for k in reversed(AVOIDABLE):   # 模型数多了：从最后一类往前扣，总数不超过人工交互
            cut = min(av[k], max(0, over))
            av[k] -= cut
            over -= cut
        out[sid] = {"abandoned": bool(x.get("abandoned")), "tasks": tasks, "avoidable": av, "necessary": ne,
                    "note": _clip(str(x.get("note") or ""), 200)}
    return out


def _task_calc(t: dict) -> dict:
    diff = t["scale"] + t["uncertainty"] + t["verify"] + t["cycle"]
    score = round(t["tier"] * t["feedback"])
    std = STD_HOURS[diff]
    out = 0 if t["tier"] == TIERS[0] else std * t["tier"] * t["feedback"] / 100 * VALUE[t["value"]][0]
    return {**t, "difficulty": diff, "score": score, "std_h": std, "output": out, "output_h": round(out, 2),
            "value_score": VALUE[t["value"]][1]}


def compute(scores: dict[str, dict], sessions: list[dict]) -> dict:
    """每个会话：结果分（标准工时加权）、难度、产出、吞吐、可避免占比；当天：四个核心指标。"""
    rows, std_sum, out_sum, active_sum, turns_sum, avoid_sum, lev_active, lev_turns = [], 0.0, 0.0, 0.0, 0, 0, 0.0, 0
    score_sum = value_sum = 0.0
    for s in scorable(sessions):
        lev_active += s["active_min"]
        lev_turns += s["human_turns"]
        sc = scores.get(s["session_id"])
        if not sc:
            continue
        tasks = [_task_calc(t) for t in sc["tasks"]] if not sc["abandoned"] else []
        std = sum(t["std_h"] for t in tasks)
        out = sum(t["output"] for t in tasks)
        weighted = sum(t["std_h"] * t["tier"] * t["feedback"] for t in tasks)
        value = sum(t["std_h"] * t["value_score"] for t in tasks)
        avoid = sum(sc["avoidable"].values())
        result = round(weighted / std) if std else None
        rows.append({
            "session_id": s["session_id"], "engine": s["engine"], "project": s["project"], "title": s.get("title", ""),
            "start": s["start"], "end": s["end"], "active_min": s["active_min"], "human_turns": s["human_turns"],
            "leverage_min": s.get("leverage_min"), "wait_p90_min": s.get("wait_p90_min"),
            "abandoned": sc["abandoned"], "tasks": tasks, "avoidable": sc["avoidable"], "necessary": sc["necessary"],
            "note": sc["note"], "result": result,
            "status": "⏸" if sc["abandoned"] else ("❌" if result is None or result < 50 else "🟡" if result < 80 else "✅"),
            "difficulty": round(sum(t["difficulty"] * t["std_h"] for t in tasks) / std) if std else None,
            "output_h": round(out, 2), "value_score": round(value / std) if std else None,
            "throughput": round(out / (s["active_min"] / 60), 2) if out and s["active_min"] else None,
            "avoidable_n": avoid, "avoidable_pct": round(avoid / s["human_turns"] * 100) if s["human_turns"] else None,
        })
        if not sc["abandoned"]:
            std_sum += std
            out_sum += out
            score_sum += weighted
            value_sum += value
            active_sum += s["active_min"]
        turns_sum += s["human_turns"]
        avoid_sum += avoid
    by_type = {k: sum(r["avoidable"][k] for r in rows) for k in AVOIDABLE}
    core = {
        "result": round(score_sum / std_sum) if std_sum else None,
        "throughput": round(out_sum / (active_sum / 60), 2) if out_sum and active_sum else None,
        "leverage": round(lev_active / lev_turns, 1) if lev_turns else None,
        "avoidable_pct": round(avoid_sum / turns_sum * 100) if turns_sum else None,
    }
    return {"core": core, "sessions": rows, "avoidable_by_type": by_type,
            "output_h": round(out_sum, 2), "value_score": round(value_sum / std_sum) if std_sum else None, "active_h": round(active_sum / 60, 2), "human_turns": turns_sum,
            "avoidable_n": avoid_sum, "scored": len(rows), "scorable": len(scorable(sessions)),
            "counts": {k: sum(1 for r in rows if r["status"] == k) for k in ("✅", "🟡", "❌", "⏸")}}
