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
first=$(printf '%s' "$2" | head -n 1)
echo '{"type":"result","result":"ok '"$first"'","session_id":"fake-sess"}'
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


def test_cap_equals_agent_concurrency():
    assert jobs._cap() == int(settings.load()["max_agent_concurrency"])


def test_busy_machine_keeps_jobs_queued(client, monkeypatch):
    db.execute("UPDATE jobs SET status='done' WHERE status IN ('queued','running')")
    spawned = []
    monkeypatch.setattr(jobs, "_spawn", spawned.append)
    monkeypatch.setattr(jobs.os, "getloadavg", lambda: (999.0, 0, 0))
    jid = db.insert("jobs", {"module": "nomod", "engine": "claude", "prompt": "p", "status": "queued", "created_at": db.now()})
    assert jobs.kick() == [] and not spawned
    m = client.get("/api/jobs/machine").json()
    assert not m["ok"] and "CPU 负载" in m["reason"] and m["queued"] == 1

    monkeypatch.setattr(jobs.os, "getloadavg", lambda: (0.1, 0, 0))
    monkeypatch.setattr(jobs, "_free_mem_gb", lambda: 1.0)
    assert jobs.kick() == [] and "可用内存" in jobs.machine()["reason"]

    monkeypatch.setattr(jobs, "_free_mem_gb", lambda: 64.0)
    assert jobs.kick() == [jid] == spawned  # 机器闲下来，排队的接上
    db.execute("UPDATE jobs SET status='done' WHERE status IN ('queued','running')")


def test_every_job_prompt_carries_resource_rule(monkeypatch):
    monkeypatch.setattr(jobs, "kick", lambda: [])
    jid = jobs.submit("nomod", "做件事")
    p = db.row("SELECT prompt FROM jobs WHERE id=?", [jid])["prompt"]
    assert p.startswith("做件事") and "不要在后台挂常驻进程" in p and "一次只跑一路" in p
    db.update("jobs", jid, {"status": "done"})


def test_free_mem_reads_this_machine():
    assert jobs._free_mem_gb() is None or jobs._free_mem_gb() > 0


def test_finished_skips_paused(client):
    jid = db.insert("jobs", {"module": "nomod", "engine": "claude", "prompt": "p", "status": "paused",
                             "created_at": db.now(), "finished_at": "2099-01-01T00:00:00"})
    assert jid not in [j["id"] for j in client.get("/api/jobs/finished", params={"since": "2098-12-31"}).json()]
