# 本地学习平台（self_startup）

轻量、纯本地的个人工作与学习平台：**规划（默认首页）/ Agent 看板 / 复盘 / 信息推荐 / 调研 / 深度学习 / 知识库**，每个板块都有一个可对话的 Agent，直接调用本地 **Claude Code**（`claude -p`），**Codex**（`codex exec`）作为备选。

```bash
./run.sh            # 前台运行：http://127.0.0.1:8780
./run.sh -d         # 后台常驻（日志 data/logs/server.log）
./run.sh stop       # 停止后台服务
```

改动自动生效：`web/` 改了打开的页面会自动刷新（正在输入或对话中时改为提示条）；`app/` 改了由 supervisor 等后台任务和对话都结束后自动重启，不会打断任务。

依赖：`uv`、`claude`（或 `codex`）。数据全部在 `data/`（SQLite `app.db` + markdown/HTML 产物），已 gitignore。

## 板块

| 板块 | 做什么 |
|---|---|
| Agent 看板 | 读取本地 Claude Code / Codex 会话日志 + 平台后台任务，按 运行中 → 等你处理（等回复/等批准/卡住/中断/出错）→ 待验收 → 已验收 流转；显示计划进度与当前步骤、最近要求与回复；可拖动验收、归档、关联规划事项、复制续接命令或在终端续接，每 10 秒刷新；「时间利用」把会话真实事件铺到时间轴：Agent 覆盖与并发容量、空档、专注时间外的人工交互、Agent 等你的时间、近 7 天规律和改进建议（同时进入复盘、知识库每日记录和规划的拆解提示） |
| 复盘 | 当天事项/目标完成情况（Agent 读本地代码和文档取证）、问题、学习任务进度；记录问题与经验；时间线回看；Claude Code / Codex 会话效率复盘（人干预次数、方式、等待时间、是否必要、改进建议） |
| 规划 | 每天列几件事 → AI 拆解（先看相关会话的已有进展和交付，每个事项不超过 4 个子任务；优先级 / 并行组 / 依赖 / 人干预度 / 执行者）→ 出草稿（依据、待你拍板的问题、子任务），在对话里讨论修改，确认采用后才写入 → 确定性排程：重度干预放进专注时间窗，自动任务放非专注时间并按并发度分 Agent 泳道；可一键把自动任务交给 Claude Code/Codex 跑 |
| 信息推荐 | 汇集 learn_evolve 已抓取的数据 + HN / HF Papers / GitHub / Reddit / RSS 博客；按热度、新鲜度、兴趣词、你的点赞反馈排序；只给标题、简介、链接 |
| 调研 | 给定主题 + 关注角度，并行调用 Claude Code / Codex / GrokBot（webhook）/ Muse（桌面 App，复制粘贴桥接），可综合成一篇；调研文档库；产品体验记录 |
| 知识库 | 检索 / 阅读自动同步的本地知识（见下） |
| 深度学习 | 单篇论文 / GitHub 项目深度解析（复用 codex 的 paper-library、github-code-walkthrough 格式并补充）；主题学习计划（领域综述 → 核心人物观点 → 关键书籍/经典 → 机制精学 → 前沿进展 → 实践），按反馈调整 |

全局设置（页面「设置」或 `data/settings.json`）：人重度干预时间窗（默认 10:00–11:40、13:30–16:50）、Agent 并发度、默认引擎、Claude/Codex 模型、复盘分析目录等。

## 本地知识库（data/kb）

SQLite 管应用状态；每次写操作后，平台自动把内容同步成一棵适合大模型检索阅读的 markdown 树（可随时重建，勿手改）：

```
data/kb/
  README.md            结构与检索说明（给大模型）
  INDEX.md             入口：分类计数、最近更新、全部标签
  daily/YYYY-MM-DD.md  一天的事项与完成、复盘、问题与经验、Agent 效率、当天产出链接（时间线）
  notes/               问题 / 经验 / 洞察 / 想法，一条一个文件
  research/  products/ 调研文档、产品体验
  learn/papers|repos|plans/  论文/项目深读（TL;DR + 笔记 + 全文内嵌）、学习计划（阶段/步骤/理解度/反馈）
  feed/saved.md        点赞 / 收藏的信息
  tags/<标签>.md       按标签的反向索引
```

- 每个文件带 YAML frontmatter：`id type title date updated tags status url summary`，先看 `summary` 判断相关性再读正文，省上下文。
- 全文检索：SQLite FTS5（trigram，中文可用），`GET /api/kb/search?q=`；也可直接 `rg data/kb`。
- 所有板块 Agent 都能只读访问 `data/kb`，并被告知先查知识库；全局 skill `ss-kb` 让普通 Claude Code / Codex 会话也能用。

## 便捷输入

- 每个页面顶部一个大输入框：Enter 发送、Shift+Enter 换行，按 `/` 随时聚焦；可切换模式（如「记一条 / 问 Agent」「加事项 / 问 Agent」）。
- 输入框下的快捷 chip 一键发常用指令；右侧对话面板随时可开（侧栏「新对话」或最近对话）。

## 结构

```
app/
  main.py        入口：核心接口 + 自动挂载 app/modules/*.py
  agent.py       调用 claude / codex CLI（stream-json），统一事件流，失败自动回退
  chat.py        /api/chat/<module>：每个板块的对话 Agent（SSE，可续聊）
  jobs.py        后台 Agent 任务（调研、解析、拆解等长任务），完成回调板块 on_job_done
  tasks.py       每日事项 CRUD（规划写、复盘读）
  db.py settings.py
  modules/       一个文件一个板块：router / SCHEMA / agent_context / agent_dirs / on_job_done
web/             无构建的 ES module 前端；web/modules/<板块>.js
skills/<板块>/SKILL.md   板块 Agent 的 skill（对话时注入 system prompt；也可装到全局）
```

**Agent 怎么工作**：对话时平台把 `skills/<板块>/SKILL.md` + 当前数据快照拼成 system prompt，Agent 通过 `curl` 调本平台 API 读写数据（接口见 `/docs`）。

**在普通 Claude Code / Codex 会话里用这些 skill**：

```bash
scripts/install_skills.sh
```

会把各板块 skill 以 `ss-<板块>` 软链到 `~/.claude/skills` 和 `~/.codex/skills`（`--uninstall` 移除）；平台需在运行中。

## 开发

```bash
uv run pytest -q
```

新增板块：复制 `app/modules/_example.py` 与 `web/modules/_example.js`，去掉下划线即可被自动发现。
