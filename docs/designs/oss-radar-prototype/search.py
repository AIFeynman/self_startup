"""检索原型：labels + 原始元数据建 FTS5(trigram)，对比 baseline（原始描述 + 原文查询）和 意图检索（改写 + 标签 + 领域 + 重排）"""
import re, json, math, sqlite3, sys, random
S = sys.argv[1]
meta = {x["name"]: x for p in ("sample.json", "pdfset.json") for x in json.load(open(f"{S}/{p}"))}
labels = {}
for p in ("r3/labels_0_50.json", "r4/labels_0_50.json"):
    for r in json.load(open(f"{S}/{p}")):
        for x in r["labels"]: labels[x["name"]] = x
db = sqlite3.connect(":memory:")
db.execute("CREATE VIRTUAL TABLE f USING fts5(name, summary, tags, descr, topics, tokenize='trigram')")
docs = []
for n, l in labels.items():
    m = meta[n]
    docs.append((n, l, m))
    db.execute("INSERT INTO f(rowid,name,summary,tags,descr,topics) VALUES (?,?,?,?,?,?)",
               (len(docs) - 1, n.replace("/", " "), l["s"], " | ".join(l["t"]), m.get("desc") or "", " ".join(m.get("topics") or [])))
W = (0.5, 1.0, 1.2, 0.8, 0.8)  # name summary tags descr topics

def hits(term, cols=None):
    t = term.lower().strip()
    if len(t) >= 3:
        q = '"' + t.replace('"', '') + '"'
        if cols: q = "{" + " ".join(cols) + "}: " + q
        try:
            return {r[0]: -r[1] for r in db.execute(f"SELECT rowid, bm25(f,{','.join(map(str,W))}) FROM f WHERE f MATCH ?", [q])}
        except sqlite3.OperationalError:
            return {}
    like = f"%{t}%"   # 2 字中文词：trigram 不支持，退回 LIKE
    cs = cols or ["name", "summary", "tags", "descr", "topics"]
    return {r[0]: 1.0 for r in db.execute(f"SELECT rowid FROM f WHERE " + " OR ".join(f"lower({c}) LIKE ?" for c in cs), [like] * len(cs))}

def baseline(q, k=10):
    # 模拟 GitHub 关键词搜索：原文按空格切词，全部命中 name/descr/topics
    terms = [t for t in q.split() if t]
    sets = [set(hits(t, ["name", "descr", "topics"])) for t in terms]
    ids = set.intersection(*sets) if sets else set()
    return sorted(ids, key=lambda i: -docs[i][2]["stars"])[:k]

def intent_search(it, k=10, by="rel"):
    must = [hits(t) for t in it["must"]]; should = [hits(t) for t in it["should"]]; neg = [hits(t, ["summary", "tags"]) for t in it.get("not", [])]
    # 原子词召回：改写给的长短语拆成词，命中不同原子词越多越相关（补短语字面不匹配）
    atoms = sorted({a for t in it["must"] + it["should"] for a in re.split(r"[\s/，,]+", t.lower()) if len(a) >= 2})
    ah = [hits(a, ["name", "summary", "tags", "topics"]) for a in atoms]
    acnt = {}
    for h in ah:
        for i in h: acnt[i] = acnt.get(i, 0) + 1
    cand = set().union(*must, *should) | {i for i, (_, l, _) in enumerate(docs) if l["d"] in it["domains"]} | {i for i, c in acnt.items() if c >= 2}
    out = []
    for i in cand:
        l = docs[i][1]
        m = max((h.get(i, 0) for h in must), default=0); s = sum(1 for h in should if i in h)
        rel = (1.0 if m else 0) + 0.15 * min(m, 3) + 0.3 * min(s, 3) / 3 + 0.15 * min(acnt.get(i, 0), 5)
        rel += 0.5 if l["d"] in it["domains"] else (0.25 if set(l.get("d2") or []) & set(it["domains"]) else 0)
        if it.get("kinds"): rel += 0.4 if l["k"] in it["kinds"] else -0.3
        if any(i in h for h in neg) and not m: rel -= 0.8
        out.append((i, rel))
    if by == "stars":
        out = [x for x in out if x[1] >= 1.0]; out.sort(key=lambda x: -docs[x[0]][2]["stars"])
    else:
        out.sort(key=lambda x: -(x[1] + 0.12 * math.log10(max(docs[x[0]][2]["stars"], 1))))
    return [(i, round(r, 2)) for i, r in out[:k]]

qs = json.load(open(f"{S}/queries.json")); its = {x["i"]: x for x in json.load(open(f"{S}/intents.json"))}
for qi, q in enumerate(qs):
    print(f"\n### {q}")
    print("  baseline:", [docs[i][0] for i in baseline(q)][:6] or "（空）")
    for i, r in intent_search(its[qi], 8):
        print(f"  {r:5} {docs[i][2]['stars']:>7} {docs[i][0][:34]:34} {docs[i][1]['d']:12} {docs[i][1]['s'][:34]}")
    print("  按 star:", [docs[i][0].split('/')[1] for i, _ in intent_search(its[qi], 6, 'stars')])

# ---- LLM 重排：候选前 40 交给模型按「能否满足需求」打 0-3 分
import subprocess, time, concurrent.futures as cf
RS = ("你是开源项目检索的重排器。给定用户需求和候选仓库（summary/tags），判断每个仓库能否直接满足需求："
      "3=正是要找的，2=能用来做（主要功能之一），1=沾边但不是主要用途，0=无关或是要排除的相反功能。"
      '只输出一行 JSON：{"<序号>":分数,...}，覆盖全部候选。')
def rerank(q, cands):
    rows = "\n".join(json.dumps({"i": n, "name": docs[i][0], "summary": docs[i][1]["s"], "tags": docs[i][1]["t"]}, ensure_ascii=False) for n, (i, _) in enumerate(cands))
    t0 = time.time()
    p = subprocess.run(["reclaude", "-p", f"需求：{q}\n候选：\n{rows}", "--model", "claude-haiku-5-5", "--output-format", "json", "--tools", "", "--effort", "low", "--system-prompt", RS], capture_output=True, text=True, timeout=300)
    res = json.loads(p.stdout); txt = res["result"]; sc = json.loads(txt[txt.find("{"):txt.rfind("}") + 1])
    return {cands[int(k)][0]: v for k, v in sc.items()}, round(time.time() - t0, 1), res.get("total_cost_usd")

if len(sys.argv) > 2:
    _print = print
    pre = {int(x): intent_search(its[int(x)], 40) for x in sys.argv[2].split(",")}
    def one(qi):
        q = qs[qi]; cands = pre[qi]
        sc, dt, cost = rerank(q, cands)
        final = sorted(cands, key=lambda x: -(sc.get(x[0], 0) + 0.3 * x[1] + 0.12 * math.log10(max(docs[x[0]][2]["stars"], 1))))
        return q, dt, cost, [(docs[i][0], sc.get(i)) for i, _ in final[:8]], [docs[i][0].split("/")[1] for i in sorted([i for i, _ in cands if sc.get(i, 0) >= 2], key=lambda i: -docs[i][2]["stars"])[:8]]
    with cf.ThreadPoolExecutor(8) as ex:
        for q, dt, cost, top, bystar in ex.map(one, [int(x) for x in sys.argv[2].split(",")]):
            print(f"\n### {q}  （重排 {dt}s, ${cost:.4f}）"); [print("  ", s, n) for n, s in top]; print("  按 star（分≥2）:", bystar)
