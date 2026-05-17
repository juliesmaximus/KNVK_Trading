# paper/runner.py — daily scheduler with live Kotak Neo feed
# FIXED: entry_price_live updated at 9:15 AM + batch API calls + gap filter

import sys
sys.path.append(str(__import__('pathlib').Path(__file__).parent.parent))

import time
import json
from pathlib import Path
from datetime import datetime, date, timezone, timedelta

from data.kotak_feed import KotakClient
from data.downloader import load_symbol
from paper.signals_daily import (
    generate_signals, get_pending_signals, update_signal_with_live_prices
)
from paper.order_manager import (
    open_trade, update_trade, get_open_trades, get_daily_summary
)
from utils.alerts import (
    alert_engine_start, alert_trade_opened, alert_daily_summary,
    alert_session_expired
)
from config import DB_PATH, STABLE_SYMBOLS, KOTAK_TOKEN_MAP

# ── IST timezone ──────────────────────────────────────────────────────────────
IST = timezone(timedelta(hours=5, minutes=30))

def now_ist() -> datetime:
    return datetime.now(IST)

def today_ist() -> str:
    return now_ist().strftime("%Y-%m-%d")

def time_ist() -> int:
    n = now_ist()
    return n.hour * 100 + n.minute


# ── module-level client ───────────────────────────────────────────────────────
kotak_client = None


def init_kotak(totp: str) -> bool:
    global kotak_client
    kotak_client = KotakClient()
    return kotak_client.login(totp)


# ── trade journal ──────────────────────────────────────────────────────────────

def log_decision(symbol: str, action: str,
                 price: float, reason: str):
    journal_dir = Path(__file__).parent.parent / "journal"
    journal_dir.mkdir(exist_ok=True)

    log_file = journal_dir / f"{today_ist()}.log"

    entry = (
        f"[{now_ist().strftime('%H:%M:%S')} IST] "
        f"{action:<12} {symbol:<12} "
        f"@ Rs{price:<10.2f} | {reason}\n"
    )

    with open(log_file, "a") as f:
        f.write(entry)

    print(f"  >> {entry.strip()}")


# ── re-authentication ──────────────────────────────────────────────────────────

def _reauth():
    global kotak_client
    print("\n" + "="*55)
    print("SESSION EXPIRED — Re-authentication required")
    print("="*55)
    alert_session_expired()
    try:
        totp = input("Enter fresh TOTP: ")
        if kotak_client:
            success = kotak_client.login(totp)
            if success:
                print("Re-authenticated successfully.")
                log_decision("SYSTEM", "REAUTH", 0, "Session renewed")
            else:
                print("Re-auth failed — running on historical data.")
    except Exception as e:
        print(f"Re-auth error: {e}")


# ── price feed (BATCH optimized) ───────────────────────────────────────────────

def get_ltp_batch(symbols: list) -> dict:
    """
    FIX for Bug #2: Get LTP for multiple symbols in ONE batch API call.
    Much faster than sequential calls. No rate limiting.
    
    Returns: {symbol: ltp, ...}
    """
    global kotak_client
    if not kotak_client or not kotak_client.is_authenticated():
        return {}

    try:
        # build batch request
        tokens = [
            {
                "instrument_token": KOTAK_TOKEN_MAP[sym],
                "exchange_segment": "nse_cm"
            }
            for sym in symbols
            if sym in KOTAK_TOKEN_MAP
        ]

        if not tokens:
            return {}

        results = kotak_client.get_quote(tokens)

        if not results:
            return {}

        # map exchange_token back to symbol
        token_to_sym = {
            str(v): k for k, v in KOTAK_TOKEN_MAP.items()
        }

        prices = {}
        for r in results:
            exchange_token = str(r.get("exchange_token", ""))
            ltp = float(r.get("ltp", 0))
            sym = token_to_sym.get(exchange_token)
            if sym and ltp > 0:
                prices[sym] = ltp

        return prices

    except Exception as e:
        print(f"  Batch LTP error: {e}")
        return {}


def get_ltp(symbol: str) -> float:
    """Get single LTP via quote call (fallback)."""
    global kotak_client
    token = KOTAK_TOKEN_MAP.get(symbol)
    if token and kotak_client and kotak_client.is_authenticated():
        try:
            result = kotak_client.get_quote([{
                "instrument_token": token,
                "exchange_segment": "nse_cm"
            }])
            if result and len(result) > 0:
                return float(result[0].get("ltp", 0))
        except:
            pass
    return 0.0


def get_latest_price(symbol: str) -> dict:
    """
    Get OHLC for stop/target checking.
    Uses ohlc_today for high/low accuracy.
    Falls back to DB if API unavailable.
    """
    global kotak_client

    if kotak_client and kotak_client.is_authenticated():
        token = KOTAK_TOKEN_MAP.get(symbol)
        if token:
            try:
                ohlc = kotak_client.get_ohlc_today(token)
                if ohlc and ohlc.get("close", 0) > 0:
                    return ohlc
            except Exception:
                pass

    try:
        df = load_symbol(symbol)
        if df.empty:
            return None
        last = df.iloc[-1]
        return {
            "high":  float(last["high"]),
            "low":   float(last["low"]),
            "close": float(last["close"]),
        }
    except:
        return None


def save_live_prices():
    """
    Fetch all symbol prices in ONE batch API call (Bug #2 fix).
    Much faster, no rate limiting issues.
    """
    global kotak_client
    if not kotak_client or not kotak_client.is_authenticated():
        return

    try:
        prices = get_ltp_batch(STABLE_SYMBOLS)

        price_file = Path(__file__).parent.parent / "journal" / "live_prices.json"
        price_file.parent.mkdir(exist_ok=True)
        with open(price_file, "w") as f:
            json.dump({
                "timestamp": now_ist().strftime("%Y-%m-%d %H:%M:%S"),
                "prices":    prices
            }, f)
        print(f"  Live prices saved: {len(prices)}/{len(STABLE_SYMBOLS)} symbols")

    except Exception as e:
        print(f"  Price save error: {e}")


# ── market helpers ─────────────────────────────────────────────────────────────

def is_market_open() -> bool:
    n = now_ist()
    if n.weekday() >= 5:
        return False
    market_open  = n.replace(hour=9,  minute=15, second=0, microsecond=0)
    market_close = n.replace(hour=15, minute=30, second=0, microsecond=0)
    return market_open <= n <= market_close


# ── daily phases ───────────────────────────────────────────────────────────────

def run_morning_open():
    """
    FIX for Bug #1: Fetch today's opening prices and update signal entries.
    Before placing any orders, verify gap is within threshold.
    """
    print(f"\n{'='*55}")
    print(f"MORNING OPEN — {now_ist().strftime('%Y-%m-%d %H:%M')} IST")
    print(f"{'='*55}")

    # STEP 1: Check for carried positions
    existing = get_open_trades()
    if not existing.empty:
        print(f"Carrying {len(existing)} positions from previous session:")
        for _, t in existing.iterrows():
            direction = "LONG" if t["direction"] == 1 else "SHORT"
            print(f"  {t['symbol']:<15} {direction} "
                  f"entry=Rs{t['entry_price']:.2f} "
                  f"stop=Rs{t['stop_current']:.2f}")
            log_decision(t["symbol"], "CARRY",
                        t["entry_price"],
                        "carried from previous session")

    existing_symbols = set(existing["symbol"].tolist()) \
                       if not existing.empty else set()

    # STEP 2: Fetch today's pending signals
    today   = today_ist()
    pending = get_pending_signals(today)

    if pending.empty:
        print("No new signals for today.")
        print(f"Total active positions: {len(existing)}")
        return

    # STEP 3: Fetch today's opening prices via batch API (Bug #2 fix)
    print(f"\nFetching opening prices for {len(pending)} signals...")
    opening_prices = get_ltp_batch(pending["symbol"].tolist())

    if not opening_prices:
        print("  WARNING: Could not fetch opening prices. Using signal prices (risky).")
    else:
        print(f"  Got {len(opening_prices)} opening prices")

    # STEP 4: Update signals with live prices + apply gap filter (Bug #1 fix)
    print(f"\nUpdating signal entry prices (gap filter = 1%):")
    gap_skipped = 0
    for _, sig in pending.iterrows():
        if sig["symbol"] in existing_symbols:
            print(f"  {sig['symbol']:<15} already open — skipped")
            continue

        if sig["symbol"] in opening_prices:
            today_open = opening_prices[sig["symbol"]]
            # Update signal with live price and check gap
            if not update_signal_with_live_prices(sig["symbol"], today_open, gap_threshold=0.01):
                gap_skipped += 1
        else:
            print(f"  {sig['symbol']:<15} no opening data — using signal price")
            update_signal_with_live_prices(sig["symbol"], sig["entry_price_signal"], gap_threshold=0.01)

    # STEP 5: Reload signals (excluding gap-filtered ones)
    new_pending = get_pending_signals(today)
    new_signals = new_pending[
        ~new_pending["symbol"].isin(existing_symbols)
    ]

    if new_signals.empty:
        print(f"\nNo tradeable signals after gap filter (skipped {gap_skipped})")
        print(f"Total active positions: {len(existing)}")
        return

    print(f"\nOpening {len(new_signals)} positions:")
    for _, sig in new_signals.iterrows():
        # Use live entry price, not signal price
        entry_price = sig["entry_price_live"] if sig["entry_price_live"] > 0 else sig["entry_price_signal"]
        
        open_trade(sig["id"], sig.to_dict())
        direction = "LONG" if sig["direction"] == 1 else "SHORT"
        log_decision(
            sig["symbol"], f"OPEN {direction}",
            entry_price,
            f"ev=Rs{sig['ev_net']:.0f} "
            f"regime={sig['regime']}"
        )
        alert_trade_opened(
            symbol    = sig["symbol"],
            direction = direction,
            entry     = entry_price,
            stop      = sig["stop_price"],
            target1   = sig["target1"],
            qty       = sig["qty"]
        )

    total = get_open_trades()
    print(f"\nTotal active positions: {len(total)}")


def run_position_monitor():
    open_trades = get_open_trades()
    if open_trades.empty:
        return

    print(f"\n[{now_ist().strftime('%H:%M')} IST] "
          f"Monitoring {len(open_trades)} positions...")

    # check session validity
    if kotak_client and kotak_client.is_authenticated():
        test_token = list(KOTAK_TOKEN_MAP.values())[0]
        test = kotak_client.get_ohlc_today(test_token)
        if not test:
            print("  Session expired — re-authenticating...")
            _reauth()

    # update positions using OHLC for stop/target accuracy
    for _, trade in open_trades.iterrows():
        price = get_latest_price(trade["symbol"])
        if not price:
            continue
        result = update_trade(
            trade_id      = trade["id"],
            current_high  = price["high"],
            current_low   = price["low"],
            current_close = price["close"]
        )
        if result is not None:
            log_decision(
                trade["symbol"], "CLOSED",
                price["close"],
                f"pnl=Rs{result:.0f}"
            )

    # save live prices for dashboard using fast batch LTP calls (Bug #2 fix)
    save_live_prices()


def run_end_of_day():
    print(f"\n{'='*55}")
    print(f"END OF DAY — {now_ist().strftime('%Y-%m-%d %H:%M')} IST")
    print(f"{'='*55}")

    open_trades = get_open_trades()
    if not open_trades.empty:
        print(f"Force closing {len(open_trades)} positions...")
        for _, trade in open_trades.iterrows():
            price = get_latest_price(trade["symbol"])
            if price:
                result = update_trade(
                    trade_id      = trade["id"],
                    current_high  = price["high"],
                    current_low   = price["low"],
                    current_close = price["close"]
                )
                if result is not None:
                    log_decision(
                        trade["symbol"], "EOD CLOSE",
                        price["close"],
                        f"pnl=Rs{result:.0f}"
                    )

    summary = get_daily_summary()
    print(f"\nDAILY SUMMARY")
    print(f"{'─'*30}")
    print(f"Trades:   {summary['trades']}")
    print(f"Net PnL:  Rs{summary['net_pnl']:,.2f}")
    print(f"Winners:  {summary.get('winners', 0)}")
    print(f"Losers:   {summary.get('losers', 0)}")

    log_decision("SYSTEM", "EOD SUMMARY", 0,
                f"trades={summary['trades']} "
                f"pnl=Rs{summary['net_pnl']:.0f} "
                f"winners={summary.get('winners',0)}")

    alert_daily_summary(
        trades   = summary["trades"],
        net_pnl  = summary["net_pnl"],
        winners  = summary.get("winners", 0),
        losers   = summary.get("losers", 0)
    )

    print(f"\nGenerating tomorrow's signals...")
    signals = generate_signals()
    print(f"Signals ready for tomorrow: {len(signals)}")


# ── main loop ──────────────────────────────────────────────────────────────────

def run_paper_trading_loop():
    print(f"\n{'='*55}")
    print(f"KNVK PAPER TRADING ENGINE")
    print(f"Universe: {len(STABLE_SYMBOLS)} stable symbols")
    print(f"Mode: PAPER ONLY — live prices via Kotak Neo")
    print(f"Server time (IST): {now_ist().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*55}")
    print(f"\nFIXES APPLIED:")
    print(f"  ✓ Bug #1: Entry price updated at 9:15 AM with today's open")
    print(f"  ✓ Bug #2: Batch API calls (all 17 symbols in 1 request)")
    print(f"  ✓ Gap filter: Skip trades if gap > 1% from signal price")
    print(f"{'='*55}")

    totp = input("\nEnter TOTP for Kotak Neo: ")
    if not init_kotak(totp):
        print("Authentication failed. Running on historical data.")
    else:
        print("Live data feed active.\n")
        alert_engine_start(len(STABLE_SYMBOLS))
        log_decision("SYSTEM", "ENGINE START", 0,
                    f"symbols={len(STABLE_SYMBOLS)}")

    morning_done = False
    eod_done     = False
    last_date    = today_ist()

    while True:
        current_time = time_ist()
        current_date = today_ist()

        if current_date != last_date:
            morning_done = False
            eod_done     = False
            last_date    = current_date
            print(f"\nNew trading day: {current_date}")

        if now_ist().weekday() >= 5:
            print(f"Weekend — market closed. "
                  f"[{now_ist().strftime('%H:%M')} IST]")
            time.sleep(3600)
            continue

        if 915 <= current_time < 1100 and not morning_done:
            run_morning_open()
            morning_done = True

        elif 920 <= current_time < 1510 and is_market_open():
            run_position_monitor()
            time.sleep(300)
            continue

        elif current_time >= 1530 and not eod_done:
            run_end_of_day()
            eod_done = True

        time.sleep(60)


# ── manual commands ────────────────────────────────────────────────────────────

if __name__ == "__main__":

    if len(sys.argv) > 1:
        cmd = sys.argv[1]

        if cmd == "signals":
            generate_signals()

        elif cmd == "summary":
            s = get_daily_summary()
            print(f"Date:    {s['date']}")
            print(f"Trades:  {s['trades']}")
            print(f"Net PnL: Rs{s['net_pnl']:,.2f}")

        elif cmd == "status":
            trades = get_open_trades()
            print(f"Open positions: {len(trades)}")
            if not trades.empty:
                print(trades[[
                    "symbol", "entry_price", "stop_current",
                    "qty_remaining", "net_pnl"
                ]].to_string())

        elif cmd == "prices":
            totp = input("TOTP: ")
            init_kotak(totp)
            print(f"\n{'Symbol':<15} {'LTP':>10}")
            print("-" * 25)
            # Use batch call instead of sequential
            prices = get_ltp_batch(STABLE_SYMBOLS)
            for sym in STABLE_SYMBOLS:
                if sym in prices:
                    print(f"{sym:<15} Rs{prices[sym]:>9.2f}")
                else:
                    print(f"{sym:<15} no data")

        elif cmd == "journal":
            log_file = Path("journal") / f"{today_ist()}.log"
            if log_file.exists():
                print(log_file.read_text())
            else:
                print("No journal entries today.")

        elif cmd == "alert_test":
            from utils.alerts import send_alert
            result = send_alert(
                "<b>KNVK Alert Test</b>\n"
                f"Time: {now_ist().strftime('%H:%M:%S')} IST\n"
                "System operational."
            )
            print(f"Alert sent: {result}")

        elif cmd == "morning":
            run_morning_open()

        else:
            print("Commands: signals | summary | status | "
                  "prices | journal | alert_test | morning")

    else:
        run_paper_trading_loop()
