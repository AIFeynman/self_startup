# 8 LoRA：用 0.8MB 的「补丁」改变模型
<!-- minutes: 20 -->
<!-- know: LoRA 低秩适配, 参数高效微调 PEFT, 秩 rank, 权重合并, 灾难性遗忘 -->

LoRA（Low-Rank Adaptation）是最常见的**参数高效微调**方法：不动原模型，只在一些权重矩阵旁边加一条低秩的「旁路」，只训练这条旁路。
原理：大矩阵 W（d×d）的更新量 ΔW 往往是低秩的，可以拆成两个小矩阵 `B(d×r) · A(r×d)`，r 远小于 d。输出变成 `W·x + B·A·x × scaling`。
- A 用高斯随机初始化，B 初始化为 **0**：训练开始时旁路输出为 0，模型行为和原来完全一样，然后慢慢学出差异。
- minimind 的实现（`model/model_lora.py`）完全手写，不依赖 peft 库，只给**输入输出维度相同的 Linear** 加旁路（也就是注意力里的 q_proj 和 o_proj）。

适用场景：基础模型缺医学知识，就叠一层医疗 LoRA；想让模型认自己的身份，就叠一层自我认知 LoRA。好处是只训很少参数、文件很小、可以随时卸下或换一个。

## LoRA 加在哪、有多少参数

```python
import torch, json, os
from model.model_lora import LoRA, apply_lora, load_lora, save_lora, merge_lora
tok = ss.tokenizer()
m = ss.load("full_sft")
base_n = sum(p.numel() for p in m.parameters())
apply_lora(m, rank=16)
lora_params = {n: p for n, p in m.named_parameters() if ".lora." in n}
ss.kv({"原模型参数": f"{base_n / 1e6:.1f}M", "LoRA 参数（rank=16）": f"{sum(p.numel() for p in lora_params.values()) / 1e6:.2f}M",
       "占比": f"{sum(p.numel() for p in lora_params.values()) / base_n:.2%}",
       "加了旁路的层": "、".join(sorted({n.split('.lora.')[0].split('.')[-1] for n in lora_params}))}, "LoRA 规模")
ss.table([[r, f"{2 * 768 * r * 16 / 1e6:.2f}M", f"{2 * 768 * r * 16 / base_n:.2%}"] for r in (4, 8, 16, 64)],
         cols=["rank", "参数量（16 个矩阵）", "占比"], title="rank 越大，旁路越粗、能表达的变化越多")
```

> 思考：为什么 B 要初始化成 0、A 用随机数？如果两个都是 0，或者都是随机数，会怎样？

## 写一份自己的「自我认知」数据
官方有 `lora_identity`（让模型说自己是 MiniMind）。我们换一个身份：本地学习平台的实践助教「小练」。几十条问答就够让 LoRA 记住。

```python
qs = ["你是谁", "你叫什么名字？", "介绍一下你自己", "你是哪个公司开发的？", "你和 ChatGPT 是什么关系？", "你能做什么？",
      "你的名字是什么", "请做个自我介绍", "你是 AI 吗？", "谁创造了你？", "你是什么模型", "你好，你是？"]
ans = ["我是小练，本地学习平台里的实践助教，基于 MiniMind 训练，专门陪你边学边动手。",
       "你好！我叫小练，是学习平台「实践」板块的助教，可以帮你理解每一步代码。",
       "我是小练，一个 6400 万参数的小模型，在你的电脑上用 LoRA 学会了自己的新身份。"]
rows = [{"conversations": [{"role": "user", "content": q}, {"role": "assistant", "content": ans[(i + j) % 3]}]}
        for i, q in enumerate(qs) for j in range(5)]
with open("dataset/lora_mine.jsonl", "w", encoding="utf-8") as f:
    f.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
ss.note(f"写好 {len(rows)} 条自我认知数据：dataset/lora_mine.jsonl")
```

## 训练 LoRA（本机，约 2–3 分钟）
从官方 SFT 模型出发，只训旁路。学习率 5e-4 比全参数微调大得多——旁路参数少、又要在几十条数据上记住新身份，需要更大的步子和更多轮。

```python long
base = ss.weights("full_sft_768.pth")
if not os.path.exists("out/base_full_sft_768.pth"):
    os.symlink(os.path.abspath(base), "out/base_full_sft_768.pth")
ss.train_live(f"python train_lora.py --data_path ../dataset/lora_mine.jsonl --from_weight base_full_sft --lora_name lora_mine "
              f"--save_dir ../out --epochs 12 --batch_size 8 --learning_rate 5e-4 --max_seq_len 256 --log_interval 5 --num_workers 0 --device {ss.device()}",
              cwd="trainer", title="LoRA 训练（自我认知，本机）")
ss.kv({"LoRA 文件": "out/lora_mine_768.pth", "大小": f"{os.path.getsize('out/lora_mine_768.pth') / 1e6:.2f} MB",
       "对比原模型权重": f"{os.path.getsize(base) / 1e6:.0f} MB"}, "产物")
```

## 挂上 / 卸下 LoRA 对比
同一个底座，挂不同的 LoRA 就是不同的「人格」。也试试官方的医疗 LoRA。

```python
plain = ss.load("full_sft")
mine = ss.load("full_sft", lora="out/lora_mine_768.pth")
for q in ["你是谁？", "你能帮我做什么？", "推荐一些中国的美食"]:
    ss.compare("原模型", ss.chat(plain, q, max_new_tokens=80, temperature=0.3), "挂上我的 LoRA", ss.chat(mine, q, max_new_tokens=80, temperature=0.3), title=q)
med = ss.load("full_sft", lora="lora_medical")
q = "我最近经常感到头晕，可能是什么原因？"
ss.compare("原模型", ss.chat(plain, q, max_new_tokens=120), "官方医疗 LoRA", ss.chat(med, q, max_new_tokens=120), title=q)
```

> 思考：问「推荐美食」时，挂了 LoRA 的模型还正常吗？如果用同样的数据做全参数微调，会发生什么？（提示：灾难性遗忘。作者建议全参微调时要把领域数据和通用数据混着训。）

## 官方身份 LoRA：`--lora_weight lora_identity`
README 里的第二个例子：`python eval_llm.py --weight full_sft --lora_weight lora_identity`，让模型认自己是「Jingyao Gong 开发的 MiniMind」。
ModelScope `gongjy/minimind-3-pytorch` 里实际发布了三个 LoRA：`lora_identity_768.pth`、`lora_medical_768.pth`、`lora_exam_768.pth`，各约 0.8MB。
注意 `--weight` 要和训 LoRA 时的底座一致（这里都是 `full_sft`），`--lora_rank` 也要和训练时一致（默认 16）。

```python
ident = ss.load("full_sft", lora="lora_identity")          # 没有就自动下载 out/official/lora_identity_768.pth
for q in ["你是谁？", "你和openai是什么关系？"]:
    ss.compare("关 LoRA（full_sft）", ss.chat(plain, q, max_new_tokens=80, temperature=0.3),
               "开 LoRA（lora_identity）", ss.chat(ident, q, max_new_tokens=80, temperature=0.3), title=q)
```

> 思考：要给 10 个客户各做一个「身份」，用 LoRA 要多存多少权重？全参微调呢？（一个底座约 138MB，一个 LoRA 约 0.8MB。）

## 合并：把补丁焊进模型
部署时不想多一次旁路计算，可以把 `B·A×scaling` 直接加回原权重，得到一个普通的完整模型（`merge_lora`，也是 `scripts/convert_model.py` 里 `convert_merge_base_lora` 做的事）。合并前后输出应该一致。

```python
from model.model_minimind import MiniMindConfig, MiniMindForCausalLM
src = MiniMindForCausalLM(MiniMindConfig())
src.load_state_dict(torch.load(base, map_location="cpu", weights_only=True))
apply_lora(src)
merge_lora(src, "out/lora_mine_768.pth", "out/full_sft_mine_merged_768.pth")
merged = ss.load(path="out/full_sft_mine_merged_768.pth")
ids = tok(tok.apply_chat_template([{"role": "user", "content": "你是谁？"}], tokenize=False, add_generation_prompt=True), return_tensors="pt").input_ids.to(ss.device())
with torch.no_grad():
    diff = (merged(ids).logits - mine(ids).logits).abs().max().item()
ss.kv({"合并后 vs 挂旁路 的最大 logits 差": f"{diff:.4f}（半精度保存带来的微小误差）", "合并后回答": ss.chat(merged, "你是谁？", temperature=0, max_new_tokens=60)}, "合并验证")
```
