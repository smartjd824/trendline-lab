#!/usr/bin/env python3
"""
Pullback Lab — is the problem the SELL rule, not the BUY rule?

Hypothesis (user): after selling, the system should be allowed to RE-BUY on a pullback (눌림목)
while the big trend (MA200) is intact — instead of waiting for a brand-new trendline breakout.

Pre-registered variants (no parameter search). Each returns a target weight w ∈ {0, 0.5, 1} per bar:
  V0  B&H                          always 1
  V1  현행형                        buy: reversal breakout in bull | sell ALL on soft exit or hard exit
  V2  현행형 + 눌림 재매수           V1, but while trend intact also re-buy on pullback bounce
  V3  분할매도 + 눌림 재매수         soft exit → sell HALF, hard exit → sell all; pullback/breakout → back to 100%
  V4  코어50 + 트레이딩50            core 50% held while trend intact (only hard exit removes it); other 50% traded
  V5  추세보유 + 눌림 재매수         only hard exit sells; re-buy on pullback / trend recovery
Soft exit definitions (two, both reported):  S1 = close < MA20 for 3 days | S2 = close < short lows-line AND < MA20
Hard exit (trend broken):                   close < MA200 for 2 days  OR  (close < long lows-line AND < MA200)
Pullback bounce: trend intact (close>MA200, MA200 flat/up, MA20>MA200), low touched MA20 (±1%) or short lows-line
                 within the last 3 bars, and today is a bullish candle closing back above MA20 (or above the lows-line).

Execution: target decided at close t, executed at open t+1; cost charged on |Δw|.
Aggregation: equal-capital sleeve per stock (sleeves not rebalanced) vs equal-weight B&H of the same stocks.

Usage: uv run python pullback_lab.py
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from strategy_lab import COST, MARKETS, F, Lab, below_n, cross_up, shift, stats

PERIODS = [("2020-03-01", "2026-12-31", "전체 2020~"), ("2020-03-01", "2023-12-31", "앞 2020~23"), ("2024-01-01", "2026-12-31", "뒤 2024~")]


def signals(f: F, soft: str) -> dict[str, np.ndarray]:
    c, o, l = f.c, f.o, f.l
    with np.errstate(invalid="ignore"):
        ma200_up = f.ma200_up > 0
        bull = (c > f.ma200) & ma200_up
        trend_ok = bull & (f.ma20 > f.ma200)
        rev = (cross_up(c, f.su) & (f.su_s < 0)) | (cross_up(c, f.lu) & (f.lu_s < 0))
        entry = rev & bull & (c > f.ma20)  # V1 buy rule (current system core)
        if soft == "S1":
            soft_x = below_n(c, f.ma20, 3)
        else:
            soft_x = (c < f.sl) & (c < f.ma20)
        hard_x = below_n(c, f.ma200, 2) | ((c < f.ll) & (c < f.ma200))
        touch20 = l <= f.ma20 * 1.01
        touchsl = l <= f.sl * 1.01
        t20 = touch20 | shift(touch20.astype(float), 1).astype(bool) | shift(touch20.astype(float), 2).astype(bool)
        tsl = touchsl | shift(touchsl.astype(float), 1).astype(bool) | shift(touchsl.astype(float), 2).astype(bool)
        bull_candle = c > o
        pb = trend_ok & bull_candle & ((t20 & (c > f.ma20)) | (tsl & (c > f.sl)))
        # bottom reversal (below MA200 allowed): descending highs-line break + close>MA20 + MA20 rising
        rev_any = rev & (c > f.ma20) & (f.ma20 > shift(f.ma20, 3))
        hard_slow = below_n(c, f.ma200, 2) & (c < f.ll)
    z = lambda a: np.nan_to_num(a.astype(float)).astype(bool)
    return {k: z(v) for k, v in dict(bull=bull, trend_ok=trend_ok, entry=entry, soft=soft_x, hard=hard_x, pb=pb, rev_any=rev_any, hard_slow=hard_slow).items()}


def target_weights(sig: dict[str, np.ndarray], variant: str) -> np.ndarray:
    T, N = sig["entry"].shape
    w = np.zeros((T, N))
    cur = np.zeros(N)
    for t in range(T):
        ent, soft, hard, pb, tok = sig["entry"][t], sig["soft"][t], sig["hard"][t], sig["pb"][t], sig["trend_ok"][t]
        if variant == "V0":
            cur[:] = 1.0
        elif variant == "V1":
            cur = np.where(cur > 0, np.where(soft | hard, 0.0, 1.0), np.where(ent, 1.0, 0.0))
        elif variant == "V2":
            cur = np.where(cur > 0, np.where(soft | hard, 0.0, 1.0), np.where(ent | pb, 1.0, 0.0))
        elif variant == "V3":
            up = ent | pb
            nxt = cur.copy()
            nxt = np.where((cur == 1.0) & soft, 0.5, nxt)
            nxt = np.where((cur < 1.0) & up, 1.0, nxt)
            nxt = np.where(hard, 0.0, nxt)
            cur = nxt
        elif variant == "V4":
            core = np.where(hard, 0.0, np.where(tok | (cur >= 0.5), 0.5, 0.0))  # core held until trend breaks
            trade_on = (cur >= 1.0)
            trade_on = np.where(trade_on, ~(soft | hard), ent | pb)
            cur = core + np.where(trade_on & (core > 0), 0.5, 0.0)
            cur = np.where((core == 0) & ent, 1.0, cur)  # breakout from flat: take both halves
        elif variant == "V5":
            cur = np.where(cur > 0, np.where(hard, 0.0, 1.0), np.where(ent | pb | tok, 1.0, 0.0))
        elif variant == "V6":
            cur = np.where(cur > 0, np.where(hard, 0.0, 1.0), np.where(ent | pb | tok | sig["rev_any"][t], 1.0, 0.0))
        elif variant == "V7":
            cur = np.where(cur > 0, np.where(sig["hard_slow"][t], 0.0, 1.0), np.where(ent | pb | tok | sig["rev_any"][t], 1.0, 0.0))
        w[t] = cur
    return w


def sleeve_returns(f: F, tgt: np.ndarray, cost: float) -> np.ndarray:
    """r_t = e_{t-1}·(o_t/c_{t-1}-1) + e_t·(c_t/o_t-1) − cost·|e_t−e_{t-1}|, e_t = tgt_{t-1} (next-open execution)."""
    c, o = f.c, f.o
    e = shift(tgt, 1)
    e = np.nan_to_num(e)
    e_prev = np.nan_to_num(shift(e, 1))
    c1 = shift(c, 1)
    with np.errstate(invalid="ignore", divide="ignore"):
        r = e_prev * (o / c1 - 1) + e * (c / o - 1) - cost * np.abs(e - e_prev)
    return np.nan_to_num(r)


def evaluate(lab: Lab, m: str, start: str, end: str, variant: str, soft: str) -> dict:
    p = lab.panel(m, start, end)
    f = p["F"]
    tgt = target_weights(signals(f, soft), variant)
    # only names trading (with valid MA200) from the window start
    active = np.isfinite(f.c[:5]).any(axis=0) & np.isfinite(f.ma200[:5]).any(axis=0)
    r = sleeve_returns(f, tgt, COST[m])[:, active]
    curves = np.cumprod(1 + r, axis=0)
    port = curves.mean(axis=1)
    pr = np.r_[port[0] - 1, port[1:] / port[:-1] - 1]
    st = stats(pr, p["ppy"])
    per = [stats(r[:, j], p["ppy"]) for j in range(r.shape[1])]
    st["names"] = r.shape[1]
    st["expo"] = float(np.mean(tgt[:, active])) * 100
    st["per_ret"] = [x["ret"] for x in per]
    st["turnover"] = float(np.abs(np.diff(tgt[:, active], axis=0)).sum(axis=0).mean())
    return st


def main() -> None:
    lab = Lab()
    variants = [("V0", "S1", "단순보유"), ("V1", "S1", "현행형(20일선3일 전량매도)"), ("V2", "S1", "현행형+눌림재매수"), ("V3", "S1", "분할매도+눌림재매수"),
                ("V4", "S1", "코어50+트레이딩50"), ("V5", "S1", "추세보유+눌림재매수"),
                ("V6", "S1", "V5+바닥 추세전환 재진입"), ("V7", "S1", "V6+매도 더 늦게(200일&장기하단)"),
                ("V1", "S2", "현행형(단기하단선&MA20)"), ("V2", "S2", "  +눌림재매수"), ("V3", "S2", "  분할매도+눌림"), ("V4", "S2", "  코어50+트레이딩")]
    for m in MARKETS:
        print(f"\n[{m}]  (각 종목 동일금액, 다음날 시가 체결, 비용 {COST[m] * 100:.2f}%/편도)")
        print(f"  {'변형':26}" + "".join(f"{lbl:>34}" for _, _, lbl in PERIODS) + f"{'종목별 B&H 이긴 비율':>22}{'평균비중':>9}{'연간회전':>8}")
        bh_per = {}
        for v, sft, name in variants:
            cells, beat = [], ""
            for s, e, lbl in PERIODS:
                st = evaluate(lab, m, s, e, v, sft)
                if v == "V0":
                    bh_per[lbl] = st["per_ret"]
                cells.append(f"{st['cagr']:+6.1f}%/년 MDD{st['mdd']:4.0f}% Sh{st['sharpe']:5.2f}")
                if lbl.startswith("전체"):
                    full = st
            if v != "V0":
                b = np.array(bh_per["전체 2020~"])
                beat = f"{np.mean(np.array(full['per_ret']) > b) * 100:.0f}%"
            yrs = 6.7
            print(f"  {name:26}" + "".join(f"{c:>34}" for c in cells) + f"{beat:>22}{full['expo']:>8.0f}%{full['turnover'] / yrs:>8.1f}")


if __name__ == "__main__":
    main()
