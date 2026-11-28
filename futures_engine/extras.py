"""선물 알림 부가 기능: 경제지표 일정 · 내 포지션(암호화 보관) · 실전 기록."""

from __future__ import annotations

import base64
import hashlib
import json
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

KST = timezone(timedelta(hours=9))
CAL_URLS = ["https://nfs.faireconomy.media/ff_calendar_thisweek.json",
            "https://nfs.faireconomy.media/ff_calendar_nextweek.json"]
# 선물에 큰 영향을 주는 미국 지표 (중요도 '높음' 전부 + 원유 재고)
EXTRA_TITLES = ("Crude Oil Inventories",)
KO_TITLES = {
    "CPI": "소비자물가(CPI)", "Core CPI": "근원 소비자물가", "PPI": "생산자물가(PPI)", "Core PPI": "근원 생산자물가",
    "Non-Farm Employment Change": "비농업 고용", "Unemployment Rate": "실업률", "FOMC": "FOMC(금리)",
    "Federal Funds Rate": "기준금리 결정", "FOMC Statement": "FOMC 성명", "FOMC Press Conference": "FOMC 기자회견",
    "FOMC Meeting Minutes": "FOMC 의사록", "Core PCE Price Index": "근원 PCE 물가", "GDP": "GDP 성장률",
    "Retail Sales": "소매판매", "Core Retail Sales": "근원 소매판매", "ISM Manufacturing PMI": "ISM 제조업",
    "ISM Services PMI": "ISM 서비스업", "Crude Oil Inventories": "원유 재고(EIA)", "JOLTS Job Openings": "구인 건수(JOLTS)",
    "Unemployment Claims": "신규 실업수당 청구", "ADP Non-Farm Employment Change": "ADP 고용", "Fed Chair": "연준 의장 발언",
}


def ko_title(t: str) -> str:
    for k in sorted(KO_TITLES, key=len, reverse=True):
        if k in t:
            rest = t.replace(k, "").strip()
            return KO_TITLES[k] + (f" {rest}" if rest else "")
    return t


def fetch_calendar(cache: dict) -> list[dict[str, Any]]:
    """6시간에 한 번만 받아 cache(state)에 보관."""
    if cache.get("events") is not None and time.time() - float(cache.get("fetched", 0)) < 6 * 3600:
        return cache["events"]
    out = []
    for url in CAL_URLS:
        try:
            r = httpx.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code != 200:
                continue
            for e in r.json():
                if e.get("country") != "USD":
                    continue
                title = e.get("title", "")
                if e.get("impact") != "High" and not any(x in title for x in EXTRA_TITLES):
                    continue
                try:
                    ts = int(datetime.fromisoformat(e["date"]).timestamp())
                except Exception:
                    continue
                out.append(dict(ts=ts, title=title, ko=ko_title(title), impact=e.get("impact", "")))
        except Exception:
            continue
    if out:
        out = sorted({(x["ts"], x["title"]): x for x in out}.values(), key=lambda x: x["ts"])
        cache.update(events=out, fetched=time.time())
    return cache.get("events") or []


def upcoming(events: list[dict], now_ts: int, hours: float) -> list[dict]:
    return [e for e in events if now_ts - 3600 <= e["ts"] <= now_ts + hours * 3600]


def fmt_event_time(ts: int) -> str:
    return datetime.fromtimestamp(ts, KST).strftime("%m-%d(%a) %H:%M").replace("Mon", "월").replace("Tue", "화") \
        .replace("Wed", "수").replace("Thu", "목").replace("Fri", "금").replace("Sat", "토").replace("Sun", "일")


# ---------------------------------------------------------------- 내 포지션 (공개 브랜치에 저장되므로 암호화)
def _key(secret: str) -> bytes:
    return hashlib.sha256(("futures-positions:" + secret).encode()).digest()


def _stream(key: bytes, n: int, nonce: bytes) -> bytes:
    out = b""
    i = 0
    while len(out) < n:
        out += hashlib.sha256(key + nonce + i.to_bytes(8, "big")).digest()
        i += 1
    return out[:n]


def encrypt(obj: Any, secret: str) -> str:
    raw = json.dumps(obj, ensure_ascii=False).encode()
    nonce = hashlib.sha256(str(time.time_ns()).encode()).digest()[:12]
    ks = _stream(_key(secret), len(raw), nonce)
    mac = hashlib.sha256(_key(secret) + nonce + raw).digest()[:8]
    return base64.b64encode(nonce + mac + bytes(a ^ b for a, b in zip(raw, ks))).decode()


def decrypt(blob: str, secret: str) -> Any:
    try:
        b = base64.b64decode(blob)
        nonce, mac, ct = b[:12], b[12:20], b[20:]
        raw = bytes(a ^ c for a, c in zip(ct, _stream(_key(secret), len(ct), nonce)))
        if hashlib.sha256(_key(secret) + nonce + raw).digest()[:8] != mac:
            return {}
        return json.loads(raw)
    except Exception:
        return {}


def parse_position_cmd(cmd: str) -> tuple[str, dict | None] | None:
    """텔레그램 명령 해석.
    pos_NQ_26800p25_2_MNQ[_26500]  → NQ 26800.25에 마이크로 2계약 (손절 26500 선택)
    pos_NQ_close / 정리 NQ          → 등록 해제
    '보유 NQ 26800.25 2 마이크로 26500' 처럼 띄어쓰기 형식도 허용
    """
    c = cmd.strip()
    if c.startswith("pos_"):
        parts = c[4:].split("_")
    elif c.startswith(("보유", "정리")):
        parts = c.split()
        if parts[0] == "정리":
            return (parts[1].upper(), None) if len(parts) > 1 else None
        parts = parts[1:]
    else:
        return None
    if not parts:
        return None
    code = parts[0].upper()
    if len(parts) >= 2 and parts[1].lower() in ("close", "정리"):
        return code, None
    try:
        price = float(parts[1].replace("p", "."))
        qty = int(parts[2]) if len(parts) > 2 else 1
        size = (parts[3] if len(parts) > 3 else "micro").lower()
        size = "std" if size in ("std", "표준", "nq", "gc", "cl") else "micro"
        stop = float(parts[4].replace("p", ".")) if len(parts) > 4 else None
    except Exception:
        return None
    return code, dict(entry=price, qty=max(1, qty), size=size, stop=stop, since=datetime.now(KST).strftime("%m-%d %H:%M"))


def position_line(s: dict, pos: dict) -> str:
    """내 포지션 손익 한 줄."""
    tv = s["micro_tick_value"] if pos["size"] == "micro" else s["tick_value"]
    pnl = (s["price"] - pos["entry"]) / s["tick"] * tv * pos["qty"]
    name = s["micro"] if pos["size"] == "micro" else s["code"]
    stop_txt = f" · 내 손절 {pos['stop']:,}" if pos.get("stop") else ""
    return f"💼 내 포지션: {name} {pos['qty']}계약 @ {pos['entry']:,} → 현재 {s['price']:,} ({'+' if pnl >= 0 else ''}${pnl:,.0f}){stop_txt}"
