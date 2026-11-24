"""Notification dispatchers: macOS desktop notification, Telegram Bot (auto-chunking), and Discord Webhook."""

from __future__ import annotations

import subprocess
from typing import Any

import httpx


def _split_chunks(text: str, max_len: int) -> list[str]:
    """Split long alert messages cleanly on line breaks."""
    if len(text) <= max_len:
        return [text]
    chunks: list[str] = []
    current: list[str] = []
    cur_len = 0
    for line in text.splitlines(keepends=True):
        if cur_len + len(line) > max_len and current:
            chunks.append("".join(current).rstrip())
            current = [line]
            cur_len = len(line)
        else:
            current.append(line)
            cur_len += len(line)
    if current:
        chunks.append("".join(current).rstrip())
    return chunks


def send_macos_notification(title: str, message: str, subtitle: str = "") -> dict[str, Any]:
    """Trigger native macOS notification via osascript."""
    safe_title = title.replace('"', "'").replace("\\", "")
    safe_sub = subtitle.replace('"', "'").replace("\\", "")
    safe_msg = message.replace('"', "'").replace("\\", "").replace("\n", " | ")[:240]
    sub_clause = f' subtitle "{safe_sub}"' if safe_sub else ""
    script = f'display notification "{safe_msg}" with title "{safe_title}"{sub_clause} sound name "Glass"'
    try:
        proc = subprocess.run(
            ["/usr/bin/osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=8,
        )
        return {"channel": "macos", "ok": proc.returncode == 0, "error": proc.stderr.strip() or None}
    except Exception as exc:
        return {"channel": "macos", "ok": False, "error": str(exc)}


def send_telegram_message(bot_token: str, chat_id: str, text: str) -> dict[str, Any]:
    if not bot_token or not chat_id:
        return {"channel": "telegram", "ok": False, "error": "BOT_TOKEN 또는 CHAT_ID가 비어 있습니다."}
    url = f"https://api.telegram.org/bot{bot_token.strip()}/sendMessage"
    chunks = _split_chunks(text, max_len=3850)
    sent = 0
    last_err = None
    try:
        with httpx.Client(timeout=15.0) as client:
            for idx, chunk in enumerate(chunks, 1):
                body = f"<b>[{idx}/{len(chunks)}]</b>\n{chunk}" if len(chunks) > 1 else chunk
                resp = client.post(
                    url,
                    json={
                        "chat_id": chat_id.strip(),
                        "text": body,
                        "parse_mode": "HTML",
                        "disable_web_page_preview": True,
                    },
                )
                data = resp.json()
                if resp.status_code == 200 and data.get("ok", False):
                    sent += 1
                else:
                    last_err = data.get("description", f"HTTP {resp.status_code}")
                    break
        return {
            "channel": "telegram",
            "ok": sent == len(chunks),
            "parts_sent": sent,
            "parts_total": len(chunks),
            "error": last_err,
        }
    except Exception as exc:
        return {"channel": "telegram", "ok": False, "error": str(exc)}


def send_discord_message(webhook_url: str, text: str) -> dict[str, Any]:
    if not webhook_url:
        return {"channel": "discord", "ok": False, "error": "Discord Webhook URL이 비어 있습니다."}
    chunks = _split_chunks(text, max_len=1900)
    sent = 0
    last_err = None
    try:
        with httpx.Client(timeout=15.0) as client:
            for chunk in chunks:
                resp = client.post(webhook_url.strip(), json={"content": chunk})
                if resp.status_code in (200, 204):
                    sent += 1
                else:
                    last_err = f"HTTP {resp.status_code}"
                    break
        return {
            "channel": "discord",
            "ok": sent == len(chunks),
            "parts_sent": sent,
            "parts_total": len(chunks),
            "error": last_err,
        }
    except Exception as exc:
        return {"channel": "discord", "ok": False, "error": str(exc)}


def dispatch_alerts(
    title: str,
    full_message: str,
    alert_cfg: dict[str, Any],
    macos_summary: str | None = None,
    macos_subtitle: str = "",
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    if alert_cfg.get("macos_enabled"):
        results.append(send_macos_notification(title, macos_summary or full_message, subtitle=macos_subtitle))
    if alert_cfg.get("telegram_enabled"):
        results.append(
            send_telegram_message(
                alert_cfg.get("telegram_bot_token", ""),
                alert_cfg.get("telegram_chat_id", ""),
                f"<b>{title}</b>\n\n{full_message}",
            )
        )
    if alert_cfg.get("discord_enabled"):
        results.append(
            send_discord_message(
                alert_cfg.get("discord_webhook_url", ""),
                f"**{title}**\n\n{full_message}",
            )
        )
    return results
