# 3 上下文与缓存：每次喂了什么、花了多少
<!-- minutes: 35 -->
<!-- know: 上下文工程, Prompt 缓存, AGENTS.md, 系统提示 -->

模型没有记忆，每一步都要把「它需要知道的一切」重新发一遍：系统提示、工具定义、项目指令文件、对话历史、工具结果。harness 的上下文层决定发什么、按什么顺序发。顺序直接决定钱：DeepSeek 和大多数服务商都按**前缀**做缓存，前缀和上次一模一样的部分按命中价收费（约为未命中的 3%）。

这一课回答：**一次请求里各部分占多少？什么样的改动会让缓存失效？写进 AGENTS.md 的规则模型会不会听？**

> 先补背景：**前缀缓存**——服务端把最近请求的开头部分存起来，新请求只要开头逐字相同，这部分就不用重算。所以「稳定的放前面、变化的放后面」是 harness 设计的基本约束：系统提示和工具定义在最前，项目指令其次，对话历史在后，每一步只在末尾追加。

## 一次请求按来源拆开
用第一步的真实输入 token 数，按各部分字符数比例分摊（粗估，只看量级）。

```python
import harness_lab as lab, json, time
r = lab.run("slug-lower", tag="ctx")["run"]
first = next(e for e in r.events if e["type"] == "assistant/message" and e["data"].get("usage"))["data"]["usage"]
total = first["inputTokens"] + first["cacheReadTokens"]
parts = {"系统提示": len(lab.system_prompt(r)),
         "工具定义": len(__import__("json").dumps(next(e for e in r.events if e["type"] == "request/header")["data"]["header"]["tools"], ensure_ascii=False))}
for e in r.of("user/message"):
    k = (e["data"].get("source") or {}).get("kind", "user")
    parts[k] = parts.get(k, 0) + len(ss._text(e["data"]["content"]))
scale = total / sum(parts.values())
ss.bars({k: round(v * scale) for k, v in parts.items()}, f"第一步约 {total} 个输入 token 的来源（按字符比例估）", unit=" token")
```

读图要点：真正的任务描述只占一小条。工具定义（31 个工具的 JSON schema）和系统提示是大头——这就是第 0 课里 sdk 比 sdk-minimal 贵的原因，也是 PTC、按需加载工具、skill 这些设计想省的地方。

## 缓存：连跑三次，再故意弄坏前缀
同一道题跑 3 个独立会话，看每个会话第一步的缓存命中；再在 AGENTS.md 里写进当前时间（每次都不同），看命中掉了多少。

```python
import time
def first_hit(r):
    u = next(e for e in r.events if e["type"] == "assistant/message" and e["data"].get("usage"))["data"]["usage"]
    return u["cacheReadTokens"], u["inputTokens"]
rows = []
for i in range(3):
    r = lab.run("count-words", tag=f"cache{i}")["run"]
    rows.append(["前缀不变", i + 1, *first_hit(r), f"{r.cost:.4f}"])
for i in range(2):
    r = lab.run("count-words", tag=f"cachets{i}", extra={"AGENTS.md": f"# 项目说明\n生成时间：{time.time()}\n"})["run"]
    rows.append(["AGENTS.md 含时间戳", i + 1, *first_hit(r), f"{r.cost:.4f}"])
ss.table(rows, ["条件", "第几次", "第一步命中 token", "第一步未命中 token", "整次花费（元）"], "跨会话的前缀缓存")
```

> 思考：时间戳只改了 AGENTS.md 里的一行，为什么命中的部分没有掉到 0？从这个现象推断 dsh 把 AGENTS.md 放在了请求的什么位置。把 learn-harness-engineering 第 4 讲「常驻上下文要限量」和这里的数字对一下：一份 5000 字的 AGENTS.md，每步多花多少？

## AGENTS.md 里的规则，模型听不听
项目约定写在 CONTRIBUTING.md（每次改动记 CHANGELOG），dsh 不会自动读它；AGENTS.md 会被 `agent-instructions` 插件自动放进上下文。同两道题，各跑「没有 AGENTS.md」和「AGENTS.md 里写一条记 CHANGELOG 的规则」。

```python
RULE = {"AGENTS.md": "# 给 agent 的说明\n- 每次改动代码后，在 CHANGELOG.md 的「## 未发布」下面加一行 `- <改了什么>`。\n- 跑测试用 `python -m unittest discover -s tests`，本项目没有 pytest。\n"}
rows = []
for tid in ("slug-lower", "count-words"):
    for name, extra in (("无", None), ("有", RULE)):
        x = lab.run(tid, tag=f"rule-{name}", extra=extra)
        rows.append([tid, name, "✓" if x["ok"] else "✗", x["why"], x["steps"], x["cost"]])
ss.table(rows, ["题", "AGENTS.md", "通过", "判分", "模型调用", "元"], "一条写进 AGENTS.md 的规则")
```

> 思考：两次各跑一遍只是单个样本，结论可靠吗？第 12 课会专门处理「同一配置跑两次结果不同」的问题。先记下你此刻的判断，到时候回来对照。

## 对照与坑
- 对照：[dsh-handbook](https://github.com/Electricitysheep/dsh-handbook) 第 14 章（实测命中率 97% 的条件）；learn-harness-engineering 第 4 讲；平台《Harness 自进化 Know-how 地图》F1「常驻上下文怎么限量」。
- 源码：`packages/context/agent-instructions`（`maxBytes` 限制每条指令链的大小，sdk 里设为 65536；默认读 `AGENTS.md`、`CLAUDE.md`，再叠加 `.local.md`）。
- 坑：项目根目录靠 `.git` 判断（`projectRootMarkers`），从项目根到工作目录逐层读 AGENTS.md。工作区如果放在另一个仓库里面，会把外层仓库的 AGENTS.md 也读进来——`ss.workspace` 因此给每个练习工作区 `git init`。
- 坑：费用里「命中」和「未命中」差 30 倍，比较两种配置时一定把两者分开看，不要只看总 token。
