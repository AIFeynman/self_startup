"""实践 TAB 的代码执行：对接 Jupyter Server（REST + WebSocket），本机和阿里云同一套协议，云端经 SSH 隧道。

执行由后端线程收集输出（stream / display_data / update_display_data / error），存进内存和 practice_cells，
前端轮询 /api/practice/exec/{id} 取增量——关掉页面训练也不中断，回来能看到完整输出。
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from datetime import datetime, timezone

import httpx

from .. import db

VIZ_MIME = "application/vnd.ssviz+json"
KEEP_MIMES = (VIZ_MIME, "image/png", "image/svg+xml", "text/html", "text/plain")
MAX_TEXT = 200_000


class Server:
    """一个 Jupyter Server 的地址 + token。"""

    def __init__(self, base: str, token: str):
        self.base, self.token = base.rstrip("/"), token

    def _h(self):
        return {"Authorization": f"token {self.token}"}

    def ok(self) -> bool:
        try:
            return httpx.get(self.base + "/api/status", headers=self._h(), timeout=5, trust_env=False).status_code == 200
        except httpx.HTTPError:
            return False

    def kernel_alive(self, kid: str) -> bool:
        try:
            return httpx.get(f"{self.base}/api/kernels/{kid}", headers=self._h(), timeout=5, trust_env=False).status_code == 200
        except httpx.HTTPError:
            return False

    def new_kernel(self) -> str:
        r = httpx.post(self.base + "/api/kernels", headers=self._h(), json={"name": "python3"}, timeout=30, trust_env=False)
        r.raise_for_status()
        return r.json()["id"]

    def interrupt(self, kid: str) -> None:
        httpx.post(f"{self.base}/api/kernels/{kid}/interrupt", headers=self._h(), timeout=10, trust_env=False)

    def shutdown(self, kid: str) -> None:
        try:
            httpx.delete(f"{self.base}/api/kernels/{kid}", headers=self._h(), timeout=10, trust_env=False)
        except httpx.HTTPError:
            pass

    def restart(self, kid: str) -> None:
        httpx.post(f"{self.base}/api/kernels/{kid}/restart", headers=self._h(), timeout=60, trust_env=False)

    def ws_url(self, kid: str) -> str:
        return self.base.replace("http", "ws", 1) + f"/api/kernels/{kid}/channels?token={self.token}"


def _msg(code: str, session: str) -> dict:
    return {"header": {"msg_id": uuid.uuid4().hex, "username": "ss", "session": session, "msg_type": "execute_request",
                       "version": "5.3", "date": datetime.now(timezone.utc).isoformat()},
            "parent_header": {}, "metadata": {}, "channel": "shell", "buffers": [],
            "content": {"code": code, "silent": False, "store_history": True, "user_expressions": {},
                        "allow_stdin": False, "stop_on_error": True}}


def ws_transport(server: Server, kid: str):
    """真实传输：返回 (send, recv)。recv 超时返回 None。"""
    from websockets.sync.client import connect
    ws = connect(server.ws_url(kid), open_timeout=20, max_size=None, ping_interval=20, ping_timeout=60)

    def send(m):
        ws.send(json.dumps(m))

    def recv(timeout):
        try:
            return json.loads(ws.recv(timeout=timeout))
        except TimeoutError:
            return None

    def close():
        ws.close()
    return send, recv, close


def _clip(data: dict) -> dict:
    out = {k: data[k] for k in KEEP_MIMES if k in data}
    if VIZ_MIME in out or "image/png" in out or "image/svg+xml" in out:
        out.pop("text/plain", None)
    return out


def apply(outputs: list[dict], m: dict) -> bool:
    """把一条 iopub 消息并入输出列表；返回这次执行是否结束（kernel 回到 idle）。"""
    t, c = m.get("msg_type") or m.get("header", {}).get("msg_type"), m.get("content", {})
    if t == "stream":
        if outputs and outputs[-1]["type"] == "stream" and outputs[-1]["name"] == c["name"]:
            outputs[-1]["text"] = (outputs[-1]["text"] + c["text"])[-MAX_TEXT:]
        else:
            outputs.append({"type": "stream", "name": c["name"], "text": c["text"][-MAX_TEXT:]})
    elif t in ("display_data", "execute_result"):
        did = (c.get("transient") or {}).get("display_id")
        outputs.append({"type": "data", "data": _clip(c.get("data", {})), "id": did})
    elif t == "update_display_data":
        did = (c.get("transient") or {}).get("display_id")
        for o in outputs:
            if o.get("id") == did:
                o["data"] = _clip(c.get("data", {}))
    elif t == "error":
        outputs.append({"type": "error", "ename": c.get("ename", ""), "evalue": c.get("evalue", ""),
                        "traceback": c.get("traceback", [])[-30:]})
    elif t == "status" and c.get("execution_state") == "idle":
        return True
    return False


class Exec:
    def __init__(self, key: str, code: str):
        self.id, self.key, self.code = uuid.uuid4().hex[:12], key, code
        self.outputs: list[dict] = []
        self.status, self.started, self.ended, self.ver = "queued", time.time(), 0.0, 0

    def view(self) -> dict:
        return {"id": self.id, "key": self.key, "status": self.status, "outputs": self.outputs, "ver": self.ver,
                "secs": round((self.ended or time.time()) - self.started, 1)}


EXECS: dict[str, Exec] = {}
LOCK = threading.Lock()


def running() -> list[Exec]:
    return [e for e in EXECS.values() if e.status in ("queued", "running")]


def save(e: Exec) -> None:
    course, lesson, cell = (e.key.split(":") + ["", "", ""])[:3]
    db.execute("INSERT INTO practice_cells (k, course, lesson, cell, code, outputs, status, secs, at) VALUES (?,?,?,?,?,?,?,?,?) "
               "ON CONFLICT(k) DO UPDATE SET code=excluded.code, outputs=excluded.outputs, status=excluded.status, "
               "secs=excluded.secs, at=excluded.at",
               [e.key, course, lesson, cell, e.code, json.dumps(e.outputs, ensure_ascii=False), e.status,
                e.view()["secs"], db.now()])


def execute(key: str, code: str, transport, on_activity=lambda: None) -> Exec:
    """开线程执行一格。transport() -> (send, recv, close)。"""
    e = Exec(key, code)
    with LOCK:
        for k in [k for k, x in EXECS.items() if x.status not in ("queued", "running") and x.key == key]:
            EXECS.pop(k)
        EXECS[e.id] = e

    def run():
        session = uuid.uuid4().hex
        last_save = 0.0
        try:
            send, recv, close = transport()
        except Exception as ex:  # noqa: BLE001
            e.outputs.append({"type": "error", "ename": "连接失败", "evalue": str(ex)[:300], "traceback": []})
            e.status, e.ended = "failed", time.time()
            e.ver += 1
            save(e)
            return
        try:
            m = _msg(code, session)
            send(m)
            mid = m["header"]["msg_id"]
            e.status = "running"
            e.ver += 1
            while True:
                r = recv(30)
                if r is None:
                    on_activity()
                    continue
                if (r.get("parent_header") or {}).get("msg_id") != mid or r.get("channel") not in ("iopub", None):
                    continue
                done = apply(e.outputs, {"msg_type": r.get("msg_type") or r["header"]["msg_type"], "content": r.get("content", {})})
                e.ver += 1
                on_activity()
                if done:
                    break
                if time.time() - last_save > 3:
                    save(e)
                    last_save = time.time()
            e.status = "error" if any(o["type"] == "error" for o in e.outputs) else "done"
        except Exception as ex:  # noqa: BLE001
            e.outputs.append({"type": "error", "ename": "连接中断", "evalue": str(ex)[:300], "traceback": []})
            e.status = "failed"
        finally:
            e.ended = time.time()
            e.ver += 1
            save(e)
            try:
                close()
            except Exception:  # noqa: BLE001
                pass
            on_activity()

    threading.Thread(target=run, daemon=True, name=f"practice-exec-{e.id}").start()
    return e
