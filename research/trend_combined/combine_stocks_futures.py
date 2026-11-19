"""Combine the stock efficiency-ratio system and the futures trend system into one account (Michael, 19 Nov 2026: "run the stock and futures systems together").

Usage: python combine_stocks_futures.py stock_equity_daily.csv futures_daily_pnl.csv OUT_DIR

Inputs (both already produced by committed scripts):
  stocks  = research/trend_following_stocks/results_equity/equity_daily.csv (er_stocks_equity.py, run 44?; volume-surge ranking, caps 200% and 100%, fixed $300,000, no compounding, no borrowing charge)
  futures = futures_daily_pnl.csv from futures_daily_export.py (original rule and candidate version 2, 0.15% and 0.25% of the account per ATR, whole contracts, short rates capped at 10 contracts)
Window: IN-SAMPLE ONLY. Stocks end 2021-08-06 (sealed years untouched), futures start 2007-12-31, so the combined window is 2008-01-02 to 2021-08-06. Futures after 2021-08-06 are cut at load.
2000 to 2007 has no futures data (stocks alone, shown for reference). Stock 2000-2002 is shown separately.
Combining: each system is run at its own size on its own $300,000; a split "a% stocks / (100-a)% futures" means a share a of the account follows the stock system and the rest the futures system,
so daily return = a x stock return + (1-a) x futures return (each return = daily dollars / $300,000). Rebalanced daily to the split (fixed-dollar accounting, same as both sources).
Measures (Michael): profit per year (percent of $300,000, no compounding), max drawdown from the running peak (percent of peak), profit divided by max drawdown, worst full calendar year; Sharpe as a side column.
Nothing is tuned: splits are a fixed menu declared here (100/0, 75/25, 50/50, 25/75, 0/100 and an equal-risk split from the whole-window volatilities, descriptive only).
"""
import sys
from pathlib import Path
import numpy as np
import pandas as pd

stock_path, fut_path, out_dir = sys.argv[1:4]
OUT = Path(out_dir); OUT.mkdir(parents=True, exist_ok=True)
pd.set_option("display.width", 250); pd.set_option("display.max_columns", 40); pd.set_option("display.max_rows", 500)
CAP = 300000.0
END = pd.Timestamp("2021-08-06")

st = pd.read_csv(stock_path, index_col=0); st.index = pd.to_datetime(st.index)
st = st[st.index <= END]
fu = pd.read_csv(fut_path); fu["date"] = pd.to_datetime(fu["date"]); fu = fu[fu["date"] <= END].set_index("date")
STK = {"stocks cap 200%": "200% | Rank by signal-day volume surge", "stocks cap 100%": "100% | Rank by signal-day volume surge"}
for v in STK.values():
    assert v in st.columns, v
spy = [c for c in st.columns if c.startswith("SPY")][0]
cal = st.index
stock_pnl = {k: st[c].diff().fillna(0.0) for k, c in STK.items()}
spy_pnl = st[spy].diff().fillna(0.0)
# futures profit onto the stock calendar: cumulate, take the value on each stock session (last futures day on or before it), difference
fut_pnl = {}
for c in fu.columns:
    cum = fu[c].cumsum().reindex(fu.index.union(cal)).ffill().fillna(0.0).reindex(cal)
    fut_pnl[c] = cum.diff().fillna(cum.iloc[0])
WIN_LO = fu.index[0]
print(f"stock sessions {cal[0].date()} to {cal[-1].date()}; futures series from {WIN_LO.date()}; combined window 2008-01-02 to {END.date()}")
w = cal >= pd.Timestamp("2008-01-02")


def stats(u, label_extra=None):
    """u: daily dollars on a $300,000 account, a pandas Series by date."""
    yrs = len(u) / 252.0
    eq = CAP + u.cumsum(); eq = pd.concat([pd.Series([CAP]), eq.reset_index(drop=True)]); pk = eq.cummax(); dd = ((eq - pk) / pk).min() * 100
    r = u / CAP; s = r.std()
    prof = u.sum() / CAP * 100 / yrs
    byyr = (u.groupby(u.index.year).sum() / CAP * 100)
    full = byyr[[y for y in byyr.index if y not in (2008,) or True]]
    worst = byyr[byyr.index <= 2020].min()
    return {"profit per year %": prof, "max drawdown %": dd, "profit / drawdown": prof / abs(dd) if dd < 0 else np.nan, "worst full calendar year %": worst, "Sharpe": r.mean() / s * np.sqrt(252) if s > 0 else np.nan}


def seg(u, lo, hi):
    m = (u.index >= pd.Timestamp(lo)) & (u.index <= pd.Timestamp(hi))
    return u[m]


# ---------------------------------------------------------------- 1. stocks alone, whole history and by early period (reference, no futures data)
rows = []
for k, u in stock_pnl.items():
    for lab, lo, hi in (("whole stock history 2000-01 to 2021-08", "2000-01-01", "2021-08-06"), ("2000 to 2002 (no futures data)", "2000-01-01", "2002-12-31"), ("2003 to 2007 (no futures data)", "2003-01-01", "2007-12-31"), ("overlap 2008-01 to 2021-08", "2008-01-02", "2021-08-06")):
        x = stats(seg(u, lo, hi)); x.update({"system": k, "period": lab}); rows.append(x)
ALONE = pd.DataFrame(rows)[["system", "period", "profit per year %", "max drawdown %", "profit / drawdown", "worst full calendar year %", "Sharpe"]]
print("\n==== 1. STOCKS ALONE (reference) ===="); print(ALONE.round(2).to_string(index=False))
ALONE.round(3).to_csv(OUT / "stocks_alone_periods.csv", index=False)

# ---------------------------------------------------------------- 2. futures alone and correlation
FW = {k: v[w] for k, v in fut_pnl.items()}
SW = {k: v[w] for k, v in stock_pnl.items()}
rows = []
for k, u in FW.items():
    x = stats(u); x.update({"system": k}); rows.append(x)
FALONE = pd.DataFrame(rows)[["system", "profit per year %", "max drawdown %", "profit / drawdown", "worst full calendar year %", "Sharpe"]]
print("\n==== 2. FUTURES ALONE, 2008-01 to 2021-08 ===="); print(FALONE.round(2).to_string(index=False))
FALONE.round(3).to_csv(OUT / "futures_alone_overlap.csv", index=False)


def corr_block(a, b, name):
    d = pd.DataFrame({"s": a / CAP, "f": b / CAP})
    out = {"stock vs futures": name}
    out["daily correlation"] = d.s.corr(d.f)
    wk = d.resample("W").sum(); mo = d.resample("ME").sum(); yr = d.resample("YE").sum()
    out["weekly correlation"] = wk.s.corr(wk.f); out["monthly correlation"] = mo.s.corr(mo.f); out["calendar-year correlation"] = yr.s.corr(yr.f)
    # on the stock system's worst 10% of months and best 10% of months
    q10, q90 = mo.s.quantile(0.10), mo.s.quantile(0.90)
    out["futures average in stock's worst 10% of months (% of account)"] = mo.f[mo.s <= q10].mean() * 100
    out["futures average in stock's best 10% of months (% of account)"] = mo.f[mo.s >= q90].mean() * 100
    out["futures average in all months (% of account)"] = mo.f.mean() * 100
    out["stock average in futures' worst 10% of months (% of account)"] = mo.s[mo.f <= mo.f.quantile(0.10)].mean() * 100
    return out


rows = [corr_block(SW[sk], FW[fk], f"{sk} | {fk}") for sk in SW for fk in FW]
CORR = pd.DataFrame(rows)
print("\n==== 3. CORRELATION (2008-01 to 2021-08) ===="); print(CORR.round(3).to_string(index=False))
CORR.round(4).to_csv(OUT / "correlation.csv", index=False)

# ---------------------------------------------------------------- 4. the stock system's three worst drawdowns: what did futures do in the same weeks
rows = []
for sk, u in SW.items():
    eq = CAP + u.cumsum(); pk = eq.cummax(); dd = (eq - pk) / pk
    used = []
    dd_work = dd.copy()
    for _ in range(3):
        t = dd_work.idxmin()
        if dd_work[t] >= -0.03: break
        p = eq[:t].idxmax()
        # end of recovery
        rec = eq[t:][eq[t:] >= eq[p]]
        endd = rec.index[0] if len(rec) else eq.index[-1]
        rows.append({"stock system": sk, "peak date": p.date(), "trough date": t.date(), "stock drawdown %": dd_work[t] * 100,
                     **{f"{fk}: futures % of account peak-to-trough": FW[fk][(FW[fk].index > p) & (FW[fk].index <= t)].sum() / CAP * 100 for fk in FW}})
        dd_work[(dd_work.index >= p) & (dd_work.index <= endd)] = 0
WORST = pd.DataFrame(rows)
print("\n==== 4. STOCK SYSTEM'S WORST DRAWDOWNS: futures profit between the same peak and trough dates ===="); print(WORST.round(2).to_string(index=False))
WORST.round(3).to_csv(OUT / "stock_worst_drawdowns_vs_futures.csv", index=False)

# ---------------------------------------------------------------- 5. allocation menu
SPLITS = [100, 75, 50, 25, 0]
rows = []
for sk in SW:
    for fk in FW:
        sv, fv = SW[sk], FW[fk]
        splits = [(f"{a}% stocks / {100 - a}% futures", a / 100.0) for a in SPLITS]
        eqw = (1 / sv.std()) / (1 / sv.std() + 1 / fv.std())
        splits.append((f"equal-risk split ({eqw * 100:.0f}% stocks / {100 - eqw * 100:.0f}% futures; whole-window volatilities, descriptive)", eqw))
        for lab, a in splits:
            u = a * sv + (1 - a) * fv
            x = stats(u); x.update({"stock version": sk, "futures version": fk, "split": lab}); rows.append(x)
ALLOC = pd.DataFrame(rows)[["stock version", "futures version", "split", "profit per year %", "max drawdown %", "profit / drawdown", "worst full calendar year %", "Sharpe"]]
print("\n==== 5. COMBINED ACCOUNT BY SPLIT, 2008-01 to 2021-08 ===="); print(ALLOC.round(2).to_string(index=False))
ALLOC.round(3).to_csv(OUT / "combined_by_split.csv", index=False)

# ---------------------------------------------------------------- 6. calendar years: stocks, futures, 50/50
rows = []
for sk in SW:
    for fk in FW:
        u50 = 0.5 * SW[sk] + 0.5 * FW[fk]
        yrs = sorted(set(SW[sk].index.year))
        for y in yrs:
            rows.append({"stock version": sk, "futures version": fk, "year": y if y != 2021 else "2021 (to 6 Aug)", "stocks %": SW[sk][SW[sk].index.year == y].sum() / CAP * 100,
                         "futures %": FW[fk][FW[fk].index.year == y].sum() / CAP * 100, "50/50 %": u50[u50.index.year == y].sum() / CAP * 100})
YR = pd.DataFrame(rows)
print("\n==== 6. YEAR BY YEAR (percent of $300,000; 2008 is the crisis year) ===="); print(YR.round(1).to_string(index=False))
YR.round(2).to_csv(OUT / "year_by_year.csv", index=False)

# ---------------------------------------------------------------- 7. start years: combined account begun on 1 January of each year (stocks cap 200% x futures version 2 0.15%), 50/50 vs each alone
rows = []
sk, fk = "stocks cap 200%", "candidate version 2 | 0.15% per ATR"
for y in range(2008, 2020):
    lo = pd.Timestamp(f"{y}-01-01")
    d = {"start year": y}
    for lab, a in (("stocks only", 1.0), ("50/50", 0.5), ("futures only", 0.0)):
        u = seg(a * SW[sk] + (1 - a) * FW[fk], lo, END); x = stats(u)
        d[f"{lab}: profit/yr %"] = x["profit per year %"]; d[f"{lab}: drawdown %"] = x["max drawdown %"]; d[f"{lab}: profit/drawdown"] = x["profit / drawdown"]
    rows.append(d)
SY = pd.DataFrame(rows)
print(f"\n==== 7. START YEARS ({sk} with {fk}) ===="); print(SY.round(2).to_string(index=False))
SY.round(3).to_csv(OUT / "start_years_example.csv", index=False)
better = (SY["50/50: profit/drawdown"] > SY["stocks only: profit/drawdown"]).sum(); print(f"50/50 beats stocks-only on profit/drawdown in {better} of {len(SY)} start years")
