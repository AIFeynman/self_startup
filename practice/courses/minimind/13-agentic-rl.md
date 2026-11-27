# 13 Agentic RL：在多轮工具调用里学
<!-- minutes: 40 -->
<!-- know: Agentic RL, 多轮 rollout, 轨迹, 延迟奖励, 环境反馈, 可验证奖励 RLVR, 训推分离, 对齐税 -->

前面的 RL 都是「单轮问答 → 立即打分」。真实的 Agent 是多步的：生成 `tool_call` → 解析 → 执行工具 → 把结果拼回上下文 → 继续生成……直到给出最终答案，才对**整条轨迹**结算一次奖励。
`trainer/train_agent.py` 是作者很喜欢的一个脚本：把 RLVR / RLAIF 式的数据组织和在线 rollout 揉在一起，踩过收敛失败、奖励被钻空子（reward hack）、多轮上下文错位等坑，最后仍保持简洁可读。

数据 `agent_rl.jsonl` / `agent_rl_math.jsonl` 比普通对话多了 `gt`（最终要命中的答案）。一条样本记作 (x, 工具集, gt)，优化的对象是一条多轮轨迹：
`τ = (a₁, o₁, a₂, o₂, …, a_T)`，奖励对整条轨迹联合打分：
`R(τ) = R_answer + R_tool + R_format + R_rm − R_unfinished`

- **R_answer**：最终回答命中 gt 的比例 × 2.5；
- **R_tool**：合法工具调用数和需要的次数对得上 +0.5，否则按差值扣分；
- **R_format**：`<tool_call>` 标签没闭合要扣分，重复啰嗦也扣；
- **R_unfinished**：轮数用完还没答完扣 0.5；
- 没调工具的回答则走长度 / 思考格式 / 奖励模型打分。

## 一条 Agentic RL 样本

```python
import json, re, sys, torch
sys.path.insert(0, "scripts")
from eval_toolcall import execute_tool
from trainer.train_agent import calculate_rewards, validate_gt_in_text
tok = ss.tokenizer()
rows = [json.loads(l) for l in open(ss.fetch_head("gongjy/minimind_dataset", "agent_rl_math.jsonl", 200, "dataset/agent_math_200.jsonl"), encoding="utf-8")]
ex = rows[0]
tools = json.loads(ex["conversations"][0]["tools"])
ss.kv({"用户问题": ex["conversations"][1]["content"], "可用工具": "、".join(t["function"]["name"] for t in tools), "gt（要命中的答案）": json.dumps(ex["gt"], ensure_ascii=False)}, "样本")
```

## 跑一条多轮轨迹，并用训练时的奖励函数打分
`rollout`：模型生成 → 发现 `<tool_call>` 就执行工具、把结果作为 tool 消息拼回去 → 继续，最多 3 轮——和仓库 `rollout_single` 的默认 `max_turns=3`、`rl_train_epoch` 里写死的 `max_turns=3` 一致。然后直接调用仓库里的 `calculate_rewards`（不接奖励模型）给这条轨迹打分。

```python
def rollout(model, row, max_turns=3, temperature=0.3):
    sys_msg, user = row["conversations"][0], row["conversations"][1]
    tools = json.loads(sys_msg["tools"])
    msgs = [{"role": "system", "content": sys_msg.get("content", "")}, {"role": "user", "content": user["content"]}]
    trace, turns = [{"role": "user", "text": user["content"]}], []
    for _ in range(max_turns):
        out = ss.chat(model, msgs, tools=tools, max_new_tokens=200, temperature=temperature).replace("<|im_end|>", "")
        turns.append(out)
        calls = []
        for c in re.findall(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", out, re.S):
            try:
                calls.append(json.loads(c))
            except json.JSONDecodeError:
                pass                      # 小模型偶尔写出坏 JSON：当作这次调用失败（训练时会在格式分上扣分）
        if not calls:
            trace.append({"role": "assistant", "text": re.sub(r"<think>.*?</think>", "", out, flags=re.S).strip()})
            return trace, turns, False
        msgs.append({"role": "assistant", "content": out.split("<tool_call>")[0], "tool_calls": calls})
        for c in calls:
            res = execute_tool(c)
            trace += [{"role": "thought", "name": c.get("name"), "text": json.dumps(c.get("arguments", {}), ensure_ascii=False)},
                      {"role": "tool", "name": c.get("name"), "text": json.dumps(res, ensure_ascii=False)}]
            msgs.append({"role": "tool", "content": json.dumps(res, ensure_ascii=False)})
    return trace, turns, True

def score(row, turns, unfinished):
    tools = json.loads(row["conversations"][0]["tools"])
    return calculate_rewards([""], [turns[-1]], [row["gt"]], [tools], 1, None, device="cpu", turn_outputs_batch=[turns], unfinished_batch=[unfinished])[0].item()

sft = ss.load("full_sft")
trace, turns, unfinished = rollout(sft, ex)
ss.trace(trace, title=f"SFT 模型的轨迹 · 奖励 R(τ) = {score(ex, turns, unfinished):+.2f}")
```

> 思考：为什么 Agent 任务更偏向**环境反馈**（工具执行结果、gt 是否命中），而不是让奖励模型给整段回答打分？（提示：奖励模型看不懂长链路的可执行语义，容易被钻空子。）

## 官方 rollout：TorchRolloutEngine + rollout_single
上面的 `rollout` 是课程简化版，只拼文本。训练时用的是 `trainer/train_agent.py` 的 `rollout_single`，底下调 `trainer/rollout_engine.py` 的 `TorchRolloutEngine`。它多做两件事：
- 每轮生成都记下 token 级 **old logprob**，后面算 ratio 用；
- 把整条轨迹拼成一个 `response_ids`，配一个 **mask**：模型自己写的 token 记 1，工具返回、模板拼接和结束符记 0。loss 只算 1 的部分——不能让模型去「学会」工具的输出。

```python
import random
import trainer.train_agent as AG
from trainer.rollout_engine import TorchRolloutEngine
from dataset.lm_dataset import AgentRLDataset
ds = AgentRLDataset("dataset/agent_math_200.jsonl", tok)
item = ds[0]
random.seed(0)
engine = TorchRolloutEngine(sft, tok, ss.device())
final, ctx, p_ids, r_ids, r_mask, old_lp, turn_outs, unf = AG.rollout_single(
    engine, tok, [dict(m) for m in item["messages"]], item["tools"], max_turns=3, max_new_tokens=128, thinking_ratio=0.1, device=ss.device())
segs, cur = [], None                      # 把 response_ids 按 mask 切段：1 = 模型生成（算 loss），0 = 工具返回（不算 loss）
for t, m in zip(r_ids, r_mask):
    if cur is None or cur[0] != m:
        cur = [m, []]; segs.append(cur)
    cur[1].append(t)
ss.table([["mask=1 · 模型生成，算 loss" if m else "mask=0 · 工具返回 / 模板 / 结束符", len(ts), tok.decode(ts).replace("\n", " ")[:80]] for m, ts in segs],
         cols=["这一段是谁写的", "token 数", "内容"], title=f"官方 rollout_single：{len(turn_outs)} 轮，response 共 {len(r_ids)} token")
R = AG.calculate_rewards([""], [final], [item["gt"]], [item["tools"]], 1, None, device="cpu", turn_outputs_batch=[turn_outs], unfinished_batch=[unf])
ss.kv({"gt": json.dumps(item["gt"], ensure_ascii=False), "轮数用完还没答完 (unfinished)": unf, "R(τ)（不接奖励模型）": f"{R[0].item():+.2f}",
       "参与 loss 的 token 占比": f"{sum(r_mask) / max(len(r_mask), 1):.0%}"}, "这条轨迹")
```

> 思考：如果 mask 写错、把工具返回也算进 loss，模型会学到什么？（提示：它会开始「自己编」工具结果。）

## 本机跑 3 步官方 rl_train_epoch
直接 import `rl_train_epoch`，`reward_model=None`（不接 InternLM，只用规则和 gt 打分）。每步 1 题 × 2 条轨迹，`max_gen_len` 96（代码默认 768），学习率 2e-6（默认 3e-7）。课程选择，约 1 分钟：

```python long
import types, time
from contextlib import nullcontext
from model.model_minimind import MiniMindConfig
random.seed(0); torch.manual_seed(0)
AG.args = types.SimpleNamespace(device=ss.device(), epochs=1, num_generations=2, max_gen_len=96, max_total_len=2500, thinking_ratio=0.1,
                                loss_type="cispo", epsilon=0.2, epsilon_high=5.0, beta=0.1, accumulation_steps=1, grad_clip=1.0,
                                log_interval=1, save_interval=10**9, debug_mode=False)
AG.lm_config, AG.tokenizer, AG.autocast_ctx = MiniMindConfig(hidden_size=768, num_hidden_layers=8), tok, nullcontext()
AG.model = ss.load("full_sft").train()
AG.optimizer = torch.optim.AdamW(AG.model.parameters(), lr=2e-6)
AG.scheduler = torch.optim.lr_scheduler.ConstantLR(AG.optimizer, factor=1.0)
logs = []
AG.Logger = logs.append
loader = [{"messages": [ds[i]["messages"]], "tools": [ds[i]["tools"]], "gt": [ds[i]["gt"]]} for i in (1, 2, 3)]
t0 = time.time()
AG.rl_train_epoch(0, loader, 10**9, TorchRolloutEngine(AG.model, tok, ss.device()), ss.load("full_sft").requires_grad_(False), reward_model=None)
get = lambda k, s: float(re.search(rf"{k}:(-?[\d.]+)", s)[1])
ss.table([[i + 1, loader[i]["messages"][0][1]["content"][:24], get("Reward", s), get("GrpStd", s), get("KL", s), get("Loss", s), get("AvgLen", s)] for i, s in enumerate(logs)],
         cols=["step", "题目", "Reward", "GrpStd", "KL", "Loss", "AvgLen"], title=f"官方 rl_train_epoch · CISPO · 3 步 × 每题 2 条轨迹 · {time.time() - t0:.0f}s")
AG.model.eval()
```

- **GrpStd**：组内奖励标准差。为 0 就是退化组，优势全为 0；
- **AvgLen**：参与 loss 的 token 数，只算模型自己写的部分。

> 思考：`train_agent.py` 默认 `num_generations=4`，这里用 2。组越小，GrpStd 越容易是 0。组大小和显存、rollout 时间怎么权衡？

## 复现作者的对比：SFT vs Agentic RL 模型
作者用一组数学工具任务对比 `full_sft` 和 RL 后的 `agent` 权重：前者 60%，后者 85%。这里取 12 道 `agent_rl_math` 题，两个模型各跑一遍，统计命中 gt 的比例和平均奖励（约 3–5 分钟）。

```python long
agent = ss.load("agent")
tasks = rows[1:13]
res = {"full_sft": [], "agent": []}
detail = []
for i, row in enumerate(tasks):
    line = [row["conversations"][1]["content"][:40], json.dumps(row["gt"], ensure_ascii=False)]
    for name, m in (("full_sft", sft), ("agent", agent)):
        tr, turns, unf = rollout(m, row)
        final = tr[-1]["text"] if tr[-1]["role"] == "assistant" else ""
        hit = bool(row["gt"]) and len(validate_gt_in_text(final, row["gt"])) == len(row["gt"])
        res[name].append((hit, score(row, turns, unf)))
        line.append(("✅ " if hit else "❌ ") + f"{res[name][-1][1]:+.1f}")
    detail.append(line)
ss.table(detail, cols=["题目", "gt", "full_sft（命中 / 奖励）", "agent（命中 / 奖励）"], title="逐题结果")
ss.bars({f"{k} 命中率": round(100 * sum(h for h, _ in v) / len(v)) for k, v in res.items()}, title="工具任务命中率", unit="%")
ss.kv({f"{k} 平均奖励": f"{sum(r for _, r in v) / len(v):+.2f}" for k, v in res.items()}, "平均轨迹奖励")
```

## 对齐税：工具更强了，聊天呢？
作者的观察：`agent` 在轻量工具任务上明显更强，但开放问答的事实性往往下降，「工具任务做得更好，开放问答反而更敢编」。后训练能把一条能力线拉高，几乎都伴随「对齐税」——模型越来越擅长迎合当前的奖励定义，不等于整体能力无损提升。

```python
for q in ["万有引力是谁提出的？", "海水为什么是咸的？"]:
    ss.compare("full_sft", ss.chat(sft, q, max_new_tokens=120, temperature=0.3), "agent（RL 后）", ss.chat(agent, q, max_new_tokens=120, temperature=0.3), title=q)
```

> 思考：如果你的产品既要工具调用、又要靠谱的知识问答，你会怎么安排训练和部署？（一个模型？两个模型路由？RL 时混入通用对话的奖励？）

## 「共舞」：对齐税的一个具体样子
README 的 RL 对比测试 1 里，GRPO 和 Agent-CISPO 回答开放问题时都出现了重复退化：Agent-CISPO 反复堆「在无垠共舞间编织共舞」，GRPO 堆「既既既」「共融与共融」。SFT 没有这个问题。
奖励分数上去了，语言本身在塌——这就是对齐税最直观的样子。用 README 的三道题复现，拿训练时的 `rep_penalty` 量重复度（约 1 分钟）：

```python long
from trainer.trainer_utils import rep_penalty
models = {"full_sft": sft, "grpo": ss.load("grpo"), "agent": ss.load("agent")}
qs = ["请介绍一下自己。", "你更擅长哪一个学科？", "鲁迅的《狂人日记》是如何批判封建礼教的？"]
torch.manual_seed(0)
outs = {q: {n: ss.chat(m, q, max_new_tokens=200, temperature=0.7) for n, m in models.items()} for q in qs}
ss.table([[q[:14], *[f"{rep_penalty(o[n]):.2f} · {o[n].count('共')}" for n in models]] for q, o in outs.items()],
         cols=["问题", *[f"{n}（重复扣分 · 「共」字数）" for n in models]], title="训练时的 rep_penalty（上限 0.5）越高 = 3-gram 重复越多")
q = qs[1]
ss.compare("GRPO", outs[q]["grpo"], "Agent-CISPO", outs[q]["agent"], title=q)
```

> 思考：`calculate_rewards` 里明明有 `rep_penalty` 扣分，上限是 0.5，为什么还是挡不住「共舞」？（提示：和长度分、奖励模型分比，0.5 有多大？换个词重复，3-gram 还算重复吗？）

## 训推分离
`train_agent.py` 的 `--rollout_engine` 可以选本地 `generate` 或远端 sglang：训练侧只管更新策略，rollout 侧负责高吞吐采样，中间通过「轨迹」和「权重同步」衔接——已经有 OpenRLHF / verl / slime 这些大规模 RL 框架的味道，只是目前是同步模式（采完一批再更新）。

两种引擎接口一样（`rollout()` 和 `update_policy()`），区别在权重同步：
- `TorchRolloutEngine.update_policy` 只是换个引用，rollout 和训练用的永远是同一份权重；
- `SGLangRolloutEngine.update_policy` 要把权重存盘、再让 sglang 服务从磁盘重载。训练循环只在每 `save_interval`（默认 10）步调一次，中间的 rollout 用的是旧权重，ratio 会偏离 1——这正是第 12 课说的 CISPO 和 GRPO 拉开差距的地方。

sglang 服务加载的是 transformers 格式的 `./minimind-3`。README 说明 transformers 版如无特殊说明通常由 `full_sft` 转换而来，正好对上 `train_agent.py` 默认的 `--from_weight full_sft`；第一次同步之前，两边的策略是同一个。另外，并非所有阶段的权重都会持续公开维护，以实际 release 为准。

## （可选）完整 Agentic RL：上云

```python long cloud
import subprocess, os
subprocess.run("pip install -q modelscope -i https://mirrors.aliyun.com/pypi/simple/ && "
               "modelscope download --dataset gongjy/minimind_dataset agent_rl.jsonl --local_dir dataset && "
               "modelscope download --model Shanghai_AI_Laboratory/internlm2-1_8b-reward --local_dir ../internlm2-1_8b-reward", shell=True, check=True)
if not os.path.exists("out/full_sft_768.pth"): ss.weights("full_sft_768.pth", out="out")
ss.train_live("python train_agent.py --data_path ../dataset/agent_rl.jsonl --epochs 1 --batch_size 2 --num_generations 4 --log_interval 1 --save_dir ../out",
              cwd="trainer", title="Agentic RL（云端 A10）", metrics=("Reward", "KL", "AvgLen"))
```


## （可选）用 sglang 做 rollout：上云
命令来自 README：先起 sglang 服务，再让 `train_agent.py` 走 `--rollout_engine sglang`。需要 CUDA，本机跑不了。

```python long cloud
import subprocess, os, time, requests
subprocess.run("pip install -q 'sglang[all]' modelscope -i https://mirrors.aliyun.com/pypi/simple/ && "
               "modelscope download --model gongjy/minimind-3 --local_dir ./minimind-3 && "
               "modelscope download --dataset gongjy/minimind_dataset agent_rl_math.jsonl --local_dir dataset", shell=True, check=True)
if not os.path.exists("../internlm2-1_8b-reward"):
    subprocess.run("modelscope download --model Shanghai_AI_Laboratory/internlm2-1_8b-reward --local_dir ../internlm2-1_8b-reward", shell=True, check=True)
if not os.path.exists("out/full_sft_768.pth"): ss.weights("full_sft_768.pth", out="out")
server = subprocess.Popen("python -m sglang.launch_server --model-path ./minimind-3 --attention-backend triton --host 0.0.0.0 --port 8998", shell=True)
for _ in range(120):
    try:
        if requests.get("http://localhost:8998/health", timeout=2).ok: break
    except requests.RequestException:
        pass
    time.sleep(5)
try:
    ss.train_live("python train_agent.py --rollout_engine sglang --sglang_base_url http://localhost:8998 --sglang_shared_path ./ckpt_mm "
                  "--data_path ../dataset/agent_rl_math.jsonl --epochs 1 --batch_size 2 --log_interval 1 --save_dir ../out",
                  cwd="trainer", title="Agentic RL · sglang rollout（云端）", metrics=("Reward", "KL", "AvgLen"))
finally:
    server.terminate()
```
