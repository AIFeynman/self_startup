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
