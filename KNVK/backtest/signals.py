# backtest/signals.py — all signal calculations for the backtester

import pandas as pd
import numpy as np
from config import (
    ZSCORE_PERIOD, ZSCORE_THRESHOLD, ATR_PERIOD,
    VWAP_STRETCH_ATR, COST, EV_FRICTION_MULTIPLIER
)


# ─── Regime ───────────────────────────────────────────────────────────────────

def classify_regime(vix_value: float) -> str:
    """
    Classify market regime based on India VIX.
    Returns: TREND | NEUTRAL | CAUTION | CHAOS
    """
    if vix_value < 15:
        return "TREND"
    elif vix_value < 20:
        return "NEUTRAL"
    elif vix_value < 30:
        return "CAUTION"
    else:
        return "CHAOS"


def add_regime(df: pd.DataFrame, vix: pd.DataFrame) -> pd.DataFrame:
    """
    Merge VIX regime into OHLCV DataFrame.
    df must have DatetimeIndex.
    """
    vix_regime = vix["close"].apply(classify_regime)
    vix_regime.name = "regime"
    df = df.join(vix_regime, how="left")
    df["regime"] = df["regime"].ffill()   # fill weekends/holidays
    return df


# ─── ATR ──────────────────────────────────────────────────────────────────────

def add_atr(df: pd.DataFrame, period: int = ATR_PERIOD) -> pd.DataFrame:
    """
    Average True Range — measures volatility.
    Used for stop loss sizing and position sizing.
    True Range = max(H-L, |H-Cprev|, |L-Cprev|)
    """
    hi, lo, cp = df["high"], df["low"], df["close"].shift(1)
    tr = pd.concat([
        hi - lo,
        (hi - cp).abs(),
        (lo - cp).abs()
    ], axis=1).max(axis=1)

    df["atr"] = tr.rolling(period).mean()
    return df


# ─── Z-Score ──────────────────────────────────────────────────────────────────

def add_zscore(df: pd.DataFrame, period: int = ZSCORE_PERIOD) -> pd.DataFrame:
    """
    Rolling Z-score of close price.
    Z > 2.5 = stretched high (mean reversion short signal)
    Z < -2.5 = stretched low (mean reversion long signal)
    """
    roll_mean = df["close"].rolling(period).mean()
    roll_std  = df["close"].rolling(period).std()
    df["zscore"] = (df["close"] - roll_mean) / roll_std
    return df


# ─── VWAP ─────────────────────────────────────────────────────────────────────

def add_vwap(df: pd.DataFrame, period: int = 20) -> pd.DataFrame:
    """
    Rolling VWAP over `period` days.
    Prevents the cumsum drift problem on long historical series.
    Resets the volume-weighted average every `period` bars.
    """
    typical = (df["high"] + df["low"] + df["close"]) / 3
    tp_vol  = typical * df["volume"]

    rolling_tp_vol = tp_vol.rolling(period).sum()
    rolling_vol    = df["volume"].rolling(period).sum()

    df["vwap"]         = rolling_tp_vol / rolling_vol
    df["vwap_stretch"] = (df["close"] - df["vwap"]).abs() / df["atr"]
    return df


# ─── Signals ──────────────────────────────────────────────────────────────────

def add_signals(df: pd.DataFrame) -> pd.DataFrame:
    """
    Generate raw long/short signals based on Z-score + VWAP stretch.

    Long signal:  Z < -2.5 AND price stretched below VWAP by > 1.5 ATR
    Short signal: Z > +2.5 AND price stretched above VWAP by > 1.5 ATR

    Returns df with signal column:
        1  = long
       -1  = short
        0  = no signal
    """
    z  = df["zscore"]
    vs = df["vwap_stretch"]

    long_signal  = (z < -ZSCORE_THRESHOLD) & (vs > VWAP_STRETCH_ATR)
    short_signal = (z >  ZSCORE_THRESHOLD) & (vs > VWAP_STRETCH_ATR)

    df["signal"] = 0
    df.loc[long_signal,  "signal"] = 1
    df.loc[short_signal, "signal"] = -1
    return df

# ─── Breakout ─────────────────────────────────────────────────────────────────

def add_breakout_signal(df: pd.DataFrame, 
                         volume_mult: float = 1.5,
                         lookback: int = 20) -> pd.DataFrame:
    """
    Breakout signal for event-driven stocks.
    Runs alongside mean reversion — does NOT override it.
    
    Conditions (all three must be true):
    1. Price breaks above 20-day high
    2. Volume > 1.5x 20-day average volume
    3. Z-score > 0 (momentum positive)
    """
    rolling_high   = df["high"].shift(1).rolling(lookback).max()
    avg_volume     = df["volume"].rolling(lookback).mean()

    breakout_long  = (
        (df["close"] > rolling_high) &          # new 20-day high
        (df["volume"] > avg_volume * volume_mult) &  # volume surge
        (df["zscore"] > 0)                      # momentum positive
    )

    breakout_short = (
        (df["close"] < df["low"].shift(1).rolling(lookback).min()) &
        (df["volume"] > avg_volume * volume_mult) &
        (df["zscore"] < 0)
    )

    # only add breakout where mean reversion has no signal
    df.loc[breakout_long  & (df["signal"] == 0), "signal"] = 2   # breakout long
    df.loc[breakout_short & (df["signal"] == 0), "signal"] = -2  # breakout short

    return df


# ─── Cost & EV ────────────────────────────────────────────────────────────────

def friction_cost(trade_value: float) -> float:
    """
    Calculate exact round-trip friction cost in rupees for Kotak Neo.
    Based on locked cost model from system spec.

    Components (intraday equity, NSE):
    - Brokerage:        ₹0 (Kotak Neo API)
    - STT:              0.025% on sell side only
    - Transaction:      0.00345% both sides (buy + sell)
    - SEBI:             ₹10 per crore (both sides)
    - Stamp duty:       0.003% buy side only
    - GST:              18% on (brokerage + transaction + SEBI)
    - Slippage:         0.05% of trade value (both sides)
    """
    c = COST

    brokerage   = 0.0
    stt         = trade_value * c["stt_sell_pct"]
    txn         = trade_value * c["txn_charge_pct"] * 2   # buy + sell
    sebi        = (trade_value / 1e7) * c["sebi_per_crore"] * 2
    stamp       = trade_value * c["stamp_buy_pct"]
    gst         = (brokerage + txn + sebi) * c["gst_pct"]
    slippage    = trade_value * c["slippage_pct"] * 2

    return brokerage + stt + txn + sebi + stamp + gst + slippage


def calculate_ev(
    trade_value: float,
    reward_r:    float,
    risk_r:      float,
    p_win:       float
) -> dict:
    """
    Calculate Expected Value of a trade after all costs.

    reward_r: reward in rupees (gross, before cost adjustment)
    risk_r:   risk in rupees (gross)
    p_win:    estimated win probability (0–1)

    Applies conservative adjustments from system spec:
    - Reward haircut: × 0.85 (slippage on exit)
    - Risk inflation: × 1.10 (prevent false positives)
    """
    friction  = friction_cost(trade_value)
    reward    = reward_r * 0.85
    risk      = risk_r   * 1.10
    ev        = (p_win * reward) - ((1 - p_win) * risk)
    ev_net    = ev - friction
    threshold = friction * EV_FRICTION_MULTIPLIER

    return {
        "ev_gross":   round(ev, 2),
        "ev_net":     round(ev_net, 2),
        "friction":   round(friction, 2),
        "threshold":  round(threshold, 2),
        "take_trade": ev_net >= threshold
    }


# ─── Position sizing ──────────────────────────────────────────────────────────

def position_size(
    capital:    float,
    entry:      float,
    stop:       float,
    risk_pct:   float = 0.01
) -> int:
    """
    Calculate number of shares to buy.
    Qty = (Capital × Risk%) ÷ (Entry - Stop)
    Returns integer shares, minimum 1.
    """
    risk_amount  = capital * risk_pct
    stop_distance = abs(entry - stop)
    if stop_distance == 0:
        return 0
    qty = int(risk_amount / stop_distance)
    return max(qty, 1)


# ─── Full pipeline ────────────────────────────────────────────────────────────

def prepare_features(
    df: pd.DataFrame,
    vix: pd.DataFrame,
    include_breakout: bool = False    # off by default
) -> pd.DataFrame:
    df = df.copy()
    df = add_regime(df, vix)
    df = add_atr(df)
    df = add_zscore(df)
    df = add_vwap(df)
    df = add_signals(df)
    if include_breakout:
        df = add_breakout_signal(df)  # runs after mean reversion
    df = df.dropna()
    return df

