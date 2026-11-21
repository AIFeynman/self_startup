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
    units = {"u1": {"sid": "x1", "quote": "q1"}, "u2": {"sid": "a1", "quote": "q2"}, "u3": {"sid": "a2", "quote": "q3"},
             "u4": {"sid": "a3", "quote": "q4"}, "u5": {"sid": "a3", "quote": "q5"}}
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
    units = {"u1": {"sid": "l1", "quote": "q", "said": "原话"}}
    card, = M.assemble({"dean": [{"name": "十二个月清单", "how": "h", "why": "", "try": "", "refs": ["u1"]}]}, units, sources)
    assert card["own"] is True and card["origin"]["kind"] == "link"
