# 14 提议与写回：一次失败该改哪一层
<!-- minutes: 40 -->
<!-- know: Harness 写回, AGENTS.md vs skill, 单变量实验, ACE playbook -->

同一个失败可以有好几种改法：加一行 AGENTS.md、写一个 skill、记一条记忆、改工具说明、加一个钩子、或改编排。《Know-how 地图》把可被进化的对象分成 7 层：常驻指令、技能、记忆、工具、确定性约束、流程编排、尺子。层与层的差别在三个轴上：**每一步都付钱还是按需付**（常驻指令每步都在上下文里，skill 用到才加载）；**靠自觉还是强制**（规则靠模型听，钩子不靠）；**多容易腐烂**（规则越积越多会互相矛盾，钩子要维护代码）。

这一课回答：**改哪层最划算？** 做法是单变量实验：每次只改一处，用第 12 课的尺子量。

## 候选改动
针对第 13 课最常见的两类失败（没读到约定、过早完成），各在两层上做一个改动：

```python
import harness_lab as lab, json, time
assert "diags" in globals(), "这一课用到前面的结果：先按顺序跑第 12 课的基线和第 13 课的诊断"
CANDIDATES = {
    "规则：记 CHANGELOG": {"layer": "rule", "content": "每次改动代码后，在 CHANGELOG.md 的「## 未发布」下加一行 `- <改了什么>`；跑测试用 python -m unittest discover -s tests。"},
    "skill：项目约定": {"layer": "skill", "name": "textkit-conventions", "content": "# textkit 约定\n1. 改代码后在 CHANGELOG.md「## 未发布」下记一行。\n2. 测试命令：python -m unittest discover -s tests（没有 pytest）。\n3. 不改 tests/ 里已有的测试。\n4. 新公开函数写 docstring。\n"},
    "规则：收工前自检": {"layer": "rule", "content": "宣布完成前逐条核对 CONTRIBUTING.md 的约定，并实际运行测试。"},
    "钩子：Stop 闸门": {"layer": "stop", "content": "changelog"},
}
ss.table([[k, v["layer"], v["content"][:90]] for k, v in CANDIDATES.items()], ["改动", "层", "内容"], "四个单变量改动")
print(lab.install("@deepseek-ai/dsh-hooks-claude-code@0.2.2-rc.2"))
```

## 每个改动单独量
每个改动只在基线上加这一处，训练集各跑 1 遍（4 × 5 次运行）。和第 12 课的基线做配对比较，并对照噪声线。

```python
results = {}
for name in list(CANDIDATES)[:2]:
    cfg = lab.apply_change(BASE, CANDIDATES[name])
    results[name] = lab.evaluate(cfg, lab.TRAIN, "cand-" + str(len(results)), title=name)
```

```python
for name in list(CANDIDATES)[2:]:
    cfg = lab.apply_change(BASE, CANDIDATES[name])
    results[name] = lab.evaluate(cfg, lab.TRAIN, "cand-" + str(len(results)), title=name)
nl = lab.noise(base_rows)["最高-最低"]
base_rate = lab.score(base_rows)["通过率"]
ss.table([[k, lab.score(v)["通过率"], round(lab.score(v)["通过率"] - base_rate, 3), "超过" if lab.score(v)["通过率"] - base_rate > nl else "没超过",
           lab.paired(base_rows, v)["B 更好"], lab.paired(base_rows, v)["B 更差"], lab.score(v)["平均花费（元）"]] for k, v in results.items()],
         ["改动", "通过率", "比基线", f"噪声线 {nl}", "更好的题", "更差的题", "平均花费"], "单变量实验")
```

> 思考：「规则」和「skill」写的是同一份约定，差别在于常驻还是按需。哪个通过率高？skill 有没有真的被加载（去轨迹里找 `skill` 工具调用）？如果 agent 根本没意识到要去读 skill，按需加载就等于没有——这是 skill 这一层最常见的失败。

## ACE：把经验写成会进化的 playbook
[ACE](https://arxiv.org/abs/2510.04618) 的做法是三个角色：生成者做任务，反思者从轨迹里提炼经验，整理者把经验**增量**合并进 playbook（加条目、改条目、删条目，而不是整篇重写，避免「上下文坍缩」——反复重写后细节被概括掉）。这里用本机 Claude 当反思者和整理者，把第 13 课的诊断写成 skill 文件。

```python
playbook = []
for r, d in diags[:6]:
    reflect = ss.llm("从这次失败里提炼一条以后能直接照做的经验（一句话，祈使句，具体到命令或文件）。只输出这句话。\n\n诊断：" + str(d) + "\n\n轨迹：\n" + lab.brief(r, 2000))
    curate = ss.llm("现有 playbook：\n" + "\n".join(f"{i}. {x}" for i, x in enumerate(playbook)) + f"\n\n新经验：{reflect.strip()}\n\n"
                    "决定怎么合并，只输出 JSON：{\"op\": \"add\"|\"merge\"|\"skip\", \"index\": 要合并的条目编号或 null, \"text\": 合并后的条目}")
    try:
        c = lab.parse_json(curate)
    except Exception:
        c = {"op": "add", "text": reflect.strip()}
    if c.get("op") == "add":
        playbook.append(c["text"])
    elif c.get("op") == "merge" and isinstance(c.get("index"), int) and c["index"] < len(playbook):
        playbook[c["index"]] = c["text"]
ss.table([[i + 1, x] for i, x in enumerate(playbook)], ["#", "条目"], "整理后的 playbook")
PLAYBOOK = {"layer": "skill", "name": "textkit-playbook", "content": "# textkit playbook\n" + "".join(f"- {x}\n" for x in playbook)}
```

## 对照与坑
- 对照：《Know-how 地图》「7 层对象」与 E（改哪层）、F（常驻上下文与记忆）两类问题；ACE。
- 坑：一次只改一处。两处一起改、分数涨了，你不知道是哪一处的功劳，也不知道另一处是不是在拖后腿。
- 坑：每个改动都要挂上证据（来自哪几条失败、量出来的数字），第 16 课退役规则时要用。
