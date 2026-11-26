"""
읽기 쉬운 텔레그램 요약 메시지 (한 개 메시지 · 약 1,500자 목표).

구성 (중요한 순서):
  1. 오늘 할 일 한 줄 요약
  2. 시장 날씨 (☀️ 강세 / 🌤 보통 / 🌧 약세·현금 대기)
  3. 주문표 (시장별 매수·매도 + 언제 주문하는지)
  4. 보유 현황 (종목 수 · 현금 비중 · 수익 상위 3)
  5. 관심 종목 (돌파·임박) / 매도 점검 종목 — 각 최대 5개
  6. 후보 규칙 비교 한 줄
  7. 자세히 보기 링크
Telegram parse_mode=HTML 용으로 동적 텍스트는 모두 이스케이프한다.
"""

from __future__ import annotations

import html
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

KST = timezone(timedelta(hours=9))
SITE_URL = "https://smartjd824.github.io/trendline-lab/"
MKT = {"KOSPI": "🇰🇷 코스피", "KOSDAQ": "🇰🇷 코스닥", "US": "🇺🇸 미국", "CRYPTO": "🪙 코인"}
INDEX_OF = {"KOSPI": "^KS11", "KOSDAQ": "^KQ11", "US": "^GSPC"}
ORDER = ["KOSPI", "KOSDAQ", "US", "CRYPTO"]


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
        return "🌧 약세 · 현금 대기"
    return "☀️ 강세" if above200 >= 55 else "🌤 보통"


def build_brief(scan: dict[str, Any], session: str = "AFTERNOON") -> tuple[str, str]:
    """(제목, 본문HTML) 반환. 본문은 이미 HTML 이스케이프됨."""
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
    items = [x for x in scan.get("items", []) if x["market"] in markets]
    by_sym = {x["symbol"]: x for x in scan.get("items", [])}

    # ---------- 1. 오늘 할 일 ----------
    n_buy = sum(len(rmk[m]["orders_next_open"]["buy"]) for m in markets if m in rmk)
    n_sell = sum(len(rmk[m]["orders_next_open"]["sell"]) for m in markets if m in rmk)
    if n_buy or n_sell:
        todo = f"🔔 <b>오늘 할 일: 매수 {n_buy}건 · 매도 {n_sell}건</b> (아래 주문표 확인)"
    else:
        todo = "✅ <b>오늘 할 일: 주문 없음</b> — 그대로 유지하세요"
    lines = [f"<b>{e(title)}</b>", todo, ""]

    # ---------- 2. 시장 날씨 ----------
    lines.append("<b>🌤 시장 날씨</b>")
    for m in markets:
        if m not in rmk:
            continue
        r = rmk[m]
        above = regime.get(m, {}).get("ma200_above_pct", 0.0)
        ix = idx.get(INDEX_OF.get(m, ""))
        if m == "CRYPTO":
            ix = by_sym.get("BTC-USD")
            ix_txt = f"비트코인 {_price(ix['close'], 'USD')} ({ix['change_pct']:+.1f}%)" if ix else ""
        else:
            ix_txt = f"{e(ix['name'])} {ix['close']:,.0f} ({ix['change_pct']:+.1f}%)" if ix else ""
        lines.append(f"{MKT[m]} {_weather(r['regime_on'], above)} · {ix_txt} · 상승추세 종목 {above:.0f}%")
    lines.append("")

    # ---------- 3. 주문표 ----------
    lines.append("<b>📝 주문표</b> <i>(순환 모의 포트폴리오 · 현재 규칙)</i>")
    any_order = False
    for m in markets:
        if m not in rmk:
            continue
        o = rmk[m]["orders_next_open"]
        if not (o["buy"] or o["sell"]):
            continue
        any_order = True
        lines.append(f"{MKT[m]} — ⏰ {_when(m, session)}")
        if o["buy"]:
            lines.append("  🟢 매수: " + ", ".join(e(x["name"]) for x in o["buy"]))
        if o["sell"]:
            lines.append("  🔴 매도: " + ", ".join(e(x["name"]) for x in o["sell"]))
    if not any_order:
        lines.append("  주문 없음")
    lines.append("")

    # ---------- 4. 보유 현황 ----------
    lines.append("<b>💼 보유 현황</b>")
    for m in markets:
        if m not in rmk:
            continue
        r = rmk[m]
        hs = r["holdings"]
        if not hs:
            lines.append(f"{MKT[m]} 현금 100% (보유 없음)")
            continue
        top = sorted(hs, key=lambda h: -h["return_pct"])[:3]
        top_txt = ", ".join(f"{e(h['name'])} {h['return_pct']:+.0f}%" for h in top)
        lines.append(f"{MKT[m]} {len(hs)}종목 · 현금 {r['cash_pct']:.0f}% · 수익 상위: {top_txt}")
    lines.append("")

    # ---------- 5. 관심 / 매도 점검 ----------
    buys = [x for x in items if x["signal"] == "BUY"]
    nears = sorted([x for x in items if x["signal"] == "NEAR"], key=lambda x: min(v for v in (x.get("dist_short_upper_pct"), x.get("dist_long_upper_pct"), 99) if v is not None))
    sells = [x for x in items if x["signal"] == "SELL"]
    watch = [(x, "오늘 상단선 돌파") for x in buys] + [
        (x, f"상단선까지 {min(v for v in (x.get('dist_short_upper_pct'), x.get('dist_long_upper_pct'), 99) if v is not None):.1f}%") for x in nears
    ]
    if watch:
        lines.append("<b>👀 관심 종목</b> <i>(추세선 돌파·임박)</i>")
        for x, why in watch[:5]:
            lines.append(f"• {e(x['name'])} {_price(x['close'], x['currency'])} ({x['change_pct']:+.1f}%) — {e(why)}")
        if len(watch) > 5:
            lines.append(f"  …외 {len(watch) - 5}종목")
        lines.append("")
    if sells:
        lines.append("<b>⚠️ 보유 중이면 매도 점검</b>")
        for x in sells[:5]:
            reason = x["reason"].split("] ", 1)[-1].split(" (")[0]
            lines.append(f"• {e(x['name'])} — {e(reason)}")
        if len(sells) > 5:
            lines.append(f"  …외 {len(sells) - 5}종목")
        lines.append("")

    # ---------- 6. 후보 규칙 비교 ----------
    if cmp_:
        started = any(r.get("since_freeze") for m in markets if m in cmp_ for r in cmp_[m]["rows"])
        basis = "고정 후" if started else "올해"
        lines.append(f"<b>🧪 규칙 비교</b> <i>({basis} 수익률 · 고정 후 성과가 진짜 검증)</i>")
        short = {"현재 규칙": "현재", "A 기울기": "기울기", "C 정배열": "정배열"}
        for m in markets:
            if m not in cmp_:
                continue
            c = cmp_[m]
            key = "since_freeze" if started else "ytd"
            parts = []
            for r in c["rows"]:
                v = r.get(key)
                parts.append(f"{short.get(r['label'], r['label'])} {v['ret']:+.1f}%" if v else f"{short.get(r['label'], r['label'])} -")
            b = c["bnh"].get(key)
            parts.append(f"단순보유 {b['ret']:+.1f}%" if b else "단순보유 -")
            lines.append(f"{MKT[m]} " + " · ".join(parts))
        lines.append("")

    lines.append(f'🔗 <a href="{SITE_URL}">자세히 보기 (차트·전체 종목)</a>')
    lines.append("<i>※ 모의 투자 신호이며 투자 권유가 아닙니다.</i>")
    from backend.scanner import to_korean  # MA200 → 200일선 등 공용 한국어 용어 변환

    return title, to_korean("\n".join(lines))
