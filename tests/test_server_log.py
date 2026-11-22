import logging
import sys

from app import main, supervisor


def access(path: str, status: int = 200) -> logging.LogRecord:
    return logging.LogRecord("uvicorn.access", logging.INFO, "", 0, '%s - "%s %s HTTP/%s" %d',
                             ("127.0.0.1:1", "GET", path, "1.1", status), None)


def test_successful_polls_are_not_access_logged():
    f = main.QuietPolls()
    assert not f.filter(access("/api/dev/status"))
    assert not f.filter(access("/api/jobs/finished?since=2026-11-22T07%3A44%3A53"))
    assert not f.filter(access("/api/notify/since?t=1"))
    assert f.filter(access("/api/dev/status", 500))
    assert f.filter(access("/api/plan/day?date=2026-11-22"))


def test_supervisor_rotates_server_log(tmp_path):
    path = tmp_path / "server.log"
    sink = supervisor.log_sink(path, max_bytes=200, backups=2)
    child = supervisor.subprocess.Popen([sys.executable, "-c", "print('x' * 50 + '\\n') ; [print('line %d ' % i + 'y' * 40) for i in range(30)]"],
                                        stdout=supervisor.subprocess.PIPE, stderr=supervisor.subprocess.STDOUT, text=True)
    supervisor.pump(child, sink)
    child.wait()
    files = sorted(p.name for p in tmp_path.iterdir())
    assert files == ["server.log", "server.log.1", "server.log.2"]
    assert all(p.stat().st_size <= 260 for p in tmp_path.iterdir())
    assert "line 29" in path.read_text()
