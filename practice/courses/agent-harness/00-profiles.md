# 0 开课：模型 + harness，各管什么
<!-- minutes: 20 -->
<!-- know: Agent Harness, profile, 插件组合, DSH_HOME -->

同一个模型，套不同的外壳，表现能差很多。这门课把「外壳」——harness——拆开来看：它决定模型每一步能看到什么、能做什么、做错了谁来拦、做完了谁来判。
主线用 [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness)（下称 dsh，MIT 协议，TypeScript）。它的设计是「一切皆插件」：循环、工具、压缩、权限、记忆入口、子 Agent 都是可以单独换掉的包，正好适合一层层拆。课程页面通过官方 Python SDK `deepseek-harness-sdk` 驱动它，SDK 自带打包好的运行时，不需要装 Node。

这一课回答一个问题：**一个 harness 至少要有什么，多出来的部分值多少？** 做法是同一道题分别交给 dsh 的两个 profile 跑：
- `sdk-minimal`：只有文件和 shell 工具、最基本的压缩；
- `sdk`：dsh 的完整默认组合（子 Agent、计划、目标、技能、网页、审批、沙箱……）。

> 先补背景：**profile** 是 dsh 的一份「插件清单 + 配置」，启动时按层叠加：内置模板 → 你在 `DSH_HOME/profiles/<名字>/` 里的用户层 → 命令行 `--patch` 传入的覆盖文件。**DSH_HOME** 是会话、配置和插件的存放目录，SDK 要求显式给出，绝不碰你自己的 `~/.dsh`。

## 检查环境和花费上限
这门课调真实的 DeepSeek API（模型 `deepseek-v4-flash`），按每次调用返回的真实 token 数记账：单格超过 2 元、整门课超过 60 元就自动中止。价格按高峰价算（缓存命中 0.014、未命中 0.44、输出 1.32 美元 / 百万 token，汇率按 7.2），宁可多记。

```python
import importlib.metadata as md, os
import harness_lab as lab
ss.kv({"SDK": md.version("deepseek-harness-sdk"), "运行时": md.version("deepseek-harness-runtime-bin"),
       "DeepSeek key": "已配置" if os.environ.get("DEEPSEEK_API_KEY") else "没有（在平台 .env 里加 DEEPSEEK_API_KEY）",
       "dsh 源码（当前目录）": os.path.basename(os.getcwd()), "练习目录": str(ss.DSH)}, "环境")
ss.spent()
```

## 两个 profile 各装了什么
`--dump-config` 打印组合后的完整插件树，不启动 agent。数一数两边的插件，看完整版多出了哪些。

```python
mini, full = lab.dump("sdk-minimal"), lab.dump("sdk")
only_full = sorted({r[1] for r in full if not r[2]} - {r[1] for r in mini})
ss.kv({"sdk-minimal 插件数": len(mini), "sdk 插件数（不含禁用）": sum(not r[2] for r in full), "sdk 里被禁用的": ", ".join(r[0] for r in full if r[2])}, "组合规模")
ss.table([[n.replace("@deepseek-ai/dsh-", "")] for n in only_full], ["只在 sdk 里的包"], f"多出来的 {len(only_full)} 个包")
```

读表要点：多出来的包大致分几类——编排（subagent、team、workflow、goal、plan-mode、todo）、上下文（skill、agent-instructions、spill、tool-result-pruner）、边界（sandbox-policy、approval、permission）、观测（session-query-sqlite、otel、feedback）。后面每一课拆其中一类。

## 同一道题，两个 profile 各跑一次
练习场 `harness_lab` 里有个小项目 textkit 和 10 道能自动判分的题。判分只看结果：在工作区的一份拷贝里跑隐藏检查，再核对项目约定（CONTRIBUTING.md 要求每次改动记 CHANGELOG、不许改已有测试）。agent 说「修好了」不算数。

```python
rows = []
for prof in ("sdk-minimal", "sdk"):
    r = lab.run("slug-lower", tag=prof, profile=prof, show=True)
    rows.append([prof, "✓" if r["ok"] else "✗", r["why"], r["steps"], r["tools"], r["in"], r["cost"], r["secs"]])
ss.table(rows, ["profile", "通过", "判分", "模型调用", "工具调用", "输入 token", "花费（元）", "秒"], "slug-lower：同一模型，两种外壳")
```

> 思考：完整版每次请求多带了上万 token 的系统提示和工具定义，它换来了什么？这道题上值不值？什么样的任务上才值？

## 模型实际看到的「外壳」
把两次运行的第一次请求拆开：提供了哪些工具、系统提示多长。这就是 harness 塞进模型上下文的东西。

```python
runs = {p: lab.run("slug-lower", tag=p + "-peek", profile=p)["run"] for p in ("sdk-minimal", "sdk")}
ss.table([[p, len(lab.offered(r)), len(lab.system_prompt(r)), ", ".join(lab.offered(r)[:12]) + (" …" if len(lab.offered(r)) > 12 else "")] for p, r in runs.items()],
         ["profile", "工具数", "系统提示字符数", "工具"], "第一次请求里的外壳")
ss.compare("sdk-minimal 系统提示（开头）", lab.system_prompt(runs["sdk-minimal"])[:1500], "sdk 系统提示（开头）", lab.system_prompt(runs["sdk"])[:1500])
```

> 思考：learn-claude-code 把 Agent 概括成「模型 + harness」，harness 只有几百行也能干活。dsh 有五十多个包。哪些是「没有就不能用」，哪些是「没有会出事」，哪些是「锦上添花」？把上面多出来的包各归一类。

## 对照与坑
- 对照：[learn-claude-code](https://github.com/shareAI-lab/learn-claude-code) 的 s01（30 行循环）；[dsh-handbook](https://github.com/Electricitysheep/dsh-handbook) 第 1–2 章（中文讲解，基于 0.1.x，命令以 0.2.x 为准）。
- 坑：不同 profile 的会话存储格式不同（sdk-minimal 写 `.jsonl`，sdk 写 zstd 压缩），同一个 DSH_HOME 混用会报 `uses .jsonl, but this backend is configured for compression "zstd"`。练习场按 profile 分开放 home。
- 坑：用户全局指令默认读 `$DSH_HOME/AGENTS.md` 和 `~/.agents/AGENTS.md`，skill 也会扫 `~/.agents/skills`——你本机给别的 agent 写的规则会混进实验。`ss.harness` 默认把 `DSH_AGENTS_HOME` 指到练习目录里的空目录。
- 坑：同一个 DSH_HOME 里会话 id 不能重复，否则 `session already exists`；`ss.agent` 默认用毫秒时间戳当 id。
