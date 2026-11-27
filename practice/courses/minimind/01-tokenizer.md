# 1 分词器：模型看到的不是字，是 token
<!-- minutes: 15 -->
<!-- know: 分词, BPE 字节对编码, 词表大小, 特殊 token, BPB 与 PPL -->

分词器可以粗略理解成大模型的一本「词典」：把文字切成一个个 **token**，换成编号喂给模型；模型输出编号，再解码回文字。
切得好不好，直接决定模型「一口能吃下多少内容」、要算多少步，甚至影响按 token 统计的指标（比如困惑度 PPL）。

## 加载 minimind 的分词器
minimind 的词表只有 **6400** 个 token。主流模型动辄几万到十几万：

| 分词器 | 词表大小 | 来源 |
|---|---|---|
| Yi | 64,000 | 零一万物 |
| Qwen2 | 151,643 | 阿里云 |
| ChatGLM | 151,329 | 智谱 |
| Mistral | 32,000 | Mistral AI |
| Llama 3 | 128,000 | Meta |
| **MiniMind** | **6,400** | 自训 |

为什么这么小？词表每多一个 token，词嵌入表就多一行，一行 `隐藏维度` 个参数。768 维下，Qwen2 的词表一张表就是 151,643 × 768 ≈ **1.16 亿**参数。
minimind 的输入嵌入和输出层共用这一张表（权重共享，第 3 课细讲）；要是不共享就是两张，约 **2.3 亿**。两种算法都比整个 minimind（64M）还大。小模型把参数留给真正干活的层更划算。

当前主线只用这一套 `minimind_tokenizer`，**不再维护 `mistral_tokenizer` 版本**，避免历史版本混淆。6400 词表编码效率比 qwen2、glm 这类中文友好的分词器弱，但作者实测并没有明显的生僻词解码失败，够稳定。

```python
tok = ss.tokenizer("./model")
ss.kv({"词表大小": tok.vocab_size, "开始符 bos": tok.bos_token, "结束符 eos": tok.eos_token, "填充符 pad": tok.pad_token,
       "特殊 token 数": len(tok.all_special_tokens)}, "minimind 分词器")
ss.bars({"MiniMind 6.4k": 6400 * 768 / 1e6, "Mistral 32k": 32000 * 768 / 1e6, "Llama3 128k": 128000 * 768 / 1e6, "Qwen2 152k": 151643 * 768 / 1e6},
        title="同样 768 维，词嵌入层要多少参数", unit="M")
```

> 思考：minimind 总共 64M 参数。如果换成 Qwen2 的词表（且输入输出共用一张表），模型会变成多大？多出来的参数能让模型更聪明吗？

## 看看一句话被切成什么
颜色块是一个个 token。中文常见词会被合成一个 token，生僻词会被拆碎。作者的经验：中文大约 **1.5~1.7 字符/token**，纯英文 **4~5 字符/token**。

```python
for s in ["白日依山尽，黄河入海流。", "The sun sets in the west.", "def add(a, b): return a + b", "量子纠缠的退相干时间"]:
    ss.tokens(s, tok)
```

词表小，会不会碰到生僻字就解不回来？BPE 从字节起步，任何字最差也能拆成字节，所以理论上不会丢字。下面拿一组生僻字、繁体、emoji 做「编码 → 解码」往返验证。

```python
rare = ["饕餮", "魑魅魍魉", "龘靐齉", "𠮷野家", "臺灣繁體", "🤖🚀", "Ωμέγα"]
ss.table([[w, len(tok(w, add_special_tokens=False).input_ids), tok.decode(tok(w, add_special_tokens=False).input_ids) == w] for w in rare],
         cols=["文本", "token 数", "解码后一字不差"], title="生僻字往返测试")
```

> 思考：生僻字能解回来，但被拆成了很多个字节级 token。这对模型「理解」这个字有什么影响？对生成速度呢？

## BPE 是怎么学出来的：自己训一个
**BPE（字节对编码）**：从单个字节开始，统计语料里最常一起出现的两块，合并成一个新 token，反复做直到词表满。
所以语料里常见的东西压缩率高，没见过的会被拆碎。minimind 仓库的 `trainer/train_tokenizer.py` 就是这个流程，下面用 3000 条预训练文本、几秒钟训三个不同大小的词表。

```python
from tokenizers import Tokenizer, models, pre_tokenizers, trainers, decoders
import json
path = ss.fetch_head("gongjy/minimind_dataset", "pretrain_t2t_mini.jsonl", 3000, "dataset/pretrain_head.jsonl")
texts = [json.loads(l)["text"] for l in open(path, encoding="utf-8")]

def train_bpe(vocab):
    t = Tokenizer(models.BPE())
    t.pre_tokenizer = pre_tokenizers.ByteLevel(add_prefix_space=False)
    t.decoder = decoders.ByteLevel()
    t.train_from_iterator(texts, trainers.BpeTrainer(vocab_size=vocab, special_tokens=["<|endoftext|>"], show_progress=False,
                                                     initial_alphabet=pre_tokenizers.ByteLevel.alphabet()))
    return t

mine = {v: train_bpe(v) for v in (300, 1000, 4000)}
probe = "人工智能正在改变我们的生活方式，从医疗到教育都有深远影响。"
for v, t in mine.items():
    enc = t.encode(probe)
    ss.pieces([(t.decode([i]) or "·", i) for i in enc.ids], title=f"我训的 {v} 词表：{len(enc.ids)} 个 token")
```

词表小的时候，一个汉字常被拆成几个字节块（显示成 � 或「·」），这正是 BPE 从字节起步的痕迹。下面直接比数量：

```python
cnt = {f"自训 {v}": len(t.encode(probe).ids) for v, t in mine.items()}
cnt["minimind 6400"] = len(tok(probe, add_special_tokens=False).input_ids)
cnt["按字节（不合并）"] = len(probe.encode("utf-8"))
ss.bars(cnt, title=f"同一句话（{len(probe)} 个字）切成多少个 token", unit=" 个")
ss.table([[t.id_to_token(i), i] for i in range(300, 312)], cols=["最早学会的合并（字节形式）", "id"], title="自训 4000 词表里排在最前面的几个合并")
```

> 思考：作者**不建议重新训练分词器**。词表一变，哪些东西都要跟着变？（提示：权重、数据格式、推理接口、和社区模型的兼容性。）

## 跑一次仓库自带的 train_tokenizer.py
上面是简化版。仓库的 `trainer/train_tokenizer.py` 多做了三件事：
- **先占 36 个 id（0–35）**：21 个 `<|endoftext|>`、`<|im_start|>`、`<|im_end|>` 这类标记（标成 special，也就是上面看到的「特殊 token 数 21」）；6 个 `<tool_call>`、`<think>` 等工具/思考标记（不标 special，`skip_special_tokens` 时也会保留）；剩下的用 `<|buffer1|>…` 占位，给以后留位置。
- **写 `tokenizer_config.json`**：bos=`<|im_start|>`、eos=`<|im_end|>`、pad=`<|endoftext|>`，并内置 **chat_template**（对话模板，第 2 课会用）。
- **自带 eval**：压缩率、编解码一致性、流式解码。

脚本默认读全量 SFT 数据。这里直接 import 它的函数，喂 2000 条 SFT 样本，词表仍是 6400，输出到 `out/learn_tokenizer/`，不碰 `model/` 里的正式分词器。

```python
import io, contextlib
from trainer.train_tokenizer import train_tokenizer, eval_tokenizer
from transformers import AutoTokenizer
sft_path = ss.fetch_head("gongjy/minimind_dataset", "sft_t2t_mini.jsonl", 2000, "dataset/sft_head.jsonl")
with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
    train_tokenizer(sft_path, "out/learn_tokenizer", 6400)
learned = AutoTokenizer.from_pretrained("out/learn_tokenizer")
ss.kv({"词表大小": len(learned), "bos / eos / pad": f"{learned.bos_token} / {learned.eos_token} / {learned.pad_token}",
       "id 0–35 和官方分词器一致": [learned.convert_ids_to_tokens(i) for i in range(36)] == [tok.convert_ids_to_tokens(i) for i in range(36)]}, "我训出的分词器")
ss.table([[i, learned.convert_ids_to_tokens(i)] for i in range(36)], cols=["id", "特殊 token"], title="id 0–35：先占位的特殊 token")
msgs = [{"role": "system", "content": "你是一个优秀的聊天机器人"}, {"role": "user", "content": "你来自哪里？"}, {"role": "assistant", "content": "我来自地球"}]
ss.compare("chat_template 渲染结果", learned.apply_chat_template(msgs, tokenize=False),
           "编码后的 token 数", f"我训的：{len(learned(learned.apply_chat_template(msgs, tokenize=False)).input_ids)}\n官方的：{len(tok(tok.apply_chat_template(msgs, tokenize=False)).input_ids)}",
           title="脚本写进 tokenizer_config.json 的对话模板")
log = io.StringIO()
with contextlib.redirect_stdout(log):
    eval_tokenizer("out/learn_tokenizer")
ss.table([[l] for l in log.getvalue().splitlines() if "压缩率" in l or "一致性" in l], cols=["脚本自带 eval 的输出（节选）"], title="eval_tokenizer：编解码一致性与压缩率")
```

> 思考：特殊 token 为什么要在 BPE 训练**之前**就占好 id 0–35？如果训完再追加，会和哪些东西冲突？

## 压缩率与跨分词器比较
同一句话，不同分词器切出的 token 数不同，所以按 token 算的困惑度（PPL）不能直接跨模型比较。更公平的是 **BPB（每字节比特数）**：把总损失摊到原始字节上。

```python
samples = {"中文": "人工智能正在改变我们的生活方式，从医疗到教育都有深远影响。",
           "英文": "Artificial intelligence is changing the way we live, from healthcare to education.",
           "代码": "for i in range(10):\n    print(i * i)"}
ss.bars({k: round(len(v) / len(tok(v, add_special_tokens=False).input_ids), 2) for k, v in samples.items()},
        title="minimind：每个 token 平均包含的字符数（越大越省）", unit=" 字符")
```

> 思考：minimind 以中文语料为主。拿它去处理大量英文代码会怎样？如果两个模型的 PPL 分别是 8 和 12，能直接说前者更好吗？
