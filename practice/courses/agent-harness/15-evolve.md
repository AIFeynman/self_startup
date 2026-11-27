# 15 进化外循环：让 harness 用失败改自己
<!-- minutes: 60 -->
<!-- know: Harness 进化, 外循环, 提议者, 过拟合, 自我改进 -->

前三课的零件拼起来，就是一个进化外循环：

1. 用当前配置跑训练集，收集失败；
2. **提议者**读失败轨迹，提出**一处**改动（加一条规则 / 一个 skill / 一个 Stop 检查）；
3. 在训练集上评测改动后的配置；
4. 比当前最好的配置好过噪声线才接受，否则回滚；
5. 记账：这一轮花了多少。

跑几轮后，在留出集上验证最终配置——这一步决定前面的提升是真的还是刷分。最后比较三种提议者：本机 Claude（外部强模型）、dsh 自己（Self-Harness 式：被改进的 agent 自己提议）、随机改动（对照组，用来回答「是不是随便改改也能涨」）。

这是花钱最多的一课：每轮评测 5 题（约 0.4 元），每个格子跑一轮，不会撞单格 2 元的上限。

## 循环的骨架
```python
import harness_lab as lab, json, time
assert "base_rows" in globals() and "CANDIDATES" in globals(), "先按顺序跑第 12–14 课"
import random
LAYERS_OK = ("rule", "skill", "stop")
def ask_claude(fail_briefs, cfg):
    return lab.parse_json(ss.llm(
        "你在改进一个 coding agent 的 harness 配置。当前配置：\n" + str({"rules": cfg.rules, "skills": list(cfg.skills), "stop_checks": cfg.stop_checks}) +
        "\n可以改的层：rule（往 AGENTS.md 加一条规则）、skill（加一个 skill 文件，content 是 Markdown 正文）、stop（加 Stop 闸门检查，content 只能是 tests 或 changelog）。\n"
        "下面是最近的失败轨迹。只提一处改动，越小越好，针对最常见的失败。只输出 JSON：{\"layer\": ..., \"name\": 可选, \"content\": ..., \"why\": 一句话}\n\n" + "\n\n----\n\n".join(fail_briefs)))
def ask_dsh(fail_briefs, cfg):
    ws = ss.workspace("proposer", {"failures.md": "\n\n----\n\n".join(fail_briefs), "config.json": json.dumps({"rules": cfg.rules, "skills": list(cfg.skills), "stop_checks": cfg.stop_checks}, ensure_ascii=False)})
    r = ss.agent("failures.md 是你自己（同一个 agent harness）最近的失败轨迹，config.json 是当前的 harness 配置。提出一处最小的配置改动来减少这类失败。"
                 "可改的层：rule（AGENTS.md 一条规则）、skill（一个 skill 的 Markdown 正文）、stop（Stop 闸门检查，tests 或 changelog）。"
                 "把改动写成 JSON 存到 proposal.json：{\"layer\": ..., \"name\": 可选, \"content\": ..., \"why\": ...}", ws, title="dsh 给自己提议", quiet_tools=True)
    f = ws / "proposal.json"
    return json.loads(f.read_text()) if f.exists() else {"layer": "none", "why": "没有写出 proposal.json：" + r.final[:80]}
def ask_random(fail_briefs, cfg):
    pool = [v for v in CANDIDATES.values()] + [{"layer": "rule", "content": random.choice(["回答尽量简短。", "优先使用 bash 工具。", "每一步先说明计划。", "修改前先备份文件。"])}]
    return random.choice(pool)
import json
def evolve_round(state, proposer, tag):
    fails = [r for r in state["rows"] if not r["ok"]][:4]
    if not fails:
        ss.note("当前配置在训练集上全过了，没有失败可学。", "info"); return state
    ch = proposer([lab.brief(r, 2500) for r in fails], state["cfg"])
    if ch.get("layer") not in LAYERS_OK:
        ss.note(f"提议的层不合法：{ch}", "warn"); return state
    cand = lab.apply_change(state["cfg"], ch)
    rows = lab.evaluate(cand, lab.TRAIN, tag, title=f"{tag}：{ch['layer']} · {str(ch.get('content'))[:40]}")
    new, old = lab.score(rows)["通过率"], lab.score(state["rows"])["通过率"]
    accept = new - old > state["noise"]
    state["log"].append([tag, ch["layer"], str(ch.get("content"))[:80], ch.get("why", "")[:60], old, new, "接受" if accept else "回滚", round(sum(r["cost"] for r in rows), 3)])
    if accept:
        state.update(cfg=cand, rows=rows)
    ss.table(state["log"], ["轮", "层", "改动", "理由", "原通过率", "新通过率", "结论", "本轮花费"], "进化日志")
    return state
NOISE = max(lab.noise(base_rows)["最高-最低"], 0.1)
first = [r for r in base_rows if r["rep"] == 0]
S_claude = {"cfg": BASE, "rows": first, "noise": NOISE, "log": []}
ss.kv({"接受门槛（噪声线，至少 0.1）": NOISE, "起点通过率": lab.score(first)["通过率"]}, "开跑前")
```

> 先补背景：接受门槛取噪声线（第 12 课量的「最高-最低」，至少 0.1）。门槛太低，噪声会被当成进步一路接受，配置越堆越大；门槛太高，真实的小改进也会被拒。论文 [RRSI](https://arxiv.org/abs/2609.24972) 讨论的就是怎样约束「提议」和「选择」两个环节，防止自我改进退化。

## 本机 Claude 当提议者，跑 3 轮
每格一轮。

```python
S_claude = evolve_round(S_claude, ask_claude, "claude-1")
```

```python
S_claude = evolve_round(S_claude, ask_claude, "claude-2")
```

```python
S_claude = evolve_round(S_claude, ask_claude, "claude-3")
S_claude["cfg"].show("Claude 提议者进化出的配置")
```

## 对照组：dsh 自己提议、随机改动
各跑 2 轮。dsh 自己提议时，它读的是自己的失败轨迹——这就是 Self-Harness 的设定。

```python
S_self = {"cfg": BASE, "rows": first, "noise": NOISE, "log": []}
S_self = evolve_round(S_self, ask_dsh, "self-1")
S_self = evolve_round(S_self, ask_dsh, "self-2")
```

```python
random.seed(7)
S_rand = {"cfg": BASE, "rows": first, "noise": NOISE, "log": []}
S_rand = evolve_round(S_rand, ask_random, "rand-1")
S_rand = evolve_round(S_rand, ask_random, "rand-2")
```

## 留出集上见真章
三条路线各自的最终配置 + 基线，在**从没参与过选择**的留出集上各跑 1 遍。

```python
final = {"基线": BASE, "Claude 提议": S_claude["cfg"], "dsh 自提议": S_self["cfg"], "随机": S_rand["cfg"]}
hold = {}
for k, cfg in final.items():
    if k != "基线" and cfg.size() == 0:
        continue
    hold[k] = lab.evaluate(cfg, lab.HOLDOUT, "hold-" + str(len(hold)), title="留出集 · " + k)
```

```python
spent_evo = {k: round(sum(x[-1] for x in s["log"]), 3) for k, s in (("Claude 提议", S_claude), ("dsh 自提议", S_self), ("随机", S_rand))}
ss.table([[k, final[k].size(), lab.score(base_rows if k == "基线" else ([r for s in (S_claude, S_self, S_rand) if s["cfg"] is final[k] for r in s["rows"]] or base_rows))["通过率"],
           lab.score(v)["通过率"], spent_evo.get(k, 0)] for k, v in hold.items()],
         ["配置", "改动数", "训练集通过率", "留出集通过率", "进化花费（元）"], "训练集 vs 留出集")
ss.spent()
```

> 思考：训练集涨了、留出集没涨的路线，学到的是什么？（看它接受的改动：是不是只对某一道训练题有用的「补丁」？）随机组如果也涨了，说明什么？[The RSI Tax](https://arxiv.org/abs/2611.13524)（2026）提醒：改进本身要花钱，算上进化的花费后，提升还值不值？

## 对照与坑
- 对照：[Meta-Harness](https://arxiv.org/abs/2603.28052)（在 harness 代码上做外循环搜索，提议者读完整的历史轨迹文件系统）；[Self-Harness](https://arxiv.org/abs/2606.09498)（agent 改进自己的 harness）；[HarnessCompass](https://arxiv.org/abs/2608.01918)（5 轮 Pass@1 从 54% 到 66%，论文自报）；RRSI；The RSI Tax。
- 坑：样本很小（训练 5 题 × 1 遍），一次接受可能就是运气。课程里只演示机制；真要用，训练集要大、每轮要重复、门槛要按重复次数调整。
- 坑：进化循环最容易学会「讨好判分器」。这里判分只看隐藏检查和项目约定，改动层也限定在三类，提议者够不着判分器——这是第 12 课防线的用处。
