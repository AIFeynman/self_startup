# 实践课格式

一门课一个目录：`practice/courses/<id>/`（平台自带）或 `data/practice/courses/<id>/`（生成的）。

## course.json

```json
{
  "title": "从零训练一个小语言模型",
  "topic": "LLM 训练",
  "summary": "一句话说明学完能做什么",
  "level": "入门 / 进阶",
  "repo": "https://github.com/owner/repo",
  "runtime": "cloud",
  "pip": ["transformers==4.57.6"],
  "know": ["分词", "自注意力"]
}
```

- `repo`：要学的仓库，平台在本机 clone，运行时工作目录就是仓库根目录；没有仓库就省略。
- `runtime`：`cloud` = 阿里云 GPU（用时才开机，按小时计费），`local` = 本机（CPU / Apple GPU）。
- `pip`：课程额外依赖。`torch` 由运行环境自带，不要写。
- `know`：这门课涉及的关键概念，页面上可以点开查知识库或让 Claude 讲解。

## NN-xxx.md（一课一个文件，按文件名排序）

```markdown
# 1 分词器：模型看到的不是字
<!-- minutes: 10 -->
<!-- know: 分词, BPE, 词表大小 -->
<!-- gpu: no -->

一两句话说明这课的目标。

## 第一步的标题
讲解（为什么这样设计、常见误区，可以用表格和公式）。

（这里放一个 python 代码块；信息串可带 long 表示要跑几分钟以上、gpu 表示需要 GPU）

> 思考：一个让人停下来想的问题（页面上可以点「问 Claude」对答案）。
```

- `## ` 分步，每步建议「讲解 → 一个短代码格 → 一个思考题」。
- 同一门课的所有代码格共享一个内核（变量跨课保留），开头已执行 `import ss`，当前目录是仓库根目录。
- 可视化用 `ss`：`ss.kv / table / bars / tokens / topk / heat / compare / line / trace / note / train_live / env_info / device`。
- 调大模型用 `ss.llm(prompt, system)`，走本机 Claude，不需要 API key。
- 取数据用 `ss.fetch_head(modelscope 数据集, 文件, 行数, 存放路径)`，只下前 N 行。
