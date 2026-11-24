# 🌐 어디서든 접속하는 무료 웹페이지 + 매일 오전 10시 자동 알림 배포 가이드 (GitHub Pages)

이 프로젝트는 **GitHub Pages + GitHub Actions**로 **완전 무료 · 24시간 접속 · 맥이 꺼져 있어도 매일 오전 10시 자동 갱신 & 텔레그램 알림**이 동작하도록 구성되어 있습니다.

---

## 1단계: GitHub 저장소 만들기 (1분)
1. [GitHub](https://github.com/new)에서 새 저장소(Repository)를 만듭니다. (예: `trendline-lab`)
   - 무료 계정에서 GitHub Pages를 쓰려면 **Public**으로 선택하세요.
   - *(검색엔진 차단 `noindex` + `robots.txt` + 비밀번호 잠금 화면이 적용되므로 외부 노출 없이 나만 볼 수 있습니다. 텔레그램 토큰은 코드에 절대 올라가지 않고 GitHub Secrets에만 안전하게 보관됩니다.)*

---

## 2단계: 코드 올리기 (터미널 3줄)
작업 폴더(`주식`)에서 아래 명령어를 실행합니다 (`<내아이디>`를 본인 GitHub 아이디로 변경):

```zsh
git remote add origin https://github.com/<내아이디>/trendline-lab.git
git branch -M main
git push -u origin main
```

---

## 3단계: 비밀번호 & 텔레그램 시크릿 등록 + Pages 켜기 (2분)
GitHub 저장소 페이지에서:

1. **비밀번호 & 텔레그램 설정**: `Settings` → `Secrets and variables` → `Actions` → `New repository secret` 클릭 후 아래 등록:
   - `SITE_PASSCODE` : 웹페이지 열 때 입력할 **나만의 비밀번호** *(예: `20260824` — 한 번 입력하면 내 폰/PC 브라우저에 기억됨)*
   - `TELEGRAM_BOT_TOKEN` : `@BotFather`에서 발급받은 텔레그램 봇 토큰
   - `TELEGRAM_CHAT_ID` : 내 텔레그램 Chat ID 숫자
2. **GitHub Pages 활성화**: `Settings` → `Pages` → `Build and deployment` → Source를 **`GitHub Actions`**로 선택
3. **첫 배포 실행**: 상단 `Actions` 탭 → **`Daily 10AM KST TrendLine Update & Telegram Alert`** 클릭 → **`Run workflow`** 클릭!
   - 약 1~2분 뒤 배포가 끝나면 **`https://<내아이디>.github.io/trendline-lab/`** 주소가 생성됩니다!

---

## 완료 후 자동으로 일어나는 일
- **어디서든 접속**: 스마트폰·회사 PC·태블릿에서 `https://<내아이디>.github.io/trendline-lab/` 접속 → 비밀번호 입력 → **150종목 차트 · 2·4·6년 비교 · 오늘의 신호 리포트** 즉시 열람!
- **매일 오전 10:00 (KST) 클라우드 자동 실행**:
  - 맥(Mac)이 꺼져 있거나 외출 중이어도 GitHub 서버가 자동으로 150종목 최신화 → 웹페이지 갱신 → **신호 뜬 전 종목 텔레그램 알림 발송**!
- **원할 때 수동 갱신**: 스마트폰으로 GitHub 앱/웹 `Actions` → `Run workflow` 버튼만 누르면 언제든 즉시 최신화 가능!
