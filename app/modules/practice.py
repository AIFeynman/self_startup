"""实践：把知识讲解和可运行代码放在一起，边学边跑（类 Colab，所见即所得）。

课程 = practice/courses/<id>/（平台自带）或 data/practice/courses/<id>/（按主题 / 仓库生成）：
  course.json：id / title / summary / repo（要学的仓库）/ pip（依赖）/ runtime（cloud=阿里云 GPU，local=本机）/ know（相关知识）
  NN-xxx.md：一课。`## ` 分步；每步是「讲解 markdown + ```python 代码格 + > 思考：问题」，代码格信息串可带 long / cloud。
运行：默认都在本机（Mac 的 CPU / Apple GPU）；只有标了 cloud 的格子（全量训练这类本机跑不动的）才开阿里云 GPU，
云上训出的权重用 ss.from_cloud() 拉回本机接着用。_practice_runtime 管运行环境，_practice_kernel 管执行和输出收集。
问答：每步复用批注组件（doc = practice:<course>:<lesson>:<step>），讲解 + 代码 + 输出一起交给本机 Claude。
"""
from __future__ import annotations

import json
import re
import shutil
import threading
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import agent, db, jobs
from . import _practice_kernel as K, _practice_runtime as RT

TITLE = "实践"
ORDER = 52
SCHEMA = """
CREATE TABLE IF NOT EXISTS practice_runtime (kind TEXT PRIMARY KEY, status TEXT, port INTEGER, token TEXT, price REAL, cap REAL,
  started_at REAL, ready_at REAL, stopped_at REAL, last_active REAL, info TEXT DEFAULT '{}', log TEXT DEFAULT '', error TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS practice_cells (k TEXT PRIMARY KEY, course TEXT, lesson TEXT, cell TEXT, code TEXT, outputs TEXT,
  status TEXT, secs REAL, at TEXT);
CREATE TABLE IF NOT EXISTS practice_kernels (course TEXT, kind TEXT, kernel TEXT, PRIMARY KEY (course, kind));
CREATE TABLE IF NOT EXISTS practice_done (course TEXT, lesson TEXT, at TEXT, PRIMARY KEY (course, lesson));
CREATE TABLE IF NOT EXISTS practice_lab (id TEXT PRIMARY KEY, course TEXT, lesson TEXT, step INTEGER, title TEXT, code TEXT, at TEXT);
"""
router = APIRouter()

BUILTIN = RT.ASSETS / "courses"
MINE = RT.ROOT / "courses"


# ---------- 课程 ----------

COURSE_ID = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def course_dirs() -> list[Path]:
    out = []
    for base in (BUILTIN, MINE):
        if base.exists():
            out += sorted(p for p in base.iterdir() if COURSE_ID.match(p.name) and (p / "course.json").exists())
    return out


def load_course(cid: str) -> dict:
    for d in course_dirs():
        if d.name == cid:
            c = json.loads((d / "course.json").read_text(encoding="utf-8"))
            c["id"], c["dir"] = d.name, d
            c["lessons"] = [lesson_meta(p) for p in sorted(d.glob("[0-9]*.md"))]
            return c
    raise HTTPException(404, "没有这门课")


H1 = re.compile(r"^# (.+)$", re.M)
META = re.compile(r"<!--\s*(\w+):\s*(.+?)\s*-->")
FENCE = re.compile(r"^```python([^\n]*)\n(.*?)^```\s*$", re.M | re.S)


def lesson_meta(p: Path) -> dict:
    text = p.read_text(encoding="utf-8")
    m = H1.search(text)
    meta = dict(META.findall(text.split("\n## ", 1)[0]))
    return {"id": p.stem, "title": m[1].strip() if m else p.stem, "minutes": int(meta.get("minutes", 0) or 0),
            "know": [x.strip() for x in meta.get("know", "").split(",") if x.strip()],
            "cloud": sum("cloud" in f[0].split() for f in FENCE.findall(text)),
            "optional": sum(bool({"cloud", "optional"} & set(f[0].split())) for f in FENCE.findall(text)), "cells": len(FENCE.findall(text))}


def parse_lesson(text: str) -> dict:
    """拆成步骤：每步 {title, parts:[{type: md|code|ask, ...}]}；代码格编号全课连续。"""
    head, *chunks = re.split(r"^## ", text, flags=re.M)
    m = H1.search(head)
    intro = META.sub("", H1.sub("", head, count=1)).strip()
    steps, n = [], 0
    for ch in chunks:
        title, _, body = ch.partition("\n")
        parts, pos = [], 0
        for fm in FENCE.finditer(body):
            pre = body[pos:fm.start()]
            parts += _md_parts(pre)
            flags = fm[1].split()
            parts.append({"type": "code", "n": n, "code": fm[2].rstrip("\n"), "long": "long" in flags, "cloud": "cloud" in flags,
                          "optional": "optional" in flags or "cloud" in flags})
            n += 1
            pos = fm.end()
        parts += _md_parts(body[pos:])
        steps.append({"title": title.strip(), "parts": parts})
    return {"title": m[1].strip() if m else "", "intro": intro, "meta": dict(META.findall(head)), "steps": steps}


def _md_parts(s: str) -> list[dict]:
    out = []
    for blk in re.split(r"\n(?=> 思考[：:])", s.strip()):
        blk = blk.strip()
        if not blk:
            continue
        if re.match(r"> 思考[：:]", blk):
            out.append({"type": "ask", "text": re.sub(r"^> ?", "", blk, flags=re.M).split("：", 1)[-1].split(":", 1)[-1].strip()})
        else:
            out.append({"type": "md", "text": blk})
    return out


def lesson_path(c: dict, lid: str) -> Path:
    p = c["dir"] / f"{lid}.md"
    if not p.exists() or not re.fullmatch(r"[\w.-]+", lid):
        raise HTTPException(404, "没有这一课")
    return p


@router.get("/courses")
def courses():
    done = {}
    for r in db.rows("SELECT course, count(*) AS n FROM practice_done GROUP BY course"):
        done[r["course"]] = r["n"]
    out = []
    for d in course_dirs():
        c = load_course(d.name)
        out.append({k: c.get(k) for k in ("id", "title", "summary", "topic", "runtime", "know", "repo", "level")}
                   | {"lessons": len(c["lessons"]), "done": done.get(c["id"], 0), "mine": d.parent == MINE,
                      "minutes": sum(x["minutes"] for x in c["lessons"])})
    return {"courses": out, "runtimes": {k: RT.view(k) for k in RT.RUNNERS}}


@router.get("/courses/{cid}")
def course(cid: str):
    c = load_course(cid)
    done = {r["lesson"]: r["at"] for r in db.rows("SELECT lesson, at FROM practice_done WHERE course=?", [cid])}
    return {k: v for k, v in c.items() if k != "dir"} | {"done": done}


@router.get("/courses/{cid}/lessons/{lid}")
def lesson(cid: str, lid: str):
    c = load_course(cid)
    L = parse_lesson(lesson_path(c, lid).read_text(encoding="utf-8"))
    cells = {r["cell"]: {"code": r["code"], "outputs": json.loads(r["outputs"] or "[]"), "status": r["status"], "secs": r["secs"], "at": r["at"]}
             for r in db.rows("SELECT * FROM practice_cells WHERE course=? AND lesson=?", [cid, lid])}
    live = {e.key.split(":")[2]: e.id for e in K.running() if e.key.startswith(f"{cid}:{lid}:")}
    lab = db.rows("SELECT id, step, title, code, at FROM practice_lab WHERE course=? AND lesson=? ORDER BY at, id", [cid, lid])
    return L | {"id": lid, "course": cid, "cells": cells, "live": live, "lab": lab,
                "done": bool(db.row("SELECT 1 FROM practice_done WHERE course=? AND lesson=?", [cid, lid]))}


# ---------- 运行环境 ----------

class StartIn(BaseModel):
    kind: str = "cloud"
    confirm: bool = False


@router.get("/runtime")
def runtime_all():
    return {k: RT.view(k) for k in RT.RUNNERS}


@router.post("/runtime/start")
def runtime_start(body: StartIn):
    if body.kind not in RT.RUNNERS:
        raise HTTPException(400, "未知运行环境")
    if body.kind == "cloud" and not body.confirm:
        try:
            return {"quote": RT.start("cloud", quote=True)}
        except Exception as e:  # noqa: BLE001
            raise HTTPException(502, f"查价格失败：{e}") from e
    return RT.start(body.kind)


@router.post("/runtime/stop")
def runtime_stop(body: StartIn):
    return RT.stop(body.kind)


# ---------- 执行 ----------

class RunIn(BaseModel):
    course: str
    lesson: str
    cell: int | str
    code: str
    kind: str = ""


BOOT = ("import os, sys, warnings\nwarnings.filterwarnings('ignore', message='IProgress not found')\nwarnings.filterwarnings('ignore', category=FutureWarning)\n"
        "os.environ['HF_DATASETS_DISABLE_PROGRESS_BARS'] = '1'\nos.environ['TRANSFORMERS_VERBOSITY'] = 'error'\nos.environ['DATASETS_VERBOSITY'] = 'error'\n"
        "W = os.environ.get('SS_WORK') or os.getcwd()\nos.chdir(W)\nsys.path.insert(0, W)\n"
        "os.path.isdir({cid!r}) and os.chdir({cid!r})\nsys.path.insert(0, os.getcwd())\nimport ss\n")
_klocks: dict[tuple, threading.Lock] = {}


def kernel_for(c: dict, kind: str) -> tuple[K.Server, str]:
    with _klocks.setdefault((c["id"], kind), threading.Lock()):
        return _kernel_for(c, kind)


def _kernel_for(c: dict, kind: str) -> tuple[K.Server, str]:
    s = RT.server(kind)
    if not s:
        raise HTTPException(409, "运行环境没开")
    RT.ensure_course(kind, c)
    r = db.row("SELECT kernel FROM practice_kernels WHERE course=? AND kind=?", [c["id"], kind])
    if r and s.kernel_alive(r["kernel"]):
        return s, r["kernel"]
    if kind == "local":
        work = RT.Local().work
        for f in [RT.ASSETS / "ss.py", *sorted((c["dir"] / "lib").glob("*.py"))]:   # 工具库和课程自带模块更新后，新内核拿到最新版
            shutil.copy(f, work / f.name)
    kid = s.new_kernel()
    boot = K.execute(f"{c['id']}:_boot:0", BOOT.format(cid=c["id"]), lambda: K.ws_transport(s, kid))
    for _ in range(600):
        if boot.status not in ("queued", "running"):
            break
        threading.Event().wait(0.1)
    if boot.status != "done":
        s.shutdown(kid)
        raise HTTPException(500, "内核初始化失败：" + json.dumps(boot.outputs, ensure_ascii=False)[:300])
    db.execute("INSERT OR REPLACE INTO practice_kernels (course, kind, kernel) VALUES (?,?,?)", [c["id"], kind, kid])
    return s, kid


@router.post("/run")
def run(body: RunIn):
    c = load_course(body.course)
    lesson_path(c, body.lesson)
    kind = body.kind or "local"
    if not RT.server(kind):
        raise HTTPException(409, "运行环境没开")
    RT.touch(kind)

    def transport():
        s, kid = kernel_for(c, kind)   # 首次要装课程依赖，可能几分钟：放在执行线程里，接口立即返回
        return K.ws_transport(s, kid)
    if isinstance(body.cell, str):
        if not db.execute("UPDATE practice_lab SET code=? WHERE id=? AND course=? AND lesson=?", [body.code, body.cell, body.course, body.lesson]):
            raise HTTPException(404, "没有这个实验格")
    e = K.execute(f"{body.course}:{body.lesson}:{body.cell}", body.code, transport, on_activity=lambda: RT.touch(kind))
    return e.view()


@router.get("/exec/{eid}")
def exec_view(eid: str, ver: int = -1):
    e = K.EXECS.get(eid)
    if not e:
        raise HTTPException(404, "没有这次执行")
    v = e.view()
    if v["ver"] == ver:
        return {"id": eid, "ver": ver, "status": v["status"], "secs": v["secs"], "same": True}
    if v["status"] in ("done", "error") and e.key.count(":") == 2:
        _maybe_done(e.key)
    return v


class PullIn(BaseModel):
    course: str
    path: str


@router.post("/pull")
def pull(body: PullIn):
    """课程里 ss.from_cloud(path)：把云端课程目录下的文件拉到本机同一位置（云上训的权重拿回来接着用）。"""
    c = load_course(body.course)
    if ".." in body.path or body.path.startswith("/"):
        raise HTTPException(400, "只接受课程目录内的相对路径")
    if not RT.server("cloud"):
        raise HTTPException(409, "云端没开机；如果已经释放，权重已自动拉回本机课程目录")
    dst = RT.Local().work / c["id"] / body.path
    RT.Cloud().get(f"/root/work/{c['id']}/{body.path}", dst)
    return {"path": str(dst), "size": dst.stat().st_size}


class KindIn(BaseModel):
    course: str
    kind: str = ""


@router.post("/interrupt")
def interrupt(body: KindIn):
    c = load_course(body.course)
    kind = body.kind or "local"
    s = RT.server(kind)
    r = db.row("SELECT kernel FROM practice_kernels WHERE course=? AND kind=?", [c["id"], kind])
    if s and r:
        s.interrupt(r["kernel"])
    return {"ok": True}


@router.post("/restart")
def restart(body: KindIn):
    c = load_course(body.course)
    kind = body.kind or "local"
    r = db.row("SELECT kernel FROM practice_kernels WHERE course=? AND kind=?", [c["id"], kind])
    s = RT.server(kind)
    if r and s:
        s.shutdown(r["kernel"])
    db.execute("DELETE FROM practice_kernels WHERE course=? AND kind=?", [c["id"], kind])
    return {"ok": True}


def _maybe_done(key: str) -> None:
    """一课所有代码格都跑成功过 → 记完成，进复盘时间线。"""
    cid, lid, _ = key.split(":")
    if db.row("SELECT 1 FROM practice_done WHERE course=? AND lesson=?", [cid, lid]):
        return
    try:
        c = load_course(cid)
        meta = next(x for x in c["lessons"] if x["id"] == lid)
    except (HTTPException, StopIteration):
        return
    ok = db.row("SELECT count(*) AS n FROM practice_cells WHERE course=? AND lesson=? AND status='done' AND cell GLOB '[0-9]*'", [cid, lid])["n"]
    if meta["cells"] and ok >= meta["cells"] - meta["optional"]:   # 云端全量 / 可选格子不算，必做的本机格子都跑通就算学完
        db.execute("INSERT OR IGNORE INTO practice_done (course, lesson, at) VALUES (?,?,?)", [cid, lid, db.now()])
        from . import _read_log
        _read_log.log("practice", f"{cid}/{lid}", f"{c['title']} · {meta['title']}", f"#practice/{cid}/{lid}", "实践")


# ---------- 实验格：学员（或 Claude 给的代码）在某一步下自己加的格子，代码和输出都存着 ----------

class LabIn(BaseModel):
    course: str
    lesson: str
    step: int = 0
    title: str = ""
    code: str = ""


class LabPatch(BaseModel):
    title: str | None = None
    code: str | None = None


@router.post("/lab")
def lab_add(body: LabIn):
    lesson_path(load_course(body.course), body.lesson)
    import secrets
    lab_id = "x" + secrets.token_hex(4)
    row = {"id": lab_id, "step": body.step, "title": body.title.strip()[:80] or "我的实验", "code": body.code, "at": db.now()}
    db.execute("INSERT INTO practice_lab (id, course, lesson, step, title, code, at) VALUES (?,?,?,?,?,?,?)",
               [lab_id, body.course, body.lesson, row["step"], row["title"], row["code"], row["at"]])
    return row


@router.patch("/lab/{lab_id}")
def lab_edit(lab_id: str, body: LabPatch):
    r = db.row("SELECT * FROM practice_lab WHERE id=?", [lab_id])
    if not r:
        raise HTTPException(404, "没有这个实验格")
    db.execute("UPDATE practice_lab SET title=?, code=? WHERE id=?",
               [(body.title if body.title is not None else r["title"]).strip()[:80] or r["title"], r["code"] if body.code is None else body.code, lab_id])
    return {"ok": True}


@router.delete("/lab/{lab_id}")
def lab_del(lab_id: str):
    r = db.row("SELECT course, lesson FROM practice_lab WHERE id=?", [lab_id])
    if not r:
        raise HTTPException(404, "没有这个实验格")
    db.execute("DELETE FROM practice_lab WHERE id=?", [lab_id])
    db.execute("DELETE FROM practice_cells WHERE k=?", [f"{r['course']}:{r['lesson']}:{lab_id}"])
    return {"ok": True}


class LabWriteIn(BaseModel):
    course: str
    lesson: str
    step: int = 0
    ask: str
    context: str = ""
    lab_id: str = ""


LAB_PROMPT = """你在给实践课页面的「实验区」写一个代码格，学员会直接在页面里运行它。

## 课程上下文（这一步的讲解、课程代码格和最近的输出）
{context}
{current}
## 学员想做的实验
{ask}

## 要求
- 只输出两部分：第一行「标题：<不超过 20 字>」，然后一个 ```python 代码块，别的都不要。
- 代码在这门课的同一个 Jupyter 内核里执行：前面格子定义的变量可能还在，但别依赖，需要的 import 和数据自己准备。
- 结果用 ss 库展示：ss.kv / table / bars / line / compare / code / note，也可以 print。读结果的要点用 ss.note 写一两句。
- 控制在 1 分钟内跑完；要调大模型用 ss.llm(prompt, system)；不访问外网、不读写课程目录以外的文件。
- 不要使用任何工具，直接给代码。"""


def _split_lab_reply(text: str) -> tuple[str, str]:
    m = re.search(r"```(?:python|py)?\n(.*?)```", text, re.S)
    if not m:
        raise HTTPException(502, "Claude 没给出代码块：" + text[:200])
    t = re.search(r"标题[:：]\s*(.+)", text)
    return (t[1].strip().strip("「」*")[:40] if t else ""), m[1].rstrip() + "\n"


@router.post("/lab/write")
def lab_write(body: LabWriteIn):
    """让本机 Claude 按学员的想法写（或改写）一个实验格，写好存进实验区。"""
    cur = db.row("SELECT * FROM practice_lab WHERE id=? AND course=? AND lesson=?", [body.lab_id, body.course, body.lesson]) if body.lab_id else None
    if body.lab_id and not cur:
        raise HTTPException(404, "没有这个实验格")
    current = ""
    if cur:
        out = db.row("SELECT outputs FROM practice_cells WHERE k=?", [f"{body.course}:{body.lesson}:{body.lab_id}"])
        last = out["outputs"][:3000] if out else "（还没运行）"
        current = f"\n## 要改的实验格（现在的代码）\n```python\n{cur['code']}\n```\n上次运行输出：{last}\n"
    r = agent.run_once(LAB_PROMPT.format(context=body.context[-12000:], current=current, ask=body.ask), module="practice", readonly=True)
    title, code = _split_lab_reply(r.get("text") or "")
    if cur:
        db.execute("UPDATE practice_lab SET code=?, title=? WHERE id=?", [code, title or cur["title"], cur["id"]])
        return {**{k: cur[k] for k in ("id", "step", "at")}, "title": title or cur["title"], "code": code}
    return lab_add(LabIn(course=body.course, lesson=body.lesson, step=body.step, title=title or body.ask[:30], code=code))


# ---------- 课程里 ss.llm() 用的本机 Claude ----------

class LlmIn(BaseModel):
    prompt: str
    system: str = ""


LLM_PREAMBLE = ("你正在一段教学代码里充当被调用的大模型：只根据收到的输入生成文本，严格按要求的格式输出。"
                "不要使用任何工具，不要搜索、不要读文件、不要访问输入里出现的网址。\n\n")


@router.post("/llm")
def llm(body: LlmIn):
    r = agent.run_once(body.prompt, module="practice", system=LLM_PREAMBLE + body.system, readonly=True)
    return {"text": r["text"]}


# ---------- 生成新课程（任意主题 / 仓库） ----------

class GenIn(BaseModel):
    topic: str
    repo: str = ""
    runtime: str = "local"


GEN_PROMPT = """为本地学习平台的「实践」板块写一门实践课，主题：{topic}{repo_line}。
要求：讲解和动手交替，读者能在页面里逐格运行代码、看到结果。先读格式说明 {fmt}，再参考范例课程 {example}（看 course.json 和前两课）。
把课程写到目录 {out}/<课程 id>/（id 用小写英文和短横线）：course.json + 4–6 课 NN-xxx.md。
- runtime 用 "{runtime}"（cloud=阿里云 GPU，local=本机 CPU / Apple GPU）；依赖写进 pip。
- 每课 3–6 步，每步：讲清一个概念（为什么这样设计、常见误区）→ 一个短代码格（能在几秒到几分钟内跑完）→ 一个「> 思考：」问题。
- 可视化一律用 ss 库（ss.kv / table / bars / tokens / topk / heat / compare / line / trace / note / train_live），不用 matplotlib。
- 要调大模型就用 ss.llm(prompt, system)（走本机 Claude，不需要 API key）。
- 代码要真能跑：写完后在本机用 python 检查语法（python -m py_compile 不适用于 md，可把代码格抽出来检查）。
最后一行只输出课程 id。"""


@router.post("/generate")
def generate(body: GenIn):
    MINE.mkdir(parents=True, exist_ok=True)
    jid = jobs.submit("practice", GEN_PROMPT.format(
        topic=body.topic, repo_line=f"，围绕仓库 {body.repo}" if body.repo else "", fmt=RT.ASSETS / "COURSE_FORMAT.md",
        example=BUILTIN / "minimind", out=MINE, runtime=body.runtime), ref=f"practice:gen", add_dirs=[str(RT.ASSETS), str(MINE)])
    return {"job": jid}


@router.get("/for")
def course_for(url: str = ""):
    """深度学习板块的项目页用：这个仓库有没有对应的实践课。"""
    u = url.rstrip("/").lower()
    for d in course_dirs():
        c = json.loads((d / "course.json").read_text(encoding="utf-8"))
        repo = c.get("repo") or ""
        repo = repo["url"] if isinstance(repo, dict) else repo
        if repo and repo.rstrip("/").removesuffix(".git").lower() == u.removesuffix(".git"):
            return {"id": d.name, "title": c.get("title")}
    return {}


def on_startup():
    RT.on_startup()


def agent_context(ref: str) -> str:
    cs = courses()["courses"]
    return "实践课：" + "；".join(f"{c['title']}（{c['done']}/{c['lessons']} 课完成，运行在{'阿里云 GPU' if c['runtime'] == 'cloud' else '本机'}）" for c in cs)
