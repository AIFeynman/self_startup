"""GitHub 项目的 Deep Dive：在深读页按需生成，要讲到「工程设计长文」的程度——读完能讲清这个系统为什么这样设计。

一个 Agent 一口气读代码、做实验、写文章，结果像读代码笔记：没有动机链、术语不定义、实验按清单凑数、只有一张图。
所以拆成四个阶段，各是一个后台任务，按顺序串起来；每个阶段有自己的产物和平台校验，失败就停在这个阶段，可以从这里重试：
    understand  理解：读仓库 + 找作者的设计文章 / 论文 / 博客，产出 understanding.md（动机链、术语表、设计决定、可检验主张）
    experiment  实验：针对主张做「选中方案 vs 朴素替代」的系统级对照 / 消融 / 参数扫描，多次运行，结果画成图，写 results.md
    write       写作：面向读者的叙事长文 deepdive.md，每个机制一张示意图，术语首次出现时定义
    review      审稿：独立按评分表逐条审，写 review.json，然后直接改稿（改前的稿留作 deepdive.draft.md）

产物（<条目目录>/deepdive/）：
    understanding.md / results.md / deepdive.md / review.json
    sources/                 作者设计文章等外部资料的摘录
    figs/                    概念图、对比图（手写 SVG）和实验数据图（figs/exp-*.svg，由数据脚本生成）
    lab/repo/                单独克隆的仓库（实验完删掉依赖目录）
    lab/E<n>-<slug>/         每个实验的脚本、原样输出 out.txt、数据 data.json
    lab/experiments.json     实验清单（平台据此校验确实跑过）
重新生成时上一版整体挪到 history/<时间>/，正文另存 deepdive.<时间>.md（图片链接改指 history 下），不覆盖。
"""
from __future__ import annotations

import json
import re
import shutil
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

STAGES = ["understand", "experiment", "write", "review"]
STAGE_NAMES = {"understand": "理解", "experiment": "实验", "write": "写作", "review": "审稿返修"}

MIN_EXPERIMENTS = 3      # 有原样输出的实验
MIN_COMPARE = 2          # 其中「对照 / 消融 / 扫描」类（检验设计主张）至少这么多
COMPARE_KINDS = ("对照", "消融", "扫描")
MIN_DECISIONS = 3        # understanding.md 里的设计决定
MIN_CLAIMS = 2           # 可检验主张
MIN_CHARS = 10000        # 正文字数下限（不计空白）
MIN_FIGS = 6             # 正文里嵌入且真实存在的图
MAX_BULLET_RATIO = 0.4   # 列表行占非空行的比例上限：要叙事，不要要点堆砌
RUBRIC = {
    "R1": "动机链：先用场景 / 痛点引出问题，讲清朴素做法为什么不行，再推出设计目标",
    "R2": "推导：每个核心设计都从一个矛盾（trade-off）讲起，说清两种朴素做法各自怎么失败、选了什么、代价和适用边界",
    "R3": "术语：每个项目自有术语首次出现时都有定义（必要时配例子），读者不需要回头查代码",
    "R4": "图：总架构图 + 每个核心机制一张示意图（最好用一条具体样例走一遍）+ 实验数据图；每张图正文都有解释",
    "R5": "实验打到主张：实验检验的是设计主张而不是实现细节，有对照方案、指标、多次运行",
    "R6": "解读：解释数字背后的原因和代价，和前文机制交叉引用，诚实写推翻 / 意外",
    "R7": "可读性：叙事散文为主，层层递进；代码片段少而精；类比经典系统设计帮助理解",
    "R8": "准确性：抽查至少 5 处说法与代码（文件:行号）和 out.txt 一致，没有编造",
    "R9": "开放问题：在设计层面（扩展性、交互、安全、成本），而不是缺陷清单",
    "R10": "覆盖原始设计：找到作者设计文章 / 论文时，它的核心设计都讲到并对照了实现",
}
# 时间预算（分钟）：实验求轻，模拟核心能力即可，不跑重型全量流程
BUDGET = {"cmd": 3, "install": 5, "exp": 5, "total": 20}
TIMEOUT_HINT = f"perl -e 'alarm shift; exec @ARGV' {BUDGET['cmd'] * 60}"   # macOS 没有 timeout 命令

HEAD = """Deep Dive「{stage_name}」阶段（共四个阶段：理解 → 实验 → 写作 → 审稿返修，每个阶段一个独立任务，靠文件交接）。
对象：{url}
{focus}
最终目标：一篇让「会编程但没看过这个项目」的读者读完能讲清**这个系统为什么这样设计**的工程长文——
像优秀的系统设计文章那样：从真实痛点出发，每个设计从一个矛盾推出来，有清晰的图，用对照实验检验设计主张。
不是读代码笔记，不是要点清单。

工作目录：{dd}（只写这里面的文件；不修改 {dd} 以外的任何文件，不读 ~/.ssh、钥匙串、环境变量里的密钥）。
"""

UNDERSTAND = """## 本阶段：理解（不写正文，只建立理解模型）
已有深读产物（先读，可以借用其中的事实，但它们一般讲得浅）：
{base}

1. 仓库：`git clone --depth 1 {url} {dd}/lab/repo`（已存在就 `git -C {dd}/lab/repo pull --ff-only`），记下 `git rev-parse HEAD`。
   读 README / docs / 设计文档 / 入口 / 核心模块 / 测试，用 `rg` 找关键数据结构、状态机、配置项，记下 `文件:行号`。
2. **找原始设计材料（必做，这一步决定深度）**：README 和 docs 里的链接、仓库 description、作者 / 组织的博客、论文（arXiv）、
   技术报告、演讲、知乎 / 公众号 / 博客上作者写的设计文章。用 WebSearch 搜「仓库名」「项目名 + 设计 / architecture / design」「作者名 + 项目名」，中英文都搜。
   很多原型仓库是某篇设计文章的配套实现——找到了，它就是主线：文章的每个核心设计都要对照到代码，文章里的实验数字就是待检验的主张。
   打不开的页面（登录墙）记下链接，换搜索结果摘要、镜像或转载。
   读到的资料各写一份摘录到 {dd}/sources/<短名>.md（链接、作者、日期、核心观点、关键数字、原话短引用 ≤ 3 句）。
3. 写 {dd}/understanding.md（中文），按这个结构：
   ## 0 资料来源
   每条：链接 · 类型（作者设计文章 / 论文 / 博客 / README）· 一句话说它提供了什么。写明有没有找到作者的设计文章。
   ## 1 一句话定位
   ## 2 动机链
   痛点（用一个具体场景说）→ 现有 / 朴素做法为什么不够（各举失败的样子）→ 作者给自己定的目标或特征（原话短引用）→ 为了这些目标拆出哪些模块（模块 ↔ 目标对应表）。
   ## 3 场景示例
   2–3 个具体场景（输入是什么、系统依次做了什么、最终效果），写作阶段拿来开篇和画示意图。
   ## 4 术语表
   每个项目自有术语（类名、概念、状态名）：定义（一句白话）· 代码位置 · 一个小例子。不少于 8 个，按读者需要的先后排序。
   ## 5 设计决定
   3–6 个最核心的，每个一个 `### D<n> 标题`，固定写：
   - 矛盾：要同时满足的两件事为什么冲突（例如连续性 vs 吞吐、实时性 vs 成本）
   - 朴素做法 A / B：各自怎么做、在什么情况下失败（具体到场景）
   - 选择：这个项目怎么做（机制，带 `文件:行号`）
   - 为什么成立 + 类比：它像哪个经典系统设计（Fast/Slow Path、缓存、投机执行、存算分离、控制回路、背压、批处理……），类比在哪里成立、哪里不成立
   - 样例走一遍：一条具体输入经过这个机制的每一步（写作阶段据此画示意图）
   - 代价与边界：付出了什么，什么条件下这个选择会变差
   ## 6 可检验主张
   `C<n>`：主张（作者原话或数字优先，其次是你从设计推出的）· 对应设计决定 D<n> · 实验思路（选中方案 vs 哪个朴素替代、测什么指标、扫什么参数、怎么在 {b_total} 分钟内用 mock / 模拟事件流跑轻量版）。
   至少 {min_claims} 条，优先挑能体现设计价值的（系统级行为：时延、吞吐、成本、正确性），不要挑实现细节（某个函数的返回值）。
   ## 7 待解问题
   读完还没弄懂、需要实验或更多资料确认的地方。
4. 只读和写文档，这一阶段不装依赖、不跑实验。最终回复末尾附 ```json
{{"stage": "understand", "sources": ["链接", ...], "author_article": "找到的作者设计文章链接或空", "decisions": 设计决定个数, "claims": 主张个数}}
```
"""

EXPERIMENT = """## 本阶段：实验（检验设计主张）
先读 {dd}/understanding.md（尤其「设计决定」和「可检验主张」）和 {dd}/sources/。仓库已克隆在 {dd}/lab/repo。

1. 依赖只装在 lab/repo 里：Node 用 `pnpm install` / `npm ci`（不加 -g），Python 用 `uv venv {dd}/lab/repo/.venv` 后装进这个 venv；不用 brew / sudo / 全局安装。
   每条可能卡住的命令都加超时：`{timeout} <命令>`（单条最多 {b_cmd} 分钟，装依赖那条最多 {b_install} 分钟）；不起常驻进程，起了服务就在同一条命令里测完并关掉。
   需要真实 LLM / 外部服务 API key 的路径不用真 key：写 mock / fake model / 本地桩（可以给 mock 加上符合实际的延迟和 token 计数），在结果里写明。
2. **时间预算**：装依赖 ≤ {b_install} 分钟（只装一次）；单个实验 ≤ {b_exp} 分钟；全部实验合计 ≤ {b_total} 分钟。实验求轻：用项目自己的模块 + 最小驱动脚本
   模拟核心能力（例如合成一条事件流喂给它），不跑构建、docker、端到端全流程、大数据集。超预算就缩小规模，在结果里写明缩了什么。
3. 设计实验（至少 {min_exp} 个，其中至少 {min_compare} 个是对照 / 消融 / 扫描）：
   - 每个实验对应一条主张 C<n>，**检验设计主张，不是实现细节**：「选中方案 vs 朴素替代」的对照（把机制关掉、换成朴素做法），
     或者沿一个关键变量（到达速率、并发数、消息量、批大小）做参数扫描，看指标怎么随之变化、拐点在哪。
   - 指标要能回答主张：完成时间（p50 / p95）、调用次数、token 数、吞吐、成功率、正确率……每个配置至少重复 3 次（以不超预算为准），写明次数。
   - 可选：E0 跑项目自带的核心测试做健康检查（type 写「自带测试」），不计入对照数。
   - 实验失败（装不上、跑不起来）也是结果：保存输出，写清卡在哪，再换一个能跑的实验补足。
4. 每个实验一个目录 {dd}/lab/E<n>-<slug>/：驱动脚本、命令完整输出 `2>&1 | tee out.txt`（原样，末尾记耗时）、汇总后的指标 data.json。
5. **画图**：对照 / 消融 / 扫描实验都要把 data.json 画成 SVG 存为 {dd}/figs/exp-E<n>.svg——对照用分组柱状图或累计曲线，扫描用折线（多次运行画散点 + 均值线），
   坐标轴有标题和单位，图例清楚，浅色底，中文字体 `font-family="PingFang SC, Microsoft YaHei, sans-serif"`。
   用 python3 脚本从 data.json 生成 SVG（不依赖 matplotlib；脚本放在实验目录里），生成后用 `python3 -c "import xml.etree.ElementTree as E;E.parse('文件')"` 检查能解析。
6. 写 {dd}/results.md：每个实验一节——对应主张 · 设计（对照的是哪几种方案、为什么这样能检验主张）· 规模与次数 · 结果表（数字）· 图 `![](figs/exp-E<n>.svg)` ·
   解读（数字为什么是这样、代价是什么、和哪个设计决定对应、证实 / 推翻 / 部分 / 意外）。最后一节「对理解的修正」：实验改变了 understanding.md 里的哪些判断。
7. 写 {dd}/lab/experiments.json：
   {{"repo_commit": "完整 hash", "env": "OS / 运行时版本", "experiments": [
     {{"id": "E1", "title": "…", "type": "对照|消融|扫描|边界|自写测试|自带测试", "claim": "C1", "runs": 重复次数,
       "cmd": "实际执行的命令", "out": "lab/E1-xxx/out.txt", "fig": "figs/exp-E1.svg", "exit_code": 0,
       "verdict": "证实|推翻|部分|意外", "finding": "一句话结论（带数字）"}}]}}
   out / fig 是相对 {dd} 的路径，文件必须真实存在；平台会逐个检查。
8. 删掉 lab/repo 下的 node_modules、.venv、构建缓存等依赖目录（保留源码、你写的脚本和所有输出），停掉你起的所有进程。
   最终回复末尾附 ```json
{{"stage": "experiment", "experiments": 实验个数, "compare": 对照类实验个数}}
```
"""

WRITE = """## 本阶段：写作
先读 {dd}/understanding.md、{dd}/results.md、{dd}/sources/、{dd}/lab/experiments.json，需要时回仓库 {dd}/lab/repo 核对代码。

写 {dd}/deepdive.md（中文，保留英文术语；目标 12000–25000 字，不少于 {min_chars} 字）。结构（按项目实际调整标题，但顺序和每节的写法要遵守）：
# 项目名 Deep Dive：一句话定位
一行：仓库链接 · 克隆的 commit（短 hash）· 原始设计材料链接（有的话）· 实验环境 · 生成日期
## TL;DR
正好 3 条 `- `：要解决什么问题 / 靠什么核心设计 / 实验验证出的最重要结论（带数字）
## 1 问题从哪来
用场景示例开篇（先让读者看到它做成了什么，可以画成对话流或时间线图）→ 动机链：痛点、朴素做法为什么不够 → 目标特征 →
总架构图 `figs/arch.svg`：方框标上对应的章节号，作为全文地图；图后逐个解释方框。
## 2 … k 每个设计决定一节（顺序按读者理解的依赖关系）
每节都这样推：先抛出矛盾（为什么难）→ 两种朴素做法各自怎么失败 → 这个项目的做法 → 一张机制示意图（用一条具体样例走一遍：
样例数据 / 事件编号写在图里）→ 解释图 → 类比经典系统设计（哪里像、哪里不像）→ 关键代码（≤ 20 行，带 `文件:行号`，只在有助理解时贴）→
代价与适用边界 → 对应实验结论（引用 E<n> 和数字）。新旧做法差异大的，画并排对比图（例如上下两条时间线）。
## 实验
开头说明实验怎么设计：检验哪些主张、对照了哪些方案、指标、规模和次数、用了什么 mock。每个实验：问题 → 设计 → 结果（数据图 + 数字表）→
解读（数字为什么是这样、代价、与前文哪个机制对应、交叉引用别的实验）。贴 out.txt 关键原样片段（不改写、不编造）。
## 开放问题
设计层面的未解问题（扩展性、交互方式、安全、成本、和其他系统协作），区分「实验看到的」和「推测的」；不要写成缺陷清单。
## 结语与可迁移结论
2–4 条可迁移到自己项目（本地学习平台：后台 Agent 任务、事件驱动、知识库）的结论，注明适用边界。用户已学过的内容（有联系就点出来）：
{known}
## 附录：复现
从零复现全部实验的命令清单（按顺序），依赖 / 环境的坑。

写法要求：
- **叙事散文为主**：段落推进，列表只用在真正并列的短项上（列表行不超过非空行的 {bullet_pct}%）；不要把 understanding.md 的条目直接搬过来。
- **术语**：项目自有术语首次出现时加粗并用一句白话定义，必要时给例子；不出现没解释过的缩写。
- **图**（不少于 {min_figs} 张，都放 {dd}/figs/ 并在正文 `![说明](figs/xxx.svg)` 嵌入）：总架构图 1 张；每个设计决定至少 1 张机制示意图；
  至少 1 张新旧做法对比图；实验数据图直接用 figs/exp-*.svg。手写 SVG：viewBox 宽 ≤ 960，浅色底（白或很浅的灰），深色文字，
  主色一种蓝 + 灰，强调用一种颜色；中文字体 `font-family="PingFang SC, Microsoft YaHei, sans-serif"`，字号 ≥ 13；文字不能溢出方框（按每个汉字约 1em 宽估算框宽）；
  箭头用 marker；文字里的 & < > 要转义。每张写完用 `python3 -c "import xml.etree.ElementTree as E;E.parse('文件')"` 检查能解析。图后正文要解释图里的每个元素。
- 所有事实可追溯：代码给 `文件:行号`，数字来自 out.txt / data.json，作者观点注明出处。
最终回复末尾附 ```json
{{"stage": "write", "title": "项目名 Deep Dive：一句话", "tldr": ["第1行", "第2行", "第3行"], "figs": 图数, "chars": 字数}}
```
"""

REVIEW = """## 本阶段：审稿与返修（你是独立审稿人，没参与前面的写作）
稿件：{dd}/deepdive.md；依据：{dd}/understanding.md、{dd}/results.md、{dd}/sources/、{dd}/lab/（out.txt、data.json）、仓库 {dd}/lab/repo。

1. 先把稿件复制为 {dd}/deepdive.draft.md（改前的稿留底）。
2. 按评分表逐条打分（1–5，5 = 达到优秀工程设计长文的水平），每条写具体问题（指到章节 / 段落）：
{rubric}
   另外逐张检查 figs/ 里被正文引用的 SVG：能否解析、文字是否溢出方框、是否浅色底、正文是否解释了它。
   R8 要真的去核对：抽查至少 5 处 `文件:行号` 和数字，写下核对结果。
3. **直接改稿**：所有低于 4 分的条目都要改到位——补动机、补推导、补定义、补图 / 改图、补实验解读、把要点堆砌改写成叙事、修正不准确的说法。
   不重新做实验；实验确实打不到主张时，在正文里如实说明局限。改完再按评分表复评。
4. 写 {dd}/review.json：
   {{"before": {{"R1": {{"score": 3, "issues": ["…"]}}, …}}, "fixes": ["改了什么", …], "checks": ["核对了哪处、结果", …],
     "after": {{"R1": {{"score": 4, "note": "…"}}, …}}}}
   R1–R10 每条都要有。
最终回复末尾附 ```json
{{"stage": "review", "title": "项目名 Deep Dive：一句话（可沿用）", "tldr": ["第1行", "第2行", "第3行"], "after_min": 复评最低分}}
```
"""

BODY = {"understand": UNDERSTAND, "experiment": EXPERIMENT, "write": WRITE, "review": REVIEW}


def dd_dir(item_dir: Path) -> Path:
    return item_dir / "deepdive"


def base_docs(item_dir: Path) -> list[Path]:
    """已有的深读产物：速读笔记、完整教程的 summary.md / index.html。"""
    return [p for p in (item_dir / "note.md", item_dir / "summary.md", item_dir / "index.html") if p.is_file()]


def next_stage(stage: str) -> str:
    i = STAGES.index(stage) if stage in STAGES else len(STAGES)
    return STAGES[i + 1] if i + 1 < len(STAGES) else ""


def prompt(stage: str, it: dict, item_dir: Path, known: str) -> str:
    dd = dd_dir(item_dir)
    base = "\n".join(f"- {p}" for p in base_docs(item_dir)) or "- （还没有，直接从仓库读起）"
    v = {"url": it["url"], "focus": ("用户关注点：" + it["focus"]) if it.get("focus") else "", "base": base, "dd": dd,
         "stage_name": STAGE_NAMES[stage], "timeout": TIMEOUT_HINT, "known": known or "（暂无）",
         "min_exp": MIN_EXPERIMENTS, "min_compare": MIN_COMPARE, "min_claims": MIN_CLAIMS, "min_chars": MIN_CHARS,
         "min_figs": MIN_FIGS, "bullet_pct": int(MAX_BULLET_RATIO * 100),
         "rubric": "\n".join(f"   - {k} {t}" for k, t in RUBRIC.items()),
         "b_cmd": BUDGET["cmd"], "b_install": BUDGET["install"], "b_exp": BUDGET["exp"], "b_total": BUDGET["total"]}
    return HEAD.format(**v) + "\n" + BODY[stage].format(**v)


# 上一版要整体挪走的产物（lab/repo 留着复用，省得重新克隆）
ARCHIVE = ("understanding.md", "results.md", "review.json", "deepdive.draft.md", "sources", "figs")


def prepare(item_dir: Path) -> Path:
    """建目录；上一版挪到 history/<时间>/，正文另存 deepdive.<时间>.md（链接改指 history），不覆盖。"""
    dd = dd_dir(item_dir)
    (dd / "lab").mkdir(parents=True, exist_ok=True)
    old = [dd / n for n in ARCHIVE if (dd / n).exists()] + [p for p in (dd / "lab").glob("E*") if p.is_dir()]
    if (dd / "lab" / "experiments.json").is_file():
        old.append(dd / "lab" / "experiments.json")
    md = dd / "deepdive.md"
    if not old and not md.is_file():
        return dd
    ts = f"{datetime.now():%Y%m%d-%H%M%S}"
    hist = dd / "history" / ts
    for p in old:
        dst = hist / p.relative_to(dd)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(p), str(dst))
    if md.is_file():
        text = md.read_text("utf-8", errors="replace")
        # 正文里的相对链接（figs/、lab/E…、sources/）指向挪走后的位置，旧版本仍能看图、点原样输出
        text = re.sub(r"(\]\(|src=\")(\./)?((?:figs|sources|lab/E|lab/experiments)[^)\"]*)", rf"\1history/{ts}/\3", text)
        (dd / f"deepdive.{ts}.md").write_text(text, "utf-8")
        md.unlink()
    return dd


def experiments(dd: Path) -> list[dict]:
    """实验清单里确实有原样输出的实验（out 文件存在、非空、在 deepdive 目录内）。"""
    try:
        data = json.loads((dd / "lab" / "experiments.json").read_text("utf-8"))
    except (OSError, ValueError):
        return []
    exps = data.get("experiments") if isinstance(data, dict) else data
    out = []
    for e in exps if isinstance(exps, list) else []:
        if not isinstance(e, dict) or not _inside(dd, e.get("out")):
            continue
        if (dd / str(e["out"])).stat().st_size > 0:
            x = {k: e.get(k) for k in ("id", "title", "type", "claim", "runs", "cmd", "out", "exit_code", "verdict", "finding")}
            x["fig"] = e["fig"] if _inside(dd, e.get("fig")) else ""
            out.append(x)
    return out


def _inside(dd: Path, rel) -> bool:
    if not rel or not isinstance(rel, str):
        return False
    p = (dd / rel).resolve()
    return p.is_relative_to(dd.resolve()) and p.is_file()


def _svg_ok(p: Path) -> bool:
    try:
        return ET.parse(p).getroot().tag.rsplit("}", 1)[-1] == "svg"
    except (ET.ParseError, OSError):
        return False


def _fig_ok(dd: Path, rel: str) -> bool:
    if not _inside(dd, rel):
        return False
    p = dd / rel
    return _svg_ok(p) if p.suffix.lower() == ".svg" else p.stat().st_size > 0


def chars(text: str) -> int:
    return len(re.sub(r"\s", "", text))


def _read(p: Path) -> str:
    return p.read_text("utf-8", errors="replace") if p.is_file() else ""


def doc_stats(dd: Path) -> dict:
    """正文的结构指标：字数、嵌入且存在的图、二级标题数、列表行占比、提到的实验编号。"""
    text = _read(dd / "deepdive.md")
    body = re.sub(r"```.*?```", "", text, flags=re.S)
    lines = [ln for ln in body.splitlines() if ln.strip()]
    bullets = [ln for ln in lines if re.match(r"\s*([-*+]|\d+\.)\s", ln)]
    refs = re.findall(r"!\[[^\]]*\]\(\s*(?:\./)?([^)\s]+)", text) + re.findall(r"<img[^>]+src=\"(?:\./)?([^\"]+)", text)
    figs = sorted({r for r in refs if _fig_ok(dd, r)})
    return {"chars": chars(body), "figs": figs, "bad_figs": sorted({r for r in refs if r not in figs}),
            "sections": len(re.findall(r"^##\s", text, re.M)),
            "bullet_ratio": round(len(bullets) / len(lines), 2) if lines else 0.0,
            "exp_ids": set(re.findall(r"\bE\d+\b", text))}


def check_stage(stage: str, dd: Path) -> tuple[bool, str]:
    """平台对每个阶段产物的结构检查（内容质量由审稿阶段按评分表把关）。返回 (ok, 不合格原因)。"""
    if stage == "understand":
        u = _read(dd / "understanding.md")
        if chars(u) < 3000:
            return False, "understanding.md 没写出来或太短（< 3000 字）"
        miss = [s for s in ("资料来源", "动机", "术语", "设计决定", "主张") if s not in u]
        if miss:
            return False, "understanding.md 缺少这些部分：" + "、".join(miss)
        n_d = len(re.findall(r"^###\s*D\d+", u, re.M))
        if n_d < MIN_DECISIONS:
            return False, f"设计决定只有 {n_d} 个（至少 {MIN_DECISIONS} 个 `### D<n>`）"
        n_c = len(set(re.findall(r"\bC(\d+)\b", u)))
        if n_c < MIN_CLAIMS:
            return False, f"可检验主张只有 {n_c} 条（至少 {MIN_CLAIMS} 条 C<n>）"
        return True, ""
    if stage == "experiment":
        if not (dd / "lab" / "experiments.json").is_file():
            return False, "没有实验清单 lab/experiments.json，无法确认实验真的跑过"
        exps = experiments(dd)
        if len(exps) < MIN_EXPERIMENTS:
            return False, f"有原样输出的实验只有 {len(exps)} 个（至少 {MIN_EXPERIMENTS} 个）"
        cmp_ = [e for e in exps if str(e.get("type") or "") in COMPARE_KINDS]
        if len(cmp_) < MIN_COMPARE:
            return False, f"对照 / 消融 / 扫描类实验只有 {len(cmp_)} 个（至少 {MIN_COMPARE} 个），实验要检验设计主张"
        nofig = [str(e["id"]) for e in cmp_ if not (e["fig"] and _fig_ok(dd, e["fig"]))]
        if nofig:
            return False, f"这些对照实验没有可用的数据图（figs/exp-*.svg）：{'、'.join(nofig)}"
        if chars(_read(dd / "results.md")) < 1500:
            return False, "results.md 没写出来或太短（< 1500 字），实验需要解读"
        return True, ""
    if stage in ("write", "review"):
        s = doc_stats(dd)
        if s["chars"] < MIN_CHARS:
            return False, f"deepdive.md 只有 {s['chars']} 字（至少 {MIN_CHARS} 字）"
        if len(s["figs"]) < MIN_FIGS:
            bad = f"；这些图引用了但不存在或 SVG 解析失败：{'、'.join(s['bad_figs'][:5])}" if s["bad_figs"] else ""
            return False, f"正文嵌入的可用图只有 {len(s['figs'])} 张（至少 {MIN_FIGS} 张）{bad}"
        if s["bullet_ratio"] > MAX_BULLET_RATIO:
            return False, f"列表行占 {int(s['bullet_ratio'] * 100)}%（上限 {int(MAX_BULLET_RATIO * 100)}%），要写成叙事而不是要点堆砌"
        miss = [str(e["id"]) for e in experiments(dd) if e.get("id") and e["id"] not in s["exp_ids"]]
        if miss:
            return False, f"正文没讲到这些实验：{'、'.join(miss)}"
        if stage == "review":
            r = review(dd)
            if not r:
                return False, "没有写出 review.json"
            lack = [k for k in RUBRIC if not isinstance((r.get("after") or {}).get(k), dict)]
            if lack:
                return False, f"review.json 的复评缺少：{'、'.join(lack)}"
        return True, ""
    return False, f"未知阶段 {stage}"


def review(dd: Path) -> dict:
    try:
        r = json.loads(_read(dd / "review.json") or "null")
    except ValueError:
        return {}
    return r if isinstance(r, dict) else {}


def review_scores(dd: Path) -> dict:
    """审稿结果摘要：{R1: {name, before, after}}，给页面展示。"""
    r = review(dd)
    out = {}
    for k, t in RUBRIC.items():
        b, a = (r.get("before") or {}).get(k), (r.get("after") or {}).get(k)
        if isinstance(a, dict) or isinstance(b, dict):
            out[k] = {"name": t.split("：")[0], "before": b.get("score") if isinstance(b, dict) else None,
                      "after": a.get("score") if isinstance(a, dict) else None}
    return out


def fail_reason(job: dict) -> str:
    """任务本身失败时，从日志末尾取原因。"""
    lines = [ln for ln in (job.get("log") or "").splitlines() if re.match(r"\[(error|exception|paused)\]", ln)]
    if lines:
        return lines[-1][:300]
    if job.get("status") == "paused":
        return "已暂停"
    return "Agent 任务失败" + (f"：{(job.get('output') or '').strip()[-200:]}" if job.get("output") else "")
