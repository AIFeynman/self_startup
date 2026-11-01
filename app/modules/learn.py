"""深度学习：A. 单篇论文 / GitHub 项目 / 文章（博客、X 长文、gist、讨论帖）/ 视频（YouTube、B 站：旁白解析 + 时间点）深读；B. 主题学习计划（分阶段步骤 + 反馈调整）。

后台 job 的 ref 约定：
    learn:item:<id>          条目深读
    learn:item:<id>:deepdive:<stage> GitHub 项目的 Deep Dive，分理解 / 实验 / 写作 / 审稿四个阶段串行（见 _deepdive.py）
    learn:plan:<id>          生成学习计划
    learn:plan:<id>:adapt    根据反馈调整计划
    learn:course:<id>        导入课程：解析官网课表成单元 + 步骤（轻量模型）；:sync = 同步新发布的讲次（只追加）
    learn:step:<id>:material 课程计划的一讲：先把课件 / 字幕 / 阅读材料整理成素材包 material.md（轻量模型），完成后接着写章节
    learn:step:<id>:chapter  把计划的一步写成章节教程 + 章末测试（:prefetch = 用户读上一章时后台预生成）
    learn:step:<id>:grade    批改章末测试的简答题
    learn:step:<id>:check:<n> 点评第 n 个「停一下」：用户的判断和要点差在哪
按需加一节：用户在某一章说「对 X 感兴趣 / X 没懂」→ 在这一章后面插一步（origin=interest|confused，parent_id 指向原章），
    立即按 learn:step:<新id>:chapter 生成一节短讲解 + 2–3 题小测试，之后和普通章节一样学、测、计入进度。
对话 ref：learn:item:<id> / learn:plan:<id> / learn:step:<id>（读某一章时）/ 空（总览）。
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel

from .. import agent, db, jobs, settings, tasks
from ..db import ROOT
from . import _deepdive
from . import _reads
from . import _video

log = logging.getLogger(__name__)

TITLE = "深度学习"
ORDER = 50
SCHEMA = """
CREATE TABLE IF NOT EXISTS learn_items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    kind        TEXT NOT NULL,              -- paper / github
    url         TEXT NOT NULL,
    title       TEXT DEFAULT '',
    focus       TEXT DEFAULT '',
    status      TEXT DEFAULT 'queued',      -- queued / running / done / failed
    job_id      INTEGER,
    output_path TEXT DEFAULT '',
    summary     TEXT DEFAULT '',            -- TL;DR
    my_notes    TEXT DEFAULT '',
    rating      INTEGER DEFAULT 0,          -- 0-5
    depth       TEXT DEFAULT 'quick',       -- quick 速读笔记 / full 完整教程（GitHub）
    created_at  TEXT,
    updated_at  TEXT
);
CREATE TABLE IF NOT EXISTS learn_plans (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    topic          TEXT NOT NULL,
    background     TEXT DEFAULT '',
    goal           TEXT DEFAULT '',
    hours_per_week REAL DEFAULT 5,
    status         TEXT DEFAULT 'generating',  -- generating / active / adapting / done / failed
    overview_md    TEXT DEFAULT '',
    job_id         INTEGER,
    created_at     TEXT,
    updated_at     TEXT,
    layout         TEXT DEFAULT '',            -- rounds 三轮由浅入深（2026-10-31 起的默认）/ '' 老计划的六阶段
    from_plan      INTEGER,                    -- 由哪个老计划「精简成三轮」而来（老计划保留，状态 archived）
    units          TEXT DEFAULT '[]',          -- 课程计划（layout=course）的单元 JSON [{name,goal}]，步骤的 stage = 单元序号
    source_url     TEXT DEFAULT '',            -- 课程计划：课程官网
    synced_at      TEXT DEFAULT ''             -- 课程计划：上次同步课表的时间
);
CREATE TABLE IF NOT EXISTS learn_steps (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id       INTEGER NOT NULL,
    stage         INTEGER DEFAULT 1,
    ord           INTEGER DEFAULT 0,
    title         TEXT NOT NULL,
    description   TEXT DEFAULT '',
    resources     TEXT DEFAULT '[]',          -- JSON [{title,url,type,why,verified?}]
    questions     TEXT DEFAULT '[]',          -- JSON [str]
    est_hours     REAL DEFAULT 1,
    status        TEXT DEFAULT 'todo',        -- todo / doing / done / skipped
    understanding INTEGER DEFAULT 0,          -- 0-5
    feedback      TEXT DEFAULT '',
    notes         TEXT DEFAULT '',
    done_at       TEXT DEFAULT '',
    goal          TEXT DEFAULT '',            -- 这一步学完要具备的能力（可检验）
    chapter_md    TEXT DEFAULT '',            -- 章节教程（markdown）
    chapter_status TEXT DEFAULT '',           -- '' / generating / ready / failed
    chapter_job   INTEGER,
    quiz          TEXT DEFAULT '[]',          -- 章末测试 JSON [{id,type:choice|short,q,options,answer,explain,reference,rubric,dim:理解|判断|应用,about,section}]
    cards         TEXT DEFAULT '[]',          -- 知识卡 JSON [{front,back,tag}]
    checks        TEXT DEFAULT '{}',          -- 「停一下」作答 JSON {序号: {q,points,answer,at,status,job_id,review}}
    quiz_result   TEXT DEFAULT '',            -- JSON {answers,items:{qid:{score,feedback}},score,status:grading|graded|failed,...}
    origin        TEXT DEFAULT '',            -- '' 计划里的步骤 / interest 按需深入 / confused 按需补课
    parent_id     INTEGER,                    -- 按需加的一节：从哪一章加出来的
    request       TEXT DEFAULT '',            -- 按需加的一节：用户的原话（感兴趣的子方向 / 没懂的地方）+ 划线原文
    step_kind     TEXT DEFAULT '',            -- 课程计划：lecture 讲次 / assignment 作业（实践步骤）
    material_status TEXT DEFAULT '',          -- 课程计划：素材包 '' / generating / ready / failed
    material_job  INTEGER
);
CREATE INDEX IF NOT EXISTS idx_learn_steps_plan ON learn_steps(plan_id);
-- 学习记录：只追加、不覆盖（作答、Agent 点评、每次测试连同当时的题目、理解度 / 反馈变化、章节重新生成），用于复盘和成长评价
CREATE TABLE IF NOT EXISTS learn_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id     INTEGER,
    step_id     INTEGER,
    kind        TEXT NOT NULL,              -- check 作答 / check_review 点评 / qa 追问清单作答 / qa_review 追问点评 / quiz 测试 / rating 理解度·反馈·状态 / chapter 章节生成 / apply 用到项目
    data        TEXT DEFAULT '{}',
    src         TEXT DEFAULT '',            -- 来源：job:<id> / backfill
    created_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_learn_events_step ON learn_events(step_id);
"""

# 三轮由浅入深（新计划默认）：先拿到最新全貌和主干，再学会判断，最后跟前沿、用项目和产品实践检验；每轮结束都可以停
ROUNDS = {1: "看懂：最新全貌与主干机制", 2: "会判断：经典与一线人物", 3: "跟前沿、做出来"}
ROUND_GOALS = {
    1: "拿到最新的领域地图（以近 12 个月的综述 / 书为主读物），吃透撑起它的 2–3 个核心机制；能把任意新论文或新产品定位到地图上、讲清它靠什么工作",
    2: "一篇经典讲透一个机制，知道主干怎么来的、为什么有效；看懂一线人物的判断和依据，能对新方案做出有依据的判断",
    3: "消化最新论文并判断价值；读懂代表性开源项目怎么落地，亲手用对标产品 / 工具并写出有依据的使用评估",
}
PLAN_COLS = {"layout": "TEXT DEFAULT ''", "from_plan": "INTEGER", "units": "TEXT DEFAULT '[]'",
             "source_url": "TEXT DEFAULT ''", "synced_at": "TEXT DEFAULT ''"}
COURSE_MAX_UNITS = 40  # 课程计划的单元数上限（一门课 15 讲左右，按主题合并后十几个单元）
# 老计划的六个阶段（2026-10-31 之前生成的计划）
STAGES = {1: "领域综述", 2: "核心人物与观点", 3: "关键书籍 / 经典论文",
          4: "核心机制 / 概念精学", 5: "前沿进展", 6: "实践与输出"}
# 每个阶段的目的：写章节、出测试、页面引导都按它来（细则见 skills/learn/chapter.md）
STAGE_GOALS = {
    1: "建立整体地图：分类体系，每个方向的痛点、热点、开放问题和主流方案；能把任意一篇新论文定位到地图上",
    2: "提升判断力：看懂一线人物怎么判断、依据是什么、哪些被验证或推翻；能对新事件做出同样深度的判断",
    3: "快速吸收核心思想和背后逻辑：10 分钟讲清一篇经典的问题、关键洞察、为什么有效、改变了什么",
    4: "吃透机制：能推导、能实现最小版本、知道失效条件",
    5: "快速消化新论文并判断价值：相对已有工作的增量、证据是否可信、代表什么趋势",
    6: "用产出检验理解：做出来、讲清楚、按验收标准自评",
}
DIMS = ("理解", "判断", "应用")  # 章末测试评估的三个维度
PASS_SCORE = 70  # 章末测试及格线：及格自动标记完成
STEP_COLS = {"goal": "TEXT DEFAULT ''", "chapter_md": "TEXT DEFAULT ''", "chapter_status": "TEXT DEFAULT ''",
             "chapter_job": "INTEGER", "quiz": "TEXT DEFAULT '[]'", "quiz_result": "TEXT DEFAULT ''",
             "cards": "TEXT DEFAULT '[]'", "checks": "TEXT DEFAULT '{}'",
             "origin": "TEXT DEFAULT ''", "parent_id": "INTEGER", "request": "TEXT DEFAULT ''",
             "step_kind": "TEXT DEFAULT ''", "material_status": "TEXT DEFAULT ''", "material_job": "INTEGER"}
EXTRA = {"interest": "深入", "confused": "补课"}  # 按需加一节的两种：感兴趣 → 往深处展开；没懂 → 换个讲法讲透
SKILL_DIR = ROOT / "skills" / "learn"
KINDS = ("paper", "github", "article", "video")
STEP_STATUS = ("todo", "doing", "done", "skipped")
router = APIRouter()


# ---------- 工具函数 ----------

def detect_kind(url: str) -> str:
    u = url.strip().lower()
    if _video.is_video_url(u):
        return "video"
    if re.search(r"(arxiv\.org|doi\.org|openreview\.net|\.pdf$|^10\.\d{4,9}/)", u):
        return "paper"
    if re.search(r"(^|//|\.)github\.com/[\w.-]+/[\w.-]+", u) and "gist.github.com" not in u or re.fullmatch(r"[a-z0-9][\w.-]*/[\w.-]+", u):
        return "github"
    p = Path(url.strip()).expanduser()
    if p.is_dir():
        return "github"  # 本地 checkout
    if u.startswith("http"):
        return "article"  # 博客 / X 长文 / gist / 讨论帖 / 官方文章
    return "paper"


def slugify(url: str) -> str:
    u = url.strip().rstrip("/")
    if m := re.search(r"(10\.\d{4,9}/\S+)", u):
        s = "doi-" + m.group(1)
    elif m := re.search(r"arxiv\.org/\w+/(\d{4}\.\d{4,5})", u) or re.fullmatch(r"(\d{4}\.\d{4,5})(v\d+)?", u):
        s = f"arxiv-{m.group(1)}"
    elif m := re.search(r"github\.com/([^/]+)/([^/#?]+)", u) or re.fullmatch(r"([\w.-]+)/([\w.-]+)", u):
        s = f"{m.group(1)}-{m.group(2).removesuffix('.git')}"
    elif vid := _video.youtube_id(u):
        s = f"yt-{vid}"
    elif m := _video.BILI_RE.search(u):
        s = f"bili-{m.group(1)}"
    else:
        s = Path(u.split("?")[0]).stem or "item"
    s = re.sub(r"[^\w.-]+", "-", s, flags=re.ASCII).strip("-.").lower()
    return s[:60] or "item"


def extract_json(text: str, key: str | None = None):
    """从 Agent 输出里取 JSON：优先最后一个 ```json 代码块，否则扫描最大的 {...}。key 给定时要求包含该键。"""
    if not text:
        return None
    ok = lambda o: isinstance(o, dict) and (key is None or key in o)  # noqa: E731
    for block in reversed(re.findall(r"```(?:json)?\s*\n(.*?)```", text, re.S)):
        try:
            o = json.loads(block)
            if ok(o):
                return o
        except json.JSONDecodeError:
            pass
    dec, best, i = json.JSONDecoder(), None, 0
    while (i := text.find("{", i)) >= 0:
        try:
            o, end = dec.raw_decode(text, i)
            if ok(o) and (best is None or end - i > best[1]):
                best = (o, end - i)
            i = end if isinstance(o, dict) else i + 1
        except json.JSONDecodeError:
            i += 1
    return best[0] if best else None


def _loads(s, default):
    if isinstance(s, (list, dict)):
        return s
    try:
        return json.loads(s or "")
    except (json.JSONDecodeError, TypeError):
        return default


def _out_root() -> Path:
    return Path(settings.get("learn.output_dir") or db.DATA_DIR / "learn").expanduser()


def _skill_dir(kind: str) -> Path:
    key = "paper_skill" if kind == "paper" else "github_skill"
    return Path(settings.get(f"learn.{key}", "")).expanduser().parent


def _ref_text(name: str) -> str:
    p = SKILL_DIR / name
    return p.read_text("utf-8") if p.exists() else ""


def _known_knowledge(exclude_id: int = 0, limit: int = 20, exclude_plan: int = 0) -> str:
    items = db.rows("SELECT id,kind,title,url,summary,my_notes FROM learn_items WHERE status='done' AND id!=? "
                    "ORDER BY id DESC LIMIT ?", [exclude_id, limit])
    plans = db.rows("SELECT id,topic,goal FROM learn_plans WHERE id!=? ORDER BY id DESC LIMIT 10", [exclude_plan])
    lines = [f"- [条目{i['id']} {i['kind']}] {i['title'] or i['url']}：{(i['summary'] or '').replace(chr(10), ' ')[:200]}"
             + (f"；我的笔记：{i['my_notes'][:150]}" if i["my_notes"] else "") for i in items]
    lines += [f"- [计划{p['id']}] 主题：{p['topic']}（目标：{p['goal'][:80]}）" for p in plans]
    return "\n".join(lines) or "（暂无）"


# ---------- A. 条目深读 ----------

_FILLER = re.compile(r"(帮我|请|把|这个|这篇|这份|一下|加入到?|加到|放到|放进|深度学习|深读|解读|解析|学习|看看|分析|里面?|中|吧|。|，|,|\s)+")


def normalize_target(text: str) -> tuple[str, str]:
    """从用户输入里抽出真正的链接/标识，剩下有意义的文字作为关注点。
    「https://github.com/a/b 这个加入到深度学习里」→ ("https://github.com/a/b", "")"""
    t = (text or "").strip()
    pats = [r"https?://github\.com/[\w.-]+/[\w.-]+(?:/(?:tree|blob)/[^\s，。]+)?",
            r"https?://[^\s，。、）)]+", r"\b10\.\d{4,9}/[^\s，。]+", r"(?<![\w/])(?:arxiv:)?\d{4}\.\d{4,5}(?:v\d+)?\b",
            r"(?<![\w/.])[A-Za-z][\w.-]*/[\w.-]+(?![\w/])", r"(?:^|\s)(~?/[^\s]+)"]
    for pat in pats:
        m = re.search(pat, t)
        if m:
            url = (m.group(1) if m.lastindex else m.group(0)).strip().rstrip(".")
            if url.startswith("arxiv:"):
                url = url[6:]
            if re.fullmatch(r"\d{4}\.\d{4,5}(v\d+)?", url):
                url = f"https://arxiv.org/abs/{url}"
            if re.search(r"github\.com/", url):
                url = re.sub(r"\.git$", "", url)
            rest = (t[:m.start()] + " " + t[m.end():]).strip()
            rest = rest if len(_FILLER.sub("", rest)) >= 2 else ""
            return url, rest
    return t, ""


class ItemIn(BaseModel):
    url: str
    kind: str = ""
    focus: str = ""
    depth: str = ""      # quick / full；空 = 论文 full、GitHub quick
    reuse: bool = False  # 同一链接已有条目就直接用（信息推荐里点「深读」）


def layout_of(p: dict | None) -> tuple[dict, dict, str]:
    """计划用哪套结构：(各轮 / 阶段 / 单元名, 目的, 单位)。"""
    if (p or {}).get("layout") == "course":
        units = [u for u in _loads(p.get("units"), []) if isinstance(u, dict)]
        return ({i: str(u.get("name") or "") for i, u in enumerate(units, 1)},
                {i: str(u.get("goal") or "") for i, u in enumerate(units, 1)}, "单元")
    return (ROUNDS, ROUND_GOALS, "轮") if (p or {}).get("layout") == "rounds" else (STAGES, STAGE_GOALS, "阶段")


def stage_label(p: dict | None, no: int, with_goal: bool = False) -> str:
    names, goals, unit = layout_of(p)
    label = (f"第 {no} 轮 · {names.get(no, '')}" if unit == "轮" else f"单元 {no} · {names.get(no, '')}" if unit == "单元"
             else f"阶段 {no} · {names.get(no, '')}")
    return label + (f" —— 本{unit}目的：{goals.get(no, '')}" if with_goal else "")


_plan_cols_ok = False


def _ensure_plan_cols() -> None:
    global _plan_cols_ok
    if _plan_cols_ok:
        return
    cols = {r["name"] for r in db.rows("PRAGMA table_info(learn_plans)")}
    for k, decl in PLAN_COLS.items():
        if k not in cols:
            db.execute(f"ALTER TABLE learn_plans ADD COLUMN {k} {decl}")
    _plan_cols_ok = True


def _ensure_step_cols() -> None:
    """老库补上章节 / 测试列。"""
    cols = {r["name"] for r in db.rows("PRAGMA table_info(learn_steps)")}
    for k, decl in STEP_COLS.items():
        if k not in cols:
            db.execute(f"ALTER TABLE learn_steps ADD COLUMN {k} {decl}")


# Deep Dive：dd_status '' / running / done / failed；dd_stage 当前（或失败停在的）阶段；dd_error 失败原因；
# dd_experiments 校验过的实验清单 JSON
DD_COLS = {"dd_status": "TEXT DEFAULT ''", "dd_stage": "TEXT DEFAULT ''", "dd_job": "INTEGER", "dd_error": "TEXT DEFAULT ''",
           "dd_experiments": "TEXT DEFAULT '[]'", "dd_title": "TEXT DEFAULT ''", "dd_at": "TEXT DEFAULT ''"}


def _ensure_depth_col() -> None:
    """老库补上 depth（速读 / 完整教程）、qa（追问清单作答与点评）和 Deep Dive 的列。"""
    cols = {r["name"] for r in db.rows("PRAGMA table_info(learn_items)")}
    if "depth" not in cols:
        db.execute("ALTER TABLE learn_items ADD COLUMN depth TEXT DEFAULT 'quick'")
    if "qa" not in cols:
        db.execute("ALTER TABLE learn_items ADD COLUMN qa TEXT DEFAULT '{}'")
    for c, t in DD_COLS.items():
        if c not in cols:
            db.execute(f"ALTER TABLE learn_items ADD COLUMN {c} {t}")


class ItemPatch(BaseModel):
    title: str | None = None
    my_notes: str | None = None
    rating: int | None = None
    status: str | None = None


def _item(iid: int) -> dict:
    it = db.row("SELECT * FROM learn_items WHERE id=?", [iid])
    if not it:
        raise HTTPException(404, "item not found")
    return it


def _item_dir(it: dict) -> Path:
    return _out_root() / f"{it['id']}-{slugify(it['url'])}"


QUICK_GITHUB = """任务：GitHub 项目速读（目标 5 分钟内完成，不追求面面俱到）
对象：{url}
{focus}
做法：
- `git clone --depth 1` 到 {out}/src（已存在就直接用）。只读 README、包清单/入口文件和最关键的 10–20 个文件；有 docs/、examples/ 时，列出其中文件，并读每篇的标题和开头，在「最值得看的部分」里写出该读哪几篇；不安装依赖、不运行代码、不写生成器或 HTML。
- 先判断类型：**代码项目**写「架构速读」；**文档 / 书籍 / 教程 / awesome 列表**（大部分是 .md）写「阅读指南」。
- 用户已学过的内容（用于「与我已有知识的联系」）：
{known}

写 {out}/note.md（中文，markdown，控制在 1500 字以内），结构：
## TL;DR
正好 3 条 `- `：做什么、给谁用 / 核心机制或全书主线 / 最值得学的一点
## 是什么
代码项目：入口 → 核心模块 → 产物的一条主链路，列关键文件（相对路径），必要时附 GitHub permalink。
文档项目：全书 / 全库结构（每章或每部分一句话），核心概念之间的关系。
## 最值得看的部分
3–5 个文件或章节，每个说明为什么值得看、带着什么问题去看。
## 与我已有知识的联系
## 可迁移结论
2–4 条。
## 最小上手实验
代码项目写 3–8 步命令和预期观察；文档项目写一个读完后可以动手做的小练习。只写步骤，不要实际运行。
## 追问清单
3 个最值得继续追问、可以直接复制到对话里的问题（练习题另写在 qa.json）。

{figs}
{qa}
完成后，最终回复末尾附一个 ```json 代码块：
{{"title": "项目名 · 一句话", "tldr": ["第1行", "第2行", "第3行"], "output": "note.md"}}
"""


FIGS = """关键图（默认必做，不是可选项）：原文里承载论证的图——结果图表、架构 / 流程图、实验设置示意、关键表格截图——要下载进笔记，读者不点原文也能看到。
- 找图：网页从 HTML 的 <img> / <figure> / srcset / og:image 里收集（r.jina.ai 的输出里是 `![](url)`）；论文优先 arXiv HTML 版
  `https://arxiv.org/html/<id>` 里的 figure 图片，没有 HTML 版就下 PDF 到输出目录，用 `pdfimages -png` 抽图，抽不出（矢量图）就
  `pdftoppm -png -r 150 -f <页> -l <页>` 渲染图所在页，再用 `magick` 裁到图的区域；GitHub 项目找 README / docs 里的架构图、效果图。
- 跳过 logo、头像、图标、装饰性头图、广告和相关文章缩略图。一般 2–8 张，宁缺毋滥；原文没有实质性的图就写一句「原文无关键图」。
- 下载：`mkdir -p {out}/figs && curl -sSL --max-filesize 8000000 -o {out}/figs/fig1.png <url>`，按出现顺序命名 fig1、fig2…，扩展名跟原图
  （webp / svg 也行）；下载后用 `file` 确认确实是图片而不是 HTML 错误页，失败的删掉。
- 每张图都要用 Read 工具打开看一遍，读出图里的真实数字和结论，不要只凭图注猜。
- 嵌入：在笔记正文里讲到它的位置插入 `![图1：图的标题](figs/fig1.png)`（必须是相对路径），紧接一行 `> 图1 说明：…`，写清图在比较什么、
  坐标 / 图例怎么读、关键数字、它支撑了作者哪个论点。HTML 产物里用 `<figure><img src="figs/fig1.png"><figcaption>…</figcaption></figure>`。
- 实在下载不了（防爬、要登录）：嵌入原图的远程 URL，并在图注里写明「未能下载，显示原站图片」；连 URL 都拿不到时文字描述图的内容并注明。
"""


QA_SPEC = """练习题（默认必做）：读完笔记后写 {out}/qa.json，帮用户检验有没有读懂，页面上逐题作答。以选择题为主，少打字：
{{"questions": [
  {{"id": "q1", "type": "choice", "q": "题干", "options": ["A 的内容", "B…", "C…", "D…"], "answer": 0,
    "explain": "为什么对、其它选项错在哪（2–3 句，带出处：笔记小节 / 原文段落 / `文件:行号`）", "section": "笔记里对应的小节标题", "dim": "理解"}},
  {{"id": "q5", "type": "short", "q": "开放题", "reference": "参考要点（3–5 句）", "rubric": ["得分点1", "得分点2"], "section": "…", "dim": "应用"}}
]}}
- 4 道选择题 + 1 道开放题（开放题最多 2 道）。选择题 4 个选项、只有一个对，answer 是正确选项的下标（从 0 开始），正确答案的位置要打散。
- 考核心机制、关键证据与数字、最容易误读的地方，dim 取 理解 / 判断 / 应用；干扰项要像真的（常见误解、把条件说反、张冠李戴），不出凭常识就能选对或纯记忆细节的题。
- 开放题留给最值得自己动手想的问题：迁移到用户自己的项目，或质疑作者的关键论证。
"""


ARTICLE = """任务：文章深读（博客 / X 长文 / gist / 讨论帖 / 官方文章），写成一份可评论、可追问的本地文档
对象：{url}
{focus}
{feed}
做法：
- 先读全文：普通网页用 WebFetch 或 curl；X / Twitter 的帖子和长文直接抓常常拿不到，依次试 `https://api.fxtwitter.com/<用户>/status/<id>`、
  `https://r.jina.ai/<原链接>`；gist 用 `https://api.github.com/gists/<id>`；HN 用 `https://hn.algolia.com/api/v1/items/<id>`（顺带看讨论里有分量的反驳）；
  Reddit 帖子用 `<帖子链接>.rss`（正文 + 高赞评论；直接抓网页常被拦，不要绕），帖子的价值往往在评论：提炼亲身实践经验
  （配置、数字、踩坑）和有分量的反驳 / 补充，帖子指向外链时也读外链。
  实在拿不到全文，就基于上面的推荐摘要写，并在文档开头写明「未读到全文」。
- 用户已学过的内容（用于「与我已有知识的联系」）：
{known}

写 {out}/note.md（中文，markdown，一到两屏，保留英文术语和原文关键句），结构：
## TL;DR
正好 3 条 `- `：作者的核心主张 / 最有说服力的论据或例子 / 最值得怀疑或最容易误读的地方
## 作者在说什么
按原文顺序把论证主线讲清楚：问题 → 主张 → 论据 → 结论。关键处附原文短引用。
## 论据可信吗
哪些是数据 / 实验 / 一手经验，哪些只是观点；作者的立场和利益相关；与主流看法的分歧。
## 与我已有知识的联系
## 可迁移结论 / 对我的启发
2–4 条，注明适用边界。
## 追问清单
3 个最值得继续追问、可以直接复制到对话里的问题（练习题另写在 qa.json）。
## 我的笔记
（留空，给用户写）

{figs}
{qa}
只写 note.md、qa.json 和 figs/ 下的图片，不要改其它文件。完成后，最终回复末尾附一个 ```json 代码块：
{{"title": "原文标题（作者）", "tldr": ["第1行", "第2行", "第3行"], "output": "note.md"}}
"""


VIDEO = """任务：视频深度解读（YouTube / B 站等），重点是旁白内容的解析总结和时间点，方便用户挑段落手动去看
对象：{url}
{focus}
{feed}
做法：
- 先取文字稿（不下载视频）：`{fetch}`
  产物：transcript.md（作者章节 + 按 ~45 秒分段、每段开头是可点击的 [mm:ss](跳转链接)）和 video.json（标题、频道、时长、字幕来源）。
  自动字幕没有标点、有错别字（人名 / 术语尤其多），按上下文纠正后再引用。
- 命令失败或提示「没有可用字幕」：时长 ≤ 90 分钟的，在同一命令末尾加 `--whisper` 重跑（本机转写，较慢）；仍拿不到就基于视频简介
  和推荐摘要写，文档开头写明「未拿到文字稿」，时间点只列作者章节。
- 文字稿很长时分段读完，不要只读开头；时间点只用文字稿里真实出现的，不要估算或编造。
- 用户已学过的内容（用于「与我已有知识的联系」）：
{known}

写 {out}/note.md（中文，markdown，保留英文术语和原话里的关键句），结构：
# 视频标题（频道）
一行：时长 · 发布日期 · 字幕来源 · [原视频](链接)
## TL;DR
正好 3 条 `- `：视频的核心观点 / 最有价值的一段（带时间点）/ 最值得怀疑或需要自己验证的说法
## 时间轴
按视频顺序 6–15 条，每条一行：`- [mm:ss](跳转链接) 小标题 —— 这一段讲了什么（一句话）`。有作者章节时以章节为骨架，长章节内部再细分。
## 旁白解析
按主题（不是逐句复述）归纳讲者的论证：问题 → 主张 → 论据 / 演示 / 数据 → 结论。每个要点后面括注出处时间点 `[mm:ss](链接)`，关键处附原话短引用。
画面里的演示、图表、代码只凭旁白无法确知的，写明「需看画面」。
## 值得手动看的片段
3–6 段，每段：`[起始](链接)–结束时间` + 为什么值得看（演示操作、图表、关键论证、精彩问答）+ 带着什么问题去看。
## 论据可信吗
哪些是实验 / 数据 / 一手经验，哪些只是观点；讲者的立场和利益相关；与主流看法的分歧。
## 与我已有知识的联系
## 可迁移结论 / 对我的启发
2–4 条，注明适用边界。
## 追问清单
3 个最值得继续追问、可以直接复制到对话里的问题（练习题另写在 qa.json）。
## 我的笔记
（留空，给用户写）

{qa}
只写 note.md、qa.json，以及取文字稿命令生成的 transcript.md、video.json、字幕文件，不要改其它文件。完成后，最终回复末尾附一个 ```json 代码块：
{{"title": "视频标题（频道）", "tldr": ["第1行", "第2行", "第3行"], "output": "note.md"}}
"""


def _feed_hint(url: str) -> str:
    """从信息推荐里点进来的：带上推荐时抓到的标题、摘要、作者，X 长文抓不到全文时至少有个底。"""
    try:
        key, tail = _reads.norm_url(url), url.rstrip("/").rsplit("/", 1)[-1][:60]
        r = next((r for r in db.rows("SELECT url, title, summary, source, extra FROM feed_items WHERE url LIKE ?", [f"%{tail}%"])
                  if _reads.norm_url(r["url"]) == key), None)
    except Exception:  # noqa: BLE001  信息推荐的表还没建
        return ""
    if not r:
        return ""
    ex = _loads(r.get("extra"), {})
    who = " · ".join(str(ex[k]) for k in ("name", "author") if ex.get(k))
    return (f"推荐时抓到的信息（来源 {r['source']}{' · ' + who if who else ''}）：\n标题：{ex.get('article_title') or r['title']}\n"
            f"摘要：{(r['summary'] or '')[:1500]}")


def item_prompt(it: dict, out: Path) -> str:
    kind = it["kind"]
    if kind == "video":
        return VIDEO.format(url=it["url"], focus=("用户关注点：" + it["focus"]) if it["focus"] else "",
                            feed=_feed_hint(it["url"]), out=out, known=_known_knowledge(it["id"]),
                            fetch=f"{sys.executable} {Path(_video.__file__).resolve()} '{it['url']}' {out}",
                            qa=QA_SPEC.format(out=out))
    if kind == "article":
        return ARTICLE.format(url=it["url"], focus=("用户关注点：" + it["focus"]) if it["focus"] else "",
                              feed=_feed_hint(it["url"]), out=out, known=_known_knowledge(it["id"]),
                              figs=FIGS.format(out=out), qa=QA_SPEC.format(out=out))
    if kind == "github" and (it.get("depth") or "quick") == "quick":
        return QUICK_GITHUB.format(url=it["url"], focus=("用户关注点：" + it["focus"]) if it["focus"] else "",
                                   out=out, known=_known_knowledge(it["id"]), figs=FIGS.format(out=out),
                                   qa=QA_SPEC.format(out=out))
    skill = settings.get("learn.paper_skill" if kind == "paper" else "learn.github_skill")
    main = "note.md" if kind == "paper" else "index.html"
    obsidian = "允许按 paper-library 格式同时归档到其 config.json 指定的 Obsidian 库。" \
        if settings.get("learn.write_obsidian", False) else \
        "不要写入 paper-library config.json 里的 Obsidian 库，也不要修改任何 skill 的文件；只写输出目录。"
    what = "论文深度解读" if kind == "paper" else "GitHub 项目架构与代码解读"
    return f"""任务：{what}
对象：{it['url']}
{('用户关注点：' + it['focus']) if it['focus'] else ''}

1. 先完整阅读并遵循 skill：{skill}（以及同目录 references/ 中相关文件{'，深度解读按 references/deep-reading.md' if kind == 'paper' else ''}）。
2. 再按下面「本平台增补」执行；两者冲突时以增补为准。
3. 输出目录（已创建，绝对路径）：{out}
   主产物：{out / main}{'；另写 ' + str(out / 'summary.md') if kind == 'github' else ''}
   {obsidian}
4. 用户已学过的内容（用于「与我已有知识的联系」；更多可 curl {agent.API_BASE}/api/learn/items 查看）：
{_known_knowledge(it['id'])}

5. 完成后，最终回复末尾附一个 ```json 代码块：
{{"title": "论文/项目标题", "tldr": ["第1行", "第2行", "第3行"], "output": "{main}"}}

6. {FIGS.format(out=out)}
7. {QA_SPEC.format(out=out)}
{'若仓库主要是文档 / 书籍 / 教程（大部分是 .md）而非代码，不要硬套代码架构讲解：改为「阅读指南」式 HTML，包括全书结构、每章一句话、概念关系图、推荐阅读顺序和最值得读的章节，不写实验脚本。' if kind == 'github' else ''}

---- 本平台增补 ----
{_ref_text(kind + '.md')}
"""


def start_item_job(it: dict) -> int:
    out = _item_dir(it)
    out.mkdir(parents=True, exist_ok=True)
    (out / "qa.json").unlink(missing_ok=True)   # 练习题跟着笔记重出；以前的作答在 qa 列里，换题后进「以前的作答」
    dirs = [str(SKILL_DIR)] if it["kind"] in ("article", "video") else [str(_skill_dir(it["kind"])), str(SKILL_DIR)]
    jid = jobs.submit("learn", item_prompt(it, out), ref=f"learn:item:{it['id']}", cwd=str(out), add_dirs=dirs)
    db.update("learn_items", it["id"], {"job_id": jid, "status": "running", "updated_at": db.now()})
    return jid


_imported = False


def import_chat_reads() -> list[int]:
    """对话里直接做过的「深度解析：链接」补成深读条目（每个进程第一次列条目时做一次，之后新建条目时按链接认领）。"""
    global _imported
    _imported = True
    _ensure_depth_col()
    return _reads.import_chat_reads(_out_root(), detect_kind, slugify, _tldr_from_md)


@router.get("/items")
def list_items():
    if not _imported:
        try:
            import_chat_reads()
        except Exception:  # noqa: BLE001  补导入失败不影响列表
            log.exception("import chat reads")
    return db.rows("SELECT * FROM learn_items ORDER BY id DESC")


@router.post("/items")
def create_item(body: ItemIn):
    _ensure_depth_col()
    url, extra = normalize_target(body.url)
    if not url:
        raise HTTPException(400, "url required")
    if _video.is_video_url(url):
        url = _video.canonical_url(url)   # 带播放列表 / 时间点参数的也算同一个视频
    if body.reuse and (old := _reads.find_item(url)):
        _reads.bind_chats(old)
        return old
    kind = body.kind if body.kind in KINDS else detect_kind(url)
    depth = body.depth if body.depth in ("quick", "full") else ("quick" if kind == "github" else "full")
    focus = "；".join(x for x in (body.focus.strip(), extra) if x)
    iid = db.insert("learn_items", {"kind": kind, "url": url, "focus": focus, "depth": depth, "status": "queued",
                                    "created_at": db.now(), "updated_at": db.now()})
    it = _item(iid)
    start_item_job(it)
    _reads.bind_chats(it)
    _reads.ensure_task(it)
    return _item(iid)


@router.get("/items/{iid}")
def get_item(iid: int):
    return _item(iid)


@router.patch("/items/{iid}")
def patch_item(iid: int, body: ItemPatch):
    _item(iid)
    data = {k: v for k, v in body.model_dump().items() if v is not None}
    if "rating" in data:
        data["rating"] = max(0, min(5, int(data["rating"])))
    data["updated_at"] = db.now()
    db.update("learn_items", iid, data)
    _reads.sync_task(iid)
    return _item(iid)


@router.get("/items/{iid}/reads")
def item_reads(iid: int):
    """条目对话里的追问与感想、对应的当天事项。"""
    _item(iid)
    t = _reads.task_of(iid)
    return {"lines": _reads.user_lines(iid), "task": {"id": t["id"], "date": t["date"], "status": t["status"]} if t else None}


# ---------- 追问清单：逐题作答 + Agent 点评 ----------

def _item_note(it: dict) -> str:
    """条目的 markdown 笔记（GitHub 优先 summary.md，和对话上下文一致）。"""
    for p in (_item_dir(it) / "summary.md", Path(it.get("output_path") or "")):
        if p.is_file() and p.suffix == ".md":
            return p.read_text("utf-8", errors="replace")
    return ""


def qa_questions(text: str) -> list[str]:
    """笔记里「## 追问清单」一节的问题：编号或列表行，续行并进上一题。"""
    m = re.search(r"^#{2,4}\s*追问清单[^\n]*\n(.*?)(?=^#{1,4}\s|\Z)", text, re.S | re.M)
    if not m:
        return []
    qs: list[str] = []
    for ln in m.group(1).splitlines():
        if not ln.strip():
            continue
        if hit := re.match(r"\s*(?:\d+[.、)）]|[-*•])\s+(.*)", ln):
            qs.append(hit.group(1).strip())
        elif qs:
            qs[-1] += " " + ln.strip()
    return [q for q in qs if q][:12]


def _item_qa(it: dict) -> dict:
    return _loads(it.get("qa"), {}) or {}


def item_quiz(it: dict) -> list[dict]:
    """条目输出目录里的 qa.json（选择题为主 + 1–2 道开放题），格式和章末测试一样；没有或不合格时为空。"""
    p = _item_dir(it) / "qa.json"
    if not p.is_file():
        return []
    try:
        return _clean_quiz(json.loads(p.read_text("utf-8")))
    except ValueError:
        return []


QA_GEN = """任务：给一篇深读笔记出练习题。条目：{title}（{url}）。今天是 {today}。
深读笔记在 {out}（note.md / summary.md；有 src/ 是源码），先完整读笔记，需要核对时再读原文或源码。

{spec}
只写 {out}/qa.json，不要改其它文件、不要调用平台 API。写完后最终回复只说一句「已写好」。
"""


def _qa_gen_job(iid: int) -> dict | None:
    return db.row("SELECT id, status FROM jobs WHERE ref=? ORDER BY id DESC LIMIT 1", [f"learn:item:{iid}:qagen"])


@router.post("/items/{iid}/qa/generate")
def gen_qa(iid: int):
    """老笔记没有练习题（或要换一套）：后台让 Agent 读笔记出题，写进 qa.json。"""
    it = _item(iid)
    if it["status"] != "done":
        raise HTTPException(400, "笔记还没生成好")
    j = _qa_gen_job(iid)
    if j and j["status"] in ("queued", "running"):
        return {"job_id": j["id"], "status": "generating"}
    out = _item_dir(it)
    prompt = QA_GEN.format(title=it["title"] or it["url"], url=it["url"], today=db.today(), out=out, spec=QA_SPEC.format(out=out))
    jid = jobs.submit("learn", prompt, ref=f"learn:item:{iid}:qagen", cwd=str(out), add_dirs=[str(out)])
    return {"job_id": jid, "status": "generating"}


@router.get("/items/{iid}/qa")
def item_qa(iid: int):
    """追问清单：笔记里的问题 + 每题的作答与点评。笔记重新生成后问题变了，旧作答放进 earlier（不丢）。"""
    _ensure_depth_col()
    it = _item(iid)
    saved = _item_qa(it)
    quiz = item_quiz(it)
    if quiz:   # 练习题：选择题答过才给答案和解析
        qs = [{"q": q["q"], "type": q["type"], "dim": q.get("dim", ""), "section": q.get("section", ""),
               **({"options": q["options"]} if q["type"] == "choice" else {})} for q in quiz]
    else:      # 老笔记：追问清单里的开放题
        qs = [{"q": q} for q in qa_questions(_item_note(it))]
    shown = {str(n) for n, q in enumerate(qs, 1) if (saved.get(str(n)) or {}).get("q") == q["q"]}
    items = []
    for n, q in enumerate(qs, 1):
        c = {**q, "n": n, **({k: v for k, v in saved[str(n)].items() if k != "q"} if str(n) in shown else {})}
        if quiz and q["type"] == "choice" and "choice" in c:
            c.update(right=quiz[n - 1]["answer"], explain=quiz[n - 1]["explain"])
        items.append(c)
    earlier = sorted(({"n": int(k.split("@")[0]), **v} for k, v in saved.items() if k not in shown and v.get("answer")),
                     key=lambda v: v.get("at", ""))
    j = _qa_gen_job(iid)
    gen = None
    if j and j["status"] in ("queued", "running"):
        gen = {"status": "generating", "job_id": j["id"]}
    elif j and not quiz:
        gen = {"status": "failed", "job_id": j["id"]}
    return {"mode": "quiz" if quiz else "open", "gen": gen, "items": items, "earlier": earlier}


class QaIn(BaseModel):
    q: str
    answer: str = ""
    review: bool = False
    choice: int | None = None   # 选择题：选了第几个选项（从 0 开始），当场判对错


def qa_prompt(it: dict, c: dict) -> str:
    out = _item_dir(it)
    src = f"；源码在 {out / 'src'}" if (out / "src").is_dir() else ""
    return f"""任务：点评用户对一道「追问清单」问题的作答，帮他看清理解到哪、差在哪。今天是 {db.today()}。
条目：{it['title'] or it['url']}（{it['kind']}，{it['url']}）
深读笔记在 {out}（note.md / summary.md{src}），先读笔记里和这道题相关的部分；需要核对时再读原文或源码，不要凭印象。

问题：{c['q']}
用户的作答：{c['answer']}
{('出题时的参考要点：' + c['reference']) if c.get('reference') else ''}

追问清单的题大多是开放题（理解机制、质疑证据、迁移到自己的项目），没有唯一答案。
要求：短、具体、鼓励为主。看理解和判断：讲对了核心、给了理由或证据就算抓到；有道理的不同观点也算抓到。
只指出真正影响理解的缺口、事实错误或想偏处（对照笔记 / 原文 / 源码说明依据），细枝末节不提。
用户写「不知道 / 不确定」时不要批评，直接在 better 里把答案讲清楚。
better 写一个简洁的参考答案（3–6 句，结论 → 理由 / 机制 → 证据或例子），带出处（笔记小节、原文段落或 `文件:行号`）；
原文没有答案的开放题，说明这是推断，并给出怎么验证。
不要写文件、不要调用平台 API。最终回复只给一个 ```json 代码块：
{{"covered": ["抓到了什么，每条一句"], "missing": ["漏掉、讲错或想偏的关键点，每条一句，说清为什么重要"],
 "better": "参考答案（含出处）", "score": 0.0}}
covered、missing 各最多 3 条，每条 40 字以内。score 取 0–1，宽松给分：核心讲对且有理由 ≥ 0.7，方向对但缺理由或证据约 0.5，基本没答到才低于 0.3。
"""


@router.post("/items/{iid}/qa/{n}")
def save_qa(iid: int, n: int, body: QaIn):
    """保存一道追问的作答；review=true 时提交后台点评。作答和点评另记进学习记录（只追加）。"""
    _ensure_depth_col()
    it = _item(iid)
    qa = _item_qa(it)
    quiz = item_quiz(it)
    q = quiz[n - 1] if 0 < n <= len(quiz) and quiz[n - 1]["q"] == body.q else None
    if quiz and not q:
        raise HTTPException(409, "练习题已更新，刷新页面再答")
    if q and q["type"] == "choice":
        return _answer_choice(it, qa, n, q, body.choice)
    old = qa.get(str(n)) or {}
    if old.get("q") and old["q"] != body.q and old.get("answer"):   # 笔记重新生成后同一编号换了题：旧作答挪到别的键，不覆盖
        qa[f"{n}@{old.get('at', '')}"] = old
        old = {}
    answer = body.answer.strip()[:3000]
    c = {"q": body.q[:600], "answer": answer, "at": db.now(), "status": "answered" if answer else "empty"}
    if q:
        c["reference"] = "；".join(filter(None, [q.get("reference", ""), *q.get("rubric", [])]))[:800]
    if old.get("review") and old.get("answer") == answer:   # 答案没改，保留上次点评
        c.update(status=old.get("status", "reviewed"), review=old["review"])
    if body.review and answer:
        c["status"] = "reviewing"
        c.pop("review", None)
        c["job_id"] = jobs.submit("learn", qa_prompt(it, c), ref=f"learn:item:{iid}:qa:{n}", add_dirs=[str(_item_dir(it))])
    qa[str(n)] = c
    db.update("learn_items", iid, {"qa": qa})
    if answer and answer != old.get("answer"):
        log_event({}, "qa", {"item_id": iid, "title": it["title"] or it["url"], "n": n, "q": c["q"], "answer": answer})
    _reads.sync_task(iid)
    return c


def _answer_choice(it: dict, qa: dict, n: int, q: dict, choice: int | None) -> dict:
    """选择题当场判：答过就锁定（换题前不改），作答和对错记进学习记录。"""
    old = qa.get(str(n)) or {}
    if old.get("q") == q["q"] and "choice" in old:
        return {**old, "n": n, "right": q["answer"], "explain": q["explain"]}
    if choice is None or not 0 <= choice < len(q["options"]):
        raise HTTPException(400, "选一个选项")
    if old.get("answer"):   # 同一编号原来是别的题的作答：挪走，不覆盖
        qa[f"{n}@{old.get('at', '')}"] = old
    ok = choice == q["answer"]
    right = f"{'ABCDEFG'[q['answer']]}. {q['options'][q['answer']]}"
    c = {"q": q["q"], "type": "choice", "choice": choice, "answer": f"{'ABCDEFG'[choice]}. {q['options'][choice]}",
         "correct": ok, "at": db.now(), "status": "reviewed",
         "review": {"covered": [], "missing": [] if ok else [f"正确答案是 {right}"], "better": q["explain"], "score": 1.0 if ok else 0.0}}
    qa[str(n)] = c
    db.update("learn_items", it["id"], {"qa": qa})
    log_event({}, "qa_review", {"item_id": it["id"], "title": it["title"] or it["url"], "n": n, "q": q["q"],
                                "answer": c["answer"], "review": c["review"]})
    _reads.sync_task(it["id"])
    return {**c, "n": n, "right": q["answer"], "explain": q["explain"]}


def _finish_qa_gen(iid: int, job: dict) -> None:
    """出题任务结束：qa.json 不合格就删掉，页面显示出题失败、可重试。"""
    it = db.row("SELECT * FROM learn_items WHERE id=?", [iid])
    p = _item_dir(it) / "qa.json" if it else None
    if p and p.is_file() and not item_quiz(it):
        p.unlink()


def _finish_qa(iid: int, n: str, job: dict) -> None:
    it = db.row("SELECT * FROM learn_items WHERE id=?", [iid])
    if not it:
        return
    qa = _item_qa(it)
    c = qa.get(n)
    if not c or c.get("job_id") != job.get("id"):
        return  # 用户已改答案重新点评
    o = extract_json(job.get("output") or "", "missing") if job.get("status") == "done" else None
    if not o:
        c["status"] = "failed"
    else:
        lst = lambda k: [str(x) for x in o.get(k) or [] if x][:4]  # noqa: E731
        try:
            score = max(0.0, min(1.0, float(o.get("score") or 0)))
        except (TypeError, ValueError):
            score = 0.0
        c.update(status="reviewed", review={"covered": lst("covered"), "missing": lst("missing"),
                                            "better": str(o.get("better") or ""), "score": score})
        log_event({}, "qa_review", {"item_id": iid, "title": it["title"] or it["url"], "n": int(n), "q": c["q"],
                                    "answer": c["answer"], "review": c["review"]}, src=f"job:{job.get('id')}")
    qa[n] = c
    db.update("learn_items", iid, {"qa": qa})


def on_chat(ref: str, text: str) -> None:
    """对话里用户发了一句话（app/chat.py 调）：条目对话里的追问 / 感想推进当天的深读事项。"""
    if m := re.fullmatch(r"learn:item:(\d+)", ref or ""):
        _reads.sync_task(int(m.group(1)))


@router.post("/items/{iid}/rerun")
def rerun_item(iid: int, body: dict | None = None):
    _ensure_depth_col()
    it = _item(iid)
    upd = {}
    if body and body.get("focus") is not None:
        upd["focus"] = body["focus"]
    if body and body.get("depth") in ("quick", "full"):
        upd["depth"] = body["depth"]
    url, _ = normalize_target(it["url"])  # 旧数据里混进了说明文字的链接，顺手修正
    if url != it["url"]:
        upd["url"] = url
    if upd:
        db.update("learn_items", iid, upd)
        it = _item(iid)
    start_item_job(it)
    return _item(iid)


@router.delete("/items/{iid}")
def delete_item(iid: int):
    db.execute("DELETE FROM learn_items WHERE id=?", [iid])  # 输出文件保留在磁盘
    return {"ok": True}


@router.get("/items/{iid}/file")
def item_file(iid: int):
    """主产物：markdown 以文本返回，html 以文件返回。"""
    p = Path(_item(iid)["output_path"] or "")
    if not p.is_file():
        raise HTTPException(404, "output not ready")
    if p.suffix in (".md", ".markdown", ".txt"):
        return PlainTextResponse(p.read_text("utf-8", errors="replace"))
    return FileResponse(p)


@router.get("/items/{iid}/out/{path:path}")
def item_out(iid: int, path: str):
    """输出目录内任意文件（HTML 教程的相对资源也能加载）。"""
    base = _item_dir(_item(iid)).resolve()
    p = (base / path).resolve()
    if not p.is_relative_to(base) or not p.is_file():
        raise HTTPException(404)
    return FileResponse(p)


def _tldr_from_md(text: str) -> str:
    m = re.search(r"^#+\s*TL;?DR.*?\n(.*?)(?=^#|\Z)", text, re.S | re.M | re.I)
    if not m:
        return ""
    lines = [ln.strip().lstrip("-*0-9.、) ").strip() for ln in m.group(1).splitlines() if ln.strip()]
    return "\n".join(lines[:3])


def _finish_item(iid: int, job: dict) -> None:
    it = db.row("SELECT * FROM learn_items WHERE id=?", [iid])
    if not it:
        return
    out = _item_dir(it)
    meta = extract_json(job.get("output") or "", "tldr") or {}
    main = None
    if meta.get("output"):
        cand = Path(meta["output"])
        cand = cand if cand.is_absolute() else out / cand
        main = cand if cand.is_file() else None
    if not main:
        md_only = it["kind"] in ("paper", "article", "video") or (it.get("depth") or "quick") == "quick"
        names = ["note.md"] if md_only else ["index.html"]
        globs = ["*.md"] if md_only else ["*.html", "*.md"]
        found = [out / n for n in names if (out / n).is_file()]
        for g in globs:
            found += sorted(p for p in out.glob(g) if p.name != "summary.md")
        main = found[0] if found else None
    tldr = meta.get("tldr")
    summary = "\n".join(map(str, tldr[:3])) if isinstance(tldr, list) else str(tldr or "")
    if not summary:
        for p in (out / "summary.md", main):
            if p and p.is_file() and p.suffix == ".md":
                summary = _tldr_from_md(p.read_text("utf-8", errors="replace"))
                if summary:
                    break
    if not summary and job.get("output"):
        summary = "\n".join(job["output"].strip().splitlines()[:3])[:600]
    ok = job.get("status") == "done" and main is not None
    data = {"status": "done" if ok else "failed", "output_path": str(main or ""), "summary": summary,
            "updated_at": db.now()}
    if meta.get("title") and not it["title"]:
        data["title"] = str(meta["title"])[:200]
    elif not it["title"] and main is not None and main.suffix == ".md":
        data["title"] = _reads.md_title(main.read_text("utf-8", errors="replace"))
    db.update("learn_items", iid, data)
    _reads.sync_task(iid)


# ---------- A2. Deep Dive（GitHub 项目，按需生成） ----------

def deepdive_info(it: dict) -> dict:
    dd = _deepdive.dd_dir(_item_dir(it))
    md = dd / "deepdive.md"
    stage = it.get("dd_stage") or ""
    return {"status": it.get("dd_status") or "", "stage": stage, "job_id": it.get("dd_job"), "error": it.get("dd_error") or "",
            "stages": [{"key": k, "name": _deepdive.STAGE_NAMES[k]} for k in _deepdive.STAGES],
            "title": it.get("dd_title") or "", "at": it.get("dd_at") or "",
            "experiments": _loads(it.get("dd_experiments"), []), "ready": md.is_file(),
            "path": str(md) if md.is_file() else "",
            "review": _deepdive.review_scores(dd) if dd.is_dir() else {},
            "versions": sorted((p.name for p in dd.glob("deepdive.*.md") if p.name != "deepdive.draft.md"), reverse=True)
            if dd.is_dir() else []}


@router.get("/items/{iid}/deepdive")
def get_deepdive(iid: int):
    _ensure_depth_col()
    return deepdive_info(_item(iid))


def _submit_dd_stage(it: dict, stage: str) -> int:
    out = _item_dir(it)
    dd = _deepdive.dd_dir(out)
    jid = jobs.submit("learn", _deepdive.prompt(stage, it, out, _known_knowledge(it["id"])),
                      ref=f"learn:item:{it['id']}:deepdive:{stage}", cwd=str(dd), add_dirs=[str(out)], tier=_tier(f"deepdive_{stage}"))
    db.update("learn_items", it["id"], {"dd_status": "running", "dd_stage": stage, "dd_job": jid, "dd_error": "", "updated_at": db.now()})
    return jid


@router.post("/items/{iid}/deepdive")
def start_deepdive(iid: int, resume: bool = False):
    """点了才生成：理解 → 实验 → 写作 → 审稿四个阶段串行。正在生成时重复点只返回当前状态。
    resume：上次失败停在某个阶段时，从这个阶段接着跑（前面阶段的产物保留）；否则整篇重新生成，上一版留作历史。"""
    _ensure_depth_col()
    it = _item(iid)
    if it["kind"] != "github":
        raise HTTPException(400, "Deep Dive 目前只支持 GitHub 项目")
    if it.get("dd_status") == "running" and it.get("dd_job"):
        j = db.row("SELECT status FROM jobs WHERE id=?", [it["dd_job"]])
        if j and j["status"] in ("queued", "running"):
            return deepdive_info(it)
    stage = it.get("dd_stage") or ""
    if resume and it.get("dd_status") == "failed" and stage in _deepdive.STAGES:
        (_deepdive.dd_dir(_item_dir(it)) / "lab").mkdir(parents=True, exist_ok=True)
    else:
        _deepdive.prepare(_item_dir(it))
        stage = _deepdive.STAGES[0]
        db.update("learn_items", iid, {"dd_experiments": "[]"})
    _submit_dd_stage(it, stage)
    return deepdive_info(_item(iid))


@router.get("/items/{iid}/deepdive/file")
def deepdive_file(iid: int, version: str = ""):
    dd = _deepdive.dd_dir(_item_dir(_item(iid)))
    name = version if re.fullmatch(r"deepdive\.[\d-]+\.md", version or "") else "deepdive.md"
    p = dd / name
    if not p.is_file():
        raise HTTPException(404, "deep dive not ready")
    return PlainTextResponse(p.read_text("utf-8", errors="replace"))


def _finish_deepdive(iid: int, stage: str, job: dict) -> None:
    """一个阶段结束：校验这一阶段的产物，合格就提交下一阶段，最后一个阶段合格才算完成；不合格停在这个阶段等重试。"""
    _ensure_depth_col()
    it = db.row("SELECT * FROM learn_items WHERE id=?", [iid])
    if not it or it.get("dd_job") != job.get("id"):
        return  # 条目删了，或者已经换了一个新任务
    dd = _deepdive.dd_dir(_item_dir(it))
    stage = stage or _deepdive.STAGES[-1]   # 老的单阶段任务按最后一个阶段校验
    ok, reason = _deepdive.check_stage(stage, dd)
    if job.get("status") != "done":
        ok, reason = False, _deepdive.fail_reason(job)
    data = {"dd_error": "" if ok else f"「{_deepdive.STAGE_NAMES.get(stage, stage)}」阶段：{reason}",
            "dd_experiments": json.dumps(_deepdive.experiments(dd), ensure_ascii=False), "updated_at": db.now()}
    meta = extract_json(job.get("output") or "", "stage") or {}
    if meta.get("title"):
        data["dd_title"] = str(meta["title"])[:200]
    elif (dd / "deepdive.md").is_file():
        data["dd_title"] = _reads.md_title((dd / "deepdive.md").read_text("utf-8", errors="replace"))[:200]
    nxt = _deepdive.next_stage(stage) if ok else ""
    if not ok:
        data.update({"dd_status": "failed", "dd_at": db.now()})
    elif not nxt:
        data.update({"dd_status": "done", "dd_at": db.now()})
    db.update("learn_items", iid, data)
    if nxt:
        _submit_dd_stage(db.row("SELECT * FROM learn_items WHERE id=?", [iid]), nxt)


# ---------- B. 主题学习计划 ----------

class PlanIn(BaseModel):
    topic: str
    background: str = ""
    goal: str = ""
    hours_per_week: float = 5


class PlanPatch(BaseModel):
    topic: str | None = None
    background: str | None = None
    goal: str | None = None
    hours_per_week: float | None = None
    status: str | None = None
    overview_md: str | None = None


class StepIn(BaseModel):
    stage: int | None = None
    ord: int | None = None
    title: str | None = None
    goal: str | None = None
    description: str | None = None
    resources: list[dict] | None = None
    questions: list[str] | None = None
    est_hours: float | None = None
    status: str | None = None
    understanding: int | None = None
    feedback: str | None = None
    notes: str | None = None


def _plan(pid: int) -> dict:
    _ensure_plan_cols()
    p = db.row("SELECT * FROM learn_plans WHERE id=?", [pid])
    if not p:
        raise HTTPException(404, "plan not found")
    return p


def _decode_step(s: dict) -> dict:
    s["resources"] = _loads(s.get("resources"), [])
    s["questions"] = _loads(s.get("questions"), [])
    s["quiz"] = _loads(s.get("quiz"), [])
    s["cards"] = _loads(s.get("cards"), [])
    s["checks"] = _loads(s.get("checks"), {}) or {}
    s["quiz_result"] = _loads(s.get("quiz_result"), None)
    return s


_ANSWER_KEYS = ("answer", "explain", "reference", "rubric")


def public_step(s: dict) -> dict:
    """给页面的步骤：测试批改完之前不带答案 / 参考答案 / 评分要点。"""
    if (s.get("quiz_result") or {}).get("status") == "graded":
        return s
    return {**s, "quiz": [{k: v for k, v in q.items() if k not in _ANSWER_KEYS} for q in s.get("quiz") or []]}


def steps_of(pid: int) -> list[dict]:
    _ensure_step_cols()
    return [_decode_step(s) for s in db.rows("SELECT * FROM learn_steps WHERE plan_id=? ORDER BY stage, ord, id", [pid])]


def _step(sid: int) -> dict:
    _ensure_step_cols()
    s = db.row("SELECT * FROM learn_steps WHERE id=?", [sid])
    if not s:
        raise HTTPException(404, "step not found")
    return _decode_step(s)


def _progress(steps: list[dict]) -> dict:
    total = sum(1 for s in steps if s["status"] != "skipped")
    done = sum(1 for s in steps if s["status"] == "done")
    hours = sum(float(s["est_hours"] or 0) for s in steps if s["status"] != "skipped")
    return {"total": total, "done": done, "hours": round(hours, 1), "pct": round(100 * done / total) if total else 0}


def _clean_resources(rs) -> list[dict]:
    out = []
    for r in rs if isinstance(rs, list) else []:
        if isinstance(r, str):
            r = {"title": r, "url": r if r.startswith("http") else ""}
        if isinstance(r, dict) and (r.get("title") or r.get("url")):
            out.append({k: r[k] for k in ("title", "url", "type", "why", "verified", "date") if k in r})
    return out


def _step_fields(d: dict) -> dict:
    """把 Agent/用户给的步骤字段规整成可写入的列。"""
    out = {}
    if d.get("title") is not None:
        out["title"] = str(d["title"])[:300]
    if d.get("goal") is not None:
        out["goal"] = str(d["goal"])[:500]
    if d.get("description") is not None:
        out["description"] = str(d["description"])
    if d.get("resources") is not None:
        out["resources"] = _clean_resources(d["resources"])
    if d.get("questions") is not None:
        qs = d["questions"] if isinstance(d["questions"], list) else [d["questions"]]
        out["questions"] = [str(q) for q in qs if q]
    for k, conv in (("est_hours", float), ("stage", int), ("ord", int), ("understanding", int)):
        if d.get(k) is not None:
            try:
                out[k] = conv(d[k])
            except (TypeError, ValueError):
                pass
    if "stage" in out:  # 上限按计划结构在 add_step 里再收：三轮 3、老计划 6、课程按单元数
        out["stage"] = max(1, min(COURSE_MAX_UNITS, out["stage"]))
    if "understanding" in out:
        out["understanding"] = max(0, min(5, out["understanding"]))
    for k in ("feedback", "notes"):
        if d.get(k) is not None:
            out[k] = str(d[k])
    if d.get("status") in STEP_STATUS:
        out["status"] = d["status"]
        out["done_at"] = db.now() if d["status"] == "done" else ""
    return out


def _stage_max(pid: int) -> int:
    """stage 上限：三轮 3、老计划 6、课程按单元数。"""
    p = db.row("SELECT layout, units FROM learn_plans WHERE id=?", [pid]) or {}
    if p.get("layout") == "course":
        return max(1, len(layout_of(p)[0]))
    return len(ROUNDS) if p.get("layout") == "rounds" else len(STAGES)


def add_step(pid: int, d: dict, after_step_id: int | None = None) -> int:
    _ensure_step_cols()
    f = _step_fields(d)
    if not f.get("title"):
        raise HTTPException(400, "title required")
    f["stage"] = min(f.get("stage", 1), _stage_max(pid))
    after = db.row("SELECT * FROM learn_steps WHERE id=? AND plan_id=?", [after_step_id, pid]) if after_step_id else None
    if after:
        f["stage"], f["ord"] = after["stage"], after["ord"] + 1
        db.execute("UPDATE learn_steps SET ord=ord+1 WHERE plan_id=? AND stage=? AND ord>?", [pid, after["stage"], after["ord"]])
    elif "ord" not in f:
        m = db.row("SELECT MAX(ord) AS m FROM learn_steps WHERE plan_id=? AND stage=?", [pid, f["stage"]])
        f["ord"] = (m["m"] if m and m["m"] is not None else -1) + 1
    f["plan_id"] = pid
    return db.insert("learn_steps", f)


def parse_plan(text: str) -> tuple[str, list[dict]]:
    """解析生成计划的输出：支持 {overview_md, steps:[...]} 或 {stages:[{stage,name,steps:[...]}]}。"""
    o = extract_json(text, "steps") or extract_json(text, "stages")
    if not o:
        raise ValueError("未找到计划 JSON")
    steps = []
    for s in o.get("steps") or []:
        if isinstance(s, dict):
            steps.append(s)
    for i, st in enumerate(o.get("stages") or [], 1):
        if not isinstance(st, dict):
            continue
        no = st.get("stage") if isinstance(st.get("stage"), int) else i
        for s in st.get("steps") or []:
            if isinstance(s, dict):
                steps.append({**s, "stage": s.get("stage") or no})
    steps = [s for s in steps if s.get("title")]
    if not steps:
        raise ValueError("计划 JSON 中没有步骤")
    return str(o.get("overview_md") or o.get("overview") or ""), steps


def apply_plan(pid: int, text: str) -> int:
    overview, steps = parse_plan(text)
    db.execute("DELETE FROM learn_steps WHERE plan_id=?", [pid])
    for s in steps:
        add_step(pid, {k: v for k, v in s.items() if k not in ("status", "ord")})
    db.update("learn_plans", pid, {"overview_md": overview, "status": "active", "updated_at": db.now()})
    return len(steps)


def apply_edits(pid: int, text: str) -> dict:
    """应用调整 JSON：{summary, edits:[{op: add|modify|skip|add_resources, ...}]}。返回统计。"""
    o = extract_json(text, "edits")
    if not o:
        raise ValueError("未找到调整 JSON")
    stat = {"add": 0, "modify": 0, "skip": 0, "add_resources": 0, "ignored": 0}
    for e in o.get("edits") or []:
        if not isinstance(e, dict):
            continue
        op = e.get("op")
        sid = e.get("step_id")
        cur = db.row("SELECT * FROM learn_steps WHERE id=? AND plan_id=?", [sid, pid]) if sid else None
        try:
            if op == "add":
                add_step(pid, {k: v for k, v in e.items() if k not in ("op", "status", "after_step_id")},
                         e.get("after_step_id"))
            elif op == "modify" and cur and cur["status"] != "done":
                f = _step_fields({k: v for k, v in e.items() if k not in ("op", "step_id", "understanding", "feedback")})
                if "stage" in f:
                    f["stage"] = min(f["stage"], _stage_max(pid))
                if f:
                    db.update("learn_steps", sid, f)
            elif op == "skip" and cur and cur["status"] != "done":
                note = (cur["notes"] + "\n" if cur["notes"] else "") + f"[调整跳过] {e.get('reason', '')}".strip()
                db.update("learn_steps", sid, {"status": "skipped", "notes": note})
            elif op == "add_resources" and cur:
                rs = _loads(cur["resources"], []) + _clean_resources(e.get("resources"))
                db.update("learn_steps", sid, {"resources": rs})
            else:
                stat["ignored"] += 1
                continue
            stat[op] += 1
        except HTTPException:
            stat["ignored"] += 1
    plan = _plan(pid)
    log = f"\n\n## 调整记录 {db.today()}\n{o.get('summary') or ''}\n（新增 {stat['add']}，修改 {stat['modify']}，跳过 {stat['skip']}，补资源 {stat['add_resources']}）"
    db.update("learn_plans", pid, {"overview_md": (plan["overview_md"] or "") + log, "status": "active",
                                   "updated_at": db.now()})
    return stat


def _from_old_block(p: dict) -> str:
    """由老计划精简成三轮：交代已经学过什么、哪里薄弱，新计划跳过已会的、补薄弱处。"""
    if not p.get("from_plan") or not db.row("SELECT id FROM learn_plans WHERE id=?", [p["from_plan"]]):
        return ""
    return (f"\n- 这份计划由用户的老计划（六阶段、偏长）精简成三轮。老计划的进度、测试和反馈如下：已完成且测试过关的内容不要再排"
            f"（第 1 轮全貌可以一句话衔接）；薄弱处和反馈里没懂的地方要在新计划里补上；老计划里仍然有价值的资源可以沿用（先核对是否仍是最新）。\n"
            f"{_plan_snapshot(p['from_plan'])[:6000]}\n")


def plan_prompt(p: dict) -> str:
    return f"""任务：为下面的主题生成一份专业级、循序渐进的三轮学习计划。今天是 {db.today()}。
主题：{p['topic']}
我的背景：{p['background'] or '（未说明）'}
学习目标：{p['goal'] or '（未说明）'}
每周可投入：{p['hours_per_week']} 小时

要求：
- 第 1 轮全貌的写法参考 {Path(settings.get('learn.paper_skill', '')).expanduser().parent.parent / 'domain-landscape' / 'SKILL.md'}（如能读取）。
- 联网检索真实资源，尽量用 WebFetch/curl 核对链接可访问。全貌必须以最新的综述 / 书为主读物，前沿只用近 6–12 个月的材料，都写日期；
  项目实践选活跃的 GitHub 仓库（写 star 和最近提交），产品实践选真实可上手的对标产品 / 工具。{_from_old_block(p)}
- 用户已学过的内容（避免重复、可做衔接）：
{_known_knowledge(exclude_plan=p['id'])}
- 不要写任何文件，也不要调用平台 API 写数据；只在最终回复中给出 JSON（一个 ```json 代码块），平台会自动导入。

---- 方法论与 JSON 格式 ----
{_ref_text('plan.md')}
"""


def _adapt_layout(p: dict) -> str:
    if p.get("layout") == "course":
        return (f"课程计划（按课程的 {len(layout_of(p)[0])} 个单元组织，stage 填单元序号；步骤来自课程的讲次和作业，"
                "不要跳过或改写讲次本身，调整只加补课 / 补资源步骤、修改说明和资源）")
    return '三轮（stage 填 1–3）' if p.get('layout') == 'rounds' else '老计划的六阶段（stage 仍按六阶段填 1–6，见方法论末尾「老计划」）'


def adapt_prompt(p: dict, note: str = "") -> str:
    return f"""任务：根据我的学习进度和反馈，调整学习计划（主题：{p['topic']}）。今天是 {db.today()}。
计划结构：{_adapt_layout(p)}
{('我的补充说明：' + note) if note else ''}

当前计划与进度（step_id 用于 edits）：
{_plan_snapshot(p['id'])}

要求：只做有依据的少量修改；补救资源要真实（尽量核对链接）；不要修改已 done 的步骤；不要调用平台 API 写数据，
只在最终回复给出「根据反馈调整时输出的 JSON」（一个 ```json 代码块），平台会自动应用。

---- 方法论与 JSON 格式 ----
{_ref_text('plan.md')}
"""


def _plan_dirs() -> list[str]:
    return [str(_skill_dir("paper").parent / "domain-landscape"), str(SKILL_DIR)]


@router.get("/plans")
def list_plans():
    out = []
    for p in db.rows("SELECT * FROM learn_plans ORDER BY id DESC"):
        p["progress"] = _progress(steps_of(p["id"]))
        out.append(p)
    return out


@router.post("/plans")
def create_plan(body: PlanIn):
    if not body.topic.strip():
        raise HTTPException(400, "topic required")
    _ensure_plan_cols()
    pid = db.insert("learn_plans", {"topic": body.topic.strip(), "background": body.background, "goal": body.goal,
                                    "hours_per_week": body.hours_per_week, "status": "generating", "layout": "rounds",
                                    "created_at": db.now(), "updated_at": db.now()})
    jid = jobs.submit("learn", plan_prompt(_plan(pid)), ref=f"learn:plan:{pid}", add_dirs=_plan_dirs())
    db.update("learn_plans", pid, {"job_id": jid})
    return get_plan(pid)


@router.get("/plans/{pid}")
def get_plan(pid: int):
    p = _plan(pid)
    steps = steps_of(pid)
    p["progress"] = _progress(steps)
    p["steps"] = [public_step(s) for s in steps]
    p["stages"], p["stage_goals"], p["unit"] = layout_of(p)
    if p.get("from_plan"):
        p["from_topic"] = (db.row("SELECT topic FROM learn_plans WHERE id=?", [p["from_plan"]]) or {}).get("topic", "")
    p["rounds_plan"] = (db.row("SELECT id FROM learn_plans WHERE from_plan=? AND status!='failed' ORDER BY id DESC", [pid]) or {}).get("id")
    return p


@router.patch("/plans/{pid}")
def patch_plan(pid: int, body: PlanPatch):
    _plan(pid)
    data = {k: v for k, v in body.model_dump().items() if v is not None}
    data["updated_at"] = db.now()
    db.update("learn_plans", pid, data)
    return get_plan(pid)


@router.delete("/plans/{pid}")
def delete_plan(pid: int):
    db.execute("DELETE FROM learn_steps WHERE plan_id=?", [pid])
    db.execute("DELETE FROM learn_plans WHERE id=?", [pid])
    return {"ok": True}


@router.post("/plans/{pid}/regenerate")
def regenerate_plan(pid: int):
    p = _plan(pid)
    if p.get("layout") == "course":  # 课程计划不清空步骤（学习记录不能丢）：没有步骤就重新导入，有就同步课表
        _start_course_job(p, sync=bool(steps_of(pid)))
        return get_plan(pid)
    if p.get("layout") != "rounds":  # 重新生成会清空步骤，顺势换成三轮
        db.update("learn_plans", pid, {"layout": "rounds"})
        p = _plan(pid)
    jid = jobs.submit("learn", plan_prompt(p), ref=f"learn:plan:{pid}", add_dirs=_plan_dirs())
    db.update("learn_plans", pid, {"job_id": jid, "status": "generating", "updated_at": db.now()})
    return get_plan(pid)


@router.post("/plans/{pid}/rounds")
def plan_to_rounds(pid: int):
    """老计划精简成三轮：另生成一份新计划（跳过已学、补薄弱处），老计划原样保留，新计划生成成功后才归档老计划。"""
    old = _plan(pid)
    if old.get("layout") == "rounds":
        raise HTTPException(400, "已经是三轮计划")
    if old.get("layout") == "course":
        raise HTTPException(400, "课程计划按课程单元组织，不精简成三轮")
    if (cur := db.row("SELECT id FROM learn_plans WHERE from_plan=? AND status!='failed' ORDER BY id DESC", [pid])):
        return get_plan(cur["id"])
    nid = db.insert("learn_plans", {"topic": old["topic"], "background": old["background"], "goal": old["goal"],
                                    "hours_per_week": old["hours_per_week"], "status": "generating", "layout": "rounds",
                                    "from_plan": pid, "created_at": db.now(), "updated_at": db.now()})
    jid = jobs.submit("learn", plan_prompt(_plan(nid)), ref=f"learn:plan:{nid}", add_dirs=_plan_dirs())
    db.update("learn_plans", nid, {"job_id": jid})
    return get_plan(nid)


@router.post("/plans/{pid}/adapt")
def adapt_plan(pid: int, body: dict | None = None):
    p = _plan(pid)
    jid = jobs.submit("learn", adapt_prompt(p, (body or {}).get("note", "")), ref=f"learn:plan:{pid}:adapt",
                      add_dirs=_plan_dirs())
    db.update("learn_plans", pid, {"job_id": jid, "status": "adapting", "updated_at": db.now()})
    return get_plan(pid)


@router.post("/plans/{pid}/steps")
def create_step(pid: int, body: StepIn, after_step_id: int | None = None):
    _plan(pid)
    return public_step(_step(add_step(pid, body.model_dump(), after_step_id)))


@router.get("/steps/{sid}")
def get_step(sid: int):
    return public_step(_step(sid))


@router.patch("/steps/{sid}")
def patch_step(sid: int, body: StepIn):
    old = _step(sid)
    f = _step_fields(body.model_dump())
    if "stage" in f:
        f["stage"] = min(f["stage"], _stage_max(old["plan_id"]))
    if f:
        db.update("learn_steps", sid, f)
        changed = {k: f[k] for k in ("understanding", "feedback", "status", "notes") if k in f and f[k] != old.get(k)}
        if changed:
            log_event(old, "rating", {**changed, "prev": {k: old.get(k) for k in changed}})
    return public_step(_step(sid))


@router.delete("/steps/{sid}")
def delete_step(sid: int):
    db.execute("DELETE FROM learn_steps WHERE id=?", [sid])
    return {"ok": True}


@router.post("/steps/{sid}/today")
def step_to_today(sid: int, body: dict | None = None):
    """把步骤加入今日计划（tasks 表，kind=learning）。"""
    s = _step(sid)
    p = _plan(s["plan_id"])
    minutes = int((body or {}).get("est_minutes") or min(180, max(30, round(float(s["est_hours"] or 1) * 60))))
    goal = s["goal"] or ("能回答：" + "；".join(s["questions"][:3]) if s["questions"] else s["description"][:200])
    t = tasks.create({"title": f"[{p['topic']}] {s['title']}", "kind": "learning", "est_minutes": minutes,
                      "goal": goal, "notes": f"learn:plan:{p['id']} step:{sid}"})
    if s["status"] == "todo":
        db.update("learn_steps", sid, {"status": "doing"})
    return t


def _finish_plan(pid: int, job: dict, adapt: bool) -> None:
    if not db.row("SELECT id FROM learn_plans WHERE id=?", [pid]):
        return
    if job.get("status") != "done":
        db.update("learn_plans", pid, {"status": "active" if adapt else "failed", "updated_at": db.now()})
        return
    try:
        apply_edits(pid, job["output"]) if adapt else apply_plan(pid, job["output"])
        p = _plan(pid)
        if not adapt and p.get("from_plan") and (old := db.row("SELECT * FROM learn_plans WHERE id=?", [p["from_plan"]])) \
                and old["status"] != "archived":  # 精简版生成好了：老计划归档（步骤、测试、记录都留着）
            db.update("learn_plans", old["id"], {"status": "archived", "updated_at": db.now(),
                                                 "overview_md": (old["overview_md"] or "") + f"\n\n## 已精简成三轮 {db.today()}\n新计划：计划 {pid}（#learn/plan/{pid}）。这份老计划的进度和学习记录都保留。"})
    except ValueError as e:
        p = _plan(pid)
        db.update("learn_plans", pid, {"status": "active" if adapt else "failed", "updated_at": db.now(),
                                       "overview_md": (p["overview_md"] or "") + f"\n\n> 解析失败（job {job['id']}）：{e}"})


# ---------- 课程计划：导入名校课程（课表 → 单元 + 讲次 / 作业），每讲先整理素材包再写章节 ----------

FETCH_SCRIPT = ROOT / "scripts" / "course_fetch.py"


def _tier(task: str) -> str:
    """这类任务用哪档模型（设置 learn.task_tiers，如 course / material / grade → light）；空 = 板块默认。"""
    return str((settings.get("learn.task_tiers", {}) or {}).get(task) or "")


class CourseIn(BaseModel):
    url: str
    background: str = ""
    goal: str = ""
    hours_per_week: float = 6


def _course_steps_text(pid: int) -> str:
    lines = []
    for s in _ordered(steps_of(pid)):
        if s.get("origin"):
            continue
        urls = " ".join(r.get("url", "") for r in s["resources"] if r.get("url"))
        lines.append(f"- 单元 {s['stage']} [{s.get('step_kind') or 'lecture'}] {s['title']} {urls}")
    return "\n".join(lines) or "（无）"


def course_prompt(p: dict, sync: bool = False) -> str:
    out = _out_root() / "plans" / str(p["id"]) / "course"
    if sync:
        units = "\n".join(f"{i}. {n}" for i, n in layout_of(p)[0].items())
        head = f"""任务：同步课程「{p['topic']}」的课表，找出官网上新发布、计划里还没有的讲次和作业。今天是 {db.today()}。
课程官网：{p['source_url']}
计划里已有的单元：
{units or '（无）'}
计划里已有的步骤（标题 + 链接；这些不要再输出）：
{_course_steps_text(p['id'])}

只输出新增的步骤：能归入已有单元的，unit 填那个单元的名字（原样）；属于新主题的，在 units 里新建单元。没有新增就输出 {{"units": []}}。"""
    else:
        head = f"""任务：把一门大学课程导入成学习计划（课表 → 单元 + 步骤）。今天是 {db.today()}。
课程官网：{p['source_url']}
我的背景：{p['background'] or '（未说明）'}；学习目标：{p['goal'] or '（未说明）'}；每周可投入 {p['hours_per_week']} 小时"""
    return f"""{head}

做法：
1. 抓课表：运行 `python3 {FETCH_SCRIPT} {out} {p['source_url']}`，读输出目录里的 .txt（JS 渲染的课程站会附上从打包 JS 里抽出的课表数据）。
   课表里有作业页 / 讲义目录 / 录像播放列表链接时，同样用这个脚本抓（多个链接一次传入）；录像只有播放列表时，
   用 `python3 {FETCH_SCRIPT} --playlist <播放列表链接>` 列出每讲视频，按标题对上讲次。必要时用 WebFetch / curl 补查。
2. 只做整理，不写讲解内容；不要下载录像，不要抓每讲的课件正文（之后每讲单独整理）。
3. 不要写其他文件，不要调用平台 API 写数据。最终回复只给一个 ```json 代码块，平台会自动导入。

整理规则：
- 单元：按主题把相邻的 1–2 讲合成一个单元（客座讲座、复习课、期中展示等可以单独成单元或略过），单元名用中文，goal 写学完这个单元能做什么（可检验）。
- 步骤：每一讲是一个 lecture 步骤（title 用「第 N 讲 · 中文标题（英文原标题）」）；每个作业是一个 assignment 步骤，放在它考查的内容所在的单元末尾，
  title 用「作业 N · 中文标题」，description 写作业要做什么、交付物、截止日期（课表有就写）。
- resources 只放课表里真实存在的链接，原样保留，不要编造：课件（type=slides）、录像（type=video）、阅读材料（type=reading）、作业说明（type=assignment）、代码仓库（type=code）；
  有日期写 date（YYYY-MM-DD）。还没发布课件 / 录像的讲次也要列出，resources 留已知的部分。
- est_hours：一讲约 2–3 小时（看录像 + 读材料 + 测试），作业按课程说明的工作量估（常见 8–15 小时）。
- overview_md：课程简介（学校、学期、讲师、先修要求、评分构成、官网链接），3–8 行。

JSON 格式：
```json
{{"title": "课程中文名（课号，学校，学期）", "overview_md": "…",
  "units": [{{"name": "单元名", "goal": "学完能…",
             "steps": [{{"title": "…", "kind": "lecture", "goal": "学完能…", "description": "本讲讲什么、要点",
                        "resources": [{{"title": "Slides", "url": "https://…", "type": "slides", "date": "2026-04-01"}}],
                        "est_hours": 2.5}}]}}]}}
```
"""


def _start_course_job(p: dict, sync: bool = False) -> int:
    jid = jobs.submit("learn", course_prompt(p, sync), ref=f"learn:course:{p['id']}" + (":sync" if sync else ""),
                      add_dirs=[str(_out_root() / "plans" / str(p["id"]))], tier=_tier("course"))
    (_out_root() / "plans" / str(p["id"]) / "course").mkdir(parents=True, exist_ok=True)
    db.update("learn_plans", p["id"], {"job_id": jid, "status": "adapting" if sync else "generating", "updated_at": db.now()})
    return jid


@router.post("/courses")
def create_course(body: CourseIn):
    url = body.url.strip()
    if not re.match(r"https?://", url):
        raise HTTPException(400, "填课程官网链接（http/https）")
    _ensure_plan_cols()
    pid = db.insert("learn_plans", {"topic": url, "background": body.background, "goal": body.goal,
                                    "hours_per_week": body.hours_per_week, "status": "generating", "layout": "course",
                                    "source_url": url, "created_at": db.now(), "updated_at": db.now()})
    _start_course_job(_plan(pid))
    return get_plan(pid)


@router.post("/plans/{pid}/sync_course")
def sync_course(pid: int):
    """课程还在上（如本学期的课）：重新看一遍课表，只追加新发布的讲次 / 作业，已有步骤和学习记录不动。"""
    p = _plan(pid)
    if p.get("layout") != "course":
        raise HTTPException(400, "只有课程计划能同步课表")
    _start_course_job(p, sync=True)
    return get_plan(pid)


def _video_key(url: str) -> str:
    """同一个 YouTube 视频的不同写法（带播放列表 / index 参数、youtu.be 短链）归一成视频 id。"""
    m = re.search(r"(?:[?&]v=|youtu\.be/|youtube\.com/live/)([\w-]{11})", url or "")
    return m.group(1) if m else ""


def apply_course(pid: int, text: str, sync: bool = False) -> int:
    """导入 / 同步课表 JSON：单元按名字对上已有单元，没有就新建；已有的步骤（同标题或同链接）跳过。返回新增步骤数。"""
    o = extract_json(text, "units")
    if not isinstance(o, dict) or not isinstance(o.get("units"), list):
        raise ValueError("未找到课表 JSON")
    p = _plan(pid)
    units = [u for u in _loads(p.get("units"), []) if isinstance(u, dict)]
    have = steps_of(pid)
    titles = {s["title"].strip() for s in have}
    urls = {r.get("url") for s in have for r in s["resources"] if r.get("url")}
    videos = {_video_key(u) for u in urls} - {""}
    added = 0
    for u in o["units"]:
        if not isinstance(u, dict) or not str(u.get("name") or "").strip():
            continue
        name = str(u["name"]).strip()[:80]
        no = next((i for i, x in enumerate(units, 1) if x.get("name") == name), 0)
        steps = [s for s in u.get("steps") or [] if isinstance(s, dict) and str(s.get("title") or "").strip()]
        if not no:
            if not steps or len(units) >= COURSE_MAX_UNITS:
                continue
            units.append({"name": name, "goal": str(u.get("goal") or "")[:300]})
            no = len(units)
            db.update("learn_plans", pid, {"units": units})  # 先写单元，add_step 按单元数收 stage
        for s in steps:
            rs = _clean_resources(s.get("resources"))
            own = {r.get("url") for r in rs if r.get("url") and r.get("type") in ("slides", "video")}
            if s["title"].strip() in titles or (own and own <= urls):
                continue
            # 一个录像只属于一讲：模型偶尔把上一讲的录像挂到后面讲次上，后出现的去掉
            rs = [r for r in rs if _video_key(r.get("url")) not in videos]
            sid = add_step(pid, {"title": s["title"], "goal": s.get("goal") or "", "description": s.get("description") or "",
                                 "resources": rs, "est_hours": s.get("est_hours") or 2, "stage": no})
            db.update("learn_steps", sid, {"step_kind": "assignment" if s.get("kind") == "assignment" else "lecture"})
            titles.add(s["title"].strip())
            urls |= {r.get("url") for r in rs if r.get("url")}
            videos |= {_video_key(r.get("url")) for r in rs} - {""}
            added += 1
    data = {"units": units, "status": "active", "synced_at": db.now(), "updated_at": db.now()}
    if not sync:
        if not added:
            raise ValueError("课表 JSON 里没有步骤")
        data["topic"] = str(o.get("title") or p["topic"])[:200]
        data["overview_md"] = str(o.get("overview_md") or "")
    else:
        data["overview_md"] = (p["overview_md"] or "") + f"\n\n## 同步课表 {db.today()}\n新增 {added} 步。"
    db.update("learn_plans", pid, data)
    return added


def _finish_course(pid: int, job: dict, sync: bool) -> None:
    if not db.row("SELECT id FROM learn_plans WHERE id=?", [pid]):
        return
    if job.get("status") != "done":
        db.update("learn_plans", pid, {"status": "active" if sync else "failed", "updated_at": db.now()})
        return
    try:
        apply_course(pid, job.get("output") or "", sync)
    except ValueError as e:
        p = _plan(pid)
        db.update("learn_plans", pid, {"status": "active" if sync else "failed", "updated_at": db.now(),
                                       "overview_md": (p["overview_md"] or "") + f"\n\n> 课表解析失败（job {job['id']}）：{e}"})


def _is_course(s: dict) -> bool:
    return bool(s.get("step_kind")) and not s.get("origin")


def material_prompt(s: dict) -> str:
    p = _plan(s["plan_id"])
    out = _step_dir(s)
    urls = [r["url"] for r in s["resources"] if r.get("url")]
    res = "\n".join(f"- [{r.get('type', '')}] {r.get('title')} {r.get('url', '')}" for r in s["resources"]) or "（无）"
    kind = "作业" if s.get("step_kind") == "assignment" else "一讲"
    return f"""任务：把课程「{p['topic']}」的{kind}「{s['title']}」的原始材料整理成中文素材包，给后面写精讲章节的人用。只整理，不写教程。
本步说明：{s['description'] or '（无）'}
资源：
{res}

做法：
1. 运行 `python3 {FETCH_SCRIPT} {out / 'raw'} {' '.join(urls) if urls else '<链接>'}`
   （课件 / 作业 PDF → 带页码的文本，YouTube 录像 → 带时间戳的英文字幕，网页 → 正文；已抓过的会跳过）。读 raw/index.json 和各 .txt。
   某个链接失败（如字幕被限流）就跳过它，在素材包开头注明缺了什么；资源里没有课件但官网有的，可用同一脚本补抓。
2. 写 {out / 'material.md'}，结构：
   - `# 素材包：<标题>`，下一行写材料来源与缺失情况。
   - `## 逐页要点`：按课件页码（第 N 页）用中文概括每页要点，公式、图表含义写清楚；内容相近的连续几页可合并。作业则按说明文档的章节整理要求、接口、评分点。
   - `## 讲者补充`：录像里课件没有、讲者口头补充的解释、例子、经验判断、学生问答，每条带时间戳 [mm:ss]。没有录像就省略。
   - `## 术语表`：中英对照表（英文 | 中文 | 一句话解释）。
   - `## 阅读材料`：每篇 2–4 句中文摘要 + 和本讲的关系。
   - `## 关键原文`：最值得对照原文的英文句子 / 定义 / 公式 5–15 条，标出处（第 N 页 / [mm:ss]），原样摘录不翻译。
3. 忠实于材料，不要补充材料里没有的内容；不确定的标「（原文不清）」。不要写其他文件，不要调用平台 API。最终回复一句话说明写完了、缺了什么。
"""


def _course_block(s: dict) -> str:
    if not _is_course(s):
        return ""
    p = _plan(s["plan_id"])
    mat = _step_dir(s) / "material.md"
    lines = [f"\n---- 这是课程计划（{p['topic']}，官网 {p.get('source_url') or '—'}）的"
             + ("一项课程作业" if s.get("step_kind") == "assignment" else "一讲") + "，以下要求优先于下面「做法」第 1 步 ----"]
    if mat.is_file():
        lines.append(f"素材包：{mat}（已从课件、录像字幕、阅读材料整理好：逐页中文要点、讲者补充、术语表、关键原文）。以它为主要依据写，"
                     f"不要再下载课件或字幕；原始文本在 {mat.parent / 'raw'}，只在核对细节时查。")
    else:
        lines.append("素材包没整理成功：自己读资源原文（课件 PDF、讲义页、阅读材料），录像不看。")
    lines.append("写法：中文精讲，术语首次出现写「中文（English）」；不要逐页翻译课件，按讲者的思路重组讲透；"
                 "关键英文原文用 <details><summary>原文</summary>…</details> 折叠保留在对应段落后，标出处（课件第 N 页 / 录像 [mm:ss]）。")
    if s.get("step_kind") == "assignment":
        lines.append("这是作业，写成实践指导：要做什么和交付物、先要懂的概念（链到前面讲过的章）、拆成几个里程碑、每步的思路和常见坑、"
                     "可运行的自检清单（测试命令 / 预期输出）。不要写出作业的解答代码（只给接口说明和伪代码级思路）；"
                     "章末测试考理解和判断，不出要求写完整实现的题。")
    return "\n".join(lines) + "\n"


def start_material_job(s: dict, note: str = "", prefetch: bool = False) -> int:
    out = _step_dir(s)
    out.mkdir(parents=True, exist_ok=True)
    (out / ".chapter_note").write_text(note, "utf-8")  # 素材包整理完接着写章节时带上用户的要求
    jid = jobs.submit("learn", material_prompt(s), ref=f"learn:step:{s['id']}:material" + (":prefetch" if prefetch else ""),
                      cwd=str(out), tier=_tier("material"))
    db.update("learn_steps", s["id"], {"chapter_status": "generating", "chapter_job": jid,
                                       "material_status": "generating", "material_job": jid})
    return jid


def _finish_material(sid: int, job: dict, prefetch: bool) -> None:
    s = db.row("SELECT * FROM learn_steps WHERE id=?", [sid])
    if not s or s.get("chapter_job") not in (None, job.get("id")):
        return
    s = _decode_step(s)
    out = _step_dir(s)
    mat = out / "material.md"
    ok = job.get("status") == "done" and mat.is_file() and len(mat.read_text("utf-8", errors="replace")) > 300
    if not ok and mat.is_file():  # 写了一半的不缓存，下次重整
        mat.rename(out / f"material.failed-{job.get('id')}.md")
    db.update("learn_steps", sid, {"material_status": "ready" if ok else "failed"})
    nf = out / ".chapter_note"
    note = nf.read_text("utf-8") if nf.is_file() else ""
    _submit_chapter(_step(sid), note, prefetch)  # 素材包失败也照常写章节：章节提示里会让它自己读原文


# ---------- 学习记录 ----------

def log_event(s: dict, kind: str, data: dict, src: str = "", at: str = "") -> None:
    db.insert("learn_events", {"plan_id": s.get("plan_id"), "step_id": s.get("id"), "kind": kind, "data": data,
                               "src": src, "created_at": at or db.now()})


def events_of(step_id: int | None = None, plan_id: int | None = None, date: str = "") -> list[dict]:
    conds = [("step_id=?", step_id), ("plan_id=?", plan_id), ("substr(created_at,1,10)=?", date)]
    where, args = [c for c, v in conds if v], [v for _, v in conds if v]
    rows = db.rows("SELECT * FROM learn_events" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY created_at, id", args)
    for r in rows:
        r["data"] = _loads(r["data"], {})
    return rows


def event_line(e: dict, titles: dict | None = None) -> str:
    """一条学习记录的一行摘要（知识库、复盘、对话上下文共用）。"""
    d, t = e["data"], (titles or {}).get(e["step_id"], f"step {e['step_id']}")
    at = (e["created_at"] or "")[11:16]
    if e["kind"] == "quiz":
        dims = "、".join(f"{k}{v}" for k, v in (d.get("dims") or {}).items())
        weak = "；".join(d.get("weak_points") or [])[:200]
        return f"{at} 测试「{t}」第 {d.get('attempt', 1)} 次 {d.get('score', '?')} 分" + (f"（{dims}）" if dims else "") + (f"；薄弱：{weak}" if weak else "")
    if e["kind"] == "check_review":
        rv = d.get("review") or {}
        return (f"{at} 停一下「{d.get('q', '')[:40]}」我答：{d.get('answer', '')[:80]} → {round(100 * float(rv.get('score') or 0))}%"
                + (f"；漏：{'；'.join(rv.get('missing') or [])[:120]}" if rv.get("missing") else ""))
    if e["kind"] == "check":
        return f"{at} 停一下「{d.get('q', '')[:40]}」我答：{d.get('answer', '')[:80]}"
    if e["kind"] == "qa_review":
        rv = d.get("review") or {}
        return (f"{at} 追问「{d.get('title', '')[:30]}」{d.get('q', '')[:40]} 我答：{d.get('answer', '')[:80]} → {round(100 * float(rv.get('score') or 0))}%"
                + (f"；漏：{'；'.join(rv.get('missing') or [])[:120]}" if rv.get("missing") else ""))
    if e["kind"] == "qa":
        return f"{at} 追问「{d.get('title', '')[:30]}」{d.get('q', '')[:40]} 我答：{d.get('answer', '')[:80]}"
    if e["kind"] == "apply":
        return f"{at} 把「{t}」用到项目 {d.get('project', '')}：{d.get('what', '')[:120]}" + (f"（{d['evidence'][:80]}）" if d.get("evidence") else "")
    if e["kind"] == "rating":
        return f"{at} 「{t}」" + "，".join(f"{k}→{v}" for k, v in d.items() if k != "prev")[:200]
    if e["kind"] == "chapter":
        return f"{at} 「{t}」章节{d.get('action', '生成')}" + (f"（要求：{d['note']}）" if d.get("note") else "")
    return f"{at} {e['kind']}"


def backfill_events() -> dict:
    """从后台任务记录里补回学习记录（有学习记录表之前的作答、点评、测试批改）。按 job 去重，可重复执行。"""
    done = {r["src"] for r in db.rows("SELECT src FROM learn_events WHERE src LIKE 'job:%'")}
    stat = {"check_review": 0, "quiz": 0}
    graded = db.rows("SELECT id, ref FROM jobs WHERE ref LIKE 'learn:step:%:grade' AND status='done' ORDER BY id")
    latest_grade = {int(r["ref"].split(":")[2]): r["id"] for r in graded}
    for j in db.rows("SELECT * FROM jobs WHERE (ref LIKE 'learn:step:%:check:%' OR ref LIKE 'learn:step:%:grade') "
                     "AND status='done' ORDER BY id"):
        if f"job:{j['id']}" in done:
            continue
        sid = int(j["ref"].split(":")[2])
        s = db.row("SELECT * FROM learn_steps WHERE id=?", [sid])
        if not s:
            continue
        s = _decode_step(s)
        at, src, prompt = j["finished_at"] or j["created_at"], f"job:{j['id']}", j["prompt"] or ""
        if ":check:" in j["ref"]:
            m = re.search(r"问题：(.*?)\n要点（参考答案）：(.*?)\n用户的判断：(.*?)\n\n要求", prompt, re.S)
            o = extract_json(j["output"] or "", "missing")
            if not m or not o:
                continue
            log_event(s, "check_review", {"idx": int(j["ref"].split(":")[-1]), "q": m.group(1).strip(), "points": m.group(2).strip(),
                                          "answer": m.group(3).strip(), "review": o, "backfill": True}, src=src, at=at)
            stat["check_review"] += 1
        else:
            o = extract_json(j["output"] or "", "items")
            if not o:
                continue
            qs = {}
            for m in re.finditer(r"### (\w+)（[^\n]*）\n题目：(.*?)\n参考答案要点：(.*?)\n评分要点：(.*?)\n用户回答：(.*?)(?=\n\n###|\n\n评分：|\Z)", prompt, re.S):
                qs[m.group(1)] = {"q": m.group(2).strip(), "reference": m.group(3).strip(), "answer": m.group(5).strip()}
            wrong = re.search(r"选择题答错的：(.*)", prompt)
            last = (s["quiz_result"] or {}) if isinstance(s["quiz_result"], dict) else {}
            score = last.get("score", last.get("last_score")) if latest_grade.get(sid) == j["id"] else None
            items = {str(x.get("id")): {**qs.get(str(x.get("id")), {}), "score": x.get("score"), "feedback": x.get("feedback")}
                     for x in o.get("items") or [] if isinstance(x, dict)}
            log_event(s, "quiz", {"attempt": last.get("attempt") or 1, "score": score, "summary": o.get("summary", ""),
                                  "assessment": o.get("assessment") or {}, "weak_points": o.get("weak_points") or [],
                                  "advice": o.get("advice", ""), "items": items, "wrong_choices": (wrong.group(1).strip() if wrong else ""),
                                  "backfill": True}, src=src, at=at)
            stat["quiz"] += 1
    return stat


@router.post("/events/backfill")
def api_backfill():
    return backfill_events()


@router.get("/steps/{sid}/events")
def step_events(sid: int):
    _step(sid)
    return events_of(step_id=sid)


class ApplyIn(BaseModel):
    project: str = ""
    what: str
    evidence: str = ""  # commit / PR / 文档路径 / 会话链接


@router.post("/steps/{sid}/apply")
def record_apply(sid: int, body: ApplyIn):
    """记一次「把这章用到项目里」（只追加）：哪个项目、做了什么、证据。"""
    s = _step(sid)
    if not body.what.strip():
        raise HTTPException(400, "写一句做了什么")
    log_event(s, "apply", {"project": body.project.strip()[:120], "what": body.what.strip()[:1000], "evidence": body.evidence.strip()[:500]})
    return {"ok": True}


@router.get("/steps/{sid}/apply")
def apply_info(sid: int, date: str = ""):
    """今天把这章用到项目：给一段可直接贴进 Claude Code / Codex 的提示（带章名和章节路径，便于自动识别引用），和今天的应用记录 / 自动发现的引用。"""
    from . import _habits
    s = _step(sid)
    p = _plan(s["plan_id"])
    cards = "\n".join(f"- {c.get('front', '')}：{re.sub(r'<[^>]+>', '', str(c.get('back', '')))[:160]}" for c in s["cards"][:6])
    prompt = (f"我刚学完《{s['title']}》（学习计划「{p['topic']}」，章节全文：{_step_dir(s) / 'chapter.md'}）。\n"
              f"本章要点：\n{cards or '（见章节全文）'}\n\n"
              "请在当前项目里找一个今天就能做完的地方用上其中一条（比如给评估加一个二元评判、补一段错误分析、改一处设计），"
              "先说你选哪条、为什么适合这个项目，再动手；做完在总结里写明「应用了《" + s["title"] + "》的哪一条」。")
    date = date or db.today()
    st = next((x for x in _habits.apply_status(date)["learned"] if x["step_id"] == sid), None)
    manual = [e for e in events_of(step_id=sid) if e["kind"] == "apply"]
    return {"prompt": prompt, "terms": _habits.chapter_terms(s), "today": st,
            "records": [{"at": e["created_at"], **e["data"]} for e in manual]}


@router.get("/habits")
def habits(date: str = "", apply: bool = True):
    """学习习惯三项的达成情况：停一下平均分对目标、学完当天用到项目、每日论文笔记。"""
    from . import _habits
    return _habits.status(date or db.today(), with_apply=apply)


@router.get("/plans/{pid}/growth")
def plan_growth(pid: int):
    """成长档案：每章最近一次测试的分数和三个维度、各维度平均、最近的薄弱点和停一下漏掉的点。"""
    _plan(pid)
    steps = {s["id"]: s for s in steps_of(pid)}
    evs = events_of(plan_id=pid)
    latest: dict[int, dict] = {}
    for e in evs:
        if e["kind"] == "quiz":
            latest[e["step_id"]] = e
    chapters = [{"step_id": k, "title": steps.get(k, {}).get("title", ""), "score": e["data"].get("score"),
                 "dims": e["data"].get("dims") or {}, "attempt": e["data"].get("attempt"), "at": e["created_at"],
                 "assessment": e["data"].get("assessment") or {}} for k, e in latest.items()]
    dims = {}
    for d in DIMS:
        vals = [c["dims"][d] for c in chapters if d in c["dims"]]
        if vals:
            dims[d] = round(sum(vals) / len(vals))
    weak = []
    for e in reversed(evs):
        if e["kind"] == "quiz":
            weak += [{"text": w, "step_id": e["step_id"], "from": "测试", "at": e["created_at"]} for w in e["data"].get("weak_points") or []]
        elif e["kind"] == "check_review":
            weak += [{"text": w, "step_id": e["step_id"], "from": "停一下", "at": e["created_at"]}
                     for w in (e["data"].get("review") or {}).get("missing") or []][:1]
    checks = [e for e in evs if e["kind"] == "check_review"]
    ck = [float((e["data"].get("review") or {}).get("score") or 0) for e in checks]
    return {"chapters": chapters, "dims": dims, "weak": weak[:12], "counts": {
        "quiz": sum(e["kind"] == "quiz" for e in evs), "check": len(checks),
        "check_avg": round(100 * sum(ck) / len(ck)) if ck else None, "events": len(evs)},
        "checks": check_stats(checks), "titles": {k: v["title"] for k, v in steps.items()}}


def check_stats(reviews: list[dict], days: int = 7) -> dict:
    """停一下点评的统计：总平均、近 N 天平均（对照目标）、四栏各自平均和最弱的一栏（只算用了固定格式的作答）。"""
    sc = lambda e: float((e["data"].get("review") or {}).get("score") or 0)  # noqa: E731
    since = (date.fromisoformat(db.today()) - timedelta(days=days - 1)).isoformat()
    recent = [sc(e) for e in reviews if (e["created_at"] or "")[:10] >= since]
    parts: dict[str, list[float]] = {k: [] for k in CHECK_PARTS}
    for e in reviews:
        for k, v in ((e["data"].get("review") or {}).get("parts") or {}).items():
            if k in parts:
                parts[k].append(float(v))
    part_avg = {k: round(100 * sum(v) / len(v)) for k, v in parts.items() if v}
    avg = lambda xs: round(100 * sum(xs) / len(xs)) if xs else None  # noqa: E731
    return {"avg": avg([sc(e) for e in reviews]), "recent_avg": avg(recent), "recent_n": len(recent), "days": days,
            "target": CHECK_TARGET, "parts": part_avg, "weakest": min(part_avg, key=part_avg.get) if part_avg else ""}


# ---------- B2. 章节教程 + 章末测试 ----------

def _step_dir(s: dict) -> Path:
    return _out_root() / "plans" / str(s["plan_id"]) / f"step-{s['id']}"


def _ordered(steps: list[dict]) -> list[dict]:
    return sorted(steps, key=lambda x: (x["stage"], x["ord"], x["id"]))


def _checks_text(s: dict) -> str:
    out = []
    for k, c in sorted((s.get("checks") or {}).items(), key=lambda kv: int(kv[0]) if str(kv[0]).isdigit() else 0):
        if not c.get("answer"):
            continue
        rv = c.get("review") or {}
        out.append(f"- 问：{c['q'][:150]}\n  我答：{c['answer'][:300]}"
                   + (f"\n  漏掉：{'；'.join((rv.get('missing') or []) + (rv.get('off') or []))[:300]}" if rv else ""))
    return "\n".join(out)


def _quiz_line(s: dict) -> str:
    r = s.get("quiz_result") or {}
    if r.get("status") != "graded":
        return ""
    weak = "；".join(r.get("weak_points") or [])[:300]
    return f"测试 {r.get('score')} 分" + (f"，薄弱：{weak}" if weak else "")


def _recent_context() -> str:
    """用户最近在读 / 在做的东西：章末测试的「学以致用」题从这里取材。"""
    since = (date.fromisoformat(db.today()) - timedelta(days=14)).isoformat()
    out = []
    for i in db.rows("SELECT kind,title,url,summary FROM learn_items WHERE status='done' ORDER BY id DESC LIMIT 8"):
        first = (i["summary"] or "").splitlines()[0][:120] if i["summary"] else ""
        out.append(f"- [深读{'论文' if i['kind'] == 'paper' else '项目'}] {i['title'] or i['url']}：{first}")
    try:
        for r in db.rows("SELECT title,created_at FROM research_docs WHERE created_at>=? ORDER BY id DESC LIMIT 5", [since]):
            out.append(f"- [调研] {r['title']}（{r['created_at'][:10]}）")
    except Exception:  # noqa: BLE001  调研模块缺失时跳过
        pass
    for tk in db.rows("SELECT title,date FROM tasks WHERE parent_id IS NULL AND date>=? ORDER BY date DESC, id DESC LIMIT 8", [since]):
        out.append(f"- [事项 {tk['date']}] {tk['title'][:160]}")
    for repo in (settings.get("repos", []) or [])[:4]:
        try:
            log = subprocess.run(["git", "-C", repo, "log", f"--since={since}", "--no-merges", "--pretty=%s", "-6"],
                                 capture_output=True, text=True, timeout=5).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            log = ""
        if log:
            out.append(f"- [项目 {Path(repo).name}] 最近提交：" + "；".join(x[:60] for x in log.splitlines()))
    return "\n".join(out) or "（暂无记录）"


def _arch_block(p: dict, s: dict, steps: list[dict]) -> str:
    """计划的第一步（全貌章）必须画体系架构图，模块能点击跳到计划里讲它的那一章 / 本章小节。"""
    main = [x for x in steps if not x.get("origin") and x["status"] != "skipped"]
    if not main or main[0]["id"] != s["id"]:
        return ""
    lst = "\n".join(f"- step_id={x['id']} {stage_label(p, x['stage'])} ·「{x['title']}」" for x in main[1:])
    return (f"\n---- 本章是计划的第一步（全貌章）：必须画「## 体系架构图」（dg-arch 组件，见规范），放在资料时效之后 ----\n"
            f"架构图要能点击跳转：模块对应计划里后面某一步时加 data-step=\"<step_id>\"，对应本章某个小节时加 data-section=\"<小节标题>\"，"
            f"都不对应就不加（平台会让用户点它按需生成一节）。计划里后面的各步：\n{lst or '（无）'}\n")


def chapter_prompt(s: dict, note: str = "") -> str:
    p = _plan(s["plan_id"])
    steps = _ordered(steps_of(p["id"]))
    before = [x for x in steps if (x["stage"], x["ord"], x["id"]) < (s["stage"], s["ord"], s["id"]) and x["status"] != "skipped"]
    prev = "\n".join(f"- 第{i}章 [{x['status']}] {x['title']}" + (f"（{_quiz_line(x)}）" if _quiz_line(x) else "")
                     + (f"；反馈：{x['feedback'][:150]}" if x["feedback"] else "") for i, x in enumerate(before, 1)) or "（这是第一章）"
    res = "\n".join(f"- {r.get('title')} {r.get('url', '')}（{r.get('type', '')}{'，' + str(r['date']) if r.get('date') else ''}）：{r.get('why', '')}"
                    for r in s["resources"]) or "（计划未给资源，自己检索）"
    out = _step_dir(s)
    return f"""任务：把学习计划里的一步写成「跟着学」的一章教程 + 章末测试。今天是 {db.today()}。

计划主题：{p['topic']}
我的背景：{p['background'] or '（未说明）'}；学习目标：{p['goal'] or '（未说明）'}
本章所在：{stage_label(p, s['stage'], True)}

本章：{s['title']}
能力目标：{s['goal'] or '（计划未写，按阶段目的和下面的说明自己定一个具体、可检验的目标）'}
计划里的说明：
{s['description'] or '（无）'}
计划给的资源：
{res}
计划里的检查题（测试要能覆盖它们）：
{chr(10).join('- ' + q for q in s['questions']) or '（无）'}

前面各章（衔接用：不要重复讲已学的；测试暴露的薄弱处在本章相关地方顺带补上）：
{prev}

用户已学的其他内容（可做联系）：
{_known_knowledge(exclude_plan=p['id'], limit=10)}

用户最近在读 / 在做（章末测试至少 1 题从中挑和本章相关的论文或项目出题，学以致用）：
{_recent_context()}
{('用户对本章的要求：' + note) if note else ''}
{_extra_block(s)}{_course_block(s)}{_arch_block(p, s, steps)}
做法：
1. 先读资源原文（WebFetch / curl；arXiv 优先读 /html/ 或 /abs/ 页）。资源不够、打不开或已过时，联网补充真实资料；全貌、前沿章节（老计划的阶段 1、3、5）必须核对资料时效，优先用最新的综述 / 书 / 论文。
2. 按下面「章节教程」规范写两个文件（绝对路径，目录已创建）：
   - {out / 'chapter.md'}
   - {out / 'quiz.json'}（测试题 + 知识卡）
   - 需要交互小组件时：{out / 'widgets'}/<名字>.html（可选，最多 2 个）
   目录里的 history/ 是旧版本归档：不要读、不要沿用，按本次要求从头写。
3. 不要调用平台 API 写数据，不要写其他目录。最终回复只用一两句话说明写完了，以及资料时效结论。

---- 章节教程规范 ----
{_ref_text('chapter.md')}
"""


def _archive_chapter(s: dict) -> str:
    """重新生成前把旧章节（正文、测试、小组件）挪到 history/<时间>/，Agent 只能重写，学习记录里留着旧版路径。"""
    out = _step_dir(s)
    olds = [p for p in (out / "chapter.md", out / "quiz.json", out / "widgets") if p.exists()]
    if not olds:
        return ""
    dest = out / "history" / db.now().replace(":", "").replace("-", "")
    dest.mkdir(parents=True, exist_ok=True)
    for p in olds:
        p.rename(dest / p.name)
    return str(dest)


def _extra_block(s: dict) -> str:
    """按需加的一节：交代用户要什么、从哪一章来、那一章里他哪里卡住了。"""
    if s.get("origin") not in EXTRA:
        return ""
    par = db.row("SELECT * FROM learn_steps WHERE id=?", [s.get("parent_id")]) if s.get("parent_id") else None
    par = _decode_step(par) if par else None
    lines = [f"\n---- 这是用户按需加的一节（{EXTRA[s['origin']]}），按「章节教程规范」末尾「按需加的一节」写，篇幅和题量按那里的要求 ----",
             f"用户的要求：{s.get('request') or s['title']}"]
    if par:
        lines.append(f"来自哪一章：「{par['title']}」（正文 {_step_dir(par) / 'chapter.md'}，先读它，不要重复它已经讲清的部分）")
        if s["origin"] == "confused":
            r = par.get("quiz_result") or {}
            wrong = [f"{q['q'][:120]}（用户答：{str((r.get('answers') or {}).get(q['id']))[:150]}；{(r['items'][q['id']].get('feedback') or '')[:150]}）"
                     for q in par["quiz"] if r.get("status") == "graded" and (r["items"].get(q["id"]) or {}).get("score", 1) < 1]
            if _quiz_line(par):
                lines.append(f"那一章的{_quiz_line(par)}" + (f"；建议：{r['advice'][:200]}" if r.get("advice") else ""))
            if wrong:
                lines.append("答错 / 没答全的题：\n" + "\n".join("- " + w for w in wrong[:4]))
            if _checks_text(par):
                lines.append("「停一下」里用户写的判断：\n" + _checks_text(par)[:1500])
            if par.get("feedback"):
                lines.append(f"用户对那一章的反馈：{par['feedback'][:300]}")
    return "\n".join(lines) + "\n"


def create_extra(sid: int, kind: str, request: str, quote: str = "") -> dict:
    """在第 sid 章后面插一节按需讲解（同一章加的多节按加的先后排），并开始生成。同样的要求已有就直接返回那一节。"""
    par = _step(sid)
    if kind not in EXTRA:
        raise HTTPException(400, "kind 只能是 interest / confused")
    request, quote = request.strip()[:500], quote.strip()[:1500]
    if not request and not quote:
        raise HTTPException(400, "写下感兴趣的子方向，或哪里没懂")
    full = (request + (f"\n划线原文：{quote}" if quote else "")).strip()
    root = par["parent_id"] or sid  # 在按需加的一节里再加，挂到原章下面
    for x in steps_of(par["plan_id"]):
        if x["parent_id"] == root and x["origin"] == kind and x["request"] == full and x["chapter_status"] != "failed":
            return x
    kids = [x for x in _ordered(steps_of(par["plan_id"])) if x["parent_id"] == root]
    anchor = kids[-1]["id"] if kids else root
    label = request or quote
    label = label if len(label) <= 30 else label[:30] + "…"
    nid = add_step(par["plan_id"], {"title": f"{EXTRA[kind]}：{label}", "est_hours": 1 if kind == "interest" else 0.5,
                                    "goal": "", "description": ""}, anchor)
    db.update("learn_steps", nid, {"origin": kind, "parent_id": root, "request": full})
    s = _step(nid)
    start_chapter_job(s)
    return _step(nid)


def start_chapter_job(s: dict, note: str = "", prefetch: bool = False) -> int:
    out = _step_dir(s)
    out.mkdir(parents=True, exist_ok=True)
    archived = _archive_chapter(s)
    if archived or note:
        log_event(s, "chapter", {"action": "重新生成" if archived else "生成", "note": note, "archived": archived,
                                 "old_score": (s.get("quiz_result") or {}).get("score") if isinstance(s.get("quiz_result"), dict) else None})
    if _is_course(s) and not (out / "material.md").is_file():  # 课程的一讲：先整理素材包（缓存，整理过就不再整理）
        return start_material_job(s, note, prefetch)
    return _submit_chapter(s, note, prefetch)


def _submit_chapter(s: dict, note: str = "", prefetch: bool = False) -> int:
    jid = jobs.submit("learn", chapter_prompt(s, note), ref=f"learn:step:{s['id']}:{'prefetch' if prefetch else 'chapter'}",
                      cwd=str(_step_dir(s)), add_dirs=[str(SKILL_DIR)], tier=_tier("chapter"))
    db.update("learn_steps", s["id"], {"chapter_status": "generating", "chapter_job": jid})
    return jid


def _prefetch_next(s: dict) -> int | None:
    """用户在读第 N 章时，后台准备第 N+1 章；同一计划已有章节在生成就不再加。"""
    steps = _ordered(steps_of(s["plan_id"]))
    if any(x["chapter_status"] == "generating" for x in steps):
        return None
    after = [x for x in steps if (x["stage"], x["ord"], x["id"]) > (s["stage"], s["ord"], s["id"])
             and x["status"] not in ("done", "skipped")]
    if after and not after[0]["chapter_status"]:
        return start_chapter_job(after[0], prefetch=True)
    return None


def _dim(q: dict) -> str:
    d = str(q.get("dim") or "")
    if d in DIMS:
        return d
    sk = str(q.get("skill") or "") + d
    return "应用" if re.search(r"应用|迁移|实践", sk) else "判断" if re.search(r"判断|证据|评估|预测", sk) else "理解"


def _clean_quiz(o, max_q: int = 6, max_short: int = 2) -> list[dict]:
    qs = o.get("questions") if isinstance(o, dict) else o
    out = []
    for i, q in enumerate(qs if isinstance(qs, list) else [], 1):
        if not isinstance(q, dict) or not str(q.get("q") or "").strip():
            continue
        item = {"id": str(q.get("id") or f"q{i}"), "type": "choice" if q.get("type") == "choice" else "short",
                "q": str(q["q"]), "dim": _dim(q), "about": str(q.get("about") or ""), "section": str(q.get("section") or "")}
        if item["type"] == "choice":
            opts = [str(x) for x in q.get("options") or []]
            try:
                ans = int(q.get("answer"))
            except (TypeError, ValueError):
                ans = -1
            if len(opts) < 2 or not 0 <= ans < len(opts):
                continue
            item.update(options=opts, answer=ans, explain=str(q.get("explain") or ""))
        else:
            rub = q.get("rubric") or []
            item.update(reference=str(q.get("reference") or ""), rubric=[str(x) for x in (rub if isinstance(rub, list) else [rub])])
        out.append(item)
    # 题少而精：章节最多 2 道手写题、总共不超过 6 题；按需加的一节 1 道、3 题（多出来的丢掉，按出题顺序保留）
    shorts = [q for q in out if q["type"] == "short"][:max_short]
    out = [q for q in out if q["type"] == "choice" or q in shorts][:max_q]
    ids = [q["id"] for q in out]
    if len(set(ids)) != len(ids):  # id 重复就重新编号
        for i, q in enumerate(out, 1):
            q["id"] = f"q{i}"
    return out


def _clean_cards(o) -> list[dict]:
    cs = o.get("cards") if isinstance(o, dict) else None
    out = []
    for c in cs if isinstance(cs, list) else []:
        if isinstance(c, dict) and str(c.get("front") or "").strip() and str(c.get("back") or "").strip():
            out.append({"front": str(c["front"])[:300], "back": str(c["back"])[:1200], "tag": str(c.get("tag") or "")[:20]})
    return out[:30]


def _with_glossary(text: str, mat: Path) -> str:
    """课程章节末尾接上素材包的术语表：Haiku 已整理好，直接拿来，不让写章节的模型再抄一遍（省输出 token）。"""
    if re.search(r"(?m)^##\s*术语表", text) or not mat.is_file():
        return text
    m = re.search(r"(?ms)^##\s*术语表.*?(?=^##\s|\Z)", mat.read_text("utf-8", errors="replace"))
    return f"{text}\n\n{m.group(0).strip()}\n" if m else text


def _finish_chapter(sid: int, job: dict) -> None:
    s = db.row("SELECT * FROM learn_steps WHERE id=?", [sid])
    if not s or s.get("chapter_job") not in (None, job.get("id")):
        return  # 已被更新的一次生成取代
    out = _step_dir(s)
    chap = out / "chapter.md"
    text = chap.read_text("utf-8", errors="replace").strip() if chap.is_file() else ""
    if text and _is_course(s):
        text = _with_glossary(text, out / "material.md")
    qo = {}
    qf = out / "quiz.json"
    if qf.is_file():
        qo = _loads(qf.read_text("utf-8", errors="replace"), {})
    if not _clean_quiz(qo):
        qo = extract_json(job.get("output") or "", "questions") or {}
    quiz, cards = _clean_quiz(qo, *((3, 1) if s.get("origin") in EXTRA else ())), _clean_cards(qo)
    ok = job.get("status") == "done" and len(text) > 200
    data = {"chapter_status": "ready" if ok else "failed"}
    if ok:
        data.update(chapter_md=text, quiz=quiz, cards=cards, checks={})  # 章节变了，「停一下」作答按序号对不上，清掉
        if s.get("origin") in EXTRA and isinstance(qo, dict):  # 按需加的一节：标题和目标由 Agent 读完原章后定
            if str(qo.get("title") or "").strip():
                data["title"] = f"{EXTRA[s['origin']]}：{str(qo['title']).strip()[:60]}"
            if str(qo.get("goal") or "").strip() and not s.get("goal"):
                data["goal"] = str(qo["goal"]).strip()[:500]
        old = _loads(s.get("quiz_result"), None)
        if old:  # 重新生成后题目变了：旧答卷作废，只留上次分数
            data["quiz_result"] = {"attempt": old.get("attempt", 0), "last_score": old.get("score", old.get("last_score"))}
    db.update("learn_steps", sid, data)


def _finalize_quiz(sid: int, r: dict) -> dict:
    """汇总分数 → 理解度；及格自动完成这一步。"""
    s = _step(sid)
    items = r.get("items") or {}
    n = len(s["quiz"]) or 1
    score = round(100 * sum(float((items.get(q["id"]) or {}).get("score") or 0) for q in s["quiz"]) / n)
    dims = {}
    for d in DIMS:
        qs = [q for q in s["quiz"] if q.get("dim", "理解") == d]
        if qs:
            dims[d] = round(100 * sum(float((items.get(q["id"]) or {}).get("score") or 0) for q in qs) / len(qs))
    r.update(score=score, dims=dims, status="graded", graded_at=db.now(), passed=score >= PASS_SCORE)
    log_event(s, "quiz", {k: r.get(k) for k in ("attempt", "score", "dims", "passed", "summary", "assessment", "weak_points",
                                                  "advice", "answers", "items")} | {"questions": s["quiz"]},
              src=f"job:{r['job_id']}" if r.get("job_id") else "")
    upd = {"quiz_result": r, "understanding": max(1, min(5, round(score / 20)))}
    if score >= PASS_SCORE and s["status"] != "done":
        upd.update(status="done", done_at=db.now())
    elif s["status"] == "todo":
        upd["status"] = "doing"
    db.update("learn_steps", sid, upd)
    return r


def grade_prompt(s: dict, r: dict) -> str:
    p = _plan(s["plan_id"])
    qs = [q for q in s["quiz"] if q["type"] == "short" and str(r["answers"].get(q["id"]) or "").strip()]
    body = "\n\n".join(f"### {q['id']}（维度：{q.get('dim') or '理解'}；对应小节：{q['section'] or '-'}"
                        + (f"；关联：{q['about']}" if q.get("about") else "") + f"）\n题目：{q['q']}\n"
                        f"参考答案要点：{q['reference']}\n评分要点：" + "；".join(q["rubric"]) + f"\n用户回答：{r['answers'][q['id']]}"
                        for q in qs)
    wrong = "；".join(f"{q['id']}（{q.get('dim') or ''}·{q['section']}）" for q in s["quiz"]
                      if q["type"] == "choice" and not (r["items"].get(q["id"]) or {}).get("score"))
    return f"""任务：批改学习测试里的简答题，像一位鼓励为主、看重理解和判断的导师。今天是 {db.today()}。
计划：{p['topic']}；本章：{stage_label(p, s['stage'])} ·「{s['title']}」
{stage_label(p, s['stage'], True).split(' —— ')[1]}
（本章正文在 {_step_dir(s) / 'chapter.md'}，需要时可读。）
选择题答错的：{wrong or '无'}

{body}

评分：每题 score 取 0 / 0.25 / 0.5 / 0.75 / 1。核心是检查理解和判断力，不要逐字逐句对评分要点：
- 核心判断对、理由大体成立 → 0.75–1（表述不同、举了别的例子、只缺次要细节都不扣成 0.5）；
- 方向对但依据薄弱或缺一个关键点 → 0.5；只复述概念、没有自己的判断 → 0.25；答非所问或明显错误 → 0。
拿不准时往高给一档，别打击积极性。
feedback 写 2–3 句：先说哪里对，再说最值得补的一点，最后一句高手会怎么想（判断类题目点出代表人物的推理路径）。
不要写文件、不要调用平台 API。最终回复只给一个 ```json 代码块：
{{"items": [{{"id": "q2", "score": 0.5, "feedback": "..."}}], "summary": "一两句总体评价",
 "assessment": {{"理解": "对这个方向的理解到什么程度（一句）", "判断": "判断力如何、离一线的人差在哪（一句）", "应用": "能否用到自己的论文/项目上（一句）"}},
 "weak_points": ["薄弱点（具体到概念/能力）"], "advice": "下一步怎么补：回看哪一节、做什么练习"}}
assessment 结合全部题目（包括选择题对错）来写，评价的是人对这个方向的整体能力，不是逐题复述。
"""


class QuizIn(BaseModel):
    answers: dict[str, str | int | None] = {}


@router.post("/steps/{sid}/open")
def open_chapter(sid: int, body: dict | None = None):
    """进入某一章：没有章节就开始生成（force 重新生成），同时后台预生成下一章。"""
    s = _step(sid)
    note, force = (body or {}).get("note", ""), bool((body or {}).get("force"))
    if force or s["chapter_status"] in ("", "failed"):
        start_chapter_job(s, note)
    elif s["chapter_status"] == "ready":
        _prefetch_next(s)
    return public_step(_step(sid))


class ExtraIn(BaseModel):
    kind: str = "interest"   # interest 感兴趣，往深处讲 / confused 没懂，换个讲法
    request: str = ""
    quote: str = ""          # 划线的原文（可选）


@router.post("/steps/{sid}/extra")
def add_extra(sid: int, body: ExtraIn):
    """按需加一节：在这一章后面插一节针对性讲解 + 小测试，立即生成。"""
    return public_step(create_extra(sid, body.kind, body.request, body.quote))


@router.get("/steps/{sid}/out/{path:path}")
def step_out(sid: int, path: str):
    """章节目录里的文件（嵌入的交互小组件 widgets/*.html 等）。
    HTML 是 Agent 写的脚本：响应头强制沙箱（不同源、不能调平台 API），直接在新窗口打开也一样。"""
    base = _step_dir(_step(sid)).resolve()
    p = (base / path).resolve()
    if not p.is_relative_to(base) or not p.is_file():
        raise HTTPException(404)
    headers = {"Content-Security-Policy": "sandbox allow-scripts"} if p.suffix.lower() in (".html", ".htm") else None
    return FileResponse(p, headers=headers)


@router.post("/steps/{sid}/quiz")
def submit_quiz(sid: int, body: QuizIn):
    """交卷：选择题当场判，简答题交给后台 Agent 批改（status=grading，完成后自动汇总）。"""
    s = _step(sid)
    if not s["quiz"]:
        raise HTTPException(400, "这一章还没有测试")
    if (s["quiz_result"] or {}).get("status") == "grading":
        raise HTTPException(409, "正在批改")
    answers = {q["id"]: body.answers.get(q["id"]) for q in s["quiz"]}
    items = {}
    for q in s["quiz"]:
        a = answers[q["id"]]
        if a is None or str(a).strip() == "":
            items[q["id"]] = {"score": 0, "feedback": "未作答"}
        elif q["type"] == "choice":
            try:
                ok = int(a) == q["answer"]
            except (TypeError, ValueError):
                ok = False
            items[q["id"]] = {"score": 1 if ok else 0, "feedback": q.get("explain", "")}
    r = {"answers": answers, "items": items, "submitted_at": db.now(),
         "attempt": int((s["quiz_result"] or {}).get("attempt") or 0) + 1}
    if any(q["id"] not in items for q in s["quiz"]):
        r["status"] = "grading"
        db.update("learn_steps", sid, {"quiz_result": r})
        r["job_id"] = jobs.submit("learn", grade_prompt(s, r), ref=f"learn:step:{sid}:grade", add_dirs=[str(_step_dir(s))],
                                    tier=_tier("grade"))
        db.update("learn_steps", sid, {"quiz_result": r})
    else:
        _finalize_quiz(sid, r)
    return public_step(_step(sid))


class CheckIn(BaseModel):
    q: str
    points: str = ""
    answer: str = ""
    parts: dict[str, str] = {}  # 固定格式的四栏，键见 CHECK_PARTS；answer 是拼好的全文
    review: bool = False


# 「停一下」固定作答格式：结论 + 为什么（机制）+ 一个例子 + 在我项目里怎么用（2026-10-31：丢分最多的是缺机制和缺例子）
CHECK_PARTS = {"结论": "一句话下判断", "机制": "为什么成立：背后的因果 / 机制", "例子": "一个具体例子或数字",
               "应用": "在我的项目里怎么用"}
CHECK_TARGET = 65  # 停一下平均分目标（%）


def check_answer(parts: dict) -> str:
    """四栏拼成一段作答全文（存档、点评、复盘都看它）。"""
    return "\n".join(f"{k}：{str(parts.get(k) or '').strip()}" for k in CHECK_PARTS if str(parts.get(k) or "").strip())


def check_prompt(s: dict, c: dict) -> str:
    p = _plan(s["plan_id"])
    return f"""任务：对照「停一下」的要点，点评用户自己写下的判断，帮他看清差距、提升判断力。今天是 {db.today()}。
计划：{p['topic']}；本章：{stage_label(p, s['stage'])} ·「{s['title']}」
{stage_label(p, s['stage'], True).split(' —— ')[1]}
（本章正文在 {_step_dir(s) / 'chapter.md'}，需要时可读。）

问题：{c['q']}
要点（参考答案）：{c['points'] or '（未提供，按本章内容判断）'}
用户的判断：{c['answer']}

用户按固定格式作答：结论（一句话判断）/ 机制（为什么成立）/ 例子（一个具体例子或数字）/ 应用（在他自己的项目里怎么用）。
某一栏没写就当这一栏缺。

要求：短、具体、鼓励为主，不要逐字逐句对要点。看的是理解和判断力：意思对、抓住了核心判断就算抓到，换了说法、举了别的例子都算；
要点之外说得有道理的也算抓到（要点不是唯一答案）。只指出真正影响理解的缺口或想偏处，细枝末节不提。
机制和例子是这类作答最常丢分的两项：机制没讲因果（只有结论）、例子空泛（没有具体对象或数字）时要在 missing 里点明，并在 better 里示范补上。
不要写文件、不要调用平台 API。最终回复只给一个 ```json 代码块：
{{"covered": ["抓到了什么（含要点之外有道理的），每条一句"], "missing": ["漏掉或想偏的关键点，每条一句，说清为什么重要"],
 "better": "高手会怎么想：一两句示范推理路径（结论 → 机制 → 例子）",
 "parts": {{"结论": 0.0, "机制": 0.0, "例子": 0.0, "应用": 0.0}}, "score": 0.0}}
covered、missing 各最多 3 条，每条一句话、40 字以内（展开的道理放进 better）。
parts 每栏 0–1：结论 = 判断对不对；机制 = 因果讲没讲清；例子 = 有没有具体、贴切的例子；应用 = 落到项目里是否具体可做（空着给 0）。
score 取 0–1，宽松给分：核心判断对了且讲了机制就 ≥ 0.7，判断对但缺机制或例子约 0.5，基本没抓住才低于 0.3。
"""


@router.post("/steps/{sid}/checks/{idx}")
def save_check(sid: int, idx: int, body: CheckIn):
    """保存一个「停一下」的作答；review=true 时提交后台点评（对照要点看差异）。"""
    s = _step(sid)
    checks = s["checks"]
    parts = {k: str(body.parts.get(k) or "").strip()[:1500] for k in CHECK_PARTS if str(body.parts.get(k) or "").strip()}
    answer = (check_answer(parts) if parts else body.answer)[:3000]
    c = {"q": body.q[:600], "points": body.points[:3000], "answer": answer, "at": db.now(),
         "status": "answered" if answer.strip() else "viewed"}
    if parts:
        c["parts"] = parts
    old = checks.get(str(idx)) or {}
    if old.get("review") and old.get("answer") == c["answer"]:  # 答案没改，保留上次点评
        c.update(status=old.get("status", "reviewed"), review=old["review"])
    if body.review and answer.strip():
        c["status"] = "reviewing"
        c.pop("review", None)
        c["job_id"] = jobs.submit("learn", check_prompt(s, c), ref=f"learn:step:{sid}:check:{idx}",
                                  add_dirs=[str(_step_dir(s))])
    checks[str(idx)] = c
    db.update("learn_steps", sid, {"checks": checks})
    if c["answer"].strip() and c["answer"] != old.get("answer"):
        log_event(s, "check", {"idx": idx, "q": c["q"], "points": c["points"], "answer": c["answer"], "parts": parts})
    return c


def _finish_check(sid: int, idx: str, job: dict) -> None:
    s = db.row("SELECT * FROM learn_steps WHERE id=?", [sid])
    if not s:
        return
    checks = _loads(s.get("checks"), {}) or {}
    c = checks.get(idx)
    if not c or c.get("job_id") != job.get("id"):
        return  # 用户已改答案重新点评
    o = extract_json(job.get("output") or "", "missing") if job.get("status") == "done" else None
    if not o:
        c["status"] = "failed"
    else:
        lst = lambda k: [str(x) for x in o.get(k) or [] if x][:6]  # noqa: E731
        try:
            score = max(0.0, min(1.0, float(o.get("score") or 0)))
        except (TypeError, ValueError):
            score = 0.0
        # 两项：抓到了（含要点外的合理补充）/ 漏掉了（含想偏的）；模型仍按老格式给 off / extra 时并进去
        c.update(status="reviewed", review={"covered": (lst("covered") + lst("extra"))[:4], "missing": (lst("missing") + lst("off"))[:4],
                                            "better": str(o.get("better") or ""), "score": score, "parts": _part_scores(o.get("parts"))})
        log_event(s, "check_review", {"idx": int(idx), "q": c["q"], "points": c.get("points", ""), "answer": c["answer"],
                                      "review": c["review"]}, src=f"job:{job.get('id')}")
    checks[idx] = c
    db.update("learn_steps", sid, {"checks": checks})


def _part_scores(v) -> dict:
    """点评给的四栏分数（0–1）；老点评没有就是空。"""
    out = {}
    for k in CHECK_PARTS:
        try:
            out[k] = max(0.0, min(1.0, float((v or {}).get(k))))
        except (TypeError, ValueError, AttributeError):
            pass
    return out


def _finish_grade(sid: int, job: dict) -> None:
    s = db.row("SELECT * FROM learn_steps WHERE id=?", [sid])
    if not s:
        return
    s = _decode_step(s)
    r = s["quiz_result"] or {}
    if r.get("status") != "grading" or r.get("job_id") not in (None, job.get("id")):
        return
    o = extract_json(job.get("output") or "", "items") if job.get("status") == "done" else None
    if not o:
        r["status"] = "failed"
        db.update("learn_steps", sid, {"quiz_result": r})
        return
    graded = {str(x.get("id")): x for x in o.get("items") or [] if isinstance(x, dict)}
    for q in s["quiz"]:
        if q["id"] in r["items"]:
            continue
        g = graded.get(q["id"]) or {}
        try:
            sc = max(0.0, min(1.0, float(g.get("score") or 0)))
        except (TypeError, ValueError):
            sc = 0.0
        r["items"][q["id"]] = {"score": sc, "feedback": str(g.get("feedback") or "（未批改）")}
    asm = o.get("assessment") if isinstance(o.get("assessment"), dict) else {}
    r["assessment"] = {d: str(asm[d])[:300] for d in DIMS if asm.get(d)}
    r.update(summary=str(o.get("summary") or ""), advice=str(o.get("advice") or ""),
             weak_points=[str(x) for x in o.get("weak_points") or []][:6])
    _finalize_quiz(sid, r)


@router.post("/steps/{sid}/quiz/reset")
def reset_quiz(sid: int):
    """重做测试（保留上次的分数在 last_score）。"""
    s = _step(sid)
    last = s["quiz_result"] or {}
    db.update("learn_steps", sid, {"quiz_result": {"attempt": last.get("attempt", 0), "last_score": last.get("score", last.get("last_score"))}
                                   if last else ""})
    return public_step(_step(sid))


def on_job_done(job: dict) -> None:
    ref = job.get("ref") or ""
    if m := re.fullmatch(r"learn:item:(\d+)", ref):
        _finish_item(int(m.group(1)), job)
    elif m := re.fullmatch(r"learn:item:(\d+):deepdive(?::(\w+))?", ref):
        _finish_deepdive(int(m.group(1)), m.group(2) or "", job)
    elif m := re.fullmatch(r"learn:plan:(\d+)(:adapt)?", ref):
        _finish_plan(int(m.group(1)), job, bool(m.group(2)))
    elif m := re.fullmatch(r"learn:course:(\d+)(:sync)?", ref):
        _finish_course(int(m.group(1)), job, bool(m.group(2)))
    elif m := re.fullmatch(r"learn:step:(\d+):material(:prefetch)?", ref):
        _finish_material(int(m.group(1)), job, bool(m.group(2)))
    elif m := re.fullmatch(r"learn:step:(\d+):(chapter|prefetch)", ref):
        _finish_chapter(int(m.group(1)), job)
    elif m := re.fullmatch(r"learn:step:(\d+):grade", ref):
        _finish_grade(int(m.group(1)), job)
    elif m := re.fullmatch(r"learn:step:(\d+):check:(\d+)", ref):
        _finish_check(int(m.group(1)), m.group(2), job)
    elif m := re.fullmatch(r"learn:item:(\d+):qa:(\d+)", ref):
        _finish_qa(int(m.group(1)), m.group(2), job)
    elif m := re.fullmatch(r"learn:item:(\d+):qagen", ref):
        _finish_qa_gen(int(m.group(1)), job)


# ---------- C. 对话上下文 ----------

def _plan_snapshot(pid: int) -> str:
    p = _plan(pid)
    steps = steps_of(pid)
    pr = _progress(steps)
    lines = [f"计划 {pid}：{p['topic']}（状态 {p['status']}，进度 {pr['done']}/{pr['total']}，{pr['hours']}h）",
             f"背景：{p['background']}；目标：{p['goal']}；每周 {p['hours_per_week']}h", ""]
    names, goals, unit = layout_of(p)
    for stage, name in names.items():
        ss = [s for s in steps if s["stage"] == stage]
        if not ss:
            continue
        lines.append(f"### {stage_label(p, stage)}（目的：{goals[stage]}）")
        for s in ss:
            chap = {"ready": "章节已生成", "generating": "章节生成中", "failed": "章节生成失败"}.get(s["chapter_status"], "")
            extra = f"按需{EXTRA[s['origin']]}（源自 step_id={s['parent_id']}）" if s.get("origin") in EXTRA else ""
            lines.append(f"- step_id={s['id']} [{s['status']}] 理解度{s['understanding']}/5 · {s['title']}（{s['est_hours']}h）"
                         + "".join(f"；{x}" for x in (extra, chap, _quiz_line(s)) if x))
            if s["goal"]:
                lines.append(f"  能力目标：{s['goal'][:200]}")
            if s["feedback"]:
                lines.append(f"  反馈：{s['feedback'][:300]}")
            if s["notes"]:
                lines.append(f"  笔记：{s['notes'][:200]}")
            if s["resources"]:
                lines.append("  资源：" + "；".join(f"{r.get('title')} {r.get('url', '')}" for r in s["resources"][:6]))
    return "\n".join(lines)


def agent_context(ref: str) -> str:
    api = f"{agent.API_BASE}/api/learn"
    if m := re.fullmatch(r"learn:item:(\d+)", ref or ""):
        it = db.row("SELECT * FROM learn_items WHERE id=?", [int(m.group(1))])
        if not it:
            return "条目不存在"
        out = _item_dir(it)
        body = ""
        for p in (out / "summary.md", Path(it["output_path"] or "")):
            if p.is_file() and p.suffix == ".md":
                body = p.read_text("utf-8", errors="replace")[:8000]
                break
        dd = _deepdive.dd_dir(out)
        dd_line = (f"Deep Dive（含真实跑过的实验，问到实验 / 机制细节时先读它）：{dd / 'deepdive.md'}，实验原样输出在 {dd / 'lab'}\n"
                   if (dd / "deepdive.md").is_file() else "")
        return (f"正在追问条目 {it['id']}（{it['kind']}）：{it['title'] or it['url']}\n来源：{it['url']}\n"
                f"状态：{it['status']}；产物：{it['output_path'] or '无'}（目录 {out}，可用 Read 读取全文）\n{dd_line}"
                f"TL;DR：{it['summary']}\n我的笔记：{it['my_notes'] or '无'}；评分：{it['rating']}/5\n"
                f"用户在这里说的话会作为「追问与感想」进复盘和知识库；他写下感想时，帮他把感想说准、和文档里的论据对上，不要只附和。\n"
                f"更新笔记：curl -s -X PATCH {api}/items/{it['id']} -H 'Content-Type: application/json' -d '{{\"my_notes\":\"...\"}}'\n\n"
                f"### 产物摘录\n{body or '（HTML 产物，请直接读取文件）'}\n\n"
                + (("### 用户在追问清单里的作答\n" + "\n".join(
                    f"- {v.get('q', '')[:120]} → 我答：{v['answer'][:300]}"
                    + (f"（点评 {round(100 * float(v['review'].get('score') or 0))}%，漏：{'；'.join(v['review'].get('missing') or [])[:160]}）" if v.get("review") else "")
                    for v in _reads.qa_answers(it)) + "\n\n") if _reads.qa_answers(it) else "")
                + f"### 用户已学其他内容\n{_known_knowledge(it['id'], 10)}")
    if m := re.fullmatch(r"learn:step:(\d+)", ref or ""):
        s = db.row("SELECT * FROM learn_steps WHERE id=?", [int(m.group(1))])
        if not s:
            return "章节不存在"
        s = _decode_step(s)
        r = s["quiz_result"] or {}
        quiz = "\n".join(f"- {q['id']} [{q['type']}] {q['q']}" + (f" → 得分 {r['items'][q['id']]['score']}；用户答：{str(r['answers'].get(q['id']))[:200]}"
                                                                  if r.get("status") == "graded" and q["id"] in r.get("items", {}) else "")
                         for q in s["quiz"])
        sp = db.row("SELECT * FROM learn_plans WHERE id=?", [s["plan_id"]])
        return (f"用户正在读计划 {s['plan_id']} 的一章（step_id={s['id']}）：{stage_label(sp, s['stage'])} ·「{s['title']}」\n"
                f"{stage_label(sp, s['stage'], True).split(' —— ')[1]}\n能力目标：{s['goal'] or '（未写）'}\n"
                f"章节文件：{_step_dir(s) / 'chapter.md'}（下方是摘录，需要时 Read 全文）；测试：{_step_dir(s) / 'quiz.json'}\n"
                f"测试结果：{_quiz_line(s) or r.get('status') or '未做'}" + (f"；建议：{r.get('advice')}" if r.get("advice") else "")
                + f"\n回答时围绕本章目标，用户答错的题优先帮他想通；不要直接改写章节，除非用户要求（重新生成：POST {api}/steps/{s['id']}/open -d '{{\"force\":true,\"note\":\"...\"}}'）。"
                + f"\n用户想系统地深入某个子方向、或某处需要从头讲透并测一测时，可以按需加一节（插在本章后，自动生成讲解 + 小测试）："
                f"curl -s -X POST {api}/steps/{s['id']}/extra -H 'Content-Type: application/json' -d '{{\"kind\":\"interest 或 confused\",\"request\":\"子方向 / 没懂的地方\"}}'，"
                f"加之前先问用户要不要；简单问题直接在对话里答。\n\n"
                f"### 学习记录（历次作答 / 测试 / 点评）\n{chr(10).join(event_line(e, {s['id']: s['title']}) for e in events_of(step_id=s['id'])[-30:]) or '（无）'}\n\n"
                f"### 「停一下」作答\n{_checks_text(s) or '（无）'}\n\n### 章末测试\n{quiz or '（无）'}\n\n### 章节摘录\n{(s['chapter_md'] or '（未生成）')[:12000]}\n\n### 计划概况\n{_plan_snapshot(s['plan_id'])[:4000]}")
    if m := re.fullmatch(r"learn:plan:(\d+)", ref or ""):
        pid = int(m.group(1))
        if not db.row("SELECT id FROM learn_plans WHERE id=?", [pid]):
            return "计划不存在"
        return (_plan_snapshot(pid) + f"\n\n修改步骤：PATCH {api}/steps/<step_id>；新增：POST {api}/plans/{pid}/steps"
                f"（可加 ?after_step_id=）；删除：DELETE {api}/steps/<step_id>；加入今日：POST {api}/steps/<step_id>/today")
    items = db.rows("SELECT id,kind,title,url,status,rating FROM learn_items ORDER BY id DESC LIMIT 20")
    plans = list_plans()[:10]
    return ("### 深读条目\n" + ("\n".join(f"- 条目{i['id']} [{i['kind']}/{i['status']}] {i['title'] or i['url']} 评分{i['rating']}"
                                          for i in items) or "（无）")
            + "\n\n### 学习计划\n" + ("\n".join(f"- 计划{p['id']} {p['topic']} [{p['status']}] 进度 {p['progress']['done']}/{p['progress']['total']}"
                                              for p in plans) or "（无）"))


def agent_dirs(ref: str) -> list[str]:
    dirs = [str(_skill_dir("paper")), str(_skill_dir("github")), str(_skill_dir("paper").parent / "domain-landscape"),
            str(SKILL_DIR), str(_out_root())]  # 章节在 _out_root()/plans/ 下
    return dirs
