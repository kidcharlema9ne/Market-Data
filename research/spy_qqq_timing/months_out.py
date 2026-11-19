"""Months out of the market, by year, for the SPY/QQQ 200-day 4% band system (Michael, 19 Nov 2026). No rule change: same band signal and next-close timing as spy_qqq_timing.py.
Out of a fund = its band signal (two sessions earlier, as in the headline timing) says out, so that fund's share sits in Treasury bills. Months out = sum over calendar months of the share of that month's sessions spent out.
A month is listed as out when the fund was out for at least half of that month's sessions. 'Both out' = SPY and QQQ out on the same sessions (the whole system share in bills).
Usage: python months_out.py PRICES OUT_DIR"""
import sys, calendar
from pathlib import Path
import pandas as pd
sys.path.insert(0, str(Path(__file__).parent))
from spy_qqq_timing import load, signal, START

px = load(sys.argv[1]); out = Path(sys.argv[2]); out.mkdir(parents=True, exist_ok=True)
pos = {f: signal(px[f], "band").shift(2).fillna(False).astype(bool) for f in ("spy", "qqq")}
o = pd.DataFrame({"SPY": ~pos["spy"], "QQQ": ~pos["qqq"]}).loc[START:]; o["Both"] = o["SPY"] & o["QQQ"]
frac = o.astype(float).groupby([o.index.year, o.index.month]).mean()  # share of each month's sessions out
rows = []
for y in sorted(set(i[0] for i in frac.index)):
    f = frac.loc[y]; r = {"year": y}
    for c in ("SPY", "QQQ", "Both"):
        r[f"{c} months out"] = round(float(f[c].sum()), 1)
        r[f"{c} months listed (half or more of the month out)"] = ", ".join(calendar.month_abbr[m] for m in f.index if f.loc[m, c] >= 0.5) or "none"
    r["months of data in year"] = len(f); rows.append(r)
R = pd.DataFrame(rows); R.to_csv(out / "months_out_by_year.csv", index=False)
tot = frac.sum(); print(f"data {px.index[0].date()} to {px.index[-1].date()}; counting from {START.date()}; whole period: SPY out {tot['SPY']:.0f} of {len(frac)} months, QQQ out {tot['QQQ']:.0f}, both out {tot['Both']:.0f}")
pd.set_option("display.width", 250, "display.max_colwidth", 80, "display.max_rows", 100)
print(R[["year", "SPY months out", "QQQ months out", "Both months out", "months of data in year"]].to_string(index=False))
for c in ("SPY", "QQQ", "Both"):
    print(f"\n{c}: months listed as out (at least half the month)")
    for _, r in R.iterrows(): print(f"  {int(r['year'])}: {r[f'{c} months listed (half or more of the month out)']}")
