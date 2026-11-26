#!/usr/bin/env python3
"""이평선 배열 매수 조건 검증 (2026-11-27)
  A  기준: 20일선 상승 & 200일선 평평/상승                         (SLOPE)
  B  5 > 40 > 20 배열 + 20일선 상승 + 200일선 (상태/첫날)          (ORD5_40_20 / ORD5_40_20E)
  C  5 > 20 > 40 정배열 + 20일선 상승 + 200일선 (상태/첫날)        (ORD5_20_40 / ORD5_20_40E)
  매도: 20일선 5일 -2% 꺾임 (공통), 지수필터 有/無. 2022~2026 연도별 이어붙임, 다음날 시가, 실비용.
사용: uv run python ma_order_lab.py
"""
from __future__ import annotations

import numpy as np

from config import ROTATION_RULES
from ma200tol_lab import fmt, rotation
from pullback_lab import sleeve_returns
from strategy_lab import COST, MARKETS, Cfg, Lab, build_signals, stats

ENTRIES = [("SLOPE", "A 기준(20일선↑)"), ("ORD5_40_20", "B 5>40>20 상태"), ("ORD5_40_20E", "B 5>40>20 첫날"),
           ("ORD5_20_40", "C 5>20>40 상태"), ("ORD5_20_40E", "C 5>20>40 첫날")]


def sleeves(lab, m, entry, start="2022-01-01", end="2099-12-31"):
    p = lab.panel(m, start, end)
    f = p["F"]
    ent, ex = build_signals(f, Cfg.parse(f"{entry}|SLP2|--"), None)
    T, N = ent.shape
    w = np.zeros((T, N)); cur = np.zeros(N, bool)
    for t in range(T):
        cur = np.where(cur, ~ex[t], ent[t] & ~ex[t]); w[t] = cur
    active = np.isfinite(f.c[:5]).any(axis=0) & np.isfinite(f.ma200[:5]).any(axis=0)
    r = sleeve_returns(f, w, COST[m])[:, active]
    port = np.cumprod(1 + r, axis=0).mean(axis=1)
    n_entries = int((np.diff(w[:, active], axis=0) > 0).sum())
    return stats(np.r_[port[0] - 1, port[1:] / port[:-1] - 1], p["ppy"]), float(w[:, active].mean()) * 100, n_entries


def main():
    lab = Lab()
    for m in MARKETS:
        K = ROTATION_RULES[m]["slots"]
        _, b, _ = rotation(lab, m, Cfg.parse("SLOPE|SLP2|--"), K)
        print(f"\n[{m}]  단순보유 {fmt(b)}")
        for e, lbl in ENTRIES:
            a1, _, x1 = rotation(lab, m, Cfg.parse(f"{e}|SLP2|RGX@TL"), K)
            a2, _, x2 = rotation(lab, m, Cfg.parse(f"{e}|SLP2|--"), K)
            s, xs, ne = sleeves(lab, m, e)
            print(f"  {lbl:16} | 순환+지수필터 {fmt(a1)} 투자{x1:3.0f}% | 순환 필터없음 {fmt(a2)} | 종목별분산 {fmt(s)} 투자{xs:3.0f}% 매수횟수{ne}")


if __name__ == "__main__":
    main()
