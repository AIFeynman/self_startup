"""把平台时区切换前写下的时间校准到当前时区：库里所有「不带时区、早于切换点」的时间串平移 N 小时。

平台用 db.now()（进程本地时区的 naive 时间）记时间；时区从系统时区改成推断/设置的时区后，旧记录还是旧时区的钟点，
和新记录混在一起排序、算耗时都会错。只改时间值本身，不删不改任何内容；带时区（+00:00 / Z）的外部时间和纯日期不动。

用法（默认只预览，加 --apply 才写，写前自动备份 app.db）：
  uv run python scripts/shift_tz.py --before 2026-10-30T16:27:54 --hours 15
  uv run python scripts/shift_tz.py --before 2026-10-30T16:27:54 --hours 15 --apply
切换点 = 服务按新时区重启的时刻（旧时区钟点），见 data/logs/server.log 的 supervisor 重启行。
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAIVE = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2})?$")
SKIP_TABLES = re.compile(r"^(sqlite_|kb_fts)")   # 全文索引是派生数据，由知识库同步重建


def plan(conn: sqlite3.Connection, before: str, hours: float) -> list[tuple[str, str, int, str, str]]:
    """返回 [(表, 列, rowid, 旧值, 新值)]。"""
    out = []
    tables = [r[0] for r in conn.execute("select name from sqlite_master where type='table'")]
    for t in tables:
        if SKIP_TABLES.match(t):
            continue
        for col in [r[1] for r in conn.execute(f'pragma table_info("{t}")')]:
            rows = conn.execute(f'select rowid, "{col}" from "{t}" where typeof("{col}")=\'text\' '
                                f'and "{col}" glob \'[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]?[0-9][0-9]:*\'')
            for rid, v in rows:
                if not NAIVE.match(v) or v.replace(" ", "T") >= before:
                    continue
                spec = "seconds" if len(v) > 16 else "minutes"
                new = (datetime.fromisoformat(v) + timedelta(hours=hours)).isoformat(timespec=spec)
                out.append((t, col, rid, v, new))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=str(ROOT / "data" / "app.db"))
    ap.add_argument("--before", required=True, help="切换点（旧时区钟点），早于它的时间才平移")
    ap.add_argument("--hours", type=float, required=True, help="平移小时数（新时区偏移 − 旧时区偏移）")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    before = datetime.fromisoformat(a.before).isoformat(timespec="seconds")
    conn = sqlite3.connect(a.db)
    changes = plan(conn, before, a.hours)
    by_col: dict[str, list] = {}
    for t, col, _rid, old, new in changes:
        by_col.setdefault(f"{t}.{col}", []).append((old, new))
    for k, vs in sorted(by_col.items()):
        print(f"{k}: {len(vs)} 条，例 {vs[0][0]} → {vs[0][1]}")
    print(f"合计 {len(changes)} 个时间值")
    if not a.apply or not changes:
        print("（预览，未写入；加 --apply 执行）" if changes else "无需校准")
        return 0
    bak = Path(a.db).with_name(f"{Path(a.db).name}.bak-{datetime.now():%Y%m%d-%H%M%S}-tz")
    with sqlite3.connect(bak) as dst:   # 用 backup API，连同 WAL 里还没落盘的一起备份
        conn.backup(dst)
    with conn:
        for t, col, rid, old, new in changes:
            conn.execute(f'update "{t}" set "{col}"=? where rowid=? and "{col}"=?', (new, rid, old))
    print(f"已写入；备份在 {bak}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
