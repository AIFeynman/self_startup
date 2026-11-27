# 1 循环：一轮里到底发生了什么
<!-- minutes: 30 -->
<!-- know: Agent 循环, ReAct, 工具调用, inbox, 终止条件 -->

所有 coding agent 的骨架都是同一个循环：请求模型 → 模型要么回答、要么要调工具 → 执行工具、把结果塞回去 → 再请求，直到模型不再要工具。这一课先在 dsh 的源码里找到这个循环，再订阅它运行时发出的事件，把一轮拆成一步一步看。

## 源码里的循环
dsh 的循环在 `packages/core/agent-loop/src/agent.ts` 的 `ReactLoopAgent`。`kick()` 一直调 `turn()`，一个 turn 里反复调 `step()`；每一步：准备请求 → 流式读模型输出 → 交给工具执行器 → 结果回填。

```python
import harness_lab as lab, json, time
P = "packages/core/agent-loop/src/agent.ts"
lab.src(P, "private async kick", 12, "kick：有活就一直转")
lab.src(P, "private async turn", 40, "turn：一轮里循环多步，直到这一步不再需要继续")
```

> 先补背景：dsh 把一次用户输入叫一个 **turn**，turn 里每请求一次模型叫一个 **step**。用户的新消息先进 **inbox**（收件箱），在下一个 step 开始前「拼接」进上下文，事件名 `agent/inbox/spliced`。所以运行中插的话不会打断当前这步，而是在下一步生效。

## 订阅事件，画出一轮
`ss.agent` 订阅 SDK 的 `session.event` 通知，边跑边画轨迹。跑完我们按事件类型数一数，再把每一步的 token 和缓存命中列出来。

```python
r = lab.run("chunks-tail", tag="loop", show=True)["run"]
from collections import Counter
ss.bars(dict(Counter(e["type"] for e in r.events).most_common(14)), "这一轮发出的事件（按类型计数）")
rows, step = [], 0
for e in r.events:
    if e["type"] == "assistant/message" and e["data"].get("usage"):
        u, step = e["data"]["usage"], step + 1
        calls = [c["name"] for c in e["data"]["message"]["content"] if c.get("type") == "tool-call"]
        rows.append([step, " ".join(calls) or "（回答）", u["inputTokens"], u["cacheReadTokens"], u["outputTokens"], f"{ss.cost_of(u):.4f}"])
ss.table(rows, ["step", "要调的工具", "输入（未命中）", "输入（命中缓存）", "输出", "元"], "每一步")
r.summary()
```

读表要点：第一步几乎全是「未命中」——系统提示和工具定义第一次发给服务端；从第二步起绝大部分输入命中缓存，因为前缀没变，只是在末尾追加了上一步的工具结果。第 3 课专门讲这件事。

## 运行中插一句话
给一个需要好几步的任务，在第 2 步结束时插话改需求，看它从哪一步开始照新要求做。

```python
h = ss.harness(lab.workspace("cli-upper", "steer"))
sid = f"steer{int(__import__('time').time())}"
said = []
def at_step2(e, run, h):
    if e["type"] == "step/end" and e["data"].get("step") == 2 and not said:
        said.append(1)
        lab.steer(h, sid, "补充要求：upper 子命令之外，再加一个 lower 子命令，输出小写。")
r = ss.agent(lab.BY_ID["cli-upper"].prompt, h=h, session=sid, on_event=at_step2, title="中途插话")
h.close()
spliced = [e["data"].get("turn") for e in r.events if e["type"] == "agent/inbox/spliced" and e["data"].get("inserted")]
ss.kv({"插话被拼进上下文的次数": len(spliced), "最终是否加了 lower": "lower" in (lab.ss.DSH / "ws/steer-cli-upper/textkit/cli.py").read_text()}, "插话生效了吗")
```

> 思考：插话进 inbox、下一步才生效，而不是立刻打断当前工具调用。这样设计的好处和代价各是什么？如果当前一步是一条要跑 10 分钟的命令呢？

## 结束原因
一轮结束时 `turn/end` 事件带原因。常见的是 `completed`（模型不再调工具）；被中止、出错、预算用完会是别的值。`ss.agent` 把它放在 `run.reason`。

```python
ends = [(e["data"].get("turn"), e["data"].get("reason")) for e in r.events if e["type"] == "turn/end"]
ss.table([[t, str(x)] for t, x in ends], ["turn", "reason"], "turn/end 事件")
```

## 对照与坑
- 对照：learn-claude-code [s01](https://github.com/shareAI-lab/learn-claude-code) 的 30 行循环：`while True: resp = llm(...); if no tool_use: break; run tools; append results`。把它的每一行对到上面的事件上：请求 = `request/header`，回复 = `assistant/message`，执行 = `tool/call`/`tool/result`，退出 = `turn/end`。
- 坑：SDK 的通知对象字段是 `.method` 和 `.payload`（不是 `.params`）；事件在 `payload["event"]`，usage 在 `assistant/message` 的 `data.usage`，其中 `inputTokens` **不含**缓存命中部分。
- 坑：SDK 没有「取消运行」的接口，要中止只能关掉 harness（`ss.agent` 超预算时就是这样做的）。
