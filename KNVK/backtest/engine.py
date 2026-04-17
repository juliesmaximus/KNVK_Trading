# backtest/engine.py — core backtester with partial exits

import sys
sys.path.append(str(__import__('pathlib').Path(__file__).parent.parent))

import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from typing import Optional
from config import (
    ATR_MULTIPLIER, RISK_PER_TRADE_PCT, MAX_TRADES_DAY,
    DAILY_LOSS_LIMIT, MIN_RR_RATIO, MIN_ATR_PCT
)
from backtest.costs import calculate_charges, ev_check


# ─── Trade record ─────────────────────────────────────────────────────────────

@dataclass
class Trade:
    symbol:       str
    entry_date:   str
    entry_price:  float
    direction:    int          # 1=long, -1=short
    qty:          int
    stop:         float
    target1:      float        # 1R — exit 50%
    target2:      float        # 2R — exit 25%
    atr:          float
    regime:       str

    # filled during simulation
    exit_date:    Optional[str]   = None
    exit_reason:  Optional[str]   = None
    gross_pnl:    float           = 0.0
    total_charges:float           = 0.0
    net_pnl:      float           = 0.0

    # partial fill tracking
    qty_remaining:int             = 0
    stop_current: float           = 0.0
    partial1_done:bool            = False
    partial2_done:bool            = False

    def __post_init__(self):
        self.qty_remaining = self.qty
        self.stop_current  = self.stop


# ─── Engine ───────────────────────────────────────────────────────────────────

class Backtester:

    def __init__(self, capital: float = 500_000):
        self.capital       = capital
        self.initial_cap   = capital
        self.trades        = []
        self.equity_curve  = []
        self.daily_pnl     = 0.0
        self.daily_trades  = 0
        self.open_trade    = None      # one position at a time for now

    # ── Position sizing ───────────────────────────────────────────────────────

    def _calc_qty(self, entry: float, stop: float, regime: str) -> int:
        risk_amt      = self.capital * RISK_PER_TRADE_PCT
        stop_distance = abs(entry - stop)
        if stop_distance == 0:
            return 0
        qty = int(risk_amt / stop_distance)
        return max(qty, 1)

    # ── Entry logic ───────────────────────────────────────────────────────────

    def _try_entry(self, row: pd.Series, symbol: str) -> Optional[Trade]:
        """
        Attempt entry on signal.
        Signal on day T → entry at open of day T+1 (handled by caller).
        """
        if row["signal"] == 0:
            return None
        if row["regime"] == "CHAOS":
            return None
        if self.daily_trades >= MAX_TRADES_DAY:
            return None
        if self.daily_pnl <= -(self.capital * DAILY_LOSS_LIMIT):
            return None
        if self.open_trade is not None:
            return None
       
        raw_signal  = row["signal"]
        direction   = 1 if raw_signal > 0 else -1
        is_breakout = abs(raw_signal) == 2

        entry_price = row["open"]
        atr         = row["atr"]
        regime      = row["regime"]

        # filter out low volatility stocks
        if (atr / entry_price) < MIN_ATR_PCT:
            return None

        # breakout uses tighter multiplier
        if is_breakout:
            multiplier = ATR_MULTIPLIER.get(regime, 2.0) * 0.75
        else:
            multiplier = ATR_MULTIPLIER.get(regime, 2.0)

        if direction == 1:
            stop    = entry_price - (multiplier * atr)
            target1 = entry_price + (2 * multiplier * atr)
            target2 = entry_price + (4 * multiplier * atr)
        else:
            stop    = entry_price + (multiplier * atr)
            target1 = entry_price - (2 * multiplier * atr)
            target2 = entry_price - (4 * multiplier * atr)
                # RR check
        reward = abs(target1 - entry_price)
        risk   = abs(entry_price - stop)
        if risk == 0 or (reward / risk) < MIN_RR_RATIO:
            return None

        # EV check
        qty        = self._calc_qty(entry_price, stop, regime)
        trade_val  = qty * entry_price
        ev         = ev_check(trade_val, reward, risk, entry_price)
        if not ev["take_trade"]:
            return None

        self.daily_trades += 1

        return Trade(
            symbol      = symbol,
            entry_date  = str(row.name),
            entry_price = entry_price,
            direction   = direction,
            qty         = qty,
            stop        = stop,
            target1     = target1,
            target2     = target2,
            atr         = atr,
            regime      = regime,
        )

    # ── Partial exit helper ───────────────────────────────────────────────────

    def _exit_partial(
        self,
        trade: Trade,
        exit_price: float,
        qty_exit: int,
        reason: str,
        date: str
    ):
        entry_val  = qty_exit * trade.entry_price
        exit_val   = qty_exit * exit_price
        gross      = (exit_price - trade.entry_price) * qty_exit * trade.direction

        charges    = calculate_charges(entry_val, side="buy")["total"] + \
                     calculate_charges(exit_val,  side="sell")["total"]

        trade.gross_pnl     += gross
        trade.total_charges += charges
        trade.qty_remaining -= qty_exit

        return gross - charges

    # ── Simulate one trade through price bars ─────────────────────────────────

    def _simulate_trade(
        self,
        trade: Trade,
        bars: pd.DataFrame       # bars AFTER entry date
    ) -> Trade:

        for date, row in bars.iterrows():
            hi = row["high"]
            lo = row["low"]
            d  = trade.direction

            # ── Partial 1 — 50% at 1R ─────────────────────────────────────
            if not trade.partial1_done:
                hit1 = (d == 1 and hi >= trade.target1) or \
                       (d == -1 and lo <= trade.target1)
                if hit1:
                    qty1 = trade.qty // 2
                    self._exit_partial(
                        trade, trade.target1, qty1, "target1", str(date))
                    trade.partial1_done = True
                    # move stop to breakeven
                    trade.stop_current = trade.entry_price

            # ── Partial 2 — 25% at 2R ─────────────────────────────────────
            if trade.partial1_done and not trade.partial2_done:
                hit2 = (d == 1 and hi >= trade.target2) or \
                       (d == -1 and lo <= trade.target2)
                if hit2:
                    qty2 = trade.qty // 4
                    self._exit_partial(
                        trade, trade.target2, qty2, "target2", str(date))
                    trade.partial2_done = True
                    # trail stop to 1R level
                    trade.stop_current = trade.target1

            # ── Stop loss check ───────────────────────────────────────────
            stop_hit = (d == 1 and lo <= trade.stop_current) or \
                       (d == -1 and hi >= trade.stop_current)
            if stop_hit:
                qty_left = trade.qty_remaining
                self._exit_partial(
                    trade, trade.stop_current, qty_left, "stop", str(date))
                trade.exit_date   = str(date)
                trade.exit_reason = "stop"
                break

            # ── Time exit — end of available bars ─────────────────────────
            if date == bars.index[-1]:
                qty_left = trade.qty_remaining
                self._exit_partial(
                    trade, row["close"], qty_left, "time", str(date))
                trade.exit_date   = str(date)
                trade.exit_reason = "time"
                break

        trade.net_pnl = trade.gross_pnl - trade.total_charges
        return trade

    # ── Main backtest loop ────────────────────────────────────────────────────

    def run(
        self,
        symbol: str,
        df: pd.DataFrame        # output of prepare_features()
    ):
        """
        Run backtest on a single symbol.
        df must have signal column from signals.py.
        """
        self.daily_pnl   = 0.0
        self.daily_trades = 0

        for i in range(len(df) - 1):
            row_signal = df.iloc[i]      # signal day T
            row_entry  = df.iloc[i + 1]  # entry day T+1

            # reset daily counters on new date
            if i > 0:
                prev_date = str(df.index[i - 1])[:10]
                curr_date = str(df.index[i])[:10]
                if curr_date != prev_date:
                    self.daily_pnl    = 0.0
                    self.daily_trades = 0

            # attempt entry
            if row_signal["signal"] != 0:
                # pass T+1 row for entry price but T signal for direction
                entry_row = row_entry.copy()
                entry_row["signal"] = row_signal["signal"]
                entry_row["atr"]    = row_signal["atr"]
                entry_row["regime"] = row_signal["regime"]

                trade = self._try_entry(entry_row, symbol)

                if trade:
                    # simulate through remaining bars
                    future_bars = df.iloc[i + 2:]
                    if len(future_bars) == 0:
                        continue
                    trade = self._simulate_trade(trade, future_bars)

                    self.trades.append(trade)
                    self.capital   += trade.net_pnl
                    self.daily_pnl += trade.net_pnl

            # equity curve snapshot
            self.equity_curve.append({
                "date":    str(df.index[i])[:10],
                "capital": round(self.capital, 2)
            })

        return self

    # ── Results ───────────────────────────────────────────────────────────────

    def results(self) -> dict:
        if not self.trades:
            return {"error": "no trades"}

        df = pd.DataFrame([{
            "symbol":       t.symbol,
            "entry_date":   t.entry_date,
            "exit_date":    t.exit_date,
            "exit_reason":  t.exit_reason,
            "direction":    "LONG" if t.direction == 1 else "SHORT",
            "qty":          t.qty,
            "entry_price":  t.entry_price,
            "gross_pnl":    round(t.gross_pnl, 2),
            "charges":      round(t.total_charges, 2),
            "net_pnl":      round(t.net_pnl, 2),
            "regime":       t.regime,
        } for t in self.trades])

        wins        = df[df["net_pnl"] > 0]
        losses      = df[df["net_pnl"] <= 0]
        total       = len(df)
        win_rate    = len(wins) / total if total > 0 else 0
        avg_win     = wins["net_pnl"].mean()    if len(wins) > 0 else 0
        avg_loss    = losses["net_pnl"].mean()  if len(losses) > 0 else 0
        profit_factor = (wins["net_pnl"].sum() / abs(losses["net_pnl"].sum())
                        if losses["net_pnl"].sum() != 0 else 0)

        equity  = pd.DataFrame(self.equity_curve)
        peak    = equity["capital"].cummax()
        dd      = (equity["capital"] - peak) / peak
        max_dd  = dd.min()

        return {
            "total_trades":   total,
            "win_rate":       round(win_rate * 100, 1),
            "avg_win":        round(avg_win, 2),
            "avg_loss":       round(avg_loss, 2),
            "profit_factor":  round(profit_factor, 2),
            "net_pnl":        round(df["net_pnl"].sum(), 2),
            "max_drawdown":   round(max_dd * 100, 2),
            "total_charges":  round(df["charges"].sum(), 2),
            "by_regime":      df.groupby("regime")["net_pnl"].sum().to_dict(),
            "by_exit":        df.groupby("exit_reason")["net_pnl"].sum().to_dict(),
            "trades_df":      df
        }