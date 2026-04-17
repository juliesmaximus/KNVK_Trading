# dashboard.py — KNVK paper trading dashboard

import sys
import time
from datetime import datetime, date

import pandas as pd
import sqlite3
import streamlit as st

sys.path.insert(0, str(__import__('pathlib').Path(__file__).parent))

from config import DB_PATH, STABLE_SYMBOLS, KOTAK_TOKEN_MAP

# ── page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title          = "KNVK Trading Dashboard",
    page_icon           = "📈",
    layout              = "wide",
    initial_sidebar_state = "expanded"
)

# ── auto refresh every 30 seconds ─────────────────────────────────────────────
from streamlit_autorefresh import st_autorefresh
st_autorefresh(interval=30000, limit=None, key="auto_refresh")

# ── DB helpers ────────────────────────────────────────────────────────────────

def get_open_trades() -> pd.DataFrame:
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql("""
        SELECT symbol, direction, entry_price, stop_current,
               target1, target2, qty, qty_remaining,
               net_pnl, entry_date
        FROM paper_trades
        WHERE status = 'OPEN'
        ORDER BY entry_date DESC
    """, conn)
    conn.close()
    df["direction"] = df["direction"].apply(
        lambda x: "LONG" if x == 1 else "SHORT"
    )
    return df


def get_closed_trades(trade_date: str = None) -> pd.DataFrame:
    if trade_date is None:
        trade_date = date.today().strftime("%Y-%m-%d")
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql("""
        SELECT symbol, direction, entry_price,
               net_pnl, total_charges, exit_reason, exit_date
        FROM paper_trades
        WHERE status = 'CLOSED' AND exit_date = ?
        ORDER BY exit_date DESC
    """, conn, params=(trade_date,))
    conn.close()
    df["direction"] = df["direction"].apply(
        lambda x: "LONG" if x == 1 else "SHORT"
    )
    return df


def get_daily_summary(trade_date: str = None) -> dict:
    if trade_date is None:
        trade_date = date.today().strftime("%Y-%m-%d")
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql("""
        SELECT * FROM paper_trades
        WHERE status = 'CLOSED' AND exit_date = ?
    """, conn, params=(trade_date,))
    conn.close()
    if df.empty:
        return {"trades": 0, "net_pnl": 0,
                "winners": 0, "losers": 0, "charges": 0}
    return {
        "trades":  len(df),
        "net_pnl": round(df["net_pnl"].sum(), 2),
        "winners": len(df[df["net_pnl"] > 0]),
        "losers":  len(df[df["net_pnl"] <= 0]),
        "charges": round(df["total_charges"].sum(), 2),
    }


def get_pending_signals(trade_date: str = None) -> pd.DataFrame:
    if trade_date is None:
        trade_date = date.today().strftime("%Y-%m-%d")
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql("""
        SELECT symbol, direction, entry_price, stop_price,
               target1, qty, ev_net, regime
        FROM paper_signals
        WHERE signal_date = ?
        ORDER BY ev_net DESC
    """, conn, params=(trade_date,))
    conn.close()
    df["direction"] = df["direction"].apply(
        lambda x: "LONG" if x == 1 else "SHORT"
    )
    return df


def get_equity_curve() -> pd.DataFrame:
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql("""
        SELECT exit_date, SUM(net_pnl) as daily_pnl
        FROM paper_trades
        WHERE status = 'CLOSED'
        GROUP BY exit_date
        ORDER BY exit_date
    """, conn)
    conn.close()
    if not df.empty:
        df["cumulative_pnl"] = df["daily_pnl"].cumsum()
    return df


def get_vix_regime() -> tuple:
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql(
        "SELECT close FROM vix_daily ORDER BY date DESC LIMIT 1",
        conn
    )
    conn.close()
    if df.empty:
        return 0, "UNKNOWN"
    vix = df["close"].iloc[0]
    if vix < 15:
        regime = "TREND"
    elif vix < 20:
        regime = "NEUTRAL"
    elif vix < 30:
        regime = "CAUTION"
    else:
        regime = "CHAOS"
    return round(vix, 2), regime


# ── live prices ────────────────────────────────────────────────────────────────

def get_live_prices() -> dict:
    """Read live prices from engine's price file."""
    try:
        from pathlib import Path
        import json
        price_file = Path(__file__).parent / "journal" / "live_prices.json"
        if price_file.exists():
            data = json.loads(price_file.read_text())
            return data.get("prices", {})
    except:
        pass
    return {}


# ── sidebar ────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.header("🔐 Kotak Neo")

    authenticated = (
        "kotak_client" in st.session_state and
        st.session_state.kotak_client.is_authenticated()
    )

    if not authenticated:
        totp = st.text_input(
            "Enter TOTP", max_chars=6, type="password",
            help="6-digit code from Google Authenticator"
        )
        if st.button("Authenticate", type="primary"):
            from data.kotak_feed import KotakClient
            client = KotakClient()
            with st.spinner("Authenticating..."):
                success = client.login(totp)
            if success:
                st.session_state.kotak_client = client
                st.success("Authenticated!")
                st.rerun()
            else:
                st.error("Failed — try fresh TOTP")
    else:
        st.success("✓ Live feed active")
        if st.button("Disconnect"):
            del st.session_state.kotak_client
            st.rerun()

    st.divider()

    # manual refresh
    if st.button("🔄 Refresh Now"):
        st.session_state.last_refresh = 0
        st.rerun()

    st.caption(f"Auto-refresh: 30s")
    st.caption(f"Last: {datetime.now().strftime('%H:%M:%S')} IST")

    st.divider()

    # engine controls
    st.header("⚙️ Engine")
    if st.button("Generate Signals"):
        from paper.signals_daily import generate_signals
        with st.spinner("Generating..."):
            signals = generate_signals(force=True)
        st.success(f"Generated {len(signals)} signals")
        st.rerun()


# ── header ─────────────────────────────────────────────────────────────────────

st.title("📈 KNVK Paper Trading Dashboard")

# ── load all data ──────────────────────────────────────────────────────────────

vix, regime     = get_vix_regime()
summary         = get_daily_summary()
open_trades     = get_open_trades()
prices          = get_live_prices()

regime_color = {
    "TREND":   "🟢",
    "NEUTRAL": "🟡",
    "CAUTION": "🟠",
    "CHAOS":   "🔴",
}.get(regime, "⚪")

# calculate unrealized PnL
unrealized_total = 0
if not open_trades.empty and prices:
    for _, row in open_trades.iterrows():
        ltp = prices.get(row["symbol"], 0)
        if ltp > 0:
            mult = 1 if row["direction"] == "LONG" else -1
            unrealized_total += (
                (ltp - row["entry_price"])
                * row["qty_remaining"]
                * mult
            )

# ── row 1 — metrics ────────────────────────────────────────────────────────────

c1, c2, c3, c4, c5 = st.columns(5)

with c1:
    st.metric(
        "India VIX", f"{vix}",
        delta=f"{regime_color} {regime}"
    )
with c2:
    st.metric("Open Positions", len(open_trades))
with c3:
    st.metric("Today's Trades", summary["trades"])
with c4:
    pnl = summary["net_pnl"]
    st.metric(
        "Today's PnL",
        f"₹{pnl:,.0f}",
        delta=f"{'▲' if pnl >= 0 else '▼'} ₹{abs(pnl):,.0f}"
    )
with c5:
    st.metric(
        "Unrealized PnL",
        f"₹{unrealized_total:,.0f}",
        delta=f"{'▲' if unrealized_total >= 0 else '▼'} ₹{abs(unrealized_total):,.0f}"
    )

st.divider()

# ── row 2 — positions + signals ────────────────────────────────────────────────

col_left, col_right = st.columns([3, 2])

with col_left:
    st.subheader("📊 Open Positions")

    if open_trades.empty:
        st.info("No open positions.")
    else:
        display = open_trades.copy()

        # add live price
        display["LTP"] = display["symbol"].map(
            lambda s: prices.get(s, 0)
        )

        # unrealized PnL per row
        display["Unreal PnL"] = display.apply(
            lambda r: (
                (r["LTP"] - r["entry_price"])
                * r["qty_remaining"]
                * (1 if r["direction"] == "LONG" else -1)
            ) if r["LTP"] > 0 else 0,
            axis=1
        )

        show = display[[
            "symbol", "direction", "entry_price",
            "LTP", "stop_current", "target1",
            "qty_remaining", "Unreal PnL"
        ]].rename(columns={
            "entry_price":   "Entry",
            "stop_current":  "Stop",
            "target1":       "Target1",
            "qty_remaining": "Qty",
        })

        def color_direction(val):
            return "color: #00c853" if val == "LONG" else "color: #ff1744"

        def color_pnl(val):
            return "color: #00c853" if val >= 0 else "color: #ff1744"

        styled = show.style.map(
            color_direction, subset=["direction"]
        ).map(
            color_pnl, subset=["Unreal PnL"]
        ).format({
            "Entry":      "₹{:.2f}",
            "LTP":        "₹{:.2f}",
            "Stop":       "₹{:.2f}",
            "Target1":    "₹{:.2f}",
            "Unreal PnL": "₹{:.2f}",
        })

        st.dataframe(styled, width='stretch', hide_index=True)

with col_right:
    st.subheader("🎯 Today's Signals")
    pending = get_pending_signals()

    if pending.empty:
        st.info("No signals — all converted to open trades.")
    else:
        st.dataframe(
            pending[[
                "symbol", "direction", "entry_price",
                "stop_price", "target1", "ev_net", "regime"
            ]].rename(columns={
                "entry_price": "Entry",
                "stop_price":  "Stop",
                "target1":     "T1",
                "ev_net":      "EV",
                "regime":      "Regime"
            }),
            width='stretch',
            hide_index=True
        )

st.divider()

# ── row 3 — closed trades + equity curve ──────────────────────────────────────

col_a, col_b = st.columns([2, 3])

with col_a:
    st.subheader("✅ Closed Today")
    closed = get_closed_trades()

    if closed.empty:
        st.info("No closed trades today.")
    else:
        st.dataframe(
            closed[[
                "symbol", "direction", "entry_price",
                "net_pnl", "exit_reason"
            ]].rename(columns={
                "entry_price": "Entry",
                "net_pnl":     "PnL",
                "exit_reason": "Reason"
            }),
            width='stretch',
            hide_index=True
        )
        c1, c2, c3 = st.columns(3)
        c1.metric("Winners", summary["winners"])
        c2.metric("Losers",  summary["losers"])
        c3.metric("Charges", f"₹{summary['charges']:,.0f}")

with col_b:
    st.subheader("📈 Equity Curve")
    equity = get_equity_curve()
    if equity.empty:
        st.info("Equity curve appears after first closed trades.")
    else:
        st.line_chart(
            equity.set_index("exit_date")["cumulative_pnl"],
            width='stretch'
        )

# ── footer ─────────────────────────────────────────────────────────────────────

st.divider()
live_status = "🟢 Live" if prices else "🔴 No live feed"
st.caption(
    f"{live_status} | "
    f"Symbols: {len(STABLE_SYMBOLS)} | "
    f"DB: {DB_PATH.name} | "
    f"Refreshed: {datetime.now().strftime('%H:%M:%S')} IST"
)