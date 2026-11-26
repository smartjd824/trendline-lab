"""
Advanced research analytics:

1. Market breadth regime  — % of each market's assets above MA200, per date (causal).
2. Walk-forward rule selection — choose (entry, exit, regime filter) on a TRAIN window,
   report honest OUT-OF-SAMPLE results on the following TEST window, and pick the live rule
   on the most recent window.
3. Portfolio-level backtest — shared capital, max concurrent positions, risk-based sizing
   (risk % of equity / stop distance), realistic costs.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd

from config import (
    ASSETS,
    MARKET_BEST_RULES,
    MARKET_COSTS,
    REGIME_MIN_BREADTH_PCT,
)
from backend.backtester import EXIT_RULES, STRATEGIES, run_backtest_single

ENTRY_MARKETS = ["KOSPI", "KOSDAQ", "US", "CRYPTO"]


# ------------------------------------------------------------------ 1. Breadth regime
def compute_market_breadth(ind_map: dict[str, pd.DataFrame]) -> dict[str, pd.Series]:
    """Per market: date -> % of that market's assets closing above MA200 (only uses data up to that date)."""
    per_mkt: dict[str, list[pd.Series]] = {m: [] for m in ENTRY_MARKETS}
    for asset in ASSETS:
        ind = ind_map.get(asset["symbol"])
        if ind is None or asset["market"] not in per_mkt:
            continue
        ma200 = ind["ma200"].to_numpy(dtype=np.float64)
        above = np.where(np.isfinite(ma200), (ind["close"].to_numpy(dtype=np.float64) > ma200).astype(float), np.nan)
        per_mkt[asset["market"]].append(pd.Series(above, index=pd.Index(ind["date"].astype(str))))

    out: dict[str, pd.Series] = {}
    all_series: list[pd.Series] = []
    for mkt, series in per_mkt.items():
        if not series:
            continue
        frame = pd.concat(series, axis=1).sort_index()
        counts = frame.notna().sum(axis=1)
        pct = frame.mean(axis=1, skipna=True) * 100.0
        out[mkt] = pct.where(counts >= 5)
        all_series.extend(series)
    if all_series:
        frame = pd.concat(all_series, axis=1).sort_index()
        out["ALL"] = (frame.mean(axis=1, skipna=True) * 100.0).where(frame.notna().sum(axis=1) >= 5)
    return out


def regime_mask(ind: pd.DataFrame, breadth: pd.Series | None, min_pct: float = REGIME_MIN_BREADTH_PCT) -> np.ndarray:
    """Bool array aligned to `ind`: True where market breadth >= min_pct (unknown breadth -> allowed)."""
    if breadth is None or breadth.empty:
        return np.ones(len(ind), dtype=bool)
    aligned = breadth.reindex(ind["date"].astype(str)).to_numpy(dtype=np.float64)
    return ~(np.isfinite(aligned) & (aligned < min_pct))


# ------------------------------------------------------------------ shared scoring
def aggregate_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Same composite score as the research matrix (return, Calmar-like bonus, win rate, PF)."""
    if not rows:
        return {"count": 0, "avg_return_pct": 0.0, "avg_bnh_pct": 0.0, "avg_win_rate_pct": 0.0,
                "avg_mdd_pct": 0.0, "avg_profit_factor": 0.0, "total_trades": 0, "score": 0.0}
    active = [r for r in rows if r["total_signals"] > 0]
    avg_ret = float(np.mean([r["total_return_pct"] for r in rows]))
    avg_mdd = float(np.mean([r["mdd_pct"] for r in rows]))
    avg_wr = float(np.mean([r["win_rate_pct"] for r in active])) if active else 0.0
    avg_pf = float(np.mean([min(r["profit_factor"], 5.0) for r in active])) if active else 0.0
    score = (avg_ret * 0.55) + (avg_ret / max(abs(avg_mdd), 10.0)) * 18.0 + (avg_wr * 0.25) + (avg_pf * 6.0)
    return {
        "count": len(rows),
        "avg_return_pct": round(avg_ret, 2),
        "avg_bnh_pct": round(float(np.mean([r["bnh_return_pct"] for r in rows])), 2),
        "avg_win_rate_pct": round(avg_wr, 1),
        "avg_mdd_pct": round(avg_mdd, 2),
        "avg_profit_factor": round(avg_pf, 2),
        "total_trades": int(sum(r["total_signals"] for r in rows)),
        "score": round(score, 2),
    }


def _rule_label(sid: str, eid: str, regime: bool) -> str:
    return f"{sid}+{EXIT_RULES[eid]['short_name']}" + ("+국면필터" if regime else "")


# ------------------------------------------------------------------ 2. Walk-forward
def walk_forward_select(
    ind_map: dict[str, pd.DataFrame],
    breadth: dict[str, pd.Series] | None = None,
    train_years: int = 4,
    test_years: int = 2,
    live_years: int = 4,
    execution: str = "next_open",
    cost_model: str = "market",
    min_trades: int = 15,
) -> dict[str, Any]:
    """
    For every market:
      VALIDATION: choose the best combo on [T-test-train, T-test], evaluate it on [T-test, T] (unseen).
      LIVE      : choose the best combo on the most recent `live_years` -> used by the scanner.
    The OOS rank of the train-selected rule tells you how much of its edge was overfitting.
    """
    breadth = breadth if breadth is not None else compute_market_breadth(ind_map)
    combos = [(sid, eid, rg) for sid in STRATEGIES for eid in EXIT_RULES if eid != "default" for rg in (False, True)]
    report: dict[str, Any] = {}

    for mkt in ENTRY_MARKETS:
        members = [(a["symbol"], ind_map[a["symbol"]]) for a in ASSETS if a["market"] == mkt and a["symbol"] in ind_map]
        if not members:
            continue
        last = max(ind["date_dt"].iloc[-1] for _, ind in members)
        test_start = last - pd.DateOffset(years=test_years)
        train_start = test_start - pd.DateOffset(years=train_years)
        live_start = last - pd.DateOffset(years=live_years)
        fmt = lambda d: d.strftime("%Y-%m-%d")  # noqa: E731
        masks = {sym: regime_mask(ind, breadth.get(mkt)) for sym, ind in members}

        def _eval(sid: str, eid: str, rg: bool, start: pd.Timestamp, end: pd.Timestamp | None) -> dict[str, Any]:
            rows = []
            for sym, ind in members:
                r = run_backtest_single(
                    sym, ind, strategy_id=sid, exit_rule=eid, execution=execution, cost_model=cost_model,
                    regime_ok=masks[sym] if rg else None,
                    start_date=fmt(start), end_date=fmt(end) if end is not None else None,
                )
                if "error" not in r:
                    rows.append(r)
            return aggregate_rows(rows)

        train_scores, test_scores, live_scores = {}, {}, {}
        for combo in combos:
            train_scores[combo] = _eval(*combo, train_start, test_start)
            test_scores[combo] = _eval(*combo, test_start, None)
            live_scores[combo] = _eval(*combo, live_start, None)

        def _best(scores: dict) -> tuple:
            eligible = {c: v for c, v in scores.items() if v["total_trades"] >= min_trades} or scores
            return max(eligible, key=lambda c: eligible[c]["score"])

        picked = _best(train_scores)
        oos_sorted = sorted(test_scores, key=lambda c: test_scores[c]["score"], reverse=True)
        oos_rank = oos_sorted.index(picked) + 1
        fb = MARKET_BEST_RULES.get(mkt)
        fb_combo = (fb["strategy_id"], fb["exit_rule"], False) if fb else None
        live = _best(live_scores)

        report[mkt] = {
            "windows": {
                "train": [fmt(train_start), fmt(test_start)],
                "test": [fmt(test_start), fmt(last)],
                "live": [fmt(live_start), fmt(last)],
            },
            "validation": {
                "selected": {"strategy_id": picked[0], "exit_rule": picked[1], "regime_filter": picked[2],
                             "label": _rule_label(*picked)},
                "train": train_scores[picked],
                "test_oos": test_scores[picked],
                "oos_rank": oos_rank,
                "combos": len(combos),
                "oos_best": {"label": _rule_label(*oos_sorted[0]), **test_scores[oos_sorted[0]]},
                "fallback_rule_test_oos": (
                    {"label": fb["label"], **test_scores[fb_combo]} if fb_combo in test_scores else None
                ),
                "avg_combo_test_score": round(float(np.mean([v["score"] for v in test_scores.values()])), 2),
            },
            "live_rule": {
                "strategy_id": live[0],
                "exit_rule": live[1],
                "regime_filter": live[2],
                "stop_mode": "atr" if live[1] == "atr_chandelier" else "fixed",
                "label": _rule_label(*live),
                "live_window_score": live_scores[live]["score"],
            },
            "live_metrics": live_scores[live],
        }

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "method": f"train {train_years}Y → OOS test {test_years}Y; live rule = best of last {live_years}Y",
        "execution": execution,
        "cost_model": cost_model,
        "markets": report,
        "caveat": "유니버스가 현재 시점의 인기 테마 종목이라 생존 편향이 남아 있습니다 (과거 성과 과대평가 가능).",
    }


# ------------------------------------------------------------------ 3. Portfolio backtest
def run_portfolio_backtest(
    ind_map: dict[str, pd.DataFrame],
    rules: dict[str, dict[str, Any]],
    breadth: dict[str, pd.Series] | None = None,
    market: str = "ALL",
    years: int = 6,
    max_positions: int = 10,
    risk_per_trade_pct: float = 1.0,
    max_weight_pct: float = 15.0,
    execution: str = "next_open",
    cost_model: str = "market",
    fee_rate: float = 0.001,
) -> dict[str, Any]:
    """
    Shared-capital simulation over the per-asset trade lists.
    Position size = min(risk_per_trade / stop_distance, max_weight) of current equity, at most `max_positions`.
    Same-day entry candidates are taken in order of the tightest stop (lowest risk) first.
    Returns are in each asset's local currency (FX moves ignored).
    """
    breadth = breadth if breadth is not None else compute_market_breadth(ind_map)
    universe = [a for a in ASSETS if (market == "ALL" or a["market"] == market) and a["symbol"] in ind_map]
    if not universe:
        return {"market": market, "error": "No assets"}

    last = max(ind_map[a["symbol"]]["date_dt"].iloc[-1] for a in universe)
    start = last - pd.DateOffset(years=years)
    start_s = start.strftime("%Y-%m-%d")

    trades_all: list[dict[str, Any]] = []
    closes: dict[str, pd.Series] = {}
    costs: dict[str, tuple[float, float]] = {}
    for a in universe:
        sym = a["symbol"]
        ind = ind_map[sym]
        rule = rules.get(a["market"], {"strategy_id": "S3", "exit_rule": "ma200_2d"})
        bt = run_backtest_single(
            sym, ind, strategy_id=rule["strategy_id"], exit_rule=rule["exit_rule"], include_series=True,
            execution=execution, cost_model=cost_model, fee_rate=fee_rate,
            stop_mode=rule.get("stop_mode", "fixed"),
            regime_ok=regime_mask(ind, breadth.get(a["market"])) if rule.get("regime_filter") else None,
            start_date=start_s,
        )
        if "error" in bt:
            continue
        for tr in bt.get("trades", []):
            trades_all.append({**tr, "symbol": sym})
        closes[sym] = pd.Series(ind["close"].to_numpy(dtype=np.float64), index=ind["date"].astype(str))
        if cost_model == "market":
            c = MARKET_COSTS.get(a["market"], {"buy": fee_rate, "sell": fee_rate})
            costs[sym] = (float(c["buy"]), float(c["sell"]))
        else:
            costs[sym] = (fee_rate, fee_rate)

    calendar = sorted({d for s in closes.values() for d in s.index if d >= start_s})
    if not calendar:
        return {"market": market, "error": "No dates"}
    px = pd.DataFrame({sym: s[~s.index.duplicated()].reindex(calendar).ffill() for sym, s in closes.items()})

    entries_by_day: dict[str, list[dict]] = {}
    for tr in trades_all:
        entries_by_day.setdefault(tr["entry_date"], []).append(tr)
    for lst in entries_by_day.values():
        lst.sort(key=lambda x: x.get("stop_pct", 8.0))

    cash = 1.0
    positions: dict[int, dict[str, Any]] = {}  # id(trade) -> {sym, units, trade}
    equity_curve: list[float] = []
    invested_frac: list[float] = []
    taken = skipped = 0
    realized: list[float] = []
    prev_equity = 1.0

    for d in calendar:
        row = px.loc[d]
        # 1) exits scheduled today (fills at the recorded exit price)
        for pid in [k for k, p in positions.items() if (not p["trade"]["open"]) and p["trade"]["exit_date"] == d]:
            p = positions.pop(pid)
            proceeds = p["units"] * p["trade"]["exit_price"] * (1.0 - costs[p["sym"]][1])
            cash += proceeds
            realized.append(proceeds / p["alloc"] - 1.0)
        # 2) entries today
        for tr in entries_by_day.get(d, []):
            if len(positions) >= max_positions or cash <= 1e-6:
                skipped += 1
                continue
            weight = min(risk_per_trade_pct / max(tr.get("stop_pct", 8.0), 0.5), max_weight_pct / 100.0)
            alloc = min(prev_equity * weight, cash)
            if alloc <= 1e-6:
                skipped += 1
                continue
            units = alloc * (1.0 - costs[tr["symbol"]][0]) / tr["entry_price"]
            cash -= alloc
            positions[id(tr)] = {"sym": tr["symbol"], "units": units, "alloc": alloc, "trade": tr}
            taken += 1
        # 3) mark to market at today's close
        mv = 0.0
        for p in positions.values():
            price = row.get(p["sym"])
            if price is None or not np.isfinite(price):
                price = p["trade"]["entry_price"]
            mv += p["units"] * float(price)
        equity = cash + mv
        equity_curve.append(equity)
        invested_frac.append(mv / equity if equity > 0 else 0.0)
        prev_equity = equity

    eq = np.asarray(equity_curve)
    peak = np.maximum.accumulate(eq)
    mdd = float(((eq / peak) - 1.0).min() * 100.0)
    span_years = max((pd.Timestamp(calendar[-1]) - pd.Timestamp(calendar[0])).days / 365.25, 0.5)
    cagr = (eq[-1] ** (1.0 / span_years) - 1.0) * 100.0 if eq[-1] > 0 else -100.0
    rets = np.diff(eq) / eq[:-1] if len(eq) > 1 else np.array([0.0])
    periods_per_year = len(calendar) / span_years
    sharpe = float(np.mean(rets) / np.std(rets) * np.sqrt(periods_per_year)) if np.std(rets) > 0 else 0.0

    # Equal-weight buy & hold benchmark over the same universe/window
    norm = px / px.bfill().iloc[0]
    bench = norm.mean(axis=1, skipna=True).to_numpy(dtype=np.float64)
    bench_peak = np.maximum.accumulate(bench)

    step = max(1, len(calendar) // 400)
    curve = [
        {"time": calendar[i], "strategy": round((eq[i] - 1.0) * 100.0, 2), "bnh": round((bench[i] - 1.0) * 100.0, 2)}
        for i in range(0, len(calendar), step)
    ]
    if curve[-1]["time"] != calendar[-1]:
        curve.append({"time": calendar[-1], "strategy": round((eq[-1] - 1.0) * 100.0, 2),
                      "bnh": round((bench[-1] - 1.0) * 100.0, 2)})

    wins = [r for r in realized if r > 0]
    return {
        "market": market,
        "years": years,
        "start_date": calendar[0],
        "end_date": calendar[-1],
        "params": {"max_positions": max_positions, "risk_per_trade_pct": risk_per_trade_pct,
                   "max_weight_pct": max_weight_pct, "execution": execution, "cost_model": cost_model},
        "rules": {m: rules[m].get("label", "") for m in rules},
        "total_return_pct": float(round((eq[-1] - 1.0) * 100.0, 2)),
        "cagr_pct": float(round(cagr, 2)),
        "mdd_pct": round(mdd, 2),
        "sharpe": round(sharpe, 2),
        "avg_invested_pct": round(float(np.mean(invested_frac)) * 100.0, 1),
        "trades_taken": taken,
        "trades_skipped": skipped,
        "closed_trades": len(realized),
        "win_rate_pct": round(len(wins) / len(realized) * 100.0, 1) if realized else 0.0,
        "open_positions": len(positions),
        "bnh_return_pct": float(round((bench[-1] - 1.0) * 100.0, 2)),
        "bnh_mdd_pct": round(float(((bench / bench_peak) - 1.0).min() * 100.0), 2),
        "equity_curve": curve,
        "note": "현지 통화 기준 수익률(환율 미반영), 종목별 신호는 독립 계산 후 자금 한도 내에서만 체결",
    }


def run_portfolio_suite(
    ind_map: dict[str, pd.DataFrame],
    rules: dict[str, dict[str, Any]],
    breadth: dict[str, pd.Series] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    breadth = breadth if breadth is not None else compute_market_breadth(ind_map)
    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "markets": {
            m: run_portfolio_backtest(ind_map, rules, breadth, market=m, **kwargs)
            for m in ["ALL", *ENTRY_MARKETS]
        },
    }
