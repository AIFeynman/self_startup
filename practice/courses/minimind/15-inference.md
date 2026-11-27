# 15 推理、长度外推与部署
<!-- minutes: 30 -->
<!-- know: 采样策略, temperature, top-p, KV 缓存, YaRN 长度外推, 困惑度, 模型格式转换, OpenAI 兼容接口, GGUF 量化 -->

模型训好了，怎么用好它：采样参数怎么调、为什么生成能这么快（KV 缓存）、训练时只见过几百个 token 怎么处理更长的文本（YaRN）、怎么转成 transformers 格式接进生态、怎么起 OpenAI 兼容接口、怎么搬到 llama.cpp / ollama / MNN 上跑。模型好不好怎么评，放在下一课。

## 采样：temperature 和 top-p 在改什么
模型每一步输出一个概率分布。**temperature** 把 logits 除以 T：T 小分布更尖（保守、重复），T 大更平（发散、易胡说）。**top-p** 只在累计概率达到 p 的最小候选集里采样，砍掉长尾。

```python
import torch, time, math, json, subprocess, os
tok = ss.tokenizer()
model = ss.load("full_sft")
ids = tok(tok.apply_chat_template([{"role": "user", "content": "写一句关于秋天的诗"}], tokenize=False, add_generation_prompt=True), return_tensors="pt").input_ids.to(ss.device())
with torch.no_grad():
    logits = model(ids).logits[0, -1].float()
for T in (0.3, 0.85, 1.5):
    p = (logits / T).softmax(-1)
    top = p.topk(10)
    ss.topk([(tok.decode([i]), v) for v, i in zip(top.values.tolist(), top.indices.tolist())], f"temperature = {T}：第一个字的分布")
sp = logits.softmax(-1).sort(descending=True).values
ss.kv({f"top-p = {pp} 时保留的候选数": int((sp.cumsum(0) < pp).sum()) + 1 for pp in (0.5, 0.9, 0.95, 0.99)}, "top-p 砍掉多少长尾")
ss.table([[T, ss.chat(model, "写一句关于秋天的诗", temperature=T, max_new_tokens=40)] for T in (0.3, 0.85, 1.5)], cols=["temperature", "输出"])
```

## KV 缓存：为什么生成越来越不慢
生成第 n 个 token 时，前面 n−1 个 token 的 K、V 已经算过了。**KV 缓存**把它们存下来，每步只算新 token——代价是显存（第 3 课算过 GQA 为什么能省一半）。关掉缓存，每步都要把整段重算一遍。

```python
def gen_speed(use_cache, n=128):
    with torch.no_grad():
        t = time.time()
        out = model.generate(ids, max_new_tokens=n, do_sample=False, use_cache=use_cache, eos_token_id=-1)
    return (out.shape[1] - ids.shape[1]) / (time.time() - t)
ss.bars({"开 KV 缓存": round(gen_speed(True), 1), "关 KV 缓存": round(gen_speed(False), 1)}, title="生成 128 个 token 的速度", unit=" token/s")
```

## YaRN：免训练把上下文拉长
minimind 训练时序列只有几百个 token。RoPE 遇到没见过的长位置，困惑度会飙升。**YaRN** 在推理时按频率分段缩放 RoPE（高频维度基本不动、低频维度按倍数压缩），免训练把可用长度拉长。
minimind 里只要 `inference_rope_scaling=True`（`eval_llm.py --inference_rope_scaling`）。代码里的参数是 `factor = 16`、`original_max_position_embeddings = 2048`（`model/model_minimind.py` 的 `MiniMindConfig`）；`eval_llm.py` 帮助文字写的「4 倍」和代码对不上，以代码为准。下面用拼起来的长文本，测不同长度下开 / 关 YaRN 的困惑度（作者用的是《西游记》白话文，结论一致：长文本上 YaRN 的 PPL 明显更低）。

```python long
texts = [json.loads(l)["text"] for l in open(ss.fetch_head("gongjy/minimind_dataset", "pretrain_t2t_mini.jsonl", 3000, "dataset/pretrain_head.jsonl"), encoding="utf-8")]
long_ids = tok("".join(texts[:400]), return_tensors="pt").input_ids[:, :4096].to(ss.device())
yarn = ss.load("full_sft", rope_scaling=True)
def ppl(m, L):
    x = long_ids[:, :L]
    with torch.no_grad():
        lp = m(x).logits[0, :-1].float().log_softmax(-1).gather(-1, x[0, 1:, None]).squeeze(-1)
    return math.exp(-lp[L // 2:].mean().item())         # 只算后半段：看模型在「远处」的表现
res = {"原始 RoPE": [], "YaRN 外推": []}
for L in (256, 512, 1024, 2048, 4096):
    res["原始 RoPE"].append([L, round(ppl(model, L), 2)])
    res["YaRN 外推"].append([L, round(ppl(yarn, L), 2)])
ss.line(res, title="不同输入长度下的困惑度（越低越好）", x="上下文长度", y="PPL")
```

> 思考：YaRN 只解决了「位置编码没见过」的问题。模型在长文本上真的能用好远处的信息吗？还需要什么？

## 转成 transformers 格式
作者主线发布的模型通常是 transformers 格式；自己训的是原生 torch 的 `.pth`。`scripts/convert_model.py` 负责互转：
- `convert_torch2transformers`：把权重装进 `Qwen3ForCausalLM`（MoE 装进 `Qwen3MoeForCausalLM`），存成标准目录，任何认 Qwen3 的工具都能直接用；
- `convert_torch2transformers_minimind`：保留 MiniMind 自己的类，加载时要 `trust_remote_code=True`；
- `convert_transformers2torch`：反过来存回 `.pth`。

脚本把 `lm_config` 写在 `__main__` 里、分词器路径写死成 `../model/`，所以下面 import 后手动补上配置，并临时切到 `scripts/` 目录。转出到系统临时目录，不碰仓库。

```python
import importlib, tempfile, shutil
from transformers import AutoModelForCausalLM, AutoTokenizer
from model.model_minimind import MiniMindConfig
cm = importlib.import_module("scripts.convert_model")
cm.lm_config = MiniMindConfig(hidden_size=768, num_hidden_layers=8, max_seq_len=8192)
hf_dir = tempfile.mkdtemp(prefix="minimind-3-")
root = os.getcwd()
os.chdir("scripts")
try:
    cm.convert_torch2transformers(f"{root}/out/official/full_sft_768.pth", hf_dir)
finally:
    os.chdir(root)
hf = AutoModelForCausalLM.from_pretrained(hf_dir, dtype=torch.float32).eval()      # 放 CPU：Qwen3 在 MPS 上 generate 会报维度错
hf_tok = AutoTokenizer.from_pretrained(hf_dir)
x = hf_tok(hf_tok.apply_chat_template([{"role": "user", "content": "你好，请介绍一下你自己"}], tokenize=False, add_generation_prompt=True), return_tensors="pt")
with torch.no_grad():
    y = hf.generate(x["input_ids"], attention_mask=x["attention_mask"], max_new_tokens=60, do_sample=False)
ss.kv({"转出目录": hf_dir, "目录里的文件": "、".join(sorted(os.listdir(hf_dir))), "architectures": json.load(open(f"{hf_dir}/config.json"))["architectures"][0],
       "AutoModelForCausalLM 加载后回答": hf_tok.decode(y[0][x["input_ids"].shape[1]:], skip_special_tokens=True)}, "torch → transformers")
```

这就是 `python eval_llm.py --load_from ./minimind-3` 做的事：`--load_from` 不是 `model` 时，它走 `AutoModelForCausalLM.from_pretrained` 分支，和上面一样。再转回去，确认两边算出来一样：

```python
back = f"{hf_dir}/back_768.pth"
cm.convert_transformers2torch(hf_dir, back)
mm = ss.load(path=back, dev="cpu")
with torch.no_grad():
    la, lb = mm(x["input_ids"]).logits.float(), hf(x["input_ids"]).logits.float()
ss.kv({"下一个词是否一致": bool((la[0, -1].argmax() == lb[0, -1].argmax()).item()), "logits 最大差": f"{(la - lb).abs().max().item():.4f}（fp16 存盘的舍入）"}, "transformers → torch")
```

transformers 格式的模型要开 YaRN，在 `config.json` 里加 `rope_scaling`（README 给的写法）。下面复制一份目录、加上这段配置，和 minimind 自己的 `inference_rope_scaling=True` 在 4096 个 token 上比 logits：

```python
yarn_dir = hf_dir + "-yarn"
shutil.copytree(hf_dir, yarn_dir, dirs_exist_ok=True)
c = json.load(open(f"{yarn_dir}/config.json"))
c["rope_scaling"] = {"type": "yarn", "factor": 16.0, "original_max_position_embeddings": 2048, "beta_fast": 32.0, "beta_slow": 1.0, "attention_factor": 1.0}
json.dump(c, open(f"{yarn_dir}/config.json", "w"), indent=2)
hf_yarn = AutoModelForCausalLM.from_pretrained(yarn_dir, dtype=torch.float32).eval()
x4k = long_ids[:, :4096].cpu()                       # 上一节 YaRN 格子里拼的长文本
with torch.no_grad():
    a, b, plain = hf_yarn(x4k).logits[0], yarn.to("cpu")(x4k).logits[0], hf(x4k).logits[0]
yarn.to(ss.device())
ss.kv({"config.json 加 rope_scaling vs --inference_rope_scaling：logits 最大差": f"{(a - b).abs().max().item():.4f}",
       "对照：不加 rope_scaling 的最大差": f"{(plain - b).abs().max().item():.2f}"}, "两种 YaRN 写法是否等价")
```

> 思考：同一份权重，装进 `Qwen3ForCausalLM` 就能被 vLLM、llama.cpp、lm_eval 直接用。MiniMind 的结构要和 Qwen3 对齐到什么程度，这种「换壳」才不掉精度？（提示：看 `strict=True`。）

## 部署：OpenAI 兼容接口
`scripts/serve_openai_api.py` 起一个兼容 OpenAI API 的服务（端口 8998），支持 `reasoning_content`、`tool_calls`、`open_thinking`，可以直接接进 FastGPT、OpenWebUI、Dify 这类 UI。下面在后台起服务，用 openai SDK 调一次，再关掉。

两个坑：服务端请求体 `stream` 默认是 `True`，SDK 不传就会收到流式文本，`r.choices` 报 `'str' object has no attribute 'choices'`，所以要显式 `stream=False`；本机设了代理时，SDK 默认的 httpx 会把 127.0.0.1 的请求也发给代理，所以传一个 `trust_env=False` 的 `http_client`。

```python long
import sys, httpx
from openai import OpenAI
log = open("out/serve_openai_api.log", "w")
proc = subprocess.Popen([sys.executable, "serve_openai_api.py", "--save_dir", "out/official", "--weight", "full_sft",
                         "--device", ss.device()], cwd="scripts", stdout=log, stderr=subprocess.STDOUT)
http = httpx.Client(trust_env=False, timeout=120)       # 不走系统代理：本机设了 HTTP(S)_PROXY 时，发往 127.0.0.1 的请求会被代理截走
try:
    for _ in range(120):                               # 等服务就绪：端口能连上（GET / 返回 404 也算）
        if proc.poll() is not None:
            raise RuntimeError("服务启动失败：\n" + open("out/serve_openai_api.log").read()[-1500:])
        try:
            http.get("http://127.0.0.1:8998/")
            break
        except httpx.ConnectError:
            time.sleep(1)
    client = OpenAI(api_key="none", base_url="http://127.0.0.1:8998/v1", http_client=http)
    r = client.chat.completions.create(model="minimind", messages=[{"role": "user", "content": "用一句话介绍你自己"}], max_tokens=80, stream=False)
    r2 = client.chat.completions.create(model="minimind", messages=[{"role": "user", "content": "1+1 等于几？"}], max_tokens=512, stream=False,
                                        extra_body={"chat_template_kwargs": {"open_thinking": True}})
finally:
    proc.terminate()
    proc.wait()
ss.kv({"普通回答": r.choices[0].message.content, "开思考后的回答": r2.choices[0].message.content,
       "思考过程（reasoning_content）": getattr(r2.choices[0].message, "reasoning_content", None) or "（没拿到：思考没在 max_tokens 内写完 </think>，全部落进了 content）"}, "通过 OpenAI SDK 调本地 minimind")
```

`scripts/chat_api.py` 是一个命令行聊天客户端：同样用 openai SDK，默认连 `http://localhost:11434/v1`（ollama 的端口）、流式输出、思考内容用灰色打印。换成 8998 就能连上面这个服务。
`scripts/web_demo.py` 是 streamlit 网页版（`pip install streamlit` 后 `cd scripts && streamlit run web_demo.py`）。它会扫描 `scripts/` 下带权重文件的子目录，所以要先把 transformers 格式的模型目录复制进去，比如 `cp -r minimind-3 ./scripts/minimind-3`。侧边栏可以调历史轮数、生成长度、温度，开关思考和工具。

## 搬到别的推理框架
**vLLM / SGLang**：高吞吐服务，需要 CUDA。都能直接起 OpenAI 兼容服务：`vllm serve /path/to/model --model-impl transformers --served-model-name "minimind" --port 8998`。

**llama.cpp**：C++ 推理，CPU / Mac 都能跑。先把 transformers 目录转 GGUF。MiniMind 的分词器 llama.cpp 不认识，要在 `convert_hf_to_gguf.py` 的 `get_vocab_base_pre` 函数末尾插一段，临时复用 qwen2：

```text
if res is None:
    res = "qwen2"
```

然后在 llama.cpp 目录下：

```text
python convert_hf_to_gguf.py /path/to/minimind-model                                  # 生成 gguf
./build/bin/llama-quantize /path/to/model/xxxx.gguf /path/to/model/xxxx.q8.gguf Q8_0  # 可选：8-bit 量化
./build/bin/llama-cli -m /path/to/model/xxxx.gguf
```

**ollama**：在模型目录写一个 `minimind.modelfile`：`FROM /path/to/model/xxxx.gguf`，加 SYSTEM 提示、对话模板（`<|im_start|>` / `<|im_end|>`、`<tool_call>`、`<think>` 那一套，完整模板见 README）和参数（`stop "<|im_end|>"`、`temperature 0.9`、`top_p 0.9`、`num_ctx 8192`）。然后 `ollama create -f minimind.modelfile minimind-local`、`ollama run minimind-local`。
不想自己转，直接用作者推到 Ollama Hub 的：`ollama run jingyaogong/minimind-3`。

**MNN**：阿里的端侧推理引擎，导出 4-bit HQQ 量化模型上手机：

```text
cd MNN/transformers/llm/export
python llmexport.py --path /path/to/模型路径/ --export mnn --hqq --dst_path 模型路径-mnn
./llm_demo /path/to/模型路径-mnn/config.json prompt.txt
```

可选：本机装了 ollama 并已经 `ollama run jingyaogong/minimind-3` 拉过模型，下面这格就用 openai SDK 走 ollama 的 OpenAI 兼容端口（11434）调它；没装或没拉，只给提示，不会去下载。

```python
import shutil
listed = subprocess.run(["ollama", "list"], capture_output=True, text=True).stdout if shutil.which("ollama") else ""
names = [l.split()[0] for l in listed.splitlines()[1:] if "minimind" in l]
if not names:
    ss.note("本机没有 ollama，或还没拉 minimind：在终端跑 `ollama run jingyaogong/minimind-3`（会下载模型），再回来重跑这格。" if shutil.which("ollama") else
            "本机没装 ollama：见 https://ollama.com 安装后，在终端跑 `ollama run jingyaogong/minimind-3`。")
else:
    oc = OpenAI(api_key="ollama", base_url="http://127.0.0.1:11434/v1", http_client=httpx.Client(trust_env=False, timeout=120))
    r = oc.chat.completions.create(model=names[0], messages=[{"role": "user", "content": "你叫什么名字"}], max_tokens=80, stream=False)
    ss.kv({"ollama 模型": names[0], "回答": r.choices[0].message.content}, "通过 ollama 调 minimind")
```

> 思考：GGUF 的 Q8_0 量化把每个权重从 16 位压到约 8 位。对 64M 这么小的模型，量化省下的内存几乎无关紧要，那在什么场景下它仍然值得做？

## 课程小结
你已经亲手走完了一个大模型的完整生命周期：分词 → 数据 → 结构 → 预训练 → SFT → 思考与工具调用 → LoRA → 蒸馏 → DPO → PPO → GRPO / CISPO → Agentic RL → MoE → 推理部署，下一课再看怎么评估它。
回头看第 11 课那张统一视角的表：后训练的各种 xxPO 只是同一个目标函数的不同取舍；而每一次「把某种能力拉高」，几乎都伴随某种对齐税。

> 思考：如果只给你 100 元云预算，你会怎么分配到预训练、SFT、RL 各个阶段，来做一个「会用工具算账的小助手」？
