"""
Empirical calibration of the 7-factor "upside score".

The raw score is a hand-weighted sum, not a probability. This module replays the score on
historical bars and measures what actually happened next:

  hit  = within `horizon` bars after entering at the next open, Target 1 was reached BEFORE the stop
  up   = close after `horizon` bars > entry

Scores are binned, shrunk toward the base rate (Bayesian prior), and made monotone with
isotonic regression (pool-adjacent-violators). The scanner then maps each live score to a
calibrated "목표가 선도달 확률".
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd

from config import ASSETS, THEMES
from backend.analytics import regime_mask
from backend.backtester import run_backtest_single

BIN_EDGES = list(range(5, 100, 5))  # 5,10,...,95
PRIOR_STRENGTH = 25.0


def _pav(values: list[float], weights: list[float]) -> list[float]:
    """Weighted isotonic (non-decreasing) regression via pool-adjacent-violators."""
    blocks = [[v, w, 1] for v, w in zip(values, weights)]
    i = 0
    while i < len(blocks) - 1:
        if blocks[i][0] > blocks[i + 1][0] + 1e-12:
            v1, w1, c1 = blocks[i]
            v2, w2, c2 = blocks[i + 1]
            w = w1 + w2
            blocks[i] = [(v1 * w1 + v2 * w2) / w if w > 0 else (v1 + v2) / 2, w, c1 + c2]
            del blocks[i + 1]
            i = max(i - 1, 0)
        else:
            i += 1
    out: list[float] = []
    for v, _, c in blocks:
        out.extend([v] * c)
    return out


def _signal_state_arrays(n: int, dates: list[str], trades: list[dict[str, Any]]) -> list[str]:
    """Reconstruct the scanner's BUY/HOLD/SELL state for every bar from the trade list."""
    idx = {d: i for i, d in enumerate(dates)}
    state = [""] * n
    for tr in trades:
        e = idx.get(tr["entry_date"])
        s = idx.get(tr.get("signal_date") or tr["entry_date"], e)
        x = idx.get(tr["exit_date"])
        if e is None:
            continue
        end = (x if x is not None else n - 1) if not tr["open"] else n - 1
        for t in range(e, end + (1 if tr["open"] else 0)):
            state[t] = "HOLD"
        for t in range(s if s is not None else e, min(e + 2, n)):
            state[t] = "BUY"
        if not tr["open"] and x is not None:
            for t in range(max(x - 1, 0), min(x + 2, n)):
                if state[t] != "BUY":
                    state[t] = "SELL"
    return state


def build_calibration(
    ind_map: dict[str, pd.DataFrame],
    rules: dict[str, dict[str, Any]],
    breadth: dict[str, pd.Series] | None = None,
    horizon: int = 20,
    step: int = 3,
    years: int = 6,
    near_threshold_pct: float = 3.0,
    execution: str = "next_open",
    cost_model: str = "market",
) -> dict[str, Any]:
    from backend.scanner import _compute_trade_plan, _extract_bar_snapshot, _score_upside_probability

    breadth = breadth or {}

    # Per-theme bull ratio per date (causal cross-section), same definition as the live scanner
    theme_frames: dict[str, list[pd.Series]] = {t["id"]: [] for t in THEMES}
    for a in ASSETS:
        ind = ind_map.get(a["symbol"])
        if ind is None:
            continue
        cl = ind["close"].to_numpy(dtype=np.float64)
        ma200 = ind["ma200"].to_numpy(dtype=np.float64)
        c10 = ind["ma200_chg10_pct"].to_numpy(dtype=np.float64)
        c5 = ind["ma200_chg5_pct"].to_numpy(dtype=np.float64)
        with np.errstate(invalid="ignore"):
            ok = (cl > ma200) & ((c10 >= -0.15) | (np.isfinite(c5) & (c5 >= 0.0)))
        theme_frames.setdefault(a["theme"], []).append(pd.Series(ok.astype(float), index=ind["date"].astype(str)))
    theme_bull = {
        th: pd.concat(lst, axis=1).mean(axis=1) * 100.0 for th, lst in theme_frames.items() if lst
    }

    samples: list[tuple[float, int, int, float, str]] = []  # score, hit, up, fwd_ret, rating
    for a in ASSETS:
        sym = a["symbol"]
        ind = ind_map.get(sym)
        if ind is None or len(ind) < 260:
            continue
        rule = rules.get(a["market"], {"strategy_id": "S3", "exit_rule": "ma200_2d"})
        bt = run_backtest_single(
            sym, ind, strategy_id=rule["strategy_id"], exit_rule=rule["exit_rule"], years=years,
            include_series=True, execution=execution, cost_model=cost_model,
            stop_mode=rule.get("stop_mode", "fixed"),
            regime_ok=regime_mask(ind, breadth.get(a["market"])) if rule.get("regime_filter") else None,
        )
        if "error" in bt:
            continue
        n = len(ind)
        dates = ind["date"].astype(str).tolist()
        states = _signal_state_arrays(n, dates, bt.get("trades", []))
        op = ind["open"].to_numpy(dtype=np.float64)
        hi = ind["high"].to_numpy(dtype=np.float64)
        lo = ind["low"].to_numpy(dtype=np.float64)
        cl = ind["close"].to_numpy(dtype=np.float64)
        tb = theme_bull.get(a["theme"])
        start_idx = dates.index(bt["start_date"]) if bt["start_date"] in dates else 220

        for t in range(max(start_idx, 220), n - horizon - 1, step):
            snap = _extract_bar_snapshot(ind, t)
            sig = states[t] or "WATCH"
            if sig == "WATCH" and snap["ma200_rule_ok"] and any(
                d is not None and 0.0 <= d <= near_threshold_pct for d in (snap["dist_su"], snap["dist_lu"])
            ):
                sig = "NEAR"
            atr_pct = float(ind["atr14_pct"].iat[t]) if "atr14_pct" in ind.columns else None
            prob, r_code, _, _ = _score_upside_probability(
                price=snap["price"], open_p=snap["open"], ma20=snap["ma20"], ma20_slope=snap["ma20_slope"],
                ma200=snap["ma200"], ma200_state=snap["ma200_state"], ma200_rule_ok=snap["ma200_rule_ok"],
                weekly_bull=snap["weekly_bull"], rsi14=snap["rsi14"], signal=sig, dist_su=snap["dist_su"],
                dist_lu=snap["dist_lu"], dist_sl=snap["dist_sl"], vol_ratio=snap["vol_ratio"],
                ret5_pct=snap["ret5_pct"], hist_pf_6y=float(bt["profit_factor"]),
                hist_wr_6y=float(bt["win_rate_pct"]), hist_ret_6y=float(bt["total_return_pct"]),
                theme_bull_pct=float(tb.get(dates[t], 0.0)) if tb is not None else 0.0,
            )
            plan = _compute_trade_plan(
                price=snap["price"], ma20=snap["ma20"], ma200=snap["ma200"], su=snap["su"], sl=snap["sl"],
                lu=snap["lu"], high180=snap["high180"], signal=sig, atr_pct=atr_pct,
            )
            entry = op[t + 1]
            if not np.isfinite(entry) or entry <= 0:
                continue
            hit = 0
            for j in range(t + 1, t + 1 + horizon):
                if lo[j] <= plan["stop_loss"]:
                    break
                if hi[j] >= plan["target_1"]:
                    hit = 1
                    break
            fwd = cl[t + horizon] / entry - 1.0
            samples.append((prob, hit, int(fwd > 0), fwd, r_code))

    if not samples:
        return {"error": "No samples"}

    arr_score = np.array([s[0] for s in samples])
    arr_hit = np.array([s[1] for s in samples], dtype=float)
    arr_up = np.array([s[2] for s in samples], dtype=float)
    arr_fwd = np.array([s[3] for s in samples], dtype=float)
    base_hit, base_up = float(arr_hit.mean()), float(arr_up.mean())

    bins = []
    edges = [0.0, *BIN_EDGES, 100.0]
    for lo_e, hi_e in zip(edges[:-1], edges[1:]):
        m = (arr_score >= lo_e) & (arr_score < hi_e)
        n_b = int(m.sum())
        bins.append({
            "lo": lo_e, "hi": hi_e, "n": n_b,
            "raw_hit": float(arr_hit[m].mean()) if n_b else None,
            "hit_s": (float(arr_hit[m].sum()) + PRIOR_STRENGTH * base_hit) / (n_b + PRIOR_STRENGTH),
            "up_s": (float(arr_up[m].sum()) + PRIOR_STRENGTH * base_up) / (n_b + PRIOR_STRENGTH),
            "avg_fwd_ret_pct": round(float(arr_fwd[m].mean()) * 100.0, 2) if n_b else None,
        })
    weights = [b["n"] + 1.0 for b in bins]
    hit_iso = _pav([b["hit_s"] for b in bins], weights)
    up_iso = _pav([b["up_s"] for b in bins], weights)
    table = []
    for b, h, u in zip(bins, hit_iso, up_iso):
        table.append({
            "lo": b["lo"], "hi": b["hi"], "n": b["n"],
            "raw_hit_pct": round(b["raw_hit"] * 100.0, 1) if b["raw_hit"] is not None else None,
            "hit_prob_pct": round(h * 100.0, 1),
            "up_prob_pct": round(u * 100.0, 1),
            "avg_fwd_ret_pct": b["avg_fwd_ret_pct"],
        })

    by_rating = {}
    for code in ("STRONG_BUY", "BUY", "WATCH_BUY", "HOLD_WATCH", "SELL_WARN"):
        m = np.array([s[4] == code for s in samples])
        if m.any():
            by_rating[code] = {
                "n": int(m.sum()),
                "hit_pct": round(float(arr_hit[m].mean()) * 100.0, 1),
                "up_pct": round(float(arr_up[m].mean()) * 100.0, 1),
                "avg_fwd_ret_pct": round(float(arr_fwd[m].mean()) * 100.0, 2),
            }

    # Discrimination check: Spearman-like rank correlation between score and forward return
    rank_corr = float(pd.Series(arr_score).rank().corr(pd.Series(arr_fwd).rank()))

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "horizon_bars": horizon,
        "samples": len(samples),
        "base_hit_pct": round(base_hit * 100.0, 1),
        "base_up_pct": round(base_up * 100.0, 1),
        "score_fwd_rank_corr": round(rank_corr, 3),
        "bins": table,
        "by_rating": by_rating,
        "definition": f"다음날 시가 진입 후 {horizon}거래일 안에 손절가보다 1차 목표가에 먼저 도달할 확률",
        "caveat": "6년 PF 요인은 전체 기간 백테스트를 사용하므로 약간의 사후 정보가 섞여 있습니다.",
    }


def calibrated_probs(calib: dict[str, Any] | None, score: float) -> dict[str, float] | None:
    """Map a raw score to calibrated hit / up probabilities (linear interpolation between bin centres)."""
    if not calib or not calib.get("bins"):
        return None
    bins = calib["bins"]
    centres = [(b["lo"] + b["hi"]) / 2.0 for b in bins]
    hit = float(np.interp(score, centres, [b["hit_prob_pct"] for b in bins]))
    up = float(np.interp(score, centres, [b["up_prob_pct"] for b in bins]))
    return {"hit_prob_pct": round(hit, 1), "up_prob_pct": round(up, 1)}
