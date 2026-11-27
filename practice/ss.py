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

LOSS_RE = re.compile(r"\((\d+)/(\d+)\).*?loss:\s*([\d.]+)")


def train_live(cmd: str, cwd: str = ".", title: str = "训练中", sample=None, every: int = 0) -> list:
    """跑训练命令，解析日志里的 (step/total) loss 画实时曲线；sample() 返回字符串时每 every 步插一条生成样例。"""
    pts, tail, samples = [], [], []
    v = View("line", {"title": title, "x": "step", "y": "loss", "series": [["loss", pts]], "tail": [], "samples": []})
    t0, last = time.time(), 0.0
    p = subprocess.Popen(cmd, shell=True, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    for ln in p.stdout:
        tail = (tail + [ln.rstrip()])[-8:]
        m = LOSS_RE.search(ln)
        if m:
            step, total, loss = int(m[1]), int(m[2]), float(m[3])
            pts.append([step, loss])
            if sample and every and step // every > len(samples):
                samples.append([step, sample()])
            prog = f"{step}/{total} · {time.time() - t0:.0f}s"
        else:
            prog = None
        if time.time() - last > 0.8 or m:
            v.update(title=title + (f" · {prog}" if prog else ""), x="step", y="loss", series=[["loss", pts]], tail=tail, samples=samples)
            last = time.time()
    p.wait()
    v.update(title=title + (" · 完成" if p.returncode == 0 else f" · 退出码 {p.returncode}"), x="step", y="loss",
             series=[["loss", pts]], tail=tail, samples=samples)
    if p.returncode:
        raise RuntimeError("训练命令失败，见上面日志最后几行")
    return pts
