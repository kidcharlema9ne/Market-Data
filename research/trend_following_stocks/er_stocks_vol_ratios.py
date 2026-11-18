"""Stocks, long only. NEW BASELINE (Michael, 18 Nov 2026): current rule + volume-surge ranking when the account is full + exit when the stock closes below its own 125-day average, in addition to the 4 ATR initial and 5 ATR trailing stops.
Usage: python er_stocks_vol_ratios.py stock_prices.parquet OUT_DIR spy_prices.parquet MODE      (MODE = hv or atr)
Test: on the trigger day (the pullback day, one day before the buy), compare short-term volatility with longer-term volatility and only take the trade if the ratio is in a chosen part of its range.
  hv  : historical volatility = standard deviation of daily log returns over N sessions ending on the trigger day.
  atr : average true range over N sessions ending on the trigger day.
Ratios (short window / long window): 5/10, 5/20, 5/90, 10/20, 10/90, 20/90.
Gates: lowest third, lowest half, highest half, highest third of the ratio's range. Range cut-offs come from ALL signals in the sample (so each gate keeps about a third or a half of signals; cut-off values are printed).
Ranked rows are one deterministic run each (volume-surge ranking). In-sample only (data through 2021-08-06). Post hoc.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
import pandas as pd

import er_stocks as B
import er_stocks_ideas_1_2_6 as I1
import er_stocks_many_ideas as MI
import er_stocks_ma_gates as G
import er_stocks_nasdaq_volume as NV

PAIRS = [(5, 10), (5, 20), (5, 90), (10, 20), (10, 90), (20, 90)]
_c = {}


def measure(g, kind, N):
    k = (id(g["c"]), kind, N)
    if k not in _c:
        c = np.asarray(g["c"], float)
        if kind == "hv":
            r = np.log(c / np.r_[np.nan, c[:-1]])
            _c[k] = pd.Series(r).rolling(N, min_periods=N).std().to_numpy()
        else:
            h, l = np.asarray(g["h"], float), np.asarray(g["l"], float); pc = np.r_[np.nan, c[:-1]]
            tr = np.nanmax(np.vstack([h - l, np.abs(h - pc), np.abs(l - pc)]), axis=0)
            tr[0] = np.nan
            _c[k] = pd.Series(tr).rolling(N, min_periods=N).mean().to_numpy()
    return _c[k]


def ratio_at(g, kind, a, b, t):
    x, y = measure(g, kind, a)[t], measure(g, kind, b)[t]
    return x / y if (np.isfinite(x) and np.isfinite(y) and y > 0) else np.nan


def main():
    prices_path, out_dir, spy_path, kind = sys.argv[1], Path(sys.argv[2]), sys.argv[3], sys.argv[4]
    out_dir.mkdir(parents=True, exist_ok=True)
    ctx, names, live, E20, dates, spy_close, mk200 = MI.setup(prices_path, spy_path)
    SEG, dropped, cal, _ = ctx
    for g in SEG:
        G.S_OF[id(g["c"])] = g["s"]
    pd.set_option("display.width", 340); pd.set_option("display.max_columns", 40); pd.set_option("display.max_colwidth", 120); pd.set_option("display.max_rows", 900)
    MI.check_baseline(ctx, mk200)
    FEAT = NV.build_features(ctx, E20)
    keys = list(FEAT.keys())
    runner = G.make_runner(125, False, False, mk200)
    rows = []

    def key_from_feat(R):
        sym, t = I1.trade_rows(SEG, R)
        sc = np.array([FEAT[(sym[k], t[k])]["s20_sig"] for k in range(len(sym))], float)
        return -np.where(np.isfinite(sc), sc, -1e9) + np.random.default_rng(20261118).random(len(sc)) * 1e-9

    def ranked(name, R):
        r = NV.scen_key(ctx, R, {"idea": f"{kind} ratio gate", "scenario": name}, key_from_feat(R)); rows.extend(r); MI.line(r, name)

    ranked("NEW BASELINE: volume-surge ranking + 125-day exit in addition to stops", MI.gen(ctx, mk200, runner=runner))
    name_of = {"hv": "historical volatility", "atr": "average true range"}[kind]
    for a, b in PAIRS:
        vals = np.array([ratio_at(SEG[i], kind, a, b, t) for (i, t) in keys], float)
        v = vals[np.isfinite(vals)]
        q33, q50, q67 = np.percentile(v, [33.3, 50, 66.7])
        print(f"\n{name_of} {a}-day / {b}-day ratio: lowest third < {q33:.2f}, median {q50:.2f}, highest third > {q67:.2f}  ({len(v):,} signals)", flush=True)
        gates = [("lowest third", lambda x, q=q33: x < q), ("lowest half", lambda x, q=q50: x < q), ("highest half", lambda x, q=q50: x >= q), ("highest third", lambda x, q=q67: x > q)]
        for gname, fn in gates:
            def cond(i, g, t, fn=fn, a=a, b=b):
                x = ratio_at(g, kind, a, b, t)
                return bool(np.isfinite(x) and fn(x))
            ranked(f"{name_of} {a}-day / {b}-day ratio in its {gname}", MI.gen(ctx, mk200, cond=cond, runner=runner))
    S = pd.DataFrame(rows); S.to_csv(out_dir / f"vol_ratios_{kind}.csv", index=False)
    S["profit / drawdown from peak"] = S["profit per year %"] / S["max drawdown %"].abs()
    cols = ["scenario", "profit per year %", "max drawdown %", "profit / drawdown from peak", "worst year %", "Sharpe ratio", "trades taken"]
    for wn in ctx[3][2]:
        for cap in (200, 100):
            print(f"\n==== {kind} | {wn} | cap {cap}% ====")
            v = S[(S.period == wn) & (S["cap %"] == cap)]
            print(v[[c for c in cols if c in v.columns]].round(2).to_string(index=False))
    print("done")


if __name__ == "__main__":
    main()
