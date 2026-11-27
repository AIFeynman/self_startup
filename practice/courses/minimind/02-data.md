# 2 数据：每个训练阶段吃什么
<!-- minutes: 15 -->
<!-- know: 预训练语料, SFT 对话数据, 对话模板, 偏好数据, RLAIF 数据, max_seq_len 截断 -->

不同训练阶段吃不同形状的数据：预训练吃大段普通文本，SFT 吃多轮对话，DPO 吃「好回答 vs 差回答」，强化学习吃只有问题、答案由模型现场生成的对话。
所有数据都在 ModelScope 的 `gongjy/minimind_dataset`，这课每种只流式读前几十到几千行看样子。

| 文件 | 大小 | 用途 |
|---|---|---|
| `pretrain_t2t_mini.jsonl` ✨ | 1.2GB | 轻量预训练，快速复现 |
| `pretrain_t2t.jsonl` | 10GB | 主线完整预训练 |
| `sft_t2t_mini.jsonl` ✨ | 1.6GB | 轻量 SFT（已混入工具调用样本） |
| `sft_t2t.jsonl` | 14GB | 主线完整 SFT |
| `dpo.jsonl` | 53MB | DPO 偏好对齐 |
| `rlaif.jsonl` ✨ | 24MB | PPO / GRPO / CISPO 强化学习 |
| `agent_rl.jsonl` | 86MB | 多轮工具调用的 Agentic RL |
| `agent_rl_math.jsonl` | 18MB | 纯数学的 Agentic RL（可验证奖励） |

作者推荐：最快从 0 训出能对话的 Zero 模型 = `pretrain_t2t_mini` + `sft_t2t_mini`；完整复现 = `pretrain_t2t` + `sft_t2t` + `rlaif / agent_rl`。

## 预训练语料：一行一段文本
格式就是 `{"text": "..."}`。来源包括通用文本、对话整理、蒸馏补充语料和各种**宽松开源协议**的数据，主要来自[匠数大模型数据集](https://www.modelscope.cn/datasets/deepctrl/deepctrl-sft-data)、[Magpie-Align](https://www.modelscope.cn/organization/Magpie-Align) 等公开数据源，进训练前做过清洗、去重、长度控制和格式统一。
预训练的目标只有一个：**词语接龙**——看前面的字，猜下一个字。

```python
import json
tok = ss.tokenizer()
path = ss.fetch_head("gongjy/minimind_dataset", "pretrain_t2t_mini.jsonl", 3000, "dataset/pretrain_head.jsonl")
rows = [json.loads(l) for l in open(path, encoding="utf-8")]
ss.table([{"#": i, "文本（前 100 字）": r["text"][:100].replace("\n", " ") + "…"} for i, r in enumerate(rows[:8])],
         title=f"预训练语料样例（共取 {len(rows)} 条）")
```

## 长度分布与截断：max_seq_len 怎么定
训练时每条样本截到 `max_seq_len` 个 **token**（不是字符）：太长的被砍掉语义，太短的用 pad 补齐浪费算力。没有完美值，只能在算力和语义完整之间找平衡。
作者推荐：mini 数据集用 768 左右，完整预训练集用 380 左右。
注意两种「长度」：`max_seq_len` 是 **token 数**；数据集文件名里标的「最大长度」（比如早期的 `sft_512 / sft_1024`）是**字符数**。README 给的经验值是中文 1.5~1.7 字符/token，100 个字符粗算 100/1.5≈67 个 token；不同数据会有波动，下面顺手实测一下。

```python
lens = [len(tok(r["text"], add_special_tokens=False).input_ids) for r in rows]
edges = [0, 64, 128, 256, 384, 512, 768, 10**9]
names = ["<64", "64–128", "128–256", "256–384", "384–512", "512–768", "≥768"]
ss.bars({n: sum(a <= x < b for x in lens) for n, a, b in zip(names, edges, edges[1:])}, title="每条样本的 token 数", unit=" 条")
for L in (340, 512, 768):
    cut = sum(x > L for x in lens) / len(lens)
    waste = sum(max(0, L - x) for x in lens) / (L * len(lens))
    ss.note(f"max_seq_len = {L}：{cut:.0%} 的样本被截断，补齐浪费 {waste:.0%} 的计算")
chars = sum(len(r["text"]) for r in rows)
ss.kv({"总字符数": chars, "总 token 数": sum(lens), "实测 字符/token": f"{chars / sum(lens):.2f}",
       "文件名写 512 字符，约等于": f"{512 * sum(lens) / chars:.0f} token"}, "字符数 ↔ token 数")
```

> 思考：长度从 340 提到 1024，注意力部分的计算量大约变成几倍？为什么作者说「更长上下文只需准备少量长样本做增量微调，推理时再用 YaRN 外推」？

## SFT 数据：多轮对话（含工具调用）
SFT 数据是 `conversations` 列表，角色有 `system / user / assistant / tool`。训练前套上**对话模板**，用 `<|im_start|>user` 这类特殊标记告诉模型谁在说话。
工具调用样本里，`tools` 挂在 system 上，`tool_calls` 挂在 assistant 上，模板会把它们展开成 `<tool_call>…</tool_call>` 和 `<tool_response>…</tool_response>`。

SFT 数据来源：高质量指令跟随数据、公开对话数据、模型蒸馏合成数据和协议友好的开源数据集，进主线前统一成多轮对话格式。其中有大量合成数据，比如作者用 `qwen3-4b` 合成的约 10 万条 tool call 数据、`qwen3` 系列的 reasoning 数据。
社区来源主要是：

| 来源 | 链接 |
|---|---|
| 匠数大模型数据集 | [ModelScope](https://www.modelscope.cn/datasets/deepctrl/deepctrl-sft-data) |
| Magpie-Align | [ModelScope](https://www.modelscope.cn/organization/Magpie-Align) |
| R1-Distill-SFT | [ModelScope](https://www.modelscope.cn/datasets/AI-ModelScope/R1-Distill-SFT) |
| COIG | [HuggingFace](https://huggingface.co/datasets/BAAI/COIG) |
| Step-3.5-Flash-SFT | [HuggingFace](https://huggingface.co/datasets/stepfun-ai/Step-3.5-Flash-SFT) |

协议：发布版本要满足来源协议的可传递性，遵守 Apache-2.0、CC-BY-NC-2.0 等要求。CC-BY-NC 是**非商业**协议——自己学习没问题，拿去做商用产品前要逐个核对来源协议。

```python
p2 = ss.fetch_head("gongjy/minimind_dataset", "sft_t2t_mini.jsonl", 2000, "dataset/sft_head.jsonl")
sft = [json.loads(l)["conversations"] for l in open(p2, encoding="utf-8")]
ss.kv({"取到对话": len(sft), "含思考过程（reasoning_content）的": sum(any(m.get("reasoning_content") for m in c) for c in sft),
       "平均消息数": f"{sum(len(c) for c in sft) / len(sft):.1f}"}, "SFT 数据概况（前 2000 条；工具调用样本在文件更后面）")
am = json.loads(open(ss.fetch_head("gongjy/minimind_dataset", "agent_rl_math.jsonl", 30, "dataset/agent_math_head.jsonl"), encoding="utf-8").readline())
tools = json.loads(am["conversations"][0]["tools"])
msgs = [{"role": "system", "content": ""},
        {"role": "user", "content": "帮我算一下 256 乘以 37 等于多少"},
        {"role": "assistant", "content": "", "tool_calls": [{"name": "calculate_math", "arguments": {"expression": "256 * 37"}}]},
        {"role": "tool", "content": json.dumps({"result": "9472"})},
        {"role": "assistant", "content": "256 乘以 37 等于 9472。"}]
ss.compare("原始对话（JSON，工具挂在 system 上）", json.dumps([{**msgs[0], "tools": [t["function"]["name"] for t in tools]}, *msgs[1:]], ensure_ascii=False, indent=1),
           "套上模板后真正喂给模型的文本", tok.apply_chat_template(msgs, tokenize=False, tools=tools)[-900:], title="一条工具调用样本")
```

> 思考：模板里每段 assistant 回答前都有 `<think>…</think>`，哪怕里面是空的。为什么要保留这个空壳？（第 7 课会揭晓。）

## 偏好数据和强化学习数据
- **DPO**：每条有 `chosen`（更好的回答）和 `rejected`（较差的回答），问题相同。模型学「往好的那边靠」。
- **RLAIF**：格式和 SFT 一样，但 assistant 内容不用——训练时由模型现场生成几个回答，再由奖励模型或规则打分。它的来历很简单：从 SFT 数据里按总长度和对话轮次筛出一批，把**最后一个 assistant 留空**，留给 rollout 阶段续写。
- **Agentic RL**：在对话基础上多了工具列表和 `gt`（最终要命中的标准答案），奖励在多轮调用结束后统一结算。

```python
dpo = [json.loads(l) for l in open(ss.fetch_head("gongjy/minimind_dataset", "dpo.jsonl", 30, "dataset/dpo_head.jsonl"), encoding="utf-8")]
d0 = next(d for d in dpo if any("一" <= ch <= "鿿" for ch in d["chosen"][0]["content"])) if any(any("一" <= ch <= "鿿" for ch in d["chosen"][0]["content"]) for d in dpo) else dpo[0]
ss.compare("chosen（偏好的）", d0["chosen"][-1]["content"][:600], "rejected（不偏好的）", d0["rejected"][-1]["content"][:600],
           title="DPO 样本 · 问题：" + d0["chosen"][0]["content"][:60])
rl = [json.loads(l) for l in open(ss.fetch_head("gongjy/minimind_dataset", "rlaif.jsonl", 30, "dataset/rlaif_head.jsonl"), encoding="utf-8")]
ag = [json.loads(l) for l in open(ss.fetch_head("gongjy/minimind_dataset", "agent_rl_math.jsonl", 30, "dataset/agent_math_head.jsonl"), encoding="utf-8")]
ss.table([["RLAIF", ", ".join(rl[0].keys()), rl[0]["conversations"][0]["content"][:80]],
          ["Agentic RL（数学）", ", ".join(ag[0].keys()), json.dumps({k: v for k, v in ag[0].items() if k != "conversations"}, ensure_ascii=False)[:160]]],
         cols=["数据", "字段", "示例"], title="强化学习数据长什么样")
ss.table([[i, len(c["conversations"]), " → ".join(m["role"] for m in c["conversations"]), repr(c["conversations"][-1]["content"])] for i, c in enumerate(rl[:6])],
         cols=["#", "消息数", "角色顺序", "最后一个 assistant 的内容"], title="RLAIF：最后一个 assistant 都是空的，等模型现场生成")
```

> 思考：RLAIF 数据为什么不需要标准答案？Agentic RL 为什么又需要 `gt`？两种奖励各适合什么任务？
