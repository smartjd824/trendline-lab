# 🌐 어디서든 접속하는 무료 웹페이지 + 매일 오전 10시 자동 알림 배포 가이드 (GitHub Pages)

이 프로젝트는 **GitHub Pages + GitHub Actions**로 **완전 무료 · 24시간 접속 · 맥이 꺼져 있어도 매일 오전 10시 자동 갱신 & 텔레그램 알림**이 동작하도록 구성되어 있습니다.

---

## 1단계: GitHub 저장소 만들기 (1분)
1. [GitHub](https://github.com/new)에서 새 저장소(Repository)를 만듭니다. (예: `trendline-lab`)
   - 무료 계정에서 GitHub Pages를 쓰려면 **Public**으로 선택하세요.
   - *(검색엔진 차단 `noindex` + `robots.txt` + 비밀번호 잠금 화면이 적용되므로 외부 노출 없이 나만 볼 수 있습니다. 텔레그램 토큰은 코드에 절대 올라가지 않고 GitHub Secrets에만 안전하게 보관됩니다.)*

---

## 2단계: 코드 올리기 (터미널 1줄)
`origin` 원격 주소(`https://github.com/smartjd824/trendline-lab.git`)는 이미 연결해 두었습니다. 작업 폴더(`주식`)에서 아래 한 줄만 실행하면 됩니다:

```zsh
git push -u origin main
```

---

## 3단계: 비밀번호 & 텔레그램 시크릿 등록 + Pages 켜기 (2분)
GitHub 저장소 페이지(https://github.com/smartjd824/trendline-lab)에서:

1. **비밀번호 & 텔레그램 설정**: `Settings` → `Secrets and variables` → `Actions` → `New repository secret` 클릭 후 아래 등록:
   - `SITE_PASSCODE` : 웹페이지 열 때 입력할 **나만의 비밀번호** *(모든 데이터 파일이 이 비밀번호로 AES-256 암호화됩니다. 날짜·숫자만 된 짧은 비밀번호는 무차별 대입으로 풀릴 수 있으니 **12자 이상 문장형**을 권장합니다 — 한 번 입력하면 내 폰/PC 브라우저에 기억됨)*
   - `TELEGRAM_BOT_TOKEN` : `@BotFather`에서 발급받은 텔레그램 봇 토큰
   - `TELEGRAM_CHAT_ID` : 내 텔레그램 Chat ID 숫자
2. **GitHub Pages 활성화**: `Settings` → `Pages` → `Build and deployment` → Source를 **`GitHub Actions`**로 선택
3. **첫 배포 실행**: 상단 `Actions` 탭 → **`Daily 10AM KST TrendLine Update & Telegram Alert`** 클릭 → **`Run workflow`** 클릭!
   - 약 1~2분 뒤 배포가 끝나면 **`https://smartjd824.github.io/trendline-lab/`** 주소가 생성됩니다!

---

## 완료 후 자동으로 일어나는 일
- **어디서든 접속**: 스마트폰·회사 PC·태블릿에서 `https://smartjd824.github.io/trendline-lab/` 접속 → 비밀번호 입력 → **150종목 차트 · 2·4·6년 비교 · 오늘의 신호 리포트** 즉시 열람!
- **매일 오전 10:00 (KST) 클라우드 자동 실행**:
  - 맥(Mac)이 꺼져 있거나 외출 중이어도 GitHub 서버가 자동으로 150종목 최신화 → 웹페이지 갱신 → **신호 뜬 전 종목 텔레그램 알림 발송**!
- **원할 때 수동 갱신**: 스마트폰으로 GitHub 앱/웹 `Actions` → `Run workflow` 버튼만 누르면 언제든 즉시 최신화 가능!

## 실전 검증 & 자동 재학습

- 매일 빌드 시 **walk-forward 규칙 선택**(과거 4년 학습 → 이후 2년 검증), **상승점수 확률 보정**, **포트폴리오 백테스트**가 자동 재계산되어 `🧪 250종목 · 테마` 탭 하단 "실전 검증" 카드와 텔레그램 리포트에 반영됩니다.
- 로컬 맥 실행(`run_alert_check.py`)은 학습 결과가 7일 이상 지나면 자동 재학습합니다. 즉시 재학습: `uv run python run_alert_check.py --retrain`
- 백테스트·스캐너 기본값은 **다음날 시가 체결 + 시장별 비용(수수료·슬리피지·거래세)** 입니다. 설정 탭에서 구버전(당일 종가 체결)으로 바꿀 수 있습니다.
