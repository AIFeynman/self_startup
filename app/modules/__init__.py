"""板块注册：app/modules/<name>.py 自动发现。

每个板块模块约定（都可选，除 router 外）：
    TITLE: str                        侧边栏名称
    ORDER: int                        侧边栏排序
    router: fastapi.APIRouter         挂载在 /api/<name>
    SCHEMA: str                       CREATE TABLE IF NOT EXISTS ...，启动时执行
    agent_context(ref: str) -> str    给对话 Agent 的数据快照（markdown/JSON 文本）
    agent_dirs(ref: str) -> list[str] 允许 Agent 额外访问的目录（如复盘要分析的代码库）
    on_job_done(job: dict) -> None    后台 job 完成回调（jobs.submit 的结果回写）
"""
from __future__ import annotations

import importlib
import logging
import pkgutil
from types import ModuleType

log = logging.getLogger(__name__)

_registry: dict[str, ModuleType] = {}


def discover() -> dict[str, ModuleType]:
    if _registry:
        return _registry
    for info in pkgutil.iter_modules(__path__):
        if info.name.startswith("_"):
            continue
        try:
            _registry[info.name] = importlib.import_module(f"{__name__}.{info.name}")
        except Exception:  # 单个板块坏了不影响其它板块
            log.exception("加载板块 %s 失败", info.name)
    return _registry


def get(name: str) -> ModuleType | None:
    return discover().get(name)


def meta() -> list[dict]:
    mods = discover()
    out = [{"id": k, "title": getattr(m, "TITLE", k), "order": getattr(m, "ORDER", 50)} for k, m in mods.items()]
    return sorted(out, key=lambda x: x["order"])
