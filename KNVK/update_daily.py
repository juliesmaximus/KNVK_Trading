# update_daily.py — run every morning before market open

from data.downloader import download_universe, init_db
from config import STABLE_SYMBOLS
from datetime import date, timedelta

today     = date.today().strftime("%Y-%m-%d")
yesterday = (date.today() - timedelta(days=3)).strftime("%Y-%m-%d")

print(f"Updating data: {yesterday} → {today}")
download_universe(
    symbols = STABLE_SYMBOLS,
    start   = yesterday,
    end     = today
)
print("Data update complete.")