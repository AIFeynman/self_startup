# 3 模型结构：64M 参数都花在哪
<!-- minutes: 12 -->
<!-- know: Transformer 解码器, RMSNorm, 自注意力, GQA, RoPE, SwiGLU, 权重共享 -->
<!-- gpu: no -->

minimind 是标准的「只有解码器」的 Transformer，和 Llama、Qwen 同一个家族：
词嵌入 → 8 个相同的 Block（RMSNorm → 注意力 → RMSNorm → 前馈）→ 归一化 → 输出层。

## 搭出模型，数参数
注意输出层和词嵌入**共用一套权重**（tie_word_embeddings）：把 token 变成向量、再把向量变回 token 概率，用的是同一张表。

```python
from model.model_minimind import MiniMindConfig, MiniMindForCausalLM
cfg = MiniMindConfig(hidden_size=768, num_hidden_layers=8)
model = MiniMindForCausalLM(cfg)
groups = {}
for n, p in model.named_parameters():
    k = ("词嵌入（与输出层共用）" if "embed" in n else "注意力" if "self_attn" in n else "前馈 FFN" if "mlp" in n
         else "归一化" if "norm" in n else "输出层" if "lm_head" in n else "其他")
    groups[k] = groups.get(k, 0) + p.numel()
total = sum(groups.values())
ss.bars({k: round(v / 1e6, 2) for k, v in groups.items()}, title=f"参数分布：共 {total/1e6:.1f}M", unit="M", stacked=True)
ss.kv({"层数": cfg.num_hidden_layers, "隐藏维度": cfg.hidden_size, "注意力头 Q": cfg.num_attention_heads,
       "注意力头 KV": cfg.num_key_value_heads, "FFN 中间维度": cfg.intermediate_size, "词表": cfg.vocab_size}, "配置")
```

> 思考：前馈层（FFN）占了一半以上的参数。它在每个 token 上做什么？为什么说「知识」主要存在 FFN 里？

## 一个 Block 里有什么
把第一个 Block 打印出来。几个关键设计：
- **RMSNorm**：比 LayerNorm 少算一个均值，更快，效果差不多。
- **GQA（分组查询注意力）**：8 个 Q 头共享 4 组 K/V，推理时 KV 缓存省一半。
- **RoPE（旋转位置编码）**：不加位置向量，而是把 Q、K 按位置「旋转」一个角度，相对位置自然体现在点积里。
- **SwiGLU**：前馈层用门控（gate × up 再 down），比普通两层 MLP 效果好。

```python
blk = model.model.layers[0]
ss.table([{"模块": n, "形状": "×".join(map(str, p.shape)), "参数量": f"{p.numel():,}"} for n, p in blk.named_parameters()],
         title="第 1 个 Block 的参数")
```

## 改改大小看看
换几组层数和宽度，看参数量怎么变。规律：参数量 ≈ 12 × 层数 × 宽度²（再加上词表 × 宽度）。

```python
sizes = {}
for h, L in [(512, 8), (768, 8), (768, 16), (1024, 16), (1024, 24)]:
    m = MiniMindForCausalLM(MiniMindConfig(hidden_size=h, num_hidden_layers=L))
    sizes[f"宽 {h} · {L} 层"] = round(sum(p.numel() for p in m.parameters()) / 1e6, 1)
    del m
ss.bars(sizes, title="不同配置的参数量", unit="M")
```

> 思考：同样 1 亿参数，「宽而浅」和「窄而深」哪个更好？minimind 的作者为什么选了 768 宽、8 层？
