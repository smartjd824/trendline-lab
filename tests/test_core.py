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
    flat = run_backtest_single("005930.KS", ind, "S3", 6, exit_rule="ma20_2d", fee_rate=0.0)
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
