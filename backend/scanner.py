"""
250-asset scanner with:
1. Position-aware strategy signals
2. Trade plan: Entry / Stop-Loss / Target 1 & 2 / Risk-Reward Ratio (R:R)
3. Market Regime Thermometer (KOSPI / KOSDAQ / US / CRYPTO / ALL)
4. Weekly 20W MA + Wilder RSI(14) Oversold emphasis
5. 7-factor Upside Probability (5% ~ 94.9%) + Exact Yesterday vs Today Rank & Probability Delta
6. Full un-truncated Telegram alert report
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import numpy as np

from config import ASSETS, MARKET_BEST_RULES, REPORTS_DIR, THEMES, load_settings
from backend.backtester import STRATEGIES, build_indicator_map, run_backtest_single
from backend.notifier import dispatch_alerts

THEME_LABELS = {t["id"]: t["label"] for t in THEMES}

MARKET_LABELS = {
    "KOSPI": "🇰🇷 코스피",
    "KOSDAQ": "🚀 코스닥",
    "US": "🇺🇸 미국주식",
    "CRYPTO": "🪙 코인",
}

RATING_META = {
    "STRONG_BUY": {"code": "STRONG_BUY", "label": "🔥 강력 매수"},
    "BUY": {"code": "BUY", "label": "🟢 매수"},
    "WATCH_BUY": {"code": "WATCH_BUY", "label": "🟡 매수 관심"},
    "HOLD_WATCH": {"code": "HOLD_WATCH", "label": "⚪ 관망"},
    "SELL_WARN": {"code": "SELL_WARN", "label": "🔴 매도/주의"},
}


def _fmt_price(val: float, currency: str) -> str:
    if currency == "KRW":
        return f"{round(val):,}원"
    if abs(val) >= 100:
        return f"${val:,.2f}"
    if abs(val) >= 1:
        return f"${val:.2f}"
    return f"${val:.4f}"


def _safe_float(val: Any) -> float | None:
    if val is None:
        return None
    f = float(val)
    return None if (np.isnan(f) or not np.isfinite(f)) else f


def _rsi_zone(rsi: float | None) -> tuple[str, str]:
    if rsi is None:
        return "UNKNOWN", "-"
    if rsi <= 30.0:
        return "EXTREME_OVERSOLD", "💎 극과매도"
    if rsi <= 36.0:
        return "OVERSOLD", "💠 과매도"
    if rsi <= 46.0:
        return "DIP_BUY", "🔹 눌림구간"
    if rsi >= 75.0:
        return "OVERBOUGHT", "⚠️ 과매수"
    return "NEUTRAL", "중립"


def _compute_trade_plan(
    *,
    price: float,
    ma20: float | None,
    ma200: float | None,
    su: float | None,
    sl: float | None,
    lu: float | None,
    high180: float | None,
    signal: str,
) -> dict[str, Any]:
    """Compute actionable Entry, Stop-Loss, Target 1/2, and Risk-Reward ratio."""
    # Entry reference: if NEAR breakout, show breakout level or current price
    entry = price

    # Candidate technical supports strictly below entry (within 2.5% ~ 12% risk band)
    candidates: list[tuple[float, str]] = []
    for lvl, name in ((sl, "단기 하단선"), (ma20, "MA20 지지"), (ma200, "MA200 지지")):
        if lvl and 0.88 * entry <= lvl <= 0.975 * entry:
            candidates.append((lvl * 0.992, name))

    if candidates:
        # Pick tightest meaningful technical support below price
        stop_loss, stop_basis = max(candidates, key=lambda x: x[0])
    else:
        stop_loss = entry * 0.92
        stop_basis = "-8% 기본손절"

    risk_amt = max(entry - stop_loss, entry * 0.025)
    risk_pct = (risk_amt / entry) * 100.0

    # Target 1: nearest overhead resistance if >= 1.5x risk, else 2.0x risk
    overhead = [lvl for lvl in (su, lu, high180) if lvl and lvl > entry * 1.03]
    nearest_res = min(overhead) if overhead else None
    if nearest_res and (nearest_res - entry) >= risk_amt * 1.6:
        target_1 = nearest_res
        t1_basis = "상단 저항/전고점"
    else:
        target_1 = entry + risk_amt * 2.0
        t1_basis = "손익비 1:2 목표"

    # Target 2: 180-day high if meaningfully higher, else 3.0x risk
    if high180 and high180 > target_1 * 1.04:
        target_2 = high180
    else:
        target_2 = entry + risk_amt * 3.0

    rr_ratio = (target_1 - entry) / risk_amt if risk_amt > 0 else 2.0
    upside_t1_pct = (target_1 / entry - 1.0) * 100.0
    upside_t2_pct = (target_2 / entry - 1.0) * 100.0

    return {
        "entry_price": round(entry, 4),
        "stop_loss": round(stop_loss, 4),
        "stop_basis": stop_basis,
        "risk_pct": round(risk_pct, 2),
        "target_1": round(target_1, 4),
        "t1_basis": t1_basis,
        "target_2": round(target_2, 4),
        "upside_t1_pct": round(upside_t1_pct, 1),
        "upside_t2_pct": round(upside_t2_pct, 1),
        "rr_ratio": round(rr_ratio, 2),
    }


def _score_upside_probability(
    *,
    price: float,
    open_p: float,
    ma20: float | None,
    ma20_slope: float | None,
    ma200: float | None,
    ma200_state: str,
    ma200_rule_ok: bool,
    weekly_bull: bool,
    rsi14: float | None,
    signal: str,
    dist_su: float | None,
    dist_lu: float | None,
    dist_sl: float | None,
    vol_ratio: float,
    ret5_pct: float,
    hist_pf_6y: float,
    hist_wr_6y: float,
    hist_ret_6y: float,
    theme_bull_pct: float,
) -> tuple[float, str, str, list[str]]:
    """
    Transparent 7-factor quantitative upside probability model (5.0% ~ 94.9%).
    Incorporates RSI oversold dip-buying bonus & weekly 20W MA confirmation.
    """
    score = 26.0
    factors: list[str] = []

    # 1. MA200 대세 추세 & 기울기 (+20 ~ -16)
    if ma200 and price > ma200:
        if ma200_state == "up":
            score += 19.0
            factors.append("MA200 상승↗")
        elif ma200_state == "flat":
            score += 14.5
            factors.append("MA200 평평→전환")
        else:
            score += 2.0
    else:
        score -= 15.0
        factors.append("MA200 하회")

    # 2. 주봉 20주선 멀티 타임프레임 (+5 ~ -2)
    if weekly_bull:
        score += 4.5
        factors.append("주봉 강세")
    else:
        score -= 2.0

    # 3. 추세선 구조 & 돌파 상태 (+21 ~ -20)
    min_upper_dist = min([d for d in (dist_su, dist_lu) if d is not None], default=None)
    if signal == "BUY":
        score += 21.0
        factors.append("상단 추세선 돌파")
    elif signal == "NEAR":
        prox_bonus = max(11.5, 18.0 - max(min_upper_dist or 2.0, 0.0) * 1.9)
        score += prox_bonus
        factors.append(f"돌파 임박({min_upper_dist:.1f}%)" if min_upper_dist is not None else "돌파 임박")
    elif signal == "HOLD":
        score += 11.0
        factors.append("상승 추세 유지")
    elif signal == "SELL":
        score -= 20.0
        factors.append("추세 이탈")
    else:
        if dist_sl is not None and -1.0 <= dist_sl <= 4.0 and price >= open_p:
            score += 9.0
            factors.append("하단 지지 반등")
        elif min_upper_dist is not None and 3.0 < min_upper_dist <= 7.0 and ma200_rule_ok:
            score += 5.5
            factors.append(f"저항선 {min_upper_dist:.1f}% 접근")

    # 4. RSI(14) 과매도 매수 기회 & 과열 방지 (+11 ~ -5)
    if rsi14 is not None:
        if rsi14 <= 30.0:
            bonus = 11.0 if ma200_rule_ok else 7.5
            score += bonus
            factors.append(f"💎 RSI 극과매도({rsi14:.0f})")
        elif rsi14 <= 36.0:
            bonus = 9.0 if ma200_rule_ok else 5.0
            score += bonus
            factors.append(f"💠 RSI 과매도({rsi14:.0f})")
        elif rsi14 <= 46.0 and ma200_rule_ok:
            score += 5.0
            factors.append(f"RSI 눌림({rsi14:.0f})")
        elif rsi14 >= 75.0:
            score -= 5.0
            factors.append(f"⚠️ RSI 과열({rsi14:.0f})")

    # 5. MA20 단기 모멘텀 & 이격도 (+10 ~ -5)
    if ma20 and ma20 > 0:
        gap_ma20 = (price / ma20 - 1.0) * 100.0
        if price > ma20:
            if ma20_slope is not None and ma20_slope > 0:
                if gap_ma20 <= 10.0:
                    score += 10.0 - abs(gap_ma20 - 4.0) * 0.2
                    factors.append("MA20 건전상승")
                elif gap_ma20 <= 18.0:
                    score += 5.5
                else:
                    score += 1.5
            else:
                score += 5.0
        else:
            # Don't double-penalize an RSI oversold dip inside a bull market
            score -= 2.0 if (rsi14 is not None and rsi14 <= 38.0 and ma200_rule_ok) else 5.5

    # 6. 거래량 & 5일 수급 (+8 ~ -3)
    if vol_ratio >= 1.6 and price >= open_p:
        score += min(8.0, 5.0 + (vol_ratio - 1.6) * 1.8)
        factors.append(f"거래량 {vol_ratio:.1f}x")
    elif vol_ratio >= 1.15 and ret5_pct > 0:
        score += min(4.5, 2.0 + ret5_pct * 0.2)
    elif ret5_pct < -6.0 and (rsi14 is None or rsi14 > 36.0):
        score -= 3.5

    # 7. 해당 종목 6년 과거 전략 궁합 + 소속 테마 강세 (+17 ~ -7)
    if hist_pf_6y >= 1.0:
        pf_pts = min(8.5, np.log1p(hist_pf_6y - 1.0) * 3.6)
        wr_pts = min(3.5, max(0.0, (hist_wr_6y - 20.0) * 0.07))
        score += pf_pts + wr_pts
        if hist_pf_6y >= 2.2 and hist_ret_6y > 20.0:
            factors.append(f"6년 PF {hist_pf_6y:.1f}")
    elif hist_pf_6y > 0:
        score -= 7.0

    theme_pts = min(5.5, max(0.0, (theme_bull_pct - 10.0) * 0.15))
    score += theme_pts
    if theme_bull_pct >= 35.0:
        factors.append("강세 테마")

    prob = round(float(np.clip(score, 5.0, 94.9)), 1)

    # 5-tier actionable rating (buy-side ratings; portfolio sell alerts handled separately for held stocks!)
    if signal == "SELL" or prob < 42.0:
        r_code = "SELL_WARN"
    elif prob >= 75.0 and ma200_rule_ok and hist_pf_6y >= 1.2:
        r_code = "STRONG_BUY"
    elif prob >= 66.0 and (ma200_rule_ok or (rsi14 is not None and rsi14 <= 32.0 and weekly_bull)):
        r_code = "BUY"
    elif prob >= 55.0 and (ma200_rule_ok or (rsi14 is not None and rsi14 <= 35.0)):
        r_code = "WATCH_BUY"
    else:
        r_code = "HOLD_WATCH"

    return prob, r_code, RATING_META[r_code]["label"], factors[:4]


def _extract_bar_snapshot(ind, idx: int) -> dict[str, Any]:
    row = ind.iloc[idx]
    prev = ind.iloc[max(0, idx - 1)]
    prev5 = ind.iloc[max(0, idx - 5)]
    price = float(row["close"])
    open_p = float(row["open"])
    prev_close = float(prev["close"])
    chg_pct = (price / prev_close - 1.0) * 100.0 if prev_close > 0 else 0.0
    ret5_pct = (price / float(prev5["close"]) - 1.0) * 100.0 if float(prev5["close"]) > 0 else 0.0

    ma20 = _safe_float(row["ma20"])
    ma20_slope = _safe_float(row["ma20_slope"])
    ma200 = _safe_float(row["ma200"])
    ma200_chg10 = _safe_float(row["ma200_chg10_pct"])
    ma200_chg5 = _safe_float(row["ma200_chg5_pct"])
    rsi14 = _safe_float(row["rsi14"]) if "rsi14" in ind.columns else None
    wma20 = _safe_float(row["wma20"]) if "wma20" in ind.columns else None
    wma20_slope = _safe_float(row["wma20_slope"]) if "wma20_slope" in ind.columns else None
    high180 = _safe_float(row["high180"]) if "high180" in ind.columns else None

    vol_ma20 = _safe_float(row["vol_ma20"]) or 0.0
    vol_ratio = (float(row["volume"]) / vol_ma20) if vol_ma20 > 0 else 1.0

    if ma200_chg10 is None:
        ma200_state = "unknown"
    elif ma200_chg10 > 0.05:
        ma200_state = "up"
    elif ma200_chg10 >= -0.15 or (ma200_chg5 is not None and ma200_chg5 >= 0.0):
        ma200_state = "flat"
    else:
        ma200_state = "down"

    ma200_rule_ok = bool(ma200 and price > ma200 and ma200_state in ("up", "flat"))
    weekly_bull = bool(wma20 and price > wma20 and (wma20_slope is None or wma20_slope >= -0.001 * wma20))

    su = _safe_float(row["short_upper"])
    sl = _safe_float(row["short_lower"])
    lu = _safe_float(row["long_upper"])
    ll = _safe_float(row["long_lower"])
    dist_su = ((su - price) / price * 100.0) if (su and price > 0) else None
    dist_lu = ((lu - price) / price * 100.0) if (lu and price > 0) else None
    dist_sl = ((price - sl) / sl * 100.0) if (sl and sl > 0) else None

    return {
        "date": str(row["date"]),
        "price": price,
        "open": open_p,
        "chg_pct": chg_pct,
        "ret5_pct": ret5_pct,
        "vol_ratio": vol_ratio,
        "ma20": ma20,
        "ma20_slope": ma20_slope,
        "ma200": ma200,
        "ma200_chg10": ma200_chg10,
        "ma200_state": ma200_state,
        "ma200_rule_ok": ma200_rule_ok,
        "rsi14": rsi14,
        "wma20": wma20,
        "weekly_bull": weekly_bull,
        "high180": high180,
        "su": su,
        "sl": sl,
        "lu": lu,
        "ll": ll,
        "dist_su": dist_su,
        "dist_lu": dist_lu,
        "dist_sl": dist_sl,
    }


def scan_all_assets(
    strategy_id: str = "AUTO_BEST",
    short_window: int = 45,
    long_window: int = 180,
    price_source: str = "wick",
    scale_mode: str = "linear",
    near_threshold_pct: float = 3.0,
    custom_params: dict[str, Any] | None = None,
    exit_rule: str = "default",
) -> dict[str, Any]:
    """
    Scan all 250 cached assets using causal strategy state, market thermometer,
    RSI(14) oversold detection, weekly MA20, trade plan (R:R), and yesterday-vs-today rank deltas.
    """
    ind_map = build_indicator_map(
        short_window=short_window,
        long_window=long_window,
        price_source=price_source,
        scale_mode=scale_mode,
    )
    items: list[dict[str, Any]] = []
    prev_snapshots: dict[str, dict[str, Any]] = {}

    for asset in ASSETS:
        sym = asset["symbol"]
        ind = ind_map.get(sym)
        if ind is None or len(ind) < 210:
            continue

        mkt = asset["market"]
        if strategy_id == "AUTO_BEST":
            rule = MARKET_BEST_RULES.get(mkt, {"strategy_id": "S3", "exit_rule": "ma200_2d", "label": "S3+MA200홀딩"})
            eff_sid = rule["strategy_id"]
            eff_exit = rule["exit_rule"]
            rule_label = rule["label"]
        else:
            eff_sid = strategy_id
            eff_exit = exit_rule
            rule_label = f"{eff_sid}+{eff_exit}"

        bt = run_backtest_single(
            sym,
            ind,
            strategy_id=eff_sid,
            years=6,
            custom_params=custom_params,
            include_series=True,
            exit_rule=eff_exit,
        )

        cur = _extract_bar_snapshot(ind, len(ind) - 1)
        prev = _extract_bar_snapshot(ind, len(ind) - 2)
        recent_dates = {cur["date"], prev["date"]}

        trades = bt.get("trades", [])
        last_trade = trades[-1] if trades else None

        # Current signal
        signal = "WATCH"
        reason = "추세 관망"
        priority = 4

        if last_trade and last_trade["open"]:
            if last_trade["entry_date"] in recent_dates:
                signal = "BUY"
                day_tag = "오늘" if last_trade["entry_date"] == cur["date"] else "전일"
                reason = f"[{rule_label}] {last_trade['entry_reason']} ({day_tag} 진입)"
                priority = 0
            else:
                signal = "HOLD"
                reason = f"[{rule_label}] 전략 추세 유지 ({last_trade['entry_date']} 돌파)"
                priority = 3
        elif last_trade and (not last_trade["open"]) and last_trade["exit_date"] in recent_dates:
            signal = "SELL"
            day_tag = "오늘" if last_trade["exit_date"] == cur["date"] else "전일"
            reason = f"[{rule_label}] {last_trade['exit_reason']} ({day_tag})"
            priority = 1
        else:
            near_notes = []
            if cur["dist_su"] is not None and 0.0 <= cur["dist_su"] <= near_threshold_pct:
                near_notes.append(f"단기상단 {cur['dist_su']:.2f}%")
            if cur["dist_lu"] is not None and 0.0 <= cur["dist_lu"] <= near_threshold_pct:
                near_notes.append(f"장기상단 {cur['dist_lu']:.2f}%")
            if near_notes and cur["ma200_rule_ok"]:
                signal = "NEAR"
                reason = f"[{rule_label}] 돌파 임박 (" + ", ".join(near_notes) + ")"
                priority = 2
            elif cur["rsi14"] is not None and cur["rsi14"] <= 35.0:
                reason = f"RSI 과매도({cur['rsi14']:.1f}) — 반등/저점 매수 주시"
            elif not cur["ma200_rule_ok"]:
                reason = "MA200 아래 (매매 제외)" if (cur["ma200"] and cur["price"] <= cur["ma200"]) else "MA200 하락 기울기 (전환 대기)"
            elif cur["ma20"] and cur["price"] > cur["ma20"]:
                reason = "MA200 평평/상승 · MA20 위 (돌파 대기)"
            else:
                reason = "MA200 조건 충족 · MA20 아래 눌림 조정"

        # Approximate yesterday's signal for exact yesterday-vs-today probability delta
        prev_signal = "WATCH"
        if last_trade and last_trade["open"] and last_trade["entry_date"] < cur["date"]:
            prev_signal = "BUY" if last_trade["entry_date"] == prev["date"] else "HOLD"
        elif last_trade and (not last_trade["open"]) and last_trade["exit_date"] == prev["date"]:
            prev_signal = "SELL"
        elif (
            prev["ma200_rule_ok"]
            and (
                (prev["dist_su"] is not None and 0.0 <= prev["dist_su"] <= near_threshold_pct)
                or (prev["dist_lu"] is not None and 0.0 <= prev["dist_lu"] <= near_threshold_pct)
            )
        ):
            prev_signal = "NEAR"

        prev_snapshots[sym] = {**prev, "signal": prev_signal}

        trade_plan = _compute_trade_plan(
            price=cur["price"],
            ma20=cur["ma20"],
            ma200=cur["ma200"],
            su=cur["su"],
            sl=cur["sl"],
            lu=cur["lu"],
            high180=cur["high180"],
            signal=signal,
        )
        rsi_code, rsi_label = _rsi_zone(cur["rsi14"])

        items.append(
            {
                "symbol": sym,
                "name": asset["name"],
                "market": mkt,
                "theme": asset.get("theme", "기타"),
                "currency": asset["currency"],
                "date": cur["date"],
                "close": round(cur["price"], 4),
                "open": round(cur["open"], 4),
                "change_pct": round(cur["chg_pct"], 2),
                "ret5_pct": round(cur["ret5_pct"], 2),
                "vol_ratio": round(cur["vol_ratio"], 2),
                "ma20": round(cur["ma20"], 4) if cur["ma20"] else None,
                "ma20_slope": round(cur["ma20_slope"], 4) if cur["ma20_slope"] is not None else None,
                "ma200": round(cur["ma200"], 4) if cur["ma200"] else None,
                "ma200_chg10_pct": round(cur["ma200_chg10"], 3) if cur["ma200_chg10"] is not None else None,
                "ma200_state": cur["ma200_state"],
                "ma200_rule_ok": cur["ma200_rule_ok"],
                "above_ma20": bool(cur["ma20"] and cur["price"] > cur["ma20"]),
                "above_ma200": bool(cur["ma200"] and cur["price"] > cur["ma200"]),
                "rsi14": round(cur["rsi14"], 1) if cur["rsi14"] is not None else None,
                "rsi_zone": rsi_code,
                "rsi_label": rsi_label,
                "weekly_bull": cur["weekly_bull"],
                "short_upper": round(cur["su"], 4) if cur["su"] else None,
                "short_lower": round(cur["sl"], 4) if cur["sl"] else None,
                "long_upper": round(cur["lu"], 4) if cur["lu"] else None,
                "long_lower": round(cur["ll"], 4) if cur["ll"] else None,
                "dist_short_upper_pct": round(cur["dist_su"], 2) if cur["dist_su"] is not None else None,
                "dist_long_upper_pct": round(cur["dist_lu"], 2) if cur["dist_lu"] is not None else None,
                "dist_short_lower_pct": round(cur["dist_sl"], 2) if cur["dist_sl"] is not None else None,
                "hist_pf_6y": float(bt.get("profit_factor", 0.0)),
                "hist_wr_6y": float(bt.get("win_rate_pct", 0.0)),
                "hist_ret_6y": float(bt.get("total_return_pct", 0.0)),
                "trade_plan": trade_plan,
                "applied_rule": rule_label,
                "signal": signal,
                "reason": reason,
                "priority": priority,
            }
        )

    # 1. Market Regime Thermometer (ALL, KOSPI, KOSDAQ, US, CRYPTO)
    market_regime: dict[str, dict[str, Any]] = {}
    for mkt in ["ALL", "KOSPI", "KOSDAQ", "US", "CRYPTO"]:
        sub = items if mkt == "ALL" else [x for x in items if x["market"] == mkt]
        n_sub = max(len(sub), 1)
        above200_pct = round(sum(1 for x in sub if x["above_ma200"]) / n_sub * 100.0, 1)
        bull_pct = round(sum(1 for x in sub if x["ma200_rule_ok"]) / n_sub * 100.0, 1)
        above20_pct = round(sum(1 for x in sub if x["above_ma20"]) / n_sub * 100.0, 1)
        oversold_cnt = sum(1 for x in sub if x["rsi14"] is not None and x["rsi14"] <= 36.0)
        if above200_pct >= 55.0:
            temp_code, temp_label = "BULL", "🔥 강세장 (공격)"
        elif above200_pct >= 30.0:
            temp_code, temp_label = "NEUTRAL", "🟡 선별장 (중립)"
        else:
            temp_code, temp_label = "BEAR", "🧊 약세·조정 (현금↑)"
        market_regime[mkt] = {
            "market": mkt,
            "total": len(sub),
            "ma200_above_pct": above200_pct,
            "ma200_bull_pct": bull_pct,
            "ma20_above_pct": above20_pct,
            "oversold_count": oversold_cnt,
            "regime": temp_code,
            "regime_label": temp_label,
        }

    # 2. Theme bull ratios (today and yesterday)
    theme_bull_map: dict[str, float] = {}
    prev_theme_bull_map: dict[str, float] = {}
    theme_stats = []
    for th in THEMES:
        tid = th["id"]
        sub = [x for x in items if x.get("theme") == tid]
        if not sub:
            continue
        b_cnt = sum(1 for x in sub if x["signal"] == "BUY")
        s_cnt = sum(1 for x in sub if x["signal"] == "SELL")
        n_cnt = sum(1 for x in sub if x["signal"] == "NEAR")
        h_cnt = sum(1 for x in sub if x["signal"] == "HOLD")
        ov_cnt = sum(1 for x in sub if x["rsi14"] is not None and x["rsi14"] <= 36.0)
        bull_pct = round(sum(1 for x in sub if x["ma200_rule_ok"]) / len(sub) * 100.0, 1)
        prev_bull_pct = round(
            sum(1 for x in sub if prev_snapshots[x["symbol"]]["ma200_rule_ok"]) / len(sub) * 100.0, 1
        )
        theme_bull_map[tid] = bull_pct
        prev_theme_bull_map[tid] = prev_bull_pct
        heat = round(b_cnt * 4.0 + n_cnt * 2.5 + h_cnt * 0.6 + (bull_pct / 25.0) - s_cnt * 1.5, 2)
        theme_stats.append(
            {
                "id": tid,
                "label": th["label"],
                "total": len(sub),
                "BUY": b_cnt,
                "SELL": s_cnt,
                "NEAR": n_cnt,
                "HOLD": h_cnt,
                "oversold": ov_cnt,
                "ma200_ok_pct": bull_pct,
                "heat": heat,
            }
        )
    theme_stats.sort(key=lambda x: (x["heat"], x["BUY"] + x["NEAR"], x["ma200_ok_pct"]), reverse=True)

    # 3. Compute TODAY & YESTERDAY upside probability for every asset
    prev_probs: dict[str, float] = {}
    for it in items:
        prob, r_code, r_label, factors = _score_upside_probability(
            price=it["close"],
            open_p=it["open"],
            ma20=it["ma20"],
            ma20_slope=it["ma20_slope"],
            ma200=it["ma200"],
            ma200_state=it["ma200_state"],
            ma200_rule_ok=it["ma200_rule_ok"],
            weekly_bull=it["weekly_bull"],
            rsi14=it["rsi14"],
            signal=it["signal"],
            dist_su=it["dist_short_upper_pct"],
            dist_lu=it["dist_long_upper_pct"],
            dist_sl=it["dist_short_lower_pct"],
            vol_ratio=it["vol_ratio"],
            ret5_pct=it["ret5_pct"],
            hist_pf_6y=it["hist_pf_6y"],
            hist_wr_6y=it["hist_wr_6y"],
            hist_ret_6y=it["hist_ret_6y"],
            theme_bull_pct=theme_bull_map.get(it["theme"], 0.0),
        )
        it["upside_prob"] = prob
        it["rating"] = r_code
        it["rating_label"] = r_label
        it["prob_factors"] = factors

        ps = prev_snapshots[it["symbol"]]
        p_prob, _, _, _ = _score_upside_probability(
            price=ps["price"],
            open_p=ps["open"],
            ma20=ps["ma20"],
            ma20_slope=ps["ma20_slope"],
            ma200=ps["ma200"],
            ma200_state=ps["ma200_state"],
            ma200_rule_ok=ps["ma200_rule_ok"],
            weekly_bull=ps["weekly_bull"],
            rsi14=ps["rsi14"],
            signal=ps["signal"],
            dist_su=ps["dist_su"],
            dist_lu=ps["dist_lu"],
            dist_sl=ps["dist_sl"],
            vol_ratio=ps["vol_ratio"],
            ret5_pct=ps["ret5_pct"],
            hist_pf_6y=it["hist_pf_6y"],
            hist_wr_6y=it["hist_wr_6y"],
            hist_ret_6y=it["hist_ret_6y"],
            theme_bull_pct=prev_theme_bull_map.get(it["theme"], 0.0),
        )
        prev_probs[it["symbol"]] = p_prob
        it["prev_prob"] = p_prob
        it["prob_delta"] = round(prob - p_prob, 1)

        it.pop("open", None)
        it.pop("ma20_slope", None)
        it.pop("dist_short_lower_pct", None)

    # 4. Exact yesterday vs today ranks across all 250 assets
    today_order = sorted(items, key=lambda x: (x["upside_prob"], x["hist_pf_6y"], x["change_pct"]), reverse=True)
    prev_order = sorted(items, key=lambda x: (prev_probs[x["symbol"]], x["hist_pf_6y"]), reverse=True)
    prev_rank_map = {x["symbol"]: idx for idx, x in enumerate(prev_order, 1)}
    for idx, it in enumerate(today_order, 1):
        pr = prev_rank_map[it["symbol"]]
        it["rank_today"] = idx
        it["rank_prev"] = pr
        it["rank_delta"] = pr - idx  # positive = moved UP
        it["is_new_top30"] = bool(idx <= 30 and pr > 30)

    items.sort(key=lambda x: (x["priority"], -x["upside_prob"], x["market"]))

    counts = {
        "BUY": sum(1 for x in items if x["signal"] == "BUY"),
        "SELL": sum(1 for x in items if x["signal"] == "SELL"),
        "NEAR": sum(1 for x in items if x["signal"] == "NEAR"),
        "HOLD": sum(1 for x in items if x["signal"] == "HOLD"),
        "WATCH": sum(1 for x in items if x["signal"] == "WATCH"),
    }
    rating_counts = {
        code: sum(1 for x in items if x["rating"] == code)
        for code in ("STRONG_BUY", "BUY", "WATCH_BUY", "HOLD_WATCH", "SELL_WARN")
    }
    oversold_total = sum(1 for x in items if x["rsi14"] is not None and x["rsi14"] <= 36.0)

    strat_name = (
        "시장별 최적 자동매칭 (코스피·코스닥·미국·코인)"
        if strategy_id == "AUTO_BEST"
        else STRATEGIES.get(strategy_id, {"name": "커스텀 전략"})["name"]
    )
    return {
        "scanned_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "strategy_id": strategy_id,
        "strategy_name": strat_name,
        "counts": counts,
        "rating_counts": rating_counts,
        "oversold_total": oversold_total,
        "market_regime": market_regime,
        "themes": theme_stats,
        "items": items,
    }


def format_full_alert_report(scan: dict[str, Any], include_near: bool = True) -> tuple[str, str, str, list[dict[str, Any]]]:
    """
    Build complete un-truncated report headed by:
    - Market Regime Thermometer
    - Hot Themes Top 3
    - Upside Probability Top 5 (with rank deltas & R:R)
    - RSI Oversold Buy Candidates
    - ALL triggered BUY / NEAR stocks
    """
    items = scan["items"]
    buys = [x for x in items if x["signal"] == "BUY"]
    sells = [x for x in items if x["signal"] == "SELL"]
    nears = [x for x in items if x["signal"] == "NEAR"] if include_near else []
    triggered = buys + sells + nears

    date_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    title = f"[추세선 {len(items)}종목 알림 · {date_str}] 매수 {len(buys)} · 임박 {len(nears)} · 과매도 {scan.get('oversold_total', 0)}"

    mr = scan.get("market_regime", {})
    rc = scan.get("rating_counts", {})
    sections: list[str] = [
        f"🌡️ 시장 온도(MA200 위): 코스피 {mr.get('KOSPI', {}).get('ma200_above_pct', 0)}% · 코스닥 {mr.get('KOSDAQ', {}).get('ma200_above_pct', 0)}% · 미국 {mr.get('US', {}).get('ma200_above_pct', 0)}% · 코인 {mr.get('CRYPTO', {}).get('ma200_above_pct', 0)}%",
        f"의견: 🔥강력매수 {rc.get('STRONG_BUY', 0)} | 🟢매수 {rc.get('BUY', 0)} | 🟡관심 {rc.get('WATCH_BUY', 0)} | 💎RSI과매도 {scan.get('oversold_total', 0)}",
    ]

    hot_themes = scan.get("themes", [])[:3]
    if hot_themes:
        sections.append("\n🔥 오늘의 강세 테마 Top 3")
        for idx, th in enumerate(hot_themes, 1):
            sections.append(
                f"  {idx}. {th['label']}: 매수 {th['BUY']} · 임박 {th['NEAR']} · 과매도 {th.get('oversold', 0)} (MA200 강세 {th['ma200_ok_pct']}%)"
            )

    top5 = sorted(items, key=lambda x: (x["upside_prob"], x["hist_pf_6y"]), reverse=True)[:5]
    if top5:
        sections.append("\n🏆 상승확률 TOP 5")
        for rank, it in enumerate(top5, 1):
            p_str = _fmt_price(it["close"], it["currency"])
            tp = it.get("trade_plan", {})
            chg = "NEW" if it.get("is_new_top30") else (f"▲{it['rank_delta']}" if it.get("rank_delta", 0) > 0 else (f"▼{abs(it['rank_delta'])}" if it.get("rank_delta", 0) < 0 else "-"))
            sections.append(
                f"  {rank}위({chg}). {it['name']}({it['symbol']}) {it['upside_prob']:.1f}% [{it['rating_label']}] · {p_str} | 손절 {_fmt_price(tp.get('stop_loss', 0), it['currency'])} · 목표 {_fmt_price(tp.get('target_1', 0), it['currency'])} (R:R 1:{tp.get('rr_ratio', 2)})"
            )

    oversold = sorted(
        [x for x in items if x["rsi14"] is not None and x["rsi14"] <= 35.0],
        key=lambda x: (-x["upside_prob"], x["rsi14"]),
    )[:8]
    if oversold:
        sections.append(f"\n💎 RSI 과매도 매수 주목 (상위 {len(oversold)}종목)")
        for it in oversold:
            p_str = _fmt_price(it["close"], it["currency"])
            sections.append(
                f"  • [{it['theme']}] {it['name']}({it['symbol']}) {p_str} · RSI {it['rsi14']} · 확률 {it['upside_prob']:.1f}% ({it['rating_label']})"
            )

    def _add_group(header: str, group: list[dict[str, Any]]) -> None:
        if not group:
            return
        sections.append(f"\n{header} ({len(group)}종목)")
        for mkt in ["KOSPI", "KOSDAQ", "US", "CRYPTO"]:
            sub = [x for x in group if x["market"] == mkt]
            if not sub:
                continue
            sections.append(f"  {MARKET_LABELS[mkt]} ({len(sub)})")
            for it in sub:
                p_str = _fmt_price(it["close"], it["currency"])
                arrow = "↗" if it["ma200_state"] == "up" else ("→" if it["ma200_state"] == "flat" else "↘")
                rsi_txt = f"RSI {it['rsi14']}" if it["rsi14"] is not None else ""
                sections.append(
                    f"  • [{it.get('theme', '')}] {it['name']}({it['symbol']}) {p_str} ({it['change_pct']:+.1f}%, 확률 {it['upside_prob']:.0f}% {it['rating_label']}, {rsi_txt}, MA200{arrow}) — {it['reason']}"
                )

    _add_group("🟢 신규 매수 신호", buys)
    if include_near:
        _add_group("🟡 추세선 돌파 임박", nears)
    _add_group("🔴 추세 이탈 참고 (보유 시 매도 점검)", sells)

    sections.append("\n🌐 TOP 30 · 내 보유종목 점검: https://smartjd824.github.io/trendline-lab/")
    full_text = "\n".join(sections)

    mac_parts = []
    if buys:
        mac_parts.append("매수: " + ", ".join(x["name"] for x in buys[:5]))
    if nears:
        mac_parts.append("임박: " + ", ".join(x["name"] for x in nears[:5]))
    macos_summary = " / ".join(mac_parts) if mac_parts else f"TOP1: {top5[0]['name']} {top5[0]['upside_prob']}%" if top5 else "스캔 완료"

    return title, full_text, macos_summary, triggered


def scan_and_notify(
    strategy_id: str | None = None,
    custom_params: dict[str, Any] | None = None,
    notify_if_empty: bool = False,
) -> dict[str, Any]:
    """Run scanner, save daily report file, and dispatch full alerts via configured channels."""
    settings = load_settings()
    sid = strategy_id or settings.get("active_strategy", "AUTO_BEST")
    scan = scan_all_assets(
        strategy_id=sid,
        short_window=int(settings.get("short_window", 45)),
        long_window=int(settings.get("long_window", 180)),
        price_source=settings.get("price_source", "wick"),
        scale_mode=settings.get("scale_mode", "linear"),
        near_threshold_pct=float(settings.get("near_threshold_pct", 3.0)),
        custom_params=custom_params,
        exit_rule=settings.get("exit_rule", "default"),
    )

    alert_cfg = settings.get("alerts", {})
    notify_near = bool(alert_cfg.get("notify_near_breakout", True))
    title, full_text, macos_summary, triggered = format_full_alert_report(scan, include_near=notify_near)

    report_file = REPORTS_DIR / f"alert_{datetime.now().strftime('%Y-%m-%d_%H%M')}.txt"
    report_file.write_text(f"{title}\n{'='*60}\n{full_text}\n", encoding="utf-8")

    if not triggered and not notify_if_empty:
        return {
            "scan": scan,
            "notified": False,
            "triggered_count": 0,
            "report_path": str(report_file),
            "alert_results": [],
            "message": "발송할 신호가 없습니다.",
        }

    alert_results = dispatch_alerts(
        title=title,
        full_message=full_text,
        alert_cfg=alert_cfg,
        macos_summary=macos_summary,
        macos_subtitle=f"리포트 저장: {report_file.name}",
    )
    return {
        "scan": scan,
        "notified": True,
        "triggered_count": len(triggered),
        "report_path": str(report_file),
        "alert_results": alert_results,
    }
