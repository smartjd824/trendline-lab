#!/usr/bin/env python3
"""
종목 구성(Universe) 자동 생성.

후보 풀 = config.LEGACY_ASSETS(기존 250) + universe_pool.NEW_CANDIDATES(신규 테마 후보)
규칙   = config.UNIVERSE_RULES (데이터 일수 · 거래대금 하한 · 시장별 최대 개수) + 가격 정밀도 · 최신 데이터 여부
결과   = universe.json (서비스 종목) + 제외 사유 리포트

사용:  uv run python build_universe.py            # 데이터 갱신 후 생성
       uv run python build_universe.py --no-sync  # 캐시된 데이터로 생성
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime

import pandas as pd

from config import LEGACY_ASSETS, UNIVERSE_PATH, UNIVERSE_RULES
from backend.data_loader import fetch_and_cache_symbols, is_low_precision, load_ohlcv
from universe_pool import EXCLUDE_ALWAYS, LEGACY_THEME_MAP, NEW_CANDIDATES, SYMBOL_THEME_OVERRIDE, THEMES_V2

CUR = {"KOSPI": "KRW", "KOSDAQ": "KRW", "US": "USD", "CRYPTO": "USD"}


def candidate_pool() -> list[dict]:
    pool: dict[str, dict] = {}
    for a in LEGACY_ASSETS:
        theme = SYMBOL_THEME_OVERRIDE.get(a["symbol"], LEGACY_THEME_MAP.get(a["theme"], a["theme"]))
        pool[a["symbol"]] = {**a, "theme": theme, "source": "기존"}
    for sym, name, mkt, theme in NEW_CANDIDATES:
        if sym not in pool:
            pool[sym] = {"symbol": sym, "name": name, "market": mkt, "theme": theme, "currency": CUR[mkt], "source": "신규"}
    return list(pool.values())


def evaluate(a: dict, latest: str) -> tuple[float, str | None]:
    if a["symbol"] in EXCLUDE_ALWAYS:
        return 0.0, EXCLUDE_ALWAYS[a["symbol"]]
    df = load_ohlcv(a["symbol"], auto_fetch=False)
    if df.empty:
        return 0.0, "데이터 없음"
    t = df.tail(60)
    liq = float(t["volume"].median()) if a["market"] == "CRYPTO" else float((t["close"] * t["volume"]).median())
    if len(df) < UNIVERSE_RULES["min_bars"]:
        return liq, f"데이터 기간 부족 ({len(df)}일 < {UNIVERSE_RULES['min_bars']}일, {df['date'].iloc[0]} 상장)"
    if (pd.Timestamp(latest) - pd.Timestamp(df["date"].iloc[-1])).days > 7:
        return liq, f"최근 데이터 끊김 (마지막 {df['date'].iloc[-1]})"
    if is_low_precision(df):
        return liq, "가격 정밀도 부족 (Yahoo 가격 뭉개짐)"
    floor = UNIVERSE_RULES["min_liquidity"][a["market"]]
    if liq < floor:
        unit, div = ("억원", 1e8) if a["currency"] == "KRW" else ("백만$", 1e6)
        return liq, f"거래대금 부족 ({liq / div:,.1f}{unit} < {floor / div:,.0f}{unit})"
    return liq, None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-sync", action="store_true")
    args = ap.parse_args()
    pool = candidate_pool()
    if not args.no_sync:
        fetch_and_cache_symbols([a["symbol"] for a in pool])
    latest = max(load_ohlcv(s, auto_fetch=False)["date"].iloc[-1] for s in ("AAPL", "005930.KS", "BTC-USD"))

    kept, dropped = [], []
    for a in pool:
        liq, why = evaluate(a, latest)
        (dropped if why else kept).append({**a, "liquidity": liq, "reason": why})

    final = []
    for mkt, cap in UNIVERSE_RULES["max_per_market"].items():
        xs = sorted([a for a in kept if a["market"] == mkt], key=lambda a: -a["liquidity"])
        final += xs[:cap]
        dropped += [{**a, "reason": f"시장별 최대 {cap}개 초과 (거래대금 순위 밖)"} for a in xs[cap:]]

    used = {a["theme"] for a in final}
    themes = [t for t in THEMES_V2 if t["id"] in used]
    assets = [{k: a[k] for k in ("symbol", "name", "market", "theme", "currency")} for a in final]
    UNIVERSE_PATH.write_text(
        json.dumps(
            {
                "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "rules": UNIVERSE_RULES,
                "themes": themes,
                "assets": assets,
                "excluded": [{"symbol": d["symbol"], "name": d["name"], "market": d["market"], "theme": d["theme"], "reason": d["reason"]} for d in dropped],
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )

    # ---- 한글 리포트 ----
    print(f"후보 {len(pool)}개 → 선정 {len(final)}개 / 제외 {len(dropped)}개  (universe.json 저장)")
    df = pd.DataFrame(final)
    print("\n[시장별 선정 수]", df["market"].value_counts().to_dict())
    print("\n[테마 × 시장]")
    print(pd.crosstab(df["theme"], df["market"]).to_string())
    print("\n[신규 편입]")
    for a in [a for a in final if a["source"] == "신규"]:
        print(f"  {a['market']:6} {a['theme']:10} {a['name']}")
    print("\n[제외 종목과 사유]")
    for d in sorted(dropped, key=lambda d: (d["market"], d["theme"])):
        print(f"  {d['market']:6} {d['theme']:10} {d['name']:24} — {d['reason']}")


if __name__ == "__main__":
    main()
