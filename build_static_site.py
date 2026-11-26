#!/usr/bin/env python3
"""
Build a 100% static, ultra-fast GitHub Pages site in ./docs/ from the 150-asset universe.

- Precomputes:
  * docs/data/meta.json (assets, strategies, exit rules, optional SHA-256 passcode lock)
  * docs/data/research_<exit>.json (2Y/4Y/6Y 150-asset comparison for default + key exit rules)
  * docs/data/exits_<strategy>.json (6-exit comparison for S1, S2, S3, S5)
  * docs/data/scanner_<strategy>.json (AUTO_BEST + S1, S2, S3, S5)
  * docs/data/latest_report.json (today's full grouped AUTO_BEST alert report)
  * docs/data/charts/<safe_symbol>.json (150 individual chart payloads, loaded on demand)
- Copies frontend assets and enables window.STATIC_MODE = true.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import base64

from config import ASSETS, BASE_DIR, INDICES, THEMES, get_market_rules
from backend.analytics import compute_market_breadth, regime_mask
from backend.research_pipeline import rebuild_advanced_research
from backend.backtester import (
    DEFAULT_CUSTOM_PARAMS,
    EXIT_RULES,
    STRATEGIES,
    build_indicator_map,
    run_backtest_single,
    run_exit_rule_comparison,
    run_research_matrix,
)
from backend.indicators import extract_current_trendlines
from backend.scanner import format_full_alert_report, scan_all_assets

KST = timezone(timedelta(hours=9))
DOCS_DIR = BASE_DIR / "docs"
FRONTEND_DIR = BASE_DIR / "frontend"


def _safe_sym(symbol: str) -> str:
    return symbol.replace("/", "_").replace(".", "_").replace("^", "IDX_").replace("=", "_")


PBKDF2_ITERATIONS = 250_000
_ENC_KEY: bytes | None = None  # set when a passcode is given -> every data JSON is AES-256-GCM encrypted


def _derive_key(passcode: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", passcode.encode("utf-8"), salt, PBKDF2_ITERATIONS, dklen=32)


def _encrypt_payload(raw: bytes) -> dict[str, Any]:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    iv = os.urandom(12)
    ct = AESGCM(_ENC_KEY).encrypt(iv, raw, None)
    return {"enc": "aes-256-gcm", "iv": base64.b64encode(iv).decode(), "ct": base64.b64encode(ct).decode()}


def _write_json(path: Path, data: Any, public: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(data, ensure_ascii=False, separators=(",", ":"), default=float)
    if _ENC_KEY is not None and not public:
        raw = json.dumps(_encrypt_payload(raw.encode("utf-8")), separators=(",", ":"))
    path.write_text(raw, encoding="utf-8")


def _build_chart_payload(
    asset: dict[str, str],
    ind: pd.DataFrame,
    short_window: int = 45,
    long_window: int = 180,
    rules: dict[str, dict[str, Any]] | None = None,
    breadth: dict[str, pd.Series] | None = None,
) -> dict[str, Any]:
    sym = asset["symbol"]
    mkt = asset["market"]
    rules = rules or get_market_rules()
    rule = rules.get(mkt, {"strategy_id": "S3", "exit_rule": "ma200_2d", "label": "S3+MA200홀딩"})
    sid = rule["strategy_id"]
    eid = rule["exit_rule"]
    extra = {
        "stop_mode": rule.get("stop_mode", "fixed"),
        "regime_ok": regime_mask(ind, (breadth or {}).get(mkt)) if rule.get("regime_filter") else None,
    }

    bt = run_backtest_single(sym, ind, strategy_id=sid, years=6, include_series=True, exit_rule=eid, **extra)
    multi_period = {
        f"{y}Y": run_backtest_single(sym, ind, strategy_id=sid, years=y, include_series=False, exit_rule=eid, **extra)
        for y in (2, 4, 6)
    }
    trendlines = extract_current_trendlines(ind, short_window=short_window, long_window=long_window)

    end_dt = ind["date_dt"].iloc[-1]
    start_dt = end_dt - pd.DateOffset(years=6)
    vis = ind[ind["date_dt"] >= start_dt].copy()
    if len(vis) < 60:
        vis = ind.tail(250).copy()

    candles = []
    volumes = []
    ma20_series = []
    ma200_series = []
    for row in vis.itertuples(index=False):
        t = str(row.date)
        o, h, l, c = round(float(row.open), 4), round(float(row.high), 4), round(float(row.low), 4), round(float(row.close), 4)
        candles.append({"time": t, "open": o, "high": h, "low": l, "close": c})
        volumes.append(
            {
                "time": t,
                "value": float(row.volume),
                "color": "rgba(38, 166, 154, 0.32)" if c >= o else "rgba(239, 83, 80, 0.32)",
            }
        )
        if not np.isnan(row.ma20):
            ma20_series.append({"time": t, "value": round(float(row.ma20), 4)})
        if not np.isnan(row.ma200):
            ma200_series.append({"time": t, "value": round(float(row.ma200), 4)})

    vis_start_date = str(vis["date"].iloc[0])
    drawable_lines = {}
    for key, seg in trendlines.items():
        if seg is None:
            drawable_lines[key] = None
            continue
        p1_date = seg["p1_date"]
        p1_price = seg["p1_price"]
        if p1_date < vis_start_date:
            first_vis_idx = int(vis.index[0])
            dx_total = max(seg["end_idx"] - seg["p1_idx"], 1)
            frac = (first_vis_idx - seg["p1_idx"]) / dx_total
            p1_price = seg["p1_price"] + frac * (seg["end_price"] - seg["p1_price"])
            p1_date = vis_start_date
        drawable_lines[key] = {
            **seg,
            "points": [
                {"time": p1_date, "value": round(float(p1_price), 4)},
                {"time": seg["end_date"], "value": round(float(seg["end_price"]), 4)},
            ],
        }

    last_row = ind.iloc[-1]
    ma200_chg10 = float(last_row["ma200_chg10_pct"]) if not np.isnan(last_row["ma200_chg10_pct"]) else None
    ma200_chg5 = float(last_row["ma200_chg5_pct"]) if not np.isnan(last_row["ma200_chg5_pct"]) else None
    ma200_state = (
        "unknown"
        if ma200_chg10 is None
        else ("up" if ma200_chg10 > 0.05 else ("flat" if (ma200_chg10 >= -0.15 or (ma200_chg5 is not None and ma200_chg5 >= 0.0)) else "down"))
    )

    return {
        "asset": asset,
        "recommended_rule": rule,
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


def build_static_site(passcode: str = "") -> dict[str, Any]:
    global _ENC_KEY
    salt = os.urandom(16)
    _ENC_KEY = _derive_key(passcode.strip(), salt) if passcode.strip() else None
    now_kst = datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")
    print(f"[Build] Starting static site build at {now_kst} ...", flush=True)

    if DOCS_DIR.exists():
        shutil.rmtree(DOCS_DIR)
    (DOCS_DIR / "static").mkdir(parents=True, exist_ok=True)
    (DOCS_DIR / "data" / "charts").mkdir(parents=True, exist_ok=True)

    # Copy frontend assets and inject STATIC_MODE flag + noindex meta
    index_html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
    index_html = index_html.replace(
        '<meta name="viewport"',
        '<meta name="robots" content="noindex, nofollow" />\n  <meta name="viewport"',
    )
    index_html = index_html.replace('href="/static/styles.css"', 'href="./static/styles.css"')
    index_html = index_html.replace(
        '<script src="/static/app.js"></script>',
        '<script>window.STATIC_MODE = true;</script>\n  <script src="./static/app.js"></script>',
    )
    (DOCS_DIR / "index.html").write_text(index_html, encoding="utf-8")
    shutil.copy2(FRONTEND_DIR / "styles.css", DOCS_DIR / "static" / "styles.css")
    shutil.copy2(FRONTEND_DIR / "app.js", DOCS_DIR / "static" / "app.js")
    (DOCS_DIR / "robots.txt").write_text("User-agent: *\nDisallow: /\n", encoding="utf-8")
    (DOCS_DIR / ".nojekyll").write_text("", encoding="utf-8")

    # 1. Load/compute all 150 indicator frames
    ind_map = build_indicator_map()
    print(f"[Build] Loaded indicators for {len(ind_map)} assets.", flush=True)

    # 1b. Walk-forward rule selection, score calibration & portfolio backtest (scanner reads these)
    advanced = rebuild_advanced_research(ind_map)
    _write_json(DOCS_DIR / "data" / "advanced.json", {**advanced, "rules": get_market_rules()})
    rules = get_market_rules()
    breadth = compute_market_breadth(ind_map)

    # 2. Precompute research matrices for key exit rules
    exit_keys = ["default", "ma200_2d", "dead_cross", "long_lower", "short_lower", "ma20_2d", "trailing_12", "atr_chandelier"]
    for eid in exit_keys:
        res = run_research_matrix(exit_rule=eid)
        _write_json(DOCS_DIR / "data" / f"research_{eid}.json", res)
    print(f"[Build] Wrote {len(exit_keys)} research matrices.", flush=True)

    # 3. Precompute 6-exit comparisons for S1, S2, S3, S5
    for sid in ["S1", "S2", "S3", "S5"]:
        ex_res = run_exit_rule_comparison(strategy_id=sid)
        _write_json(DOCS_DIR / "data" / f"exits_{sid}.json", ex_res)
    print("[Build] Wrote exit rule comparisons.", flush=True)

    # 4. Precompute scanners (AUTO_BEST + S1, S2, S3, S5) + full daily report
    auto_scan = scan_all_assets(strategy_id="AUTO_BEST")
    _write_json(DOCS_DIR / "data" / "scanner_AUTO_BEST.json", auto_scan)
    title, full_text, mac_sum, triggered = format_full_alert_report(auto_scan, include_near=True)
    _write_json(
        DOCS_DIR / "data" / "latest_report.json",
        {
            "generated_at": now_kst,
            "title": title,
            "full_text": full_text,
            "summary": mac_sum,
            "counts": auto_scan["counts"],
            "triggered_count": len(triggered),
        },
    )
    for sid in ["S1", "S2", "S3", "S5"]:
        _write_json(DOCS_DIR / "data" / f"scanner_{sid}.json", scan_all_assets(strategy_id=sid))
    print("[Build] Wrote scanner & latest report.", flush=True)

    # 5. Precompute 250 individual asset + 10 global index chart JSONs
    charts_written = 0
    for asset in list(ASSETS) + list(INDICES):
        sym = asset["symbol"]
        ind = ind_map.get(sym)
        if ind is None or len(ind) < 210:
            continue
        payload = _build_chart_payload(asset, ind, rules=rules, breadth=breadth)
        _write_json(DOCS_DIR / "data" / "charts" / f"{_safe_sym(sym)}.json", payload)
        charts_written += 1
    print(f"[Build] Wrote {charts_written} chart JSON files (250 assets + 10 indices).", flush=True)

    # 6. Meta. With a passcode, ALL data files (incl. meta body) are AES-256-GCM encrypted with a
    #    PBKDF2-SHA256 derived key — the old client-side SHA-256 check protected nothing.
    meta = {
        "static_mode": True,
        "generated_at": now_kst,
        "assets": ASSETS,
        "themes": THEMES,
        "strategies": list(STRATEGIES.values()),
        "exit_rules": list(EXIT_RULES.values()),
        "market_best_rules": rules,
        "cache": {"total": len(ASSETS), "cached": charts_written, "ready": charts_written == len(ASSETS)},
        "settings": {
            "short_window": 45,
            "long_window": 180,
            "price_source": "wick",
            "scale_mode": "linear",
            "near_threshold_pct": 3.0,
            "active_strategy": "AUTO_BEST",
            "exit_rule": "ma200_2d",
            "execution": "next_open",
            "cost_model": "market",
            "alerts": {},
        },
        "default_custom_params": DEFAULT_CUSTOM_PARAMS,
    }
    if _ENC_KEY is not None:
        lock = {
            "static_mode": True,
            "generated_at": now_kst,
            "passcode_required": True,
            "kdf": {"name": "PBKDF2-SHA256", "iterations": PBKDF2_ITERATIONS, "salt": base64.b64encode(salt).decode()},
            "meta_enc": _encrypt_payload(json.dumps(meta, ensure_ascii=False).encode("utf-8")),
        }
        _write_json(DOCS_DIR / "data" / "meta.json", lock, public=True)
    else:
        _write_json(DOCS_DIR / "data" / "meta.json", {**meta, "passcode_required": False}, public=True)

    total_bytes = sum(p.stat().st_size for p in DOCS_DIR.rglob("*") if p.is_file())
    summary = {
        "docs_dir": str(DOCS_DIR),
        "charts_written": charts_written,
        "total_size_mb": round(total_bytes / (1024 * 1024), 2),
        "passcode_protected": _ENC_KEY is not None,
        "generated_at": now_kst,
    }
    print(f"[Build] Complete! {summary}", flush=True)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Build static GitHub Pages site into ./docs/")
    parser.add_argument(
        "--passcode",
        default=os.environ.get("SITE_PASSCODE", ""),
        help="Optional passcode to lock web dashboard (or set SITE_PASSCODE env var)",
    )
    args = parser.parse_args()
    build_static_site(passcode=args.passcode)


if __name__ == "__main__":
    main()
