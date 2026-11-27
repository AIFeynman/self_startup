# 12 GRPO 与 CISPO：没有 Critic 的强化学习
<!-- minutes: 40 -->
<!-- know: GRPO 组相对策略优化, 组内归一化优势, 退化组, CISPO, 重要性采样权重裁剪, 规则奖励, 奖励稀疏, KL 估计 k3 -->

2025 年初 DeepSeek-R1 出圈，来自 DeepSeekMath 论文的 **GRPO** 迅速成为最受关注的 RL 算法，如今已是 DAPO、GSPO、CISPO 等各种变体的共同基线。一句话概括它的创新：**分组相对价值估计**。

对同一个问题，让模型生成 N 个回答、各自打分，用**组内平均分**当基线：
`A_i = (R_i − μ_组) / (σ_组 + ε)`
高于平均的回答被鼓励，低于平均的被抑制——不需要 Critic 网络，省一半模型、训练更稳。作者的实验里 GRPO 的 reward 稳定上升到 4 左右，比 PPO 收敛上限更高。

两个要注意的坑：
- **退化组**：一组 N 个回答分数几乎一样（全对或全错），优势全是 0，这一组白采了。超小模型上特别明显，所以训练数据要卡在模型「够得着」的难度。
- **奖励稀疏**：拿 64M 模型做高考数学题，全是 0 分，学不到任何东西。作者的办法是用**连续的**奖励模型分数（−3 到 +3），哪怕都很差也能分出「更差」和「没那么差」。另外两条：监控 Var(r)，以及混合奖励 `r_total = α·r_model + β·r_rule`（第 11 课有演示）；别用二元规则奖励 + 超纲数据。

这一课在本机**亲手写一个 GRPO**：任务是 20 以内的加法、要求「只回答数字」。奖励用规则：**格式分**（是否只输出一个数字）+ **接近分**（答案越接近越高）。从官方 SFT 模型出发训几十步。

为什么不用两位数加法？试过：SFT 模型两位数加法正确率只有 3%（会说 59+63=139），几十步 RL 根本拉不动——这正是上面说的「超出能力边界，学不到东西」。选任务要卡在模型「够得着」的地方。

## 先看基线：SFT 模型做 20 以内加法
固定 30 道题，贪心解码测两个指标：「只回答数字」的比例、答对的比例。训练后再测。

```python
import torch, random, re, math, json
tok = ss.tokenizer()
dev = ss.device()
random.seed(0)
def make_task():
    a, b = random.randint(1, 20), random.randint(1, 20)
    return f"{a}+{b}等于多少？只回答数字。", a + b
def reward_fn(text, gt):
    t = text.strip().replace(",", "")
    fmt = 0.5 if re.fullmatch(r"-?\d+", t) else -0.5                 # 格式分：只输出一个数字
    nums = re.findall(r"-?\d+", t)
    close = -0.5 if not nums else (0.5 if int(nums[-1]) == gt else max(-0.5, 0.5 - abs(int(nums[-1]) - gt) / 10))   # 接近分
    return fmt + close
evalset = [make_task() for _ in range(30)]
def evaluate(m):
    outs = [(ss.chat(m, q, temperature=0, max_new_tokens=12).strip(), gt) for q, gt in evalset]
    pure = sum(bool(re.fullmatch(r"-?\d+", o)) for o, _ in outs) / len(outs)
    acc = sum(bool(re.findall(r"-?\d+", o)) and int(re.findall(r"-?\d+", o)[-1]) == gt for o, gt in outs) / len(outs)
    return pure, acc, outs
policy = ss.load("full_sft")
base_pure, base_acc, outs = evaluate(policy)
ss.kv({"只回答数字的比例": f"{base_pure:.0%}", "答对的比例": f"{base_acc:.0%}",
       "示例": f"{evalset[0][0]} → {outs[0][0][:40]}（正确 {evalset[0][1]}）"}, "基线：SFT 模型（30 题）")
```

## 采样一组，看组内优势
对一道题采 6 个回答（温度 1.0，要有多样性），打分、组内归一化。注意：如果 6 个全对或全错，优势全是 0——这就是退化组。

```python
def rollout(m, prompt, G=6, max_new=12):
    text = tok.apply_chat_template([{"role": "user", "content": prompt}], tokenize=False, add_generation_prompt=True)
    ids = tok(text, return_tensors="pt").input_ids.to(dev)
    with torch.no_grad():
        out = m.generate(ids, max_new_tokens=max_new, do_sample=True, temperature=1.0, top_p=1.0, num_return_sequences=G,
                         eos_token_id=tok.eos_token_id, pad_token_id=tok.pad_token_id)
    comp = out[:, ids.shape[1]:].clone()        # generate 在推理模式里跑，clone 成普通张量后才能参与反向传播
    eos = comp == tok.eos_token_id
    mask = ((eos.int().cumsum(1) - eos.int()) == 0).float()     # 第一个结束符（含）之前的 token 才算
    texts = [tok.decode(c[mk.bool()], skip_special_tokens=True) for c, mk in zip(comp, mask)]
    return ids.clone(), comp, mask, texts
q, gt = make_task()
_, _, _, texts = rollout(policy, q)
R = torch.tensor([reward_fn(t, gt) for t in texts])
A = (R - R.mean()) / (R.std() + 1e-4)
ss.table([[t.strip()[:30], f"{r:+.2f}", f"{a:+.2f}"] for t, r, a in zip(texts, R.tolist(), A.tolist())], cols=["回答", "奖励 R", "组内优势 A"],
         title=f"{q}（正确答案 {gt}）")
```

> 思考：组内优势的均值永远是 0。这意味着每一组里总有一半回答被「惩罚」——哪怕它们其实也答对了？

## GRPO 和 CISPO 的唯一区别：被裁剪后还有没有梯度
PPO / GRPO 里，概率比 r 一旦超出 [1−ε, 1+ε]，`min(r·A, clip(r)·A)` 取到的是常数，**梯度直接断掉**。
**CISPO**（MiniMax 提出）改成 `clip(r, max=ε_high).detach() × A × log π`：比值只当权重、截断后也不会切断 log π 的梯度路径。改动只有一行，作者直接把它做成 `train_grpo.py` 的一个 `loss_type`。下面用自动求导验证：

```python
old = torch.tensor([-1.0, -1.5, -0.5])
A3 = torch.tensor([1.0, 1.0, -1.0])
rows = []
for kind in ("grpo", "cispo"):
    logp = torch.tensor([-1.0, -1.0, -1.0], requires_grad=True)
    ratio = (logp - old).exp()
    if kind == "grpo":
        obj = torch.minimum(ratio * A3, ratio.clamp(0.8, 1.2) * A3)
    else:
        obj = ratio.clamp(max=5.0).detach() * A3 * logp
    obj.sum().backward()
    rows.append([kind.upper(), *[f"{g:+.3f}" for g in logp.grad.tolist()]])
r_show = [f"{x:.2f}" for x in (torch.tensor([-1.0] * 3) - old).exp().tolist()]
ss.table(rows, cols=["算法", f"token1：r={r_show[0]}, A=+1", f"token2：r={r_show[1]}, A=+1（超上界）", f"token3：r={r_show[2]}, A=−1（超下界）"],
         title="对 log π 的梯度：GRPO 在被裁剪的 token 上梯度为 0，CISPO 仍有梯度")
```

## 手写 GRPO / CISPO 训练循环（本机，约 2–4 分钟）
每一步：取 2 道题 × 每题 6 个回答 → 规则打分 → 组内归一化优势 → 在同一批数据上更新 2 次（第二次时 r 不再等于 1，裁剪才会生效）→ 加一点 KL 约束防跑偏（k3 估计：`exp(ref−logp) − (ref−logp) − 1`）。
改 `LOSS = "cispo"` 再跑一遍，就能对比两种算法。

```python long
LOSS, STEPS, G, LR, BETA, EPS = "grpo", 40, 6, 2e-6, 0.04, 0.2
policy = ss.load("full_sft"); policy.train()
ref = ss.load("full_sft")
for p in ref.parameters(): p.requires_grad_(False)
opt = torch.optim.AdamW(policy.parameters(), lr=LR)
def token_logps(m, ids, comp):
    full = torch.cat([ids.repeat(comp.shape[0], 1), comp], 1)
    logits = m(full).logits[:, ids.shape[1] - 1:-1].float()
    return logits.log_softmax(-1).gather(-1, comp[..., None]).squeeze(-1)
hist = {"平均奖励": [], "退化组比例": [], "KL": []}
view = ss.line(hist, title=f"手写 {LOSS.upper()}：20 以内加法", y="值")
for step in range(1, STEPS + 1):
    rs, degen, kls = [], 0, []
    for _ in range(2):
        q, gt = make_task()
        ids, comp, mask, texts = rollout(policy, q, G)
        R = torch.tensor([reward_fn(t, gt) for t in texts], device=dev)
        rs += R.tolist()
        if R.std() < 1e-6:
            degen += 1
            continue
        adv = ((R - R.mean()) / (R.std() + 1e-4))[:, None]
        with torch.no_grad():
            old_lp, ref_lp = token_logps(policy, ids, comp), token_logps(ref, ids, comp)
        for _ in range(2):
            lp = token_logps(policy, ids, comp)
            ratio = (lp - old_lp).exp()
            if LOSS == "grpo":
                pg = torch.minimum(ratio * adv, ratio.clamp(1 - EPS, 1 + EPS) * adv)
            else:
                pg = ratio.clamp(max=5.0).detach() * adv * lp
            kl = (ref_lp - lp).exp() - (ref_lp - lp) - 1
            loss = -((pg - BETA * kl) * mask).sum() / mask.sum()
            opt.zero_grad(); loss.backward(); torch.nn.utils.clip_grad_norm_(policy.parameters(), 1.0); opt.step()
        kls.append(((kl * mask).sum() / mask.sum()).item())
    hist["平均奖励"].append([step, round(sum(rs) / len(rs), 3)])
    hist["退化组比例"].append([step, degen / 2])
    hist["KL"].append([step, round(sum(kls) / max(len(kls), 1), 4)])
    view.update(title=f"手写 {LOSS.upper()}：20 以内加法 · 第 {step}/{STEPS} 步", x="step", y="值", series=[[k, v] for k, v in hist.items()])
policy.eval()
pure, acc, outs2 = evaluate(policy)
ss.table([["只回答数字的比例", f"{base_pure:.0%}", f"{pure:.0%}"], ["答对的比例", f"{base_acc:.0%}", f"{acc:.0%}"]],
         cols=["指标（30 道固定题）", "训练前", f"{LOSS.upper()} {STEPS} 步后"], title="效果")
ss.table([[q, o[:30], gt] for (q, gt), (o, _) in list(zip(evalset, outs2))[:6]], cols=["题目", "训练后回答", "正确答案"])
```

> 思考：作者提醒「Policy Loss 不是越低越好」：它是按梯度等于策略梯度构造的代理目标，每轮还做组内归一化，绝对值没有意义。判断 GRPO 有没有收敛，应该看什么？

## 官方 train_grpo.py 本机小跑：`--loss_type grpo` vs `cispo`
上面是手写版。现在直接 import `trainer/train_grpo.py` 的 `grpo_train_epoch`，用官方循环各跑 4 步。只换两样：
- **奖励模型**换成同接口的 `RuleRM`，内部复用上面的 `reward_fn`。官方 `calculate_rewards` 照常先加长度分（20–800 字 +0.5，否则 −0.5）、思考格式分、重复扣分，再加 `get_score()` 的分——这就是 `r_total = r_rule + r_model` 的混合奖励。
- **规模**缩小：每步 2 题 × 4 个回答，`max_gen_len` 16，学习率 2e-6（代码默认 3e-7）。课程选择，为了几步内能看到变化。

顺手包一层 `calculate_rewards`，多记一列**组内 Var(r)**——README 建议训练时盯这个数，持续接近 0 就要调数据或奖励。

```python
import types, time
from contextlib import nullcontext
import trainer.train_grpo as GR
from trainer.rollout_engine import TorchRolloutEngine
from model.model_minimind import MiniMindConfig

class RuleRM:                      # 顶替 InternLM 奖励模型：复用上面的 reward_fn（格式分 + 接近分）
    def get_score(self, messages, answer):
        a, b = map(int, re.findall(r"\d+", messages[-1]["content"])[:2])
        return reward_fn(answer, a + b)

def official_grpo(loss_type, steps=4, B=2, G=4):
    random.seed(0); torch.manual_seed(0)
    GR.args = types.SimpleNamespace(device=dev, epochs=1, max_seq_len=128, max_gen_len=16, num_generations=G, loss_type=loss_type,
                                    epsilon=0.2, epsilon_high=5.0, beta=0.1, accumulation_steps=1, grad_clip=1.0,
                                    log_interval=1, save_interval=10**9, debug_mode=False)
    GR.lm_config, GR.tokenizer, GR.autocast_ctx = MiniMindConfig(hidden_size=768, num_hidden_layers=8), tok, nullcontext()
    GR.model = ss.load("full_sft").train()
    GR.optimizer = torch.optim.AdamW(GR.model.parameters(), lr=2e-6)
    GR.scheduler = torch.optim.lr_scheduler.ConstantLR(GR.optimizer, factor=1.0)
    ref = ss.load("full_sft").requires_grad_(False)
    rows, var = [], []
    GR.raw_rewards = getattr(GR, "raw_rewards", GR.calculate_rewards)     # 重跑本格时别把包装再包一层
    def watched(prompts, responses, rm):                                   # 原样调用官方 calculate_rewards，只多记一个组内方差
        r = GR.raw_rewards(prompts, responses, rm)
        var.append(r.view(-1, G).var(dim=1, unbiased=False).mean().item())
        return r
    GR.calculate_rewards = watched
    GR.Logger = lambda msg: rows.append(msg)
    loader = []
    for _ in range(steps):
        qs = [make_task()[0] for _ in range(B)]
        loader.append({"prompt": [tok.apply_chat_template([{"role": "user", "content": q}], tokenize=False, add_generation_prompt=True, open_thinking=False) for q in qs]})
    t0 = time.time()
    GR.grpo_train_epoch(0, loader, 10**9, TorchRolloutEngine(GR.model, tok, dev), ref, RuleRM())   # iters 给极大值：不保存 checkpoint
    get = lambda k, s: float(re.search(rf"{k}: (-?[\d.]+)", s)[1])
    return [[i + 1, get("Reward", s), get("KL_ref", s), get("Adv Std", s), get("Actor Loss", s), round(v, 4)] for i, (s, v) in enumerate(zip(rows, var))], time.time() - t0

out = {}
for lt in ("grpo", "cispo"):
    out[lt], sec = official_grpo(lt)
    ss.table(out[lt], cols=["step", "Reward", "KL_ref", "Adv Std", "Actor Loss", "组内 Var(r)"], title=f"官方 grpo_train_epoch · --loss_type {lt} · 4 步 {sec:.0f}s")
ss.line({lt.upper(): [[r[0], r[1]] for r in rows] for lt, rows in out.items()}, title="两种 loss 的平均奖励：两条线重合", y="Reward")
```

看 Reward 列：**两种 loss 跑出来一模一样**。原因在代码里：用本地 torch 引擎时，每批 rollout 只更新 1 次，`old_per_token_logps` 就是当前策略算的，ratio ≡ 1。r = 1 时 GRPO 的 `min(r·A, clip(r)·A)` 和 CISPO 的 `clip(r).detach()·A·log π` 梯度都是 `A·∇log π`。Actor Loss 数值不同，梯度相同。

两者真正分开，要等 ratio 偏离 1：同一批数据多次更新，或者 rollout 用的权重落后于训练权重。后者在 sglang 引擎里会发生：`update_policy` 只在每 `save_interval`（默认 10）步同步一次权重。

再看 Var(r) 列：哪一步变成 0，那一步 Adv Std 也是 0——退化组，整批白采。

> 思考：既然本地 on-policy 时 GRPO 和 CISPO 等价，作者为什么还把 `cispo` 设成默认？（提示：想想训推分离之后 ratio 会怎样。）

## thinking_ratio：多大比例的 prompt 打开思考
`RLAIFDataset` 按 `thinking_ratio` 的概率给 prompt 加 `open_thinking=True`；`calculate_rewards` 里遇到 `</think>` 会额外按思考长度和闭合打分。默认值以代码为准：

```python
rows = []
for f in ("train_ppo.py", "train_grpo.py", "train_agent.py"):
    src = open(f"trainer/{f}", encoding="utf-8").read()
    rows.append([f, re.search(r'"--thinking_ratio", type=float, default=([\d.]+)', src)[1], re.search(r'"--loss_type".*?default="(\w+)"', src)[1] if "--loss_type" in src else "—",
                 re.search(r'"--learning_rate", type=float, default=([\de.-]+)', src)[1]])
ss.table(rows, cols=["脚本", "thinking_ratio 默认", "loss_type 默认", "learning_rate 默认"], title="以代码为准：三个 RL 脚本的默认值")
```

GRPO / PPO 默认 0.9：大部分样本练「先想再答」。Agent 默认 0.1：大部分轨迹不开思考，直接调工具。

> 思考：如果把 GRPO 的 thinking_ratio 改成 0，奖励里思考格式那几项就永远不触发。这算「简化」还是「丢了一路信号」？

## 官方 GRPO 模型 vs SFT
作者用 InternLM2-1.8B 奖励模型在 `rlaif.jsonl` 上训出了 `grpo_768.pth`。作者的观察：RL 之后奖励分数上去了，但回答可能变得冗长、套话多——这就是**对齐税**（reward hacking / capability trade-off）。

注意：README 说明并非所有阶段（DPO、PPO、GRPO、CISPO、Agent、LoRA 等）的权重都会持续维护、单独公开，以实际 release 为准；`transformers` 版本如无特殊说明，通常由 `full_sft` 转换而来。所以想比 RL 前后，要用 PyTorch 权重（`grpo_768.pth` 这类）；直接下 `minimind-3`（transformers 版）拿到的通常是 SFT。

```python
sft, grpo = ss.load("full_sft"), ss.load("grpo")
for q in ["请介绍一下自己。", "你更擅长哪一个学科？"]:
    ss.compare("SFT", ss.chat(sft, q, max_new_tokens=150), "GRPO（官方）", ss.chat(grpo, q, max_new_tokens=150), title=q)
```

## （可选）用奖励模型完整训练 GRPO / CISPO：上云
仓库的 `train_grpo.py`：每题生成 6 个回答，用 InternLM2-1.8B 奖励模型打连续分数。`--loss_type cispo` 是作者默认，改成 `grpo` 对比。

```python long cloud
import subprocess, os
subprocess.run("pip install -q modelscope -i https://mirrors.aliyun.com/pypi/simple/ && "
               "modelscope download --dataset gongjy/minimind_dataset rlaif.jsonl --local_dir dataset && "
               "modelscope download --model Shanghai_AI_Laboratory/internlm2-1_8b-reward --local_dir ../internlm2-1_8b-reward", shell=True, check=True)
if not os.path.exists("out/full_sft_768.pth"): ss.weights("full_sft_768.pth", out="out")
ss.train_live("python train_grpo.py --data_path ../dataset/rlaif.jsonl --loss_type cispo --epochs 1 --batch_size 2 --num_generations 6 "
              "--log_interval 1 --save_dir ../out", cwd="trainer", title="CISPO + 奖励模型（云端 A10）", metrics=("Reward", "KL_ref"))
```
