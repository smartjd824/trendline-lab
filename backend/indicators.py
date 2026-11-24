"""Indicators: MA20, MA200, and strict No-Look-Ahead multi-horizon Upper/Lower Trendlines."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class TrendlineSegment:
    kind: str  # "upper" | "lower"
    horizon: str  # "short" | "long"
    p1_idx: int
    p2_idx: int
    p1_date: str
    p2_date: str
    p1_price: float
    p2_price: float
    slope: float  # price change per bar (or log-price change per bar if scale=="log")
    scale_mode: str
    current_value: float  # value projected to the evaluation bar
    end_idx: int
    end_date: str
    end_price: float


def _line_value(p1_idx: int, p1_val: float, slope: float, target_idx: int, is_log: bool) -> float:
    raw = p1_val + slope * (target_idx - p1_idx)
    return float(np.exp(raw)) if is_log else float(raw)


def fit_outer_trendline(
    values: np.ndarray,
    end_excl: int,
    window: int,
    kind: str,
    is_log: bool = False,
    inv_dx: np.ndarray | None = None,
) -> tuple[int, int, float, float, float] | None:
    """
    Fit an outer tangent trendline strictly on bars [start, end_excl - 1].

    - kind == 'upper': starts at highest peak p1 in [start, end_excl - min_span],
      connects to p2 in [p1 + min_span, end_excl - 1] with MAXIMUM slope.
    - kind == 'lower': starts at lowest trough p1 in [start, end_excl - min_span],
      connects to p2 in [p1 + min_span, end_excl - 1] with MINIMUM slope.
    """
    if end_excl < 12:
        return None
    start = end_excl - window if end_excl > window else 0
    eff_len = end_excl - start
    min_span = int(eff_len * 0.15)
    if min_span < 6:
        min_span = 6
    if eff_len <= min_span + 2:
        return None

    search_end = end_excl - min_span
    seg_left = values[start:search_end]
    if seg_left.size == 0:
        return None

    p1 = start + (int(np.argmax(seg_left)) if kind == "upper" else int(np.argmin(seg_left)))
    p1_val = float(values[p1])

    right_start = p1 + min_span
    if right_start >= end_excl:
        return None

    right_vals = values[right_start:end_excl]
    span_end = end_excl - p1
    if inv_dx is not None and span_end <= inv_dx.size:
        slopes = (right_vals - p1_val) * inv_dx[min_span:span_end]
    else:
        dx = np.arange(min_span, span_end, dtype=np.float64)
        slopes = (right_vals - p1_val) / dx

    p2_rel = int(np.argmax(slopes)) if kind == "upper" else int(np.argmin(slopes))
    p2 = right_start + p2_rel
    slope = float(slopes[p2_rel])
    raw = p1_val + slope * span_end
    projected = float(np.exp(raw)) if is_log else float(raw)
    return p1, p2, p1_val, slope, projected


def compute_indicator_frame(
    df: pd.DataFrame,
    short_window: int = 45,
    long_window: int = 180,
    price_source: str = "wick",
    scale_mode: str = "linear",
) -> pd.DataFrame:
    """
    Compute MA20, MA200, VolMA20, and rolling No-Look-Ahead trendline projections
    for every bar t (fitted strictly on bars < t, projected onto bar t).
    """
    out = df.copy().reset_index(drop=True)
    close = out["close"].to_numpy(dtype=np.float64)
    high = out["high"].to_numpy(dtype=np.float64)
    low = out["low"].to_numpy(dtype=np.float64)
    vol = out["volume"].to_numpy(dtype=np.float64)

    out["ma20"] = pd.Series(close).rolling(20, min_periods=20).mean()
    out["ma200"] = pd.Series(close).rolling(200, min_periods=200).mean()
    out["vol_ma20"] = pd.Series(vol).rolling(20, min_periods=10).mean()
    out["ma20_slope"] = out["ma20"].diff(3)
    # 10-bar % change of MA200: >= -0.15% means flat or gently/strongly rising
    out["ma200_chg10_pct"] = (out["ma200"] / out["ma200"].shift(10) - 1.0) * 100.0
    out["ma200_chg5_pct"] = (out["ma200"] / out["ma200"].shift(5) - 1.0) * 100.0

    is_log = scale_mode == "log"
    upper_src = close if price_source == "body" else high
    lower_src = close if price_source == "body" else low
    if is_log:
        upper_vals = np.log(np.maximum(upper_src, 1e-9))
        lower_vals = np.log(np.maximum(lower_src, 1e-9))
    else:
        upper_vals = upper_src
        lower_vals = lower_src

    n = len(out)
    su = np.full(n, np.nan, dtype=np.float64)
    sl = np.full(n, np.nan, dtype=np.float64)
    lu = np.full(n, np.nan, dtype=np.float64)
    ll = np.full(n, np.nan, dtype=np.float64)
    su_slope = np.full(n, np.nan, dtype=np.float64)
    sl_slope = np.full(n, np.nan, dtype=np.float64)
    lu_slope = np.full(n, np.nan, dtype=np.float64)
    ll_slope = np.full(n, np.nan, dtype=np.float64)

    # Precomputed reciprocal distances for fast O(W) inner loop
    max_w = max(short_window, long_window) + 10
    inv_dx = np.zeros(max_w + 1, dtype=np.float64)
    inv_dx[1:] = 1.0 / np.arange(1, max_w + 1, dtype=np.float64)

    # Strict no-look-ahead: bar t uses trendline fitted on [t - W, t - 1], projected to t.
    for t in range(15, n):
        r_su = fit_outer_trendline(upper_vals, t, short_window, "upper", is_log, inv_dx)
        if r_su is not None:
            su[t] = r_su[4]
            su_slope[t] = r_su[3]

        r_sl = fit_outer_trendline(lower_vals, t, short_window, "lower", is_log, inv_dx)
        if r_sl is not None:
            sl[t] = r_sl[4]
            sl_slope[t] = r_sl[3]

        r_lu = fit_outer_trendline(upper_vals, t, long_window, "upper", is_log, inv_dx)
        if r_lu is not None:
            lu[t] = r_lu[4]
            lu_slope[t] = r_lu[3]

        r_ll = fit_outer_trendline(lower_vals, t, long_window, "lower", is_log, inv_dx)
        if r_ll is not None:
            ll[t] = r_ll[4]
            ll_slope[t] = r_ll[3]

    out["short_upper"] = su
    out["short_lower"] = sl
    out["long_upper"] = lu
    out["long_lower"] = ll
    out["short_upper_slope"] = su_slope
    out["short_lower_slope"] = sl_slope
    out["long_upper_slope"] = lu_slope
    out["long_lower_slope"] = ll_slope

    return out


def extract_current_trendlines(
    df: pd.DataFrame,
    short_window: int = 45,
    long_window: int = 180,
    price_source: str = "wick",
    scale_mode: str = "linear",
    as_of_idx: int | None = None,
) -> dict[str, dict | None]:
    """
    Extract drawable straight trendline segments (p1 -> latest bar) for the chart UI.
    Fits up to `as_of_idx` (default: last bar - 1 so latest bar breakouts are visibly piercing the line!).
    """
    n = len(df)
    if n < 20:
        return {"short_upper": None, "short_lower": None, "long_upper": None, "long_lower": None}

    eval_idx = (n - 1) if as_of_idx is None else min(max(as_of_idx, 15), n - 1)
    dates = df["date"].tolist()
    close = df["close"].to_numpy(dtype=np.float64)
    high = df["high"].to_numpy(dtype=np.float64)
    low = df["low"].to_numpy(dtype=np.float64)

    is_log = scale_mode == "log"
    upper_src = close if price_source == "body" else high
    lower_src = close if price_source == "body" else low
    upper_vals = np.log(np.maximum(upper_src, 1e-9)) if is_log else upper_src
    lower_vals = np.log(np.maximum(lower_src, 1e-9)) if is_log else lower_src

    specs = [
        ("short_upper", upper_vals, short_window, "upper", "short"),
        ("short_lower", lower_vals, short_window, "lower", "short"),
        ("long_upper", upper_vals, long_window, "upper", "long"),
        ("long_lower", lower_vals, long_window, "lower", "long"),
    ]

    result: dict[str, dict | None] = {}
    for key, vals, win, kind, horizon in specs:
        fit = fit_outer_trendline(vals, eval_idx, win, kind, is_log)
        if fit is None:
            result[key] = None
            continue
        p1, p2, p1_val, slope, proj_eval = fit
        p1_price = float(np.exp(p1_val)) if is_log else float(p1_val)
        p2_price = _line_value(p1, p1_val, slope, p2, is_log)
        end_idx = n - 1
        end_price = _line_value(p1, p1_val, slope, end_idx, is_log)
        result[key] = {
            "key": key,
            "kind": kind,
            "horizon": horizon,
            "p1_idx": p1,
            "p2_idx": p2,
            "p1_date": dates[p1],
            "p2_date": dates[p2],
            "p1_price": round(p1_price, 6),
            "p2_price": round(p2_price, 6),
            "end_idx": end_idx,
            "end_date": dates[end_idx],
            "end_price": round(end_price, 6),
            "current_value": round(proj_eval, 6),
            "slope_pct_per_bar": round(
                (float(np.exp(slope) - 1.0) * 100.0) if is_log else (slope / max(p1_price, 1e-9) * 100.0),
                4,
            ),
            "direction": "down" if slope < 0 else "up",
        }
    return result
