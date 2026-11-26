#!/usr/bin/env python3
"""
거래대금 상위 종목 × 기울기 전략 검증 (2026-11-26)

A. 순환 포트폴리오: 신규 진입을 '그 시점' 최근 60일 거래대금 상위 N개로 제한 (N=10/20/30/50/전체)
   규칙: 기울기 (매수 20일선↑ & 200일선 평평·상승 / 매도 20일선 5일 -2%) ± 지수필터
   비교: 같은 시장 동일가중 단순보유, 현재 고정 규칙
B. '기울기가 먹히는 종목'이 지속되는가:
   2020-03~2023-12에 기울기(종목 단독)가 단순보유보다 샤프가 높았던 종목 → 2024~에도 계속 높았나?
   + 거래대금 순위와 기울기 우위의 관계 (앞/뒤 기간)

사용: uv run python liquidity_lab.py
"""

from __future__ import annotations


import numpy as np

from config import ASSET_MAP, ROTATION_RULES
from pullback_lab import sleeve_returns
from slope_lab import slope_signals, target_weights
from strategy_lab import COST, Cfg, Lab, bnh, simulate, stats

YEARS = (2022, 2023, 2024, 2025, 2026)


def yearly(lab, m, cfg, k, liq_top):
    rs, bs = [], []
    for y in YEARS:
        p = lab.panel(m, f"{y}-01-01", f"{y}-12-31")
        rs.append(simulate(p, cfg, k, COST[m], liq_top=liq_top)["r"])
        bs.append(bnh(p, COST[m]))
    ppy = 365 if m == "CRYPTO" else 252
    return stats(np.concatenate(rs), ppy), stats(np.concatenate(bs), ppy)


def fmt(s):
    return f"연{s['cagr']:+6.1f}% MDD{s['mdd']:4.0f}% 샤프{s['sharpe']:5.2f}"


def part_a(lab):
    print("A. 순환 포트폴리오 — 신규 진입을 그 시점 거래대금 상위 N개로 제한 (2022~2026 연도별 이어붙임)")
    for m in ("US", "CRYPTO", "KOSPI", "KOSDAQ"):
        cur = Cfg.parse(ROTATION_RULES[m]["rule"])
        K0 = ROTATION_RULES[m]["slots"]
        n_all = len(lab.by_mkt[m])
        a, b = yearly(lab, m, cur, K0, None)
        print(f"\n[{m}] 종목 {n_all}개 | 단순보유 {fmt(b)} | 현재 고정규칙({cur.label()}, {K0}칸) {fmt(a)}")
        for reg in ("--", "RGX@TL"):
            cfg = Cfg.parse(f"SLOPE|SLP2|{reg}")
            for n in (10, 20, 30, 50, None):
                if n and n >= n_all:
                    continue
                k = min(K0, n) if n else K0
                s, _ = yearly(lab, m, cfg, k, n)
                tag = f"상위 {n}개" if n else "전체"
                print(f"  기울기 지수필터{'O' if reg != '--' else 'X'} {tag:7}({k:2}칸): {fmt(s)}")


def per_stock_edge(lab, m, start, end):
    """종목 단독 기울기(한번에, 매도 -2%) 샤프 - 단순보유 샤프, 그리고 기간 평균 거래대금."""
    p = lab.panel(m, start, end)
    f = p["F"]
    w = target_weights(slope_signals(f, 2.0), "B1")
    r = sleeve_returns(f, w, COST[m])
    rb = sleeve_returns(f, np.ones_like(f.c), COST[m])
    out = {}
    for j, s in enumerate(p["syms"]):
        ok = np.isfinite(f.c[:, j])
        if ok.sum() < 200 or not np.isfinite(f.ma200[ok, j][0]):
            continue
        a, b = stats(r[ok, j], p["ppy"]), stats(rb[ok, j], p["ppy"])
        out[s] = (a["sharpe"] - b["sharpe"], a["mdd"] - b["mdd"], float(np.nanmedian(f.tv[:, j])))
    return out


def rank_corr(x, y):
    rx, ry = np.argsort(np.argsort(x)), np.argsort(np.argsort(y))
    return float(np.corrcoef(rx, ry)[0, 1])


def part_b(lab):
    print("\nB. '기울기가 먹히는 종목'이 다음 기간에도 먹히는가? (종목 단독, 샤프 기준)")
    for m in ("US", "CRYPTO", "KOSPI", "KOSDAQ"):
        e1 = per_stock_edge(lab, m, "2020-03-01", "2023-12-31")
        e2 = per_stock_edge(lab, m, "2024-01-01", "2099-12-31")
        common = [s for s in e1 if s in e2]
        if len(common) < 10:
            continue
        x = np.array([e1[s][0] for s in common])
        y = np.array([e2[s][0] for s in common])
        good = x > 0
        persist = rank_corr(x, y)
        liq1 = np.array([e1[s][2] for s in common])
        liq2 = np.array([e2[s][2] for s in common])
        print(f"\n[{m}] 종목 {len(common)}개")
        print(f"  앞 기간에 먹힌 종목 {good.sum()}개 → 뒤 기간에도 먹힌 비율 {np.mean(y[good] > 0) * 100:.0f}%"
              f" | 앞 기간에 안 먹힌 종목 → 뒤 기간 먹힌 비율 {np.mean(y[~good] > 0) * 100:.0f}%")
        print(f"  앞·뒤 기간 우위의 순위상관 {persist:+.2f} (0에 가까우면 '먹히는 종목'은 우연)")
        print(f"  거래대금 순위와 기울기 우위의 순위상관: 앞 {rank_corr(liq1, x):+.2f}, 뒤 {rank_corr(liq2, y):+.2f} (+면 거래대금 클수록 잘 먹힘)")
        top = sorted(common, key=lambda s: -liq2[common.index(s)])[:15]
        hit = np.mean([e2[s][0] > 0 for s in top]) * 100
        rest = np.mean([e2[s][0] > 0 for s in common if s not in top]) * 100
        print(f"  뒤 기간 거래대금 상위 15개 중 먹힌 비율 {hit:.0f}% vs 나머지 {rest:.0f}%")
        best = sorted(common, key=lambda s: -(e1[s][0] + e2[s][0]))[:6]
        print("  두 기간 모두 우위가 컸던 종목:", ", ".join(f"{ASSET_MAP[s]['name']}" for s in best if e1[s][0] > 0 and e2[s][0] > 0))


if __name__ == "__main__":
    lab = Lab()
    import sys
    if "b" not in sys.argv[1:]:
        part_a(lab)
    part_b(lab)
