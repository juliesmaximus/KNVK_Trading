# data/downloader.py — fetch and store historical OHLCV via yFinance
# yFinance used on local machine only — AWS reads from DB directly

import sys
sys.path.append(str(__import__('pathlib').Path(__file__).parent.parent))

import pandas as pd
import sqlite3
import time
from config import (
    NIFTY_100_SYMBOLS, DAILY_START_DATE, DAILY_END_DATE, DB_PATH
)

# yFinance only available on local machine
try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except ImportError:
    YFINANCE_AVAILABLE = False


# ─── Database setup ───────────────────────────────────────────────────────────

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS daily_ohlcv (
            symbol  TEXT,
            date    TEXT,
            open    REAL,
            high    REAL,
            low     REAL,
            close   REAL,
            volume  REAL,
            PRIMARY KEY (symbol, date)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS vix_daily (
            date    TEXT PRIMARY KEY,
            open    REAL,
            high    REAL,
            low     REAL,
            close   REAL
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS download_log (
            symbol    TEXT,
            interval  TEXT,
            last_date TEXT,
            status    TEXT,
            PRIMARY KEY (symbol, interval)
        )
    """)
    conn.commit()
    conn.close()
    print("DB initialised:", DB_PATH)


# ─── Fetch helpers ────────────────────────────────────────────────────────────

def fetch_daily(symbol: str, start: str, end: str) -> pd.DataFrame | None:
    if not YFINANCE_AVAILABLE:
        print("yFinance not available — skipping download.")
        return None
    try:
        ticker = yf.Ticker(f"{symbol}.NS")
        raw = ticker.history(start=start, end=end, interval="1d")

        if raw is None or raw.empty:
            return None

        raw.columns = [c.lower() for c in raw.columns]
        raw = raw[["open", "high", "low", "close", "volume"]]
        raw.index = pd.to_datetime(raw.index).tz_localize(None)
        raw.index.name = "date"
        raw = raw.reset_index()
        raw["date"]   = raw["date"].dt.strftime("%Y-%m-%d")
        raw["symbol"] = symbol
        return raw[["symbol", "date", "open", "high", "low", "close", "volume"]]

    except Exception as e:
        print(f"  ERROR {symbol}: {e}")
        return None


def fetch_vix(start: str, end: str) -> pd.DataFrame | None:
    if not YFINANCE_AVAILABLE:
        return None
    try:
        ticker = yf.Ticker("^INDIAVIX")
        raw = ticker.history(start=start, end=end, interval="1d")

        if raw is None or raw.empty:
            return None

        raw.columns = [c.lower() for c in raw.columns]
        raw = raw[["open", "high", "low", "close"]]
        raw.index = pd.to_datetime(raw.index).tz_localize(None)
        raw.index.name = "date"
        raw = raw.reset_index()
        raw["date"] = raw["date"].dt.strftime("%Y-%m-%d")
        return raw[["date", "open", "high", "low", "close"]]

    except Exception as e:
        print(f"  ERROR VIX: {e}")
        return None


# ─── Storage helpers ──────────────────────────────────────────────────────────

def save_daily(df: pd.DataFrame):
    conn = sqlite3.connect(DB_PATH)
    for _, row in df.iterrows():
        conn.execute("""
            INSERT OR IGNORE INTO daily_ohlcv
            (symbol, date, open, high, low, close, volume)
            VALUES (?,?,?,?,?,?,?)
        """, tuple(row))
    conn.commit()
    conn.close()


def save_vix(df: pd.DataFrame):
    conn = sqlite3.connect(DB_PATH)
    for _, row in df.iterrows():
        conn.execute("""
            INSERT OR IGNORE INTO vix_daily
            (date, open, high, low, close)
            VALUES (?,?,?,?,?)
        """, tuple(row))
    conn.commit()
    conn.close()


def log_download(symbol: str, status: str, rows: int):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        INSERT OR REPLACE INTO download_log VALUES (?,?,?,?)
    """, (symbol, "1d", DAILY_END_DATE, status))
    conn.commit()
    conn.close()


# ─── Main download job ────────────────────────────────────────────────────────

def download_universe(
    symbols: list  = NIFTY_100_SYMBOLS,
    start: str     = DAILY_START_DATE,
    end: str       = DAILY_END_DATE,
    delay: float   = 0.3
):
    if not YFINANCE_AVAILABLE:
        print("yFinance not available — cannot download.")
        print("Run this on your local machine.")
        return 0, []

    init_db()
    total   = len(symbols)
    success = 0
    failed  = []

    print(f"\nDownloading daily OHLCV: {start} -> {end}")
    print(f"Symbols: {total} | Source: yFinance (.NS)\n")

    for i, sym in enumerate(symbols, 1):
        print(f"[{i:>3}/{total}] {sym:<20}", end=" ", flush=True)
        df = fetch_daily(sym, start, end)

        if df is not None and not df.empty:
            save_daily(df)
            log_download(sym, "OK", len(df))
            print(f"OK  {len(df)} rows")
            success += 1
        else:
            log_download(sym, "FAIL", 0)
            print("FAIL  no data")
            failed.append(sym)

        time.sleep(delay)

    print(f"\n[VIX] Fetching India VIX...", end=" ", flush=True)
    vdf = fetch_vix(start, end)
    if vdf is not None and not vdf.empty:
        save_vix(vdf)
        print(f"OK  {len(vdf)} rows")
    else:
        print("FAIL")

    print(f"\n{'─'*45}")
    print(f"Complete. Success: {success}/{total}")
    if failed:
        print(f"Failed: {failed}")
    return success, failed


# ─── Load helpers (used by backtester and paper engine) ───────────────────────

def load_symbol(symbol: str) -> pd.DataFrame:
    """Load daily OHLCV for one symbol from DB."""
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql(
        "SELECT * FROM daily_ohlcv WHERE symbol=? ORDER BY date",
        conn, params=(symbol,)
    )
    conn.close()
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date")


def load_vix() -> pd.DataFrame:
    """Load VIX daily from DB."""
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql("SELECT * FROM vix_daily ORDER BY date", conn)
    conn.close()
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date")


if __name__ == "__main__":
    if YFINANCE_AVAILABLE:
        download_universe()
    else:
        print("yFinance not available.")
        print("Run on local machine to download data.")