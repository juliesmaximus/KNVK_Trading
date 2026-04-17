# backtest/walkforward.py — out-of-sample validation

import sys
sys.path.append(str(__import__('pathlib').Path(__file__).parent.parent))

import pandas as pd
from data.downloader import load_symbol, load_vix
from backtest.signals import prepare_features
from backtest.engine import Backtester
from config import ACTIVE_SYMBOLS


def run_walkforward(
    real_capital: float = 100_000,
    leverage:     float = 5.0,
    train_end:    str   = "2023-12-31",
    test_start:   str   = "2024-01-01",
    test_end:     str   = "2024-12-31"
):
    trading_capital = real_capital * leverage
    vix             = load_vix()

    train_results = []
    test_results  = []
    failed        = []

    print(f"Walk-Forward Validation")
    print(f"Train: 2021-01-01 → {train_end}")
    print(f"Test:  {test_start} → {test_end}")
    print(f"{'─'*55}\n")

    for sym in ACTIVE_SYMBOLS:
        try:
            df  = load_symbol(sym)
            if df.empty:
                failed.append(sym)
                continue

            out = prepare_features(df, vix, include_breakout=False)

            # ── Train period ──────────────────────────────────────
            train_df = out[out.index <= train_end]
            if len(train_df) < 100:
                continue

            bt_train = Backtester(capital=trading_capital)
            bt_train.run(sym, train_df)
            r_train  = bt_train.results()

            if "error" in r_train:
                continue

            # ── Test period (out of sample) ───────────────────────
            test_df = out[
                (out.index >= test_start) &
                (out.index <= test_end)
            ]
            if len(test_df) < 20:
                continue

            bt_test = Backtester(capital=trading_capital)
            bt_test.run(sym, test_df)
            r_test  = bt_test.results()

            if "error" in r_test:
                test_results.append({
                    "symbol":        sym,
                    "trades":        0,
                    "win_rate":      0,
                    "net_pnl":       0,
                    "profit_factor": 0,
                    "max_drawdown":  0,
                })
            else:
                test_results.append({
                    "symbol":        sym,
                    "trades":        r_test["total_trades"],
                    "win_rate":      r_test["win_rate"],
                    "net_pnl":       r_test["net_pnl"],
                    "profit_factor": r_test["profit_factor"],
                    "max_drawdown":  r_test["max_drawdown"],
                })

            train_results.append({
                "symbol":        sym,
                "trades":        r_train["total_trades"],
                "win_rate":      r_train["win_rate"],
                "net_pnl":       r_train["net_pnl"],
                "profit_factor": r_train["profit_factor"],
                "max_drawdown":  r_train["max_drawdown"],
            })

            r_test_pf = r_test["profit_factor"] if "error" not in r_test else 0
            r_test_pnl = r_test["net_pnl"] if "error" not in r_test else 0
            print(f"✓ {sym:<20} "
                  f"train_pf={r_train['profit_factor']:<6} "
                  f"test_pf={r_test_pf:<6} "
                  f"test_pnl=₹{r_test_pnl:.0f}")

        except Exception as e:
            print(f"✗ {sym:<20} ERROR: {e}")
            failed.append(sym)

    # ── Summary ───────────────────────────────────────────────────
    df_train = pd.DataFrame(train_results)
    df_test  = pd.DataFrame(test_results)

    print(f"\n{'═'*55}")
    print(f"WALK-FORWARD SUMMARY")
    print(f"{'═'*55}")
    print(f"{'Metric':<25} {'TRAIN':>12} {'TEST (OOS)':>12}")
    print(f"{'─'*50}")
    print(f"{'Symbols':<25} {len(df_train):>12} {len(df_test):>12}")
    print(f"{'Total trades':<25} {df_train['trades'].sum():>12} {df_test['trades'].sum():>12}")
    print(f"{'Avg win rate':<25} {df_train['win_rate'].mean():>11.1f}% {df_test['win_rate'].mean():>11.1f}%")
    print(f"{'Total net PnL':<25} ₹{df_train['net_pnl'].sum():>10,.0f} ₹{df_test['net_pnl'].sum():>10,.0f}")
    print(f"{'Avg profit factor':<25} {df_train['profit_factor'].mean():>12.2f} {df_test['profit_factor'].mean():>12.2f}")
    print(f"{'Worst drawdown':<25} {df_train['max_drawdown'].min():>11.1f}% {df_test['max_drawdown'].min():>11.1f}%")

    pnl_ratio = (df_test['net_pnl'].sum() /
                 df_train['net_pnl'].sum() * 3) if df_train['net_pnl'].sum() > 0 else 0
    print(f"\nOOS PnL ratio (test×3 vs train): {pnl_ratio:.2f}×")
    print("(>0.7 = good | 0.5-0.7 = acceptable | <0.5 = overfitted)")

    merged = df_train.merge(df_test, on="symbol", suffixes=("_train", "_test"))
    flipped = merged[
        (merged["net_pnl_train"] > 0) &
        (merged["net_pnl_test"]  < 0)
    ]["symbol"].tolist()
    print(f"\nSymbols profitable in train but losing in test: {flipped}")

    merged.to_csv("walkforward_results.csv", index=False)
    print(f"\nFull results saved: walkforward_results.csv")

    return df_train, df_test


def get_stable_symbols(
    df_train: pd.DataFrame,
    df_test:  pd.DataFrame
) -> list:
    """
    Returns symbols profitable in both train and test periods.
    These are the only symbols we trade live.
    """
    merged = df_train.merge(
        df_test, on="symbol", suffixes=("_train", "_test")
    )

    stable = merged[
        (merged["net_pnl_train"]       > 0) &
        (merged["net_pnl_test"]        > 0) &
        (merged["profit_factor_train"] >= 1.2) &
        (merged["profit_factor_test"]  >= 1.0)
    ]["symbol"].tolist()

    return stable

def run_rolling_walkforward(
    real_capital: float = 100_000,
    leverage:     float = 5.0,
    symbols:      list  = None,
    window_months: int  = 6
):
    """
    Tests signal across multiple 6-month windows.
    More robust than single train/test split.
    """
    if symbols is None:
        from config import STABLE_SYMBOLS
        symbols = STABLE_SYMBOLS

    trading_capital = real_capital * leverage
    vix             = load_vix()

    windows = [
        ("2021-01-01", "2021-06-30"),
        ("2021-07-01", "2021-12-31"),
        ("2022-01-01", "2022-06-30"),
        ("2022-07-01", "2022-12-31"),
        ("2023-01-01", "2023-06-30"),
        ("2023-07-01", "2023-12-31"),
        ("2024-01-01", "2024-06-30"),
        ("2024-07-01", "2024-12-31"),
    ]

    print(f"\nRolling Walk-Forward — {len(windows)} windows")
    print(f"Symbols: {len(symbols)}")
    print(f"{'─'*60}")
    print(f"{'Window':<25} {'Trades':>8} {'Win%':>8} {'PnL':>12} {'PF':>8}")
    print(f"{'─'*60}")

    window_results = []

    for start, end in windows:
        window_trades  = 0
        window_pnl     = 0
        window_wins    = 0
        window_pf_list = []

        for sym in symbols:
            try:
                df  = load_symbol(sym)
                if df.empty:
                    continue

                out = prepare_features(df, vix, include_breakout=False)
                period_df = out[
                    (out.index >= start) &
                    (out.index <= end)
                ]

                if len(period_df) < 20:
                    continue

                bt = Backtester(capital=trading_capital)
                bt.run(sym, period_df)
                r  = bt.results()

                if "error" not in r:
                    window_trades += r["total_trades"]
                    window_pnl    += r["net_pnl"]
                    window_pf_list.append(r["profit_factor"])

            except:
                continue

        avg_pf = sum(window_pf_list) / len(window_pf_list) if window_pf_list else 0
        profitable = "✓" if window_pnl > 0 else "✗"

        print(f"{profitable} {start} → {end}   "
              f"{window_trades:>8} "
              f"{avg_pf:>8.2f} "
              f"₹{window_pnl:>10,.0f}")

        window_results.append({
            "window":   f"{start[:7]}",
            "trades":   window_trades,
            "pnl":      window_pnl,
            "pf":       avg_pf
        })

    df_w = pd.DataFrame(window_results)
    profitable_windows = (df_w["pnl"] > 0).sum()

    print(f"{'─'*60}")
    print(f"Profitable windows: {profitable_windows}/{len(windows)}")
    print(f"Avg PnL per window: ₹{df_w['pnl'].mean():,.0f}")
    print(f"Worst window PnL:   ₹{df_w['pnl'].min():,.0f}")
    print(f"Best window PnL:    ₹{df_w['pnl'].max():,.0f}")

    return df_w


if __name__ == "__main__":
    df_train, df_test = run_walkforward()
    stable = get_stable_symbols(df_train, df_test)

    print(f"\n{'═'*55}")
    print(f"STABLE SYMBOLS — profitable in BOTH periods")
    print(f"{'═'*55}")
    print(f"Count: {len(stable)}")
    print(stable)

    print(f"\n{'═'*55}")
    print(f"ROLLING WALK-FORWARD on stable universe")
    print(f"{'═'*55}")
    run_rolling_walkforward(symbols=stable)