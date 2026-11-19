"""Stocks, long only: the FROZEN current best rule run once on the sealed years, with and without the volume-surge ranking (Michael, 19 Nov 2026: "run the system out of sample ... once with the volume surge rule and once without").
Usage: python er_stocks_oos.py stock_prices.parquet OUT_DIR spy_prices.parquet

The rule is exactly the one in the hand-off doc and Entries 155 to 170 (nothing is changed or tuned here): common stocks, one series per company, $3M 15-session average dollar volume floor, 20-session efficiency ratio at
least 0.50 with rising close, 20-session watch, buy the next open after a close 1.5 ATR below the best high since the signal, strongest 20% by 126-session return that day, SPY above its 200-day average (checked on the trigger
day), 4 ATR initial stop, 5 ATR trailing stop, no time limit, 0.05 ATR a side, 0.10% of a fixed $300,000 per ATR, whole shares, position value capped at 200% (and 100%) of the account, one position per stock.
Two versions of what happens when the account is full and several signals arrive on the same day:
  VOLUME SURGE  = the signal with the biggest volume surge on its signal day is taken first (the current baseline).
  WITHOUT       = random pick, 8 different random draws (mean, lowest and highest shown), exactly as in the in-sample tables.
Out-of-sample period = every session after 6 Aug 2021 (the in-sample cut), to the last day in the data. The account starts EMPTY and fixed at $300,000 on the first session after the cut; the 200-day SPY average, ATRs
and 126-session returns use earlier prices as warm-up (that is just history, not a test). The SPY 200-day gate and everything else were fixed before these years were read.
Reported: profit per year, max drawdown from the account's running peak, profit per year / drawdown, Sharpe ratio, worst year, trades, plus SPY buy and hold (price only, whole shares) over the same dates and the per-trade
average in ATR units beside the SPY move over the same holds (D-053). A cap of 200% is shown with and without a 4% a year charge on borrowed money (account value is fixed at $300,000, so borrowed = position value above it).
Before the out-of-sample numbers, the whole in-sample run is reproduced with the same code on the extended data (documented: +25.1% / Sharpe 0.69 / -21.7% / worst year -16.1% at cap 200%, volume surge) as a check
that nothing in the pipeline changed. Positions still open on the last day are closed at that day's close (counted separately). THIS IS THE ONE SEALED RUN: it is not to be rerun with changed settings.
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
import er_stocks_start_years as SY
from er_stocks import CAPITAL, EPOCH

IS_END = pd.Timestamp("2021-08-06")
OOS_START = pd.Timestamp("2021-08-09")
FAR = pd.Timestamp("2100-01-01")
BORROW = 0.04
K = 8


def patch(name, value):
    n = 0
    for mod in list(sys.modules.values()):
        if mod is not None and hasattr(mod, name) and isinstance(getattr(mod, name, None), pd.Timestamp):
            setattr(mod, name, value); n += 1
    return n


def stats_for(P, dates, lo, hi, borrow=None):
    Q = MI.add_interest(P, 0.0, borrow) if borrow else P
    st, cal_y = B.wstats(Q["pnl"], dates, lo, hi, Q["open_n"], Q["gross"])
    dd = abs(st["max drawdown %"])
    st = dict(st); st["profit per year / drawdown"] = st["profit per year %"] / dd if dd > 0 else np.nan
    return st, cal_y


def spy_pnl(spy_close, dates, lo, hi):
    sel = np.flatnonzero(np.asarray((dates >= lo) & (dates <= hi)))
    i0 = sel[0]
    px = spy_close[i0 - 1] if i0 > 0 and np.isfinite(spy_close[i0 - 1]) else spy_close[i0]
    sh = np.floor(CAPITAL / px)
    pnl = np.zeros(len(spy_close)); pnl[sel] = sh * np.diff(np.r_[px, spy_close[sel]])
    return pnl


def surge_key(R, SEG, FEAT):
    sym, t = I1.trade_rows(SEG, R)
    surge = np.array([FEAT[(sym[k], t[k])]["s20_sig"] for k in range(len(R["d"]))], float)
    return -np.where(np.isfinite(surge), surge, -1e9) + np.random.default_rng(20261118).random(len(R["d"])) * 1e-9


def row_of(label, st, P, R, dates, lo, hi, cap, spy_close):
    ed = dates[R["sess_e"]]
    inw = P["taken"] & np.asarray((ed >= lo) & (ed <= hi))
    bench = (spy_close[R["sess_x"]] / spy_close[R["sess_e"]] - 1.0) * R["px_e"] / R["a0"]
    ra = R["res"][inw]; bm = bench[inw]; bm = bm[np.isfinite(bm)]
    sel = np.asarray((dates >= lo) & (dates <= hi))
    g = P["gross"][sel] / CAPITAL * 100
    out = {"version": label, "profit per year %": st["profit per year %"], "max drawdown % (from peak)": st["max drawdown %"], "profit per year / drawdown": st["profit per year / drawdown"],
           "Sharpe ratio": st["Sharpe ratio"], "worst year %": st["worst year %"], "years positive": st["years positive"], "trades taken": int(inw.sum()),
           "average open positions": st["average open positions"], "% of sessions at the cap": float((g >= cap * 100 * 0.95).mean() * 100),
           "average ATR per trade": float(ra.mean()) if inw.any() else np.nan, "SPY move over the same holds (ATR units)": float(bm.mean()) if len(bm) else np.nan}
    out["excess over SPY (ATR units)"] = out["average ATR per trade"] - out["SPY move over the same holds (ATR units)"]
    return out


def main():
    prices_path, out_dir, spy_path = sys.argv[1], Path(sys.argv[2]), sys.argv[3]
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"patched END in {patch('END', FAR)} modules (the in-sample cut is no longer applied; the sealed years are read from here on)", flush=True)
    ctx, names, live, E20, dates, spy_close, mk200 = MI.setup(prices_path, spy_path)
    SEG, dropped, cal, _ = ctx
    last = dates[-1]
    spy_dates = (pd.read_csv(spy_path) if spy_path.endswith(".csv") else pd.read_parquet(spy_path))["date_i"]
    print(f"calendar {dates[0].date()} to {last.date()} ({len(dates)} sessions); SPY file last date {(EPOCH + pd.Timedelta(days=int(spy_dates.max()))).date()}; sessions after the cut: {int((dates > IS_END).sum())}", flush=True)
    assert last > pd.Timestamp("2022-06-30"), "the data does not extend past mid-2022: nothing to test"
    FEAT = NV.build_features(ctx, E20)
    pd.set_option("display.width", 320); pd.set_option("display.max_columns", 40); pd.set_option("display.max_rows", 200)

    # ---- 1. reproduce the in-sample baseline with the same code (check)
    patch("FIRST_TRADE", pd.Timestamp("2000-03-01"))
    R_is = MI.gen(ctx, mk200)
    key_is = surge_key(R_is, SEG, FEAT)
    lo0 = pd.Timestamp("2000-01-01")
    for cap in (2.0, 1.0):
        P = MI.portfolio_gen(R_is, cal, cap, key_is)
        st, _ = stats_for(P, dates, lo0, IS_END)
        print(f"CHECK in-sample whole 2000 to Aug 2021, volume surge, cap {int(cap*100)}%: {st['profit per year %']:+.1f}% / Sharpe {st['Sharpe ratio']:.2f} / {st['max drawdown %']:.1f}% / worst year {st['worst year %']:.1f}%"
              + ("   (documented +25.1% / 0.69 / -21.7% / -16.1%)" if cap == 2.0 else "   (documented +14.5% / 0.67 / -18.1% / -11.4%)"), flush=True)
        if cap == 2.0 and abs(st["Sharpe ratio"] - 0.69) > 0.03:
            print("!!!! IN-SAMPLE CHECK DOES NOT MATCH THE DOCUMENTED BASELINE: treat the out-of-sample numbers as unverified !!!!", flush=True)
    del R_is

    # ---- 2. the out-of-sample run: account empty on the first session after the cut
    patch("FIRST_TRADE", OOS_START)
    R = MI.gen(ctx, mk200)
    n = len(R["d"])
    key_s = surge_key(R, SEG, FEAT)
    print(f"out-of-sample signals (entries from {OOS_START.date()} on, before any account limit): {n:,}; closed because the data ended: {int((R['how'] == 'data end').sum())}", flush=True)
    sel = np.asarray(dates >= OOS_START)
    print(f"SPY above its 200-day average on {mk200[sel].mean()*100:.0f}% of out-of-sample sessions", flush=True)
    lo, hi = OOS_START, last

    spy = spy_pnl(spy_close, dates, lo, hi)
    st_spy, cy_spy = B.wstats(spy, dates, lo, hi)
    dd = abs(st_spy["max drawdown %"]); st_spy["profit per year / drawdown"] = st_spy["profit per year %"] / dd
    print(f"SPY buy and hold {lo.date()} to {hi.date()} (price only): {st_spy['profit per year %']:+.1f}% a year / max drawdown {st_spy['max drawdown %']:.1f}% / profit÷drawdown {st_spy['profit per year / drawdown']:.2f} / Sharpe {st_spy['Sharpe ratio']:.2f} / worst year {st_spy['worst year %']:.1f}%", flush=True)

    variants = [("cap 200%, 4% charge on borrowed money", 2.0, BORROW), ("cap 200%, no charge on borrowed money", 2.0, None), ("cap 100% (no borrowing)", 1.0, None)]
    tables = {}; yearly = {}
    for vname, cap, borrow in variants:
        rows = []
        P = MI.portfolio_gen(R, cal, cap, key_s)
        st, cy = stats_for(P, dates, lo, hi, borrow)
        Pq = MI.add_interest(P, 0.0, borrow) if borrow else P
        rows.append(row_of("volume surge ranking", st, P, R, dates, lo, hi, cap, spy_close)); yearly[(vname, "volume surge ranking")] = cy
        rnd = []; cys = []
        for s in range(K):
            keyr = np.random.default_rng(1000 + s).random(n)
            Pr = MI.portfolio_gen(R, cal, cap, keyr)
            sr, cyr = stats_for(Pr, dates, lo, hi, borrow)
            rnd.append(row_of(f"random pick {s+1}", sr, Pr, R, dates, lo, hi, cap, spy_close)); cys.append(cyr)
        D = pd.DataFrame(rnd)
        mean = {c: D[c].mean() for c in D.columns if c not in ("version", "years positive")}
        mean.update(version="without volume surge: mean of 8 random picks", **{"years positive": ""})
        rows.append(mean)
        rows.append({"version": "  random picks, lowest", **{c: D[c].min() for c in ("profit per year %", "max drawdown % (from peak)", "profit per year / drawdown", "Sharpe ratio", "worst year %")}})
        rows.append({"version": "  random picks, highest", **{c: D[c].max() for c in ("profit per year %", "max drawdown % (from peak)", "profit per year / drawdown", "Sharpe ratio", "worst year %")}})
        rows.append({"version": "SPY buy and hold (price only)", "profit per year %": st_spy["profit per year %"], "max drawdown % (from peak)": st_spy["max drawdown %"], "profit per year / drawdown": st_spy["profit per year / drawdown"],
                     "Sharpe ratio": st_spy["Sharpe ratio"], "worst year %": st_spy["worst year %"], "years positive": st_spy["years positive"]})
        T = pd.DataFrame(rows); tables[vname] = T
        yearly[(vname, "without volume surge (mean of 8 random picks)")] = pd.concat(cys, axis=1).mean(axis=1)
        T.round(3).to_csv(out_dir / f"oos_{vname.split(',')[0].replace(' ', '').replace('%', '')}_{'charge' if borrow else 'nocharge'}.csv", index=False)
        print(f"\n==== OUT OF SAMPLE {lo.date()} to {hi.date()} | {vname} | fixed $300,000 account, started empty ====")
        print(T.round(2).to_string(index=False), flush=True)
        # how much does the volume-surge ranking actually change the trades the account takes?
        Ps = MI.portfolio_gen(R, cal, cap, key_s)
        print(f"  trades taken with volume surge: {int(Ps['taken'].sum()):,} of {n:,} signals; random picks take {D['trades taken'].mean():.0f} on average; trades taken by both lists overlap (volume surge vs the first random draw): "
              f"{int((Ps['taken'] & MI.portfolio_gen(R, cal, cap, np.random.default_rng(1000).random(n))['taken']).sum()):,}", flush=True)

    # ---- 3. year by year (cap 200% with the 4% charge, and 100%)
    for vname in (variants[0][0], variants[2][0]):
        Y = pd.DataFrame({"volume surge %": yearly[(vname, "volume surge ranking")], "without volume surge, mean of 8 random picks %": yearly[(vname, "without volume surge (mean of 8 random picks)")], "SPY buy and hold %": cy_spy})
        Y.round(2).to_csv(out_dir / f"oos_by_year_{vname.split(',')[0].replace(' ', '').replace('%', '')}.csv")
        print(f"\n==== profit by calendar year, percent of $300,000 | {vname} (first and last years are partial) ====")
        print(Y.round(1).to_string(), flush=True)
    print("done")


if __name__ == "__main__":
    main()
