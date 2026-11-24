"""150-asset position-aware latest signal scanner & full-report alert builder (supports AUTO_BEST per-market mode)."""

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


def _fmt_price(val: float, currency: str) -> str:
    if currency == "KRW":
        return f"{round(val):,}원"
    if abs(val) >= 100:
        return f"${val:,.2f}"
    if abs(val) >= 1:
        return f"${val:.2f}"
    return f"${val:.4f}"


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
    Scan all 150 cached assets using true causal strategy state.
    When strategy_id == 'AUTO_BEST', automatically applies each market's 150-asset optimal (entry, exit) rule.
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

        bt = run_backtest_single(
            sym,
            ind,
            strategy_id=eff_sid,
            years=2,
            custom_params=custom_params,
            include_series=True,
            exit_rule=eff_exit,
        )

        last = ind.iloc[-1]
        prev = ind.iloc[-2]
        last_date = str(last["date"])
        prev_date = str(prev["date"])
        recent_dates = {last_date, prev_date}

        price = float(last["close"])
        prev_close = float(prev["close"])
        chg_pct = (price / prev_close - 1.0) * 100.0 if prev_close > 0 else 0.0
        ma20 = float(last["ma20"]) if not np.isnan(last["ma20"]) else None
        ma200 = float(last["ma200"]) if not np.isnan(last["ma200"]) else None
        ma200_chg10 = float(last["ma200_chg10_pct"]) if not np.isnan(last["ma200_chg10_pct"]) else None
        ma200_chg5 = float(last["ma200_chg5_pct"]) if not np.isnan(last["ma200_chg5_pct"]) else None
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
                "change_pct": round(chg_pct, 2),
                "ma20": round(ma20, 4) if ma20 else None,
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
                "applied_rule": rule_label,
                "signal": signal,
                "reason": reason,
                "priority": priority,
            }
        )

    items.sort(
        key=lambda x: (
            x["priority"],
            x["market"],
            min(
                abs(x["dist_short_upper_pct"]) if x["dist_short_upper_pct"] is not None else 999.0,
                abs(x["dist_long_upper_pct"]) if x["dist_long_upper_pct"] is not None else 999.0,
            ),
        )
    )
    counts = {
        "BUY": sum(1 for x in items if x["signal"] == "BUY"),
        "SELL": sum(1 for x in items if x["signal"] == "SELL"),
        "NEAR": sum(1 for x in items if x["signal"] == "NEAR"),
        "HOLD": sum(1 for x in items if x["signal"] == "HOLD"),
        "WATCH": sum(1 for x in items if x["signal"] == "WATCH"),
    }

    # Theme heat / momentum summary across all 10 themes
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
        "themes": theme_stats,
        "items": items,
    }


def format_full_alert_report(scan: dict[str, Any], include_near: bool = True) -> tuple[str, str, str, list[dict[str, Any]]]:
    """
    Build complete un-truncated report grouping ALL triggered stocks by Signal -> Market,
    headed by Top 3 Hot Themes.
    """
    items = scan["items"]
    buys = [x for x in items if x["signal"] == "BUY"]
    sells = [x for x in items if x["signal"] == "SELL"]
    nears = [x for x in items if x["signal"] == "NEAR"] if include_near else []
    triggered = buys + sells + nears

    date_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    title = f"[추세선 {len(items)}종목 알림 · {date_str}] 매수 {len(buys)} · 매도 {len(sells)} · 임박 {len(nears)}"

    sections: list[str] = [
        f"전략: {scan['strategy_name']}",
        f"요약: 🟢매수 {len(buys)} | 🔴매도 {len(sells)} | 🟡임박 {len(nears)} | 🔵보유 {scan['counts']['HOLD']} (총 {len(items)}종목)",
    ]

    hot_themes = scan.get("themes", [])[:3]
    if hot_themes:
        sections.append("\n🔥 오늘의 강세 테마 Top 3")
        for idx, th in enumerate(hot_themes, 1):
            sections.append(
                f"  {idx}. {th['label']}: 매수 {th['BUY']} · 임박 {th['NEAR']} · 보유 {th['HOLD']} (MA200 강세 {th['ma200_ok_pct']}%)"
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
                    f"  • [{th_name}] {it['name']}({it['symbol']}) {p_str} ({it['change_pct']:+.1f}%, MA200{arrow}) — {it['reason']}"
                )

    _add_group("🟢 신규 매수 신호", buys)
    _add_group("🔴 청산/매도 신호", sells)
    if include_near:
        _add_group("🟡 추세선 돌파 임박", nears)

    sections.append("\n🌐 웹 차트 바로가기: https://smartjd824.github.io/trendline-lab/")
    full_text = "\n".join(sections)

    # Concise macOS desktop summary (fits macOS banner cleanly)
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
    """Run scanner, save daily report file, and dispatch full alerts via Mac / Telegram / Discord."""
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

    # Always archive full daily report to data/reports/
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
