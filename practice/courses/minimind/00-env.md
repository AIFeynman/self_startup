# 0 开课：这门课怎么学、机器够不够用
<!-- minutes: 10 -->
<!-- know: GPU 算力, TFLOPS, 混合精度 bf16, 训练算力估算 6ND, Scaling Law -->

[MiniMind](https://github.com/jingyaogong/minimind) 是一个从零训练 64M 小语言模型的开源项目（Apache-2.0），作者用单张 3090 约 2 小时、3 块钱就能训出一个能对话的模型。
它几乎覆盖了大模型训练的完整链路：**分词 → 预训练 → 指令微调（SFT）→ LoRA → 蒸馏 → DPO → PPO / GRPO / CISPO → Agentic RL → MoE → 推理部署**，而且全部是原生 PyTorch 手写，没有黑盒框架。

这门课把它的 README 讲解和代码逐段拆开，每个算法都动手跑一遍。讲解改编自 MiniMind README，图表和数字以你本机实跑为准。

## 这门课怎么跑
- **默认全在你的 Mac 上跑**：用 Apple GPU（MPS）。每个训练算法都用小数据「小跑」几分钟，足够看清它在做什么。
- **只有全量训练放到云上**：标着「云端 GPU · 可选」的格子，是本机要跑好几个小时的完整训练。点运行时会先报价，确认后才开一台阿里云 A10，空闲 30 分钟自动释放。不跑也不影响学完。
- **前面的变量后面能接着用**：同一门课的格子共享一个 Python 进程。中途重启了内核，就从这一课第一格重跑。
- **训练出的权重都在仓库的 `out/` 目录**；后面的课程优先用作者发布的官方权重（第一次用时自动下载，每个约 138MB），这样即使你只小跑，也能看到成熟模型的效果。

```python
ss.env_info()
```

> 思考：「小跑」和「全量训练」除了时间，最大的区别是什么？小跑能说明什么，不能说明什么？

## 实测算力
**TFLOPS** = 每秒万亿次浮点运算。下面做 20 次 4096×4096 的矩阵乘（每次约 2×4096³ 次运算），测出这台机器的实际算力。
训练几乎全是矩阵乘：GPU 有成千上万个并行单元专门干这个，CPU 只有十几个核，同样的活要慢几十倍。
GPU 上通常用 **bf16（半精度）**：每个数只占 2 字节、速度是 fp32 的数倍，指数位和 fp32 一样多不容易溢出，是现代大模型训练的标配。Mac 的 MPS 目前用 fp32 更稳。

```python
import torch, time
dev = ss.device()
dt = torch.bfloat16 if dev == "cuda" else torch.float32
x = torch.randn(4096, 4096, device=dev, dtype=dt)
sync = torch.cuda.synchronize if dev == "cuda" else (torch.mps.synchronize if dev == "mps" else (lambda: None))
for _ in range(3): x @ x
sync(); t = time.time(); n = 20
for _ in range(n): y = x @ x
sync()
tflops = 2 * 4096**3 * n / (time.time() - t) / 1e12
ss.kv({"设备": dev, "精度": str(dt).replace("torch.", ""), "实测矩阵乘算力": f"{tflops:.1f} TFLOPS",
       "对比": "RTX 3090 bf16 约 70、A10 约 125、H100 约 990（理论峰值）"}, "算力实测")
```

## 估一估：训完要多久
经验公式：训练总计算量 ≈ **6 × 参数量 N × 训练 token 数 D**（前向 2ND，反向 4ND）。真实训练里 GPU 不可能一直满载，实际利用率（MFU）一般 30%–50%。

```python
N, D, mfu = 64e6, 2.8e8, 0.35          # minimind-3 约 6400 万参数；mini 预训练集约 2.8 亿 token
hours = 6 * N * D / (tflops * 1e12 * mfu) / 3600
ss.kv({"总计算量": f"{6*N*D:.2e} 次浮点运算", "假设利用率": f"{mfu:.0%}", "本机预训练（mini 数据）预计": f"{hours:.1f} 小时"}, "训练时长估算")
ss.table([["minimind-3（64M）", "≈1.21h / 1.57 元", "≈1.10h / 1.43 元", "≈0.9h / 1.17 元", "≈1.1h / 1.43 元"],
          ["minimind-3-moe（198M，激活 64M）", "≈1.69h / 2.20 元", "≈1.54h / 2.00 元", "≈1.26h / 1.64 元", "≈1.54h / 2.00 元"]],
         cols=["模型", "预训练 mini", "SFT mini", "工具调用", "RLAIF"], title="作者实测：单卡 3090（约 1.3 元/小时）上各阶段 1 个 epoch 的时间和费用")
```

> 思考：作者说用 8 张 H100 能把训练压到分钟级。按 6ND 估算，8×H100 的算力是 3090 的多少倍？为什么实际加速往往达不到这个倍数？

## Zero 路线：最便宜的「能对话」
作者给的最短路线：`pretrain_t2t_mini` + `sft_t2t_mini` 各跑 1 个 epoch，就能从 0 得到一个能对话的 **Zero 模型**。
README 的估算（单卡 3090）：dense 版约 **2.31 小时 / 3.0 元**，MoE 版约 **3.23 小时 / 4.2 元**。这是估算，只用来感受门槛。
下面换算成你这台机器要多久：上一格估的是 dense 预训练（3090 上 1.21 小时），按 3090 上的时间比例放大到整条路线。

```python
zero = {"minimind-3（dense）": (2.31, 3.0), "minimind-3-moe": (3.23, 4.2)}
ss.table([[k, f"{h} h", f"{y} 元", f"{h / 1.21:.2f} 倍", f"≈{hours * h / 1.21:.1f} h"] for k, (h, y) in zero.items()],
         cols=["模型", "3090 时长", "3090 费用", "相当于几次 dense 预训练", "本机粗估"],
         title="Zero 路线：pretrain_t2t_mini + sft_t2t_mini，1 epoch")
```

> 思考：MoE 版总参数 198M、每个 token 只激活 64M，按 6ND 它的计算量应该和 dense 差不多。为什么实际多花了约 40% 的时间？
