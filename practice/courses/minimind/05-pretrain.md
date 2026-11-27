# 5 预训练：学会高质量的「词语接龙」
<!-- minutes: 20 -->
<!-- know: 预训练, 下一个 token 预测, 学习率与余弦退火, 梯度累积, 混合精度训练, 检查点与续训 -->

大模型首先要把尽可能多的基础知识和语言规律吸进参数里。预训练就是让模型埋头读大量文本（百科、新闻、书籍、对话……），从中学到事实知识、语言模式和上下文之间的统计关系。
这个阶段是「无监督」的：没人逐条告诉它对错，它只做一件事——**词语接龙**。输入「秦始皇」，它要能接出「是中国历史上的第一位皇帝」。

这一课先在本机用 2000 条数据小跑一遍，看 loss 怎么降、生成怎么变；再和作者完整预训练的官方模型比一比。

## 准备一小份数据
从 mini 预训练集取前 2000 条。

```python
import json, os, torch
tok = ss.tokenizer()
path = ss.fetch_head("gongjy/minimind_dataset", "pretrain_t2t_mini.jsonl", 3000, "dataset/pretrain_head.jsonl")
lines = open(path, encoding="utf-8").readlines()[:2000]
open("dataset/pretrain_2k.jsonl", "w", encoding="utf-8").writelines(lines)
ss.note(f"小跑数据：{len(lines)} 条，约 {sum(len(json.loads(l)['text']) for l in lines) / 1e4:.0f} 万字")
```

## 读懂训练脚本的关键参数
`trainer/train_pretrain.py` 就是一个标准训练循环：取一批 → 前向算 loss → 反向求梯度 → 优化器更新。几个关键设计：
- **学习率 5e-4 + 余弦退火**：开始步子大、越往后越小，避免末期震荡。
- **梯度累积 `accumulation_steps=8`**：每 8 个小批次才更新一次权重，等于一次看 8 倍数据。显存不够时用时间换空间。
- **混合精度 bf16**：前向反向用半精度省显存提速度，权重更新用 fp32 保精度（Mac 上走 fp32）。
- **梯度裁剪 1.0**：防止偶发的超大梯度把模型打崩。
- **每 `save_interval` 步存一次**，`--from_resume 1` 可以断点续训（下面专门有一格）。

```python
src = open("trainer/train_pretrain.py", encoding="utf-8").read()
start = src.index("def train_epoch")
ss.show("table", title="train_pretrain.py 的核心循环（节选）", cols=["代码"],
        rows=[[l] for l in src[start:start + 2200].splitlines() if l.strip()][:40])
```

## 小规模预训练（本机实时曲线）
2000 条 × 1 个 epoch，batch 16，约 125 步，Mac 上 1–2 分钟。权重存到 `out/pretrain_768.pth`（自己训的放在 `out/`，官方权重放在 `out/official/`，互不覆盖）。

```python long
pts = ss.train_live(f"python train_pretrain.py --data_path ../dataset/pretrain_2k.jsonl --epochs 1 --batch_size 16 --log_interval 5 "
                    f"--save_dir ../out --num_workers 0 --device {ss.device()}", cwd="trainer", title="小规模预训练（2000 条，本机）")
ss.kv({"起始 loss": pts[0][1], "最终 loss": pts[-1][1], "理论瞎猜": 8.76}, "结果")
```

> 思考：loss 前几十步掉得飞快，后面越来越平。前面学到的是什么？（提示：先学会高频字和标点，再学搭配，最后才是知识。）

## 断点续训：`--from_resume 1`
训练动辄几小时，断电、断网、云机被回收都可能发生。minimind 每到 `save_interval` 步存两份东西：
- `out/<权重名>_768.pth`：只有模型权重（半精度），拿来推理。
- `checkpoints/<权重名>_768_resume.pth`：完整检查点——模型、优化器状态、第几轮第几步、GPU 数量、wandb 的 run id。

加 `--from_resume 1` 再跑同一条命令，脚本自动找到这个检查点：恢复模型和优化器，跳过已经训过的批次，从下一步接着走。
下面模拟一次「中途断电」：400 条数据、batch 16，一共 25 步，每 10 步存一次；跑到第 12 步时直接杀掉进程，再续训。权重名用 `resume_demo`，不覆盖上面小跑的结果。

```python
import subprocess, sys, re
open("dataset/resume_demo.jsonl", "w", encoding="utf-8").writelines(lines[:400])
args = ["--data_path", "../dataset/resume_demo.jsonl", "--epochs", "1", "--batch_size", "16", "--max_seq_len", "128",
        "--log_interval", "1", "--save_interval", "10", "--save_weight", "resume_demo", "--save_dir", "../out",
        "--num_workers", "0", "--device", ss.device()]
p = subprocess.Popen([sys.executable, "-u", "train_pretrain.py", *args], cwd="trainer", text=True,
                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env={**os.environ, "PYTORCH_ENABLE_MPS_FALLBACK": "1"})
first = []
for ln in p.stdout:
    m = re.search(r"\((\d+)/\d+\), loss: ([\d.]+)", ln)
    if m:
        first.append([int(m[1]), float(m[2])])
        if int(m[1]) >= 12:
            p.kill(); break
p.wait()
ck = torch.load("checkpoints/resume_demo_768_resume.pth", map_location="cpu", weights_only=False)
ss.kv({"进程被杀在": f"第 {first[-1][0]} 步", "检查点记录的位置": f"第 {ck['epoch'] + 1} 轮 · 第 {ck['step']} 步",
       "检查点里有": "、".join(ck.keys()), "第 11、12 步": "训了但没存，续训时会重做"}, "断电现场")
second = ss.train_live("python train_pretrain.py " + " ".join(args) + " --from_resume 1", cwd="trainer", title="--from_resume 1：从检查点接着训")
ss.line({"第一次（第 12 步被杀）": first, "续训": list(second)}, title=f"续训从第 {second[0][0]} 步接上")
a, b = dict(first).get(11), dict(second).get(11)
ss.note(f"第 11 步的 loss：第一次 {a}，续训 {b}" + ("——同一份权重、优化器状态和同一批数据，结果对得上" if a == b else "——有细微差别，来自设备上的非确定性运算"))
```

> 思考：续训从第 11 步开始，第 11、12 步被重训了一遍。`save_interval` 设成 1 不就不丢进度了吗？代价是什么？

还有两个工程开关，本机不跑，知道就行：
- `--use_wandb`：把 loss、学习率等曲线记到在线看板。国内直连 WandB 不稳，代码里实际是 `import swanlab as wandb`，用 [SwanLab](https://swanlab.cn/)，接口基本兼容。续训时用检查点里的 run id 接着写同一条曲线。
- **多卡**：`torchrun --nproc_per_node N train_pretrain.py`，单机 N 卡 DDP（数据并行）。每张卡跑一份模型、吃不同的数据，梯度自动求平均。检查点记录了当时的卡数，换卡数续训时会自动换算 step（比如 2 卡第 100 步 → 1 卡第 200 步）。

## 三个模型续写同一个开头
随机权重、你刚小跑的、作者完整预训练的（mini 集约 2.8 亿 token × 多轮）。预训练模型没学过对话格式，所以用「续写」方式测：直接给开头，不套对话模板。

```python
from model.model_minimind import MiniMindConfig, MiniMindForCausalLM
fresh = MiniMindForCausalLM(MiniMindConfig()).to(ss.device()).eval()
mine = ss.load("pretrain", mine=True)
official = ss.load("pretrain")
for p in ["人工智能是", "春天来了，", "为什么天空是蓝色的？"]:
    ss.table([["随机权重", ss.chat(fresh, p, raw=True, max_new_tokens=50)],
              ["我的小跑（2000 条）", ss.chat(mine, p, raw=True, max_new_tokens=50)],
              ["官方预训练", ss.chat(official, p, raw=True, max_new_tokens=80)]], cols=["模型", f"续写「{p}」"])
```

> 思考：官方预训练模型能把「为什么天空是蓝色的」接成一段解释，但它并不会「回答问题」——它只是在续写一段像百科的文字。这和「对话」差在哪？（下一课 SFT 解决。）

## 用困惑度量化差距
在没参与训练的文本上算 loss：越低说明越「懂」这种语言。

```python
import math
held = [json.loads(l)["text"] for l in open(path, encoding="utf-8").readlines()[2500:2600]]
def ppl(m):
    tot, n = 0.0, 0
    for t in held:
        ids = tok(tok.bos_token + t, return_tensors="pt", truncation=True, max_length=256).input_ids.to(ss.device())
        with torch.no_grad():
            tot += m(ids, labels=ids).loss.item() * (ids.shape[1] - 1); n += ids.shape[1] - 1
    return math.exp(tot / n)
ss.bars({"随机权重": round(ppl(fresh)), "我的小跑": round(ppl(mine)), "官方预训练": round(ppl(official))}, title="在 100 条没见过的文本上的困惑度（越低越好）")
```

## （可选）全量预训练：上云
完整的 mini 预训练集 1.2GB，本机要好几个小时；A10 上约 1.3 小时、约 5 元。点运行会先报价，确认后开机；跑完用下一格把权重拉回本机，就能拿它替换上面的「官方预训练」做对比。

```python long cloud
import subprocess
subprocess.run("pip install -q modelscope -i https://mirrors.aliyun.com/pypi/simple/ && "
               "modelscope download --dataset gongjy/minimind_dataset pretrain_t2t_mini.jsonl --local_dir dataset", shell=True, check=True)
ss.train_live("python train_pretrain.py --data_path ../dataset/pretrain_t2t_mini.jsonl --epochs 1 --batch_size 32 --max_seq_len 768 "
              "--log_interval 50 --save_dir ../out --num_workers 4", cwd="trainer", title="全量预训练（云端 A10）")
```

```python optional
# 云上训完后运行：把云端权重拉回本机，存成 out/cloud_pretrain_768.pth
path = ss.from_cloud("out/pretrain_768.pth")
import shutil; shutil.move(path, "out/cloud_pretrain_768.pth")
full = ss.load(path="out/cloud_pretrain_768.pth")
ss.compare("我的全量预训练", ss.chat(full, "人工智能是", raw=True, max_new_tokens=80), "官方预训练", ss.chat(official, "人工智能是", raw=True, max_new_tokens=80))
```
