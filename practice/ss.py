"""实践课在内核里用的小工具：可视化（平台原生渲染，不依赖 matplotlib）、调本机 Claude、取数据、带实时曲线的训练。

所有可视化都输出 MIME application/vnd.ssviz+json，平台前端按 kind 渲染；display_id 可原地更新（实时曲线）。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path

MIME = "application/vnd.ssviz+json"
PLATFORM = os.environ.get("SS_PLATFORM", "http://127.0.0.1:8780")
RUNTIME = os.environ.get("SS_RUNTIME", "local")


class View:
    def __init__(self, kind: str, data: dict, plain: str = ""):
        from IPython.display import display
        self.kind = kind
        self.h = display({MIME: {"kind": kind, **data}, "text/plain": plain or kind}, raw=True, display_id=True)

    def _ipython_display_(self):   # 作为格子最后一行的返回值时不再重复显示
        pass

    def update(self, **data):
        self.h.update({MIME: {"kind": self.kind, **data}, "text/plain": self.kind}, raw=True)


def show(kind: str, **data) -> View:
    """通用出口：show('table', cols=[...], rows=[...])。"""
    return View(kind, data)


def kv(pairs: dict | list, title: str = "") -> View:
    items = list(pairs.items()) if isinstance(pairs, dict) else list(pairs)
    return View("kv", {"title": title, "items": [[str(k), str(v)] for k, v in items]})


def table(rows: list, cols: list | None = None, title: str = "") -> View:
    if rows and isinstance(rows[0], dict):
        cols = cols or list(rows[0].keys())
        rows = [[r.get(c, "") for c in cols] for r in rows]
    return View("table", {"title": title, "cols": cols or [], "rows": [[str(x) for x in r] for r in rows[:200]]})


def bars(items: dict | list, title: str = "", unit: str = "", stacked: bool = False) -> View:
    """items: {名字: 数值} 或 [(名字, 数值, 备注)]；stacked=True 画成一条占比条。"""
    it = list(items.items()) if isinstance(items, dict) else list(items)
    return View("bars", {"title": title, "unit": unit, "stacked": stacked,
                         "items": [[str(x[0]), float(x[1]), str(x[2]) if len(x) > 2 else ""] for x in it]})


def tokens(text: str, tokenizer, title: str = "") -> View:
    ids = tokenizer(text, add_special_tokens=False).input_ids
    pieces = [tokenizer.decode([i]) for i in ids]
    return View("tokens", {"title": title or f"{len(text)} 个字符 → {len(ids)} 个 token",
                           "items": [[p, int(i)] for p, i in zip(pieces, ids)]})


def pieces(items: list, title: str = "") -> View:
    """直接显示 [(片段, id)] 或 [(片段, id, 是否高亮)]：用于自训分词器、标出参与 loss 的 token 等。"""
    return View("tokens", {"title": title, "items": [[str(x[0]), int(x[1]), *([bool(x[2])] if len(x) > 2 else [])] for x in items]})


def topk(pairs: list, title: str = "下一个词的概率") -> View:
    return View("bars", {"title": title, "unit": "%", "stacked": False,
                         "items": [[repr(t)[1:-1] if t.strip() != t or not t else t, round(float(p) * 100, 2), ""] for t, p in pairs]})


def heat(values, rows: list, cols: list, title: str = "") -> View:
    v = [[round(float(x), 4) for x in r] for r in (values.tolist() if hasattr(values, "tolist") else values)]
    return View("heat", {"title": title, "rows": [str(x) for x in rows], "cols": [str(x) for x in cols], "values": v})


def compare(a_title: str, a_text: str, b_title: str, b_text: str, title: str = "") -> View:
    return View("compare", {"title": title, "a": [a_title, a_text], "b": [b_title, b_text]})


def line(series: dict, title: str = "", x: str = "step", y: str = "loss") -> View:
    return View("line", {"title": title, "x": x, "y": y, "series": [[k, v] for k, v in series.items()]})


def trace(steps: list, title: str = "Agent 运行轨迹") -> View:
    """steps: [{role: user|assistant|tool|thought, name?, text}]"""
    return View("trace", {"title": title, "steps": steps})


def note(text: str, level: str = "info") -> View:
    return View("note", {"text": text, "level": level})


# ---------- 环境 ----------

def env_info() -> View:
    import platform
    info = {"运行环境": "阿里云 GPU" if RUNTIME == "cloud" else "本机", "Python": platform.python_version()}
    try:
        import torch
        info["PyTorch"] = torch.__version__
        if torch.cuda.is_available():
            p = torch.cuda.get_device_properties(0)
            info["加速"] = f"CUDA · {p.name} · {p.total_memory / 2**30:.0f} GB 显存"
            info["bf16"] = "支持" if torch.cuda.is_bf16_supported() else "不支持"
        elif getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            info["加速"] = "Apple MPS（统一内存）"
        else:
            info["加速"] = "只有 CPU"
    except ImportError:
        info["PyTorch"] = "未安装"
    return kv(info, "运行环境")


def device() -> str:
    import torch
    return "cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu"


# ---------- 调本机 Claude（经平台；云端经 SSH 反向隧道） ----------

def llm(prompt: str, system: str = "", timeout: int = 600) -> str:
    import httpx
    r = httpx.post(PLATFORM + "/api/practice/llm", json={"prompt": prompt, "system": system}, timeout=timeout, trust_env=False)
    r.raise_for_status()
    return r.json()["text"]


# ---------- 数据：只取前 N 行，不下整个数据集 ----------

MS = "https://www.modelscope.cn/datasets/{repo}/resolve/master/{file}"


def fetch_head(repo: str, file: str, lines: int, dst: str) -> str:
    """从 ModelScope 流式读前 N 行存到 dst（几 MB），够课堂小跑；全量用 modelscope download。"""
    import httpx
    p = Path(dst)
    if p.exists() and sum(1 for _ in p.open(encoding="utf-8")) >= lines:
        return str(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with httpx.stream("GET", MS.format(repo=repo, file=file), follow_redirects=True, timeout=120) as r, p.open("w", encoding="utf-8") as f:
        r.raise_for_status()
        for ln in r.iter_lines():
            if ln.strip():
                f.write(ln + "\n")
                n += 1
                if n >= lines:
                    break
    return str(p)


# ---------- 带实时 loss 曲线的训练 ----------

class Points(list):
    """训练曲线的点；作为格子最后一行时不再打印一长串数字。"""
    def _ipython_display_(self):
        pass


STEP_RE = re.compile(r"\((\d+)/(\d+)\)")


def train_live(cmd: str, cwd: str = ".", title: str = "训练中", metrics=("loss",), sample=None, every: int = 0) -> list:
    """跑训练命令，从日志里解析 (step/total) 和 metrics 里每个指标（如 loss / ce / distill / reward）画实时曲线。
    返回第一个指标的 [[step, 值], ...]；sample() 返回字符串时每 every 步插一条生成样例。"""
    import sys
    if cmd.startswith("python "):
        cmd = f'"{sys.executable}" -u ' + cmd[7:]          # 用内核同一个 Python 环境；-u 让日志实时吐出来
    env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTORCH_ENABLE_MPS_FALLBACK": "1"}
    res = {m: re.compile(rf"(?<![\w_]){re.escape(m)}:\s*(-?[\d.]+(?:e-?\d+)?)") for m in metrics}
    series = {m: [] for m in metrics}
    tail, samples = [], []
    v = View("line", {"title": title, "x": "step", "y": metrics[0], "series": [[m, []] for m in metrics], "tail": [], "samples": []})
    t0, last, prog = time.time(), 0.0, ""
    p = subprocess.Popen(cmd, shell=True, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, env=env)
    for ln in p.stdout:
        tail = (tail + [ln.rstrip()])[-8:]
        sm = STEP_RE.search(ln)
        got = False
        if sm:
            step = int(sm[1])
            for m, rx in res.items():
                mm = rx.search(ln)
                if mm:
                    series[m].append([step, float(mm[1])])
                    got = True
            if got:
                prog = f"{step}/{sm[2]} · {time.time() - t0:.0f}s"
                if sample and every and step // every > len(samples):
                    samples.append([step, sample()])
        if time.time() - last > 0.8 or got:
            v.update(title=title + (f" · {prog}" if prog else ""), x="step", y=metrics[0], series=[[m, series[m]] for m in metrics], tail=tail, samples=samples)
            last = time.time()
    p.wait()
    v.update(title=title + (" · 完成" if p.returncode == 0 else f" · 退出码 {p.returncode}"), x="step", y=metrics[0],
             series=[[m, series[m]] for m in metrics], tail=tail, samples=samples)
    if p.returncode:
        raise RuntimeError("训练命令失败，见上面日志最后几行")
    return Points(series[metrics[0]])


# ---------- minimind 课程用：官方权重、加载模型、对话、拉回云端权重 ----------

MS_MODEL = "https://www.modelscope.cn/models/{repo}/resolve/master/{file}"
_TOK = {}


def weights(file: str, repo: str = "gongjy/minimind-3-pytorch", out: str = "out/official") -> str:
    """把作者发布的官方权重（如 full_sft_768.pth，约 138MB）下到 out/official/，已有就跳过。和自己训的 out/*.pth 分开放，不会互相覆盖。"""
    import httpx
    p = Path(out) / file
    if p.exists() and p.stat().st_size > 1000:
        return str(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    v = View("note", {"text": f"下载官方权重 {file}…", "level": "info"})
    tmp, got, t0 = p.with_suffix(".part"), 0, time.time()
    with httpx.stream("GET", MS_MODEL.format(repo=repo, file=file), follow_redirects=True, timeout=300) as r, tmp.open("wb") as f:
        r.raise_for_status()
        total = int(r.headers.get("content-length") or 0)
        for chunk in r.iter_bytes(1 << 20):
            f.write(chunk)
            got += len(chunk)
            if time.time() - t0 > 1:
                v.update(text=f"下载官方权重 {file}：{got / 1e6:.0f} / {total / 1e6:.0f} MB", level="info")
                t0 = time.time()
    tmp.rename(p)
    v.update(text=f"已下载 {file}（{got / 1e6:.0f} MB）", level="info")
    return str(p)


def tokenizer(path: str = "./model"):
    if path not in _TOK:
        from transformers import AutoTokenizer
        _TOK[path] = AutoTokenizer.from_pretrained(path)
    return _TOK[path]


def load(weight: str = "full_sft", moe: bool = False, lora: str = "", path: str = "", mine: bool = False, hidden_size: int = 768,
         layers: int = 8, rope_scaling: bool = False, dev: str = ""):
    """加载 minimind。默认加载作者发布的官方权重（weight = pretrain / full_sft / dpo / grpo / ppo_actor / agent …，没有就自动下载）；
    mine=True 加载自己训的 out/<weight>_768.pth；path= 指定任意文件。"""
    import torch
    from model.model_minimind import MiniMindConfig, MiniMindForCausalLM
    name = f"{weight}_{hidden_size}{'_moe' if moe else ''}.pth"
    file = path or (f"out/{name}" if mine else f"out/official/{name}")
    if not Path(file).exists():
        if path or mine:
            raise FileNotFoundError(f"{file} 不存在：先跑这一课前面的训练格子")
        weights(name)
    m = MiniMindForCausalLM(MiniMindConfig(hidden_size=hidden_size, num_hidden_layers=layers, use_moe=moe, inference_rope_scaling=rope_scaling))
    m.load_state_dict(torch.load(file, map_location="cpu", weights_only=True), strict=False)
    if lora:
        from model.model_lora import apply_lora, load_lora
        lp = lora if lora.endswith(".pth") else f"out/official/{lora}_{hidden_size}.pth"
        if not Path(lp).exists():
            weights(Path(lp).name)
        apply_lora(m)
        load_lora(m, lp)
    return m.to(dev or device()).eval()


def chat(model, prompt, history=None, open_thinking=False, tools=None, max_new_tokens=256, temperature=0.7, top_p=0.9, raw=False) -> str:
    """一问一答。prompt 是字符串或完整 messages；raw=True 不套对话模板（给预训练模型续写用）。"""
    import torch
    tok = tokenizer()
    if raw:
        text = tok.bos_token + prompt
    else:
        msgs = prompt if isinstance(prompt, list) else [*(history or []), {"role": "user", "content": prompt}]
        text = tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True, open_thinking=open_thinking, tools=tools)
    dev = next(model.parameters()).device
    ids = tok(text, return_tensors="pt").to(dev)
    with torch.no_grad():
        out = model.generate(ids["input_ids"], attention_mask=ids["attention_mask"], max_new_tokens=max_new_tokens, do_sample=temperature > 0,
                             temperature=max(temperature, 1e-5), top_p=top_p, eos_token_id=tok.eos_token_id, pad_token_id=tok.pad_token_id)
    return tok.decode(out[0][ids["input_ids"].shape[1]:], skip_special_tokens=not tools and not open_thinking)


def from_cloud(path: str) -> str:
    """把云端课程目录里的文件（比如云上训的 out/pretrain_768.pth）拉回本机同一位置。"""
    import httpx
    r = httpx.post(PLATFORM + "/api/practice/pull", json={"course": Path.cwd().name, "path": path}, timeout=1800, trust_env=False)
    if r.status_code != 200:
        raise RuntimeError(r.json().get("detail", r.text))
    return r.json()["path"]
