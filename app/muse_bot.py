"""Muse 自动提问进程：python -m app.muse_bot <research_results id>（由调研板块以独立会话启动）。

Muse 没有 API / CLI，这里用 Playwright 驱动本机 Google Chrome 打开网页版：
- 浏览器配置放在 <DATA_DIR>/muse-browser，登录一次之后一直有效；
- 没登录（找不到输入框）时结果记为 awaiting_login，窗口保持打开，用户登录后自动继续提问；
- 把 brief 填进输入框发送，等页面文字连续一段时间不再变化，取回答写回结果；
- 服务重启不影响它；同一时间只有一个进程用这个浏览器配置（文件锁排队）。
页面结构可能改版：输入框 / 回答的选择器可在 engines.muse.selectors 里覆盖；自动失败时退回手动粘贴。
"""
from __future__ import annotations

import fcntl
import logging
import os
import sys
import time

from . import db, settings

log = logging.getLogger("muse_bot")
PROFILE = db.DATA_DIR / "muse-browser"
INPUT = 'textarea, [contenteditable="true"], [role="textbox"]'
STOP = 'button[aria-label*="Stop" i], button[aria-label*="停止"]'
LOGIN_WAIT = 600     # 等用户登录的最长秒数
ANSWER_WAIT = 900    # Muse 是 Agent，可能跑很久
SETTLE = 20          # 页面文字连续这么多秒不变，视为回答完成


def _cfg() -> dict:
    return {"url": "https://muse.ai", "selectors": {}, **(settings.get("engines.muse", {}) or {})}


def _set(res_id: int, **data) -> None:
    from .modules import research
    research._set_result(res_id, **data)


def _body_text(page) -> str:
    try:
        return page.inner_text("body", timeout=5000)
    except Exception:  # noqa: BLE001
        return ""


def _answer(page, brief: str, before: str, sel: str) -> str:
    """优先用配置的回答选择器取最后一条；否则取发送后新出现的文字里、提问之后的部分。"""
    if sel:
        loc = page.locator(sel)
        if loc.count():
            return loc.last.inner_text().strip()
    text = _body_text(page)
    tail = brief.strip().splitlines()[-1].strip()
    i = text.rfind(tail) if tail else -1
    if i >= 0:
        return text[i + len(tail):].strip()
    return text[len(before):].strip() if text.startswith(before[:200]) else text.strip()


def run(res_id: int) -> None:
    from playwright.sync_api import sync_playwright

    from .modules import research
    x = research._result(res_id)
    brief, cfg = x["brief"], _cfg()
    sels = cfg.get("selectors") or {}
    PROFILE.mkdir(parents=True, exist_ok=True)
    with open(PROFILE / ".lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)  # 浏览器配置同一时间只能被一个 Chrome 用，排队
        with sync_playwright() as p:
            ctx = p.chromium.launch_persistent_context(str(PROFILE), channel="chrome", headless=False,
                                                       viewport=None, args=["--no-first-run"])
            try:
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                page.goto(cfg["url"], wait_until="domcontentloaded", timeout=60000)
                box = page.locator(sels.get("input") or INPUT).first
                try:
                    box.wait_for(state="visible", timeout=20000)
                except Exception:  # noqa: BLE001
                    _set(res_id, status="awaiting_login",
                         error="Muse 还没登录：请在弹出的 Chrome 窗口里登录，登录后会自动提问（10 分钟内有效）。")
                    box.wait_for(state="visible", timeout=LOGIN_WAIT * 1000)
                    db.update("research_results", res_id, {"status": "running", "error": ""})
                before = _body_text(page)
                box.click()
                box.fill(brief)
                page.wait_for_timeout(500)
                send = sels.get("send")
                if send and page.locator(send).count():
                    page.locator(send).last.click()
                else:
                    box.press("Enter")
                _set(res_id, status="running", error="已在 Muse 中提问，等待回答…")
                deadline, last, stable_since = time.monotonic() + ANSWER_WAIT, "", time.monotonic()
                while time.monotonic() < deadline:
                    page.wait_for_timeout(3000)
                    now = _body_text(page)
                    if now != last:
                        last, stable_since = now, time.monotonic()
                        continue
                    busy = page.locator(sels.get("stop") or STOP).count() > 0
                    if not busy and time.monotonic() - stable_since >= SETTLE and len(now) > len(before) + 50:
                        break
                ans = _answer(page, brief, before, sels.get("answer", ""))
                if len(ans) < 20:
                    raise RuntimeError("没取到回答（页面结构可能变了）")
                _set(res_id, status="done", content=ans, error="")
            finally:
                ctx.close()


def main(res_id: int) -> None:
    logging.basicConfig(level=logging.INFO, format=f"%(asctime)s muse {res_id}: %(message)s")
    db.update("research_results", res_id, {"request_id": f"pid:{os.getpid()}"})
    try:
        run(res_id)
    except Exception as e:  # noqa: BLE001
        log.exception("muse auto")
        _set(res_id, status="awaiting_paste",
             error=f"自动提问失败：{str(e)[:300]}。可点「自动提问」重试，或复制提问到 Muse 手动问、把回答粘贴回来。")


if __name__ == "__main__":
    db.init()
    main(int(sys.argv[1]))
