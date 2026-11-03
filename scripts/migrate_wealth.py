"""一次性迁移：把 wealth 仓库（Signal Atlas，端口 8768）的数据搬进理财板块。

    uv run python scripts/migrate_wealth.py [/path/to/wealth]

复制：var/ai-monitor/*.json 回测缓存 → data/wealth/；monitor_config/positions.json → data/wealth/positions.json；
五个标的的 K 线、最新报价、相关新闻、最新估值 / 业绩超预期、登记的成交 → app.db 的 wealth_* 表。重复跑是安全的（INSERT OR REPLACE / IGNORE）。
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db  # noqa: E402
from app.modules import _wealth_service as svc  # noqa: E402

SYMBOLS = tuple(svc.ASSETS)
CACHES = ("dividend_valuation.json", "fx_rates.json", "sell_backtest.json", "sell_backtest_history.json", "switch_backtest.json",
          "target_plan_backtest.json", "target_plan_history.json")


def main(repo: Path) -> None:
    src_dir = repo / "var" / "ai-monitor"
    svc.DATA.mkdir(parents=True, exist_ok=True)
    for name in CACHES:
        if (src_dir / name).exists():
            shutil.copy2(src_dir / name, svc.DATA / name)
    if not svc.POSITIONS.exists():
        shutil.copy2(repo / "monitor_config" / "positions.json", svc.POSITIONS)
    db.init([svc.SCHEMA])
    src = sqlite3.connect(src_dir / "monitor.sqlite3")
    src.row_factory = sqlite3.Row
    marks = ",".join("?" * len(SYMBOLS))
    counts: dict[str, int] = {}

    bars = src.execute(f"SELECT symbol, interval, ts, open, high, low, close, adj_close, volume FROM price_bars WHERE symbol IN ({marks})",
                       SYMBOLS).fetchall()
    with db._lock:
        c = db.conn()
        c.executemany("INSERT OR REPLACE INTO wealth_bars VALUES(?,?,?,?,?,?,?,?,?)", [tuple(r) for r in bars])
        c.commit()
    counts["bars"] = len(bars)

    quotes = src.execute(f"SELECT q.* FROM quote_snapshots q JOIN (SELECT symbol, MAX(id) AS id FROM quote_snapshots GROUP BY symbol) m "
                         f"ON m.id=q.id WHERE q.symbol IN ({marks})", SYMBOLS).fetchall()
    for q in quotes:
        svc.store_quote(q["symbol"], {**dict(q), "retrieved_at": q["observed_at"]})
    counts["quotes"] = len(quotes)

    news = 0
    for r in src.execute("SELECT * FROM news_items").fetchall():
        symbols = [s for s in json.loads(r["symbols_json"] or "[]") if s in SYMBOLS]
        bucket = r["query_bucket"] or ""
        if not symbols and bucket not in {f"position:{s}" for s in SYMBOLS}:
            continue
        news += db.execute("INSERT OR IGNORE INTO wealth_news(hash, bucket, symbols, title, url, source, published_at, retrieved_at) "
                           "VALUES(?,?,?,?,?,?,?,?)",
                           (r["content_hash"], bucket, json.dumps(sorted(symbols)), r["title"], r["url"], r["source"],
                            r["published_at"], r["retrieved_at"]))
    counts["news"] = news

    research = src.execute(f"SELECT r.* FROM research_snapshots r JOIN (SELECT symbol, kind, MAX(as_of_date) AS d FROM research_snapshots "
                           f"GROUP BY symbol, kind) m ON m.symbol=r.symbol AND m.kind=r.kind AND m.d=r.as_of_date "
                           f"WHERE r.kind IN ('profile','estimates') AND r.symbol IN ({marks})", SYMBOLS).fetchall()
    for r in research:
        db.execute("INSERT OR REPLACE INTO wealth_research(symbol, kind, payload, retrieved_at) VALUES(?,?,?,?)",
                   (r["symbol"], r["kind"], r["payload_json"], r["retrieved_at"]))
    counts["research"] = len(research)

    trades = src.execute("SELECT * FROM position_trades ORDER BY id").fetchall()
    existing = {(t["symbol"], t["executed_at"], t["shares"]) for t in db.rows("SELECT symbol, executed_at, shares FROM wealth_trades")}
    for t in trades:
        if (t["symbol"], t["executed_at"], t["shares"]) not in existing:
            db.insert("wealth_trades", {k: t[k] for k in ("symbol", "executed_at", "shares", "price", "note", "created_at")})
    counts["trades"] = len(trades)

    job = src.execute("SELECT * FROM scheduler_state WHERE job_name='positions'").fetchone()
    if job:
        db.execute("INSERT OR REPLACE INTO wealth_jobs VALUES(?,?,?,?,?)", tuple(job[k] for k in
                   ("job_name", "last_started_at", "last_completed_at", "last_status", "last_error")))
    print(json.dumps({"data_dir": str(svc.DATA), **counts}, ensure_ascii=False))


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else Path.home() / "project" / "wealth"))
