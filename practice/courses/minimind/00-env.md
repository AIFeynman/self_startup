# 0 环境检查：这台机器能训多大的模型
<!-- minutes: 5 -->
<!-- know: GPU 算力, TFLOPS, 混合精度 bf16, 训练算力估算 6ND -->
<!-- gpu: yes -->

先确认代码跑在哪、有多少算力，再用一个公式估出训完 minimind 要多久——以后看任何模型都能这样先算一笔账。

## 看看运行环境
训练大模型几乎全是矩阵乘法。GPU 有上万个并行计算单元，专门干这个；CPU 只有几十个核，同样的活要慢几十到几百倍。
这门课默认跑在阿里云的 A10 显卡（24GB 显存）上。

```python
ss.env_info()
```

> 思考：显存 24GB 意味着什么？64M 参数的模型，权重本身只占多少显存（每个参数 2 字节）？剩下的显存都被谁用了？

## 实测算力
**TFLOPS** = 每秒万亿次浮点运算。下面做 20 次 4096×4096 的矩阵乘，每次约 2×4096³ 次运算，算出这张卡实际有多快。
在 GPU 上我们用 **bf16（半精度）**：每个数只占 2 字节，速度是 fp32 的好几倍，而且指数位和 fp32 一样多，不容易溢出——这是现代大模型训练的标配。

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
ss.kv({"设备": dev, "精度": str(dt).replace("torch.", ""), "实测矩阵乘算力": f"{tflops:.1f} TFLOPS"}, "算力实测")
```

## 估一估：训完要多久
经验公式：训练一个模型的总计算量 ≈ **6 × 参数量 N × 训练 token 数 D**（前向 2ND，反向 4ND）。
真实训练里 GPU 不可能一直满载，实际利用率（MFU）一般在 30%–50%。

```python
N = 64e6                     # minimind-3 约 6400 万参数
D = 2.8e8                    # mini 预训练集约 2.8 亿 token（1.2GB 文本）
mfu = 0.35
hours = 6 * N * D / (tflops * 1e12 * mfu) / 3600
ss.kv({"总计算量": f"{6*N*D:.2e} 次浮点运算", "假设利用率": f"{mfu:.0%}", "预计预训练耗时": f"{hours:.1f} 小时",
       "按 3.5 元/小时": f"约 {hours*3.5:.1f} 元"}, "训练时长估算")
```

> 思考：如果参数量翻 10 倍、数据也翻 10 倍，训练时间会变成多少倍？这就是为什么大模型训练要上千张卡。
