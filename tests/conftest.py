"""测试用临时数据目录；必须在 import app 之前设置。"""
import os
import tempfile

# 总是用新的临时目录：即便从平台的 Agent 子进程里跑测试，也不会写到真实数据
os.environ["SELF_STARTUP_DATA"] = tempfile.mkdtemp(prefix="ss-test-")
# 测试不读真实的 Claude Code / Codex 会话日志
import json as _json  # noqa: E402
from pathlib import Path as _Path  # noqa: E402

_Path(os.environ["SELF_STARTUP_DATA"], "settings.json").write_text(_json.dumps({"session_dirs": {"claude": [], "codex": []}}))

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


def pytest_configure(config):
    config.addinivalue_line("markers", "real_runner: 真的起 app.jobrun 进程（配合假的 claude CLI）")
