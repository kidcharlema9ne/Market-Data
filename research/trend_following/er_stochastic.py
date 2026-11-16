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
TRIGGERS = [("pullback 2.5 ATR (current best)", 2.5, None, None), ("pullback 1.5 ATR", 1.5, None, None)]
for sp_ in (5, 14):
    for th_ in (10, 20, 30):
        TRIGGERS.append((f"stochastic {sp_}-session slow at or beyond {th_}", None, sp_, th_))
for sp_ in (5, 14):
    TRIGGERS.append((f"pullback 1.5 ATR and stochastic {sp_}-session at or beyond 20", 1.5, sp_, 20))
    TRIGGERS.append((f"pullback 2.5 ATR and stochastic {sp_}-session at or beyond 20", 2.5, sp_, 20))
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
    SK = {}
    for p in (5, 14):
        hh_ = pd.Series(h).rolling(p).max(); ll_ = pd.Series(l).rolling(p).min()
        rk = 100 * (cs - ll_) / (hh_ - ll_).where((hh_ - ll_) > 0)
        SK[p] = rk.rolling(3).mean().to_numpy()      # slow stochastic: raw %K over p sessions, smoothed with a 3-session average
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
                for nm, pm, sp, th in TRIGGERS:
                    if nm in hit:
                        continue
                    ok = True
                    if pm is not None:
                        ok = ok and dep >= pm
                    if sp is not None:
                        kv = SK[sp][t]
                        ok = ok and bool(np.isfinite(kv)) and ((kv <= th) if dn > 0 else (kv >= 100 - th))
                    if ok:
                        hit[nm] = t
                if len(hit) == len(TRIGGERS):
                    break
            for nm, t in hit.items():
                add((tname, nm, 20), offset + t, dn)
    for lst, arr in ((FO, o), (FH, h), (FL, l), (FC, c), (FA, atr)):
        lst.append(sliding_window_view(arr[1:], FW)[:m])
    DATE.append(g["file_date"].to_numpy()[:m]); MK.append(np.full(m, len(names) - 1)); ATR0.append(atr[:m])
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
RISK_PCTS = (0.10, 0.25, 0.50)     # percent of capital risked per 1 ATR (= the 1 ATR initial stop), fixed dollars, no compounding
ALLD = pd.DatetimeIndex(sorted(set(np.concatenate(MDATES))))
ALLD = ALLD[(ALLD >= DEV_START) & (ALLD <= DEV_END)]
pos_of = {d: i for i, d in enumerate(ALLD)}


def daily_pnl_atr(rows, d, res, held, mask):
    """Daily mark-to-market P&L in entry-ATR units for the kept trades flagged in mask. Entry at next open; marks at closes; net result (incl. cost) booked on the exit day."""
    pnl = np.zeros(len(ALLD)); opn = np.zeros(len(ALLD))
    idx = np.where(mask)[0]
    for i in idx:
        r = rows[i]; mid = MK[r]; loc = r - MOFF[mid]
        h = int(held[i]); dn = d[i]; a0 = ATR0[r]; en = O[r, 0]
        cum_prev = 0.0
        for j in range(1, h + 1):
            cum = res[i] if j == h else dn * (C[r, j - 1] - en) / a0
            dt = MDATES[mid][loc + j]
            p = pos_of.get(pd.Timestamp(dt))
            if p is not None:
                pnl[p] += cum - cum_prev; opn[p] += 1
            cum_prev = cum
    return pnl, opn


def stats(pnl_atr, opn, scale_pct, label_):
    usd = pnl_atr * CAPITAL * scale_pct / 100.0
    eq = CAPITAL + np.cumsum(usd)
    peak = np.maximum.accumulate(eq)
    dd = (eq - peak)
    ddp = dd / peak
    r = usd / CAPITAL
    yrs = len(ALLD) / 252.0
    sh = r.mean() / r.std() * np.sqrt(252) if r.std() > 0 else np.nan
    cal = pd.Series(usd, index=ALLD).groupby(ALLD.year).sum() / CAPITAL * 100
    underwater = (eq < peak)
    longest = 0; cur = 0
    for u in underwater:
        cur = cur + 1 if u else 0
        longest = max(longest, cur)
    tro = int(np.argmin(dd)); pk = int(np.argmax(eq[:tro + 1]))
    return dict(label=label_, risk_pct_per_ATR=scale_pct, return_per_year_pct=(eq[-1] - CAPITAL) / CAPITAL * 100 / yrs, vol_per_year_pct=r.std() * np.sqrt(252) * 100,
                sharpe=sh, max_drawdown_usd=dd.min(), max_drawdown_pct_of_peak=ddp.min() * 100, max_drawdown_pct_of_start=dd.min() / CAPITAL * 100,
                drawdown_peak=str(ALLD[pk].date()), drawdown_trough=str(ALLD[tro].date()), longest_underwater_sessions=longest,
                best_year_pct=cal.max(), worst_year_pct=cal.min(), years_positive=f"{int((cal>0).sum())} of {len(cal)}",
                avg_open_positions=float(opn.mean()), max_open_positions=int(opn.max()), end_equity=eq[-1]), cal


summ = []
for tname in (TRENDS[0], TRENDS[4]):
    for (nm, pm, sp, th) in TRIGGERS:
        lst = entries.get((tname, nm, 20))
        if not lst:
            continue
        rows0, d0 = dedupe(lst)
        for e in (("trail", 5.0, 130), ("time", None, 60)):
            res_all, held_all = sim(rows0, d0, *e)
            kp = nonoverlap(rows0, held_all)
            rows, d, res, held = rows0[kp], d0[kp], res_all[kp], held_all[kp]
            sr = np.isin(mkt_names[rows], SHORT_RATES)
            for variant, mask in (("all 48 markets", np.ones(len(rows), bool)), ("without short-rate futures", ~sr)):
                pnl, opn = daily_pnl_atr(rows, d, res, held, mask)
                st, cal = stats(pnl, opn, 0.25, "")
                x = res[mask]; fh = np.asarray(DATE[rows][mask] < SPLIT)
                top = np.argsort(-x)[:10]; kk = np.ones(len(x), bool); kk[top] = False
                st.update(signal=tname[:22], trigger=nm, exit=label(e), markets=variant, n_trades=int(mask.sum()), trades_per_month=mask.sum() / YEARS / 12,
                          avg_ATR_per_trade=float(x.mean()), win_rate_pct=float((x > 0).mean() * 100), avg_sessions=float(held[mask].mean()),
                          first_half_ATR=float(x[fh].mean()) if fh.sum() > 20 else np.nan, second_half_ATR=float(x[~fh].mean()) if (~fh).sum() > 20 else np.nan,
                          avg_ATR_without_top_10=float(x[kk].mean()), worst_year_pct_=st["worst_year_pct"], positive_years=st["years_positive"])
                summ.append(st)
        print(f"done {tname[:22]} | {nm} ({time.time()-t0:.0f}s)", flush=True)
S = pd.DataFrame(summ)
cols = ["signal", "trigger", "exit", "markets", "n_trades", "trades_per_month", "avg_ATR_per_trade", "avg_ATR_without_top_10", "win_rate_pct", "first_half_ATR", "second_half_ATR",
        "return_per_year_pct", "vol_per_year_pct", "sharpe", "max_drawdown_pct_of_peak", "max_drawdown_usd", "longest_underwater_sessions", "worst_year_pct", "best_year_pct", "positive_years", "avg_open_positions"]
S[cols].to_csv(f"{out_dir}/stochastic_portfolio.csv", index=False)
pd.set_option("display.width", 320); pd.set_option("display.max_columns", 40); pd.set_option("display.max_rows", 500)
for sig in S.signal.unique():
    for ex in ("trail 5 ATR, max 130", "time exit 60"):
        v = S[(S.signal == sig) & (S.exit == ex)]
        print(f"\n==== {sig} | {ex} | portfolio at 0.25% of $300k per ATR ====")
        print(v[["trigger", "markets", "n_trades", "trades_per_month", "avg_ATR_per_trade", "avg_ATR_without_top_10", "first_half_ATR", "second_half_ATR", "return_per_year_pct", "sharpe", "max_drawdown_pct_of_peak"]].round(2).to_string(index=False))
print("done", f"{time.time()-t0:.0f}s")
