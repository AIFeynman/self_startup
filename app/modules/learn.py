"""深度学习：A. 单篇论文 / GitHub 项目深读；B. 主题学习计划（分阶段步骤 + 反馈调整）。

后台 job 的 ref 约定：
    learn:item:<id>          条目深读
    learn:plan:<id>          生成学习计划
    learn:plan:<id>:adapt    根据反馈调整计划
    learn:step:<id>:chapter  把计划的一步写成章节教程 + 章末测试（:prefetch = 用户读上一章时后台预生成）
    learn:step:<id>:grade    批改章末测试的简答题
    learn:step:<id>:check:<n> 点评第 n 个「停一下」：用户的判断和要点差在哪
对话 ref：learn:item:<id> / learn:plan:<id> / learn:step:<id>（读某一章时）/ 空（总览）。
"""
from __future__ import annotations

import json
import re
import subprocess
from datetime import date, timedelta
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel

from .. import agent, db, jobs, settings, tasks
from ..db import ROOT

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
    updated_at     TEXT
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
    quiz_result   TEXT DEFAULT ''             -- JSON {answers,items:{qid:{score,feedback}},score,status:grading|graded|failed,...}
);
CREATE INDEX IF NOT EXISTS idx_learn_steps_plan ON learn_steps(plan_id);
-- 学习记录：只追加、不覆盖（作答、Agent 点评、每次测试连同当时的题目、理解度 / 反馈变化、章节重新生成），用于复盘和成长评价
CREATE TABLE IF NOT EXISTS learn_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id     INTEGER,
    step_id     INTEGER,
    kind        TEXT NOT NULL,              -- check 作答 / check_review 点评 / quiz 测试 / rating 理解度·反馈·状态 / chapter 章节生成
    data        TEXT DEFAULT '{}',
    src         TEXT DEFAULT '',            -- 来源：job:<id> / backfill
    created_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_learn_events_step ON learn_events(step_id);
"""

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
             "cards": "TEXT DEFAULT '[]'", "checks": "TEXT DEFAULT '{}'"}
SKILL_DIR = ROOT / "skills" / "learn"
STEP_STATUS = ("todo", "doing", "done", "skipped")
router = APIRouter()


# ---------- 工具函数 ----------

def detect_kind(url: str) -> str:
    u = url.strip().lower()
    if re.search(r"(arxiv\.org|doi\.org|openreview\.net|\.pdf$|^10\.\d{4,9}/)", u):
        return "paper"
    if "github.com" in u or re.fullmatch(r"[a-z0-9][\w.-]*/[\w.-]+", u):
        return "github"
    p = Path(url.strip()).expanduser()
    if p.is_dir():
        return "github"  # 本地 checkout
    return "paper"  # arxiv / pdf / doi / openreview / 其他论文链接


def slugify(url: str) -> str:
    u = url.strip().rstrip("/")
    if m := re.search(r"(10\.\d{4,9}/\S+)", u):
        s = "doi-" + m.group(1)
    elif m := re.search(r"arxiv\.org/\w+/(\d{4}\.\d{4,5})", u) or re.fullmatch(r"(\d{4}\.\d{4,5})(v\d+)?", u):
        s = f"arxiv-{m.group(1)}"
    elif m := re.search(r"github\.com/([^/]+)/([^/#?]+)", u) or re.fullmatch(r"([\w.-]+)/([\w.-]+)", u):
        s = f"{m.group(1)}-{m.group(2).removesuffix('.git')}"
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


def _ensure_step_cols() -> None:
    """老库补上章节 / 测试列。"""
    cols = {r["name"] for r in db.rows("PRAGMA table_info(learn_steps)")}
    for k, decl in STEP_COLS.items():
        if k not in cols:
            db.execute(f"ALTER TABLE learn_steps ADD COLUMN {k} {decl}")


def _ensure_depth_col() -> None:
    cols = {r["name"] for r in db.rows("PRAGMA table_info(learn_items)")}
    if "depth" not in cols:
        db.execute("ALTER TABLE learn_items ADD COLUMN depth TEXT DEFAULT 'quick'")


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
- `git clone --depth 1` 到 {out}/src（已存在就直接用）。只读 README、包清单/入口文件和最关键的 10–20 个文件；不安装依赖、不运行代码、不写生成器或 HTML。
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
5 个可以直接复制到对话里的问题。

完成后，最终回复末尾附一个 ```json 代码块：
{{"title": "项目名 · 一句话", "tldr": ["第1行", "第2行", "第3行"], "output": "note.md"}}
"""


def item_prompt(it: dict, out: Path) -> str:
    kind = it["kind"]
    if kind == "github" and (it.get("depth") or "quick") == "quick":
        return QUICK_GITHUB.format(url=it["url"], focus=("用户关注点：" + it["focus"]) if it["focus"] else "",
                                   out=out, known=_known_knowledge(it["id"]))
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

{'若仓库主要是文档 / 书籍 / 教程（大部分是 .md）而非代码，不要硬套代码架构讲解：改为「阅读指南」式 HTML，包括全书结构、每章一句话、概念关系图、推荐阅读顺序和最值得读的章节，不写实验脚本。' if kind == 'github' else ''}

---- 本平台增补 ----
{_ref_text(kind + '.md')}
"""


def start_item_job(it: dict) -> int:
    out = _item_dir(it)
    out.mkdir(parents=True, exist_ok=True)
    jid = jobs.submit("learn", item_prompt(it, out), ref=f"learn:item:{it['id']}", cwd=str(out),
                      add_dirs=[str(_skill_dir(it["kind"])), str(SKILL_DIR)])
    db.update("learn_items", it["id"], {"job_id": jid, "status": "running", "updated_at": db.now()})
    return jid


@router.get("/items")
def list_items():
    return db.rows("SELECT * FROM learn_items ORDER BY id DESC")


@router.post("/items")
def create_item(body: ItemIn):
    _ensure_depth_col()
    url, extra = normalize_target(body.url)
    if not url:
        raise HTTPException(400, "url required")
    kind = body.kind if body.kind in ("paper", "github") else detect_kind(url)
    depth = body.depth if body.depth in ("quick", "full") else ("quick" if kind == "github" else "full")
    focus = "；".join(x for x in (body.focus.strip(), extra) if x)
    iid = db.insert("learn_items", {"kind": kind, "url": url, "focus": focus, "depth": depth, "status": "queued",
                                    "created_at": db.now(), "updated_at": db.now()})
    start_item_job(_item(iid))
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
    return _item(iid)


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
        quick = it["kind"] == "github" and (it.get("depth") or "quick") == "quick"
        names = ["note.md"] if it["kind"] == "paper" or quick else ["index.html"]
        globs = ["*.md"] if it["kind"] == "paper" or quick else ["*.html", "*.md"]
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
    db.update("learn_items", iid, data)


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
    if "stage" in out:
        out["stage"] = max(1, min(6, out["stage"]))
    if "understanding" in out:
        out["understanding"] = max(0, min(5, out["understanding"]))
    for k in ("feedback", "notes"):
        if d.get(k) is not None:
            out[k] = str(d[k])
    if d.get("status") in STEP_STATUS:
        out["status"] = d["status"]
        out["done_at"] = db.now() if d["status"] == "done" else ""
    return out


def add_step(pid: int, d: dict, after_step_id: int | None = None) -> int:
    _ensure_step_cols()
    f = _step_fields(d)
    if not f.get("title"):
        raise HTTPException(400, "title required")
    f.setdefault("stage", 1)
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


def plan_prompt(p: dict) -> str:
    return f"""任务：为下面的主题生成一份专业级、可交互的学习计划。今天是 {db.today()}。
主题：{p['topic']}
我的背景：{p['background'] or '（未说明）'}
学习目标：{p['goal'] or '（未说明）'}
每周可投入：{p['hours_per_week']} 小时

要求：
- 阶段 1 的写法参考 {Path(settings.get('learn.paper_skill', '')).expanduser().parent.parent / 'domain-landscape' / 'SKILL.md'}（如能读取）。
- 联网检索真实资源，尽量用 WebFetch/curl 核对链接可访问；前沿进展写明日期。
- 用户已学过的内容（避免重复、可做衔接）：
{_known_knowledge(exclude_plan=p['id'])}
- 不要写任何文件，也不要调用平台 API 写数据；只在最终回复中给出 JSON（一个 ```json 代码块），平台会自动导入。

---- 方法论与 JSON 格式 ----
{_ref_text('plan.md')}
"""


def adapt_prompt(p: dict, note: str = "") -> str:
    return f"""任务：根据我的学习进度和反馈，调整学习计划（主题：{p['topic']}）。今天是 {db.today()}。
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
    pid = db.insert("learn_plans", {"topic": body.topic.strip(), "background": body.background, "goal": body.goal,
                                    "hours_per_week": body.hours_per_week, "status": "generating",
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
    p["stages"] = STAGES
    p["stage_goals"] = STAGE_GOALS
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
    jid = jobs.submit("learn", plan_prompt(p), ref=f"learn:plan:{pid}", add_dirs=_plan_dirs())
    db.update("learn_plans", pid, {"job_id": jid, "status": "generating", "updated_at": db.now()})
    return get_plan(pid)


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
    except ValueError as e:
        p = _plan(pid)
        db.update("learn_plans", pid, {"status": "active" if adapt else "failed", "updated_at": db.now(),
                                       "overview_md": (p["overview_md"] or "") + f"\n\n> 解析失败（job {job['id']}）：{e}"})


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
        "titles": {k: v["title"] for k, v in steps.items()}}


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
                   + (f"\n  漏掉：{'；'.join(rv.get('missing') or [])[:200]}；想偏：{'；'.join(rv.get('off') or [])[:200]}" if rv else ""))
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
本章所在阶段：阶段 {s['stage']} · {STAGES.get(s['stage'], '')} —— 本阶段目的：{STAGE_GOALS.get(s['stage'], '')}

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

做法：
1. 先读资源原文（WebFetch / curl；arXiv 优先读 /html/ 或 /abs/ 页）。资源不够、打不开或已过时，联网补充真实资料；阶段 1、3、5 必须核对资料时效。
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


def start_chapter_job(s: dict, note: str = "", prefetch: bool = False) -> int:
    out = _step_dir(s)
    out.mkdir(parents=True, exist_ok=True)
    archived = _archive_chapter(s)
    if archived or note:
        log_event(s, "chapter", {"action": "重新生成" if archived else "生成", "note": note, "archived": archived,
                                 "old_score": (s.get("quiz_result") or {}).get("score") if isinstance(s.get("quiz_result"), dict) else None})
    jid = jobs.submit("learn", chapter_prompt(s, note), ref=f"learn:step:{s['id']}:{'prefetch' if prefetch else 'chapter'}",
                      cwd=str(out), add_dirs=[str(SKILL_DIR)])
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


def _clean_quiz(o) -> list[dict]:
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
    # 题少而精：最多 2 道手写题、总共不超过 6 题（多出来的丢掉，按出题顺序保留）
    shorts = [q for q in out if q["type"] == "short"][:2]
    out = [q for q in out if q["type"] == "choice" or q in shorts][:6]
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


def _finish_chapter(sid: int, job: dict) -> None:
    s = db.row("SELECT * FROM learn_steps WHERE id=?", [sid])
    if not s or s.get("chapter_job") not in (None, job.get("id")):
        return  # 已被更新的一次生成取代
    out = _step_dir(s)
    chap = out / "chapter.md"
    text = chap.read_text("utf-8", errors="replace").strip() if chap.is_file() else ""
    qo = {}
    qf = out / "quiz.json"
    if qf.is_file():
        qo = _loads(qf.read_text("utf-8", errors="replace"), {})
    if not _clean_quiz(qo):
        qo = extract_json(job.get("output") or "", "questions") or {}
    quiz, cards = _clean_quiz(qo), _clean_cards(qo)
    ok = job.get("status") == "done" and len(text) > 200
    data = {"chapter_status": "ready" if ok else "failed"}
    if ok:
        data.update(chapter_md=text, quiz=quiz, cards=cards, checks={})  # 章节变了，「停一下」作答按序号对不上，清掉
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
    return f"""任务：批改学习测试里的简答题，像一位严格但愿意教的导师。今天是 {db.today()}。
计划：{p['topic']}；本章：阶段 {s['stage']} · {STAGES.get(s['stage'], '')} ·「{s['title']}」
本阶段目的：{STAGE_GOALS.get(s['stage'], '')}
（本章正文在 {_step_dir(s) / 'chapter.md'}，需要时可读。）
选择题答错的：{wrong or '无'}

{body}

评分：每题 score 取 0 / 0.25 / 0.5 / 0.75 / 1，按评分要点给分；意思对、表述不同也给分；只复述概念、没有理由或判断的不给满分。
feedback 写 2–4 句：哪里对、缺了什么、高手会怎么想（判断类题目要点出代表人物的推理路径和你的依据）。
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
        r["job_id"] = jobs.submit("learn", grade_prompt(s, r), ref=f"learn:step:{sid}:grade", add_dirs=[str(_step_dir(s))])
        db.update("learn_steps", sid, {"quiz_result": r})
    else:
        _finalize_quiz(sid, r)
    return public_step(_step(sid))


class CheckIn(BaseModel):
    q: str
    points: str = ""
    answer: str = ""
    review: bool = False


def check_prompt(s: dict, c: dict) -> str:
    p = _plan(s["plan_id"])
    return f"""任务：对照「停一下」的要点，点评用户自己写下的判断，帮他看清差距、提升判断力。今天是 {db.today()}。
计划：{p['topic']}；本章：阶段 {s['stage']} · {STAGES.get(s['stage'], '')} ·「{s['title']}」
本阶段目的：{STAGE_GOALS.get(s['stage'], '')}
（本章正文在 {_step_dir(s) / 'chapter.md'}，需要时可读。）

问题：{c['q']}
要点（参考答案）：{c['points'] or '（未提供，按本章内容判断）'}
用户的判断：{c['answer']}

要求：具体、短、不客套。用户说对的要认可；要点里没有但用户说得有道理的也要指出（要点不是唯一答案）。
不要写文件、不要调用平台 API。最终回复只给一个 ```json 代码块：
{{"covered": ["抓到的要点（用用户的话对应到要点）"], "missing": ["漏掉的要点，及为什么重要"], "off": ["想偏或说错的地方，错在哪"],
 "extra": ["要点之外、用户说得有道理的补充"], "better": "高手会怎么想：一两句示范推理路径", "score": 0.0}}
score 取 0–1，表示对要点的覆盖和推理质量。
"""


@router.post("/steps/{sid}/checks/{idx}")
def save_check(sid: int, idx: int, body: CheckIn):
    """保存一个「停一下」的作答；review=true 时提交后台点评（对照要点看差异）。"""
    s = _step(sid)
    checks = s["checks"]
    c = {"q": body.q[:600], "points": body.points[:3000], "answer": body.answer[:3000], "at": db.now(),
         "status": "answered" if body.answer.strip() else "viewed"}
    old = checks.get(str(idx)) or {}
    if old.get("review") and old.get("answer") == c["answer"]:  # 答案没改，保留上次点评
        c.update(status=old.get("status", "reviewed"), review=old["review"])
    if body.review and body.answer.strip():
        c["status"] = "reviewing"
        c.pop("review", None)
        c["job_id"] = jobs.submit("learn", check_prompt(s, c), ref=f"learn:step:{sid}:check:{idx}",
                                  add_dirs=[str(_step_dir(s))])
    checks[str(idx)] = c
    db.update("learn_steps", sid, {"checks": checks})
    if c["answer"].strip() and c["answer"] != old.get("answer"):
        log_event(s, "check", {"idx": idx, "q": c["q"], "points": c["points"], "answer": c["answer"]})
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
        c.update(status="reviewed", review={"covered": lst("covered"), "missing": lst("missing"), "off": lst("off"),
                                            "extra": lst("extra"), "better": str(o.get("better") or ""), "score": score})
        log_event(s, "check_review", {"idx": int(idx), "q": c["q"], "points": c.get("points", ""), "answer": c["answer"],
                                      "review": c["review"]}, src=f"job:{job.get('id')}")
    checks[idx] = c
    db.update("learn_steps", sid, {"checks": checks})


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
    elif m := re.fullmatch(r"learn:plan:(\d+)(:adapt)?", ref):
        _finish_plan(int(m.group(1)), job, bool(m.group(2)))
    elif m := re.fullmatch(r"learn:step:(\d+):(chapter|prefetch)", ref):
        _finish_chapter(int(m.group(1)), job)
    elif m := re.fullmatch(r"learn:step:(\d+):grade", ref):
        _finish_grade(int(m.group(1)), job)
    elif m := re.fullmatch(r"learn:step:(\d+):check:(\d+)", ref):
        _finish_check(int(m.group(1)), m.group(2), job)


# ---------- C. 对话上下文 ----------

def _plan_snapshot(pid: int) -> str:
    p = _plan(pid)
    steps = steps_of(pid)
    pr = _progress(steps)
    lines = [f"计划 {pid}：{p['topic']}（状态 {p['status']}，进度 {pr['done']}/{pr['total']}，{pr['hours']}h）",
             f"背景：{p['background']}；目标：{p['goal']}；每周 {p['hours_per_week']}h", ""]
    for stage, name in STAGES.items():
        ss = [s for s in steps if s["stage"] == stage]
        if not ss:
            continue
        lines.append(f"### 阶段{stage} {name}（目的：{STAGE_GOALS[stage]}）")
        for s in ss:
            chap = {"ready": "章节已生成", "generating": "章节生成中", "failed": "章节生成失败"}.get(s["chapter_status"], "")
            lines.append(f"- step_id={s['id']} [{s['status']}] 理解度{s['understanding']}/5 · {s['title']}（{s['est_hours']}h）"
                         + "".join(f"；{x}" for x in (chap, _quiz_line(s)) if x))
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
        return (f"正在追问条目 {it['id']}（{it['kind']}）：{it['title'] or it['url']}\n来源：{it['url']}\n"
                f"状态：{it['status']}；产物：{it['output_path'] or '无'}（目录 {out}，可用 Read 读取全文）\n"
                f"TL;DR：{it['summary']}\n我的笔记：{it['my_notes'] or '无'}；评分：{it['rating']}/5\n"
                f"更新笔记：curl -s -X PATCH {api}/items/{it['id']} -H 'Content-Type: application/json' -d '{{\"my_notes\":\"...\"}}'\n\n"
                f"### 产物摘录\n{body or '（HTML 产物，请直接读取文件）'}\n\n### 用户已学其他内容\n{_known_knowledge(it['id'], 10)}")
    if m := re.fullmatch(r"learn:step:(\d+)", ref or ""):
        s = db.row("SELECT * FROM learn_steps WHERE id=?", [int(m.group(1))])
        if not s:
            return "章节不存在"
        s = _decode_step(s)
        r = s["quiz_result"] or {}
        quiz = "\n".join(f"- {q['id']} [{q['type']}] {q['q']}" + (f" → 得分 {r['items'][q['id']]['score']}；用户答：{str(r['answers'].get(q['id']))[:200]}"
                                                                  if r.get("status") == "graded" and q["id"] in r.get("items", {}) else "")
                         for q in s["quiz"])
        return (f"用户正在读计划 {s['plan_id']} 的一章（step_id={s['id']}）：阶段 {s['stage']} · {STAGES.get(s['stage'], '')} ·「{s['title']}」\n"
                f"本阶段目的：{STAGE_GOALS.get(s['stage'], '')}\n能力目标：{s['goal'] or '（未写）'}\n"
                f"章节文件：{_step_dir(s) / 'chapter.md'}（下方是摘录，需要时 Read 全文）；测试：{_step_dir(s) / 'quiz.json'}\n"
                f"测试结果：{_quiz_line(s) or r.get('status') or '未做'}" + (f"；建议：{r.get('advice')}" if r.get("advice") else "")
                + f"\n回答时围绕本章目标，用户答错的题优先帮他想通；不要直接改写章节，除非用户要求（重新生成：POST {api}/steps/{s['id']}/open -d '{{\"force\":true,\"note\":\"...\"}}'）。\n\n"
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
