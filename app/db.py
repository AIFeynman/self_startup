"""SQLite 存储：一个文件 data/app.db。

核心表在这里定义；每个板块模块可以在自己的文件里声明 SCHEMA（CREATE TABLE IF NOT EXISTS ...），
启动时由 app.modules 统一执行，不需要改本文件。
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("SELF_STARTUP_DATA") or ROOT / "data")
DB_PATH = DATA_DIR / "app.db"

CORE_SCHEMA = """
-- 每日目标与事项：规划写入，复盘读取/打分
CREATE TABLE IF NOT EXISTS tasks (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    date          TEXT NOT NULL,             -- YYYY-MM-DD
    parent_id     INTEGER,                   -- 拆解出的子任务指向父任务
    title         TEXT NOT NULL,
    goal          TEXT DEFAULT '',           -- 完成标准 / 目标
    kind          TEXT DEFAULT 'work',       -- work / learning / life
    priority      INTEGER DEFAULT 2,         -- 1 最高 … 4 最低
    human_level   TEXT DEFAULT 'medium',     -- heavy / medium / light / auto（人干预度）
    executor      TEXT DEFAULT 'human',      -- human / claude / codex / mixed
    est_minutes   INTEGER DEFAULT 30,
    parallel_group TEXT DEFAULT '',          -- 同组可并行
    depends_on    TEXT DEFAULT '[]',         -- JSON [task_id]
    start_time    TEXT DEFAULT '',           -- HH:MM，排程结果
    end_time      TEXT DEFAULT '',
    status        TEXT DEFAULT 'todo',       -- todo / doing / done / partial / dropped
    progress      INTEGER DEFAULT 0,         -- 0-100
    repo          TEXT DEFAULT '',           -- 关联代码库/文档目录（复盘时分析）
    notes         TEXT DEFAULT '',
    created_at    TEXT,
    updated_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_tasks_date ON tasks(date);

-- Agent 对话：每个板块一条或多条会话，记录引擎侧 session id 以便续聊
CREATE TABLE IF NOT EXISTS chat_sessions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    module        TEXT NOT NULL,
    ref           TEXT DEFAULT '',           -- 绑定的对象，如 learn:plan:3、research:12
    engine        TEXT NOT NULL,
    engine_session TEXT DEFAULT '',          -- claude session_id / codex thread_id
    title         TEXT DEFAULT '',
    created_at    TEXT,
    updated_at    TEXT
);
CREATE TABLE IF NOT EXISTS chat_messages (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id    INTEGER NOT NULL,
    role          TEXT NOT NULL,             -- user / assistant / tool / error
    content       TEXT NOT NULL,
    created_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_msgs_session ON chat_messages(session_id);

-- 后台 Agent 任务（调研、深度解析等长任务）
CREATE TABLE IF NOT EXISTS jobs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    module        TEXT NOT NULL,
    ref           TEXT DEFAULT '',
    engine        TEXT NOT NULL,
    prompt        TEXT NOT NULL,
    status        TEXT DEFAULT 'queued',     -- queued / running / done / failed
    output        TEXT DEFAULT '',
    log           TEXT DEFAULT '',
    engine_session TEXT DEFAULT '',
    chat_session_id INTEGER,                 -- 由哪个对话发起；完成后把结果回帖到这个对话
    cwd           TEXT DEFAULT '',           -- 运行目录（审批后续接同一会话要在同一目录）
    created_at    TEXT,
    started_at    TEXT,
    finished_at   TEXT
);

-- 待人审批 / 决策：从 Agent 执行结果里提取（NEEDS_YOU: 行或「需要你做」小节）。
-- 一个任务的事项都决定完后，平台续接那个 Agent 会话把决定发过去（followup_job_id）。
CREATE TABLE IF NOT EXISTS approvals (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id        INTEGER NOT NULL,
    item          TEXT NOT NULL,
    status        TEXT DEFAULT 'pending',    -- pending / approved / rejected / replied / dismissed
    note          TEXT DEFAULT '',
    followup_job_id INTEGER,
    created_at    TEXT,
    decided_at    TEXT,
    UNIQUE(job_id, item)
);
"""

_lock = threading.RLock()


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


_conn: sqlite3.Connection | None = None


def conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = connect()
    return _conn


def init(extra_schemas: Iterable[str] = ()) -> None:
    with _lock:
        c = conn()
        c.executescript(CORE_SCHEMA)
        for s in extra_schemas:
            if s:
                c.executescript(s)
        cols = {r[1] for r in c.execute("PRAGMA table_info(jobs)")}
        if "chat_session_id" not in cols:
            c.execute("ALTER TABLE jobs ADD COLUMN chat_session_id INTEGER")
        if "cwd" not in cols:
            c.execute("ALTER TABLE jobs ADD COLUMN cwd TEXT DEFAULT ''")
        c.commit()


def rows(sql: str, params: Iterable[Any] = ()) -> list[dict]:
    with _lock:
        return [dict(r) for r in conn().execute(sql, tuple(params)).fetchall()]


def row(sql: str, params: Iterable[Any] = ()) -> dict | None:
    with _lock:
        r = conn().execute(sql, tuple(params)).fetchone()
        return dict(r) if r else None


def execute(sql: str, params: Iterable[Any] = ()) -> int:
    """执行写语句，返回 lastrowid（INSERT）或 rowcount。"""
    with _lock:
        cur = conn().execute(sql, tuple(params))
        conn().commit()
        return cur.lastrowid if sql.lstrip().upper().startswith("INSERT") else cur.rowcount


def insert(table: str, data: dict) -> int:
    cols = list(data.keys())
    sql = f"INSERT INTO {table} ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})"
    return execute(sql, [_enc(data[k]) for k in cols])


def update(table: str, id_: int, data: dict) -> int:
    if not data:
        return 0
    sets = ",".join(f"{k}=?" for k in data)
    return execute(f"UPDATE {table} SET {sets} WHERE id=?", [_enc(v) for v in data.values()] + [id_])


def _enc(v: Any) -> Any:
    return json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v
