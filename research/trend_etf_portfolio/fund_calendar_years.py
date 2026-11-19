"""Calendar-year PRICE returns (no dividends) of SPY, QQQ, VEA, VWO, IAU, BIV with stand-ins chained in front, IN-SAMPLE ONLY (prices cut at 2021-08-06; 2021 is a partial year).
Usage: python fund_calendar_years.py PRICES OUT_DIR"""
import sys
from pathlib import Path
import pandas as pd
sys.path.insert(0, str(Path(__file__).parent))
from etf_portfolio_timing import load, SPLIT, FUNDS

px = load(sys.argv[1]); px = px[px.index <= SPLIT][FUNDS]; out = Path(sys.argv[2]); out.mkdir(parents=True, exist_ok=True)
ye = px.groupby(px.index.year).last(); first = {f: px[f].dropna().index[0] for f in FUNDS}
yr = (ye / ye.shift(1) - 1) * 100
for f in FUNDS:  # a fund's first calendar year is partial: blank it
    yr.loc[yr.index <= first[f].year, f] = float("nan")
yr = yr.round(1); yr.index.name = "year"; yr.to_csv(out / "fund_calendar_years.csv")
pd.set_option("display.width", 200)
print("Calendar-year price return %, 2021 only through 6 Aug (blank = fund or stand-in not yet trading a full year)"); print(yr.to_string())
for name, a in (("VEA", "developed"), ("VWO", "emerging")):
    for b in ("SPY", "QQQ"):
        d = yr[[name, b]].dropna(); w = d[d[name] > d[b]]
        print(f"\n{name} ({a}) beat {b} in {len(w)} of {len(d)} years: {', '.join(str(int(y)) for y in w.index)}")
