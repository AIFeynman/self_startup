---
name: learn
description: 深度学习板块：A. 单篇论文 / GitHub 项目深读（沿用 codex 的 paper-library 与 github-code-walkthrough 格式并增补 TL;DR、与已有知识的联系、可迁移结论、追问清单、最小上手实验）；B. 主题学习计划（领域综述 → 核心人物 → 经典书籍论文 → 机制精学 → 前沿进展 → 实践输出，可打分、反馈、自动调整）。用于「深读这篇论文/这个仓库」「给我做一个 X 的学习计划」「根据我的反馈调整计划」。
---

# 深度学习板块

两类学习，数据都在本地平台（默认 `http://127.0.0.1:8780`，环境变量 `SELF_STARTUP_API` 覆盖；下文 `$API` 指它）。

## A. 条目深读（论文 / GitHub 项目）

- 论文：遵循 `~/.codex/skills/paper-library/SKILL.md`（深读按其 `references/deep-reading.md`），再按本目录 [paper.md](paper.md) 增补。产物 `note.md`。
- GitHub：遵循 `~/.codex/skills/github-code-walkthrough/SKILL.md`，再按 [github.md](github.md) 增补。产物离线 `index.html` + 短 `summary.md`。
- 产物写到 `<数据目录>/learn/<id>-<slug>/`；不写入 Obsidian（除非设置 `learn.write_obsidian=true`）。
- 增补要点：顶部 3 行 TL;DR；与用户已学条目/计划的具体联系；可迁移结论（注明边界）；5–8 条可直接继续问的追问清单；「最小上手实验」（论文写 30–90 分钟的机制验证实验，GitHub 写上手命令）。

追问某个条目时（对话 ref `learn:item:<id>`）：先读产物文件再回答，引用原文定位；用户的新认识可写回 `my_notes`。

## B. 主题学习计划

方法论与 JSON 格式见 [plan.md](plan.md)。深度学习板块的后台任务和对话默认用 Sonnet 5.5（设置 `module_models.learn`，只影响本板块）。六阶段固定编号：1 领域综述、2 核心人物与观点、3 关键书籍/经典论文、4 核心机制/概念精学、5 前沿进展（写日期）、6 实践与输出。每步有资源（真实链接，`verified` 标记是否核对）、检查题、预估小时。

**跟着学（章节 + 测试）**：每一步展开成一章教程（替用户消化资料、按阶段目的组织：综述 → 领域地图与痛点/热点/问题/方案矩阵并核对资料时效；人物 → 判断依据与分歧，练判断力；经典/前沿 → 一句话核心思想、背后逻辑、证据与增量）+ 章末测试（选择题当场判、简答/判断题由 Agent 批改），70 分及格自动完成该步，薄弱点回流到计划调整。写法和测试格式见 [chapter.md](chapter.md)。读某一章时对话 ref 是 `learn:step:<id>`：围绕本章能力目标回答，用户答错的题优先帮他想通。

反馈闭环：每步 `status`(todo/doing/done/skipped)、`understanding`(0–5)、`feedback`、`notes`。对话中（ref `learn:plan:<id>`）可直接按用户要求增删改步骤；只讨论时不写数据。调整原则：理解度低 → 补前置或换更易懂资源；理解度高且快 → 跳过同类或加深；不改已完成步骤。

## API（curl 示例）

```bash
# 条目
curl -s $API/api/learn/items
curl -s -X POST $API/api/learn/items -H 'Content-Type: application/json' -d '{"url":"https://arxiv.org/abs/2401.00001","focus":"关注评测设计"}'   # kind 自动识别，可传 paper/github
curl -s -X PATCH $API/api/learn/items/3 -H 'Content-Type: application/json' -d '{"my_notes":"...","rating":4}'
curl -s -X POST $API/api/learn/items/3/rerun
curl -s $API/api/learn/items/3/file            # 主产物（md 为文本）
# 计划
curl -s -X POST $API/api/learn/plans -H 'Content-Type: application/json' -d '{"topic":"世界模型","background":"熟悉深度学习","goal":"能读懂前沿论文并复现一个小实验","hours_per_week":6}'
curl -s $API/api/learn/plans/1                 # 含 steps、progress
curl -s -X PATCH $API/api/learn/steps/12 -H 'Content-Type: application/json' -d '{"status":"done","understanding":3,"feedback":"公式推导没跟上"}'
curl -s -X POST "$API/api/learn/plans/1/steps?after_step_id=12" -H 'Content-Type: application/json' \
  -d '{"stage":4,"title":"补：变分推断基础","description":"...","resources":[{"title":"...","url":"https://...","type":"blog","why":"..."}],"questions":["..."],"est_hours":2}'
curl -s -X DELETE $API/api/learn/steps/15
curl -s -X POST $API/api/learn/plans/1/adapt -H 'Content-Type: application/json' -d '{"note":"第4阶段太难"}'   # 后台 Agent 根据反馈调整
curl -s -X POST $API/api/learn/steps/12/today  # 加入今日计划（tasks，kind=learning）
# 章节 + 测试
curl -s -X POST $API/api/learn/steps/12/open -H 'Content-Type: application/json' -d '{}'   # 没有章节就生成（force:true + note 重新生成），并预生成下一章
curl -s $API/api/learn/steps/12                # 含 chapter_md / quiz（交卷批改前不含答案）/ quiz_result
curl -s -X POST $API/api/learn/steps/12/quiz -H 'Content-Type: application/json' -d '{"answers":{"q1":2,"q2":"我的判断是…因为…"}}'
curl -s -X POST $API/api/learn/steps/12/quiz/reset
```

后台任务（生成/调整/深读）状态：`curl -s "$API/api/jobs?module=learn"`。

## 独立使用（平台未运行时）

- 深读：直接按上面的 skill + 增补文件执行，产物写到用户指定目录。
- 计划：按 plan.md 方法论直接以 Markdown 输出计划（阶段 → 步骤 → 资源/检查题/小时），并在每次用户反馈后按调整原则修改。
