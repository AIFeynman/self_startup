"""任务在独立的 runner 进程里跑：排队与并发上限、进程不在了的清理、跨进程暂停。"""
import os
import stat
import subprocess
import sys
import time

import pytest

from app import db, jobs, settings

FAKE_CLAUDE = """#!/bin/sh
# 假的 claude CLI：输出 stream-json；提示词里有 slow 就先停 30 秒（用来测暂停）
echo '{"type":"system","subtype":"init","session_id":"fake-sess"}'
echo '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Bash","input":{"command":"echo hi"}}]}}'
case "$2" in *slow*) sleep 30 ;; esac
echo '{"type":"result","result":"ok '"$2"'","session_id":"fake-sess"}'
"""


def _wait(jid, until, timeout=15):
    end = time.time() + timeout
    while time.time() < end:
        j = db.row("SELECT * FROM jobs WHERE id=?", [jid])
        if until(j):
            return j
        time.sleep(0.2)
    raise AssertionError(f"job {jid} 超时：{j['status']} {j['log']}")


@pytest.fixture
def fake_claude(tmp_path):
    p = tmp_path / "claude"
    p.write_text(FAKE_CLAUDE)
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    old = settings.load()["engines"]["claude"].get("bin", "claude")
    settings.save({"engines": {"claude": {"bin": str(p)}}})
    yield p
    settings.save({"engines": {"claude": {"bin": old}}})


@pytest.mark.real_runner
def test_runner_process_runs_and_pauses(client, fake_claude):
    jid = jobs.submit("nomod", "fast", engine="claude")
    j = _wait(jid, lambda j: j["status"] not in ("queued", "running"))
    assert j["status"] == "done" and j["output"] == "ok fast" and j["pid"] and j["pid"] != os.getpid()
    assert j["engine_session"] == "fake-sess" and "[tool] Bash: echo hi" in j["log"]

    jid = jobs.submit("nomod", "slow", engine="claude")
    j = _wait(jid, lambda j: j["pid"] and "[tool]" in (j["log"] or ""))
    assert client.post(f"/api/jobs/{jid}/pause").json() == {"ok": True}
    j = _wait(jid, lambda j: j["status"] != "running", timeout=8)  # 不用等那 30 秒
    assert j["status"] == "paused" and j["engine_session"] == "fake-sess"
    time.sleep(0.5)
    jobs.reap()  # 回收退出的子进程
    assert not jobs._alive(j["pid"])  # runner 自己也退出了


def test_kick_respects_cap_and_reaps_dead_runners(client, monkeypatch):
    db.execute("UPDATE jobs SET status='done' WHERE status IN ('queued','running')")
    spawned = []
    monkeypatch.setattr(jobs, "_spawn", spawned.append)
    ids = [db.insert("jobs", {"module": "nomod", "engine": "claude", "prompt": "p", "status": "queued", "created_at": db.now()})
           for _ in range(jobs._cap() + 2)]
    assert jobs.kick() == ids[:jobs._cap()] == spawned
    assert jobs.kick() == []  # 满了

    # 有一个 runner 没了（被杀 / 机器重启）：记为失败，空出的位置给下一个
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    db.update("jobs", ids[0], {"pid": dead.pid})
    for jid in ids[1:jobs._cap()]:
        db.update("jobs", jid, {"pid": os.getpid()})
    assert jobs.kick() == [ids[jobs._cap()]]
    assert db.row("SELECT status,log FROM jobs WHERE id=?", [ids[0]])["status"] == "failed"
    db.execute("UPDATE jobs SET status='done' WHERE status IN ('queued','running')")


def test_supervisor_waits_only_for_chats():
    from app import supervisor
    src = open(supervisor.__file__, encoding="utf-8").read()
    assert 'if b and b["chats"]:' in src
