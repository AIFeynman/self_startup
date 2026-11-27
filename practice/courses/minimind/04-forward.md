# 4 一次前向：模型怎么「猜下一个字」
<!-- minutes: 15 -->
<!-- know: 自回归, logits, softmax, 交叉熵损失, 困惑度 PPL, 注意力图, 因果掩码 -->

语言模型只做一件事：给定前面的 token，输出下一个 token 在整个词表上的概率分布。训练就是让正确答案的概率越来越大。
这一课对比**随机初始化的模型**和作者发布的**预训练模型**，看同一次前向里到底发生了什么。

## 随机模型 vs 预训练模型：猜下一个字
随机模型的权重是乱的，对 6400 个 token 几乎均匀瞎猜（每个约 0.016%）；预训练模型读过十几亿字，会把概率集中到合理的几个字上。
预训练权重第一次用会自动下载（约 138MB）。

```python
import torch, math
from model.model_minimind import MiniMindConfig, MiniMindForCausalLM
tok = ss.tokenizer()
dev = ss.device()
fresh = MiniMindForCausalLM(MiniMindConfig()).to(dev).eval()
pre = ss.load("pretrain")
ids = tok(tok.bos_token + "秦始皇是中国历史上第一位", return_tensors="pt").input_ids.to(dev)
for name, m in [("随机初始化", fresh), ("官方预训练", pre)]:
    with torch.no_grad():
        probs = m(ids).logits[0, -1].float().softmax(-1)
    top = probs.topk(10)
    ss.topk([(tok.decode([i]), p) for p, i in zip(top.values.tolist(), top.indices.tolist())], f"{name}：「秦始皇是中国历史上第一位」后面接什么")
```

## 损失（loss）是怎么算的
**交叉熵** = 正确答案概率的负对数。猜对的概率是 1，loss 是 0；概率越小，loss 越大。
随机模型对每个 token 都是瞎猜，loss 应该 ≈ **ln(6400) ≈ 8.76**——训练开始时看到 loss ≈ 8.8，说明初始化正常。
**困惑度 PPL = e^loss**：可以理解为「平均每一步在多少个候选里犹豫」。

```python
text = "人工智能是研究如何让计算机模拟人类智能的学科。"
ids = tok(tok.bos_token + text, return_tensors="pt").input_ids.to(dev)
rows = []
for name, m in [("随机初始化", fresh), ("官方预训练", pre)]:
    with torch.no_grad():
        loss = m(ids, labels=ids).loss.item()
    rows.append([name, f"{loss:.3f}", f"{math.exp(loss):.1f}"])
rows.append(["理论瞎猜 ln(6400)", f"{math.log(6400):.3f}", "6400"])
ss.table(rows, cols=["模型", "loss", "困惑度 PPL"], title=f"同一句话「{text}」上的交叉熵")
```

> 思考：如果训练开始时 loss 是 20 而不是 8.8，可能哪里出了问题？

## 逐 token 看：哪些字好猜、哪些难猜
把每个位置「正确答案的概率」画出来。标点、固定搭配很好猜；句子开头的新信息很难猜——这就是语言的信息量分布。

```python
with torch.no_grad():
    lp = pre(ids).logits[0, :-1].float().log_softmax(-1)
tgt = ids[0, 1:]
p = lp.gather(-1, tgt[:, None]).squeeze(-1).exp().tolist()
ss.bars([(tok.decode([t]), round(x * 100, 1)) for t, x in zip(tgt.tolist(), p)], title="预训练模型：每个位置猜中正确 token 的概率", unit="%")
```

## 注意力在看哪里
每个 token 通过注意力决定「从前面哪些 token 取信息」。**因果掩码**保证只能看前面、不能偷看后面（所以热力图是下三角）。
下面挂一个钩子，复现模型里的注意力计算，画出第 1 层和最后一层某个头的注意力。

```python
from model.model_minimind import apply_rotary_pos_emb, repeat_kv
def attn_map(m, ids, layer, head):
    got = {}
    attn = m.model.layers[layer].self_attn
    h = attn.register_forward_hook(lambda mod, args, kwargs, out: got.update(x=args[0], pe=args[1]), with_kwargs=True)
    with torch.no_grad():
        m(ids)
        x, (cos, sin) = got["x"], got["pe"]
        b, n, _ = x.shape
        q = attn.q_norm(attn.q_proj(x).view(b, n, attn.n_local_heads, attn.head_dim))
        k = attn.k_norm(attn.k_proj(x).view(b, n, attn.n_local_kv_heads, attn.head_dim))
        q, k = apply_rotary_pos_emb(q, k, cos, sin)
        k = repeat_kv(k, attn.n_rep)
        s = (q.transpose(1, 2) @ k.transpose(1, 2).transpose(-2, -1)) / math.sqrt(attn.head_dim)
        s = s + torch.full((n, n), float("-inf"), device=s.device).triu(1)
    h.remove()
    return s.softmax(-1)[0, head].float().cpu()
sent = "小明把苹果给了小红，因为她饿了。"
ids2 = tok(tok.bos_token + sent, return_tensors="pt").input_ids.to(dev)
labels = [tok.decode([t]) for t in ids2[0]]
for layer, head in [(0, 0), (7, 3)]:
    ss.heat(attn_map(pre, ids2, layer, head), rows=labels, cols=labels, title=f"第 {layer + 1} 层 · 第 {head + 1} 个头：每一行是一个 token 在看谁")
```

> 思考：很多头会把大量注意力放在第一个 token（开始符）上，这被称为「注意力汇聚点（attention sink）」。为什么模型会学出这种模式？

## 数据在模型里怎么流动
给每一层挂钩子记录输出形状：[批大小, 序列长度, 隐藏维度] 一路不变，只有最后的输出层把 768 维映射回 6400 个 token 的分数。

```python
shapes = []
hooks = [m.register_forward_hook(lambda mod, i, o, n=n: shapes.append({"模块": n, "输出形状": "×".join(map(str, (o[0] if isinstance(o, tuple) else o).shape))}))
         for n, m in [("词嵌入", pre.model.embed_tokens), *[(f"Block {i + 1}", l) for i, l in enumerate(pre.model.layers)], ("最终归一化", pre.model.norm), ("输出层", pre.lm_head)]]
with torch.no_grad():
    pre(ids2)
for h in hooks: h.remove()
ss.table(shapes, title=f"「{sent}」（{ids2.shape[1]} 个 token）经过每一层")
```
