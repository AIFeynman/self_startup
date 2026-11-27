# 10 DPO：从「好坏对比」里学偏好
<!-- minutes: 20 -->
<!-- know: RLHF, 偏好对齐, DPO 直接偏好优化, 参考模型, β 系数, 隐式奖励, off-policy -->

前面的训练都是「词语接龙」，模型只学到「什么话常见」，没学到「什么回答好、什么回答差」。
**RLHF（基于人类反馈的强化学习）** 用人类偏好来纠正它：像培训新员工，拿优秀员工的做法当正例、消极员工的做法当反例。

**DPO（直接偏好优化）** 是最简洁的一种：从 PPO 带 KL 约束的目标推导出一个对偏好对的解析损失，**不需要奖励模型、不需要在线采样**，只要一个正在训的策略模型 π 和一个冻结的参考模型 π_ref：

`L_DPO = −log σ( β · [ log π(y_w|x)/π_ref(y_w|x) − log π(y_l|x)/π_ref(y_l|x) ] )`

y_w 是被偏好的回答（chosen），y_l 是不被偏好的（rejected）。直觉：让 chosen 相对参考模型的概率涨得比 rejected 多。

放进作者的「PO 算法统一视角」（所有 xxPO 都是在优化 策略项 Φ − 正则项 h(KL)，区别只在三个组件怎么设计）：
| 组件 | DPO 里是什么 |
|-|-|
| 策略项 | log r_w − log r_l：chosen 和 rejected 各自相对参考模型的对数概率比之差 |
| 优势项 | 没有显式优势，偏好对比隐式体现 |
| 正则项 | 隐含在 β 里：β 控制能偏离参考模型多远 |

- **只要两个模型**：actor（在训的策略）和 ref（冻结的参考），不用同步训 Reward / Value 模型，显存低、收敛稳、实现简单。
- **off-policy**：用静态偏好数据，可以反复多轮训练；参考模型固定，所以它的输出可以预先缓存。`train_dpo.py` 是每步在 `no_grad` 下现算 ref；本课下面对留出数据先缓存了一份。
- **局限**：不做在线探索，更多用于「偏好 / 安全」对齐，对「能不能做对题」这类智力提升有限（也取决于数据：大规模收集正反样本并人工评估很难）。

RLHF 的反馈来自**人**（更贴近真实偏好，但成本高、效率低）；后面第 11–13 课的 RLAIF 反馈来自**模型或规则**（自动化、可扩展，但可能偏离人的真实偏好）。DPO 属于前者。

## 手算一次 DPO 损失
策略模型和参考模型都是官方 SFT 时，括号里是 0，损失 = −log σ(0) = **ln 2 ≈ 0.693**——这是 DPO 训练的起点。下面在一条真实偏好对上逐项算出来。

```python
import torch, torch.nn.functional as F, json, os, math
from trainer.train_dpo import logits_to_log_probs, dpo_loss
tok = ss.tokenizer()
policy, ref = ss.load("full_sft"), ss.load("full_sft")
dpo = [json.loads(l) for l in open(ss.fetch_head("gongjy/minimind_dataset", "dpo.jsonl", 600, "dataset/dpo_head.jsonl"), encoding="utf-8")]

def seq_logp(m, msgs, max_len=512):
    """对话里最后一段 assistant 回答的总对数概率（只算回答部分）。"""
    prompt = tok.apply_chat_template(msgs[:-1], tokenize=False, add_generation_prompt=True)
    full = tok.apply_chat_template(msgs, tokenize=False)
    ids = tok(full, return_tensors="pt", truncation=True, max_length=max_len).input_ids.to(ss.device())
    n_prompt = len(tok(prompt).input_ids)
    with torch.no_grad():
        lp = logits_to_log_probs(m(ids).logits[:, :-1], ids[:, 1:])
    return lp[0, n_prompt - 1:].sum().item()

zh = lambda t: sum("\u4e00" <= ch <= "\u9fff" for ch in t) > 5
q = lambda x: x["chosen"][-2]["content"]                                 # 最后一轮的用户问题（多轮对话里第一句可能只是 "continue"）
d = next((x for x in dpo if len(x["chosen"]) == 2 and zh(q(x))), None) or next(x for x in dpo if len(q(x)) > 20)
beta = 0.15
pw, pl, rw, rl = seq_logp(policy, d["chosen"]), seq_logp(policy, d["rejected"]), seq_logp(ref, d["chosen"]), seq_logp(ref, d["rejected"])
z = beta * ((pw - rw) - (pl - rl))
ss.kv({"问题": q(d)[:80], "log π(chosen)": f"{pw:.1f}", "log π(rejected)": f"{pl:.1f}",
       "括号里的差 × β": f"{z:.4f}", "DPO 损失": f"{-F.logsigmoid(torch.tensor(z)).item():.4f}（起点应为 ln2 = {math.log(2):.4f}）"}, "一条偏好对上的 DPO")
```

> 思考：DPO 只看「相对参考模型的变化」，不看绝对概率。如果直接最大化 log π(chosen) − log π(rejected)、不要参考模型，会出什么问题？

## β 在控制什么
记 Δ = (log π(y_w)/π_ref(y_w)) − (log π(y_l)/π_ref(y_l))，损失 = −log σ(β·Δ)。画出不同 β 下损失随 Δ 的变化：β 越大，曲线越陡，Δ 稍微变正损失就掉到接近 0，梯度很快消失；β 越小，要把 Δ 推得更远才算「学够了」，策略就会离参考模型更远。代码默认 `--beta 0.15`。

```python
ss.line({f"β={b}": [[x / 2, -F.logsigmoid(torch.tensor(b * x / 2)).item()] for x in range(-40, 41)] for b in (0.05, 0.15, 0.5, 1.0)},
        title="DPO 损失 vs 对数概率比之差 Δ", x="Δ", y="loss")
ss.kv({"本条样本的 Δ": f"{(pw - rw) - (pl - rl):.4f}（策略 = 参考，所以是 0）", "β=0.15 时的损失": f"{-F.logsigmoid(torch.tensor(0.15 * ((pw - rw) - (pl - rl)))).item():.4f}"}, "对照")
```

> 思考：β=0.15 时，要把损失降到 0.1，Δ 大约要多大？换成 β=0.5 呢？这说明 β 大小和「策略被允许离参考模型多远」是什么关系？

## 训练前：模型本身偏好哪个回答？
**隐式奖励** r = β · log(π/π_ref)。训练前策略 = 参考，所以看不出偏好。我们留出 40 条没参与训练的偏好对，训练后再看「chosen 的隐式奖励是否高于 rejected」。

```python
held, train_rows = dpo[-40:], dpo[:400]
with open("dataset/dpo_train.jsonl", "w", encoding="utf-8") as f:
    f.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in train_rows)
base_ref = {i: (seq_logp(ref, d["chosen"]), seq_logp(ref, d["rejected"])) for i, d in enumerate(held)}
ss.note(f"训练用 {len(train_rows)} 对，留出 {len(held)} 对做评估；参考模型对留出数据的打分已缓存")
```

## 小跑 DPO（本机）
用仓库的 `train_dpo.py`，从官方 SFT 出发。作者默认学习率 4e-8（代码注释：「建议 <=5e-8 避免遗忘」，DPO 很容易训崩），这里为了几分钟内看到变化调到 5e-7。
其他默认值：`--beta 0.15`、`--epochs 1`、`--batch_size 4`、`--max_seq_len 1024`。训完默认保存为 `out/dpo_*.pth`，这里用 `--save_weight dpo_mine` 存成 `dpo_mine_768.pth`。
README 的命名表里有 `dpo_768.pth`，但 ModelScope `gongjy/minimind-3-pytorch` 目前没有发布这份权重（作者说明：并非所有阶段的权重都持续公开），所以这课只用自己训的。

```python long
base = ss.weights("full_sft_768.pth")
if not os.path.exists("out/base_full_sft_768.pth"):
    os.symlink(os.path.abspath(base), "out/base_full_sft_768.pth")
ss.train_live(f"python train_dpo.py --data_path ../dataset/dpo_train.jsonl --from_weight base_full_sft --save_weight dpo_mine --save_dir ../out "
              f"--epochs 1 --batch_size 2 --max_seq_len 512 --learning_rate 5e-7 --log_interval 5 --num_workers 0 --device {ss.device()}",
              cwd="trainer", title="DPO 小跑（400 对，本机）", metrics=("dpo_loss",))
```

## 训练后：偏好有没有学进去？
对留出的 40 对，算 chosen 和 rejected 的隐式奖励差（margin）。DPO 起作用的话，margin 的均值应该变成正的，「chosen 胜出」的比例应该超过一半。

```python
mine = ss.load("dpo_mine", mine=True)
margins = []
for i, d in enumerate(held):
    cw, cl = base_ref[i]
    margins.append(beta * ((seq_logp(mine, d["chosen"]) - cw) - (seq_logp(mine, d["rejected"]) - cl)))
ss.kv({"平均奖励差（训练前 = 0）": f"{sum(margins) / len(margins):+.4f}", "chosen 胜出比例": f"{sum(m > 0 for m in margins) / len(margins):.0%}",
       "对应 DPO 损失": f"{sum(-F.logsigmoid(torch.tensor(m)).item() for m in margins) / len(margins):.4f}（训练前 0.6931）"}, "留出偏好对上的效果")
ss.bars([(f"#{i}", round(m, 4)) for i, m in enumerate(margins[:20])], title="前 20 对：chosen 相对 rejected 的隐式奖励差（正 = 学到了偏好）")
```

> 思考：学习率调大 10 倍会怎样？DPO 训过头常见的症状是 chosen 和 rejected 的概率**一起下降**，回答越来越短或乱。为什么会这样？

## 回答有什么变化

```python
for q in ["怎样才能更好地学习一门新语言？", "Write a short poem about autumn."]:
    ss.compare("SFT（DPO 前）", ss.chat(ref, q, max_new_tokens=150, temperature=0.3), "我的 DPO", ss.chat(mine, q, max_new_tokens=150, temperature=0.3), title=q)
```
