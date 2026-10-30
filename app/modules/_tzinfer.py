"""从作息推断你所在的时区（设置里 timezone 留空时用）：人工消息按 UTC 小时分桶，找最长的一段「几乎没有消息」的小时（睡觉），
把它的中点对到本地 03:30。只有数据够多、睡眠段清楚、而且和系统时区差 ≥2 小时才采用，否则跟随系统。
结果缓存在 data/tz_inferred.json（settings.apply_timezone 启动时读），每天最多重算一次。"""
from __future__ import annotations

import json
from datetime import date as Date, datetime, timedelta, timezone

from .. import db, settings
from . import _review_sessions as rs

MIN_MSGS = 50
MIN_QUIET_HOURS = 4
SLEEP_CENTER = 3.5   # 睡眠段中点对应的本地时刻


def infer_offset(stamps_utc: list[datetime]) -> tuple[int, dict] | None:
    """人工消息的 UTC 时间 → (UTC 偏移小时, 依据)；数据不够或看不出睡眠段时返回 None。"""
    if len(stamps_utc) < MIN_MSGS:
        return None
    hist = [0] * 24
    for t in stamps_utc:
        hist[t.hour] += 1
    limit = max(1.0, 0.15 * len(stamps_utc) / 24)   # 低于平均每小时的 15% 算「几乎没有」
    quiet = [c <= limit for c in hist]
    if all(quiet):
        return None
    best = (0, 0)  # (长度, 起点)
    for s in range(24):
        if quiet[s] and not quiet[(s - 1) % 24]:
            n = 0
            while quiet[(s + n) % 24] and n < 24:
                n += 1
            best = max(best, (n, s))
    n, s = best
    if n < MIN_QUIET_HOURS:
        return None
    off = round(SLEEP_CENTER - (s + n / 2))
    off = (off + 12) % 24 - 12            # 归一到 -12..+11
    if off == -12:
        off = 12
    return off, {"quiet_utc": f"{s:02d}:00–{(s + n) % 24:02d}:00", "quiet_hours": n, "messages": len(stamps_utc)}


def _human_stamps(days: int = 10) -> list[datetime]:
    dirs = settings.get("session_dirs", {}) or {}
    today = datetime.now().date()
    since = datetime.combine(today - timedelta(days=days), datetime.min.time()).timestamp()
    files = [(p, rs.read_claude) for p in rs._claude_files(dirs.get("claude", []), since)]
    for i in range(days + 1):
        files += [(p, rs.read_codex) for p in rs._codex_files(dirs.get("codex", []), today - timedelta(days=i), since)]
    out, seen = [], set()
    for p, reader in files:
        if str(p) in seen:
            continue
        seen.add(str(p))
        try:
            meta, events = reader(p)
        except Exception:  # noqa: BLE001
            continue
        if meta.get("automated"):
            continue
        # 读日志时已换成本地时间（naive），按当前本地时区换回 UTC，推断与当前 TZ 无关
        out += [e["ts"].astimezone(timezone.utc) for e in events if e["kind"] == "human"]
    return out


def zone_name(off: int) -> str:
    return "UTC" if off == 0 else f"Etc/GMT{-off:+d}"   # IANA 的 Etc/GMT 符号是反的：UTC+8 = Etc/GMT-8


def refresh(force: bool = False) -> dict:
    """重算并缓存推断结果；设置里写了 timezone 时不推断。返回缓存内容。"""
    path = db.DATA_DIR / settings.TZ_CACHE
    try:
        cur = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        cur = {}
    if settings.get("timezone"):
        return cur
    if not force and cur.get("date") == Date.today().isoformat():
        return cur
    r = infer_offset(_human_stamps())
    sys_off = round(settings.system_utc_offset())
    data = {"date": Date.today().isoformat(), "tz": "", "system_offset": sys_off}
    if r:
        off, why = r
        data.update(why, offset=off)
        if abs(((off - sys_off) + 12) % 24 - 12) >= 2:   # 和系统时区差 ≥2 小时才采用
            data["tz"] = zone_name(off)
    db.DATA_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), "utf-8")
    return data
