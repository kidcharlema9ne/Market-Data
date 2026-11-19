"""Diagnostics for the sealed-year run (er_stocks_oos.py, Entry 171). NOTHING IN THE RULE IS CHANGED OR TUNED: this only looks at whether the poor out-of-sample result is real trading or a data artifact, and compares trade quality by entry year.
Usage: python er_stocks_oos_diagnostics.py stock_prices.parquet OUT_DIR spy_prices.parquet

One continuous account from 2000-03-01 to the last day (cap 200%, fixed $300,000, volume-surge ranking, no borrowing charge) so every entry year is on the same footing. Tables:
  1. by entry year: signals, trades taken, average result in ATR (net of cost) with SPY's move over the same holds beside it, win rate, share of trades stopped out by a gap, dollars as percent of $300,000, share of sessions the SPY 200-day gate is on.
  2. the 25 worst and 25 best taken trades from 9 Aug 2021 on, by dollars (symbol, dates, prices, result in ATR, shares), to spot unadjusted splits or bad prints.
  3. the out-of-sample profit by the entry half-year (what the trades entered in each half-year earned in total, however long they were held).
  4. biggest one-day moves in held positions (a split not removed would show as a near -50% or +100% day).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
import pandas as pd

import er_stocks as B
import er_stocks_many_ideas as MI
import er_stocks_nasdaq_volume as NV
import er_stocks_oos as O
from er_stocks import CAPITAL, EPOCH


def main():
    prices_path, out_dir, spy_path = sys.argv[1], Path(sys.argv[2]), sys.argv[3]
    out_dir.mkdir(parents=True, exist_ok=True)
    O.patch("END", O.FAR)
    ctx, names, live, E20, dates, spy_close, mk200 = MI.setup(prices_path, spy_path)
    SEG, dropped, cal, _ = ctx
    FEAT = NV.build_features(ctx, E20)
    O.patch("FIRST_TRADE", pd.Timestamp("2000-03-01"))
    R = MI.gen(ctx, mk200)
    n = len(R["d"])
    key = O.surge_key(R, SEG, FEAT)
    P = MI.portfolio_gen(R, cal, 2.0, key)
    tk = P["taken"]; sh = P["shares"]
    usd = sh * (R["res"] * R["a0"])
    ed = dates[R["sess_e"]]; xd = dates[R["sess_x"]]
    bench = (spy_close[R["sess_x"]] / spy_close[R["sess_e"]] - 1.0) * R["px_e"] / R["a0"]
    pd.set_option("display.width", 320); pd.set_option("display.max_columns", 40); pd.set_option("display.max_rows", 300)
    rows = []
    for y in range(2000, 2027):
        m = np.asarray(ed.year == y); mt = m & tk
        if m.sum() == 0:
            continue
        sel = np.asarray(dates.year == y) & np.asarray(dates >= pd.Timestamp("2000-03-01"))
        gap = mt & (R["how"] == "stop") & (R["px_x"] < R["px_e"] - 4.0 * R["a0"] - 1e-9)
        rows.append({"entry year": y, "signals": int(m.sum()), "trades taken": int(mt.sum()), "average ATR per trade (taken)": R["res"][mt].mean() if mt.any() else np.nan,
                     "SPY move over the same holds (ATR units)": np.nanmean(bench[mt]) if mt.any() else np.nan, "win rate % (taken)": (R["res"][mt] > 0).mean() * 100 if mt.any() else np.nan,
                     "median sessions held": float(np.median(R["held"][mt])) if mt.any() else np.nan, "stopped out by a gap through the initial stop %": gap.sum() / max(mt.sum(), 1) * 100,
                     "dollars of trades entered, % of $300,000": usd[mt].sum() / CAPITAL * 100, "SPY 200-day gate on, % of sessions": mk200[sel].mean() * 100,
                     "all signals average ATR (before account limit)": R["res"][m].mean()})
    T = pd.DataFrame(rows); T.round(3).to_csv(out_dir / "by_entry_year.csv", index=False)
    print("\n==== by entry year, one continuous cap-200% volume-surge account (no borrowing charge) ====")
    print(T.round(2).to_string(index=False), flush=True)

    oos = np.asarray(ed >= O.OOS_START) & tk
    idx = np.flatnonzero(oos)
    D = pd.DataFrame({"symbol": [names[R["sym"][k]] for k in idx], "entry": [d.date() for d in ed[idx]], "exit": [d.date() for d in xd[idx]], "entry price": R["px_e"][idx], "exit price": R["px_x"][idx],
                      "ATR dollars": R["a0"][idx], "result in ATR": R["res"][idx], "shares": sh[idx], "dollars": usd[idx], "sessions held": R["held"][idx], "how it ended": R["how"][idx]})
    D.sort_values("dollars").head(25).round(2).to_csv(out_dir / "worst25.csv", index=False)
    D.sort_values("dollars").tail(25).round(2).to_csv(out_dir / "best25.csv", index=False)
    print("\n==== 25 worst taken trades since 9 Aug 2021 (dollars) ====")
    print(D.sort_values("dollars").head(25).round(2).to_string(index=False))
    print("\n==== 25 best taken trades since 9 Aug 2021 (dollars) ====")
    print(D.sort_values("dollars").tail(25).round(2).to_string(index=False), flush=True)
    print(f"\nout-of-sample taken trades: {len(D):,}; total dollars {D['dollars'].sum():,.0f}; worst 25 sum {D.sort_values('dollars').head(25)['dollars'].sum():,.0f}; best 25 sum {D.sort_values('dollars').tail(25)['dollars'].sum():,.0f}; trades with result below -6 ATR: {(D['result in ATR'] < -6).sum()}; above +15 ATR: {(D['result in ATR'] > 15).sum()}")

    hy = pd.Series(["%dH%d" % (d.year, 1 if d.month <= 6 else 2) for d in ed[idx]])
    H = pd.DataFrame({"half-year of entry": hy, "dollars": usd[idx], "res": R["res"][idx]}).groupby("half-year of entry").agg(trades=("dollars", "size"), dollars=("dollars", "sum"), average_ATR=("res", "mean"))
    H["dollars % of $300,000"] = H["dollars"] / CAPITAL * 100
    H.round(2).to_csv(out_dir / "by_entry_half_year.csv")
    print("\n==== out of sample: what trades entered in each half-year earned in total (cap 200%, volume surge) ====")
    print(H.round(2).to_string(), flush=True)

    # one-day moves inside held positions: look for unremoved splits (a bad print would also show up as a gap stop fill)
    ex = []
    for k in idx:
        g = SEG[R["sym"][k]]; s = g["s"]; a = np.searchsorted(s, R["sess_e"][k]); b = np.searchsorted(s, R["sess_x"][k])
        c = g["c"].astype(float)
        if b > a:
            r1 = c[a + 1:b + 1] / c[a:b] - 1.0
            j = int(np.argmin(r1)); jj = int(np.argmax(r1))
            ex.append((names[R["sym"][k]], float(r1[j]), float(r1[jj]), dates[s[a + 1 + j]].date()))
    E = pd.DataFrame(ex, columns=["symbol", "worst one-day move", "best one-day move", "date of worst"])
    print("\n==== largest one-day closing moves inside taken out-of-sample trades ====")
    print(E.sort_values("worst one-day move").head(15).round(3).to_string(index=False))
    print(E.sort_values("best one-day move", ascending=False).head(10)[["symbol", "best one-day move"]].round(3).to_string(index=False))
    n_half = int((E["worst one-day move"] <= -0.45).sum())
    print(f"positions with a one-day close fall of 45% or more: {n_half}; of 100% or more rise: {int((E['best one-day move'] >= 1.0).sum())}", flush=True)
    print("done")


if __name__ == "__main__":
    main()
