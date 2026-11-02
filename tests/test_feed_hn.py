"""HN 精读：评论树展开、提炼结果校验、挑帖、经验库聚合、分类拆分、知识库同步。不触网、不调 LLM。"""
from app.modules import _feed_hn as hnd


def _tree():
    return {"id": 1, "children": [
        {"id": 10, "author": "a", "text": "small thread", "children": []},
        {"id": 20, "author": "b", "text": 'Try <a href="https://github.com/x/tool">github.com/x/tool</a>, works great',
         "children": [{"id": 21, "author": "c", "text": "+1 to https://github.com/x/tool", "children": []},
                      {"id": 22, "author": "d", "text": "", "children": [{"id": 23, "author": "e", "text": "deep reply", "children": []}]}]},
    ]}


def test_flatten_order_and_links():
    out = hnd.flatten(_tree(), top_order=[10, 20])
    ids = [x["id"] for x in out]
    assert ids[0] == 10                     # 顶层按 HN 排序
    assert 22 not in ids and 23 in ids      # 空评论跳过，子评论保留
    assert ids.index(23) < ids.index(21)    # 楼中楼按回复数
    t20 = next(x for x in out if x["id"] == 20)
    assert "https://github.com/x/tool" in t20["text"] and "<a" not in t20["text"]
    assert hnd.flatten(_tree())[0]["id"] == 20   # 没有 HN 排序时按回复数


def test_clean_digest_validates():
    comments = hnd.flatten(_tree(), [10, 20])
    text = hnd.render(comments)
    raw = {"tldr": "推荐工具", "links": [{"url": "https://github.com/x/tool/", "kind": "仓库", "title": "tool", "cids": [20, 999]},
                                         {"url": "https://made.up/link", "kind": "博客"}],
           "entities": [{"name": "tool", "kind": "乱写", "sentiment": "pos", "cids": [21]}, {"name": ""}],
           "opinions": [{"stance": "主流", "claim": "好用", "n": "3"}], "experiences": [{"who": "b", "did": "用了", "result": "好"}]}
    d = hnd.clean_digest(raw, comments, text)
    assert [l["url"] for l in d["links"]] == ["https://github.com/x/tool"]    # 编造的链接丢掉
    assert d["links"][0]["mentions"] == 2 and d["links"][0]["cids"] == [20]   # 提及按原文数，假 cid 去掉
    assert d["entities"] == [{"name": "tool", "kind": "其他", "sentiment": "pos", "note": "", "cids": [21]}]
    assert d["opinions"][0]["n"] == 3 and d["total"] == len(comments) and d["read"] == len(comments)


def test_needs_and_pick():
    it = lambda i, n, pop, **ex: {"id": f"hn:{i}", "source": "hn", "popularity": pop, "extra": {"comments": n, **ex}}  # noqa: E731
    assert not hnd.needs(it(1, 10, 1))
    assert hnd.needs(it(1, 40, 1))
    assert not hnd.needs(it(1, 50, 1, hn={"tldr": "x"}, hn_src=40))       # 涨得不够不重做
    assert hnd.needs(it(1, 100, 1, hn={"tldr": "x"}, hn_src=40))
    items = [it(1, 40, 5), it(2, 40, 50), it(3, 5, 999), {**it(4, 99, 99), "source": "reddit"}]
    assert [x["id"] for x in hnd.pick(items, top=1)] == ["hn:2"]


def _post(i, ents, links=(), exps=(), date="2026-10-30"):
    return {"id": f"hn:{i}", "title": f"Post {i}", "date": date, "extra": {"hn_url": f"https://news.ycombinator.com/item?id={i}",
            "hn": {"entities": list(ents), "links": list(links), "experiences": list(exps)}}}


def test_library_aggregates():
    e = lambda n, s: {"name": n, "kind": "技术", "sentiment": s, "note": f"{n} {s}", "cids": [1]}  # noqa: E731
    l = {"url": "https://a.com/x", "kind": "博客", "title": "A", "why": "讲得清楚", "mentions": 2, "cids": []}
    items = [_post(1, [e("Postgres", "pos"), e("Redis", "neg")], [l], [{"who": "dba", "did": "迁移到 Postgres", "result": "省钱", "cids": []}]),
             _post(2, [e("postgres", "neg")], [{**l, "url": "https://a.com/x/", "mentions": 1}])]
    lib = hnd.library(items)
    assert lib["posts"] == 2
    pg = lib["entities"][0]
    assert pg["name"] == "Postgres" and pg["posts"] == 2 and pg["pos"] == 1 and pg["neg"] == 1   # 大小写合并
    assert lib["links"][0]["posts"] == 2 and lib["links"][0]["mentions"] == 3                    # 尾斜杠合并
    assert lib["experiences"][0]["post"]["id"] == "hn:1"
    q = hnd.library(items, "redis")
    assert [g["name"] for g in q["entities"]] == ["Redis"] and not q["links"] and not q["experiences"]


def test_api_hn_tab_split_library_and_kb(client, monkeypatch):
    from app import db, kb
    from app.modules import feed
    d = {"tldr": "大家觉得 Postgres 够用", "links": [{"url": "https://pg.org", "kind": "文档", "title": "PG", "why": "官方", "mentions": 1, "cids": [5]}],
         "entities": [{"name": "Postgres", "kind": "技术", "sentiment": "pos", "note": "稳", "cids": [5]}],
         "opinions": [{"stance": "主流", "claim": "先用 PG", "n": 4, "cids": [5]}],
         "experiences": [{"who": "运维", "did": "单机 PG 扛住", "result": "两年没出事", "cids": [5]}], "read": 3, "total": 3}
    feed.upsert([{"id": "hn:9001", "source": "hn", "type": "discussion", "title": "Just use Postgres", "url": "https://x.com/pg",
                  "date": "2025-01-01T00:00:00+00:00", "popularity": 300,
                  "extra": {"hn_url": "https://news.ycombinator.com/item?id=9001", "comments": 80}},
                 {"id": "reddit:9002", "source": "reddit", "type": "discussion", "title": "Reddit thread pg", "url": "https://r.com/1",
                  "date": "2025-01-01T00:00:00+00:00", "popularity": 10, "extra": {}}])
    feed._save_hn_digest("hn:9001", d, 80)
    # 重新抓到同一帖不会冲掉提炼
    feed.upsert([{"id": "hn:9001", "source": "hn", "type": "discussion", "title": "Just use Postgres", "url": "https://x.com/pg",
                  "popularity": 320, "extra": {"comments": 85}}])

    ids = lambda t: {x["id"] for x in client.get(f"/api/feed/items?type={t}&limit=200").json()["items"]}  # noqa: E731
    assert "hn:9001" in ids("hn") and "reddit:9002" not in ids("hn")
    assert "hn:9001" not in ids("discussion") and "reddit:9002" in ids("discussion")
    item = next(x for x in client.get("/api/feed/items?type=hn&limit=200").json()["items"] if x["id"] == "hn:9001")
    assert item["extra"]["hn"]["tldr"] == d["tldr"]

    lib = client.get("/api/feed/hn/library").json()
    assert lib["posts"] >= 1 and any(g["name"] == "Postgres" for g in lib["entities"])
    assert not client.get("/api/feed/hn/library?q=zzznomatch").json()["entities"]
    assert client.post("/api/feed/hn/digest", json={"id": "reddit:9002"}).status_code == 404

    kb.sync()
    assert not list((kb.KB_DIR / "feed/hn").glob("9001-*.md")) if (kb.KB_DIR / "feed/hn").exists() else True   # 没赞藏不同步
    client.post("/api/feed/feedback", json={"id": "hn:9001", "saved": True})
    kb.sync()
    doc = next((kb.KB_DIR / "feed/hn").glob("9001-*.md")).read_text()
    assert "大家觉得 Postgres 够用" in doc and "单机 PG 扛住" in doc and "https://news.ycombinator.com/item?id=5" in doc

    client.post("/api/feed/feedback", json={"id": "hn:9001", "hidden": True})
    assert not any(g["name"] == "Postgres" for g in client.get("/api/feed/hn/library").json()["entities"])
