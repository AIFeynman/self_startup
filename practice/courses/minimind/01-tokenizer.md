# 1 分词器：模型看到的不是字，是 token
<!-- minutes: 10 -->
<!-- know: 分词, BPE, 词表大小, 特殊 token -->
<!-- gpu: no -->

模型只认识整数。分词器把文字切成一个个 **token**，再换成编号。切得好不好，直接决定模型「一口能吃下多少内容」。

## 加载 minimind 的分词器
minimind 的词表只有 **6400** 个 token（GPT-4 约 10 万）。词表小，模型的嵌入层和输出层就小——64M 的小模型里，这能省下大量参数。

```python
from transformers import AutoTokenizer
tok = AutoTokenizer.from_pretrained("./model")
ss.kv({"词表大小": tok.vocab_size, "开始符 bos": tok.bos_token, "结束符 eos": tok.eos_token, "填充符 pad": tok.pad_token}, "分词器")
```

## 看看一句话被切成什么
颜色块是一个个 token。注意中文常见词会被合成一个 token，生僻词会被拆碎。

```python
for s in ["今天天气真好，适合出去散步。", "Large language models predict the next token.", "def add(a, b): return a + b", "量子纠缠的退相干时间"]:
    ss.tokens(s, tok)
```

> 思考：「量子纠缠」被切成了几块？词表小的代价是什么？（提示：同样一段话，token 越多，模型要算的步数越多，能看的上下文越短。）

## 压缩率：每个 token 平均几个字符
BPE（字节对编码）从单个字节开始，反复把语料里最常一起出现的两块合并成新 token，直到词表满。所以训练语料里常见的东西压缩率高。

```python
samples = {"中文": "人工智能正在改变我们的生活方式，从医疗到教育都有深远影响。",
           "英文": "Artificial intelligence is changing the way we live, from healthcare to education.",
           "代码": "for i in range(10):\n    print(i * i)"}
ss.bars({k: round(len(v) / len(tok(v, add_special_tokens=False).input_ids), 2) for k, v in samples.items()},
        title="每个 token 平均包含的字符数（越大越省）", unit=" 字符")
```

> 思考：minimind 的语料以中文为主。如果拿它去处理大量英文代码，会出现什么问题？
