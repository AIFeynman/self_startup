---
name: intel
description: 产品雷达板块：持续跟踪大公司（OpenAI / Anthropic / Google / 微软 GitHub / xAI / Meta / DeepSeek / Qwen / Kimi / Mistral）和明星 AI native 公司（Cursor / Cognition / Replit / Lovable / Perplexity / Manus / MiniMax / ElevenLabs / Midjourney / Suno）的产品、功能、定价、商业变化；官方 changelog / 定价页快照 diff + 官方 RSS / 博客 / X / GitHub，跨源去重成「事件」，按 S/A/B/C 分级，B 级及以上自动出「五层解读卡」（变了什么 / 用户问题 / 产品逻辑 / 技术逻辑 / 商业逻辑 / 所以呢）。用于「这周 S/A 级变化有哪些」「Anthropic 最近做了什么」「Cursor 定价改了吗」「解读一下这次发布」「把 X 公司加进雷达」。另跟踪 AI 创业公司：TrustMRR 每日收入快照（verified MRR / 30 天收入）、新闻里的公开 ARR（reported，分开显示）、16 个固定赛道、生意拆解卡（收入 / 卖什么 / 怎么收钱 / 客户从哪来 / 做对了什么 / 可抄的打法 / 风险）、Product Hunt 日榜解读；用于「哪些 AI 小公司 MRR 涨得快」「语音赛道谁在赚钱」「X 是怎么获客的」「今天 PH 榜上有什么」。
---

# 产品雷达

数据在本地平台（默认 `http://127.0.0.1:8780`，环境变量 `SELF_STARTUP_API` 覆盖；下文 `$API` 指它）。
设计稿：`docs/designs/2026-11-01-product-intel-design.md`。代码：`app/modules/intel.py`（落库 / 调度 / 接口）、`_intel_watch.py`（默认名单）、`_intel_snap.py`（抓取 / diff / 定价结构化）、`_intel_events.py`（实体链接 / 分类去重 / 分级 / 解读卡）、`_intel_startup.py`（TrustMRR 解析 / 收入异动规则 / 赛道 / 拆解卡 / PH / 公开 ARR）。创业公司设计稿：`docs/designs/2026-11-01-startup-intel-design.md`。

## 链路

1. **采集**（后台每 10 分钟一轮，到期才抓：changelog / rss 6 小时，pricing / docs 24 小时）
   - `changelog`：抓页面 → 取正文 → 和上一版快照 diff，新增块按日期行切成条目。首次快照只收近 14 天的条目。
   - `pricing`：DeepSeek 把定价页结构化（plans / usage），和上一版对比出变化；变化里的价格数字必须在新旧页面原文里出现，否则丢弃。首次只存结构。
   - `rss`：官方 RSS / GitHub releases（去掉 alpha / nightly 等预发布），只收 14 天内。
   - `docs`：只存快照，不出事件。
   - 认领信息推荐（feed）里的条目：公司域名的博客、公司 X 账号、公司 GitHub 组织 → 官方候选；HN ≥100 分 / 其它博客 / Product Hunt 标题命中公司别名 → 第三方候选（只并入已有事件，不单独成事件）。
   - 快照存在 `data/intel/snapshots/<source_id>/`。403 / JS 渲染页记在信息源的 `last_err`。
2. **识别**：按公司分批（15 条一批）交给 DeepSeek 判断是不是真实变化、类型、规模、是否和已有事件（近 7 天）或同批更早候选是同一件事 → 建事件或合并来源。链接已在某事件来源里的直接合并，不调模型。
3. **分级**（代码规则，`_intel_events.auto_level`）：T1 定价 / 套餐变化、T1 旗舰模型 / 新产品 → S；其它新产品、定价、战略级合作融资、T1/T2 大功能 → A；普通功能 / API → B；小改进 → C。人工改级别写 `intel_level_log`，改到 B 以上会自动出卡。
4. **解读卡**：B 级及以上、近 7 天的事件，按 S → A → B 排队提交后台 Claude 任务（standard 档），每天最多 `intel.cards_per_day`（默认 20）张；手动「重新解读」不受限。完成后校验 6 节齐全、有 `[来源](链接, 日期)` 出处 → `done`，否则 `incomplete`。每次生成都追加一行 `intel_analysis`，不覆盖。

## 创业公司链路（每天一次，`intel.startups` 开关）

1. **TrustMRR 快照**：抓首页 / AI 分类 / 在售列表，AI 分类且有收入的全部建档（`kind='startup'`），指标按天只追加写 `intel_metric`（同一天同一指标同一来源不重复）。首日只建基线，不追溯异动。
2. **收入异动**（代码规则 `_intel_startup.detect`）：MRR 跨过 $10k / $50k / $100k / $1M、30 天环比 ≥ +100%（MRR ≥ $3k）或 ≤ −40%（MRR ≥ $5k）、新挂牌出售 → `type=revenue|listing` 事件；收入事件不出五层卡，改看公司的拆解卡。
3. **详情页**：每天最多 `details_per_day` 个，补官网、创始人 X、渠道、定价。
4. **赛道**：16 个固定赛道（`_intel_startup.TRACKS`），DeepSeek 每轮归 150 家，同一次调用顺带写中文一句话简介（`ext.intro_zh`：做什么 + 帮谁解决什么问题；原文简介变了会重写）；页面上人工改的（`track_manual=1`）不再被覆盖。
5. **公开 ARR**：信息推荐里命中 ARR / MRR 关键词的条目让 DeepSeek 抽数字，数字必须在原文出现，记成 `source='reported'`，报道里的新公司自动建档（`ai=-1` 待确认）。
6. **PH 日榜**：取前 `ph_top` 名，DeepSeek 一段话解读 + 每条归赛道。
7. **生意拆解卡**：Claude 联网写 7 节卡片，每天自动最多 `profiles_per_day`（10）张，同一家 `profile_days`（30）天内不重复；手动「写拆解卡」不受限。只追加 `intel_profile`。

## API

```bash
curl -s "$API/api/intel/events?level=S,A&days=7"          # 事件流；level 逗号分隔，days=0 不限，company=<slug>，q=关键词
curl -s "$API/api/intel/events/12"                        # 事件详情：来源、最新解读卡全文（card.content）、历史版本、级别调整
curl -s -X POST $API/api/intel/events/12/level -H 'Content-Type: application/json' -d '{"level":"A","reason":"战略级"}'
curl -s -X POST $API/api/intel/events/12/card             # 重新生成解读卡（返回 job_id）
curl -s "$API/api/intel/companies"                        # 名单 + 事件数 + 信息源健康
curl -s "$API/api/intel/companies/anthropic"              # 一家公司的时间线 + 调研板块里的一手体验
curl -s -X POST $API/api/intel/companies -H 'Content-Type: application/json' -d '{"name":"Windsurf","tier":3,"aliases":["Windsurf"],"domains":["windsurf.com"]}'
curl -s -X PATCH $API/api/intel/companies/5 -H 'Content-Type: application/json' -d '{"enabled":0}'
curl -s "$API/api/intel/sources"                          # 信息源：快照数、候选数、上次成功、错误
curl -s -X POST $API/api/intel/sources -H 'Content-Type: application/json' -d '{"company_id":5,"kind":"changelog","url":"https://…/changelog","label":"Windsurf Changelog"}'
curl -s -X POST $API/api/intel/sources/7/fetch            # 立即抓一个源（同步）
curl -s -X POST $API/api/intel/run -H 'Content-Type: application/json' -d '{"force_fetch":true}'   # 后台跑一轮（所有源都抓）
curl -s "$API/api/intel/status"                           # 上一轮结果、待分类候选、异常信息源、今日解读卡额度、startup_last
curl -s "$API/api/intel/startups?track=voice&sort=growth&q=" # 创业公司表；sort=rev|growth|reported，all=1 含非 AI，watch=1 只看关注
curl -s "$API/api/intel/tracks"                           # 16 个赛道：公司数、合计 MRR、增长中位数、头部公司
curl -s "$API/api/intel/tracks/sales"                     # 单个赛道：公司、收入事件、PH 条目
curl -s "$API/api/intel/ph?days=7"                        # PH 日榜 + 解读
curl -s -X POST $API/api/intel/startups/run -H 'Content-Type: application/json' -d '{"force_fetch":true,"cards":false}'  # 后台跑一遍创业公司链路
curl -s -X POST $API/api/intel/companies/221/profile      # 写 / 重写生意拆解卡（返回 job_id）
curl -s -X PATCH $API/api/intel/companies/221 -H 'Content-Type: application/json' -d '{"track":"voice","watch":1,"ai":1,"ext":{"bizpeel_url":"https://bizpeel.com/…","notes":"手动粘贴的资料"}}'
```

设置（`PUT /api/settings` 写在 `intel` 下）：`cards_per_day`（20）、`card_days`（7）、`feed_lookback_days`（3）、`cycle_minutes`（10）、`startups`（true）、`details_per_day`（40）、`profiles_per_day`（10）、`profile_days`（30）、`ph_top`（20）。需要 `.env` 里有 `DEEPSEEK_API_KEY`（分类和定价结构化）；没有时候选会一直 pending。

## 怎么回答

- 「最近有什么重要变化」：GET `/events?level=S,A&days=7`，按公司归类，每条一句话 + 级别 + 有无解读卡；S 级放最前。
- 「解读一下 X」：先找事件（`q=` 或公司时间线），有 `done` 解读卡就基于卡片回答并给页面链接 `#intel/e/<id>`；没有就 POST `/card` 生成，或者直接按卡片 6 节结构答，事实带来源和日期、推断标【推测】。
- 「X 公司最近在干什么」：GET `/companies/<slug>`，看连续动作（定价 + 功能 + 模型放在一起看），给出方向判断，标明哪些是推测。
- 加公司 / 加信息源：先确认 changelog / 定价页能直接抓（`/sources/<id>/fetch` 看 `last_err`）；403 或 JS 渲染的页面先找有没有 RSS / GitHub releases 替代，没有就记 note「需浏览器 / 人工」。
- 不要自己编造发布日期和价格；平台里没有的写「平台里还没收到」。
- 「哪些 AI 小公司涨得快 / X 赛道谁在赚钱」：GET `/startups?sort=growth` 或 `/tracks/<slug>`；verified（TrustMRR）和 reported（公开报道）分开说，不要混算。
- 「X 是怎么赚钱 / 获客的」：GET `/companies/<slug>` 看 `profile`；没有就 POST `/companies/<id>/profile`，页面 `#intel/c/<slug>`。
