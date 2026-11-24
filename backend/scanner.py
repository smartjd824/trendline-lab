"""250-asset position-aware latest signal scanner, 6-factor upside probability leaderboard, & full-report alerts."""

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


def _score_upside_probability(
    *,
    price: float,
    open_p: float,
    ma20: float | None,
    ma20_slope: float | None,
    ma200: float | None,
    ma200_state: str,
    ma200_rule_ok: bool,
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
    Transparent 6-factor quantitative upside probability model (clamped 5% ~ 95%).
    Returns (upside_prob_pct, rating_code, rating_label, key_factors).
    """
    score = 28.0
    factors: list[str] = []

    # 1. MA200 대세 추세 & 기울기 (+22 ~ -16)
    if ma200 and price > ma200:
        if ma200_state == "up":
            score += 20.0
            factors.append("MA200 상승↗")
        elif ma200_state == "flat":
            score += 15.0
            factors.append("MA200 평평→전환")
        else:
            score += 2.0
    else:
        score -= 16.0
        factors.append("MA200 하회")

    # 2. 추세선 구조 & 돌파 상태 (+22 ~ -22)
    min_upper_dist = min(
        [d for d in (dist_su, dist_lu) if d is not None],
        default=None,
    )
    if signal == "BUY":
        score += 22.0
        factors.append("상단 추세선 돌파")
    elif signal == "NEAR":
        prox_bonus = max(12.0, 19.0 - max(min_upper_dist or 2.0, 0.0) * 2.0)
        score += prox_bonus
        factors.append(f"돌파 임박({min_upper_dist:.1f}%)" if min_upper_dist is not None else "돌파 임박")
    elif signal == "HOLD":
        score += 12.0
        factors.append("상승 추세 보유중")
    elif signal == "SELL":
        score -= 22.0
        factors.append("추세 이탈/청산")
    else:
        if dist_sl is not None and -1.0 <= dist_sl <= 4.0 and price >= open_p:
            score += 9.0
            factors.append("하단 지지 반등")
        elif min_upper_dist is not None and 3.0 < min_upper_dist <= 7.0 and ma200_rule_ok:
            score += 6.0
            factors.append(f"저항선 {min_upper_dist:.1f}% 접근")

    # 3. MA20 단기 모멘텀 & 과열 방지 (+12 ~ -6)
    if ma20 and ma20 > 0:
        gap_ma20 = (price / ma20 - 1.0) * 100.0
        if price > ma20:
            if ma20_slope is not None and ma20_slope > 0:
                if gap_ma20 <= 10.0:
                    score += 11.5 - abs(gap_ma20 - 4.0) * 0.25
                    factors.append("MA20 건전상승")
                elif gap_ma20 <= 18.0:
                    score += 6.5
                else:
                    score += 2.0
                    factors.append("단기 과열주의")
            else:
                score += 6.0
        else:
            score -= 6.0

    # 4. 거래량 & 5일 단기 수급 (+9 ~ -4)
    if vol_ratio >= 1.6 and price >= open_p:
        score += min(9.0, 5.5 + (vol_ratio - 1.6) * 2.0)
        factors.append(f"거래량 {vol_ratio:.1f}x")
    elif vol_ratio >= 1.15 and ret5_pct > 0:
        score += min(5.0, 2.5 + ret5_pct * 0.25)
    elif ret5_pct < -6.0:
        score -= 4.0

    # 5. 해당 종목의 6년 과거 전략 궁합 (연속 PF·승률 반영, +13 ~ -8)
    if hist_pf_6y >= 1.0:
        pf_pts = min(9.0, np.log1p(hist_pf_6y - 1.0) * 3.8)
        wr_pts = min(4.0, max(0.0, (hist_wr_6y - 20.0) * 0.08))
        score += pf_pts + wr_pts
        if hist_pf_6y >= 2.2 and hist_ret_6y > 20.0:
            factors.append(f"6년 PF {hist_pf_6y:.1f}")
    elif hist_pf_6y > 0:
        score -= 7.0

    # 6. 소속 테마 자금 유입 강도 (+6 ~ 0)
    theme_pts = min(6.0, max(0.0, (theme_bull_pct - 10.0) * 0.16))
    score += theme_pts
    if theme_bull_pct >= 35.0:
        factors.append("강세 테마")

    prob = round(float(np.clip(score, 5.0, 94.9)), 1)

    # 5-tier actionable rating (Strong Buy requires proven historical edge PF >= 1.2)
    if signal == "SELL" or prob < 42.0:
        r_code = "SELL_WARN"
    elif prob >= 75.0 and ma200_rule_ok and hist_pf_6y >= 1.2 and signal in ("BUY", "NEAR", "HOLD"):
        r_code = "STRONG_BUY"
    elif prob >= 66.0 and ma200_rule_ok:
        r_code = "BUY"
    elif prob >= 56.0 and ma200_rule_ok:
        r_code = "WATCH_BUY"
    else:
        r_code = "HOLD_WATCH"

    return prob, r_code, RATING_META[r_code]["label"], factors[:4]


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
    Scan all 250 cached assets using true causal strategy state + 6-factor upside probability ranking.
    """
    ind_map = build_indicator_map(
        short_window=short_window,
        long_window=long_window,
        price_source=price_source,
        scale_mode=scale_mode,
    )
    items: list[dict[str, Any]] = []

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

        # 6-year backtest gives both current position state AND long-term historical edge (PF / WR / Return)
        bt = run_backtest_single(
            sym,
            ind,
            strategy_id=eff_sid,
            years=6,
            custom_params=custom_params,
            include_series=True,
            exit_rule=eff_exit,
        )

        last = ind.iloc[-1]
        prev = ind.iloc[-2]
        prev5 = ind.iloc[-6] if len(ind) >= 6 else prev
        last_date = str(last["date"])
        prev_date = str(prev["date"])
        recent_dates = {last_date, prev_date}

        price = float(last["close"])
        open_p = float(last["open"])
        prev_close = float(prev["close"])
        chg_pct = (price / prev_close - 1.0) * 100.0 if prev_close > 0 else 0.0
        ret5_pct = (price / float(prev5["close"]) - 1.0) * 100.0 if float(prev5["close"]) > 0 else 0.0

        ma20 = float(last["ma20"]) if not np.isnan(last["ma20"]) else None
        ma20_slope = float(last["ma20_slope"]) if not np.isnan(last["ma20_slope"]) else None
        ma200 = float(last["ma200"]) if not np.isnan(last["ma200"]) else None
        ma200_chg10 = float(last["ma200_chg10_pct"]) if not np.isnan(last["ma200_chg10_pct"]) else None
        ma200_chg5 = float(last["ma200_chg5_pct"]) if not np.isnan(last["ma200_chg5_pct"]) else None
        vol_ma20 = float(last["vol_ma20"]) if not np.isnan(last["vol_ma20"]) else 0.0
        vol_ratio = (float(last["volume"]) / vol_ma20) if vol_ma20 > 0 else 1.0

        if ma200_chg10 is None:
            ma200_state = "unknown"
        elif ma200_chg10 > 0.05:
            ma200_state = "up"
        elif ma200_chg10 >= -0.15 or (ma200_chg5 is not None and ma200_chg5 >= 0.0):
            ma200_state = "flat"
        else:
            ma200_state = "down"
        ma200_rule_ok = bool(ma200 and price > ma200 and ma200_state in ("up", "flat"))

        su = float(last["short_upper"]) if not np.isnan(last["short_upper"]) else None
        sl = float(last["short_lower"]) if not np.isnan(last["short_lower"]) else None
        lu = float(last["long_upper"]) if not np.isnan(last["long_upper"]) else None
        ll = float(last["long_lower"]) if not np.isnan(last["long_lower"]) else None

        dist_su = ((su - price) / price * 100.0) if (su and price > 0) else None
        dist_lu = ((lu - price) / price * 100.0) if (lu and price > 0) else None
        dist_sl = ((price - sl) / sl * 100.0) if (sl and sl > 0) else None

        trades = bt.get("trades", [])
        last_trade = trades[-1] if trades else None

        signal = "WATCH"
        reason = "추세 관망"
        priority = 4

        if last_trade and last_trade["open"]:
            if last_trade["entry_date"] in recent_dates:
                signal = "BUY"
                day_tag = "오늘" if last_trade["entry_date"] == last_date else "전일"
                reason = f"[{rule_label}] {last_trade['entry_reason']} ({day_tag} 진입 · {last_trade['return_pct']:+.1f}%)"
                priority = 0
            else:
                signal = "HOLD"
                reason = f"[{rule_label}] 보유 중 ({last_trade['entry_date']} 진입 · {last_trade['return_pct']:+.1f}%)"
                priority = 3
        elif last_trade and (not last_trade["open"]) and last_trade["exit_date"] in recent_dates:
            signal = "SELL"
            day_tag = "오늘" if last_trade["exit_date"] == last_date else "전일"
            reason = f"[{rule_label}] {last_trade['exit_reason']} ({day_tag} 청산 · 확정 {last_trade['return_pct']:+.1f}%)"
            priority = 1
        else:
            near_notes = []
            if dist_su is not None and 0.0 <= dist_su <= near_threshold_pct:
                near_notes.append(f"단기상단 {dist_su:.2f}%")
            if dist_lu is not None and 0.0 <= dist_lu <= near_threshold_pct:
                near_notes.append(f"장기상단 {dist_lu:.2f}%")
            if near_notes and ma200_rule_ok:
                signal = "NEAR"
                reason = f"[{rule_label}] 돌파 임박 (" + ", ".join(near_notes) + ")"
                priority = 2
            elif not ma200_rule_ok:
                if ma200 and price <= ma200:
                    reason = "MA200 아래 (매매 제외)"
                else:
                    reason = "MA200 하락 기울기 (평평/상승 대기)"
            elif ma20 and price > ma20:
                reason = "MA200 평평/상승 · MA20 위 (돌파 대기)"
            else:
                reason = "MA200 조건 충족 · MA20 아래 조정"

        items.append(
            {
                "symbol": sym,
                "name": asset["name"],
                "market": mkt,
                "theme": asset.get("theme", "기타"),
                "currency": asset["currency"],
                "date": last_date,
                "close": round(price, 4),
                "open": round(open_p, 4),
                "change_pct": round(chg_pct, 2),
                "ret5_pct": round(ret5_pct, 2),
                "vol_ratio": round(vol_ratio, 2),
                "ma20": round(ma20, 4) if ma20 else None,
                "ma20_slope": round(ma20_slope, 4) if ma20_slope is not None else None,
                "ma200": round(ma200, 4) if ma200 else None,
                "ma200_chg10_pct": round(ma200_chg10, 3) if ma200_chg10 is not None else None,
                "ma200_state": ma200_state,
                "ma200_rule_ok": ma200_rule_ok,
                "above_ma20": bool(ma20 and price > ma20),
                "above_ma200": bool(ma200 and price > ma200),
                "short_upper": round(su, 4) if su else None,
                "short_lower": round(sl, 4) if sl else None,
                "long_upper": round(lu, 4) if lu else None,
                "long_lower": round(ll, 4) if ll else None,
                "dist_short_upper_pct": round(dist_su, 2) if dist_su is not None else None,
                "dist_long_upper_pct": round(dist_lu, 2) if dist_lu is not None else None,
                "dist_short_lower_pct": round(dist_sl, 2) if dist_sl is not None else None,
                "hist_pf_6y": float(bt.get("profit_factor", 0.0)),
                "hist_wr_6y": float(bt.get("win_rate_pct", 0.0)),
                "hist_ret_6y": float(bt.get("total_return_pct", 0.0)),
                "applied_rule": rule_label,
                "signal": signal,
                "reason": reason,
                "priority": priority,
            }
        )

    # First pass: compute theme bull ratios so theme momentum feeds into individual upside probability
    theme_bull_map: dict[str, float] = {}
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
        bull_pct = round(sum(1 for x in sub if x["ma200_rule_ok"]) / len(sub) * 100.0, 1)
        theme_bull_map[tid] = bull_pct
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
                "ma200_ok_pct": bull_pct,
                "heat": heat,
            }
        )
    theme_stats.sort(key=lambda x: (x["heat"], x["BUY"] + x["NEAR"], x["ma200_ok_pct"]), reverse=True)

    # Second pass: compute 6-factor upside probability & 5-tier rating for every asset
    for it in items:
        prob, r_code, r_label, factors = _score_upside_probability(
            price=it["close"],
            open_p=it["open"],
            ma20=it["ma20"],
            ma20_slope=it["ma20_slope"],
            ma200=it["ma200"],
            ma200_state=it["ma200_state"],
            ma200_rule_ok=it["ma200_rule_ok"],
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
        # Remove helper fields not needed by frontend
        it.pop("open", None)
        it.pop("ma20_slope", None)
        it.pop("dist_short_lower_pct", None)

    items.sort(
        key=lambda x: (
            x["priority"],
            -x["upside_prob"],
            x["market"],
        )
    )

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
        "themes": theme_stats,
        "items": items,
    }


def format_full_alert_report(scan: dict[str, Any], include_near: bool = True) -> tuple[str, str, str, list[dict[str, Any]]]:
    """
    Build complete un-truncated report headed by Hot Themes Top 3 + Upside Probability Top 5
    followed by ALL triggered stocks grouped by Signal -> Market.
    """
    items = scan["items"]
    buys = [x for x in items if x["signal"] == "BUY"]
    sells = [x for x in items if x["signal"] == "SELL"]
    nears = [x for x in items if x["signal"] == "NEAR"] if include_near else []
    triggered = buys + sells + nears

    date_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    title = f"[추세선 {len(items)}종목 알림 · {date_str}] 매수 {len(buys)} · 매도 {len(sells)} · 임박 {len(nears)}"

    rc = scan.get("rating_counts", {})
    sections: list[str] = [
        f"전략: {scan['strategy_name']}",
        f"신호: 🟢매수 {len(buys)} | 🔴매도 {len(sells)} | 🟡임박 {len(nears)} | 🔵보유 {scan['counts']['HOLD']} (총 {len(items)}종목)",
        f"의견: 🔥강력매수 {rc.get('STRONG_BUY', 0)} | 🟢매수 {rc.get('BUY', 0)} | 🟡관심 {rc.get('WATCH_BUY', 0)}",
    ]

    hot_themes = scan.get("themes", [])[:3]
    if hot_themes:
        sections.append("\n🔥 오늘의 강세 테마 Top 3")
        for idx, th in enumerate(hot_themes, 1):
            sections.append(
                f"  {idx}. {th['label']}: 매수 {th['BUY']} · 임박 {th['NEAR']} · 보유 {th['HOLD']} (MA200 강세 {th['ma200_ok_pct']}%)"
            )

    top5 = sorted(items, key=lambda x: (x["upside_prob"], x["hist_pf_6y"]), reverse=True)[:5]
    if top5:
        sections.append("\n🏆 상승확률 TOP 5")
        for rank, it in enumerate(top5, 1):
            p_str = _fmt_price(it["close"], it["currency"])
            sections.append(
                f"  {rank}위. {it['name']}({it['symbol']}) {it['upside_prob']:.1f}% [{it['rating_label']}] · {p_str} ({', '.join(it.get('prob_factors', [])[:3])})"
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
                th_name = it.get("theme", "")
                sections.append(
                    f"  • [{th_name}] {it['name']}({it['symbol']}) {p_str} ({it['change_pct']:+.1f}%, 확률 {it['upside_prob']:.0f}% {it['rating_label']}, MA200{arrow}) — {it['reason']}"
                )

    _add_group("🟢 신규 매수 신호", buys)
    _add_group("🔴 청산/매도 신호", sells)
    if include_near:
        _add_group("🟡 추세선 돌파 임박", nears)

    sections.append("\n🌐 상승확률 TOP 30 & 차트 보기: https://smartjd824.github.io/trendline-lab/")
    full_text = "\n".join(sections)

    mac_parts = []
    if buys:
        mac_parts.append("매수: " + ", ".join(x["name"] for x in buys[:5]) + (f" 외 {len(buys)-5}" if len(buys) > 5 else ""))
    if sells:
        mac_parts.append("매도: " + ", ".join(x["name"] for x in sells[:5]) + (f" 외 {len(sells)-5}" if len(sells) > 5 else ""))
    if nears:
        mac_parts.append("임박: " + ", ".join(x["name"] for x in nears[:5]) + (f" 외 {len(nears)-5}" if len(nears) > 5 else ""))
    macos_summary = " / ".join(mac_parts) if mac_parts else "신규 매수·매도·임박 종목 없음"

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
            "message": "발송할 매수/매도/돌파 임박 신호가 없습니다.",
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
