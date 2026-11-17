"""Common stocks, long only, strongest 6-month performers, frozen rule: initial stop 4 ATR, trailing stop 5 ATR, no time limit.
Michael, 17 Nov 2026: "What if you exit the entire portfolio when SPY goes below the 200-day moving average, rather than just not take new positions?"
Usage: python er_stocks_exit_all.py stock_prices.parquet OUT_DIR spy_prices.parquet
EXIT RULE (new): when the market switch is OFF at the close of a session, every open long is sold at the NEXT session's open (a gap through a stop still fills at the open; same price). Re-entry only through a fresh signal while the switch is on.
Switch = SPY closes above its 200-session average (band 0%), or the band versions from Entry 138 (on above +w%, off below -w%, w = 1, 2, 3, 5; keeps state in between).
Compared: no market condition; entries only gated by SPY (Entry 136/137 rule, band 0%); and exit-everything versions for band 0, 1, 2, 3, 5%. Costs unchanged (0.05 ATR a side, so a forced exit costs the same as a stop exit).
Everything else exactly as er_stocks_market_band.py (common stocks, $3M floor, strength top 20% and all stocks, 0.10% of $300k per ATR, cap 200%, whole shares, data through 2021-08-06 only, same named SPY declines).
Post hoc on development years; grid; best row is not a result.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
import pandas as pd

import er_stocks as B
import er_stocks_common_momentum as M
from er_stocks import CAPITAL, END, EPOCH, MAIN_START
from er_stocks_market_band import switch, max_dd, EPISODES

TOPS = (0.20, 1.0)
SMA_N = 200
SEED = 20261117
VNAME = "initial stop 4 ATR, trailing stop 5 ATR"
OFF = {}                      # id(open array of a stock segment) -> boolean per row: switch is OFF at the close of that row
_orig_run_trade = B.run_trade


def kill_trade(o, h, l, c, atr, t, d, init, mm, cap):
    off = OFF.get(id(o))
    if off is None:
        return _orig_run_trade(o, h, l, c, atr, t, d, init, mm, cap)
    n = len(c); e = t + 1
    if e >= n:
        return None
    a0 = atr[t]; entry = o[e]; stop = entry - d * init * a0; best = entry; marks = []
    for j in range(e, n):
        k = j - e
        if k > 0 and off[j - 1]:
            return j, o[j], marks, "market switch off"
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


def selftest_kill():
    f = np.float64
    o = np.array([100, 100, 101, 102, 103, 104], f); h = o + 1; l = o - 1; c = o + 0.5; atr = np.full(6, 2.0)
    off = np.array([False, False, True, True, True, True])        # switch off at the close of row 2 -> sell at the open of row 3
    OFF[id(o)] = off
    r = kill_trade(o, h, l, c, atr, 0, 1, 4.0, 5.0, None)
    assert r[0] == 3 and r[1] == 102.0 and r[3] == "market switch off" and r[2] == [c[1], c[2]], r
    OFF[id(o)] = np.zeros(6, bool)
    r = kill_trade(o, h, l, c, atr, 0, 1, 4.0, 5.0, None)
    assert r[3] == "data end", r
    OFF.clear()
    print("forced-exit self-test passed", flush=True)


def main():
    prices_path, out_dir, spy_path = sys.argv[1], Path(sys.argv[2]), sys.argv[3]
    out_dir.mkdir(parents=True, exist_ok=True)
    B.selftest(); M.selftest_common(); selftest_kill()
    B.run_trade = kill_trade
    M.VERSIONS.clear(); M.VERSIONS[VNAME] = (4.0, 5.0, None)
    SEG, names, dropped, cal = M.build(prices_path)
    dates = pd.DatetimeIndex(EPOCH + pd.to_timedelta(cal, unit="D"))
    sp = (pd.read_csv(spy_path) if spy_path.endswith('.csv') else pd.read_parquet(spy_path))
    sp = sp[sp["date_i"] <= (END - EPOCH).days].sort_values("date_i").drop_duplicates("date_i")
    spc = pd.Series(sp["close"].to_numpy(float), index=np.searchsorted(cal, sp["date_i"].to_numpy()))
    spc = spc[spc.index < len(cal)]
    full = spc.reindex(range(len(cal))).ffill()
    sma = full.rolling(SMA_N, min_periods=SMA_N).mean()
    dist = ((full / sma - 1.0) * 100).to_numpy()
    sw = {w: switch(dist, w, -w) for w in (0, 1, 2, 3, 5)}
    # name -> (switch array or None, exit all when off?)
    COND = {"no market condition": (None, False), "entries only, SPY band 0%": (sw[0], False)}
    for w in (0, 1, 2, 3, 5):
        COND[f"exit all and entries, SPY band {w}%"] = (sw[w], True)
    WIN = {"2000 to 2007": (pd.Timestamp("2000-01-01"), MAIN_START - pd.Timedelta(days=1)), "2008 to Aug 2021 (futures development years)": (MAIN_START, END), "whole in-sample 2000 to Aug 2021": (pd.Timestamp("2000-01-01"), END)}
    rows, yr, epi = [], {}, []
    fc = full.to_numpy()
    for top in TOPS:
        for cname, (mk, kill) in COND.items():
            OFF.clear()
            if kill:
                for g in SEG:
                    OFF[id(g["o"])] = ~mk[g["s"]]
            R = M.trades_for(SEG, dropped, cal, top, VNAME, market_ok=mk, long_only=True)
            n = len(R["d"])
            forced = int((R["how"] == "market switch off").sum()) if n else 0
            print(f"top {int(top*100)}% | {cname}: {n:,} trades, {forced:,} sold because the switch turned off", flush=True)
            if n == 0:
                continue
            rng_key = np.random.default_rng(SEED).random(n)
            ed = dates[R["sess_e"]]
            P = B.portfolio(R, cal, (1,), M.SIZE, 2.0, rng_key)
            for wn, (lo, hi) in WIN.items():
                m = np.asarray((ed >= lo) & (ed <= hi))
                st, cal_y = B.wstats(P["pnl"], dates, lo, hi, P["open_n"], P["gross"])
                if not st:
                    continue
                inw = P["taken"] & m
                resa = R["res"][inw]
                st.update({"strongest share kept": top, "market condition": cname, "window": wn, "trades": int(inw.sum()), "sold when switch turned off": int((R["how"][inw] == "market switch off").sum()),
                           "win rate %": float((resa > 0).mean() * 100) if inw.any() else np.nan, "average ATR per trade": float(resa.mean()) if inw.any() else np.nan})
                rows.append(st)
                if wn.startswith("whole"):
                    yr[f"top {int(top*100)}% | {cname}"] = pd.Series(cal_y)
            for en, a, b in EPISODES:
                mm = np.asarray((dates >= pd.Timestamp(a)) & (dates <= pd.Timestamp(b)))
                if mm.sum() < 2:
                    continue
                ps = P["pnl"][mm]
                epi.append({"strongest share kept": top, "market condition": cname, "episode": en, "strategy profit % of $300k": float(ps.sum() / CAPITAL * 100), "strategy worst drop %": max_dd(ps),
                            "SPY change %": float(fc[mm][-1] / fc[mm][0] * 100 - 100), "SPY worst drop %": float((fc[mm] / np.maximum.accumulate(fc[mm]) - 1).min() * 100)})
    OFF.clear()
    S = pd.DataFrame(rows); S.to_csv(out_dir / "exit_all_summary.csv", index=False)
    E = pd.DataFrame(epi); E.to_csv(out_dir / "declines.csv", index=False)
    pd.DataFrame(yr).round(2).to_csv(out_dir / "profit_by_year_pct.csv")
    pd.set_option("display.width", 320); pd.set_option("display.max_columns", 50); pd.set_option("display.max_rows", 800)
    cols = ["market condition", "trades", "sold when switch turned off", "win rate %", "average ATR per trade", "profit per year %", "Sharpe ratio", "max drawdown %", "years positive", "worst year %", "first date account below zero"]
    for top in TOPS:
        for wn in WIN:
            v = S[(S.window == wn) & (S["strongest share kept"] == top)]
            print(f"\n==== top {int(top*100)}% | {VNAME} | long only | cap 200% | {wn} ====")
            print(v[cols].round(2).to_string(index=False))
    for top in TOPS:
        print(f"\n==== named market declines, top {int(top*100)}%: strategy profit % of $300k (worst drop inside window %) ====")
        e = E[E["strongest share kept"] == top]
        tab = e.pivot(index="market condition", columns="episode", values="strategy profit % of $300k").reindex(index=list(COND), columns=[x[0] for x in EPISODES])
        tab2 = e.pivot(index="market condition", columns="episode", values="strategy worst drop %").reindex(index=list(COND), columns=[x[0] for x in EPISODES])
        print((tab.round(1).astype(str) + " (" + tab2.round(1).astype(str) + ")").to_string())
        s1 = e[e["market condition"] == "no market condition"].set_index("episode")
        print("SPY change (worst drop):", {k: f"{s1.loc[k,'SPY change %']:.1f} ({s1.loc[k,'SPY worst drop %']:.1f})" for k, _, _ in EPISODES if k in s1.index})
    print("\n==== profit by calendar year, percent of $300k ===="); print(pd.DataFrame(yr).round(1).to_string())
    print("done")


if __name__ == "__main__":
    main()
