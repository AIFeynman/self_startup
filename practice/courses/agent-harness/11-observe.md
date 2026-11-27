# 11 观测：轨迹、会话库与反馈
<!-- minutes: 30 -->
<!-- know: Agent 可观测性, trace, 会话日志, 用户反馈 -->

要改进 harness，先得能回答「它刚才为什么这样做」。dsh 的观测层给了三类原始材料：
- **会话日志**：每个事件都持久化（sdk 下是 zstd 压缩的 JSONL），`session-query` 在它上面提供精确读取和 SQLite FTS5 全文检索；
- **反馈**：`message-feedback` 把好评 / 差评 / 分类 / 备注写进会话日志，**绝不进入模型历史**；
- **遥测**：OpenTelemetry 指标和 span（`session-telemetry-otel`）。

这一课把前面所有课留下的会话当成数据集，做一次「事后分析」。这也是第二部分的起点：信号从这里来。

## 读出所有会话
```python
import harness_lab as lab, json, time
S = lab.sessions()
rows = [[s["home"], s["id"], len(s["events"]), sum(e.get("type") == "tool/call" for e in s["events"])] for s in S]
ss.kv({"会话数": len(S), "事件总数": sum(r[2] for r in rows), "工具调用总数": sum(r[3] for r in rows)}, "练习目录里的全部会话")
ss.table(sorted(rows, key=lambda r: -r[2])[:15], ["home", "会话", "事件数", "工具调用"], "事件最多的 15 个会话")
```

## 每类工具的调用次数、失败率、耗时
`tool/call` 和 `tool/result` 用 `callId` 配对；两者的时间戳差就是工具耗时（含沙箱和审批等待）。

```python
from collections import defaultdict
stat = defaultdict(lambda: {"n": 0, "err": 0, "ms": []})
for s in S:
    t0 = {}
    for e in s["events"]:
        d = e.get("data") or {}
        if e.get("type") == "tool/call":
            t0[d.get("callId")] = (d.get("name"), e.get("time"))
        elif e.get("type") == "tool/result":
            cid = (d.get("message") or {}).get("toolCallId")
            if cid in t0:
                name, t = t0.pop(cid)
                st = stat[name]; st["n"] += 1; st["err"] += bool((d.get("message") or {}).get("isError"))
                if t and e.get("time"): st["ms"].append(e["time"] - t)
rows = [[k, v["n"], v["err"], f"{v['err'] / v['n']:.0%}", round(sorted(v["ms"])[len(v["ms"]) // 2]) if v["ms"] else "-"] for k, v in stat.items()]
ss.table(sorted(rows, key=lambda r: -r[1]), ["工具", "调用", "出错", "出错率", "耗时中位数（毫秒）"], "工具使用画像")
```

> 思考：出错率最高的工具，错误是模型用错了（参数不对、路径不存在）、环境不对（没有 pytest），还是被拦了（沙箱、钩子、审批）？这三种该改的分别是哪一层？第 13 课会让一个诊断 agent 来做这个分类。

## 反馈存在哪、为什么不进模型
在一个会话里用 `/feedback` 记一条差评，然后去日志里找它，再确认之后的请求里没有它。

```python
import time
h = ss.harness(lab.workspace("slug-lower", "fb"))
sid = f"fb{int(time.time())}"
r = ss.agent("把 slugify 修好。", h=h, session=sid, title="先干活", show=False)
fb = ss.agent("/feedback 这次没有更新 CHANGELOG，违反了 CONTRIBUTING.md 的约定", h=h, session=sid, title="记反馈")
r2 = ss.agent("刚才我对你有什么评价吗？不用工具，直接回答。", h=h, session=sid, title="模型知道吗")
h.close()
log = next((s for s in lab.sessions() if s["id"] == sid), {"events": []})["events"]
ss.kv({"反馈命令结果": fb.reason + " · " + fb.final[:120], "日志里的反馈事件": sorted({e["type"] for e in log if "feedback" in e.get("type", "")}),
       "模型的回答": r2.final[:300]}, "反馈的去向")
```

> 思考：「反馈绝不进模型」是故意的——如果差评直接进上下文，模型会学会讨好打分的人，而不是把事做对。那么反馈要怎样才能变成改进？（答案就是第二部分：由 harness 之外的一个循环读反馈、归因、改配置、验证。）

## 把一次失败还原成时间线
从会话库里挑一个判分没过的练习，把它的轨迹画出来，逐步看在哪一步走偏。

```python
pick = [s for s in S if any(e.get("type") == "tool/call" for e in s["events"]) and "stop-" in s["cwd"]] or S
s = pick[0] if pick else {"events": [], "cwd": "（还没有会话：先跑前面几课）", "id": ""}
steps = []
for e in s["events"]:
    d = e.get("data") or {}
    if e.get("type") == "user/message" and (d.get("source") or {}).get("kind") == "user":
        steps.append({"role": "user", "text": ss._text(d.get("content"))[:400]})
    elif e.get("type") == "tool/call":
        steps.append({"role": "thought", "text": f"{d.get('name')} {str(d.get('arguments'))[:300]}"})
    elif e.get("type") == "tool/result":
        steps.append({"role": "tool", "text": ss._text((d.get("message") or {}).get("content"))[:300]})
    elif e.get("type") == "assistant/message":
        t = ss._text((d.get("message") or {}).get("content"))
        if t.strip(): steps.append({"role": "assistant", "text": t[:400]})
ss.trace(steps, f"时间线：{s['cwd'][-40:]} / {s['id']}")
```

## 对照与坑
- 源码：`packages/session-query/session-query-sqlite`（派生索引，不改会话日志）、`packages/feedback/message-feedback`、`packages/session/session-telemetry-otel`。
- 对照：平台《Know-how 地图》B1「trace 怎么记才能拿来归因」；learn-harness-engineering 第 11 讲。
- 坑：会话目录名是工作区路径换成 `-` 的 slug，按任务找会话时用它匹配；同一路径的多次运行都在同一个目录下。
- 坑：sdk 的日志是多帧 zstd，解压要 `read_across_frames=True`，否则只读到第一帧。
