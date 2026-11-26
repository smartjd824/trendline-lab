"""Rebuild and persist the advanced research artifacts (walk-forward rules, calibration, portfolio)."""

from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Any

import config
from backend.analytics import compute_market_breadth, run_portfolio_suite, walk_forward_select
from backend.backtester import build_indicator_map
from backend.calibration import build_calibration


def _save(path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, default=float), encoding="utf-8")


def artifacts_age_days() -> float | None:
    """Age in days of the oldest advanced-research artifact (None if any is missing)."""
    paths = [config.LEARNED_RULES_PATH, config.CALIBRATION_PATH, config.PORTFOLIO_PATH]
    if not all(p.exists() for p in paths):
        return None
    oldest = min(p.stat().st_mtime for p in paths)
    return (time.time() - oldest) / 86400.0


def rebuild_advanced_research(ind_map=None, verbose: bool = True) -> dict[str, Any]:
    t0 = time.time()
    ind_map = ind_map or build_indicator_map()
    breadth = compute_market_breadth(ind_map)

    wf = walk_forward_select(ind_map, breadth)
    _save(config.LEARNED_RULES_PATH, wf)
    if verbose:
        print(f"[Research+] walk-forward rules saved ({time.time() - t0:.0f}s)", flush=True)

    rules = config.get_market_rules()
    calib = build_calibration(ind_map, rules, breadth)
    _save(config.CALIBRATION_PATH, calib)
    if verbose:
        print(f"[Research+] calibration saved: {calib.get('samples', 0)} samples ({time.time() - t0:.0f}s)", flush=True)

    portfolio = run_portfolio_suite(ind_map, rules, breadth)
    _save(config.PORTFOLIO_PATH, portfolio)
    if verbose:
        print(f"[Research+] portfolio backtest saved ({time.time() - t0:.0f}s)", flush=True)

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "walk_forward": wf,
        "calibration": calib,
        "portfolio": portfolio,
        "breadth_now": {k: (round(float(v.dropna().iloc[-1]), 1) if not v.dropna().empty else None) for k, v in breadth.items()},
    }


def load_advanced_research() -> dict[str, Any]:
    return {
        "walk_forward": config.read_json_file(config.LEARNED_RULES_PATH),
        "calibration": config.read_json_file(config.CALIBRATION_PATH),
        "portfolio": config.read_json_file(config.PORTFOLIO_PATH),
        "rules": config.get_market_rules(),
    }
