# 5 预训练：看着模型学会说话
<!-- minutes: 20 -->
<!-- know: 预训练, 学习率, 梯度累积, 混合精度训练, 检查点 -->
<!-- gpu: yes -->

真正开始训练。先用 2 万条数据小跑几分钟，看 loss 从 8.8 往下掉、生成的句子从乱码变得像话；想要完整效果再跑全量。

## 准备一份小数据
取预训练集的前 2 万条（约 30MB）。

```python
path = ss.fetch_head("gongjy/minimind_dataset", "pretrain_t2t_mini.jsonl", 20000, "dataset/pretrain_20k.jsonl")
ss.note(f"已就绪：{path}")
```

## 小规模预训练（实时曲线）
用 minimind 自带的训练脚本。几个参数：
- `batch_size 32` × `accumulation_steps 8`：每 8 个小批次才更新一次权重，等于一次看 256 条。显存不够时常用这招。
- `dtype bfloat16`：混合精度，前向反向用 bf16，权重更新用 fp32。
- 学习率 5e-4，余弦衰减。

```python long gpu
pts = ss.train_live("python train_pretrain.py --data_path ../dataset/pretrain_20k.jsonl --epochs 1 --batch_size 32 "
                    "--log_interval 10 --save_dir ../out --num_workers 2", cwd="trainer", title="小规模预训练（2 万条）")
ss.kv({"起始 loss": pts[0][1] if pts else "-", "最终 loss": pts[-1][1] if pts else "-"}, "结果")
```

> 思考：loss 曲线前几十步掉得飞快，后面越来越平。前面学到的是什么？（提示：先学会高频字和标点，再学搭配，最后才是知识。）

## 训练前 vs 训练后
同一个开头，让随机模型和刚训好的模型各续写一段。

```python
import torch
dev = ss.device()
trained = MiniMindForCausalLM(cfg)
trained.load_state_dict(torch.load("out/pretrain_768.pth", map_location="cpu"), strict=False)
trained = trained.to(dev).eval()
fresh = MiniMindForCausalLM(cfg).to(dev).eval()

def cont(m, text, n=60):
    ids = tok(tok.bos_token + text, return_tensors="pt").input_ids.to(dev)
    with torch.no_grad():
        out = m.generate(ids, max_new_tokens=n, do_sample=True, temperature=0.8, top_p=0.9, eos_token_id=tok.eos_token_id)
    return text + tok.decode(out[0][ids.shape[1]:], skip_special_tokens=True)

for p in ["人工智能是", "春天来了，"]:
    ss.compare("训练前（随机权重）", cont(fresh, p), "训练后（2 万条，几分钟）", cont(trained, p), title=f"续写：「{p}」")
```

> 思考：只看了 2 万条，模型已经会写通顺的句子了，但内容常常胡说。要让它「说对」，需要什么？

## （可选）全量预训练
完整的 mini 预训练集 1.2GB，A10 上约 1.3 小时、约 5 元。会在云端跑完，关掉页面也不停；结束时平台会把权重拉回本机。

```python long gpu
import subprocess
subprocess.run("pip install -q modelscope -i https://mirrors.aliyun.com/pypi/simple/ && "
               "modelscope download --dataset gongjy/minimind_dataset pretrain_t2t_mini.jsonl --local_dir dataset", shell=True, check=True)
ss.train_live("python train_pretrain.py --data_path ../dataset/pretrain_t2t_mini.jsonl --epochs 1 --batch_size 32 "
              "--log_interval 50 --save_dir ../out --num_workers 4", cwd="trainer", title="全量预训练")
```
