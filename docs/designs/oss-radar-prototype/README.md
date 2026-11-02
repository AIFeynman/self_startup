# 开源雷达原型（2026-11-01）

设计稿：[../2026-11-01-oss-radar-design.md](../2026-11-01-oss-radar-design.md)。这些是一次性实验脚本，不是平台代码；Q1/Q2 实现时参考。

- `label2.py`：打包标注（分类体系放 `--system-prompt`，每次 50 个）。参数：`taxonomy sample out_dir start count batch`。
- `cmp.py`：两次标注的一致性对比。
- `queries.json` / `rewrite.py` / `intents.json`：15 条中文功能查询和改写结果。
- `search.py`：FTS5 召回 + 特征打分 + 原子词召回 + Haiku 精排。用法：`uv run python -I search.py <数据目录> 0,1,2`（数据目录要有 sample.json、pdfset.json、r3/、r4/ 的标注结果）。
- `rerank-results-15q.txt`：15 条查询精排后的结果。
