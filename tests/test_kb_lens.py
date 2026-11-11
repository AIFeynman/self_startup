from app.modules import kb as kb_mod

DOMAINS = ["产品", "设计", "运营", "工程", "算法", "增长"]
SECTIONS = ["goal", "lenses", "levers", "headroom", "quality", "pitfalls", "sources", "drill"]


def test_lens_cards_cover_every_domain(client):
    data = client.get("/api/kb/lens").json()
    assert [d["name"] for d in data["domains"]] == DOMAINS
    ids = set()
    for d in data["domains"]:
        assert len(d["cards"]) >= 3
        for c in d["cards"]:
            assert c["id"] not in ids
            ids.add(c["id"])
            assert c["domain"] == d["name"] and c["title"]
            for k in SECTIONS:
                assert c[k], (c["id"], k)
            assert all(lv["name"] and lv["how"] for lv in c["levers"])
    assert [s["key"] for s in data["sections"]][:6] == SECTIONS[:6]


def test_lens_chat_context_carries_card(client):
    perf = next(c for d in client.get("/api/kb/lens").json()["domains"] for c in d["cards"] if c["id"] == "eng-perf")
    ctx = kb_mod.agent_context("lens:eng-perf")
    assert perf["title"] in ctx and perf["levers"][0]["name"] in ctx and perf["drill"] in ctx
    assert "先让用户给出自己的判断" in ctx
    overview = kb_mod.agent_context("lens:")
    assert all(d in overview for d in DOMAINS) and perf["title"] in overview
    assert kb_mod.agent_context("lens:nope") == overview
