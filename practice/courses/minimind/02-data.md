# 2 数据：模型从哪里学
<!-- minutes: 10 -->
<!-- know: 预训练语料, SFT 对话数据, 对话模板, 序列截断 -->
<!-- gpu: no -->

预训练学「语言本身」（海量普通文本，预测下一个字）；SFT 学「怎么回答问题」（一问一答的对话）。这课只下载前几千条看看样子。

## 预训练语料长什么样
数据在 ModelScope 的 `gongjy/minimind_dataset`。完整的 mini 预训练集 1.2GB，这里只流式读前 3000 行（几 MB）。

```python
import json
path = ss.fetch_head("gongjy/minimind_dataset", "pretrain_t2t_mini.jsonl", 3000, "dataset/pretrain_head.jsonl")
rows = [json.loads(l) for l in open(path, encoding="utf-8")]
ss.table([{"#": i, "文本（前 100 字）": r["text"][:100].replace("\n", " ") + "…"} for i, r in enumerate(rows[:8])],
         title=f"预训练语料样例（共取 {len(rows)} 条）")
```

## 长度分布与截断
训练时每条样本被截到 **340 个 token**（`--max_seq_len`）：太长的被砍掉，太短的用 pad 补齐，pad 的位置不算 loss。

```python
lens = [len(tok(r["text"], add_special_tokens=False).input_ids) for r in rows]
edges = [0, 64, 128, 256, 340, 512, 1024, 10**9]
names = ["<64", "64–128", "128–256", "256–340", "340–512", "512–1024", "≥1024"]
cnt = {n: sum(a <= x < b for x in lens) for n, a, b in zip(names, edges, edges[1:])}
ss.bars(cnt, title="每条样本的 token 数", unit=" 条")
ss.note(f"超过 340 会被截断的样本：{sum(x > 340 for x in lens) / len(lens):.0%}；平均 {sum(lens)/len(lens):.0f} token")
```

> 思考：如果把截断长度从 340 改成 1024，训练会变慢多少？（注意力的计算量和长度是什么关系？）

## SFT 对话数据和对话模板
SFT 数据是多轮对话。训练前要套上**对话模板**：用 `<|im_start|>user` 这类特殊标记告诉模型谁在说话。模型只在 assistant 的回答部分算 loss——它要学的是怎么回答，不是怎么提问。

```python
p2 = ss.fetch_head("gongjy/minimind_dataset", "sft_t2t_mini.jsonl", 200, "dataset/sft_head.jsonl")
conv = json.loads(open(p2, encoding="utf-8").readline())["conversations"]
msgs = [{"role": m["role"], "content": m["content"]} for m in conv]
ss.compare("原始对话（JSON）", json.dumps(msgs, ensure_ascii=False, indent=1)[:800],
           "套上模板后真正喂给模型的文本", tok.apply_chat_template(msgs, tokenize=False)[:800])
```

> 思考：模板里每段 assistant 回答前都有一段 `<think>…</think>`，它是干什么用的？
