"""本地知识库：把各板块的数据同步成一棵适合大模型检索和阅读的 markdown 树（data/kb/）。

SQLite 仍是应用状态的唯一来源；kb/ 是自动生成、随时可重建的「可读镜像」：
- 一条知识一个文件，YAML frontmatter 带 type/title/date/tags/summary，正文是完整内容；
- INDEX.md 是入口（各类计数、最近更新、标签），tags/<标签>.md 是按标签的反向索引，
  daily/<日期>.md 把一天的计划、完成、复盘、笔记、效率、产出串在一起（按时间线检索）；
- 同时维护 SQLite FTS5（trigram，中文可用）全文索引，供 /api/kb/search 快速检索。
大模型的检索顺序：INDEX.md → tags/ 或 rg 搜 frontmatter/summary → 只读命中的文件。
"""
from __future__ import annotations

import json
import logging
import re
import threading
from pathlib import Path

from . import db

log = logging.getLogger(__name__)
KB_DIR = db.DATA_DIR / "kb"
MANIFEST = ".manifest.json"

TYPE_DIRS = {
    "daily": "daily", "note": "notes", "research": "research", "product": "products",
    "paper": "learn/papers", "papernote": "learn/paper-notes", "repo": "learn/repos", "plan": "learn/plans", "feed": "feed", "annotation": "annotations",
}
TYPE_NAMES = {
    "daily": "每日记录", "note": "问题与经验", "research": "调研", "product": "产品体验",
    "paper": "论文深读", "papernote": "论文笔记", "repo": "项目解读", "plan": "学习计划", "feed": "收藏的信息", "annotation": "阅读批注",
}

README = """# 本地知识库（自动生成，勿手改）

由学习平台从 SQLite 自动同步；修改请在平台里做，或调用平台 API。

## 目录
- `INDEX.md`：入口。各类数量、最近更新、全部标签。
- `daily/YYYY-MM-DD.md`：一天的计划与完成、复盘、问题与经验、Agent 效率、当天产出（时间线检索用这里）。
- `notes/`：问题 / 经验 / 洞察 / 想法，一条一个文件。
- `research/`：调研文档（含各引擎结果与综合）。`products/`：产品体验。
- `learn/papers/`、`learn/repos/`：论文 / GitHub 项目深读（TL;DR + 我的笔记 + 全文或产物路径）。
- `learn/plans/`：主题学习计划（阶段、步骤、进度、理解度、反馈）。
- `feed/saved.md`：点赞 / 收藏的信息流条目。
- `annotations/`：阅读批注，一份材料一个文件：划线原文 + 我的评论 + 问 Claude 的问答。
- `tags/<标签>.md`：按标签列出相关文件。

## 文件格式
每个文件以 YAML frontmatter 开头：`id` `type` `title` `date` `updated` `tags` `status` `url` `summary`。
`summary` 是 1–3 行摘要，判断相关性先看它，再决定是否读正文。

## 检索建议（给大模型）
1. 先读 `INDEX.md`；按主题看 `tags/`；按日期看 `daily/`。
2. 关键词：`rg -l "关键词" data/kb`，或只搜摘要 `rg "^summary:.*关键词" data/kb`。
3. 或调用 `GET /api/kb/search?q=关键词&type=note`（全文索引，返回路径 + 摘要 + 片段）。
4. 只读命中的少数文件，引用时给出文件路径。
"""

_lock = threading.Lock()
_timer: threading.Timer | None = None


# ---------- 文档构造 ----------

def _slug(s: str, n: int = 40) -> str:
    s = re.sub(r"[^\w一-鿿-]+", "-", (s or "").strip().lower()).strip("-")
    return s[:n] or "untitled"


def _tags(v) -> list[str]:
    if not v:
        return []
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except json.JSONDecodeError:
            v = re.split(r"[,，;；\s]+", v)
    return [str(t).strip().lstrip("#") for t in v if str(t).strip()]


def _yaml_val(v) -> str:
    if isinstance(v, list):
        return "[" + ", ".join(json.dumps(x, ensure_ascii=False) for x in v) + "]"
    s = str(v if v is not None else "").replace("\n", " ").strip()
    return json.dumps(s, ensure_ascii=False) if s and (":" in s or s[0] in "[{#&*!|>'\"%@`-") else s


def _doc(type_: str, key, title: str, body: str, *, date: str = "", updated: str = "", tags=None,
         status: str = "", url: str = "", summary: str = "", path: str | None = None) -> dict:
    body = re.sub(r"\A\s*#\s+" + re.escape(title.strip()) + r"\s*\n", "", body or "")
    tags = sorted(set(_tags(tags)))
    rel = path or f"{TYPE_DIRS[type_]}/{key}-{_slug(title)}.md"
    meta = {"id": f"{type_}:{key}", "type": type_, "title": title, "date": (date or "")[:10],
            "updated": (updated or date or "")[:19], "tags": tags, "status": status, "url": url,
            "summary": re.sub(r"\s+", " ", summary or "")[:300]}
    fm = "\n".join(f"{k}: {_yaml_val(v)}" for k, v in meta.items() if v not in ("", [], None))
    return {**meta, "path": rel, "body": body.strip(), "text": f"---\n{fm}\n---\n\n# {title}\n\n{body.strip()}\n"}


def _has(table: str) -> bool:
    return bool(db.row("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", [table]))


def _first_lines(text: str, n: int = 2) -> str:
    lines = [ln.strip("#>-* ").strip() for ln in (text or "").splitlines() if ln.strip() and not ln.startswith("---")]
    return " ".join(lines[:n])


def _gist(text: str, n: int = 2) -> str:
    """取正文里前几句「像内容」的话：跳过标题、表格、元信息短行（如「调研 ID：1」）。"""
    lines = (text or "").splitlines()
    # 有「要点/结论/TL;DR/摘要」小节时优先取那里
    for i, ln in enumerate(lines):
        if ln.lstrip().startswith("#") and re.search(r"要点|结论|TL;?DR|摘要|总结|Summary", ln, re.I):
            lines = lines[i + 1:]
            break
    out = []
    for ln in lines:
        t = ln.strip().lstrip("-*>0123456789. ").strip()
        if not t or ln.lstrip().startswith(("#", "|", "---", "```")) or len(t) < 24 or re.search(r"ID[:：]\s*\d", t):
            continue
        out.append(t.replace("**", ""))
        if len(out) >= n:
            break
    return " ".join(out) or _first_lines(text, n)


# ---------- 各类数据 → 文档 ----------

def _notes() -> list[dict]:
    if not _has("review_notes"):
        return []
    kinds = {"problem": "问题", "lesson": "经验", "insight": "洞察", "idea": "想法"}
    return [_doc("note", n["id"], n["title"] or _first_lines(n["content"], 1)[:40],
                 f"类型：{kinds.get(n['kind'], n['kind'])} · 日期：{n['date']}\n\n{n['content']}",
                 date=n["date"], updated=n.get("updated_at") or "", tags=_tags(n["tags"]) + [kinds.get(n["kind"], n["kind"])],
                 status=n["kind"], summary=_first_lines(n["content"]) or n["title"],
                 path=f"notes/{n['date']}-{n['id']}-{_slug(n['title'] or n['content'][:20])}.md")
            for n in db.rows("SELECT * FROM review_notes ORDER BY id")]


def _research() -> list[dict]:
    if not _has("research_docs"):
        return []
    out = []
    for d in db.rows("SELECT * FROM research_docs ORDER BY id"):
        r = db.row("SELECT * FROM research WHERE id=?", [d["research_id"]]) if d.get("research_id") else None
        tags = _tags(d.get("tags")) + (_tags(r["angles"]) if r else [])
        summ = (_gist(r["synthesis"]) if r and r.get("synthesis") else "") or _gist(d["content"])
        out.append(_doc("research", d["id"], d["title"], d["content"] or "", date=d["created_at"],
                        updated=d.get("updated_at") or "", tags=tags, status=(r or {}).get("status", "doc"), summary=summ))
    return out


def _products() -> list[dict]:
    if not _has("products"):
        return []
    out = []
    for p in db.rows("SELECT * FROM products ORDER BY id"):
        body = "\n".join(x for x in [
            f"- 分类：{p['category']}" if p.get("category") else "",
            f"- 评分：{'★' * int(p['rating'] or 0)}" if p.get("rating") else "",
            f"- 链接：{p['url']}" if p.get("url") else "",
            f"- 使用时间：{p['used_at']}" if p.get("used_at") else "",
            f"\n## 体验\n{p['experience']}" if p.get("experience") else "",
            f"\n## 优点\n{p['pros']}" if p.get("pros") else "",
            f"\n## 缺点\n{p['cons']}" if p.get("cons") else "",
        ] if x)
        out.append(_doc("product", p["id"], p["name"], body, date=p.get("used_at") or p["created_at"],
                        updated=p.get("updated_at") or "", tags=_tags(p.get("tags")) + ([p["category"]] if p.get("category") else []),
                        url=p.get("url") or "", summary=_first_lines(p.get("experience") or "", 2)))
    return out


def _learn_items() -> list[dict]:
    if not _has("learn_items"):
        return []
    out = []
    for it in db.rows("SELECT * FROM learn_items ORDER BY id"):
        type_ = "repo" if it["kind"] == "github" else "paper"  # 文章深读和论文放一起
        body = [f"- 链接：{it['url']}", f"- 状态：{it['status']}"]
        if it.get("rating"):
            body.append(f"- 评分：{'★' * int(it['rating'])}")
        if it.get("output_path"):
            body.append(f"- 产物：{it['output_path']}")
        if it.get("summary"):
            body.append(f"\n## TL;DR\n{it['summary']}")
        if it.get("my_notes"):
            body.append(f"\n## 我的笔记\n{it['my_notes']}")
        # 论文笔记 / 项目摘要直接内嵌，一个文件就能读全
        op = Path(it.get("output_path") or "")
        full = op if op.suffix == ".md" else op.parent / "summary.md" if op.suffix == ".html" else None
        try:  # 条目对话里的追问与感想
            from .modules import _reads
            body.append(_reads.kb_section(it["id"]))
        except Exception:  # noqa: BLE001
            pass
        if full and full.exists():
            body.append("\n## 全文\n" + full.read_text("utf-8", errors="ignore"))
        out.append(_doc(type_, it["id"], it["title"] or it["url"], "\n".join(body), date=it["created_at"],
                        updated=it.get("updated_at") or "", tags=[it["kind"]], status=it["status"], url=it["url"],
                        summary=_first_lines(it.get("summary") or "", 3)))
    return out


def _plans() -> list[dict]:
    if not _has("learn_plans"):
        return []
    stages = {1: "领域综述", 2: "核心人物与观点", 3: "关键书籍/经典论文", 4: "核心机制精学", 5: "前沿进展", 6: "实践与输出"}
    out = []
    for p in db.rows("SELECT * FROM learn_plans ORDER BY id"):
        steps = db.rows("SELECT * FROM learn_steps WHERE plan_id=? ORDER BY stage, ord, id", [p["id"]])
        done = sum(s["status"] == "done" for s in steps)
        body = [f"- 目标：{p['goal']}", f"- 背景：{p['background']}", f"- 每周投入：{p['hours_per_week']} 小时",
                f"- 进度：{done}/{len(steps)}", "", p.get("overview_md") or ""]
        cur = None
        for s in steps:
            if s["stage"] != cur:
                cur = s["stage"]
                body.append(f"\n## 阶段 {cur} · {stages.get(cur, '')}")
            mark = {"done": "x", "doing": "~", "skipped": "-"}.get(s["status"], " ")
            body.append(f"\n### [{mark}] {s['title']}（step {s['id']}，约 {s['est_hours']}h）\n{s['description']}")
            for r in json.loads(s["resources"] or "[]"):
                body.append(f"- [{r.get('title')}]({r.get('url', '')}) {r.get('why', '')}")
            if s.get("understanding"):
                body.append(f"- 理解度：{s['understanding']}/5")
            if s.get("feedback"):
                body.append(f"- 反馈：{s['feedback']}")
            qr = json.loads(s["quiz_result"]) if s.get("quiz_result") else {}
            if qr.get("status") == "graded":
                weak = "；".join(qr.get("weak_points") or [])
                body.append(f"- 章末测试：{qr.get('score')} 分" + (f"；薄弱：{weak}" if weak else ""))
            if s.get("chapter_md"):
                body.append(f"\n<details><summary>章节教程</summary>\n\n{s['chapter_md']}\n\n</details>")
        if _has("learn_events"):
            body += _learn_events_md(plan_id=p["id"])
        out.append(_doc("plan", p["id"], p["topic"], "\n".join(body), date=p["created_at"], updated=p.get("updated_at") or "",
                        tags=["学习计划", p["topic"]], status=p["status"],
                        summary=f"{p['goal']}（进度 {done}/{len(steps)}）"))
    return out


def _feed_saved() -> list[dict]:
    if not _has("feed_feedback"):
        return []
    rs = db.rows("SELECT i.*, f.vote, f.saved FROM feed_items i JOIN feed_feedback f ON f.item_id=i.id "
                 "WHERE (f.vote=1 OR f.saved=1) AND f.hidden=0 ORDER BY i.date DESC")
    if not rs:
        return []
    lines = []
    for r in rs:
        flag = "☆" if r["saved"] else "👍"
        lines.append(f"- {flag} [{r['title']}]({r['url']}) · {r['source']} · {r['date'][:10]}\n  {r['summary'][:200]}")
    return [_doc("feed", "saved", "收藏与点赞的信息", "\n".join(lines), updated=db.now(), tags=["信息流"],
                 summary=f"{len(rs)} 条点赞/收藏，最近：{rs[0]['title']}", path="feed/saved.md")]


def _paper_notes() -> list[dict]:
    """每日论文笔记：信息推荐里读完写下的一句话判断，按天一篇。"""
    if not _has("feed_feedback") or "verdict" not in {r["name"] for r in db.rows("PRAGMA table_info(feed_feedback)")}:
        return []
    rs = db.rows("SELECT i.title, i.url, i.source, i.type, f.verdict, f.verdict_at FROM feed_feedback f JOIN feed_items i ON i.id=f.item_id "
                 "WHERE f.verdict<>'' AND f.verdict_at<>'' ORDER BY f.verdict_at")
    by: dict[str, list[dict]] = {}
    for r in rs:
        by.setdefault(r["verdict_at"][:10], []).append(r)
    out = []
    for d, xs in by.items():
        body = "\n".join(f"- [{r['title']}]({r['url']}) · {r['source']}（{r['verdict_at'][11:16]}）\n  **判断**：{r['verdict']}" for r in xs)
        out.append(_doc("papernote", d, f"{d} 论文笔记", body, date=d, updated=xs[-1]["verdict_at"], tags=["论文", "每日论文"],
                        summary=f"{len(xs)} 篇：{xs[0]['title'][:40]}", path=f"learn/paper-notes/{d}.md"))
    return out


def _annotations() -> list[dict]:
    """一份材料一个文件：每条划线（或针对全文）一节，下面是评论和问答。"""
    if not _has("annotations"):
        return []
    out = []
    for g in db.rows("SELECT doc, max(title) title, max(link) link, min(created_at) c, max(updated_at) u, count(*) n "
                     "FROM annotations GROUP BY doc ORDER BY min(id)"):
        body, first = [f"材料：`{g['doc']}`" + (f"（平台 {g['link']}）" if g["link"] else ""), ""], ""
        for a in db.rows("SELECT * FROM annotations WHERE doc=? ORDER BY id", [g["doc"]]):
            body.append("## " + (f"「{_clip(a['quote'], 60)}」" if a["quote"] else "全文") + ("（已解决）" if a["status"] == "resolved" else ""))
            if a["quote"]:
                body.append("> " + a["quote"].replace("\n", "\n> "))
            for m in db.rows("SELECT * FROM annotation_msgs WHERE annotation_id=? AND status!='pending' ORDER BY id", [a["id"]]):
                who = "我" if m["role"] == "user" else "Claude"
                body.append(f"\n**{who}**（{m['created_at'][:16].replace('T', ' ')}）：{m['content'].strip()}")
                first = first or (m["content"] if m["role"] == "user" else "")
            body.append("")
        title = f"批注：{g['title'] or g['doc']}"
        out.append(_doc("annotation", _slug(g["doc"], 30), title, "\n".join(body), date=g["c"], updated=g["u"],
                        summary=f"{g['n']} 条批注。{_clip(first, 120)}"))
    return out


def _clip(t: str, n: int) -> str:
    t = re.sub(r"\s+", " ", t or "").strip()
    return t if len(t) <= n else t[:n] + "…"


def _learn_events_md(date: str = "", plan_id: int = 0) -> list[str]:
    """学习记录（测试、停一下作答与 Agent 点评、理解度 / 反馈变化）的 markdown 行。"""
    try:
        from .modules import learn
        titles = {r["id"]: r["title"] for r in db.rows("SELECT id, title FROM learn_steps")}
        lines = [f"- {learn.event_line(e, titles)}" for e in learn.events_of(plan_id=plan_id or None, date=date) if e["kind"] != "check"]
    except Exception:  # noqa: BLE001
        return []
    return (["\n## 学习记录"] + lines) if lines else []


def _daily(docs: list[dict]) -> list[dict]:
    dates = {r["date"] for r in db.rows("SELECT DISTINCT date FROM tasks")}
    for t in ("review_days", "review_notes", "review_agent_stats", "agent_util"):
        if _has(t):
            dates |= {r["date"] for r in db.rows(f"SELECT DISTINCT date FROM {t}")}
    if _has("learn_events"):
        dates |= {r["d"] for r in db.rows("SELECT DISTINCT substr(created_at,1,10) AS d FROM learn_events")}
    by_date: dict[str, list[dict]] = {}
    for d in docs:
        if d["date"]:
            by_date.setdefault(d["date"], []).append(d)
    out = []
    st_name = {"todo": "未开始", "doing": "进行中", "done": "完成", "partial": "部分", "dropped": "放弃"}
    for date in sorted(x for x in dates if x):
        tasks = db.rows("SELECT * FROM tasks WHERE date=? ORDER BY COALESCE(start_time,''), priority, id", [date])
        tops = [t for t in tasks if not t["parent_id"]]
        done = sum(t["status"] == "done" for t in tops)
        body = [f"## 事项与目标（完成 {done}/{len(tops)}）"]
        for t in tops:
            body.append(f"- [{st_name.get(t['status'], t['status'])}] P{t['priority']} {t['title']}"
                        + (f" — 目标：{t['goal']}" if t["goal"] else "") + (f"（{t['start_time']}-{t['end_time']}）" if t["start_time"] else ""))
            for c in (x for x in tasks if x["parent_id"] == t["id"]):
                body.append(f"  - [{st_name.get(c['status'], c['status'])}] {c['title']} · {c['human_level']}/{c['executor']}")
        rv = db.row("SELECT * FROM review_days WHERE date=?", [date]) if _has("review_days") else None
        if rv:
            for k, name in (("summary", "总结"), ("wins", "做成了什么"), ("problems", "问题"), ("next_actions", "下一步")):
                if rv.get(k):
                    body.append(f"\n## {name}\n{rv[k]}")
            if rv.get("ai_analysis"):
                body.append(f"\n## AI 完成情况检查\n{rv['ai_analysis']}")
            if rv.get("improve_md"):
                body.append(f"\n## AI 改进分析（结合会话与学习反馈）\n{rv['improve_md']}")
        ef = db.row("SELECT * FROM review_agent_stats WHERE date=?", [date]) if _has("review_agent_stats") else None
        if ef:
            s = json.loads(ef["summary"] or "{}")
            body.append(f"\n## Agent 效率\n- 会话 {s.get('sessions', 0)}（交互 {s.get('interactive', 0)}），人工介入 {s.get('human_turns', 0)} 次，"
                        f"Agent 等你 {s.get('wait_wall_min', s.get('wait_total_min', 0))} 分钟（墙钟；各会话累加 {s.get('wait_total_min', 0)}），工具调用 {s.get('tool_calls', 0)}")
            if ef.get("reflection"):
                body.append(f"\n### 反思\n{ef['reflection']}")
        ut = db.row("SELECT * FROM agent_util WHERE date=?", [date]) if _has("agent_util") else None
        if ut:
            u, ud = json.loads(ut["summary"] or "{}"), json.loads(ut["data"] or "{}")
            body.append(f"\n## 时间利用\n- Agent 覆盖 {u.get('coverage_pct')}%（工作时间内 {u.get('coverage_work_pct', '-')}%），并发容量 {u.get('capacity_pct')}%，空档 {u.get('idle_min')} 分钟"
                        f"（专注时间内 {u.get('idle_focus_min')}）\n- 人工交互 {u.get('human_total')} 次，专注时间外 {u.get('human_out_focus')} 次；"
                        f"Agent 等你 {u.get('wait_wall_min', u.get('wait_total_min'))} 分钟（各会话累加 {u.get('wait_total_min')} Agent·分钟）")
            body += [f"- 建议：{a}" for a in ud.get("advice", [])[:5]]
        dl = db.row("SELECT data FROM agent_delivery WHERE date=?", [date]) if _has("agent_delivery") else None
        if dl:
            g = json.loads(dl["data"] or "{}")
            for k, t in (("delivered", "已交付"), ("changed_after", "交付后仍有改动"), ("committed", "已提交未推送")):
                if g.get(k):
                    body.append(f"\n## {t}（{len(g[k])}）" if k == "delivered" else f"\n### {t}（{len(g[k])}）")
                    body += [f"- {x['at']} [{'/'.join(x['labels'])}] {x['project']} · {x['title']}"
                             + (f"（文档：{', '.join(x['docs'][:3])}）" if x.get("docs") else "") for x in g[k]]
        if _has("learn_events"):
            body += _learn_events_md(date)
        related = [d for d in by_date.get(date, []) if d["type"] != "daily"]
        if related:
            body.append("\n## 当天产出与记录")
            body += [f"- [{TYPE_NAMES[d['type']]}] [{d['title']}](../{d['path']}) — {d['summary'][:80]}" for d in related]
        summary = f"事项完成 {done}/{len(tops)}" + (f"；{_first_lines(rv['summary'], 1)}" if rv and rv.get("summary") else "")
        out.append(_doc("daily", date, f"{date} 每日记录", "\n".join(body), date=date, updated=(rv or {}).get("updated_at") or "",
                        summary=summary, path=f"daily/{date}.md"))
    return out


def build() -> list[dict]:
    docs: list[dict] = []
    for fn in (_notes, _research, _products, _learn_items, _plans, _feed_saved, _paper_notes, _annotations):
        try:
            docs += fn()
        except Exception:  # noqa: BLE001 —— 单类出错不影响其它
            log.exception("kb build %s", fn.__name__)
    try:
        docs += _daily(docs)
    except Exception:  # noqa: BLE001
        log.exception("kb build daily")
    return docs


def _index(docs: list[dict]) -> tuple[str, dict[str, list[dict]]]:
    counts: dict[str, int] = {}
    tags: dict[str, list[dict]] = {}
    for d in docs:
        counts[d["type"]] = counts.get(d["type"], 0) + 1
        for t in d["tags"]:
            tags.setdefault(t, []).append(d)
    recent = sorted(docs, key=lambda d: d["updated"] or d["date"], reverse=True)[:40]
    lines = [f"# 知识库索引\n\n更新于 {db.now()} · 共 {len(docs)} 个文件。先看这里，再按类型 / 标签 / 日期读具体文件。\n",
             "## 分类", *[f"- {TYPE_NAMES[k]}（`{TYPE_DIRS[k]}/`）：{v}" for k, v in sorted(counts.items())],
             "\n## 最近更新", "| 日期 | 类型 | 标题 | 摘要 |", "|---|---|---|---|",
             *[f"| {(d['updated'] or d['date'])[:10]} | {TYPE_NAMES[d['type']]} | [{d['title']}]({d['path']}) | {d['summary'][:60]} |" for d in recent],
             "\n## 标签", " · ".join(f"[{t}](tags/{_slug(t)}.md)（{len(v)}）" for t, v in sorted(tags.items(), key=lambda x: -len(x[1])))]
    return "\n".join(lines) + "\n", tags


# ---------- 写盘 + 全文索引 ----------

FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS kb_fts USING fts5(
    path UNINDEXED, type UNINDEXED, title, tags, summary, body, date UNINDEXED, tokenize='trigram');
"""


def sync() -> dict:
    """全量重建（数据量小，几百个文件毫秒级）；只写有变化的文件，删除已不存在的。"""
    with _lock:
        docs = build()
        index, tags = _index(docs)
        files = {d["path"]: d["text"] for d in docs}
        files["INDEX.md"] = index
        files["README.md"] = README
        for t, ds in tags.items():
            files[f"tags/{_slug(t)}.md"] = f"# 标签：{t}\n\n" + "\n".join(
                f"- [{TYPE_NAMES[d['type']]}] [{d['title']}](../{d['path']}) · {d['date']} — {d['summary'][:80]}" for d in ds) + "\n"
        KB_DIR.mkdir(parents=True, exist_ok=True)
        mpath = KB_DIR / MANIFEST
        old = set(json.loads(mpath.read_text())) if mpath.exists() else set()
        written = 0
        for rel, text in files.items():
            p = KB_DIR / rel
            if p.exists() and p.read_text("utf-8") == text:
                continue
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, "utf-8")
            written += 1
        for rel in old - set(files):
            (KB_DIR / rel).unlink(missing_ok=True)
        mpath.write_text(json.dumps(sorted(files), ensure_ascii=False))
        db.init([FTS_SCHEMA])
        with db._lock:
            c = db.conn()
            c.execute("DELETE FROM kb_fts")
            c.executemany("INSERT INTO kb_fts(path,type,title,tags,summary,body,date) VALUES (?,?,?,?,?,?,?)",
                          [(d["path"], d["type"], d["title"], " ".join(d["tags"]), d["summary"], d["body"], d["date"]) for d in docs])
            c.commit()
        return {"docs": len(docs), "written": written, "removed": len(old - set(files)), "dir": str(KB_DIR)}


def schedule_sync(delay: float = 3.0) -> None:
    """写操作后防抖同步。"""
    global _timer
    if _timer:
        _timer.cancel()
    _timer = threading.Timer(delay, _safe_sync)
    _timer.daemon = True
    _timer.start()


def _safe_sync() -> None:
    try:
        sync()
    except Exception:  # noqa: BLE001
        log.exception("kb sync failed")


def search(q: str, type_: str = "", limit: int = 20) -> list[dict]:
    db.init([FTS_SCHEMA])
    q = (q or "").strip()
    if not q:
        return []
    where, args = "", []
    if type_:
        where, args = " AND type=?", [type_]
    if len(q) >= 3:  # trigram 至少 3 个字符
        terms = " AND ".join('"' + t.replace('"', '') + '"' for t in q.split() if len(t) >= 3) or '"' + q.replace('"', '') + '"'
        try:
            return db.rows(f"SELECT path,type,title,tags,summary,date,snippet(kb_fts,5,'«','»','…',16) AS snippet "
                           f"FROM kb_fts WHERE kb_fts MATCH ?{where} ORDER BY rank LIMIT ?", [terms, *args, limit])
        except Exception:  # noqa: BLE001 —— 语法问题回退到 LIKE
            pass
    like = f"%{q}%"
    return db.rows(f"SELECT path,type,title,tags,summary,date,substr(body,1,120) AS snippet FROM kb_fts "
                   f"WHERE (title LIKE ? OR tags LIKE ? OR summary LIKE ? OR body LIKE ?){where} LIMIT ?",
                   [like, like, like, like, *args, limit])


def read(rel: str) -> str:
    p = (KB_DIR / rel).resolve()
    if not str(p).startswith(str(KB_DIR.resolve())) or not p.is_file():
        raise FileNotFoundError(rel)
    return p.read_text("utf-8")
