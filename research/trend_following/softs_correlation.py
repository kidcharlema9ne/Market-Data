"""Correlation of London cocoa (C) and Robusta coffee (RM) with the US-traded markets in the trend universe.

Usage: python softs_correlation.py futures_prices.parquet futures_data/trend_universe.csv OUT_DIR

Descriptive only (no strategy, no tuning). Log returns of the ratio back-adjusted closes.
London closes before New York, so daily returns are partly out of step; weekly returns (Friday to Friday) remove most of that.
London cocoa is priced in pounds; 'C in dollars' adds the daily pound/dollar return (B6) to the cocoa return.
"""
import sys
import numpy as np
import pandas as pd

prices_path, universe_path, out_dir = sys.argv[1:4]
px = pd.read_parquet(prices_path)
px["file_date"] = pd.to_datetime(px["file_date"])
close = px.pivot_table(index="file_date", columns="symbol", values="close", aggfunc="last").sort_index()
uni = pd.read_csv(universe_path)
us48 = [s for s in uni[uni.in_original_48 == "yes"].price_symbol if s in close.columns]

ret = np.log(close).diff()
ret["C_usd"] = ret["C"] + ret["B6"]  # pound return plus pound/dollar return = cocoa return in dollars
wk = ret.resample("W-FRI").sum(min_count=1)
# weeks with fewer than 3 sessions are dropped by requiring the count
cnt = ret["ES"].resample("W-FRI").count()
wk = wk[cnt >= 3]

periods = {
    "development years (2007-12-31 to 2021-08-06)": ("2007-12-31", "2021-08-06"),
    "recent years (2021-11-08 to 2026-11-06)": ("2021-11-08", "2026-11-06"),
    "all years": ("2007-12-31", "2026-11-06"),
}


def corr(df, a, b, lo, hi):
    d = df.loc[lo:hi, [a, b]].dropna()
    return d[a].corr(d[b]), len(d)


pairs = [("C", "CC", "London cocoa vs New York cocoa (London in pounds)"),
         ("C_usd", "CC", "London cocoa converted to dollars vs New York cocoa"),
         ("RM", "KC", "Robusta vs arabica coffee (New York)"),
         ("RM", "CC", "Robusta vs New York cocoa"),
         ("C", "RM", "London cocoa vs Robusta"),
         ("C", "B6", "London cocoa (pounds) vs British pound"),
         ("RM", "SB", "Robusta vs New York sugar")]
rows = []
for pname, (lo, hi) in periods.items():
    for a, b, label in pairs:
        d, nd = corr(ret, a, b, lo, hi)
        w, nw = corr(wk, a, b, lo, hi)
        rows.append({"period": pname, "pair": label, "daily_corr": d, "daily_n": nd, "weekly_corr": w, "weekly_n": nw})
res = pd.DataFrame(rows)
res.to_csv(f"{out_dir}/softs_correlation_pairs.csv", index=False)

# strongest and weakest links to the other US markets (weekly, all years)
other = []
for a in ["C", "RM"]:
    for b in us48:
        w, nw = corr(wk, a, b, "2007-12-31", "2026-11-06")
        other.append({"foreign_symbol": a, "us_symbol": b, "weekly_corr_all_years": w, "weeks": nw})
other = pd.DataFrame(other).dropna()
other.to_csv(f"{out_dir}/softs_correlation_vs_all_us48.csv", index=False)

pd.set_option("display.width", 220, "display.max_rows", 200, "display.max_colwidth", 60)
print(res.round(3).to_string(index=False))
for a in ["C", "RM"]:
    o = other[other.foreign_symbol == a].sort_values("weekly_corr_all_years", ascending=False)
    print(f"\n{a}: top 6 and bottom 3 weekly correlations with your original 48 (all years)")
    print(o.head(6).round(3).to_string(index=False))
    print(o.tail(3).round(3).to_string(index=False))
    print("median absolute weekly correlation with the 48:", round(o.weekly_corr_all_years.abs().median(), 3))
for s in ["C", "RM", "CC", "KC"]:
    d = close[s].dropna()
    print(s, "first", d.index[0].date(), "last", d.index[-1].date(), "days", len(d))
