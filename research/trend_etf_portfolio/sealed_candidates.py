"""SEALED-YEARS LOOK, ONE TIME (Michael, 19 Nov 2026). Three candidates frozen BEFORE this run; nothing is tuned on the sealed years (after 2021-08-06).
Frozen candidates (4% band rule, 200-day average, next-close trades, Treasury bill interest when out, annual rebalance, price only, no costs/taxes):
  (1) SPY/QQQ 75%: SPY 37.5, QQQ 37.5, bills 25 (Michael's current system)
  (2) Stock-heavy: SPY 25, QQQ 10, VEA 15, VWO 5, gold (IAU) 10, BIV 25, bills 10
  (3) SPY/QQQ 50%: SPY 25, QQQ 25, bills 50 (the in-sample dial setting that matched stock-heavy's profit and drawdown)
Buy and hold of the same weights is shown for reference only. Other allocations from the in-sample study are NOT reported here.
Usage: python sealed_candidates.py PRICES OUT_DIR TBILL_CSV"""
import sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).parent))
from etf_portfolio_timing import load, SPLIT, FUNDS, cash_daily, sleeve, portfolio, metrics, first_ok

px = load(sys.argv[1]); out = Path(sys.argv[2]); out.mkdir(parents=True, exist_ok=True)
tb = pd.read_csv(sys.argv[3], parse_dates=["date"]).set_index("date")["rate"]; cash = cash_daily(px.index, tb)
start = max(first_ok(px, f) for f in FUNDS); end = px.index[-1]; s0 = SPLIT + pd.Timedelta(days=1)
print(f"data to {end.date()}; common start {start.date()}; sealed window {s0.date()} to {end.date()} (2021 and 2026 are partial years; Treasury bill rate after Oct 2026 carried forward)")
cands = {"SPY/QQQ 75% (current)": {"SPY": .375, "QQQ": .375, "bills": .25},
         "Stock-heavy": {"SPY": .25, "QQQ": .10, "VEA": .15, "VWO": .05, "IAU": .10, "BIV": .25, "bills": .10},
         "SPY/QQQ 50%": {"SPY": .25, "QQQ": .25, "bills": .50}}
rows = []; yearly = []; curves = {}
for rn, rk in (("200-day with 4% band", "band"), ("buy and hold", "hold")):
    S = {f: sleeve(px, cash, f, rk) for f in FUNDS}; R = pd.DataFrame({f: S[f][0] for f in FUNDS}); R["bills"] = cash
    for n, w in cands.items():
        r = portfolio(R, w); pos = pd.DataFrame({f: S[f][1] for f in FUNDS})
        curves[f"{n} | {rn}"] = (1 + r.loc[s0:]).cumprod() * 500000
        for pn, (a, b) in {"sealed (Aug 2021 to end)": (s0, end), "whole (2005 to end)": (start, end)}.items():
            m, yr = metrics(r.loc[a:b]); ent = sum(int((pos[f].astype(int).diff() == 1).loc[a:b].sum()) for f in FUNDS if w.get(f, 0) > 0)
            rows.append({"candidate": n, "rule": rn, "period": pn, **m, "entries per year": round(ent / m["years"], 1) if rk == "band" else 0})
            if pn.startswith("sealed"):
                for y, v in yr.items(): yearly.append({"candidate": n, "rule": rn, "year": int(y), "return %": round(v * 100, 1)})
P = pd.DataFrame(rows); Y = pd.DataFrame(yearly); P.to_csv(out / "sealed_candidates.csv", index=False); Y.to_csv(out / "sealed_candidates_yearly.csv", index=False)
pd.DataFrame(curves).round(0).to_csv(out / "sealed_equity_curves_500k.csv")
pd.set_option("display.width", 250, "display.max_columns", 30)
for pn in P.period.unique():
    print(f"\n=== {pn} ==="); print(P[P.period == pn].drop(columns="period").to_string(index=False))
for rn in ("200-day with 4% band", "buy and hold"):
    print(f"\n=== calendar years %, sealed window, {rn} ==="); print(Y[Y.rule == rn].pivot(index="year", columns="candidate", values="return %").to_string())
