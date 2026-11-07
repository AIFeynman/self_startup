"""测试用临时数据目录；必须在 import app 之前设置。"""
import os
import tempfile

# 总是用新的临时目录：即便从平台的 Agent 子进程里跑测试，也不会写到真实数据
os.environ["SELF_STARTUP_DATA"] = tempfile.mkdtemp(prefix="ss-test-")
# 测试不读真实的 Claude Code / Codex 会话日志
import json as _json  # noqa: E402
from pathlib import Path as _Path  # noqa: E402

_Path(os.environ["SELF_STARTUP_DATA"], "settings.json").write_text(_json.dumps({"session_dirs": {"claude": [], "codex": []}, "notify": {"system": False}}))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture(scope="session")
def client():
    from app.main import app
    return TestClient(app)


@pytest.fixture(autouse=True)
def _no_runner(request, monkeypatch):
    """默认不真的起 runner 进程（否则排队的测试任务会去调真实的 claude）；标了 real_runner 的测试除外。"""
    if request.node.get_closest_marker("real_runner"):
        return
    from app import jobs
    monkeypatch.setattr(jobs, "_spawn", lambda jid: None)


@pytest.fixture(autouse=True)
def _idle_machine(request, monkeypatch):
    """默认当机器空闲：kick 会看本机真实负载 / 内存，跑测试时机器忙就不起任务，测试时好时坏；标了 real_machine 的测试除外。"""
    if request.node.get_closest_marker("real_machine"):
        return
    from app import jobs
    monkeypatch.setattr(jobs.os, "getloadavg", lambda: (0.1, 0.1, 0.1))
    monkeypatch.setattr(jobs, "_free_mem_gb", lambda: 64.0)


@pytest.fixture(autouse=True)
def _no_graph_refresh(monkeypatch):
    """kb.sync() 默认会在后台起概念抽取；测试里不调真实 DeepSeek，需要时直接调 kb_graph.refresh()。"""
    from app import kb_graph
    monkeypatch.setattr(kb_graph, "schedule_refresh", lambda: None)


@pytest.fixture(autouse=True)
def _no_span_leftovers(request):
    """跨日 / 不设结束的事项会出现在之后每一天，测试结束就删掉，免得串到别的测试的日期里。"""
    yield
    if "client" in request.fixturenames:
        from app import db
        db.execute("DELETE FROM tasks WHERE end_date IS NULL OR end_date>date")


def pytest_configure(config):
    config.addinivalue_line("markers", "real_machine: 读本机真实的负载 / 内存")
    config.addinivalue_line("markers", "real_runner: 真的起 app.jobrun 进程（配合假的 claude CLI）")
