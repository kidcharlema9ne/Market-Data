"""Stocks, long only: how far below the ORIGINAL $300,000 the account gets when started at the beginning of every 3-month (and 6-month) period (Michael, 19 Nov 2026).
Usage: python er_stocks_initial_drawdown.py stock_prices.parquet OUT_DIR spy_prices.parquet

Same baseline as er_stocks_start_years.py (volume-surge ranking when full, fixed $300,000, 0.10% per ATR, 0.05 ATR a side, position value capped at 200% and at 100%; common stocks, $3M floor, SPY above its 200-day).
Account is started EMPTY on the first day of each calendar quarter (and each half-year) from 2000 to 2021 and run to the end of the development data (6 Aug 2021). Not peak to valley: the measure is
the lowest account value reached, compared with the starting $300,000 (closed trades plus open positions marked each day). Reported for each start:
  - lowest point over the whole run (percent and dollars below $300,000; 0 if the account never went below it), and the date of that low
  - lowest point inside the first 12 months and first 24 months
  - date the account first got back above $300,000 for good after that low (never, if it did not), and days from start to the low
  - profit per year of the whole run, for context
In-sample only; the sealed years are never read.
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
from er_stocks import CAPITAL, END


def low_stats(pnl, dates, lo, hi):
    sel = np.flatnonzero(np.asarray((dates >= lo) & (dates <= hi)))
    if len(sel) < 30:
        return None
    d = pd.DatetimeIndex(dates[sel])
    eq = CAPITAL + np.cumsum(pnl[sel])
    out = {"start": lo.date().isoformat(), "end": hi.date().isoformat()}
    for lab, days in (("whole run", None), ("first 12 months", 365), ("first 24 months", 730)):
        m = np.ones(len(eq), bool) if days is None else np.asarray(d <= lo + pd.Timedelta(days=days))
        if m.sum() < 5:
            out[f"lowest % vs $300k, {lab}"] = np.nan
            continue
        e = eq[m]
        i = int(np.argmin(e))
        low = min(e[i] - CAPITAL, 0.0)
        out[f"lowest % vs $300k, {lab}"] = low / CAPITAL * 100
        if days is None:
            out["lowest $ vs $300k, whole run"] = low
            out["date of lowest"] = d[i].date().isoformat() if low < 0 else "never below"
            out["days from start to lowest"] = int((d[i] - lo).days) if low < 0 else 0
            if low < 0:
                above = np.flatnonzero(eq[i:] > CAPITAL)
                out["back above $300k"] = d[i + above[0]].date().isoformat() if len(above) else "never"
            else:
                out["back above $300k"] = ""
    out["profit per year %"] = (eq[-1] - CAPITAL) / CAPITAL * 100 / (len(eq) / 252.0)
    out["profit % at end"] = (eq[-1] - CAPITAL) / CAPITAL * 100
    return out


def starts(step_months):
    s = []
    for y in range(2000, 2022):
        for mth in range(1, 13, step_months):
            t = pd.Timestamp(year=y, month=mth, day=1)
            if t < END - pd.Timedelta(days=365):      # need at least a year of run
                s.append(t)
    return s


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
    key = -np.where(np.isfinite(surge), surge, -1e9) + np.random.default_rng(20261118).random(n) * 1e-9
    for cap in (2.0, 1.0):
        P = B.wstats(MI.portfolio_gen(R, cal, cap, key)["pnl"], dates, pd.Timestamp("2000-01-01"), END)[0]
        print(f"whole period, cap {int(cap*100)}%: {P['profit per year %']:+.1f}% a year / max drawdown {P['max drawdown %']:.1f}% (documented: cap 200% +25.1% / -21.7%; cap 100% +14.5% / -18.1%)", flush=True)
    pd.set_option("display.width", 320); pd.set_option("display.max_columns", 40); pd.set_option("display.max_rows", 400)
    for cap in (2.0, 1.0):
        cl = f"cap{int(cap*100)}"
        for step, nm in ((3, "3-month starts"), (6, "6-month starts")):
            rows = []
            for lo in starts(step):
                ed = dates[R["sess_e"]]
                m = np.asarray((ed >= lo) & (ed <= END))
                if m.sum() < 5:
                    continue
                Rs = SY.subset(R, m)
                P = MI.portfolio_gen(Rs, cal, cap, key[m])
                r = low_stats(P["pnl"], dates, lo, END)
                if r:
                    rows.append(r)
            df = pd.DataFrame(rows)
            df.round(2).to_csv(out_dir / f"initial_drawdown_{cl}_{nm.replace(' ', '_').replace('-', '')}.csv", index=False)
            col = "lowest % vs $300k, whole run"
            print(f"\n==== {nm} | cap {int(cap*100)}% | account started empty on the first day of each period, run to 6 Aug 2021 ====")
            print(df[["start", col, "lowest $ vs $300k, whole run", "date of lowest", "days from start to lowest", "back above $300k",
                      "lowest % vs $300k, first 12 months", "lowest % vs $300k, first 24 months", "profit per year %"]].round(1).to_string(index=False))
            print(f"  worst start: {df.loc[df[col].idxmin(), 'start']} at {df[col].min():.1f}% ; median lowest {df[col].median():.1f}% ; starts that never went below $300k: {int((df[col] >= 0).sum())} of {len(df)} ; "
                  f"starts that lost 10%+ at some point: {int((df[col] <= -10).sum())} ; 20%+: {int((df[col] <= -20).sum())} ; 30%+: {int((df[col] <= -30).sum())}")
    print("done")


if __name__ == "__main__":
    main()
