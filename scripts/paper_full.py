"""论文脉络库全量跑（设计稿 §2 / §7 P1）：分类体系 52 个二级方向 × 年份切片 → 门槛 → 详情 → 经典回拉 → Jev → 标注。

用法（写 SELF_STARTUP_DATA 指向的库，正式库先备份）：
    SELF_STARTUP_DATA=<目录> uv run python -m scripts.paper_full collect [方向code ...]
    ... judge | label | all
每一步都能重跑：采集按方向记进度跳过已做的，标注按 label_src 哈希跳过已标的；进度和花费记到 <目录>/paper_full.json。
"""
from __future__ import annotations

import json
import logging
import re
import sys
import time
from datetime import datetime

from app import db
from app.modules import _paper_collect as col, _paper_label as lab

# 二级方向 → S2 检索式（英文，S2 bulk 语法：| 或、+ 与、"" 短语）。分类体系的 eg 是中文，S2 只认英文。
QUERIES = {
    "arch": '"transformer architecture" | "attention mechanism" | "self-attention" | "positional encoding" | "layer normalization" | "efficient transformer"',
    "moe": '"mixture of experts" | "mixture-of-experts" | "sparsely-gated" | "expert routing" | "sparse expert"',
    "ssm": '"state space model" | Mamba | RWKV | "linear attention" | "linear transformer" | "structured state space"',
    "pt_data": '"pretraining data" | "pre-training data" | "data mixture" | "data filtering" | "deduplication" | ("synthetic data" + "language model")',
    "scaling": '"scaling laws" | "scaling law" | "compute-optimal" | "emergent abilities" | ("scaling" + "language models")',
    "tokenizer": 'tokenizer | tokenization | "byte pair encoding" | "subword units" | "byte-level"',
    "long_ctx": '"long context" | "long-context" | "context window" | "length extrapolation" | "rotary position" | "long sequence"',
    "pt_obj": '"masked language model" | "self-supervised learning" | "contrastive learning" | "masked autoencoder" | "pre-training objective"',
    "sft": '"instruction tuning" | "instruction-tuned" | "instruction following" | "supervised fine-tuning" | "instruction data"',
    "pref_opt": '"reinforcement learning from human feedback" | RLHF | "preference optimization" | "direct preference" | "human preferences"',
    "reason_rl": '"verifiable rewards" | GRPO | ("reinforcement learning" + reasoning + "language models") | "long chain-of-thought"',
    "reward_model": '"reward model" | "reward modeling" | "process reward" | "reward hacking" | "outcome reward"',
    "distill": '"knowledge distillation" | "model distillation" | "self-distillation" | ("distillation" + "language models")',
    "peft": '"parameter-efficient fine-tuning" | "low-rank adaptation" | LoRA | "prompt tuning" | "prefix tuning" | adapters',
    "alignment": '"constitutional ai" | RLAIF | "scalable oversight" | ("alignment" + "language models") | "value alignment"',
    "quant": 'quantization | "model compression" | pruning | "low-bit" | "post-training quantization" | sparsity',
    "accel": '"speculative decoding" | "kv cache" | FlashAttention | "efficient inference" | "parallel decoding" | "inference acceleration"',
    "serving": '"llm serving" | "inference serving" | "paged attention" | "batch scheduling" | "serving system" | "inference engine"',
    "tt_compute": '"test-time compute" | "test-time scaling" | "self-consistency" | "best-of-n" | ("tree search" + "language models")',
    "reasoning": '"chain-of-thought" | "chain of thought" | "mathematical reasoning" | "logical reasoning" | ("reasoning" + "language models")',
    "code": '"code generation" | "code language model" | "program synthesis" | "program repair" | "code llm"',
    "multiling": '"multilingual" | "cross-lingual" | "low-resource languages" | ("machine translation" + "large language models")',
    "icl": '"in-context learning" | "prompt engineering" | ("few-shot learning" + "language models") | "prompting"',
    "tool_use": '"tool use" | "tool learning" | "function calling" | ReAct | ("api calls" + "language models")',
    "planning": '("planning" + "llm agents") | "self-reflection" | "self-improvement" | "task decomposition" | Reflexion',
    "memory": '("memory" + "llm agents") | "long-term memory" | "memory-augmented" | ("episodic memory" + agents)',
    "multi_agent": '("multi-agent" + "language models") | "multi-agent collaboration" | "agent debate" | "role-playing agents"',
    "coding_agent": '"software engineering agent" | SWE-bench | "coding agent" | "repository-level" | "issue resolution"',
    "gui_agent": '"web agent" | "gui agent" | "computer use" | "mobile agent" | "web navigation" | "os agent"',
    "agent_eval": '"agent benchmark" | ("benchmark" + "llm agents") | ("interactive environments" + agents) | AgentBench',
    "rag": '"retrieval-augmented" | "retrieval augmented generation" | GraphRAG | "retrieval-enhanced"',
    "retrieval": '"dense retrieval" | "dense passage retrieval" | "text embeddings" | reranking | "neural retrieval" | ColBERT',
    "know_edit": '"knowledge editing" | "model editing" | "editing factual knowledge" | ("knowledge update" + "language models")',
    "hallucination": 'hallucination | "factuality" | "factual consistency" | ("attribution" + "language models") | "fact verification"',
    "vlm": '"vision-language model" | "vision language model" | "multimodal large language model" | CLIP | "visual instruction tuning" | "image-text"',
    "img_gen": '"diffusion model" | "text-to-image" | "generative adversarial" | "image generation" | "image editing" | "score-based"',
    "video_gen": '"video generation" | "text-to-video" | "3d generation" | "world model" | "novel view synthesis" | NeRF',
    "speech": '"speech recognition" | "text-to-speech" | "speech synthesis" | "audio generation" | "spoken language" | "speech representation"',
    "embodied": '"robot learning" | "vision-language-action" | "embodied agent" | "autonomous driving" | "robotic manipulation"',
    "eval_method": '("benchmark" + "language models") | "data contamination" | "evaluation of large language models" | leaderboard',
    "llm_judge": '"llm-as-a-judge" | "llm as a judge" | "model-based evaluation" | ("automatic evaluation" + "language models") | "pairwise comparison"',
    "interp": '"mechanistic interpretability" | "interpretability" | probing | "sparse autoencoder" | "circuit analysis" | "feature attribution"',
    "jailbreak": 'jailbreak | "prompt injection" | "red teaming" | ("adversarial attacks" + "language models") | "adversarial examples"',
    "safety_align": '"ai safety" | "harmlessness" | "safety alignment" | ("refusal" + "language models") | "harmful content"',
    "privacy": '"membership inference" | "training data extraction" | watermarking | ("differential privacy" + "deep learning") | memorization',
    "fairness": '"social bias" | fairness | "gender bias" | ("stereotypes" + "language models") | debiasing',
    "rec_gen": '"generative recommendation" | "generative recommender" | "semantic ids" | "generative retrieval" | ("item tokenization" + recommendation) | "sequential transducers"',
    "rec_llm": '("large language models" + recommendation) | ("llm" + recommender) | "conversational recommendation" | ("agent" + recommendation)',
    "rec_classic": '"recommender systems" | "collaborative filtering" | "click-through rate prediction" | "ctr prediction" | "sequential recommendation" | ("ranking" + "industrial" + recommendation)',
    "rl": '"reinforcement learning" | "policy gradient" | "q-learning" | "offline reinforcement learning" | "multi-agent reinforcement learning"',
    "cv": '"image classification" | "object detection" | "semantic segmentation" | "vision transformer" | "convolutional neural network"',
    "nlp_classic": '"named entity recognition" | "neural machine translation" | BERT | "sequence labeling" | "text classification" | "sentiment analysis"',
    "gnn": '"graph neural network" | "graph neural networks" | "graph representation learning" | "graph convolutional" | "node classification"',
    "optim": '"stochastic optimization" | "adaptive optimizer" | ("optimizer" + "neural networks") | "batch normalization" | "weight initialization" | "loss landscape" | ("generalization" + "deep neural networks")',
}


OUT = db.DATA_DIR / "paper_full.json"


def _load() -> dict:
    return json.loads(OUT.read_text()) if OUT.exists() else {}


def _save(k: str, v) -> None:
    d = _load()
    d[k] = v
    OUT.write_text(json.dumps(d, ensure_ascii=False, indent=1))


def collect(only: list[str] | None = None) -> None:
    t0 = time.time()
    c = col.client()
    done = _load().get("collect_done", [])
    per = _load().get("collect_per", {})
    for code, q in QUERIES.items():
        if (only and code not in only) or (not only and code in done):
            continue
        n, full = 0, []
        for name, year, mc, pages in col.slices():
            got = col.search_bulk(q, c, pages=pages, year=year, min_cites=mc)
            for p in got:
                col.upsert(p, code)
            n += len(got)
            if len(got) >= pages * 1000:
                full.append(name)                         # 取满了：检索式太宽，这一截可能没取全
        per[code] = {"n": n, "full": full}
        if code not in done:
            done.append(code)
        _save("collect_per", per)
        _save("collect_done", done)
        logging.info("%s：%d 条（取满：%s）S2 %s", code, n, full or "-", col.usage)
    col.mark_hot()
    near = col.near_industry()                            # 先取摘要才判得出工业界论文
    col.fetch_details(c, on_page=lambda i, n: logging.info("工业界候选详情 %d/%d", i, n), ids=near)
    logging.info("门槛：%s", col.admit_all())
    col.fetch_details(c, on_page=lambda i, n: logging.info("详情 %d/%d", i, n))
    logging.info("经典回拉 %d 篇", len(col.pull_classics(c)))
    col.fetch_details(c)
    _save("collect", {"seconds": round(time.time() - t0), **col.stats()})
    logging.info("采集完成 %s", col.stats())


def judge() -> None:
    t0 = time.time()
    st = lab.judge_recent()
    st["admit"] = col.admit_all()
    st["seconds"] = round(time.time() - t0)
    _save("judge", st)
    logging.info("Jev %s", st)


def label(step: int = 200, tail: bool = False) -> None:
    """分段标注（每段 step 篇），每段落库；本机登录校验失败或整段 0 篇就停，不换别的模型。
    tail=True 从队尾（被引少的）往前标，给第二个进程用（如 PAPER_LLM_ENGINE=deepseek），两头在中间汇合。"""
    t0, total, cost, tried = time.time(), 0, 0.0, set()
    while rows := [x for x in lab.todo()[::-1 if tail else 1] if x[0]["s2id"] not in tried][:step]:   # 两次都没标上的不再反复问
        tried |= {x[0]["s2id"] for x in rows}
        st = lab.run(items=rows)
        total, cost = total + st["labeled"], round(cost + st["cost"], 4)
        logging.info("标注 +%d（累计 %d，等价 $%.2f）%s", st["labeled"], total, cost, st["errors"][-2:] or "")
        _save("label_tail" if tail else "label", {"labeled": total, "cost": cost, "seconds": round(time.time() - t0), "engine": lab.engine(),
                        "errors": st["errors"][-5:]})
        if not st["labeled"] or any("没有走本机登录" in e for e in st["errors"]):
            logging.error("标注停止：%s", st["errors"][-3:])
            sys.exit(1)


REC = re.compile(r"recommend|click-through|\bctr\b|collaborative filtering", re.I)


def relabel_rec() -> None:
    """分类体系加了「推荐系统」后，把以前标在别的方向（多是 other）的推荐论文重标一遍。"""
    corpus = lab._corpus()
    rows = [r for r in db.rows("SELECT p.* FROM paper_items p JOIN paper_labels l ON l.s2id=p.s2id "
                               "WHERE p.status='in' AND l.d NOT LIKE 'rec_%'") if REC.search(f"{r['title']} {r['abstract']}")]
    st = lab.run(items=[(r, lab.refs_of(r, corpus)) for r in rows])
    _save("relabel_rec", {"todo": len(rows), "labeled": st["labeled"], "errors": st["errors"][-5:]})
    logging.info("推荐论文重标 %d/%d %s", st["labeled"], len(rows), st["errors"][-2:] or "")


STEPS = {"collect": collect, "judge": judge, "label": label, "label_tail": lambda: label(tail=True),
         "relabel_rec": relabel_rec}


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    db.init([col.SCHEMA])
    args = sys.argv[1:]
    if args[0] == "collect":
        collect([a for a in args[1:] if a != "all"] or (list(QUERIES) if "all" in args else None))
    else:
        for step in (list(STEPS) if args[0] == "all" else args):
            STEPS[step]()


if __name__ == "__main__":
    main()
