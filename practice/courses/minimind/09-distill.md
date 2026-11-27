# 9 知识蒸馏：让小模型学大模型
<!-- minutes: 20 -->
<!-- know: 知识蒸馏, 黑盒蒸馏, 白盒蒸馏, KL 散度, 蒸馏温度, 暗知识 -->

蒸馏 = 让「学生」模型模仿「老师」模型。分两类：
- **黑盒蒸馏**：学生只看得到老师**说了什么**（最终答案），本质上就是对老师的输出做 SFT。DeepSeek-R1、Qwen3 的高质量回答、思维链、工具调用数据都算黑盒蒸馏信号；minimind 主线 SFT 数据里已经混了大量这种数据。
  `L_blackbox = CE(y_teacher, p_student)`
- **白盒蒸馏**：学生还能看到老师在**每个 token 上的完整概率分布**，学的不只是标准答案，还有老师在候选词之间的相对倾向（「暗知识」）。
  `L_whitebox = α · CE + (1−α) · T² · KL(p_teacher^T ‖ p_student^T)`

黑盒蒸馏更常见，也更贴近 minimind 主线的实际做法；严格说它就是对老师输出做硬标签 SFT，只是随着 LLM 流行被广义地叫作「蒸馏」。它学到的是答案、风格和行为模式，看不到老师内部怎么做判断。

`trainer/train_distillation.py` 是白盒蒸馏的参考实现：教师 / 学生双模型加载、CE + KL 混合损失、温度缩放、dense 与 MoE 互相蒸馏，还有断点续训（`--from_resume 1`）和多卡（`torchrun`）。
代码里的两个关键超参（默认值）：
- `--temperature 1.5`：蒸馏温度，推荐 1.0–2.0。
- `--alpha 0.5`：CE 的权重，总损失 = α·CE + (1−α)·KL。α=1 退化成普通 SFT，α=0 只模仿老师分布、不看标准答案。

## 温度 T：把老师的「犹豫」放大
softmax 前把 logits 除以 T。T=1 时分布很尖，只看得到第一名；T 变大，第二、三名的概率被抬起来——这些「老师觉得也有点可能」的信息，正是硬标签里没有的。
乘 T² 是为了抵消温度带来的梯度缩小，让不同温度下损失量级可比。

```python
import torch, torch.nn.functional as F, os, json
tok = ss.tokenizer()
teacher = ss.load("full_sft")
text = tok.apply_chat_template([{"role": "user", "content": "中国的首都是哪里？"}], tokenize=False, add_generation_prompt=True) + "中国的首都是"
ids = tok(text, return_tensors="pt").input_ids.to(ss.device())
with torch.no_grad():
    logits = teacher(ids).logits[0, -1].float()
for T in (1.0, 2.0, 4.0):
    p = F.softmax(logits / T, -1)
    top = p.topk(8)
    ss.topk([(tok.decode([i]), v) for v, i in zip(top.values.tolist(), top.indices.tolist())], f"老师的下一个词分布 · 温度 T = {T}")
```

> 思考：作者推荐 T 在 1.0–2.0。T 太大会怎样？（分布会接近均匀，老师的判断也被抹平了。）

## 自己算一遍白盒蒸馏损失
学生 = 一个随机初始化的小号 minimind（512 维 · 8 层），老师 = 官方 SFT 模型。在同一批数据上算 CE、KL 和总损失，再和仓库里的 `distillation_loss` 比对。

```python
from model.model_minimind import MiniMindConfig, MiniMindForCausalLM
from trainer.train_distillation import distillation_loss
student = MiniMindForCausalLM(MiniMindConfig(hidden_size=512, num_hidden_layers=8)).to(ss.device())
batch = tok(tok.apply_chat_template([{"role": "user", "content": "介绍一下长城"}, {"role": "assistant", "content": "长城是中国古代的军事防御工程，绵延上万里。"}], tokenize=False),
            return_tensors="pt").input_ids.to(ss.device())
T, alpha = 1.5, 0.5
with torch.no_grad():
    t_logits = teacher(batch).logits[0, :-1].float()
s_logits = student(batch).logits[0, :-1].float()
ce = F.cross_entropy(s_logits, batch[0, 1:])
kl = F.kl_div(F.log_softmax(s_logits / T, -1), F.softmax(t_logits / T, -1), reduction="batchmean") * T * T
ss.kv({"学生参数": f"{sum(p.numel() for p in student.parameters()) / 1e6:.1f}M（老师 64M）", "CE（对标准答案）": f"{ce.item():.3f}",
       "T²·KL（对老师分布）": f"{kl.item():.3f}", "仓库 distillation_loss": f"{distillation_loss(s_logits, t_logits, temperature=T).item():.3f}",
       f"总损失 α={alpha}": f"{(alpha * ce + (1 - alpha) * kl).item():.3f}"}, "白盒蒸馏损失（手算 vs 仓库实现）")
```

和仓库实现的两处差别：仓库只在 assistant 回答的 token 上算 CE 和 KL（`loss_mask`，和第 6 课 SFT 一样），并把老师 logits 截到学生词表大小；上面手算对整句都算了。

## α 和 T 怎么影响损失
沿用上一格的 CE 和老师 / 学生 logits：扫一遍 α，看总损失在 CE 和 KL 之间怎么插值；再扫 T，看乘上 T² 前后 KL 的量级。

```python
ss.line({"总损失": [[a / 10, (a / 10 * ce + (1 - a / 10) * kl).item()] for a in range(11)]},
        title=f"T={T} 时总损失随 α 变化（α=0 只看老师，α=1 只看标准答案）", x="α", y="loss")
rows = []
for t in (1.0, 1.5, 2.0, 4.0, 8.0):
    raw = F.kl_div(F.log_softmax(s_logits / t, -1), F.softmax(t_logits / t, -1), reduction="batchmean").item()
    rows.append([t, f"{raw:.4f}", f"{raw * t * t:.4f}"])
ss.table(rows, cols=["温度 T", "KL（不乘 T²）", "T²·KL（仓库用的）"], title="温度越高 KL 越小，乘 T² 把量级拉回来")
```

> 思考：如果老师本身答错了某个 token，α 调小（更信老师）会怎样？什么情况下你会把 α 调大？

## 小跑白盒蒸馏（本机）
学生从零开始，同时学标准答案和老师分布。日志里能同时看到 `ce` 和 `distill` 两条曲线。
仓库默认是在已 SFT 的学生（`--from_student_weight full_sft`）上用 `--learning_rate 5e-6` 训 6 个 epoch；这里学生从零开始、只跑 1 个 epoch，所以学习率调到 5e-4。

```python long
p2 = ss.fetch_head("gongjy/minimind_dataset", "sft_t2t_mini.jsonl", 2000, "dataset/sft_head.jsonl")
base = ss.weights("full_sft_768.pth")
if not os.path.exists("out/base_full_sft_768.pth"):
    os.symlink(os.path.abspath(base), "out/base_full_sft_768.pth")
ss.train_live(f"python train_distillation.py --data_path ../dataset/sft_head.jsonl --student_hidden_size 512 --student_num_layers 8 "
              f"--teacher_hidden_size 768 --teacher_num_layers 8 --teacher_use_moe 0 --from_student_weight none --from_teacher_weight base_full_sft "
              f"--save_dir ../out --epochs 1 --batch_size 8 --max_seq_len 256 --learning_rate 5e-4 --log_interval 5 --num_workers 0 --device {ss.device()}",
              cwd="trainer", title="白盒蒸馏：512 维学生 ← 768 维老师（本机）", metrics=("loss", "ce", "distill"))
```

> 思考：只跑一个 epoch、从零开始的学生，蒸馏能让它学会对话吗？作者的实现是在**已经 SFT 过的学生**上继续蒸馏，为什么这样更合理？

## 黑盒蒸馏：本质就是对老师的回答做 SFT
让老师回答一批问题，把「问题 + 老师回答」存成 SFT 格式，学生拿去做第 6 课的 SFT——这就是黑盒蒸馏。拿 DeepSeek、Qwen 的回答训小模型，都是这个套路。

```python
qs = ["什么是光合作用？", "推荐三本入门的历史书。", "怎么提高睡眠质量？", "解释一下什么是通货膨胀。"]
rows = [{"conversations": [{"role": "user", "content": q}, {"role": "assistant", "content": ss.chat(teacher, q, max_new_tokens=120)}]} for q in qs]
with open("dataset/blackbox_distill.jsonl", "w", encoding="utf-8") as f:
    f.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
ss.table([[r["conversations"][0]["content"], r["conversations"][1]["content"][:120]] for r in rows], cols=["问题", "老师的回答（将作为学生的训练标签）"],
         title="黑盒蒸馏数据：dataset/blackbox_distill.jsonl")
```

> 思考：黑盒蒸馏只能学到老师「说了什么」。如果老师偶尔胡说，学生会怎样？白盒蒸馏能缓解吗？

## （可选）用 MoE 老师做完整蒸馏：上云
作者默认的配置：老师是 MoE 版（198M），学生是 dense 版（64M），都从 SFT 权重出发，在完整 SFT 集上蒸馏。

```python long cloud
import subprocess, os
subprocess.run("pip install -q modelscope -i https://mirrors.aliyun.com/pypi/simple/ && "
               "modelscope download --dataset gongjy/minimind_dataset sft_t2t_mini.jsonl --local_dir dataset", shell=True, check=True)
for f in ("full_sft_768.pth", "full_sft_768_moe.pth"):
    if not os.path.exists(f"out/{f}"): ss.weights(f, out="out")
ss.train_live("python train_distillation.py --data_path ../dataset/sft_t2t_mini.jsonl --teacher_use_moe 1 --epochs 1 --batch_size 16 "
              "--log_interval 50 --save_dir ../out --num_workers 4", cwd="trainer", title="MoE 老师 → dense 学生（云端）", metrics=("loss", "ce", "distill"))
```
