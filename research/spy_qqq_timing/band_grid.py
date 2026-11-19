"""SPY/QQQ 200-day exit rules compared: buy and hold, plain 200-day, and 2%, 3%, 4% bands (Michael, 19 Nov 2026).
NOT A CLEAN SEALED TEST: the sealed years (after 2021-08-06) were already looked at once for the plain and 4% rules (Entry 170). The 2% and 3% bands are new here and are evaluated on years already seen, so any choice made from the sealed column is selection on spent data. In-sample is shown beside it.
Same engine as spy_qqq_timing.py: each fund is its own half of the invested share, never rebalanced between funds; out = Treasury bill interest; signal at the close, trade at the NEXT session's close; price only, no costs or taxes.
Band b: enter when close > 200-day average x (1+b), leave when close < average x (1-b), otherwise keep the state. Plain = in while close > average.
Usage: python band_grid.py PRICES OUT_DIR TBILL_CSV"""
import sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).parent))
from spy_qqq_timing import load, band_state, signal, cash_daily, sleeve_returns, combine, metrics, START, SPLIT

px = load(sys.argv[1]); out = Path(sys.argv[2]); out.mkdir(parents=True, exist_ok=True)
tb = pd.read_csv(sys.argv[3], parse_dates=["date"]).set_index("date")["rate"]; cash = cash_daily(px.index, tb)
rules = {"buy and hold": lambda p: signal(p, "hold"), "plain 200-day": lambda p: signal(p, "plain"),
         "2% band": lambda p: band_state(p, 200, 0.02), "3% band": lambda p: band_state(p, 200, 0.03), "4% band": lambda p: band_state(p, 200, 0.04)}
periods = {"in-sample (Oct 2000 to Aug 2021)": (START, SPLIT), "sealed years, already seen (Aug 2021 to Nov 2026)": (SPLIT + pd.Timedelta(days=1), px.index[-1]), "whole (Oct 2000 to Nov 2026)": (START, px.index[-1])}
rows = []; yearly = []
for rn, fn in rules.items():
    rets, poss = {}, {}
    for f in ("spy", "qqq"):
        rets[f], poss[f] = sleeve_returns(px, fn(px[f]), cash, "next_close", f)
    base = combine(rets["spy"], rets["qqq"]); inv = (poss["spy"].astype(float) + poss["qqq"].astype(float)) / 2
    for w in (0.75, 0.5):
        r = w * base + (1 - w) * cash
        for pn, (a, b) in periods.items():
            m, yr = metrics(r.loc[a:b], inv.loc[a:b]); e = sum(int((poss[f].astype(int).diff() == 1).loc[a:b].sum()) for f in ("spy", "qqq"))
            rows.append({"rule": rn, "invested": int(w * 100), "period": pn, **m, "entries per year (both funds)": round(e / m["years"], 1) if rn != "buy and hold" else 0})
            if w == 0.75 and pn.startswith("sealed"):
                for y, v in yr.items(): yearly.append({"rule": rn, "year": int(y), "return %": round(v * 100, 1)})
R = pd.DataFrame(rows); R.to_csv(out / "band_grid.csv", index=False); Y = pd.DataFrame(yearly); Y.to_csv(out / "band_grid_sealed_years.csv", index=False)
pd.set_option("display.width", 250, "display.max_columns", 30)
key = ["rule", "years", "growth per year %", "average yearly return %", "best year %", "worst year %", "worst month %", "worst drawdown %", "growth per year / worst drawdown", "Sharpe (0% cash)", "time invested %", "entries per year (both funds)"]
for w in (75, 50):
    for pn in periods:
        print(f"\n=== {w}% invested | {pn} ==="); print(R[(R.invested == w) & (R.period == pn)][key].to_string(index=False))
print("\n=== calendar years %, 75% invested, sealed window (2021 from 9 Aug, 2026 to 6 Nov) ==="); print(Y.pivot(index="year", columns="rule", values="return %")[list(rules)].to_string())
