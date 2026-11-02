"""打包批量标注试跑：python label.py taxonomy.json sample.json out_dir start count batch"""
import os, json, subprocess, sys, time, random, concurrent.futures as cf
tax_p, sample_p, out_dir, start, count, batch = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4]), int(sys.argv[5]), int(sys.argv[6])
tax = json.load(open(tax_p))
repos = [x for p in sample_p.split(",") for x in json.load(open(p))]
if os.environ.get("SHUFFLE", "1") == "1": random.Random(7).shuffle(repos)
repos = repos[start:start + count]

def tax_text():
    lines = ["形态 kind（单选）：" + "；".join(f"{k['code']}={k['name']}（{k['desc']}）" for k in tax["kinds"])]
    lines.append("AI 关系 ai（单选）：" + "；".join(f"{a['code']}={a['name']}" + (f"（{a['desc']}）" if a['desc'] else "") for a in tax["ai_relation"]))
    lines.append("领域 domain（填二级 code）：")
    for d in tax["domains"]:
        lines.append(f"[{d['name']}] " + "；".join(f"{c['code']}={c['name']}（{'/'.join(c['eg'])}）" for c in d["children"]))
    return "\n".join(lines)

SYSTEM = """你在给 GitHub 仓库做分类，供开发者按功能搜索开源项目（如「我想做 PDF 解析」）。分类体系：
{tax}

对下面每个仓库输出一行 JSON（JSON Lines，不要代码块、不要解释），字段：
{{"i":序号,"k":kind,"d":主领域二级code,"d2":[副领域code，0-2个],"ai":ai关系,"t":[功能标签3-8个，中文为主、专有名词保留英文，写「能用它做什么」，优先用分类体系里 eg 的词],"s":"中文一句话说它能做什么（≤40字）"}}
规则：教程/书/awesome 也按它讲的主题归 domain（如 LLM 教程 → d=llm, k=tutorial）；看不出用途 d=other。
"""

def row(n, r):
    return json.dumps({"i": n, "name": r["name"], "stars": r["stars"], "lang": r.get("lang"), "topics": (r.get("topics") or [])[:12], "desc": (r.get("desc") or "")[:300]}, ensure_ascii=False)

T = tax_text()
SYS = SYSTEM.format(tax=T)
def run(bi):
    chunk = repos[bi:bi + batch]
    prompt = "仓库：\n" + "\n".join(row(n, r) for n, r in enumerate(chunk))
    t0 = time.time()
    p = subprocess.run(["reclaude", "-p", prompt, "--model", "claude-haiku-5-5", "--output-format", "json", *(["--effort", os.environ["EFFORT"]] if os.environ.get("EFFORT") else []), "--tools", "", "--system-prompt", SYS], capture_output=True, text=True, timeout=600)
    dt = time.time() - t0
    try:
        res = json.loads(p.stdout)
    except Exception:
        return {"bi": bi, "err": (p.stdout + p.stderr)[-500:], "dt": dt}
    out = []
    for line in (res.get("result") or "").splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                x = json.loads(line); x["name"] = chunk[x["i"]]["name"]; out.append(x)
            except Exception:
                pass
    return {"bi": bi, "n": len(chunk), "got": len(out), "dt": round(dt, 1), "usage": res.get("usage"), "cost": res.get("total_cost_usd"), "prompt_chars": len(prompt), "labels": out}

with cf.ThreadPoolExecutor(4) as ex:
    results = list(ex.map(run, range(0, len(repos), batch)))
json.dump(results, open(f"{out_dir}/labels_{start}_{batch}.json", "w"), ensure_ascii=False, indent=1)
for r in results:
    print({k: v for k, v in r.items() if k != "labels"})
