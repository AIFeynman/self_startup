"""只评估「本人发声判断」：用 people_eval 产出的已标注参考池（pool_<渠道>.json + labels.json）离线跑 voice_filter，
算判断层相对标注的准确率 / 召回率，不调用任何外部搜索接口。

python scripts/people_judge_eval.py --eval-dir <people_eval 输出目录> [--channels news,podcast,youtube]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import agent  # noqa: E402
from app.modules import _people as P  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--eval-dir", required=True)
    ap.add_argument("--channels", default="news,podcast,youtube")
    ap.add_argument("--model", default="claude-haiku-5-5")
    a = ap.parse_args()
    d = Path(a.eval_dir)
    labels = json.loads((d / "labels.json").read_text())
    run = lambda prompt, system="", model="": agent.run_once(prompt, engine="claude", system=system, model=model, readonly=True, fallback=False)
    for ch in a.channels.split(","):
        f = d / f"pool_{ch}.json"
        if not f.exists():
            continue
        pool = [it for it in json.loads(f.read_text()) if it["id"] in labels]
        kept, errs = P.voice_filter(pool, run, a.model)
        keep = {it["id"] for it in kept}
        gold = {i for i in (it["id"] for it in pool) if labels[i]["voice"]}
        ev = lambda ids: {labels[i].get("event") or i for i in ids}
        tp = keep & gold
        print(ch, {"pool": len(pool), "gold": len(gold), "kept": len(keep),
                   "precision": round(len(tp) / len(keep), 3) if keep else None,
                   "recall": round(len(tp) / len(gold), 3) if gold else None,
                   "event_recall": round(len(ev(tp)) / len(ev(gold)), 3) if gold else None, "errors": errs})
        for it in pool:
            if (it["id"] in keep) != (it["id"] in gold):
                print("   ", "FP" if it["id"] in keep else "FN", ",".join(it["people"]), "|", it["title"][:80], "|",
                      it["extra"].get("show") or it["extra"].get("uploader") or it["extra"].get("outlet") or "", "|", labels[it["id"]].get("note"))


if __name__ == "__main__":
    main()
