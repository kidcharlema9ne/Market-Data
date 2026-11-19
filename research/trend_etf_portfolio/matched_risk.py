"""Matched-risk test (Michael, 19 Nov 2026), IN-SAMPLE ONLY (prices cut at 2021-08-06 before any calculation).
Question: does a six-fund mix beat simply holding more Treasury bills in the SPY/QQQ system? Same 4% band rule, same window as etf_portfolio_timing.py.
Two-fund family: share w in the system (half SPY, half QQQ), 1-w in Treasury bills, annual rebalance. For each mix, find w with the SAME worst drawdown (compare profit per year) and w with the SAME profit per year (compare worst drawdown).
Usage: python matched_risk.py PRICES OUT_DIR TBILL_CSV"""
import sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).parent))
from etf_portfolio_timing import load, SPLIT, FUNDS, cash_daily, sleeve, portfolio, metrics, first_ok

px = load(sys.argv[1]); px = px[px.index <= SPLIT]; out = Path(sys.argv[2]); out.mkdir(parents=True, exist_ok=True)
tb = pd.read_csv(sys.argv[3], parse_dates=["date"]).set_index("date")["rate"]; cash = cash_daily(px.index, tb)
start = max(first_ok(px, f) for f in FUNDS); print(f"window {start.date()} to {px.index[-1].date()}")
band = {f: sleeve(px, cash, f, "band")[0] for f in FUNDS}; hold = {f: sleeve(px, cash, f, "hold")[0] for f in FUNDS}
R = pd.DataFrame(band); R["bills"] = cash; R = R.loc[start:]
inv = {f: 1 / hold[f].loc[start:].std() for f in FUNDS}; t = sum(inv.values())
mixes = {
    "Equal split of six funds": {f: 1 / 6 for f in FUNDS},
    "Stock-heavy": {"SPY": .25, "QQQ": .10, "VEA": .15, "VWO": .05, "IAU": .10, "BIV": .25, "bills": .10},
    "Balanced": {"SPY": .20, "QQQ": .05, "VEA": .10, "VWO": .05, "IAU": .10, "BIV": .30, "bills": .20},
    "Equal risk": {f: inv[f] / t for f in FUNDS},
}


def stats(w):
    m, _ = metrics(portfolio(R, w).loc[start:]); return m["profit per year %"], m["max drawdown %"]


grid = np.round(np.arange(0.05, 1.0001, 0.01), 2)
fam = pd.DataFrame([(w, *stats({"SPY": w / 2, "QQQ": w / 2, "bills": 1 - w})) for w in grid], columns=["share in SPY/QQQ", "profit per year %", "max drawdown %"])
fam.to_csv(out / "two_fund_dial.csv", index=False)
chk = fam[fam["share in SPY/QQQ"] == 0.75].iloc[0]; print(f"check: SPY 37.5 / QQQ 37.5 / bills 25 -> profit {chk['profit per year %']}%, max drawdown {chk['max drawdown %']}% (earlier run: 7.70 / -15.4 with a 37.5/37.5 split)")
rows = []
for n, w in mixes.items():
    p, d = stats(w)
    a = fam.iloc[(fam["max drawdown %"] - d).abs().argmin()]; b = fam.iloc[(fam["profit per year %"] - p).abs().argmin()]
    rows.append({"mix": n, "mix profit/yr %": p, "mix max drawdown %": d,
                 "same drawdown: share in SPY/QQQ %": int(a["share in SPY/QQQ"] * 100), "SPY/QQQ profit/yr %": a["profit per year %"], "SPY/QQQ max drawdown %": a["max drawdown %"], "profit gap (mix minus SPY/QQQ)": round(p - a["profit per year %"], 2),
                 "same profit: share in SPY/QQQ %": int(b["share in SPY/QQQ"] * 100), "SPY/QQQ profit/yr % (matched)": b["profit per year %"], "SPY/QQQ max drawdown % (matched)": b["max drawdown %"], "drawdown gap (mix minus SPY/QQQ)": round(d - b["max drawdown %"], 1)})
M = pd.DataFrame(rows); M.to_csv(out / "matched_risk.csv", index=False)
pd.set_option("display.width", 250, "display.max_columns", 30, "display.max_colwidth", 40)
print("\nSAME WORST DRAWDOWN: positive profit gap = mix is better"); print(M[["mix", "mix profit/yr %", "mix max drawdown %", "same drawdown: share in SPY/QQQ %", "SPY/QQQ profit/yr %", "SPY/QQQ max drawdown %", "profit gap (mix minus SPY/QQQ)"]].to_string(index=False))
print("\nSAME PROFIT PER YEAR: negative drawdown gap = mix has the deeper drawdown (worse); positive = shallower (better)"); print(M[["mix", "mix profit/yr %", "mix max drawdown %", "same profit: share in SPY/QQQ %", "SPY/QQQ profit/yr % (matched)", "SPY/QQQ max drawdown % (matched)", "drawdown gap (mix minus SPY/QQQ)"]].to_string(index=False))
print("\nTwo-fund dial (every 10 points):"); print(fam[(fam["share in SPY/QQQ"] * 100).round().astype(int) % 10 == 0].to_string(index=False))
