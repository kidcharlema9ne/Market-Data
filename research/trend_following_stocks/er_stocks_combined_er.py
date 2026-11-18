"""Stocks, long only: combine two efficiency ratio tests (Michael, 17 Nov 2026: "what if we were to combine the 60-day 0.3 with the 20-day 0.5?").
Usage: python er_stocks_combined_er.py stock_prices.parquet OUT_DIR spy_prices.parquet PULL   (PULL = pullback depth in ATR, e.g. 1.5 or 2.5)
Rules compared (all else identical, the current best rule): common stocks, one series per company, $3M floor, strongest 20% by 126-session return, long only, SPY above its 200-session average for entries, 4 ATR initial stop,
5 ATR trailing stop, no time limit, 0.05 ATR a side, 0.10% of $300k per ATR, caps 200% and 100%.
  20-day alone:  20-session efficiency ratio at or above 0.50 with a rising 20-session close.
  60-day alone:  60-session efficiency ratio at or above 0.30 with a rising 60-session close.
  both required: both of the above hold on the same day (the first day both hold starts the watch).
  either:        at least one of the above holds (the first day either holds starts the watch).
A watch lasts 20 sessions; buy the next open after a close PULL ATR below the best high since the signal. Single-rule rows are checked against the existing signal code (exact match required).
Post hoc on development years; the best row is not a result. Data through 2021-08-06 only; sealed years untouched.
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
from er_stocks_null_baseline import spy_setup, evaluate, run_trades, VNAME


def q_long(g, er, dr, thr):
    return np.isfinite(er) & (er >= thr) & (dr > 0) & np.isfinite(g["atr"]) & (g["atr"] > 1e-6 * g["c"])


def cands_from_q(g, q, pull):
    c, h, atr = g["c"], g["h"], g["atr"]
    n = len(c)
    qprev = np.r_[False, q[:-1]]
    out = []
    for st in np.where(q & ~qprev)[0]:
        peak = h[st]
        for t in range(st + 1, min(st + M.WATCH, n - 2) + 1):
            peak = max(peak, h[t])
            a = atr[t]
            if not (a == a and a > 0):
                continue
            if (peak - c[t]) / a >= pull:
                out.append((t, 1))
                break
    return out


def main():
    prices_path, out_dir, spy_path, pull = sys.argv[1], Path(sys.argv[2]), sys.argv[3], float(sys.argv[4])
    out_dir.mkdir(parents=True, exist_ok=True)
    B.selftest(); M.selftest_common()
    M.VERSIONS.clear(); M.VERSIONS[VNAME] = (4.0, 5.0, None)
    SEG, names, dropped, cal = M.build(prices_path)
    live = [i for i in range(len(SEG)) if i not in dropped]
    E20 = {i: er_dr(SEG[i], 20) for i in live}
    E60 = {i: er_dr(SEG[i], 60) for i in live}
    # checks: original signals (pullback 2.5, 20-day 0.50) and the new function agree exactly
    chk = [i for i in live if SEG[i]["cand"]][:: 25]
    M.PULL = 2.5
    for i in chk:
        er, dr = E20[i]
        assert long_cands(SEG[i], er, dr, M.ER_MIN) == [(t, d) for (t, d) in SEG[i]["cand"] if d > 0], f"mismatch (original) in segment {i}"
    M.PULL = pull
    for i in live[:: 25]:
        for E, thr in ((E20, 0.50), (E60, 0.30)):
            er, dr = E[i]
            assert cands_from_q(SEG[i], q_long(SEG[i], er, dr, thr), pull) == long_cands(SEG[i], er, dr, thr), f"mismatch (new function) in segment {i}"
    print(f"signal checks passed (original signals at 2.5 ATR; new function equals the existing one for both single rules at {pull:g} ATR)", flush=True)
    dates = pd.DatetimeIndex(EPOCH + pd.to_timedelta(cal, unit="D"))
    spy_close, mk = spy_setup(spy_path, cal)
    WIN = {"2000 to 2007": (pd.Timestamp("2000-01-01"), MAIN_START - pd.Timedelta(days=1)), "2008 to Aug 2021": (MAIN_START, END), "whole 2000 to Aug 2021": (pd.Timestamp("2000-01-01"), END)}
    pd.set_option("display.width", 300); pd.set_option("display.max_columns", 40); pd.set_option("display.max_rows", 500)
    rules = {"20-day ratio 0.50 alone": lambda a, b: a, "60-day ratio 0.30 alone": lambda a, b: b, "both required": lambda a, b: a & b, "either one": lambda a, b: a | b}
    rows = []
    for name, f in rules.items():
        for i in live:
            g = SEG[i]
            qa = q_long(g, *E20[i], 0.50); qb = q_long(g, *E60[i], 0.30)
            g["cand"] = cands_from_q(g, f(qa, qb), pull)
        R = run_trades(SEG, dropped, cal, mk)
        print(f"{name}, pullback {pull:g} ATR: {len(R['d']):,} signals", flush=True)
        rows += evaluate(R, cal, dates, spy_close, WIN, {"entry rule": name})
    S = pd.DataFrame(rows); S.to_csv(out_dir / "combined_er_summary.csv", index=False)
    exp = {2.5: {"20-day ratio 0.50 alone": (20.8, 0.59), "60-day ratio 0.30 alone": (22.1, 0.62)}, 1.5: {"20-day ratio 0.50 alone": (22.9, 0.64)}}.get(pull, {})
    for nm, (pf, sh) in exp.items():
        r = S[(S["entry rule"] == nm) & (S["cap %"] == 200) & S.period.str.startswith("whole")].iloc[0]
        ok = abs(r["Sharpe ratio"] - sh) <= 0.015
        print(f"REPRODUCTION CHECK {nm} at {pull:g} ATR (documented +{pf}% / {sh}): got {r['profit per year %']:+.1f}% / {r['Sharpe ratio']:.2f} {'OK' if ok else '!!!! MISMATCH, do not trust !!!!'}", flush=True)
    for wn in WIN:
        for cap in (200, 100):
            v = S[(S.period == wn) & (S["cap %"] == cap)]
            print(f"\n==== combining efficiency ratio tests | pullback {pull:g} ATR | long only | strongest 20% | SPY 200-day for entries | {VNAME} | cap {cap}% | {wn} ====")
            print(v.drop(columns=["period", "cap %"]).round(2).to_string(index=False))
    print("done")


if __name__ == "__main__":
    main()
