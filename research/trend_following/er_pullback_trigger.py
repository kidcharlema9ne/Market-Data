"""Pullbacks inside smooth trends, and short-term confirmation triggers, with a tight stop. 48 COT markets, DEVELOPMENT YEARS ONLY.

Usage: python er_pullback_trigger.py futures_prices.parquet report_universe_48_markets.csv OUT_DIR

SEALED YEARS: prices after 2021-08-06 are removed the moment the file is read (development window 2007-12-31 to 2021-08-06). Nothing sealed is used.

QUALIFYING TREND (pooled, in plain words): a market qualifies on a day if ANY of these is true: its 5-session efficiency ratio is at least 0.60, its 10-session ratio is at least 0.45,
its 20-session ratio is at least 0.50 (close-based ratio). Direction = the sign of the net close change over each qualifying window added together; ties are skipped.
Single-window versions and a no-ratio control (direction = 20-session net change, any day) are run beside it so we can see whether the ratio adds anything.
PULLBACK DEPTH (long case; mirrored for shorts): how far today's close is below the highest high of the last 5 (or 10) sessions, in units of the 20-day ATR.

PART 1, DEPTH CURVE (entry at the next open): average result per trade, in ATR, by pullback depth band, for stops of 1, 1.5 and 2 ATR and time exits at the close of session 5, 10, 15, 20.
Smooth rise with depth = probably real; jumpy = noise.
PART 2, TRIGGERS (Michael, 16 Nov 2026: wait for a small range and for short-term confirmation that the trend is resuming, not buy a falling wide-range day). On a qualifying market with a
pullback of at least 0.5 / 1.0 / 1.5 ATR from the 5-session extreme, the setup day is the signal day. Entry options:
  immediate next open;
  buy the break of the setup day's high (short: low), as a stop order good for the next 3 sessions (a gap through fills at the open);
  the same break, only when the setup day was an inside day (range inside the prior day's range);
  the same break, only when the setup day's range was at most 0.7 ATR (a quiet, small-range day);
  the same break, only when the setup day's range was the smallest of the last 4 sessions (volatility contracting).
Stops: 1 ATR from the fill, or "setup-day extreme" (below the setup day's low for longs, above its high for shorts, but never closer than 0.5 ATR).
Exits: close of session 5, 10, 15, 20 counting the fill session as 1; stop checked first inside a bar; a gap through the stop fills at the open; the fill bar can be stopped out (worst case).
Cost 0.10 ATR round trip. Results are in ATR (and in risk units for the setup-day stop, which has a different risk size every time).
SUBSETS: "first day of run" (the first day a market enters the group in a given direction) is the honest count; "all days" repeats nearly the same trade on consecutive days.
CONTROL FOR LUCK: many cells are looked at here, so a cell only counts as a lead when it has enough first-of-run signals, is positive in both halves of the years, and sits next to similar cells.
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
HOLD = 20
WAIT = 3
FW = WAIT + HOLD
COST_RT = 0.10
ATRW = 20
THR = {5: 0.60, 10: 0.45, 20: 0.50}
WINDOWS = [5, 10, 20]
STOPS = (1.0, 1.5, 2.0)
TIMES = (5, 10, 15, 20)
PRICE_MAP = {"6A": "A6", "6B": "B6", "6C": "AD", "6E": "E6", "6J": "J1", "6L": "BR", "6M": "MP", "6N": "N6", "6S": "E1", "ZB": "US", "BRR": "BTC", "LBR": "LBS"}
GROUPS = {"grains": ["ZW", "KE", "ZC", "ZS", "ZL", "ZM"], "energy": ["HO", "NG", "CL", "BZ", "RB"], "softs": ["CT", "CC", "SB", "KC"], "meats": ["HE", "LE", "GF"],
          "metals": ["PL", "SI", "HG", "GC"], "currencies": ["6A", "6B", "6C", "6E", "6J", "6M", "6N", "6S", "6L", "DX"],
          "rates": ["ZB", "UB", "ZN", "TN", "ZF", "ZT", "ZQ", "SR1", "SR3"], "stock indexes": ["YM", "ES", "MES", "NQ", "MNQ", "RTY"], "volatility": ["VX"]}
GROUP_OF = {m: g for g, ms in GROUPS.items() for m in ms}
t0 = time.time()

px = pd.read_parquet(prices_path)
px["file_date"] = pd.to_datetime(px["file_date"])
px = px[(px["file_date"] >= DEV_START) & (px["file_date"] <= DEV_END)].copy()
assert px["file_date"].max() <= DEV_END
print(f"development rows {len(px):,}; {px['file_date'].min().date()} to {px['file_date'].max().date()}; sealed years removed at load")
uni = pd.read_csv(uni_path)
YEARS = (DEV_END - DEV_START).days / 365.25

cols = ["mkt", "date", "atr0", "c0", "dc1"] + [f"er{w}" for w in WINDOWS] + [f"dir{w}" for w in WINDOWS] + ["hi5", "lo5", "hi10", "lo10", "hprev", "lprev", "hsig", "lsig", "csig", "r1", "r2", "r3", "dir20x"]
store = {k: [] for k in cols}
FO, FH, FL, FC = [], [], [], []
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
    cs, hs, ls = pd.Series(c), pd.Series(h), pd.Series(l)
    m = n - FW
    names.append(ib)
    store["mkt"].append(np.full(m, mid)); store["date"].append(g["file_date"].to_numpy()[:m])
    store["atr0"].append(atr[:m]); store["c0"].append(c[:m]); store["dc1"].append((cs - cs.shift(1)).to_numpy()[:m])
    for w in WINDOWS:
        path = pd.Series(np.abs(np.diff(c, prepend=np.nan))).rolling(w).sum()
        store[f"er{w}"].append(((cs - cs.shift(w)).abs() / path).to_numpy()[:m])
        store[f"dir{w}"].append(np.sign(cs - cs.shift(w)).fillna(0).to_numpy()[:m])
    store["dir20x"].append(np.sign(cs - cs.shift(20)).fillna(0).to_numpy()[:m])
    store["hi5"].append(hs.rolling(5).max().to_numpy()[:m]); store["lo5"].append(ls.rolling(5).min().to_numpy()[:m])
    store["hi10"].append(hs.rolling(10).max().to_numpy()[:m]); store["lo10"].append(ls.rolling(10).min().to_numpy()[:m])
    store["hprev"].append(hs.shift(1).to_numpy()[:m]); store["lprev"].append(ls.shift(1).to_numpy()[:m])
    store["hsig"].append(h[:m]); store["lsig"].append(l[:m]); store["csig"].append(c[:m])
    rng_ = pd.Series(h - l)
    for k, nm in ((1, "r1"), (2, "r2"), (3, "r3")):
        store[nm].append(rng_.shift(k).to_numpy()[:m])
    for lst, arr in ((FO, o), (FH, h), (FL, l), (FC, c)):
        lst.append(sliding_window_view(arr[1:], FW)[:m])
S = {k: np.concatenate(v) for k, v in store.items()}
O, H, L, C = (np.concatenate(x) for x in (FO, FH, FL, FC))
N = len(S["mkt"])
atr0 = S["atr0"]
dates = pd.DatetimeIndex(S["date"])
first_half = np.asarray(dates < SPLIT)
yrs_arr = np.asarray(dates.year)
mkt_names = np.array(names)[S["mkt"]]
grp_arr = np.array([GROUP_OF.get(x, "other") for x in mkt_names])
base_ok = np.isfinite(atr0) & (atr0 > 1e-5 * S["c0"]) & np.isfinite(O).all(1) & np.isfinite(H).all(1) & np.isfinite(L).all(1) & np.isfinite(C).all(1)
same_mkt_prev = np.r_[False, S["mkt"][1:] == S["mkt"][:-1]]
print(f"{len(names)} markets; {N:,} market-days with a full {FW}-session forward path; {time.time()-t0:.0f}s", flush=True)


def run_start(member, d):
    prev = np.r_[False, member[:-1]] & same_mkt_prev
    prev_d = np.r_[0, d[:-1]]
    return member & ~(prev & (prev_d == d))


def simulate(d, fill, e, sd, cap):
    """Trade filled at price `fill` on forward bar e (0..2); stop sd ATR away; exit at the close of session `cap` (fill session = 1). Returns result in ATR after cost."""
    idx = e[:, None] + np.arange(cap)[None, :]
    Og, Hg, Lg, Cg = (np.take_along_axis(M, idx, 1) for M in (O, H, L, C))
    long = d > 0
    stop = fill - d * sd * atr0
    res = np.full(N, np.nan)
    alive = np.ones(N, bool)
    for k in range(cap):
        o, h, l, c = Og[:, k], Hg[:, k], Lg[:, k], Cg[:, k]
        hit = alive & np.where(long, l <= stop, h >= stop)
        gap = np.where(long, o <= stop, o >= stop) if k > 0 else np.zeros(N, bool)
        px_stop = np.where(gap, o, stop)
        res[hit] = (d * (px_stop - fill) / atr0)[hit]
        alive &= ~hit
        if k == cap - 1:
            res[alive] = (d * (c - fill) / atr0)[alive]
    return res - COST_RT


def tstat(x):
    x = x[np.isfinite(x)]
    return float(x.mean() / x.std(ddof=1) * np.sqrt(len(x))) if len(x) > 30 and x.std() > 0 else np.nan


def stats(mask, res, label, detail_key, risk=None):
    row = dict(label)
    n = int(mask.sum())
    row["n"] = n
    row["per_month"] = n / YEARS / 12
    if n < 30:
        return row
    for key, arr in res.items():
        row[f"avg_ATR_stop{key[0]:g}_t{key[1]}"] = float(np.nanmean(arr[mask]))
    x = res[detail_key]
    row["win_rate_pct"] = float((x[mask] > 0).mean() * 100)
    a, b = mask & first_half, mask & ~first_half
    row["first_half"] = float(np.nanmean(x[a])) if a.sum() > 20 else np.nan
    row["second_half"] = float(np.nanmean(x[b])) if b.sum() > 20 else np.nan
    row["t_stat"] = tstat(x[mask])
    yr = pd.Series(x[mask]).groupby(yrs_arr[mask]).mean()
    row["pct_years_positive"] = float((yr > 0).mean() * 100)
    if risk is not None:
        row["avg_risk_ATR"] = float(np.nanmean(risk[mask]))
        row["avg_R"] = float(np.nanmean((x / risk)[mask]))
    return row


# ---- directions and qualification
q = {w: base_ok & np.isfinite(S[f"er{w}"]) & (S[f"er{w}"] >= THR[w]) & (S[f"dir{w}"] != 0) for w in WINDOWS}
dsum = sum(q[w] * S[f"dir{w}"] for w in WINDOWS)
d_pool = np.sign(dsum)
qual_pool = (q[5] | q[10] | q[20]) & (d_pool != 0)
d_ctrl = S["dir20x"].copy()
ok_ctrl = base_ok & (d_ctrl != 0)
print(f"qualifying market-days: pooled {qual_pool.sum():,}; single {[int(q[w].sum()) for w in WINDOWS]}; control (any day) {ok_ctrl.sum():,}", flush=True)


def depth(d, which):
    hi, lo = S[f"hi{which}"], S[f"lo{which}"]
    return np.where(d > 0, hi - S["csig"], S["csig"] - lo) / atr0


# ---- PART 1: depth curve, entry at next open
e0 = np.zeros(N, int)
fill0 = O[:, 0]
part1_rows = []
sets = [("pooled (any of the three windows)", d_pool, qual_pool, True), ("5-session ratio at least 0.60", S["dir5"], q[5], False),
        ("10-session ratio at least 0.45", S["dir10"], q[10], False), ("20-session ratio at least 0.50", S["dir20"], q[20], False),
        ("control: no ratio filter, direction of the 20-session change", d_ctrl, ok_ctrl, False)]
BINS5 = [0, 0.5, 1.0, 1.5, 2.0, 3.0, 99]
BINS10 = [0, 1.0, 2.0, 3.0, 4.0, 99]
for lab, d, qual, full in sets:
    grid = [(s, T) for s in (STOPS if full else (1.0,)) for T in TIMES]
    res = {(s, T): simulate(d, fill0, e0, s, T) for s, T in grid}
    for which, bins in ((5, BINS5), (10, BINS10)):
        dep = depth(d, which)
        allm = qual
        for lo, hi in zip([None] + bins[:-1], [None] + bins[1:]):
            if lo is None:
                mem, dl = allm, "any depth"
            else:
                mem = allm & (dep >= lo) & (dep < hi)
                dl = f"{lo:g} to {hi:g} ATR" if hi < 99 else f"{lo:g} ATR and deeper"
            for sub, mm in (("all days", mem), ("first day of run", mem & run_start(mem, d))):
                part1_rows.append(stats(mm, res, dict(trend=lab, pullback_from=f"{which}-session extreme", depth=dl, subset=sub), (1.0, 10)))
    print(f"part 1 '{lab}' done {time.time()-t0:.0f}s", flush=True)
pd.DataFrame(part1_rows).to_csv(f"{out_dir}/pullback_depth_curve.csv", index=False)

# ---- PART 2: triggers
part2_rows, grp_rows, yr_rows = [], [], []
for ctrl, d, qual in (("ratio-qualified (pooled)", d_pool, qual_pool), ("control: no ratio filter", d_ctrl, ok_ctrl)):
    long = d > 0
    trig = np.where(long, S["hsig"], S["lsig"])
    lvl = np.where(long, S["lsig"], S["hsig"])
    e = np.full(N, -1)
    fill = np.full(N, np.nan)
    for j in range(WAIT - 1, -1, -1):           # earliest bar wins
        cond = np.where(long, H[:, j] >= trig, L[:, j] <= trig)
        fj = np.where(long, np.where(O[:, j] >= trig, O[:, j], trig), np.where(O[:, j] <= trig, O[:, j], trig))
        e = np.where(cond, j, e)
        fill = np.where(cond, fj, fill)
    filled = e >= 0
    e_safe = np.where(filled, e, 0)
    fill_safe = np.where(filled, fill, O[:, 0])
    sd_struct = np.maximum(0.5, d * (fill_safe - lvl) / atr0)
    res_imm = {(1.0, T): simulate(d, fill0, e0, 1.0, T) for T in TIMES}
    res_brk1 = {(1.0, T): simulate(d, fill_safe, e_safe, 1.0, T) for T in TIMES}
    res_brks = {(1.0, T): simulate(d, fill_safe, e_safe, sd_struct, T) for T in TIMES}
    inside = (S["hsig"] <= S["hprev"]) & (S["lsig"] >= S["lprev"])
    rng_t = S["hsig"] - S["lsig"]
    narrow = rng_t <= 0.7 * atr0
    nr4 = (rng_t <= S["r1"]) & (rng_t <= S["r2"]) & (rng_t <= S["r3"])
    dep5 = depth(d, 5)
    trigs = [("immediate next open", None, res_imm, "1 ATR", np.ones(N, bool), None),
             ("break of the setup day's extreme (any setup day)", filled, res_brk1, "1 ATR", np.ones(N, bool), None),
             ("break, setup day was an inside day", filled, res_brk1, "1 ATR", inside, None),
             ("break, setup day range at most 0.7 ATR", filled, res_brk1, "1 ATR", narrow, None),
             ("break, setup day range smallest of last 4", filled, res_brk1, "1 ATR", nr4, None),
             ("break of the setup day's extreme (any setup day)", filled, res_brks, "setup-day extreme", np.ones(N, bool), sd_struct),
             ("break, setup day was an inside day", filled, res_brks, "setup-day extreme", inside, sd_struct),
             ("break, setup day range at most 0.7 ATR", filled, res_brks, "setup-day extreme", narrow, sd_struct),
             ("break, setup day range smallest of last 4", filled, res_brks, "setup-day extreme", nr4, sd_struct)]
    for X in ((0.5, 1.0, 1.5) if ctrl.startswith("ratio") else (1.0,)):
        setup = qual & (dep5 >= X)
        for tlab, fmask, res, stype, extra, risk in trigs:
            mem = setup & extra
            traded = mem if fmask is None else (mem & fmask)
            for sub, mm in (("all days", traded), ("first day of run", traded & run_start(mem, d))):
                part2_rows.append(stats(mm, res, dict(trend=ctrl, pullback_at_least=f"{X:g} ATR from the 5-session extreme", entry=tlab, stop=stype, subset=sub), (1.0, 10), risk))
                if sub == "first day of run" and X == 1.0:
                    x = res[(1.0, 10)]
                    base = dict(trend=ctrl, entry=tlab, stop=stype)
                    gr = dict(base)
                    for gname in list(GROUPS) + ["other"]:
                        gm = mm & (grp_arr == gname)
                        gr[f"{gname} n"] = int(gm.sum()); gr[f"{gname} avg_ATR_t10"] = float(np.nanmean(x[gm])) if gm.sum() >= 20 else np.nan
                    grp_rows.append(gr)
                    yr = dict(base)
                    for yv in sorted(set(yrs_arr)):
                        ym = mm & (yrs_arr == yv)
                        yr[str(yv)] = float(np.nanmean(x[ym])) if ym.sum() >= 15 else np.nan
                    yr_rows.append(yr)
    print(f"part 2 '{ctrl}' done {time.time()-t0:.0f}s", flush=True)
pd.DataFrame(part2_rows).to_csv(f"{out_dir}/trigger_results.csv", index=False)
pd.DataFrame(grp_rows).to_csv(f"{out_dir}/trigger_by_market_group.csv", index=False)
pd.DataFrame(yr_rows).to_csv(f"{out_dir}/trigger_by_year.csv", index=False)

pd.set_option("display.width", 280); pd.set_option("display.max_columns", 50); pd.set_option("display.max_rows", 800)
d1 = pd.DataFrame(part1_rows)
print("\n==== PART 1: DEPTH CURVE (first day of run), pooled, all stops and exits ====")
print(d1[(d1.subset == "first day of run") & d1.trend.str.startswith("pooled")].drop(columns=["subset", "trend"]).round(3).to_string(index=False))
print("\n==== PART 1: other trend definitions, 1 ATR stop (first day of run) ====")
keep = ["trend", "pullback_from", "depth", "n", "per_month", "avg_ATR_stop1_t5", "avg_ATR_stop1_t10", "avg_ATR_stop1_t15", "avg_ATR_stop1_t20", "first_half", "second_half", "t_stat"]
print(d1[(d1.subset == "first day of run") & ~d1.trend.str.startswith("pooled")][keep].round(3).to_string(index=False))
d2 = pd.DataFrame(part2_rows)
print("\n==== PART 2: TRIGGERS (first day of run) ====")
keep2 = ["trend", "pullback_at_least", "entry", "stop", "n", "per_month", "avg_ATR_stop1_t5", "avg_ATR_stop1_t10", "avg_ATR_stop1_t15", "avg_ATR_stop1_t20", "win_rate_pct", "first_half", "second_half", "t_stat", "pct_years_positive", "avg_risk_ATR", "avg_R"]
print(d2[d2.subset == "first day of run"][[c for c in keep2 if c in d2]].round(3).to_string(index=False))
print("done", f"{time.time()-t0:.0f}s")
