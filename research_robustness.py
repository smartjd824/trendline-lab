#!/usr/bin/env python3
"""
Strategy robustness check for MARKET_BEST_RULES (AUTO_BEST).

1) Execution sensitivity — same rule, three fill assumptions:
     A. close fill, 0.1%/side fee                     (current dashboard assumption)
     B. next-day open fill, 0.1%/side fee + 0.1% slip
     C. B + realistic KR costs (0.25%/side ≈ 수수료 + 매도 거래세 0.15~0.18% 분산)
2) Walk-forward / out-of-sample — pick the best (entry, exit) per market using ONLY data
   up to 2 years ago, then score every combo on the most recent 2 years that the selection never saw.
   If the configured MARKET_BEST_RULES rank poorly out-of-sample, the rule set is likely overfit.

Usage:  uv run python research_robustness.py [--oos-years 2]
"""

from __future__ import annotations

import argparse
from statistics import mean, median

import pandas as pd

from config import ASSETS, MARKET_BEST_RULES
from backend.backtester import build_indicator_map, run_backtest_single

MARKETS = ["KOSPI", "KOSDAQ", "US", "CRYPTO"]
ENTRIES = ["S1", "S2", "S3", "S4", "S5"]
EXITS = ["ma20_2d", "short_lower", "long_lower", "ma200_2d", "trailing_12", "dead_cross"]


def _summ(rows: list[dict]) -> dict:
    rows = [r for r in rows if "error" not in r]
    if not rows:
        return {"n": 0, "avg": 0.0, "med": 0.0, "bnh": 0.0, "mdd": 0.0, "beat": 0}
    return {
        "n": len(rows),
        "avg": mean(r["total_return_pct"] for r in rows),
        "med": median(r["total_return_pct"] for r in rows),
        "bnh": mean(r["bnh_return_pct"] for r in rows),
        "mdd": mean(r["mdd_pct"] for r in rows),
        "beat": sum(1 for r in rows if r["total_return_pct"] > r["bnh_return_pct"]),
    }


def _score(s: dict) -> float:
    # Median return (robust to one-off moonshots) + risk-adjusted mean
    return s["med"] + s["avg"] / max(abs(s["mdd"]), 10.0) * 10.0


def execution_sensitivity(ind_map: dict[str, pd.DataFrame], years: int) -> None:
    print(f"\n=== 1) 체결 가정 민감도 (최근 {years}년, MARKET_BEST_RULES) ===")
    print(f"{'시장':8} {'규칙':16} {'A 종가체결':>12} {'B 익일시가+슬립':>16} {'C B+국내실비용':>16} {'B&H':>9}")
    for mkt in MARKETS:
        rule = MARKET_BEST_RULES[mkt]
        syms = [a["symbol"] for a in ASSETS if a["market"] == mkt and a["symbol"] in ind_map]
        kr = mkt in ("KOSPI", "KOSDAQ")
        variants = {
            "A": dict(fill_mode="close", fee_rate=0.001, slippage_pct=0.0),
            "B": dict(fill_mode="next_open", fee_rate=0.001, slippage_pct=0.1),
            "C": dict(fill_mode="next_open", fee_rate=0.0025 if kr else 0.001, slippage_pct=0.1 if kr else 0.15),
        }
        out = {}
        for k, kw in variants.items():
            rows = [
                run_backtest_single(s, ind_map[s], strategy_id=rule["strategy_id"], exit_rule=rule["exit_rule"], years=years, **kw)
                for s in syms
            ]
            out[k] = _summ(rows)
        print(
            f"{mkt:8} {rule['label']:16} {out['A']['avg']:>+11.1f}% {out['B']['avg']:>+15.1f}% {out['C']['avg']:>+15.1f}% {out['A']['bnh']:>+8.1f}%"
        )


def walk_forward(ind_map: dict[str, pd.DataFrame], oos_years: int, is_years: int) -> None:
    print(f"\n=== 2) 워크포워드 검증: {is_years}년 학습구간에서 고른 규칙 → 최근 {oos_years}년(미사용 구간) 성과 ===")
    any_ind = next(iter(ind_map.values()))
    cutoff = any_ind["date_dt"].iloc[-1] - pd.DateOffset(years=oos_years)

    for mkt in MARKETS:
        syms = [a["symbol"] for a in ASSETS if a["market"] == mkt and a["symbol"] in ind_map]
        is_scores: dict[tuple[str, str], float] = {}
        oos_stats: dict[tuple[str, str], dict] = {}
        for sid in ENTRIES:
            for eid in EXITS:
                is_rows, oos_rows = [], []
                for s in syms:
                    ind = ind_map[s]
                    train = ind[ind["date_dt"] < cutoff].reset_index(drop=True)
                    if len(train) >= 260:
                        is_rows.append(run_backtest_single(s, train, strategy_id=sid, exit_rule=eid, years=is_years))
                    oos_rows.append(run_backtest_single(s, ind, strategy_id=sid, exit_rule=eid, years=oos_years))
                is_scores[(sid, eid)] = _score(_summ(is_rows))
                oos_stats[(sid, eid)] = _summ(oos_rows)

        is_rank = sorted(is_scores, key=is_scores.get, reverse=True)
        oos_rank = sorted(oos_stats, key=lambda k: _score(oos_stats[k]), reverse=True)
        picked = is_rank[0]
        cfg = (MARKET_BEST_RULES[mkt]["strategy_id"], MARKET_BEST_RULES[mkt]["exit_rule"])
        total = len(oos_rank)

        def _fmt(k: tuple[str, str]) -> str:
            st = oos_stats[k]
            return f"{k[0]}+{k[1]:<11} OOS순위 {oos_rank.index(k) + 1:>2}/{total} 평균 {st['avg']:+6.1f}% 중앙 {st['med']:+6.1f}% B&H초과 {st['beat']}/{st['n']}"

        print(f"\n[{mkt}] 최근 {oos_years}년 B&H 평균 {oos_stats[picked]['bnh']:+.1f}%")
        print(f"  학습구간 1위 규칙   : {_fmt(picked)}")
        print(f"  현재 설정 규칙      : {_fmt(cfg)}")
        print(f"  최근 {oos_years}년 실제 1위 : {_fmt(oos_rank[0])}")


def main() -> None:
    ap = argparse.ArgumentParser(description="MARKET_BEST_RULES 견고성(체결가정·워크포워드) 점검")
    ap.add_argument("--oos-years", type=int, default=2)
    ap.add_argument("--is-years", type=int, default=4)
    ap.add_argument("--sens-years", type=int, default=6)
    args = ap.parse_args()

    ind_map = build_indicator_map()
    print(f"Loaded {len(ind_map)} indicator frames")
    execution_sensitivity(ind_map, args.sens_years)
    walk_forward(ind_map, args.oos_years, args.is_years)


if __name__ == "__main__":
    main()
