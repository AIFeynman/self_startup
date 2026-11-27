# 10 长任务连续性：恢复、交接、干净收尾
<!-- minutes: 35 -->
<!-- know: 会话恢复, 交接文件, SessionStart hook, 长任务 -->

长任务一定会中断：进程被杀、机器重启、上下文满了要换新会话、明天接着干。连续性有两条路：
- **恢复同一个会话**：dsh 把每个事件持久化到会话日志，`resume_session` 从日志重建状态接着跑；
- **新会话 + 交接文件**：上一个会话收工时把进度、决策、下一步写进文件，下一个会话开工先读。前者保留了全部细节（包括错误的思路），后者只留下被整理过的结论。

dsh 内置了前者；后者要我们自己搭——用 SessionStart 钩子在开工时注入进度文件，用 Stop 钩子在收工前检查交接写了没有。这是 learn-harness-engineering 项目 03 的做法，这里在 dsh 上复现。

## 跑到一半强制关掉，再恢复
在第 3 步结束时直接关掉运行时（模拟进程被杀），然后用同一个 DSH_HOME 起一个新运行时，`resume_session` 接着跑。

```python
import harness_lab as lab, json, time
import threading, time
task = lab.BY_ID["cli-freq"]
ws = lab.workspace(task, "resume")
sid = f"resume{int(time.time())}"
h = ss.harness(ws)
def kill_at_3(e, run, h):
    if e["type"] == "step/end" and e["data"].get("step") == 3:
        threading.Thread(target=h.close, daemon=True).start()
try:
    r1 = ss.agent(task.prompt, h=h, session=sid, on_event=kill_at_3, title="跑到第 3 步被杀")
except Exception as e:
    ss.note(f"运行时被关掉：{type(e).__name__}", "warn")
h2 = ss.harness(ws)
r2 = ss.agent("刚才被中断了，接着把任务做完。", h=h2, session=sid, resume=True, title="恢复后继续")
h2.close()
ok, why = lab.grade(task, ws)
ss.kv({"恢复后判分": why, "恢复后模型调用": len(r2.usage), "恢复后第一步输入 token": r2.usage[0]["inputTokens"] + r2.usage[0]["cacheReadTokens"] if r2.usage else 0}, "resume")
```

> 思考：恢复后第一步的输入里包含了被杀前的全部历史（所以 token 不少），但缓存还在不在？如果中断发生在一个工具执行到一半时，恢复后这个工具调用算什么状态？

## 交接文件：开工先读，收工必写
SessionStart 钩子把 `PROGRESS.md` 的内容作为上下文注入新会话；Stop 钩子要求收工前更新 `PROGRESS.md`（做了什么、还剩什么、下一步）。两个**互不相通的新会话**接力完成一道题，比较有无交接时第二个会话的表现。

```python
start = lab.script("handoff_start", r'''
import json, os
text = open("PROGRESS.md", encoding="utf-8").read() if os.path.exists("PROGRESS.md") else "（没有进度文件，这是第一次开工）"
print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "上一个会话留下的进度：\n" + text}}, ensure_ascii=False))
''')
stop = lab.script("handoff_stop", r'''
import json, os, sys, time
e = json.load(sys.stdin)
fresh = os.path.exists("PROGRESS.md") and time.time() - os.path.getmtime("PROGRESS.md") < 600
if not fresh and not e.get("stop_hook_active"):
    print(json.dumps({"decision": "block", "reason": "收工前更新 PROGRESS.md：做了什么、还剩什么、下一步具体做什么。"}, ensure_ascii=False))
''')
HANDOFF = lab.hooks("handoff", {"SessionStart": [{"hooks": [{"type": "command", "command": start}]}], "Stop": [{"hooks": [{"type": "command", "command": stop}]}]})
part1 = "第一阶段：只在 textkit/core.py 里加一个 top_words(text, k) 函数（返回出现最多的 k 个 (词, 次数)），先不要动命令行。"
part2 = "继续上一次的工作，把整个任务做完：" + task.prompt
rows = []
for name, patches in (("无交接", []), ("交接文件 + 钩子", [HANDOFF])):
    ws = lab.workspace(task, "handoff-" + name)
    a = ss.agent(part1, ws, patches=patches, title=name + " · 会话 1", show=False)
    b = ss.agent(part2, ws, patches=patches, title=name + " · 会话 2")
    ok, why = lab.grade(task, ws)
    rows.append([name, "✓" if ok else "✗", why, len(b.usage), f"{a.cost + b.cost:.4f}", (ws / "PROGRESS.md").exists(), "top_words" in (ws / "textkit/cli.py").read_text()])
ss.table(rows, ["方式", "通过", "判分", "会话 2 调用", "两段总花费", "有 PROGRESS.md", "会话 2 复用了 top_words"], "两个新会话接力")
```

## 对照与坑
- 源码：`packages/session/session-persistence`（日志即状态）、`packages/core/session`。
- 对照：learn-claude-code s10–s12；learn-harness-engineering 第 5、6、12 讲与项目 03（初始化阶段 + 进度文件 + 干净收尾）；Anthropic《Effective harnesses for long-running agents》里的 initializer agent + progress file。
- 坑：同一个会话同一时间只能被一个运行时持有（`session.lock`）；被杀的运行时如果没退干净，resume 会报「被占用」。
- 坑：SessionStart 钩子是「脱离运行」的，不阻塞会话启动；注入的上下文在首个轮次前加入，钩子太慢时可能赶不上。
