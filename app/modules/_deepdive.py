"""GitHub 项目的 Deep Dive：在深读页按需生成，比 HTML 教程深一层——自己拉仓库、写测试、做实验并跑出结果。

结构参照「Super-agent 设计探索」那类工程文章：问题与设计目标 → 整体架构 → 核心模块逐个讲（机制 + 代码出处 + 设计取舍）
→ 实验（每个都有假设、命令、真实输出、结论）→ 局限与开放问题 → 对我的启发 → 复现附录。
实验跑在条目输出目录下的 deepdive/lab/（本机隔离目录：单独克隆一份仓库，依赖只装在里面）。

产物（<条目目录>/deepdive/）：
    deepdive.md              正文
    figs/                    架构图、README 里的关键图
    lab/repo/                单独克隆的仓库（实验完删掉 node_modules / .venv 等依赖目录）
    lab/E<n>-<slug>/         每个实验的脚本 / 测试文件和原样输出 out.txt
    lab/experiments.json     实验清单（平台据此校验确实跑过）
重新生成时旧版正文改名为 deepdive.<时间>.md 保留，不覆盖。
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

MIN_EXPERIMENTS = 3   # 少于这么多「有原样输出的实验」不算完成
TIMEOUT_HINT = "perl -e 'alarm shift; exec @ARGV' 600"   # macOS 没有 timeout 命令

PROMPT = """任务：GitHub 项目 Deep Dive——比已有的速读 / HTML 教程深得多的工程解读，**必须真实动手**：自己拉仓库、写测试、做实验、跑出结果。
对象：{url}
{focus}
已有深读产物（先读，Deep Dive 不重复它们，而是往深处走、用实验验证或推翻其中的说法）：
{base}

## 工作目录（本机隔离目录，所有写入都只在这里）
- 根目录：{dd}（已创建）
- `git clone --depth 1 {url} {dd}/lab/repo`（已存在就 `git -C {dd}/lab/repo pull --ff-only`），记下 `git rev-parse HEAD`。
- 依赖只装在 lab/repo 里：Node 用 `pnpm install` / `npm ci`（不加 -g），Python 用 `uv venv {dd}/lab/repo/.venv` 后装进这个 venv；
  不用 brew / sudo / 全局安装，不修改 {dd} 以外的任何文件，不读 ~/.ssh、钥匙串、环境变量里的密钥。
- 每条可能卡住的命令都加超时：`{timeout} <命令>`（单条最多 10 分钟）；不起常驻进程，起了服务就在同一条命令里测完并关掉。
- 需要真实 LLM / 外部服务 API key 的路径，不要用真 key：写 mock / fake model / 本地桩，或者只测不依赖模型的部分，并在文中说明。

## 先读懂，再定实验
1. 读 README / docs / 入口 / 核心模块，画出主链路；用 `rg` 找关键数据结构和状态机，记下 `文件:行号`。
2. 列出这个项目**最核心的 3–6 个设计决定**（它为什么这样设计、换一种做法会怎样），每个都想一个能用实验检验的问题。
3. 实验清单（至少 {min_exp} 个，一般 4–8 个，每个都要真的跑）：
   - E1 必做：跑项目自带的测试 / 示例（`pnpm test`、`pytest`、examples 里的脚本），报告通过数、失败数和失败原因。
   - 至少 1 个**自己写的测试**：针对核心机制写新的单元测试 / 脚本（放进 lab/E<n>-<slug>/，必要时复制进 repo 的 tests 目录再跑），
     断言你从代码里读出的行为——读出来的结论被测试推翻时，如实写「推翻」。
   - 至少 1 个**消融 / 对照**：改一个参数、关掉一个机制、换一种输入，对比前后的输出或数字（例如关掉某个过滤 / 批处理 / 重试，看行为怎么变）。
   - 至少 1 个**边界 / 失败用例**：异常输入、并发、超时、权限被拒、资源上限，看系统怎么失败、能不能恢复。
   - 能量化的给数字（耗时、次数、token、吞吐、成功率），多次运行取均值并写明次数。
4. 每个实验一个目录 `{dd}/lab/E<n>-<slug>/`：放你写的脚本 / 测试文件，命令的完整输出用 `2>&1 | tee out.txt` 原样保存到 out.txt。
   实验失败（装不上、跑不起来）也是结果：保存输出，写清卡在哪、怎么绕过或为什么放弃，再换一个能跑的实验补足数量。

## 写 {dd}/deepdive.md（中文，markdown，保留英文术语；通常 6000–15000 字）
结构：
# 项目名 Deep Dive：一句话定位
一行：仓库链接 · 克隆的 commit（短 hash）· 实验环境（OS、node / python 版本）· 生成日期
## TL;DR
正好 3 条 `- `：项目要解决什么、靠什么核心设计 / 实验验证出的最重要结论（带数字）/ 最大的局限或最容易误判的地方
## 1. 问题与设计目标
它要解决的痛点，现有做法为什么不行，作者给自己定的目标 / 特征（README、docs、源码注释里的原话短引用）。
## 2. 整体架构
一张架构图（手写 SVG 存为 figs/arch.svg，浅色底、文字可读，嵌入 `![架构](figs/arch.svg)`；或用文本框图代码块）+ 一条请求 / 事件从进到出的主链路，
每一跳给 `文件:行号`。README / docs 里有承载论证的图就下载到 figs/ 嵌入并解释。
## 3. 核心机制（每个设计决定一小节：3.1、3.2…）
每节：它怎么工作（关键代码片段 ≤ 30 行，带 `文件:行号`）→ 为什么这样设计、放弃了什么 → 对应实验的结论（引用实验编号 E<n>）。
## 4. 实验
开头一张表：编号 | 问题 | 类型（自带测试 / 自写测试 / 消融 / 边界 / 性能）| 结论（证实 / 推翻 / 部分 / 意外）。
然后每个实验一小节，固定五段：
- **问题 / 假设**
- **做法**：写了什么（文件路径 lab/E<n>-…/xxx，关键代码贴出来）
- **命令**：```bash 原样可复制的命令```
- **输出**：```text 从 out.txt 原样摘取的关键部分（不改写、不编造，删节处写 …省略 N 行…）```
- **结论**：证实 / 推翻 / 部分 / 意外 + 解释，以及它对理解第 3 节哪个机制有什么帮助。
## 5. 局限与开放问题
实验暴露的问题、代码里的 TODO / 已知缺陷、规模化 / 安全 / 成本上的未解问题；区分「实验看到的」和「推测的」。
## 6. 与我已有知识的联系 / 可迁移结论
用户已学过的内容：
{known}
2–4 条可迁移到自己项目（本地学习平台：后台 Agent 任务、事件驱动、知识库）的结论，注明适用边界。
## 7. 复现附录
从零复现全部实验的命令清单（按顺序），以及依赖 / 环境的坑。

## 收尾
- 写 {dd}/lab/experiments.json：
  {{"repo_commit": "完整 hash", "env": "OS / 运行时版本", "experiments": [
    {{"id": "E1", "title": "…", "type": "自带测试|自写测试|消融|边界|性能", "cmd": "实际执行的命令", "out": "lab/E1-xxx/out.txt",
      "exit_code": 0, "verdict": "证实|推翻|部分|意外", "finding": "一句话结论"}}]}}
  out 是相对 {dd} 的路径，文件必须真实存在且是那条命令的原样输出；平台会逐个检查，没有原样输出的实验不算。
- 删掉 lab/repo 下的 node_modules、.venv、构建缓存等依赖目录（保留源码、你写的测试和所有 out.txt），停掉你起的所有进程。
- 只写 {dd} 下的文件。最终回复末尾附一个 ```json 代码块：
{{"title": "项目名 Deep Dive：一句话", "tldr": ["第1行", "第2行", "第3行"], "experiments": 实验个数, "output": "deepdive.md"}}
"""


def dd_dir(item_dir: Path) -> Path:
    return item_dir / "deepdive"


def base_docs(item_dir: Path) -> list[Path]:
    """已有的深读产物：速读笔记、完整教程的 summary.md / index.html。"""
    return [p for p in (item_dir / "note.md", item_dir / "summary.md", item_dir / "index.html") if p.is_file()]


def prompt(it: dict, item_dir: Path, known: str) -> str:
    dd = dd_dir(item_dir)
    base = "\n".join(f"- {p}" for p in base_docs(item_dir)) or "- （还没有，直接从仓库读起）"
    return PROMPT.format(url=it["url"], focus=("用户关注点：" + it["focus"]) if it.get("focus") else "", base=base,
                         dd=dd, timeout=TIMEOUT_HINT, min_exp=MIN_EXPERIMENTS, known=known)


def prepare(item_dir: Path) -> Path:
    """建目录；旧版正文改名保留（不覆盖），实验清单清掉，以免校验时拿到上一版的。"""
    dd = dd_dir(item_dir)
    (dd / "lab").mkdir(parents=True, exist_ok=True)
    old = dd / "deepdive.md"
    if old.is_file():
        old.rename(dd / f"deepdive.{datetime.now():%Y%m%d-%H%M%S}.md")
    (dd / "lab" / "experiments.json").unlink(missing_ok=True)
    return dd


def experiments(dd: Path) -> list[dict]:
    """实验清单里确实有原样输出的实验（out 文件存在、非空、在 deepdive 目录内）。"""
    try:
        data = json.loads((dd / "lab" / "experiments.json").read_text("utf-8"))
    except (OSError, ValueError):
        return []
    exps = data.get("experiments") if isinstance(data, dict) else data
    out = []
    base = dd.resolve()
    for e in exps if isinstance(exps, list) else []:
        if not isinstance(e, dict) or not e.get("out"):
            continue
        p = (dd / str(e["out"])).resolve()
        if p.is_relative_to(base) and p.is_file() and p.stat().st_size > 0:
            out.append({k: e.get(k) for k in ("id", "title", "type", "cmd", "out", "exit_code", "verdict", "finding")})
    return out


def check(dd: Path) -> tuple[bool, str, list[dict]]:
    """生成结果是否合格：(ok, 失败原因, 有输出的实验)。"""
    md = dd / "deepdive.md"
    exps = experiments(dd)
    if not md.is_file() or md.stat().st_size < 500:
        return False, "没有写出 deepdive.md", exps
    if not (dd / "lab" / "experiments.json").is_file():
        return False, "没有实验清单 lab/experiments.json，无法确认实验真的跑过", exps
    if len(exps) < MIN_EXPERIMENTS:
        return False, f"有原样输出的实验只有 {len(exps)} 个（至少 {MIN_EXPERIMENTS} 个）", exps
    return True, "", exps


def fail_reason(job: dict) -> str:
    """任务本身失败时，从日志末尾取原因。"""
    lines = [ln for ln in (job.get("log") or "").splitlines() if re.match(r"\[(error|exception|paused)\]", ln)]
    if lines:
        return lines[-1][:300]
    if job.get("status") == "paused":
        return "已暂停"
    return "Agent 任务失败" + (f"：{(job.get('output') or '').strip()[-200:]}" if job.get("output") else "")
