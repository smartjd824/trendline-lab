#!/bin/zsh
# 매일 오전 10시 자동 감시(launchd)와 오전 09:58 자동 기상(pmset)을 모두 해제합니다.

PLIST="$HOME/Library/LaunchAgents/com.trendline.quantlab.daily10am.plist"
if [ -f "$PLIST" ]; then
  launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null || true
  rm -f "$PLIST"
  echo "✓ launchd 오전 10시 스케줄을 해제했습니다."
else
  echo "- launchd 스케줄 파일이 이미 없습니다."
fi

echo "자동 기상(pmset) 예약도 취소하려면 Mac 암호를 입력해 주세요 (취소하려면 Ctrl+C):"
sudo pmset repeat cancel
pmset -g sched
