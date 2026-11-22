"""Decide what the daily run still has to do, so a timer that fires every 15 minutes costs almost nothing once the day is done.

Writes etf_needed=true/false to $GITHUB_OUTPUT: true when any live ETF in prices/etf_recent.csv.gz is behind the expected trading day.
(The futures check lives inside daily_update.py because it needs the table in R2.)
"""
import os
import sys
from datetime import timedelta

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from trading_days import NYSE_HOLIDAYS, expected_day, now_et  # noqa: E402
from fetch_etf_prices import ETFS  # noqa: E402

expected = expected_day(now_et(), NYSE_HOLIDAYS)
try:
    newest = pd.read_csv("prices/etf_recent.csv.gz").groupby("symbol")["file_date"].max()
except Exception:
    newest = pd.Series(dtype=str)
live = {s for s in ETFS if s not in newest.index or newest[s] >= (expected - timedelta(days=10)).isoformat()}
behind = sorted(s for s in live if s not in newest.index or newest[s] < expected.isoformat())
print(f"expected trading day {expected}; ETFs behind: {behind or 'none'}")
gh = os.environ.get("GITHUB_OUTPUT")
if gh:
    open(gh, "a").write(f"etf_needed={'true' if behind else 'false'}\n")
