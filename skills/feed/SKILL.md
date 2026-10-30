---
name: feed
description: 信息推荐板块：收集 AI 相关的论文、博客、产品、开源项目、用户讨论（HN / Hugging Face 每日论文 / AlphaXiv / GitHub / RSS 博客 / Reddit，外加只读导入 learn_evolve），按热度 + 新鲜度 + 兴趣词 + 用户反馈排序推荐，只给标题 + 简介 + 链接 + 推荐理由，不逐条深度分析。用于「今天最值得看的 5 条」「最近有什么 agent 相关的新论文/项目」「把 X 加进兴趣词」「我不想再看到 Y」「刷新信息源」。
---

# 信息推荐板块

数据在本地平台（默认 `http://127.0.0.1:8780`，环境变量 `SELF_STARTUP_API` 覆盖；下文 `$API` 指它）。
在普通 Claude Code 会话里也能用：先 `API=${SELF_STARTUP_API:-http://127.0.0.1:8780}`，确认 `curl -s $API/api/feed/status` 有响应。

## 来源

| source | 类型 | 热度信号 |
|---|---|---|
| learn_evolve | 各类（只读导入 `../learn_evolve/.news.db` 最近 30 天 + 所有有评分的条目，简介取 raw JSON 的 summary/abstract/description 等） | 原始热度；它的 star/good 评分是正向先验，bad/skip 是负向 |
| hn | 讨论 | Algolia 搜 AI 关键词，近 7 天，points |
| hf | 论文 | Hugging Face daily papers，upvotes |
| arxiv | 论文 | AlphaXiv Hot，近 14 天，likes |
| github | 项目 | Search API，近 14 天新建的 AI 仓库，stars（设 `GITHUB_TOKEN` 提高限额） |
| blog | 博客 | `settings.feed.rss` 里的 RSS/Atom，无热度 |
| reddit | 讨论 | r/LocalLLaMA、r/ClaudeAI、r/MachineLearning 本周 top（JSON 被挡时退回 RSS，无票数） |

每个来源独立失败，错误记在 `/api/feed/status` 的 `results.<source>.errors`，不影响其它来源。

## 排序（确定性、可解释）

score = 热度（同源内 log 归一化，0–1；整源无热度给 0.35）
      + 2.0 × 新鲜度（`0.5^(小时数/half_life_hours)`，默认半衰期 72h）
      + 0.45 × 命中兴趣词数（最多 3 个；英文按词边界匹配，标题+简介）
      + 反馈亲和（你赞过/收藏的标题词 +、踩过的 −；你常赞的来源 +；learn_evolve 的 star/good/bad 也算样本）
      + learn_evolve 评分先验 + 本条自己被赞 +1 / 被踩 −2；隐藏的条目不出现
同一 URL（arXiv/HF 论文统一按 arXiv id）或同一标题只保留分最高的一条，其余记为「也见于」。
每条带 `why`，例如 `HN 312分 · 24 小时内 · 命中 agent · 你赞过相似内容（memory）`。

## API

```bash
curl -s "$API/api/feed/items?limit=10"                       # 排序后的推荐（全部类型）
curl -s "$API/api/feed/items?type=paper&limit=5"             # type: paper/blog/product/repo/discussion/news
curl -s "$API/api/feed/items?saved=true"                     # 已收藏
curl -s "$API/api/feed/items?q=memory"                       # 标题/简介筛选
curl -s -X POST $API/api/feed/refresh -H 'Content-Type: application/json' -d '{}'                 # 后台刷新全部来源
curl -s -X POST $API/api/feed/refresh -H 'Content-Type: application/json' -d '{"sources":["hn","github"],"wait":true}'  # 同步刷新指定来源
curl -s $API/api/feed/status                                 # 刷新状态、各来源条数/错误、反馈统计
curl -s -X POST $API/api/feed/feedback -H 'Content-Type: application/json' -d '{"id":"hn:123","vote":1}'   # vote 1/-1/0
curl -s -X POST $API/api/feed/feedback -H 'Content-Type: application/json' -d '{"id":"hn:123","saved":true}'
curl -s -X POST $API/api/feed/feedback -H 'Content-Type: application/json' -d '{"id":"hn:123","hidden":true}'
curl -s $API/api/feed/config                                 # 当前兴趣词、半衰期、查询词、RSS 列表
# 修改兴趣词（整体替换列表）；其它旋钮同理写在 feed 下：half_life_hours / hn_queries / github_queries / reddit / rss / sources
curl -s -X PUT $API/api/settings -H 'Content-Type: application/json' -d '{"feed":{"interests":["agent","llm","mcp","rl"]}}'
```

条目 id 形如 `hn:123`、`github:owner/repo`、`arxiv:2610.12345`、`hf:2610.12345`、`blog:<hash>`、`reddit:<id>`。

## 怎么给推荐

- 以平台的排序结果为准（数据快照里已有前 30 条；需要更多或某类型时调 `/api/feed/items`）。
- 先看 `/api/feed/status` 的 `last_fetched`：超过 12 小时或为空就先同步刷新（`"wait":true`）再推荐，并在回复里写明数据截至何时。learn_evolve 已停更时（库内最新日期远早于今天），它导入的条目只当偏好样本，不当「今天的新内容」推荐。
- 推荐里每条写出来源和日期（如「HN · 10-29」）；发布日期早于 14 天的条目要标「旧」，除非用户要的就是经典内容。
- 每条：**标题（链接）** + 一句中文简介（基于 summary 改写，≤50 字） + 推荐理由（来自 why，可简化）。不要逐条深度分析、不要编造简介里没有的结论。
- 「今天最值得看的 N 条」：取排序前列，兼顾类型多样：同一类型最多占一半（排序前列常被 GitHub 项目占满，要主动用 `type=paper`、`type=blog` 补论文和博客），跳过明显重复和只靠关键词命中、简介看不出价值的项目。
- 用户说「多推/少推 X」：改兴趣词（PUT /api/settings）或对相关条目赞/踩；「不想看到这条」→ hidden。改完简述改了什么。
- 想深读某条：提示用户点该条的「深度学习」按钮（交给深度学习板块）。
