# 2 上下文与记忆：步骤一多就装不下
<!-- minutes: 12 -->
<!-- know: 上下文窗口, 记忆压缩, 摘要 -->

上一课的 `history` 每一步都在变长。真实任务动辄几十上百步，工具输出又长，很快就会超出上下文窗口，而且越长越贵、越慢、越容易「忘了重点」。

## 看 history 怎么膨胀
让 Agent 读一个很长的文件，统计每一步的上下文长度。

```python
open("sandbox/log.txt", "w", encoding="utf-8").write("\n".join(f"2026-11-{d:02d} INFO job {i} ok" for d in range(1, 28) for i in range(40)))
lens = []
_llm = ss.llm
def counting_llm(prompt, system=""):
    lens.append(len(prompt))
    return _llm(prompt, system=system)
ss.llm = counting_llm
run_agent("读 sandbox/log.txt，告诉我一共有多少行、最后一行是什么。")
ss.llm = _llm
ss.bars({f"第 {i+1} 步": n for i, n in enumerate(lens)}, title="每一步发给模型的上下文长度", unit=" 字符")
```

> 思考：工具返回了整个文件，之后每一步都要重复携带。有哪些办法让它变短？

## 压缩：把旧的观察换成摘要
常见做法：工具输出太长就截断并注明；历史超过阈值，就让模型把前面的过程总结成几行，替换原文。

```python
def compact(history, limit=1500):
    if len(history) <= limit:
        return history
    head, tail = history[:limit // 2], history[-limit // 2:]
    summary = ss.llm("把下面 Agent 的工作过程压缩成 3 行要点，保留已知事实和数字：\n" + head)
    return "（前面过程的摘要）" + summary.strip() + "\n…\n" + tail

TOOLS["read_file"] = (lambda path: (lambda t: t if len(t) < 800 else t[:400] + f"\n…（共 {len(t)} 字符，已截断）…\n" + t[-200:])(read_file(path)),
                      "读取文件内容，参数 path（相对路径）；很长的文件只返回开头和结尾")
TOOLS["line_count"] = (lambda path: str(sum(1 for _ in open(path, encoding="utf-8"))), "统计文件行数，参数 path")
SYSTEM = SYSTEM.split("可用工具：")[0] + "可用工具：\n" + "\n".join(f"- {k}: {d}" for k, (_, d) in TOOLS.items())
COMPACT = compact
lens.clear(); ss.llm = counting_llm
run_agent("读 sandbox/log.txt，告诉我一共有多少行、最后一行是什么。")
ss.llm = _llm
COMPACT = lambda h: h
ss.bars({f"第 {i+1} 步": n for i, n in enumerate(lens)}, title="改进后：每一步的上下文长度", unit=" 字符")
```

> 思考：加一个专门的 `line_count` 工具，比让模型读全文再数，好在哪？这和 Claude Code 里 Grep、Glob 这些工具的设计思路一样吗？
