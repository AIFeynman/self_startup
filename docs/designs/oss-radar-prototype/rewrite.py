"""一次调用把一批用户查询改写成检索意图（原型；线上每条查询单独改写并缓存）"""
import json, subprocess, sys
tax = json.load(open(sys.argv[1]))
qs = json.load(open(sys.argv[2]))
doms = "；".join(f"{c['code']}={c['name']}" for d in tax["domains"] for c in d["children"])
SYS = f"""你把开发者的找开源项目需求改写成检索意图。领域 code：{doms}
形态 kind：app library framework plugin model dataset research tutorial book awesome template。
对每条查询输出一行 JSON：{{"i":序号,"must":[核心功能词，中英文各写几种说法，如 "PDF 解析","PDF parsing","PDF 文本提取","pdf extraction"],"should":[相关但非必须的词，如 "OCR","表格抽取","版面分析"],"not":[容易混淆但不是用户要的功能，如 "PDF 生成","PDF 阅读器"],"domains":[最可能的 1-3 个领域 code],"kinds":[用户明确要某种形态才填，如要教程填 tutorial，否则空]}}
只输出 JSON Lines。"""
prompt = "\n".join(f'{i}: {q}' for i, q in enumerate(qs))
p = subprocess.run(["reclaude", "-p", prompt, "--model", "claude-haiku-5-5", "--output-format", "json", "--tools", "", "--system-prompt", SYS], capture_output=True, text=True, timeout=300)
res = json.loads(p.stdout)
out = [json.loads(l) for l in res["result"].splitlines() if l.strip().startswith("{")]
json.dump(out, open(sys.argv[3], "w"), ensure_ascii=False, indent=1)
print(res.get("usage", {}).get("output_tokens"), res.get("total_cost_usd"), res.get("duration_ms"))
for x in out: print(qs[x["i"]], "→", x)
