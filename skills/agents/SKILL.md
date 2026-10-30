---
name: agents
description: Agent 看板：查看本地 Claude Code / Codex 会话和平台后台任务的实时进度（运行中 / 等你处理 / 待验收 / 已验收），找出卡住、等批准、等回复的会话，给出处理建议，并可标记验收、归档、关联规划事项。用于「现在哪些 Agent 在跑」「哪些在等我」「各会话进展到哪了」「把这个标记完成」。
---

# Agent 看板

数据来自本地会话日志（只读）：Claude Code `~/.claude/projects/*/*.jsonl`（及 `.rec` 账号目录），Codex `~/.codex/sessions/YYYY/MM/DD/*.jsonl`，以及平台自己的后台任务。

## 状态怎么判断
- **运行中**：回合未结束，且 2 分钟内日志有写入（或 20 分钟内，标「较久未输出」）。
- **等你处理**：Agent 以问句结束（等你回复）／工具调用没有结果且长时间不动（等待批准？）／回合未结束超 20 分钟（可能卡住）／被中断／出错／平台任务失败。
- **待验收**：回合正常结束；若计划没走完会标「已停 · 计划 3/5」。
- **已验收 / 归档**：用户手动标记；会话之后有新活动会自动失效。

## 接口（$API 默认 http://127.0.0.1:8780）
- 看板：`curl -s "$API/api/agents/board?hours=24"`（`automated=true` 显示脚本会话）
- 标记：`curl -s -X POST $API/api/agents/state -H 'Content-Type: application/json' -d '{"key":"claude:<id>","col":"done","note":"已验收","task_id":12}'`（col: done / archived / "" 恢复自动；带 task_id 时验收会把规划事项标记完成）
- 续接命令：`POST /api/agents/resume-command {"key","cwd"}`；在终端打开：`POST /api/agents/open`（只在用户明确要求时调用）

## 回答方式
先给「等你处理」的会话（按紧急程度：等批准 > 卡住 > 等回复 > 中断/出错），每条一句话说明在等什么、建议怎么做；再简述运行中的进度（计划 x/y、当前步骤）；待验收的只列标题。不要编造日志里没有的进展。
