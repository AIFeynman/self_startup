"""Muse 自动提问进程：python -m app.muse_bot <research_results id>（由调研板块以独立会话启动）。

Muse 没有 API / CLI，这里用 Playwright 驱动本机 Google Chrome 打开网页版：
- 浏览器配置放在 <DATA_DIR>/muse-browser，登录一次之后一直有效；
- 没登录（找不到输入框）时结果记为 awaiting_login，窗口保持打开，用户登录后自动继续提问；
- 每次先点「新旁聊」开一个空对话（不混进主要聊天的旧内容），把 brief 填进输入框发送；
- 回答取对话区（role=log）里最后一条「你：」提问之后的全部消息，文字连续一段时间不变视为答完；
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
INPUT = 'textarea[aria-label="消息"], textarea:not([aria-label="搜索"]), [contenteditable="true"]'
NEW_CHAT = 'button[aria-label="新旁聊"], [data-testid="hatch-chat-compose"]'
LOG = '[role="log"]'
# 对话区每个直接子节点是一组消息；用户消息带读屏标签「你：」（主要聊天里是「用户消息：」），回答没有或是「助手消息：」
REPLIES_JS = r"""(sel) => {
  const log = document.querySelector(sel); if (!log) return [];
  const groups = [...log.children].map(c => {
    const labels = [...c.querySelectorAll('.sr-only')].map(s => s.textContent.trim());
    let t = c.innerText.trim();
    for (const l of labels) if (/^(你|用户消息|助手消息)[：:]$/.test(l)) t = t.replace(l, '').trim();
    return {user: labels.some(l => /^(你|用户消息)[：:]/.test(l)), t: t.replace(/^助手消息[：:]\s*/, '')};
  });
  let i = groups.map(g => g.user).lastIndexOf(true);
  return i < 0 ? [] : groups.slice(i + 1).map(g => g.t).filter(t => t && !/^\d{1,2}:\d{2}$/.test(t));
}"""
STOP = 'button[aria-label*="Stop" i], button[aria-label*="停止"]'
LOGIN_WAIT = 600     # 等用户登录的最长秒数
ANSWER_WAIT = 900    # Muse 是 Agent，可能跑很久
SETTLE = 20          # 页面文字连续这么多秒不变，视为回答完成


def _cfg() -> dict:
    return {"url": "https://muse.ai", "selectors": {}, **(settings.get("engines.muse", {}) or {})}


def _set(res_id: int, **data) -> None:
    from .modules import research
    research._set_result(res_id, **data)


def _replies(page, sels: dict) -> list[str]:
    """最后一次提问之后的回答（可能分多条）；配置了 selectors.answer 时按它取全部匹配。"""
    try:
        if sels.get("answer"):
            return [t.strip() for t in page.locator(sels["answer"]).all_inner_texts()]
        return page.evaluate(REPLIES_JS, sels.get("log") or LOG)
    except Exception:  # noqa: BLE001
        return []


def _new_chat(page, url: str, box) -> None:
    """开一个空的旁聊；找不到按钮就直接打开 /thread/new。"""
    btn = page.locator(NEW_CHAT).first
    try:
        btn.click(timeout=5000)
    except Exception:  # noqa: BLE001
        page.goto(url.rstrip("/") + "/thread/new", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(2000)
    box.wait_for(state="visible", timeout=20000)


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
                _new_chat(page, cfg["url"], box)
                box.click()
                box.fill(brief)
                page.wait_for_timeout(500)
                send = sels.get("send")
                if send and page.locator(send).count():
                    page.locator(send).last.click()
                else:
                    box.press("Enter")
                _set(res_id, status="running", error="已在 Muse 中提问，等待回答…")
                deadline, last, stable_since = time.monotonic() + ANSWER_WAIT, None, time.monotonic()
                while time.monotonic() < deadline:
                    page.wait_for_timeout(3000)
                    now = _replies(page, sels)
                    if now != last:
                        last, stable_since = now, time.monotonic()
                        continue
                    busy = page.locator(sels.get("stop") or STOP).count() > 0
                    if now and not busy and time.monotonic() - stable_since >= SETTLE:
                        break
                ans = "\n\n".join(_replies(page, sels)).strip()
                if not ans:
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
