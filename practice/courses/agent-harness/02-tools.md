# 2 工具：模型看到的，和真正执行的
<!-- minutes: 35 -->
<!-- know: 工具调用, 工具执行器, Programmatic Tool Calling, Code mode, 工具错误恢复 -->

模型并不「执行」工具，它只输出一段「我要调哪个工具、参数是什么」的文字；真正执行、校验参数、处理失败的是 harness 里的**工具执行器**。dsh 有两种执行器：
- `tool-executor-native`（默认）：模型每次调一个或几个工具，一次请求一来一回；
- `tool-executor-ptc`（Programmatic Tool Calling，又叫 Code mode）：只给模型一个 `run_code` 工具，模型写一段程序，在程序里循环调用其他工具，中间结果不回到上下文，只有最终输出回来。

这一课回答：**同样的工具，换一种调用方式，步数和 token 能差多少？工具不顺手时模型会怎么绕？**

## 读执行器的说明
两个执行器同一作用域只能挂一个。看 PTC 的源码入口，注意它怎样给模型生成「SDK」、怎样限制一个程序里的子调用数。

```python
import harness_lab as lab, json, time
lab.src("packages/core/tool-executor-ptc/README.zh.md", "## 概述", 6, "PTC 执行器做什么")
ss.table([[r[0], r[1], "禁用" if r[2] else "启用"] for r in lab.dump("sdk") if "executor" in r[0] or r[0] == "ptc-runtime"], ["id", "包", "状态"], "sdk 里的执行器")
```

## 一个要读很多文件的任务：native vs PTC
任务：统计 textkit 每个 `.py` 文件里的函数个数和行数，写成表。native 执行器下模型通常一个个文件读；PTC 下它可以写一段循环一次做完。

```python
PTC = lab.patch("ptc", """
- id: tool-executor-native
  disabled: true
- id: tool-executor-ptc
  disabled: false
""")
task = "统计 textkit/ 和 tests/ 下每个 .py 文件的函数个数（def 开头的行）和总行数，结果写到 stats.md 的表格里。"
rows = []
for name, patches in (("native", []), ("ptc", [PTC])):
    ws = ss.workspace(f"tools-{name}", lab.project())
    r = ss.agent(task, ws, patches=patches, title=name)
    t = r.tokens()
    rows.append([name, len(r.usage), " ".join(r.tools[:8]), t["inputTokens"] + t["cacheReadTokens"], t["outputTokens"], f"{r.cost:.4f}", round(r.seconds), (ws / "stats.md").exists()])
ss.table(rows, ["执行器", "模型调用", "工具", "输入 token", "输出 token", "元", "秒", "写出 stats.md"], "同一任务，两种执行器")
```

> 思考：PTC 省的是哪一部分 token？如果中间某个文件读出来是 50KB，两种方式下它分别会不会进上下文？PTC 的代价是什么（提示：模型要写对程序，出错时调试信息也更少）？

## 拿掉一个工具，看模型怎么绕
用 patch 关掉 `tool-fs`（读写编辑文件的工具），只留 shell，再做一道修 bug 的题。

```python
NOFS = lab.patch("no-fs", """
- id: tool-fs
  disabled: true
""")
r = lab.run("slug-lower", tag="nofs", patches=[NOFS], show=True)
ss.kv({"判分": r["why"], "用到的工具": " → ".join(r["run"].tools), "模型调用": r["steps"]}, "没有文件工具时")
```

## 工具报错时
让工具报错：工作区里放一个模型会去跑、但一定失败的测试命令说明，看它读到错误后怎么调整。

```python
extra = {"Makefile": "test:\n\tpython -m pytest tests\n"}
r = lab.run("chunks-tail", tag="toolerr", extra=extra, show=True)
errs = [e for e in r["run"].of("tool/result") if e["data"]["message"].get("isError") or "No module named pytest" in ss._text(e["data"]["message"]["content"])]
ss.kv({"判分": r["why"], "出错的工具结果": len(errs), "用到的工具": " → ".join(r["run"].tools)}, "撞到 pytest 不存在之后")
```

> 思考：项目里 CONTRIBUTING.md 写了「本项目不用 pytest」。模型是先读约定再动手，还是先撞墙再回头读？这个差别后面「写回」那一课会用到：一条经验写进哪里，才能让它下次先读到。

## 对照与坑
- 对照：learn-claude-code s02（工具注册表 + 分发）；dsh-handbook 第 8 章；Anthropic 的 Programmatic Tool Calling 与 Cloudflare 的 Code Mode 是同一个思路。
- 坑：在纯 PTC 下，模型直接调程序专用的工具会得到 `UNKNOWN_TOOL`——「通告给模型的」和「能调的」保持一致，这是故意的。
- 坑：`disabled: true` 关掉的是整个插件；只想对模型隐藏某个工具、但保留给别的插件用，要看该插件自己的配置项。
