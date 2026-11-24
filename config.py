"""Project configuration: 150 representative assets (KOSPI 50, KOSDAQ 50, US 30, CRYPTO 20), defaults, and alert settings."""

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
    currency: str


ASSETS: list[AssetInfo] = [
    # ==================== 국내 코스피 대표 50종목 (KOSPI) ====================
    {"symbol": "005930.KS", "name": "삼성전자", "market": "KOSPI", "currency": "KRW"},
    {"symbol": "000660.KS", "name": "SK하이닉스", "market": "KOSPI", "currency": "KRW"},
    {"symbol": "373220.KS", "name": "LG에너지솔루션", "market": "KOSPI", "currency": "KRW"},
    {"symbol": "207940.KS", "name": "삼성바이오로직스", "market": "KOSPI", "currency": "KRW"},
    {"symbol": "005380.KS", "name": "현대차", "market": "KOSPI", "currency": "KRW"},
    {"symbol": "000270.KS", "name": "기아", "market": "KOSPI", "currency": "KRW"},
    {"symbol": "068270.KS", "name": "셀트리온", "market": "KOSPI", "currency": "KRW"},
    {"symbol": "105560.KS", "name": "KB금융", "market": "KOSPI", "currency": "KRW"},
    {"symbol": "055550.KS", "name": "신한지주", "market": "KOSPI", "currency": "KRW"},
    {"symbol": "035420.KS", "name": "NAVER", "market": "KOSPI", "currency": "KRW"},
    {"symbol": "035720.KS", "name": "카카오", "market": "KOSPI", "currency": "KRW"},
    {"symbol": "005490.KS", "name": "POSCO홀딩스", "market": "KOSPI", "currency": "KRW"},
    {"symbol": "051910.KS", "name": "LG화학", "market": "KOSPI", "currency": "KRW"},
    {"symbol": "006400.KS", "name": "삼성SDI", "market": "KOSPI", "currency": "KRW"},
    {"symbol": "012330.KS", "name": "현대모비스", "market": "KOSPI", "currency": "KRW"},
    {"symbol": "028260.KS", "name": "삼성물산", "market": "KOSPI", "currency": "KRW"},
    {"symbol": "032830.KS", "name": "삼성생명", "market": "KOSPI", "currency": "KRW"},
    {"symbol": "086790.KS", "name": "하나금융지주", "market": "KOSPI", "currency": "KRW"},
    {"symbol": "316140.KS", "name": "우리금융지주", "market": "KOSPI", "currency": "KRW"},
    {"symbol": "138040.KS", "name": "메리츠금융지주", "market": "KOSPI", "currency": "KRW"},
    {"symbol": "012450.KS", "name": "한화에어로스페이스", "market": "KOSPI", "currency": "KRW"},
    {"symbol": "329180.KS", "name": "HD현대중공업", "market": "KOSPI", "currency": "KRW"},
    {"symbol": "009540.KS", "name": "HD한국조선해양", "market": "KOSPI", "currency": "KRW"},
    {"symbol": "042660.KS", "name": "한화오션", "market": "KOSPI", "currency": "KRW"},
    {"symbol": "010140.KS", "name": "삼성중공업", "market": "KOSPI", "currency": "KRW"},
    {"symbol": "034020.KS", "name": "두산에너빌리티", "market": "KOSPI", "currency": "KRW"},
    {"symbol": "267260.KS", "name": "HD현대일렉트릭", "market": "KOSPI", "currency": "KRW"},
    {"symbol": "010120.KS", "name": "LS ELECTRIC", "market": "KOSPI", "currency": "KRW"},
    {"symbol": "066570.KS", "name": "LG전자", "market": "KOSPI", "currency": "KRW"},
    {"symbol": "003550.KS", "name": "LG", "market": "KOSPI", "currency": "KRW"},
    {"symbol": "034730.KS", "name": "SK", "market": "KOSPI", "currency": "KRW"},
    {"symbol": "096770.KS", "name": "SK이노베이션", "market": "KOSPI", "currency": "KRW"},
    {"symbol": "017670.KS", "name": "SK텔레콤", "market": "KOSPI", "currency": "KRW"},
    {"symbol": "030200.KS", "name": "KT", "market": "KOSPI", "currency": "KRW"},
    {"symbol": "032640.KS", "name": "LG유플러스", "market": "KOSPI", "currency": "KRW"},
    {"symbol": "015760.KS", "name": "한국전력", "market": "KOSPI", "currency": "KRW"},
    {"symbol": "033780.KS", "name": "KT&G", "market": "KOSPI", "currency": "KRW"},
    {"symbol": "000810.KS", "name": "삼성화재", "market": "KOSPI", "currency": "KRW"},
    {"symbol": "003490.KS", "name": "대한항공", "market": "KOSPI", "currency": "KRW"},
    {"symbol": "011200.KS", "name": "HMM", "market": "KOSPI", "currency": "KRW"},
    {"symbol": "009150.KS", "name": "삼성전기", "market": "KOSPI", "currency": "KRW"},
    {"symbol": "018260.KS", "name": "삼성에스디에스", "market": "KOSPI", "currency": "KRW"},
    {"symbol": "259960.KS", "name": "크래프톤", "market": "KOSPI", "currency": "KRW"},
    {"symbol": "352820.KS", "name": "하이브", "market": "KOSPI", "currency": "KRW"},
    {"symbol": "064350.KS", "name": "현대로템", "market": "KOSPI", "currency": "KRW"},
    {"symbol": "047810.KS", "name": "한국항공우주", "market": "KOSPI", "currency": "KRW"},
    {"symbol": "000100.KS", "name": "유한양행", "market": "KOSPI", "currency": "KRW"},
    {"symbol": "090430.KS", "name": "아모레퍼시픽", "market": "KOSPI", "currency": "KRW"},
    {"symbol": "010950.KS", "name": "S-Oil", "market": "KOSPI", "currency": "KRW"},
    {"symbol": "003670.KS", "name": "포스코퓨처엠", "market": "KOSPI", "currency": "KRW"},
    # ==================== 국내 코스닥 대표 50종목 (KOSDAQ) ====================
    {"symbol": "196170.KQ", "name": "알테오젠", "market": "KOSDAQ", "currency": "KRW"},
    {"symbol": "247540.KQ", "name": "에코프로비엠", "market": "KOSDAQ", "currency": "KRW"},
    {"symbol": "086520.KQ", "name": "에코프로", "market": "KOSDAQ", "currency": "KRW"},
    {"symbol": "028300.KQ", "name": "HLB", "market": "KOSDAQ", "currency": "KRW"},
    {"symbol": "277810.KQ", "name": "레인보우로보틱스", "market": "KOSDAQ", "currency": "KRW"},
    {"symbol": "141080.KQ", "name": "리가켐바이오", "market": "KOSDAQ", "currency": "KRW"},
    {"symbol": "214450.KQ", "name": "파마리서치", "market": "KOSDAQ", "currency": "KRW"},
    {"symbol": "145020.KQ", "name": "휴젤", "market": "KOSDAQ", "currency": "KRW"},
    {"symbol": "214150.KQ", "name": "클래시스", "market": "KOSDAQ", "currency": "KRW"},
    {"symbol": "000250.KQ", "name": "삼천당제약", "market": "KOSDAQ", "currency": "KRW"},
    {"symbol": "087010.KQ", "name": "펩트론", "market": "KOSDAQ", "currency": "KRW"},
    {"symbol": "058470.KQ", "name": "리노공업", "market": "KOSDAQ", "currency": "KRW"},
    {"symbol": "403870.KQ", "name": "HPSP", "market": "KOSDAQ", "currency": "KRW"},
    {"symbol": "035900.KQ", "name": "JYP Ent.", "market": "KOSDAQ", "currency": "KRW"},
    {"symbol": "041510.KQ", "name": "에스엠", "market": "KOSDAQ", "currency": "KRW"},
    {"symbol": "122870.KQ", "name": "와이지엔터테인먼트", "market": "KOSDAQ", "currency": "KRW"},
    {"symbol": "263750.KQ", "name": "펄어비스", "market": "KOSDAQ", "currency": "KRW"},
    {"symbol": "293490.KQ", "name": "카카오게임즈", "market": "KOSDAQ", "currency": "KRW"},
    {"symbol": "112040.KQ", "name": "위메이드", "market": "KOSDAQ", "currency": "KRW"},
    {"symbol": "253450.KQ", "name": "스튜디오드래곤", "market": "KOSDAQ", "currency": "KRW"},
    {"symbol": "068760.KQ", "name": "셀트리온제약", "market": "KOSDAQ", "currency": "KRW"},
    {"symbol": "298380.KQ", "name": "에이비엘바이오", "market": "KOSDAQ", "currency": "KRW"},
    {"symbol": "237690.KQ", "name": "에스티팜", "market": "KOSDAQ", "currency": "KRW"},
    {"symbol": "096530.KQ", "name": "씨젠", "market": "KOSDAQ", "currency": "KRW"},
    {"symbol": "214370.KQ", "name": "케어젠", "market": "KOSDAQ", "currency": "KRW"},
    {"symbol": "005290.KQ", "name": "동진쎄미켐", "market": "KOSDAQ", "currency": "KRW"},
    {"symbol": "357780.KQ", "name": "솔브레인", "market": "KOSDAQ", "currency": "KRW"},
    {"symbol": "240810.KQ", "name": "원익IPS", "market": "KOSDAQ", "currency": "KRW"},
    {"symbol": "039030.KQ", "name": "이오테크닉스", "market": "KOSDAQ", "currency": "KRW"},
    {"symbol": "036930.KQ", "name": "주성엔지니어링", "market": "KOSDAQ", "currency": "KRW"},
    {"symbol": "089030.KQ", "name": "테크윙", "market": "KOSDAQ", "currency": "KRW"},
    {"symbol": "095340.KQ", "name": "ISC", "market": "KOSDAQ", "currency": "KRW"},
    {"symbol": "140860.KQ", "name": "파크시스템스", "market": "KOSDAQ", "currency": "KRW"},
    {"symbol": "098460.KQ", "name": "고영", "market": "KOSDAQ", "currency": "KRW"},
    {"symbol": "222800.KQ", "name": "심텍", "market": "KOSDAQ", "currency": "KRW"},
    {"symbol": "078600.KQ", "name": "대주전자재료", "market": "KOSDAQ", "currency": "KRW"},
    {"symbol": "348370.KQ", "name": "엔켐", "market": "KOSDAQ", "currency": "KRW"},
    {"symbol": "137400.KQ", "name": "피엔티", "market": "KOSDAQ", "currency": "KRW"},
    {"symbol": "281740.KQ", "name": "레이크머티리얼즈", "market": "KOSDAQ", "currency": "KRW"},
    {"symbol": "257720.KQ", "name": "실리콘투", "market": "KOSDAQ", "currency": "KRW"},
    {"symbol": "035760.KQ", "name": "CJ ENM", "market": "KOSDAQ", "currency": "KRW"},
    {"symbol": "067160.KQ", "name": "SOOP", "market": "KOSDAQ", "currency": "KRW"},
    {"symbol": "086900.KQ", "name": "메디톡스", "market": "KOSDAQ", "currency": "KRW"},
    {"symbol": "048410.KQ", "name": "현대바이오", "market": "KOSDAQ", "currency": "KRW"},
    {"symbol": "032500.KQ", "name": "케이엠더블유", "market": "KOSDAQ", "currency": "KRW"},
    {"symbol": "064760.KQ", "name": "티씨케이", "market": "KOSDAQ", "currency": "KRW"},
    {"symbol": "036540.KQ", "name": "SFA반도체", "market": "KOSDAQ", "currency": "KRW"},
    {"symbol": "056190.KQ", "name": "에스에프에이", "market": "KOSDAQ", "currency": "KRW"},
    {"symbol": "084370.KQ", "name": "유진테크", "market": "KOSDAQ", "currency": "KRW"},
    {"symbol": "067310.KQ", "name": "하나마이크론", "market": "KOSDAQ", "currency": "KRW"},
    # ==================== 미국주식 대표 30종목 (US) ====================
    {"symbol": "AAPL", "name": "Apple", "market": "US", "currency": "USD"},
    {"symbol": "MSFT", "name": "Microsoft", "market": "US", "currency": "USD"},
    {"symbol": "NVDA", "name": "NVIDIA", "market": "US", "currency": "USD"},
    {"symbol": "GOOGL", "name": "Alphabet", "market": "US", "currency": "USD"},
    {"symbol": "AMZN", "name": "Amazon", "market": "US", "currency": "USD"},
    {"symbol": "META", "name": "Meta", "market": "US", "currency": "USD"},
    {"symbol": "TSLA", "name": "Tesla", "market": "US", "currency": "USD"},
    {"symbol": "AVGO", "name": "Broadcom", "market": "US", "currency": "USD"},
    {"symbol": "BRK-B", "name": "Berkshire Hathaway", "market": "US", "currency": "USD"},
    {"symbol": "LLY", "name": "Eli Lilly", "market": "US", "currency": "USD"},
    {"symbol": "JPM", "name": "JPMorgan", "market": "US", "currency": "USD"},
    {"symbol": "V", "name": "Visa", "market": "US", "currency": "USD"},
    {"symbol": "MA", "name": "Mastercard", "market": "US", "currency": "USD"},
    {"symbol": "UNH", "name": "UnitedHealth", "market": "US", "currency": "USD"},
    {"symbol": "XOM", "name": "Exxon Mobil", "market": "US", "currency": "USD"},
    {"symbol": "COST", "name": "Costco", "market": "US", "currency": "USD"},
    {"symbol": "WMT", "name": "Walmart", "market": "US", "currency": "USD"},
    {"symbol": "HD", "name": "Home Depot", "market": "US", "currency": "USD"},
    {"symbol": "PG", "name": "Procter & Gamble", "market": "US", "currency": "USD"},
    {"symbol": "JNJ", "name": "Johnson & Johnson", "market": "US", "currency": "USD"},
    {"symbol": "NFLX", "name": "Netflix", "market": "US", "currency": "USD"},
    {"symbol": "AMD", "name": "AMD", "market": "US", "currency": "USD"},
    {"symbol": "ORCL", "name": "Oracle", "market": "US", "currency": "USD"},
    {"symbol": "CRM", "name": "Salesforce", "market": "US", "currency": "USD"},
    {"symbol": "ADBE", "name": "Adobe", "market": "US", "currency": "USD"},
    {"symbol": "CSCO", "name": "Cisco", "market": "US", "currency": "USD"},
    {"symbol": "QCOM", "name": "Qualcomm", "market": "US", "currency": "USD"},
    {"symbol": "INTC", "name": "Intel", "market": "US", "currency": "USD"},
    {"symbol": "PLTR", "name": "Palantir", "market": "US", "currency": "USD"},
    {"symbol": "DIS", "name": "Disney", "market": "US", "currency": "USD"},
    # ==================== 암호화폐 대표 20종목 (CRYPTO) ====================
    {"symbol": "BTC-USD", "name": "Bitcoin", "market": "CRYPTO", "currency": "USD"},
    {"symbol": "ETH-USD", "name": "Ethereum", "market": "CRYPTO", "currency": "USD"},
    {"symbol": "SOL-USD", "name": "Solana", "market": "CRYPTO", "currency": "USD"},
    {"symbol": "XRP-USD", "name": "XRP", "market": "CRYPTO", "currency": "USD"},
    {"symbol": "BNB-USD", "name": "BNB", "market": "CRYPTO", "currency": "USD"},
    {"symbol": "ADA-USD", "name": "Cardano", "market": "CRYPTO", "currency": "USD"},
    {"symbol": "DOGE-USD", "name": "Dogecoin", "market": "CRYPTO", "currency": "USD"},
    {"symbol": "AVAX-USD", "name": "Avalanche", "market": "CRYPTO", "currency": "USD"},
    {"symbol": "LINK-USD", "name": "Chainlink", "market": "CRYPTO", "currency": "USD"},
    {"symbol": "TRX-USD", "name": "TRON", "market": "CRYPTO", "currency": "USD"},
    {"symbol": "DOT-USD", "name": "Polkadot", "market": "CRYPTO", "currency": "USD"},
    {"symbol": "LTC-USD", "name": "Litecoin", "market": "CRYPTO", "currency": "USD"},
    {"symbol": "BCH-USD", "name": "Bitcoin Cash", "market": "CRYPTO", "currency": "USD"},
    {"symbol": "XLM-USD", "name": "Stellar", "market": "CRYPTO", "currency": "USD"},
    {"symbol": "ATOM-USD", "name": "Cosmos", "market": "CRYPTO", "currency": "USD"},
    {"symbol": "ETC-USD", "name": "Ethereum Classic", "market": "CRYPTO", "currency": "USD"},
    {"symbol": "ALGO-USD", "name": "Algorand", "market": "CRYPTO", "currency": "USD"},
    {"symbol": "VET-USD", "name": "VeChain", "market": "CRYPTO", "currency": "USD"},
    {"symbol": "HBAR-USD", "name": "Hedera", "market": "CRYPTO", "currency": "USD"},
    {"symbol": "NEAR-USD", "name": "NEAR Protocol", "market": "CRYPTO", "currency": "USD"},
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
        "macos_enabled": True,
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
