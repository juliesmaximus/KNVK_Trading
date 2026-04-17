# KNVK Algorithmic Trading System
## Complete Documentation — April 2026

---

## 1. SYSTEM OVERVIEW

KNVK is a retail algorithmic trading system built for Indian equity markets (NSE).
It combines mean reversion signals with institutional-grade risk management,
deployed on AWS EC2 for 24/7 paper trading with a path to live trading.

### Architecture Summary
```
Data Source      → yFinance (historical) + Kotak Neo API (live)
Signal Engine    → Z-score + VWAP stretch + ATR regime filter
Risk Engine      → Fixed fractional sizing + ATR trailing stop
Execution        → Kotak Neo API (paper now, live next)
Dashboard        → Streamlit on AWS EC2
Alerts           → Telegram bot
Learning         → Daily performance tracking + risk multiplier
```

### Key Numbers
```
Universe         → 17 stable symbols (Nifty 100/200)
Backtest period  → 2021-2024 (4 years)
Walk-forward     → 8/8 windows profitable
Avg win rate     → 49.1%
Avg profit factor→ 2.07
Worst drawdown   → -3.6%
Capital          → Rs1,00,000 real + 5x leverage = Rs5,00,000 trading
```

---

## 2. COMPLETE FILE STRUCTURE

```
KNVK/
├── config.py                    # All parameters — single source of truth
├── main.py                      # Full universe backtest runner
├── verify.py                    # System health check
├── reset_today.py               # Clean today's trades/signals
├── update_daily.py              # Download latest OHLCV data
├── check_trade.py               # Show open trade details
├── dashboard.py                 # Streamlit live dashboard
├── morning_test.py              # Run all tests in one command
│
├── data/
│   ├── downloader.py            # yFinance OHLCV downloader (local only)
│   ├── kotak_feed.py            # Kotak Neo live API client
│   ├── universe.py              # Symbol verification
│   └── store/
│       └── knvk_backtest.db     # SQLite database (97,360+ rows)
│
├── backtest/
│   ├── signals.py               # Z-score, ATR, VWAP, regime calculations
│   ├── costs.py                 # Exact NSE charge model
│   ├── engine.py                # Backtester with partial exits
│   └── walkforward.py           # Walk-forward + stable symbol finder
│
├── paper/
│   ├── signals_daily.py         # EOD signal generation
│   ├── order_manager.py         # Paper order lifecycle
│   └── runner.py                # Daily scheduler (engine)
│
├── utils/
│   ├── alerts.py                # Telegram notifications
│   └── learning.py              # Daily learning + risk multiplier
│
└── journal/
    ├── YYYY-MM-DD.log           # Daily trade journal
    ├── live_prices.json         # Live prices from engine (for dashboard)
    └── cron.log                 # Automation logs
```

---

## 3. SYSTEM WORKFLOW

### Daily Automation (Cron on AWS)
```
08:55 AM IST  → update_daily.py       Download yesterday's OHLCV
03:40 PM IST  → signals_daily.py      Generate tomorrow's signals
03:45 PM IST  → learning.py           Update performance + Telegram report
```

### Manual Daily Task (Only one)
```
09:10 AM IST  → SSH into AWS
               tmux attach -t knvk
               Enter TOTP
               Engine runs automatically until 3:30 PM
```

### Engine Daily Flow
```
09:15 AM  Morning open — place limit orders for pending signals
09:20 AM  Monitor every 5 min — check stops/targets
03:10 PM  Force close all positions at market price
03:30 PM  Generate tomorrow's signals
03:45 PM  Learning cycle — update symbol performance
```

---

## 4. SIGNAL LOGIC

### Pre-Screening (Monthly)
```
Quality filter:   ROE rank + ROA rank + D/E rank → top 100
Momentum filter:  6M Sharpe + 1Y Sharpe rank → top 60
Combined:         Intersection → ~40-60 stocks
Walk-forward:     Only trade symbols profitable in BOTH train and test
Final universe:   17 stable symbols
```

### Signal Generation (Daily)
```
Regime check:   VIX < 15 TREND | 15-20 NEUTRAL | 20-30 CAUTION | >30 CHAOS
Z-score:        |Z| > 2.5 on 20-period rolling (15-min)
VWAP stretch:   Price > 1.5x ATR from 20-day rolling VWAP
ATR filter:     ATR/Price > 1.5% (excludes slow movers)
EV check:       EV_net >= friction (min 2:1 RR)
```

### Trade Management
```
Entry:          Limit order on retest (no market orders — SEBI)
Partial 1:      50% exit at 1R, move stop to breakeven
Partial 2:      25% exit at 2R, trail stop to 1R
Remainder:      25% runs with ATR trail
Time exit:      Force close at 3:10 PM IST
```

---

## 5. COST MODEL (Kotak Neo, NSE Intraday)

```
Brokerage:      Rs0 (Kotak Neo API — zero brokerage from Nov 2025)
STT:            0.025% sell side only
NSE Transaction:0.00345% both sides
SEBI charge:    Rs10 per crore
Stamp duty:     0.003% buy side only
GST:            18% on (brokerage + txn + SEBI)
Slippage:       0.05% both sides (conservative estimate)
─────────────────────────────────────────────────────
Total friction: ~Rs32 per Rs1L round trip (0.032%)
Min EV needed:  Rs32 per trade (1x friction)
```

---

## 6. AWS DEPLOYMENT

```
Instance:       t3.small, ap-south-1 (Mumbai)
Elastic IP:     13.235.14.47
OS:             Ubuntu 24.04 LTS
Python:         3.12.3 (venv)
Database:       SQLite (local) → PostgreSQL (future)
Dashboard:      http://13.235.14.47:8501
Session mgr:    tmux (knvk session)
```

### AWS Commands
```bash
# Connect
ssh -i C:\keys\knvk-key.pem ubuntu@13.235.14.47

# Attach to running session
tmux attach -t knvk

# Switch windows inside tmux
Ctrl+B then 0  → engine
Ctrl+B then 1  → dashboard

# Detach (keep running)
Ctrl+B then D

# Start fresh session
tmux new-session -s knvk -n engine
```

---

## 7. STABLE SYMBOLS (17)

```python
STABLE_SYMBOLS = [
    'HDFCBANK', 'KOTAKBANK', 'BAJFINANCE', 'NESTLEIND',
    'ASIANPAINT', 'ADANIENT', 'BAJAJFINSV', 'SBILIFE',
    'ADANIPORTS', 'CHOLAFIN', 'TORNTPHARM', 'BIOCON',
    'BHEL', 'GAIL', 'BANKBARODA', 'IDFCFIRSTB', 'DLF'
]
```

Selected via walk-forward validation — profitable in BOTH
train period (2021-2023) AND test period (2024).

---

## 8. KNOWN BUGS AND ISSUES (As of April 17, 2026)

### CRITICAL — Must fix before live trading

#### Bug 1: Entry price uses yesterday's close, not today's open
```
Problem:  Signal generated at 3:40 PM uses yesterday's close as entry.
          Next morning stock may gap up/down significantly.
          Example: BHEL signal entry Rs292.50, opened at Rs308.
          Paper trades assume unrealistic fills.

Impact:   HIGH — makes paper trading results unrealistic
          Live trading: limit order never fills if price gaps away

Fix needed:
  1. At 9:15 AM fetch today's opening price for each signal
  2. Update entry_price in paper_signals before opening positions
  3. Add gap filter: skip trade if gap > 1% from signal price
```

#### Bug 2: Kotak API timeouts during peak market hours
```
Problem:  Sequential API calls for 17 symbols causes timeouts.
          Only 9/17 symbols get live prices consistently.
          
Fix applied: Batch API call (all 17 in one request) — partial fix
Status:  Batch call works in testing but still some symbols
         returning DB prices in production

Fix needed:
  Replace get_ohlc_today (2 API calls) with single batch LTP call
  Use OHLC only for stop/target checking, LTP for dashboard display
```

#### Bug 3: Engine timezone was UTC not IST
```
Problem:  AWS server runs UTC. Engine triggered morning open at
          3:48 AM IST instead of 9:15 AM IST.
          
Fix applied: Added IST timezone conversion throughout runner.py
Status:  FIXED — now_ist() function used everywhere
```

#### Bug 4: Double authentication (engine + dashboard)
```
Problem:  Engine and dashboard are separate processes.
          Both need TOTP authentication separately.
          
Fix applied: Engine writes live_prices.json, dashboard reads it.
Status:  PARTIALLY FIXED — dashboard reads JSON file
         but LTP still shows 0 for some symbols (Bug 2)
```

### IMPORTANT — Fix before live trading

#### Bug 5: Morning open window too narrow
```
Problem:  Engine only triggers morning open 9:15-10:00 AM.
          If started late (laptop issues, power cuts), positions
          never open for the day.
          
Fix applied: Extended window to 9:15-11:00 AM
Status:  NEEDS DEPLOYMENT to AWS
```

#### Bug 6: Position carry-over not fully tested
```
Problem:  Multi-day swing trades should carry overnight.
          Not tested with real multi-day scenarios yet.
Status:  Code written, untested in production
```

#### Bug 7: No gap-up/gap-down handling
```
Problem:  If stock gaps significantly from signal price,
          system still enters at signal price (unrealistic).
Status:  Not implemented
```

---

## 9. CHANGES TO BE ADDED (Priority Order)

### Before Live Trading (Critical)
```
1. Entry price fix
   - Fetch today's open at 9:15 AM
   - Update signal entry prices before placing orders
   - Add gap filter (skip if gap > 1%)

2. Live order execution engine
   - place_order() via Kotak Neo API
   - Order fill verification
   - Capital validation (check margin before order)
   - Duplicate order prevention
   - Emergency close all via Telegram command

3. PAPER_TRADE = True/False flag
   - Single config change to go live
   - Paper and live trades tagged separately in DB
   - Never mix paper and live results

4. Zerodha as primary data feed
   - More stable than Kotak during peak hours
   - Use for historical data + live feed
   - Kotak for order execution only (zero brokerage)

5. Capital reconciliation
   - Compare DB positions vs Kotak actual positions
   - Alert if mismatch detected
   - Run at start of day and end of day

6. Shared session (engine + dashboard)
   - One TOTP at startup
   - Both engine and dashboard use same authenticated session
   - No double authentication
```

### After First Month Live (Important)
```
7. Bracket orders via Kotak
   - Place entry + stop + target in one order
   - Reduces manual intervention

8. GTT (Good Till Trigger) orders
   - Place next day's orders the night before
   - Automatic entry without manual morning run

9. Telegram command interface
   - /status — show open positions
   - /close_all — emergency close
   - /pause — stop new entries
   - /resume — restart trading

10. Walk-forward retraining
    - Monthly re-run of stable symbol selection
    - Auto-update STABLE_SYMBOLS based on live performance

11. Intraday layer (15-min signals)
    - Add intraday Z-score on top of daily signals
    - More trade opportunities
    - Higher capital utilization

12. PostgreSQL migration
    - Replace SQLite for production
    - Better concurrent reads/writes
    - Required for multi-user dashboard
```

### Nice to Have (Post-Profitable)
```
13. SMS backup alerts via Twilio
14. Weekly performance PDF report
15. Factor model monthly rescreen (Quality + Momentum)
16. Options hedging layer
17. Multi-broker support
```

---

## 10. SEBI COMPLIANCE STATUS

```
Registration required:  NO (below 10 OPS threshold)
RA license needed:      NO (white box strategy)
Static IP required:     YES — AWS Elastic IP 13.235.14.47 ✓
Session logout daily:   YES — EOD routine handles this ✓
Trading allowed:        Personal account only ✓
Code changes:           Minor OK, major = re-register
Framework effective:    August 2025 (already applicable)
```

---

## 11. BROKER SETUP

### Kotak Neo (Primary)
```
Use:        Order execution + live quotes
Brokerage:  Rs0 per order (API trades)
Rate limit: 10 orders/second
Auth:       TOTP + MPIN (daily)
Whitelist:  13.235.14.47 (AWS Elastic IP)
```

### Zerodha (Data Feed — To Be Added)
```
Use:        Primary data feed (more stable)
Cost:       Rs500/month KiteConnect API
Rate limit: 10 requests/second
Auth:       API key + secret + request token (daily)
Status:     To be integrated next session
```

---

## 12. ENVIRONMENT VARIABLES (.env)

```
KOTAK_CONSUMER_KEY=
KOTAK_MOBILE=+91xxxxxxxxxx
KOTAK_UCC=
KOTAK_MPIN=
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
ZERODHA_API_KEY=        (to be added)
ZERODHA_API_SECRET=     (to be added)
```

---

## 13. NEXT SESSION PLAN (Weekend Build)

### Saturday — Core Fixes
```
AM: Fix entry price (today's open not yesterday's close)
AM: Zerodha KiteConnect integration
PM: Live execution engine (place_order, fill check, capital validation)
PM: PAPER_TRADE flag
```

### Sunday — Testing + Deploy
```
AM: Capital reconciliation
AM: Shared session fix
PM: Full system test on paper
PM: Deploy to AWS
```

### Monday — Go Live (Semi-Live First)
```
09:00: Start engine in semi-live mode (manual approval)
09:15: First real orders placed
15:30: Review results
```

---

## 14. ABOUT CODEBASE (Claude Projects)

**Question: How useful is Claude Projects (Codebase) for this?**

**Highly recommended for this project. Here's why:**

Advantages over chat:
```
1. Persistent context — Claude remembers all your files
   No need to paste code every session
   
2. Direct file editing — Claude reads and edits files directly
   No copy-paste errors
   No version confusion
   
3. Faster iteration — changes applied directly to files
   No manual transfer step
   
4. Better debugging — Claude sees actual file content
   Not what you think the file says
   
5. Cleaner code — no accumulated patches
   Each change is surgical and precise
```

Current problems caused by NOT using codebase:
```
- Multiple versions of runner.py floating around
- Patches applied to wrong versions
- "give clean code" requests 10+ times today
- Bugs introduced by manual copy-paste
- Entry price bug persisted because 
  we couldn't see actual file content
```

**Recommendation:**
Upload your KNVK folder to Claude Projects.
All future sessions will be much faster and cleaner.

How to set up:
```
1. Open Claude.ai → Projects
2. Create new project "KNVK Trading"
3. Upload your KNVK folder contents
4. Start new chat — Claude has full context
5. Say "continue building KNVK" — no re-explanation needed
```

---

## 15. QUICK REFERENCE COMMANDS

### Local Machine
```powershell
# Transfer single file to AWS
scp -i C:\keys\knvk-key.pem C:\KNVK\[file] ubuntu@13.235.14.47:~/KNVK/[file]

# Transfer all files
scp -i C:\keys\knvk-key.pem -r C:\KNVK\* ubuntu@13.235.14.47:~/KNVK/

# SSH into AWS
ssh -i C:\keys\knvk-key.pem ubuntu@13.235.14.47
```

### AWS Daily Commands
```bash
# Morning
tmux attach -t knvk              # attach to running session
python3 paper/runner.py status   # check positions
python3 paper/signals_daily.py   # generate signals if needed
python3 paper/runner.py morning  # manually trigger morning open

# Monitoring  
python3 paper/runner.py prices   # check live prices
python3 paper/runner.py journal  # today's decisions log
python3 check_trade.py           # entry/stop/target for all positions

# End of day
python3 paper/runner.py summary  # daily PnL summary
python3 utils/learning.py        # performance update + Telegram report

# Emergency
python3 reset_today.py           # clear today's trades
python3 verify.py                # full system health check
```

---

## 16. PAPER TRADING RESULTS (To Date)

```
Day 1 (Apr 16, 2026):
  Trades:   12
  Net PnL:  -Rs636 (laptop shutdown — unrealistic exits at entry price)
  Winners:  0
  Note:     Not a real result — system failure day

Day 2 (Apr 17, 2026):
  Status:   In progress
  Positions: 8 open
  Issues:   Entry price gap (BHEL Rs292 vs actual Rs308+)
            Live prices partially working
```

---

*Last updated: April 17, 2026*
*Next session: Weekend build — Zerodha integration + live execution engine*
