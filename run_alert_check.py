#!/usr/bin/env python3
"""
Daily scheduled runner:
1. Waits briefly for Wi-Fi/network after macOS Dark Wake
2. Refreshes all 150 assets (KOSPI 50, KOSDAQ 50, US 30, CRYPTO 20)
3. Scans with AUTO_BEST (per-market optimal rules) or configured strategy
4. Sends complete grouped alert report via macOS Notification + Telegram (+ Discord if enabled)
5. With --auto-sleep: returns Mac to sleep ONLY if user has been idle >= 3 minutes
"""

from __future__ import annotations

import argparse
import json
import re
import socket
import subprocess
import time
from datetime import datetime

from backend.data_loader import fetch_and_cache_symbols
from backend.scanner import scan_and_notify


def wait_for_network(timeout_sec: int = 45) -> bool:
    """Wait until DNS/network is ready after waking from macOS sleep."""
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            socket.gethostbyname("query2.finance.yahoo.com")
            return True
        except OSError:
            time.sleep(3)
    return False


def get_macos_idle_seconds() -> float | None:
    """Read macOS HIDIdleTime (seconds since last keyboard/mouse activity)."""
    try:
        out = subprocess.check_output(
            ["/usr/sbin/ioreg", "-c", "IOHIDSystem"],
            text=True,
            timeout=5,
        )
        m = re.search(r'"HIDIdleTime"\s*=\s*(\d+)', out)
        if m:
            return int(m.group(1)) / 1_000_000_000.0
    except Exception:
        pass
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="150종목 추세선 신호 스캔 & Mac/텔레그램 알림 발송")
    parser.add_argument("--strategy", default=None, help="전략 ID (AUTO_BEST, S1~S5). 생략 시 저장 설정 사용")
    parser.add_argument("--no-sync", action="store_true", help="시세 최신화 건너뛰기")
    parser.add_argument("--force-sync", action="store_true", help="캐시 무시하고 강제 최신화")
    parser.add_argument("--always-notify", action="store_true", help="신호가 0건이어도 요약 알림 발송")
    parser.add_argument(
        "--auto-sleep",
        action="store_true",
        help="작업 완료 후 사용자가 3분 이상 유휴 상태(자동 기상)이면 다시 잠자기 모드로 복귀",
    )
    parser.add_argument("--idle-threshold", type=int, default=180, help="자동 잠자기 판단 유휴 시간(초, 기본 180초)")
    parser.add_argument("--retrain", action="store_true", help="walk-forward 규칙·확률 보정·포트폴리오를 즉시 재학습")
    parser.add_argument("--retrain-days", type=float, default=7.0, help="이 일수보다 오래된 학습 결과는 자동 재학습 (기본 7일)")
    parser.add_argument("--dry-run", action="store_true", help="알림 발송·잠자기 없이 스캔 결과만 출력")
    args = parser.parse_args()

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n========== [TrendLine Daily Check {ts}] ==========", flush=True)

    if not args.no_sync:
        if not wait_for_network(45):
            print("[Warn] 네트워크 연결 대기 시간 초과 — 캐시된 데이터로 진행합니다.", flush=True)
        else:
            sync_res = fetch_and_cache_symbols(force=args.force_sync)
            print(
                f"[Sync] 요청={sync_res['requested']} 갱신={len(sync_res['updated'])} 실패={len(sync_res['failed'])}",
                flush=True,
            )

    from backend.research_pipeline import artifacts_age_days, rebuild_advanced_research

    age = artifacts_age_days()
    if args.retrain or age is None or age >= args.retrain_days:
        print(f"[Retrain] 학습 결과 {'없음' if age is None else f'{age:.1f}일 경과'} → walk-forward·보정·포트폴리오 재학습", flush=True)
        try:
            rebuild_advanced_research()
        except Exception as exc:  # never block the daily alert because of research
            print(f"[Retrain] 실패 — 기존/기본 규칙으로 진행: {exc}", flush=True)

    if args.dry_run:
        from backend.scanner import format_full_alert_report, scan_all_assets
        from config import load_settings

        settings = load_settings()
        sid = args.strategy or settings.get("active_strategy", "AUTO_BEST")
        scan = scan_all_assets(strategy_id=sid)
        title, full_text, mac_sum, triggered = format_full_alert_report(scan, include_near=True)
        print(title)
        print(full_text)
        print(f"[DryRun] triggered={len(triggered)} | macOS summary={mac_sum}", flush=True)
        return

    res = scan_and_notify(strategy_id=args.strategy, notify_if_empty=args.always_notify)
    scan = res["scan"]
    print(
        f"[Scan {scan['scanned_at']}] 전략={scan['strategy_id']} "
        f"매수={scan['counts']['BUY']} 매도={scan['counts']['SELL']} "
        f"임박={scan['counts']['NEAR']} 보유={scan['counts']['HOLD']}",
        flush=True,
    )
    print(f"[Report] {res.get('report_path')}", flush=True)
    if res.get("notified"):
        print("[Alert Results]", json.dumps(res["alert_results"], ensure_ascii=False), flush=True)
    else:
        print("[Alert]", res.get("message"), flush=True)

    if args.auto_sleep:
        idle_sec = get_macos_idle_seconds()
        print(f"[AutoSleep] 현재 사용자 유휴 시간: {idle_sec:.1f}초 (기준: {args.idle_threshold}초)" if idle_sec is not None else "[AutoSleep] 유휴 시간 확인 불가", flush=True)
        if idle_sec is not None and idle_sec >= args.idle_threshold:
            print("[AutoSleep] 자동 기상 상태로 판단 — 5초 후 잠자기 모드로 복귀합니다.", flush=True)
            time.sleep(5)
            subprocess.run(["/usr/bin/pmset", "sleepnow"], check=False)
        else:
            print("[AutoSleep] 맥을 사용 중인 것으로 감지되어 잠자기 복귀를 건너뜁니다.", flush=True)


if __name__ == "__main__":
    main()
