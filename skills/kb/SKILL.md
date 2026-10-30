---
name: kb
description: 本地知识库检索与阅读：在学习平台自动同步的 markdown 知识树（每日记录、问题与经验、调研、产品体验、论文/项目深读、学习计划、收藏信息）里快速找到相关内容并带路径引用作答。用于「我之前记过/学过/调研过 X 吗」「上周关于 X 的结论是什么」「把我关于 X 的积累汇总一下」。
---

# 本地知识库

知识库目录：`<平台 data 目录>/kb/`（默认 `self_startup/data/kb/`），由平台从 SQLite 自动同步，**只读**；要改内容请调用对应板块的 API。

## 结构
- `INDEX.md`：入口，分类计数、最近更新、全部标签。
- `daily/YYYY-MM-DD.md`：当天事项与完成、复盘、问题与经验、Agent 效率、当天产出链接。
- `notes/` 问题与经验 · `research/` 调研 · `products/` 产品体验 · `learn/papers|repos|plans/` 深读与学习计划 · `feed/saved.md` 收藏 · `tags/<标签>.md` 反向索引。
- 每个文件开头是 YAML frontmatter：`id type title date updated tags status url summary`。

## 检索步骤
1. 读 `INDEX.md` 了解有什么；主题明确时看 `tags/`，问时间时看 `daily/`。
2. 关键词检索（任选）：
   - `curl -s "$API/api/kb/search?q=关键词&type=note"`（全文索引，中文 ≥3 字效果最好；返回 path/summary/snippet）
   - `rg -l "关键词" data/kb`；只扫摘要：`rg "^summary:.*关键词" data/kb`
3. 先看 summary 判断相关性，只完整阅读最相关的 2–5 个文件（`curl -s "$API/api/kb/doc?path=notes/xxx.md"` 或直接读文件）。
4. 回答时引用文件路径；区分「知识库里记录的」和「你的推断」；没找到就直说。

`$API` 默认 `http://127.0.0.1:8780`。同步：`curl -s -X POST $API/api/kb/sync`。
