"""Multi-strategy 2Y/4Y/6Y backtesting engine for MA20/MA200 (above + flat/rising) + Upper/Lower Trendlines."""

from __future__ import annotations

import pickle
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import numpy as np
import pandas as pd

from config import ASSET_MAP, ASSETS, IND_CACHE_DIR, MARKETS
from backend.data_loader import load_all_cached_ohlcv, load_ohlcv
from backend.indicators import compute_indicator_frame

# MA200 10-bar % change threshold for "평평하거나 미세하게 상승"
# >= -0.15% over 10 trading days (~ -0.015%/day) captures flat leveling-off and any upward tilt.
MA200_FLAT_MIN_PCT = -0.15

STRATEGIES: dict[str, dict[str, str]] = {
    "S1": {
        "id": "S1",
        "name": "강세장 단기 눌림목 돌파",
        "short_name": "S1 단기눌림",
        "description": "MA200 위 & MA200 평평/상승 + 단기 하락 상단선 돌파 + MA20 위 매수, 단기 하단선·MA20 이탈 매도",
    },
    "S2": {
        "id": "S2",
        "name": "장기 추세선 돌파 안착",
        "short_name": "S2 장기돌파",
        "description": "MA200 위 & MA200 평평/상승 + 장기 상단 추세선 돌파 + MA20 안착 매수, MA20 2일 이탈/MA200 이탈 매도",
    },
    "S3": {
        "id": "S3",
        "name": "단·장기 통합 상단 돌파",
        "short_name": "S3 통합돌파",
        "description": "MA200 위 & MA200 평평/상승 + 단기 또는 장기 상단 추세선 돌파 + MA20 위 매수, 하단 지지·MA20 이탈 매도",
    },
    "S4": {
        "id": "S4",
        "name": "이중 지지 합류(Confluence)",
        "short_name": "S4 이중지지",
        "description": "MA200 위 & MA200 평평/상승 + 상승 하단 지지선과 MA20/MA200 합류 양봉 반등 매수, 상단 저항 익절",
    },
    "S5": {
        "id": "S5",
        "name": "삼각수렴 돌파 + 거래량",
        "short_name": "S5 수렴거래량",
        "description": "MA200 위 & MA200 평평/상승 + 상단 하락·하단 상승 수렴 돌파 + 거래량 1.3배↑ 매수",
    },
}

EXIT_RULES: dict[str, dict[str, str]] = {
    "default": {
        "id": "default",
        "name": "전략 기본 청산",
        "short_name": "기본 청산",
        "description": "각 전략 고유의 MA20/지지선 청산 + -8% 손절 + MA200 2일 이탈",
    },
    "ma20_2d": {
        "id": "ma20_2d",
        "name": "MA20 2일 연속 이탈",
        "short_name": "MA20 2일이탈",
        "description": "종가가 20일선 아래 2일 연속 마감 시 청산 (-8% 손절, MA200 2일 이탈)",
    },
    "short_lower": {
        "id": "short_lower",
        "name": "단기 하단 추세선 이탈",
        "short_name": "단기하단 이탈",
        "description": "단기 하단 지지선 이탈 시 청산 — MA20 일시 흔들림은 버팀 (-10% 손절)",
    },
    "long_lower": {
        "id": "long_lower",
        "name": "장기 하단 추세선 이탈",
        "short_name": "장기하단 이탈",
        "description": "장기 하단 지지선 이탈 또는 MA200 2일 이탈 시 청산 (-12% 손절)",
    },
    "ma200_2d": {
        "id": "ma200_2d",
        "name": "MA200 2일 이탈까지 홀딩",
        "short_name": "MA200 홀딩",
        "description": "200일선 위에 있는 동안 끝까지 보유, 200일선 2일 연속 이탈 시 청산 (-12% 손절)",
    },
    "trailing_12": {
        "id": "trailing_12",
        "name": "고점 대비 -12% 트레일링",
        "short_name": "-12% 트레일링",
        "description": "진입 후 최고가 대비 -12% 하락 시 익절/손절 (또는 MA200 2일 이탈)",
    },
    "dead_cross": {
        "id": "dead_cross",
        "name": "20·200일 데드크로스",
        "short_name": "데드크로스",
        "description": "MA20이 MA200 아래로 교차할 때까지 대형 추세 보유 (-12% 초기 손절)",
    },
}

DEFAULT_CUSTOM_PARAMS: dict[str, Any] = {
    "horizon": "both",  # "short" | "long" | "both"
    "require_descending": True,
    "ma200_filter": "above_flat_up",  # "above_flat_up" | "above_strict_up" | "above" | "none"
    "ma200_flat_tol": -0.15,  # 10-bar % threshold for flat/rising MA200
    "ma20_filter": True,
    "ma20_rising": False,
    "vol_mult": 1.0,
    "confirm_bars": 1,
    "exit_mode": "ma20_2d",  # "ma20_break" | "ma20_2d" | "lower_and_ma20" | "upper_tp_or_ma20"
    "stop_loss_pct": 8.0,
    "take_profit_pct": 0.0,
}

# In-memory cache: (symbol, short_w, long_w, price_src, scale, last_date, rows) -> DataFrame
_IND_CACHE: dict[tuple, pd.DataFrame] = {}


def _disk_cache_path(symbol: str, short_w: int, long_w: int, price_src: str, scale: str, last_date: str, rows: int):
    safe_sym = symbol.replace("/", "_").replace(".", "_")
    return IND_CACHE_DIR / f"{safe_sym}_{short_w}_{long_w}_{price_src}_{scale}_{last_date}_{rows}.pkl"


def get_cached_indicators(
    symbol: str,
    df: pd.DataFrame | None = None,
    short_window: int = 45,
    long_window: int = 180,
    price_source: str = "wick",
    scale_mode: str = "linear",
) -> pd.DataFrame:
    if df is None:
        df = load_ohlcv(symbol)
    if df.empty:
        return df
    last_date = str(df["date"].iloc[-1])
    rows = len(df)
    key = (symbol, short_window, long_window, price_source, scale_mode, last_date, rows)
    cached = _IND_CACHE.get(key)
    if cached is not None:
        return cached

    cache_file = _disk_cache_path(symbol, short_window, long_window, price_source, scale_mode, last_date, rows)
    if cache_file.exists():
        try:
            with cache_file.open("rb") as f:
                ind = pickle.load(f)
            _IND_CACHE[key] = ind
            return ind
        except Exception:
            pass

    ind = compute_indicator_frame(
        df,
        short_window=short_window,
        long_window=long_window,
        price_source=price_source,
        scale_mode=scale_mode,
    )
    _IND_CACHE[key] = ind
    try:
        with cache_file.open("wb") as f:
            pickle.dump(ind, f, protocol=pickle.HIGHEST_PROTOCOL)
    except Exception:
        pass
    return ind


def build_indicator_map(
    short_window: int = 45,
    long_window: int = 180,
    price_source: str = "wick",
    scale_mode: str = "linear",
) -> dict[str, pd.DataFrame]:
    """Load/compute indicator frames for all assets in parallel (uses memory + disk cache)."""
    all_dfs = load_all_cached_ohlcv()
    tasks = []
    for asset in ASSETS:
        sym = asset["symbol"]
        df = all_dfs.get(sym)
        if df is not None and len(df) >= 220:
            tasks.append((sym, df))

    def _work(item: tuple[str, pd.DataFrame]) -> tuple[str, pd.DataFrame]:
        sym, df = item
        return sym, get_cached_indicators(
            sym,
            df=df,
            short_window=short_window,
            long_window=long_window,
            price_source=price_source,
            scale_mode=scale_mode,
        )

    ind_map: dict[str, pd.DataFrame] = {}
    with ThreadPoolExecutor(max_workers=6) as pool:
        for sym, ind in pool.map(_work, tasks):
            ind_map[sym] = ind
    return ind_map


def clear_indicator_cache() -> None:
    _IND_CACHE.clear()
    for p in IND_CACHE_DIR.glob("*.pkl"):
        try:
            p.unlink()
        except Exception:
            pass


def _is_valid(val: float) -> bool:
    return not np.isnan(val) and np.isfinite(val)


def _shift1(arr: np.ndarray) -> np.ndarray:
    out = np.empty_like(arr)
    out[0] = np.nan
    out[1:] = arr[:-1]
    return out


def _shift2(arr: np.ndarray) -> np.ndarray:
    out = np.empty_like(arr)
    out[:2] = np.nan
    out[2:] = arr[:-2]
    return out


def evaluate_signals(
    ind: pd.DataFrame,
    strategy_id: str = "S3",
    custom_params: dict[str, Any] | None = None,
    with_reasons: bool = True,
) -> tuple[np.ndarray, np.ndarray, list[str], list[str]]:
    """
    Vectorized causal signal evaluation for every bar in `ind`.
    Core rule enforced across S1~S5 (and default in S6):
      1) Trade strictly ABOVE MA200 (close > ma200)
      2) MA200 must be flat or rising even slightly (10-bar change >= -0.15% OR 5-bar change >= 0%)
    """
    n = len(ind)
    buy_sig = np.zeros(n, dtype=bool)
    sell_sig = np.zeros(n, dtype=bool)
    buy_reason = [""] * n
    sell_reason = [""] * n
    if n < 3:
        return buy_sig, sell_sig, buy_reason, sell_reason

    op = ind["open"].to_numpy(dtype=np.float64)
    hi = ind["high"].to_numpy(dtype=np.float64)
    lo = ind["low"].to_numpy(dtype=np.float64)
    cl = ind["close"].to_numpy(dtype=np.float64)
    vo = ind["volume"].to_numpy(dtype=np.float64)
    ma20 = ind["ma20"].to_numpy(dtype=np.float64)
    ma200 = ind["ma200"].to_numpy(dtype=np.float64)
    vol_ma20 = ind["vol_ma20"].to_numpy(dtype=np.float64)
    ma20_slope = ind["ma20_slope"].to_numpy(dtype=np.float64)
    ma200_chg10 = ind["ma200_chg10_pct"].to_numpy(dtype=np.float64)
    ma200_chg5 = ind["ma200_chg5_pct"].to_numpy(dtype=np.float64)

    su = ind["short_upper"].to_numpy(dtype=np.float64)
    sl = ind["short_lower"].to_numpy(dtype=np.float64)
    lu = ind["long_upper"].to_numpy(dtype=np.float64)
    ll = ind["long_lower"].to_numpy(dtype=np.float64)
    su_s = ind["short_upper_slope"].to_numpy(dtype=np.float64)
    sl_s = ind["short_lower_slope"].to_numpy(dtype=np.float64)
    lu_s = ind["long_upper_slope"].to_numpy(dtype=np.float64)
    ll_s = ind["long_lower_slope"].to_numpy(dtype=np.float64)

    cl1 = _shift1(cl)
    cl2 = _shift2(cl)
    ma20_1 = _shift1(ma20)
    ma200_1 = _shift1(ma200)
    su1 = _shift1(su)
    su2 = _shift2(su)
    lu1 = _shift1(lu)
    lu2 = _shift2(lu)

    valid = np.isfinite(ma20) & np.isfinite(ma200) & np.isfinite(ma200_chg10)
    valid[:2] = False

    with np.errstate(invalid="ignore", divide="ignore"):
        above_ma200 = cl > ma200
        ma200_flat_or_up = (ma200_chg10 >= MA200_FLAT_MIN_PCT) | (np.isfinite(ma200_chg5) & (ma200_chg5 >= 0.0))
        ma200_gate = valid & above_ma200 & ma200_flat_or_up
        ma200_broken = valid & (cl < ma200) & np.isfinite(ma200_1) & (cl1 < ma200_1)

        su_cross = np.isfinite(su) & np.isfinite(su1) & (cl > su) & (cl1 <= su1)
        lu_cross = np.isfinite(lu) & np.isfinite(lu1) & (cl > lu) & (cl1 <= lu1)
        safe_vma = np.where(np.isfinite(vol_ma20) & (vol_ma20 > 0), vol_ma20, 1.0)
        vol_ratio = np.where(np.isfinite(vol_ma20) & (vol_ma20 > 0), vo / safe_vma, 1.0)

        cp = {**DEFAULT_CUSTOM_PARAMS, **(custom_params or {})}

        if strategy_id == "S1":
            buy_sig = ma200_gate & su_cross & np.isfinite(su_s) & (su_s < 0) & (cl > ma20)
            sell_sig = valid & (((cl < ma20) & np.isfinite(sl) & (cl < sl)) | ma200_broken)
        elif strategy_id == "S2":
            above_lu = np.isfinite(lu) & (cl > lu)
            ma200_cross = (cl > ma200) & np.isfinite(ma200_1) & (cl1 <= ma200_1)
            buy_sig = ma200_gate & (cl > ma20) & ((lu_cross & np.isfinite(lu_s) & (lu_s < 0)) | (ma200_cross & above_lu))
            sell_sig = valid & (((cl < ma20) & np.isfinite(ma20_1) & (cl1 < ma20_1)) | ma200_broken)
        elif strategy_id == "S3":
            buy_sig = ma200_gate & (su_cross | lu_cross) & (cl > ma20)
            sell_sig = valid & (
                ((cl < ma20) & np.isfinite(sl) & (cl < sl))
                | ((cl < ma20) & np.isfinite(ma20_1) & (cl1 < ma20_1))
                | ma200_broken
            )
        elif strategy_id == "S4":
            near_sl = np.isfinite(sl) & np.isfinite(sl_s) & (sl_s > 0) & (np.abs(lo - sl) / np.maximum(sl, 1e-9) <= 0.03)
            near_ll = np.isfinite(ll) & np.isfinite(ll_s) & (ll_s > 0) & (np.abs(lo - ll) / np.maximum(ll, 1e-9) <= 0.03)
            near_m20 = np.abs(lo - ma20) / np.maximum(ma20, 1e-9) <= 0.03
            near_m200 = np.abs(lo - ma200) / np.maximum(ma200, 1e-9) <= 0.035
            buy_sig = ma200_gate & (near_sl | near_ll) & (near_m20 | near_m200) & (cl > op) & (cl >= ma20 * 0.99)
            hit_upper = (np.isfinite(su) & (hi >= su * 0.995)) | (np.isfinite(lu) & (hi >= lu * 0.995))
            broke_support = (np.isfinite(sl) & (cl < sl * 0.985) & (cl < ma20)) | ma200_broken
            sell_sig = valid & (hit_upper | broke_support)
        elif strategy_id == "S5":
            short_conv = np.isfinite(su_s) & np.isfinite(sl_s) & (su_s < 0) & (sl_s > 0)
            long_conv = np.isfinite(lu_s) & np.isfinite(ll_s) & (lu_s < 0) & (ll_s > 0)
            buy_sig = ma200_gate & ((short_conv & su_cross) | (long_conv & lu_cross)) & (cl > ma20) & (vol_ratio >= 1.3)
            sell_sig = valid & (
                ((cl < ma20) & np.isfinite(ma20_1) & (cl1 < ma20_1))
                | (np.isfinite(sl) & (cl < sl))
                | ma200_broken
            )
        elif strategy_id == "S6":
            horizon = cp["horizon"]
            req_desc = bool(cp["require_descending"])
            confirm = int(cp["confirm_bars"])
            flat_tol = float(cp.get("ma200_flat_tol", MA200_FLAT_MIN_PCT))

            def _vbreak(line: np.ndarray, line1: np.ndarray, line2: np.ndarray, slope: np.ndarray) -> np.ndarray:
                base = np.isfinite(line) & np.isfinite(slope)
                if req_desc:
                    base = base & (slope < 0)
                if confirm <= 1:
                    return base & np.isfinite(line1) & (cl > line) & (cl1 <= line1)
                return base & np.isfinite(line1) & np.isfinite(line2) & (cl > line) & (cl1 > line1) & (cl2 <= line2)

            if horizon == "short":
                broke = _vbreak(su, su1, su2, su_s)
            elif horizon == "long":
                broke = _vbreak(lu, lu1, lu2, lu_s)
            else:
                broke = _vbreak(su, su1, su2, su_s) | _vbreak(lu, lu1, lu2, lu_s)

            m200_mode = cp["ma200_filter"]
            if m200_mode == "none":
                ma200_ok = valid
            elif m200_mode == "above":
                ma200_ok = valid & (cl > ma200)
            elif m200_mode == "above_strict_up":
                ma200_ok = valid & (cl > ma200) & (ma200_chg10 > 0.0)
            else:
                ma200_ok = valid & (cl > ma200) & ((ma200_chg10 >= flat_tol) | (np.isfinite(ma200_chg5) & (ma200_chg5 >= 0.0)))

            ma20_ok = np.ones(n, dtype=bool) if not cp["ma20_filter"] else (cl > ma20)
            ma20_slope_ok = np.ones(n, dtype=bool) if not cp["ma20_rising"] else (np.isfinite(ma20_slope) & (ma20_slope > 0))
            vol_ok = vol_ratio >= float(cp["vol_mult"])
            buy_sig = broke & ma200_ok & ma20_ok & ma20_slope_ok & vol_ok

            exit_mode = cp["exit_mode"]
            base_exit = ma200_broken if m200_mode != "none" else np.zeros(n, dtype=bool)
            if exit_mode == "ma20_break":
                sell_sig = valid & (base_exit | (cl < ma20))
            elif exit_mode == "ma20_2d":
                sell_sig = valid & (base_exit | ((cl < ma20) & np.isfinite(ma20_1) & (cl1 < ma20_1)))
            elif exit_mode == "lower_and_ma20":
                sell_sig = valid & (base_exit | ((cl < ma20) & np.isfinite(sl) & (cl < sl)))
            elif exit_mode == "upper_tp_or_ma20":
                sell_sig = valid & (
                    base_exit
                    | (np.isfinite(su) & (hi >= su * 0.995))
                    | ((cl < ma20) & np.isfinite(ma20_1) & (cl1 < ma20_1))
                )

    if with_reasons:
        for t in np.flatnonzero(buy_sig):
            tag = "MA200 상승" if ma200_chg10[t] > 0.05 else "MA200 평평·미세상승"
            if strategy_id == "S1":
                buy_reason[t] = f"{tag} + 단기 하락선 돌파 + MA20 위"
            elif strategy_id == "S2":
                buy_reason[t] = f"{tag} + 장기 상단선 돌파 안착"
            elif strategy_id == "S3":
                buy_reason[t] = f"{tag} + " + ("장기" if lu_cross[t] else "단기") + " 상단선 돌파 + MA20 위"
            elif strategy_id == "S4":
                buy_reason[t] = f"{tag} + 상승 지지선·이평선 이중 지지 반등"
            elif strategy_id == "S5":
                buy_reason[t] = f"{tag} + 삼각수렴 돌파 + 거래량 {vol_ratio[t]:.1f}배"
            else:
                buy_reason[t] = f"{tag} + 커스텀 돌파 조건 충족"

        for t in np.flatnonzero(sell_sig):
            if ma200_broken[t]:
                sell_reason[t] = "MA200 이탈 청산"
            elif strategy_id == "S1":
                sell_reason[t] = "단기 지지선·MA20 동시 이탈"
            elif strategy_id == "S2":
                sell_reason[t] = "MA20 2일 연속 이탈"
            elif strategy_id == "S3":
                sell_reason[t] = "MA20·하단 지지 이탈"
            elif strategy_id == "S4":
                sell_reason[t] = "상단 저항 도달 익절 또는 지지 이탈"
            elif strategy_id == "S5":
                sell_reason[t] = "MA20 2일 이탈 또는 하단 지지 이탈"
            else:
                sell_reason[t] = "커스텀 청산 조건 충족"

    return buy_sig, sell_sig, buy_reason, sell_reason


def run_backtest_single(
    symbol: str,
    ind: pd.DataFrame,
    strategy_id: str = "S3",
    years: int = 6,
    fee_rate: float = 0.001,
    custom_params: dict[str, Any] | None = None,
    include_series: bool = False,
    exit_rule: str = "default",
) -> dict[str, Any]:
    """Run causal backtest for a single symbol over the last `years` (2, 4, or 6)."""
    asset = ASSET_MAP.get(symbol, {"symbol": symbol, "name": symbol, "market": "UNKNOWN", "currency": "USD"})
    if ind.empty or len(ind) < 220:
        return {
            "symbol": symbol,
            "name": asset["name"],
            "market": asset["market"],
            "strategy_id": strategy_id,
            "exit_rule": exit_rule,
            "years": years,
            "error": "Insufficient data",
        }

    end_dt = ind["date_dt"].iloc[-1]
    start_dt = end_dt - pd.DateOffset(years=years)
    start_idx_arr = np.where(ind["date_dt"].to_numpy() >= np.datetime64(start_dt))[0]
    start_idx = int(start_idx_arr[0]) if len(start_idx_arr) > 0 else 0

    # Ensure fair start where MA200 + MA200 slope are valid
    valid_ma200 = np.where(~np.isnan(ind["ma200_chg10_pct"].to_numpy(dtype=np.float64)))[0]
    if len(valid_ma200) > 0 and start_idx < int(valid_ma200[0]):
        start_idx = int(valid_ma200[0])

    if start_idx >= len(ind) - 5:
        start_idx = max(0, len(ind) - 60)

    buy_sig, sell_sig, buy_reason, sell_reason = evaluate_signals(
        ind, strategy_id, custom_params, with_reasons=include_series
    )
    cl = ind["close"].to_numpy(dtype=np.float64)
    ma20 = ind["ma20"].to_numpy(dtype=np.float64)
    ma200 = ind["ma200"].to_numpy(dtype=np.float64)
    sl = ind["short_lower"].to_numpy(dtype=np.float64)
    ll = ind["long_lower"].to_numpy(dtype=np.float64)
    dates = ind["date"].tolist()

    cp = {**DEFAULT_CUSTOM_PARAMS, **(custom_params or {})}
    if exit_rule == "default":
        stop_loss_pct = float(cp["stop_loss_pct"]) if strategy_id == "S6" else (7.0 if strategy_id == "S4" else 8.0)
        take_profit_pct = float(cp["take_profit_pct"]) if strategy_id == "S6" else 0.0
    elif exit_rule == "ma20_2d":
        stop_loss_pct, take_profit_pct = 8.0, 0.0
    elif exit_rule == "short_lower":
        stop_loss_pct, take_profit_pct = 10.0, 0.0
    elif exit_rule in ("long_lower", "ma200_2d", "dead_cross"):
        stop_loss_pct, take_profit_pct = 12.0, 0.0
    elif exit_rule == "trailing_12":
        stop_loss_pct, take_profit_pct = 12.0, 0.0
    else:
        stop_loss_pct, take_profit_pct = 8.0, 0.0

    cash = 1.0
    shares = 0.0
    in_pos = False
    entry_price = 0.0
    peak_price_in_pos = 0.0
    entry_idx = -1
    entry_date = ""
    entry_reason_str = ""

    trades: list[dict[str, Any]] = []
    equity_curve: list[dict[str, Any]] = []
    peak_eq = 1.0
    max_dd = 0.0

    bnh_base = cl[start_idx]

    for t in range(start_idx, len(ind)):
        price = cl[t]
        if in_pos:
            if price > peak_price_in_pos:
                peak_price_in_pos = price
            ret_from_entry = (price / entry_price - 1.0) * 100.0
            dd_from_peak = (price / peak_price_in_pos - 1.0) * 100.0
            stop_hit = stop_loss_pct > 0 and ret_from_entry <= -stop_loss_pct
            tp_hit = take_profit_pct > 0 and ret_from_entry >= take_profit_pct
            min_hold_ok = (t - entry_idx) >= (3 if (strategy_id == "S4" and exit_rule == "default") else 1)

            ma200_2d_break = (
                t >= 1
                and _is_valid(ma200[t])
                and _is_valid(ma200[t - 1])
                and price < ma200[t]
                and cl[t - 1] < ma200[t - 1]
            )

            rule_exit = False
            rule_reason = ""
            if exit_rule == "default":
                rule_exit = bool(sell_sig[t])
                rule_reason = sell_reason[t]
            elif exit_rule == "ma20_2d":
                if t >= 1 and _is_valid(ma20[t]) and _is_valid(ma20[t - 1]) and price < ma20[t] and cl[t - 1] < ma20[t - 1]:
                    rule_exit, rule_reason = True, "MA20 2일 연속 이탈"
                elif ma200_2d_break:
                    rule_exit, rule_reason = True, "MA200 2일 이탈"
            elif exit_rule == "short_lower":
                if _is_valid(sl[t]) and price < sl[t]:
                    rule_exit, rule_reason = True, "단기 하단 추세선 이탈"
                elif ma200_2d_break:
                    rule_exit, rule_reason = True, "MA200 2일 이탈"
            elif exit_rule == "long_lower":
                if _is_valid(ll[t]) and price < ll[t]:
                    rule_exit, rule_reason = True, "장기 하단 추세선 이탈"
                elif ma200_2d_break:
                    rule_exit, rule_reason = True, "MA200 2일 이탈"
            elif exit_rule == "ma200_2d":
                if ma200_2d_break:
                    rule_exit, rule_reason = True, "MA200 2일 연속 이탈"
            elif exit_rule == "trailing_12":
                if dd_from_peak <= -12.0:
                    rule_exit, rule_reason = True, "고점 대비 -12% 트레일링 청산"
                elif ma200_2d_break:
                    rule_exit, rule_reason = True, "MA200 2일 이탈"
            elif exit_rule == "dead_cross":
                if _is_valid(ma20[t]) and _is_valid(ma200[t]) and ma20[t] < ma200[t]:
                    rule_exit, rule_reason = True, "MA20·MA200 데드크로스 청산"

            if stop_hit or tp_hit or (rule_exit and min_hold_ok):
                exit_price = price
                cash = shares * exit_price * (1.0 - fee_rate)
                shares = 0.0
                in_pos = False
                net_ret = ((exit_price * (1.0 - fee_rate)) / (entry_price * (1.0 + fee_rate)) - 1.0) * 100.0
                reason = (
                    f"손절 (-{stop_loss_pct:.0f}%)"
                    if stop_hit
                    else (f"목표 익절 (+{take_profit_pct:.0f}%)" if tp_hit else rule_reason)
                )
                trades.append(
                    {
                        "entry_date": entry_date,
                        "exit_date": dates[t],
                        "entry_price": round(entry_price, 6),
                        "exit_price": round(exit_price, 6),
                        "return_pct": round(net_ret, 2),
                        "holding_days": t - entry_idx,
                        "entry_reason": entry_reason_str,
                        "exit_reason": reason,
                        "open": False,
                    }
                )
        else:
            if buy_sig[t]:
                entry_price = price
                peak_price_in_pos = price
                shares = (cash * (1.0 - fee_rate)) / entry_price
                cash = 0.0
                in_pos = True
                entry_idx = t
                entry_date = dates[t]
                entry_reason_str = buy_reason[t]

        eq = (shares * price) if in_pos else cash
        if eq > peak_eq:
            peak_eq = eq
        dd = (eq / peak_eq - 1.0) * 100.0
        if dd < max_dd:
            max_dd = dd

        if include_series:
            equity_curve.append(
                {
                    "time": dates[t],
                    "strategy": round((eq - 1.0) * 100.0, 2),
                    "bnh": round((price / bnh_base - 1.0) * 100.0, 2),
                }
            )

    final_price = cl[-1]
    final_eq = (shares * final_price * (1.0 - fee_rate)) if in_pos else cash
    total_return_pct = (final_eq - 1.0) * 100.0
    bnh_return_pct = (final_price / bnh_base - 1.0) * 100.0

    open_trade = None
    if in_pos:
        unrealized = ((final_price * (1.0 - fee_rate)) / (entry_price * (1.0 + fee_rate)) - 1.0) * 100.0
        open_trade = {
            "entry_date": entry_date,
            "exit_date": dates[-1],
            "entry_price": round(entry_price, 6),
            "exit_price": round(final_price, 6),
            "return_pct": round(unrealized, 2),
            "holding_days": (len(ind) - 1) - entry_idx,
            "entry_reason": entry_reason_str,
            "exit_reason": "보유 중 (미실현)",
            "open": True,
        }

    eval_trades = trades if trades else ([open_trade] if open_trade else [])
    wins = [tr for tr in eval_trades if tr["return_pct"] > 0]
    losses = [tr for tr in eval_trades if tr["return_pct"] <= 0]
    win_rate = (len(wins) / len(eval_trades) * 100.0) if eval_trades else 0.0

    gross_profit = sum(tr["return_pct"] for tr in wins)
    gross_loss = abs(sum(tr["return_pct"] for tr in losses))
    if gross_loss > 0:
        profit_factor = round(gross_profit / gross_loss, 2)
    elif gross_profit > 0:
        profit_factor = 9.99
    else:
        profit_factor = 0.0

    avg_trade_ret = (sum(tr["return_pct"] for tr in eval_trades) / len(eval_trades)) if eval_trades else 0.0
    avg_hold_days = (sum(tr["holding_days"] for tr in eval_trades) / len(eval_trades)) if eval_trades else 0.0
    actual_years = max((ind["date_dt"].iloc[-1] - ind["date_dt"].iloc[start_idx]).days / 365.25, 0.5)
    cagr = ((final_eq ** (1.0 / actual_years)) - 1.0) * 100.0 if final_eq > 0 else -100.0

    result: dict[str, Any] = {
        "symbol": symbol,
        "name": asset["name"],
        "market": asset["market"],
        "currency": asset["currency"],
        "strategy_id": strategy_id,
        "exit_rule": exit_rule,
        "years": years,
        "start_date": dates[start_idx],
        "end_date": dates[-1],
        "total_return_pct": round(total_return_pct, 2),
        "bnh_return_pct": round(bnh_return_pct, 2),
        "excess_return_pct": round(total_return_pct - bnh_return_pct, 2),
        "cagr_pct": round(cagr, 2),
        "win_rate_pct": round(win_rate, 1),
        "mdd_pct": round(max_dd, 2),
        "profit_factor": profit_factor,
        "trade_count": len(trades),
        "total_signals": len(trades) + (1 if open_trade else 0),
        "avg_trade_return_pct": round(avg_trade_ret, 2),
        "avg_hold_days": round(avg_hold_days, 1),
        "holding_now": in_pos,
    }
    if include_series:
        all_trades = trades + ([open_trade] if open_trade else [])
        result["trades"] = all_trades
        result["equity_curve"] = equity_curve
    return result


def run_research_matrix(
    short_window: int = 45,
    long_window: int = 180,
    price_source: str = "wick",
    scale_mode: str = "linear",
    fee_rate: float = 0.001,
    include_custom: bool = False,
    custom_params: dict[str, Any] | None = None,
    exit_rule: str = "default",
) -> dict[str, Any]:
    """
    Run full 30-asset × (S1..S5 [+ S6]) × (2Y, 4Y, 6Y) comparison matrix.
    Returns strategy rankings overall and per market, plus full per-asset details.
    """
    strategy_ids = list(STRATEGIES.keys()) + (["S6"] if include_custom else [])
    periods = [2, 4, 6]

    ind_map = build_indicator_map(
        short_window=short_window,
        long_window=long_window,
        price_source=price_source,
        scale_mode=scale_mode,
    )

    per_asset: dict[str, dict[str, dict[str, Any]]] = {}
    summary_by_strategy: list[dict[str, Any]] = []

    for sid in strategy_ids:
        per_asset[sid] = {}
        strat_meta = STRATEGIES.get(
            sid,
            {"id": "S6", "name": "커스텀 전략", "short_name": "S6 커스텀", "description": "사용자 지정 파라미터 전략"},
        )
        period_summaries: dict[str, Any] = {}

        for y in periods:
            pkey = f"{y}Y"
            rows: list[dict[str, Any]] = []
            for asset in ASSETS:
                sym = asset["symbol"]
                ind = ind_map.get(sym)
                if ind is None:
                    continue
                res = run_backtest_single(
                    sym,
                    ind,
                    strategy_id=sid,
                    years=y,
                    fee_rate=fee_rate,
                    custom_params=custom_params,
                    include_series=False,
                    exit_rule=exit_rule,
                )
                if "error" not in res:
                    rows.append(res)

            per_asset[sid][pkey] = {r["symbol"]: r for r in rows}

            def _agg(subset: list[dict[str, Any]]) -> dict[str, Any]:
                if not subset:
                    return {
                        "count": 0,
                        "avg_return_pct": 0.0,
                        "median_return_pct": 0.0,
                        "avg_bnh_pct": 0.0,
                        "avg_excess_pct": 0.0,
                        "avg_win_rate_pct": 0.0,
                        "avg_mdd_pct": 0.0,
                        "avg_profit_factor": 0.0,
                        "total_trades": 0,
                        "beat_bnh_count": 0,
                        "positive_count": 0,
                        "score": 0.0,
                    }
                active = [r for r in subset if r["total_signals"] > 0]
                rets = [r["total_return_pct"] for r in subset]
                bnhs = [r["bnh_return_pct"] for r in subset]
                mdds = [r["mdd_pct"] for r in subset]
                wrs = [r["win_rate_pct"] for r in active] if active else [0.0]
                pfs = [min(r["profit_factor"], 5.0) for r in active] if active else [0.0]

                avg_ret = float(np.mean(rets))
                avg_wr = float(np.mean(wrs))
                avg_mdd = float(np.mean(mdds))
                avg_pf = float(np.mean(pfs))
                calmar_bonus = (avg_ret / max(abs(avg_mdd), 10.0)) * 18.0
                score = (avg_ret * 0.55) + calmar_bonus + (avg_wr * 0.25) + (avg_pf * 6.0)

                return {
                    "count": len(subset),
                    "avg_return_pct": round(avg_ret, 2),
                    "median_return_pct": round(float(np.median(rets)), 2),
                    "avg_bnh_pct": round(float(np.mean(bnhs)), 2),
                    "avg_excess_pct": round(avg_ret - float(np.mean(bnhs)), 2),
                    "avg_win_rate_pct": round(avg_wr, 1),
                    "avg_mdd_pct": round(avg_mdd, 2),
                    "avg_profit_factor": round(avg_pf, 2),
                    "total_trades": int(sum(r["total_signals"] for r in subset)),
                    "beat_bnh_count": int(sum(1 for r in subset if r["total_return_pct"] > r["bnh_return_pct"])),
                    "positive_count": int(sum(1 for r in subset if r["total_return_pct"] > 0)),
                    "score": round(score, 2),
                }

            period_summaries[pkey] = {
                "ALL": _agg(rows),
                "KOSPI": _agg([r for r in rows if r["market"] == "KOSPI"]),
                "KOSDAQ": _agg([r for r in rows if r["market"] == "KOSDAQ"]),
                "US": _agg([r for r in rows if r["market"] == "US"]),
                "CRYPTO": _agg([r for r in rows if r["market"] == "CRYPTO"]),
            }

        overall_score = round(
            (
                period_summaries["2Y"]["ALL"]["score"]
                + period_summaries["4Y"]["ALL"]["score"]
                + period_summaries["6Y"]["ALL"]["score"]
            )
            / 3.0,
            2,
        )
        summary_by_strategy.append(
            {
                **strat_meta,
                "overall_score": overall_score,
                "periods": period_summaries,
            }
        )

    recommendations: dict[str, dict[str, Any]] = {}
    for mkt in MARKETS:
        best = max(
            summary_by_strategy,
            key=lambda s: (
                s["periods"]["2Y"][mkt]["score"]
                + s["periods"]["4Y"][mkt]["score"]
                + s["periods"]["6Y"][mkt]["score"]
            )
            / 3.0,
        )
        recommendations[mkt] = {
            "strategy_id": best["id"],
            "strategy_name": best["name"],
            "avg_win_rate_6y": best["periods"]["6Y"][mkt]["avg_win_rate_pct"],
            "avg_return_2y": best["periods"]["2Y"][mkt]["avg_return_pct"],
            "avg_return_4y": best["periods"]["4Y"][mkt]["avg_return_pct"],
            "avg_return_6y": best["periods"]["6Y"][mkt]["avg_return_pct"],
            "avg_mdd_6y": best["periods"]["6Y"][mkt]["avg_mdd_pct"],
        }

    return {
        "assets_loaded": len(ind_map),
        "periods": ["2Y", "4Y", "6Y"],
        "ma200_rule": "종가 > MA200 AND MA200 평평/미세상승(10일 변화율 ≥ -0.15% 또는 5일 변화율 ≥ 0%)",
        "params": {
            "short_window": short_window,
            "long_window": long_window,
            "price_source": price_source,
            "scale_mode": scale_mode,
            "fee_rate": fee_rate,
            "exit_rule": exit_rule,
        },
        "strategies": summary_by_strategy,
        "recommendations": recommendations,
        "per_asset": per_asset,
    }


def run_exit_rule_comparison(
    strategy_id: str = "S3",
    short_window: int = 45,
    long_window: int = 180,
    price_source: str = "wick",
    scale_mode: str = "linear",
    fee_rate: float = 0.001,
) -> dict[str, Any]:
    """Compare all 6 explicit exit rules for a given entry strategy across 150 assets and 2Y/4Y/6Y."""
    ind_map = build_indicator_map(
        short_window=short_window,
        long_window=long_window,
        price_source=price_source,
        scale_mode=scale_mode,
    )

    exit_ids = ["ma20_2d", "short_lower", "long_lower", "ma200_2d", "trailing_12", "dead_cross"]
    periods = [2, 4, 6]
    results: list[dict[str, Any]] = []

    for eid in exit_ids:
        period_summaries: dict[str, Any] = {}
        for y in periods:
            rows = []
            for asset in ASSETS:
                sym = asset["symbol"]
                ind = ind_map.get(sym)
                if ind is None:
                    continue
                r = run_backtest_single(
                    sym,
                    ind,
                    strategy_id=strategy_id,
                    years=y,
                    fee_rate=fee_rate,
                    include_series=False,
                    exit_rule=eid,
                )
                if "error" not in r:
                    rows.append(r)

            def _agg(subset: list[dict[str, Any]]) -> dict[str, Any]:
                if not subset:
                    return {
                        "avg_return_pct": 0.0,
                        "median_return_pct": 0.0,
                        "avg_bnh_pct": 0.0,
                        "avg_win_rate_pct": 0.0,
                        "avg_mdd_pct": 0.0,
                        "avg_profit_factor": 0.0,
                        "avg_hold_days": 0.0,
                        "total_trades": 0,
                        "score": 0.0,
                    }
                active = [r for r in subset if r["total_signals"] > 0]
                rets = [r["total_return_pct"] for r in subset]
                bnhs = [r["bnh_return_pct"] for r in subset]
                mdds = [r["mdd_pct"] for r in subset]
                wrs = [r["win_rate_pct"] for r in active] if active else [0.0]
                pfs = [min(r["profit_factor"], 5.0) for r in active] if active else [0.0]
                holds = [r["avg_hold_days"] for r in active] if active else [0.0]

                avg_ret = float(np.mean(rets))
                avg_wr = float(np.mean(wrs))
                avg_mdd = float(np.mean(mdds))
                avg_pf = float(np.mean(pfs))
                calmar_bonus = (avg_ret / max(abs(avg_mdd), 10.0)) * 18.0
                score = (avg_ret * 0.55) + calmar_bonus + (avg_wr * 0.25) + (avg_pf * 6.0)
                return {
                    "avg_return_pct": round(avg_ret, 2),
                    "median_return_pct": round(float(np.median(rets)), 2),
                    "avg_bnh_pct": round(float(np.mean(bnhs)), 2),
                    "avg_win_rate_pct": round(avg_wr, 1),
                    "avg_mdd_pct": round(avg_mdd, 2),
                    "avg_profit_factor": round(avg_pf, 2),
                    "avg_hold_days": round(float(np.mean(holds)), 1),
                    "total_trades": int(sum(r["total_signals"] for r in subset)),
                    "score": round(score, 2),
                }

            period_summaries[f"{y}Y"] = {
                "ALL": _agg(rows),
                "KOSPI": _agg([r for r in rows if r["market"] == "KOSPI"]),
                "KOSDAQ": _agg([r for r in rows if r["market"] == "KOSDAQ"]),
                "US": _agg([r for r in rows if r["market"] == "US"]),
                "CRYPTO": _agg([r for r in rows if r["market"] == "CRYPTO"]),
            }

        results.append({**EXIT_RULES[eid], "periods": period_summaries})

    best_by_market: dict[str, dict[str, Any]] = {}
    for mkt in MARKETS:
        best = max(
            results,
            key=lambda x: (
                x["periods"]["2Y"][mkt]["score"]
                + x["periods"]["4Y"][mkt]["score"]
                + x["periods"]["6Y"][mkt]["score"]
            )
            / 3.0,
        )
        best_by_market[mkt] = {
            "exit_id": best["id"],
            "exit_name": best["name"],
            "ret_6y": best["periods"]["6Y"][mkt]["avg_return_pct"],
            "wr_6y": best["periods"]["6Y"][mkt]["avg_win_rate_pct"],
            "mdd_6y": best["periods"]["6Y"][mkt]["avg_mdd_pct"],
            "pf_6y": best["periods"]["6Y"][mkt]["avg_profit_factor"],
        }

    return {
        "strategy_id": strategy_id,
        "strategy_name": STRATEGIES.get(strategy_id, {"name": strategy_id})["name"],
        "exits": results,
        "best_by_market": best_by_market,
    }
