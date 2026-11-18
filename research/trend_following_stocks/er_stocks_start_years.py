"""Stocks, long only: the current baseline started in every year (Michael, 18 Nov 2026: "show profit per year and drawdown for every start year").
Usage: python er_stocks_start_years.py stock_prices.parquet OUT_DIR spy_prices.parquet

Baseline = the current best rule with volume-surge ranking when the account is full (hand-off doc 17 Nov 2026, Entries 155 and 157): common stocks, one series per company, $3M floor, 20-session efficiency ratio 0.50 with
rising close, 20-session watch, buy the next open after a close 1.5 ATR below the best high since the signal, strongest 20% by 126-session return that day, SPY above its 200-day, 4 ATR initial stop, 5 ATR trailing stop,
no time limit, 0.05 ATR a side, 0.10% of a fixed $300,000 per ATR, position value capped at 200% (and 100%) of the account. When the account is full the signal with the biggest volume surge on its signal day is taken first.

What is new here: the account is started EMPTY on 1 January of each start year (no positions carried in from earlier years) and run to the end of the development data (6 Aug 2021). Three tables:
  1. start year Y to 6 Aug 2021 (one row per start year, 2000 to 2020);
  2. every 3-year window (start 1 Jan of Y, end 31 Dec of Y+2);
  3. every 5-year window (start 1 Jan of Y, end 31 Dec of Y+4).
Each row shows profit per year (percent of the fixed $300,000), Sharpe ratio, max drawdown from the account's running peak (percent of the peak), profit per year divided by the drawdown, worst calendar year and years positive, with SPY
buy and hold (price only, $300,000 whole shares) over the same dates beside it. In a window, positions still open on the last day are marked at that day's close (their later days are not counted).
In-sample only (data through 2021-08-06); the sealed years are never read.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
import pandas as pd

import er_stocks as B
import er_stocks_ideas_1_2_6 as I1
import er_stocks_many_ideas as MI
import er_stocks_nasdaq_volume as NV
from er_stocks import CAPITAL, END, EPOCH


def subset(R, mask):
    """Keep only the trades where mask is True (renumbering the trade ids that the daily rows point to)."""
    keep = np.flatnonzero(mask)
    newid = np.full(len(mask), -1, np.int64); newid[keep] = np.arange(len(keep))
    out = {}
    for k in MI.KEYS + ("how",):
        out[k] = R[k][keep]
    fm = mask[R["f_tid"]]
    out["f_sess"] = R["f_sess"][fm]; out["f_incr"] = R["f_incr"][fm]; out["f_tid"] = newid[R["f_tid"][fm]]
    out["parent"] = np.full(len(keep), -1, np.int64)
    return out


def spy_hold(spy_close, dates, lo, hi):
    """SPY buy and hold price only, whole shares bought with $300,000 at the close before the first day of the window."""
    sel = np.flatnonzero(np.asarray((dates >= lo) & (dates <= hi)))
    if len(sel) < 30:
        return {}
    i0 = sel[0]
    px = spy_close[i0 - 1] if i0 > 0 and np.isfinite(spy_close[i0 - 1]) else spy_close[i0]
    sh = np.floor(CAPITAL / px)
    pnl = np.zeros(len(spy_close)); d = np.diff(np.r_[px, spy_close[sel]])
    pnl[sel] = sh * d
    st, _ = B.wstats(pnl, dates, lo, hi)
    return st


def run_window(R, key, cal, dates, spy_close, lo, hi, cap):
    ed = dates[R["sess_e"]]
    m = np.asarray((ed >= lo) & (ed <= hi))
    if m.sum() < 5:
        return None
    Rs = subset(R, m)
    P = MI.portfolio_gen(Rs, cal, cap, key[m])
    st, cal_y = B.wstats(P["pnl"], dates, lo, hi, P["open_n"], P["gross"])
    if not st:
        return None
    bm = spy_hold(spy_close, dates, lo, hi)
    dd = abs(st["max drawdown %"])
    row = {"start": lo.date().isoformat(), "end": hi.date().isoformat(), "years": round((hi - lo).days / 365.25, 1), "profit per year %": st["profit per year %"], "Sharpe ratio": st["Sharpe ratio"],
           "max drawdown % (from peak)": st["max drawdown %"], "profit per year / drawdown": st["profit per year %"] / dd if dd > 0 else np.nan, "worst year %": st["worst year %"], "years positive": st["years positive"],
           "trades taken": int(P["taken"].sum()), "average open positions": st["average open positions"],
           "SPY buy and hold profit per year %": bm.get("profit per year %", np.nan), "SPY buy and hold max drawdown %": bm.get("max drawdown %", np.nan)}
    return row


def main():
    prices_path, out_dir, spy_path = sys.argv[1], Path(sys.argv[2]), sys.argv[3]
    out_dir.mkdir(parents=True, exist_ok=True)
    ctx, names, live, E20, dates, spy_close, mk200 = MI.setup(prices_path, spy_path)
    SEG, dropped, cal, _ = ctx
    MI.check_baseline(ctx, mk200)
    R = MI.gen(ctx, mk200)
    n = len(R["d"])
    FEAT = NV.build_features(ctx, E20)
    sym, t = I1.trade_rows(SEG, R)
    surge = np.array([FEAT[(sym[k], t[k])]["s20_sig"] for k in range(n)], float)
    key = -np.where(np.isfinite(surge), surge, -1e9) + np.random.default_rng(20261118).random(n) * 1e-9      # smaller first: biggest volume surge taken first when the account is full
    # reproduce the documented baseline on the whole period first
    W0 = (pd.Timestamp("2000-01-01"), END)
    for cap in (2.0, 1.0):
        P = MI.portfolio_gen(R, cal, cap, key)
        st, _ = B.wstats(P["pnl"], dates, W0[0], W0[1], P["open_n"], P["gross"])
        print(f"whole period, cap {int(cap*100)}%: {st['profit per year %']:+.1f}% a year / Sharpe {st['Sharpe ratio']:.2f} / max drawdown {st['max drawdown %']:.1f}% / worst year {st['worst year %']:.1f}%"
              + ("  (documented +25.1% / 0.69 / -21.7% / -16.1%)" if cap == 2.0 else "  (documented +14.5% / 0.67 / -18.1%)"), flush=True)
        if cap == 2.0 and abs(st["Sharpe ratio"] - 0.69) > 0.02:
            print("!!!! MISMATCH WITH THE DOCUMENTED VOLUME-SURGE BASELINE: do not trust this run until explained !!!!", flush=True)
    pd.set_option("display.width", 320); pd.set_option("display.max_columns", 40); pd.set_option("display.max_rows", 200)
    first_year = 2000
    tabs = {}
    for cap in (2.0, 1.0):
        cl = f"cap{int(cap*100)}"
        rows = []
        for y in range(first_year, 2021):
            r = run_window(R, key, cal, dates, spy_close, pd.Timestamp(f"{y}-01-01"), END, cap)
            if r:
                rows.append(r)
        tabs[(cl, "start year to Aug 2021")] = pd.DataFrame(rows)
        for L in (3, 5):
            rows = []
            for y in range(first_year, 2021 - L + 1 + 1):
                hi = pd.Timestamp(f"{y + L - 1}-12-31")
                if hi > END:
                    continue
                r = run_window(R, key, cal, dates, spy_close, pd.Timestamp(f"{y}-01-01"), hi, cap)
                if r:
                    rows.append(r)
            tabs[(cl, f"rolling {L}-year windows")] = pd.DataFrame(rows)
    for (cl, nm), df in tabs.items():
        fn = f"start_years_{cl}_{nm.replace(' ', '_').replace('-', '')}.csv"
        df.round(3).to_csv(out_dir / fn, index=False)
        print(f"\n==== {nm} | account value capped at {cl[3:]}% | volume-surge baseline | account started empty on 1 January ====")
        print(df.round(2).to_string(index=False))
        if len(df):
            print(f"  spread across rows: profit per year {df['profit per year %'].min():.1f}% to {df['profit per year %'].max():.1f}% (median {df['profit per year %'].median():.1f}%); max drawdown {df['max drawdown % (from peak)'].min():.1f}% to {df['max drawdown % (from peak)'].max():.1f}%; "
                  f"windows with a loss: {int((df['profit per year %'] < 0).sum())} of {len(df)}")
    print("done")


if __name__ == "__main__":
    main()
