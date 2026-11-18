"""Stocks, long only: the stock's OWN moving average as an entry condition and as an exit (Michael, 18 Nov 2026).
Usage: python er_stocks_ma_gates.py stock_prices.parquet OUT_DIR spy_prices.parquet MODE
Everything else is the current best rule (hand-off doc), exactly as in er_stocks_many_ideas.py (top 20% by 126-session return, 4 ATR initial stop, 5 ATR trailing stop, 1.5 ATR pullback entry, SPY above its 200-day for entries, caps 200% and 100%, 8 random picks).
MODES
  entry  (1) REPLACE the SPY 200-day condition with: the stock closed above its own 50, 100 or 200-day average on the trigger day. (2) KEEP the SPY condition and also require the stock above its own 50, 100 or 200-day average.
  bear   Bear-market exception: enter when SPY is above its 200-day average OR the stock is above its own 50, 100 or 200-day average (still the top 20% by 126-session return). Full size. Reports how many trades start while SPY is below its 200-day average.
  exit   Exit (next open) when the stock closes below its own 50, 100 or 200-day average: (a) in addition to the 4 ATR initial and 5 ATR trailing stops, (b) in place of the trailing stop (initial stop kept), (c) in addition, but only on days when SPY is below its 200-day average.
In-sample only (data through 2021-08-06); sealed years not read. Post hoc.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
import pandas as pd

import er_stocks as B
import er_stocks_many_ideas as MI
from er_stocks import CAPITAL, END

MAS = (50, 100, 200)
_ma = {}
S_OF = {}


def ma_of(c, N):
    k = (id(c), N)
    if k not in _ma:
        _ma[k] = pd.Series(np.asarray(c, float)).rolling(N, min_periods=N).mean().to_numpy()
    return _ma[k]


def above(N):
    def f(i, g, t):
        m = ma_of(g["c"], N)[t]
        return bool(np.isfinite(m) and g["c"][t] > m)
    return f


def make_runner(N, replace, only_bear, MK, use_ma=True):
    mm = 1e9 if replace else 5.0
    def runner(o, h, l, c, atr, t, d):
        n = len(c); e = t + 1
        if e >= n:
            return None
        ma = ma_of(c, N); s = S_OF[id(c)]
        a0 = atr[t]; entry = o[e]; stop = entry - 4.0 * a0; best = entry; marks = []
        for j in range(e, n):
            if l[j] <= stop:
                gap = j > e and o[j] <= stop
                return j, (o[j] if gap else stop), marks, "stop"
            marks.append(c[j]); best = max(best, c[j])
            na = atr[j]
            if na == na:
                stop = max(stop, best - mm * na)
            if use_ma and (not only_bear or not MK[s[j]]) and ma[j] == ma[j] and c[j] < ma[j] and j + 1 < n:
                return j + 1, o[j + 1], marks, "stock average exit"
        return n - 1, c[n - 1], marks[:-1], "data end"
    return runner


def main():
    prices_path, out_dir, spy_path, mode = sys.argv[1], Path(sys.argv[2]), sys.argv[3], sys.argv[4]
    out_dir.mkdir(parents=True, exist_ok=True)
    ctx, names, live, E20, dates, spy_close, mk200 = MI.setup(prices_path, spy_path)
    SEG, dropped, cal, _ = ctx
    for g in SEG:
        S_OF[id(g["c"])] = g["s"]
    pd.set_option("display.width", 340); pd.set_option("display.max_columns", 40); pd.set_option("display.max_colwidth", 110); pd.set_option("display.max_rows", 900)
    MI.check_baseline(ctx, mk200)
    # self-test: the copied exit routine with the stock-average exit switched off equals the standard one
    n = 0
    for i, g in enumerate(SEG):
        if i in dropped or not g["cand"]:
            continue
        for t, d in g["cand"][:2]:
            a = MI.base_runner(g["o"], g["h"], g["l"], g["c"], g["atr"], t, 1); b = make_runner(200, False, False, mk200, use_ma=False)(g["o"], g["h"], g["l"], g["c"], g["atr"], t, 1)
            if a is None:
                assert b is None; continue
            assert a[0] == b[0] and a[1] == b[1] and np.allclose(a[2], b[2]) and a[3] == b[3], (i, t); n += 1
        if n > 300:
            break
    print(f"copied exit routine (average exit off) matches the standard one on {n} trades", flush=True)
    rows = []
    base = MI.gen(ctx, mk200)
    rows += MI.scen(ctx, base, {"idea": "baseline", "scenario": "current best rule (SPY above its 200-day for entries)"}); MI.line(rows, "baseline")
    allon = np.ones(len(cal), bool)
    def run(name, idea, R, **kw):
        r = MI.scen(ctx, R, {"idea": idea, "scenario": name}, **kw); rows.extend(r); MI.line(r, name)
    def spy_below_share(R):
        ok = np.asarray(mk200)[np.maximum(R["sess_e"] - 1, 0)]
        return float((~ok).mean() * 100) if len(ok) else float("nan")
    if mode == "entry":
        for N in MAS:
            R = MI.gen(ctx, allon, cond=above(N))
            run(f"REPLACE the SPY condition: stock above its own {N}-day average", "1 stock average instead of SPY", R)
            print(f"     ({len(R['d']):,} signals; {spy_below_share(R):.0f}% of them start while SPY is below its 200-day)", flush=True)
        for N in MAS:
            R = MI.gen(ctx, mk200, cond=above(N))
            run(f"KEEP the SPY condition AND stock above its own {N}-day average", "2 both conditions", R)
    elif mode == "bear":
        for N in MAS:
            f = above(N)
            R = MI.gen(ctx, allon, cond=lambda i, g, t, f=f: bool(mk200[g["s"][t]]) or f(i, g, t))
            run(f"SPY above its 200-day OR stock above its own {N}-day average (top 20% by 126-session return)", "3 bear-market exception", R)
            print(f"     ({len(R['d']):,} signals vs {len(base['d']):,} in the base rule; {spy_below_share(R):.0f}% start while SPY is below its 200-day)", flush=True)
    elif mode == "exit":
        for N in MAS:
            for tag, replace, only_bear in (("in addition to the stops", False, False), ("in place of the trailing stop", True, False), ("in addition, only while SPY is below its 200-day", False, True)):
                R = MI.gen(ctx, mk200, runner=make_runner(N, replace, only_bear, mk200))
                run(f"exit when the stock closes below its own {N}-day average, {tag}", "4 stock-average exit", R)
                print(f"     (share of trades ended by the average: {float((R['how'] == 'stock average exit').mean() * 100):.0f}%)", flush=True)
    S = pd.DataFrame(rows); S.to_csv(out_dir / f"ma_gates_{mode}.csv", index=False)
    S["profit / drawdown from peak"] = S["profit per year %"] / S["max drawdown %"].abs()
    cols = ["scenario", "profit per year %", "Sharpe ratio", "Sharpe lowest pick", "Sharpe highest pick", "max drawdown %", "profit / drawdown from peak", "worst year %", "trades taken", "average open positions"]
    for wn in ctx[3][2]:
        for cap in (200, 100):
            print(f"\n==== {mode} | {wn} | cap {cap}% | mean of {MI.KSEEDS} random picks ====")
            v = S[(S.period == wn) & (S["cap %"] == cap)]
            print(v[[c for c in cols if c in v.columns]].round(2).to_string(index=False))
    print("done")


if __name__ == "__main__":
    main()
