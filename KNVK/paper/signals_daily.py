# paper/signals_daily.py — end of day signal generator
# runs at 3:30 PM IST every trading day

import sys
sys.path.append(str(__import__('pathlib').Path(__file__).parent.parent))

import sqlite3
import pandas as pd
from datetime import datetime, date
from backtest.signals import prepare_features
from backtest.costs import ev_check
from data.downloader import load_symbol, load_vix
from config import (
    STABLE_SYMBOLS, ATR_MULTIPLIER, RISK_PER_TRADE_PCT,
    MIN_ATR_PCT, MIN_RR_RATIO, DB_PATH
)


# ─── DB setup ─────────────────────────────────────────────────────────────────

def init_paper_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS paper_signals (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            signal_date   TEXT,
            symbol        TEXT,
            direction     INTEGER,
            entry_price   REAL,
            stop_price    REAL,
            target1       REAL,
            target2       REAL,
            atr           REAL,
            regime        TEXT,
            qty           INTEGER,
            trade_value   REAL,
            ev_net        REAL,
            status        TEXT DEFAULT 'PENDING',
            created_at    TEXT,
            UNIQUE(signal_date, symbol)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS paper_trades (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            signal_id       INTEGER,
            symbol          TEXT,
            entry_date      TEXT,
            entry_price     REAL,
            direction       INTEGER,
            qty             INTEGER,
            stop_price      REAL,
            target1         REAL,
            target2         REAL,
            qty_remaining   INTEGER,
            partial1_done   INTEGER DEFAULT 0,
            partial2_done   INTEGER DEFAULT 0,
            stop_current    REAL,
            status          TEXT DEFAULT 'OPEN',
            gross_pnl       REAL DEFAULT 0,
            total_charges   REAL DEFAULT 0,
            net_pnl         REAL DEFAULT 0,
            exit_date       TEXT,
            exit_reason     TEXT,
            created_at      TEXT
        )
    """)
    conn.commit()
    conn.close()


# ─── Clear today's signals ────────────────────────────────────────────────────

def clear_todays_signals(signal_date: str):
    """Remove pending signals for today — allows regeneration."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        DELETE FROM paper_signals
        WHERE signal_date = ? AND status = 'PENDING'
    """, (signal_date,))
    conn.commit()
    conn.close()


# ─── Signal generation ────────────────────────────────────────────────────────

def generate_signals(
    capital:      float = 500_000,
    signal_date:  str   = None,
    force:        bool  = False
) -> list:
    """
    Run end-of-day signal generation across stable universe.
    Called at 3:30 PM IST after market close.
    force=True clears existing signals and regenerates.
    Returns list of actionable signals for next day.
    """
    if signal_date is None:
        signal_date = date.today().strftime("%Y-%m-%d")

    init_paper_db()

    # clear and regenerate if forced
    if force:
        clear_todays_signals(signal_date)
        print(f"Cleared existing signals for {signal_date}")

    vix     = load_vix()
    signals = []

    print(f"\nGenerating signals for {signal_date}")
    print(f"Universe: {len(STABLE_SYMBOLS)} symbols")
    print(f"{'─'*50}")

    for sym in STABLE_SYMBOLS:
        try:
            df = load_symbol(sym)
            if df.empty:
                continue

            out = prepare_features(df, vix, include_breakout=False)
            if out.empty:
                continue

            # regime check
            latest_regime = out["regime"].iloc[-1]
            if latest_regime == "CHAOS":
                print(f"  {sym:<20} SKIP — CHAOS regime")
                continue

            if len(out) < 2:
                continue

            last_row = out.iloc[-1]

            if last_row["signal"] == 0:
                continue

            # calculate parameters
            direction  = 1 if last_row["signal"] > 0 else -1
            atr        = last_row["atr"]
            regime     = last_row["regime"]
            multiplier = ATR_MULTIPLIER.get(regime, 2.0)
            entry      = last_row["close"]

            # ATR filter
            if (atr / entry) < MIN_ATR_PCT:
                continue

            # stops and targets
            if direction == 1:
                stop    = entry - (multiplier * atr)
                target1 = entry + (2 * multiplier * atr)
                target2 = entry + (4 * multiplier * atr)
            else:
                stop    = entry + (multiplier * atr)
                target1 = entry - (2 * multiplier * atr)
                target2 = entry - (4 * multiplier * atr)

            # RR check
            reward = abs(target1 - entry)
            risk   = abs(entry - stop)
            if risk == 0 or (reward / risk) < MIN_RR_RATIO:
                continue

            # position sizing
            from utils.learning import get_risk_multiplier
            risk_mult = get_risk_multiplier(sym)
            if risk_mult == 0.0:
                    print(f"  {sym:<20} SKIP — suspended by learning engine")
                    continue
            risk_amt  = capital * RISK_PER_TRADE_PCT * risk_mult
            qty       = max(int(risk_amt / risk), 1)
            trade_val = qty * entry

            # EV check
            ev = ev_check(trade_val, reward, risk, entry)
            if not ev["take_trade"]:
                continue

            signal = {
                "signal_date":  signal_date,
                "symbol":       sym,
                "direction":    direction,
                "entry_price":  round(entry, 2),
                "stop_price":   round(stop, 2),
                "target1":      round(target1, 2),
                "target2":      round(target2, 2),
                "atr":          round(atr, 2),
                "regime":       regime,
                "qty":          qty,
                "trade_value":  round(trade_val, 2),
                "ev_net":       round(ev["ev_net"], 2),
            }
            signals.append(signal)

            direction_str = "LONG" if direction == 1 else "SHORT"
            print(f"  {sym:<20} {direction_str:<6} "
                  f"entry=₹{entry:<8.2f} "
                  f"stop=₹{stop:<8.2f} "
                  f"qty={qty:<5} "
                  f"ev=₹{ev['ev_net']:.0f}")

        except Exception as e:
            print(f"  {sym:<20} ERROR: {e}")

    # save to DB
    if signals:
        conn = sqlite3.connect(DB_PATH)
        for s in signals:
            conn.execute("""
                INSERT OR IGNORE INTO paper_signals
                (signal_date, symbol, direction, entry_price,
                 stop_price, target1, target2, atr, regime,
                 qty, trade_value, ev_net, status, created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'PENDING',?)
            """, (
                s["signal_date"], s["symbol"], s["direction"],
                s["entry_price"], s["stop_price"], s["target1"],
                s["target2"], s["atr"], s["regime"], s["qty"],
                s["trade_value"], s["ev_net"],
                datetime.now().isoformat()
            ))
        conn.commit()
        conn.close()

    print(f"\n{'─'*50}")
    print(f"Signals generated: {len(signals)}")
    print(f"Saved to DB: {DB_PATH}")
    return signals


def get_pending_signals(signal_date: str = None) -> pd.DataFrame:
    """Load pending signals for today from DB."""
    if signal_date is None:
        signal_date = date.today().strftime("%Y-%m-%d")

    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql("""
        SELECT * FROM paper_signals
        WHERE signal_date = ? AND status = 'PENDING'
        ORDER BY ev_net DESC
    """, conn, params=(signal_date,))
    conn.close()
    return df


if __name__ == "__main__":
    # force regenerate today's signals
    signals = generate_signals(force=True)

    if signals:
        print(f"\nTop signal:")
        s = signals[0]
        print(f"  Symbol:    {s['symbol']}")
        print(f"  Direction: {'LONG' if s['direction']==1 else 'SHORT'}")
        print(f"  Entry:     ₹{s['entry_price']}")
        print(f"  Stop:      ₹{s['stop_price']}")
        print(f"  Target1:   ₹{s['target1']}")
        print(f"  Target2:   ₹{s['target2']}")
        print(f"  Qty:       {s['qty']}")
        print(f"  EV:        ₹{s['ev_net']}")
    else:
        print("No signals today.")