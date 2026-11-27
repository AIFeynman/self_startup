# 0 Agent 就是一个循环
<!-- minutes: 10 -->
<!-- know: Agent 循环, 工具调用, 观察, 终止条件 -->

聊天机器人回答一次就结束；Agent 会**反复**做三件事：想下一步 → 调用工具 → 看结果，直到任务完成。下面从零写一个。
这门课的模型调用走本机 Claude（`ss.llm`），不需要 API key。

## 先问一次模型
单次调用：给输入、拿输出。模型自己不能算精确的数、不能读你的文件——它只会生成文字。

```python
ans = ss.llm("17 的 23 次方是多少？只回答数字。")
ss.compare("模型直接回答", ans.strip(), "Python 精确计算", str(17 ** 23), title="模型不擅长的事")
```

> 思考：模型答错（或者答对）的原因是什么？如果它能「用计算器」，问题就解决了吗？

## 给它工具，写出循环
约定一个格式：模型每一步只输出一段 JSON——要么调用工具 `{"tool": 名字, "args": {...}}`，要么给最终答案 `{"final": ...}`。
我们执行工具，把结果作为「观察」塞回去，再问下一步。这就是 Agent 的全部骨架。

```python
import json, re, math

TOOLS = {
    "calc": (lambda expr: str(eval(expr, {"__builtins__": {}}, {"math": math})), "计算 Python 数学表达式，参数 expr，例如 {\"expr\": \"17**23\"}"),
    "word_count": (lambda text: str(len(text.split())), "统计英文单词数，参数 text"),
}
SYSTEM = ("你是一个会用工具的助手。每一步只输出一段 JSON，不要别的文字。\n"
          "调用工具：{\"tool\": \"名字\", \"args\": {...}}；给出最终答案：{\"final\": \"答案\"}。\n可用工具：\n"
          + "\n".join(f"- {k}: {d}" for k, (_, d) in TOOLS.items()))

def parse(text):
    m = re.search(r"\{.*\}", text, re.S)
    return json.loads(m.group(0)) if m else {"final": text}

COMPACT = lambda h: h          # 第 2 课会换成「压缩历史」

def run_agent(task, max_steps=6):
    history, steps = f"任务：{task}", [{"role": "user", "text": task}]
    view = ss.trace(steps, title=f"Agent 运行轨迹：{task}")      # 每走一步原地更新
    for _ in range(max_steps):
        history = COMPACT(history)
        act = parse(ss.llm(history, system=SYSTEM))
        if "final" in act:
            steps.append({"role": "assistant", "text": str(act["final"])})
            break
        name, args = act.get("tool"), act.get("args", {})
        steps.append({"role": "thought", "name": name, "text": json.dumps(args, ensure_ascii=False)})
        view.update(title=f"Agent 运行轨迹：{task}", steps=steps)
        try:
            obs = TOOLS[name][0](**args)
        except Exception as e:
            obs = f"工具出错：{e!r}"
        steps.append({"role": "tool", "name": name, "text": obs})
        view.update(title=f"Agent 运行轨迹：{task}", steps=steps)
        history += f"\n调用 {name}({json.dumps(args, ensure_ascii=False)}) → 观察：{obs}"
    view.update(title=f"Agent 运行轨迹：{task}", steps=steps)

run_agent("17 的 23 次方是多少？再算出它的各位数字之和。")
```

> 思考：这个循环里，「记忆」存在哪里？如果任务要 100 步，会遇到什么问题？

## 自己出个题
改下面的任务，看 Agent 怎么拆步骤。试试一个需要连续用两个工具的任务。

```python
run_agent("计算 2 的 100 次方有几位数，再数一下这句话有几个英文单词：the quick brown fox jumps over the lazy dog")
```
