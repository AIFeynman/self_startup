"""开源雷达的长任务进程：python -m app.modules._oss_run <run id>（由 intel.start_run 以独立会话启动）。

任务（oss_runs.task）：
    collect   全量切片拉取（约 20-40 分钟，只调 GitHub）
    label     标注队列（progress.limit 限量；全量 6.6 万个约 6-9 小时，走订阅 Haiku）
    daily     每日新增：门槛段做差 + 7 天新建 + 信息推荐里的高星仓库，再标注新进来的
    weekly    每周刷新：GraphQL 刷 star / push / 归档 / 改名，再标注需要重标的
服务重启不影响它；SIGTERM（页面上点「停止」）→ 当前批次做完后停，状态记 stopped，下次接着跑（标注按 label_src 续）。
"""
from __future__ import annotations

import json
import logging
import os
import signal
import sys
import traceback

from .. import db

_stop = False


def _set(rid: int, **kw) -> None:
    if "progress" in kw:
        kw["progress"] = json.dumps(kw["progress"], ensure_ascii=False)
    db.update("oss_runs", rid, kw)


def main(rid: int) -> None:
    global _stop
    from . import _oss_collect as col, _oss_label as lab
    logging.basicConfig(level=logging.INFO, format=f"%(asctime)s oss run {rid}: %(message)s")
    r = db.row("SELECT * FROM oss_runs WHERE id=?", [rid])
    if not r or r["status"] != "running":
        return
    db.update("oss_runs", rid, {"pid": os.getpid()})
    prog = json.loads(r["progress"] or "{}")
    limit = int(prog.get("limit") or 0)

    def on_term(*_):
        global _stop
        _stop = True
    signal.signal(signal.SIGTERM, on_term)

    class Stopped(Exception):
        pass

    def tick(stage: str):
        def f(*a):
            if _stop:
                raise Stopped
            prog[stage] = [x if not isinstance(x, dict) else {k: v for k, v in x.items() if k != "errors"} for x in a]
            _set(rid, progress=prog)
        return f

    try:
        if r["task"] == "collect":
            prog["collect"] = col.collect_all(on_page=tick("page"))
        elif r["task"] == "daily":
            prog["collect"] = col.collect_new(on_page=tick("page"))
        elif r["task"] == "weekly":
            prog["refresh"] = col.refresh(on_batch=tick("refresh_at"))
        if r["task"] in ("label", "daily", "weekly"):
            prog["label"] = lab.run(limit=limit, on_progress=tick("label_at"))
        _set(rid, status="done", progress=prog, finished=db.now())
    except Stopped:
        _set(rid, status="stopped", progress=prog, finished=db.now())
    except Exception as e:  # noqa: BLE001
        _set(rid, status="failed", progress=prog, finished=db.now(),
             log=f"{type(e).__name__}: {e}\n{traceback.format_exc()[-1500:]}")


if __name__ == "__main__":
    from .. import modules
    db.init([getattr(m, "SCHEMA", "") for m in modules.discover().values()])
    main(int(sys.argv[1]))
