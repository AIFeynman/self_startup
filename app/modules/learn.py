"""深度学习：A. 单篇论文 / GitHub 项目深读；B. 主题学习计划（分阶段步骤 + 反馈调整）。

后台 job 的 ref 约定：
    learn:item:<id>          条目深读
    learn:plan:<id>          生成学习计划
    learn:plan:<id>:adapt    根据反馈调整计划
对话 ref：learn:item:<id> / learn:plan:<id> / 空（总览）。
"""
from __future__ import annotations

import json
import re
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
    done_at       TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_learn_steps_plan ON learn_steps(plan_id);
"""

STAGES = {1: "领域综述", 2: "核心人物与观点", 3: "关键书籍 / 经典论文",
          4: "核心机制 / 概念精学", 5: "前沿进展", 6: "实践与输出"}
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

class ItemIn(BaseModel):
    url: str
    kind: str = ""
    focus: str = ""


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


def item_prompt(it: dict, out: Path) -> str:
    kind = it["kind"]
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
    url = body.url.strip()
    if not url:
        raise HTTPException(400, "url required")
    kind = body.kind if body.kind in ("paper", "github") else detect_kind(url)
    iid = db.insert("learn_items", {"kind": kind, "url": url, "focus": body.focus, "status": "queued",
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
    it = _item(iid)
    if body and body.get("focus") is not None:
        db.update("learn_items", iid, {"focus": body["focus"]})
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
        names = ["note.md"] if it["kind"] == "paper" else ["index.html"]
        globs = ["*.md"] if it["kind"] == "paper" else ["*.html", "*.md"]
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
    return s


def steps_of(pid: int) -> list[dict]:
    return [_decode_step(s) for s in db.rows("SELECT * FROM learn_steps WHERE plan_id=? ORDER BY stage, ord, id", [pid])]


def _step(sid: int) -> dict:
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
    p["steps"] = steps_of(pid)
    p["progress"] = _progress(p["steps"])
    p["stages"] = STAGES
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
    return _step(add_step(pid, body.model_dump(), after_step_id))


@router.patch("/steps/{sid}")
def patch_step(sid: int, body: StepIn):
    _step(sid)
    f = _step_fields(body.model_dump())
    if f:
        db.update("learn_steps", sid, f)
    return _step(sid)


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
    goal = "能回答：" + "；".join(s["questions"][:3]) if s["questions"] else s["description"][:200]
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


def on_job_done(job: dict) -> None:
    ref = job.get("ref") or ""
    if m := re.fullmatch(r"learn:item:(\d+)", ref):
        _finish_item(int(m.group(1)), job)
    elif m := re.fullmatch(r"learn:plan:(\d+)(:adapt)?", ref):
        _finish_plan(int(m.group(1)), job, bool(m.group(2)))


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
        lines.append(f"### 阶段{stage} {name}")
        for s in ss:
            lines.append(f"- step_id={s['id']} [{s['status']}] 理解度{s['understanding']}/5 · {s['title']}（{s['est_hours']}h）")
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
            str(SKILL_DIR), str(_out_root())]
    return dirs
