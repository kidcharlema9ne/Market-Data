"""Common stocks, long only, strongest 20% over 126 sessions, SPY above its 200-session average for new entries, 4 ATR initial stop, 5 ATR trailing stop, no time limit, 0.10% of $300k per ATR, $3M floor.
Michael, 17 Nov 2026: "play with the window and number of efficiency ratio ... longer windows, higher numbers, lower numbers ... a whole optimization."
Varies ONLY the efficiency ratio window (sessions over which net change is compared with the total path) and the efficiency ratio threshold that starts a watch. Direction = sign of the net close change over the same window.
Everything else fixed (20-session ATR, watch 20 sessions for a 2.5 ATR pullback, enter next open, one position per stock, 0.05 ATR a side). The current rule is window 20, threshold 0.50.
Usage: python er_stocks_er_grid.py stock_prices.parquet OUT_DIR spy_prices.parquet WINDOWS   (WINDOWS like 10,15,20)
The ranking, liquidity and duplicate work is built once; only the efficiency-ratio signals are recomputed (the window 20 / threshold 0.50 signals are checked against the originals, exact match required).
Post hoc on development years; grid of windows x thresholds; best cell is not a result, only a smooth plateau means something. Data through 2021-08-06 only; sealed years untouched.
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

VNAME = "initial stop 4 ATR, trailing stop 5 ATR"
SEED = 20261117
THRESHOLDS = (0.30, 0.40, 0.50, 0.60, 0.70)


def er_dr(g, n_er):
    cs = pd.Series(g["c"])
    path = pd.Series(np.abs(np.diff(g["c"], prepend=np.nan))).rolling(n_er).sum()
    er = ((cs - cs.shift(n_er)).abs() / path).to_numpy()
    dr = np.sign(cs - cs.shift(n_er)).fillna(0).to_numpy()
    return er, dr


def long_cands(g, er, dr, thr):
    """Same signal logic as er_stocks_common_momentum.analyze, up-trends only: list of (decision row, +1)."""
    c, h, l, atr = g["c"], g["h"], g["l"], g["atr"]
    n = len(c)
    q = np.isfinite(er) & (er >= thr) & (dr != 0) & np.isfinite(atr) & (atr > 1e-6 * c)
    qprev = np.r_[False, q[:-1]]; dprev = np.r_[0.0, dr[:-1]]
    starts = np.where(q & ~(qprev & (dprev == dr)) & (dr > 0))[0]
    out = []
    for st in starts:
        peak = h[st]
        for t in range(st + 1, min(st + M.WATCH, n - 2) + 1):
            peak = max(peak, h[t])
            a = atr[t]
            if not (a == a and a > 0):
                continue
            if (peak - c[t]) / a >= M.PULL:
                out.append((t, 1))
                break
    return out


def main():
    prices_path, out_dir, spy_path = sys.argv[1], Path(sys.argv[2]), sys.argv[3]
    windows = [int(x) for x in sys.argv[4].split(",")]
    out_dir.mkdir(parents=True, exist_ok=True)
    B.selftest(); M.selftest_common()
    M.VERSIONS.clear(); M.VERSIONS[VNAME] = (4.0, 5.0, None)
    SEG, names, dropped, cal = M.build(prices_path)
    live = [i for i, g in enumerate(SEG) if i not in dropped and g["cand"]]
    # exact-match check of the recomputed signals at the current setting
    for i in live[:: max(1, len(live) // 400)]:
        g = SEG[i]; er, dr = er_dr(g, M.ER_N)
        assert long_cands(g, er, dr, M.ER_MIN) == [(t, d) for (t, d) in g["cand"] if d > 0], f"signal mismatch in segment {i}"
    print(f"signal recomputation matches the original on {len(live[::max(1, len(live)//400)])} segments (window {M.ER_N}, threshold {M.ER_MIN})", flush=True)
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
    for n_er in windows:
        ERC = {i: er_dr(SEG[i], n_er) for i in live}
        for thr in THRESHOLDS:
            for i in live:
                er, dr = ERC[i]
                SEG[i]["cand"] = long_cands(SEG[i], er, dr, thr)
            R = M.trades_for(SEG, dropped, cal, 0.20, VNAME, market_ok=mk, long_only=True)
            n = len(R["d"])
            print(f"window {n_er}, threshold {thr:.2f}: {n:,} signals", flush=True)
            if n == 0:
                continue
            key = np.random.default_rng(SEED).random(n)
            ed = dates[R["sess_e"]]
            for cap in (2.0, 1.0):
                P = B.portfolio(R, cal, (1,), M.SIZE, cap, key)
                for wn, (lo, hi) in WIN.items():
                    st, cal_y = B.wstats(P["pnl"], dates, lo, hi, P["open_n"], P["gross"])
                    if not st:
                        continue
                    inw = P["taken"] & np.asarray((ed >= lo) & (ed <= hi))
                    ra = R["res"][inw]
                    rows.append({"ER window": n_er, "ER threshold": thr, "cap %": int(cap * 100), "period": wn, "signals": n, "trades taken": int(inw.sum()), "win rate %": float((ra > 0).mean() * 100) if inw.any() else np.nan,
                                 "average ATR per trade": float(ra.mean()) if inw.any() else np.nan, "average sessions held": float(R["held"][inw].mean()) if inw.any() else np.nan,
                                 "profit per year %": st["profit per year %"], "Sharpe ratio": st["Sharpe ratio"], "max drawdown %": st["max drawdown %"], "worst year %": st["worst year %"], "years positive": st["years positive"],
                                 "average position value % of account": st["average position value % of account"]})
    S = pd.DataFrame(rows); S.to_csv(out_dir / "er_grid_summary.csv", index=False)
    pd.set_option("display.width", 300); pd.set_option("display.max_columns", 30); pd.set_option("display.max_rows", 500)
    for wn in WIN:
        for cap in (200, 100):
            v = S[(S.period == wn) & (S["cap %"] == cap)]
            print(f"\n==== efficiency ratio window x threshold | long only | strongest 20% | SPY 200-day for entries | {VNAME} | cap {cap}% | {wn} ====")
            print(v.drop(columns=["period", "cap %", "signals"]).round(2).to_string(index=False))
    print("done")


if __name__ == "__main__":
    main()
