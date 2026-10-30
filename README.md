# 本地学习平台（self_startup）

轻量、纯本地的个人工作与学习平台：**复盘 / 规划 / 信息推荐 / 调研 / 深度学习**五个板块，每个板块都有一个可对话的 Agent，直接调用本地 **Claude Code**（`claude -p`），**Codex**（`codex exec`）作为备选。

```bash
./run.sh            # http://127.0.0.1:8780
```

依赖：`uv`、`claude`（或 `codex`）。数据全部在 `data/`（SQLite `app.db` + markdown/HTML 产物），已 gitignore。

## 板块

| 板块 | 做什么 |
|---|---|
| 复盘 | 当天事项/目标完成情况（Agent 读本地代码和文档取证）、问题、学习任务进度；记录问题与经验；时间线回看；Claude Code / Codex 会话效率复盘（人干预次数、方式、等待时间、是否必要、改进建议） |
| 规划 | 每天列几件事 → AI 拆解（优先级 / 并行组 / 依赖 / 人干预度 / 执行者）→ 确定性排程：重度干预放进专注时间窗，自动任务放非专注时间并按并发度分 Agent 泳道；可一键把自动任务交给 Claude Code/Codex 跑 |
| 信息推荐 | 汇集 learn_evolve 已抓取的数据 + HN / HF Papers / GitHub / Reddit / RSS 博客；按热度、新鲜度、兴趣词、你的点赞反馈排序；只给标题、简介、链接 |
| 调研 | 给定主题 + 关注角度，并行调用 Claude Code / Codex / GrokBot（webhook）/ Muse（桌面 App，复制粘贴桥接），可综合成一篇；调研文档库；产品体验记录 |
| 深度学习 | 单篇论文 / GitHub 项目深度解析（复用 codex 的 paper-library、github-code-walkthrough 格式并补充）；主题学习计划（领域综述 → 核心人物观点 → 关键书籍/经典 → 机制精学 → 前沿进展 → 实践），按反馈调整 |

全局设置（页面「设置」或 `data/settings.json`）：人重度干预时间窗（默认 10:00–11:40、13:30–16:50）、Agent 并发度、默认引擎、Claude/Codex 模型、复盘分析目录等。

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
