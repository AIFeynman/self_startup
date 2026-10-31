---
name: feed
description: 信息推荐板块：收集 AI 相关的论文、博客、产品、开源项目、用户讨论（HN / Hugging Face 每日论文 / AlphaXiv / GitHub / 博客 RSS 与官方站 / 播客 / Reddit / X / Product Hunt），按热度 + 新鲜度 + 兴趣词 + 用户反馈排序推荐，只给标题 + 简介 + 链接 + 推荐理由，不逐条深度分析。用于「今天最值得看的 5 条」「最近有什么 agent 相关的新论文/项目」「把 X 加进兴趣词」「我不想再看到 Y」「刷新信息源」。
---

# 信息推荐板块

数据在本地平台（默认 `http://127.0.0.1:8780`，环境变量 `SELF_STARTUP_API` 覆盖；下文 `$API` 指它）。
在普通 Claude Code 会话里也能用：先 `API=${SELF_STARTUP_API:-http://127.0.0.1:8780}`，确认 `curl -s $API/api/feed/status` 有响应。

## 来源

| source | 类型 | 热度信号 |
|---|---|---|
| hn | 讨论 | Algolia 搜 AI 关键词，近 7 天，points |
| hf | 论文 | Hugging Face daily papers，upvotes |
| arxiv | 论文 | AlphaXiv Hot，近 14 天，likes |
| github | 项目 | Search API，近 14 天新建的 AI 仓库，stars（设 `GITHUB_TOKEN` 提高限额） |
| blog | 博客 | `settings.feed.rss` 里约 40 个 RSS/Atom（厂商官方、研究机构、一线实践者、中文媒体），加 `feed.sites` 里没有 RSS 的官方站（Claude.dev、Kimi、MiniMax、DeepSeek、字节 Seed…，读文章页的标题 / 发布日期 / 简介，`extra.via=scrape`）；无热度 |
| podcast | 播客 | `settings.feed.podcasts` 的播客 RSS（Latent Space、Dwarkesh、No Priors、MLST、硅谷101…），每档最多 5 期，只取节目简介；无热度 |
| xiaoyuzhou | 播客 | `settings.feed.xiaoyuzhou` 的小宇宙节目页（张小珺、十字路口、晚点聊），直读页面内嵌数据，每档最多 5 期；失败时依次试 `feed.rsshub_bases` 的公共 RSSHub；playCount（播放） |
| reddit | 讨论 | r/LocalLLaMA、r/ClaudeAI、r/MachineLearning 本周 top（JSON 被挡时退回 RSS，无票数） |
| twitter | 讨论 | `feed.x_accounts` 名单（约 95 个官方 / 研究 / 工程账号）每人近 3 天 ≥100 赞的原创推文取前 2 条 + `feed.x_queries` 热帖搜索（结果需含明确 AI 词）；likes。GetXAPI 优先、twitterapi.io 兜底，每账号 / 搜索词一次请求。X 长文（Article）标 `extra.x_article`（own 自己发 / quoted 引用），自己发的长文另调 twitterapi.io 补标题和开头（`extra.article_title`，每次最多 20 篇，补过的不再调），不取正文；搜索来的长文补不到标题或与 AI 无关就丢掉 |
| producthunt | 产品 | 官方 GraphQL，近 2 天按票数，只留 AI 相关；votes。没配密钥时退回公开 feed（无票数） |

接口密钥放项目根目录 `.env`（不进 git）：`DEEPSEEK_API_KEY`（中文一句话）、`GETXAPI_KEY` / `TWITTER_API_KEY`（X）、`PN_API_KEY` + `PN_API_Secret` 或 `PRODUCTHUNT_TOKEN`（Product Hunt）、`GITHUB_TOKEN`。缺 X 密钥时 x 来源报错、其它来源照常。

每个来源独立失败，错误记在 `/api/feed/status` 的 `results.<source>.errors`，不影响其它来源。

## 排序（确定性、可解释）

score = 热度（同源最近 30 天条目里的百分位，0–1；整源无热度给 0.35，避免历史爆款压低新条目）
      + 2.0 × 新鲜度（`0.5^(小时数/半衰期)`；半衰期 = half_life_hours（默认 72h）× 类型系数：讨论 0.5、产品 0.67、
        博客 1、项目 / 论文 1.67、播客 2.33；只精确到天的日期按当天中午算）
      + 0.45 × 命中兴趣词数（最多 3 个；英文按词边界匹配，标题+简介）
      + 反馈亲和（你赞过/收藏的标题词 +、踩过的 −，常见虚词不算；某来源样本 ≥5 条才算「你常赞 X」；
        早先从 learn_evolve 导入的条目，其 star/good/bad 评分也算样本和先验）
      + 1.2 官方博客（链接域名是 anthropic.com / claude.com / claude.dev / openai.com / deepmind.google / blog.google / research.google）
      + 0.4 X 长文（引用长文 +0.2）+ 0.3 关注账号（X 名单里的账号，搜索来的不加）
      + 0.25 × 其它来源也收了同一条（最多 2 个，「也见于」）
      + 本条自己被赞 +1 / 被踩 −2；隐藏的条目不出现
同一 URL（arXiv/HF 论文统一按 arXiv id）、同一标题，或「同一件事」（标题词重合 ≥3 个、Jaccard ≥0.5、发布相差 ≤4 天）
只保留分最高的一条，其余记为「也见于 HN×2、博客」。
`why` 的顺序：官方 / X 长文 / 关注账号 → 热度（GitHub 带「建 N 天」）→ 新鲜度 → 命中兴趣词（只写最具体的）→ 偏好线索（只说兴趣词之外、在 ≥2 条赞过内容里出现的词）。
`gist`：排序前列（全部前 60 + 每类前 10，标题已是中文的除外）的中文一句话（≤40 字，DeepSeek deepseek-v4-flash 根据标题和简介生成，
不补充给出内容以外的事实）。完整刷新后自动补，只刷部分来源不跑；`POST /api/feed/gist` 手动补。推荐时优先用 gist 当中文简介。
API 返回的 `summary` 已去掉与标题重复的开头（推文标题就是第一句）；HN 链接帖的简介是原文页的 og:description，GitHub 标题带一句话描述。
「全部」列表做多样化：前 5 条（今日精选）每个来源最多 1 条、每类最多 2 条；前 30 条每类 ≤40%、每个来源 ≤20%。
每条带 `why`，例如 `HN 312分 · 24 小时内 · 命中 agent · 你赞过相似内容（memory）`。

## API

```bash
curl -s "$API/api/feed/items?limit=10"                       # 排序后的推荐（全部类型）
curl -s "$API/api/feed/items?type=paper&limit=5"             # type: paper/blog/podcast/product/repo/discussion/news
curl -s "$API/api/feed/items?saved=true"                     # 已收藏
curl -s "$API/api/feed/items?q=memory"                       # 标题/简介筛选
curl -s "$API/api/feed/items?days=1&sort=hot"                # days: 只要最近 N 天发布的；sort: score 综合（默认）/ new 最新 / hot 最热（同源热度百分位）
curl -s -X POST $API/api/feed/refresh -H 'Content-Type: application/json' -d '{}'                 # 后台刷新全部来源
curl -s -X POST $API/api/feed/refresh -H 'Content-Type: application/json' -d '{"sources":["hn","github"],"wait":true}'  # 同步刷新指定来源
curl -s $API/api/feed/status                                 # 刷新状态、各来源条数/错误、反馈统计
curl -s -X POST $API/api/feed/feedback -H 'Content-Type: application/json' -d '{"id":"hn:123","vote":1}'   # vote 1/-1/0
curl -s -X POST $API/api/feed/feedback -H 'Content-Type: application/json' -d '{"id":"hn:123","saved":true}'
curl -s -X POST $API/api/feed/feedback -H 'Content-Type: application/json' -d '{"id":"hn:123","hidden":true}'
curl -s $API/api/feed/config                                 # 当前兴趣词、半衰期、查询词、RSS / 官方站 / 播客 / X 名单
# 修改兴趣词（整体替换列表）；其它旋钮同理写在 feed 下：half_life_hours / hn_queries / github_queries / reddit / rss / sites / podcasts / xiaoyuzhou / rsshub_bases / x_accounts / x_queries / x_min_likes / sources
curl -s -X PUT $API/api/settings -H 'Content-Type: application/json' -d '{"feed":{"interests":["agent","llm","mcp","rl"]}}'
```

条目 id 形如 `hn:123`、`github:owner/repo`、`arxiv:2610.12345`、`hf:2610.12345`、`blog:<hash>`、`podcast:<hash>`、`xiaoyuzhou:<eid>`、`reddit:<id>`、`twitter:<tweet id>`、`producthunt:<id>`。

## 怎么给推荐

- 以平台的排序结果为准（数据快照里已有前 30 条；需要更多或某类型时调 `/api/feed/items`）。
- 先看 `/api/feed/status` 的 `last_fetched`：超过 12 小时或为空就先同步刷新（`"wait":true`）再推荐，并在回复里写明数据截至何时。
- 推荐里每条写出来源和日期（如「HN · 10-29」）；发布日期早于 14 天的条目要标「旧」，除非用户要的就是经典内容。
- 每条：**标题（链接）** + 一句中文简介（基于 summary 改写，≤50 字） + 推荐理由（来自 why，可简化）。不要逐条深度分析、不要编造简介里没有的结论。
- 「今天最值得看的 N 条」：取排序前列，兼顾类型多样：同一类型最多占一半（排序前列常被 GitHub 项目占满，要主动用 `type=paper`、`type=blog` 补论文和博客），跳过明显重复和只靠关键词命中、简介看不出价值的项目。
- 用户说「多推/少推 X」：改兴趣词（PUT /api/settings）或对相关条目赞/踩；「不想看到这条」→ hidden。改完简述改了什么。
- 想深读某条：提示用户点该条的「深度学习」按钮（交给深度学习板块）。
