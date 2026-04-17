# config.py — single source of truth for all system parameters

from pathlib import Path

# ─── Paths ────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data" / "store"
DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = DATA_DIR / "knvk_backtest.db"
DB_URL = f"sqlite:///{DB_PATH}"          # swap to postgres on AWS

# ─── Universe ─────────────────────────────────────────────────────────────────
# In config.py — replace NIFTY_100_SYMBOLS and add SYMBOL_MAP

NIFTY_100_SYMBOLS = [
    "RELIANCE", "TCS", "HDFCBANK", "BHARTIARTL", "ICICIBANK",
    "INFY", "SBIN", "HINDUNILVR", "ITC", "KOTAKBANK",
    "LT", "AXISBANK", "WIPRO", "HCLTECH", "BAJFINANCE",
    "MARUTI", "SUNPHARMA", "ULTRACEMCO", "TITAN", "NESTLEIND",
    "ASIANPAINT", "ADANIENT", "POWERGRID", "NTPC", "ONGC",
    "TECHM", "BAJAJFINSV", "PERSISTENT", "DRREDDY", "CIPLA",
    "COALINDIA", "JSWSTEEL", "TATASTEEL", "HINDALCO", "GRASIM",
    "INDUSINDBK", "BRITANNIA", "EICHERMOT", "DIVISLAB", "BPCL",
    "TATACONSUM", "APOLLOHOSP", "SBILIFE", "HDFCLIFE", "BAJAJ-AUTO",
    "HEROMOTOCO", "ADANIPORTS", "SHRIRAMFIN", "LTIM", "PIDILITIND",
    "CHOLAFIN", "HAVELLS", "DABUR", "MARICO", "SIEMENS",
    "TORNTPHARM", "MUTHOOTFIN", "LUPIN", "BIOCON", "BOSCHLTD",
    "AMBUJACEM", "ACC", "INDIGO", "TRENT", "DIXON",
    "DMART", "NAUKRI", "PAYTM", "POLICYBZR", "IRCTC",
    "MOTHERSON", "ESCORTS", "VOLTAS", "CONCOR", "BHEL",
    "SAIL", "NMDC", "GAIL", "IOC", "HINDPETRO",
    "BANKBARODA", "PNB", "CANBK", "FEDERALBNK", "IDFCFIRSTB",
    "AUROPHARMA", "ALKEM", "GLAXO", "PFIZER", "ABBOTINDIA",
    "COLPAL", "GODREJCP", "EMAMILTD", "PGHH", "UNITDSPR",
    "UBL", "RADICO", "OBEROIRLTY", "DLF", "PRESTIGE",
]

STABLE_SYMBOLS = [
    'HDFCBANK', 'KOTAKBANK', 'BAJFINANCE', 'NESTLEIND',
    'ASIANPAINT', 'ADANIENT', 'BAJAJFINSV', 'SBILIFE',
    'ADANIPORTS', 'CHOLAFIN', 'TORNTPHARM', 'BIOCON',
    'BHEL', 'GAIL', 'BANKBARODA', 'IDFCFIRSTB', 'DLF'
]

# Symbols where mean reversion signal is structurally broken
# Based on backtest pf < 0.5 across 3 years

EXCLUDED_SYMBOLS = [
    # original exclusions
    'ITC', 'HCLTECH', 'NTPC', 'PERSISTENT', 'GRASIM', 'BPCL',
    'HDFCLIFE', 'LTIM', 'PIDILITIND', 'HAVELLS', 'AMBUJACEM',
    'ACC', 'TRENT', 'NAUKRI', 'IRCTC', 'VOLTAS', 'GLAXO',
    'COLPAL', 'GODREJCP', 'UNITDSPR', 'NMDC', 'TATACONSUM',
    # removing loss-making marginal stocks
    'RELIANCE', 'LT', 'TITAN', 'BRITANNIA', 'HEROMOTOCO',
    'MARICO', 'ALKEM', 'ABBOTINDIA', 'PGHH', 'OBEROIRLTY'
]

# clear breakout list — no longer needed
BREAKOUT_SYMBOLS = []

ACTIVE_SYMBOLS = [s for s in NIFTY_100_SYMBOLS if s not in EXCLUDED_SYMBOLS]

# Kotak Neo instrument tokens for stable universe
KOTAK_TOKEN_MAP = {
    'HDFCBANK':   '1333',
    'KOTAKBANK':  '1922',
    'BAJFINANCE': '317',
    'NESTLEIND':  '17963',
    'ASIANPAINT': '236',
    'ADANIENT':   '25',
    'BAJAJFINSV': '16675',
    'SBILIFE':    '21808',
    'ADANIPORTS': '15083',
    'CHOLAFIN':   '685',
    'TORNTPHARM': '3518',
    'BIOCON':     '11373',
    'BHEL':       '438',
    'GAIL':       '4717',
    'BANKBARODA': '4668',
    'IDFCFIRSTB': '11184',
    'DLF':        '14732',
}

# Maps our clean symbol name → actual yFinance ticker
# Only needed for symbols that don't follow the simple SYMBOL.NS pattern
SYMBOL_MAP = {
    "INFY":      "INFY.NS",        # INFOSYS trades as INFY on Yahoo
    "TMPV":      "TMPV.NS",        # Tata Motors PV (renamed Oct 2025)
    "UNITDSPR":  "UNITDSPR.NS",    # United Spirits / McDowell
    "BAJAJ-AUTO": "BAJAJ-AUTO.NS", # hyphen preserved
    "MCDOWELL-N": "UNITDSPR.NS",   # alias → same stock
}
# ─── Data parameters ──────────────────────────────────────────────────────────
DAILY_START_DATE   = "2021-01-01"
DAILY_END_DATE     = "2024-12-31"
INTRADAY_INTERVAL  = "15m"
DAILY_INTERVAL     = "1d"

# ─── Regime thresholds ────────────────────────────────────────────────────────
VIX_TREND          = 15.0
VIX_NEUTRAL_HIGH   = 20.0
VIX_CAUTION_HIGH   = 30.0

# ─── Signal parameters ────────────────────────────────────────────────────────
ZSCORE_PERIOD      = 20
ZSCORE_THRESHOLD   = 2.5
ATR_PERIOD         = 14
VWAP_STRETCH_ATR   = 1.5

# ─── Risk parameters ─────────────────────────────────────────────────────────
RISK_PER_TRADE_PCT = 0.005         # 1% base risk
MAX_RISK_PCT       = 0.015         # 1.5% max
MAX_POSITIONS      = 5            # intraday concurrent
MAX_TRADES_DAY     = 12
DAILY_LOSS_LIMIT   = 0.01         # 2% kill switch

# ATR multiplier by VIX regime
ATR_MULTIPLIER = {
    "TREND":   1.5,
    "NEUTRAL": 2.0,
    "CAUTION": 2.5,
    "CHAOS":   0.0,                # no trades
}

# ─── Cost model (Kotak Neo, NSE, intraday equity) ─────────────────────────────
COST = {
    "brokerage_pct":    0.0,       # ₹0 Kotak Neo API
    "stt_sell_pct":     0.00025,   # 0.025% sell side
    "txn_charge_pct":   0.0000345, # NSE 0.00345% both sides
    "sebi_per_crore":   10.0,
    "gst_pct":          0.18,      # on brokerage+txn+sebi
    "stamp_buy_pct":    0.00003,   # 0.003% buy side only
    "slippage_pct":     0.0005,    # 0.05% conservative estimate
}

# ─── Backtester settings ──────────────────────────────────────────────────────
EV_FRICTION_MULTIPLIER = 1.0      # ev_net must exceed friction once
MIN_RR_RATIO           = 2.0      # minimum reward:risk ratio
MIN_WIN_RATE           = 0.40     # minimum assumed win probability
PARTIAL_EXIT_1_R       = 1.0      # take 50% at 1R
PARTIAL_EXIT_2_R       = 2.0      # take 25% at 2R
MIN_ATR_PCT = 0.015    # ATR must be >= 1.5% of price