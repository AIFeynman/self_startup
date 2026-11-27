# 13 信号与归因：从失败轨迹找到 harness 的毛病
<!-- minutes: 40 -->
<!-- know: 失败归因, 轨迹诊断, LLM 评审, 诊断准确率 -->

第 12 课得到了一批失败。下一步不是马上改，而是回答：**每个失败是 harness 的毛病，还是模型能力的问题？是哪一层的毛病？** 改错了层，要么没用，要么按下葫芦浮起瓢。

做法：让一个**独立的诊断者**逐条读失败轨迹、按症状分桶。诊断者不能是被评的那个 agent 自己（谁干活谁不裁决），这里用本机 Claude（`ss.llm`，走平台的本机 Claude，不花 DeepSeek 的钱）。然后人工抽查，算诊断准确率——诊断者本身也要被量。

## 取出失败
```python
import harness_lab as lab, json, time
assert "base_rows" in globals(), "这一课用到前面的结果：先按顺序跑第 12 课的「基线跑 3 遍」"
fails = [r for r in base_rows if not r["ok"]]
ss.table([[r["task"], r["rep"], r["why"], r["steps"]] for r in fails], ["题", "第几遍", "判分", "模型调用"], f"基线的 {len(fails)} 次失败")
print(lab.brief(fails[0])[:2500] if fails else "基线全过了：把第 12 课换成 sdk-minimal 或去掉某个工具再跑一次，制造一些失败。")
```

## 诊断者：按症状分桶
分桶表沿用一线常见的失败类型；每条要给证据（轨迹里的哪一步）和该改的层。

```python
BUCKETS = ["没读到项目约定", "工具误用或环境不对", "上下文丢了约束", "过早宣布完成", "权限或沙箱卡住", "改错了地方或范围不对", "模型能力不足"]
LAYERS = ["AGENTS.md 规则", "skill", "记忆", "工具说明或配置", "钩子（确定性检查）", "编排（计划/目标/子 agent）", "不改 harness（模型问题）"]
def diagnose(row):
    prompt = (f"你在给一个 coding agent 的失败做归因。症状分桶只能从这些里选：{BUCKETS}；建议改的层只能从这些里选：{LAYERS}。\n"
              "项目约定写在工作区的 CONTRIBUTING.md 里（agent 需要自己去读）。\n"
              "只输出一个 JSON：{\"bucket\": ..., \"harness_problem\": true/false, \"evidence\": \"轨迹里的哪一步说明了什么\", \"layer\": ..., \"fix\": \"一句话改法\"}\n\n轨迹：\n" + lab.brief(row))
    return lab.parse_json(ss.llm(prompt))
diags = []
for r in fails[:8]:
    try:
        d = diagnose(r)
    except Exception as e:
        d = {"bucket": "诊断失败", "harness_problem": None, "evidence": str(e)[:80], "layer": "", "fix": ""}
    diags.append((r, d))
ss.table([[r["task"], d.get("bucket"), d.get("harness_problem"), d.get("layer"), d.get("evidence", "")[:120], d.get("fix", "")[:80]] for r, d in diags],
         ["题", "症状", "harness 问题", "该改的层", "证据", "改法"], "诊断结果")
from collections import Counter
ss.bars(dict(Counter(d.get("bucket") for _, d in diags)), "失败按症状分桶")
```

## 人工抽查：诊断准确率
自己读前几条轨迹（上面 `lab.brief` 打印的格式），在下面填你的判断，算和诊断者一致的比例。不填就默认你同意诊断者——那这个数就没有意义，所以至少改一条你认真看过的。

```python
mine = {i: d.get("bucket") for i, (_, d) in enumerate(diags[:5])}   # 改成你的判断，例如 mine[0] = "过早宣布完成"
agree = sum(mine[i] == diags[i][1].get("bucket") for i in mine)
ss.kv({"抽查条数": len(mine), "一致": agree, "诊断准确率（相对你）": f"{agree / max(1, len(mine)):.0%}"}, "诊断者被量了一次")
```

> 思考：如果大多数失败都落在「没读到项目约定」，这其实是一个很便宜就能修的 harness 问题（约定没进上下文）。如果落在「模型能力不足」，改 harness 的收益就有限，该考虑换模型或拆任务。你的分桶结果更像哪种？

## 对照与坑
- 对照：[HarnessFix](https://arxiv.org/abs/2606.06324)（2026）：先基于轨迹诊断出 harness 的缺陷类型再定向修，比初始 harness 提升 6.3%–18.4%（论文自报）；[AHE](https://arxiv.org/abs/2604.25850)（2026）：把「组件、经验、决策」三类可观测性做成支柱，让每次改动都对应一个可被证伪的约定。
- 坑：诊断者读的是压缩过的轨迹（`lab.brief` 截断了长输出），它看不到的东西就诊断不出来；证据字段让你能回头核对。
- 坑：别让诊断者看判分规则的全部细节再去诊断——它会倾向于把一切归到判分关心的那几条上。
