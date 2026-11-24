"""Project configuration: 250 theme-tagged representative assets (KOSPI 70, KOSDAQ 70, US 80, CRYPTO 30)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TypedDict

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "market_data.db"
SETTINGS_PATH = DATA_DIR / "user_settings.json"
IND_CACHE_DIR = DATA_DIR / "ind_cache"
IND_CACHE_DIR.mkdir(exist_ok=True)
REPORTS_DIR = DATA_DIR / "reports"
REPORTS_DIR.mkdir(exist_ok=True)
LOGS_DIR = DATA_DIR / "logs"
LOGS_DIR.mkdir(exist_ok=True)

MARKETS = ["ALL", "KOSPI", "KOSDAQ", "US", "CRYPTO"]

THEMES: list[dict[str, str]] = [
    {"id": "AI·반도체", "label": "🤖 AI·반도체"},
    {"id": "전력·원전", "label": "⚡ 전력·원전"},
    {"id": "방산·조선·우주", "label": "🚀 방산·조선·우주"},
    {"id": "로봇·모빌리티", "label": "🦾 로봇·모빌리티"},
    {"id": "바이오·헬스케어", "label": "🧬 바이오·헬스케어"},
    {"id": "2차전지·소재", "label": "🔋 2차전지·소재"},
    {"id": "빅테크·SW·IT", "label": "💻 빅테크·SW·IT"},
    {"id": "금융·가치·ETF", "label": "🏦 금융·가치·ETF"},
    {"id": "소비·엔터·K뷰티", "label": "💄 소비·엔터·K뷰티"},
    {"id": "코인·디지털자산", "label": "🪙 코인·디지털자산"},
]

# 150-asset 2Y/4Y/6Y research-backed optimal (entry, exit) combo per market
MARKET_BEST_RULES: dict[str, dict[str, str]] = {
    "KOSPI": {"strategy_id": "S1", "exit_rule": "dead_cross", "label": "S1+데드크로스"},
    "KOSDAQ": {"strategy_id": "S3", "exit_rule": "long_lower", "label": "S3+장기하단"},
    "US": {"strategy_id": "S3", "exit_rule": "ma200_2d", "label": "S3+MA200홀딩"},
    "CRYPTO": {"strategy_id": "S5", "exit_rule": "ma20_2d", "label": "S5+MA20이탈"},
}


class AssetInfo(TypedDict):
    symbol: str
    name: str
    market: str  # "KOSPI" | "KOSDAQ" | "US" | "CRYPTO"
    theme: str
    currency: str


def _a(symbol: str, name: str, market: str, theme: str, currency: str) -> AssetInfo:
    return {"symbol": symbol, "name": name, "market": market, "theme": theme, "currency": currency}


ASSETS: list[AssetInfo] = [
    # ==================== 국내 코스피 70종목 (KOSPI) ====================
    # AI·반도체
    _a("005930.KS", "삼성전자", "KOSPI", "AI·반도체", "KRW"),
    _a("000660.KS", "SK하이닉스", "KOSPI", "AI·반도체", "KRW"),
    _a("042700.KS", "한미반도체", "KOSPI", "AI·반도체", "KRW"),
    _a("007660.KS", "이수페타시스", "KOSPI", "AI·반도체", "KRW"),
    _a("009150.KS", "삼성전기", "KOSPI", "AI·반도체", "KRW"),
    _a("066570.KS", "LG전자", "KOSPI", "AI·반도체", "KRW"),
    # 전력·원전
    _a("267260.KS", "HD현대일렉트릭", "KOSPI", "전력·원전", "KRW"),
    _a("298040.KS", "효성중공업", "KOSPI", "전력·원전", "KRW"),
    _a("010120.KS", "LS ELECTRIC", "KOSPI", "전력·원전", "KRW"),
    _a("034020.KS", "두산에너빌리티", "KOSPI", "전력·원전", "KRW"),
    _a("052690.KS", "한전기술", "KOSPI", "전력·원전", "KRW"),
    _a("015760.KS", "한국전력", "KOSPI", "전력·원전", "KRW"),
    _a("006260.KS", "LS", "KOSPI", "전력·원전", "KRW"),
    _a("010950.KS", "S-Oil", "KOSPI", "전력·원전", "KRW"),
    # 방산·조선·우주
    _a("012450.KS", "한화에어로스페이스", "KOSPI", "방산·조선·우주", "KRW"),
    _a("064350.KS", "현대로템", "KOSPI", "방산·조선·우주", "KRW"),
    _a("079550.KS", "LIG넥스원", "KOSPI", "방산·조선·우주", "KRW"),
    _a("047810.KS", "한국항공우주", "KOSPI", "방산·조선·우주", "KRW"),
    _a("272210.KS", "한화시스템", "KOSPI", "방산·조선·우주", "KRW"),
    _a("329180.KS", "HD현대중공업", "KOSPI", "방산·조선·우주", "KRW"),
    _a("009540.KS", "HD한국조선해양", "KOSPI", "방산·조선·우주", "KRW"),
    _a("042660.KS", "한화오션", "KOSPI", "방산·조선·우주", "KRW"),
    _a("010140.KS", "삼성중공업", "KOSPI", "방산·조선·우주", "KRW"),
    _a("267250.KS", "HD현대", "KOSPI", "방산·조선·우주", "KRW"),
    _a("011200.KS", "HMM", "KOSPI", "방산·조선·우주", "KRW"),
    # 로봇·모빌리티
    _a("005380.KS", "현대차", "KOSPI", "로봇·모빌리티", "KRW"),
    _a("000270.KS", "기아", "KOSPI", "로봇·모빌리티", "KRW"),
    _a("012330.KS", "현대모비스", "KOSPI", "로봇·모빌리티", "KRW"),
    _a("307950.KS", "현대오토에버", "KOSPI", "로봇·모빌리티", "KRW"),
    _a("454910.KS", "두산로보틱스", "KOSPI", "로봇·모빌리티", "KRW"),
    _a("003490.KS", "대한항공", "KOSPI", "로봇·모빌리티", "KRW"),
    # 바이오·헬스케어
    _a("207940.KS", "삼성바이오로직스", "KOSPI", "바이오·헬스케어", "KRW"),
    _a("068270.KS", "셀트리온", "KOSPI", "바이오·헬스케어", "KRW"),
    _a("000100.KS", "유한양행", "KOSPI", "바이오·헬스케어", "KRW"),
    _a("128940.KS", "한미약품", "KOSPI", "바이오·헬스케어", "KRW"),
    _a("302440.KS", "SK바이오사이언스", "KOSPI", "바이오·헬스케어", "KRW"),
    # 2차전지·소재
    _a("373220.KS", "LG에너지솔루션", "KOSPI", "2차전지·소재", "KRW"),
    _a("006400.KS", "삼성SDI", "KOSPI", "2차전지·소재", "KRW"),
    _a("051910.KS", "LG화학", "KOSPI", "2차전지·소재", "KRW"),
    _a("005490.KS", "POSCO홀딩스", "KOSPI", "2차전지·소재", "KRW"),
    _a("003670.KS", "포스코퓨처엠", "KOSPI", "2차전지·소재", "KRW"),
    _a("096770.KS", "SK이노베이션", "KOSPI", "2차전지·소재", "KRW"),
    _a("010130.KS", "고려아연", "KOSPI", "2차전지·소재", "KRW"),
    # 빅테크·SW·IT
    _a("035420.KS", "NAVER", "KOSPI", "빅테크·SW·IT", "KRW"),
    _a("035720.KS", "카카오", "KOSPI", "빅테크·SW·IT", "KRW"),
    _a("018260.KS", "삼성에스디에스", "KOSPI", "빅테크·SW·IT", "KRW"),
    _a("017670.KS", "SK텔레콤", "KOSPI", "빅테크·SW·IT", "KRW"),
    _a("030200.KS", "KT", "KOSPI", "빅테크·SW·IT", "KRW"),
    _a("032640.KS", "LG유플러스", "KOSPI", "빅테크·SW·IT", "KRW"),
    # 금융·가치·ETF
    _a("105560.KS", "KB금융", "KOSPI", "금융·가치·ETF", "KRW"),
    _a("055550.KS", "신한지주", "KOSPI", "금융·가치·ETF", "KRW"),
    _a("086790.KS", "하나금융지주", "KOSPI", "금융·가치·ETF", "KRW"),
    _a("316140.KS", "우리금융지주", "KOSPI", "금융·가치·ETF", "KRW"),
    _a("138040.KS", "메리츠금융지주", "KOSPI", "금융·가치·ETF", "KRW"),
    _a("024110.KS", "기업은행", "KOSPI", "금융·가치·ETF", "KRW"),
    _a("032830.KS", "삼성생명", "KOSPI", "금융·가치·ETF", "KRW"),
    _a("000810.KS", "삼성화재", "KOSPI", "금융·가치·ETF", "KRW"),
    _a("005830.KS", "DB손해보험", "KOSPI", "금융·가치·ETF", "KRW"),
    _a("028260.KS", "삼성물산", "KOSPI", "금융·가치·ETF", "KRW"),
    _a("003550.KS", "LG", "KOSPI", "금융·가치·ETF", "KRW"),
    _a("034730.KS", "SK", "KOSPI", "금융·가치·ETF", "KRW"),
    _a("033780.KS", "KT&G", "KOSPI", "금융·가치·ETF", "KRW"),
    # 소비·엔터·K뷰티
    _a("003230.KS", "삼양식품", "KOSPI", "소비·엔터·K뷰티", "KRW"),
    _a("278470.KS", "에이피알", "KOSPI", "소비·엔터·K뷰티", "KRW"),
    _a("090430.KS", "아모레퍼시픽", "KOSPI", "소비·엔터·K뷰티", "KRW"),
    _a("051900.KS", "LG생활건강", "KOSPI", "소비·엔터·K뷰티", "KRW"),
    _a("192820.KS", "코스맥스", "KOSPI", "소비·엔터·K뷰티", "KRW"),
    _a("097950.KS", "CJ제일제당", "KOSPI", "소비·엔터·K뷰티", "KRW"),
    _a("352820.KS", "하이브", "KOSPI", "소비·엔터·K뷰티", "KRW"),
    _a("259960.KS", "크래프톤", "KOSPI", "소비·엔터·K뷰티", "KRW"),

    # ==================== 국내 코스닥 70종목 (KOSDAQ) ====================
    # AI·반도체
    _a("058470.KQ", "리노공업", "KOSDAQ", "AI·반도체", "KRW"),
    _a("403870.KQ", "HPSP", "KOSDAQ", "AI·반도체", "KRW"),
    _a("005290.KQ", "동진쎄미켐", "KOSDAQ", "AI·반도체", "KRW"),
    _a("357780.KQ", "솔브레인", "KOSDAQ", "AI·반도체", "KRW"),
    _a("240810.KQ", "원익IPS", "KOSDAQ", "AI·반도체", "KRW"),
    _a("039030.KQ", "이오테크닉스", "KOSDAQ", "AI·반도체", "KRW"),
    _a("036930.KQ", "주성엔지니어링", "KOSDAQ", "AI·반도체", "KRW"),
    _a("089030.KQ", "테크윙", "KOSDAQ", "AI·반도체", "KRW"),
    _a("095340.KQ", "ISC", "KOSDAQ", "AI·반도체", "KRW"),
    _a("140860.KQ", "파크시스템스", "KOSDAQ", "AI·반도체", "KRW"),
    _a("222800.KQ", "심텍", "KOSDAQ", "AI·반도체", "KRW"),
    _a("064760.KQ", "티씨케이", "KOSDAQ", "AI·반도체", "KRW"),
    _a("036540.KQ", "SFA반도체", "KOSDAQ", "AI·반도체", "KRW"),
    _a("056190.KQ", "에스에프에이", "KOSDAQ", "AI·반도체", "KRW"),
    _a("084370.KQ", "유진테크", "KOSDAQ", "AI·반도체", "KRW"),
    _a("067310.KQ", "하나마이크론", "KOSDAQ", "AI·반도체", "KRW"),
    _a("399720.KQ", "가온칩스", "KOSDAQ", "AI·반도체", "KRW"),
    _a("131970.KQ", "두산테스나", "KOSDAQ", "AI·반도체", "KRW"),
    _a("095610.KQ", "테스", "KOSDAQ", "AI·반도체", "KRW"),
    _a("319660.KQ", "피에스케이", "KOSDAQ", "AI·반도체", "KRW"),
    _a("074600.KQ", "원익QnC", "KOSDAQ", "AI·반도체", "KRW"),
    _a("131290.KQ", "티에스이", "KOSDAQ", "AI·반도체", "KRW"),
    _a("089010.KQ", "켐트로닉스", "KOSDAQ", "AI·반도체", "KRW"),
    # 전력·원전
    _a("083650.KQ", "비에이치아이", "KOSDAQ", "전력·원전", "KRW"),
    _a("032500.KQ", "케이엠더블유", "KOSDAQ", "전력·원전", "KRW"),
    # 방산·조선·우주
    _a("099320.KQ", "쎄트렉아이", "KOSDAQ", "방산·조선·우주", "KRW"),
    _a("218410.KQ", "RFHIC", "KOSDAQ", "방산·조선·우주", "KRW"),
    _a("065350.KQ", "신성델타테크", "KOSDAQ", "방산·조선·우주", "KRW"),
    # 로봇·모빌리티
    _a("277810.KQ", "레인보우로보틱스", "KOSDAQ", "로봇·모빌리티", "KRW"),
    _a("098460.KQ", "고영", "KOSDAQ", "로봇·모빌리티", "KRW"),
    _a("058610.KQ", "에스피지", "KOSDAQ", "로봇·모빌리티", "KRW"),
    _a("108490.KQ", "로보티즈", "KOSDAQ", "로봇·모빌리티", "KRW"),
    _a("090710.KQ", "휴림로봇", "KOSDAQ", "로봇·모빌리티", "KRW"),
    # 바이오·헬스케어
    _a("196170.KQ", "알테오젠", "KOSDAQ", "바이오·헬스케어", "KRW"),
    _a("028300.KQ", "HLB", "KOSDAQ", "바이오·헬스케어", "KRW"),
    _a("141080.KQ", "리가켐바이오", "KOSDAQ", "바이오·헬스케어", "KRW"),
    _a("214450.KQ", "파마리서치", "KOSDAQ", "바이오·헬스케어", "KRW"),
    _a("145020.KQ", "휴젤", "KOSDAQ", "바이오·헬스케어", "KRW"),
    _a("214150.KQ", "클래시스", "KOSDAQ", "바이오·헬스케어", "KRW"),
    _a("000250.KQ", "삼천당제약", "KOSDAQ", "바이오·헬스케어", "KRW"),
    _a("087010.KQ", "펩트론", "KOSDAQ", "바이오·헬스케어", "KRW"),
    _a("068760.KQ", "셀트리온제약", "KOSDAQ", "바이오·헬스케어", "KRW"),
    _a("298380.KQ", "에이비엘바이오", "KOSDAQ", "바이오·헬스케어", "KRW"),
    _a("237690.KQ", "에스티팜", "KOSDAQ", "바이오·헬스케어", "KRW"),
    _a("096530.KQ", "씨젠", "KOSDAQ", "바이오·헬스케어", "KRW"),
    _a("214370.KQ", "케어젠", "KOSDAQ", "바이오·헬스케어", "KRW"),
    _a("086900.KQ", "메디톡스", "KOSDAQ", "바이오·헬스케어", "KRW"),
    _a("048410.KQ", "현대바이오", "KOSDAQ", "바이오·헬스케어", "KRW"),
    _a("310210.KQ", "보로노이", "KOSDAQ", "바이오·헬스케어", "KRW"),
    _a("226950.KQ", "올릭스", "KOSDAQ", "바이오·헬스케어", "KRW"),
    _a("085660.KQ", "차바이오텍", "KOSDAQ", "바이오·헬스케어", "KRW"),
    _a("039200.KQ", "오스코텍", "KOSDAQ", "바이오·헬스케어", "KRW"),
    # 2차전지·소재
    _a("247540.KQ", "에코프로비엠", "KOSDAQ", "2차전지·소재", "KRW"),
    _a("086520.KQ", "에코프로", "KOSDAQ", "2차전지·소재", "KRW"),
    _a("078600.KQ", "대주전자재료", "KOSDAQ", "2차전지·소재", "KRW"),
    _a("348370.KQ", "엔켐", "KOSDAQ", "2차전지·소재", "KRW"),
    _a("137400.KQ", "피엔티", "KOSDAQ", "2차전지·소재", "KRW"),
    _a("281740.KQ", "레이크머티리얼즈", "KOSDAQ", "2차전지·소재", "KRW"),
    _a("365340.KQ", "성일하이텍", "KOSDAQ", "2차전지·소재", "KRW"),
    _a("278280.KQ", "천보", "KOSDAQ", "2차전지·소재", "KRW"),
    # 소비·엔터·K뷰티
    _a("035900.KQ", "JYP Ent.", "KOSDAQ", "소비·엔터·K뷰티", "KRW"),
    _a("041510.KQ", "에스엠", "KOSDAQ", "소비·엔터·K뷰티", "KRW"),
    _a("122870.KQ", "와이지엔터테인먼트", "KOSDAQ", "소비·엔터·K뷰티", "KRW"),
    _a("263750.KQ", "펄어비스", "KOSDAQ", "소비·엔터·K뷰티", "KRW"),
    _a("293490.KQ", "카카오게임즈", "KOSDAQ", "소비·엔터·K뷰티", "KRW"),
    _a("112040.KQ", "위메이드", "KOSDAQ", "소비·엔터·K뷰티", "KRW"),
    _a("253450.KQ", "스튜디오드래곤", "KOSDAQ", "소비·엔터·K뷰티", "KRW"),
    _a("257720.KQ", "실리콘투", "KOSDAQ", "소비·엔터·K뷰티", "KRW"),
    _a("035760.KQ", "CJ ENM", "KOSDAQ", "소비·엔터·K뷰티", "KRW"),
    _a("067160.KQ", "SOOP", "KOSDAQ", "소비·엔터·K뷰티", "KRW"),

    # ==================== 미국주식 80종목 (US) ====================
    # AI·반도체 (14)
    _a("NVDA", "NVIDIA", "US", "AI·반도체", "USD"),
    _a("AVGO", "Broadcom", "US", "AI·반도체", "USD"),
    _a("AMD", "AMD", "US", "AI·반도체", "USD"),
    _a("TSM", "TSMC", "US", "AI·반도체", "USD"),
    _a("ASML", "ASML", "US", "AI·반도체", "USD"),
    _a("MU", "Micron", "US", "AI·반도체", "USD"),
    _a("ARM", "Arm Holdings", "US", "AI·반도체", "USD"),
    _a("MRVL", "Marvell", "US", "AI·반도체", "USD"),
    _a("QCOM", "Qualcomm", "US", "AI·반도체", "USD"),
    _a("INTC", "Intel", "US", "AI·반도체", "USD"),
    _a("AMAT", "Applied Materials", "US", "AI·반도체", "USD"),
    _a("LRCX", "Lam Research", "US", "AI·반도체", "USD"),
    _a("KLAC", "KLA Corp", "US", "AI·반도체", "USD"),
    _a("SMCI", "Super Micro", "US", "AI·반도체", "USD"),
    # 빅테크·SW·IT (20)
    _a("AAPL", "Apple", "US", "빅테크·SW·IT", "USD"),
    _a("MSFT", "Microsoft", "US", "빅테크·SW·IT", "USD"),
    _a("GOOGL", "Alphabet", "US", "빅테크·SW·IT", "USD"),
    _a("AMZN", "Amazon", "US", "빅테크·SW·IT", "USD"),
    _a("META", "Meta", "US", "빅테크·SW·IT", "USD"),
    _a("ORCL", "Oracle", "US", "빅테크·SW·IT", "USD"),
    _a("CRM", "Salesforce", "US", "빅테크·SW·IT", "USD"),
    _a("ADBE", "Adobe", "US", "빅테크·SW·IT", "USD"),
    _a("CSCO", "Cisco", "US", "빅테크·SW·IT", "USD"),
    _a("PLTR", "Palantir", "US", "빅테크·SW·IT", "USD"),
    _a("NOW", "ServiceNow", "US", "빅테크·SW·IT", "USD"),
    _a("CRWD", "CrowdStrike", "US", "빅테크·SW·IT", "USD"),
    _a("PANW", "Palo Alto", "US", "빅테크·SW·IT", "USD"),
    _a("SNOW", "Snowflake", "US", "빅테크·SW·IT", "USD"),
    _a("APP", "AppLovin", "US", "빅테크·SW·IT", "USD"),
    _a("SHOP", "Shopify", "US", "빅테크·SW·IT", "USD"),
    _a("ANET", "Arista Networks", "US", "빅테크·SW·IT", "USD"),
    _a("IBM", "IBM", "US", "빅테크·SW·IT", "USD"),
    _a("NET", "Cloudflare", "US", "빅테크·SW·IT", "USD"),
    _a("DDOG", "Datadog", "US", "빅테크·SW·IT", "USD"),
    # 전력·원전 (8)
    _a("CEG", "Constellation Energy", "US", "전력·원전", "USD"),
    _a("VST", "Vistra", "US", "전력·원전", "USD"),
    _a("GEV", "GE Vernova", "US", "전력·원전", "USD"),
    _a("VRT", "Vertiv", "US", "전력·원전", "USD"),
    _a("ETN", "Eaton", "US", "전력·원전", "USD"),
    _a("NEE", "NextEra Energy", "US", "전력·원전", "USD"),
    _a("CCJ", "Cameco", "US", "전력·원전", "USD"),
    _a("XOM", "Exxon Mobil", "US", "전력·원전", "USD"),
    # 방산·조선·우주 (6)
    _a("LMT", "Lockheed Martin", "US", "방산·조선·우주", "USD"),
    _a("RTX", "RTX Corp", "US", "방산·조선·우주", "USD"),
    _a("NOC", "Northrop Grumman", "US", "방산·조선·우주", "USD"),
    _a("GD", "General Dynamics", "US", "방산·조선·우주", "USD"),
    _a("RKLB", "Rocket Lab", "US", "방산·조선·우주", "USD"),
    _a("AXON", "Axon Enterprise", "US", "방산·조선·우주", "USD"),
    # 로봇·모빌리티 (4)
    _a("TSLA", "Tesla", "US", "로봇·모빌리티", "USD"),
    _a("ISRG", "Intuitive Surgical", "US", "로봇·모빌리티", "USD"),
    _a("UBER", "Uber", "US", "로봇·모빌리티", "USD"),
    _a("DE", "Deere & Co", "US", "로봇·모빌리티", "USD"),
    # 바이오·헬스케어 (7)
    _a("LLY", "Eli Lilly", "US", "바이오·헬스케어", "USD"),
    _a("NVO", "Novo Nordisk", "US", "바이오·헬스케어", "USD"),
    _a("UNH", "UnitedHealth", "US", "바이오·헬스케어", "USD"),
    _a("JNJ", "Johnson & Johnson", "US", "바이오·헬스케어", "USD"),
    _a("ABBV", "AbbVie", "US", "바이오·헬스케어", "USD"),
    _a("VRTX", "Vertex Pharma", "US", "바이오·헬스케어", "USD"),
    _a("AMGN", "Amgen", "US", "바이오·헬스케어", "USD"),
    # 2차전지·소재 (3)
    _a("ALB", "Albemarle", "US", "2차전지·소재", "USD"),
    _a("ENPH", "Enphase Energy", "US", "2차전지·소재", "USD"),
    _a("FCX", "Freeport-McMoRan", "US", "2차전지·소재", "USD"),
    # 금융·가치·ETF (12)
    _a("BRK-B", "Berkshire Hathaway", "US", "금융·가치·ETF", "USD"),
    _a("JPM", "JPMorgan", "US", "금융·가치·ETF", "USD"),
    _a("GS", "Goldman Sachs", "US", "금융·가치·ETF", "USD"),
    _a("V", "Visa", "US", "금융·가치·ETF", "USD"),
    _a("MA", "Mastercard", "US", "금융·가치·ETF", "USD"),
    _a("COIN", "Coinbase", "US", "금융·가치·ETF", "USD"),
    _a("MSTR", "Strategy (MSTR)", "US", "금융·가치·ETF", "USD"),
    _a("HOOD", "Robinhood", "US", "금융·가치·ETF", "USD"),
    _a("QQQ", "Invesco QQQ", "US", "금융·가치·ETF", "USD"),
    _a("SPY", "SPDR S&P 500", "US", "금융·가치·ETF", "USD"),
    _a("SOXX", "iShares Semiconductor", "US", "금융·가치·ETF", "USD"),
    _a("GLD", "SPDR Gold ETF", "US", "금융·가치·ETF", "USD"),
    # 소비·엔터·K뷰티 (6)
    _a("NFLX", "Netflix", "US", "소비·엔터·K뷰티", "USD"),
    _a("DIS", "Disney", "US", "소비·엔터·K뷰티", "USD"),
    _a("COST", "Costco", "US", "소비·엔터·K뷰티", "USD"),
    _a("WMT", "Walmart", "US", "소비·엔터·K뷰티", "USD"),
    _a("HD", "Home Depot", "US", "소비·엔터·K뷰티", "USD"),
    _a("PG", "Procter & Gamble", "US", "소비·엔터·K뷰티", "USD"),

    # ==================== 암호화폐 30종목 (CRYPTO) ====================
    _a("BTC-USD", "Bitcoin", "CRYPTO", "코인·디지털자산", "USD"),
    _a("ETH-USD", "Ethereum", "CRYPTO", "코인·디지털자산", "USD"),
    _a("SOL-USD", "Solana", "CRYPTO", "코인·디지털자산", "USD"),
    _a("XRP-USD", "XRP", "CRYPTO", "코인·디지털자산", "USD"),
    _a("BNB-USD", "BNB", "CRYPTO", "코인·디지털자산", "USD"),
    _a("ADA-USD", "Cardano", "CRYPTO", "코인·디지털자산", "USD"),
    _a("DOGE-USD", "Dogecoin", "CRYPTO", "코인·디지털자산", "USD"),
    _a("AVAX-USD", "Avalanche", "CRYPTO", "코인·디지털자산", "USD"),
    _a("LINK-USD", "Chainlink", "CRYPTO", "코인·디지털자산", "USD"),
    _a("TRX-USD", "TRON", "CRYPTO", "코인·디지털자산", "USD"),
    _a("DOT-USD", "Polkadot", "CRYPTO", "코인·디지털자산", "USD"),
    _a("LTC-USD", "Litecoin", "CRYPTO", "코인·디지털자산", "USD"),
    _a("BCH-USD", "Bitcoin Cash", "CRYPTO", "코인·디지털자산", "USD"),
    _a("XLM-USD", "Stellar", "CRYPTO", "코인·디지털자산", "USD"),
    _a("ATOM-USD", "Cosmos", "CRYPTO", "코인·디지털자산", "USD"),
    _a("ETC-USD", "Ethereum Classic", "CRYPTO", "코인·디지털자산", "USD"),
    _a("ALGO-USD", "Algorand", "CRYPTO", "코인·디지털자산", "USD"),
    _a("VET-USD", "VeChain", "CRYPTO", "코인·디지털자산", "USD"),
    _a("HBAR-USD", "Hedera", "CRYPTO", "코인·디지털자산", "USD"),
    _a("NEAR-USD", "NEAR Protocol", "CRYPTO", "코인·디지털자산", "USD"),
    _a("SUI20947-USD", "Sui", "CRYPTO", "코인·디지털자산", "USD"),
    _a("FET-USD", "Fetch.ai (ASI)", "CRYPTO", "AI·반도체", "USD"),
    _a("UNI7083-USD", "Uniswap", "CRYPTO", "코인·디지털자산", "USD"),
    _a("AAVE-USD", "Aave", "CRYPTO", "코인·디지털자산", "USD"),
    _a("SHIB-USD", "Shiba Inu", "CRYPTO", "코인·디지털자산", "USD"),
    _a("PEPE24478-USD", "Pepe", "CRYPTO", "코인·디지털자산", "USD"),
    _a("INJ-USD", "Injective", "CRYPTO", "코인·디지털자산", "USD"),
    _a("ICP-USD", "Internet Computer", "CRYPTO", "코인·디지털자산", "USD"),
    _a("FIL-USD", "Filecoin", "CRYPTO", "코인·디지털자산", "USD"),
    _a("TAO22974-USD", "Bittensor (AI)", "CRYPTO", "AI·반도체", "USD"),
]

ASSET_MAP: dict[str, AssetInfo] = {a["symbol"]: a for a in ASSETS}

DEFAULT_SETTINGS = {
    "short_window": 45,
    "long_window": 180,
    "price_source": "wick",  # "wick" (High/Low) | "body" (Close)
    "scale_mode": "linear",  # "linear" | "log"
    "fee_rate": 0.001,  # 0.1% per side (0.2% round-trip)
    "near_threshold_pct": 3.0,  # 돌파 임박 기준 (%)
    "active_strategy": "AUTO_BEST",
    "exit_rule": "default",
    "alerts": {
        "macos_enabled": False,
        "telegram_enabled": False,
        "telegram_bot_token": "",
        "telegram_chat_id": "",
        "discord_enabled": False,
        "discord_webhook_url": "",
        "notify_near_breakout": True,
    },
}


def load_settings() -> dict:
    if not SETTINGS_PATH.exists():
        save_settings(DEFAULT_SETTINGS)
        return json.loads(json.dumps(DEFAULT_SETTINGS))
    try:
        saved = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        merged = json.loads(json.dumps(DEFAULT_SETTINGS))
        for k, v in saved.items():
            if k == "alerts" and isinstance(v, dict):
                merged["alerts"].update(v)
            else:
                merged[k] = v
        return merged
    except Exception:
        return json.loads(json.dumps(DEFAULT_SETTINGS))


def save_settings(settings: dict) -> dict:
    SETTINGS_PATH.write_text(
        json.dumps(settings, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return settings
