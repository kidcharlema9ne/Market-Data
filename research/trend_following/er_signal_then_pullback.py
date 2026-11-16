"""Trend signal first, pullback after it, then a time exit or a trailing stop. 48 COT markets, DEVELOPMENT YEARS ONLY.

Usage: python er_signal_then_pullback.py futures_prices.parquet report_universe_48_markets.csv OUT_DIR

SEALED YEARS: prices after 2021-08-06 are removed the moment the file is read (development window 2007-12-31 to 2021-08-06). Nothing sealed is used.

THE SEQUENCE (Michael, 16 Nov 2026: "the trend signal fires, then the pullback comes after it")
1. SIGNAL: the efficiency ratio qualifies (close-based). Pooled trend = any of: 5-session ratio at least 0.60, 10-session at least 0.45, 20-session at least 0.50 (directions added;
   ties skipped). Also run alone: 10-session at least 0.45; 20-session at least 0.50. Only the FIRST day of a qualifying run (a market newly qualifying in a direction) starts a watch.
2. WATCH: from the signal day on, track the best price reached since the signal (highest high for longs, lowest low for shorts; the signal day's own extreme counts). The watch ends
   after N sessions (10, 20 or 40) or when an entry is taken, whichever comes first.
3. PULLBACK: on any close AFTER the signal day, the pullback is how far the close sits from that best price, in ATR (20-day ATR on that day). The first close that is at least X ATR back
   (X = 0.5, 1, 1.5, 2, 2.5, 3) triggers an entry at the NEXT session's open, in the signal's direction. One entry per watch.
4. EXITS, all with a 1 ATR initial stop from the entry price (stop checked before anything else inside a bar; a gap through it fills at the open; cost 0.05 ATR a side):
   - time exit at the close of session 5, 10, 20 (entry session counts as 1);
   - trailing stop M ATR below the best close since entry (M = 2, 3, 4; recomputed with the current ATR, only ever moving in the trade's favour; the 1 ATR initial stop governs
     until the trailing level passes it), with a maximum hold of 20, 40 or 60 sessions (close of that session).
Results are in ATR (the initial risk is 1 ATR, so ATR = risk units).
CONTROL: a "no ratio" watch that starts every 5th session in the direction of the 20-session net close change (same pullback rule), to see whether the ratio adds anything.
Reference from the same-day snapshot test (Entry 108): pooled ratio and a pullback of at least 1.5 ATR from the 5-session high, next open, 1 ATR stop, exit at session 10: +0.28 ATR on 1,099 signals.
Everything chosen after looking at the development years is a lead, not a rule.
"""
import sys
import time
import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

prices_path, uni_path, out_dir = sys.argv[1:4]
DEV_START, DEV_END = pd.Timestamp("2007-12-31"), pd.Timestamp("2021-08-06")
SPLIT = pd.Timestamp("2015-01-01")
FW = 60
COST_RT = 0.10
ATRW = 20
XS = (0.5, 1.0, 1.5, 2.0, 2.5, 3.0)
NS = (10, 20, 40)
NMAX = max(NS)
EXITS = [("time", None, 5), ("time", None, 10), ("time", None, 20)] + [("trail", mm, cap) for mm in (2.0, 3.0, 4.0) for cap in (20, 40, 60)]
PRICE_MAP = {"6A": "A6", "6B": "B6", "6C": "AD", "6E": "E6", "6J": "J1", "6L": "BR", "6M": "MP", "6N": "N6", "6S": "E1", "ZB": "US", "BRR": "BTC", "LBR": "LBS"}
GROUPS = {"grains": ["ZW", "KE", "ZC", "ZS", "ZL", "ZM"], "energy": ["HO", "NG", "CL", "BZ", "RB"], "softs": ["CT", "CC", "SB", "KC"], "meats": ["HE", "LE", "GF"],
          "metals": ["PL", "SI", "HG", "GC"], "currencies": ["6A", "6B", "6C", "6E", "6J", "6M", "6N", "6S", "6L", "DX"],
          "rates": ["ZB", "UB", "ZN", "TN", "ZF", "ZT", "ZQ", "SR1", "SR3"], "stock indexes": ["YM", "ES", "MES", "NQ", "MNQ", "RTY"], "volatility": ["VX"]}
GROUP_OF = {m: g for g, ms in GROUPS.items() for m in ms}
TRENDS = ["pooled ratio (any of 5, 10, 20 sessions)", "10-session ratio at least 0.45 alone", "20-session ratio at least 0.50 alone", "control: no ratio, every 5th session, 20-session direction"]
t0 = time.time()

px = pd.read_parquet(prices_path)
px["file_date"] = pd.to_datetime(px["file_date"])
px = px[(px["file_date"] >= DEV_START) & (px["file_date"] <= DEV_END)].copy()
assert px["file_date"].max() <= DEV_END
print(f"development rows {len(px):,}; {px['file_date'].min().date()} to {px['file_date'].max().date()}; sealed years removed at load")
uni = pd.read_csv(uni_path)
YEARS = (DEV_END - DEV_START).days / 365.25

FO, FH, FL, FC, FA = [], [], [], [], []
DATE, MK, ATR0 = [], [], []
entries = {}          # (trend, X, N) -> list of (global row, direction)
offset = 0
names = []


def add(key, row, d):
    entries.setdefault(key, []).append((row, d))


for mid, ib in enumerate(uni["ibkr"]):
    sym = PRICE_MAP.get(ib, ib)
    g = px[px["symbol"] == sym].sort_values("file_date").drop_duplicates("file_date").dropna(subset=["close", "high", "low"])
    if len(g) < 250:
        print(f"  skipped {ib} ({sym}): only {len(g)} development sessions")
        continue
    c = g["close"].to_numpy(float).copy()
    o = g["open"].fillna(g["close"]).to_numpy(float).copy()
    h, l = g["high"].to_numpy(float).copy(), g["low"].to_numpy(float).copy()
    for k in range(1, len(c)):
        r = c[k] / c[k - 1]
        if r > 5 or r < 0.2:
            f = 10.0 ** round(np.log10(r))
            if f != 1.0:
                c[:k] *= f; o[:k] *= f; h[:k] *= f; l[:k] *= f
    n = len(c)
    pc = np.r_[np.nan, c[:-1]]
    tr = np.maximum.reduce([h - l, np.abs(h - pc), np.abs(l - pc)])
    tr[0] = h[0] - l[0]
    atr = pd.Series(tr).rolling(ATRW).mean().to_numpy()
    cs = pd.Series(c)
    m = n - FW                      # decision days 0..m-1 have a full forward path
    names.append(ib)
    er, dr = {}, {}
    for w in (5, 10, 20):
        path = pd.Series(np.abs(np.diff(c, prepend=np.nan))).rolling(w).sum()
        er[w] = ((cs - cs.shift(w)).abs() / path).to_numpy()
        dr[w] = np.sign(cs - cs.shift(w)).fillna(0).to_numpy()
    q5 = np.isfinite(er[5]) & (er[5] >= 0.60) & (dr[5] != 0)
    q10 = np.isfinite(er[10]) & (er[10] >= 0.45) & (dr[10] != 0)
    q20 = np.isfinite(er[20]) & (er[20] >= 0.50) & (dr[20] != 0)
    d_pool = np.sign(q5 * dr[5] + q10 * dr[10] + q20 * dr[20])
    okatr = np.isfinite(atr) & (atr > 1e-5 * c)
    defs = {TRENDS[0]: ((q5 | q10 | q20) & (d_pool != 0) & okatr, d_pool),
            TRENDS[1]: (q10 & okatr, dr[10]),
            TRENDS[2]: (q20 & okatr, dr[20]),
            TRENDS[3]: (((np.arange(n) % 5) == 0) & (dr[20] != 0) & okatr, dr[20])}
    for tname, (q, d) in defs.items():
        qprev = np.r_[False, q[:-1]]
        dprev = np.r_[0.0, d[:-1]]
        starts = np.where(q & ~(qprev & (dprev == d)) if not tname.startswith("control") else q)[0]
        for s in starts:
            if s >= m - 1:
                continue
            dn = d[s]
            peak = h[s] if dn > 0 else l[s]
            hit = {}
            for t in range(s + 1, min(s + NMAX, m - 1) + 1):
                peak = max(peak, h[t]) if dn > 0 else min(peak, l[t])
                a = atr[t]
                if not (a == a and a > 0):
                    continue
                dep = (peak - c[t]) / a if dn > 0 else (c[t] - peak) / a
                for X in XS:
                    if X not in hit and dep >= X:
                        hit[X] = t
                if len(hit) == len(XS):
                    break
            for X, t in hit.items():
                for N in NS:
                    if t - s <= N:
                        add((tname, X, N), offset + t, dn)
    for lst, arr in ((FO, o), (FH, h), (FL, l), (FC, c), (FA, atr)):
        lst.append(sliding_window_view(arr[1:], FW)[:m])
    DATE.append(g["file_date"].to_numpy()[:m]); MK.append(np.full(m, mid)); ATR0.append(atr[:m])
    offset += m
O, H, L, C, A = (np.concatenate(x) for x in (FO, FH, FL, FC, FA))
DATE = pd.DatetimeIndex(np.concatenate(DATE)); MK = np.concatenate(MK); ATR0 = np.concatenate(ATR0)
mkt_names = np.array(names)[MK]
print(f"{len(names)} markets; {offset:,} decision days; {sum(len(v) for v in entries.values()):,} entries across {len(entries)} combinations; {time.time()-t0:.0f}s", flush=True)


def sim(rows, d, kind, mm, cap):
    Oo, Hh, Ll, Cc, Aa = (M[rows][:, :cap] for M in (O, H, L, C, A))
    n = len(rows)
    entry = Oo[:, 0]
    atr0 = ATR0[rows]
    long = d > 0
    stop = entry - d * atr0
    best = entry.copy()
    res = np.full(n, np.nan)
    held = np.zeros(n, int)
    alive = np.ones(n, bool)
    for k in range(cap):
        o, h, l, c, a = Oo[:, k], Hh[:, k], Ll[:, k], Cc[:, k], Aa[:, k]
        hit = alive & np.where(long, l <= stop, h >= stop)
        gap = np.where(long, o <= stop, o >= stop) if k > 0 else np.zeros(n, bool)
        pxs = np.where(gap, o, stop)
        res[hit] = (d * (pxs - entry) / atr0)[hit]; held[hit] = k + 1
        alive &= ~hit
        if kind == "trail":
            best = np.where(alive, np.where(long, np.maximum(best, c), np.minimum(best, c)), best)
            new = best - d * mm * a
            stop = np.where(alive & np.isfinite(new), np.where(long, np.maximum(stop, new), np.minimum(stop, new)), stop)
        if k == cap - 1:
            res[alive] = (d * (c - entry) / atr0)[alive]; held[alive] = k + 1
    return res - COST_RT, held


def tstat(x):
    return float(x.mean() / x.std(ddof=1) * np.sqrt(len(x))) if len(x) > 30 and x.std() > 0 else np.nan


def label(e):
    return f"time exit {e[2]}" if e[0] == "time" else f"trail {e[1]:g} ATR, max {e[2]}"


rows_out, by_year, by_group = [], [], []
for (tname, X, N), lst in sorted(entries.items(), key=lambda kv: (TRENDS.index(kv[0][0]), kv[0][1], kv[0][2])):
    rows = np.array([r for r, _ in lst]); d = np.array([x for _, x in lst], float)
    if len(rows) < 30:
        continue
    fh = np.asarray(DATE[rows] < SPLIT)
    yrs = np.asarray(DATE[rows].year)
    for e in EXITS:
        res, held = sim(rows, d, *e)
        row = dict(trend=tname, pullback_x_atr=X, watch_sessions=N, exit=label(e), n=len(rows), per_month=len(rows) / YEARS / 12, avg_ATR=float(np.nanmean(res)),
                   win_rate_pct=float((res > 0).mean() * 100), avg_sessions=float(held.mean()), pct_held_over_20=float((held > 20).mean() * 100),
                   first_half=float(res[fh].mean()) if fh.sum() > 20 else np.nan, second_half=float(res[~fh].mean()) if (~fh).sum() > 20 else np.nan,
                   t_stat=tstat(res), pct_years_positive=float((pd.Series(res).groupby(yrs).mean() > 0).mean() * 100),
                   best_winner_ATR=float(np.nanmax(res)), avg_winner=float(res[res > 0].mean()) if (res > 0).any() else np.nan, avg_loser=float(res[res <= 0].mean()))
        rows_out.append(row)
        if tname == TRENDS[0] and X == 1.5 and N == 20 and e in (("time", None, 10), ("trail", 3.0, 60), ("trail", 3.0, 40)):
            for yv in sorted(set(yrs)):
                by_year.append(dict(exit=label(e), year=int(yv), n=int((yrs == yv).sum()), avg_ATR=float(res[yrs == yv].mean())))
            gm = mkt_names[rows]
            for gname in list(GROUPS):
                mk_ = np.array([GROUP_OF.get(x, "other") == gname for x in gm])
                by_group.append(dict(exit=label(e), group=gname, n=int(mk_.sum()), avg_ATR=float(res[mk_].mean()) if mk_.sum() >= 15 else np.nan))
    print(f"{tname[:30]} X={X} N={N}: {len(rows)} entries ({time.time()-t0:.0f}s)", flush=True)
out = pd.DataFrame(rows_out)
out.to_csv(f"{out_dir}/signal_then_pullback.csv", index=False)
pd.DataFrame(by_year).to_csv(f"{out_dir}/headline_by_year.csv", index=False)
pd.DataFrame(by_group).to_csv(f"{out_dir}/headline_by_group.csv", index=False)

pd.set_option("display.width", 280); pd.set_option("display.max_columns", 50); pd.set_option("display.max_rows", 900)
key = ["time exit 5", "time exit 10", "time exit 20", "trail 2 ATR, max 40", "trail 3 ATR, max 40", "trail 3 ATR, max 60", "trail 4 ATR, max 60"]
for tname in TRENDS:
    sub = out[(out.trend == tname) & out.exit.isin(key)]
    if sub.empty:
        continue
    pv = sub.pivot_table(index=["pullback_x_atr", "watch_sessions", "n", "per_month"], columns="exit", values="avg_ATR")[[k for k in key if k in sub.exit.unique()]]
    print(f"\n==== {tname}: average result in ATR by pullback size, watch length and exit ====")
    print(pv.round(3).to_string())
head = out[(out.trend == TRENDS[0]) & (out.pullback_x_atr == 1.5) & (out.watch_sessions == 20)]
print("\n==== HEADLINE (pooled, pullback 1.5 ATR, watch 20 sessions): every exit ====")
print(head.drop(columns=["trend", "pullback_x_atr", "watch_sessions"]).round(3).to_string(index=False))
print("\nby year:\n" + pd.DataFrame(by_year).pivot_table(index="year", columns="exit", values="avg_ATR").round(3).to_string())
print("\nby group:\n" + pd.DataFrame(by_group).pivot_table(index="group", columns="exit", values="avg_ATR").round(3).to_string())
print("done", f"{time.time()-t0:.0f}s")
