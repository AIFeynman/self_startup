from app.modules import _demand_run as dr


def _cards():
    return {
        "sierra": {"name": "Sierra", "sources": ["创业公司"], "arr_v": 4e8, "scene": "客服", "pain": "p", "product": "x"},
        "revid": {"name": "Revid", "sources": ["增长 Case"], "arr_v": 7.2e6, "scene": "视频", "pain": "p", "product": "x"},
        "tiny": {"name": "Tiny", "sources": ["创业公司"], "arr_v": 2e4, "scene": "s", "pain": "p", "product": "x"},
        "done": {"name": "Done", "sources": ["创业公司"], "arr_v": 5e6, "deep": {"moat": []}},
        "skip": {"name": "Skip", "sources": ["创业公司"], "arr_v": 5e6, "skip": True},
    }


def test_deep_todo_only_mid_and_large_without_deep_biggest_first():
    from app.modules import _demand_deep as deep
    assert deep.todo(_cards()) == ["sierra", "revid"]


def test_deep_fill_keeps_structure_drops_unknown_moat_kind_and_stops_at_budget(monkeypatch, tmp_path):
    from app.modules import _demand_deep as deep
    monkeypatch.setattr(dr, "BASE", tmp_path)
    cards = _cards()
    seen = []

    class Fake:
        light = strong = "m"
        cost = 0.0
        fails = 0

        def call(self, model, system, user, web=False):
            seen.append((web, user))
            self.cost += 1
            return {"pain": {"who": "大企业客服负责人", "before": "外包呼叫中心", "cost": "每通电话 $5", "why_now": "模型能连续对话"},
                    "model": {"payer": "企业", "pricing": "按解决的会话计费", "unit": "", "expand": "从客服扩到销售"},
                    "moat": [{"kind": "工作流嵌入", "detail": "接进 CRM 和工单"}, {"kind": "胡写", "detail": "?"}],
                    "weak": "大厂能做", "rivals": [{"name": "Decagon", "diff": "更偏中型"}], "facts": [{"k": "ARR", "v": "$400M"}],
                    "risks": "", "sources": ["https://a", "https://b"]}
    import threading
    monkeypatch.setattr(deep, "PARALLEL", 1)
    ctx = Fake()
    ctx.lock = threading.Lock()
    n = deep.fill(ctx, cards, deep.todo(cards), budget=1)
    assert n == 1 and len(seen) == 1 and seen[0][0] is True
    d = dr._load("cards.json", {})["sierra"]["deep"]
    assert d["pain"]["cost"] == "每通电话 $5" and [m["kind"] for m in d["moat"]] == ["工作流嵌入"]
    assert d["rivals"][0]["name"] == "Decagon" and d["date"] and "deep" not in cards["revid"]


def _graph():
    return {"scenes": [{"id": "G2", "name": "视频制作与剪辑", "desc": "d", "subs": [
        {"id": "S10", "name": "长视频切片太费时", "pain": "p", "products": ["opus"]},
        {"id": "S11", "name": "字幕手打慢又不准", "pain": "p", "products": []}]}],
        "domains": [{"id": "D1", "name": "内容与创作", "scenes": ["G2"]}]}


def test_chain_audit_adds_missing_links_as_new_pain_nodes_once(monkeypatch, tmp_path):
    from app.modules import _demand_chain as ch
    monkeypatch.setattr(dr, "BASE", tmp_path)
    g = _graph()

    class Fake:
        light = strong = "m"
        cost = 0.0
        fails = 0

        def call(self, model, system, user, web=False):
            return {"links": [
                {"name": "选题与爆款预估", "job": "发之前判断能不能火", "covered": [], "pain": "做完才知道没人看", "examples": ["vidIQ", "1of10"], "query": "AI YouTube viral prediction tool"},
                {"name": "剪辑切片", "job": "切出高光", "covered": ["S10"]},
                {"name": "瞎编", "job": "x", "covered": ["S999"]}]}
    got = ch.audit(Fake(), g, {"opus": {"name": "Opus Clip"}}, ["G2"])
    subs = g["scenes"][0]["subs"]
    new = [s for s in subs if s.get("chain")]
    assert len(new) == 1 and new[0]["name"] == "选题与爆款预估" and new[0]["pain"] == "做完才知道没人看" and new[0]["products"] == []
    assert new[0]["id"] not in ("S10", "S11") and got == [{"sub": new[0]["id"], "scene": "视频制作与剪辑", "link": "选题与爆款预估", "query": "AI YouTube viral prediction tool", "examples": ["vidIQ", "1of10"]}]
    links = dr._load("chain.json", {})["G2"]["links"]
    assert [x["sub"] for x in links] == [new[0]["id"], "S10", ""]
    assert ch.audit(Fake(), g, {}, ["G2"]) == [] and len([s for s in g["scenes"][0]["subs"] if s.get("chain")]) == 1


def test_chain_finds_companies_of_any_size_and_pins_them_to_the_gap_node(monkeypatch, tmp_path):
    from app.modules import _demand_chain as ch, _demand_mid as mid
    monkeypatch.setattr(dr, "BASE", tmp_path)

    class Fake:
        light = strong = "m"
        cost = 0.0
        fails = 0

        def call(self, model, system, user, web=False):
            return {"companies": [{"name": "vidIQ", "one_liner": "YouTube 选题与预测", "arr": "ARR 约 $50M"},
                                  {"name": "1of10", "one_liner": "找爆款选题"},
                                  {"name": "OpenAI", "arr": "ARR 约 $10B"}]}
    gaps = [{"sub": "S40", "scene": "视频制作与剪辑", "link": "选题与爆款预估", "query": "q", "examples": ["vidIQ"]}]
    new = ch.find(Fake(), gaps, {"openai": {"name": "OpenAI", "arr_v": 1e10}})
    found = dr._load("mid.json", {})
    assert sorted(new) == ["1of10", "vidiq"] and found["vidiq"]["sub"] == "S40" and found["1of10"]["source"] == ch.SOURCE
    P = {}
    mid.add_to(P, dr.norm)
    assert P["1of10"]["sources"] == [ch.SOURCE]


def test_add_new_places_pinned_cards_into_their_gap_node_without_asking(monkeypatch, tmp_path):
    monkeypatch.setattr(dr, "BASE", tmp_path)
    dr._save("mid.json", {"vidiq": {"name": "vidIQ", "sub": "S40"}})
    g = _graph()
    g["scenes"][0]["subs"].append({"id": "S40", "name": "选题与爆款预估", "pain": "p", "products": [], "chain": True})
    cards = {"opus": {"name": "Opus"}, "vidiq": {"name": "vidIQ", "scene": "s", "pain": "p"}}
    calls = []

    class Fake:
        light = strong = "m"
        cost = 0.0
        fails = 0

        def call(self, *a, **k):
            calls.append(a)
            return {}
    dr.add_new(Fake(), g, cards)
    assert g["scenes"][0]["subs"][2]["products"] == ["vidiq"] and calls == []


def test_watch_audits_oldest_scenes_and_fills_gaps(monkeypatch, tmp_path):
    from app.modules import _demand_chain as ch, _demand_watch as w
    monkeypatch.setattr(dr, "BASE", tmp_path)
    dr._save("graph.json", _graph())
    monkeypatch.setattr(w, "_headlines", lambda: [])
    monkeypatch.setattr(w, "process", lambda ctx, keys: None)
    did = {}
    monkeypatch.setattr(ch, "audit", lambda ctx, g, cards, ids: did.setdefault("audit", ids) and [{"sub": "S40", "scene": "x", "link": "选题", "query": "q", "examples": []}])
    monkeypatch.setattr(ch, "find", lambda ctx, gaps, known: did.setdefault("find", gaps) and ["vidiq"])

    class Fake:
        light = strong = "m"
        cost = 0.0
        fails = 0

        def call(self, model, system, user, web=False):
            return {}
    log = w.run_watch(Fake(), budget=5)
    assert did["audit"] == ["G2"] and did["find"][0]["sub"] == "S40"
    assert log["chain"] == ["选题"] and "vidIQ" not in log["new"]
