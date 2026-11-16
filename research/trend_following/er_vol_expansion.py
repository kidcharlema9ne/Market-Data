"""Why did the short-rate (and other) trades pay so much: volatility expansion or plain trendiness? Plus a cap on short-rate position size. Frozen best rule, whole history 2008 to Nov 2026.

Usage: python er_vol_expansion.py futures_prices.parquet report_universe_48_markets.csv OUT_DIR

NO TUNING. Same signals, exits, costs as Entries 121 to 124. Whole contracts on $300k at 0.25% per ATR (and 0.15% for the cap test), today's contract values, one contract too big -> skip.
Per trade (variant 1, whole contracts only) it records:
 - entry ATR as a percentile of the market's previous 250 sessions (was the position sized in a quiet period?)
 - how far ATR expanded during the hold: highest ATR / entry ATR, and the average ATR over the hold / entry ATR
 - result in entry-ATR units (what the portfolio books) and the same trade re-measured in CURRENT-ATR units (each day's price change divided by that day's prior ATR, i.e. a position that is
   re-sized every day to keep its risk constant); if the second figure is small, the profit came from volatility expanding while the position stayed the same size
 - path efficiency over the hold (net move divided by the sum of daily moves) and the net move expressed in entry ATRs per session held
Then profit by trade group (short-rate futures, other interest rates, everything else; top 10 trades vs the rest), and the dollars the trades would have made if re-sized daily.
Short-rate cap test: contracts in ZQ, SR1, SR3, ZT limited to 5, 10, 20 (and uncapped), whole history, development and sealed windows, 0.15% and 0.25%.
"""
import sys
from pathlib import Path
import time
import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

prices_path, uni_path, out_dir = sys.argv[1:4]
DEV_START, DEV_END = pd.Timestamp("2007-12-01"), pd.Timestamp("2030-01-01")      # load from mid-2020 only to warm up the indicators
TEST_START = pd.Timestamp("2008-02-01")                                         # the sealed years begin here
SPLIT = pd.Timestamp("2015-01-01")
FW = 130
COST_RT = 0.10
ATRW = 20
XS = (1.5, 2.0, 2.5, 3.0)
NS = (20,)
NMAX = max(NS)
EXITS = [("time", None, 20), ("time", None, 60)] + [("trail", mm, cap) for mm in (3.0, 4.0, 5.0, 6.0) for cap in (60, 90, 130)]
PRICE_MAP = {"6A": "A6", "6B": "B6", "6C": "AD", "6E": "E6", "6J": "J1", "6L": "BR", "6M": "MP", "6N": "N6", "6S": "E1", "ZB": "US", "BRR": "BTC", "LBR": "LBS"}
GROUPS = {"grains": ["ZW", "KE", "ZC", "ZS", "ZL", "ZM"], "energy": ["HO", "NG", "CL", "BZ", "RB"], "softs": ["CT", "CC", "SB", "KC"], "meats": ["HE", "LE", "GF"],
          "metals": ["PL", "SI", "HG", "GC"], "currencies": ["6A", "6B", "6C", "6E", "6J", "6M", "6N", "6S", "6L", "DX"],
          "rates": ["ZB", "UB", "ZN", "TN", "ZF", "ZT", "ZQ", "SR1", "SR3"], "stock indexes": ["YM", "ES", "MES", "NQ", "MNQ", "RTY"], "volatility": ["VX"]}
GROUP_OF = {m: g for g, ms in GROUPS.items() for m in ms}
TRENDS = ["20-session ratio at least 0.50 alone", "40-session ratio at least 0.35 alone", "20-session at least 0.50 AND 40-session at least 0.35", "20-session at least 0.50 OR 40-session at least 0.35", "control: no ratio, every 5th session, 20-session direction"]
TRIGGERS = [("market entry: 2.5 ATR pullback, next open (marked best)", 2.5, [])]
LIMITS = []
for X_ in ():
    LIMITS.append((f"buy limit {X_} ATR below the best price since the signal, filled on touch", X_, 0.0))
    LIMITS.append((f"buy limit {X_} ATR below the best price since the signal, filled only if price trades 0.1 ATR through", X_, 0.1))
PXD = {}
ATRSER = {}
t0 = time.time()

px = pd.read_parquet(prices_path)
px["file_date"] = pd.to_datetime(px["file_date"])
px = px[(px["file_date"] >= DEV_START) & (px["file_date"] <= DEV_END)].copy()
assert px["file_date"].max() <= DEV_END
print(f"development rows {len(px):,}; {px['file_date'].min().date()} to {px['file_date'].max().date()}; indicator warm-up from 2020-06; trades counted only from 2021-08-07")
uni = pd.read_csv(uni_path)
YEARS = (DEV_END - DEV_START).days / 365.25

FO, FH, FL, FC, FA = [], [], [], [], []
DATE, MK, ATR0 = [], [], []
entries = {}          # (trend, X, N) -> list of (global row, direction)
offset = 0
names = []
MDATES, MOFF = [], []


def add(key, row, d, px=None):
    entries.setdefault(key, []).append((row, d))
    if px is not None:
        PXD.setdefault(key, {})[row] = px


for mid, ib in enumerate(uni["ibkr"]):
    if ib in ("MES", "MNQ"):
        continue
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
    ATRSER[ib] = atr.copy()
    cs = pd.Series(c)
    m = n - FW                      # decision days 0..m-1 have a full forward path
    names.append(ib); MDATES.append(g['file_date'].to_numpy()); MOFF.append(offset)
    er, dr = {}, {}
    for w in (20, 40):
        path = pd.Series(np.abs(np.diff(c, prepend=np.nan))).rolling(w).sum()
        er[w] = ((cs - cs.shift(w)).abs() / path).to_numpy()
        dr[w] = np.sign(cs - cs.shift(w)).fillna(0).to_numpy()
    q20 = np.isfinite(er[20]) & (er[20] >= 0.50) & (dr[20] != 0)
    q40 = np.isfinite(er[40]) & (er[40] >= 0.35) & (dr[40] != 0)
    qb = q20 & q40 & (dr[20] == dr[40])
    qe = q20 | q40
    d_e = np.sign(q20 * dr[20] + q40 * dr[40])
    rng = h - l
    locn = pd.Series(np.where(rng > 0, (c - l) / np.where(rng > 0, rng, 1), 0.5))
    ph, pl_, pcl = np.r_[np.nan, h[:-1]], np.r_[np.nan, l[:-1]], np.r_[np.nan, c[:-1]]
    rs = pd.Series(rng)
    gain = pd.Series(np.maximum(np.diff(c, prepend=np.nan), 0)).rolling(2).mean(); loss = pd.Series(np.maximum(-np.diff(c, prepend=np.nan), 0)).rolling(2).mean()
    rsi2 = (100 * gain / (gain + loss).where((gain + loss) > 0)).to_numpy()
    ema10 = cs.ewm(span=10, adjust=False).mean().to_numpy()
    atr_ratio = (pd.Series(atr) / pd.Series(atr).rolling(100).mean()).to_numpy()
    tr100 = (cs - cs.shift(100)).to_numpy()
    nr7 = (rs <= rs.rolling(7).min()).to_numpy(); nr4 = (rs <= rs.rolling(4).min()).to_numpy()
    CD = {}
    for dn_ in (1, -1):
        ag = dn_ * (c - pcl)                                        # change against (negative) or with (positive) the trend direction
        cc = {"inside": (h < ph) & (l > pl_), "nr7": nr7, "nr4": nr4, "narrow": rng <= 0.7 * atr,
              "wide_ctr": (rng >= 1.5 * atr) & (dn_ * (c - o) < 0),
              "hammer": (rng >= 1.5 * atr) & ((locn.to_numpy() >= 0.75) if dn_ > 0 else (locn.to_numpy() <= 0.25)),
              "weak_close": (locn.to_numpy() <= 0.25) if dn_ > 0 else (locn.to_numpy() >= 0.75),
              "bounce": (ag > 0) & (dn_ * (c - o) > 0),
              "down3": (ag < 0) & (np.r_[np.nan, ag[:-1]] < 0) & (np.r_[np.nan, np.nan, ag[:-2]] < 0),
              "down4": (ag < 0) & (np.r_[np.nan, ag[:-1]] < 0) & (np.r_[np.nan, np.nan, ag[:-2]] < 0) & (np.r_[np.nan, np.nan, np.nan, ag[:-3]] < 0),
              "rsi2": (rsi2 <= 10) if dn_ > 0 else (rsi2 >= 90),
              "below_ema": dn_ * (ema10 - c) / atr >= 2.0,
              "trend100": dn_ * tr100 > 0, "calm": atr_ratio < 1.0, "hot": atr_ratio >= 1.0}
        for k_, v_ in cc.items():
            CD[(k_, dn_)] = np.nan_to_num(np.asarray(v_, dtype=float), nan=0.0) > 0
    okatr = np.isfinite(atr) & (atr > 1e-5 * c)
    defs = {TRENDS[0]: (q20 & okatr, dr[20]),
            TRENDS[1]: (q40 & okatr, dr[40]),
            TRENDS[2]: (qb & okatr, dr[20]),
            TRENDS[3]: (qe & (d_e != 0) & okatr, d_e),
            TRENDS[4]: (((np.arange(n) % 5) == 0) & (dr[20] != 0) & okatr, dr[20])}
    defs = {k_: v_ for k_, v_ in defs.items() if k_ == TRENDS[0]}
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
            for t in range(s + 1, min(s + 20, m - 1) + 1):
                peak = max(peak, h[t]) if dn > 0 else min(peak, l[t])
                a = atr[t]
                if not (a == a and a > 0):
                    continue
                dep = (peak - c[t]) / a if dn > 0 else (c[t] - peak) / a
                for nm, pm, cl in TRIGGERS:
                    if nm in hit:
                        continue
                    if pm is not None and dep < pm:
                        continue
                    if all(CD[(cn, int(dn))][t] for cn in cl):
                        hit[nm] = t
                if len(hit) == len(TRIGGERS):
                    break
            for nm, t in hit.items():
                add((tname, nm, 20), offset + t, dn)
            peakL = h[s] if dn > 0 else l[s]
            filled = {}
            for t in range(s, min(s + 19, m - 1) + 1):
                if t > s:
                    peakL = max(peakL, h[t]) if dn > 0 else min(peakL, l[t])
                a_ = atr[t]
                if not (a_ == a_ and a_ > 0) or t + 1 >= n:
                    continue
                for nm, X_, thr in LIMITS:
                    if nm in filled:
                        continue
                    if dn > 0:
                        lv = peakL - X_ * a_
                        if l[t + 1] <= lv - thr * a_:
                            filled[nm] = (t, min(o[t + 1], lv))
                    else:
                        lv = peakL + X_ * a_
                        if h[t + 1] >= lv + thr * a_:
                            filled[nm] = (t, max(o[t + 1], lv))
                if len(filled) == len(LIMITS):
                    break
            for nm, (t, pxf) in filled.items():
                add((tname, nm, 20), offset + t, dn, pxf)
    for lst, arr in ((FO, o), (FH, h), (FL, l), (FC, c), (FA, atr)):
        lst.append(sliding_window_view(arr[1:], FW)[:m])
    DATE.append(g["file_date"].to_numpy()[:m]); MK.append(np.full(m, len(names) - 1)); ATR0.append(atr[:m])
    offset += m
O, H, L, C, A = (np.concatenate(x) for x in (FO, FH, FL, FC, FA))
DATE = pd.DatetimeIndex(np.concatenate(DATE)); MK = np.concatenate(MK); ATR0 = np.concatenate(ATR0)
mkt_names = np.array(names)[MK]
print(f"{len(names)} markets; {offset:,} decision days; {sum(len(v) for v in entries.values()):,} entries across {len(entries)} combinations; {time.time()-t0:.0f}s", flush=True)


def sim(rows, d, kind, mm, cap, px=None):
    Oo, Hh, Ll, Cc, Aa = (M[rows][:, :cap] for M in (O, H, L, C, A))
    n = len(rows)
    entry = Oo[:, 0] if px is None else px
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


def nonoverlap(rows, held):
    """One open position per market: skip an entry whose decision day falls before the previous kept trade of that market has exited."""
    keep = np.zeros(len(rows), bool)
    last = {}
    for i in range(len(rows)):
        mk = MK[rows[i]]
        if rows[i] >= last.get(mk, -1):
            keep[i] = True
            last[mk] = rows[i] + held[i]
    return keep


def dedupe(lst):
    rows = np.array([r for r, _ in lst]); d = np.array([x for _, x in lst], float)
    rows, idx = np.unique(rows, return_index=True)
    return rows, d[idx]



def label(e):
    return f"time exit {e[2]}" if e[0] == "time" else f"trail {e[1]:g} ATR, max {e[2]}"


CAPITAL = 300_000.0
SHORT_RATES = ["ZQ", "SR1", "SR3", "ZT"]
tu = pd.read_csv(str(Path(uni_path).parent / "trend_universe.csv"))
MULT_BY_ROOT = dict(zip(tu["ibkr_root"], tu["multiplier"]))
MICRO = {"ES": 5, "NQ": 2, "GC": 10, "CL": 100, "SI": 1000, "RTY": 5}      # micro contracts traded on the (identical-price) full-size history
MULT = np.array([MICRO.get(ib, MULT_BY_ROOT.get(ib, np.nan)) for ib in names], float)
assert np.isfinite(MULT).all(), [ib for ib, mu in zip(names, MULT) if not np.isfinite(mu)]
cs_ = pd.read_csv(str(Path(__file__).resolve().parent / "results" / "contract_size_atr20.csv"))
LAST_CLOSE = dict(zip(cs_["price_symbol"], cs_["last_close"]))      # today's real front-contract prices (ratio back-adjusted series end on the real price)
REFPX = np.array([LAST_CLOSE.get(PRICE_MAP.get(ib, ib), np.nan) for ib in names], float)
assert np.isfinite(REFPX).all(), [ib for ib, v_ in zip(names, REFPX) if not np.isfinite(v_)]
ALLD = pd.DatetimeIndex(sorted(set(np.concatenate(MDATES))))
ALLD = ALLD[(ALLD >= TEST_START)]
YEARS = len(ALLD) / 252.0
SPLIT = ALLD[len(ALLD) // 2]
pos_of = {d_: i_ for i_, d_ in enumerate(ALLD)}
SPLIT_I = np.asarray(ALLD < SPLIT)


def dedupe_px(lst, key):
    rows = np.array([r for r, _ in lst]); d = np.array([x for _, x in lst], float)
    rows, idx = np.unique(rows, return_index=True)
    d = d[idx]
    keep_ = np.asarray(DATE[rows] >= TEST_START)
    rows, d = rows[keep_], d[keep_]
    px = np.array([PXD[key][r] for r in rows]) if key in PXD else O[rows, 0]
    return rows, d, px


def daily_usd(rows, d, res, held, px, w, mask):
    """Daily mark-to-market dollars. w = dollars per 1 entry-ATR for each trade. Net result (cost included) booked on the exit day."""
    pnl = np.zeros(len(ALLD)); opn = np.zeros(len(ALLD)); heat = np.zeros(len(ALLD))
    for i in np.where(mask)[0]:
        r = rows[i]; mid = MK[r]; loc = r - MOFF[mid]; h_ = int(held[i]); dn = d[i]; a0 = ATR0[r]; en = px[i]; cp = 0.0
        for j in range(1, h_ + 1):
            cum = res[i] if j == h_ else dn * (C[r, j - 1] - en) / a0
            p = pos_of.get(pd.Timestamp(MDATES[mid][loc + j]))
            if p is not None:
                pnl[p] += (cum - cp) * w[i]; opn[p] += 1; heat[p] += w[i]
            cp = cum
    return pnl, opn, heat


def stats_usd(usd, opn, heat):
    eq = CAPITAL + np.cumsum(usd); peak = np.maximum.accumulate(eq); dd = eq - peak
    r = usd / CAPITAL; yrs = len(ALLD) / 252.0
    cal = pd.Series(usd, index=ALLD).groupby(ALLD.year).sum() / CAPITAL * 100
    cur = 0; longest = 0
    for u in (eq < peak):
        cur = cur + 1 if u else 0; longest = max(longest, cur)
    sh = lambda x: x.mean() / x.std() * np.sqrt(252) if x.std() > 0 else np.nan
    return dict(return_per_year_pct=(eq[-1] - CAPITAL) / CAPITAL * 100 / yrs, vol_per_year_pct=r.std() * np.sqrt(252) * 100, sharpe=sh(r), sharpe_first_half=sh(r[SPLIT_I]), sharpe_second_half=sh(r[~SPLIT_I]),
                max_drawdown_usd=dd.min(), max_drawdown_pct_of_peak=(dd / peak).min() * 100, longest_underwater_sessions=longest, worst_year_pct=cal.min(), best_year_pct=cal.max(),
                years_positive=f"{int((cal > 0).sum())} of {len(cal)}", avg_open_positions=float(opn.mean()), max_open_positions=int(opn.max()),
                avg_risk_per_ATR_open_pct=float(heat.mean() / CAPITAL * 100), max_risk_per_ATR_open_pct=float(heat.max() / CAPITAL * 100)), cal


# ====================================================================== report section (volatility expansion and short-rate cap)
CUT = pd.Timestamp("2021-08-06")
OTHER_RATES = ["ZB", "UB", "ZN", "TN", "ZF"]
tname = TRENDS[0]; nm = TRIGGERS[0][0]
rows0, d0, px0 = dedupe_px(entries[(tname, nm, 20)], (tname, nm, 20))
res_all, held_all = sim(rows0, d0, "trail", 5.0, 130, px=px0)
kp = nonoverlap(rows0, held_all)
rows, d, res, held, px = rows0[kp], d0[kp], res_all[kp], held_all[kp], px0[kp]
N = len(rows)
mk_names = mkt_names[rows]
is_sealed = np.asarray(DATE[rows] > CUT)
atr_pct = ATR0[rows] / px
grp_arr = np.where(np.isin(mk_names, SHORT_RATES), "short-rate futures", np.where(np.isin(mk_names, OTHER_RATES), "other interest-rate futures", "everything else"))
print(f"trades {N}; short-rate {int((grp_arr=='short-rate futures').sum())}", flush=True)

# ---- per-trade volatility diagnostics
pct_entry = np.full(N, np.nan); max_exp = np.zeros(N); avg_exp = np.zeros(N); res_cur = np.zeros(N); eff = np.zeros(N); move_per_sess = np.zeros(N); end_pct = np.full(N, np.nan)
for i in range(N):
    mid = MK[rows[i]]; loc = rows[i] - MOFF[mid]; ib = names[mid]
    ser = ATRSER[ib]; a0 = ATR0[rows[i]]
    hist = ser[max(0, loc - 250):loc]; hist = hist[np.isfinite(hist)]
    if len(hist) > 50:
        pct_entry[i] = float((hist < a0).mean() * 100)
    h_ = int(held[i])
    path_a = A[rows[i], :h_]                      # ATR as of the close of each session in the hold (session 1 = entry session)
    path_c = C[rows[i], :h_]
    ok = np.isfinite(path_a)
    max_exp[i] = np.nanmax(path_a[ok]) / a0 if ok.any() else np.nan
    avg_exp[i] = np.nanmean(path_a[ok]) / a0 if ok.any() else np.nan
    # re-sized daily: each session's change divided by the prior session's ATR (entry ATR for the first)
    prev_c = np.r_[px[i], path_c[:-1]]; prev_a = np.r_[a0, path_a[:-1]]
    prev_a = np.where(np.isfinite(prev_a) & (prev_a > 0), prev_a, a0)
    steps = d[i] * (path_c - prev_c)
    # last session: replace the close by the actual exit price implied by the result
    exit_px = px[i] + d[i] * (res[i] + COST_RT) * a0
    steps[-1] = d[i] * (exit_px - prev_c[-1])
    res_cur[i] = float((steps / prev_a).sum() - COST_RT)
    gross = np.abs(np.diff(np.r_[px[i], path_c[:-1], exit_px])).sum()
    eff[i] = abs(exit_px - px[i]) / gross if gross > 0 else np.nan
    move_per_sess[i] = (res[i] + COST_RT) / max(h_, 1)
    end_pct[i] = np.nan

tgt = CAPITAL * 0.25 / 100
atr_d = atr_pct * REFPX[MK[rows]] * MULT[MK[rows]]
ncon = np.maximum(1.0, np.rint(tgt / atr_d)); w = ncon * atr_d; allowed = atr_d <= 2 * tgt
usd = res * w * allowed; usd_cur = res_cur * w * allowed
T = pd.DataFrame(dict(market=mk_names, group=grp_arr, decision_date=pd.to_datetime(DATE[rows]).date, direction=d.astype(int), sessions_held=held, result_ATR_entry_units=res, result_ATR_resized_daily=res_cur,
                      entry_ATR_percentile_vs_prior_250=pct_entry, max_ATR_over_entry_ATR=max_exp, avg_ATR_over_entry_ATR=avg_exp, path_efficiency=eff, entry_ATRs_per_session=move_per_sess,
                      contracts=ncon, dollars_per_ATR=w, allowed=allowed, sealed=is_sealed, profit_usd=usd, profit_usd_if_resized_daily=usd_cur))
T.to_csv(f"{out_dir}/vol_expansion_trade_table.csv", index=False)
A_ = T[T.allowed].copy()
A_["rank"] = A_.profit_usd.rank(ascending=False, method="first")
A_["bucket"] = np.where(A_["rank"] <= 10, "10 biggest trades", np.where(A_.group == "short-rate futures", "other short-rate trades", "all other trades"))
pd.set_option("display.width", 300); pd.set_option("display.max_columns", 40); pd.set_option("display.max_rows", 200)
print("\n==== trade buckets (whole contracts, 0.25%, whole history) ====")
g = A_.groupby("bucket").agg(trades=("profit_usd", "size"), profit_usd=("profit_usd", "sum"), profit_if_resized_daily_usd=("profit_usd_if_resized_daily", "sum"), avg_result_ATR=("result_ATR_entry_units", "mean"),
                              avg_result_resized_ATR=("result_ATR_resized_daily", "mean"), median_entry_ATR_percentile=("entry_ATR_percentile_vs_prior_250", "median"),
                              median_max_ATR_expansion=("max_ATR_over_entry_ATR", "median"), median_avg_ATR_expansion=("avg_ATR_over_entry_ATR", "median"), median_path_efficiency=("path_efficiency", "median"),
                              median_sessions_held=("sessions_held", "median"))
print(g.round(2).to_string())
print("\n==== trade group (short rates / other rates / everything else) ====")
g = A_.groupby("group").agg(trades=("profit_usd", "size"), profit_usd=("profit_usd", "sum"), profit_if_resized_daily_usd=("profit_usd_if_resized_daily", "sum"), avg_result_ATR=("result_ATR_entry_units", "mean"),
                             avg_result_resized_ATR=("result_ATR_resized_daily", "mean"), median_entry_ATR_percentile=("entry_ATR_percentile_vs_prior_250", "median"),
                             median_max_ATR_expansion=("max_ATR_over_entry_ATR", "median"), median_avg_ATR_expansion=("avg_ATR_over_entry_ATR", "median"), median_path_efficiency=("path_efficiency", "median"))
print(g.round(2).to_string())
print("\n==== the 15 biggest trades ====")
print(A_.sort_values("profit_usd", ascending=False).head(15)[["market", "decision_date", "direction", "sessions_held", "result_ATR_entry_units", "result_ATR_resized_daily", "entry_ATR_percentile_vs_prior_250",
                                                              "max_ATR_over_entry_ATR", "avg_ATR_over_entry_ATR", "path_efficiency", "contracts", "profit_usd", "profit_usd_if_resized_daily"]].round(2).to_string(index=False))
print("\n==== winners over 10 ATR (entry units): how many kept more than half their size when re-sized daily? ====")
big = A_[A_.result_ATR_entry_units > 10]
print(len(big), "trades;", int((big.result_ATR_resized_daily > 0.5 * big.result_ATR_entry_units).sum()), "kept over half;", "median entry ATR percentile", round(big.entry_ATR_percentile_vs_prior_250.median(), 1), "; median max ATR expansion", round(big.max_ATR_over_entry_ATR.median(), 2))
print("all trades: median entry ATR percentile", round(A_.entry_ATR_percentile_vs_prior_250.median(), 1), "; median max expansion", round(A_.max_ATR_over_entry_ATR.median(), 2))
# correlation of result with expansion
print("\ncorrelation of result (entry ATR units) with max ATR expansion: %.2f; with entry ATR percentile: %.2f" % (A_.result_ATR_entry_units.corr(A_.max_ATR_over_entry_ATR), A_.result_ATR_entry_units.corr(A_.entry_ATR_percentile_vs_prior_250)))

# ---- short-rate cap test
ALLD2 = ALLD
def stats_win(usd_, opn, heat, lo, hi):
    sel = np.asarray((ALLD >= lo) & (ALLD <= hi)); u = usd_[sel]
    eq = np.r_[CAPITAL, CAPITAL + np.cumsum(u)]; peak = np.maximum.accumulate(eq); dd = eq - peak; r = u / CAPITAL
    sh = lambda x: x.mean() / x.std() * np.sqrt(252) if len(x) > 20 and x.std() > 0 else np.nan
    return (eq[-1] - CAPITAL) / CAPITAL * 100 / (len(u) / 252.0), r.std() * np.sqrt(252) * 100, sh(r), (dd / peak).min() * 100, dd.min()
WIN = {"development": (~is_sealed, ALLD[0], CUT), "sealed": (is_sealed, CUT + pd.Timedelta(days=1), ALLD[-1]), "whole history": (np.ones(N, bool), ALLD[0], ALLD[-1])}
isSR = np.isin(mk_names, SHORT_RATES)
rows_out = []
for tp in (0.15, 0.25):
    tg = CAPITAL * tp / 100
    ad = atr_pct * REFPX[MK[rows]] * MULT[MK[rows]]
    for capn in (None, 20, 10, 5, 2):
        nc = np.maximum(1.0, np.rint(tg / ad))
        if capn:
            nc = np.where(isSR, np.minimum(nc, capn), nc)
        ww = nc * ad; al = ad <= 2 * tg
        for wn, (tm, lo, hi) in WIN.items():
            m2 = al & tm
            pnl, opn, heat = daily_usd(rows, d, res, held, px, ww, m2)
            rt, vol, sh, ddp, ddu = stats_win(pnl, opn, heat, lo, hi)
            rows_out.append(dict(target_pct=tp, short_rate_contract_cap=capn or "none", window=wn, return_per_year_pct=rt, vol_pct=vol, sharpe=sh, max_drawdown_pct=ddp, max_drawdown_usd=ddu,
                                 short_rate_profit_usd=float((res * ww)[m2 & isSR].sum()), total_profit_usd=float((res * ww)[m2].sum()), max_short_rate_contracts_in_a_trade=float(nc[m2 & isSR].max()) if (m2 & isSR).any() else np.nan))
C_ = pd.DataFrame(rows_out)
C_.to_csv(f"{out_dir}/short_rate_cap_test.csv", index=False)
print("\n==== short-rate contract cap (whole contracts, whole history first) ====")
for wn in ("whole history", "development", "sealed"):
    print(f"\n-- {wn} --"); print(C_[C_.window == wn].drop(columns=["window"]).round(2).to_string(index=False))
print("done", f"{time.time()-t0:.0f}s")
