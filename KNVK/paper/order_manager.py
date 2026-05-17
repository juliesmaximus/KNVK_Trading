# paper/order_manager.py — paper order lifecycle management
# FIXED: Uses entry_price_live from signals (today's open price)

import sys
sys.path.append(str(__import__('pathlib').Path(__file__).parent.parent))

import sqlite3
import pandas as pd
from datetime import datetime, date
from backtest.costs import calculate_charges
from data.downloader import load_symbol
from config import DB_PATH


def get_open_trades() -> pd.DataFrame:
    """Load all currently open paper trades."""
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql("""
        SELECT * FROM paper_trades
        WHERE status = 'OPEN'
        ORDER BY created_at
    """, conn)
    conn.close()
    return df


def open_trade(signal_id: int, signal: dict) -> int:
    """
    FIX for Bug #1: Convert a pending signal into an open paper trade.
    Uses entry_price_live (today's opening price) instead of yesterday's close.
    Called at 9:15 AM when market opens.
    Returns trade id.
    """
    conn = sqlite3.connect(DB_PATH)

    # Use entry_price_live if available, fallback to entry_price_signal
    entry_price = signal.get("entry_price_live", 0)
    if entry_price <= 0:
        entry_price = signal.get("entry_price_signal", signal.get("entry_price", 0))

    cursor = conn.execute("""
        INSERT INTO paper_trades
        (signal_id, symbol, entry_date, entry_price,
         direction, qty, stop_price, target1, target2,
         qty_remaining, stop_current, status, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,'OPEN',?)
    """, (
        signal_id,
        signal["symbol"],
        date.today().strftime("%Y-%m-%d"),
        entry_price,
        signal["direction"],
        signal["qty"],
        signal["stop_price"],
        signal["target1"],
        signal["target2"],
        signal["qty"],
        signal["stop_price"],
        datetime.now().isoformat()
    ))

    # mark signal as active
    conn.execute("""
        UPDATE paper_signals SET status='ACTIVE'
        WHERE id=?
    """, (signal_id,))

    conn.commit()
    trade_id = cursor.lastrowid
    conn.close()

    # Distinguish between signal price and actual entry price
    price_source = "today's open" if signal.get("entry_price_live", 0) > 0 else "signal price"
    print(f"  ✓ Paper order opened: {signal['symbol']} "
          f"{'LONG' if signal['direction']==1 else 'SHORT'} "
          f"× {signal['qty']} @ ₹{entry_price:.2f} ({price_source})")

    return trade_id


def update_trade(
    trade_id:    int,
    current_high: float,
    current_low:  float,
    current_close: float,
    trade_date:   str = None
):
    """
    Check and update a single open trade against current price.
    Handles partial exits and stop hits.
    Called during market hours and at end of day.
    """
    if trade_date is None:
        trade_date = date.today().strftime("%Y-%m-%d")

    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        "SELECT * FROM paper_trades WHERE id=?", (trade_id,)
    ).fetchone()
    conn.close()

    if not row:
        return

    cols = [
        "id", "signal_id", "symbol", "entry_date", "entry_price",
        "direction", "qty", "stop_price", "target1", "target2",
        "qty_remaining", "partial1_done", "partial2_done",
        "stop_current", "status", "gross_pnl", "total_charges",
        "net_pnl", "exit_date", "exit_reason", "created_at"
    ]
    trade = dict(zip(cols, row))

    d             = trade["direction"]
    qty_remaining = trade["qty_remaining"]
    partial1_done = trade["partial1_done"]
    partial2_done = trade["partial2_done"]
    stop_current  = trade["stop_current"]
    gross_pnl     = trade["gross_pnl"]
    total_charges = trade["total_charges"]
    entry_price   = trade["entry_price"]

    exit_reason = None
    closed      = False

    # ── Partial 1 — 50% at target1 ────────────────────────────
    if not partial1_done:
        hit1 = (d == 1 and current_high >= trade["target1"]) or \
               (d == -1 and current_low <= trade["target1"])
        if hit1:
            qty1      = trade["qty"] // 2
            exit_val  = qty1 * trade["target1"]
            entry_val = qty1 * entry_price
            pnl1      = (trade["target1"] - entry_price) * qty1 * d

            charges1  = calculate_charges(entry_val, "buy")["total"] + \
                        calculate_charges(exit_val, "sell")["total"]

            gross_pnl     += pnl1
            total_charges += charges1
            qty_remaining -= qty1
            partial1_done  = 1
            stop_current   = entry_price   # move to breakeven

            print(f"  ★ {trade['symbol']} partial1 hit @ "
                  f"₹{trade['target1']} | pnl=₹{pnl1-charges1:.0f}")

    # ── Partial 2 — 25% at target2 ────────────────────────────
    if partial1_done and not partial2_done:
        hit2 = (d == 1 and current_high >= trade["target2"]) or \
               (d == -1 and current_low <= trade["target2"])
        if hit2:
            qty2      = trade["qty"] // 4
            exit_val  = qty2 * trade["target2"]
            entry_val = qty2 * entry_price
            pnl2      = (trade["target2"] - entry_price) * qty2 * d

            charges2  = calculate_charges(entry_val, "buy")["total"] + \
                        calculate_charges(exit_val, "sell")["total"]

            gross_pnl     += pnl2
            total_charges += charges2
            qty_remaining -= qty2
            partial2_done  = 1
            stop_current   = trade["target1"]  # trail to 1R

            print(f"  ★★ {trade['symbol']} partial2 hit @ "
                  f"₹{trade['target2']} | pnl=₹{pnl2-charges2:.0f}")

    # ── Stop check ─────────────────────────────────────────────
    stop_hit = (d == 1 and current_low <= stop_current) or \
               (d == -1 and current_high >= stop_current)

    if stop_hit and qty_remaining > 0:
        exit_val  = qty_remaining * stop_current
        entry_val = qty_remaining * entry_price
        pnl_stop  = (stop_current - entry_price) * qty_remaining * d

        charges_s = calculate_charges(entry_val, "buy")["total"] + \
                    calculate_charges(exit_val, "sell")["total"]

        gross_pnl     += pnl_stop
        total_charges += charges_s
        qty_remaining  = 0
        exit_reason    = "stop"
        closed         = True

        print(f"  ✗ {trade['symbol']} stopped @ "
              f"₹{stop_current:.2f} | pnl=₹{pnl_stop-charges_s:.0f}")

    # ── Time exit at 3:10 PM ───────────────────────────────────
    now = datetime.now()
    if not closed and now.hour == 15 and now.minute >= 10:
        if qty_remaining > 0:
            exit_val  = qty_remaining * current_close
            entry_val = qty_remaining * entry_price
            pnl_time  = (current_close - entry_price) * qty_remaining * d

            charges_t = calculate_charges(entry_val, "buy")["total"] + \
                        calculate_charges(exit_val, "sell")["total"]

            gross_pnl     += pnl_time
            total_charges += charges_t
            qty_remaining  = 0
            exit_reason    = "time"
            closed         = True

            print(f"  ⏱ {trade['symbol']} time exit @ "
                  f"₹{current_close:.2f} | pnl=₹{pnl_time-charges_t:.0f}")

    # ── Update DB ──────────────────────────────────────────────
    net_pnl = gross_pnl - total_charges
    status  = "CLOSED" if closed else "OPEN"

    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        UPDATE paper_trades SET
            qty_remaining  = ?,
            partial1_done  = ?,
            partial2_done  = ?,
            stop_current   = ?,
            gross_pnl      = ?,
            total_charges  = ?,
            net_pnl        = ?,
            status         = ?,
            exit_date      = ?,
            exit_reason    = ?
        WHERE id = ?
    """, (
        qty_remaining, partial1_done, partial2_done,
        stop_current, gross_pnl, total_charges, net_pnl,
        status,
        trade_date if closed else None,
        exit_reason,
        trade_id
    ))

    if closed:
        conn.execute("""
            UPDATE paper_signals SET status='DONE'
            WHERE id = ?
        """, (trade["signal_id"],))

    conn.commit()
    conn.close()

    return net_pnl if closed else None


def get_daily_summary(trade_date: str = None) -> dict:
    """Get paper trading summary for a given date."""
    if trade_date is None:
        trade_date = date.today().strftime("%Y-%m-%d")

    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql("""
        SELECT * FROM paper_trades
        WHERE exit_date = ? AND status = 'CLOSED'
    """, conn, params=(trade_date,))
    conn.close()

    if df.empty:
        return {"date": trade_date, "trades": 0, "net_pnl": 0}

    return {
        "date":          trade_date,
        "trades":        len(df),
        "net_pnl":       round(df["net_pnl"].sum(), 2),
        "gross_pnl":     round(df["gross_pnl"].sum(), 2),
        "total_charges": round(df["total_charges"].sum(), 2),
        "winners":       len(df[df["net_pnl"] > 0]),
        "losers":        len(df[df["net_pnl"] <= 0]),
    }


if __name__ == "__main__":
    # test — show open trades and today's summary
    open_trades = get_open_trades()
    print(f"Open paper trades: {len(open_trades)}")
    if not open_trades.empty:
        print(open_trades[["symbol", "entry_price",
                           "stop_current", "net_pnl"]].to_string())

    summary = get_daily_summary()
    print(f"\nToday's summary: {summary}")
