"""선물 1시간봉 규칙 엔진.

연구(선물_분봉/research)로 정한 규칙:
  매수  : 20일선 기울기(3봉 변화/ATR) 상승 전환 + 종가 > 200일선 + 200일선 10봉 변화 ≥ 0 + RSI ≥ 50
          → 신호 봉 다음 봉 시가 매수, 처음 손절 = 1.5 × ATR
  매도  : 금·나스닥 = 2계약 반반 → 기울기 꺾이면 절반, 종가 200일선 아래면 나머지
          크루드 오일 = 기울기 꺾이면 전부
  공통  : 신호는 '완성된 봉'으로만 판단, 월물 교체 가격 틈 보정, 비용(미끄러짐 1틱씩 + 손절 1틱 + 왕복 수수료)
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yfinance as yf

logging.getLogger("yfinance").setLevel(logging.CRITICAL)

SLIP = 1.0
STOP_SLIP = 1.0
KST_OFFSET = 9 * 3600

FUTURES: list[dict[str, Any]] = [
    dict(symbol="NQ=F", code="NQ", micro="MNQ", name="나스닥 100", icon="📈", tick=0.25, tick_value=5.0,
         micro_tick_value=0.5, comm_std=4.5, comm_micro=1.3, decimals=2, root="NQ", suffix=".CME",
         months=[3, 6, 9, 12], exit_mode="half"),
    dict(symbol="GC=F", code="GC", micro="MGC", name="금", icon="🥇", tick=0.1, tick_value=10.0,
         micro_tick_value=1.0, comm_std=5.0, comm_micro=1.5, decimals=1, root="GC", suffix=".CMX",
         months=[2, 4, 6, 8, 10, 12], exit_mode="half"),
    dict(symbol="CL=F", code="CL", micro="MCL", name="크루드 오일", icon="🛢️", tick=0.01, tick_value=10.0,
         micro_tick_value=1.0, comm_std=5.0, comm_micro=1.5, decimals=2, root="CL", suffix=".NYM",
         months=list(range(1, 13)), exit_mode="all"),
]
SPEC = {f["symbol"]: f for f in FUTURES}
MONTH_CODES = "FGHJKMNQUVXZ"


# ------------------------------------------------------------------ 시세
def yahoo_history(ticker: str, period: str, interval: str) -> pd.DataFrame:
    try:
        raw = yf.Ticker(ticker).history(period=period, interval=interval, auto_adjust=False, actions=False)
    except Exception:
        return pd.DataFrame()
    if raw is None or raw.empty:
        return pd.DataFrame()
    df = raw.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]].dropna(subset=["open", "high", "low", "close"])
    df = df[(df["close"] > 0) & (df["open"] > 0)]
    idx = pd.DatetimeIndex(df.index)
    idx = idx.tz_localize("UTC") if idx.tz is None else idx.tz_convert("UTC")
    out = pd.DataFrame({"ts_utc": idx.as_unit("s").asi8.astype(np.int64),
                        **{c: df[c].to_numpy(float) for c in ("open", "high", "low", "close")},
                        "volume": df["volume"].fillna(0).to_numpy(float)})
    return out.drop_duplicates("ts_utc", keep="last").sort_values("ts_utc").reset_index(drop=True)


def merge_store(path: Path, fresh: pd.DataFrame, limit: int = 20000) -> pd.DataFrame:
    path.parent.mkdir(parents=True, exist_ok=True)
    old = pd.read_csv(path) if path.exists() else pd.DataFrame()
    if fresh is None or fresh.empty:
        return old
    both = pd.concat([old, fresh], ignore_index=True) if not old.empty else fresh
    both = both.drop_duplicates("ts_utc", keep="last").sort_values("ts_utc").reset_index(drop=True).iloc[-limit:]
    both.to_csv(path, index=False)
    return both


# ------------------------------------------------------------------ 월물 교체 보정
def _contracts(spec: dict, today: dt.date) -> list[str]:
    out = []
    for k in range(-3, 7):
        m0 = today.month - 1 + k
        y, m = today.year + m0 // 12, m0 % 12 + 1
        if m in spec["months"]:
            out.append(f"{spec['root']}{MONTH_CODES[m - 1]}{y % 100:02d}{spec['suffix']}")
    return out


def _third_friday(y: int, m: int) -> dt.date:
    d = dt.date(y, m, 15)
    return d + dt.timedelta((4 - d.weekday()) % 7)


def _in_roll_window(root: str, d: dt.date) -> bool:
    if root == "NQ":
        if d.month not in (3, 6, 9, 12):
            return False
        f = _third_friday(d.year, d.month)
        return f - dt.timedelta(9) <= d <= f + dt.timedelta(1)
    if root == "CL":
        return 14 <= d.day <= 26
    if root == "GC":
        if d.month not in (1, 3, 5, 7, 9, 11):
            return False
        last = dt.date(d.year + (d.month == 12), d.month % 12 + 1, 1) - dt.timedelta(1)
        return last - dt.timedelta(9) <= d <= last
    return False


def detect_rolls(spec: dict, f60: pd.DataFrame, store: Path, prev_events: list[dict]) -> list[dict]:
    """정확한 감지(개별 월물과 가격 대조) + 오래된 구간은 추정(교체 시기 + 4ATR 이상 틈, 주말 제외)."""
    cols = {}
    for tk in _contracts(spec, dt.date.today()):
        st = merge_store(store / "contracts" / f"{tk.replace('.', '_')}_60m.csv", yahoo_history(tk, "60d", "60m"))
        if not st.empty:
            cols[tk] = st.set_index("ts_utc")["close"]
    for p in (store / "contracts").glob(f"{spec['root']}*_60m.csv"):
        tk = p.stem.replace("_60m", "").replace("_", ".")
        if tk not in cols:
            try:
                cols[tk] = pd.read_csv(p).set_index("ts_utc")["close"]
            except Exception:
                pass
    exact, cov = [], None
    if cols:
        f = f60.set_index("ts_utc")["close"]
        M = pd.DataFrame(cols).reindex(f.index)
        diff = M.sub(f, axis=0).abs().div(f, axis=0).dropna(how="all")
        if not diff.empty:
            best = diff.idxmin(axis=1)[diff.min(axis=1) <= 0.0003]
            if not best.empty:
                cov = int(best.index[0])
                lab, ts = best.to_numpy(), best.index.to_numpy()
                for i in range(1, len(lab)):
                    a, b = lab[i - 1], lab[i]
                    if a == b or not all(lab[j] == b for j in range(i, min(i + 3, len(lab)))):
                        continue
                    tp = int(ts[i - 1])
                    pa, pb = M.at[tp, a], M.at[tp, b]
                    if np.isfinite(pa) and np.isfinite(pb):
                        exact.append(dict(ts_utc=int(ts[i]), spread=float(pb - pa), method="exact", src=f"{a}→{b}"))
    keep = {e["ts_utc"]: e for e in prev_events if e.get("method") == "exact"}
    for e in exact:
        if not any(abs(e["ts_utc"] - t) < 6 * 3600 for t in keep):
            keep[e["ts_utc"]] = e
    exact_all = sorted(keep.values(), key=lambda e: e["ts_utc"])
    starts = ([cov] if cov else []) + [e["ts_utc"] for e in exact_all]
    bound = min(starts) if starts else None
    df = f60 if bound is None else f60[f60["ts_utc"] < bound]
    est = []
    if len(df) > 30:
        o, c = df["open"].to_numpy(), df["close"].to_numpy()
        rng = pd.Series(df["high"].to_numpy() - df["low"].to_numpy()).rolling(14).mean().to_numpy()
        ts = df["ts_utc"].to_numpy()
        et = pd.to_datetime(ts, unit="s", utc=True).tz_convert("America/New_York")
        cand: dict[str, tuple[float, int]] = {}
        for i in range(15, len(df)):
            if not np.isfinite(rng[i - 1]) or rng[i - 1] <= 0 or ts[i] - ts[i - 1] >= 86400:
                continue
            rel = abs(o[i] - c[i - 1]) / rng[i - 1]
            d = et[i].date()
            if rel >= 4 and _in_roll_window(spec["root"], d):
                k = f"{d.year}-{d.month}"
                if k not in cand or rel > cand[k][0]:
                    cand[k] = (rel, i)
        est = [dict(ts_utc=int(ts[i]), spread=float(o[i] - c[i - 1]), method="estimate", src="") for _, i in cand.values()]
    return sorted(exact_all + est, key=lambda e: e["ts_utc"])


def apply_rolls(raw: pd.DataFrame, events: list[dict]) -> tuple[pd.DataFrame, list[dict]]:
    if raw.empty or not events:
        return raw, []
    df = raw.copy()
    ts, o, c = df["ts_utc"].to_numpy(), df["open"].to_numpy(), df["close"].to_numpy()
    shift = np.zeros(len(df))
    applied = []
    for e in events:
        t = e["ts_utc"]
        if t <= ts[0] or t > ts[-1] + 3600:
            continue
        win = np.where((ts >= t - 3600) & (ts <= t + 3600))[0]
        win = win[win > 0]
        if win.size:
            k = int(win[np.argmax(np.abs(o[win] - c[win - 1]))])
        else:
            after = np.where(ts >= t)[0]
            if not after.size:
                continue
            k = int(after[0])
        shift[:k] += e["spread"]
        applied.append(e)
    for col in ("open", "high", "low", "close"):
        df[col] = df[col].to_numpy() + shift
    if (df[["open", "high", "low", "close"]] <= 0).any().any():
        return raw, []
    return df, applied


# ------------------------------------------------------------------ 지표
def indicators(df: pd.DataFrame, seconds: int) -> pd.DataFrame:
    out = df.copy().reset_index(drop=True)
    c = out["close"]
    for w in (20, 60, 200):
        out[f"ma{w}"] = c.rolling(w, min_periods=w).mean()
    pc = c.shift(1)
    tr = pd.concat([out["high"] - out["low"], (out["high"] - pc).abs(), (out["low"] - pc).abs()], axis=1).max(axis=1)
    out["atr"] = tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    d = c.diff()
    g = d.clip(lower=0).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    l_ = (-d).clip(lower=0).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    out["rsi"] = np.where(l_ > 0, 100 - 100 / (1 + g / l_.replace(0, np.nan)), np.where(g > 0, 100.0, 50.0))
    out.loc[:13, "rsi"] = np.nan
    out["s20"] = (out["ma20"] - out["ma20"].shift(3)) / out["atr"]
    out["m200chg"] = (out["ma200"] / out["ma200"].shift(10) - 1) * 100
    et = pd.to_datetime(out["ts_utc"], unit="s", utc=True).dt.tz_convert("America/New_York")
    out["session"] = (et + pd.Timedelta(hours=6)).dt.strftime("%Y-%m-%d")   # CME 거래일 (뉴욕 18시 시작)
    out["time_kst"] = pd.to_datetime(out["ts_utc"] + KST_OFFSET, unit="s").dt.strftime("%m-%d %H:%M")
    out["complete"] = (out["ts_utc"] + seconds) <= time.time()
    return out


def fit_line(vals: np.ndarray, end_excl: int, window: int, kind: str):
    """직전 window봉 바깥 접선 (현재 봉 제외). (p1, p2, 기울기, 현재 봉 위치 값)"""
    start = max(0, end_excl - window)
    eff = end_excl - start
    min_span = max(6, int(eff * 0.15))
    if eff <= min_span + 2:
        return None
    seg = vals[start:end_excl - min_span]
    if seg.size == 0:
        return None
    p1 = start + int(np.argmax(seg) if kind == "upper" else np.argmin(seg))
    rs = p1 + min_span
    if rs >= end_excl:
        return None
    dx = np.arange(min_span, end_excl - p1, dtype=float)
    slopes = (vals[rs:end_excl] - vals[p1]) / dx
    k = int(np.argmax(slopes) if kind == "upper" else np.argmin(slopes))
    slope = float(slopes[k])
    return p1, rs + k, slope, float(vals[p1] + slope * (end_excl - p1))


# ------------------------------------------------------------------ 규칙 실행 (과거 전체를 다시 계산 → 현재 상태·사건)
def run_rules(df: pd.DataFrame, spec: dict) -> dict[str, Any]:
    d = df[df["complete"]].reset_index(drop=True)
    o, h, l, c = (d[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    ma200, atr, s20, rsi, m200 = (d[k].to_numpy(float) for k in ("ma200", "atr", "s20", "rsi", "m200chg"))
    ts = d["ts_utc"].to_numpy(np.int64)
    s20p = np.r_[np.nan, s20[:-1]]
    ok = np.isfinite(ma200) & np.isfinite(s20) & np.isfinite(s20p) & np.isfinite(rsi) & np.isfinite(m200)
    buy = ok & (s20p <= 0) & (s20 > 0) & (c > ma200) & (m200 >= 0) & (rsi >= 50)
    cp = np.r_[np.nan, c[:-1]]
    NEAR = 0.05
    # 임박 조건 (보유 상태에 따라 하나만 사용)
    near_buy = ok & (c > ma200) & (m200 >= 0) & (s20 < 0) & (s20 > -NEAR) & (s20 > s20p) & (rsi >= 45)
    near_sell = ok & (s20 > 0) & (s20 < NEAR) & (s20 < s20p)
    near_rest = ok & (c > ma200) & ((c - ma200) < 0.5 * atr) & (c < cp)
    was_near = {"BUY_NEAR": False, "SELL_NEAR": False, "REST_NEAR": False}
    half = spec["exit_mode"] == "half"
    tick, tv, mtv = spec["tick"], spec["tick_value"], spec["micro_tick_value"]
    n = len(c)
    events: list[dict] = []
    trades: list[dict] = []
    pos = None   # dict(units=[...], entry, stop, risk, ei)

    def ev(i, kind, text, price):
        events.append(dict(ts=int(ts[i]), bar_kst=d["time_kst"].iat[i], kind=kind, text=text,
                           price=round(float(price), spec["decimals"])))

    def close_unit(u, px, stop_hit, j):
        slip = 2 * SLIP + (STOP_SLIP if stop_hit else 0)
        ticks = (px - pos["entry"]) / tick - slip
        u.update(open=False, exit=px, exit_ts=int(ts[j]),
                 r=(ticks * tv - spec["comm_std"]) / (pos["risk"] / tick * tv),
                 micro=ticks * mtv - spec["comm_micro"])

    i = 205
    pending_buy = None
    while i < n:
        if pos is None:
            if pending_buy is not None:
                sig_i = pending_buy
                pending_buy = None
                risk = max((atr[sig_i] if np.isfinite(atr[sig_i]) else o[i] * 0.01) * 1.5, tick * 5)
                units = [dict(name="A", open=True), dict(name="B", open=True)] if half else [dict(name="A", open=True)]
                pos = dict(units=units, entry=o[i], stop=o[i] - risk, risk=risk, ei=i, entry_ts=int(ts[i]), exits={})
                was_near.update(SELL_NEAR=False, REST_NEAR=False)
            elif buy[i]:
                pending_buy = i
                ev(i, "BUY", "20일선 기울기 상승 전환 (200일선 위·상승, RSI ≥ 50) → 다음 봉 시가 매수", c[i])
                was_near.update(BUY_NEAR=False)
                i += 1
                continue
            else:
                if near_buy[i] and not was_near["BUY_NEAR"]:
                    ev(i, "BUY_NEAR", f"20일선 기울기({s20[i]:+.3f})가 0 바로 아래에서 올라오는 중 → 0을 넘으면 매수 신호", c[i])
                was_near["BUY_NEAR"] = bool(near_buy[i])
                i += 1
                continue
        # 보유 중
        p = pos
        if p.get("pending_exit"):
            for u in p["units"]:
                if u["open"] and u["name"] in p["pending_exit"]:
                    close_unit(u, o[i], False, i)
            p["pending_exit"] = None
        stop_hit = False
        if any(u["open"] for u in p["units"]):
            if i > p["ei"] and o[i] <= p["stop"]:
                px, stop_hit = o[i], True
            elif l[i] <= p["stop"]:
                px, stop_hit = p["stop"], True
            if stop_hit:
                for u in p["units"]:
                    if u["open"]:
                        close_unit(u, px, True, i)
                ev(i, "STOP", f"손절선({p['stop']:.{spec['decimals']}f}) 도달 → 남은 물량 정리", px)
        if any(u["open"] for u in p["units"]) and i + 1 <= n:
            want = []
            uA = p["units"][0]
            if uA["open"] and s20[i] < 0:
                want.append("A")
                ev(i, "HALF" if half else "SELL_ALL",
                   "20일선 기울기 꺾임 → 다음 봉 시가 " + ("절반 매도" if half else "전부 매도"), c[i])
            if half and p["units"][1]["open"] and c[i] < ma200[i]:
                want.append("B")
                ev(i, "SELL_REST", "종가가 200일선 아래 → 다음 봉 시가 나머지 매도", c[i])
            if want:
                p["pending_exit"] = want
            else:
                # 매도 임박
                if uA["open"]:
                    if near_sell[i] and not was_near["SELL_NEAR"]:
                        ev(i, "SELL_NEAR", f"20일선 기울기({s20[i]:+.3f})가 0 바로 위에서 내려가는 중 → 0 아래로 꺾이면 " + ("절반 매도" if half else "전부 매도"), c[i])
                    was_near["SELL_NEAR"] = bool(near_sell[i])
                elif half and p["units"][1]["open"]:
                    if near_rest[i] and not was_near["REST_NEAR"]:
                        ev(i, "REST_NEAR", f"가격이 200일선({ma200[i]:.{spec['decimals']}f}) 바로 위까지 내려옴 → 종가가 아래로 마감하면 나머지 매도", c[i])
                    was_near["REST_NEAR"] = bool(near_rest[i])
        if not any(u["open"] for u in p["units"]):
            was_near.update(SELL_NEAR=False, REST_NEAR=False, BUY_NEAR=False)
            trades.append(dict(entry_ts=p["entry_ts"], entry=p["entry"],
                               r=float(np.mean([u["r"] for u in p["units"]])),
                               micro=float(np.mean([u["micro"] for u in p["units"]])) * (2 if half else 1),
                               exit_ts=max(u["exit_ts"] for u in p["units"])))
            pos = None
            # 정리한 그 봉에서 바로 새 매수 신호도 확인
            if buy[i]:
                pending_buy = i
                ev(i, "BUY", "20일선 기울기 상승 전환 (200일선 위·상승, RSI ≥ 50) → 다음 봉 시가 매수", c[i])
        i += 1

    last = n - 1
    state: dict[str, Any] = dict(status="없음")
    live_close = float(df["close"].iat[-1])
    if pending_buy is not None and pos is None:
        state = dict(status="매수 신호", note="다음 봉 시가 매수 예정", ref=round(c[pending_buy], spec["decimals"]),
                     stop=round(c[pending_buy] - max(atr[pending_buy] * 1.5, tick * 5), spec["decimals"]))
    elif pos is not None:
        open_units = [u for u in pos["units"] if u["open"]]
        qty = len(open_units)
        r_now = (live_close - pos["entry"]) / pos["risk"]
        state = dict(status=("보유 (2계약)" if qty == 2 else "절반 보유" if half else "보유"),
                     entry=round(pos["entry"], spec["decimals"]), entry_kst=d["time_kst"].iat[pos["ei"]],
                     stop=round(pos["stop"], spec["decimals"]), r_now=round(r_now, 2),
                     micro_now=round((live_close - pos["entry"]) / tick * mtv * qty, 1),
                     pending=pos.get("pending_exit"))
    state.update(s20=round(float(s20[last]), 3) if np.isfinite(s20[last]) else None,
                 above200=bool(c[last] > ma200[last]) if np.isfinite(ma200[last]) else None,
                 dist200_pct=round((c[last] / ma200[last] - 1) * 100, 2) if np.isfinite(ma200[last]) else None,
                 rsi=round(float(rsi[last]), 1) if np.isfinite(rsi[last]) else None,
                 signal_bar_kst=d["time_kst"].iat[last])
    return dict(events=events, trades=trades, state=state)


def bt_summary(trades: list[dict]) -> dict[str, Any]:
    if not trades:
        return dict(n=0)
    r = np.array([t["r"] for t in trades]); u = np.array([t["micro"] for t in trades])
    cum = np.cumsum(u)
    return dict(n=len(r), win=round(float((u > 0).mean() * 100), 1), avg_r=round(float(r.mean()), 3),
                micro_total=round(float(u.sum())), micro_mdd=round(float(np.max(np.maximum.accumulate(np.r_[0, cum]) - np.r_[0, cum]))),
                since=pd.to_datetime(trades[0]["entry_ts"] + KST_OFFSET, unit="s").strftime("%Y-%m-%d"))


# ------------------------------------------------------------------ 차트 자료
def chart_payload(df: pd.DataFrame, events: list[dict], bars: int, dec: int) -> dict[str, Any]:
    v = df.iloc[-bars:].reset_index(drop=True)
    t = (v["ts_utc"] + KST_OFFSET).astype(int).tolist()
    rnd = lambda x: None if not np.isfinite(x) else round(float(x), dec + 1)  # noqa: E731
    out = dict(candles=[dict(time=t[i], open=rnd(v["open"][i]), high=rnd(v["high"][i]), low=rnd(v["low"][i]), close=rnd(v["close"][i]))
                        for i in range(len(v))])
    for w in (20, 60, 200):
        arr = v[f"ma{w}"].to_numpy(float)
        out[f"ma{w}"] = [dict(time=t[i], value=rnd(arr[i])) for i in range(len(v)) if np.isfinite(arr[i])]
    # 현재 추세선 (단기 20봉 · 장기 150봉)
    full_h, full_l = df["high"].to_numpy(float), df["low"].to_numpy(float)
    n = len(df)
    lines = []
    for label, w in (("단기", 20), ("장기", 150)):
        for kind, vals, color in (("upper", full_h, "#ff9800" if w == 20 else "#2979ff"), ("lower", full_l, "#ba68c8" if w == 20 else "#00e676")):
            r = fit_line(vals, n, w, kind)
            if not r:
                continue
            p1, _, slope, _ = r
            if n - p1 > bars:
                continue
            ts_all = (df["ts_utc"] + KST_OFFSET).astype(int).to_numpy()
            lines.append(dict(label=f"{label} {'상단' if kind == 'upper' else '하단'}", color=color,
                              points=[dict(time=int(ts_all[p1]), value=rnd(vals[p1])),
                                      dict(time=int(ts_all[-1]), value=rnd(vals[p1] + slope * (n - 1 - p1)))]))
    out["trendlines"] = lines
    t0 = t[0]
    mk = {"BUY": ("belowBar", "#00e676", "arrowUp", "매수"), "HALF": ("aboveBar", "#ffd54f", "arrowDown", "절반"),
          "SELL_ALL": ("aboveBar", "#ffd54f", "arrowDown", "매도"), "SELL_REST": ("aboveBar", "#ff5252", "arrowDown", "나머지"),
          "STOP": ("aboveBar", "#ff1744", "square", "손절")}
    out["markers"] = [dict(time=e["ts"] + KST_OFFSET, position=mk[e["kind"]][0], color=mk[e["kind"]][1], shape=mk[e["kind"]][2],
                           text=mk[e["kind"]][3]) for e in events if e["ts"] + KST_OFFSET >= t0 and e["kind"] in mk]
    return out


def analyze_symbol(spec: dict, store: Path, prev_rolls: list[dict]) -> tuple[dict, dict, list[dict], list[dict]]:
    sym = spec["symbol"]
    safe = sym.replace("=", "_")
    raw60 = merge_store(store / "continuous" / f"{safe}_60m.csv", yahoo_history(sym, "730d", "60m"), 30000)
    if raw60.empty:
        raise RuntimeError(f"{sym} 시세를 받지 못했습니다")
    rolls = detect_rolls(spec, raw60, store, prev_rolls)
    adj60, applied = apply_rolls(raw60, rolls)
    df60 = indicators(adj60, 3600)
    res = run_rules(df60, spec)
    raw15 = yahoo_history(sym, "60d", "15m")
    adj15, _ = apply_rolls(raw15, rolls) if not raw15.empty else (raw15, [])
    df15 = indicators(adj15, 900) if not adj15.empty else pd.DataFrame()

    last = df60.iloc[-1]
    sess = df60[df60["session"] == last["session"]]
    day_open = float(sess["open"].iat[0]) if len(sess) else float(df60["close"].iat[-2])
    summary = dict(
        symbol=sym, code=spec["code"], micro=spec["micro"], name=spec["name"], icon=spec["icon"],
        exit_rule=("기울기 꺾이면 절반 → 200일선 아래 마감이면 나머지" if spec["exit_mode"] == "half" else "기울기 꺾이면 전부 매도"),
        price=round(float(last["close"]), spec["decimals"]), time_kst=str(last["time_kst"]),
        live_partial=not bool(last["complete"]),
        day_chg_pct=round((float(last["close"]) / day_open - 1) * 100, 2),
        ma20=round(float(last["ma20"]), spec["decimals"]), ma60=round(float(last["ma60"]), spec["decimals"]),
        ma200=round(float(last["ma200"]), spec["decimals"]),
        state=res["state"], backtest=bt_summary(res["trades"]),
        recent_events=res["events"][-12:][::-1],
        recent_trades=[dict(entry_kst=pd.to_datetime(t["entry_ts"] + KST_OFFSET, unit="s").strftime("%m-%d %H:%M"),
                            exit_kst=pd.to_datetime(t["exit_ts"] + KST_OFFSET, unit="s").strftime("%m-%d %H:%M"),
                            r=round(t["r"], 2), micro=round(t["micro"], 1)) for t in res["trades"][-10:][::-1]],
        rolls=[dict(time_kst=pd.to_datetime(e["ts_utc"] + KST_OFFSET, unit="s").strftime("%Y-%m-%d %H:%M"),
                    spread=round(e["spread"], spec["decimals"]), method=e["method"]) for e in applied][-6:],
    )
    charts = {"60m": chart_payload(df60, res["events"], 1100, spec["decimals"])}   # 약 7주
    if not df15.empty:
        charts["15m"] = chart_payload(df15, [], 2400, spec["decimals"])   # 약 1달
    return summary, charts, rolls, res["events"]
