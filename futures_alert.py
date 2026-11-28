"""선물 1시간봉 매수·매도 알림 (깃허브 액션 매시간 실행).

- 한국 시간 00:00~07:00 은 알림을 보내지 않고 모아 두었다가 07시 이후 첫 실행에 '밤사이 신호'로 보냄
- 웹사이트 버튼 → 텔레그램 봇 명령으로 야간 제한 해제/복구
    /start night_on      : 야간 제한 해제 (계속)
    /start night_tonight : 오늘 밤만 해제 (다음 07시까지)
    /start night_off     : 야간 제한 다시 켜기
- 알림은 매수 임박·매수 신호·매도 임박·매도 신호(손절 포함) 때만 (매일 요약 없음, 수동 실행 시 --force-summary 로만)
- 결과 파일: <out>/latest.json, <out>/chart_<종목>.json, <out>/state.json, <out>/store/ (시세·월물 보관)

실행: python futures_alert.py --out futures_out/futures [--dry-run] [--force-summary]
"""

from __future__ import annotations

import argparse
import html
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from futures_engine.engine import FUTURES, analyze_symbol
from futures_engine.extras import (decrypt, encrypt, fetch_calendar, fmt_event_time, parse_position_cmd,
                                   position_line, upcoming)

LIVE_SINCE_DEFAULT = int(datetime(2026, 11, 28, 13, 47, tzinfo=timezone(timedelta(hours=9))).timestamp())  # 실제 운영 시작
HELP = ("🤖 <b>선물 봇 명령</b>\n"
        "/현황 — 지금 3종목 상태\n"
        "/보유 NQ 26800.25 2 마이크로 26500 — 내 포지션 등록 (종목 가격 계약수 [마이크로|표준] [내 손절])\n"
        "/정리 NQ — 내 포지션 등록 해제\n"
        "/야간해제 · /오늘밤 · /야간제한 — 00~07시 알림 설정\n"
        "※ 명령은 매시간 7분 전후 실행 때 처리되어 답장까지 최대 1시간 걸립니다.")

KST = timezone(timedelta(hours=9))
QUIET_START, QUIET_END = 0, 7
SITE_URL = os.environ.get("SITE_URL", "https://smartjd824.github.io/trendline-lab/")
KIND_ICON = {"BUY": "🟢 매수 신호", "BUY_NEAR": "🟩 매수 임박", "HALF": "🟡 절반 매도 신호", "SELL_ALL": "🟡 전부 매도 신호",
             "SELL_NEAR": "🟧 매도 임박", "SELL_REST": "🔴 나머지 매도 신호", "REST_NEAR": "🟥 나머지 매도 임박", "STOP": "⛔ 손절 (매도)"}


def tg(method: str, token: str, **params):
    try:
        r = httpx.post(f"https://api.telegram.org/bot{token}/{method}", json=params, timeout=15)
        return r.json()
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "description": str(exc)}


def send(token: str, chat: str, text: str, dry: bool) -> bool:
    if dry or not token or not chat:
        print("----- (보내지 않음) -----\n" + text)
        return True
    res = tg("sendMessage", token, chat_id=chat, text=text, parse_mode="HTML", disable_web_page_preview=True)
    if not res.get("ok"):
        print("텔레그램 실패:", res.get("description"))
    return bool(res.get("ok"))


def read_commands(token: str, chat: str, state: dict, now: datetime) -> list[str]:
    """봇에 온 야간 알림 명령 처리. 처리한 내용(답장용 문구) 목록을 돌려줌."""
    if not token or not chat:
        return []
    res = tg("getUpdates", token, offset=int(state.get("tg_offset", 0)) + 1, timeout=0, allowed_updates=["message"])
    if not res.get("ok"):
        print("명령 읽기 실패:", res.get("description"))
        return []
    done = []
    for up in res.get("result", []):
        state["tg_offset"] = max(int(state.get("tg_offset", 0)), int(up["update_id"]))
        msg = up.get("message") or {}
        if str((msg.get("chat") or {}).get("id")) != str(chat).strip():
            continue   # 내 대화방에서 온 명령만
        text = (msg.get("text") or "").strip()
        cmd = text.replace("/start", "").replace("/", "").strip()
        cmd = cmd.lower() if cmd.isascii() else cmd
        if cmd in ("현황", "status", "state"):
            state["_want_status"] = True
            continue
        if cmd in ("도움", "help", "명령"):
            done.append(HELP)
            continue
        pc = parse_position_cmd(cmd)
        if pc:
            code, pos = pc
            code = code.upper()
            positions = decrypt(state.get("positions_enc", ""), token) if state.get("positions_enc") else {}
            if pos is None:
                positions.pop(code, None)
                done.append(f"🗑 {code} 내 포지션 등록을 지웠습니다.")
            else:
                positions[code] = pos
                done.append(f"💼 {code} 내 포지션 등록: {pos['entry']:,} · {pos['qty']}계약({'마이크로' if pos['size'] == 'micro' else '표준'})"
                            + (f" · 내 손절 {pos['stop']:,}" if pos.get("stop") else "") + "\n신호가 나오면 내 손익과 함께 알려 드립니다.")
            state["positions_enc"] = encrypt(positions, token)
            continue
        if cmd in ("night_on", "야간해제"):
            state["night"] = {"mode": "always"}
            done.append("🌙 야간 알림 제한을 <b>해제</b>했습니다. 이제 밤에도 선물 신호가 바로 옵니다.")
        elif cmd in ("night_tonight", "오늘밤"):
            until = (now + timedelta(days=1 if now.hour >= QUIET_END else 0)).replace(hour=QUIET_END, minute=0, second=0, microsecond=0)
            state["night"] = {"mode": "tonight", "until": until.isoformat()}
            done.append(f"🌙 <b>오늘 밤만</b> 야간 알림 제한을 풀었습니다 ({until:%m-%d %H:%M}까지).")
        elif cmd in ("night_off", "야간제한"):
            state["night"] = {"mode": "quiet"}
            done.append("😴 야간 알림 제한을 다시 켰습니다. 00~07시 신호는 아침에 모아서 보냅니다.")
    return done


def night_status(state: dict, now: datetime) -> dict:
    n = state.get("night") or {"mode": "quiet"}
    if n.get("mode") == "tonight":
        until = datetime.fromisoformat(n["until"])
        if now >= until:
            n = {"mode": "quiet"}
            state["night"] = n
    quiet_hour = QUIET_START <= now.hour < QUIET_END
    allowed = (not quiet_hour) or n.get("mode") in ("always", "tonight")
    label = {"always": "해제됨 (밤에도 알림)", "tonight": f"오늘 밤만 해제 ({datetime.fromisoformat(n['until']):%m-%d %H:%M}까지)" if n.get("until") else "", "quiet": "켜짐 (00~07시 알림 없음)"}[n.get("mode", "quiet")]
    return {"mode": n.get("mode", "quiet"), "label": label, "quiet_hour": quiet_hour, "allowed": allowed}


def fmt_event(s: dict, e: dict, positions: dict | None = None, econ: list | None = None) -> str:
    txt = (f"{KIND_ICON.get(e['kind'], e['kind'])} · {s['icon']} <b>{html.escape(s['name'])}</b> ({s['code']}/{s['micro']})\n"
           f"   {html.escape(e['text'])}\n   신호 봉 {e['bar_kst']} · 기준가 {e['price']:,}")
    if e["kind"] in ("BUY", "BUY_NEAR"):
        txt += f"\n   손절 기준 1계약 위험: 마이크로 약 ${s['risk_micro']:,} · 표준 약 ${s['risk_std']:,}"
    if positions and s["code"] in positions:
        txt += "\n   " + position_line(s, positions[s["code"]])
    if econ:
        txt += "\n   ⚠️ 곧 발표: " + ", ".join(f"{x['ko']} {fmt_event_time(x['ts'])}" for x in econ[:3]) + " — 발표 전후 급변동 주의"
    return txt


def fmt_state(s: dict) -> str:
    st = s["state"]
    base = f"{s['icon']} <b>{html.escape(s['name'])}</b> {s['price']:,} ({s['day_chg_pct']:+.2f}%) · "
    if st["status"] in ("없음",):
        cond = "200일선 위" if st.get("above200") else "200일선 아래"
        return base + f"관망 ({cond}, 20일선 기울기 {st.get('s20')})"
    if st["status"] == "매수 신호":
        return base + f"🟢 매수 신호 — 다음 봉 시가 매수 (손절 {st['stop']:,})"
    return base + f"💼 {st['status']} · 진입 {st['entry']:,} · 손절 {st['stop']:,} · 현재 {st['r_now']:+.2f}R"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="futures_out/futures")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force-summary", action="store_true", help="현황 요약을 지금 보내기 (수동 실행 확인용)")
    args = ap.parse_args()
    out = Path(args.out)
    store = out / "store"
    out.mkdir(parents=True, exist_ok=True)
    state_path = out / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    now = datetime.now(KST)

    replies = read_commands(token, chat, state, now)
    positions = decrypt(state["positions_enc"], token) if (state.get("positions_enc") and token) else {}
    live_since = int(state.setdefault("live_since", LIVE_SINCE_DEFAULT))
    cal = fetch_calendar(state.setdefault("calendar", {}))
    now_ts = int(now.timestamp())
    econ_soon = upcoming(cal, now_ts, 3)
    night = night_status(state, now)

    summaries, new_events, errors = [], [], []
    first_run = "last_event_ts" not in state
    last_ts = state.setdefault("last_event_ts", {})
    rolls_all = state.setdefault("rolls", {})
    for spec in FUTURES:
        try:
            summ, charts, rolls, events = analyze_symbol(spec, store, rolls_all.get(spec["symbol"], []))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{spec['name']}: {exc}")
            continue
        rolls_all[spec["symbol"]] = [r for r in rolls if r.get("method") == "exact"]
        summaries.append(summ)
        (out / f"chart_{spec['code']}.json").write_text(json.dumps(charts, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        prev = int(last_ts.get(spec["symbol"], 0))
        if first_run:
            # 처음 실행이면 과거 신호는 보내지 않고 기준점만 잡음
            last_ts[spec["symbol"]] = max([e["ts"] for e in events] + [0])
            continue
        fresh = [e for e in events if e["ts"] > prev]
        for e in fresh:
            new_events.append((summ, e))

    # 보낼지 결정
    pending = state.setdefault("pending", [])
    msgs = []
    for r in replies:
        msgs.append(r)
    if new_events:
        lines = [fmt_event(s, e, positions, econ_soon) for s, e in new_events]
        if night["allowed"]:
            msgs.append("⚡ <b>선물 알림 (1시간봉)</b>\n\n" + "\n\n".join(lines))
        else:
            pending.extend(lines)
    # 내 포지션 손절선 도달 (한 번만)
    pos_changed = False
    for s in summaries:
        p_ = positions.get(s["code"])
        if p_ and p_.get("stop") and not p_.get("stop_alerted") and s["price"] <= p_["stop"]:
            line = f"⛔ <b>내 손절선 도달</b> · {s['icon']} {html.escape(s['name'])} 현재 {s['price']:,} ≤ 내 손절 {p_['stop']:,}\n   " + position_line(s, p_)
            (msgs if night["allowed"] else pending).append(line)
            p_["stop_alerted"] = True
            pos_changed = True
    if pos_changed:
        state["positions_enc"] = encrypt(positions, token)
    if state.pop("_want_status", False):
        args.force_summary = True
    # 매일 현황 요약은 보내지 않음 (신호·임박 때만 알림). 수동 실행에서 요청할 때만 보냄
    morning_due = False
    if pending and night["allowed"]:
        msgs.append("🌙 <b>밤사이 선물 신호</b> (00~07시)\n\n" + "\n\n".join(pending))
        state["pending"] = []
    if (morning_due or args.force_summary) and summaries:
        body = "\n".join(fmt_state(s) + (("\n   " + position_line(s, positions[s["code"]])) if s["code"] in positions else "") for s in summaries)
        nxt = upcoming(cal, now_ts, 72)
        cal_txt = ("\n\n📅 3일 안 주요 지표: " + ", ".join(f"{x['ko']} {fmt_event_time(x['ts'])}" for x in nxt[:5])) if nxt else ""
        msgs.append(f"☀️ <b>선물 현황</b> {now:%m-%d %H:%M}\n{body}{cal_txt}\n\n야간 알림 제한: {night['label']}\n🔗 {SITE_URL}")
        state["last_morning"] = now.strftime("%Y-%m-%d")

    sent_ok = all(send(token, chat, m, args.dry_run) for m in msgs) if msgs else True
    if sent_ok:
        for s, e in new_events:
            last_ts[s["symbol"]] = max(int(last_ts.get(s["symbol"], 0)), e["ts"])

    bot_user = ""
    if token:
        me = tg("getMe", token)
        bot_user = (me.get("result") or {}).get("username", "") if me.get("ok") else ""
    live_all = []
    for s in summaries:
        trades = [t for t in s.pop("_trades_all", []) if t["entry_ts"] >= live_since]
        live_all += trades
        u = [t["micro"] for t in trades]
        s["live"] = dict(n=len(trades), win=round(sum(x > 0 for x in u) / len(u) * 100) if u else None,
                         avg_r=round(sum(t["r"] for t in trades) / len(trades), 2) if trades else None,
                         micro_total=round(sum(u), 1),
                         trades=[dict(entry_kst=datetime.fromtimestamp(t["entry_ts"], KST).strftime("%m-%d %H:%M"),
                                      exit_kst=datetime.fromtimestamp(t["exit_ts"], KST).strftime("%m-%d %H:%M"),
                                      r=round(t["r"], 2), micro=round(t["micro"], 1)) for t in trades[-20:][::-1]],
                         events=[e for e in s["recent_events"] if e["ts"] >= live_since])
    u_all = [t["micro"] for t in live_all]
    live_total = dict(since=datetime.fromtimestamp(live_since, KST).strftime("%Y-%m-%d %H:%M"), n=len(live_all),
                      micro_total=round(sum(u_all), 1), win=round(sum(x > 0 for x in u_all) / len(u_all) * 100) if u_all else None)
    calendar_week = [dict(time_kst=fmt_event_time(x["ts"]), ts=x["ts"], ko=x["ko"], title=x["title"], impact=x["impact"])
                     for x in cal if now_ts - 6 * 3600 <= x["ts"] <= now_ts + 8 * 86400]
    latest = dict(updated_kst=now.strftime("%Y-%m-%d %H:%M"), items=summaries, errors=errors, live=live_total, calendar=calendar_week,
                  night=night, bot_username=bot_user, quiet_hours=f"{QUIET_START:02d}:00~{QUIET_END:02d}:00",
                  rule=dict(buy="20일선 기울기 상승 전환 + 200일선 위·상승 + RSI ≥ 50 (1시간봉 완성 봉 기준, 다음 봉 시가)",
                            stop="처음 손절 1.5 × ATR",
                            sell_half="금·나스닥: 기울기 꺾이면 절반, 종가 200일선 아래면 나머지",
                            sell_all="크루드 오일: 기울기 꺾이면 전부"))
    (out / "latest.json").write_text(json.dumps(latest, ensure_ascii=False, indent=1), encoding="utf-8")
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[선물] {now:%m-%d %H:%M} 종목 {len(summaries)}개 · 새 신호 {len(new_events)}건 · 보낸 메시지 {len(msgs)}개 · 야간 {night['label']} · 오류 {errors}")
    return 0 if summaries else 1


if __name__ == "__main__":
    sys.exit(main())
