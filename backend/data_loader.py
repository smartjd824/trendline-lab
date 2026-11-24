"""Market data loader with local SQLite cache for 30 KR/US/Crypto assets."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Iterable

import pandas as pd
import yfinance as yf

from config import ASSET_MAP, ASSETS, DB_PATH, INDEX_MAP, INDICES


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ohlcv (
            symbol TEXT NOT NULL,
            date TEXT NOT NULL,
            open REAL NOT NULL,
            high REAL NOT NULL,
            low REAL NOT NULL,
            close REAL NOT NULL,
            volume REAL NOT NULL,
            PRIMARY KEY (symbol, date)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sync_meta (
            symbol TEXT PRIMARY KEY,
            last_updated TEXT NOT NULL,
            rows_count INTEGER NOT NULL,
            first_date TEXT,
            last_date TEXT
        )
        """
    )
    conn.commit()
    return conn


def _normalize_yf_df(raw: pd.DataFrame, symbol: str) -> pd.DataFrame:
    if raw is None or raw.empty:
        return pd.DataFrame()
    df = raw.copy()
    if isinstance(df.columns, pd.MultiIndex):
        if symbol in df.columns.get_level_values(-1):
            df = df.xs(symbol, axis=1, level=-1)
        elif symbol in df.columns.get_level_values(0):
            df = df.xs(symbol, axis=1, level=0)
        else:
            df.columns = [c[0] for c in df.columns]

    rename_map = {c: str(c).strip().lower() for c in df.columns}
    df = df.rename(columns=rename_map)
    required = ["open", "high", "low", "close"]
    if not all(col in df.columns for col in required):
        return pd.DataFrame()
    if "volume" not in df.columns:
        df["volume"] = 0.0

    df = df[["open", "high", "low", "close", "volume"]].copy()
    df = df.dropna(subset=["open", "high", "low", "close"])
    df = df[df["close"] > 0]
    df["volume"] = df["volume"].fillna(0.0)
    idx = pd.to_datetime(df.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    df.index = idx.strftime("%Y-%m-%d")
    df = df[~df.index.duplicated(keep="last")].sort_index()
    return df


def fetch_and_cache_symbols(
    symbols: Iterable[str] | None = None,
    years: float = 7.6,
    force: bool = False,
) -> dict:
    """Download daily OHLCV via yfinance and upsert into local SQLite cache."""
    target_symbols = list(symbols) if symbols else ([a["symbol"] for a in ASSETS] + [i["symbol"] for i in INDICES])
    conn = _get_conn()
    now_iso = datetime.now(timezone.utc).isoformat()
    start_date = (datetime.now() - timedelta(days=int(years * 365))).strftime("%Y-%m-%d")

    # Determine which symbols actually need refreshing (older than 4 hours unless forced)
    to_fetch: list[str] = []
    if force:
        to_fetch = target_symbols
    else:
        cur = conn.execute("SELECT symbol, last_updated, rows_count FROM sync_meta")
        meta = {row[0]: (row[1], row[2]) for row in cur.fetchall()}
        cutoff = datetime.now(timezone.utc) - timedelta(hours=4)
        for sym in target_symbols:
            if sym not in meta or meta[sym][1] < 250:
                to_fetch.append(sym)
            else:
                try:
                    ts = datetime.fromisoformat(meta[sym][0])
                    if ts < cutoff:
                        to_fetch.append(sym)
                except Exception:
                    to_fetch.append(sym)

    updated: list[str] = []
    failed: list[dict] = []

    if to_fetch:
        # Batch download in chunks of 10 for reliability and speed
        chunk_size = 10
        for i in range(0, len(to_fetch), chunk_size):
            chunk = to_fetch[i : i + chunk_size]
            try:
                raw = yf.download(
                    tickers=" ".join(chunk),
                    start=start_date,
                    interval="1d",
                    auto_adjust=True,
                    progress=False,
                    threads=True,
                    group_by="ticker" if len(chunk) > 1 else "column",
                )
            except Exception:
                raw = pd.DataFrame()

            for sym in chunk:
                try:
                    sub = raw[sym] if (len(chunk) > 1 and isinstance(raw.columns, pd.MultiIndex) and sym in raw.columns.get_level_values(0)) else raw
                    df = _normalize_yf_df(sub, sym)
                    if df.empty or len(df) < 50:
                        # Fallback individual fetch
                        single = yf.Ticker(sym).history(start=start_date, interval="1d", auto_adjust=True)
                        df = _normalize_yf_df(single, sym)
                    if df.empty:
                        failed.append({"symbol": sym, "error": "No data returned"})
                        continue

                    rows = [
                        (sym, d, float(r.open), float(r.high), float(r.low), float(r.close), float(r.volume))
                        for d, r in df.iterrows()
                    ]
                    conn.executemany(
                        """
                        INSERT OR REPLACE INTO ohlcv (symbol, date, open, high, low, close, volume)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        rows,
                    )
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO sync_meta (symbol, last_updated, rows_count, first_date, last_date)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (sym, now_iso, len(rows), rows[0][1], rows[-1][1]),
                    )
                    conn.commit()
                    updated.append(sym)
                except Exception as exc:
                    failed.append({"symbol": sym, "error": str(exc)})

    conn.close()
    return {
        "requested": len(target_symbols),
        "fetched": len(to_fetch),
        "updated": updated,
        "failed": failed,
    }


def load_ohlcv(symbol: str, auto_fetch: bool = True) -> pd.DataFrame:
    """Load daily OHLCV DataFrame for one symbol from SQLite cache."""
    conn = _get_conn()
    df = pd.read_sql_query(
        """
        SELECT date, open, high, low, close, volume
        FROM ohlcv
        WHERE symbol = ?
        ORDER BY date ASC
        """,
        conn,
        params=(symbol,),
    )
    conn.close()

    if df.empty and auto_fetch:
        fetch_and_cache_symbols([symbol], force=True)
        conn = _get_conn()
        df = pd.read_sql_query(
            """
            SELECT date, open, high, low, close, volume
            FROM ohlcv
            WHERE symbol = ?
            ORDER BY date ASC
            """,
            conn,
            params=(symbol,),
        )
        conn.close()

    if not df.empty:
        df["date_dt"] = pd.to_datetime(df["date"])
    return df


def load_all_cached_ohlcv() -> dict[str, pd.DataFrame]:
    """Load all 30 assets from SQLite in one pass for fast batch backtesting."""
    conn = _get_conn()
    all_df = pd.read_sql_query(
        """
        SELECT symbol, date, open, high, low, close, volume
        FROM ohlcv
        ORDER BY symbol ASC, date ASC
        """,
        conn,
    )
    conn.close()

    result: dict[str, pd.DataFrame] = {}
    if all_df.empty:
        return result
    for sym, grp in all_df.groupby("symbol", sort=False):
        if sym in ASSET_MAP or sym in INDEX_MAP:
            g = grp.drop(columns=["symbol"]).reset_index(drop=True)
            g["date_dt"] = pd.to_datetime(g["date"])
            result[str(sym)] = g
    return result


def get_cache_status() -> dict:
    """Return metadata about cached data for all 30 assets."""
    conn = _get_conn()
    cur = conn.execute("SELECT symbol, last_updated, rows_count, first_date, last_date FROM sync_meta")
    rows = {r[0]: {"last_updated": r[1], "rows": r[2], "first_date": r[3], "last_date": r[4]} for r in cur.fetchall()}
    conn.close()

    assets_status = []
    for asset in ASSETS:
        meta = rows.get(asset["symbol"])
        assets_status.append(
            {
                **asset,
                "cached": meta is not None and meta["rows"] > 0,
                "rows": meta["rows"] if meta else 0,
                "first_date": meta["first_date"] if meta else None,
                "last_date": meta["last_date"] if meta else None,
                "last_updated": meta["last_updated"] if meta else None,
            }
        )

    cached_count = sum(1 for a in assets_status if a["cached"])
    return {
        "total": len(ASSETS),
        "cached": cached_count,
        "ready": cached_count == len(ASSETS),
        "assets": assets_status,
    }
