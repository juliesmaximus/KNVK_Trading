# main.py — run full universe backtest

from data.downloader import load_symbol, load_vix
from backtest.signals import prepare_features
from backtest.engine import Backtester
import pandas as pd
from config import ACTIVE_SYMBOLS, BREAKOUT_SYMBOLS, STABLE_SYMBOLS

# change loop to use stable symbols


def run_full_backtest(
    real_capital:   float = 100_000,
    leverage:       float = 5.0
):
    trading_capital = real_capital * leverage   # ₹5,00,000
    vix         = load_vix()
    all_results = []
    failed      = []

    print(f"Real capital:    ₹{real_capital:,.0f}")
    print(f"Leverage:        {leverage}×")
    print(f"Trading capital: ₹{trading_capital:,.0f}")
    print(f"Symbols:         {len(ACTIVE_SYMBOLS)}\n")

    for sym in STABLE_SYMBOLS:
        try:
            df = load_symbol(sym)
            if df.empty:
                failed.append(sym)
                continue

            out = prepare_features(df, vix, include_breakout=False)
            bt  = Backtester(capital=trading_capital)
            bt.run(sym, out)
            r   = bt.results()

            if "error" in r:
                failed.append(sym)
                continue

            all_results.append({
                "symbol":        sym,
                "trades":        r["total_trades"],
                "win_rate":      r["win_rate"],
                "net_pnl":       r["net_pnl"],
                "profit_factor": r["profit_factor"],
                "max_drawdown":  r["max_drawdown"],
                "total_charges": r["total_charges"],
            })
            print(f"✓ {sym:<20} trades={r['total_trades']:<4} "
                  f"pnl=₹{r['net_pnl']:<10} pf={r['profit_factor']}")

        except Exception as e:
            print(f"✗ {sym:<20} ERROR: {e}")
            failed.append(sym)

    if not all_results:
        print("No results generated.")
        return

    df_r = pd.DataFrame(all_results)
    total_pnl      = df_r["net_pnl"].sum()
    avg_pnl_sym    = df_r["net_pnl"].mean()
    pnl_on_real    = (total_pnl / (real_capital * len(all_results))) * 100

    print(f"\n{'═'*55}")
    print(f"PORTFOLIO BACKTEST — ₹{real_capital:,.0f} + {leverage}× LEVERAGE")
    print(f"{'═'*55}")
    print(f"Symbols run:           {len(all_results)}")
    print(f"Total trades:          {df_r['trades'].sum()}")
    print(f"Avg win rate:          {df_r['win_rate'].mean():.1f}%")
    print(f"Total net PnL:         ₹{total_pnl:,.2f}")
    print(f"Avg PnL per symbol:    ₹{avg_pnl_sym:,.2f}")
    print(f"Avg profit factor:     {df_r['profit_factor'].mean():.2f}")
    print(f"Total charges paid:    ₹{df_r['total_charges'].sum():,.2f}")
    print(f"Worst drawdown:        {df_r['max_drawdown'].min():.1f}%")

    broken   = df_r[df_r["profit_factor"] < 0.5]["symbol"].tolist()
    marginal = df_r[(df_r["profit_factor"] >= 0.5) &
                    (df_r["profit_factor"] < 0.8)]["symbol"].tolist()
    strong   = df_r[df_r["profit_factor"] >= 1.5]["symbol"].tolist()

    print(f"\nStructurally broken (pf < 0.5):  {broken}")
    print(f"Marginal (pf 0.5-0.8):            {marginal}")
    print(f"Strong performers (pf > 1.5):     {strong}")

    print(f"\nTop 5 by PnL:")
    print(df_r.nlargest(5, "net_pnl")[
        ["symbol", "trades", "win_rate", "net_pnl", "profit_factor"]
    ].to_string(index=False))

    print(f"\nBottom 5 by PnL:")
    print(df_r.nsmallest(5, "net_pnl")[
        ["symbol", "trades", "win_rate", "net_pnl", "profit_factor"]
    ].to_string(index=False))

    return df_r


if __name__ == "__main__":
    run_full_backtest(real_capital=100_000, leverage=5.0)