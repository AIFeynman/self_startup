# 9 子 Agent、团队与 workflow：把活分出去
<!-- minutes: 35 -->
<!-- know: 子 Agent, 上下文隔离, Agent team, workflow -->

一个 agent 读二十个文件，二十份内容都堆在它的上下文里，后面每一步都要为它们付钱，还会把注意力冲散。**子 Agent** 的核心价值不是「并行」，而是**上下文隔离**：子 agent 在自己的上下文里读完、只把结论交回来，主 agent 的上下文只多了几百字。代价是：子 agent 看不到主 agent 知道的东西，交回的结论可能丢细节；总 token 往往更多。

dsh 给了三个层次：
- `subagent` / `subagent_fork` 工具：主 agent 临时派一个（fork 会继承主会话的上下文）；
- `agent-team`：多个长期存在的 agent 互发消息（`send_message`、`list_agents`）；
- `workflow`：用程序写死编排（谁先谁后、扇出几个），不让模型临场决定怎么拆。

## 一个要读很多文件的调研任务
在 dsh 源码里（只读模式）调研：`packages/compaction` 下每个包各管什么、彼此怎么配合。单 agent 自己读 vs 要求它把每个包派给一个子 agent。比主上下文的峰值、总花费、耗时。

```python
import harness_lab as lab, json, time
import os
Q = "调研 packages/compaction 目录：下面每个包各管什么、在什么时机起作用、彼此怎么配合。读各包的 README.zh.md 和 src/index.ts，最后用一张表总结。不要修改任何文件。"
ways = [("单 agent", Q), ("委托子 agent", Q + "\n要求：每个包交给一个 subagent 去读，你只汇总它们交回的结论。")]
rows, answers = [], {}
for name, prompt in ways:
    r = ss.agent(prompt, os.getcwd(), env={"DSH_PERMISSION_MODE": "read-only"}, approve=lambda t, why: False, title=name, quiet_tools=True)
    peak = max(u["inputTokens"] + u["cacheReadTokens"] for u in r.usage)
    sub = sum(u["inputTokens"] + u["cacheReadTokens"] for u in r.sub_usage)
    rows.append([name, len(r.usage), peak, len(r.sub_usage), sub, f"{r.cost:.4f}", round(r.seconds)])
    answers[name] = r.final
ss.table(rows, ["方式", "主会话调用", "主上下文峰值 token", "子会话调用", "子会话输入 token", "总花费（元）", "秒"], "上下文隔离的账")
ss.compare("单 agent 的结论", answers["单 agent"][:2000], "委托子 agent 的结论", answers["委托子 agent"][:2000])
```

> 思考：哪份结论更准？逐条对一下 `packages/compaction/README.zh.md` 里的官方说法。如果委托版丢了细节，丢在哪一环——子 agent 没读到，还是交回结论时被压缩掉了？

## 让程序决定怎么拆：workflow
`workflow` 工具让模型写一段固定的编排程序（底层跑在 PTC 运行时上）：例如「对每个包并行派一个子 agent，全部完成后汇总」。比较它和让模型临场决定。

```python
r = ss.agent(Q + "\n要求：用 workflow 工具写一个固定流程——对 packages/compaction 下的每个子目录并行派一个 agent 读，全部完成后再汇总。",
             os.getcwd(), env={"DSH_PERMISSION_MODE": "read-only"}, approve=lambda t, why: False, title="workflow", quiet_tools=True)
wf = [c for c in r.calls if c["name"] == "workflow"]
ss.kv({"调用 workflow 次数": len(wf), "子会话调用": len(r.sub_usage), "花费（元）": f"{r.cost:.4f}"}, "workflow")
if wf:
    ss.show("table", title="模型写的编排程序（参数开头）", cols=["参数"], rows=[[wf[0]["arguments"][:1500]]])
```

## 对照与坑
- 源码：`packages/subagent/subagent`、`packages/subagent/subagent-fork-in-process`、`packages/team/agent-team`、`packages/workflow/workflow-ptc`。
- 对照：learn-claude-code s06（子 agent）、s13（团队）、s16（workflow）；Anthropic《How we built our multi-agent research system》：多 agent 总 token 约为单 agent 的 15 倍，换来的是广度任务上的质量（厂商自报）。
- 坑：子 agent 的 token 记在**子会话**上，只看主会话的 usage 会严重低估花费——`ss.agent` 已把子会话的调用一并记账（`run.sub_usage`）。
- 坑：fork 型子 agent 继承主会话全部上下文，隔离效果最差；要隔离就用普通 subagent 并把任务写完整。
