"""Efficiency ratio trend rule on STOCKS, in-sample: old version vs new version (Michael, 17 Nov 2026: "test our efficiency ratio trading system on stocks ... the old version and the new version ... in sample").

Usage: python er_stocks.py stock_prices.parquet OUT_DIR [spy_prices.parquet]      (a .csv with columns symbol,date_i,open,high,low,close,volume also works, for the self-test)

Rule (same entry for both versions, close-based, copied from the futures work, nothing tuned for stocks):
  1. 20-session efficiency ratio (|20-session net close change| / sum of |daily close changes|) of 0.50 or more; direction = sign of the 20-session net close change. Only the first day a stock newly
     qualifies in a direction starts a watch.
  2. Watch up to 20 sessions for a pullback: a close at least 2.5 ATR (20-day average true range) below the best high since the signal (long) or above the lowest low since the signal (short).
  3. Enter at the next session's open. One position per stock.
  4. OLD VERSION: 1 ATR initial stop from entry, then 5 ATR trailing stop from the best close, NO time limit (Michael, 17 Nov 2026: the 130-session limit was wrong for the old version).
     NEW VERSION (version 2): 2 ATR initial stop, then 5 ATR trailing stop from the best close, no time limit.
  Cost 0.05 ATR a side (0.10 ATR round trip). Gap through a stop fills at the open.
Stock rules: liquidity floor = average dollar volume (close x volume) of the prior 15 sessions of at least $3,000,000, all 15 sessions present, checked on the decision day (same definition as the
insider study, Entry 19). Position size = whole shares, 0.10% of a fixed $300,000 per ATR (Michael, 17 Nov 2026) (shares = floor(target / ATR in dollars per share); skip if under 1 share). Total position value
(longs and shorts added together) is capped at 200% of the account (Michael's choice; 100% fully paid and no cap shown for comparison); when a cap is full a new signal is skipped, same-day ties in a fixed random order (seed
20261117). Stocks are tested long and short, long only and short only.
In-sample = data through 2021-08-06 (the same development cut as the futures work; later years stay sealed and are not read). Windows: 2000-2007, 2008 to Aug 2021 (the futures development years), whole.
Positions still open on the last day, or whose stock stops trading (delisting, trading suspended), are closed at the last available close. A series is cut into separate stocks at a gap of more than 5
missing sessions or a one-day close move beyond 5x or below 0.2x (reused tickers, identity collisions, Entry 19). The archive is split adjusted, dividends not included.
Reports: profit per year (percent of $300k), Sharpe ratio, max drawdown; buy-and-hold SPY (price only) beside it when spy_prices.parquet is given.
"""
import heapq
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

CAPITAL = 300_000.0
FLOOR = 3_000_000.0
ADV_N = 15
ER_N, ER_MIN, ATR_N, PULL, WATCH, TRAIL = 20, 0.50, 20, 2.5, 20, 5.0
COST_RT = 0.10
EPOCH = pd.Timestamp("1970-01-01")
END = pd.Timestamp("2021-08-06")
FIRST_TRADE = pd.Timestamp("2000-03-01")
MAIN_START = pd.Timestamp("2008-02-01")
VERSIONS = {"old version (1 ATR stop, 5 ATR trail, no time limit)": (1.0, TRAIL, None),
            "new version 2 (2 ATR stop, 5 ATR trail, no time limit)": (2.0, TRAIL, None)}
SIZES = (0.10,)
CAPS = (2.0, 1.0, None)
SIDES = {"long and short": (1, -1), "long only": (1,), "short only": (-1,)}
SEED = 20261117


def run_trade(o, h, l, c, atr, t, d, init, mm, cap):
    """Decision day row t, enter at open of row t+1. Returns (exit_row, exit_price, close marks of the days before the exit day, how) or None."""
    n = len(c)
    e = t + 1
    if e >= n:
        return None
    a0 = atr[t]
    entry = o[e]
    stop = entry - d * init * a0
    best = entry
    marks = []
    for j in range(e, n):
        k = j - e
        hit = (l[j] <= stop) if d > 0 else (h[j] >= stop)
        if hit:
            gap = k > 0 and ((o[j] <= stop) if d > 0 else (o[j] >= stop))
            return j, (o[j] if gap else stop), marks, "stop"
        marks.append(c[j])
        best = max(best, c[j]) if d > 0 else min(best, c[j])
        na = atr[j]
        if na == na:
            new = best - d * mm * na
            stop = max(stop, new) if d > 0 else min(stop, new)
        if cap is not None and k == cap - 1:
            return j, c[j], marks[:-1], "time limit"
    return n - 1, c[n - 1], marks[:-1], "data end"


def selftest():
    f = np.float64
    # long, entry 100, ATR 2, init 1 ATR -> stop 98: day 2 low 97.5 hits, fills at 98 -> -1 ATR
    o = np.array([100, 100, 100, 100], f); h = np.array([101, 102, 101, 101], f); l = np.array([99, 99, 97.5, 99], f); c = np.array([100, 101, 99, 100], f); atr = np.full(4, 2.0)
    r = run_trade(o, h, l, c, atr, 0, 1, 1.0, 5.0, None)
    assert r[0] == 2 and r[1] == 98.0 and r[3] == "stop" and r[2] == [101], r
    # gap: day 2 opens 96 below the stop -> fills at 96
    o2 = o.copy(); o2[2] = 96.0
    r = run_trade(o2, h, l, c, atr, 0, 1, 1.0, 5.0, None)
    assert r[1] == 96.0, r
    # trailing: rally to close 120, ATR 2, 5 ATR trail -> stop 110; next low 109 exits at 110
    n = 8
    o3 = np.array([100, 100, 105, 110, 115, 120, 120, 118], f); h3 = o3 + 1; l3 = o3 - 1; c3 = np.array([100, 105, 110, 115, 120, 120, 119, 117], f); l3[7] = 109.0
    r = run_trade(o3, h3, l3, c3, np.full(n, 2.0), 0, 1, 1.0, 5.0, None)
    assert r[0] == 7 and r[1] == 110.0, r
    # short mirror: entry 100, stop 102 (1 ATR), high 103 on a later day exits at 102
    o4 = np.array([100, 100, 100, 100], f); h4 = np.array([101, 101, 103, 101], f); l4 = np.array([99, 98, 98, 98], f); c4 = np.array([100, 99, 100, 99], f)
    r = run_trade(o4, h4, l4, c4, np.full(4, 2.0), 0, -1, 1.0, 5.0, None)
    assert r[0] == 2 and r[1] == 102.0, r
    # time limit: cap 3 sessions exits at the close of the 3rd session
    o5 = np.full(6, 100.0); c5 = np.array([100, 100.5, 101, 101.5, 102, 102.5]); r = run_trade(o5, c5 + 0.2, c5 - 0.2, c5, np.full(6, 2.0), 0, 1, 2.0, 5.0, 3)
    assert r[0] == 3 and r[1] == c5[3] and r[3] == "time limit", r
    print("simulator self-test passed", flush=True)


def load(path):
    if str(path).endswith(".csv"):
        df = pd.read_csv(path)
        codes, uni = pd.factorize(df["symbol"])
        return codes.astype(np.int64), np.asarray(uni), df["date_i"].to_numpy(np.int64), *(df[c].to_numpy(float) for c in ("open", "high", "low", "close", "volume"))
    import pyarrow as pa
    import pyarrow.parquet as pq
    t = pq.read_table(path)
    enc = t.column("symbol").combine_chunks().dictionary_encode()
    codes = enc.indices.to_numpy(zero_copy_only=False).astype(np.int64)
    uni = np.asarray(enc.dictionary.to_pylist())
    cols = [t.column(c).to_numpy().astype(np.float32 if c != "date_i" else np.int64) for c in ("date_i", "open", "high", "low", "close", "volume")]
    return codes, uni, cols[0], cols[1], cols[2], cols[3], cols[4], cols[5]


def segments(sym, date_i, o, h, l, c, v):
    """Yield (name, session_index, o, h, l, c, v) per stock segment. Rows must be sorted by symbol then date."""
    cal = np.unique(date_i)
    sess = np.searchsorted(cal, date_i)
    bounds = np.r_[0, np.where(np.diff(sym) != 0)[0] + 1, len(sym)]
    for b in range(len(bounds) - 1):
        a, z = bounds[b], bounds[b + 1]
        s = sess[a:z]
        cc = c[a:z].astype(float)
        cut = np.where((np.diff(s) > 6) | (cc[1:] / cc[:-1] > 5) | (cc[1:] / cc[:-1] < 0.2))[0] + 1
        edges = np.r_[0, cut, z - a]
        for q in range(len(edges) - 1):
            i, j = a + edges[q], a + edges[q + 1]
            if j - i >= 60:
                yield sym[a], q, sess[i:j], o[i:j].astype(float), h[i:j].astype(float), l[i:j].astype(float), c[i:j].astype(float), v[i:j].astype(float)


def candidates(s, o, h, l, c, v):
    """Pullback entries for one stock segment: list of (decision row, direction) and the ATR array."""
    n = len(c)
    pc_ = np.r_[np.nan, c[:-1]]
    tr = np.maximum.reduce([h - l, np.abs(h - pc_), np.abs(l - pc_)])
    tr[0] = h[0] - l[0]
    atr = pd.Series(tr).rolling(ATR_N).mean().to_numpy()
    cs = pd.Series(c)
    path = pd.Series(np.abs(np.diff(c, prepend=np.nan))).rolling(ER_N).sum()
    er = ((cs - cs.shift(ER_N)).abs() / path).to_numpy()
    dr = np.sign(cs - cs.shift(ER_N)).fillna(0).to_numpy()
    dv = pd.Series(c * v)
    adv = dv.rolling(ADV_N).mean().to_numpy()
    span = np.r_[np.full(ADV_N - 1, False), (s[ADV_N - 1:] - s[:-(ADV_N - 1)]) == ADV_N - 1]
    liq = span & np.isfinite(adv) & (adv >= FLOOR)
    if not liq.any():
        return [], atr, liq
    q = np.isfinite(er) & (er >= ER_MIN) & (dr != 0) & np.isfinite(atr) & (atr > 1e-6 * c)
    qprev = np.r_[False, q[:-1]]
    dprev = np.r_[0.0, dr[:-1]]
    starts = np.where(q & ~(qprev & (dprev == dr)))[0]
    out = []
    for st in starts:
        dn = dr[st]
        peak = h[st] if dn > 0 else l[st]
        for t in range(st + 1, min(st + WATCH, n - 2) + 1):
            peak = max(peak, h[t]) if dn > 0 else min(peak, l[t])
            a = atr[t]
            if not (a == a and a > 0):
                continue
            dep = (peak - c[t]) / a if dn > 0 else (c[t] - peak) / a
            if dep >= PULL:
                if liq[t]:
                    out.append((t, int(dn)))
                break
    return out, atr, liq


def build(path):
    t0 = time.time()
    sym, uni, date_i, o, h, l, c, v = load(path)
    end_i = (END - EPOCH).days
    keep = (date_i <= end_i) & np.isfinite(c) & (c > 0) & (o > 0) & (h >= l) & (l > 0)
    sym, date_i, o, h, l, c, v = (x[keep] for x in (sym, date_i, o, h, l, c, v))
    order = np.lexsort((date_i, sym))
    sym, date_i, o, h, l, c, v = (x[order] for x in (sym, date_i, o, h, l, c, v))
    dup = np.r_[False, (np.diff(sym) == 0) & (np.diff(date_i) == 0)]
    if dup.any():
        sym, date_i, o, h, l, c, v = (x[~dup] for x in (sym, date_i, o, h, l, c, v))
    cal = np.unique(date_i)
    print(f"{len(sym):,} rows; {len(uni):,} symbols; {len(cal)} sessions {(EPOCH + pd.Timedelta(days=int(cal[0]))).date()} to {(EPOCH + pd.Timedelta(days=int(cal[-1]))).date()}; load {time.time()-t0:.0f}s", flush=True)
    first_i = (FIRST_TRADE - EPOCH).days
    V = {name: dict(sess_e=[], sess_x=[], d=[], px_e=[], a0=[], res=[], held=[], how=[], sym=[], f_sess=[], f_incr=[], f_tid=[]) for name in VERSIONS}
    n_seg = n_liq_seg = n_cand = 0
    for code, q, s, so, sh, sl, sc, sv in segments(sym, date_i, o, h, l, c, v):
        n_seg += 1
        cand, atr, liq = candidates(s, so, sh, sl, sc, sv)
        if not liq.any():
            continue
        n_liq_seg += 1
        cand = [(t, d) for t, d in cand if t + 1 < len(sc) and cal[s[t + 1]] >= first_i]
        n_cand += len(cand)
        for name, (init, mm, cap) in VERSIONS.items():
            R = V[name]
            last_exit = -1
            for t, d in cand:
                if t < last_exit:
                    continue
                res = run_trade(so, sh, sl, sc, atr, t, d, init, mm, cap)
                if res is None:
                    continue
                x, xpx, marks, how = res
                e = t + 1
                entry, a0 = so[e], atr[t]
                last_exit = x
                seq = np.r_[entry, np.asarray(marks, float), xpx]
                incr = d * np.diff(seq)
                tid = len(R["d"])
                R["sess_e"].append(int(s[e])); R["sess_x"].append(int(s[x])); R["d"].append(d); R["px_e"].append(entry); R["a0"].append(a0)
                R["res"].append(d * (xpx - entry) / a0 - COST_RT); R["held"].append(x - e + 1); R["how"].append(how); R["sym"].append(int(code))
                R["f_sess"].append(s[e:x + 1]); R["f_incr"].append(incr); R["f_tid"].append(np.full(len(incr), tid))
    print(f"{n_seg:,} stock segments; {n_liq_seg:,} ever liquid; {n_cand:,} pullback entries passing the $3M floor; {time.time()-t0:.0f}s", flush=True)
    for name, R in V.items():
        for k in ("sess_e", "sess_x", "d", "px_e", "a0", "res", "held", "sym"):
            R[k] = np.asarray(R[k], dtype=float if k in ("px_e", "a0", "res") else np.int64)
        R["how"] = np.asarray(R["how"])
        for k in ("f_sess", "f_incr", "f_tid"):
            R[k] = np.concatenate(R[k]) if R[k] else np.array([])
        print(f"  {name}: {len(R['d']):,} trades (one position per stock, before any account limit)", flush=True)
    return V, cal


def portfolio(R, cal, sides, tp, cap, rng_key):
    n = len(R["d"])
    tgt = CAPITAL * tp / 100.0
    shares = np.floor(tgt / R["a0"])
    ok = np.isin(R["d"], sides) & (shares >= 1)
    notional = shares * R["px_e"]
    idx = np.where(ok)[0]
    order = idx[np.lexsort((rng_key[idx], R["sess_e"][idx]))]
    taken = np.zeros(n, bool)
    heap, gross = [], 0.0
    for i in order:
        while heap and heap[0][0] < R["sess_e"][i]:
            gross -= heapq.heappop(heap)[1]
        if cap is not None and gross + notional[i] > cap * CAPITAL:
            continue
        taken[i] = True
        heapq.heappush(heap, (R["sess_x"][i], notional[i])); gross += notional[i]
    m = len(cal)
    w = shares * taken
    pnl = np.bincount(R["f_sess"], weights=R["f_incr"] * w[R["f_tid"]], minlength=m).astype(float)
    cost_ps = 0.5 * COST_RT * R["a0"] * w
    pnl -= np.bincount(R["sess_e"], weights=cost_ps, minlength=m) + np.bincount(R["sess_x"], weights=cost_ps, minlength=m)
    trade_usd = w * (R["res"] * R["a0"])          # res is net of cost in ATR units, so this is net dollars
    assert abs(pnl.sum() - trade_usd.sum()) < 1e-6 * max(1.0, abs(trade_usd).sum()), (pnl.sum(), trade_usd.sum())
    diff_n = np.zeros(m + 1); diff_v = np.zeros(m + 1)
    for arr, wt in ((diff_n, np.ones(n)), (diff_v, notional)):
        np.add.at(arr, R["sess_e"][taken], wt[taken]); np.add.at(arr, R["sess_x"][taken] + 1, -wt[taken])
    return dict(pnl=pnl, taken=taken, trade_usd=trade_usd, open_n=np.cumsum(diff_n)[:m], gross=np.cumsum(diff_v)[:m], skipped_cap=int((ok & ~taken).sum()), skipped_small=int((np.isin(R["d"], sides) & (shares < 1)).sum()))


def wstats(pnl, dates, lo, hi, open_n=None, gross=None):
    sel = np.asarray((dates >= lo) & (dates <= hi))
    u = pnl[sel]
    if len(u) < 30:
        return {}, None
    eq = np.r_[CAPITAL, CAPITAL + np.cumsum(u)]
    peak = np.maximum.accumulate(eq)
    r = u / CAPITAL
    yrs = pd.DatetimeIndex(dates[sel])
    cal_y = pd.Series(u, index=yrs).groupby(yrs.year).sum() / CAPITAL * 100
    cur = longest = 0
    for fl in (eq[1:] < peak[1:]):
        cur = cur + 1 if fl else 0
        longest = max(longest, cur)
    st = {"profit per year %": (eq[-1] - CAPITAL) / CAPITAL * 100 / (len(u) / 252.0), "Sharpe ratio": r.mean() / r.std() * np.sqrt(252) if r.std() > 0 else np.nan,
          "max drawdown %": ((eq - peak) / peak).min() * 100, "worst year %": cal_y.min(), "best year %": cal_y.max(), "years positive": f"{int((cal_y > 0).sum())} of {len(cal_y)}",
          "longest time under water (sessions)": longest}
    if open_n is not None:
        st["average open positions"] = float(open_n[sel].mean()); st["most open positions"] = int(open_n[sel].max())
        st["average position value % of account"] = float(gross[sel].mean() / CAPITAL * 100); st["most position value % of account"] = float(gross[sel].max() / CAPITAL * 100)
    return st, cal_y


def main():
    prices_path, out_dir = sys.argv[1], Path(sys.argv[2])
    out_dir.mkdir(parents=True, exist_ok=True)
    selftest()
    V, cal = build(prices_path)
    dates = EPOCH + pd.to_timedelta(cal, unit="D")
    dates = pd.DatetimeIndex(dates)
    WIN = {"2000 to 2007": (pd.Timestamp("2000-01-01"), MAIN_START - pd.Timedelta(days=1)), "2008 to Aug 2021 (futures development years)": (MAIN_START, END), "whole in-sample 2000 to Aug 2021": (pd.Timestamp("2000-01-01"), END)}
    rows = []
    by_year = {}
    daily_keep = {}
    for vname, R in V.items():
        rng_key = np.random.default_rng(SEED).random(len(R["d"]))
        ed = dates[R["sess_e"]] if len(R["d"]) else dates[:0]
        for sname, sides in SIDES.items():
            for tp in SIZES:
                for cap in CAPS:
                    P = portfolio(R, cal, sides, tp, cap, rng_key)
                    capl = "no cap" if cap is None else f"position value capped at {int(cap*100)}% of the account"
                    for wn, (lo, hi) in WIN.items():
                        st, cal_y = wstats(P["pnl"], dates, lo, hi, P["open_n"], P["gross"])
                        if not st:
                            continue
                        inw = P["taken"] & np.asarray((ed >= lo) & (ed <= hi))
                        usd = P["trade_usd"][inw]; resa = R["res"][inw]
                        top = np.sort(usd)[::-1][:10]
                        st.update({"version": vname, "sides": sname, "size per ATR %": tp, "account limit": capl, "window": wn, "trades": int(inw.sum()), "stocks traded": int(len(set(R["sym"][inw]))),
                                   "win rate %": float((resa > 0).mean() * 100) if inw.any() else np.nan, "average ATR per trade": float(resa.mean()) if inw.any() else np.nan,
                                   "average sessions held": float(R["held"][inw].mean()) if inw.any() else np.nan, "ten biggest trades share of profit %": float(top.sum() / usd.sum() * 100) if usd.sum() > 0 else np.nan,
                                   "total profit $": float(usd.sum()), "signals skipped, account full": P["skipped_cap"], "signals skipped, under 1 share": P["skipped_small"]})
                        rows.append(st)
                        if wn.startswith("whole") and cap == 2.0:
                            by_year[(vname, sname)] = cal_y
                            daily_keep[(vname, sname)] = P["pnl"]
        # unconstrained per-trade summary (before any account limit or sizing)
    S = pd.DataFrame(rows)
    S.to_csv(out_dir / "stock_results_summary.csv", index=False)
    pd.DataFrame({f"{k[0][:12]} | {k[1]}": v for k, v in by_year.items()}).round(2).to_csv(out_dir / "profit_by_year_pct_0.10_cap200.csv")
    # per-trade table before sizing and account limits
    pt = []
    for vname, R in V.items():
        ed = dates[R["sess_e"]]
        for sname, sides in SIDES.items():
            for wn, (lo, hi) in WIN.items():
                m = np.isin(R["d"], sides) & np.asarray((ed >= lo) & (ed <= hi))
                if m.any():
                    pt.append({"version": vname, "sides": sname, "window": wn, "trades": int(m.sum()), "win rate %": float((R["res"][m] > 0).mean() * 100), "average ATR per trade": float(R["res"][m].mean()),
                               "median ATR per trade": float(np.median(R["res"][m])), "average sessions held": float(R["held"][m].mean()), "closed at data end %": float((R["how"][m] == "data end").mean() * 100),
                               "closed by time limit %": float((R["how"][m] == "time limit").mean() * 100)})
    PT = pd.DataFrame(pt)
    PT.to_csv(out_dir / "per_trade_before_sizing.csv", index=False)
    # SPY buy and hold
    spy = None
    if len(sys.argv) > 3:
        sp = pd.read_parquet(sys.argv[3])
        sp = sp[sp["date_i"] <= (END - EPOCH).days].sort_values("date_i").drop_duplicates("date_i")
        sd = EPOCH + pd.to_timedelta(sp["date_i"].to_numpy(), unit="D")
        pnl_spy = np.zeros(len(cal))
        pos = np.searchsorted(cal, sp["date_i"].to_numpy())
        cc = sp["close"].to_numpy(float)
        sh = np.floor(CAPITAL / cc[0])
        pnl_spy[pos[1:]] = sh * np.diff(cc)
        spy = {wn: wstats(pnl_spy, dates, lo, hi)[0] for wn, (lo, hi) in WIN.items()}
        pd.DataFrame(spy).T.round(2).to_csv(out_dir / "spy_buy_and_hold.csv")
    pd.set_option("display.width", 300); pd.set_option("display.max_columns", 40); pd.set_option("display.max_rows", 500)
    cols = ["version", "trades", "stocks traded", "win rate %", "average ATR per trade", "ten biggest trades share of profit %", "profit per year %", "Sharpe ratio", "max drawdown %", "years positive", "worst year %", "average open positions", "most open positions", "average position value % of account", "signals skipped, account full"]
    print("\n==== per trade, before sizing and account limits (ATR, net of 0.10 ATR cost) ====")
    print(PT.round(3).to_string(index=False))
    sort_cols = ["sides", "size per ATR %", "version"]
    for wn in WIN:
        v = S[(S.window == wn) & (S["account limit"] == "position value capped at 200% of the account")].copy()
        v["version"] = v["version"].str.slice(0, 11)
        v = v.sort_values(sort_cols, key=lambda col: col.map({"long and short": 0, "long only": 1, "short only": 2}) if col.name == "sides" else col)
        print(f"\n==== {wn} | position value capped at 200% of the account ====")
        print(v[["sides", "size per ATR %"] + cols].round(2).to_string(index=False))
    v = S[(S.window.str.startswith("whole")) & (S.sides == "long and short") & (S["size per ATR %"] == 0.10)].copy()
    v["version"] = v["version"].str.slice(0, 11)
    print("\n==== whole in-sample | long and short | 0.10% per ATR | effect of the account limit ====")
    print(v[["account limit"] + cols].round(2).to_string(index=False))
    if spy:
        print("\n==== SPY buy and hold, price only, $300k, same windows ====")
        print(pd.DataFrame(spy).T[["profit per year %", "Sharpe ratio", "max drawdown %"]].round(2).to_string())
    print("\n==== profit by calendar year, percent of $300k (0.10% per ATR, position value capped at 200%) ====")
    print(pd.DataFrame({f"{k[0][:11]} | {k[1]}": v for k, v in by_year.items()}).round(1).to_string())
    print("done")


if __name__ == "__main__":
    main()
