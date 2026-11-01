"""后台常驻启动器（./run.sh -d 用）：跑 uvicorn 子进程，盯 app/ 下的 Python 改动，空闲时自动重启。

- 后台任务（深读 / 调研 / 规划执行…）在各自独立的 runner 进程里跑（app/jobrun.py），重启不影响它们，不用等；
- 对话（SSE）还在服务进程里，重启会断开：改动后先写 data/.reload_pending（页面上显示「等 N 个对话结束后重启」），
  每隔几秒问一次 /api/dev/status，对话都结束了才重启。
- 改出语法错误导致服务起不来：不反复拉起，等下一次改动再试。
- 前端（web/）改动不需要重启，页面自己会刷新（见 web/app.js watchUpdates）。
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from .db import DATA_DIR, ROOT

PORT = int(os.environ.get("PORT", "8780"))
WATCH = [ROOT / "app"]
POLL = 2.0
FLAG = DATA_DIR / ".reload_pending"


def log(msg: str) -> None:
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} supervisor: {msg}", flush=True)


def snapshot() -> dict[str, float]:
    out = {}
    for root in WATCH:
        for p in root.rglob("*.py"):
            try:
                out[str(p)] = p.stat().st_mtime
            except OSError:
                pass
    return out


def changed(old: dict, new: dict) -> list[str]:
    return sorted({p for p in old.keys() | new.keys() if old.get(p) != new.get(p)})


def busy() -> dict | None:
    """None = 服务没响应（起不来或正在启动）。"""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/dev/status", timeout=3) as r:
            return json.loads(r.read())["busy"]
    except Exception:  # noqa: BLE001
        return None


def start(extra: list[str]) -> subprocess.Popen:
    cmd = [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(PORT),
           "--timeout-graceful-shutdown", "30", *extra]
    log("启动服务：" + " ".join(cmd[2:]))
    from .agent import clean_env  # 服务本身（信息源抓取等）也不走继承来的 Claude Code 沙箱代理
    return subprocess.Popen(cmd, cwd=str(ROOT), env=clean_env())


def stop(proc: subprocess.Popen) -> None:
    if proc.poll() is None:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=40)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


def set_flag(files: list[str], b: dict | None) -> None:
    rel = [os.path.relpath(f, ROOT) for f in files][:10]
    try:
        old = json.loads(FLAG.read_text("utf-8")) if FLAG.exists() else {}
    except (OSError, json.JSONDecodeError):
        old = {}
    FLAG.write_text(json.dumps({"since": old.get("since") or time.strftime("%H:%M:%S"),
                                "files": sorted(set(old.get("files", [])) | set(rel))[:10],
                                "busy": b or {}}, ensure_ascii=False), "utf-8")


def main() -> None:
    extra = sys.argv[1:]
    FLAG.unlink(missing_ok=True)
    proc = start(extra)
    seen = snapshot()
    pending: list[str] = []
    stopping = False
    deaf = 0  # 有待重启改动时，服务连续没响应的次数

    def on_term(*_):
        nonlocal stopping
        stopping = True
    signal.signal(signal.SIGTERM, on_term)
    signal.signal(signal.SIGINT, on_term)

    while not stopping:
        time.sleep(POLL)
        now = snapshot()
        diff = changed(seen, now)
        seen = now
        if diff:
            pending = sorted(set(pending) | set(diff))
            log("检测到改动：" + ", ".join(os.path.relpath(f, ROOT) for f in diff[:5]))
        if proc.poll() is not None and not pending:
            continue  # 挂了（多半是改出了错误），等下一次改动再拉起
        if not pending:
            continue
        b = busy() if proc.poll() is None else {"jobs": 0, "chats": 0}
        if b and b["chats"]:
            set_flag(pending, b)
            continue
        if b is None and proc.poll() is None and deaf < 30:
            deaf += 1  # 服务没响应但进程还在（正在启动 / 卡住）：等一分钟，还不行就直接重启
            set_flag(pending, None)
            continue
        deaf = 0
        log(f"空闲，重启以加载 {len(pending)} 个改动")
        stop(proc)
        FLAG.unlink(missing_ok=True)
        pending = []
        proc = start(extra)
    log("退出")
    stop(proc)
    FLAG.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
