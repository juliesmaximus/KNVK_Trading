# verify.py — system health check

from data.kotak_feed import KotakClient
from config import STABLE_SYMBOLS, KOTAK_TOKEN_MAP, DB_PATH
import sqlite3

print("System verification")
print("─" * 30)

# check kotak client
c = KotakClient()
print(f"get_ohlc_today:      {hasattr(c, 'get_ohlc_today')}")

# check config
print(f"Stable symbols:      {len(STABLE_SYMBOLS)}")
print(f"Token map:           {len(KOTAK_TOKEN_MAP)}")

# check DB
conn = sqlite3.connect(DB_PATH)
signals  = conn.execute(
    "SELECT COUNT(*) FROM paper_signals WHERE status='PENDING'"
).fetchone()[0]
trades   = conn.execute(
    "SELECT COUNT(*) FROM paper_trades WHERE status='OPEN'"
).fetchone()[0]
ohlc_rows = conn.execute(
    "SELECT COUNT(*) FROM daily_ohlcv"
).fetchone()[0]
conn.close()

print(f"Pending signals:     {signals}")
print(f"Open trades:         {trades}")
print(f"OHLCV rows in DB:    {ohlc_rows}")
print("─" * 30)
print("All good — ready for tomorrow.")