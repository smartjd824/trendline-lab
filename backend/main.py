"""FastAPI application serving the 30-asset Trendline Research Lab & Alert Service."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from config import ASSET_MAP, ASSETS, BASE_DIR, INDEX_MAP, INDICES, THEMES, load_settings, save_settings
from backend.backtester import (
    DEFAULT_CUSTOM_PARAMS,
    EXIT_RULES,
    STRATEGIES,
    clear_indicator_cache,
    completed_bars_only_setting,
    get_cached_indicators,
    run_backtest_single,
    run_exit_rule_comparison,
    run_research_matrix,
)
from backend.data_loader import drop_incomplete_last_bar, fetch_and_cache_symbols, get_cache_status, load_ohlcv
from backend.indicators import extract_current_trendlines
from backend.notifier import dispatch_alerts
from backend.scanner import scan_all_assets, scan_and_notify

FRONTEND_DIR = BASE_DIR / "frontend"

app = FastAPI(title="MA20·MA200 추세선 30종목 연구실 & 신호 알림 서비스", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class CustomResearchRequest(BaseModel):
    short_window: int = 45
    long_window: int = 180
    price_source: str = "wick"
    scale_mode: str = "linear"
    fee_rate: float = 0.001
    custom_params: dict[str, Any] = DEFAULT_CUSTOM_PARAMS


class SettingsPayload(BaseModel):
    short_window: int = 45
    long_window: int = 180
    price_source: str = "wick"
    scale_mode: str = "linear"
    fee_rate: float = 0.001
    near_threshold_pct: float = 3.0
    active_strategy: str = "S5"
    exit_rule: str = "default"
    completed_bars_only: bool = True
    alerts: dict[str, Any]


@app.get("/")
def serve_index():
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/api/assets")
def api_assets():
    return {
        "assets": ASSETS,
        "themes": THEMES,
        "strategies": list(STRATEGIES.values()),
        "exit_rules": list(EXIT_RULES.values()),
        "cache": get_cache_status(),
        "settings": load_settings(),
        "default_custom_params": DEFAULT_CUSTOM_PARAMS,
    }


@app.post("/api/sync")
def api_sync(force: bool = False):
    res = fetch_and_cache_symbols(force=force)
    clear_indicator_cache()
    return {"sync": res, "cache": get_cache_status()}


@app.get("/api/chart/{symbol}")
def api_chart(
    symbol: str,
    strategy_id: str = Query("S3"),
    exit_rule: str = Query("default"),
    years: int = Query(6, ge=1, le=7),
    short_window: int = Query(45, ge=15, le=120),
    long_window: int = Query(180, ge=60, le=360),
    price_source: str = Query("wick"),
    scale_mode: str = Query("linear"),
    fee_rate: float = Query(0.001, ge=0.0, le=0.02),
):
    if symbol not in ASSET_MAP and symbol not in INDEX_MAP:
        raise HTTPException(status_code=404, detail=f"Unknown symbol: {symbol}")

    df = load_ohlcv(symbol, auto_fetch=True)
    if df.empty:
        raise HTTPException(status_code=503, detail=f"Failed to load data for {symbol}")
    if completed_bars_only_setting():
        df = drop_incomplete_last_bar(symbol, df)

    ind = get_cached_indicators(
        symbol,
        df=df,
        short_window=short_window,
        long_window=long_window,
        price_source=price_source,
        scale_mode=scale_mode,
    )
    bt = run_backtest_single(
        symbol,
        ind,
        strategy_id=strategy_id,
        years=years,
        fee_rate=fee_rate,
        include_series=True,
        exit_rule=exit_rule,
    )
    trendlines = extract_current_trendlines(
        ind,
        short_window=short_window,
        long_window=long_window,
        price_source=price_source,
        scale_mode=scale_mode,
    )

    # Display window: selected years (or full available)
    end_dt = ind["date_dt"].iloc[-1]
    start_dt = end_dt - __import__("pandas").DateOffset(years=years)
    vis = ind[ind["date_dt"] >= start_dt].copy()
    if len(vis) < 60:
        vis = ind.tail(250).copy()

    candles = []
    ma20_series = []
    ma200_series = []
    volumes = []

    for row in vis.itertuples(index=False):
        t = str(row.date)
        candles.append(
            {
                "time": t,
                "open": round(float(row.open), 4),
                "high": round(float(row.high), 4),
                "low": round(float(row.low), 4),
                "close": round(float(row.close), 4),
            }
        )
        is_up = float(row.close) >= float(row.open)
        volumes.append(
            {
                "time": t,
                "value": float(row.volume),
                "color": "rgba(38, 166, 154, 0.32)" if is_up else "rgba(239, 83, 80, 0.32)",
            }
        )
        if not np.isnan(row.ma20):
            ma20_series.append({"time": t, "value": round(float(row.ma20), 4)})
        if not np.isnan(row.ma200):
            ma200_series.append({"time": t, "value": round(float(row.ma200), 4)})

    # Build straight trendline point pairs for Lightweight Charts
    vis_start_date = str(vis["date"].iloc[0])
    drawable_lines = {}
    for key, seg in trendlines.items():
        if seg is None:
            drawable_lines[key] = None
            continue
        # Clamp p1 if older than visible start date so line renders cleanly inside visible range
        p1_date = seg["p1_date"]
        p1_price = seg["p1_price"]
        if p1_date < vis_start_date:
            # Interpolate exact value at vis_start_date index
            first_vis_idx = int(vis.index[0])
            dx_total = max(seg["end_idx"] - seg["p1_idx"], 1)
            frac = (first_vis_idx - seg["p1_idx"]) / dx_total
            if scale_mode == "log" and seg["p1_price"] > 0 and seg["end_price"] > 0:
                p1_price = float(np.exp(np.log(seg["p1_price"]) + frac * (np.log(seg["end_price"]) - np.log(seg["p1_price"]))))
            else:
                p1_price = seg["p1_price"] + frac * (seg["end_price"] - seg["p1_price"])
            p1_date = vis_start_date

        drawable_lines[key] = {
            **seg,
            "points": [
                {"time": p1_date, "value": round(float(p1_price), 4)},
                {"time": seg["end_date"], "value": round(float(seg["end_price"]), 4)},
            ],
        }

    # Also compute 2Y, 4Y, 6Y quick summary for this symbol under selected strategy
    multi_period = {}
    for y in (2, 4, 6):
        multi_period[f"{y}Y"] = run_backtest_single(
            symbol, ind, strategy_id=strategy_id, years=y, fee_rate=fee_rate, include_series=False, exit_rule=exit_rule
        )

    last_row = ind.iloc[-1]
    ma200_chg10 = float(last_row["ma200_chg10_pct"]) if not np.isnan(last_row["ma200_chg10_pct"]) else None
    ma200_chg5 = float(last_row["ma200_chg5_pct"]) if not np.isnan(last_row["ma200_chg5_pct"]) else None
    ma200_state = (
        "unknown"
        if ma200_chg10 is None
        else ("up" if ma200_chg10 > 0.05 else ("flat" if (ma200_chg10 >= -0.15 or (ma200_chg5 is not None and ma200_chg5 >= 0.0)) else "down"))
    )

    return {
        "asset": ASSET_MAP.get(symbol) or INDEX_MAP[symbol],
        "candles": candles,
        "volumes": volumes,
        "ma20": ma20_series,
        "ma200": ma200_series,
        "ma200_status": {
            "chg10_pct": round(ma200_chg10, 3) if ma200_chg10 is not None else None,
            "state": ma200_state,
            "above": bool(not np.isnan(last_row["ma200"]) and float(last_row["close"]) > float(last_row["ma200"])),
        },
        "trendlines": drawable_lines,
        "backtest": bt,
        "multi_period": multi_period,
    }


@app.get("/api/research")
def api_research(
    short_window: int = Query(45, ge=15, le=120),
    long_window: int = Query(180, ge=60, le=360),
    price_source: str = Query("wick"),
    scale_mode: str = Query("linear"),
    fee_rate: float = Query(0.001, ge=0.0, le=0.02),
    exit_rule: str = Query("default"),
    fill_mode: str = Query("close", pattern="^(close|next_open)$"),
    slippage_pct: float = Query(0.0, ge=0.0, le=2.0),
):
    return run_research_matrix(
        short_window=short_window,
        long_window=long_window,
        price_source=price_source,
        scale_mode=scale_mode,
        fee_rate=fee_rate,
        include_custom=False,
        exit_rule=exit_rule,
        fill_mode=fill_mode,
        slippage_pct=slippage_pct,
    )


@app.get("/api/research/exits")
def api_research_exits(
    strategy_id: str = Query("S3"),
    short_window: int = Query(45, ge=15, le=120),
    long_window: int = Query(180, ge=60, le=360),
    price_source: str = Query("wick"),
    scale_mode: str = Query("linear"),
    fee_rate: float = Query(0.001, ge=0.0, le=0.02),
):
    return run_exit_rule_comparison(
        strategy_id=strategy_id,
        short_window=short_window,
        long_window=long_window,
        price_source=price_source,
        scale_mode=scale_mode,
        fee_rate=fee_rate,
    )


@app.post("/api/research/custom")
def api_research_custom(req: CustomResearchRequest):
    return run_research_matrix(
        short_window=req.short_window,
        long_window=req.long_window,
        price_source=req.price_source,
        scale_mode=req.scale_mode,
        fee_rate=req.fee_rate,
        include_custom=True,
        custom_params=req.custom_params,
    )


@app.get("/api/scanner")
def api_scanner(
    strategy_id: str = Query("AUTO_BEST"),
    exit_rule: str = Query("default"),
    short_window: int = Query(45, ge=15, le=120),
    long_window: int = Query(180, ge=60, le=360),
    price_source: str = Query("wick"),
    scale_mode: str = Query("linear"),
    near_threshold_pct: float = Query(3.0, ge=0.5, le=15.0),
):
    return scan_all_assets(
        strategy_id=strategy_id,
        short_window=short_window,
        long_window=long_window,
        price_source=price_source,
        scale_mode=scale_mode,
        near_threshold_pct=near_threshold_pct,
        exit_rule=exit_rule,
    )


@app.post("/api/alerts/send")
def api_send_alerts(strategy_id: str | None = None):
    return scan_and_notify(strategy_id=strategy_id)


@app.post("/api/alerts/test")
def api_test_alert():
    settings = load_settings()
    res = dispatch_alerts(
        "추세선 연구실 테스트 알림",
        "알림 연동이 정상적으로 작동합니다! (MA20·MA200 + 30종목 신호 감시 준비 완료)",
        settings.get("alerts", {}),
    )
    return {"results": res}


@app.get("/api/settings")
def api_get_settings():
    return load_settings()


@app.post("/api/settings")
def api_save_settings(payload: SettingsPayload):
    saved = save_settings(payload.model_dump())
    return saved


if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")
