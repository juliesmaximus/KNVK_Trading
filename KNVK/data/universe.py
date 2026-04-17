# data/universe.py — verify symbols against what NSE can actually serve

import sys
sys.path.append(str(__import__('pathlib').Path(__file__).parent.parent))

from openchart import NSEData
from config import NIFTY_100_SYMBOLS
import pandas as pd

def get_verified_universe() -> list[str]:
    """
    Cross-check our symbol list against NSE live.
    Returns only symbols that OpenChart can fetch.
    """
    nse = NSEData()
    verified = []
    failed  = []

    print(f"Verifying {len(NIFTY_100_SYMBOLS)} symbols against NSE...")

    for sym in NIFTY_100_SYMBOLS:
        nse_sym = f"{sym}-EQ"
        result  = nse.search(sym, "EQ")
        if result is not None and len(result) > 0:
            verified.append(sym)
        else:
            failed.append(sym)

    print(f"\n✓ Verified : {len(verified)}")
    print(f"✗ Failed   : {len(failed)}")
    if failed:
        print(f"  Failed symbols: {failed}")

    return verified


if __name__ == "__main__":
    universe = get_verified_universe()
    print(f"\nFinal universe: {len(universe)} stocks")