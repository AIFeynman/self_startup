"""X 长文库全流程（可断点续跑）：python -m scripts.xart_run crawl|gate|titles|rel|full|score|funnel [起 止] [--limit N]"""
import json
import sys

from app.modules import _xart as x


def main(argv: list[str]) -> None:
    x.init()
    cmd, rest = argv[0], argv[1:]
    limit = int(rest[rest.index("--limit") + 1]) if "--limit" in rest else 0
    pos = [a for a in rest if not a.startswith("--") and not a.isdigit()]
    if cmd == "crawl":
        for d in x.days(pos[0], pos[-1]):
            print(json.dumps(x.crawl_day(d), ensure_ascii=False), flush=True)
    elif cmd == "all":
        for d in x.days(pos[0], pos[-1]):
            print(json.dumps(x.crawl_day(d), ensure_ascii=False), flush=True)
        for step in ("gate", "titles", "relevance", "fulltext", "score"):
            print(step, json.dumps(getattr(x, step)(), ensure_ascii=False), flush=True)
    else:
        fn = {"gate": x.gate, "titles": x.titles, "rel": x.relevance, "full": x.fulltext, "score": x.score, "funnel": x.funnel}[cmd]
        print(json.dumps(fn(limit=limit) if cmd not in ("gate", "funnel") else fn(), ensure_ascii=False))
    print("funnel", json.dumps(x.funnel(), ensure_ascii=False))


if __name__ == "__main__":
    main(sys.argv[1:])
