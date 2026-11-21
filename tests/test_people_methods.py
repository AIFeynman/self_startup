from app.modules import _people_methods as M


def test_snippets_cut_windows_around_name_and_merge_overlaps():
    text = "前言" * 400 + "Karpathy 提出 LLM Wiki：把资料放 raw/，让模型编译成 wiki。" + "中段" * 50 + "Karpathy 还说要定期 lint。" + "结尾" * 400
    parts = M.snippets(text, "karpathy", width=200)
    assert len(parts) == 1
    assert "LLM Wiki" in parts[0] and "lint" in parts[0]
    assert len(parts[0]) < len(text) / 3


def test_snippets_empty_when_person_not_named():
    assert M.snippets("讲的是 RAG 和向量库", "karpathy") == []


def test_quote_must_appear_verbatim_ignoring_spacing():
    src = "Something I'm finding very useful recently:\nusing LLMs to build personal knowledge bases"
    assert M.quote_ok("finding very useful recently: using LLMs", src)
    assert not M.quote_ok("very useful to build wikis", src)
    assert not M.quote_ok("", src)


def _src(sid, kind, author, url, date):
    return {"id": sid, "kind": kind, "author": author, "url": url, "date": date, "title": sid}


def test_assemble_marks_own_words_and_counts_distinct_retellers():
    sources = {s["id"]: s for s in [
        _src("x1", "own", "karpathy", "https://x.com/karpathy/status/1", "2026-04-02"),
        _src("a1", "retell", "imryven", "https://x.com/i/article/1", "2026-10-27"),
        _src("a2", "retell", "imryven", "https://x.com/i/article/2", "2026-10-28"),
        _src("a3", "retell", "haoran", "https://x.com/i/article/3", "2026-09-19"),
    ]}
    units = {k: {"sid": sid, "quote": "q", "spark": 3, "kind": "做法"}
             for k, sid in {"u1": "x1", "u2": "a1", "u3": "a2", "u4": "a3", "u5": "a3"}.items()}
    groups = {"karpathy": [
        {"name": "LLM Wiki", "how": "h", "why": "w", "try": "t", "refs": ["u1", "u2", "u3", "u4"]},
        {"name": "只有转述", "how": "h", "why": "w", "try": "t", "refs": ["u5"]},
    ]}
    cards = M.assemble(groups, units, sources)
    first, second = cards
    assert first["name"] == "LLM Wiki" and first["own"] is True
    assert first["origin"]["url"] == "https://x.com/karpathy/status/1"
    assert first["retellers"] == 2
    assert second["own"] is False and second["origin"]["url"] == "https://x.com/i/article/3"


def test_assemble_drops_unknown_refs_and_empty_groups():
    cards = M.assemble({"dean": [{"name": "n", "how": "h", "why": "", "try": "", "refs": ["nope"]}]}, {}, {})
    assert cards == []


def test_windows_cover_last_year_by_quarter():
    ws = M.windows("2026-11-21", 4)
    assert ws[0] == ("2026-08-21", "2026-11-22") and ws[-1][0] == "2025-11-21"
    assert all(a < b for a, b in ws) and all(ws[i][0] == ws[i + 1][1] for i in range(3))


def test_own_queries_raise_threshold_only_when_window_is_full():
    calls = []

    def search(q):
        calls.append(q)
        full = "min_faves:300 " in q and "since:2026-08-21" in q
        return [{"id": str(i)} for i in range(20 if full else 3)]
    M.own_queries("karpathy", [("2026-08-21", "2026-11-22"), ("2026-05-21", "2026-08-21")], search)
    hot = [q for q in calls if "since:2026-08-21" in q]
    cold = [q for q in calls if "since:2026-05-21" in q]
    assert [q.split("min_faves:")[1].split()[0] for q in hot] == ["300", "3000"]
    assert len(cold) == 1


def test_interview_quote_counts_as_own_words():
    sources = {"l1": _src("l1", "link", "36kr.com", "https://www.36kr.com/p/1", "2026-11-21")}
    units = {"u1": {"sid": "l1", "quote": "q", "said": "原话", "spark": 3, "kind": "做法"}}
    card, = M.assemble({"dean": [{"name": "十二个月清单", "how": "h", "why": "", "try": "", "refs": ["u1"]}]}, units, sources)
    assert card["own"] is True and card["origin"]["kind"] == "link"


def test_screen_keeps_links_and_unscored_drops_low_jev():
    srcs = [{"id": "a", "kind": "own"}, {"id": "b", "kind": "retell"}, {"id": "c", "kind": "link"}, {"id": "d", "kind": "own"}]
    kept = M.screened(srcs, {"a": 0.9, "b": 0.2, "c": 0.1})
    assert [s["id"] for s in kept] == ["a", "c", "d"]


def test_assemble_keeps_only_high_spark_and_carries_kind():
    sources = {"x1": _src("x1", "own", "karpathy", "u1", "2026-04-02"), "x2": _src("x2", "own", "karpathy", "u2", "2026-05-01")}
    units = {"u1": {"sid": "x1", "quote": "q", "spark": 3, "kind": "观点"}, "u2": {"sid": "x2", "quote": "q", "spark": 2, "kind": "做法"},
             "u3": {"sid": "x2", "quote": "q", "spark": 2, "kind": "做法"}}
    cards = M.assemble({"karpathy": [{"name": "强", "how": "h", "why": "w", "try": "", "refs": ["u1", "u2"]},
                                     {"name": "弱", "how": "h", "why": "w", "try": "t", "refs": ["u3"]}]}, units, sources)
    assert [(c["name"], c["spark"], c["kind"]) for c in cards] == [("强", 3, "观点")]


def test_own_windows_incremental_after_first_fetch():
    assert M.own_windows("2026-11-21", "2026-11-14") == [("2026-11-11", "2026-11-22")]
    assert M.own_windows("2026-11-21", "") == M.windows("2026-11-21")


def test_merge_reuses_people_whose_units_did_not_change():
    prev = {"karpathy": {"refs": ["a#0", "b#0"], "g": [{"name": "旧标题"}]}, "dean": {"refs": ["c#0"], "g": [{"name": "x"}]}}
    keep, todo = M.plan_merge({"karpathy": ["b#0", "a#0"], "dean": ["c#0", "d#0"], "ng": ["e#0"]}, prev)
    assert keep == {"karpathy": prev["karpathy"]}
    assert sorted(todo) == ["dean", "ng"]


def test_weekly_due():
    day, now = 86400, 1_000_000_000
    assert M.due({}, now)
    assert not M.due({"done": True, "updated": now - 3 * day}, now)
    assert M.due({"done": True, "updated": now - 7 * day}, now)
    assert not M.due({"error": "失败", "updated": now - 3600}, now)
    assert M.due({"error": "失败", "updated": now - 4 * 3600}, now)
    assert not M.due({"done": False, "updated": now - 60}, now, running=True)


def test_retell_scan_finds_each_named_person_once(monkeypatch):
    rows = [("1", "imryven", "t", "2026-10-27", "Karpathy 说把资料放 raw/，Andrej Karpathy 又说要 lint。Jeff Dean 建议写下十件事。"),
            ("2", "karpathy", "t", "2026-10-28", "I (Karpathy) keep a wiki."),
            ("3", "x", "t", "2026-10-29", "讲 RAG 的文章")]

    class Conn:
        def execute(self, *a):
            return rows
    monkeypatch.setattr(M.sqlite3, "connect", lambda *a, **k: Conn())
    got = sorted((s["id"], s["kind"]) for s in M.retell_x_art([M.P.by_id()["karpathy"], M.P.by_id()["dean"]]))
    assert got == [("xart:1:dean", "retell"), ("xart:1:karpathy", "retell"), ("xart:2:karpathy", "own")]
