#!/usr/bin/env python3
"""200일선 허용 기준 완화 검증: 매수 = 20일선 상승 & 200일선 10일 변화율 ≥ -tol% (매도 = 20일선 5일 -2%).

사용: uv run python ma200tol_lab.py
"""
from __future__ import annotations

import numpy as np

from config import ROTATION_RULES
from pullback_lab import sleeve_returns
from slope_lab import slope_signals, target_weights
from strategy_lab import COST, MARKETS, Cfg, Lab, bnh, simulate, stats

TOLS = [("0.15", "현행 ≥-0.15%"), ("0.3", "완화 ≥-0.3%"), ("0.5", "완화 ≥-0.5%"), ("1.0", "완화 ≥-1.0%"), ("NONE", "조건 없음")]
YEARS = (2022, 2023, 2024, 2025, 2026)


def fmt(s):
    return f"연{s['cagr']:+6.1f}% MDD{s['mdd']:4.0f}% 샤프{s['sharpe']:5.2f}"


def rotation(lab, m, cfg, k):
    rs, bs, ex = [], [], []
    for y in YEARS:
        p = lab.panel(m, f"{y}-01-01", f"{y}-12-31")
        sim = simulate(p, cfg, k, COST[m])
        rs.append(sim["r"]); bs.append(bnh(p, COST[m])); ex.append(sim["expo"])
    ppy = 365 if m == "CRYPTO" else 252
    return stats(np.concatenate(rs), ppy), stats(np.concatenate(bs), ppy), float(np.mean(ex))


def sleeves(lab, m, tol, start="2022-01-01", end="2099-12-31"):
    p = lab.panel(m, start, end)
    f = p["F"]
    active = np.isfinite(f.c[:5]).any(axis=0) & np.isfinite(f.ma200[:5]).any(axis=0)
    t = None if tol == "NONE" else float(tol)
    w = target_weights(slope_signals(f, 2.0, t), "B1")
    r = sleeve_returns(f, w, COST[m])[:, active]
    port = np.cumprod(1 + r, axis=0).mean(axis=1)
    return stats(np.r_[port[0] - 1, port[1:] / port[:-1] - 1], p["ppy"]), float(w[:, active].mean()) * 100


def main():
    lab = Lab()
    for m in MARKETS:
        K = ROTATION_RULES[m]["slots"]
        print(f"\n[{m}]")
        _, b, _ = rotation(lab, m, Cfg.parse("SLOPE|SLP2|--"), K)
        print(f"  단순보유                         {fmt(b)}")
        for tol, lbl in TOLS:
            line = f"  {lbl:14}"
            for reg in ("RGX@TL", "--"):
                a, _, ex = rotation(lab, m, Cfg.parse(f"SLOPE_T{tol}|SLP2|{reg}"), K)
                line += f" | 순환+{'지수필터' if reg != '--' else '필터없음'} {fmt(a)} 투자{ex:3.0f}%"
            s, ex = sleeves(lab, m, tol)
            line += f" | 종목별분산 {fmt(s)} 투자{ex:3.0f}%"
            print(line)


if __name__ == "__main__":
    main()
