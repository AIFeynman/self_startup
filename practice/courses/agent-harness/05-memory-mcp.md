# 5 长期记忆：dsh 没有，自己接一个
<!-- minutes: 40 -->
<!-- know: Agent 记忆, MCP, stdio 传输, 记忆污染 -->

会话一结束，这次踩过的坑就没了。dsh 本身不带长期记忆，它的做法是：通过 `mcp-client` 接任意 MCP 记忆服务（官方指南 `docs/user/guide/mcp-memory.zh.md` 给了 Memorix、MCP Reference Memory、Engram 三份参考配置）。这一课我们不装第三方，**用 Python 手写一个最小的记忆服务**，接进 dsh，然后回答三个问题：记忆能不能让第二次做得更好？错的记忆会不会被盲信？记忆放 MCP 按需查，和直接写进 AGENTS.md，哪个划算？

> 先补背景：**MCP**（Model Context Protocol）是给 agent 接外部工具的通用协议。stdio 传输下，harness 启动一个子进程，双方每行一条 JSON-RPC 消息：`initialize` 握手、`tools/list` 列工具、`tools/call` 调用。dsh 把服务的工具以 `mcp__<服务名>__<工具名>` 暴露给模型。

## 写一个 40 行的记忆服务
三个工具：`remember` 写一条、`recall` 按关键词查、`forget` 标记一条作废。数据存在一个 JSON 文件里。

```python
import harness_lab as lab, json, time
MEM_DB = ss.DSH / "memory.json"
MEM_DB.unlink(missing_ok=True)
server = lab.script("memory_mcp", r'''
import json, sys, time
from pathlib import Path
DB = Path(sys.argv[1])
TOOLS = [
  {"name": "remember", "description": "记下一条以后会用到的经验（踩过的坑、项目约定）。一条只写一件事。",
   "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}},
  {"name": "recall", "description": "按关键词检索以前记下的经验。开始任务前先查。",
   "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
  {"name": "forget", "description": "把一条已证明是错的经验作废，参数是编号。",
   "inputSchema": {"type": "object", "properties": {"id": {"type": "integer"}}, "required": ["id"]}},
]
def load(): return json.loads(DB.read_text()) if DB.exists() else []
def call(name, a):
    items = load()
    if name == "remember":
        items.append({"id": len(items) + 1, "text": a["text"], "t": time.time(), "dead": False}); DB.write_text(json.dumps(items, ensure_ascii=False)); return f"已记下 #{len(items)}"
    if name == "forget":
        for m in items:
            if m["id"] == a["id"]: m["dead"] = True
        DB.write_text(json.dumps(items, ensure_ascii=False)); return f"已作废 #{a['id']}"
    live = [m for m in items if not m["dead"]]
    words = a.get("query", "").lower().split()
    hits = [m for m in live if any(w in m["text"].lower() for w in words)] or live[-5:]
    return "\n".join(f"#{m['id']} {m['text']}" for m in hits) or "（没有记忆）"
for line in sys.stdin:
    msg = json.loads(line); mid, m = msg.get("id"), msg.get("method")
    if mid is None: continue
    if m == "initialize": res = {"protocolVersion": msg["params"].get("protocolVersion", "2025-06-18"), "capabilities": {"tools": {}}, "serverInfo": {"name": "memory", "version": "0.1"}}
    elif m == "tools/list": res = {"tools": TOOLS}
    elif m == "tools/call": res = {"content": [{"type": "text", "text": call(msg["params"]["name"], msg["params"].get("arguments") or {})}]}
    else:
        print(json.dumps({"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": m}}), flush=True); continue
    print(json.dumps({"jsonrpc": "2.0", "id": mid, "result": res}, ensure_ascii=False), flush=True)
''')
py, path = server.split(" ", 1)
MEM = lab.mcp("memory", py, [path, MEM_DB])
print(MEM.read_text())
```

先不用 agent，自己当客户端跟它握手，确认协议对。

```python
import subprocess, json
p = subprocess.run([py, path, str(MEM_DB)], input="\n".join(json.dumps(m) for m in [
    {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
    {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "recall", "arguments": {"query": "测试"}}}]) + "\n", capture_output=True, text=True)
ss.table([[json.loads(l)["id"], l[:160]] for l in p.stdout.splitlines()], ["id", "回复"], "手动走一遍 MCP")
MEM_DB.unlink(missing_ok=True)
```

## 第一次踩坑 → 记下 → 第二次同类任务
AGENTS.md 里只写记忆的用法（开工先 recall，收工把新经验 remember），不写项目约定本身。第一轮做 `chunks-tail`，看它记下什么；第二轮换一道新题 `cli-upper`，和「没有记忆」的对照组比。

```python
USE_MEM = {"AGENTS.md": "# 给 agent 的说明\n- 开工前先用 recall 查和任务相关的经验。\n- 收工前把这次学到的、以后同项目还会用到的经验用 remember 记下来，一条一件事。\n"}
first = lab.run("chunks-tail", tag="mem1", extra=USE_MEM, patches=[MEM], show=True)
ss.table([[m["id"], m["text"]] for m in json.loads(MEM_DB.read_text())] if MEM_DB.exists() else [], ["#", "记下的经验"], "第一轮之后的记忆")
rows = [["第一轮 chunks-tail（有记忆服务）", first["ok"], first["why"], first["steps"], first["cost"]]]
for name, patches in (("第二轮 cli-upper · 有记忆", [MEM]), ("第二轮 cli-upper · 无记忆", [])):
    x = lab.run("cli-upper", tag="mem2" + str(len(patches)), extra=USE_MEM if patches else None, patches=patches)
    rows.append([name, x["ok"], x["why"], x["steps"], x["cost"]])
ss.table(rows, ["运行", "通过", "判分", "模型调用", "元"], "记忆有没有帮上忙")
```

## 一条错的记忆
手动塞两条错经验：「测试用 pytest -x 跑」「这个项目不需要写 CHANGELOG」。看它会不会照做，以及会不会在发现矛盾后用 `forget` 作废。

```python
MEM_DB.write_text(json.dumps([{"id": 1, "text": "本项目测试用 pytest -x 跑", "t": 0, "dead": False},
                              {"id": 2, "text": "这个项目不需要写 CHANGELOG，写了会被拒", "t": 0, "dead": False}], ensure_ascii=False))
x = lab.run("count-words", tag="badmem", extra=USE_MEM, patches=[MEM], show=True)
ss.kv({"判分": x["why"], "调用过 forget": "mcp__memory__forget" in x["run"].tools, "记忆现状": [(m["id"], m["dead"]) for m in json.loads(MEM_DB.read_text())]}, "错记忆的下场")
```

> 思考：模型读了 CONTRIBUTING.md 吗？如果读了，它信文件还是信记忆？平台的《Know-how 地图》F3–F4 讨论过「记忆谁来写、冲突怎么消解、怎么遗忘」，一线反馈是自动写入的记忆采用率只有一成左右。你会给记忆加什么字段（来源、证据、过期时间）来减少盲信？

## 放 MCP 还是写进 AGENTS.md
记忆放 MCP：只有调 recall 时才进上下文，但每次查要多一来一回。写进 AGENTS.md：每一步都带着，但不用查。用上面的数字算一笔账。

```python
mem_text = "\n".join(m["text"] for m in json.loads(MEM_DB.read_text()))
per_step = len(mem_text) / 2
ss.kv({"记忆总长（字符）": len(mem_text), "写进 AGENTS.md 每步多带（粗估 token）": round(per_step),
       "一道题约多少步": x["steps"], "按缓存命中价算的额外花费（元/题）": round(per_step * x["steps"] * 0.014 / 1e6 * 7.2, 6)}, "两种放法的成本")
```

## 对照与坑
- 对照：learn-claude-code s09（筛选 → 提取 → 整理）；[ACE](https://arxiv.org/abs/2510.04618)（把上下文当作可演化的 playbook，第 14 课会用到）；官方 `docs/user/guide/mcp-memory.zh.md`。
- 坑：dsh 的 stdio 桥在启动子进程前会**剥掉所有 `DSH_*` 和名字像凭据的环境变量**，记忆服务要的路径和密钥用命令行参数或 `config.env` 显式传。
- 坑：MCP 服务的 stdout 只能输出协议消息，调试信息打到 stderr，否则会把握手弄坏。
