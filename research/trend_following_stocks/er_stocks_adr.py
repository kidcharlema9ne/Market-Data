"""Stocks, long only: current best rule with an extra gate that the stock's average daily range (ADR) must be at least X percent (Michael, 17 Nov 2026; X = 5 is the request, other values show the trend).
Usage: python er_stocks_adr.py stock_prices.parquet OUT_DIR spy_prices.parquet
ADR percent = 100 * (average over the last 20 sessions of high / low  - 1), the usual TradingView definition, using only data up to and including the close of the trigger day (no look-ahead).
The gate is checked on the TRIGGER day (the day of the 1.5 ATR pullback close), next to the strength and SPY gates; the efficiency ratio signal and the strength ranking (all eligible stocks) are unchanged.
All else is the current best rule (hand-off 17 Nov 2026): common stocks, one series per company, $3M floor, 20-session efficiency ratio 0.50 with rising close starts a 20-session watch, buy the next open after a close 1.5 ATR
below the best high since the signal, strongest 20% by 126-session return, SPY above its 200-session average for entries, 4 ATR initial / 5 ATR trailing stop, no time limit, 0.05 ATR a side, 0.10% of $300k per ATR,
caps 200% and 100% (fixed $300k, no compounding). ADR threshold 0 reproduces the reference (+22.9% / 0.64 / -22%).
In-sample only (data through 2021-08-06); sealed years untouched.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
import pandas as pd

import er_stocks as B
import er_stocks_common_momentum as M
from er_stocks import EPOCH, MAIN_START, END
from er_stocks_er_grid import er_dr, long_cands
from er_stocks_null_baseline import spy_setup, run_trades, evaluate, VNAME

PULL = 1.5
ADR_N = 20
THRESHOLDS = (0.0, 3.0, 4.0, 5.0, 6.0, 8.0)


def adr_pct(g):
    return ((pd.Series(g["h"] / g["l"]).rolling(ADR_N).mean() - 1.0) * 100).to_numpy()


def main():
    prices_path, out_dir, spy_path = sys.argv[1], Path(sys.argv[2]), sys.argv[3]
    out_dir.mkdir(parents=True, exist_ok=True)
    B.selftest(); M.selftest_common()
    M.VERSIONS.clear(); M.VERSIONS[VNAME] = (4.0, 5.0, None)
    SEG, names, dropped, cal = M.build(prices_path)
    live = [i for i in range(len(SEG)) if i not in dropped]
    ERC = {i: er_dr(SEG[i], M.ER_N) for i in live}
    ADR = {i: adr_pct(SEG[i]) for i in live}
    chk = [i for i in live if SEG[i]["cand"]][:: 25]
    M.PULL = 2.5
    for i in chk:
        er, dr = ERC[i]
        assert long_cands(SEG[i], er, dr, M.ER_MIN) == [(t, d) for (t, d) in SEG[i]["cand"] if d > 0], f"mismatch in segment {i}"
    print(f"signal check passed on {len(chk)} segments", flush=True)
    M.PULL = PULL
    base = {i: long_cands(SEG[i], *ERC[i], M.ER_MIN) for i in live}
    dates = pd.DatetimeIndex(EPOCH + pd.to_timedelta(cal, unit="D"))
    spy_close, mk = spy_setup(spy_path, cal)
    WIN = {"2000 to 2007": (pd.Timestamp("2000-01-01"), MAIN_START - pd.Timedelta(days=1)), "2008 to Aug 2021": (MAIN_START, END), "whole 2000 to Aug 2021": (pd.Timestamp("2000-01-01"), END)}
    pd.set_option("display.width", 300); pd.set_option("display.max_columns", 40); pd.set_option("display.max_rows", 600)
    rows, prof = [], []
    for thr in THRESHOLDS:
        for i in live:
            a = ADR[i]
            SEG[i]["cand"] = [(t, d) for (t, d) in base[i] if np.isfinite(a[t]) and a[t] >= thr]
        R = run_trades(SEG, dropped, cal, mk)
        n = len(R["d"])
        # profile of the qualifying trades (before the account cap): ADR at the trigger day, price, ATR as % of price
        adr_at = np.array([ADR[s][np.searchsorted(SEG[s]["s"], e) - 1] for s, e in zip(R["sym"], R["sess_e"])]) if n else np.array([])
        atrp = R["a0"] / R["px_e"] * 100 if n else np.array([])
        prof.append({"ADR gate %": thr, "qualifying trades before the cap": n, "average ADR % of those trades": float(np.nanmean(adr_at)) if n else np.nan,
                     "average ATR % of price": float(np.mean(atrp)) if n else np.nan, "share with entry price under $5 %": float((R["px_e"] < 5).mean() * 100) if n else np.nan,
                     "share with entry price under $10 %": float((R["px_e"] < 10).mean() * 100) if n else np.nan})
        print(f"ADR gate {thr:g}%: {n:,} qualifying trades", flush=True)
        rows += evaluate(R, cal, dates, spy_close, WIN, {"ADR gate %": thr})
        if thr == 0.0:
            r0 = [r for r in rows if r["ADR gate %"] == 0.0 and r["cap %"] == 200 and r["period"].startswith("whole")]
            if r0:
                print(f"REPRODUCTION CHECK (whole, cap 200%, expect +22.9 / 0.64 / -22): {r0[0]['profit per year %']:+.1f} / {r0[0]['Sharpe ratio']:.2f} / {r0[0]['max drawdown %']:.0f}", flush=True)
                if abs(r0[0]["Sharpe ratio"] - 0.64) > 0.015:
                    print("!!!! MISMATCH WITH THE DOCUMENTED REFERENCE: do not trust this run until explained !!!!", flush=True)
    S = pd.DataFrame(rows); S.to_csv(out_dir / "adr_summary.csv", index=False)
    P = pd.DataFrame(prof); P.to_csv(out_dir / "adr_profile.csv", index=False)
    print("\n==== profile of qualifying trades by ADR gate ====")
    print(P.round(2).to_string(index=False))
    for wn in WIN:
        for cap in (200, 100):
            v = S[(S.period == wn) & (S["cap %"] == cap)]
            print(f"\n==== ADR gate | current best rule | long only | strongest 20% | SPY 200-day | {VNAME} | cap {cap}% | {wn} ====")
            print(v.drop(columns=["period", "cap %"]).round(2).to_string(index=False))
    print("done")


if __name__ == "__main__":
    main()
