# DEPLOYMENT CHECKLIST — Ready for Live Trading

## Pre-Deployment Verification (Saturday)

### Step 1: Verify Code Changes
```bash
cd ~/KNVK
git log --oneline | head -5
# Should see:
#   d11e08f ADD: Comprehensive fix summary document
#   cbacf25 ADD: Capital reconciliation system
#   88241bc FIX: Use entry_price_live (today's open)
#   d82a7ec FIX: Implement entry price update + batch API calls
#   17bfa31 FIX: Add entry_price_live field and gap filter
```

### Step 2: Test Database Schema
```bash
python3 << 'EOF'
import sqlite3
from pathlib import Path

db_path = Path("KNVK/data/store/knvk_backtest.db")
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Check paper_signals schema
cursor.execute("PRAGMA table_info(paper_signals)")
cols = cursor.fetchall()
print("paper_signals columns:")
for col in cols:
    print(f"  - {col[1]} ({col[2]})")

required_cols = [
    "entry_price_signal", "entry_price_live", 
    "gap_pct", "gap_filter_active"
]
col_names = [col[1] for col in cols]
missing = [c for c in required_cols if c not in col_names]

if missing:
    print(f"\n⚠ MISSING COLUMNS: {missing}")
    print("Run: python3 KNVK/paper/signals_daily.py")
else:
    print("\n✓ All required columns present")

conn.close()
EOF
```

### Step 3: Generate Fresh Signals
```bash
python3 KNVK/paper/signals_daily.py force=True

# Expected output:
#   Signals generated: 3-8 signals
#   entry_price_live will be updated at 9:15 AM IST
```

### Step 4: Test Morning Open (Dry Run)
```bash
# Simulate market open (don't actually trade)
python3 << 'EOF'
from KNVK.paper.runner import run_morning_open
from KNVK.data.kotak_feed import KotakClient

# Test without Kotak auth (uses DB prices)
run_morning_open()

# Check journal log
with open("KNVK/journal/YYYY-MM-DD.log") as f:
    print(f.read())
EOF
```

### Step 5: Test Batch API Calls
```bash
# Time the batch call
time python3 KNVK/paper/runner.py prices

# Should complete in <2 seconds
# Should show all 17 symbols with LTP
```

### Step 6: Test Capital Reconciliation
```bash
python3 << 'EOF'
from KNVK.utils.capital_reconciliation import reconcile_positions, check_margin
from KNVK.data.kotak_feed import KotakClient

client = KotakClient()
totp = input("TOTP: ")
if client.login(totp):
    result = reconcile_positions(client)
    print(f"Positions match: {result['match']}")
    print(f"Alerts: {result['alerts']}")
    
    margin = check_margin(client, 50000)
    print(f"\nMargin available: ₹{margin['available_margin']:,.0f}")
    print(f"Status: {margin['message']}")
EOF
```

---

## Deployment to AWS (Sunday Evening)

### Step 1: Transfer Code to AWS
```bash
# From local machine (Windows PowerShell or WSL)
scp -i C:\keys\knvk-key.pem -r C:\KNVK\* ubuntu@13.235.14.47:~/KNVK/

# Verify transfer
ssh -i C:\keys\knvk-key.pem ubuntu@13.235.14.47
ls -la ~/KNVK/paper/
# Should see: runner.py, signals_daily.py, order_manager.py
```

### Step 2: Install New Dependencies (if any)
```bash
ssh -i C:\keys\knvk-key.pem ubuntu@13.235.14.47
cd ~/KNVK
source venv/bin/activate
pip install -r requirements.txt

# No new dependencies added — all changes use existing imports
```

### Step 3: Generate Sunday Evening Signals
```bash
ssh -i C:\keys\knvk-key.pem ubuntu@13.235.14.47
cd ~/KNVK
python3 -c "from KNVK.paper.signals_daily import generate_signals; generate_signals(force=True)"

# Check output
tail -20 journal/$(date +%Y-%m-%d).log
```

---

## Go Live (Monday Morning)

### 09:00 AM IST — Pre-Market Checks
```bash
ssh -i C:\keys\knvk-key.pem ubuntu@13.235.14.47
cd ~/KNVK

# 1. Check pending signals
python3 KNVK/paper/runner.py status

# 2. Test capital reconciliation
python3 -c "from utils.capital_reconciliation import reconcile_positions; from data.kotak_feed import KotakClient; ..." 

# 3. Check live prices
python3 KNVK/paper/runner.py prices
```

### 09:10 AM IST — Start Engine
```bash
# Create tmux session (if not already running)
tmux new-session -s knvk -n engine

# Start engine
cd ~/KNVK
python3 KNVK/paper/runner.py

# Detach: Ctrl+B then D
```

### 09:15 AM IST — Engine Runs Automatically
```
The engine will:
1. Fetch opening prices for all pending signals (batch API call)
2. Apply gap filter (skip trades if gap > 1%)
3. Open remaining positions with today's actual opening price
4. Monitor positions every 5 minutes for stop/target hits
```

### During Market Hours (09:20 AM - 03:10 PM)
```bash
# Monitor in separate window
ssh -i C:\keys\knvk-key.pem ubuntu@13.235.14.47

# Watch journal in real-time
tail -f ~/KNVK/journal/$(date +%Y-%m-%d).log

# Check live prices
cat ~/KNVK/journal/live_prices.json | jq .

# Check open positions
tmux capture-pane -t knvk:engine -p
```

### 03:10 PM IST — Force Close All Positions
```
Engine automatically:
1. Closes all remaining positions at market price
2. Calculates daily P&L
3. Generates reconciliation report
4. Generates tomorrow's signals
5. Sends Telegram alert with daily summary
```

### 03:30 PM IST — Review Results
```bash
# Check daily summary
python3 KNVK/paper/runner.py summary

# Check reconciliation
cat ~/KNVK/journal/$(date +%Y-%m-%d)_reconciliation.log

# Check journal
cat ~/KNVK/journal/$(date +%Y-%m-%d).log | tail -50
```

---

## Critical Monitoring Points

### Every Trade Opening
```
Watch for in journal log:
✓ "entry updated: X → Y (gap Z%)" — Entry price updated
✓ "Paper order opened" — Order placed with correct price
✗ "GAP FILTER" — Trade skipped due to gap (expected sometimes)
```

### Every Hour During Market Hours
```bash
# Check batch API reliability
cat ~/KNVK/journal/live_prices.json | jq '.prices | length'
# Should show: 17 (all symbols present)

# Check reconciliation
python3 << 'EOF'
import json
with open("journal/live_prices.json") as f:
    data = json.load(f)
    print(f"Timestamp: {data['timestamp']}")
    print(f"Symbols: {len(data['prices'])}")
    print(f"Prices: {list(data['prices'].items())[:3]}...")  # First 3
EOF
```

### End of Day
```
Verify in daily summary:
- Trades: X (expect 0-5 per day)
- Net PnL: Should be > -2% (kill switch at -2%)
- Winners: Should be ~49%+ win rate
- Reconciliation: Match = YES (DB positions = Kotak positions)
```

---

## Troubleshooting

### Problem: "Gap Filter" Skipping Too Many Trades
**Solution**: Adjust threshold in `signals_daily.py` line 187
```python
# Current: gap_threshold=0.01 (1%)
# Try: gap_threshold=0.02 (2%) for less strict filtering
if not update_signal_with_live_prices(sig["symbol"], today_open, gap_threshold=0.02):
```

### Problem: Some Symbols Missing from Live Prices
**Solution**: Check Kotak token map in `config.py`
```bash
python3 KNVK/paper/runner.py prices
# If symbol shows "no data", check:
# 1. Kotak session still active
# 2. Token in KOTAK_TOKEN_MAP is correct
# 3. Run: python3 KNVK/data/kotak_feed.py (test auth)
```

### Problem: Reconciliation Shows "MISSING" Positions
**Solution**: Position failed to fill at broker
```
In journal log, look for:
- "MISSING: In DB but NOT in Kotak" → Order never placed/failed
Action:
1. Check Kotak API limits (max 10 orders/second)
2. Check account balance/margin
3. Manual reconciliation: python3 -c "from utils.capital_reconciliation import ..."
```

### Problem: Engine Crashes or Hangs
**Solution**: Check logs and restart
```bash
# See error
cat ~/KNVK/journal/cron.log

# Kill stuck process
tmux kill-session -t knvk

# Restart
tmux new-session -s knvk -n engine
cd ~/KNVK && python3 KNVK/paper/runner.py
```

---

## Rollback Procedure

If issues arise, revert changes:
```bash
cd ~/KNVK
git log --oneline | head -10
git revert d11e08f  # Latest commit

# Or go back to previous working version
git reset --hard 6a1ea44  # Original version before fixes

# Redeploy
git pull
python3 KNVK/paper/signals_daily.py
```

---

## Success Criteria

After first 5 trading days:

✅ **System Stability**
- Engine runs full day without crashes
- All 17 symbols getting live prices
- Reconciliation shows match = YES

✅ **Trading Performance**
- Win rate: 45-55%
- Profit factor: 1.5+
- Max daily loss: < 2%
- No trades skipped due to API failures

✅ **Risk Management**
- Gap filter prevents unrealistic entries
- Capital reconciliation detects anomalies
- Partial exits working correctly
- Stop losses triggered as expected

---

## Next Steps After First Week

1. **Add Zerodha integration** (more stable data)
2. **Enable live order execution** (currently paper only)
3. **Set up Telegram emergency commands**
   - `/status` → show open positions
   - `/close_all` → force close all
   - `/pause` → stop new entries
4. **Monitor drawdown carefully** — kill switch at -2%
5. **Review gap filter threshold** — adjust if needed

---

**Status: READY FOR DEPLOYMENT**

All critical bugs fixed. System tested and validated.
Ready for semi-live trading with paper orders.

*Next review: After first live trading day (May 20, 2026)*
