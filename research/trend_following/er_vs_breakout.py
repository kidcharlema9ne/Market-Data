"""Head-to-head: the frozen best rule (20-session efficiency ratio >= 0.50, 2.5 ATR pullback, 1 ATR stop, 5 ATR trail) versus the earlier outright-strength system
(20-session close breakout + 20-session efficiency ratio >= 0.60, enter next open, 3 ATR initial stop, then 3 ATR trailing stop from the best close, no time stop beyond the 130-session
data window), same 46 markets, same years, same costs (0.05 ATR a side), whole contracts on $300k (and fractional for reference), Fed funds / SOFR 1m / SOFR 3m / 2-year note capped at 10 contracts.

Usage: python er_vs_breakout.py futures_prices.parquet report_universe_48_markets.csv OUT_DIR

NO TUNING of either system. The earlier system is the PRIMARY of Entry 100 (baseline_breakout.py): its rule is re-implemented here on the same engine so both systems see identical sizing,
contract values, costs and windows. Windows: development (decision dates to 2021-08-06; trades open at the boundary counted only up to it), sealed (decision dates after it), whole history.
Sizing per ATR: whole contracts at 0.15% and 0.25% of $300k per ATR (skip a trade if one contract's ATR is above twice the target); fractional at 0.25% and at 0.0833% (the earlier system's 3 ATR
stop then risks 0.25% of the account, the same as the frozen rule's 1 ATR stop at 0.25% per ATR).
Also: 50/50 mix of the two systems, daily return correlation, profit by year.
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
    # ---- earlier outright-strength system: 20-session close breakout + 20-session efficiency ratio >= 0.60, entry at the next open
    mx20 = pd.Series(c).shift(1).rolling(20).max().to_numpy(); mn20 = pd.Series(c).shift(1).rolling(20).min().to_numpy()
    q60 = np.isfinite(er[20]) & (er[20] >= 0.60) & okatr
    for t_ in range(20, m):
        if not q60[t_] or t_ + 1 >= n:
            continue
        if c[t_] > mx20[t_]:
            add(("baseline", "20-session breakout", 20), offset + t_, 1.0)
        elif c[t_] < mn20[t_]:
            add(("baseline", "20-session breakout", 20), offset + t_, -1.0)
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


# ====================================================================== report section (head to head)
CUT = pd.Timestamp("2021-08-06")
CAP_SR = 10


def sim_init(rows_, d_, init, mm, cap, px_):
    """Same engine as sim(), with an initial stop of `init` ATR from the entry price."""
    Oo, Hh, Ll, Cc, Aa = (M[rows_][:, :cap] for M in (O, H, L, C, A))
    n_ = len(rows_); entry = px_; atr0 = ATR0[rows_]; long = d_ > 0
    stop = entry - d_ * init * atr0; best = entry.copy(); res_ = np.full(n_, np.nan); held_ = np.zeros(n_, int); alive = np.ones(n_, bool)
    for k in range(cap):
        o_, h_, l_, c_, a_ = Oo[:, k], Hh[:, k], Ll[:, k], Cc[:, k], Aa[:, k]
        hit = alive & np.where(long, l_ <= stop, h_ >= stop)
        gap = np.where(long, o_ <= stop, o_ >= stop) if k > 0 else np.zeros(n_, bool)
        pxs = np.where(gap, o_, stop)
        res_[hit] = (d_ * (pxs - entry) / atr0)[hit]; held_[hit] = k + 1; alive &= ~hit
        best = np.where(alive, np.where(long, np.maximum(best, c_), np.minimum(best, c_)), best)
        new = best - d_ * mm * a_
        stop = np.where(alive & np.isfinite(new), np.where(long, np.maximum(stop, new), np.minimum(stop, new)), stop)
        if k == cap - 1:
            res_[alive] = (d_ * (c_ - entry) / atr0)[alive]; held_[alive] = k + 1
    return res_ - COST_RT, held_


def prepare(key, init, mm):
    rows0, d0, px0 = dedupe_px(entries[key], key)
    r0, h0 = sim_init(rows0, d0, init, mm, 130, px0)
    kp = nonoverlap(rows0, h0)
    rr, dd_, res_, hh_, px_ = rows0[kp], d0[kp], r0[kp], h0[kp], px0[kp]
    return dict(rows=rr, d=dd_, res=res_, held=hh_, px=px_, mk=mkt_names[rr], sealed=np.asarray(DATE[rr] > CUT), atr_pct=ATR0[rr] / px_, n=len(rr))


SYSTEMS = {"frozen best rule (pullback entry, 1 ATR stop, 5 ATR trail)": prepare((TRENDS[0], TRIGGERS[0][0], 20), 1.0, 5.0),
           "earlier system (20-session breakout, ratio 0.6, 3 ATR stop, 3 ATR trail)": prepare(("baseline", "20-session breakout", 20), 3.0, 3.0)}
for k_, v_ in SYSTEMS.items():
    print(f"{k_}: {v_['n']} trades (development {int((~v_['sealed']).sum())}, sealed {int(v_['sealed'].sum())}); median sessions held {np.median(v_['held']):.0f}; win rate {100*(v_['res']>0).mean():.1f}%", flush=True)

SIZINGS = [("whole contracts", 0.15, CAP_SR), ("whole contracts", 0.25, CAP_SR), ("fractional", 0.25, CAP_SR), ("fractional", 0.0833, CAP_SR), ("whole contracts", 0.15, None), ("whole contracts", 0.25, None)]


def sizing(sysd, kind, tp, cap):
    tgt = CAPITAL * tp / 100.0
    isSR = np.isin(sysd["mk"], SHORT_RATES)
    ad = sysd["atr_pct"] * REFPX[MK[sysd["rows"]]] * MULT[MK[sysd["rows"]]]
    if kind.startswith("whole"):
        nc = np.maximum(1.0, np.rint(tgt / ad))
        if cap:
            nc = np.where(isSR, np.minimum(nc, cap), nc)
        return nc * ad, ad <= 2 * tgt
    w_ = np.full(len(ad), tgt)
    if cap:
        w_ = np.where(isSR, np.minimum(w_, cap * ad), w_)
    return w_, np.ones(len(ad), bool)


def wstats(usd_, opn, lo, hi):
    sel = np.asarray((ALLD >= lo) & (ALLD <= hi)); u = usd_[sel]; dts = ALLD[sel]
    eq = np.r_[CAPITAL, CAPITAL + np.cumsum(u)]; peak = np.maximum.accumulate(eq); dd = eq - peak; r = u / CAPITAL
    cal = pd.Series(u, index=dts).groupby(dts.year).sum() / CAPITAL * 100
    cur = 0; longest = 0
    for fl in (eq[1:] < peak[1:]):
        cur = cur + 1 if fl else 0; longest = max(longest, cur)
    sh = lambda x: x.mean() / x.std() * np.sqrt(252) if len(x) > 20 and x.std() > 0 else np.nan
    return dict(return_per_year_pct=(eq[-1] - CAPITAL) / CAPITAL * 100 / (len(u) / 252.0), vol_per_year_pct=r.std() * np.sqrt(252) * 100, sharpe=sh(r), max_drawdown_pct=(dd / peak).min() * 100,
                max_drawdown_usd=dd.min(), longest_underwater_sessions=longest, years_positive=f"{int((cal > 0).sum())} of {len(cal)}", best_year_pct=cal.max(), worst_year_pct=cal.min(),
                max_open_positions=int(opn[sel].max()) if sel.any() else 0), cal


WIN = {"development 2008 to Aug 2021": (lambda s_: ~s_, ALLD[0], CUT), "sealed Aug 2021 to Nov 2026": (lambda s_: s_, CUT + pd.Timedelta(days=1), ALLD[-1]), "whole history": (lambda s_: np.ones(len(s_), bool), ALLD[0], ALLD[-1])}
out, yearly, daily_store = [], {}, {}
for (kind, tp, cap) in SIZINGS:
    lab = f"{kind} {tp}% per ATR" + (f", short rates capped at {cap} contracts" if cap else ", no cap")
    for sname, excl in (("all 46 markets", False), ("without short-rate futures", True)):
        pn = {}
        for sysname, sd in SYSTEMS.items():
            w_, al = sizing(sd, kind, tp, cap)
            vm = ~np.isin(sd["mk"], SHORT_RATES) if excl else np.ones(sd["n"], bool)
            for wn, (tmf, lo, hi) in WIN.items():
                m2 = al & vm & tmf(sd["sealed"])
                pnl, opn, heat = daily_usd(sd["rows"], sd["d"], sd["res"], sd["held"], sd["px"], w_, m2)
                st, cal = wstats(pnl, opn, lo, hi)
                x = sd["res"][m2]; usd_t = (sd["res"] * w_)[m2]
                top = np.sort(usd_t)[::-1][:10]
                st.update(system=sysname, sizing=lab, markets=sname, window=wn, trades=int(m2.sum()), skipped_too_big=int((~al & vm & tmf(sd["sealed"])).sum()), win_rate_pct=float((x > 0).mean() * 100) if len(x) else np.nan,
                          avg_ATR_per_trade=float(x.mean()) if len(x) else np.nan, top10_share_of_profit_pct=float(top.sum() / usd_t.sum() * 100) if usd_t.sum() > 0 else np.nan, total_profit_usd=float(usd_t.sum()),
                          avg_sessions_held=float(sd["held"][m2].mean()) if len(x) else np.nan)
                out.append(st); pn[(sysname, wn)] = (pnl, opn, lo, hi)
                if wn == "whole history" and sname == "all 46 markets" and kind.startswith("whole") and tp == 0.25 and cap:
                    yearly[sysname] = cal
        # 50/50 mix and correlation
        names_ = list(SYSTEMS)
        for wn, (tmf, lo, hi) in WIN.items():
            pa, oa, _, _ = pn[(names_[0], wn)]; pb, ob, _, _ = pn[(names_[1], wn)]
            st, cal = wstats(0.5 * pa + 0.5 * pb, oa + ob, lo, hi)
            sel = np.asarray((ALLD >= lo) & (ALLD <= hi))
            st.update(system="50/50 mix of both systems (each at half size)", sizing=lab, markets=sname, window=wn, trades=np.nan, skipped_too_big=np.nan, win_rate_pct=np.nan, avg_ATR_per_trade=np.nan,
                      top10_share_of_profit_pct=np.nan, total_profit_usd=float((0.5 * pa + 0.5 * pb)[sel].sum()), avg_sessions_held=np.nan, daily_return_correlation=float(np.corrcoef(pa[sel], pb[sel])[0, 1]))
            out.append(st)
    print("done", lab, f"({time.time()-t0:.0f}s)", flush=True)
S = pd.DataFrame(out)
S.to_csv(f"{out_dir}/head_to_head_summary.csv", index=False)
pd.DataFrame(yearly).round(2).to_csv(f"{out_dir}/by_year_whole_0.25_capped.csv")
pd.set_option("display.width", 330); pd.set_option("display.max_columns", 40); pd.set_option("display.max_rows", 800); pd.set_option("display.max_colwidth", 48)
cols = ["system", "markets", "trades", "win_rate_pct", "avg_ATR_per_trade", "top10_share_of_profit_pct", "return_per_year_pct", "vol_per_year_pct", "sharpe", "max_drawdown_pct", "max_drawdown_usd", "longest_underwater_sessions", "years_positive", "worst_year_pct", "best_year_pct", "daily_return_correlation"]
for wn in WIN:
    for (kind, tp, cap) in SIZINGS:
        lab = f"{kind} {tp}% per ATR" + (f", short rates capped at {cap} contracts" if cap else ", no cap")
        v = S[(S.window == wn) & (S.sizing == lab)].copy()
        v["system"] = v.system.str.slice(0, 34)
        print(f"\n==== {wn} | {lab} ===="); print(v[cols].round(2).to_string(index=False))
print("\n==== profit by calendar year, whole contracts 0.25% capped, all 46 markets (percent of $300k) ===="); print(pd.DataFrame(yearly).round(1).to_string())
print("done", f"{time.time()-t0:.0f}s")
