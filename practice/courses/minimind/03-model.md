# 3 模型结构：64M 参数都花在哪
<!-- minutes: 20 -->
<!-- know: Transformer 解码器, Pre-Norm, RMSNorm, 自注意力, GQA 分组查询注意力, RoPE 旋转位置编码, SwiGLU, 权重共享, MobileLLM 深而窄 -->

minimind-3 是标准的 **Decoder-Only Transformer**，整体配置向 Qwen3 生态对齐，方便转换到 transformers / llama.cpp / ollama / vllm：
- **Pre-Norm + RMSNorm**：先归一化再进注意力 / 前馈层，训练更稳。
- **SwiGLU** 激活的前馈层。
- **RoPE** 旋转位置编码，支持 **YaRN** 长度外推。
- `q_heads=8`、`kv_heads=4`（GQA），`max_position_embeddings=32768`，`rope_theta=1e6`。
- **QK-Norm**：Q、K 在旋转之前各做一次 RMSNorm，防止注意力分数数值爆炸（Qwen3 同款）。

| 模型 | 参数 | 词表 | 层数 | d_model | kv_heads | q_heads | 备注 |
|---|---|---|---|---|---|---|---|
| minimind-3 | 64M | 6400 | 8 | 768 | 4 | 8 | Dense |
| minimind-3-moe | 198M（激活 64M） | 6400 | 8 | 768 | 4 | 8 | 4 专家 / top-1 |
| minimind2-small | 26M | 6400 | 8 | 512 | 2 | 8 | 历史版本 |
| minimind2-moe | 145M | 6400 | 8 | 640 | 2 | 8 | 历史版本（MoE） |
| minimind2 | 104M | 6400 | 16 | 768 | 2 | 8 | 历史版本 |

## 搭出模型，数参数
注意输出层和词嵌入**共用一套权重**（tie_word_embeddings）：token → 向量、向量 → token 概率，用的是同一张表。这张表是 6400 × 768 ≈ 492 万参数；不共享就得再来一张。词表换成 Qwen2 的 151,643，一张就是约 1.16 亿，两张约 2.3 亿（第 1 课算过）。

```python
import torch, math
from model.model_minimind import MiniMindConfig, MiniMindForCausalLM
tok = ss.tokenizer()
cfg = MiniMindConfig(hidden_size=768, num_hidden_layers=8)
model = MiniMindForCausalLM(cfg)
groups = {}
for n, p in model.named_parameters():
    k = ("词嵌入（与输出层共用）" if "embed" in n else "注意力" if "self_attn" in n else "前馈 FFN" if "mlp" in n
         else "归一化" if "norm" in n else "其他")
    groups[k] = groups.get(k, 0) + p.numel()
ss.bars({k: round(v / 1e6, 2) for k, v in groups.items()}, title=f"参数分布：共 {sum(groups.values())/1e6:.1f}M", unit="M", stacked=True)
ss.kv({"层数": cfg.num_hidden_layers, "隐藏维度": cfg.hidden_size, "注意力头 Q / KV": f"{cfg.num_attention_heads} / {cfg.num_key_value_heads}",
       "每头维度": cfg.head_dim, "FFN 中间维度": f"{cfg.intermediate_size}（≈ 768×π）", "RoPE θ": cfg.rope_theta, "最大位置": cfg.max_position_embeddings}, "配置")
```

> 思考：前馈层占了七成参数。它对每个 token 做什么？为什么常说「知识」主要存在 FFN 里？

## RMSNorm：自己算一遍
LayerNorm 要减均值、除标准差；**RMSNorm** 只除以均方根（不减均值），少一步计算，效果差不多：
`y = x / sqrt(mean(x²) + ε) × weight`。下面手算，和模型里的模块比对。

```python
norm = model.model.layers[0].input_layernorm
x = torch.randn(2, 5, 768)
mine = x / torch.sqrt(x.pow(2).mean(-1, keepdim=True) + norm.eps) * norm.weight
ss.kv({"手算 vs 模块 最大误差": f"{(mine - norm(x)).abs().max().item():.2e}",
       "归一化前每个向量的均方根": f"{x.pow(2).mean(-1).sqrt().mean():.3f}",
       "归一化后": f"{mine.pow(2).mean(-1).sqrt().mean():.3f}"}, "RMSNorm")
```

## GQA：为什么 8 个 Q 头只配 4 组 K/V
推理时每生成一个 token，都要把之前所有 token 的 K、V 存下来（**KV 缓存**），避免重复计算。上下文一长，KV 缓存就是显存大头。
**GQA（分组查询注意力）**让多个 Q 头共享一组 K/V：minimind 8 个 Q 头共享 4 组 K/V，缓存直接减半，效果损失很小。

```python
def kv_cache_mb(kv_heads, ctx, layers=8, head_dim=96, bytes_=2):
    return 2 * layers * kv_heads * head_dim * ctx * bytes_ / 2**20
ss.table([[ctx, f"{kv_cache_mb(8, ctx):.1f}", f"{kv_cache_mb(4, ctx):.1f}", f"{kv_cache_mb(1, ctx):.1f}"] for ctx in (512, 2048, 8192, 32768)],
         cols=["上下文长度", "MHA 8 组 KV (MB)", "GQA 4 组 (MB)", "MQA 1 组 (MB)"], title="单条序列的 KV 缓存大小（bf16）")
attn = model.model.layers[0].self_attn
ss.kv({"q_proj": "×".join(map(str, attn.q_proj.weight.shape)), "k_proj": "×".join(map(str, attn.k_proj.weight.shape)),
       "v_proj": "×".join(map(str, attn.v_proj.weight.shape)), "o_proj": "×".join(map(str, attn.o_proj.weight.shape))}, "注意力投影矩阵形状（输出×输入）")
```

> 思考：K、V 的投影矩阵只有 Q 的一半大。GQA 省下的是参数、计算，还是推理时的显存？哪个最重要？

## RoPE：位置是「转」进去的
RoPE 不往输入里加位置向量，而是把每个位置的 Q、K 按位置 **旋转** 一个角度（不同维度转速不同）。
妙处在于：两个 token 的点积只和它们的**相对距离**有关。下面验证：把同样的 q、k 一起挪到不同位置，点积不变。

```python
from model.model_minimind import precompute_freqs_cis, apply_rotary_pos_emb
cos, sin = precompute_freqs_cis(dim=96, end=4096, rope_base=1e6)
q, k = torch.randn(1, 1, 1, 96), torch.randn(1, 1, 1, 96)
def score(pq, pk):
    qe, _ = apply_rotary_pos_emb(q, q, cos[pq:pq + 1], sin[pq:pq + 1])
    _, ke = apply_rotary_pos_emb(k, k, cos[pk:pk + 1], sin[pk:pk + 1])
    return (qe * ke).sum().item()
ss.table([[f"q 在 {a}，k 在 {b}", b - a, f"{score(a, b):.4f}"] for a, b in [(0, 5), (100, 105), (2000, 2005), (0, 50), (300, 350)]],
         cols=["位置", "相对距离", "点积"], title="相对距离相同 → 点积相同")
ss.heat(cos[:64, :48:2], rows=list(range(64)), cols=list(range(0, 48, 2)), title="cos(位置 × 频率)：低维转得快（左），高维转得慢（右）")
```

> 思考：`rope_theta=1e6` 比原版 Transformer 的 1e4 大很多。θ 越大，高维转得越慢——这对处理长文本有什么好处？

## SwiGLU 与「深而窄」
前馈层用 SwiGLU：`down( silu(gate(x)) × up(x) )`，三块矩阵，比普通两层 MLP 多一个「门」。
层数和宽度怎么分？[MobileLLM](https://arxiv.org/pdf/2402.14905) 发现：参数量固定时，小模型**深而窄**往往比宽而浅好（125M 时 30~42 层优于 12 层）。但「窄」有下限：`d_model < 512` 时词嵌入太窄，固定头数下每个头（d_head）也太窄，加层也补不回来。反过来，`d_model > 1536` 之后，继续加层往往比继续加宽更划算。minimind 选 768 宽、8 层：更浅训练更快，768 也不至于窄到模式崩溃，是训练速度、稳定性和效果的折中。

```python
sizes = {}
for h, L in [(512, 8), (768, 8), (768, 16), (512, 24), (1024, 16)]:
    m = MiniMindForCausalLM(MiniMindConfig(hidden_size=h, num_hidden_layers=L))
    sizes[f"宽 {h} · {L} 层 · 每头 {h // 8} 维"] = round(sum(p.numel() for p in m.parameters()) / 1e6, 1)
    del m
ss.bars(sizes, title="不同宽度和层数的参数量（参数 ≈ 12 × 层数 × 宽度² + 词表 × 宽度）", unit="M")
```

> 思考：「宽 512 · 24 层」和「宽 768 · 8 层」参数量接近。前者训练时每步更快还是更慢？为什么？
