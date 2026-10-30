# 主题学习计划：方法论与 JSON 格式

目标：把一个陌生主题变成「专业级」学习路径——先建立领域地图，再认识人和观点，读经典，精学机制，追到前沿，最后用输出检验。每一步都可打分、反馈、调整。

## 六个阶段（stage 固定编号，按顺序）
1. **领域综述**：按 `~/.codex/skills/domain-landscape/SKILL.md` 的思路——底层逻辑（根问题、约束、核心机制、失效边界）、体系分支与关键任务、相邻领域关系。资源：高质量综述、课程讲义、权威入门。
2. **核心人物与观点**：5–8 位代表人物/团队，「贡献 → 核心主张 → 证据与边界 → 最新状态」；有分歧要并列。资源：本人论文/演讲/访谈原文。
3. **关键书籍 / 经典论文**：真正奠基的书和论文，说明读哪几章/哪几节、读完能回答什么。
4. **核心机制 / 概念精学**：3–6 个必须吃透的机制，每个一步，附可推导/可复现的材料。
5. **前沿进展**：最近 12–18 个月的论文、实验室、开源仓库，每项写明日期和证据级别（预印本/会议/部署）。
6. **实践与输出**：最小项目、复现实验、写一篇费曼式讲解或对比评测；用产出检验理解。

每阶段 1–4 步，总共 10–20 步；总时长与 hours_per_week 匹配（大约 4–10 周）。按用户背景跳过已会内容、加强薄弱处。

## 资源要求
- 只给真实存在的链接；能访问的先用 WebFetch/curl 核对，`verified: true`；无法核对的 `verified: false`，不要编造 URL。
- `type`: paper / book / course / video / blog / repo / doc / talk。
- `why`: 一句话说明它在这一步解决什么。

## 检查题
- 每步 2–4 道，能检验理解而非记忆（「为什么」「如果没有…会怎样」「如何验证」）。

## 生成计划时输出的 JSON（最终回复里放一个 ```json 代码块）
```json
{
  "overview_md": "Markdown：主题边界、底层逻辑一段话、路线总览、资料核对日期",
  "steps": [
    {"stage": 1, "title": "...", "description": "做什么、产出什么（Markdown 可）",
     "resources": [{"title": "...", "url": "https://...", "type": "paper", "why": "...", "verified": true}],
     "questions": ["..."], "est_hours": 3}
  ]
}
```

## 根据反馈调整时输出的 JSON
```json
{
  "summary": "一两句：发现了什么问题、怎么调",
  "edits": [
    {"op": "add", "stage": 4, "after_step_id": 12, "title": "...", "description": "...", "resources": [], "questions": [], "est_hours": 2},
    {"op": "modify", "step_id": 13, "title": "...", "description": "...", "est_hours": 3, "questions": ["..."]},
    {"op": "skip", "step_id": 15, "reason": "已掌握"},
    {"op": "add_resources", "step_id": 12, "resources": [{"title": "...", "url": "...", "type": "blog", "why": "补救：..."}]}
  ]
}
```
调整原则：理解度 ≤2 或反馈说没懂 → 补前置/换更易懂的资源（add_resources 或 add 补救步）；理解度 5 且很快完成 → 后续同类步骤可 skip 或加深；不修改已 done 的步骤；只做有依据的少量修改。
