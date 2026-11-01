"""单个后台任务的执行进程：python -m app.jobrun <job id>（由 jobs.kick 以独立会话启动）。

服务重启不影响它；收到 SIGTERM（平台上点「暂停」）→ 停掉 CLI 子进程，任务记为已暂停、保留会话；
跑完同步一次知识库，再 kick 一次把排队的下一个任务接上。
"""
from __future__ import annotations

import json
import logging
import os
import signal
import sys

from . import agent, db, jobs, kb


def main(jid: int) -> None:
    logging.basicConfig(level=logging.INFO, format=f"%(asctime)s job {jid}: %(message)s")
    j = db.row("SELECT * FROM jobs WHERE id=?", [jid])
    if not j or j["status"] != "running":  # kick 认领时已置为 running；别的状态说明已被暂停 / 处理过
        return
    db.update("jobs", jid, {"pid": os.getpid()})

    def on_term(*_):
        jobs._paused.add(jid)
        if proc := jobs._procs.get(jid):
            agent.stop(proc)
    signal.signal(signal.SIGTERM, on_term)
    jobs._run(jid, j["module"], j["prompt"], j["engine"], j["system"] or "", j["cwd"] or None,
              json.loads(j["add_dirs"] or "[]"), j["session_in"] or "", j.get("model") or "")
    kb._safe_sync()
    jobs.kick()


if __name__ == "__main__":
    db.init()
    main(int(sys.argv[1]))
