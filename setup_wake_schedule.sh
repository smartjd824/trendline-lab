#!/bin/zsh
# 매일 오전 09:58에 잠자기 상태의 Mac을 자동으로 깨우도록 macOS pmset 스케줄을 등록합니다.
# (실제 150종목 감시 및 알림은 launchd가 매일 오전 10:00에 자동 실행하고, 유휴 상태면 다시 잠자기 복귀)

echo "매일 오전 09:58 자동 기상(wakeorpoweron) 예약을 설정합니다. Mac 로그인 암호를 입력해 주세요."
sudo pmset repeat wakeorpoweron MTWRFSU 09:58:00

echo ""
echo "현재 등록된 Mac 전원/기상 스케줄:"
pmset -g sched
