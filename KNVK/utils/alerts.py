# utils/alerts.py — Telegram alerts for trading events

import os
import requests
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID")
BASE_URL  = f"https://api.telegram.org/bot{BOT_TOKEN}"


def send_alert(message: str) -> bool:
    """Send a Telegram message."""
    if not BOT_TOKEN or not CHAT_ID:
        print("Telegram not configured.")
        return False
    try:
        resp = requests.post(
            f"{BASE_URL}/sendMessage",
            json={
                "chat_id":    CHAT_ID,
                "text":       message,
                "parse_mode": "HTML"
            },
            timeout=5
        )
        return resp.status_code == 200
    except Exception as e:
        print(f"Alert error: {e}")
        return False


def alert_engine_start(symbols: int):
    send_alert(
        f"<b>KNVK Engine Started</b>\n"
        f"Time: {datetime.now().strftime('%H:%M')} IST\n"
        f"Universe: {symbols} symbols\n"
        f"Mode: PAPER TRADING"
    )


def alert_trade_opened(symbol: str, direction: str,
                       entry: float, stop: float,
                       target1: float, qty: int):
    emoji = "📈" if direction == "LONG" else "📉"
    send_alert(
        f"{emoji} <b>TRADE OPENED</b>\n"
        f"Symbol:  {symbol}\n"
        f"Direction: {direction}\n"
        f"Entry:   Rs{entry:.2f}\n"
        f"Stop:    Rs{stop:.2f}\n"
        f"Target1: Rs{target1:.2f}\n"
        f"Qty:     {qty}"
    )


def alert_partial_exit(symbol: str, target: str,
                       price: float, pnl: float):
    send_alert(
        f"⭐ <b>PARTIAL EXIT — {target}</b>\n"
        f"Symbol: {symbol}\n"
        f"Price:  Rs{price:.2f}\n"
        f"PnL:    Rs{pnl:,.0f}"
    )


def alert_stop_hit(symbol: str, price: float, pnl: float):
    send_alert(
        f"🛑 <b>STOP HIT</b>\n"
        f"Symbol: {symbol}\n"
        f"Price:  Rs{price:.2f}\n"
        f"PnL:    Rs{pnl:,.0f}"
    )


def alert_daily_summary(trades: int, net_pnl: float,
                        winners: int, losers: int):
    emoji = "✅" if net_pnl >= 0 else "❌"
    send_alert(
        f"{emoji} <b>DAILY SUMMARY</b>\n"
        f"Date:    {datetime.now().strftime('%Y-%m-%d')}\n"
        f"Trades:  {trades}\n"
        f"Net PnL: Rs{net_pnl:,.0f}\n"
        f"Winners: {winners}\n"
        f"Losers:  {losers}"
    )


def alert_session_expired():
    send_alert(
        f"⚠️ <b>SESSION EXPIRED</b>\n"
        f"Time: {datetime.now().strftime('%H:%M')} IST\n"
        f"Action: Re-authentication required"
    )


def alert_kill_switch(reason: str):
    send_alert(
        f"🚨 <b>KILL SWITCH TRIGGERED</b>\n"
        f"Reason: {reason}\n"
        f"Time:   {datetime.now().strftime('%H:%M')} IST\n"
        f"Action: All positions being closed"
    )


if __name__ == "__main__":
    print("Testing Telegram alert...")
    result = send_alert(
        "<b>KNVK Test Alert</b>\n"
        "Telegram integration working correctly."
    )
    print(f"Sent: {result}")