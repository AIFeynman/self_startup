"""实践 TAB：课程解析、执行输出合并、阿里云按需开关机（假 aliyun / ssh）、看门狗、接口。不联网、不开机。"""
import json
import time
from types import SimpleNamespace

import pytest

from app import db
from app.modules import _practice_kernel as K, _practice_runtime as RT, practice as P


@pytest.fixture(autouse=True)
def _clean(client):
    for t in ("practice_runtime", "practice_cells", "practice_kernels", "practice_done"):
        db.execute(f"DELETE FROM {t}")
    K.EXECS.clear()


LESSON = """# 3 模型结构
<!-- minutes: 12 -->
<!-- know: GQA, RoPE -->

开头说明。

## 搭出模型
讲解一段。

```python
x = 1
```

> 思考：为什么？

## 训练
```python long gpu
train()
```
收尾。
"""


def test_parse_lesson_steps_cells_and_asks():
    L = P.parse_lesson(LESSON)
    assert L["title"] == "3 模型结构" and L["intro"] == "开头说明。" and L["meta"]["know"] == "GQA, RoPE"
    s1, s2 = L["steps"]
    assert s1["title"] == "搭出模型" and [p["type"] for p in s1["parts"]] == ["md", "code", "ask"]
    assert s1["parts"][1] == {"type": "code", "n": 0, "code": "x = 1", "long": False, "gpu": False}
    assert s1["parts"][2]["text"] == "为什么？"
    assert s2["parts"][0]["n"] == 1 and s2["parts"][0]["long"] and s2["parts"][0]["gpu"] and s2["parts"][1]["text"] == "收尾。"


def test_builtin_courses_parse_and_have_cells():
    got = {c["id"]: c for c in P.courses()["courses"]}
    assert got["minimind"]["runtime"] == "cloud" and got["agents-basics"]["runtime"] == "local"
    for cid in got:
        c = P.load_course(cid)
        assert c["lessons"] and all(x["cells"] > 0 for x in c["lessons"])
        for x in c["lessons"]:
            L = P.parse_lesson(P.lesson_path(c, x["id"]).read_text(encoding="utf-8"))
            codes = [p["code"] for s in L["steps"] for p in s["parts"] if p["type"] == "code"]
            for code in codes:
                compile(code, f"{cid}/{x['id']}", "exec")   # 课程里的代码至少语法正确


def test_apply_merges_streams_updates_displays_and_finishes():
    out = []
    assert not K.apply(out, {"msg_type": "stream", "content": {"name": "stdout", "text": "a"}})
    K.apply(out, {"msg_type": "stream", "content": {"name": "stdout", "text": "b"}})
    K.apply(out, {"msg_type": "display_data", "content": {"data": {K.VIZ_MIME: {"kind": "line", "series": []}, "text/plain": "x"},
                                                           "transient": {"display_id": "d1"}}})
    K.apply(out, {"msg_type": "update_display_data", "content": {"data": {K.VIZ_MIME: {"kind": "line", "series": [[1]]}},
                                                                  "transient": {"display_id": "d1"}}})
    K.apply(out, {"msg_type": "error", "content": {"ename": "ValueError", "evalue": "bad", "traceback": ["tb"]}})
    assert out[0] == {"type": "stream", "name": "stdout", "text": "ab"}
    assert out[1]["data"] == {K.VIZ_MIME: {"kind": "line", "series": [[1]]}}   # 原地更新，富输出不带 text/plain
    assert out[2]["ename"] == "ValueError"
    assert K.apply(out, {"msg_type": "status", "content": {"execution_state": "idle"}})


def fake_transport(replies):
    def transport():
        sent = []

        def send(m):
            sent.append(m)

        def recv(timeout):
            if not replies:
                return None
            r = replies.pop(0)
            return {**r, "parent_header": {"msg_id": sent[0]["header"]["msg_id"]}, "channel": "iopub"}
        return send, recv, lambda: None
    return transport


def wait(e):
    for _ in range(100):
        if e.status not in ("queued", "running"):
            return
        time.sleep(0.02)


def test_execute_collects_outputs_and_saves_cell():
    replies = [{"msg_type": "status", "content": {"execution_state": "busy"}},
               {"msg_type": "stream", "content": {"name": "stdout", "text": "hi\n"}},
               {"msg_type": "status", "content": {"execution_state": "idle"}}]
    e = K.execute("minimind:00-env:1", "print('hi')", fake_transport(replies))
    wait(e)
    assert e.status == "done" and e.outputs == [{"type": "stream", "name": "stdout", "text": "hi\n"}]
    row = db.row("SELECT * FROM practice_cells WHERE k='minimind:00-env:1'")
    assert row["status"] == "done" and row["lesson"] == "00-env" and json.loads(row["outputs"])[0]["text"] == "hi\n"

    def broken():
        raise ConnectionError("tunnel down")
    e2 = K.execute("minimind:00-env:2", "x", broken)
    wait(e2)
    assert e2.status == "failed" and "tunnel down" in e2.outputs[0]["evalue"]


# ---------- 阿里云：假 aliyun / ssh ----------

class FakeAli:
    def __init__(self, have_net=False):
        self.calls, self.have_net = [], have_net

    def __call__(self, cmd, timeout=600):
        self.calls.append(cmd)
        out = {}
        if cmd[0] == "aliyun":
            api = cmd[4]
            out = {"DescribeSpotPriceHistory": {"SpotPrices": {"SpotPriceType": [{"SpotPrice": 3.9 if "cn-hangzhou-j" in cmd else 3.3}]}},
                   "DescribeVpcs": {"Vpcs": {"Vpc": [{"VpcId": "vpc-1"}]}},
                   "DescribeVSwitches": {"VSwitches": {"VSwitch": [{"VSwitchId": "vsw-1"}] if self.have_net else []}},
                   "CreateVSwitch": {"VSwitchId": "vsw-new"},
                   "DescribeSecurityGroups": {"SecurityGroups": {"SecurityGroup": [{"SecurityGroupId": "sg-1"}] if self.have_net else []}},
                   "CreateSecurityGroup": {"SecurityGroupId": "sg-new"},
                   "DescribeKeyPairs": {"KeyPairs": {"KeyPair": [{"KeyPairName": "ss-practice"}] if self.have_net else []}},
                   "DescribeImages": {"Images": {"Image": [{"ImageId": "ubuntu_22_04_x64_100G_with_gpu_driver_and_cuda_alibase_20260909.vhd"},
                                                           {"ImageId": "ubuntu_22_04_x64_20G_alibase.vhd"}]}},
                   "RunInstances": {"InstanceIdSets": {"InstanceIdSet": ["i-abc"]}},
                   "DescribeInstances": {"Instances": {"Instance": [{"Status": "Running", "PublicIpAddress": {"IpAddress": ["1.2.3.4"]}}]}},
                   }.get(api, {})
        return SimpleNamespace(returncode=0, stdout=json.dumps(out), stderr="")

    def api(self, name):
        return [c for c in self.calls if c[0] == "aliyun" and c[4] == name]


@pytest.fixture
def cloud(monkeypatch, tmp_path):
    fake = FakeAli()
    monkeypatch.setattr(RT, "ROOT", tmp_path)
    (tmp_path / "ssh").mkdir()
    (tmp_path / "ssh" / "id_ed25519").write_text("k")
    (tmp_path / "ssh" / "id_ed25519.pub").write_text("ssh-ed25519 AAAA ss-practice")
    monkeypatch.setattr(RT, "Cloud", lambda runner=None, _C=RT.Cloud: _C(runner or fake))
    monkeypatch.setitem(RT.RUNNERS, "cloud", RT.Cloud)
    monkeypatch.setattr(RT.subprocess, "Popen", lambda *a, **k: SimpleNamespace(pid=99999999, kill=lambda: None))
    monkeypatch.setattr(K.Server, "ok", lambda self: True)
    monkeypatch.setattr(RT, "threading", SimpleNamespace(Thread=lambda target, **k: SimpleNamespace(start=target), Lock=RT.threading.Lock))
    return fake


def test_cloud_quote_then_boot_creates_network_and_spot_instance_with_auto_release(client, cloud):
    q = client.post("/api/practice/runtime/start", json={"kind": "cloud"}).json()["quote"]
    assert q["zone"] == "cn-hangzhou-k" and q["price"] == round(3.3 + RT.CLOUD_DEFAULTS["disk_yuan_h"], 3)
    assert not cloud.api("RunInstances")                       # 只报价，不开机
    v = client.post("/api/practice/runtime/start", json={"kind": "cloud", "confirm": True}).json()
    assert v["status"] == "ready" and v["ip"] == "1.2.3.4"
    assert cloud.api("CreateVSwitch") and cloud.api("CreateSecurityGroup") and cloud.api("ImportKeyPair")
    run = cloud.api("RunInstances")[0]
    arg = lambda k: run[run.index(k) + 1]  # noqa: E731
    assert arg("--SpotStrategy") == "SpotAsPriceGo" and arg("--ZoneId") == "cn-hangzhou-k" and arg("--VSwitchId") == "vsw-new"
    assert arg("--ImageId").startswith("ubuntu_22_04_x64_100G_with_gpu_driver")
    assert arg("--AutoReleaseTime").endswith("Z")              # 平台挂了也会到点释放
    assert any(c[0] == "ssh" and "cloud_setup.sh" in c[-1] for c in cloud.calls)


def test_guard_releases_idle_or_over_budget_instance(client, cloud):
    client.post("/api/practice/runtime/start", json={"kind": "cloud", "confirm": True})
    assert RT.guard() == ""
    db.execute("UPDATE practice_runtime SET last_active=? WHERE kind='cloud'", [time.time() - 31 * 60])
    assert RT.guard() == "idle"
    assert cloud.api("DeleteInstance")[0][cloud.api("DeleteInstance")[0].index("--InstanceId") + 1] == "i-abc"
    assert RT.state("cloud")["status"] == "stopped"
    client.post("/api/practice/runtime/start", json={"kind": "cloud", "confirm": True})
    db.execute("UPDATE practice_runtime SET started_at=? WHERE kind='cloud'", [time.time() - 10 * 3600])
    assert RT.guard() == "cap" and len(cloud.api("DeleteInstance")) == 2


def test_boot_failure_releases_instance(client, cloud, monkeypatch):
    monkeypatch.setattr(K.Server, "ok", lambda self: False)
    monkeypatch.setattr(RT.time, "sleep", lambda s: None)
    v = client.post("/api/practice/runtime/start", json={"kind": "cloud", "confirm": True}).json()
    assert RT.state("cloud")["status"] == "failed" and cloud.api("DeleteInstance")
    assert v["kind"] == "cloud"


def test_api_lesson_run_guard_and_progress(client, monkeypatch):
    L = client.get("/api/practice/courses/agents-basics/lessons/00-loop").json()
    assert L["steps"] and L["cells"] == {} and not L["done"]
    r = client.post("/api/practice/run", json={"course": "agents-basics", "lesson": "00-loop", "cell": 0, "code": "1"})
    assert r.status_code == 409                                 # 运行环境没开
    assert client.get("/api/practice/for", params={"url": "https://github.com/jingyaogong/minimind/"}).json()["id"] == "minimind"
    n = P.load_course("agents-basics")["lessons"][0]["cells"]
    for i in range(n):
        db.execute("INSERT INTO practice_cells (k, course, lesson, cell, status) VALUES (?,?,?,?, 'done')",
                   [f"agents-basics:00-loop:{i}", "agents-basics", "00-loop", str(i)])
    P._maybe_done("agents-basics:00-loop:0")
    assert client.get("/api/practice/courses/agents-basics").json()["done"]["00-loop"]
    assert db.row("SELECT * FROM read_log WHERE kind='practice'")["url"] == "#practice/agents-basics/00-loop"
