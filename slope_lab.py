#!/usr/bin/env python3
"""
기울기 규칙 검증 (사용자 규칙, 2026-11-26)

  매수     : 20일선 기울기 상승(5일 변화율 > 0) AND 200일선 평평/상승(10일 변화율 ≥ -0.15%)
  추가매수 : 보유 중 20일선 기울기가 꺾였다가(≤0) 다시 상승(>0)으로 회복할 때 (200일선 조건 유지)
  매도     : 20일선 기울기가 너무 꺾임 = 5일 변화율 < -T%   (T = 0.5 / 1 / 2 / 3 % 모두 보고)

  B1 한번에 : 매수 100%, 매도 후 기울기 회복(+200일선 조건)이면 다시 100%
  B2 나눠서 : 첫 매수 50%, 기울기 회복 시 +50% (최대 100%), 매도는 전량

비교 기준 (같은 조건: 2022-01-01~, 다음날 시가 체결, 실제 비용)
  · 각 종목 동일금액 분산 (종목별 규칙 적용) vs 동일금액 단순보유
  · 순환 포트폴리오 버전 (K칸, 120일 모멘텀 순 선택) vs 단순보유

사용: uv run python slope_lab.py
"""

from __future__ import annotations

import numpy as np

from config import ROTATION_RULES
from pullback_lab import sleeve_returns
from strategy_lab import COST, MARKETS, Cfg, Lab, bnh, shift, simulate, stats

THRESHOLDS = [0.5, 1.0, 2.0, 3.0]
PERIODS = [("2022-01-01", "2099-12-31", "2022~현재"), ("2020-03-01", "2023-12-31", "앞 2020~23"), ("2024-01-01", "2099-12-31", "뒤 2024~")]


def slope_signals(f, T: float, tol: float | None = 0.15) -> dict[str, np.ndarray]:
    with np.errstate(invalid="ignore", divide="ignore"):
        s20 = f.ma20 / shift(f.ma20, 5) - 1.0
        up20 = s20 > 0
        ma200_ok = (f.ma200_up > 0) if tol == 0.15 else (np.isfinite(f.ma200) if tol is None else (f.ma200_chg >= -tol))
        recover = up20 & (shift(s20, 1) <= 0)  # 기울기 회복 (꺾였다가 다시 상승 전환)
        too_down = s20 < -T / 100.0
    z = lambda a: np.nan_to_num(a.astype(float)).astype(bool)
    return {"buy": z(up20 & ma200_ok), "recover": z(recover & ma200_ok), "sell": z(too_down)}


def target_weights(sig: dict[str, np.ndarray], mode: str) -> np.ndarray:
    T, N = sig["buy"].shape
    w = np.zeros((T, N))
    cur = np.zeros(N)
    sold = np.zeros(N, bool)  # 매도 후에는 '회복' 신호가 나와야 재매수
    for t in range(T):
        buy, rec, sell = sig["buy"][t], sig["recover"][t], sig["sell"][t]
        if mode == "B1":
            entry = np.where(sold, rec, buy)
            nxt = np.where(cur > 0, np.where(sell, 0.0, 1.0), np.where(entry, 1.0, 0.0))
        else:  # B2
            entry = np.where(sold, rec, buy)
            nxt = cur.copy()
            nxt = np.where((cur == 0) & entry, 0.5, nxt)
            nxt = np.where((cur == 0.5) & rec, 1.0, nxt)
            nxt = np.where(sell, 0.0, nxt)
        sold = np.where(sell & (cur > 0), True, np.where(nxt > 0, False, sold))
        cur = nxt
        w[t] = cur
    return w


def sleeve_eval(lab: Lab, m: str, start: str, end: str, mode: str, T: float) -> tuple[dict, float]:
    p = lab.panel(m, start, end)
    f = p["F"]
    active = np.isfinite(f.c[:5]).any(axis=0) & np.isfinite(f.ma200[:5]).any(axis=0)
    w = target_weights(slope_signals(f, T), mode)
    r = sleeve_returns(f, w, COST[m])[:, active]
    port = np.cumprod(1 + r, axis=0).mean(axis=1)
    st = stats(np.r_[port[0] - 1, port[1:] / port[:-1] - 1], p["ppy"])
    return st, float(w[:, active].mean()) * 100


def bnh_eval(lab: Lab, m: str, start: str, end: str) -> dict:
    p = lab.panel(m, start, end)
    f = p["F"]
    active = np.isfinite(f.c[:5]).any(axis=0) & np.isfinite(f.ma200[:5]).any(axis=0)
    w = np.ones_like(f.c)
    r = sleeve_returns(f, w, COST[m])[:, active]
    port = np.cumprod(1 + r, axis=0).mean(axis=1)
    return stats(np.r_[port[0] - 1, port[1:] / port[:-1] - 1], p["ppy"])


def fmt(s: dict) -> str:
    return f"연{s['cagr']:+6.1f}% MDD{s['mdd']:4.0f}% 샤프{s['sharpe']:5.2f}"


def main() -> None:
    lab = Lab()
    print("① 종목별 분산 (각 종목 동일금액에 규칙 적용) — 2022~현재 / 앞 / 뒤")
    for m in MARKETS:
        print(f"\n[{m}]")
        print("  " + f"{'단순보유':22}" + " | ".join(f"{lbl}: {fmt(bnh_eval(lab, m, s, e))}" for s, e, lbl in PERIODS))
        for mode in ("B1", "B2"):
            for T in THRESHOLDS:
                cells, expo = [], 0
                for s, e, lbl in PERIODS:
                    st, ex = sleeve_eval(lab, m, s, e, mode, T)
                    if lbl.startswith("2022"):
                        expo = ex
                    cells.append(f"{lbl}: {fmt(st)}")
                name = f"{'한번에' if mode == 'B1' else '나눠서'} 매도-{T:g}%"
                print(f"  {name:16}(투자{expo:3.0f}%) " + " | ".join(cells))

    print("\n② 순환 포트폴리오 버전 (기울기 매수/매도 + 모멘텀 순 선택) — 2022~현재")
    for m in MARKETS:
        K = ROTATION_RULES[m]["slots"]
        p = lab.panel(m, "2022-01-01", "2099-12-31")
        b = stats(bnh(p, COST[m]), p["ppy"])
        print(f"\n[{m}] K={K}  단순보유 {fmt(b)}")
        for T in THRESHOLDS:
            for reg in ("--", "RGX@TL"):
                cfg = Cfg.parse(f"SLOPE|SLP{T:g}|{reg}")
                sim = simulate(p, cfg, K, COST[m])
                print(f"  매도-{T:g}% 지수필터 {'없음' if reg == '--' else '있음'}: {fmt(stats(sim['r'], p['ppy']))} (투자 {sim['expo']:.0f}%)")


if __name__ == "__main__":
    main()
