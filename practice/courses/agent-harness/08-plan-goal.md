# 8 规划与目标：先列计划，独立判断做完没
<!-- minutes: 35 -->
<!-- know: Plan mode, Goal, Ralph loop, 过早完成 -->

多步任务常见两种失败：一上来就动手、做到一半方向错了；或者做了一部分就宣布完成。dsh 给了几种编排方式：
- **直接做**：一轮对话，模型自己决定步骤；
- **`/plan`**（`plan-mode`）：先只读地调研、写计划，交给人审阅，批准后才动手；
- **`/goal`**（`goal` + `goal-round-driver`）：设一个目标，harness 自动开多轮，每轮结束判断目标达成没有，没达成就继续；
- **ralph**（实验包 `tool-ralph`）：每一轮都开一个**全新**的子 agent，只靠文件里的进度接力，避免长上下文把它带偏。

这一课同一道多步题四种跑法，比完成度、步数和花费；再用 SDK 驳回一次计划，看它怎么改。

## 四种跑法
题：`cli-freq`（给命令行加 freq 子命令，要读 core、改 cli、记 CHANGELOG）。`/plan` 的计划审阅通过 SDK 的 `on_user_question` 回答，这里先一律批准。

```python
import harness_lab as lab, json, time
def approve_all(req):
    q = req.questions[0]
    return {"answers": [{"id": q["id"], "selected": ["Approve"]}]}
RALPH = __import__("pathlib").Path("packages/experimental/ralph-bundle/cordis.patch.yml").resolve()
t = lab.BY_ID["cli-freq"]
ways = [("直接", t.prompt, {}), ("/plan", "/plan " + t.prompt, {"on_user_question": approve_all}),
        ("/goal", "/goal " + t.prompt + " 完成标准：命令输出正确，CHANGELOG 已记录。", {}),
        ("ralph", "用 ralph 工具完成这个任务：" + t.prompt, {"patches": [RALPH]})]
rows = []
for name, prompt, kw in ways:
    x = lab.run("cli-freq", tag="orch-" + name.strip("/"), prompt=prompt, show=True, **kw)
    r = x["run"]
    rows.append([name, "✓" if x["ok"] else "✗", x["why"], len(r.usage), len(r.sub_usage), f"{r.cost:.4f}", round(r.seconds)])
ss.table(rows, ["跑法", "通过", "判分", "主会话模型调用", "子会话模型调用", "元", "秒"], "同一道多步题，四种编排")
```

> 思考：`/goal` 和 ralph 都是「做完一轮再判断要不要继续」，区别在于判断者看到的上下文：goal 在同一个会话里接着跑，ralph 每轮从零开始只读文件。哪种更不容易「自我感觉良好」地宣布完成？哪种更贵？learn-harness-engineering 第 7、9 讲专门讲过早宣布完成。

## 驳回一次计划
第一次审阅时驳回，并给出修改意见（「计划里必须包含更新 CHANGELOG 和跑单元测试」），第二次再批准。看修改后的计划有没有采纳意见。

```python
reviews = []
def review_once(req):
    q = req.questions[0]
    reviews.append(q.get("detail", ""))
    if len(reviews) == 1:
        return {"answers": [{"id": q["id"], "selected": ["Keep planning"], "custom": "计划里必须包含：更新 CHANGELOG.md、用 python -m unittest 跑测试。"}]}
    return {"answers": [{"id": q["id"], "selected": ["Approve"]}]}
x = lab.run("cli-freq", tag="plan-review", prompt="/plan " + t.prompt, on_user_question=review_once)
ss.compare("第一版计划", reviews[0][:1500] if reviews else "（没收到计划）", "第二版计划", reviews[1][:1500] if len(reviews) > 1 else "（没有第二版）", "驳回前后")
ss.kv({"判分": x["why"], "审阅次数": len(reviews)}, "结果")
```

## 对照与坑
- 源码：`packages/plan/plan-mode`、`packages/goal/goal-round-driver`、`packages/experimental/tool-ralph`。
- 对照：learn-claude-code s05（todo）、s17；Geoffrey Huntley 的 Ralph Wiggum 循环（每轮全新上下文、靠文件接力）。
- 坑：计划审阅走的是 `user-question/ask` 请求，`intent.kind` 为 `plan-review`；SDK 里没设 `on_user_question` 时，计划会一直等审阅。
- 坑：`/goal` 会自动开很多轮，一定配花费上限（`ss.agent` 的单格 2 元上限在这里最容易触发）。
