"""Frozen best rule (20-session efficiency ratio >= 0.50, 2.5 ATR pullback, next open, 1 ATR stop, 5 ATR trail, max 130 sessions), re-run over the WHOLE history 2008 to Nov 2026
with (a) the short-rate futures taken out, (b) micro contracts and ETF stand-ins for the markets one whole contract is too big for, (c) profit by market and by year.

Usage: python er_etf_standins.py futures_prices.parquet report_universe_48_markets.csv OUT_DIR

NO NEW TUNING. The rule is the one frozen in Entry 121. The sealed years (decision dates after 2021-08-06) were opened in Entry 122 and are USED; this script only re-cuts the same rule
three ways: development window (decision dates to 2021-08-06; trades still open at the boundary are counted only up to it), sealed window (decision dates after it, as Entry 122) and the whole history.
Sizing: whole contracts on $300k at 0.15% and 0.25% of the account per ATR, today's contract values, skip a trade if one contract's ATR is above twice the target (as Entries 120 and 122).
Variants: (1) whole contracts only; (2) plus micro Dow (MYM, $0.50 a point), micro Henry Hub natural gas (1,000 mmBtu) and micro copper (2,500 lb) in place of the full-size contracts (multipliers
to be confirmed at the broker); (3) plus ETF stand-ins, fully paid, for markets still too big where a US ETF exists, total ETF cash capped at $150k, simulated on the futures' percent moves
(no tracking error, roll drag or fund fees modelled); (4) upper bound: every skipped trade done at fractional size.
"Short-rate futures" = Fed funds (ZQ), SOFR 1-month (SR1), SOFR 3-month (SR3) and the 2-year note (ZT), as in Entries 120 and 122.
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


# ====================================================================== report section (new)
CUT = pd.Timestamp("2021-08-06")
OTHER_RATES = ["ZB", "UB", "ZN", "TN", "ZF"]
ETF_CAP = 150_000.0
ETF_OK = {"PL": "PPLT", "BZ": "BNO", "RB": "UGA", "UB": "EDV", "ZB": "TLT", "SI": "SLV", "ZW": "WEAT", "ZS": "SOYB", "6S": "FXF", "6E": "FXE", "NQ": "QQQ", "GC": "GLD"}
# No US ETF found for: heating oil (HO), feeder cattle (GF), coffee (KC), cocoa (CC), Dow (use micro MYM), natural gas and copper (micro futures here).
MICRO2 = dict(MICRO); MICRO2.update({"YM": 0.5, "NG": 1000.0, "HG": 2500.0})
MULT2 = np.array([MICRO2.get(ib, MULT_BY_ROOT.get(ib, np.nan)) for ib in names], float)
FACE = {"ZQ": 5e6, "SR1": 5e6, "SR3": 1e6, "ZT": 2e5}


def grp(m):
    if m in SHORT_RATES:
        return "short-rate futures"
    if m in OTHER_RATES:
        return "other interest-rate futures"
    return GROUP_OF.get(m, "other")


tname = TRENDS[0]; nm = TRIGGERS[0][0]
rows0, d0, px0 = dedupe_px(entries[(tname, nm, 20)], (tname, nm, 20))
res_all, held_all = sim(rows0, d0, "trail", 5.0, 130, px=px0)
kp = nonoverlap(rows0, held_all)
rows, d, res, held, px = rows0[kp], d0[kp], res_all[kp], held_all[kp], px0[kp]
N = len(rows)
mk_names = mkt_names[rows]
dec_date = DATE[rows]
is_sealed = np.asarray(dec_date > CUT)
atr_pct = ATR0[rows] / px
P0 = np.zeros(N, int); P1 = np.zeros(N, int)
for i in range(N):
    mid = MK[rows[i]]; loc = rows[i] - MOFF[mid]
    P0[i] = ALLD.searchsorted(pd.Timestamp(MDATES[mid][loc + 1])); P1[i] = ALLD.searchsorted(pd.Timestamp(MDATES[mid][loc + int(held[i])]))
grp_arr = np.array([grp(m) for m in mk_names])
print(f"frozen rule trades (one position per market, 46 markets): {N}; development {int((~is_sealed).sum())}, sealed {int(is_sealed.sum())}; window {ALLD[0].date()} to {ALLD[-1].date()}", flush=True)

SETS = {"all 46 markets": np.ones(N, bool),
        "without short-rate futures (Fed funds, SOFR 1m, SOFR 3m, 2-year note)": ~np.isin(mk_names, SHORT_RATES),
        "without any interest-rate futures": ~np.isin(mk_names, SHORT_RATES + OTHER_RATES)}
WINDOWS = {"development 2008 to Aug 2021": (~is_sealed, ALLD[0], CUT), "sealed Aug 2021 to Nov 2026": (is_sealed, CUT + pd.Timedelta(days=1), ALLD[-1]), "whole history": (np.ones(N, bool), ALLD[0], ALLD[-1])}


def window_stats(usd, opn, heat, lo, hi):
    sel = np.asarray((ALLD >= lo) & (ALLD <= hi)); u = usd[sel]; dts = ALLD[sel]
    eq = np.r_[CAPITAL, CAPITAL + np.cumsum(u)]; peak = np.maximum.accumulate(eq); dd = eq - peak
    r = u / CAPITAL; yrs = len(u) / 252.0
    cal = pd.Series(u, index=dts).groupby(dts.year).sum() / CAPITAL * 100
    cur = 0; longest = 0
    for flag in (eq[1:] < peak[1:]):
        cur = cur + 1 if flag else 0; longest = max(longest, cur)
    sh = lambda x: x.mean() / x.std() * np.sqrt(252) if len(x) > 20 and x.std() > 0 else np.nan
    half = len(u) // 2
    return dict(return_per_year_pct=(eq[-1] - CAPITAL) / CAPITAL * 100 / yrs, vol_per_year_pct=r.std() * np.sqrt(252) * 100, sharpe=sh(r), sharpe_first_half=sh(r[:half]), sharpe_second_half=sh(r[half:]),
                max_drawdown_usd=dd.min(), max_drawdown_pct_of_peak=(dd / peak).min() * 100, longest_underwater_sessions=longest, best_year_pct=cal.max(), worst_year_pct=cal.min(),
                years_positive=f"{int((cal > 0).sum())} of {len(cal)}", max_open_positions=int(opn[sel].max()) if sel.any() else 0, years=yrs)


def apply_cap(cand, notional, cap):
    ok = np.zeros(N, bool); load = np.zeros(len(ALLD))
    for i in np.where(cand)[0][np.argsort(P0[np.where(cand)[0]], kind="stable")]:
        if load[P0[i]:P1[i] + 1].max() + notional[i] <= cap:
            load[P0[i]:P1[i] + 1] += notional[i]; ok[i] = True
    return ok, load


def build(mult, tgt, mode):
    atr_d = atr_pct * REFPX[MK[rows]] * mult[MK[rows]]
    ncon = np.maximum(1.0, np.rint(tgt / atr_d)); w = ncon * atr_d; allowed = atr_d <= 2 * tgt
    is_etf = np.zeros(N, bool); load = np.zeros(len(ALLD))
    if mode in ("etf", "upper"):
        notional = tgt / atr_pct
        cand = ~allowed & (np.isin(mk_names, list(ETF_OK)) if mode == "etf" else np.ones(N, bool))
        if mode == "etf":
            ok, load = apply_cap(cand, notional, ETF_CAP)
        else:
            ok = cand
        w = np.where(ok, tgt, w); is_etf = ok; allowed = allowed | ok
        ncon = np.where(ok, np.nan, ncon)
    return w, allowed, is_etf, ncon, atr_d, load


VARIANTS = {"1 whole contracts only (as Entries 120 and 122)": (MULT, None),
            "2 plus micro Dow, micro natural gas, micro copper": (MULT2, None),
            "3 plus ETF stand-ins where a US ETF exists (cash cap $150k)": (MULT2, "etf"),
            "4 upper bound: every skipped trade at fractional size": (MULT2, "upper")}
out, permkt, bygrp, ledger_rows = [], [], {}, None
for vname, (mult, mode) in VARIANTS.items():
    for tgt_pct in (0.15, 0.25):
        tgt = CAPITAL * tgt_pct / 100.0
        w, allowed, is_etf, ncon, atr_d, load = build(mult, tgt, mode)
        for sname, sm in SETS.items():
            mask = allowed & sm
            for wname, (tm, lo, hi) in WINDOWS.items():
                m2 = mask & tm
                pnl, opn, heat = daily_usd(rows, d, res, held, px, w, m2)
                st = window_stats(pnl, opn, heat, lo, hi)
                x = res[m2]
                top = np.argsort(-x)[:10]; kk = np.ones(len(x), bool); kk[top] = False
                st.update(variant=vname, target_pct_per_ATR=tgt_pct, markets=sname, window=wname, n_trades=int(m2.sum()), skipped_too_big=int((~allowed & sm & tm).sum()),
                          etf_trades=int((is_etf & m2).sum()), win_rate_pct=float((x > 0).mean() * 100) if len(x) else np.nan, avg_ATR_per_trade=float(x.mean()) if len(x) else np.nan,
                          avg_ATR_without_top_10=float(x[kk].mean()) if len(x) > 10 else np.nan, total_profit_usd=float((res[m2] * w[m2]).sum()),
                          peak_etf_cash_usd=float(load.max()) if mode == "etf" else np.nan)
                out.append(st)
        if tgt_pct == 0.25 and vname[0] in "13":
            for wname, (tm, lo, hi) in WINDOWS.items():
                for m_ in names:
                    sel = allowed & tm & (mk_names == m_)
                    if sel.any():
                        permkt.append(dict(variant=vname, window=wname, market=m_, group=grp(m_), trades=int(sel.sum()), profit_usd=float((res[sel] * w[sel]).sum()),
                                           profit_pct_of_account=float((res[sel] * w[sel]).sum() / CAPITAL * 100), win_rate_pct=float((res[sel] > 0).mean() * 100), avg_ATR_per_trade=float(res[sel].mean()),
                                           avg_sessions_held=float(held[sel].mean()), median_contracts=float(np.nanmedian(ncon[sel])) if np.isfinite(ncon[sel]).any() else np.nan,
                                           etf_trades=int((is_etf & sel).sum()), median_atr_pct_of_price=float(np.median(atr_pct[sel]) * 100)))
            yy = {}
            for g_ in sorted(set(grp_arr)):
                pnl, opn, heat = daily_usd(rows, d, res, held, px, w, allowed & (grp_arr == g_))
                yy[g_] = pd.Series(pnl, index=ALLD).groupby(ALLD.year).sum() / CAPITAL * 100
            bygrp[vname] = pd.DataFrame(yy)
            if vname[0] == "1":
                ledger_rows = dict(market=mk_names, group=grp_arr, decision_date=pd.to_datetime(dec_date).date, direction=d.astype(int), sessions_held=held, result_ATR_net=res, atr_pct_of_price=atr_pct * 100,
                                   contracts=ncon, dollars_per_ATR=w, allowed=allowed, sealed=is_sealed, profit_usd=res * w * allowed)
    print(f"done variant {vname[:50]} ({time.time()-t0:.0f}s)", flush=True)
S = pd.DataFrame(out)
S.to_csv(f"{out_dir}/summary_all_windows.csv", index=False)
pd.DataFrame(permkt).to_csv(f"{out_dir}/per_market_profit.csv", index=False)
for v_, df_ in bygrp.items():
    df_.round(2).to_csv(f"{out_dir}/by_group_by_year_variant{v_[0]}_at_0.25pct.csv")
pd.DataFrame(ledger_rows).to_csv(f"{out_dir}/trade_ledger_variant1_at_0.25pct.csv", index=False)
pd.set_option("display.width", 330); pd.set_option("display.max_columns", 40); pd.set_option("display.max_rows", 600); pd.set_option("display.max_colwidth", 60)
show = ["target_pct_per_ATR", "markets", "n_trades", "skipped_too_big", "etf_trades", "win_rate_pct", "avg_ATR_per_trade", "avg_ATR_without_top_10", "return_per_year_pct", "vol_per_year_pct", "sharpe", "max_drawdown_pct_of_peak", "longest_underwater_sessions", "best_year_pct", "worst_year_pct", "years_positive", "peak_etf_cash_usd"]
for wname in WINDOWS:
    for vname in VARIANTS:
        v = S[(S.window == wname) & (S.variant == vname)].sort_values(["target_pct_per_ATR", "markets"])
        v = v.assign(markets=v.markets.str.slice(0, 24))
        print(f"\n==== {wname} | {vname} ===="); print(v[show].round(2).to_string(index=False))
print("\n==== profit by group and year, variant 1 at 0.25% (percent of $300k) ===="); print(bygrp[list(bygrp)[0]].round(1).to_string())
print("\n==== profit by group and year, variant 3 at 0.25% ===="); print(bygrp[[k for k in bygrp if k[0] == "3"][0]].round(1).to_string())
pm = pd.DataFrame(permkt)
for wname in WINDOWS:
    v = pm[(pm.window == wname) & (pm.variant.str[0] == "1")].sort_values("profit_usd", ascending=False)
    print(f"\n==== per market profit, variant 1 at 0.25%, {wname} ===="); print(v.drop(columns=["variant", "window"]).round(2).to_string(index=False))
for m_ in SHORT_RATES:
    sel = (mk_names == m_)
    print(f"{m_}: face value per contract ${FACE[m_]:,.0f}; contracts per trade at 0.25% target median {np.nanmedian(np.maximum(1, np.rint(750 / (atr_pct[sel] * REFPX[MK[rows]][sel] * MULT[MK[rows]][sel])))):.0f}")
print("done", f"{time.time()-t0:.0f}s")
