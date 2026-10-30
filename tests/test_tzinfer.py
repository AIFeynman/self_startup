from datetime import datetime, timedelta, timezone

from app.modules import _tzinfer as T


def _stamps(hour_counts: dict[int, int]) -> list[datetime]:
    base = datetime(2026, 10, 20, tzinfo=timezone.utc)
    return [base + timedelta(hours=h, minutes=(i * 7) % 60) for h, n in hour_counts.items() for i in range(n)]


# 真实数据（近 7 天人工消息，按 UTC 小时）：北京时间 02–06 点几乎为零 → UTC+8
REAL_UTC = {7: 61, 8: 69, 9: 54, 10: 29, 11: 26, 12: 42, 13: 37, 14: 32, 15: 6, 16: 1, 17: 4, 18: 0, 19: 0, 20: 0, 21: 0,
            22: 3, 23: 37, 0: 58, 1: 62, 2: 54, 3: 51, 4: 44, 5: 54, 6: 62}


def test_infers_utc_plus_8_from_sleep_gap():
    off, why = T.infer_offset(_stamps(REAL_UTC))
    assert off == 8 and why["quiet_hours"] >= 4
    assert T.zone_name(8) == "Etc/GMT-8" and T.zone_name(-7) == "Etc/GMT+7" and T.zone_name(0) == "UTC"


def test_shifted_pattern_shifts_offset():
    # 同样的作息整体晚 15 小时（= UTC-7 的人）
    off, _ = T.infer_offset(_stamps({(h + 15) % 24: n for h, n in REAL_UTC.items()}))
    assert off == -7


def test_not_enough_signal_returns_none():
    assert T.infer_offset(_stamps({10: 10, 11: 10})) is None                    # 太少
    assert T.infer_offset(_stamps({h: 20 for h in range(24)})) is None          # 全天平均，看不出睡眠
    assert T.infer_offset(_stamps({h: (0 if h in (3, 4) else 20) for h in range(24)})) is None   # 只空 2 小时


def test_refresh_respects_explicit_setting_and_threshold(monkeypatch):
    from app import settings
    monkeypatch.setattr(T, "_human_stamps", lambda days=10: _stamps(REAL_UTC))
    monkeypatch.setattr(settings, "system_utc_offset", lambda at=None: -7.0)
    r = T.refresh(force=True)
    assert r["tz"] == "Etc/GMT-8" and r["offset"] == 8
    monkeypatch.setattr(settings, "system_utc_offset", lambda at=None: 8.0)    # 系统本来就是 +8：不用改
    assert T.refresh(force=True)["tz"] == ""
    real_get = settings.get
    monkeypatch.setattr(settings, "get", lambda p, d=None: "Asia/Tokyo" if p == "timezone" else real_get(p, d))
    monkeypatch.setattr(T, "_human_stamps", lambda days=10: (_ for _ in ()).throw(AssertionError("写了时区就不该再推断")))
    try:
        assert T.refresh(force=True)["tz"] == ""                               # 沿用上次缓存，不重算
    finally:
        (T.db.DATA_DIR / settings.TZ_CACHE).unlink(missing_ok=True)
