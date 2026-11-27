# 6 SFT 指令微调：从「续写」到「回答」
<!-- minutes: 20 -->
<!-- know: 有监督微调 SFT, 对话模板, loss 掩码, 指令跟随, mid training, Zero 模型 -->

预训练模型只会续写。SFT（有监督微调）用高质量的多轮对话继续训练，让模型适应 `user / assistant / system / tool` 的角色结构，学会「看到问题 → 给出回答」。
SFT 不只是调说话格式：像 minimind 主线 14GB 的 SFT 数据，已经接近一种 **mid training**——继续往参数里灌知识、任务模式和助手风格。
训练时对指令和回答长度做截断，兼顾显存和效率；需要更长上下文时，补少量长样本做增量微调，推理时再用 YaRN 外推到 2048 以上。

## 关键细节：只在回答上算 loss
SFT 的输入是整段对话，但 loss **只算 assistant 的回答部分**：问题是给定的，模型要学的是怎么答，不是怎么问。
`dataset/lm_dataset.py` 的 `SFTDataset.generate_labels` 找到每段 `<|im_start|>assistant` 到 `<|im_end|>` 之间的 token，其余位置的标签设成 -100（不算 loss）。下面把一条样本里参与 loss 的 token 标出来（彩色 = 算 loss，灰色 = 不算）。

```python
import json, torch
from dataset.lm_dataset import SFTDataset
tok = ss.tokenizer()
p2 = ss.fetch_head("gongjy/minimind_dataset", "sft_t2t_mini.jsonl", 2000, "dataset/sft_head.jsonl")
ds = SFTDataset(p2, tok, max_length=256)
x, y = ds[3]
n = int((x != tok.pad_token_id).sum())
ss.pieces([(tok.decode([int(a)]), int(a), int(b) != -100) for a, b in zip(x[:n], y[:n])],
          title=f"一条 SFT 样本：{n} 个 token，其中 {(y[:n] != -100).sum().item()} 个参与 loss")
```

> 思考：如果问题部分也算 loss，模型会学到什么奇怪的东西？多轮对话里，前几轮的回答要不要算 loss？

## 小规模 SFT（本机）
从**官方预训练权重**出发，用 2000 条对话训 1 个 epoch（约 2–4 分钟）。
SFT 的学习率要比预训练小：已经学会的东西别冲掉。看代码默认值：
- `train_pretrain.py`：`--learning_rate 5e-4`
- `train_full_sft.py`：`--learning_rate 1e-5`，是预训练的 1/50，约 1.7 个数量级。

这里只训 2000 条、1 个 epoch，为了几分钟内看到效果，用 `5e-5`（预训练的 1/10，差一个数量级）。正式全量 SFT 用默认的 1e-5。

```python long
import os
os.makedirs("out", exist_ok=True)
base = ss.weights("pretrain_768.pth")                      # 官方预训练权重（out/official/）
if not os.path.exists("out/base_pretrain_768.pth"):
    os.symlink(os.path.abspath(base), "out/base_pretrain_768.pth")
pts = ss.train_live(f"python train_full_sft.py --data_path ../dataset/sft_head.jsonl --from_weight base_pretrain --save_dir ../out "
                    f"--epochs 1 --batch_size 8 --max_seq_len 512 --learning_rate 5e-5 --log_interval 5 --num_workers 0 --device {ss.device()}",
                    cwd="trainer", title="小规模 SFT（2000 条对话，本机）")
```

## 预训练 vs 我的 SFT vs 官方 SFT
同样的问题，套上对话模板问三个模型。注意预训练模型会「接着编问题」或答非所问，而 SFT 后会正经回答。

```python
pre = ss.load("pretrain")
mine = ss.load("full_sft", mine=True)
official = ss.load("full_sft")
for q in ["请介绍一下自己。", "推荐一些杭州的特色美食。", "解释什么是机器学习"]:
    ss.table([["官方预训练（没学过对话）", ss.chat(pre, q, max_new_tokens=80)],
              ["我的小跑 SFT（2000 条）", ss.chat(mine, q, max_new_tokens=80)],
              ["官方 SFT（14GB 对话）", ss.chat(official, q, max_new_tokens=120)]], cols=["模型", q])
```

> 思考：只训了 2000 条，模型已经学会「用回答的口吻」说话，但内容常常不对。格式和知识，哪个更容易通过 SFT 学到？

## Zero 模型：只用 mini 数据从零训出来的样子
作者用 `pretrain_t2t_mini + sft_t2t_mini`、单卡 3090 约 2 小时训出了 **Zero 模型**（`full_sft_zero_768.pth`）。它具备基础对话能力，但事实知识和泛化都有限——比如英文问题会胡言乱语。看看「最低成本」能训到什么程度。

```python
zero = ss.load("full_sft_zero")
for q in ["请为我讲解「大语言模型」这个概念。", "Introduce the history of the United States, please."]:
    ss.compare("Zero 模型（约 2 小时 / 3 元）", ss.chat(zero, q, max_new_tokens=120), "官方 SFT（完整数据）", ss.chat(official, q, max_new_tokens=120), title=q)
```

## （可选）全量 SFT：上云
在你自己全量预训练的基础上做 SFT（或者直接从官方预训练出发）。A10 上 mini SFT 集约 1.2 小时。

```python long cloud
import subprocess
subprocess.run("pip install -q modelscope -i https://mirrors.aliyun.com/pypi/simple/ && "
               "modelscope download --dataset gongjy/minimind_dataset sft_t2t_mini.jsonl --local_dir dataset", shell=True, check=True)
import os
if not os.path.exists("out/pretrain_768.pth"):          # 没在云上做全量预训练，就从官方预训练权重出发
    ss.weights("pretrain_768.pth", out="out")
ss.train_live("python train_full_sft.py --data_path ../dataset/sft_t2t_mini.jsonl --from_weight pretrain --epochs 1 --batch_size 16 "
              "--max_seq_len 768 --log_interval 50 --save_dir ../out --num_workers 4", cwd="trainer", title="全量 SFT（云端 A10）")
```
