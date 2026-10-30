"""测试用临时数据目录；必须在 import app 之前设置。"""
import os
import tempfile

# 总是用新的临时目录：即便从平台的 Agent 子进程里跑测试，也不会写到真实数据
os.environ["SELF_STARTUP_DATA"] = tempfile.mkdtemp(prefix="ss-test-")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture(scope="session")
def client():
    from app.main import app
    return TestClient(app)
