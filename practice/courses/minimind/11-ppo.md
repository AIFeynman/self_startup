# 11 强化学习总览与 PPO
<!-- minutes: 35 -->
<!-- know: RLHF 与 RLAIF, 奖励模型, 规则奖励, 奖励稀疏, 策略优化统一视角, PPO, 重要性采样比, clip 裁剪, Critic 价值网络, GAE 优势估计, on-policy -->

SFT 之后的强化学习主要有两条路：

| 类型 | 裁判 | 优点 | 缺点 |
|---|---|---|---|
| RLHF | 人类 | 更贴近真实人类偏好 | 成本高、效率低 |
| RLAIF | 模型 / 规则 / 环境 | 自动化、可扩展 | 可能偏离真实偏好 |

minimind 把「AI 反馈」理解得宽一些：奖励可以来自**奖励模型**（如 InternLM2-1.8B-Reward），也可以来自**规则**（数学答案对不对、代码能不能过测试、JSON 能不能解析），或者**环境**（工具是否执行成功、任务是否完成）。DeepSeek-R1 就是用规则验证数学答案，不需要奖励模型。

## 一个公式看懂所有 xxPO
作者的统一视角：所有策略优化算法都在优化同一个期望，只是三个零件不同——

`J = E[ Φ(r_t, A_t) − h(KL_t) ]`，训练时最小化 `L = −J`

- **策略项 Φ**：怎么用概率比 `r_t = π_θ(o_t)/π_old(o_t)` 和优势 A_t 更新策略；
- **优势项 A_t**：这个回答比「平均水平」好多少（这很关键：大模型算对定积分不稀奇，小模型答对加减法就该被鼓励）；
- **正则项 h(KL)**：别离参考模型太远，防跑偏，但也别管太死。

| 算法 | 策略项 | 优势项 | 正则项 | 训练的模型数 |
|---|---|---|---|---|
| DPO | log r_w − log r_l | 无显式优势 | 隐含在 β 里 | 1（前向 2 个） |
| PPO | min(r·A, clip(r, 1−ε, 1+ε)·A) | Critic 网络 / GAE 估计 | β·E[KL] | 2 |
| GRPO | 同 PPO | 组内归一化 (R−μ)/σ | β·KL_t | 1 |
| CISPO | clip(r, 0, ε_high)·A·log π | 组内归一化 | β·KL_t | 1 |

**说白了，这些算法不是各自孤立的，而是同一个目标函数在不同权衡下的自然变体。**

## PPO 的核心：裁剪
PPO（OpenAI 2017）是 LLM 强化学习最经典的基线。新策略和采样时的旧策略差太多，梯度估计就不可靠，所以把概率比 r 限制在 [1−ε, 1+ε]：
- 优势为正（好回答）：r 超过 1+ε 后不再给奖励——**涨够了就停**；
- 优势为负（坏回答）：r 低于 1−ε 后不再惩罚——**压够了就停**。

```python
import torch, math, json, os
r = torch.linspace(0.2, 2.0, 91)
eps = 0.2
def ppo_obj(r, A):
    return torch.minimum(r * A, r.clamp(1 - eps, 1 + eps) * A)
ss.line({"A = +1（好回答）": [[round(x, 3), round(y, 3)] for x, y in zip(r.tolist(), ppo_obj(r, 1).tolist())],
         "A = −1（坏回答）": [[round(x, 3), round(y, 3)] for x, y in zip(r.tolist(), ppo_obj(r, -1).tolist())]},
        title="PPO 的裁剪目标：横轴是概率比 r = π_new / π_old（ε = 0.2）", x="r", y="目标值")
```

> 思考：A>0 时，r 小于 1−ε 那一段为什么**没有**被裁？（提示：min 取的是更悲观的那个。）

## 优势怎么来：Critic 与 GAE
PPO 训练一个 **Critic（价值网络）** 预测「从这里往后能拿多少奖励」V(s)。**GAE（广义优势估计）** 把每一步的 TD 误差 `δ_t = r_t + γV(s_{t+1}) − V(s_t)` 按 (γλ) 衰减加权求和，在偏差和方差之间折中。
LLM 场景里奖励通常只在最后一个 token 给（奖励模型对整段回答打分），中间每步奖励为 0（再扣一点 KL）。下面手算一个 6 个 token 的回答：

```python
def gae(rewards, values, gamma=1.0, lam=0.95):
    adv, last = [0.0] * len(rewards), 0.0
    for t in reversed(range(len(rewards))):
        nxt = values[t + 1] if t + 1 < len(values) else 0.0
        delta = rewards[t] + gamma * nxt - values[t]
        last = delta + gamma * lam * last
        adv[t] = last
    return adv
rewards = [0, 0, 0, 0, 0, 2.0]                 # 奖励模型只给最后一个 token 打分
values = [0.5, 0.6, 0.8, 1.1, 1.5, 1.8]        # Critic 对每个位置的估计
adv = gae(rewards, values)
ss.table([[t, rewards[t], values[t], f"{adv[t]:+.3f}"] for t in range(6)], cols=["token 位置", "即时奖励", "Critic 估值 V", "GAE 优势"],
         title="GAE：最终奖励 2.0 被「分摊」回前面每个 token")
```

> 思考：如果 Critic 一开始估得很不准，优势就不准，Actor 会往错误方向更新——这就是作者说 PPO「reward 提升缓慢」的原因。GRPO 怎么绕开 Critic？（下一课。）

## 看看 PPO 真正改了什么：官方 PPO 模型 vs SFT
作者发布了 PPO 训完的 `ppo_actor_768.pth`。让 SFT 模型生成一段回答，算这段回答在两个模型下每个 token 的概率比 r 和 KL——这就是训练时 PPO 在盯着看的量。

```python
tok = ss.tokenizer()
sft, ppo = ss.load("full_sft"), ss.load("ppo_actor")
q = "请解释一下什么是光合作用？"
ans = ss.chat(sft, q, max_new_tokens=100, temperature=0.7)
prompt = tok.apply_chat_template([{"role": "user", "content": q}], tokenize=False, add_generation_prompt=True)
ids = tok(prompt + ans, return_tensors="pt").input_ids.to(ss.device())
n = len(tok(prompt).input_ids)
with torch.no_grad():
    lp_old = sft(ids).logits[0, n - 1:-1].float().log_softmax(-1).gather(-1, ids[0, n:, None]).squeeze(-1)
    lp_new = ppo(ids).logits[0, n - 1:-1].float().log_softmax(-1).gather(-1, ids[0, n:, None]).squeeze(-1)
ratio = (lp_new - lp_old).exp()
ss.kv({"回答 token 数": len(ratio), "概率比 r 的均值": f"{ratio.mean():.3f}", "超出 [0.8, 1.2] 的比例（会被 clip）": f"{((ratio < 0.8) | (ratio > 1.2)).float().mean():.0%}",
       "近似 KL(old‖new)": f"{(lp_old - lp_new).mean():.4f}"}, "SFT 回答在 PPO 模型下的概率比")
ss.bars([(tok.decode([t]), round(x, 2)) for t, x in zip(ids[0, n:n + 30].tolist(), ratio[:30].tolist())], title="前 30 个 token 的概率比 r（>1 = PPO 更倾向这个词）")
ss.compare("SFT", ans, "PPO（官方）", ss.chat(ppo, q, max_new_tokens=100, temperature=0.7), title=q)
```

## 本机小跑官方 PPO：Critic、优势、ratio 与 clip
直接 import `trainer/train_ppo.py` 的 `CriticModel` 和 `ppo_train_epoch`，不抄代码。只换两样：
- **奖励模型**换成规则：`calculate_rewards` 照常算长度分、思考格式分、重复扣分，再加 `reward_model.get_score()` 的分。我们给一个同接口的 `RuleRM`：20 以内加法，答案越接近分越高（−1 到 +1，连续）。
- **规模**缩小：`max_gen_len` 24（代码默认 1024），每步 2 个 prompt，跑 4 步。学习率调大到 2e-6 / 1e-4（代码默认 3e-7 / 5e-7），不然几步看不出变化。这是课程选择。

`CriticModel` 就是 MiniMind 主干 + 一个 `value_head`（hidden → 1）。主干从 `full_sft` 加载（`strict=False`），`value_head` 是随机初始化的。先看它对一条回答的估值：

```python
import random, re, types, time
from contextlib import nullcontext
import trainer.train_ppo as P
from trainer.rollout_engine import TorchRolloutEngine
from model.model_minimind import MiniMindConfig

dev = ss.device()
tok = ss.tokenizer()

class RuleRM:                      # 顶替 InternLM 奖励模型：接口和 LMForRewardModel.get_score 一样
    def get_score(self, messages, answer):
        a, b = map(int, re.findall(r"\d+", messages[-1]["content"])[:2])
        nums = re.findall(r"-?\d+", answer.replace(",", ""))
        return -1.0 if not nums else max(-1.0, 1.0 - abs(int(nums[-1]) - (a + b)) / 10)

def make_prompts(n):
    qs = [f"{random.randint(1, 20)}+{random.randint(1, 20)}等于多少？" for _ in range(n)]
    return [tok.apply_chat_template([{"role": "user", "content": q}], tokenize=False, add_generation_prompt=True, open_thinking=False) for q in qs]

def setup_ppo(update_iters):
    P.args = types.SimpleNamespace(device=dev, epochs=1, max_seq_len=128, max_gen_len=24, gamma=1.0, lam=0.95, clip_epsilon=0.2, vf_coef=0.5,
                                   kl_coef=0.02, cliprange_value=0.2, ppo_update_iters=update_iters, early_stop_kl=0.25, mini_batch_size=2,
                                   accumulation_steps=1, grad_clip=1.0, debug_mode=False, debug_log_ratio=False, save_interval=10**9)
    P.lm_config = MiniMindConfig(hidden_size=768, num_hidden_layers=8)
    P.tokenizer, P.autocast_ctx = tok, nullcontext()
    P.actor_model = ss.load("full_sft").train()
    P.critic_model = P.CriticModel(P.lm_config)
    P.critic_model.load_state_dict(torch.load("out/official/full_sft_768.pth", map_location="cpu"), strict=False)   # 主干同 SFT，value_head 随机
    P.critic_model.to(dev)
    P.actor_optimizer = torch.optim.AdamW(P.actor_model.parameters(), lr=2e-6)
    P.critic_optimizer = torch.optim.AdamW(P.critic_model.parameters(), lr=1e-4)
    ref = ss.load("full_sft").requires_grad_(False)
    sched = [torch.optim.lr_scheduler.ConstantLR(o, factor=1.0) for o in (P.actor_optimizer, P.critic_optimizer)]
    return TorchRolloutEngine(P.actor_model, tok, dev), ref, sched

# 训练前先看 Critic：主干是 SFT、value_head 随机初始化，估值基本是噪声
random.seed(1)
engine, ref, _ = setup_ppo(1)
p0 = make_prompts(1)
enc = tok(p0, return_tensors="pt").to(dev)
ro = engine.rollout(enc.input_ids, enc.attention_mask, num_generations=1, max_new_tokens=24)
with torch.no_grad():
    V = P.critic_model(input_ids=ro.output_ids)[0, ro.prompt_lens[0] - 1:-1].tolist()
resp = ro.completion_ids[0].tolist()
L = resp.index(tok.eos_token_id) + 1 if tok.eos_token_id in resp else len(resp)
msgs = [{"role": "user", "content": re.search(r"user\n(.*?)<\|im_end\|>", p0[0], re.S)[1]}]
R = RuleRM().get_score(msgs, ro.completions[0])
adv = gae([0.0] * (L - 1) + [R], V[:L])
ss.table([[tok.decode([t]), f"{v:+.3f}", f"{a:+.3f}"] for t, v, a in zip(resp[:L], V[:L], adv)], cols=["token", "Critic 估值 V", "GAE 优势"],
         title=f"{msgs[0]['content']} → {ro.completions[0].strip()[:30]} · 规则分 {R:+.2f}")
del engine, ref
```

> 思考：Critic 刚初始化时估值是噪声，GAE 算出的优势也就是噪声。PPO 早期 Actor 在跟着噪声走——代码里 Critic 学习率默认 5e-7，比 Actor 的 3e-7 大。你还能想到什么办法让 Critic 先「热身」？

## ppo_update_iters：同一批 rollout 更新几次
`ppo_update_iters`（代码默认 2）是「同一批采样数据重复更新几次」。第 1 次更新时策略还没变，`ratio = π_new / π_old ≈ 1`，clip 不起作用；从第 2 次起 ratio 才偏离 1，clip 才开始拦。下面两种设置各跑 4 步（约 30 秒）：

```python
LOG = re.compile(r"Reward: ([-\d.]+), KL_ref: ([-\d.]+), Approx KL: ([-\d.]+), ClipFrac: ([-\d.]+), Critic Loss: ([-\d.]+)")
def run_ppo(update_iters, steps, view=None):
    random.seed(0); torch.manual_seed(0)
    engine, ref, (s1, s2) = setup_ppo(update_iters)
    rows = []
    def logger(msg):
        m = LOG.search(msg)
        if m:
            rows.append([len(rows) + 1, *map(float, m.groups())])
            if view:
                view.update(title=f"官方 ppo_train_epoch · ppo_update_iters={update_iters} · 第 {len(rows)}/{steps} 步", x="step", y="值",
                            series=[["Reward", [[r[0], r[1]] for r in rows]], ["ClipFrac", [[r[0], r[4]] for r in rows]], ["Critic Loss", [[r[0], r[5]] for r in rows]]])
    P.Logger = logger
    loader = [{"prompt": make_prompts(2)} for _ in range(steps)]
    P.ppo_train_epoch(0, loader, 10**9, engine, ref, s1, s2, RuleRM())   # iters 给极大值：不触发保存 checkpoint
    return rows

t0 = time.time()
view = ss.line({}, title="官方 ppo_train_epoch", y="值")
r2 = run_ppo(2, 4, view)
r1 = run_ppo(1, 4)
ss.table([[it, f"{sum(r[3] for r in rs) / len(rs):.4f}", f"{sum(r[4] for r in rs) / len(rs):.3f}", f"{rs[0][5]:.3f} → {rs[-1][5]:.3f}"]
          for it, rs in ((1, r1), (2, r2))], cols=["ppo_update_iters", "平均 Approx KL", "平均 ClipFrac", "Critic Loss 首 → 末"],
         title=f"同一批 rollout 更新 1 次 vs 2 次（各 4 步，共 {time.time() - t0:.0f}s）")
```

日志里的量：
- **ClipFrac**：|ratio − 1| > ε 的 token 比例。`ppo_update_iters=1` 时它应该是 0。
- **Approx KL**：`0.5·(log ratio)²` 的均值。超过 `early_stop_kl`（默认 0.25）就提前停掉这批的剩余更新。
- **Critic Loss**：带 clip 的价值回归损失，应该往下走。

> 思考：`ppo_update_iters` 调大，数据复用率更高，但 ratio 偏得更远、ClipFrac 更高。为什么说 PPO「旧数据只能有限复用」？

## 奖励稀疏：先看 Var(r)
上面用的是**连续**的接近分。换成「答对 1 分、答错 0 分」的**二元**规则奖励，再给超出能力的题（比如 64M 模型做三位数乘法），一组回答全是 0 分，Var(r) = 0，优势全为 0，没有梯度。

README 的建议：
- **监控 Var(r)**：训练时看奖励方差，持续接近 0 就要调数据或奖励；
- **混合奖励**：`r_total = α·r_model + β·r_rule`，比如格式分（规则）+ 回答质量分（奖励模型）。`calculate_rewards` 就是这么拼的：长度分 + 思考格式分 − 重复扣分 + 奖励模型分；
- **别用二元规则奖励 + 超纲数据**（如 MATH500），容易奖励全零。

下面每题采 6 个回答，对比两种奖励的组内方差：

```python
from trainer.rollout_engine import TorchRolloutEngine
engine = TorchRolloutEngine(sft, tok, ss.device())
random.seed(2); torch.manual_seed(0)
rows = []
for a, b in [(random.randint(100, 999), random.randint(100, 999)) for _ in range(4)]:   # 三位数乘法：对 64M 模型是「超纲题」
    p = tok.apply_chat_template([{"role": "user", "content": f"{a}*{b}等于多少？"}], tokenize=False, add_generation_prompt=True, open_thinking=False)
    enc = tok([p], return_tensors="pt").to(ss.device())
    outs = engine.rollout(enc.input_ids, enc.attention_mask, num_generations=6, max_new_tokens=32).completions
    preds = [int(n[-1]) if (n := re.findall(r"\d+", o.replace(",", ""))) else None for o in outs]
    binary = torch.tensor([1.0 if x == a * b else 0.0 for x in preds])
    cont = torch.tensor([-1.0 if x is None else max(-1.0, 1.0 - abs(math.log10(x + 1) - math.log10(a * b + 1))) for x in preds])
    rows.append([f"{a}*{b}", f"{binary.var(unbiased=False):.3f}", f"{cont.var(unbiased=False):.3f}", outs[0].strip()[:30]])
ss.table(rows, cols=["题目（6 个回答一组）", "二元奖励 Var(r)", "连续奖励 Var(r)", "示例回答"],
         title="Var(r) = 0 时组内优势全是 0，这一批白采")
```

> 思考：连续奖励也有 Var(r) = 0 的组（比如全都没给出数字）。这时候混一个奖励模型分进来，为什么能救？

## PPO vs DPO
- **DPO（off-policy）**：静态偏好对，像监督学习一样反复多轮训练，数据效率高、成本低，不需要奖励模型。
- **PPO（on-policy）**：必须用当前策略实时采样新数据，旧数据只能有限复用，否则分布偏移；数据效率低，但更适合探索。
- PPO 要同时维护 Actor、Critic（还要参考模型和奖励模型），显存约为单网络方法的 1.5–2 倍。

## （可选）完整 PPO 训练：上云
需要 InternLM2-1.8B 奖励模型（约 3.8GB）+ Actor + Critic + 参考模型，本机跑太慢。日志里看 Reward、KL_ref、ClipFrac 三条曲线。

```python long cloud
import subprocess, os
subprocess.run("pip install -q modelscope -i https://mirrors.aliyun.com/pypi/simple/ && "
               "modelscope download --dataset gongjy/minimind_dataset rlaif.jsonl --local_dir dataset && "
               "modelscope download --model Shanghai_AI_Laboratory/internlm2-1_8b-reward --local_dir ../internlm2-1_8b-reward", shell=True, check=True)
if not os.path.exists("out/full_sft_768.pth"): ss.weights("full_sft_768.pth", out="out")
ss.train_live("python train_ppo.py --data_path ../dataset/rlaif.jsonl --epochs 1 --batch_size 2 --log_interval 1 --save_dir ../out",
              cwd="trainer", title="PPO（云端 A10）", metrics=("Reward", "KL_ref", "ClipFrac"))
```
