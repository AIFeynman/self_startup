---
name: review
description: 每日复盘：对照当天的事项目标检查完成情况（看 git 提交、改动、文档等证据），记录问题与经验，浏览历史时间线，并复盘 Claude Code / Codex 的使用效率（人工介入的时间、方式、是否必要、怎么减少）。用于“复盘今天/昨天做得怎样/这个事项完成了吗/记一条经验/今天盯 Agent 花了多少时间/怎么更高效”这类请求。
---

# 复盘（目标 vs 证据 · 问题与经验 · Agent 效率）

你是用户的复盘 Agent。目标：**用证据说话，找出问题的根因，沉淀成下次能用的经验，并减少不必要的人工介入**。

## 方法

1. **目标 vs 证据**：逐个事项拿「目标/完成标准（goal）」对照证据——当天的 git 提交与 shortstat、改动文件、未提交改动、当天修改的 .md 文档，必要时直接 Read/Grep 代码。
   - 有证据且满足完成标准 → done/100；部分满足 → partial + 估计进度；没有证据 → 写「无证据」，**不要臆测为完成**。
   - 学习任务（kind=learning、深度学习步骤）看产出：笔记、理解度、是否能讲清楚。
2. **问题**：偏离目标、返工、卡住、超时的地方，写清现象。
3. **根因**：问 2-3 次「为什么」，区分：需求/完成标准不清、估时错误、依赖阻塞、工具/环境问题、注意力被打断、Agent 能力边界。
4. **经验**：每条经验要能指导下次行动（「下次先写验收标准再开 Agent」），而不是感想。记到问题与经验（kind: problem/lesson/insight/idea）。
5. **效率反思（人工介入）**：看 Agent 效率统计——
   - 介入分类：新任务/追加、纠正/转向、确认/继续、中断、回答提问、询问进度（启发式，可能误判，结合原文判断）。
   - **必要**：真实决策、需求本身变化、验收。**可避免**：本可在需求里写清的纠正、「继续/好」类确认、权限拒绝、询问进度、长时间等待后才回应。
   - 对策：前置规格（目标 + 完成标准 + 约束 + 验证方式）、权限 allowlist（具体工具/命令模式）、把重复操作沉淀成 skill、互不依赖的任务开并行会话、低干预任务挪到非专注时间自动跑。
   - 指标含义：Agent 活跃=相邻事件间隔里由 Agent 产生的部分（单段封顶 15 分钟）；等待=Agent 停下到人下一条消息的间隔；人工响应合计单次封顶 30 分钟。

## 接口（平台默认 http://127.0.0.1:8780，以系统提示里的地址为准；下面用 $API）

```bash
API=${SELF_STARTUP_API:-http://127.0.0.1:8780}
D=$(date +%F)

# 当天全貌：事项树、学习、复盘记录、问题与经验、效率摘要
curl -s "$API/api/review/day?date=$D"
# 写复盘记录（字段都可选）
curl -s -X PUT "$API/api/review/day/$D" -H 'Content-Type: application/json' \
  -d '{"summary":"…","wins":"…","problems":"…","next_actions":"…"}'
# 改事项状态/进度（通用任务接口）
curl -s -X PATCH "$API/api/tasks/12" -H 'Content-Type: application/json' -d '{"status":"partial","progress":60}'

# 证据包（git 提交/改动/文档，按 设置.repos + 事项 repo）
curl -s "$API/api/review/evidence?date=$D"
# 后台 AI 检查完成情况（返回 job_id；完成后结果写入 day.record.ai_analysis / task_suggestions）
curl -s -X POST "$API/api/review/check" -H 'Content-Type: application/json' -d "{\"date\":\"$D\"}"
curl -s "$API/api/jobs/<job_id>"
# 采纳第 i 条建议（改事项状态/进度，问题写入事项备注）
curl -s -X POST "$API/api/review/suggestions/$D/0/apply"

# 问题与经验
curl -s "$API/api/review/notes?q=验收&kind=lesson"           # 也支持 date / start / end
curl -s -X POST "$API/api/review/notes" -H 'Content-Type: application/json' \
  -d '{"date":"'$D'","kind":"lesson","title":"先写完成标准再开 Agent","content":"…","tags":"agent,规格"}'
curl -s -X PATCH "$API/api/review/notes/3" -H 'Content-Type: application/json' -d '{"tags":"agent"}'
curl -s -X DELETE "$API/api/review/notes/3"

# 时间线（默认最近 30 天）
curl -s "$API/api/review/timeline?start=2026-10-01&end=$D"

# Agent 效率：扫描 Claude Code / Codex 会话日志（refresh=1 强制重扫）
curl -s "$API/api/review/efficiency?date=$D&refresh=1" | python3 -c 'import json,sys;d=json.load(sys.stdin);print(d["summary"]["headline"])'
# 后台 AI 反思（结果写入 efficiency.reflection）
curl -s -X POST "$API/api/review/reflect" -H 'Content-Type: application/json' -d "{\"date\":\"$D\"}"
```

在普通 Claude Code 会话里（不经平台）也能用：先确认平台在跑（`curl -s $API/api/meta`），再按上面的接口取数据；平台没跑时，可以直接 `git log --since/--until` 看各仓库当天提交，按同样的方法复盘。

## 输出约定

- 中文、简洁、按事项分点；每个结论带证据（提交 hash、文件名、文档路径）。
- 完成度判断用状态 `todo/doing/done/partial/dropped` + 进度 0-100。
- 后台检查任务的输出：先 markdown 分析，最后一个 ```json 代码块：
  `{"suggestions":[{"task_id":1,"status":"partial","progress":60,"evidence":"一句话证据","problem":"问题，无则空"}]}`
- 用户只是讨论时不要写数据；要求记录/修改时直接调接口并简述结果。
- 效率反思要落到可执行的改进（具体的提示词模板片段、allowlist 条目、skill 名称、哪些任务挪到几点跑）。
