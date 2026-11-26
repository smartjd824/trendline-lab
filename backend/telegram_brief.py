"""
읽기 쉬운 텔레그램 요약 메시지 — '다 보여주되 한 줄씩 쉽게'.

구성 (중요한 순서):
  1. 🔔 오늘 할 일 (내 보유종목 점검 · 모의 주문 건수)
  2. 💼 내 보유종목 (웹에 등록한 종목: 현재가 · 수익률 · 상태)  ← MY_HOLDINGS_JSON
  3. 🌍 지수 흐름 (시장별 날씨 + 나스닥·반도체·금·VIX·환율·금리)
  4. 📝 모의 포트폴리오 주문표
  5. 📈 추세선 돌파 임박 / 신규 돌파
  6. 🏆 상승확률 상위 3 (코스피 · 코스닥 · 미국 · 코인)
  7. 🔥 강세 테마 상위 3
  8. ⚠️ 매도 점검 (추세 이탈)
  9. 🧪 규칙 비교
 10. 🔗 자세히 보기
Telegram parse_mode=HTML 용 — 동적 텍스트는 모두 이스케이프.
"""

from __future__ import annotations

import html
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

KST = timezone(timedelta(hours=9))
SITE_URL = "https://smartjd824.github.io/trendline-lab/"
MKT = {"KOSPI": "🇰🇷 코스피", "KOSDAQ": "🇰🇷 코스닥", "US": "🇺🇸 미국", "CRYPTO": "🪙 코인"}
INDEX_OF = {"KOSPI": "^KS11", "KOSDAQ": "^KQ11", "US": "^GSPC"}
EXTRA_INDICES = ["^NDX", "^SOX", "^DJI", "GC=F"]  # 시장 날씨에 안 나온 주요 지수
MACRO = ["^VIX", "KRW=X", "^TNX"]
ORDER = ["KOSPI", "KOSDAQ", "US", "CRYPTO"]
ARROW = {"up": "↗", "flat": "→", "down": "↘"}


def e(x: Any) -> str:
    return html.escape(str(x), quote=False)


def _price(v: float, cur: str) -> str:
    if cur == "KRW":
        return f"{round(v):,}원"
    if abs(v) >= 100:
        return f"${v:,.0f}"
    if abs(v) >= 1:
        return f"${v:,.2f}"
    return f"${v:.4f}"


def _us_open_kst() -> str:
    dst = datetime.now(ZoneInfo("America/New_York")).utcoffset() == timedelta(hours=-4)
    return "22:30" if dst else "23:30"


def _when(mkt: str, session: str) -> str:
    if mkt in ("KOSPI", "KOSDAQ"):
        return "오늘 종가 동시호가(15:20~15:30) 또는 내일 09:00 시가" if session == "AFTERNOON" else "오늘 09:00 시가"
    if mkt == "US":
        return f"오늘 밤 {_us_open_kst()} 개장"
    return "지금 바로"


def _weather(regime_on: bool, above200: float) -> str:
    if not regime_on:
        return "🌧 약세(현금 대기)"
    return "☀️ 강세" if above200 >= 55 else "🌤 보통"


def _near_dist(x: dict) -> float:
    vals = [v for v in (x.get("dist_short_upper_pct"), x.get("dist_long_upper_pct")) if v is not None]
    return min(vals) if vals else 99.0


# ----------------------------------------------------------------------------- 내 보유종목
def load_holdings() -> list[dict]:
    """
    웹 '내 보유종목'의 백업 JSON({"holdings":[...]}).
      1순위: 환경변수 MY_HOLDINGS_JSON (GitHub Secrets — 비공개)
      2순위: data/my_holdings.json (내 컴퓨터, git에 안 올라감)
    """
    raw = os.environ.get("MY_HOLDINGS_JSON", "").strip()
    if not raw:
        p = Path(__file__).resolve().parent.parent / "data" / "my_holdings.json"
        raw = p.read_text(encoding="utf-8") if p.exists() else ""
    if not raw:
        return []
    try:
        obj = json.loads(raw)
        hs = obj.get("holdings", obj) if isinstance(obj, dict) else obj
        return [h for h in hs if isinstance(h, dict) and h.get("symbol")]
    except Exception:
        return []


def holding_status(h: dict, it: dict) -> tuple[int, str, str, float]:
    """웹(app.js evaluateHoldingStatus)과 같은 규칙 + 20일선 기울기 꺾임. (경보단계, 아이콘라벨, 설명, 수익률%)"""
    avg = float(h.get("avgPrice") or 0) or it["close"]
    pnl = (it["close"] / avg - 1) * 100 if avg > 0 else 0.0
    tp = it.get("trade_plan") or {}
    cs = h.get("customStop")
    stop = float(cs) if cs not in (None, "", 0) else (tp.get("stop_loss") or avg * 0.92)
    target1 = tp.get("target_1") or avg * 1.18
    cur = it.get("currency", "USD")
    if it["close"] <= stop:
        return 3, "🔴 손절선 도달", f"손절가 {_price(stop, cur)} 하회", pnl
    if it.get("signal") == "SELL" or (not it.get("above_ma200", True) and not it.get("above_ma20", True)):
        why = it["reason"].split("] ", 1)[-1].split(" (")[0] if it.get("signal") == "SELL" else "200일선·20일선 모두 아래"
        return 3, "🔴 매도 점검", why, pnl
    slope = it.get("ma20_chg5_pct")
    if slope is not None and slope < -2.0:
        return 2, "🟠 주의", f"20일선이 5일간 {slope:.1f}% 꺾임", pnl
    if not it.get("above_ma20", True) and pnl < 0:
        return 2, "🟠 주의", "20일선 아래 + 손실 구간", pnl
    rsi = it.get("rsi14")
    if (it["close"] >= target1 and pnl >= 10) or (rsi is not None and rsi >= 76 and pnl >= 12):
        return 1, "🎯 익절 검토", f"1차 목표가 {_price(target1, cur)} 도달" if it["close"] >= target1 else f"과열(RSI {rsi:.0f})", pnl
    return 0, "🟢 유지", "추세 유지 중", pnl


# ----------------------------------------------------------------------------- 본문
def build_brief(scan: dict[str, Any], session: str = "AFTERNOON", holdings: list[dict] | None = None) -> tuple[str, str]:
    """(제목, 본문HTML). 본문은 이미 HTML 이스케이프됨."""
    holdings = load_holdings() if holdings is None else holdings
    markets = ["US", "CRYPTO"] if session == "MORNING" else ORDER
    now = datetime.now(KST)
    wd = "월화수목금토일"[now.weekday()]
    kind = "아침 리포트 (미국·코인)" if session == "MORNING" else "오후 리포트 (한국·종합)"
    title = f"📊 {now:%m/%d}({wd}) {kind}"

    rot = scan.get("rotation") or {}
    rmk = rot.get("markets", {})
    cmp_ = (rot.get("compare") or {}).get("markets", {})
    regime = scan.get("market_regime", {})
    idx = {x["symbol"]: x for x in scan.get("indices", [])}
    all_items = scan.get("items", [])
    by_sym = {x["symbol"]: x for x in all_items}
    items = [x for x in all_items if x["market"] in markets]

    # ---------- 내 보유종목 평가 ----------
    my_rows = []
    for h in holdings:
        it = by_sym.get(h["symbol"]) or idx.get(h["symbol"])
        if not it:
            continue
        lvl, lab, why, pnl = holding_status(h, it)
        my_rows.append((lvl, lab, why, pnl, it))
    my_rows.sort(key=lambda r: (-r[0], -r[3]))
    my_alerts = sum(1 for r in my_rows if r[0] >= 2)

    # ---------- 1. 오늘 할 일 ----------
    n_buy = sum(len(rmk[m]["orders_next_open"]["buy"]) for m in markets if m in rmk)
    n_sell = sum(len(rmk[m]["orders_next_open"]["sell"]) for m in markets if m in rmk)
    todo = []
    if my_alerts:
        todo.append(f"내 보유종목 점검 {my_alerts}건")
    if n_buy or n_sell:
        todo.append(f"모의 주문 매수 {n_buy} · 매도 {n_sell}")
    head = f"🔔 <b>오늘 할 일: {' · '.join(todo)}</b>" if todo else "✅ <b>오늘 할 일: 특별한 조치 없음</b> — 그대로 유지하세요"
    L = [f"<b>{e(title)}</b>", head, ""]

    # ---------- 2. 내 보유종목 ----------
    L.append("<b>💼 내 보유종목</b>")
    if my_rows:
        for lvl, lab, why, pnl, it in my_rows:
            L.append(f"{lab} {e(it['name'])} {_price(it['close'], it.get('currency', 'USD'))} · 수익 {pnl:+.1f}% — {e(why)}")
    elif holdings:
        L.append("  등록 종목의 시세를 찾지 못했습니다 (종목 구성에서 빠졌을 수 있음)")
    else:
        L.append("  <i>웹 '내 보유종목'을 연결하면 여기에 매일 점검 결과가 나옵니다</i>")
    L.append("")

    # ---------- 3. 지수 흐름 ----------
    L.append("<b>🌍 지수 흐름</b> <i>(날씨 = 지수 추세 필터 · %는 200일선 위 종목 비율)</i>")
    for m in ORDER:  # 날씨는 항상 4개 시장 모두 (전체 흐름 파악)
        if m not in rmk:
            continue
        above = regime.get(m, {}).get("ma200_above_pct", 0.0)
        if m == "CRYPTO":
            x = by_sym.get("BTC-USD")
            ix = f"비트코인 {_price(x['close'], 'USD')} ({x['change_pct']:+.1f}%)" if x else ""
        else:
            x = idx.get(INDEX_OF[m])
            ix = f"{e(x['name'])} {x['close']:,.0f} ({x['change_pct']:+.1f}%, 1개월 {x['ret20_pct']:+.1f}%) {ARROW.get(x['ma200_state'], '')}" if x else ""
        L.append(f"{MKT[m]} {_weather(rmk[m]['regime_on'], above)} · {ix} · {above:.0f}%")
    extra = []
    for s in EXTRA_INDICES:
        x = idx.get(s)
        if x:
            extra.append(f"{e(x['name'])} {x['change_pct']:+.1f}%{ARROW.get(x['ma200_state'], '')}")
    if extra:
        L.append("  " + " · ".join(extra))
    macro = []
    for s in MACRO:
        x = idx.get(s)
        if x:
            unit = x.get("unit", "")
            val = f"{x['close']:,.2f}{'%' if unit == '%' else ''}" if unit != "원" else f"{x['close']:,.0f}원"
            macro.append(f"{e(x['name'])} {val} {e(x.get('status_label', ''))}")
    if macro:
        L.append("  " + " · ".join(macro))
    L.append("  <i>↗ 200일선 상승 · → 평평 · ↘ 하락</i>")
    L.append("")

    # ---------- 4. 모의 주문표 ----------
    L.append("<b>📝 모의 포트폴리오 주문</b> <i>(현재 규칙)</i>")
    any_order = False
    for m in markets:
        if m not in rmk:
            continue
        r = rmk[m]
        o = r["orders_next_open"]
        held = f"보유 {len(r['holdings'])}/{r['slots']} · 현금 {r['cash_pct']:.0f}%"
        if o["buy"] or o["sell"]:
            any_order = True
            L.append(f"{MKT[m]} ⏰ {_when(m, session)} ({held})")
            if o["buy"]:
                L.append("  🟢 매수: " + ", ".join(e(x["name"]) for x in o["buy"]))
            if o["sell"]:
                L.append("  🔴 매도: " + ", ".join(e(x["name"]) for x in o["sell"]))
        else:
            L.append(f"{MKT[m]} 주문 없음 ({held})")
    L.append("")

    # ---------- 5. 추세선 돌파 임박 ----------
    buys = [x for x in items if x["signal"] == "BUY"]
    nears = sorted([x for x in items if x["signal"] == "NEAR"], key=_near_dist)
    L.append("<b>📈 추세선 돌파 임박</b> <i>(하락 상단선까지 남은 거리)</i>")
    if buys or nears:
        for x in buys[:5]:
            L.append(f"🚀 {e(x['name'])} {_price(x['close'], x['currency'])} ({x['change_pct']:+.1f}%) — 오늘 돌파!")
        for x in nears[: max(0, 8 - len(buys[:5]))]:
            L.append(f"• {e(x['name'])} {_price(x['close'], x['currency'])} ({x['change_pct']:+.1f}%) — {_near_dist(x):.1f}% 남음")
    else:
        L.append("  해당 종목 없음")
    L.append("")

    # ---------- 6. 상승확률 상위 3 (시장별) ----------
    L.append("<b>🏆 상승확률 상위 3</b> <i>(추세·이평·RSI·거래량 종합 점수)</i>")
    for m in markets:
        top = sorted([x for x in items if x["market"] == m], key=lambda x: -x["upside_prob"])[:3]
        if top:
            L.append(f"{MKT[m]} " + " · ".join(f"{e(x['name'])} {x['upside_prob']:.0f}%" for x in top))
    L.append("")

    # ---------- 7. 강세 테마 상위 3 ----------
    th = scan.get("themes", [])[:3]
    if th:
        L.append("<b>🔥 강세 테마 상위 3</b>")
        for i, t in enumerate(th, 1):
            L.append(f"{i}. {e(t['label'])} — 상승추세 {t['ma200_ok_pct']:.0f}% · 돌파·임박 {t['BUY'] + t['NEAR']}종목")
        L.append("")

    # ---------- 8. 매도 점검 ----------
    sells = [x for x in items if x["signal"] == "SELL"]
    if sells:
        L.append("<b>⚠️ 추세 이탈 (보유 중이면 매도 점검)</b>")
        for x in sells[:6]:
            reason = x["reason"].split("] ", 1)[-1].split(" (")[0]
            L.append(f"• {e(x['name'])} — {e(reason)}")
        if len(sells) > 6:
            L.append(f"  …외 {len(sells) - 6}종목")
        L.append("")

    # ---------- 9. 규칙 비교 ----------
    if cmp_:
        started = any(r.get("since_freeze") for m in markets if m in cmp_ for r in cmp_[m]["rows"])
        key = "since_freeze" if started else "ytd"
        L.append(f"<b>🧪 규칙 비교</b> <i>({'고정 후' if started else '올해'} 수익률 · 고정 후 성과가 진짜 검증)</i>")
        short = {"현재 규칙": "현재", "A 기울기": "기울기", "C 정배열": "정배열"}
        for m in markets:
            if m not in cmp_:
                continue
            c = cmp_[m]
            parts = [f"{short.get(r['label'], r['label'])} {r[key]['ret']:+.1f}%" if r.get(key) else f"{short.get(r['label'], r['label'])} -" for r in c["rows"]]
            b = c["bnh"].get(key)
            parts.append(f"단순보유 {b['ret']:+.1f}%" if b else "단순보유 -")
            L.append(f"{MKT[m]} " + " · ".join(parts))
        L.append("")

    L.append(f'🔗 <a href="{SITE_URL}">자세히 보기 (차트·전체 종목·내 보유종목)</a>')
    L.append("<i>※ 모의 투자 신호이며 투자 권유가 아닙니다.</i>")
    from backend.scanner import to_korean  # MA200 → 200일선 등 공용 한국어 용어

    return title, to_korean("\n".join(L))
