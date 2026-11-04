"""规划页「我提交的任务」：各类任务的进展要按真实情况归类，不能照抄板块里停住的 status。"""
from app import db


def _new_job(status="running", log="", ref="x"):
    return db.insert("jobs", {"module": "learn", "ref": ref, "engine": "claude", "prompt": "p", "status": status,
                              "log": log, "created_at": db.now()})


def _research(topic, results, **kw):
    rid = db.insert("research", {"topic": topic, "engines": "[]", "angles": "[]", "status": "running", "created_at": db.now(), **kw})
    for engine, status, job in results:
        db.insert("research_results", {"research_id": rid, "engine": engine, "status": status, "job_id": job, "created_at": db.now()})
    return rid


def _find(client, link):
    d = client.get("/api/plan/submitted").json()
    return next(x for x in d["items"] if x["link"] == link), d


def test_research_states(client):
    running = _research("进行中", [("claude", "running", _new_job(log="[tool] WebSearch foo\n[tool] Read bar")), ("codex", "done", None)])
    x, _ = _find(client, f"#research/r/{running}")
    assert x["state"] == "running" and "1/2" in x["detail"] and "已 2 步" in x["detail"] and "Read bar" in x["detail"]

    timeout = _research("超时", [("claude", "done", None), ("grokbot", "timeout", None)])  # 板块里一直是 running
    x, _ = _find(client, f"#research/r/{timeout}")
    assert x["state"] == "needs" and "GrokBot" in x["detail"]

    paste = _research("待粘贴", [("muse", "awaiting_paste", None)])
    assert _find(client, f"#research/r/{paste}")[0]["state"] == "needs"

    no_synth = _research("待综合", [("claude", "done", None), ("codex", "done", None)])
    x, _ = _find(client, f"#research/r/{no_synth}")
    assert x["state"] == "needs" and "综合" in x["detail"]

    single = _research("单引擎", [("claude", "done", None)])
    assert _find(client, f"#research/r/{single}")[0]["state"] == "done"

    synth = _research("已综合", [("claude", "done", None), ("codex", "done", None)], synthesis="结论", synth_status="done")
    x, _ = _find(client, f"#research/r/{synth}")
    assert x["state"] == "done" and x["detail"] == "已综合"

    # runner 被杀：结果表还写着 running，job 已经失败，不能算进行中
    dead = _research("中断", [("claude", "running", _new_job(status="failed"))])
    assert _find(client, f"#research/r/{dead}")[0]["state"] == "needs"


def _read(**kw):
    return db.insert("learn_items", {"kind": "article", "url": "http://x/y", "title": "文章", "status": "done", "created_at": db.now(), **kw})


def test_read_states(client):
    live = _read(status="running", job_id=_new_job(status="queued"))
    assert _find(client, f"#learn/item/{live}")[0]["state"] == "running"

    dead = _read(status="running", job_id=_new_job(status="failed"))
    x, _ = _find(client, f"#learn/item/{dead}")
    assert x["state"] == "needs" and "中断" in x["detail"]

    assert _find(client, f"#learn/item/{_read()}")[0]["state"] == "ready"
    assert _find(client, f"#learn/item/{_read(rating=3)}")[0]["state"] == "done"

    done = _read()
    db.insert("tasks", {"date": db.today(), "title": "深读：文章", "status": "done", "notes": f"deepread:item:{done} #learn/item/{done}"})
    assert _find(client, f"#learn/item/{done}")[0]["state"] == "done"

    x, _ = _find(client, f"#learn/item/{_read(dd_status='running', dd_job=_new_job(), dd_stage='map')}/deepdive")
    assert x["state"] == "running" and "深度解读" in x["detail"]


def _plan(status="active", steps=(), **kw):
    pid = db.insert("learn_plans", {"topic": "主题", "status": status, "created_at": db.now(), **kw})
    for i, st in enumerate(steps):
        db.insert("learn_steps", {"plan_id": pid, "status": st, "title": f"s{i}", "stage": 1, "ord": i})
    return pid


def test_plan_states(client):
    x, _ = _find(client, f"#learn/plan/{_plan(steps=['done', 'todo', 'todo', 'skipped'])}")
    assert x["state"] == "ready" and x["pct"] == 33 and "1/3" in x["detail"]
    x, _ = _find(client, f"#learn/plan/{_plan(steps=['todo'])}")
    assert x["state"] == "ready" and "还没开始" in x["detail"]
    assert _find(client, f"#learn/plan/{_plan(steps=['done'])}")[0]["state"] == "done"
    assert _find(client, f"#learn/plan/{_plan('generating', job_id=_new_job())}")[0]["state"] == "running"
    assert _find(client, f"#learn/plan/{_plan('generating', job_id=_new_job(status='failed'))}")[0]["state"] == "needs"
    archived = _plan("archived")
    assert all(x["link"] != f"#learn/plan/{archived}" for x in client.get("/api/plan/submitted").json()["items"])


def test_book_states(client):
    bid = db.insert("learn_books", {"url": "/a.pdf", "title": "书", "status": "ready", "cur_idx": 1, "created_at": db.now()})
    for i in range(4):
        db.insert("learn_book_chapters", {"book_id": bid, "idx": i, "title": f"c{i}"})
    x, _ = _find(client, f"#learn/book/{bid}")
    assert x["state"] == "ready" and x["pct"] == 50 and "2/4" in x["detail"]
    bad = db.insert("learn_books", {"url": "/b.pdf", "status": "failed", "error": "打不开", "created_at": db.now()})
    assert _find(client, f"#learn/book/{bad}")[0]["state"] == "needs"
    parsing = db.insert("learn_books", {"url": "/c.pdf", "status": "ingesting", "created_at": db.now()})
    assert _find(client, f"#learn/book/{parsing}")[0]["state"] == "running"


def test_order_and_counts(client):
    d = client.get("/api/plan/submitted").json()
    order = ["needs", "running", "ready", "done"]
    ranks = [order.index(x["state"]) for x in d["items"]]
    assert ranks == sorted(ranks)
    assert sum(d["counts"].values()) == len(d["items"])
