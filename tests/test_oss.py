"""开源雷达：入库、标注校验 / 重问 / 续跑、检索（召回 + 精排 + 缓存 + 按 star）、接口、信息推荐反向复用。不联网。"""
import json
from datetime import datetime, timezone

import pytest

from app import db
from app.modules import _oss_collect as col, _oss_label as lab, _oss_search as srch


def raw(name, stars, desc="", topics=(), lang="Python", **kw):
    return {"full_name": name, "description": desc, "stargazers_count": stars, "language": lang, "topics": list(topics),
            "created_at": "2024-01-01T00:00:00Z", "pushed_at": "2026-10-30T00:00:00Z", "node_id": "N_" + name,
            "html_url": f"https://github.com/{name}", **kw}


REPOS = [
    raw("a/pdfx", 5000, "Parse PDF documents into markdown", ["pdf", "parser"]),
    raw("b/ocrkit", 3000, "OCR toolkit for scanned documents", ["ocr"]),
    raw("c/webui", 20000, "A web UI framework", ["frontend"], lang="TypeScript"),
    raw("d/caveman", 1500, "Turn any document into clean text for LLM", ["llm"]),
]
LABELS = {
    "a/pdfx": {"k": "library", "d": "doc_parsing", "ai": "for_ai", "t": ["PDF 解析", "PDF 转 Markdown"], "s": "把 PDF 解析成 Markdown"},
    "b/ocrkit": {"k": "library", "d": "cv", "ai": "core", "t": ["OCR", "文字识别"], "s": "扫描件文字识别"},
    "c/webui": {"k": "framework", "d": "frontend", "ai": "none", "t": ["前端组件", "Web UI"], "s": "Web 前端组件框架"},
    "d/caveman": {"k": "app", "d": "doc_parsing", "ai": "for_ai", "t": ["文档转文本", "PDF 解析"], "s": "把文档转成给大模型用的纯文本"},
}


@pytest.fixture(autouse=True)
def _clean(client):
    for t in ("oss_repos", "oss_labels", "oss_fts", "oss_query_cache", "oss_runs"):
        db.execute(f"DELETE FROM {t}")
    lab.taxonomy.cache_clear()


def fake_cli(drop=(), bad=()):
    """按 prompt 里的仓库输出 JSON Lines；drop 里的第一次漏掉，bad 里的第一次给非法 code。"""
    calls = []

    def call(prompt):
        rows = [json.loads(x) for x in prompt.split("\n")[1:]]
        calls.append([r["name"] for r in rows])
        lines = []
        for r in rows:
            if r["name"] in drop and len(calls) == 1:
                continue
            lb = dict(LABELS[r["name"]])
            if r["name"] in bad and len(calls) == 1:
                lb["d"] = "no_such_domain"
            lines.append(json.dumps({"i": r["i"], **lb, "d2": []}, ensure_ascii=False))
        return {"result": "\n".join(lines), "total_cost_usd": 0.01}
    call.calls = calls
    return call


def test_engine_default_deepseek_and_switch(monkeypatch):
    assert lab.engine() == "deepseek"
    monkeypatch.setattr(lab.settings, "get", lambda k, d=None: "haiku" if k == "oss.label_engine" else d)
    assert lab.engine() == "haiku"
    monkeypatch.setattr(lab.settings, "get", lambda k, d=None: "gpt" if k == "oss.label_engine" else d)
    assert lab.engine() == "deepseek"   # 不认识的引擎回落到默认


def test_deepseek_call_cost_and_prompt(monkeypatch):
    sent = {}

    class R:
        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": '{"i":0}'}}],
                    "usage": {"prompt_tokens": 13000, "prompt_cache_hit_tokens": 12000, "completion_tokens": 1000}}

    def post(url, **kw):
        sent.update(url=url, **kw)
        return R()
    monkeypatch.setenv("DEEPSEEK_API_KEY", "k")
    monkeypatch.setattr(lab.httpx, "post", post)
    out = lab._deepseek("仓库：x")
    assert sent["url"].endswith("/chat/completions") and sent["json"]["thinking"] == {"type": "disabled"}
    assert "5-8 个" in sent["json"]["messages"][0]["content"]          # 调过的补充规则带上了
    assert out["total_cost_usd"] == pytest.approx(12000 * 0.0028e-6 + 1000 * 0.14e-6 + 1000 * 0.28e-6)
    monkeypatch.delenv("DEEPSEEK_API_KEY")
    with pytest.raises(RuntimeError):
        lab._deepseek("x")


def test_taxonomy_codes_cover_test_labels():
    cs = lab.codes()
    for lb in LABELS.values():
        assert lb["k"] in cs["k"] and lb["d"] in cs["d"] and lb["ai"] in cs["ai"]


def test_upsert_threshold_fork_and_rename():
    assert col.upsert(REPOS + [raw("e/small", 500), raw("f/forked", 9000, fork=True)], "slice") == [r["full_name"] for r in REPOS]
    # 改名：node_id 相同，名字换了 → 更新原行，不新增
    assert col.upsert([raw("a/pdfx2", 5100, node_id="N_a/pdfx")], "new") == []
    assert db.row("SELECT name, stars FROM oss_repos WHERE node_id='N_a/pdfx'") == {"name": "a/pdfx2", "stars": 5100}


def test_clean_readme():
    md = "# Title\n[![ci](https://x/badge.svg)](https://x)\n<p align=center><img src=a.png></p>\nParse [PDF](https://p) files.\n```py\ncode()\n```"
    t = col.clean_readme(md)
    assert "Parse PDF files" in t and "badge" not in t and "code()" not in t and "<" not in t


def test_label_validate_retry_and_resume():
    col.upsert(REPOS, "slice")
    db.execute("UPDATE oss_repos SET readme_oid=''")   # 当作已取过 README
    call = fake_cli(drop={"b/ocrkit"}, bad={"c/webui"})
    st = lab.run(call=call, batch=50, parallel=1)
    assert st["labeled"] == 4 and st["cost"] == 0.02
    assert sorted(call.calls[1]) == ["b/ocrkit", "c/webui"]          # 漏的和不合格的单独重问
    assert db.row("SELECT d FROM oss_labels WHERE name='c/webui'")["d"] == "frontend"
    assert lab.todo() == []                                            # 内容没变：不再进队列
    db.execute("UPDATE oss_repos SET descr='new desc' WHERE name='a/pdfx'")
    db.execute("UPDATE oss_repos SET stars=4000 WHERE name='d/caveman'")   # star 翻倍也重标
    assert {r["name"] for r in lab.todo()} == {"a/pdfx", "d/caveman"}


def _setup():
    col.upsert(REPOS, "slice")
    db.execute("UPDATE oss_repos SET readme_oid=''")
    lab.run(call=fake_cli(), parallel=1)


def fake_chat(rr=None):
    calls = []

    def chat(system, user, max_tokens=2000, client=None):
        calls.append(system[:10])
        if "改写" in system:
            return {"must": ["PDF 解析", "pdf parse"], "should": ["markdown"], "not": ["OCR"], "domains": ["doc_parsing"], "kinds": []}
        names = [json.loads(x)["name"] for x in user.split("\n")[2:]]
        return {str(i): (rr or {}).get(n, [0, ""]) for i, n in enumerate(names)}
    chat.calls = calls
    return chat


def test_search_rerank_cache_and_stars_mode():
    _setup()
    chat = fake_chat({"a/pdfx": [3, "直接解析 PDF"], "d/caveman": [2, "能把 PDF 转文本"], "b/ocrkit": [1, ""]})
    r = srch.search("我想做PDF解析", chat=chat)
    names = [x["name"] for x in r["results"]]
    assert r["reranked"] and names[0] == "a/pdfx" and "c/webui" not in names
    assert r["results"][0]["why"] == "直接解析 PDF"
    # 按 star：只留精排 ≥2 的，按 star 排
    r2 = srch.search("我想做PDF解析", by="stars", chat=chat)
    assert [x["name"] for x in r2["results"]] == ["a/pdfx", "d/caveman"]
    assert len(chat.calls) == 2                                          # 第二次走缓存，不再调模型
    assert [x["name"] for x in srch.search("我想做PDF解析", kind="app", chat=chat)["results"]] == ["d/caveman"]


def test_search_without_llm_falls_back():
    _setup()

    def broken(*a, **k):
        raise RuntimeError("no key")
    r = srch.search("PDF 解析", chat=broken, use_cache=False)
    assert not r["reranked"] and r["errors"]
    assert {x["name"] for x in r["results"][:2]} == {"a/pdfx", "d/caveman"}
    assert db.row("SELECT count(*) AS n FROM oss_query_cache")["n"] == 0   # 失败的结果不缓存


def test_api_browse_status_and_run_guard(client, monkeypatch):
    _setup()
    b = client.get("/api/intel/oss/search", params={"domain": "doc_parsing"}).json()
    assert b["mode"] == "browse" and [x["name"] for x in b["results"]] == ["a/pdfx", "d/caveman"]
    st = client.get("/api/intel/oss/status").json()
    assert st["repos"] == 4 and st["labeled"] == 4 and st["todo"] == 0 and st["by_domain"]["doc_parsing"] == 2
    from app.modules import _oss_radar as intel
    spawned = []
    monkeypatch.setattr(intel, "_spawn", lambda rid: spawned.append(rid))
    run = client.post("/api/intel/oss/runs", json={"task": "label", "limit": 10}).json()
    assert spawned == [run["id"]] and json.loads(run["progress"]) == {"limit": 10}
    assert client.post("/api/intel/oss/runs", json={"task": "daily"}).status_code == 409   # 同时只跑一个
    assert client.post(f"/api/intel/oss/runs/{run['id']}/stop").json()["status"] == "stopped"
    assert client.post("/api/intel/oss/runs", json={"task": "nope"}).status_code == 400


def test_schedule_only_after_library_exists(monkeypatch):
    from app.modules import _oss_radar as intel
    spawned = []
    monkeypatch.setattr(intel, "_spawn", lambda rid: spawned.append(rid))
    assert intel.maybe_schedule() == ""          # 没标注过：不自动跑（全量只手动开）
    _setup()
    assert intel.maybe_schedule() == "weekly"
    db.execute("UPDATE oss_runs SET status='done'")
    assert intel.maybe_schedule() == "daily"
    db.execute("UPDATE oss_runs SET status='done'")
    assert intel.maybe_schedule() == ""


def test_feed_reuses_radar_labels(monkeypatch):
    from app.modules import feed
    _setup()
    db.execute("DELETE FROM feed_items")
    for name, title in (("c/webui", "webui：A web UI framework"), ("z/unknown", "unknown：something")):
        db.insert("feed_items", {"id": f"github:{name}", "source": "github", "type": "repo", "title": title, "summary": "",
                                 "url": "", "date": "2026-11-01T00:00:00+00:00", "popularity": 20000,
                                 "extra": {"repo": name, "trending": True}, "fetched_at": db.now()})
    asked = []
    monkeypatch.setattr(feed.judge, "judge", lambda todo, **k: (asked.extend(it["id"] for it, _, _ in todo) or {}, []))
    feed.run_judge(now=datetime(2026, 11, 2, tzinfo=timezone.utc))   # 固定时间：条目日期写死，超过 PIN_DAYS 就不判了
    assert asked == ["github:z/unknown"]                       # 库里有的不再问 Jev
    ex = json.loads(db.row("SELECT extra FROM feed_items WHERE id='github:c/webui'")["extra"])
    assert ex["judge_ai"] == 0.0 and ex["judge_by"] == "oss" and ex["oss"]["d"] == "frontend"


def test_gql_nodes_splits_on_github_timeout(monkeypatch):
    """一批太大 GitHub 回 502：对半拆开再查，结果合起来不丢仓库。"""
    sizes = []

    def fake(c, q, v):
        ids = v["ids"]
        sizes.append(len(ids))
        if len(ids) > 25:
            raise col.GqlTimeout("GraphQL 502")
        return {"data": {"nodes": [{"id": i} for i in ids]}}
    monkeypatch.setattr(col, "_gql", fake)
    ids = [f"N{i}" for i in range(100)]
    got = col.gql_nodes(None, ids, with_text=False)
    assert list(got) == ids and all(got[i] == {"id": i} for i in ids)
    assert sizes[:3] == [100, 50, 25]


def test_validate_bad_kind_or_domain_falls_back():
    x = {"k": "lang_runtime", "d": "lang_runtime", "ai": "none", "t": ["Go 编译器"], "s": "Go 语言官方仓库"}
    assert lab.validate(x) is None                                # 第一轮严格：填错就重问
    assert lab.validate(x, lenient=True)["k"] == "other"          # 重问时 kind 填成领域 code：不丢整条
    y = lab.validate({**x, "d": "template", "d2": ["frontend", "frontend", "mobile"]}, lenient=True)
    assert (y["d"], y["d2"]) == ("frontend", ["mobile"])          # 领域填成 kind code：取副领域
    assert lab.validate({**x, "d": "template"}, lenient=True)["d"] == "other"
    assert lab.validate({**x, "ai": "maybe"}, lenient=True) is None   # AI 关系错仍然不收


def test_recall_spacing_variant_primary_domain_and_generic_atoms(monkeypatch):
    _setup()
    assert set(srch.hits("pdf转markdown")) == set(srch.hits("pdf 转 markdown")) != set()   # 中英交界补空格
    it = {"must": ["无关说法"], "should": [], "not": [], "domains": ["cv", "doc_parsing"], "kinds": []}
    rel = {d["name"]: d["rel"] for d in srch.recall(it)}
    assert rel["b/ocrkit"] > rel["a/pdfx"]                       # 第一个领域加满分，其余减半
    it = {"must": ["无关说法"], "should": ["parse markdown"], "not": [], "domains": [], "kinds": []}
    assert "a/pdfx" in {d["name"] for d in srch.recall(it)}       # 两个词都命中 → 召回
    monkeypatch.setattr(srch, "ATOM_MAX_HITS", 0)                 # 两个词都超过上限，当泛词
    assert "a/pdfx" not in {d["name"] for d in srch.recall(it)}
