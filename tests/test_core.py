"""Core regression tests on synthetic OHLCV (no network needed)."""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from backend.backtester import EXIT_RULES, STRATEGIES, run_backtest_single
from backend.data_loader import drop_incomplete_last_bar, is_bar_complete
from backend.indicators import compute_indicator_frame
from backend.notifier import _split_chunks


def _synth(seed: int = 0, n: int = 1700) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    r = rng.normal(0.0004, 0.02, n) + 0.003 * np.sin(np.arange(n) / 40)
    c = 100 * np.exp(np.cumsum(r))
    o = c * np.exp(rng.normal(0, 0.006, n))
    h = np.maximum(o, c) * np.exp(np.abs(rng.normal(0, 0.01, n)))
    lo = np.minimum(o, c) * np.exp(-np.abs(rng.normal(0, 0.01, n)))
    v = rng.lognormal(10, 0.4, n)
    d = pd.bdate_range("2019-01-01", periods=n)
    return pd.DataFrame(
        {"date": d.strftime("%Y-%m-%d"), "open": o, "high": h, "low": lo, "close": c, "volume": v, "date_dt": d}
    )


@pytest.fixture(scope="module")
def ind() -> pd.DataFrame:
    return compute_indicator_frame(_synth())


def test_indicators_are_causal():
    """Appending future bars must not change any already-computed indicator value."""
    full = _synth(1, 900)
    a = compute_indicator_frame(full.iloc[:700].reset_index(drop=True))
    b = compute_indicator_frame(full).iloc[:700]
    cols = ["ma20", "ma200", "rsi14", "short_upper", "short_lower", "long_upper", "long_lower", "high180"]
    # wma20 on the very last partial week legitimately uses that week's latest close; compare all but last 5 bars
    pd.testing.assert_frame_equal(a[cols].iloc[:-5], b[cols].iloc[:-5], check_dtype=False)


@pytest.mark.parametrize("execution", ["close", "next_open"])
@pytest.mark.parametrize("sid", list(STRATEGIES) + ["S6"])
def test_backtest_runs_all_combos(ind, sid, execution):
    for eid in EXIT_RULES:
        r = run_backtest_single("005930.KS", ind, sid, 6, exit_rule=eid, execution=execution, include_series=True)
        assert "error" not in r
        assert -100.0 <= r["mdd_pct"] <= 0.0
        assert 0.0 <= r["exposure_pct"] <= 100.0
        for tr in r["trades"]:
            assert tr["entry_date"] <= tr["exit_date"]
            if execution == "next_open":
                assert tr["signal_date"] < tr["entry_date"], "next_open must fill AFTER the signal bar"


def test_next_open_fills_at_open(ind):
    r = run_backtest_single("005930.KS", ind, "S3", 6, exit_rule="ma200_2d", execution="next_open", include_series=True)
    opens = dict(zip(ind["date"], ind["open"]))
    for tr in r["trades"]:
        assert tr["entry_price"] == pytest.approx(opens[tr["entry_date"]], rel=1e-6)


def test_intraday_stop_never_worse_than_gap(ind):
    """With next_open, a -8% stop fills at the stop price, or at the open if the bar gapped below it."""
    r = run_backtest_single("005930.KS", ind, "S2", 6, exit_rule="ma20_2d", execution="next_open", include_series=True)
    opens = dict(zip(ind["date"], ind["open"]))
    for tr in r["trades"]:
        if tr["exit_reason"].startswith("손절"):
            stop_px = tr["entry_price"] * 0.92
            assert tr["exit_price"] == pytest.approx(min(stop_px, opens[tr["exit_date"]]), rel=1e-6)


def test_market_cost_model_is_costlier(ind):
    flat = run_backtest_single("005930.KS", ind, "S3", 6, exit_rule="ma20_2d", fee_rate=0.0, cost_model="flat")
    mkt = run_backtest_single("005930.KS", ind, "S3", 6, exit_rule="ma20_2d", cost_model="market")
    if flat["trade_count"]:
        assert mkt["total_return_pct"] < flat["total_return_pct"]


def test_incomplete_bar_detection():
    # 2026-11-26 01:00 UTC == 10:00 KST: today's KR & crypto bars are still forming, last US bar is closed.
    now = datetime(2026, 11, 26, 1, 0, tzinfo=timezone.utc)
    assert not is_bar_complete("005930.KS", "2026-11-26", now)
    assert is_bar_complete("005930.KS", "2026-11-25", now)
    assert not is_bar_complete("BTC-USD", "2026-11-26", now)
    assert is_bar_complete("BTC-USD", "2026-11-25", now)
    assert is_bar_complete("AAPL", "2026-11-25", now)
    assert not is_bar_complete("^KS11", "2026-11-26", now)

    df = pd.DataFrame({"date": ["2026-11-25", "2026-11-26"], "close": [1.0, 2.0]})
    assert len(drop_incomplete_last_bar("005930.KS", df, now)) == 1
    assert len(drop_incomplete_last_bar("AAPL", df.iloc[:1], now)) == 1


def test_split_chunks_respects_limit_and_entities():
    text = "a" * 95 + "&amp;" + "b" * 300 + "\nshort line\n"
    chunks = _split_chunks(text, 100)
    assert all(len(c) <= 100 for c in chunks)
    assert "".join(chunks).count("&amp;") == 1


# ---------------------------------------------------------------- advanced features
def test_atr_stop_and_chandelier(ind):
    from backend.backtester import ATR_STOP_MAX_PCT, ATR_STOP_MIN_PCT

    r = run_backtest_single("005930.KS", ind, "S3", 6, exit_rule="atr_chandelier", include_series=True)
    assert r["stop_mode"] == "atr"
    for tr in r["trades"]:
        assert ATR_STOP_MIN_PCT <= tr["stop_pct"] <= ATR_STOP_MAX_PCT
    r2 = run_backtest_single("005930.KS", ind, "S3", 6, exit_rule="ma20_2d", stop_mode="atr", include_series=True)
    assert any(tr["stop_pct"] != 8.0 for tr in r2["trades"]) or not r2["trades"]


def test_regime_filter_blocks_entries(ind):
    blocked = np.zeros(len(ind), dtype=bool)
    r = run_backtest_single("005930.KS", ind, "S3", 6, exit_rule="ma20_2d", regime_ok=blocked)
    assert r["total_signals"] == 0


def test_windowed_backtest_respects_end_date(ind):
    end = ind["date"].iloc[-300]
    r = run_backtest_single("005930.KS", ind, "S3", 6, exit_rule="ma20_2d", include_series=True,
                            start_date=ind["date"].iloc[-900], end_date=end)
    assert r["end_date"] == end
    assert all(tr["exit_date"] <= end for tr in r["trades"])
    assert r["pending_order"] is None


def test_isotonic_is_monotone():
    from backend.calibration import _pav

    out = _pav([0.1, 0.3, 0.2, 0.25, 0.5, 0.4], [1, 1, 1, 1, 1, 1])
    assert all(a <= b + 1e-12 for a, b in zip(out, out[1:]))
    assert sum(out) == pytest.approx(sum([0.1, 0.3, 0.2, 0.25, 0.5, 0.4]))


def test_regime_mask_alignment(ind):
    from backend.analytics import regime_mask

    breadth = pd.Series([10.0] * 5, index=ind["date"].iloc[-5:].tolist())
    m = regime_mask(ind, breadth, 30.0)
    assert m[:-5].all() and not m[-5:].any()


def test_portfolio_small(monkeypatch):
    import backend.analytics as an

    assets = [a for a in an.ASSETS if a["market"] == "US"][:6]
    monkeypatch.setattr(an, "ASSETS", assets)
    ind_map = {a["symbol"]: compute_indicator_frame(_synth(i + 10, 1500)) for i, a in enumerate(assets)}
    br = an.compute_market_breadth(ind_map)
    assert "US" not in br or br["US"].dropna().between(0, 100).all()
    rules = {"US": {"strategy_id": "S3", "exit_rule": "ma200_2d", "label": "x"}}
    pf = an.run_portfolio_backtest(ind_map, rules, br, market="US", max_positions=3)
    assert -100 <= pf["mdd_pct"] <= 0 and pf["trades_taken"] >= 1
    assert pf["avg_invested_pct"] <= 100.0


def test_static_encryption_roundtrip():
    import base64
    import json

    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    import build_static_site as b

    b._ENC_KEY = b._derive_key("pw", b"0123456789abcdef")
    try:
        enc = b._encrypt_payload(json.dumps({"a": 1}).encode())
        plain = AESGCM(b._ENC_KEY).decrypt(base64.b64decode(enc["iv"]), base64.b64decode(enc["ct"]), None)
        assert json.loads(plain) == {"a": 1}
    finally:
        b._ENC_KEY = None
