# backtest/costs.py — standalone cost model, fully testable

import sys
sys.path.append(str(__import__('pathlib').Path(__file__).parent.parent))

from config import COST, MIN_RR_RATIO


def calculate_charges(
    trade_value: float,
    side: str = "both"   # "buy", "sell", or "both" (round trip)
) -> dict:
    """
    Calculate exact NSE equity intraday charges in rupees.
    Kotak Neo API — zero brokerage.

    Args:
        trade_value: total value of one side (qty × price)
        side: "buy", "sell", or "both" for round trip

    Returns:
        dict with each charge broken out + total
    """
    if trade_value == 0:
        return {
            "trade_value": 0, "brokerage": 0, "stt": 0,
            "txn": 0, "sebi": 0, "stamp": 0, "gst": 0,
            "slippage": 0, "total": 0, "pct_of_trade": 0
             }
    c = COST

    # --- per side charges ---
    brokerage = 0.0

    # STT: only on sell side
    stt = trade_value * c["stt_sell_pct"] if side in ("sell", "both") else 0.0

    # Transaction charge: both sides
    sides = 2 if side == "both" else 1
    txn   = trade_value * c["txn_charge_pct"] * sides

    # SEBI: ₹10 per crore, both sides
    sebi  = (trade_value / 1e7) * c["sebi_per_crore"] * sides

    # Stamp duty: buy side only
    stamp = trade_value * c["stamp_buy_pct"] if side in ("buy", "both") else 0.0

    # GST: 18% on brokerage + txn + sebi (NOT on stt or stamp)
    gst   = (brokerage + txn + sebi) * c["gst_pct"]

    # Slippage: both sides (entry + exit)
    slippage = trade_value * c["slippage_pct"] * sides

    total = brokerage + stt + txn + sebi + stamp + gst + slippage

    return {
        "trade_value": round(trade_value, 2),
        "brokerage":   round(brokerage,   2),
        "stt":         round(stt,         2),
        "txn":         round(txn,         2),
        "sebi":        round(sebi,        4),
        "stamp":       round(stamp,       2),
        "gst":         round(gst,         2),
        "slippage":    round(slippage,    2),
        "total":       round(total,       2),
        "pct_of_trade": round((total / trade_value) * 100, 4)
    }


def min_move_to_breakeven(trade_value: float) -> float:
    """
    Minimum price move needed just to cover friction costs.
    Returns as percentage of trade value.
    """
    charges = calculate_charges(trade_value)
    return charges["pct_of_trade"]


def ev_check(
    trade_value: float,
    reward_pts:  float,
    risk_pts:    float,
    entry_price: float,
    p_win:       float = 0.45
) -> dict:
    """
    Full EV check with cost adjustment.

    Args:
        trade_value: qty × entry_price
        reward_pts:  target - entry (points)
        risk_pts:    entry - stop (points)
        entry_price: for converting points to rupees
        p_win:       estimated win probability

    Returns:
        dict with ev, threshold, and take_trade decision
    """
    qty      = trade_value / entry_price
    reward_r = qty * reward_pts * 0.85    # haircut per spec
    risk_r   = qty * risk_pts   * 1.10    # inflate per spec

    charges  = calculate_charges(trade_value)
    friction = charges["total"]

    ev_gross = (p_win * reward_r) - ((1 - p_win) * risk_r)
    ev_net   = ev_gross - friction
    threshold  = friction * 1.0       # ev_net must at least cover friction
    take_trade = (
    ev_net >= threshold and
    (reward_pts / risk_pts) >= MIN_RR_RATIO
    )

    return {
        "ev_gross":    round(ev_gross,  2),
        "ev_net":      round(ev_net,    2),
        "friction":    round(friction,  2),
        "threshold":   round(threshold, 2),
        "reward_r":    round(reward_r,  2),
        "risk_r":      round(risk_r,    2),
        "take_trade":  ev_net >= threshold,
        "rr_ratio":    round(reward_pts / risk_pts, 2) if risk_pts > 0 else 0
    }


if __name__ == "__main__":
    # ── Verification against our locked spec ──────────────────────────────────
    # From spec: ₹1L intraday trade on Kotak Neo should cost ~₹32 round trip

    print("=" * 50)
    print("Cost model verification — ₹1,00,000 intraday trade")
    print("=" * 50)

    charges = calculate_charges(100_000)
    for k, v in charges.items():
        print(f"  {k:<20} {v}")

    print()
    print(f"  Breakeven move needed: {min_move_to_breakeven(100_000):.4f}%")

    print()
    print("=" * 50)
    print("EV check — entry ₹1000, target ₹1030, stop ₹985")
    print("Capital at risk: ₹1,00,000 | p_win: 0.45")
    print("=" * 50)

    ev = ev_check(
        trade_value=100_000,
        reward_pts=40,
        risk_pts=20,
        entry_price=1000,
        p_win=0.45
    )
    for k, v in ev.items():
        print(f"  {k:<20} {v}")