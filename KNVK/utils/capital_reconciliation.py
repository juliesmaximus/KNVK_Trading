# utils/capital_reconciliation.py — FIXED: Capital reconciliation system
# Compares DB positions vs actual Kotak positions daily

import sys
sys.path.append(str(__import__('pathlib').Path(__file__).parent.parent))

import sqlite3
import pandas as pd
from datetime import datetime, date, timezone, timedelta
from data.kotak_feed import KotakClient
from paper.order_manager import get_open_trades
from config import DB_PATH

IST = timezone(timedelta(hours=5, minutes=30))

def now_ist() -> datetime:
    return datetime.now(IST)

def today_ist() -> str:
    return now_ist().strftime("%Y-%m-%d")


def reconcile_positions(kotak_client: KotakClient) -> dict:
    """
    FIX for capital management: Compare DB positions vs actual Kotak positions.
    Called at start of day (9:15 AM) and end of day (3:30 PM).
    
    Returns:
        {
            "db_positions": count,
            "kotak_positions": count,
            "match": bool,
            "details": [mismatch details],
            "alerts": [alert messages]
        }
    """
    alerts = []
    details = []
    
    # Get DB positions
    db_trades = get_open_trades()
    db_positions = {}
    
    if not db_trades.empty:
        for _, trade in db_trades.iterrows():
            db_positions[trade["symbol"]] = {
                "qty": trade["qty_remaining"],
                "entry": trade["entry_price"],
                "direction": "LONG" if trade["direction"] == 1 else "SHORT"
            }
    
    # Get Kotak positions
    kotak_positions = {}
    if kotak_client and kotak_client.is_authenticated():
        try:
            positions_response = kotak_client.get_positions()
            if positions_response:
                # Parse Kotak positions format
                for pos in positions_response:
                    symbol = pos.get("symbol", "")
                    qty = int(pos.get("qty", 0))
                    if qty != 0 and symbol:
                        kotak_positions[symbol] = {
                            "qty": qty,
                            "entry": float(pos.get("averagePrice", 0)),
                            "direction": "LONG" if qty > 0 else "SHORT"
                        }
        except Exception as e:
            alerts.append(f"ERROR: Could not fetch Kotak positions: {e}")
    else:
        alerts.append("WARNING: Not authenticated with Kotak — skipping reconciliation")
    
    # Compare
    all_symbols = set(db_positions.keys()) | set(kotak_positions.keys())
    
    for sym in all_symbols:
        db_pos = db_positions.get(sym)
        kt_pos = kotak_positions.get(sym)
        
        if db_pos and kt_pos:
            # Both exist — check quantity match
            if db_pos["qty"] != kt_pos["qty"]:
                mismatch = f"{sym}: DB qty={db_pos['qty']} vs Kotak qty={kt_pos['qty']}"
                details.append(mismatch)
                alerts.append(f"MISMATCH: {mismatch}")
        
        elif db_pos and not kt_pos:
            # In DB but not in Kotak — possible order failed
            mismatch = f"{sym}: In DB (qty={db_pos['qty']}) but NOT in Kotak"
            details.append(mismatch)
            alerts.append(f"MISSING: {mismatch}")
        
        elif not db_pos and kt_pos:
            # In Kotak but not in DB — manual trade or sync error
            mismatch = f"{sym}: In Kotak (qty={kt_pos['qty']}) but NOT in DB"
            details.append(mismatch)
            alerts.append(f"EXTRA: {mismatch}")
    
    match = (len(details) == 0)
    
    return {
        "timestamp": now_ist().strftime("%Y-%m-%d %H:%M:%S"),
        "db_position_count": len(db_positions),
        "kotak_position_count": len(kotak_positions),
        "match": match,
        "mismatches": details,
        "alerts": alerts
    }


def check_margin(kotak_client: KotakClient, required_margin: float) -> dict:
    """
    FIX for capital validation: Check if account has sufficient margin before trading.
    Called before opening new positions.
    
    Args:
        kotak_client: authenticated KotakClient
        required_margin: margin needed for next trade
    
    Returns:
        {
            "available_margin": float,
            "required_margin": float,
            "sufficient": bool,
            "message": str
        }
    """
    if not kotak_client or not kotak_client.is_authenticated():
        return {
            "available_margin": 0,
            "required_margin": required_margin,
            "sufficient": False,
            "message": "Not authenticated"
        }
    
    try:
        limits = kotak_client.get_limits()
        if not limits:
            return {
                "available_margin": 0,
                "required_margin": required_margin,
                "sufficient": False,
                "message": "Could not fetch limits"
            }
        
        # Parse limits response
        available_margin = float(limits.get("availableMargin", 0))
        
        sufficient = available_margin >= required_margin
        
        return {
            "available_margin": available_margin,
            "required_margin": required_margin,
            "sufficient": sufficient,
            "message": (
                f"Margin OK: ₹{available_margin:.0f} >= ₹{required_margin:.0f}" 
                if sufficient 
                else f"INSUFFICIENT: ₹{available_margin:.0f} < ₹{required_margin:.0f}"
            )
        }
    
    except Exception as e:
        return {
            "available_margin": 0,
            "required_margin": required_margin,
            "sufficient": False,
            "message": f"Error checking margin: {e}"
        }


def log_reconciliation(result: dict):
    """Save reconciliation results to journal log."""
    journal_dir = Path(__file__).parent.parent / "journal"
    journal_dir.mkdir(exist_ok=True)
    
    log_file = journal_dir / f"{today_ist()}_reconciliation.log"
    
    entry = (
        f"\n[{result['timestamp']}] RECONCILIATION\n"
        f"  DB positions: {result['db_position_count']}\n"
        f"  Kotak positions: {result['kotak_position_count']}\n"
        f"  Match: {'✓ YES' if result['match'] else '✗ NO'}\n"
    )
    
    if result['alerts']:
        entry += f"  Alerts:\n"
        for alert in result['alerts']:
            entry += f"    - {alert}\n"
    
    if result['mismatches']:
        entry += f"  Mismatches:\n"
        for mismatch in result['mismatches']:
            entry += f"    - {mismatch}\n"
    
    with open(log_file, "a") as f:
        f.write(entry)
    
    return log_file


if __name__ == "__main__":
    from pathlib import Path
    from utils.alerts import send_alert
    
    # Example usage
    client = KotakClient()
    
    print("Testing capital reconciliation...")
    result = reconcile_positions(client)
    
    print(f"\nReconciliation Result:")
    print(f"  DB positions: {result['db_position_count']}")
    print(f"  Kotak positions: {result['kotak_position_count']}")
    print(f"  Match: {result['match']}")
    
    if result['alerts']:
        print(f"\nAlerts:")
        for alert in result['alerts']:
            print(f"  - {alert}")
    
    print(f"\n\nMargin Check:")
    margin_result = check_margin(client, 50000)
    print(f"  Available: ₹{margin_result['available_margin']:,.0f}")
    print(f"  Required: ₹{margin_result['required_margin']:,.0f}")
    print(f"  Status: {margin_result['message']}")
