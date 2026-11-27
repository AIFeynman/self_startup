# 16 闸门、退役与运行中自进化
<!-- minutes: 45 -->
<!-- know: 人工闸门, 规则退役, 消融实验, 运行中自进化, 成熟度 -->

第 15 课的循环会一直往配置里加东西。最后三个问题：**哪些改动可以自动生效、哪些要人批？规则越积越多怎么办？能不能在一次任务里边做边改？**

## 闸门：按风险分级
改动的风险取决于它能做什么：一条 AGENTS.md 规则最坏是让模型多做点事；一个钩子是一段会被执行的程序；一个权限改动会扩大 agent 能碰到的范围。分级规则：

| 层 | 风险 | 闸门 |
|---|---|---|
| 规则、skill | 只影响模型读到的文字 | 过了尺子就自动生效 |
| Stop 检查（我们预置的两种） | 执行固定代码 | 自动生效 |
| 新钩子脚本、权限、工具 | 执行任意代码 / 扩大权限 | 必须人批 |

人批用的就是第 6 课的审批协议思路：把改动摊开给人看，人点了才生效。这里用一个集合模拟「人已批准的改动」。

```python
import harness_lab as lab, json, time
assert "S_claude" in globals(), "先跑第 15 课"
AUTO = {"rule", "skill", "stop"}
HUMAN_APPROVED = set()          # 人审过的改动写在这里，例如 HUMAN_APPROVED.add("hook:check_docstring")
def gate(ch):
    kind = ch["layer"]
    if kind in AUTO:
        return True, "自动"
    key = f"{kind}:{ch.get('name', '')}"
    return key in HUMAN_APPROVED, "人工" + ("已批" if key in HUMAN_APPROVED else "未批，不生效")
for ch in [{"layer": "rule", "content": "x"}, {"layer": "hook", "name": "check_docstring"}, {"layer": "permission", "name": "danger-full-access"}]:
    print(ch["layer"], gate(ch))
```

## 退役：每条规则还有没有贡献
对进化出的配置做消融：每次去掉一处，在训练集上重跑。去掉后分数不降的，就是可以退役的。

```python
cfg = S_claude["cfg"] if S_claude["cfg"].size() else lab.apply_change(lab.apply_change(BASE, CANDIDATES["规则：记 CHANGELOG"]), CANDIDATES["钩子：Stop 闸门"])
full_rows = lab.evaluate(cfg, lab.TRAIN, "ablate-full", title="完整配置")
items = [("rule", i) for i in range(len(cfg.rules))] + [("skill", k) for k in cfg.skills] + [("stop", c) for c in cfg.stop_checks]
abl = []
for kind, key in items[:3]:
    c = cfg.copy()
    if kind == "rule": label = c.rules.pop(key)
    elif kind == "skill": c.skills.pop(key); label = key
    else: c.stop_checks.remove(key); label = key
    rows = lab.evaluate(c, lab.TRAIN, f"ablate-{len(abl)}", title="去掉 " + str(label)[:30])
    abl.append([kind, str(label)[:60], lab.score(full_rows)["通过率"], lab.score(rows)["通过率"], "可退役" if lab.score(rows)["通过率"] >= lab.score(full_rows)["通过率"] else "保留"])
ss.table(abl, ["层", "改动", "完整配置通过率", "去掉后", "结论"], "消融")
```

> 思考：一次消融只跑 1 遍，同样受噪声影响。规则「去掉后分数不降」可能是因为它真没用，也可能是因为另一条规则覆盖了同样的事（两条规则说同一件事）。实际系统里，退役前还会看触发次数（钩子触发了几次、规则被违反过几次）——第 11 课的会话库就能统计。

## 运行中自进化：让 agent 在任务里给自己建 skill
前面的进化都发生在任务之间。另一条路是让 agent 在任务**进行中**改进自己：允许它把重复做的事写成 skill，后面的任务直接用。同一个工作区连续做三道题，看它有没有建 skill、后面的题有没有用上。

```python
SELF = {"AGENTS.md": "# 给 agent 的说明\n- 如果你发现某个操作在这个项目里会反复用到（比如项目约定、测试命令、常见检查），把它写成一个 skill：.agents/skills/<名字>/SKILL.md，开头 YAML frontmatter 写 name 和 description。以后的任务可以直接用。\n"}
ws = lab.workspace("slug-lower", "live", SELF)
rows = []
for tid in ("slug-lower", "count-words", "cli-upper"):
    t = lab.BY_ID[tid]
    for rel, change in t.seed.items():
        p = ws / rel; old, new = change; p.write_text(p.read_text().replace(old, new, 1))
    r = ss.agent(t.prompt, ws, title="同一工作区 · " + tid)
    ok, why = lab.grade(t, ws)
    skills = sorted(p.parent.name for p in ws.glob(".agents/skills/*/SKILL.md"))
    rows.append([tid, "✓" if ok else "✗", why, len(r.usage), ", ".join(skills) or "无", "skill" in r.tools, f"{r.cost:.4f}"])
ss.table(rows, ["题（按顺序）", "通过", "判分", "模型调用", "此时已有的 skill", "这题用了 skill", "元"], "运行中自建 skill")
```

> 思考：它建的 skill 是帮了忙还是添了乱（后面的题步数少了吗？有没有因为 skill 写错而照着错做）？[Live-SWE-agent](https://arxiv.org/abs/2511.13646) 让 agent 在运行中自建工具，[TTHE](https://arxiv.org/abs/2607.08124)（测试时 harness 进化）指出难点在于：任务中途能拿到的「好不好」的信号（测试过没过、命令报不报错）是否可靠。

## 给自己的配置定级
《Know-how 地图》把 harness 进化的成熟度分成五级。对照这门课搭出来的东西，看自己在哪一级、离下一级缺什么。

```python
ss.table([["L0", "全靠人改，没有记录", "—"],
          ["L1", "有轨迹和反馈的记录，人看了再改", "第 11 课"],
          ["L2", "有可重复的评测，改动要过尺子", "第 12 课"],
          ["L3", "失败自动归因、自动提议，人批准后生效", "第 13–15 课 + 闸门"],
          ["L4", "低风险改动自动生效、自动退役，高风险走人工闸门，持续在留出集上监控", "第 16 课，仍缺持续监控"]],
         ["级别", "特征", "这门课里对应"], "Harness 进化成熟度")
ss.spent()
```

## 课程小结
第一部分把 dsh 一层层拆开：循环和事件、两种工具执行器、上下文和缓存、转存和压缩、外接记忆、沙箱和审批、钩子、计划和目标、子 agent、续跑、观测。第二部分在它上面搭了一个 dsh 自己没有的东西：用尺子量、用诊断者归因、按层写回、外循环进化、按风险过闸、消融退役。

还没人解决好的问题：小样本下怎样可靠地判断「真提升」；进化出的规则怎样避免互相矛盾、越积越乱；运行中自进化的信号怎样不被 agent 自己「做出来」；改进本身的花费什么时候不值。
