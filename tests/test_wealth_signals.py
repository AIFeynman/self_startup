"""强弱信号：不看未来、分数方向、转弱触发、阶段表、组合回放。"""
import math

from app.modules import _wealth_signals as sig

DAY = 86400


def _bars(closes, volumes=None):
    return [{"ts": 1_600_000_000 + i * DAY, "close": c, "adj_close": c, "high": c * 1.01, "low": c * 0.99, "open": c,
             "volume": (volumes[i] if volumes else 1000)} for i, c in enumerate(closes)]


def _series(closes, bench, volumes=None):
    ts = [1_600_000_000 + i * DAY for i in range(len(closes))]
    return sig.series(ts, closes, closes, volumes or [1000] * len(closes), ts, bench)


def test_series_does_not_look_ahead():
    closes = [100 * math.exp(0.02 * math.sin(i / 3) + 0.001 * i) for i in range(320)]
    bench = [100 * math.exp(0.0005 * i) for i in range(320)]
    vols = [1000 + 300 * math.sin(i) for i in range(320)]
    full = _series(closes, bench, vols)
    cut = _series(closes[:260], bench[:260], vols[:260])
    for key in ("rs20", "rs60", "up_down", "vol_ratio", "score", "weak_exit", "m200"):
        assert full[key][:260] == cut[key]


def test_score_strong_and_weak():
    bench = [100.0] * 300
    rising = [100 * 1.002 ** i * (1.004 if i % 2 else 1.0) for i in range(300)]
    vols = [2000 if i % 2 else 1000 for i in range(300)]    # 上涨日量大
    assert _series(rising, bench, vols)["score"][-1] == 3
    falling = [100 * 0.998 ** i * (0.996 if i % 2 else 1.0) for i in range(300)]
    assert _series(falling, bench, vols)["score"][-1] == -3


def test_weak_exit_needs_prior_strength():
    bench = [100.0] * 400
    vols = [2000 if i % 2 else 1000 for i in range(400)]
    always_down = [100 * 0.998 ** i * (0.996 if i % 2 else 1.0) for i in range(400)]
    assert not any(_series(always_down, bench, vols)["weak_exit"][300:])
    turn = [100 * 1.003 ** min(i, 250) * 0.99 ** max(i - 250, 0) * (1.004 if i < 250 and i % 2 else 0.996 if i % 2 else 1.0) for i in range(400)]
    assert any(_series(turn, bench, vols)["weak_exit"][251:])


def test_snapshot_reads_benchmark_and_handles_short_history():
    closes = [100 * 1.002 ** i * (1.004 if i % 2 else 1.0) for i in range(300)]
    snap = sig.snapshot(_bars(closes), _bars([100.0] * 300), "恒生科技 ETF")
    assert snap["relative"]["state"] == 1 and snap["benchmark"]["name"] == "恒生科技 ETF"
    assert snap["ma"]["state"] == 1 and snap["ma"]["slopes"]["m200"] > 0
    assert sig.snapshot(_bars(closes[:100]), _bars([100.0] * 300), "x") is None
    assert sig.snapshot(_bars(closes), _bars([100.0] * 30), "x") is None


def test_stages_follow_price_and_target():
    bars = _bars([70.0] * 40 + [78.0 / 1.01] + [75.0] * 10)
    rows = {r["key"]: r for r in sig.stages(75.0, 100.0, bars, None)}
    assert rows["before"]["active"] and "78.0" in rows["before"]["range"]
    assert [k for k, r in rows.items() if r["active"]] == ["before"]
    assert next(r["key"] for r in sig.stages(95.0, 100.0, bars, None) if r["active"]) == "near"
    assert next(r["key"] for r in sig.stages(99.0, 100.0, bars, None) if r["active"]) == "window"
    # 前高已在目标区以上：没有中间段
    assert "middle" not in {r["key"] for r in sig.stages(80.0, 100.0, _bars([120.0] * 30), None)}


def _history(path):
    n = len(path)
    return {"ts": [1_500_000_000 + i * DAY for i in range(n)], "close": path, "adj": path, "high": path, "volume": [1000] * n}


def test_replay_rules_on_known_paths():
    n = 400
    up = _history([50 * 1.01 ** i for i in range(n)])
    frame = {**up, **sig.series(up["ts"], up["close"], up["adj"], up["volume"], up["ts"], [100.0] * n)}
    flat = _history([10.0] * n)
    net = lambda p: p
    ladder = [(1.0, 0.5), (1.5, 0.5)]
    keep = (1 - sig.switch_plan.SWITCH_COST_RATE) ** 2
    assert abs(sig._replay(frame, flat, 200, 100, "now", 80.0, ladder, net) - 80.0 * keep) < 1e-9
    assert abs(sig._replay(frame, flat, 200, 100, "hold", 80.0, ladder, net) - 80.0 * 1.01 ** 100) < 1e-6
    # 一半现卖，一半在 1.5 倍成交；都转入不涨的 ETF
    assert abs(sig._replay(frame, flat, 200, 100, "lad", 80.0, ladder, net) - (40.0 + 60.0) * keep) < 1e-9


def test_replay_weak_exit_sells_the_rest():
    n = 400
    path = [100.0] * 300 + [100.0 * 0.98 ** i for i in range(1, 101)]
    h = _history(path)
    frame = {**h, "score": [None] * n, "weak_exit": [False] * n}
    frame["weak_exit"][310] = True
    flat = _history([10.0] * n)
    value = sig._replay(frame, flat, 250, 149, "halflowweak", 100.0, [(1.0, 1.0)], lambda p: p)
    held = sig._replay(frame, flat, 250, 149, "halflow", 100.0, [(1.0, 1.0)], lambda p: p)
    assert value > held


def test_backtest_report_and_evidence(tmp_path):
    import random
    rng = random.Random(5)

    def walk(drift):
        price, out = 100.0, []
        for _ in range(1400):
            price *= math.exp(rng.gauss(drift, 0.02))
            out.append(price)
        return out

    def fake():
        symbols = dict.fromkeys((*sig.HK_GROUP, *sig.US_GROUP, sig.HK_BENCH, sig.US_BENCH, *sig.EXTRA))
        out = {}
        for s in symbols:
            h = _history(walk(0.0003))
            h["volume"] = [rng.randint(500, 2000) for _ in h["close"]]
            out[s] = h
        return out

    report = sig.run_backtest(tmp_path, 75.0, [(1.0, 0.2), (1.2, 0.8)], 0.0015, refresh=True, fetch=fake)
    sig.save(report, tmp_path)
    loaded = sig.load(tmp_path)
    for group in ("holdout", "hk", "us"):
        rows = loaded["combos"][group]["756"]["rows"]
        assert set(rows) == set(sig.COMBOS)
        assert rows["now"]["n"] == loaded["combos"][group]["756"]["n"]
    ev = sig.evidence(loaded)
    assert ev["years"] == 3 and ev["findings"] and ev["combos"]["holdout"]["rows"]["lad"]["label"] == "页面阶梯"
    assert sig.evidence(None) is None
    assert any(r["evidence"] != "回测还没生成" for r in sig.stages(75.0, 100.0, _bars([75.0] * 30), loaded))


def test_combo_example_uses_whole_lots():
    ex = sig.combo_example(75.0, 8500, 100, "HK")
    assert ex["now_shares"] == 4200
    assert ex["now_shares"] + sum(r["shares"] for r in ex["rungs"]) == 8500
    assert all(r["shares"] % 100 == 0 for r in ex["rungs"])
    assert sig.combo_example(75.0, 500, 100, "HK") is None
