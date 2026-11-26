#!/usr/bin/env python3
"""
GitHub Actions 전용: 세션별 텔레그램/디스코드 알림 + 모의 포트폴리오 실전 성과 기록.

  REPORT_SESSION=MORNING   (07:47 KST 예약 · 08:30 전후 도착)  미국·코인
  REPORT_SESSION=AFTERNOON (14:37 KST 예약 · 15:00 전후 도착)  한국 장중 예비 + 종합

build_static_site.py 가 만든 docs/data/scanner_AUTO_BEST.json 을 재사용한다 (재스캔 없음).
track/forward_log.csv 에 후보 규칙별 '고정 후' 성과를 한 줄씩 누적 → 워크플로가 커밋
(실전 검증 기록 보존 + 60일 무활동 시 예약 실행 자동 중지 방지).
"""

from __future__ import annotations

import csv
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.notifier import dispatch_alerts
from backend.scanner import format_full_alert_report

KST = timezone(timedelta(hours=9))
SCAN_PATH = Path("docs/data/scanner_AUTO_BEST.json")
LOG_PATH = Path("track/forward_log.csv")
FIELDS = ["run_at_kst", "session", "market", "as_of", "candidate", "rule", "since_freeze_ret", "forward_days",
          "ytd_ret", "since_start_ret", "since_start_mdd", "holdings", "buy_next_open", "sell_next_open"]


def append_forward_log(scan: dict, session: str) -> int:
    cmp_ = (scan.get("rotation") or {}).get("compare") or {}
    now = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    rows = []
    for mkt, m in cmp_.get("markets", {}).items():
        for r in m["rows"]:
            rows.append({
                "run_at_kst": now, "session": session, "market": mkt, "as_of": m["as_of"], "candidate": r["label"], "rule": r["rule"],
                "since_freeze_ret": r["since_freeze"]["ret"] if r["since_freeze"] else "", "forward_days": r["forward_days"],
                "ytd_ret": r["ytd"]["ret"], "since_start_ret": r["since_start"]["ret"], "since_start_mdd": r["since_start"]["mdd"],
                "holdings": r["holdings"], "buy_next_open": " / ".join(r["buy_next_open"]), "sell_next_open": " / ".join(r["sell_next_open"]),
            })
        b = m["bnh"]
        rows.append({
            "run_at_kst": now, "session": session, "market": mkt, "as_of": m["as_of"], "candidate": "단순보유", "rule": "EW B&H",
            "since_freeze_ret": b["since_freeze"]["ret"] if b["since_freeze"] else "", "forward_days": "",
            "ytd_ret": b["ytd"]["ret"], "since_start_ret": b["since_start"]["ret"], "since_start_mdd": b["since_start"]["mdd"],
            "holdings": "", "buy_next_open": "", "sell_next_open": "",
        })
    LOG_PATH.parent.mkdir(exist_ok=True)
    new_file = not LOG_PATH.exists()
    with LOG_PATH.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new_file:
            w.writeheader()
        w.writerows(rows)
    return len(rows)


def main() -> None:
    session = os.environ.get("REPORT_SESSION", "AFTERNOON").upper()
    scan = json.loads(SCAN_PATH.read_text(encoding="utf-8"))
    print(f"[Session] {session} · 기록 {append_forward_log(scan, session)}줄 → {LOG_PATH}")

    tg_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    tg_chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    dc_url = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if not (tg_token and tg_chat) and not dc_url:
        print("No cloud alert secrets configured — skipping cloud notification.")
        return
    title, full_text, _, _ = format_full_alert_report(scan, include_near=True, session=session)
    cfg = {
        "macos_enabled": False,
        "telegram_enabled": bool(tg_token and tg_chat), "telegram_bot_token": tg_token, "telegram_chat_id": tg_chat,
        "discord_enabled": bool(dc_url), "discord_webhook_url": dc_url,
    }
    print("Cloud Alert Results:", dispatch_alerts(title, full_text, cfg))


if __name__ == "__main__":
    main()
