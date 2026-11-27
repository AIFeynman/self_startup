# 4 一次前向：模型怎么「猜下一个字」
<!-- minutes: 10 -->
<!-- know: 自回归, logits, softmax, 交叉熵损失, 困惑度 -->
<!-- gpu: no -->

语言模型只做一件事：给定前面的 token，输出下一个 token 的概率分布。训练就是让正确答案的概率越来越大。

## 随机初始化的模型在猜什么
还没训练的模型，权重是随机的，对 6400 个 token 的猜测几乎是均匀分布——每个大约 1/6400 ≈ 0.016%。

```python
import torch, math
model.eval()
ids = tok("今天天气", return_tensors="pt").input_ids
with torch.no_grad():
    out = model(ids)
probs = out.logits[0, -1].float().softmax(-1)
top = probs.topk(10)
ss.topk([(tok.decode([i]), p) for p, i in zip(top.values.tolist(), top.indices.tolist())], "随机模型：「今天天气」后面接什么")
ss.kv({"输入 token 数": ids.shape[1], "logits 形状": "×".join(map(str, out.logits.shape)), "最高概率": f"{top.values[0]:.4%}"})
```

## 损失（loss）是怎么算的
**交叉熵** = 正确答案概率的负对数：猜对的概率是 1，loss 就是 0；概率越小，loss 越大。
随机模型对每个 token 都是瞎猜，loss 应该约等于 **ln(6400) ≈ 8.76**。训练开始时看到 loss ≈ 8.8，说明一切正常。

```python
text = "人工智能是研究如何让计算机模拟人类智能的学科。"
ids = tok(text, return_tensors="pt").input_ids
with torch.no_grad():
    loss = model(ids, labels=ids).loss.item()
ss.kv({"随机模型的 loss": f"{loss:.3f}", "理论值 ln(6400)": f"{math.log(6400):.3f}", "困惑度 e^loss": f"{math.exp(loss):.0f}",
       "含义": "相当于每一步在约这么多个 token 里瞎猜"}, "交叉熵")
```

> 思考：如果训练开始时 loss 是 20 而不是 8.8，可能哪里出了问题？

## 数据在模型里怎么流动
给每一层挂一个钩子，记录输出形状：[批大小, 序列长度, 隐藏维度] 一路不变，只有最后的输出层把 768 维映射回 6400 个 token 的分数。

```python
shapes = []
hooks = [m.register_forward_hook(lambda mod, i, o, n=n: shapes.append({"模块": n, "输出形状": "×".join(map(str, (o[0] if isinstance(o, tuple) else o).shape))}))
         for n, m in [("词嵌入", model.model.embed_tokens), *[(f"Block {i}", l) for i, l in enumerate(model.model.layers)], ("最终归一化", model.model.norm), ("输出层", model.lm_head)]]
with torch.no_grad():
    model(ids)
for h in hooks: h.remove()
ss.table(shapes, title=f"「{text[:8]}…」({ids.shape[1]} 个 token) 经过每一层")
```
