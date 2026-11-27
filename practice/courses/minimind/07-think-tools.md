# 7 自适应思考与工具调用
<!-- minutes: 15 -->
<!-- know: 思考模式 think 标签, open_thinking, chat_template, Tool Calling, tool_call 格式, 多轮工具调用 -->

`2026-03` 起，仓库删掉了单独的 `train_reason.py`，也不再发布 `reason_*.pth` 权重。minimind 不再单独训一个「推理模型」，而是把「要不要显式思考」下沉到**对话模板**：模板总会预留 `<think></think>` 结构，同一个模型在推理时用 `open_thinking` 开关切换。
- `open_thinking=0`：模板注入空的 `<think>\n\n</think>`，模型直接回答。
- `open_thinking=1`：模板只注入 `<think>` 开头，模型先输出思考过程，再给答案。
训练时混合「空 think」「显式 reasoning」样本（按 `thinking_ratio` 采样），让模型见过「该想时想、该直答时直答」。

工具调用也已并入主线 SFT 数据（作者用 qwen3-4b 合成约 10 万条，覆盖约 10 个模拟工具：算数、查时间、查天气、汇率……），默认的 `full_sft` 就有基础工具调用能力。

## 模板长什么样：开 / 关思考
同一个问题，看两种开关下喂给模型的文本差在哪。

```python
tok = ss.tokenizer()
msgs = [{"role": "user", "content": "鸡兔同笼，头 10 个，脚 28 只，各几只？"}]
ss.compare("open_thinking=0（直接答）", tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True, open_thinking=False),
           "open_thinking=1（先思考）", tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True, open_thinking=True), title="模板差异")
```

## 让官方 SFT 模型分别直答和思考

```python
model = ss.load("full_sft")
for q in ["鸡兔同笼，头 10 个，脚 28 只，各几只？", "为什么冬天北方比南方干燥？"]:
    ss.compare("直接回答", ss.chat(model, q, max_new_tokens=150), "先思考再回答", ss.chat(model, q, open_thinking=True, max_new_tokens=300), title=q)
```

> 思考：64M 的模型「思考」后答案一定更对吗？显式思考对小模型和大模型的收益为什么差别很大？

三个入口都支持这个开关，底层都是把 `open_thinking` 传给 `apply_chat_template`：
- CLI：`python eval_llm.py --weight full_sft --open_thinking 1`
- OpenAI 兼容接口（`scripts/serve_openai_api.py`，端口 8998）：请求里带 `extra_body={"chat_template_kwargs": {"open_thinking": True}}`；服务端也认顶层 `open_thinking` 和 `enable_thinking`。
- WebUI（`scripts/web_demo.py`）：界面上有「思考」开关，提示写着多轮对话或 Tool Call 共存时思考不稳定。

## 多轮对话与解码速度：eval_llm 的 `--historys` 和 `--show_speed`
`eval_llm.py` 默认每轮只发当前这一句（`--historys 0`），模型记不住上一轮。`--historys N` 携带最近 N 条消息（要是偶数：一问一答算 2 条）。
`--show_speed 1`（默认开）在每轮回答后打印 `[Speed]: xx tokens/s`，即生成 token 数 ÷ 用时。
下面用 `ss.chat` 的 messages 输入复现同样的逻辑：先自我介绍，再问「我叫什么」。

```python
import time
def eval_chat(model, prompts, historys=0):
    conv, rows = [], []
    for q in prompts:
        conv = conv[-historys:] if historys else []          # 和 eval_llm.py 一样：只留最近 historys 条
        conv.append({"role": "user", "content": q})
        st = time.time()
        ans = ss.chat(model, conv, max_new_tokens=80, temperature=0.3)
        speed = len(tok(ans).input_ids) / (time.time() - st)
        conv.append({"role": "assistant", "content": ans})
        rows.append([q, ans, f"{speed:.1f}"])
    return rows

qs = ["我叫小明，今年 18 岁，喜欢打篮球。", "我叫什么名字？喜欢什么运动？"]
for h in (0, 2):
    ss.table(eval_chat(model, qs, historys=h), cols=["问题", "回答", "速度 tokens/s"], title=f"--historys {h}")
```

> 思考：历史越长，每轮要处理的 prompt 越长。为什么 `eval_llm.py` 把 `--historys` 默认设成 0？带太多历史对 64M、训练截断较短的模型有什么影响？

## 工具调用：一次完整的来回
工具定义挂在 system 消息上；模型输出 `<tool_call>{"name": ..., "arguments": ...}</tool_call>`；我们执行工具，把结果作为 `tool` 消息塞回去；模型再看结果作答。
这就是 Agent 的最小闭环——下面用 minimind 仓库 `scripts/eval_toolcall.py` 里的模拟工具跑一遍。

```python
import json, re, sys
sys.path.insert(0, "scripts")
from eval_toolcall import TOOLS, execute_tool, get_tools

def run_tools(model, prompt, names, max_turns=4):
    tools, msgs, trace = get_tools(names), [{"role": "user", "content": prompt}], [{"role": "user", "text": prompt}]
    for _ in range(max_turns):
        out = ss.chat(model, msgs, tools=tools, max_new_tokens=200, temperature=0.3)
        calls = []
        for c in re.findall(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", out, re.S):
            try:
                calls.append(json.loads(c))
            except json.JSONDecodeError:
                pass                      # 小模型偶尔写出坏 JSON：当作这次调用失败（训练时会在格式分上扣分）
        if not calls:
            final = re.sub(r"<think>.*?</think>", "", out, flags=re.S).replace("<|im_end|>", "").strip()
            trace.append({"role": "assistant", "text": final})
            return trace
        msgs.append({"role": "assistant", "content": out.split("<tool_call>")[0], "tool_calls": calls})
        for c in calls:
            trace.append({"role": "thought", "name": c["name"], "text": json.dumps(c.get("arguments", {}), ensure_ascii=False)})
            res = execute_tool(c)
            trace.append({"role": "tool", "name": c["name"], "text": json.dumps(res, ensure_ascii=False)})
            msgs.append({"role": "tool", "content": json.dumps(res, ensure_ascii=False)})
    return trace

ss.trace(run_tools(model, "帮我算一下 256 乘以 37 等于多少", ["calculate_math", "get_current_time"]), title="单次工具调用")
ss.trace(run_tools(model, "帮我生成一个1到1000的随机数，然后计算它的平方", ["random_number", "calculate_math", "text_length"]), title="两步工具调用")
```

> 思考：模型怎么知道该调哪个工具、参数怎么填？它「看到」的是什么？（回去看上面模板里 `# Tools` 那段。）

`scripts/eval_toolcall.py` 自己也能跑这个闭环：`cd scripts && python eval_toolcall.py --weight full_sft` 用本地权重（`--backend local`，默认）。
加 `--backend api` 则改走 OpenAI 兼容接口（默认 `--api_base_url http://localhost:11434/v1`，即本机 ollama；`--api_model jingyaogong/minimind-3:latest`）：工具调用先从响应的 `tool_calls` 字段里取（取不到再从文本里解析 `<tool_call>`），工具结果带 `tool_call_id` 塞回去。模型、工具、判分逻辑都一样，只换推理后端。这门课不起 API 服务，这里只做说明。

## 跑一遍作者的 8 个测试用例
统计每个任务是否调了正确的工具。作者坦言：工具只有约 10 个模拟工具，「还谈不上明确的泛化能力」。同时开思考和工具调用时，模型也不太会稳定输出思考——训练数据里缺少两者同时出现的样本。

```python
from eval_toolcall import TEST_CASES
rows = []
for case in TEST_CASES:
    tr = run_tools(model, case["prompt"], case["tools"])
    used = [s["name"] for s in tr if s["role"] == "thought"]
    rows.append([case["prompt"], "、".join(case["tools"]), "、".join(used) or "（没调工具）", tr[-1]["text"][:60] if tr[-1]["role"] == "assistant" else "（超过轮数）"])
ss.table(rows, cols=["任务", "可用工具", "实际调用", "最终回答"], title="full_sft 的工具调用表现")
```
