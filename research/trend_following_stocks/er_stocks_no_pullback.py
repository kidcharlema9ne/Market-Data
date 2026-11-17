"""Stocks, long only, NO pullback wait: buy at the next open as soon as the efficiency ratio signal is on (Michael, 17 Nov 2026: "I thought we were just buying ... where you just bought the efficiency ratio at a certain level").
Usage: python er_stocks_no_pullback.py stock_prices.parquet OUT_DIR spy_prices.parquet MODE
MODE: first    - the first session the 20-session efficiency ratio is 0.50 or more with a rising 20-session net change (the same signal day that used to START the pullback watch) -> buy next open
      anyday   - any session while the ratio is 0.50 or more with a rising net change and we are flat in that stock -> buy next open (re-enter after an exit as long as the signal is still on)
      breakout - the earlier outright-strength system: close above the highest close of the previous 20 sessions AND 20-session efficiency ratio 0.60 or more, flat in the stock -> buy next open
Stops tried for each: initial 1 ATR / trailing 5 ATR (the old stock rule), 3 ATR / 3 ATR (the earlier system's), 4 ATR / 5 ATR (current stock rule's stops). No time limit.
Same filters as before: common stocks, $3M floor, SPY above its 200-session average for new entries, strongest 20% (126 sessions) or all stocks, 0.10% of $300k per ATR, caps 200% and 100%, 0.05 ATR a side, data through 2021-08-06 only.
Post hoc on development years; grid; best row is not a result; sealed years untouched.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
import pandas as pd

import er_stocks as B
import er_stocks_common_momentum as M
from er_stocks import CAPITAL, END, EPOCH, MAIN_START
from er_stocks_market_band import switch
from er_stocks_er_grid import er_dr, long_cands

STOPS = ((1.0, 5.0), (3.0, 3.0), (4.0, 5.0))


def cands(g, er, dr, mode):
    c = g["c"]; atr = g["atr"]
    if mode == "first":
        return None
    q = np.isfinite(er) & (dr > 0) & np.isfinite(atr) & (atr > 1e-6 * c)
    if mode == "anyday":
        q &= er >= 0.50
    else:
        prior_hi = pd.Series(c).shift(1).rolling(20).max().to_numpy()
        q &= (er >= 0.60) & np.isfinite(prior_hi) & (c > prior_hi)
    n = len(c)
    return [(int(t), 1) for t in np.where(q)[0] if t <= n - 2]


def main():
    prices_path, out_dir, spy_path, mode = sys.argv[1], Path(sys.argv[2]), sys.argv[3], sys.argv[4]
    out_dir.mkdir(parents=True, exist_ok=True)
    B.selftest(); M.selftest_common()
    M.VERSIONS.clear()
    for ini, tr in STOPS:
        M.VERSIONS[f"initial stop {ini:g} ATR, trailing stop {tr:g} ATR"] = (ini, tr, None)
    SEG, names, dropped, cal = M.build(prices_path)
    live = [i for i in range(len(SEG)) if i not in dropped]
    n_all = 0
    for i in live:
        g = SEG[i]; er, dr = er_dr(g, M.ER_N)
        if mode == "first":
            g["cand"] = None
            # the signal day itself: first session the ratio qualifies in the up direction
            q = np.isfinite(er) & (er >= M.ER_MIN) & (dr > 0) & np.isfinite(g["atr"]) & (g["atr"] > 1e-6 * g["c"])
            qprev = np.r_[False, q[:-1]]; dprev = np.r_[0.0, dr[:-1]]
            starts = np.where(q & ~(qprev & (dprev == dr)))[0]
            g["cand"] = [(int(t), 1) for t in starts if t <= len(g["c"]) - 2]
        else:
            g["cand"] = cands(g, er, dr, mode)
        n_all += len(g["cand"])
    print(f"mode {mode}: {n_all:,} signal days in liquid common-stock segments", flush=True)
    dates = pd.DatetimeIndex(EPOCH + pd.to_timedelta(cal, unit="D"))
    sp = (pd.read_csv(spy_path) if spy_path.endswith('.csv') else pd.read_parquet(spy_path))
    sp = sp[sp["date_i"] <= (END - EPOCH).days].sort_values("date_i").drop_duplicates("date_i")
    spc = pd.Series(sp["close"].to_numpy(float), index=np.searchsorted(cal, sp["date_i"].to_numpy()))
    spc = spc[spc.index < len(cal)]
    full = spc.reindex(range(len(cal))).ffill()
    sma = full.rolling(200, min_periods=200).mean()
    mk = switch(((full / sma - 1.0) * 100).to_numpy(), 0, 0)
    WIN = {"2000 to 2007": (pd.Timestamp("2000-01-01"), MAIN_START - pd.Timedelta(days=1)), "2008 to Aug 2021": (MAIN_START, END), "whole 2000 to Aug 2021": (pd.Timestamp("2000-01-01"), END)}
    rows = []
    for top in (0.20, 1.0):
        for vname in M.VERSIONS:
            R = M.trades_for(SEG, dropped, cal, top, vname, market_ok=mk, long_only=True)
            n = len(R["d"])
            print(f"{mode} | top {int(top*100)}% | {vname}: {n:,} signals", flush=True)
            if n == 0:
                continue
            key = np.random.default_rng(20261117).random(n)
            ed = dates[R["sess_e"]]
            for cap in (2.0, 1.0):
                P = B.portfolio(R, cal, (1,), M.SIZE, cap, key)
                for wn, (lo, hi) in WIN.items():
                    st, cal_y = B.wstats(P["pnl"], dates, lo, hi, P["open_n"], P["gross"])
                    if not st:
                        continue
                    inw = P["taken"] & np.asarray((ed >= lo) & (ed <= hi))
                    ra = R["res"][inw]
                    rows.append({"entry": mode, "strongest share kept": top, "stops": vname, "cap %": int(cap * 100), "period": wn, "signals": n, "trades taken": int(inw.sum()), "win rate %": float((ra > 0).mean() * 100) if inw.any() else np.nan,
                                 "average ATR per trade": float(ra.mean()) if inw.any() else np.nan, "average sessions held": float(R["held"][inw].mean()) if inw.any() else np.nan,
                                 "profit per year %": st["profit per year %"], "Sharpe ratio": st["Sharpe ratio"], "max drawdown %": st["max drawdown %"], "worst year %": st["worst year %"], "years positive": st["years positive"],
                                 "average position value % of account": st["average position value % of account"], "first date account below zero": st["first date account below zero"]})
    S = pd.DataFrame(rows); S.to_csv(out_dir / f"{mode}_summary.csv", index=False)
    pd.set_option("display.width", 300); pd.set_option("display.max_columns", 30); pd.set_option("display.max_rows", 500)
    for wn in WIN:
        for cap in (200, 100):
            v = S[(S.period == wn) & (S["cap %"] == cap)]
            print(f"\n==== {mode} entry, no pullback | long only | SPY 200-day for entries | cap {cap}% | {wn} ====")
            print(v.drop(columns=["entry", "period", "cap %", "signals"]).round(2).to_string(index=False))
    print("done")


if __name__ == "__main__":
    main()
