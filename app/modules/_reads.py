"""深读条目的「读」这一侧：追问对话绑定到条目、记成当天的深读事项、追问与感想进复盘和知识库。

- 对话：条目页「继续追问」用 ref=learn:item:<id>，关掉再开会续上；以前在对话里直接「深度解析：<链接>」的会话，
  按链接认领到条目上（没有条目的，把 Agent 那次的回复存成条目的 note.md，不重跑）。
- 事项：开始深读时在当天加一条学习事项「深读：<标题>」；文档生成好算进行中，在对话里追问 / 写感想、写笔记或打分算完成。
- 追问与感想：用户在条目对话里发的话（不含开头那句「深度解析：链接」）。以问句结尾的算追问，其余算感想。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .. import db, tasks
from ._feed_rank import norm_url

TAG = "deepread:item:"
_ASK = re.compile(r"[?？]\s*$|^(为什么|怎么|如何|什么|是不是|能不能|有没有|哪)")
_OPENER = re.compile(r"^\s*(深度解析|深读|深度阅读|解读)[:：]?\s*\S+\s*$")


def ref_of(iid: int) -> str:
    return f"learn:item:{iid}"


def _key(url: str) -> str:
    """同一篇的链接归一：X 的分享链接带 ?s=20&t=…，twitter.com 和 x.com 是同一个。"""
    k = norm_url(url)
    host, _, rest = k.partition("/")
    if host in ("x.com", "twitter.com", "mobile.twitter.com"):
        return "x.com/" + rest.split("?", 1)[0]
    return k


def _same(a: str, b: str) -> bool:
    return bool(a and b) and _key(a) == _key(b)


def find_item(url: str) -> dict | None:
    """同一链接已有的条目（失败的不算，重新开一个）。"""
    for it in db.rows("SELECT * FROM learn_items WHERE status!='failed' ORDER BY id DESC"):
        if _same(it["url"], url):
            return it
    return None


def _session_url(s: dict) -> str:
    m = re.search(r"https?://\S+", s.get("title") or "")
    if not m:
        return ""
    first = db.row("SELECT content FROM chat_messages WHERE session_id=? AND role='user' ORDER BY id LIMIT 1", [s["id"]])
    m2 = re.search(r"https?://[^\s，。、）)]+", (first or {}).get("content") or "")
    return (m2 or m).group(0)


def _loose_sessions() -> list[dict]:
    """学习板块里没绑定对象、开头是「深度解析：链接」的对话。"""
    return [s for s in db.rows("SELECT * FROM chat_sessions WHERE module='learn' AND COALESCE(ref,'')='' ORDER BY id")
            if re.match(r"\s*(深度解析|深读|深度阅读|解读)[:：]", s.get("title") or "")]


def bind_chats(it: dict) -> int:
    """把以前对同一链接的「深度解析」对话挂到这个条目上，条目页的追问就能续上。"""
    n = 0
    for s in _loose_sessions():
        if _same(_session_url(s), it["url"]):
            db.update("chat_sessions", s["id"], {"ref": ref_of(it["id"])})
            n += 1
    return n


def md_title(md: str) -> str:
    """文档第一个标题，去掉「深度解析：」这类前缀。"""
    t = next((ln.lstrip("# ").strip() for ln in md.splitlines() if ln.startswith("#")), "")
    return re.sub(r"^(深度解析|深读|深度阅读|解读)[:：]\s*", "", t)[:200]


def import_chat_reads(out_root: Path, detect_kind, slugify, tldr_from_md) -> list[int]:
    """在对话里直接做的深度解析，补成深读条目：有条目的认领过去；没有的用 Agent 那次的回复当 note.md（不重跑）。
    只加条目、改对话的绑定，不动对话内容；绑定过的对话不会再处理，所以可以反复调用。"""
    made = []
    for s in _loose_sessions():
        url = _session_url(s)
        if not url:
            continue
        it = find_item(url)
        if not it:
            reply = max((m["content"] for m in db.rows("SELECT content FROM chat_messages WHERE session_id=? AND role='assistant'", [s["id"]])),
                        key=len, default="")
            if len(reply) < 400:  # 没写出像样的解读，留给用户自己决定要不要深读
                continue
            title = md_title(reply)
            kind = detect_kind(url)
            iid = db.insert("learn_items", {"kind": kind, "url": url, "title": title, "focus": "", "depth": "quick", "status": "done",
                                            "summary": tldr_from_md(reply), "created_at": s["created_at"], "updated_at": s["updated_at"]})
            d = out_root / f"{iid}-{slugify(url)}"
            d.mkdir(parents=True, exist_ok=True)
            (d / "note.md").write_text(reply, "utf-8")
            db.update("learn_items", iid, {"output_path": str(d / "note.md")})
            it = db.row("SELECT * FROM learn_items WHERE id=?", [iid])
            made.append(iid)
        db.update("chat_sessions", s["id"], {"ref": ref_of(it["id"])})
        if (s.get("created_at") or "")[:10] == db.today():
            ensure_task(it, date=db.today())
            sync_task(it["id"])
    return made


# ---------- 追问与感想 ----------

def user_lines(iid: int, date: str = "") -> list[dict]:
    rows = db.rows("SELECT m.content, m.created_at FROM chat_messages m JOIN chat_sessions s ON s.id=m.session_id "
                   "WHERE s.ref=? AND m.role='user' ORDER BY m.id", [ref_of(iid)])
    out = []
    for r in rows:
        t = (r["content"] or "").strip()
        if not t or _OPENER.match(t) or len(t) < 4:
            continue
        if date and (r["created_at"] or "")[:10] != date:
            continue
        out.append({"text": t, "at": r["created_at"] or "", "kind": "ask" if _ASK.search(t) else "thought"})
    return out


def qa_answers(it: dict | None) -> list[dict]:
    """追问清单里写过作答的题（含 Agent 点评），按编号排。"""
    try:
        qa = json.loads((it or {}).get("qa") or "{}")
    except (TypeError, ValueError):
        return []
    return sorted((v for v in qa.values() if isinstance(v, dict) and (v.get("answer") or "").strip()), key=lambda v: v.get("at", ""))


def kb_section(iid: int) -> str:
    ls = user_lines(iid)
    answered = qa_answers(db.row("SELECT * FROM learn_items WHERE id=?", [iid]))
    if not ls and not answered:
        return ""
    asks = [x for x in ls if x["kind"] == "ask"]
    thoughts = [x for x in ls if x["kind"] == "thought"]
    body = ["\n## 追问与感想"]
    if thoughts:
        body += ["### 感想"] + [f"- {x['at'][:16].replace('T', ' ')} {x['text']}" for x in thoughts]
    if asks:
        body += ["### 追问"] + [f"- {x['at'][:16].replace('T', ' ')} {x['text']}" for x in asks]
    if answered:
        body.append("### 追问清单作答")
        for v in answered:
            rv = v.get("review") or {}
            body.append(f"- **{v.get('q', '')}**\n  我答：{v['answer']}"
                        + (f"\n  Agent 点评 {round(100 * float(rv.get('score') or 0))}%：{rv.get('better', '')}" if rv else ""))
    return "\n".join(body)


# ---------- 当天的深读事项 ----------

def task_of(iid: int) -> dict | None:
    return db.row("SELECT * FROM tasks WHERE notes LIKE ? ORDER BY id DESC LIMIT 1", [f"%{TAG}{iid} %"])


def ensure_task(it: dict, date: str = "") -> dict | None:
    t = task_of(it["id"])
    if t:
        return t
    return tasks.create({"date": date or db.today(), "title": f"深读：{(it.get('title') or it['url'])[:60]}", "kind": "learning",
                         "est_minutes": 30, "priority": 3, "human_level": "high", "status": "doing", "progress": 10,
                         "goal": "读完深读文档，在条目页追问或写下感想 / 笔记（会进复盘和知识库）",
                         "notes": f"{TAG}{it['id']} #learn/item/{it['id']}"})


def sync_task(iid: int) -> None:
    """文档好了算一半；追问 / 写感想 / 答追问清单 / 写笔记 / 打分算读完。只往前推，不改用户手动设的完成或放弃。"""
    t = task_of(iid)
    it = db.row("SELECT * FROM learn_items WHERE id=?", [iid])
    if not t or not it or t["status"] in ("done", "dropped"):
        return
    engaged = bool(user_lines(iid)) or bool(qa_answers(it)) or bool((it.get("my_notes") or "").strip()) or bool(it.get("rating"))
    if engaged:
        tasks.patch(t["id"], {"status": "done", "progress": 100})
    elif it["status"] == "done" and (t.get("progress") or 0) < 50:
        tasks.patch(t["id"], {"progress": 50})
    if it.get("title") and t["title"] == f"深读：{it['url'][:60]}":  # 开始时只有链接，生成好后换成标题
        tasks.patch(t["id"], {"title": f"深读：{it['title'][:60]}"})


def day_reads(date: str) -> list[dict]:
    """这一天有动静的深读：当天开始、当天生成好，或当天在条目对话里追问 / 写了感想。"""
    ids = {r["id"] for r in db.rows("SELECT id FROM learn_items WHERE substr(created_at,1,10)=? OR (status='done' AND substr(updated_at,1,10)=?)",
                                    [date, date])}
    ids |= {int(r["ref"].rsplit(":", 1)[1]) for r in db.rows(
        "SELECT DISTINCT s.ref FROM chat_sessions s JOIN chat_messages m ON m.session_id=s.id "
        "WHERE s.ref LIKE 'learn:item:%' AND m.role='user' AND substr(m.created_at,1,10)=?", [date])}
    out = []
    for iid in sorted(ids):
        it = db.row("SELECT id, kind, title, url, status, rating, my_notes FROM learn_items WHERE id=?", [iid])
        if not it:
            continue
        ls = user_lines(iid, date)
        out.append({**it, "asks": sum(x["kind"] == "ask" for x in ls),
                    "thoughts": [x["text"][:200] for x in ls if x["kind"] == "thought"][:5]})
    return out


def day_lines(date: str) -> list[str]:
    out = []
    for r in day_reads(date):
        s = f"深读「{r['title'] or r['url']}」（{r['kind']}，{r['status']}）"
        if r["asks"]:
            s += f"；追问 {r['asks']} 次"
        if r["thoughts"]:
            s += "；感想：" + " / ".join(r["thoughts"])
        out.append(s)
    return out
