# 14 MoE：参数多、算得少
<!-- minutes: 25 -->
<!-- know: 混合专家 MoE, 路由 router, top-k 路由, 负载均衡辅助损失, 激活参数, 直通估计 straight-through -->

**MoE（混合专家）** 把前馈层换成多个「专家」（各是一个小 FFN），再加一个**路由器**：每个 token 只送给得分最高的 k 个专家计算。
于是模型的**总参数**很大（容量大、能装更多知识），但每个 token 实际**激活的参数**不多（计算量小）。

minimind-3-moe：4 个专家、top-1 路由、去掉共享专家（兼容 Qwen3-MoE 风格），**总参数 198M，激活 64M**——和 dense 版每个 token 的计算量相同。

一个反直觉的地方：大家都说「MoE 推理更快」，但**训练时**专家多了反而慢很多。token 要先按专家分桶、再分别前向，原生 PyTorch 里 kernel 启停和调度开销会急剧变重，要靠 Triton 自定义 kernel、DeepSpeed-MoE、Megatron 这类融合算子优化。作者保留原生 PyTorch 的普适性，选了 `4 专家 / top-1` 这个甜点：只比 dense 慢约 50%。

## 路由器怎么分配 token
看 `model/model_minimind.py` 的 `MOEFeedForward`：
1. 路由器（一个 Linear）给每个 token 打出 4 个专家的分数，softmax 成概率；
2. 取 top-1 的专家；
3. top-1 时权重固定为 1.0，但用**直通估计**（`top1 - top1.detach() + 1.0`）让梯度还能传回路由器；
4. 训练时加**负载均衡辅助损失**：`(每个专家分到的 token 比例 · 平均路由概率)` 求和 × 专家数，防止所有 token 都挤到一个专家。

```python
import torch, time, inspect
from model.model_minimind import MOEFeedForward
src = inspect.getsource(MOEFeedForward.forward)
ss.show("table", title="MOEFeedForward.forward（仓库原码）", cols=["代码"], rows=[[l] for l in src.splitlines() if l.strip()])
```

## 加载官方 MoE 模型，数参数
第一次会下载 `full_sft_768_moe.pth`（约 407MB）。

```python
tok = ss.tokenizer()
moe = ss.load("full_sft", moe=True)
dense = ss.load("full_sft")
total = sum(p.numel() for p in moe.parameters())
expert = sum(p.numel() for n, p in moe.named_parameters() if ".experts." in n)
cfg = moe.config
active = total - expert + expert // cfg.num_experts * cfg.num_experts_per_tok
ss.kv({"专家数 / 每 token 激活": f"{cfg.num_experts} / {cfg.num_experts_per_tok}", "总参数": f"{total / 1e6:.1f}M", "每个 token 激活": f"{active / 1e6:.1f}M",
       "dense 版参数": f"{sum(p.numel() for p in dense.parameters()) / 1e6:.1f}M", "辅助损失系数": cfg.router_aux_loss_coef}, "minimind-3-moe")
```

## 看看每个专家都在处理什么
给每一层的路由器挂钩子，统计不同类型文本里 token 被送到哪个专家。专家会不会自发「分工」？

```python
texts = {"中文百科": "长江是中国第一长河，发源于青藏高原，最终注入东海。", "英文": "The quick brown fox jumps over the lazy dog near the river bank.",
         "代码": "def fib(n):\n    return n if n < 2 else fib(n - 1) + fib(n - 2)", "数学": "计算 (12 + 35) × 4 − 18 ÷ 3 的结果。"}
picks = {}
hooks = []
for li, layer in enumerate(moe.model.layers):
    hooks.append(layer.mlp.gate.register_forward_hook(lambda mod, i, o, li=li: picks.setdefault(li, []).append(o.softmax(-1).argmax(-1).flatten().cpu())))
rows = []
for name, t in texts.items():
    picks.clear()
    ids = tok(t, return_tensors="pt").input_ids.to(ss.device())
    with torch.no_grad():
        moe(ids)
    for li in (0, 3, 7):
        c = torch.bincount(picks[li][0], minlength=cfg.num_experts).tolist()
        rows.append([name, f"第 {li + 1} 层", *[f"{x / sum(c):.0%}" for x in c]])
for h in hooks: h.remove()
ss.table(rows, cols=["文本类型", "层", *[f"专家 {i}" for i in range(cfg.num_experts)]], title="各类文本的 token 被路由到哪个专家")
```

> 思考：如果某一层所有 token 都去了同一个专家，会发生什么？负载均衡损失为什么是「分到的比例 × 平均概率」而不是直接让比例相等？

## 速度对比：dense vs MoE（本机推理）

```python
def speed(m, n=64):
    ids = tok(tok.apply_chat_template([{"role": "user", "content": "介绍一下中国的四大发明"}], tokenize=False, add_generation_prompt=True), return_tensors="pt").input_ids.to(ss.device())
    with torch.no_grad():
        m.generate(ids, max_new_tokens=8, do_sample=False)
        t = time.time()
        out = m.generate(ids, max_new_tokens=n, do_sample=False, eos_token_id=-1)
    return (out.shape[1] - ids.shape[1]) / (time.time() - t)
ss.bars({"dense（64M）": round(speed(dense), 1), "MoE（198M，激活 64M）": round(speed(moe), 1)}, title="本机生成速度", unit=" token/s")
q = "推荐一些中国的美食"
ss.compare("dense", ss.chat(dense, q, max_new_tokens=120), "MoE", ss.chat(moe, q, max_new_tokens=120), title=q)
```

> 思考：作者的横评里 MoE 版「表达最流畅、结构感最好」，但知识幻觉照样严重（说大熊猫吃海产品）。多出来的 134M 参数买到了什么，没买到什么？

## 本机小跑一次 MoE 预训练
同一个 `train_pretrain.py`，加 `--use_moe 1` 就换成 MoE 结构。训练循环里 `loss = res.loss + res.aux_loss`：日志里的 `loss` 是总损失，`logits_loss` 是交叉熵，`aux_loss` 是 8 层负载均衡损失之和（已乘系数 `router_aux_loss_coef = 5e-4`）。
这里只取 320 条、序列截到 256，20 步左右，Mac 上约 2 分钟。权重存到 `out/moe_mine_768_moe.pth`，不碰官方权重。脚本还会在 `checkpoints/` 存一份带优化器状态的续训文件 `moe_mine_768_moe_resume.pth`（约 2.4GB），用不上可以删。

```python long
lines = open(ss.fetch_head("gongjy/minimind_dataset", "pretrain_t2t_mini.jsonl", 3000, "dataset/pretrain_head.jsonl"), encoding="utf-8").readlines()[:320]
open("dataset/pretrain_320.jsonl", "w", encoding="utf-8").writelines(lines)
ss.train_live(f"python train_pretrain.py --use_moe 1 --data_path ../dataset/pretrain_320.jsonl --epochs 1 --batch_size 16 --max_seq_len 256 "
              f"--log_interval 1 --save_weight moe_mine --save_dir ../out --num_workers 0 --device {ss.device()}",
              cwd="trainer", title="MoE 小规模预训练（320 条，本机）", metrics=("loss", "aux_loss"))
```

`aux_loss` 的数值很小（系数只有 5e-4），和 loss 画在一起几乎贴着 0。换个看法：把每层的 `aux_loss` 除以系数，就是 `专家数 × Σ(分到的比例 × 平均路由概率)`——完全均衡时等于 1，所有 token 挤到一个专家时等于专家数 4。
下面把刚训的模型切到 `train()` 模式前向一次（只有训练模式才算 aux_loss），和官方 MoE 对比每层的均衡程度。

```python
import json
batch = tok([json.loads(l)["text"] for l in lines[:8]], return_tensors="pt", padding=True, truncation=True, max_length=256).input_ids.to(ss.device())
def router_stats(m):
    share = {}
    hooks = [l.mlp.gate.register_forward_hook(lambda mod, i, o, li=li: share.__setitem__(li, torch.bincount(o.argmax(-1).flatten(), minlength=m.config.num_experts).float() / o.shape[0]))
             for li, l in enumerate(m.model.layers)]
    m.train()
    with torch.no_grad():
        out = m(batch)
    m.eval()
    for h in hooks: h.remove()
    coef = m.config.router_aux_loss_coef
    return out.aux_loss.item(), [[round(l.mlp.aux_loss.item() / coef, 2), f"{share[li].max().item():.0%}"] for li, l in enumerate(m.model.layers)]
mine_moe = ss.load("moe_mine", moe=True, mine=True)
a1, r1 = router_stats(mine_moe)
a2, r2 = router_stats(moe)
ss.table([[f"第 {i + 1} 层", *x, *y] for i, (x, y) in enumerate(zip(r1, r2))], cols=["层", "小跑：aux/系数", "小跑：最忙专家占比", "官方：aux/系数", "官方：最忙专家占比"],
         title="每层路由均衡程度（aux/系数 = 1 完全均衡，= 4 全挤到一个专家）")
ss.kv({"小跑 aux_loss（8 层之和）": round(a1, 5), "官方 MoE aux_loss": round(a2, 5), "router_aux_loss_coef": mine_moe.config.router_aux_loss_coef}, "前向一次取 aux_loss")
```

> 思考：才训 20 步，各层的 aux/系数 就已经在 1 附近，和官方完整训练的模型差不多。是负载均衡损失在起作用，还是随机初始化的路由器本来就接近均匀？把 `router_aux_loss_coef` 设成 0 再跑一次，你预期哪几层会先「塌」到一个专家上？
