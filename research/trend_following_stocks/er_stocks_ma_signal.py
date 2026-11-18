"""Stocks, long only, with the VOLUME-SURGE RANKING as the pick when the account is full (Michael, 18 Nov 2026: the volume-surge ranking is the new baseline).
Usage: python er_stocks_ma_signal.py stock_prices.parquet OUT_DIR spy_prices.parquet MODE
Pick rule in every ranked row: when the account cannot take every signal that day, take the signal with the highest signal-day volume surge first (signal-day volume / average volume of the 20 sessions before it). Ranked rows are one deterministic run.
Everything else as in the current best rule (top 20% by 126-session return on the trigger day, SPY above its 200-day for entries unless stated, 1.5 ATR pullback, 4 ATR initial and 5 ATR trailing stop, caps 200% and 100%).
MODES
  entry            volume-surge baseline; keep the SPY condition AND require the stock above its own 50, 100 or 200-day average on the trigger day.
  exit_in_addition exit (next open) when the stock closes below its own 50, 75, 100, 125 or 200-day average, in addition to the stops.
  exit_in_place    same, in place of the 5 ATR trailing stop (4 ATR initial stop kept).
  exit_spy_below   same, in addition to the stops, but only on days when SPY is below its 200-day average.
  signal           the efficiency ratio signal is REPLACED by a moving-average signal. (a) cross-up: the first close above the stock's own 50, 100 or 200-day average after being below starts a 20-session watch; buy the next open after a close 1.5 ATR below the highest high since. (b) state: the stock is above its own average and has fallen 1.5 ATR below its highest high of the last 20 sessions (first such day); buy the next open. Random pick (8 picks) for both; cross-up also ranked by the cross-day volume surge.
In-sample only (data through 2021-08-06). Post hoc.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
import pandas as pd

import er_stocks as B
import er_stocks_common_momentum as M
import er_stocks_ideas_1_2_6 as I1
import er_stocks_many_ideas as MI
import er_stocks_ma_gates as G
import er_stocks_nasdaq_volume as NV
from er_stocks_combined_er import cands_from_q

SURGE = {}


def surge_array(i):
    v = np.asarray(MI.VOLS[i], float)
    m20 = pd.Series(v).shift(1).rolling(20, min_periods=20).mean().to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(m20 > 0, v / m20, np.nan)


def main():
    prices_path, out_dir, spy_path, mode = sys.argv[1], Path(sys.argv[2]), sys.argv[3], sys.argv[4]
    out_dir.mkdir(parents=True, exist_ok=True)
    ctx, names, live, E20, dates, spy_close, mk200 = MI.setup(prices_path, spy_path)
    SEG, dropped, cal, _ = ctx
    for g in SEG:
        G.S_OF[id(g["c"])] = g["s"]
    pd.set_option("display.width", 340); pd.set_option("display.max_columns", 40); pd.set_option("display.max_colwidth", 120); pd.set_option("display.max_rows", 900)
    MI.check_baseline(ctx, mk200)
    FEAT = NV.build_features(ctx, E20)
    rows = []

    def key_from_feat(R):
        sym, t = I1.trade_rows(SEG, R)
        sc = np.array([FEAT[(sym[k], t[k])]["s20_sig"] for k in range(len(sym))], float)
        return -np.where(np.isfinite(sc), sc, -1e9) + np.random.default_rng(20261118).random(len(sc)) * 1e-9

    def key_from_surge(R):
        sym, t = I1.trade_rows(SEG, R)
        sc = np.array([SURGE.get((sym[k], t[k]), np.nan) for k in range(len(sym))], float)
        return -np.where(np.isfinite(sc), sc, -1e9) + np.random.default_rng(20261118).random(len(sc)) * 1e-9

    def ranked(name, idea, R, keyfn=key_from_feat):
        r = NV.scen_key(ctx, R, {"idea": idea, "scenario": name}, keyfn(R)); rows.extend(r); MI.line(r, name)

    def randomp(name, idea, R):
        r = MI.scen(ctx, R, {"idea": idea, "scenario": name}); rows.extend(r); MI.line(r, name)

    base = MI.gen(ctx, mk200)
    ranked("BASELINE: current rule, ranked by signal-day volume surge", "baseline", base)
    if mode == "entry":
        for N in G.MAS:
            ranked(f"surge ranking, SPY condition AND stock above its own {N}-day average", "entry", MI.gen(ctx, mk200, cond=G.above(N)))
    elif mode in ("exit_in_addition", "exit_in_place", "exit_spy_below"):
        replace, only_bear = {"exit_in_addition": (False, False), "exit_in_place": (True, False), "exit_spy_below": (False, True)}[mode]
        for N in (50, 75, 100, 125, 200):
            R = MI.gen(ctx, mk200, runner=G.make_runner(N, replace, only_bear, mk200))
            ranked(f"surge ranking, exit when the stock closes below its own {N}-day average ({mode.replace('exit_', '').replace('_', ' ')})", "exit", R)
            print(f"     (share of trades ended by the average: {float((R['how'] == 'stock average exit').mean() * 100):.0f}%)", flush=True)
    elif mode == "signal":
        randomp("current signal (efficiency ratio), random pick", "baseline", base)
        allon = mk200
        for N in G.MAS:
            sm_all = {}
            def cross(i, g, N=N, sm_all=sm_all):
                c, atr = g["c"], g["atr"]; ma = G.ma_of(c, N)
                q = np.isfinite(ma) & (c > ma) & np.isfinite(atr) & (atr > 1e-6 * c)
                out = cands_from_q(g, q, 1.5)
                if out:
                    sm = NV.sig_map(g, q); s20 = surge_array(i)
                    for t, _ in out:
                        SURGE[(i, t)] = s20[sm[t]]
                return out
            Rc = MI.gen(ctx, mk200, cands=lambda i, g, f=cross: f(i, g))
            print(f"     (cross-up above the {N}-day average: {len(Rc['d']):,} signals vs {len(base['d']):,})", flush=True)
            randomp(f"signal REPLACED: first close above the stock's own {N}-day average, then 1.5 ATR pullback (random pick)", "signal replaced, cross-up", Rc)
            ranked(f"signal REPLACED: cross-up above the {N}-day average, ranked by cross-day volume surge", "signal replaced, cross-up", Rc, key_from_surge)
            def state(i, g, N=N):
                c, h, atr = g["c"], g["h"], g["atr"]; n = len(c); ma = G.ma_of(c, N)
                hh = pd.Series(h).rolling(20, min_periods=20).max().to_numpy()
                with np.errstate(invalid="ignore"):
                    cond = np.isfinite(ma) & (c > ma) & np.isfinite(atr) & (atr > 1e-6 * c) & ((hh - c) / atr >= 1.5)
                trig = cond & ~np.r_[False, cond[:-1]]
                return [(int(t), 1) for t in np.where(trig)[0] if t + 1 < n]
            Rs = MI.gen(ctx, mk200, cands=lambda i, g, f=state: f(i, g))
            print(f"     (state version above the {N}-day average: {len(Rs['d']):,} signals)", flush=True)
            randomp(f"signal REPLACED: stock above its own {N}-day average and 1.5 ATR below its 20-session high (random pick)", "signal replaced, state", Rs)
    S = pd.DataFrame(rows); S.to_csv(out_dir / f"ma_signal_{mode}.csv", index=False)
    S["profit / drawdown from peak"] = S["profit per year %"] / S["max drawdown %"].abs()
    cols = ["scenario", "profit per year %", "Sharpe ratio", "max drawdown %", "profit / drawdown from peak", "worst year %", "trades taken"]
    for wn in ctx[3][2]:
        for cap in (200, 100):
            print(f"\n==== {mode} | {wn} | cap {cap}% ====")
            v = S[(S.period == wn) & (S["cap %"] == cap)]
            print(v[[c for c in cols if c in v.columns]].round(2).to_string(index=False))
    print("done")


if __name__ == "__main__":
    main()
