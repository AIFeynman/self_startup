# 1 工具设计：描述决定 Agent 用不用得对
<!-- minutes: 12 -->
<!-- know: 工具描述, 错误恢复, 观察反馈 -->

模型看不到工具的代码，只能看到你写的**描述**。描述写得含糊，Agent 就会传错参数、选错工具。工具出错时把错误原样告诉它，它往往能自己纠正。

## 让工具出错，看 Agent 怎么恢复
故意给一个容易用错的工具：`read_file` 只接受相对路径，传错就报错。观察 Agent 拿到错误信息后会不会换个参数重试。

```python
import os
os.makedirs("sandbox", exist_ok=True)
open("sandbox/notes.txt", "w", encoding="utf-8").write("会议纪要：周五发布 v2，负责人小王；风险：数据迁移。\n")

def read_file(path):
    if path.startswith("/"):
        raise ValueError("只接受 sandbox/ 下的相对路径")
    return open(path, encoding="utf-8").read()

TOOLS["read_file"] = (read_file, "读取文件内容，参数 path（相对路径）")
TOOLS["list_dir"] = (lambda path=".": ", ".join(sorted(os.listdir(path))), "列出目录里的文件，参数 path，默认当前目录")
SYSTEM = SYSTEM.split("可用工具：")[0] + "可用工具：\n" + "\n".join(f"- {k}: {d}" for k, (_, d) in TOOLS.items())
run_agent("找到会议纪要文件，告诉我 v2 什么时候发布、谁负责。")
```

> 思考：如果把错误信息吞掉，只返回「失败」两个字，Agent 还能恢复吗？好的错误信息应该包含什么？

## 描述好坏的对比
同一个工具，换一种含糊的描述，看 Agent 的表现差多少。

```python
good = TOOLS["calc"]
TOOLS["calc"] = (good[0], "算东西")
SYSTEM = SYSTEM.split("可用工具：")[0] + "可用工具：\n" + "\n".join(f"- {k}: {d}" for k, (_, d) in TOOLS.items())
run_agent("一个圆的半径是 3.7，面积是多少？保留两位小数。")
TOOLS["calc"] = good
SYSTEM = SYSTEM.split("可用工具：")[0] + "可用工具：\n" + "\n".join(f"- {k}: {d}" for k, (_, d) in TOOLS.items())
```

> 思考：Claude Code 的每个工具描述都有好几段话，还写了「什么时候不要用」。为什么要写这么长？
