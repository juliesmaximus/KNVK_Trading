# morning_test.py — single command to run everything fresh each morning

import subprocess
import sys
from datetime import datetime

print(f"\n{'═'*55}")
print(f"KNVK MORNING TEST — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
print(f"{'═'*55}\n")

steps = [
    ("Full backtest",      ["python3", "main.py"]),
    ("Walk-forward test",  ["python3", "backtest/walkforward.py"]),
]

for name, cmd in steps:
    print(f"\n▶ Running: {name}")
    print(f"{'─'*40}")
    result = subprocess.run(cmd, capture_output=False, text=True)
    if result.returncode != 0:
        print(f"✗ {name} failed")
        sys.exit(1)
    print(f"✓ {name} complete")

print(f"\n{'═'*55}")
print(f"ALL TESTS COMPLETE")
print(f"Check walkforward_results.csv for detailed OOS results")
print(f"{'═'*55}\n")