"""FastAPI 入口：挂载核心接口 + 自动发现的板块 + 静态前端。"""
from __future__ import annotations

import json
import logging
import time

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import agent, chat, db, jobs, kb, modules, settings, tasks

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(title="本地学习平台", version="0.1.0")

mods = modules.discover()
db.init(getattr(m, "SCHEMA", "") for m in mods.values())

app.include_router(chat.router)
app.include_router(jobs.router)
app.include_router(tasks.router)
for name, m in mods.items():
    if hasattr(m, "router"):
        app.include_router(m.router, prefix=f"/api/{name}", tags=[name])


@app.on_event("startup")
def _startup():
    jobs._mark_interrupted()  # 只在真正启动服务时清理上次中断的任务
    kb.schedule_sync(0.5)
    for m in mods.values():  # 板块自己的后台任务（如信息推荐的定时刷新）
        if hasattr(m, "on_startup"):
            m.on_startup()


@app.middleware("http")
async def _kb_sync_after_write(request: Request, call_next):
    """任何写接口之后，防抖同步一次知识库（data/kb）。"""
    resp = await call_next(request)
    if request.url.path.startswith("/static/"):
        resp.headers["Cache-Control"] = "no-cache"  # 本地开发：前端改动立即生效
    if request.method != "GET" and request.url.path.startswith("/api/") and not request.url.path.startswith(("/api/chat", "/api/kb")):
        kb.schedule_sync()
    return resp


STARTED = time.time()
RELOAD_FLAG = db.DATA_DIR / ".reload_pending"  # supervisor 写：后端有改动、等任务结束后重启


def busy() -> dict:
    """正在跑的后台任务和对话；supervisor 只在都为 0 时重启，避免杀掉任务。"""
    n = (db.row("SELECT count(*) AS n FROM jobs WHERE status IN ('queued','running')") or {}).get("n", 0)
    return {"jobs": n, "chats": chat.active}


def static_version() -> float:
    web = db.ROOT / "web"
    return max((p.stat().st_mtime for p in web.rglob("*") if p.is_file()), default=0)


@app.get("/api/dev/status")
def dev_status():
    """前端轮询：前端文件变了就自动刷新；后端等重启时显示提示。"""
    pending = None
    if RELOAD_FLAG.exists():
        try:
            pending = json.loads(RELOAD_FLAG.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            pending = {}
    return {"started": STARTED, "static_version": static_version(), "busy": busy(), "reload_pending": pending}


@app.get("/api/meta")
def meta():
    return {"modules": modules.meta(), "today": db.today(),
            "engines": {e: agent.available(e) for e in ("claude", "codex")}}


@app.get("/api/settings")
def get_settings():
    return settings.load()


@app.put("/api/settings")
def put_settings(body: dict):
    return settings.save(body)


app.mount("/static", StaticFiles(directory=str(db.ROOT / "web")), name="static")


@app.get("/")
def index():
    return FileResponse(db.ROOT / "web" / "index.html")
