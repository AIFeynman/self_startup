"""语音通话的慢思考：本机只读 Claude Code。同一时间想一件事，再来的排一个（再来就合并）。

结果按 <spoken>念给用户听的</spoken><brief>提纲</brief> + 正文 输出，念的和提纲会上云，正文只留在本机。
"""
from __future__ import annotations

import logging
import re
import threading
import time
from typing import Callable

from . import agent

log = logging.getLogger(__name__)

SLOW_FORMAT = """## 现在是语音通话
用户的话来自语音转写，可能有错字；另一半「快思考」负责接话，你的结论由它念给用户听，在用户听来只有一个人，念的话里不要提快思考、慢思考。严格按这个格式输出：
<spoken>念给用户听的话，最多三句，口语，先说结论。数字和名字要写全。不用列表、路径、链接、代码。如果快思考刚才说的有错，先纠正；说得对就只说新内容。</spoken>
<brief>给快思考的提纲，几个短句，用户追问时它靠这个接话。只写结论和理由，不要抄用户的记录、知识库原文和代码。</brief>
然后写完整回答，可以用 markdown，会显示在屏幕上，不会念出来。"""

# 上云的进度只说在做哪一类事，不带文件路径和查询内容
DOING = {"Read": "在读资料", "Glob": "在找文件", "Grep": "在搜资料", "WebSearch": "在上网查", "WebFetch": "在看网页"}

_SPOKEN = re.compile(r"<spoken>(.*?)</spoken>", re.S)
_BRIEF = re.compile(r"<brief>(.*?)</brief>", re.S)


def body_of(text: str) -> str:
    """去掉标签后的完整回答；模型只写了标签里的内容时，就用那些内容。"""
    rest = _BRIEF.sub("", _SPOKEN.sub("", text)).strip()
    if rest:
        return rest
    return "\n\n".join(m.group(1).strip() for m in (_SPOKEN.search(text), _BRIEF.search(text)) if m)


def fallback_spoken(text: str) -> str:
    """模型没按格式写：取前三句，去掉 markdown 符号。"""
    plain = re.sub(r"```.*?```", "", text, flags=re.S)
    plain = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", plain)
    plain = re.sub(r"[*_`#>|]", "", plain)
    return "".join(re.findall(r"[^。！？!?\n]+[。！？!?]?", plain)[:3]).strip()


class Task:
    def __init__(self, objective: str):
        self.objective, self.started = objective, time.monotonic()
        self.doing, self.cued_doing, self.cues = "", "", 0
        self.proc, self.cancelled = None, False


class Thinker:
    """emit(kind, text) 在通话的事件循环里调用：spoken / brief / full / failed。"""

    def __init__(self, loop, emit: Callable[[str, str], None], *, system: str, dirs: list[str], session: str = "",
                 model: str = "", history: Callable[[], str] = lambda: "", on_session: Callable[[str], None] = lambda _: None):
        self.loop, self.emit, self.system, self.dirs, self.session = loop, emit, system + "\n\n" + SLOW_FORMAT, dirs, session
        self.model, self.history, self.on_session = model, history, on_session
        self.task: Task | None = None
        self.queued = ""

    def warm(self) -> None:
        agent.warm_up(system=self.system, session=self.session, add_dirs=self.dirs, model=self.model)

    def ask(self, objective: str) -> str:
        if self.task:  # 还在想别的：排一个，再来就合并
            self.queued = f"{self.queued}；{objective}" if self.queued else objective
            return "queued"
        self._start(objective)
        return "accepted"

    def update(self, info: str) -> str:
        """用户补充了信息：停掉重开，把新信息并进去。"""
        if not self.task:
            self._start(info)
            return "accepted"
        objective = f"{self.task.objective}\n用户补充：{info}"
        self.cancel(keep_queue=True)
        self._start(objective)
        return "updated"

    def cancel(self, keep_queue: bool = False) -> str:
        task, self.task = self.task, None
        if not keep_queue:
            self.queued = ""
        if not task:
            return "idle"
        task.cancelled = True
        if task.proc:
            agent.stop(task.proc)
        return "cancelled"

    def status(self) -> dict:
        if not self.task:
            return {"state": "idle"}
        return {"state": "thinking", "elapsed_s": round(time.monotonic() - self.task.started),
                "doing": self.task.doing or "在想", "queued": bool(self.queued)}

    def due_cue(self, at: tuple[float, ...]) -> str:
        """到了该报进度的时候，返回真实在做的事；没有新动作就不报，不编。"""
        t = self.task
        if not t or t.cues >= len(at) or time.monotonic() - t.started < at[t.cues] or not t.doing or t.doing == t.cued_doing:
            return ""
        t.cues += 1
        t.cued_doing = t.doing
        return t.doing

    def _start(self, objective: str) -> None:
        self.task = Task(objective)
        threading.Thread(target=self._work, args=(self.task,), daemon=True).start()

    def _prompt(self, objective: str) -> str:
        said = self.history()
        return f"（最近的通话）\n{said}\n\n要想的问题：{objective}" if said else f"要想的问题：{objective}"

    def _post(self, task: Task, fn, *args) -> None:
        self.loop.call_soon_threadsafe(lambda: None if task.cancelled else fn(*args))

    def _work(self, task: Task) -> None:
        text, final, sent_spoken, sent_brief, failed = "", "", False, False, ""
        run = agent.run_stream(self._prompt(task.objective), system=self.system, session=self.session, add_dirs=self.dirs,
                               model=self.model, readonly=True, on_proc=lambda p: setattr(task, "proc", p))
        try:
            for ev in run:
                if task.cancelled:
                    return
                kind = ev["type"]
                if kind == "session":
                    self._post(task, self._remember, ev["id"])
                elif kind == "tool":
                    task.doing = DOING.get(ev["text"].split(":")[0], task.doing)
                elif kind == "delta":
                    text += ev["text"]
                elif kind == "text":
                    text = text if text else ev["text"]
                elif kind == "done":
                    final = ev["text"]
                elif kind == "error" and ev.get("fatal"):
                    failed = ev["text"]
                # 念的那几句一写完就送，不等后面的正文
                m = None if sent_spoken else _SPOKEN.search(text)
                if m:
                    sent_spoken = True
                    self._post(task, self.emit, "spoken", m.group(1).strip())
                b = None if sent_brief else _BRIEF.search(text)
                if b:
                    sent_brief = True
                    self._post(task, self.emit, "brief", b.group(1).strip())
        except Exception as e:  # noqa: BLE001 —— 慢思考出错不能把通话带挂
            log.exception("慢思考失败")
            failed = str(e)
        finally:
            run.close()
        if task.cancelled:
            return
        final = "" if failed else final or text  # 出错就不算数，哪怕已经写了一半
        if final and not sent_spoken:
            m = _SPOKEN.search(final)
            spoken = m.group(1).strip() if m else fallback_spoken(final)
            if not m:
                log.warning("慢思考没按格式输出，取前三句")
            self._post(task, self.emit, "spoken", spoken)
        self._post(task, self._finish, task, body_of(final) if final else "", failed)

    def _remember(self, session: str) -> None:
        self.session = session
        self.on_session(session)

    def _finish(self, task: Task, full: str, failed: str) -> None:
        if self.task is not task:
            return
        self.task = None
        self.emit("full", full) if full else self.emit("failed", failed or "没有回复")
        if self.queued:
            next_up, self.queued = self.queued, ""
            self._start(next_up)
        else:
            threading.Thread(target=self.warm, daemon=True).start()
