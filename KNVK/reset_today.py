# reset_today.py — clean today's trades and signals

import sqlite3
from config import DB_PATH
from datetime import date

today = date.today().strftime("%Y-%m-%d")
conn  = sqlite3.connect(DB_PATH)

trades  = conn.execute("DELETE FROM paper_trades  WHERE entry_date  = ?", (today,)).rowcount
signals = conn.execute("DELETE FROM paper_signals WHERE signal_date = ?", (today,)).rowcount

conn.commit()
conn.close()

print(f"Deleted {trades} trades and {signals} signals for {today}")
print("Clean slate — ready to regenerate.")