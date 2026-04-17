# utils/learning.py — daily learning and performance tracking

import sys
sys.path.append(str(__import__('pathlib').Path(__file__).parent.parent))

import sqlite3
import pandas as pd
from datetime import datetime, date, timezone, timedelta
from config import DB_PATH, STABLE_SYMBOLS
from utils.alerts import send_alert

# ── IST timezone ───────────────────────────────────────────────────────────────
IST = timezone(timedelta(hours=5, minutes=30))

def now_ist() -> datetime:
    return datetime.now(IST)

def today_ist() -> str:
    return now_ist().strftime("%Y-%m-%d")


# ─── DB setup ─────────────────────────────────────────────────────────────────

def init_learning_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS symbol_performance (
            symbol              TEXT PRIMARY KEY,
            total_trades        INTEGER DEFAULT 0,
            winning_trades      INTEGER DEFAULT 0,
            losing_trades       INTEGER DEFAULT 0,
            consecutive_losses  INTEGER DEFAULT 0,
            consecutive_wins    INTEGER DEFAULT 0,
            total_pnl           REAL DEFAULT 0,
            avg_pnl             REAL DEFAULT 0,
            risk_multiplier     REAL DEFAULT 1.0,
            status              TEXT DEFAULT 'ACTIVE',
            last_updated        TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS daily_performance (
            date            TEXT PRIMARY KEY,
            total_trades    INTEGER,
            winners         INTEGER,
            losers          INTEGER,
            net_pnl         REAL,
            win_rate        REAL,
            vix_regime      TEXT,
            notes           TEXT
        )
    """)
    conn.commit()
    conn.close()


# ─── Update symbol performance ────────────────────────────────────────────────

def update_symbol_performance(trade_date: str = None):
    if trade_date is None:
        trade_date = today_ist()

    init_learning_db()
    conn = sqlite3.connect(DB_PATH)

    trades = pd.read_sql("""
        SELECT symbol, net_pnl, exit_reason
        FROM paper_trades
        WHERE status = 'CLOSED'
        AND exit_date = ?
    """, conn, params=(trade_date,))

    if trades.empty:
        conn.close()
        return

    alerts_to_send = []

    for sym, group in trades.groupby("symbol"):
        sym_pnl  = group["net_pnl"].sum()
        sym_wins = len(group[group["net_pnl"] > 0])
        sym_loss = len(group[group["net_pnl"] <= 0])

        existing = conn.execute("""
            SELECT * FROM symbol_performance WHERE symbol=?
        """, (sym,)).fetchone()

        if existing:
            cols = [
                "symbol", "total_trades", "winning_trades",
                "losing_trades", "consecutive_losses",
                "consecutive_wins", "total_pnl", "avg_pnl",
                "risk_multiplier", "status", "last_updated"
            ]
            perf = dict(zip(cols, existing))
        else:
            perf = {
                "symbol": sym, "total_trades": 0,
                "winning_trades": 0, "losing_trades": 0,
                "consecutive_losses": 0, "consecutive_wins": 0,
                "total_pnl": 0, "avg_pnl": 0,
                "risk_multiplier": 1.0, "status": "ACTIVE"
            }

        perf["total_trades"]   += len(group)
        perf["winning_trades"] += sym_wins
        perf["losing_trades"]  += sym_loss
        perf["total_pnl"]      += sym_pnl
        perf["last_updated"]    = trade_date

        if perf["total_trades"] > 0:
            perf["avg_pnl"] = perf["total_pnl"] / perf["total_trades"]

        if sym_pnl > 0:
            perf["consecutive_wins"]  += 1
            perf["consecutive_losses"] = 0
        else:
            perf["consecutive_losses"] += 1
            perf["consecutive_wins"]    = 0

        cons_loss = perf["consecutive_losses"]

        if cons_loss >= 7:
            perf["risk_multiplier"] = 0.0
            perf["status"]          = "SUSPENDED"
            alerts_to_send.append((
                sym, "SUSPENDED",
                f"7 consecutive losses. Manual review required.\n"
                f"Total PnL: Rs{perf['total_pnl']:.0f}"
            ))
        elif cons_loss >= 5:
            perf["risk_multiplier"] = 0.25
            perf["status"]          = "REDUCED"
            alerts_to_send.append((
                sym, "CRITICAL",
                f"5 consecutive losses. Size reduced to 25%.\n"
                f"Total PnL: Rs{perf['total_pnl']:.0f}"
            ))
        elif cons_loss >= 3:
            perf["risk_multiplier"] = 0.5
            perf["status"]          = "CAUTION"
            alerts_to_send.append((
                sym, "CAUTION",
                f"3 consecutive losses. Size reduced to 50%.\n"
                f"Total PnL: Rs{perf['total_pnl']:.0f}"
            ))
        else:
            if cons_loss == 0 and perf["consecutive_wins"] >= 2:
                perf["risk_multiplier"] = min(
                    perf["risk_multiplier"] + 0.25, 1.0
                )
                if perf["risk_multiplier"] >= 1.0:
                    perf["status"] = "ACTIVE"

        conn.execute("""
            INSERT OR REPLACE INTO symbol_performance
            (symbol, total_trades, winning_trades, losing_trades,
             consecutive_losses, consecutive_wins, total_pnl,
             avg_pnl, risk_multiplier, status, last_updated)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """, (
            perf["symbol"], perf["total_trades"],
            perf["winning_trades"], perf["losing_trades"],
            perf["consecutive_losses"], perf["consecutive_wins"],
            perf["total_pnl"], perf["avg_pnl"],
            perf["risk_multiplier"], perf["status"],
            perf["last_updated"]
        ))

    conn.commit()
    conn.close()

    for sym, level, msg in alerts_to_send:
        emoji = "🚨" if level == "SUSPENDED" else \
                "⚠️" if level == "CRITICAL" else "🔶"
        send_alert(f"{emoji} <b>{level}: {sym}</b>\n{msg}")


# ─── Update daily performance ─────────────────────────────────────────────────

def update_daily_performance(trade_date: str = None):
    if trade_date is None:
        trade_date = today_ist()

    init_learning_db()
    conn = sqlite3.connect(DB_PATH)

    trades = pd.read_sql("""
        SELECT net_pnl FROM paper_trades
        WHERE status='CLOSED' AND exit_date=?
    """, conn, params=(trade_date,))

    vix = pd.read_sql("""
        SELECT close FROM vix_daily
        ORDER BY date DESC LIMIT 1
    """, conn)

    vix_val = vix["close"].iloc[0] if not vix.empty else 0
    regime  = (
        "TREND"   if vix_val < 15 else
        "NEUTRAL" if vix_val < 20 else
        "CAUTION" if vix_val < 30 else
        "CHAOS"
    )

    if not trades.empty:
        winners  = len(trades[trades["net_pnl"] > 0])
        losers   = len(trades[trades["net_pnl"] <= 0])
        net_pnl  = trades["net_pnl"].sum()
        win_rate = winners / len(trades) if len(trades) > 0 else 0

        conn.execute("""
            INSERT OR REPLACE INTO daily_performance
            (date, total_trades, winners, losers,
             net_pnl, win_rate, vix_regime)
            VALUES (?,?,?,?,?,?,?)
        """, (
            trade_date, len(trades), winners, losers,
            net_pnl, win_rate, regime
        ))
        conn.commit()

    conn.close()


# ─── Get risk multiplier ──────────────────────────────────────────────────────

def get_risk_multiplier(symbol: str) -> float:
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("""
        SELECT risk_multiplier, status
        FROM symbol_performance
        WHERE symbol = ?
    """, (symbol,)).fetchone()
    conn.close()

    if not row:
        return 1.0
    if row[1] == "SUSPENDED":
        return 0.0
    return row[0]


# ─── Send daily intelligence report ───────────────────────────────────────────

def send_intelligence_report(trade_date: str = None):
    if trade_date is None:
        trade_date = today_ist()

    init_learning_db()
    conn = sqlite3.connect(DB_PATH)

    day = pd.read_sql("""
        SELECT * FROM daily_performance WHERE date = ?
    """, conn, params=(trade_date,))

    symbols = pd.read_sql("""
        SELECT symbol, consecutive_losses, consecutive_wins,
               risk_multiplier, status, avg_pnl, total_trades
        FROM symbol_performance
        ORDER BY risk_multiplier ASC
    """, conn)

    week = pd.read_sql("""
        SELECT date, net_pnl, win_rate, vix_regime
        FROM daily_performance
        ORDER BY date DESC LIMIT 7
    """, conn)

    conn.close()

    if day.empty:
        send_alert(
            f"<b>KNVK Daily Report</b>\n"
            f"Date: {trade_date}\n"
            f"No closed trades today."
        )
        return

    d = day.iloc[0]
    suspended = symbols[symbols["status"] == "SUSPENDED"]["symbol"].tolist()
    caution   = symbols[symbols["status"] == "CAUTION"]["symbol"].tolist()
    reduced   = symbols[symbols["status"] == "REDUCED"]["symbol"].tolist()
    week_pnl  = week["net_pnl"].sum() if not week.empty else 0

    report = (
        f"<b>KNVK Daily Intelligence Report</b>\n"
        f"Date: {trade_date}\n\n"
        f"<b>Today</b>\n"
        f"Trades:   {int(d['total_trades'])}\n"
        f"Winners:  {int(d['winners'])}\n"
        f"Losers:   {int(d['losers'])}\n"
        f"Win rate: {d['win_rate']*100:.1f}%\n"
        f"Net PnL:  Rs{d['net_pnl']:,.0f}\n"
        f"Regime:   {d['vix_regime']}\n\n"
        f"<b>7-Day PnL</b>: Rs{week_pnl:,.0f}\n\n"
        f"<b>Symbol Health</b>\n"
    )

    if suspended:
        report += f"Suspended: {', '.join(suspended)}\n"
    if caution:
        report += f"Caution:   {', '.join(caution)}\n"
    if reduced:
        report += f"Reduced:   {', '.join(reduced)}\n"
    if not suspended and not caution and not reduced:
        report += "All symbols healthy\n"

    send_alert(report)


# ─── Full EOD learning cycle ───────────────────────────────────────────────────

def run_eod_learning(trade_date: str = None):
    if trade_date is None:
        trade_date = today_ist()

    print(f"\nRunning EOD learning cycle for {trade_date}")
    print("─" * 40)

    print("1. Updating symbol performance...")
    update_symbol_performance(trade_date)

    print("2. Logging daily performance...")
    update_daily_performance(trade_date)

    print("3. Sending intelligence report...")
    send_intelligence_report(trade_date)

    print("EOD learning complete.")


# ─── Performance report ────────────────────────────────────────────────────────

def print_performance_report():
    init_learning_db()
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql("""
        SELECT symbol, total_trades, winning_trades,
               consecutive_losses, risk_multiplier,
               status, avg_pnl, total_pnl
        FROM symbol_performance
        ORDER BY total_pnl DESC
    """, conn)
    conn.close()

    if df.empty:
        print("No performance data yet.")
        return

    print(f"\n{'Symbol':<15} {'Trades':>7} {'Wins':>5} "
          f"{'ConsLoss':>9} {'Risk':>6} {'Status':>10} "
          f"{'AvgPnL':>8} {'TotalPnL':>10}")
    print("─" * 75)

    for _, r in df.iterrows():
        print(
            f"{r['symbol']:<15} "
            f"{int(r['total_trades']):>7} "
            f"{int(r['winning_trades']):>5} "
            f"{int(r['consecutive_losses']):>9} "
            f"{r['risk_multiplier']:>6.2f} "
            f"{r['status']:>10} "
            f"Rs{r['avg_pnl']:>6.0f} "
            f"Rs{r['total_pnl']:>8.0f}"
        )


if __name__ == "__main__":
    run_eod_learning()
    print_performance_report()