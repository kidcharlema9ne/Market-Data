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
from pathlib import Path
import time
import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

prices_path, uni_path, out_dir = sys.argv[1:4]
DEV_START, DEV_END = pd.Timestamp("2007-12-31"), pd.Timestamp("2021-08-06")
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
for X_ in (1.5, 2.0, 2.5, 3.0):
    LIMITS.append((f"buy limit {X_} ATR below the best price since the signal, filled on touch", X_, 0.0))
    LIMITS.append((f"buy limit {X_} ATR below the best price since the signal, filled only if price trades 0.1 ATR through", X_, 0.1))
PXD = {}
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
    defs = {k_: v_ for k_, v_ in defs.items() if k_ in (TRENDS[0], TRENDS[4])}
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
ALLD = ALLD[(ALLD >= DEV_START) & (ALLD <= DEV_END)]
pos_of = {d_: i_ for i_, d_ in enumerate(ALLD)}
SPLIT_I = np.asarray(ALLD < SPLIT)


def dedupe_px(lst, key):
    rows = np.array([r for r, _ in lst]); d = np.array([x for _, x in lst], float)
    rows, idx = np.unique(rows, return_index=True)
    d = d[idx]
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


METHODS = [t_[0] for t_ in TRIGGERS] + [t_[0] for t_ in LIMITS]
summ, yearly, permkt = [], {}, []
tname = TRENDS[0]
EXIT = ("trail", 5.0, 130)
for nm in METHODS:
    lst = entries.get((tname, nm, 20))
    if not lst:
        continue
    rows0, d0, px0 = dedupe_px(lst, (tname, nm, 20))
    res_all, held_all = sim(rows0, d0, *EXIT, px=px0)
    kp = nonoverlap(rows0, held_all)
    rows, d, res, held, px = rows0[kp], d0[kp], res_all[kp], held_all[kp], px0[kp]
    sr = np.isin(mkt_names[rows], SHORT_RATES)
    atr_d = (ATR0[rows] / px) * REFPX[MK[rows]] * MULT[MK[rows]]    # dollars per 1 ATR per contract in TODAY's contract terms: the trade's ATR as a percent of price times today's contract value
    for sizing, tgt_pct in (("fractional contracts", 0.25), ("whole contracts", 0.15), ("whole contracts", 0.25), ("whole contracts", 0.35)):
        tgt = CAPITAL * tgt_pct / 100.0
        if sizing.startswith("fractional"):
            w = np.full(len(rows), tgt); allowed = np.ones(len(rows), bool); ncon = np.full(len(rows), np.nan)
        else:
            ncon = np.maximum(1.0, np.rint(tgt / atr_d)); w = ncon * atr_d; allowed = atr_d <= 2 * tgt
        for variant, vm in (("all 46 markets", np.ones(len(rows), bool)), ("without short-rate futures", ~sr)):
            mask = allowed & vm
            pnl, opn, heat = daily_usd(rows, d, res, held, px, w, mask)
            assert abs(pnl.sum() - (res[mask] * w[mask]).sum()) < 1e-6 * max(1.0, abs(pnl).sum()), (pnl.sum(), (res[mask] * w[mask]).sum())
            st, cal = stats_usd(pnl, opn, heat)
            x = res[mask]; top = np.argsort(-x)[:10]; kk = np.ones(len(x), bool); kk[top] = False
            st.update(entry=nm, sizing=sizing, target_risk_pct_per_ATR=tgt_pct, markets=variant, n_trades=int(mask.sum()), skipped_one_contract_too_big=int((~allowed & vm).sum()),
                      trades_per_month=mask.sum() / YEARS / 12, avg_ATR_per_trade=float(x.mean()), avg_ATR_without_top_10=float(x[kk].mean()), win_rate_pct=float((x > 0).mean() * 100),
                      end_equity=CAPITAL + pnl.sum())
            summ.append(st)
            if variant.startswith("all") and tgt_pct == 0.25:
                yearly[(nm[:40], sizing)] = cal
    if nm in (METHODS[0],):
        for mid_, ib in enumerate(names):
            sel = (MK[rows] == mid_)
            if sel.sum():
                permkt.append(dict(market=ib, multiplier=MULT[mid_], trades=int(sel.sum()), median_ATR_dollars_per_contract=float(np.median(atr_d[sel])),
                                   median_contracts_at_0_25pct=float(np.median(np.maximum(1, np.rint(750 / atr_d[sel])))), share_skipped_at_0_25pct=float((atr_d[sel] > 1500).mean())))
    print(f"done {nm[:70]} ({time.time()-t0:.0f}s)", flush=True)
S = pd.DataFrame(summ)
cols = ["entry", "sizing", "target_risk_pct_per_ATR", "markets", "n_trades", "skipped_one_contract_too_big", "trades_per_month", "avg_ATR_per_trade", "avg_ATR_without_top_10", "win_rate_pct",
        "return_per_year_pct", "vol_per_year_pct", "sharpe", "sharpe_first_half", "sharpe_second_half", "max_drawdown_usd", "max_drawdown_pct_of_peak", "longest_underwater_sessions",
        "worst_year_pct", "best_year_pct", "years_positive", "avg_open_positions", "max_open_positions", "avg_risk_per_ATR_open_pct", "max_risk_per_ATR_open_pct", "end_equity"]
S[cols].to_csv(f"{out_dir}/whole_contract_and_limit_entries.csv", index=False)
pd.DataFrame(permkt).to_csv(f"{out_dir}/per_market_contracts.csv", index=False)
pd.DataFrame({" | ".join(k): v for k, v in yearly.items()}).to_csv(f"{out_dir}/by_year_at_0.25pct.csv")
pd.set_option("display.width", 330); pd.set_option("display.max_columns", 40); pd.set_option("display.max_rows", 500); pd.set_option("display.max_colwidth", 70)
show = ["entry", "sizing", "target_risk_pct_per_ATR", "markets", "n_trades", "skipped_one_contract_too_big", "trades_per_month", "avg_ATR_per_trade", "avg_ATR_without_top_10", "return_per_year_pct", "sharpe", "sharpe_first_half", "sharpe_second_half", "max_drawdown_pct_of_peak", "max_open_positions", "max_risk_per_ATR_open_pct"]
print("\n==== MARKETS (46: the 48 less MES and MNQ, whose full-size twins ES and NQ carry the same prices) ====")
for sz in ("fractional contracts", "whole contracts"):
    v = S[(S.sizing == sz)].sort_values(["markets", "target_risk_pct_per_ATR", "sharpe"], ascending=[True, True, False])
    print(f"\n---- {sz} ----"); print(v[show].round(2).to_string(index=False))
print("\n==== per market: contract size ===="); print(pd.DataFrame(permkt).round(2).to_string(index=False))
print("\n==== by year (percent of $300k, 0.25% target) ===="); print(pd.DataFrame({" | ".join(k): v for k, v in yearly.items()}).round(1).to_string())
print("done", f"{time.time()-t0:.0f}s")
