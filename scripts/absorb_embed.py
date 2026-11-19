"""吸收流水线的向量计算：absorb_embed.py <文本列表.json> <输出.npy> <最大长度> <模型> <缓存目录>

需要 torch 和 transformers，所以由设置 absorb.embed_python 指定的解释器单独运行。
算过的文本按内容存在缓存目录里，换选题时论文、开源项目、产品动态这些重复出现的材料不用再算。
"""
import fcntl
import hashlib
import json
import os
import sys
from pathlib import Path

import numpy as np

src, out, max_len, model, cache = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4], Path(sys.argv[5])
texts = json.load(open(src, encoding="utf-8"))
cache.mkdir(parents=True, exist_ok=True)
lock = open(cache / "lock", "w")
fcntl.flock(lock, fcntl.LOCK_EX)
tag = hashlib.sha1(f"{model}|{max_len}".encode()).hexdigest()[:10]
kf, vf = cache / f"{tag}.keys.json", cache / f"{tag}.npy"
keys = json.load(open(kf, encoding="utf-8")) if kf.exists() else []
vecs = np.load(vf) if vf.exists() else None
pos = {k: i for i, k in enumerate(keys)}
hs = [hashlib.sha1(t.encode()).hexdigest() for t in texts]
todo = list(dict.fromkeys(h for h in hs if h not in pos))
print(f"{len(texts)} 条，缓存命中 {len(texts) - sum(h not in pos for h in hs)}，要算 {len(todo)}", flush=True)
if todo:
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    import torch
    from transformers import AutoModel, AutoTokenizer
    snaps = sorted((Path.home() / ".cache/huggingface/hub" / ("models--" + model.replace("/", "--")) / "snapshots").glob("*"))
    path = str(snaps[-1]) if snaps else model
    tok = AutoTokenizer.from_pretrained(path, padding_side="left")
    m = AutoModel.from_pretrained(path, torch_dtype=torch.float32).eval()
    first = {h: t for h, t in zip(reversed(hs), reversed(texts))}
    new = []
    with torch.no_grad():
        for s in range(0, len(todo), 16):
            b = tok([first[h] for h in todo[s:s + 16]], padding=True, truncation=True, max_length=max_len, return_tensors="pt")
            new.append(torch.nn.functional.normalize(m(**b).last_hidden_state[:, -1], dim=-1).numpy())
            if s % 800 == 0:
                print(s, len(todo), flush=True)
    new = np.concatenate(new)
    vecs = new if vecs is None else np.concatenate([vecs, new])
    keys += todo
    pos = {k: i for i, k in enumerate(keys)}
    np.save(cache / f"{tag}.tmp.npy", vecs)
    (cache / f"{tag}.tmp.npy").replace(vf)
    kf.write_text(json.dumps(keys), "utf-8")
np.save(out, vecs[[pos[h] for h in hs]] if texts else np.zeros((0, 1024), dtype=np.float32))
