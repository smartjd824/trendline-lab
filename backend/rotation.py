"""
순환 모의 포트폴리오 (Paper Rotation Portfolio).

ROTATION_RULES(config.py, 2026-11-26 고정)를 ROTATION_START부터 오늘까지 매일 동일하게 재생해서
  * 지금 보유 중인 종목 (진입일·진입가·수익률·비중)
  * 다음 거래일 시가에 실행할 매수/매도 주문
  * 시장 레짐(지수 추세선 필터) 상태
  * 누적·올해 성과 vs 동일가중 단순보유
를 계산한다. 규칙이 고정되어 있으므로 같은 데이터 → 항상 같은 결과(재현 가능).
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from config import ASSET_MAP, ROTATION_CANDIDATES, ROTATION_FREEZE_DATE, ROTATION_RULES, ROTATION_START
from strategy_lab import COST, Cfg, Lab, bnh, simulate, stats


def _perf(r: np.ndarray, ppy: int) -> dict[str, float]:
    st = stats(r, ppy)
    return {k: round(v, 2) for k, v in st.items()}


def _perf_mask(r: np.ndarray, mask: np.ndarray, ppy: int) -> dict[str, float] | None:
    if mask.sum() < 1:
        return None
    return _perf(r[mask], ppy)


def compare_candidates(lab: Lab, end: str = "2099-12-31") -> dict[str, Any]:
    """후보 규칙(ROTATION_CANDIDATES)별 모의 성과 비교 — 고정일 이후 성과가 실제 검증."""
    out: dict[str, Any] = {"freeze_date": ROTATION_FREEZE_DATE, "candidates": [
        {"id": cid, "label": c["label"], "desc": c["desc"]} for cid, c in ROTATION_CANDIDATES.items()], "markets": {}}
    for mkt, spec in ROTATION_RULES.items():
        if not lab.by_mkt.get(mkt):
            continue
        p = lab.panel(mkt, ROTATION_START, end)
        cal, syms, ppy = p["cal"], p["syms"], p["ppy"]
        bh_r = bnh(p, COST[mkt])
        year = str(cal[-1])[:4]
        ytd = np.array([str(d).startswith(year) for d in cal])
        fwd = cal >= ROTATION_FREEZE_DATE
        rows = []
        for cid, c in ROTATION_CANDIDATES.items():
            cfg = Cfg.parse(c["rules"][mkt])
            sim = simulate(p, cfg, spec["slots"], COST[mkt], return_state=True, liquidate_end=False)
            st = sim["state"]
            nm = lambda idx: [ASSET_MAP.get(syms[j], {"name": syms[j]})["name"] for j in idx]
            rows.append({
                "id": cid, "label": c["label"], "rule": c["rules"][mkt],
                "since_start": _perf(sim["r"], ppy), "ytd": _perf(sim["r"][ytd], ppy),
                "since_freeze": _perf_mask(sim["r"], fwd, ppy), "forward_days": int(fwd.sum()),
                "holdings": len(st["held"]), "cash_pct": round(st["cash_weight"] * 100, 1),
                "buy_next_open": nm(st["buy_next_open"]), "sell_next_open": nm(st["sell_next_open"]),
            })
        out["markets"][mkt] = {
            "slots": spec["slots"], "as_of": str(cal[-1]), "rows": rows,
            "bnh": {"since_start": _perf(bh_r, ppy), "ytd": _perf(bh_r[ytd], ppy), "since_freeze": _perf_mask(bh_r, fwd, ppy)},
        }
    return out


def compute_rotation(ind_map: dict[str, pd.DataFrame], end: str = "2099-12-31") -> dict[str, Any]:
    lab = Lab(ind_map)
    out: dict[str, Any] = {"start": ROTATION_START, "markets": {}}
    out["compare"] = compare_candidates(lab, end)
    for mkt, spec in ROTATION_RULES.items():
        if not lab.by_mkt.get(mkt):
            continue
        cfg = Cfg.parse(spec["rule"])
        p = lab.panel(mkt, ROTATION_START, end)
        cal, syms, fp = p["cal"], p["syms"], p["F"]
        sim = simulate(p, cfg, spec["slots"], COST[mkt], return_state=True, liquidate_end=False)
        st = sim["state"]
        ppy = p["ppy"]
        bh_r = bnh(p, COST[mkt])

        # 올해 성과 (YTD)
        year = str(cal[-1])[:4]
        ytd_mask = np.array([str(d).startswith(year) for d in cal])
        last_close = pd.DataFrame(fp.c).ffill().to_numpy()[-1]

        holdings = []
        for j, ti, px, w in sorted(st["held"], key=lambda x: -x[3]):
            sym = syms[j]
            a = ASSET_MAP.get(sym, {"name": sym, "theme": "", "currency": "USD"})
            holdings.append({
                "symbol": sym, "name": a["name"], "theme": a.get("theme", ""), "currency": a.get("currency", "USD"),
                "entry_date": str(cal[ti]), "entry_price": round(px, 6), "close": round(float(last_close[j]), 6),
                "return_pct": round((last_close[j] / px - 1) * 100, 2), "weight_pct": round(w * 100, 1),
                "sell_next_open": j in st["sell_next_open"],
            })

        def _names(idx: list[int]) -> list[dict[str, str]]:
            return [{"symbol": syms[j], "name": ASSET_MAP.get(syms[j], {"name": syms[j]})["name"]} for j in idx]

        recent = [
            {"date": str(cal[t]), "action": act, "symbol": syms[j], "name": ASSET_MAP.get(syms[j], {"name": syms[j]})["name"], "price": round(px, 6)}
            for t, j, act, px in st["log"][-20:]
        ][::-1]
        regime_now = bool(p["regimes"][cfg.regime_def][-1]) if cfg.regime != "--" else True
        out["markets"][mkt] = {
            "rule": spec["rule"], "label": spec["label"], "basis": spec["basis"], "slots": spec["slots"],
            "as_of": str(cal[-1]),
            "regime_on": regime_now,
            "cash_pct": round(st["cash_weight"] * 100, 1),
            "holdings": holdings,
            "orders_next_open": {"buy": _names(st["buy_next_open"]), "sell": _names(st["sell_next_open"])},
            "recent_trades": recent,
            "perf_since_start": _perf(sim["r"], ppy),
            "bnh_since_start": _perf(bh_r, ppy),
            "perf_ytd": _perf(sim["r"][ytd_mask], ppy),
            "bnh_ytd": _perf(bh_r[ytd_mask], ppy),
            "trades": sim["trades"],
        }
    return out


def format_rotation_report(rot: dict[str, Any], markets: list[str] | None = None) -> list[str]:
    """텔레그램/리포트용 한글 요약 라인. markets 지정 시 해당 시장만."""
    labels = {"KOSPI": "🇰🇷 코스피", "KOSDAQ": "🚀 코스닥", "US": "🇺🇸 미국", "CRYPTO": "🪙 코인"}
    lines = [f"\n🔄 순환 모의 포트폴리오 (규칙 고정 2026-11-26 · {rot['start']}~ 재생 · 다음날 시가 체결 가정)"]
    for mkt, m in rot.get("markets", {}).items():
        if markets and mkt not in markets:
            continue
        ps, bs = m["perf_since_start"], m["bnh_since_start"]
        py, by = m["perf_ytd"], m["bnh_ytd"]
        reg = "켜짐(투자)" if m["regime_on"] else "꺼짐(현금화)"
        lines.append(
            f"  {labels.get(mkt, mkt)} [{m['label']}] 지수필터 {reg} · 보유 {len(m['holdings'])}/{m['slots']} · 현금 {m['cash_pct']:.0f}%"
        )
        lines.append(
            f"    누적 {ps['ret']:+.0f}% (단순보유 {bs['ret']:+.0f}%) · 올해 {py['ret']:+.1f}% (단순보유 {by['ret']:+.1f}%) · MDD {ps['mdd']:.0f}%"
        )
        buys = ", ".join(x["name"] for x in m["orders_next_open"]["buy"]) or "없음"
        sells = ", ".join(x["name"] for x in m["orders_next_open"]["sell"]) or "없음"
        lines.append(f"    ▶ 다음 시가 매수: {buys}")
        lines.append(f"    ▶ 다음 시가 매도: {sells}")
        top = ", ".join(f"{h['name']}({h['return_pct']:+.0f}%)" for h in m["holdings"][:6])
        if top:
            lines.append(f"    보유: {top}" + (" …" if len(m["holdings"]) > 6 else ""))

    cmp_ = rot.get("compare")
    if cmp_ and cmp_.get("markets"):
        lines.append(f"\n🧪 후보 규칙 모의 비교 (고정 {cmp_['freeze_date']} · '고정후'가 실제 검증 성과)")
        for mkt, m in cmp_["markets"].items():
            if markets and mkt not in markets:
                continue
            b = m["bnh"]
            bf = f"{b['since_freeze']['ret']:+.1f}%" if b["since_freeze"] else "-"
            lines.append(f"  {labels.get(mkt, mkt)} (단순보유 고정후 {bf} · 올해 {b['ytd']['ret']:+.1f}%)")
            for r in m["rows"]:
                sf = f"{r['since_freeze']['ret']:+.1f}%({r['forward_days']}일)" if r["since_freeze"] else "시작 전"
                orders = []
                if r["buy_next_open"]:
                    orders.append("매수 " + ", ".join(r["buy_next_open"][:4]) + ("…" if len(r["buy_next_open"]) > 4 else ""))
                if r["sell_next_open"]:
                    orders.append("매도 " + ", ".join(r["sell_next_open"][:4]) + ("…" if len(r["sell_next_open"]) > 4 else ""))
                lines.append(
                    f"    · {r['label']}: 고정후 {sf} · 올해 {r['ytd']['ret']:+.1f}% · 누적 {r['since_start']['ret']:+.0f}% · MDD {r['since_start']['mdd']:.0f}% · 보유 {r['holdings']}"
                    + (f" · {' / '.join(orders)}" if orders else "")
                )
    return lines
