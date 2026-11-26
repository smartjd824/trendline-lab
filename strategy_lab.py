#!/usr/bin/env python3
"""
Strategy Lab v2 — systematic search for an MA20/MA200 + Trendline (highs/lows) trend-reversal system
that beats Buy & Hold, under strict anti-overfitting discipline.

Building blocks (all causal, from backend.indicators — fitted strictly on bars < t):
  su / lu : short(45) / long(180) UPPER trendline through the HIGHS → break of a DESCENDING one = reversal up
  sl / ll : short / long LOWER trendline through the LOWS          → break = reversal down
  MA20 / MA50 / MA200 (+ MA200 slope), 120-day momentum
  Market regime = the market's own index run through the same MA200 / trendline logic.

Discipline
  * Signal on close t → fill at OPEN t+1. Per-market one-way cost (fee + tax + slippage).
  * Portfolio rotation: K equal slots; freed cash rotates into the strongest new signals (120d momentum).
  * Benchmark: equal-weight Buy & Hold of the same universe (same survivorship bias on both sides).
  * Walk-forward: for each test year Y, choose rules using ONLY data < Y, trade Y, stitch all test years.

Usage:
  uv run python strategy_lab.py asset        # per-asset timing vs per-asset B&H (in-sample)
  uv run python strategy_lab.py walk         # walk-forward 2022..now (the honest result)
  uv run python strategy_lab.py fixed CFG    # one config on every year, e.g. "REV_OR_TREND|MA20x3|RGX@TL"
"""

from __future__ import annotations

import itertools
import sys
import time
from dataclasses import dataclass, fields

import numpy as np
import pandas as pd

from config import ASSETS
from backend.backtester import build_indicator_map

COST = {"KOSPI": 0.0025, "KOSDAQ": 0.0025, "US": 0.0010, "CRYPTO": 0.0015}
MARKETS = ["KOSPI", "KOSDAQ", "US", "CRYPTO"]
REGIME_INDEX = {"KOSPI": "^KS11", "KOSDAQ": "^KQ11", "US": "^GSPC", "CRYPTO": "BTC-USD"}
KS = (10, 20)


# ----------------------------------------------------------------------------- helpers (1-D or 2-D, time on axis 0)
def shift(x: np.ndarray, k: int = 1) -> np.ndarray:
    out = np.full(x.shape, np.nan)
    out[k:] = x[:-k]
    return out


def cross_up(x: np.ndarray, line: np.ndarray) -> np.ndarray:
    with np.errstate(invalid="ignore"):
        return (x > line) & (shift(x) <= shift(line))


def below_n(x: np.ndarray, line: np.ndarray, n: int) -> np.ndarray:
    with np.errstate(invalid="ignore"):
        b = (x < line).astype(float)
    if n <= 1:
        return b > 0
    roll = (pd.DataFrame(b) if b.ndim == 2 else pd.Series(b)).rolling(n, min_periods=n).sum().to_numpy()
    return roll >= n


# ----------------------------------------------------------------------------- features
@dataclass
class F:
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray
    c: np.ndarray
    ma20: np.ndarray
    ma50: np.ndarray
    ma200: np.ndarray
    ma200_up: np.ndarray
    su: np.ndarray
    lu: np.ndarray
    sl: np.ndarray
    ll: np.ndarray
    su_s: np.ndarray
    lu_s: np.ndarray
    mom: np.ndarray
    tv: np.ndarray  # 최근 60일 거래대금 중앙값 (시점별, 미래정보 없음)
    ma200_chg: np.ndarray  # 200일선 10일 변화율(%)
    ma5: np.ndarray
    ma40: np.ndarray


def make_features(ind: pd.DataFrame, crypto: bool = False) -> tuple[np.ndarray, F]:
    c = ind["close"].to_numpy(float)
    cs = pd.Series(c)
    f = F(
        o=ind["open"].to_numpy(float),
        h=ind["high"].to_numpy(float),
        l=ind["low"].to_numpy(float),
        c=c,
        ma20=ind["ma20"].to_numpy(float),
        ma50=cs.rolling(50, min_periods=50).mean().to_numpy(),
        ma200=ind["ma200"].to_numpy(float),
        ma200_up=(ind["ma200_chg10_pct"].to_numpy(float) >= -0.15).astype(float),
        su=ind["short_upper"].to_numpy(float),
        lu=ind["long_upper"].to_numpy(float),
        sl=ind["short_lower"].to_numpy(float),
        ll=ind["long_lower"].to_numpy(float),
        su_s=ind["short_upper_slope"].to_numpy(float),
        lu_s=ind["long_upper_slope"].to_numpy(float),
        mom=(cs / cs.shift(120) - 1.0).to_numpy(),
        ma200_chg=ind["ma200_chg10_pct"].to_numpy(float),
        ma5=cs.rolling(5, min_periods=5).mean().to_numpy(),
        ma40=cs.rolling(40, min_periods=40).mean().to_numpy(),
        tv=(pd.Series(ind["volume"].to_numpy(float)) * (1.0 if crypto else cs)).rolling(60, min_periods=20).median().to_numpy(),
    )
    return ind["date"].to_numpy(str), f


# ----------------------------------------------------------------------------- strategy space
ENTRIES = ["REV_BULL", "REV_ANY", "REV_OR_X200", "REV_OR_TREND", "TREND", "GC_OR_REV", "PB_TREND_REV"]
EXITS = ["LL", "LL_AND_MA200", "SL_AND_MA20", "MA20x3", "MA50x2", "MA200x2", "DEAD", "LL_OR_DEAD", "HARD", "SLOW"]
# Market regime use:  --  none | RG  entry filter | RGX entry filter + liquidate all when regime turns off
REGIMES = ["--", "RG", "RGX"]
REGIME_DEFS = ["MA200", "TL"]  # how the index regime is defined (see regime_series)


@dataclass(frozen=True)
class Cfg:
    entry: str
    exit: str
    regime: str = "--"
    regime_def: str = "MA200"

    def label(self) -> str:
        return f"{self.entry}|{self.exit}|{self.regime}" + (f"@{self.regime_def}" if self.regime != "--" else "")

    @staticmethod
    def parse(s: str) -> "Cfg":
        parts = s.split("|")
        reg, rdef = (parts[2].split("@") + ["MA200"])[:2] if len(parts) > 2 else ("--", "MA200")
        return Cfg(parts[0], parts[1], reg, rdef)


def build_signals(f: F, cfg: Cfg, regime: np.ndarray | None) -> tuple[np.ndarray, np.ndarray]:
    c = f.c
    with np.errstate(invalid="ignore"):
        rev_s = cross_up(c, f.su) & (f.su_s < 0)  # break of descending short highs-line
        rev_l = cross_up(c, f.lu) & (f.lu_s < 0)  # break of descending long highs-line
        rev = rev_s | rev_l
        ma200_up = f.ma200_up > 0
        bull = (c > f.ma200) & ma200_up
        ma20_up = f.ma20 > shift(f.ma20, 3)
        trend_state = (c > f.ma20) & (f.ma20 > f.ma200) & ma200_up

        e = cfg.entry
        if e == "REV_BULL":  # reversal break only inside a rising-MA200 bull trend (current system core)
            ent = rev & bull & (c > f.ma20)
        elif e == "REV_ANY":  # reversal break anywhere (incl. below MA200 = early bottom), MA20 rising
            ent = rev & (c > f.ma20) & ma20_up
        elif e == "REV_OR_X200":  # reversal break or MA200 reclaim
            ent = (rev & (c > f.ma20)) | (cross_up(c, f.ma200) & ma20_up)
        elif e == "REV_OR_TREND":  # reversal break OR established uptrend (re-entry after shakeouts)
            ent = (rev & (c > f.ma20) & ma20_up) | trend_state
        elif e == "TREND":
            ent = trend_state
        elif e == "GC_OR_REV":  # golden cross or long highs-line break
            ent = cross_up(f.ma20, f.ma200) | (rev_l & (c > f.ma20))
        elif e == "SLOPE":  # 사용자 규칙: 20일선 기울기 상승(5일) & 200일선 평평/상승
            ent = (f.ma20 / shift(f.ma20, 5) - 1 > 0) & ma200_up
        elif e.startswith("ORD"):
            # 이평선 배열 + 20일선 상승 + 200일선 평평/상승
            #   ORD5_40_20 : 5일선 > 40일선 > 20일선 (눌림 후 단기 반등)   ORD5_20_40 : 5 > 20 > 40 (정배열)
            #   끝에 E    : 배열이 '처음 만들어진 날'만 매수 (없으면 배열 상태인 날 모두 매수 후보)
            up20s = (f.ma20 / shift(f.ma20, 5) - 1 > 0)
            body = e.rstrip("E")
            order = (f.ma5 > f.ma40) & (f.ma40 > f.ma20) if body == "ORD5_40_20" else (f.ma5 > f.ma20) & (f.ma20 > f.ma40)
            order = np.nan_to_num(order.astype(float)).astype(bool)
            if e.endswith("E"):
                order = order & ~(shift(order.astype(float), 1) > 0)
            ent = order & up20s & ma200_up
        elif e.startswith("SLOPE_T"):  # 200일선 허용 하한 변경: SLOPE_T0.5 = 10일 변화율 ≥ -0.5%, SLOPE_TNONE = 조건 없음
            tol = e[7:]
            m200 = np.ones(c.shape, bool) if tol == "NONE" else (f.ma200_chg >= -float(tol))
            ent = (f.ma20 / shift(f.ma20, 5) - 1 > 0) & m200 & np.isfinite(f.ma200)
        elif e == "PB_TREND_REV":  # pullback_lab V6/V7 re-entry: breakout | pullback bounce | trend state | bottom reversal
            t20 = f.l <= f.ma20 * 1.01
            tsl = f.l <= f.sl * 1.01
            t20 = t20 | (shift(t20.astype(float), 1) > 0) | (shift(t20.astype(float), 2) > 0)
            tsl = tsl | (shift(tsl.astype(float), 1) > 0) | (shift(tsl.astype(float), 2) > 0)
            pb = trend_state & (c > f.o) & ((t20 & (c > f.ma20)) | (tsl & (c > f.sl)))
            ent = (rev & bull & (c > f.ma20)) | pb | trend_state | (rev & (c > f.ma20) & ma20_up)
        else:
            raise ValueError(e)

        x = cfg.exit
        if x == "LL":
            ex = c < f.ll
        elif x == "LL_AND_MA200":
            ex = (c < f.ll) & (c < f.ma200)
        elif x == "SL_AND_MA20":
            ex = (c < f.sl) & (c < f.ma20)
        elif x == "MA20x3":
            ex = below_n(c, f.ma20, 3)
        elif x == "MA50x2":
            ex = below_n(c, f.ma50, 2)
        elif x == "MA200x2":
            ex = below_n(c, f.ma200, 2)
        elif x == "DEAD":
            ex = f.ma20 < f.ma200
        elif x == "LL_OR_DEAD":
            ex = (c < f.ll) | ((f.ma20 < f.ma200) & (c < f.ma20))
        elif x.startswith("SLP"):  # 사용자 규칙: 20일선 5일 변화율 < -T% 이면 매도
            ex = (f.ma20 / shift(f.ma20, 5) - 1) < -float(x[3:]) / 100.0
        elif x == "HARD":  # pullback_lab V5/V6: trend broken
            ex = below_n(c, f.ma200, 2) | ((c < f.ll) & (c < f.ma200))
        elif x == "SLOW":  # pullback_lab V7: both MA200 (2d) and long lows-line lost
            ex = below_n(c, f.ma200, 2) & (c < f.ll)
        else:
            raise ValueError(x)

    if cfg.regime != "--" and regime is not None:
        reg = regime if regime.ndim == ent.ndim else regime[:, None]
        ent = ent & reg
        if cfg.regime == "RGX":
            ex = ex | ~reg
    return np.nan_to_num(ent).astype(bool), np.nan_to_num(ex).astype(bool)


def regime_series(fi: F, kind: str) -> np.ndarray:
    """Index regime from the SAME building blocks applied to the market index."""
    with np.errstate(invalid="ignore"):
        if kind == "MA200":  # index above a flat/rising MA200
            return (fi.c > fi.ma200) & (fi.ma200_up > 0)
        if kind == "TL":
            # trendline state machine on the index: OFF when the long lows-line AND MA50 break,
            # back ON when a descending highs-line breaks or MA200 bull state returns
            off = (fi.c < fi.ll) & (fi.c < fi.ma50)
            on = cross_up(fi.c, fi.su) | cross_up(fi.c, fi.lu) | ((fi.c > fi.ma200) & (fi.ma200_up > 0) & (fi.c > fi.ma50))
            st = np.zeros(len(fi.c), bool)
            state = True
            for t in range(len(fi.c)):
                if state and off[t]:
                    state = False
                elif (not state) and on[t]:
                    state = True
                st[t] = state
            return st
    raise ValueError(kind)


# ----------------------------------------------------------------------------- data
class Lab:
    def __init__(self, ind_map: dict[str, pd.DataFrame] | None = None) -> None:
        ind_map = ind_map if ind_map is not None else build_indicator_map()
        self.feats: dict[str, tuple[np.ndarray, F]] = {s: make_features(ind, s.endswith("-USD")) for s, ind in ind_map.items()}
        self.by_mkt: dict[str, list[str]] = {m: [] for m in MARKETS}
        for a in ASSETS:
            if a["symbol"] in self.feats:
                self.by_mkt[a["market"]].append(a["symbol"])
        self._panels: dict[tuple, dict] = {}

    def panel(self, m: str, start: str, end: str) -> dict:
        """Calendar-aligned (T x N) feature panel for one market and window (+ index regimes)."""
        key = (m, start, end)
        if key in self._panels:
            return self._panels[key]
        syms = self.by_mkt[m]
        cal = np.array(sorted(set().union(*[set(d[(d >= start) & (d <= end)]) for d, _ in (self.feats[s] for s in syms)])))

        def align(d: np.ndarray, arr: np.ndarray) -> np.ndarray:
            return pd.Series(arr, index=d).reindex(cal).to_numpy(float)

        cols = {fl.name: np.column_stack([align(self.feats[s][0], getattr(self.feats[s][1], fl.name)) for s in syms]) for fl in fields(F)}
        fp = F(**cols)
        di, fi = self.feats[REGIME_INDEX[m]]
        regimes = {}
        for kind in REGIME_DEFS:
            r = pd.Series(regime_series(fi, kind).astype(float), index=di).reindex(cal).ffill().fillna(0).to_numpy() > 0
            regimes[kind] = r
        p = {"cal": cal, "syms": syms, "F": fp, "regimes": regimes, "ppy": 365 if m == "CRYPTO" else 252}
        self._panels[key] = p
        return p


# ----------------------------------------------------------------------------- portfolio simulation
def stats(r: np.ndarray, ppy: float) -> dict:
    eq = np.cumprod(1 + r)
    tot = eq[-1] - 1 if len(eq) else 0.0
    yrs = max(len(r) / ppy, 1e-9)
    cagr = (1 + tot) ** (1 / yrs) - 1 if tot > -1 else -1
    mdd = float(np.min(eq / np.maximum.accumulate(eq) - 1)) if len(eq) else 0.0
    sd = np.std(r)
    return {"ret": tot * 100, "cagr": cagr * 100, "mdd": mdd * 100, "sharpe": float(np.mean(r) / sd * np.sqrt(ppy)) if sd > 0 else 0.0}


def simulate(p: dict, cfg: Cfg, k: int, cost: float, return_state: bool = False, liquidate_end: bool = True, liq_top: int | None = None) -> dict:
    """K equal slots, signals at close → next-open fills, entries ranked by 120d momentum. Returns daily returns."""
    fp: F = p["F"]
    ENT, EX = build_signals(fp, cfg, p["regimes"][cfg.regime_def])
    O, C, MOM = fp.o, fp.c, fp.mom
    T, N = C.shape
    if liq_top:  # 신규 진입은 '그 시점' 거래대금 상위 liq_top 종목으로 제한
        tvm = np.where(np.isfinite(fp.tv), fp.tv, -np.inf)
        rank = (-tvm).argsort(axis=1).argsort(axis=1)
        ENT = ENT & (rank < liq_top) & np.isfinite(fp.tv)
    Cf = pd.DataFrame(C).ffill().to_numpy()
    Of = np.where(np.isfinite(O), O, Cf)
    cash, sh = 1.0, np.zeros(N)
    held = np.zeros(N, bool)
    buy_q = np.zeros(N, bool)
    sell_q = np.zeros(N, bool)
    eq = np.empty(T)
    expo = np.empty(T)
    trades = 0
    ent_idx = np.full(N, -1)
    ent_px = np.zeros(N)
    log: list[tuple[int, int, str, float]] = []  # (t, j, BUY/SELL, price)
    for t in range(T):
        live = np.isfinite(O[t])
        sq = sell_q & held & live
        if sq.any():
            cash += float(np.sum(sh[sq] * O[t, sq])) * (1 - cost)
            if return_state:
                log.extend((t, int(j), "SELL", float(O[t, j])) for j in np.flatnonzero(sq))
            sh[sq] = 0
            held[sq] = False
        bq = np.flatnonzero(buy_q & ~held & live)
        if len(bq):
            alloc = (cash + float(np.nansum(sh[held] * Of[t, held]))) / k
            for j in bq:
                if held.sum() >= k or cash <= 1e-12:
                    break
                a = min(alloc, cash)
                sh[j] = a * (1 - cost) / O[t, j]
                cash -= a
                held[j] = True
                trades += 1
                ent_idx[j], ent_px[j] = t, O[t, j]
                if return_state:
                    log.append((t, int(j), "BUY", float(O[t, j])))
        buy_q[:] = False
        val_pos = float(np.nansum(sh[held] * Cf[t, held]))
        eq[t] = cash + val_pos
        expo[t] = val_pos / eq[t] if eq[t] > 0 else 0
        ok = np.isfinite(C[t])
        sell_q = held & ok & EX[t]
        free = k - int(held.sum() - sell_q.sum())
        if free > 0:
            cand = np.flatnonzero(ENT[t] & ~held & ok & ~EX[t])
            if len(cand):
                key = np.nan_to_num(MOM[t, cand], nan=-9.0)
                buy_q[cand[np.argsort(-key)[:free]]] = True
    # liquidation value at window end (pay exit cost) so every test year is self-contained
    if liquidate_end:
        eq[-1] = cash + float(np.nansum(sh[held] * Cf[-1, held])) * (1 - cost)
    r = np.r_[eq[0] - 1.0, eq[1:] / eq[:-1] - 1]
    out = {"r": r, "trades": trades, "expo": float(np.mean(expo)) * 100}
    if return_state:
        val = eq[-1]
        out["state"] = {
            "equity": eq,
            "cash_weight": float(cash / val) if val > 0 else 1.0,
            "held": [(int(j), int(ent_idx[j]), float(ent_px[j]), float(sh[j] * Cf[-1, j] / val)) for j in np.flatnonzero(held)],
            "sell_next_open": [int(j) for j in np.flatnonzero(sell_q)],
            "buy_next_open": [int(j) for j in np.flatnonzero(buy_q)],
            "log": log,
        }
    return out


def bnh(p: dict, cost: float) -> np.ndarray:
    """Equal-weight B&H of the universe, bought at each name's first open in the window, sold at window end."""
    fp: F = p["F"]
    O, C = fp.o, fp.c
    Cf = pd.DataFrame(C).ffill().to_numpy()
    curves = []
    for j in range(C.shape[1]):
        fin = np.flatnonzero(np.isfinite(O[:, j]))
        if len(fin) == 0 or fin[0] > 5:  # only names already trading at window start
            continue
        cur = Cf[:, j] / O[fin[0], j] * (1 - cost)
        cur[: fin[0]] = 1.0
        curves.append(cur)
    eq = np.mean(curves, axis=0)
    eq[-1] *= 1 - cost
    return np.r_[eq[0] - 1.0, eq[1:] / eq[:-1] - 1]


# ----------------------------------------------------------------------------- selection & walk-forward
GRID = [Cfg(e, x, r, d) for e, x, r, d in itertools.product(ENTRIES, EXITS, REGIMES, REGIME_DEFS) if not (r == "--" and d != "MA200")]


def robust_score(lab: Lab, m: str, cfg: Cfg, start: str, end: str) -> tuple[float, bool]:
    """Mean Sharpe over K; eligible only if CAGR > EW-B&H CAGR for every K."""
    p = lab.panel(m, start, end)
    bh = stats(bnh(p, COST[m]), p["ppy"])
    res = [stats(simulate(p, cfg, k, COST[m])["r"], p["ppy"]) for k in KS]
    return float(np.mean([r["sharpe"] for r in res])), all(r["cagr"] > bh["cagr"] for r in res)


def pick(lab: Lab, m: str, train_start: str, train_end: str) -> Cfg:
    scored = [(cfg, *robust_score(lab, m, cfg, train_start, train_end)) for cfg in GRID]
    elig = [s for s in scored if s[2]] or scored
    return max(elig, key=lambda s: s[1])[0]


def walk_forward(lab: Lab, test_years=(2022, 2023, 2024, 2025, 2026), train_start="2020-01-01", fixed: dict[str, Cfg] | None = None) -> dict:
    print("Walk-forward: each test year uses rules chosen ONLY on data before it (expanding window)." if not fixed else "Fixed config, evaluated year by year.")
    print(f"Grid {len(GRID)} configs x K{KS}; fills next open; costs {COST}\n")
    summary = {}
    for m in MARKETS:
        rows, strat_r, bh_r = [], {k: [] for k in KS}, []
        ppy = 365 if m == "CRYPTO" else 252
        for y in test_years:
            cfg = fixed[m] if fixed else pick(lab, m, train_start, f"{y - 1}-12-31")
            p = lab.panel(m, f"{y}-01-01", f"{y}-12-31")
            b = bnh(p, COST[m])
            bh_r.append(b)
            line = f"  {y} {cfg.label():30}"
            for k in KS:
                sim = simulate(p, cfg, k, COST[m])
                strat_r[k].append(sim["r"])
                st = stats(sim["r"], ppy)
                line += f" K{k}: {st['ret']:+6.1f}% (MDD {st['mdd']:4.0f}%, 투자 {sim['expo']:3.0f}%)"
            bs = stats(b, ppy)
            rows.append(line + f" | B&H {bs['ret']:+6.1f}% (MDD {bs['mdd']:4.0f}%)")
        print(f"[{m}]")
        print("\n".join(rows))
        tot = {k: stats(np.concatenate(strat_r[k]), ppy) for k in KS}
        tb = stats(np.concatenate(bh_r), ppy)
        out = "  ⇒ 누적 " + " ".join(f"K{k}: {tot[k]['ret']:+.0f}% CAGR {tot[k]['cagr']:+.1f}% MDD {tot[k]['mdd']:.0f}% Sharpe {tot[k]['sharpe']:.2f} |" for k in KS)
        print(out + f" B&H: {tb['ret']:+.0f}% CAGR {tb['cagr']:+.1f}% MDD {tb['mdd']:.0f}% Sharpe {tb['sharpe']:.2f}\n", flush=True)
        summary[m] = (tot, tb)
    return summary


def per_asset(lab: Lab, start="2020-01-01", end="2024-06-30") -> None:
    """Single-asset timing vs that asset's own B&H (shows why rotation is needed)."""
    for m in MARKETS:
        p = lab.panel(m, start, end)
        out = []
        for cfg in [Cfg(e, x) for e, x in itertools.product(ENTRIES, EXITS)]:
            beat = []
            for j in range(len(p["syms"])):
                sub = {**p, "F": F(**{fl.name: getattr(p["F"], fl.name)[:, j : j + 1] for fl in fields(F)})}
                s = stats(simulate(sub, cfg, 1, COST[m])["r"], p["ppy"])
                b = stats(bnh(sub, COST[m]), p["ppy"])
                beat.append(s["ret"] > b["ret"])
            out.append((np.mean(beat) * 100, cfg.label()))
        out.sort(reverse=True)
        print(f"[{m}] 종목별 단독 타이밍이 그 종목 B&H를 이긴 비율 — 최고 {out[0][0]:.0f}% ({out[0][1]}), 중앙 {np.median([o[0] for o in out]):.0f}%")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "walk"
    t0 = time.time()
    lab = Lab()
    if mode == "asset":
        per_asset(lab)
    elif mode == "walk":
        walk_forward(lab)
    elif mode == "fixed":
        cfg = Cfg.parse(sys.argv[2])
        walk_forward(lab, fixed={m: cfg for m in MARKETS})
    print(f"({time.time() - t0:.0f}s)")
