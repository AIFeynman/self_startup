"""HN 吸收：采帖门槛、共识度分级、话题综合的引用检查、资源去重。不触网、不调 LLM。"""
from app.modules import _absorb_hn as hn


def _p(**k):
    return {"title": "x", "points": 0, "comments": 0, **k}


def test_keep_thresholds():
    assert hn.keep(_p(points=50)) and hn.keep(_p(comments=40))
    assert not hn.keep(_p(points=49, comments=39))
    assert hn.keep(_p(title="Show HN: tool", comments=10)) and not hn.keep(_p(title="Show HN: tool", comments=9))
    assert not hn.keep(_p(title="Ask the room", comments=10))


def test_consensus_levels():
    c = lambda *ns: [{"n": n} for n in ns]  # noqa: E731
    assert hn.consensus(c(12, 5), 60) == "讨论少"
    assert hn.consensus(c(12, 5), 200) == "基本共识"       # 12/17 = 70%
    assert hn.consensus(c(10, 8, 2), 200) == "有分歧"      # 第二大 40%
    assert hn.consensus(c(10, 2, 2), 200) == "基本共识"    # 10/14 = 71%


def test_resource_key_merges_variants():
    assert hn.res_key("https://www.example.com/a/?utm_source=x") == hn.res_key("http://example.com/a")
    assert hn.res_key("https://www.youtube.com/watch?v=1&si=zz") == hn.res_key("https://youtube.com/watch?v=1")
    assert hn.res_key("https://www.youtube.com/watch?v=1") != hn.res_key("https://www.youtube.com/watch?v=2")


def _dg():
    op = lambda claim, n, q: {"stance": "主流", "claim": claim, "n": n, "cids": [7], "quote": q, "by": "u"}  # noqa: E731
    return {"a": {"opinions": [op("审查成瓶颈", 12, "review is the bottleneck now"), op("工具优先", 5, "use deterministic tools first")],
                  "experiences": [{"who": "我", "did": "做过", "result": "好", "cids": [8], "quote": "q", "by": "v"}]}}


class _R:
    def __init__(self, out):
        self.out = out

    strong = "m"

    def call(self, *a):
        return self.out


def test_synth_checks_citations_and_counts():
    posts = {"a": {"title": "T", "comments": 100}}
    t = {"title": "话题", "posts": ["a"]}
    out = {"verdict": "多数认为审查是瓶颈 [2][9]", "camps": [{"claim": "工具优先", "side": "反对", "refs": ["p0o1", "bogus"]},
                                                       {"claim": "审查成瓶颈", "side": "主流", "refs": ["p0o0"]}, {"claim": "编的", "refs": ["nope"]}],
           "exps": [{"ref": "p0e0", "outcome": "乱写"}, {"ref": "zzz", "outcome": "成功"}], "mine": [{"judgment": "不存在", "rel": "相反"}]}
    s = hn.synth_one(_R(out), t, posts, _dg(), [{"title": "我的判断", "stance": "s"}])
    assert [c["claim"] for c in s["camps"]] == ["审查成瓶颈", "工具优先"]          # 编造的阵营丢掉，按人数排序
    assert s["camps"][0]["n"] == 12 and s["camps"][0]["quote"] == "review is the bottleneck now"
    assert s["verdict"] == "多数认为审查是瓶颈 [1]"                                # 引用改成排序后的序号，不存在的去掉
    assert [x["outcome"] for x in s["exps"]] == ["有条件"] and s["mine"] == []     # 乱写的结果归有条件，不存在的判断丢弃


def test_synth_hides_uncited_verdict():
    s = hn.synth_one(_R({"verdict": "没有引用的结论", "camps": [{"claim": "a", "refs": ["p0o0"]}]}), {"title": "t", "posts": ["a"]}, {"a": {"title": "T", "comments": 9}}, _dg(), [])
    assert s["verdict"] == "" and s["verdict_unchecked"]


def test_api_hn_runs_page_and_react(client, tmp_path, monkeypatch):
    import json
    from app.modules import absorb
    monkeypatch.setattr(hn, "BASE", tmp_path / "hn")
    monkeypatch.setattr(absorb, "FB", tmp_path / "fb.jsonl")
    d = tmp_path / "hn" / "2026-11-13_2026-11-19"
    d.mkdir(parents=True)
    (d / "run.json").write_text(json.dumps({"start": "2026-11-13", "end": "2026-11-19"}))
    (d / "status.json").write_text(json.dumps({"done": True, "pid": 0}))
    (d / "page.json").write_text(json.dumps({"meta": {}, "topics": [{"id": 0, "title": "话题", "kind": "议题", "consensus": "有分歧"}], "resources": [], "tail": []}))
    assert client.get("/api/absorb/hn/runs").json()[0]["done"] is True
    rid = "2026-11-13_2026-11-19"
    assert client.get(f"/api/absorb/hn/runs/{rid}").json()["data"]["topics"][0]["title"] == "话题"
    assert client.post(f"/api/absorb/hn/runs/{rid}/react", json={"topic": 0, "act": "很受用", "stance": "站反对", "stars": 4}).status_code == 200
    assert client.get(f"/api/absorb/hn/runs/{rid}").json()["reactions"]["0"]["act"] == "很受用" and client.get(f"/api/absorb/hn/runs/{rid}").json()["reactions"]["0"]["stars"] == 4
    assert client.post(f"/api/absorb/hn/runs/{rid}/react", json={"topic": 0, "stars": 6}).status_code == 400
    assert client.post(f"/api/absorb/hn/runs/{rid}/react", json={"topic": 0, "stars": 3}).status_code == 200      # 只打星也算一条表态
    assert client.post(f"/api/absorb/hn/runs/{rid}/react", json={"topic": 0, "act": "乱写"}).status_code == 400
    assert client.post(f"/api/absorb/hn/runs/{rid}/react", json={"topic": 9, "act": "很受用"}).status_code == 404
    assert client.post(f"/api/absorb/hn/runs/{rid}/react", json={"topic": 0}).status_code == 200
    assert client.get(f"/api/absorb/hn/runs/{rid}").json()["reactions"] == {}
    ev = [json.loads(x) for x in (tmp_path / "fb.jsonl").read_text().splitlines()]
    assert ev[0]["src"] == "hn" and ev[0]["claim"] == "话题" and ev[0]["stance"] == "站反对" and ev[0]["stars"] == 4
    assert client.get("/api/absorb/feedback").json()["n"] == 0        # HN 表态不混进选题吸收的反馈统计


def test_page_resource_intent_and_ranking():
    posts = [{"id": "a", "title": "A", "url": "", "hn_url": "", "points": 1, "comments": 100, "author": "op"}]
    lk = lambda u, intent, by, **k: {"url": u, "title": u, "kind": "仓库", "why": "w", "intent": intent, "by": by, "self": False, **k}  # noqa: E731
    dg = {"a": {"tldr": "", "total": 3, "people": 3, "raw_ops": 0, "raw_exps": 0, "opinions": [], "experiences": [],
                "links": [lk("https://x.com/doc", "佐证", ["u1", "u2", "u3"]), lk("https://x.com/tool", "推荐", ["u1"]),
                          lk("https://x.com/bad", "批评", ["u2"]), lk("https://x.com/self", "推荐", ["op"], **{"self": True})]}}
    files = {"posts.json": posts, "relevance.json": {"a": "ai"}, "digests.json": dg, "topics.json": {"topics": [], "tail": []},
             "synth.json": [{"title": "t", "kind": "议题", "posts": ["a"], "verdict": "v", "verdict_unchecked": False, "camps": [], "exps": [], "mine": []}],
             "collected_all.json": {"queried": 1}, "status.json": {}}

    class R:
        start, end, light, strong = "2026-11-13", "2026-11-19", "haiku", "sonnet"
        load = staticmethod(lambda n: files[n])

    page = hn.s_page(R())
    by = {x["url"]: x for x in page["resources"]}
    assert by["https://x.com/tool"]["intent"] == "推荐" and by["https://x.com/tool"]["rec"] == 1
    assert by["https://x.com/self"]["rec"] == 0                      # 作者自己推荐不算推荐者
    assert by["https://x.com/bad"]["intent"] == "批评" and by["https://x.com/doc"]["intent"] == "佐证"
    assert page["resources"][0]["url"] == "https://x.com/tool"       # 推荐排在只被引用的前面，哪怕引用的人更多
    assert page["topics"][0]["res"] == [page["resources"].index(by[u]) for u in by]


def test_rel_label_thresholds():
    assert [hn.rel_label(p) for p in (0.29, 0.3, 0.59, 0.6, 0.95)] == ["no", "edge", "edge", "ai", "ai"]


def test_digest_post_uses_light_model_and_checks_quotes(monkeypatch, tmp_path):
    monkeypatch.setattr(hn.hnd, "CACHE_DIR", tmp_path)
    comments = [{"id": 5, "depth": 0, "author": "u", "text": "I tried it and it saved us a lot of time", "replies": 0}]
    monkeypatch.setattr(hn.hnd, "fetch_thread", lambda pid, c: ("op", comments))
    seen = {}

    class R:
        light = "haiku"

        def call(self, model, system, user):
            seen["model"] = model
            return {"tldr": "t", "opinions": [{"stance": "主流", "claim": "好用", "n": 1, "quote": "it saved us a lot of time"},
                                              {"stance": "少数", "claim": "编的", "n": 1, "quote": "nothing like this was said here"}]}

    d = hn.digest_post(R(), {"id": "1", "title": "T", "url": "", "points": 9, "comments": 5}, None)
    assert seen["model"] == "haiku" and [o["claim"] for o in d["opinions"]] == ["好用"]
    assert hn.digest_post(type("R", (), {"light": "h", "call": lambda *a: None})(), {"id": "2", "title": "T", "url": "", "points": 9, "comments": 5}, None) is None   # 模型没返回：不写缓存


def test_daily_window_ends_yesterday():
    import datetime as dt
    assert hn.daily_window(7, dt.date(2026, 11, 20)) == ("2026-11-13", "2026-11-19")


def test_cache_reuses_until_comments_grow(tmp_path, monkeypatch):
    monkeypatch.setattr(hn.hnd, "CACHE_DIR", tmp_path)
    assert hn.hnd.cache_get("1", 100) is None
    hn.hnd.cache_put("1", {"tldr": "x"}, 100)
    assert hn.hnd.cache_get("1", 120)["tldr"] == "x"      # 涨得不够
    assert hn.hnd.cache_get("1", 149)["tldr"] == "x"
    assert hn.hnd.cache_get("1", 150) is None              # 涨到 1.5 倍且多 30 条以上才重做
    hn.hnd.cache_put("2", {"tldr": "y"}, 10)
    assert hn.hnd.cache_get("2", 40) is None               # 10 → 40：超过 1.5 倍且多 30 条，重做
    assert hn.hnd.cache_get("2", 39)["tldr"] == "y"


def test_digest_post_hits_cache_without_model(tmp_path, monkeypatch):
    monkeypatch.setattr(hn.hnd, "CACHE_DIR", tmp_path)
    hn.hnd.cache_put("7", {"tldr": "cached", "opinions": []}, 90)

    class R:
        light = "h"

        def call(self, *a):
            raise AssertionError("命中缓存不该调模型")

    assert hn.digest_post(R(), {"id": "7", "title": "T", "url": "", "points": 1, "comments": 95}, None)["tldr"] == "cached"


def test_synth_cache_key_follows_member_digests():
    a = {"opinions": [1]}
    k = lambda ids, dg: hn.synth_key({"posts": ids}, dg, [])  # noqa: E731
    assert k(["x", "y"], {"x": a, "y": a}) == k(["y", "x"], {"x": a, "y": a})
    assert k(["x"], {"x": a}) != k(["x"], {"x": {"opinions": [2]}})


def test_prune_keeps_latest_runs_only(tmp_path, monkeypatch):
    monkeypatch.setattr(hn, "BASE", tmp_path)
    for n in ("2026-11-10_2026-11-16", "2026-11-11_2026-11-17", "2026-11-12_2026-11-18", "_cache", "_cmp"):
        (tmp_path / n).mkdir()
    assert hn.prune(2) == ["2026-11-10_2026-11-16"]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["2026-11-11_2026-11-17", "2026-11-12_2026-11-18", "_cache", "_cmp"]


def test_maybe_run_once_a_day(tmp_path, monkeypatch):
    import json
    from app.modules import absorb
    monkeypatch.setattr(hn, "BASE", tmp_path)
    monkeypatch.setattr(hn, "daily_window", lambda days=7, today=None: ("2026-11-14", "2026-11-20"))
    launched = []
    monkeypatch.setattr(absorb, "_hn_launch", lambda s, e: launched.append((s, e)) or f"{s}_{e}")
    assert absorb.hn_maybe_run(now=1000.0) == "2026-11-14_2026-11-20" and launched          # 今天的窗口还没有，启动
    d = tmp_path / "2026-11-14_2026-11-20"
    d.mkdir()
    (d / "run.json").write_text("{}")
    (d / "status.json").write_text(json.dumps({"done": False, "updated": 1000.0, "error": "x"}))
    assert absorb.hn_maybe_run(now=1000.0 + 3600) == ""                                       # 中断不到 3 小时，先不重试
    assert absorb.hn_maybe_run(now=1000.0 + 4 * 3600) == "2026-11-14_2026-11-20"             # 3 小时后从断点接着跑
    (d / "page.json").write_text("{}")
    (d / "status.json").write_text(json.dumps({"done": True, "updated": 1.0}))
    n = len(launched)
    assert absorb.hn_maybe_run(now=1e9) == "" and len(launched) == n                         # 已跑完，不重复
    monkeypatch.setattr(absorb.settings, "get", lambda k, d=None: False if k == "absorb.hn_daily" else d)
    (d / "page.json").unlink()
    assert absorb.hn_maybe_run(now=1e9) == ""                                                 # 开关关掉
