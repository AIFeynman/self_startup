"""我提交的任务 · 规划页的总览：调研、深读、学习计划、读书提交过哪些、各到哪一步，点一行进到各自的页面。

只读各板块已有的表，不改状态。不直接用板块自己的 status：
    runner 被杀（reap）不回调板块，条目会一直停在 running —— 这里按 job 状态判断
    调研有引擎超时，状态一直是 running；全部引擎完成但没综合，也算 done —— 这里按各引擎结果判断

state：running 进行中 / needs 等你处理 / ready 可以看了（生成好没读、计划在学）/ done 已看完

关闭只记在 plan_submitted_closed，不动板块自己的数据。关闭后又跑起来的（比如重试）照常显示，跑完回到已关闭。
"""
from __future__ import annotations

from .. import db, jobs

ORDER = ["needs", "running", "ready", "done"]
READ_KIND = {"paper": "论文", "github": "项目", "article": "文章", "video": "视频"}
ENGINE = {"claude": "Claude", "codex": "Codex", "grokbot": "GrokBot", "muse": "Muse"}
_LIVE = ("queued", "running")


def _clip(s: str, n: int = 60) -> str:
    s = " ".join((s or "").split())
    return s if len(s) <= n else s[:n - 1] + "…"


class _Jobs:
    """这次请求里的 job：跟到续接后的最新一轮；进行中的给一句「到哪一步」。机器状态只在有排队时看一次。"""

    def __init__(self):
        self._busy: dict | None = None

    def status(self, jid: int | None) -> dict:
        if not jid:
            return {}
        return jobs.chain_tip(jid)[0] or {}

    def _machine(self) -> dict:
        if self._busy is None:
            self._busy = jobs.machine()
        return self._busy

    def brief(self, j: dict) -> str:
        if j.get("status") == "queued":
            m = self._machine()
            return "排队中" if m["ok"] else f"机器忙，排队中（{m['reason']}）"
        if j.get("status") != "running":
            return ""
        steps = [ln[7:] for ln in (j.get("log") or "").split("\n") if ln.startswith("[tool] ")]
        return f"已 {len(steps)} 步 · 正在：{_clip(steps[-1], 50)}" if steps else "启动中"


def _item(type_: str, id_: int, label: str, title: str, state: str, detail: str, link: str, created: str, pct: int | None = None) -> dict:
    return {"key": f"{type_}:{id_}", "type": type_, "label": label, "title": title, "state": state, "detail": detail,
            "link": link, "created_at": created or "", "pct": pct}


def _research(js: _Jobs) -> list[dict]:
    from . import research as rs
    out = []
    rows = db.rows("SELECT id,topic,synthesis,synth_status,synth_job_id,created_at FROM research ORDER BY id DESC LIMIT 200")
    for r in rows:
        res = db.rows("SELECT engine,status,job_id FROM research_results WHERE research_id=? ORDER BY id", [r["id"]])
        live, ending, stopped = [], [], False
        for x in res:
            name = ENGINE.get(x["engine"], x["engine"])
            j = js.status(x["job_id"]) if x["status"] in rs.PENDING else {}
            if j and j.get("status") not in _LIVE:  # runner 中断 / 暂停：结果表还停在进行中
                x["status"], stopped = "failed", True
            elif x["status"] == "awaiting_login":
                ending.append(f"{name} 等你登录")
            elif x["status"] in rs.PENDING:
                brief = js.brief(j)
                live.append(f"{name}：{brief}" if brief else f"{name} 进行中")
            elif x["status"] == "awaiting_paste":
                ending.append(f"{name} 等你粘贴回答")
            elif x["status"] == "timeout":
                ending.append(f"{name} 等待超时，可继续等或重试")
        n_done = sum(x["status"] == "done" for x in res)
        have = f"{n_done}/{len(res)} 个引擎完成"
        synth = js.status(r["synth_job_id"]) if r["synth_status"] == "running" else {}
        if synth and synth.get("status") in _LIVE:
            state, detail = "running", f"正在综合 · {js.brief(synth)}"
        elif live:
            state, detail = "running", " · ".join([have, *live])
        elif ending:
            state, detail = "needs", " · ".join([have, *ending])
        elif res and not n_done:
            state, detail = "needs", "全部引擎失败，可打开重试"
        elif r["synth_status"] == "failed" or synth:
            state, detail = "needs", f"{have} · 综合失败，可重试"
        elif n_done >= 2 and not r["synthesis"]:
            state, detail = "needs", f"{have} · 还没综合，打开点「综合」"
        else:
            state, detail = "done", "已综合" if r["synthesis"] else have
            if stopped or n_done < len(res):
                detail += f" · {len(res) - n_done} 个引擎失败"
        out.append(_item("research", r["id"], "调研", r["topic"], state, detail, f"#research/r/{r['id']}", r["created_at"]))
    return out


def _deep_reads(js: _Jobs) -> list[dict]:
    from . import _reads as reads, learn
    learn._ensure_depth_col()
    read = {int(t["notes"].split(reads.TAG, 1)[1].split()[0]): t["status"]
            for t in db.rows("SELECT notes,status FROM tasks WHERE notes LIKE ?", [f"%{reads.TAG}%"])}
    out = []
    rows = db.rows("SELECT id,kind,url,title,status,job_id,my_notes,rating,dd_status,dd_stage,dd_job,dd_error,created_at FROM learn_items "
                   "ORDER BY id DESC LIMIT 300")
    for it in rows:
        link = f"#learn/item/{it['id']}"
        kind = READ_KIND.get(it["kind"], "深读")
        title = it["title"] or it["url"]
        if it["status"] in _LIVE:
            j = js.status(it["job_id"])
            if j and j.get("status") not in _LIVE:
                state, detail = "needs", "已暂停，可在复盘 · Agent 效率的看板继续" if j["status"] == "paused" else "任务中断，打开可重新生成"
            else:
                state, detail = "running", f"生成深读笔记 · {js.brief(j)}" if j else "生成深读笔记"
        elif it["status"] == "failed":
            state, detail = "needs", "生成失败，打开可重新生成"
        elif it.get("dd_status") == "running" and (dd := js.status(it["dd_job"])).get("status") in _LIVE:
            state, detail, link = "running", f"深度解读 {it['dd_stage'] or ''} · {js.brief(dd)}", link + "/deepdive"
        elif it.get("dd_status") == "failed":
            state, detail, link = "needs", f"深度解读失败：{_clip(it['dd_error'], 40)}", link + "/deepdive"
        elif read.get(it["id"]) == "done" or (it["my_notes"] or "").strip() or it["rating"]:
            state, detail = "done", "已读"
        else:
            state, detail = "ready", "笔记已生成，待读"
        out.append(_item("read", it["id"], f"深读·{kind}", title, state, detail, link, it["created_at"]))
    return out


def _plans(js: _Jobs) -> list[dict]:
    steps: dict[int, list[int]] = {}
    for s in db.rows("SELECT plan_id, sum(status='done') d, sum(status!='skipped') n FROM learn_steps GROUP BY plan_id"):
        steps[s["plan_id"]] = [s["d"] or 0, s["n"] or 0]
    out = []
    for p in db.rows("SELECT id,topic,status,job_id,created_at FROM learn_plans WHERE status!='archived' ORDER BY id DESC LIMIT 100"):
        link = f"#learn/plan/{p['id']}"
        d, n = steps.get(p["id"], [0, 0])
        pct = round(100 * d / n) if n else None
        if p["status"] in ("generating", "adapting"):
            j = js.status(p["job_id"])
            what = "生成计划" if p["status"] == "generating" else "调整计划"
            if j and j.get("status") not in _LIVE:
                state, detail = "needs", f"{what}中断，打开可重试"
            else:
                state, detail = "running", f"{what} · {js.brief(j)}" if j else what
        elif p["status"] == "failed":
            state, detail = "needs", "生成失败，打开可重试"
        elif n and d >= n or p["status"] == "done":
            state, detail = "done", f"学完 {d}/{n} 步"
        else:
            state, detail = "ready", f"学到 {d}/{n} 步" if d else f"还没开始，共 {n} 步"
        out.append(_item("plan", p["id"], "学习计划", p["topic"], state, detail, link, p["created_at"], pct))
    return out


def _books(js: _Jobs) -> list[dict]:
    out = []
    rows = db.rows("SELECT b.id,b.url,b.title,b.status,b.error,b.overview_status,b.overview_job,b.cur_idx,b.created_at,"
                   "(SELECT count(*) FROM learn_book_chapters c WHERE c.book_id=b.id) n FROM learn_books b ORDER BY b.id DESC LIMIT 100")
    for b in rows:
        link = f"#learn/book/{b['id']}"
        n, at = b["n"] or 0, (b["cur_idx"] or 0) + 1
        pct = round(100 * at / n) if n else None
        if b["status"] == "failed":
            state, detail = "needs", f"解析失败：{_clip(b['error'], 40)}"
        elif b["status"] != "ready":
            state, detail, pct = "running", "解析目录", None
        elif b["overview_status"] == "generating" and (j := js.status(b["overview_job"])).get("status") in _LIVE:
            state, detail, pct = "running", f"生成全书导读 · {js.brief(j)}", None
        else:
            state, detail = "ready", f"读到第 {at}/{n} 篇" if at > 1 else f"共 {n} 篇，从头开始"
        out.append(_item("book", b["id"], "读书", b["title"] or b["url"], state, detail, link, b["created_at"], pct))
    return out


def collect() -> dict:
    """全部提交过的任务，按 等你处理 → 进行中 → 可以看了 → 已看完，同组新提交的在前。已关闭的带 closed，不计入各组。"""
    js = _Jobs()
    closed = {r["key"] for r in db.rows("SELECT key FROM plan_submitted_closed")}
    items = [*_research(js), *_deep_reads(js), *_plans(js), *_books(js)]
    for x in items:
        x["closed"] = x["key"] in closed and x["state"] != "running"
    items.sort(key=lambda x: x["created_at"], reverse=True)
    items.sort(key=lambda x: ORDER.index(x["state"]))
    counts = {s: sum(x["state"] == s and not x["closed"] for x in items) for s in ORDER}
    counts["closed"] = sum(x["closed"] for x in items)
    return {"items": items, "counts": counts}


def set_closed(key: str, closed: bool) -> None:
    if closed:
        db.execute("INSERT OR IGNORE INTO plan_submitted_closed(key,closed_at) VALUES(?,?)", [key, db.now()])
    else:
        db.execute("DELETE FROM plan_submitted_closed WHERE key=?", [key])
