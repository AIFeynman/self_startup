# 4 上下文满了：大输出转存与压缩
<!-- minutes: 40 -->
<!-- know: 上下文压缩, 工具结果截断, spill, 约束遗忘 -->

上下文窗口再大也会满，而且远没满时就已经又贵又慢。dsh 有三道防线，作用在不同时机：
- **spill**（`spill-policy`）：单个工具结果太大时，正文转存到文件，上下文里只留开头、提示和取回方式；
- **tool-result-pruner**：旧的、长的工具结果在后续请求里被剪成「头 4096 字 + 尾 1024 字」；
- **compaction-basic**：整个对话接近阈值时，把早期历史总结成一段摘要，只逐字保留最近一部分。

前两道只动工具结果，第三道会改写你说过的话。所以这一课的重点是：**压缩之后，早先定下的规矩还在不在？**

## 一个 200KB 的日志
工作区放一个 200KB 的日志，只有一行以 `ERROR` 开头。看模型拿到的工具结果有多大、是否被转存。

```python
import harness_lab as lab, json, time
import random
random.seed(0)
log = "\n".join(f"INFO {i} " + "".join(random.choices("abcdef0123456789", k=60)) for i in range(3000))
lines = log.split("\n"); lines[2222] = "ERROR disk quota exceeded on /var/data"; log = "\n".join(lines) + "\n"
ws = ss.workspace("spill", {"big.log": log})
r = ss.agent("用 cat 把 big.log 整个打出来，然后告诉我以 ERROR 开头的那一行是什么。", ws, title="cat 一个 200KB 的文件")
for e in r.of("tool/result")[:3]:
    t = ss._text(e["data"]["message"]["content"])
    ss.kv({"模型看到的长度（字符）": len(t), "原文件（字符）": len(log), "开头": t[:160], "结尾": t[-300:]}, "一次工具结果")
ss.kv({"答对了吗": "disk quota" in r.final, "最终回答": r.final[:300]}, "结果")
```

> 思考：转存后模型怎么找到那一行——它是重新 grep，还是去读转存文件？哪种更省？sdk 里 `maxInlineTokens: 12500`，调小到 2000 会怎样？

## 手动压缩一次，看规矩丢没丢
同一个会话：第一句话定三条规矩，接着聊几轮无关的事把历史拉长，然后用 `/compact` 命令强制压缩，压缩前后各问一次「我给你定了哪些规矩」。

```python
import time
h = ss.harness(ss.workspace("compact", lab.project()))
sid = f"compact{int(time.time())}"
ask = lambda q, t: ss.agent(q, h=h, session=sid, title=t, show=False)
ask("这个会话的三条规矩：1) 不许修改 tests/ 目录；2) 每次回答第一句是结论；3) 金额一律用人民币。记住它们，回复「好」。", "定规矩")
for q in ("读一下 textkit/core.py，逐个函数解释一遍。", "再读 textkit/cli.py 和 CONTRIBUTING.md，总结约定。", "列出 textkit 可以改进的 5 个地方，每条写理由。"):
    ask(q, "拉长历史")
before = ask("不用工具：我在这个会话开头给你定了哪些规矩？逐条列出原文。", "压缩前")
c = ask("/compact", "压缩")
after = ask("不用工具：我在这个会话开头给你定了哪些规矩？逐条列出原文。", "压缩后")
h.close()
ss.compare("压缩前", before.final, "压缩后", after.final, "规矩还在吗")
ss.kv({"压缩命令结果": c.reason, "压缩相关事件": sorted({e["type"] for e in c.events if "compact" in e["type"]})}, "压缩")
```

> 思考：如果压缩后某条规矩丢了，责任在哪一层——摘要提示词、保留比例 `retainRatio`，还是「规矩只说了一次、混在对话里」本身？论文 Governance Decay（2026）测的就是这件事：压缩会悄悄抹掉安全约束。你会怎么让关键约束「不怕压缩」？（提示：第 3 课的 AGENTS.md 每步都重新注入，第 7 课的钩子根本不在上下文里。）

## 改压缩参数
用 patch 把自动压缩阈值调得很低（窗口的 3%，约 3 万 token），让一道普通题自然触发自动压缩，看它发生在第几步。

```python
LOW = lab.patch("compact-low", """
- id: compaction-basic
  config:
    thresholdRatio: 0.03
    retainTokens: 4000
""")
x = lab.run("cli-freq", tag="lowcompact", patches=[LOW], show=True)
ss.kv({"判分": x["why"], "模型调用": x["steps"], "压缩事件": [e["type"] for e in x["run"].events if "compact" in e["type"]][:6]}, "阈值调低之后")
```

## 对照与坑
- 源码：`packages/spill/spill-policy`、`packages/compaction/compaction-basic`（阈值公式 `floor(min(W × thresholdRatio, W − O − headroomTokens))`）、`packages/compaction/compaction-tool-result-pruner`。
- 对照：learn-claude-code s08 的四步压缩；dsh-handbook 第 9 章。
- 坑：`retainTokens` 和 `retainRatio` 互斥，且必须小于算出来的阈值，否则启动时报错。
- 坑：工具结果被 pruner 剪掉的部分在会话日志里还在，只是不再发给模型；回放轨迹时别以为模型「看到了」全文。
