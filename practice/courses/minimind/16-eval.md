# 16 评估：分数说明了什么
<!-- minutes: 25 -->
<!-- know: 主观评测, 对齐税, 重复退化, 选择题评测, 条件对数概率, acc_norm, 随机基线, 标准误, 显著性, lm-evaluation-harness, 数据污染 -->

模型训完了，怎么知道它好不好？这一课走三种看法：同一问题让不同阶段的模型作答（主观）、和其他小模型横评打分（半主观）、跑 benchmark（客观）。重点是读懂分数：随机基线在哪、差几个点才算真的有差别、分数会被什么骗。

## RL 之后，聊天变了味
作者在相同随机种子和超参下，对比了 minimind-3 的三个阶段：SFT、GRPO、Agent-CISPO。问「请介绍一下自己」「你更擅长哪一个学科」「鲁迅的《狂人日记》是如何批判封建礼教的」：
- **SFT** 回答平实，有事实错误，但不至于失控；
- **GRPO** 开始跑题、堆套话，「既既既」「确保与既」这种断句出现；
- **Agent-CISPO** 最夸张：「在无垠共舞间编织共舞」反复出现，几乎每句都绕回「共舞」「共鸣」「璀璨篇章」。

另一边，在 20 道数学工具调用题上，agent 权重 17/20（85%），full_sft 只有 12/20（60%）。工具任务明显变强，开放问答变差——这就是第 13 课说的**对齐税**：奖励定义越窄，模型越会迎合它，不等于整体能力无损提升。「共舞」式的重复是一个很直观的症状。一种可能的解释：某些辞藻在奖励模型那里得分偏高，RL 就把它们越推越多。

下面自己复现一次：三个权重答同样两个问题，统计重复 4-gram 占比和「共舞」出现次数。采样有随机性，多跑几次看趋势。

```python long
import torch, math, time
tok = ss.tokenizer()
models = {"SFT": ss.load("full_sft"), "GRPO": ss.load("grpo"), "Agent-CISPO": ss.load("agent")}
def rep4(s):
    g = [s[i:i + 4] for i in range(len(s) - 3)]
    return 1 - len(set(g)) / max(len(g), 1)
rows = []
for q in ["请介绍一下自己。", "你更擅长哪一个学科？"]:
    for name, m in models.items():
        torch.manual_seed(0)
        a = ss.chat(m, q, max_new_tokens=300, temperature=0.85)
        rows.append([q, name, len(a), f"{rep4(a):.0%}", a.count("共舞"), a[:120] + "…"])
ss.table(rows, cols=["问题", "模型", "字数", "重复 4-gram 占比", "「共舞」次数", "开头"], title="同一问题，三个阶段的回答")
```

> 思考：「重复 4-gram 占比」能抓到「共舞」这种退化，但抓不到「一本正经地编」。如果要给 RL 训练加一个防退化的监控指标，你会选什么？它会不会又被模型钻空子？

## 和其他小模型比：说得好 vs 说得对
作者让 4 个模型答同一组题（长江、万有引力、大熊猫吃什么、海水为什么咸、珠峰、写快速排序、20 字摘要），再按准确性、完整性、逻辑性、代码质量打分。README 自己注明：样本量有限、带主观性，只供体验参考。

| 排名 | 模型 | 准确性 (30) | 完整性 (30) | 逻辑性 (20) | 代码质量 (20) | 总分 (100) |
|---|---|---|---|---|---|---|
| 1 | minimind-3-moe（0.2B-A0.06B） | 11 | 23 | 16 | 18 | 68 |
| 2 | chatlm-mini-chinese（0.2B） | 25 | 19 | 15 | 3 | 62 |
| 3 | minimind-3（0.06B） | 10 | 21 | 13 | 17 | 61 |
| 4 | baby-llama2-chinese（0.2B） | 8 | 6 | 5 | 2 | 21 |

- MoE 版表达最流畅、结构最好、代码正确，但把长江说成珠穆朗玛峰、说大熊猫吃海产品；
- chatlm-mini-chinese 知识最扎实（万有引力归于牛顿、1687 年《自然哲学的数学原理》），但快排的判断条件写反，摘要题直接放弃；
- minimind-3 和它总分只差 1 分（61 vs 62），优劣几乎互补：准确性 10 vs 25，代码 17 vs 3。

结论：参数预算有限时，「说得好」和「说得对」很难兼得。总分接近，不代表模型相近。

> 思考：这张表的总分是四项加起来的。如果你的场景是「给小学生答科学问题」，你会怎么改权重？排名会变吗？

## 选择题 benchmark 是怎么算分的
C-Eval、CMMLU、PIQA 这类评测通常不让模型自由作答，而是给定题目 `y` 和候选项 `x`，比较条件概率 `p(x | y)`，取最大的那个。选项是多个 token 时，比较整段选项的对数概率之和。
两个常见细节：
- **随机基线看选项数**：四选一是 25%，PIQA 只有两个选项，随机就是 50%。minimind-3 的 PIQA 是 50.65，看着比 C-Eval 的 24.89 高一倍，其实两个都贴着随机基线；
- **acc_norm**：长选项的对数概率天然更低（每多一个 token 多乘一个小于 1 的概率），所以 lm_eval 还会报按长度归一的 acc_norm。

下面 8 道题（4 道四选一、4 道 PIQA 风格的二选一），对比套 / 不套对话模板，以及 SFT 和 GRPO：

```python
qs = [("中国的首都是哪座城市？", ["上海", "北京", "广州", "深圳"], 1),
      ("水在标准大气压下的沸点是多少摄氏度？", ["50", "80", "100", "120"], 2),
      ("《红楼梦》的作者是谁？", ["曹雪芹", "罗贯中", "施耐庵", "吴承恩"], 0),
      ("光合作用主要发生在植物细胞的哪个结构中？", ["线粒体", "细胞核", "叶绿体", "液泡"], 2),
      ("想把钉子钉进木板，应该怎么做？", ["用锤子敲钉子的头", "用海绵按压钉子"], 0),
      ("怎样让热汤凉得更快？", ["把汤倒进宽口的盘子里", "给汤盖上厚棉被"], 0),
      ("下雨天出门，怎样不被淋湿？", ["撑一把伞", "穿一双拖鞋"], 0),
      ("怎样把一张纸对折成两半？", ["把两条短边对齐后压平折痕", "把纸揉成一团再展开"], 0)]
def opt_logp(m, q, opt, chat=True):
    prompt = tok.apply_chat_template([{"role": "user", "content": q}], tokenize=False, add_generation_prompt=True) if chat else tok.bos_token + f"问题：{q}\n答案："
    full = tok(prompt + opt, return_tensors="pt").input_ids.to(ss.device())
    n = len(tok(prompt).input_ids)
    with torch.no_grad():
        lp = m(full).logits[0, n - 1:-1].float().log_softmax(-1).gather(-1, full[0, n:, None]).squeeze(-1)
    return lp.sum().item(), len(opt)
def evaluate(m, chat=True):
    acc = acc_norm = 0
    detail = []
    for q, opts, ans in qs:
        s = [opt_logp(m, q, o, chat) for o in opts]
        pick = max(range(len(opts)), key=lambda i: s[i][0])
        pick_n = max(range(len(opts)), key=lambda i: s[i][0] / s[i][1])     # 按选项字数归一
        acc += pick == ans
        acc_norm += pick_n == ans
        detail.append([q, len(opts), " / ".join(f"{o}({v:.1f})" for o, (v, _) in zip(opts, s)), opts[pick], "✅" if pick == ans else "❌"])
    return acc / len(qs), acc_norm / len(qs), detail
a, an, detail = evaluate(models["SFT"])
ss.table(detail, cols=["题目", "选项数", "各选项对数概率之和", "模型选", "对错"], title="SFT 模型按选项概率作答")
rows = [[name, f"{x:.0%}", f"{y:.0%}"] for name, (x, y, _) in {"SFT · 套对话模板": (a, an, None), "SFT · 不套模板": evaluate(models["SFT"], chat=False),
                                                                "GRPO · 套对话模板": evaluate(models["GRPO"])}.items()]
rows.append(["随机作答（按每题选项数）", f"{sum(1 / len(o) for _, o, _ in qs) / len(qs):.0%}", ""])
ss.table(rows, cols=["设置", "acc", "acc_norm"], title=f"{len(qs)} 道题的小评测")
```

看二选一的题：错的往往是更长的正确选项（「把两条短边对齐后压平折痕」）输给了短选项。acc_norm 想修正的就是这种偏差，但按字数归一不一定救得回来，所以两个分数都要看。「套不套对话模板」对应 lm_eval 的 `--apply_chat_template`：指令模型要加，gpt2 这种纯基座模型不加。

> 思考：只有 8 道题，答对一道就是 12.5 个点。这个小评测上 SFT 的 acc 比 GRPO 高，能说明 SFT 更强吗？（下一节算给你看。）

## 客观评测：benchmark 表
作者用 [lm-evaluation-harness](https://github.com/EleutherAI/lm-evaluation-harness) 跑了 7 个数据集（C-Eval、CMMLU 是中文，其余英文）。命令（模型要先转成 transformers 格式，见第 15 课）：

```text
HF_ENDPOINT=https://hf-mirror.com lm_eval --model hf --model_args pretrained="/path/to/model",dtype=auto \
  --tasks "ceval-valid,cmmlu,arc_easy,piqa,openbookqa,hellaswag,social_iqa" --batch_size 16 --device cpu --trust_remote_code --apply_chat_template
```

想在本机快速试，加 `--limit 20` 每个任务只跑前 20 题（分数只能看流程通不通，见下一节的分辨率）。`lm_eval ls tasks` 列出支持的数据集。

| 模型 | 参数 | ceval / cmmlu | arc / piqa / obqa / hellaswag / siqa |
|---|---|---|---|
| minimind-3 | 64M | 24.89 / 25.38 | 28.49 / 50.65 / 23.60 / 28.28 / 34.19 |
| minimind-3-moe | 198M | 25.48 / 24.32 | 27.74 / 50.71 / 26.20 / 27.43 / 34.03 |
| minimind-3-exam | 64M | 30.98 / 26.12 | 35.61 / 56.26 / 24.20 / 28.40 / 34.19 |
| Steel-LLM | 1121M | 24.89 / 25.32 | 39.69 / 65.13 / 26.00 / 35.73 / 39.15 |
| gpt2-medium | 360M | 23.18 / 25.00 | 43.60 / 66.38 / 30.20 / 39.38 / 39.10 |
| TinyLlama-1.1B | 1100M | 25.71 / 25.03 | 54.80 / 74.43 / 35.60 / 60.38 / 43.09 |
| SmolLM2-135M | 135M | 24.44 / 24.71 | 58.50 / 68.17 / 32.80 / 43.15 / 39.46 |
| Aquila-135M | 135M | 25.19 / 25.10 | 54.59 / 67.52 / 34.40 / 41.67 / 39.66 |

MiniMind 数据规模远小于表里其他模型、训练偏中文，也没专门对齐选择题格式，英文分数自然低。中文两项，所有模型都挤在 25 附近——四选一的随机基线。

## 差几个点才算有差别
`lm_eval` 每个指标都附带 `stderr`，主要由测试集大小决定：二项分布的标准误 `√(p(1−p)/n)`。README 给的分辨率表：

| 数据集 | obqa | ceval | piqa | siqa | arc | hellaswag | cmmlu |
|---|---|---|---|---|---|---|---|
| 样本量 | 500 | ~1.3k | 1838 | 1954 | 2376 | 10042 | 11582 |
| ± 标准误 | 1.9 | 1.2 | 1.2 | 1.1 | 0.9 | 0.5 | 0.4 |

比较两个模型时，差值的标准误是两个标准误的平方和开根号，分数接近时约为单项的 **√2 倍**。按「差值超过约 2 倍差值标准误才算能区分」：obqa 上小于约 5 个点、ceval / piqa / siqa 上小于约 3 个点的差异，都分不开两个模型。

```python
def se(acc, n):                        # acc 用百分数
    return 100 * math.sqrt(acc / 100 * (1 - acc / 100) / n)
def compare(name, a, b, n):
    d, s = b - a, math.sqrt(se(a, n) ** 2 + se(b, n) ** 2)
    return [name, n, f"{a} → {b}", f"{d:+.2f}", f"±{s:.2f}", f"{abs(d) / s:.1f}", "能区分" if abs(d) > 2 * s else "分不开"]
ss.table([[k, n, f"±{se(p, n):.2f}"] for k, n, p in [("obqa", 500, 25), ("ceval", 1300, 25), ("piqa", 1838, 50), ("hellaswag", 10042, 28), ("cmmlu", 11582, 25), ("上面的 8 题小评测", 8, 75)]],
         cols=["数据集", "样本量", "√(p(1−p)/n)"], title="自己算一遍分辨率表")
ss.table([compare("obqa：minimind-3 vs moe", 23.60, 26.20, 500), compare("ceval：minimind-3 vs exam", 24.89, 30.98, 1300),
          compare("piqa：minimind-3 vs exam", 50.65, 56.26, 1838), compare("cmmlu：minimind-3 vs moe", 25.38, 24.32, 11582),
          compare("arc：minimind-3 vs moe", 28.49, 27.74, 2376)],
         cols=["对比", "样本量", "分数", "差值", "差值标准误", "差值 / 标准误", "结论（超过 2 倍）"], title="两个分数的差异显著吗")
```

MoE 比 dense 多了 134M 参数，benchmark 上的差异却全部落在噪声里；exam 版在 ceval、piqa 上的提升则是实打实的。

> 思考：两个模型在**同一套题**上作答，题目难度是共享的，把它们当独立样本算 √2 倍其实偏保守。如果拿到逐题的对错，你会怎么做更灵敏的配对比较？

## minimind-3-exam 与数据污染
minimind-3-exam 不是更大的模型，也几乎没注入新知识：只在 `lora_exam.jsonl` 上做了一次轻量 LoRA，再把 `lora_exam_768.pth` 合并回 minimind-3。这份数据从 ceval 和 mmlu（英文）的 test 子集抽样，加了前缀、后缀等格式增强，作用是对齐「题目 + 候选项」的组织形式，而不是背答案。

README 说明：上面 7 个评测集和这份对齐数据**没有样本交集**，所以不算污染。仅做格式对齐，7 个任务平均提升约 2.9 个点。
反过来，如果直接在有交集的数据上微调，分数会严重失真：minimind-3 在有污染的 ceval / cmmlu 子集上跑到过约 97%，但没有任何参考意义。

> 思考：exam 的提升说明小模型在这类评测上的瓶颈，一部分在「没见过这种格式」而不在知识。那 benchmark 分数到底在测什么？你会怎么设计一个评测，让格式对齐带来的提升尽量小？
