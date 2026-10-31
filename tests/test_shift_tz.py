import importlib.util
import sqlite3
from pathlib import Path

spec = importlib.util.spec_from_file_location("shift_tz", Path(__file__).resolve().parent.parent / "scripts" / "shift_tz.py")
shift_tz = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shift_tz)


def test_shift_only_naive_times_before_cutoff(tmp_path):
    p = tmp_path / "app.db"
    c = sqlite3.connect(p)
    c.execute("create table t (id integer primary key, at text, pub text, day text, body text)")
    c.executemany("insert into t (at, pub, day, body) values (?,?,?,?)", [
        ("2026-10-30T16:25:29", "2026-10-30T16:00:00+00:00", "2026-10-30", "旧记录"),
        ("2026-10-31T07:42:49", "2026-10-30T17:00:00+00:00", "2026-10-31", "新记录"),
        ("2026-10-30T23:59", "", "", "分钟精度"),
    ])
    c.commit()
    c.close()
    assert shift_tz.main(["--db", str(p), "--before", "2026-10-30T16:27:54", "--hours", "15"]) == 0
    assert sqlite3.connect(p).execute("select at from t where id=1").fetchone()[0] == "2026-10-30T16:25:29"  # 预览不写
    assert shift_tz.main(["--db", str(p), "--before", "2026-10-30T16:27:54", "--hours", "15", "--apply"]) == 0
    rows = sqlite3.connect(p).execute("select at, pub, day, body from t order by id").fetchall()
    assert rows[0] == ("2026-10-31T07:25:29", "2026-10-30T16:00:00+00:00", "2026-10-30", "旧记录")
    assert rows[1][0] == "2026-10-31T07:42:49"          # 切换后的不动
    assert rows[2][0] == "2026-10-30T23:59"              # 晚于切换点不动，精度保持
    assert list(tmp_path.glob("app.db.bak-*-tz"))
