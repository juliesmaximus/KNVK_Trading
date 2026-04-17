# check_trade.py — check specific trade details

import sqlite3
from config import DB_PATH

conn = sqlite3.connect(DB_PATH)
rows = conn.execute("""
    SELECT symbol, direction, entry_price,
           stop_price, target1, target2, qty_remaining
    FROM paper_trades
    WHERE status = 'OPEN'
    ORDER BY symbol
""").fetchall()
conn.close()

print(f"{'Symbol':<15} {'Dir':<6} {'Entry':>8} {'Stop':>8} {'T1':>8} {'T2':>8} {'Qty':>6}")
print("─" * 65)
for r in rows:
    direction = "LONG" if r[1] == 1 else "SHORT"
    print(f"{r[0]:<15} {direction:<6} "
          f"₹{r[2]:>7.2f} ₹{r[3]:>7.2f} "
          f"₹{r[4]:>7.2f} ₹{r[5]:>7.2f} {r[6]:>6}")