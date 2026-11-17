"""Stocks, long only: how deep a pullback (in ATR) to wait for before buying (Michael, 17 Nov 2026: "Let's try other ATR pullbacks and see what happens").
Usage: python er_stocks_pullback_depth.py stock_prices.parquet OUT_DIR spy_prices.parquet DEPTHS   (DEPTHS like none,0.5,1.0 ; 'none' = buy the next open after the signal day, no wait)
Fixed: 20-session efficiency ratio 0.50 or more with a rising 20-session net close change starts a watch (first qualifying day); the watch lasts 20 sessions; buy the next open once a close is at least DEPTH ATR below the best high since the signal;
4 ATR initial stop, 5 ATR trailing stop from the best close, no time limit; common stocks, $3M floor, SPY above 200-day for entries, strongest 20% (126 sessions) or all stocks, 0.10% of $300k per ATR, caps 200% and 100%, 0.05 ATR a side.
Depth 2.5 is the current rule. Post hoc on development years; grid; best row is not a result; data through 2021-08-06 only; sealed years untouched.
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

VNAME = "initial stop 4 ATR, trailing stop 5 ATR"


def main():
    prices_path, out_dir, spy_path = sys.argv[1], Path(sys.argv[2]), sys.argv[3]
    depths = [None if x == "none" else float(x) for x in sys.argv[4].split(",")]
    out_dir.mkdir(parents=True, exist_ok=True)
    B.selftest(); M.selftest_common()
    M.VERSIONS.clear(); M.VERSIONS[VNAME] = (4.0, 5.0, None)
    SEG, names, dropped, cal = M.build(prices_path)
    live = [i for i in range(len(SEG)) if i not in dropped]
    ERC = {i: er_dr(SEG[i], M.ER_N) for i in live}
    # check: depth 2.5 reproduces the existing pullback signals exactly
    chk = [i for i in live if SEG[i]["cand"]][:: 25]
    M.PULL = 2.5
    for i in chk:
        er, dr = ERC[i]
        assert long_cands(SEG[i], er, dr, M.ER_MIN) == [(t, d) for (t, d) in SEG[i]["cand"] if d > 0], f"mismatch in segment {i}"
    print(f"depth 2.5 signals match the original on {len(chk)} segments", flush=True)
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
    for depth in depths:
        label = "none (buy at the signal)" if depth is None else f"{depth:g} ATR"
        for i in live:
            g = SEG[i]; er, dr = ERC[i]
            if depth is None:
                q = np.isfinite(er) & (er >= M.ER_MIN) & (dr > 0) & np.isfinite(g["atr"]) & (g["atr"] > 1e-6 * g["c"])
                qprev = np.r_[False, q[:-1]]; dprev = np.r_[0.0, dr[:-1]]
                g["cand"] = [(int(t), 1) for t in np.where(q & ~(qprev & (dprev == dr)))[0] if t <= len(g["c"]) - 2]
            else:
                M.PULL = depth
                g["cand"] = long_cands(g, er, dr, M.ER_MIN)
        for top in (0.20, 1.0):
            R = M.trades_for(SEG, dropped, cal, top, VNAME, market_ok=mk, long_only=True)
            n = len(R["d"])
            print(f"pullback {label} | top {int(top*100)}%: {n:,} signals", flush=True)
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
                    rows.append({"pullback depth": label, "strongest share kept": top, "cap %": int(cap * 100), "period": wn, "signals": n, "trades taken": int(inw.sum()), "win rate %": float((ra > 0).mean() * 100) if inw.any() else np.nan,
                                 "average ATR per trade": float(ra.mean()) if inw.any() else np.nan, "average sessions held": float(R["held"][inw].mean()) if inw.any() else np.nan,
                                 "profit per year %": st["profit per year %"], "Sharpe ratio": st["Sharpe ratio"], "max drawdown %": st["max drawdown %"], "worst year %": st["worst year %"], "years positive": st["years positive"],
                                 "average position value % of account": st["average position value % of account"]})
    S = pd.DataFrame(rows); S.to_csv(out_dir / "pullback_depth_summary.csv", index=False)
    pd.set_option("display.width", 300); pd.set_option("display.max_columns", 30); pd.set_option("display.max_rows", 500)
    for wn in WIN:
        for top in (0.20, 1.0):
            for cap in (200, 100):
                v = S[(S.period == wn) & (S["cap %"] == cap) & (S["strongest share kept"] == top)]
                print(f"\n==== pullback depth | long only | top {int(top*100)}% | SPY 200-day for entries | {VNAME} | cap {cap}% | {wn} ====")
                print(v.drop(columns=["period", "cap %", "strongest share kept", "signals"]).round(2).to_string(index=False))
    print("done")


if __name__ == "__main__":
    main()
