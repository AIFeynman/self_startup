# 信息推荐 / 深读 / 调研：能力达成审计（2026-10-30）

- **基线分支**：最新 `origin/main`（`1fa3023`），新建功能分支 `feat/content-quality-audit`（worktree `../self_startup-cqa`）。基线是任务里写明的，规划时已人工确认。
- **已完成到哪**：三个板块的代码和 skill 已在 main 上。10-29 复盘（`data/kb/daily/2026-10-29.md` #6–#8）把三条真实流程判为 partial 70–80%，指出了三个问题：深读缺「最小上手实验」、推荐理由里的「你赞过」实际来自 learn_evolve、Reddit 429。`673d4fd` 删掉了失效的 anthropic RSS 默认源。
- **本次从哪接着做**：不重做 10-29 的流程跑通。本次补上之前没做的部分：数据量和更新频率、内容抽检、覆盖面、使用情况、价值评估；然后修掉低风险问题，大改动写进「明天继续」。

数据口径：`data/app.db` 的只读副本（10-30 07:10 前后拷贝），外加当场对各信息源的只读抓取。不改动 `data/` 下的任何文件。

---

## 1. 用户要求（来自事项 #16 与各板块 skill 描述）

| 能力 | 用户要求 |
|---|---|
| F 信息推荐 | 持续收集 AI 论文 / 博客 / 产品 / 开源项目 / 讨论；按热度、新鲜度、兴趣、反馈排序；每条有标题、简介、链接、推荐理由；内容专业、覆盖好、有真实价值 |
| L1 单篇深读 | 论文 / 仓库深读，沿用 paper-library / github-walkthrough 格式，增补 TL;DR、与已有知识的联系、可迁移结论、追问清单、最小上手实验 |
| L2 学习计划 | 六阶段主题计划（资源有真实链接），可打分、反馈、自动调整 |
| R 调研 | 按关注角度做调研，有来源、有日期，可多引擎并行再综合，入文档库 |

## 2. 能力达成矩阵

图例：✅ 达成　🟡 部分达成　❌ 未达成

| 能力 | 持续产出（数量 / 频率） | 专业准确（抽检） | 覆盖面 / 来源与日期 | 被用上（点击 / 反馈 / 引用） | 真实价值 |
|---|---|---|---|---|---|
| **F 信息推荐** | ❌ 共 668 条，全部是 **10-29 19:4x 的一次刷新**，之后没再刷新过（`fetched_at` 只有 1 个日期）。代码里没有定时刷新，只能手动点刷新。其中 learn_evolve 导入 380 条，最新日期是 **2026-06-27**，已停更 4 个月 | 🟡 抽检排序前 5 条，标题、链接、日期与源站一致（HN 50284255 / 50296486 分数随时间变化属正常；GitHub grim-prompter、digital-human-koubo 一致）。**第 3 条 `ChannelCooperStart/capri-ai` 已经 404**（3 天 431★ 后被删，疑似刷星仓库） | 🟡 日期字段 100% 有值，但格式不统一（`2026-06-10` / `...Z` / `+00:00`，排序能解析）。HN 链接帖 54/112 **没有简介**。RSS 实际只有 2 个源在出数据：anthropic SSL 失败，lilianweng 30 天内无新文。**没有一家大厂的研究博客**（DeepMind / HF / Anthropic Engineering）。排序前 30 条里 GitHub 项目 16 条、论文 3 条、博客 1 条，有 4 条是 6 月的旧推文 | ❌ `feed_feedback` 只有 1 行，而且是 vote=0（相当于撤销），赞、踩、收藏都是 0。**没有点击埋点**，点击量无从统计。被用上的证据只有 1 条：EAT 论文（`arxiv:2610.36848`）从推荐进了深读（learn #5） | 🟡 有一次真实转化（EAT 深读质量很高），但量很小。排序靠关键词命中 + 来源亲和，被「claude code / codex」关键词仓库占满，信噪比偏低 |
| **L1 单篇深读** | 🟡 3 篇，都在 10-29 19:41 ~ 10-30 00:49 之间，还没有形成规律的产出节奏 | ✅ 3/3 核对过（全部条目，不足 5 篇）。ReAct：ALFWorld 71 vs BUTLER 37（+34），WebShop 40.0 vs 28.7，与 arXiv 摘要的「+34% / +10%」一致。EAT：作者、日期 10-27、MLA 1.2×、36/47、3.01× / 3.44×、RoboDojo 62.1 vs 55.3，全部与摘要一致；还主动指出了论文自身的数字矛盾。Handbook：Apache-2.0、30 章、20 余个案例，与仓库一致（README 列 24 个案例条目） | 🟡 TL;DR、与已有知识的联系、可迁移结论（带边界）、追问清单都有，引用了原文页码 / 图表。**两篇论文都缺「最小上手实验」**（`grep` 找不到），原因是 `skills/learn/paper.md` 根本没要求写；仓库速读有这一节，而且真的跑了实验 | 🟡 EAT 的「与已有知识的联系」具体引用了 learn #1、#4 和计划 #1，说明联系机制有效。两篇论文的「我的笔记」为空；只有 EAT 有 1540 字 `my_notes`，三篇评分都是 0 | ✅ 质量是专业读者水平，能直接用来判断论文可信度。缺的是实验环节：读完没有动手的落点 |
| **L2 学习计划** | 🟡 1 个计划（Agent 评测），16 步，10-29 生成 | 🟡 抽检资源（SWE-bench、τ-bench、Hamel / Shreya / Eugene Yan、METR）都是该领域公认的核心资料；资源链接未逐条点开核对 | ✅ 六阶段齐全，前沿阶段写了具体基准名 | ❌ **进度 0/16**，16 步全是 todo，理解度和反馈都为空，没有一步加进过今日计划 | ❌ 目前没有价值：计划生成后没人跟进，「反馈 → 调整」闭环一次都没跑过 |
| **R 调研** | 🟡 只有 1 篇（10-29），只跑了 claude 一个引擎；codex / grokbot 没跑过，也没做过「综合」 | ✅ 抽检：Claude Code 的 headless 行为（`--bare`、`--permission-mode dontAsk`、stream-json 事件）与官方文档一致；计费变动的时间线（5 月宣布、6-15 暂停）有 Help Center 10-07 更新作依据；文中主动标出 3 处资料冲突。不足 5 篇，只能抽这 1 篇 | 🟡 有来源列表（23 个唯一链接），区分了事实和观点。但 **23 处「日期未知」**，其中 GitHub issue、官方文档这类本来能查到日期的占多数；没有标注一手 / 二手来源 | 🟡 它是这个平台调用层选型的依据，被复盘引用过（10-29 #7）。agent.py 后续是否采纳了「关 stdin / 看门狗」等建议，没有核对 | ✅ 对本项目有直接决策价值 |

### 「功能在但没数据 / 没价值」的项：原因与修复

| 项 | 原因 | 修复（✔ 本次已做 / → 明天继续） |
|---|---|---|
| F 持续产出 | 没有定时刷新，只能手动触发；learn_evolve 停更后仍导入它近 30 天的旧数据 | ✔ feed skill 规定 `last_fetched` 超过 12 小时先刷新再推荐，learn_evolve 停更时只把它当偏好样本 → 后台每 N 小时自动刷新（`feed.auto_refresh_hours`），status 里显示各来源最新日期，并对停更来源告警 |
| F 覆盖 | RSS 只有 2 个源在出数据；HN 链接帖没有简介 | ✔ 默认 RSS 从 3 个扩到 12 个（逐个实测都能抓到，见验收清单）✔ HN 链接帖补上事实性简介「链接到 域名 · N 分 · N 条评论」→ 你的 `data/settings.json` 会覆盖默认列表，需要你决定是否写入（见决策 D1）|
| F 排序信噪比 | 关键词命中可以叠加，GitHub 新仓库热度高；没有类型多样性约束；有刷星仓库 | ✔ skill 要求 Agent 推荐时同一类型最多占一半，并补论文和博客 → 在排序里做类型配额，对 GitHub 仓库加「存活 + 账号年龄」过滤，旧条目对「今天」降权 |
| F 被用上 | 没有点击埋点；反馈按钮基本没人用 | → 记录「打开链接」点击（feed_feedback 加 `clicks` 和 `last_click`），复盘里统计推荐→点击→深读的转化；每周在复盘里提示一次「本周赞 / 踩 0 条，排序没有个性化信号」 |
| L1 缺实验 | `paper.md` 增补里没有「最小上手实验」 | ✔ `paper.md` 加了第 5 段：30–90 分钟的机制验证实验（要验证的结论、最小设置、步骤、预期观察和证伪信号）|
| L2 计划 0 进度 | 计划生成后没有进入每日规划，也没有提醒 | → 规划拆解时自动带上当前学习计划的下一步（`/steps/{id}/today` 已有接口）；这需要你先决定学习时间放在专注窗还是非专注窗（决策 D3）|
| R 日期缺失 | prompt 只说「查不到写日期未知」，没教去哪里找日期 | ✔ research prompt 写明去哪里找日期（页面发布时间、issue 创建日期、changelog、版本号），查不到时写查阅日期；来源标一手 / 二手；每个角度至少 2 个独立来源，资料不足时直说 |
| R 单引擎 | 只跑过 claude，codex 和综合从没验证过 | → 下次调研时选 claude+codex 两个引擎，并验证「综合」 |

## 3. 本次改动

| 文件 | 改动 | 风险 |
|---|---|---|
| `skills/learn/paper.md`、`skills/learn/SKILL.md` | 论文深读增加「最小上手实验」一节 | prompt，下次深读生效 |
| `app/modules/research.py` | 调研 prompt：日期查找规则、一手 / 二手来源标注、每个角度的最低来源数 | prompt |
| `app/modules/_feed_sources.py` | HN 链接帖没有正文时，用「链接到 域名 · 分数 · 评论数」作简介（只用 API 返回的事实，不编造） | 模板字段，有单测 |
| `app/settings.py` | 默认 RSS 3 → 12 个（OpenAI、Anthropic News / Engineering 社区镜像、DeepMind、HF、Simon Willison、Latent Space、Interconnects、Hamel、Eugene Yan、Raschka、Lilian Weng） | 来源配置；只影响没有自定义 rss 的安装 |
| `skills/feed/SKILL.md` | 数据过期先刷新；推荐时写来源和日期，旧条目标「旧」；类型配额，跳过只靠关键词命中的项目 | prompt |
| `tests/test_feed.py` | HN 简介单测 | — |

## 4. 明天继续（大改动，本次不做）

1. 定时刷新 feed（`feed.auto_refresh_hours`，默认 6），status 显示各来源最新日期和停更告警。
2. 排序：类型配额（每类最多占 top N 的 40%）；超过 14 天的条目在「今天」视图里降权；GitHub 仓库在入库时检查存活、owner 账号年龄、星标增速，过滤刷星仓库。
3. 点击埋点和转化漏斗（推荐 → 点击 → 赞 / 收藏 → 深读 → 笔记 / 计划引用），进入复盘和看板。
4. 学习计划接入规划：每天自动建议 1 步，完成后提示打分和反馈，触发 adapt。
5. 调研：跑一次 claude+codex 双引擎和「综合」，确认 codex 链路可用。
6. 统一 feed 的 `date` 格式（入库时转成 ISO UTC）。

---

## 5. 审核包

### 5.1 决策清单

| # | 决策点 | 采用的默认 | 改选其他选项的返工量 |
|---|---|---|---|
| D1 | 你的 `data/settings.json` 里 `feed.rss` 仍然是旧的 4 个源（含已失效的 anthropic），会覆盖新的默认列表。要不要换成新的 12 个？ | **没有改**（红线：不改仓库外的数据）。需要的话，平台运行时执行：<br>`curl -s -X PUT $API/api/settings -H 'Content-Type: application/json' -d '{"feed":{"rss":[...见 app/settings.py...]}}'`<br>或者删掉 settings.json 里的 `feed.rss`，改用默认值 | 1 条命令；想回退，改回旧列表即可 |
| D2 | Anthropic 没有官方 RSS，用社区镜像 `Olshansk/rss-feeds`（第三方，可能停更） | 采用镜像，作为 RSS 中的一个，失败只影响它自己 | 删掉 2 行配置 |
| D3 | 学习计划接入规划时放专注窗还是非专注窗 | 暂不实现，写在明天继续 #4，默认建议放非专注窗的学习块 | 实现后改一个配置 |
| D4 | 「你赞过相似内容」的样本包含 learn_evolve 里的 star / good 评分 | 保持：那些评分也是你在 learn_evolve 里打的，算你的偏好；单测也约定了这个文案 | 想区分来源，改 `_feed_rank` 约 15 行 |
| D5 | 深读和调研不足 5 篇，抽检怎么做 | 全部核对（深读 3 篇 + 调研 1 篇），feed 抽 top 5 | — |

### 5.2 验收清单（按完成标准逐条）

| 完成标准 | 结果 | 证据 |
|---|---|---|
| 分支：基于最新 origin/main 新建 feat/content-quality-audit | ✅ | `git log feat/content-quality-audit`，父提交 `1fa3023` |
| 文档开头写基线、进度、接续点 | ✅ | 本文档开头 |
| 每项能力写出用户要求 | ✅ | §1 |
| 持续产出（数量、频率） | ✅ | §2 第 1 列；SQL：`select source,count(*),min(fetched_at),max(fetched_at) from feed_items group by 1` |
| 专业准确（抽 5 篇对比权威来源） | ✅（深读 / 调研不足 5 篇，已全部核对） | arXiv 2210.03629 / 2610.36848 摘要、github.com/aliyun/ai-agent-handbook、HN Algolia items API、GitHub repos API（capri-ai 返回 404） |
| 覆盖面、来源、日期 | ✅ | §2 第 3 列；各信息源实测：hn 74、hf 50、alphaxiv 60、github 65、reddit 30（r/MachineLearning 429）、RSS：openai 15、simon 15、anthropic SSL 失败、lilianweng 0；新增源：HF 15、DeepMind 11、Latent Space 15、Interconnects 6、Hamel 1、Raschka 1、Anthropic News 镜像 15、Engineering 镜像 1、Eugene Yan 0（30 天内无新文） |
| 被用上（点击 / 反馈 / 引用） | ✅ | `feed_feedback` 1 行，vote=0；没有点击表；learn #5 来自 `arxiv:2610.36848`；`learn_steps` 16 步都是 todo |
| 真实价值 | ✅ | §2 第 5 列 |
| 能力达成矩阵，每格附证据 | ✅ | §2 |
| 没数据 / 没价值的项写原因和修复方案 | ✅ | §2 下表 |
| 只做低风险改动，大改写进明天继续 | ✅ | §3、§4 |
| commit 并 push 到功能分支 | ✅ | 见 5.4 |
| 测试 | ✅ | `uv run pytest -q`：74 passed（含新增的 1 个） |

### 5.3 合并 main 的改动清单

§3 列的 7 个文件，再加上本文档 `docs/audits/2026-10-30-content-quality-audit.md`。不涉及数据库 schema 和前端。合并后：prompt 和 skill 在下次任务时生效；HN 简介在下次刷新时生效；默认 RSS 只在没有自定义 rss 时生效（见 D1）。

### 5.4 版本与回滚

- 功能分支：`feat/content-quality-audit`；基线 `1fa3023`。
- 回滚：如果合并后需要撤销，`git revert <本分支的合并提交>`；不合并就没有影响。数据没有变更，无需回滚。
