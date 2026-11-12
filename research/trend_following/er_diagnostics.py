"""Why does fed funds (ZQ) have so many trades? Per-market diagnostics of the 20-session close-based efficiency ratio.

Efficiency ratio (Kaufman, same as trend_er_optimize.py): |close now - close 20 sessions ago| / sum of the 20 daily |close changes|.
Development years only (2007-12-31 to 2021-08-06); sealed years are cut at load.
Usage: python er_diagnostics.py futures_prices.parquet trend_universe.csv portfolio_51_list.csv out_dir
"""
import sys
import numpy as np
import pandas as pd

prices_path, uni_path, list_path, out_dir = sys.argv[1:5]
DEV_START, DEV_END = pd.Timestamp("2007-12-31"), pd.Timestamp("2021-08-06")
W = 20
PATH_OVERRIDE = {"SO3": "L"}

px = pd.read_parquet(prices_path)
px["file_date"] = pd.to_datetime(px["file_date"])
px = px[(px["file_date"] >= DEV_START) & (px["file_date"] <= DEV_END)].copy()
uni = pd.read_csv(uni_path)
fam = dict(zip(uni["price_symbol"], uni["family"]))
mult = dict(zip(uni["price_symbol"], uni["multiplier"]))
lst = pd.read_csv(list_path)
rows_by_sym = px.groupby("symbol").size().to_dict()
mapping = {}
for sym in lst["price_symbol"]:
    f = fam.get(sym)
    cands = [s for s, ff in fam.items() if ff == f and s in rows_by_sym]
    best = max(cands, key=lambda s: rows_by_sym[s]) if cands else None
    own = rows_by_sym.get(sym, 0)
    if best is None:
        mapping[sym] = None
    elif own >= 0.7 * rows_by_sym[best]:
        mapping[sym] = sym
    else:
        mapping[sym] = best
    ov = PATH_OVERRIDE.get(sym)
    if ov and rows_by_sym.get(ov, 0) >= 150 and own < 0.7 * rows_by_sym[ov]:
        mapping[sym] = ov

rows, yearly = [], []
for sym, src in mapping.items():
    if src is None:
        continue
    g = px[px["symbol"] == src].sort_values("file_date").drop_duplicates("file_date").dropna(subset=["close", "high", "low"])
    if len(g) < 150:
        continue
    c = g["close"].to_numpy(float).copy()
    h, l = g["high"].to_numpy(float), g["low"].to_numpy(float)
    d = np.diff(c, prepend=np.nan)
    pc = np.r_[np.nan, c[:-1]]
    tr = np.maximum.reduce([h - l, np.abs(h - pc), np.abs(l - pc)])
    atr = pd.Series(tr).rolling(W).mean().to_numpy()
    cs = pd.Series(c)
    path = pd.Series(np.abs(d)).rolling(W).sum()
    er = ((cs - cs.shift(W)).abs() / path).to_numpy()
    ad = np.abs(d[1:])
    nz = ad[ad > 1e-9]
    step = float(np.percentile(nz, 5)) if len(nz) else np.nan     # smallest typical nonzero daily move = tick proxy
    ok = ~np.isnan(er)
    rows.append(dict(symbol=sym, price_path_from=src, sessions=len(g),
                     share_er_ge_060=float((er[ok] >= 0.60).mean()), share_er_ge_055=float((er[ok] >= 0.55).mean()),
                     median_er=float(np.median(er[ok])),
                     share_days_zero_change=float((ad <= 1e-9).mean()),
                     tick_proxy_points=step,
                     median_atr_in_ticks=float(np.nanmedian(atr) / step) if step == step and step > 0 else np.nan,
                     median_abs_daily_change_in_ticks=float(np.median(ad) / step) if step == step and step > 0 else np.nan))
    if sym in ("ZQ", "SR1", "SR3", "ER", "SO3", "ZN", "ES", "CL", "GC"):
        yr = g["file_date"].dt.year.to_numpy()
        for y in sorted(set(yr)):
            s = (yr == y) & (~np.isnan(er))
            if s.sum() < 20:
                continue
            idx = np.where(yr == y)[0]
            net = c[idx[-1]] - c[idx[0]]
            yearly.append(dict(symbol=sym, year=int(y), sessions=int(len(idx)), share_er_ge_060=float((er[s] >= 0.60).mean()),
                               median_er=float(np.median(er[s])), net_close_change_points=float(net),
                               mean_daily_change_in_atr=float(np.nanmean(d[idx] / atr[idx])),
                               share_days_zero_change=float((np.abs(d[idx]) <= 1e-9).mean()),
                               median_atr_points=float(np.nanmedian(atr[idx]))))

res = pd.DataFrame(rows).sort_values("share_er_ge_060", ascending=False)
yr = pd.DataFrame(yearly)
res.round(4).to_csv(f"{out_dir}/er_share_by_market.csv", index=False)
yr.round(5).to_csv(f"{out_dir}/er_by_year_selected_markets.csv", index=False)
pd.set_option("display.width", 250)
print("=== share of sessions with efficiency ratio >= 0.60, by market (development years) ===")
print(res.round(3).to_string(index=False))
print("\n=== selected markets by year ===")
print(yr.round(4).to_string(index=False))
