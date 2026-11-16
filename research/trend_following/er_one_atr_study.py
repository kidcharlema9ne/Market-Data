"""One-ATR-stop study: does a smooth recent trend (efficiency ratio) give an edge when the stop is only 1 ATR away? DEVELOPMENT YEARS ONLY.

Usage: python er_one_atr_study.py futures_prices.parquet report_universe_48_markets.csv OUT_DIR

SEALED YEARS: prices after 2021-08-06 are removed the moment the file is read (development window 2007-12-31 to 2021-08-06). Nothing sealed is used.

WHY (Michael, 16 Nov 2026): he cannot run a full portfolio and expects to trade with about a 1 ATR stop and to time entries with other indicators, so the question is
what happens from a signal with a tight stop, in short windows, with a smaller target. No portfolio is simulated; every signal is judged on its own in ATR (risk) units.

SIGNAL: on any day, a market whose close-based efficiency ratio over the window (5, 10, 20 or 40 sessions) sits in a band, going in the direction of the net close change
over that window. Entry at the NEXT session's open. ATR = 20-day average true range on the signal day. Risk unit = 1 ATR (the stop distance).
Paths are followed for at most 20 sessions. Stops are checked before targets inside a bar; a gap through a stop fills at the open.
Cost: 0.05 ATR per side, so 0.10 risk units deducted from every trade.

EXIT RULES (all with a 1 ATR initial stop):
  - target 2 ATR, else stop, else close of session 20
  - target 3 ATR, else stop, else close of session 20
  - 1 ATR trailing stop from the best close (ratchets, uses the current ATR), close of session 20 at the latest
  - no target, close of session 10
FIRST-PASSAGE numbers (no exit rule, no cost): the share of signals that reach +1, +2, +3 ATR before touching the 1 ATR stop within 20 sessions.

CONTROLS: all days in the momentum direction with no ratio filter, and all days with a RANDOM direction (fixed seed). The random-direction row is the no-edge baseline: any
signal has to beat it, after the same cost.
SUBSETS: "all days" counts every qualifying day (consecutive days are nearly the same trade, so t-statistics are overstated); "first day of run" keeps only the first day a
market enters the group in a given direction, which is much closer to independent trades. Trust the second for significance.
SECTIONS: (1) bands of the ratio by window; (2) the top 3 and top 5 markets of the day by ratio (what a limited-capital trader could actually take); (3) timing filters on top of a
qualifying ratio (counter-trend day, pullback from the recent extreme, inside day, close back through the prior day's extreme).
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
CAP = 20
COST_RT = 0.10
ATRW = 20
WINDOWS = [5, 10, 20, 40]
BANDS = {5: [0, 0.4, 0.6, 0.8, 1.01], 10: [0, 0.3, 0.45, 0.6, 1.01], 20: [0, 0.2, 0.35, 0.5, 0.6, 1.01], 40: [0, 0.15, 0.25, 0.35, 0.5, 1.01]}
TIMING_BASES = [(5, 0.6), (10, 0.45), (20, 0.5)]
TOPN = (3, 5)
PRICE_MAP = {"6A": "A6", "6B": "B6", "6C": "AD", "6E": "E6", "6J": "J1", "6L": "BR", "6M": "MP", "6N": "N6", "6S": "E1", "ZB": "US", "BRR": "BTC", "LBR": "LBS"}
rng = np.random.default_rng(20261116)
t0 = time.time()

px = pd.read_parquet(prices_path)
px["file_date"] = pd.to_datetime(px["file_date"])
px = px[(px["file_date"] >= DEV_START) & (px["file_date"] <= DEV_END)].copy()
assert px["file_date"].max() <= DEV_END
print(f"development rows {len(px):,}; {px['file_date'].min().date()} to {px['file_date'].max().date()}; sealed years removed at load")
uni = pd.read_csv(uni_path)

cols = ["mkt", "date", "atr0", "c0", "i_in_mkt"] + [f"er{w}" for w in WINDOWS] + [f"dir{w}" for w in WINDOWS] + \
       ["dc1", "dc2", "hi5", "lo5", "hi10", "lo10", "hprev", "lprev", "hsig", "lsig", "csig"]
store = {k: [] for k in cols}
FO, FH, FL, FC, FA = [], [], [], [], []
names = []
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
    m = n - CAP
    names.append(ib)
    store["mkt"].append(np.full(m, mid)); store["date"].append(g["file_date"].to_numpy()[:m])
    store["atr0"].append(atr[:m]); store["c0"].append(c[:m]); store["i_in_mkt"].append(np.arange(m))
    for w in WINDOWS:
        path = pd.Series(np.abs(np.diff(c, prepend=np.nan))).rolling(w).sum()
        store[f"er{w}"].append(((cs - cs.shift(w)).abs() / path).to_numpy()[:m])
        store[f"dir{w}"].append(np.sign(cs - cs.shift(w)).fillna(0).to_numpy()[:m])
    hs, ls = pd.Series(h), pd.Series(l)
    store["dc1"].append((cs - cs.shift(1)).to_numpy()[:m]); store["dc2"].append((cs.shift(1) - cs.shift(2)).to_numpy()[:m])
    store["hi5"].append(hs.rolling(5).max().to_numpy()[:m]); store["lo5"].append(ls.rolling(5).min().to_numpy()[:m])
    store["hi10"].append(hs.rolling(10).max().to_numpy()[:m]); store["lo10"].append(ls.rolling(10).min().to_numpy()[:m])
    store["hprev"].append(hs.shift(1).to_numpy()[:m]); store["lprev"].append(ls.shift(1).to_numpy()[:m])
    store["hsig"].append(h[:m]); store["lsig"].append(l[:m]); store["csig"].append(c[:m])
    # forward paths: row i holds sessions i+1 .. i+CAP
    for lst, arr in ((FO, o), (FH, h), (FL, l), (FC, c), (FA, atr)):
        lst.append(sliding_window_view(arr[1:], CAP)[:m])
S = {k: np.concatenate(v) for k, v in store.items()}
O, H, L, C, A = (np.concatenate(x) for x in (FO, FH, FL, FC, FA))
N = len(S["mkt"])
entry = O[:, 0]
atr0 = S["atr0"]
dates = pd.DatetimeIndex(S["date"])
first_half = np.asarray(dates < SPLIT)
base_ok = np.isfinite(atr0) & (atr0 > 1e-5 * S["c0"]) & np.isfinite(entry) & np.isfinite(O).all(1) & np.isfinite(H).all(1) & np.isfinite(L).all(1) & np.isfinite(C).all(1)
print(f"{len(names)} markets; {N:,} market-days with a full {CAP}-session forward path; {time.time()-t0:.0f}s", flush=True)
same_mkt_prev = np.r_[False, S["mkt"][1:] == S["mkt"][:-1]]


def first_idx(cond):
    return np.where(cond.any(1), cond.argmax(1), 99)


def simulate(d, target, trail, cap_exit):
    res = np.full(N, np.nan)
    held = np.zeros(N, int)
    alive = np.ones(N, bool)
    long = d > 0
    stop = entry - d * atr0
    best = entry.copy()
    for k in range(cap_exit):
        o, h, l, c, a = O[:, k], H[:, k], L[:, k], C[:, k], A[:, k]
        hit = alive & np.where(long, l <= stop, h >= stop)
        gap = np.where(long, o <= stop, o >= stop)
        px_stop = np.where(gap, o, stop)
        res[hit] = (d * (px_stop - entry) / atr0)[hit]; held[hit] = k + 1
        alive &= ~hit
        if target is not None:
            tgt = entry + d * target * atr0
            th = alive & np.where(long, h >= tgt, l <= tgt)
            res[th] = target; held[th] = k + 1
            alive &= ~th
        if trail:
            best = np.where(alive, np.where(long, np.maximum(best, c), np.minimum(best, c)), best)
            new = best - d * a
            stop = np.where(alive & np.isfinite(new), np.where(long, np.maximum(stop, new), np.minimum(stop, new)), stop)
        if k == cap_exit - 1:
            res[alive] = (d * (c - entry) / atr0)[alive]; held[alive] = k + 1
    return res - COST_RT, held


RULES = [("target2", 2.0, False, CAP), ("target3", 3.0, False, CAP), ("trail1", None, True, CAP), ("time10", None, False, 10)]


def outcomes(d):
    out = {}
    for name, tgt, tr, cap in RULES:
        out[name], out[name + "_held"] = simulate(d, tgt, tr, cap)
    long = (d > 0)[:, None]
    fav = np.where(long, H - entry[:, None], entry[:, None] - L) / atr0[:, None]
    adv = np.where(long, entry[:, None] - L, H - entry[:, None]) / atr0[:, None]
    s = first_idx(adv >= 1.0)
    for j in (1, 2, 3):
        out[f"p{j}"] = first_idx(fav >= j) < s     # target reached on an earlier bar than the stop (same bar counts as stopped)
    out["stopfirst"] = (s < first_idx(fav >= 1.0))
    return out


def tstat(x):
    x = x[np.isfinite(x)]
    return float(x.mean() / x.std(ddof=1) * np.sqrt(len(x))) if len(x) > 30 and x.std() > 0 else np.nan


def stats(mask, out, label):
    row = dict(label)
    n = int(mask.sum())
    row["n"] = n
    if n < 30:
        return row
    for j in (1, 2, 3):
        row[f"pct_reach_plus{j}_before_stop"] = out[f"p{j}"][mask].mean() * 100
    row["pct_stopped_before_plus1"] = out["stopfirst"][mask].mean() * 100
    for name, *_ in RULES:
        row[f"avg_R_{name}"] = float(np.nanmean(out[name][mask]))
    for name in ("trail1", "target3"):
        row[f"avg_R_{name}_first_half"] = float(np.nanmean(out[name][mask & first_half])) if (mask & first_half).sum() > 20 else np.nan
        row[f"avg_R_{name}_second_half"] = float(np.nanmean(out[name][mask & ~first_half])) if (mask & ~first_half).sum() > 20 else np.nan
    row["t_trail1"] = tstat(out["trail1"][mask]); row["t_target3"] = tstat(out["target3"][mask])
    row["avg_sessions_trail1"] = float(out["trail1_held"][mask].mean())
    return row


def run_start(member, d):
    prev = np.r_[False, member[:-1]] & same_mkt_prev
    prev_d = np.r_[0, d[:-1]]
    return member & ~(prev & (prev_d == d))


rows1, rows2, rows3 = [], [], []
# controls
d_rand = rng.choice([-1.0, 1.0], N)
out_rand = outcomes(d_rand)
rows1.append(stats(base_ok, out_rand, dict(window="none", band="all days, RANDOM direction (no-edge baseline)", subset="all days")))
for w in WINDOWS:
    d = S[f"dir{w}"]
    ok = base_ok & np.isfinite(S[f"er{w}"]) & (d != 0)
    out = outcomes(d)
    er = S[f"er{w}"]
    groups = [("all days, momentum direction, no ratio filter", ok)]
    edges = BANDS[w]
    for lo, hi in zip(edges[:-1], edges[1:]):
        groups.append((f"ratio {lo:.2f} to {min(hi, 1.0):.2f}" + (" and above" if hi > 1 else ""), ok & (er >= lo) & (er < hi)))
    for lab, mk_ in groups:
        for sub, mm in (("all days", mk_), ("first day of run", mk_ & run_start(mk_, d))):
            rows1.append(stats(mm, out, dict(window=w, band=lab, subset=sub)))
    # top N markets of the day by ratio
    dfr = pd.DataFrame({"date": S["date"], "er": er + rng.random(N) * 1e-9})
    dfr.loc[~ok, "er"] = np.nan
    rank = dfr.groupby("date")["er"].rank(ascending=False, method="first").to_numpy()
    for nn in TOPN:
        mem = ok & (rank <= nn)
        for sub, mm in (("all days", mem), ("first day of run", mem & run_start(mem, d))):
            r = stats(mm, out, dict(window=w, group=f"top {nn} markets of the day by ratio", subset=sub))
            r["avg_ratio"] = float(er[mm].mean()) if mm.any() else np.nan
            rows2.append(r)
    print(f"window {w} done {time.time()-t0:.0f}s", flush=True)
    # timing filters
    for bw, thr in TIMING_BASES:
        if bw != w:
            continue
        qual = ok & (er >= thr)
        long = d > 0
        c, atrv = S["csig"], atr0
        pull5 = np.where(long, S["hi5"] - c, c - S["lo5"]) >= 1.0 * atrv
        pull10 = np.where(long, S["hi10"] - c, c - S["lo10"]) >= 2.0 * atrv
        counter = d * S["dc1"] < 0
        inside = (S["hsig"] <= S["hprev"]) & (S["lsig"] >= S["lprev"])
        reversal = (d * S["dc1"] > 0) & (d * S["dc2"] < 0) & np.where(long, c > S["hprev"], c < S["lprev"])
        variants = [("no timing filter", np.ones(N, bool)), ("counter-trend day (close against the trend)", counter),
                    ("pullback of at least 1 ATR from the 5-day extreme", pull5), ("pullback of at least 2 ATR from the 10-day extreme", pull10),
                    ("inside day", inside), ("close back through the prior day's extreme after a counter-trend day", reversal)]
        for lab, f in variants:
            for sub, mm in (("all days", qual & f), ("first day of run", qual & f & run_start(qual & f, d))):
                rows3.append(stats(mm, out, dict(window=w, ratio_at_least=thr, timing=lab, subset=sub)))

pd.DataFrame(rows1).to_csv(f"{out_dir}/one_atr_by_band.csv", index=False)
pd.DataFrame(rows2).to_csv(f"{out_dir}/one_atr_top_markets.csv", index=False)
pd.DataFrame(rows3).to_csv(f"{out_dir}/one_atr_timing.csv", index=False)
pd.set_option("display.width", 260); pd.set_option("display.max_columns", 40); pd.set_option("display.max_rows", 500)
short = ["n", "pct_reach_plus1_before_stop", "pct_reach_plus2_before_stop", "pct_reach_plus3_before_stop", "avg_R_target2", "avg_R_target3", "avg_R_trail1", "avg_R_time10", "t_trail1"]
for nm, rr, key in (("BANDS", rows1, ["window", "band", "subset"]), ("TOP MARKETS", rows2, ["window", "group", "subset"]), ("TIMING", rows3, ["window", "ratio_at_least", "timing", "subset"])):
    df = pd.DataFrame(rr)
    print(f"\n==== {nm} ====")
    print(df[key + [c for c in short if c in df]].round(3).to_string(index=False))
print("done", f"{time.time()-t0:.0f}s")
