"""Stocks, long only: how much of the time is the account at its cap, how many positions are open, what does leverage cost, and what does an unleveraged (100%) version return?
(Michael, 17 Nov 2026.) Usage: python er_stocks_exposure.py stock_prices.parquet OUT_DIR spy_prices.parquet
Rules (all else the current best rule, 1.5 ATR pullback): common stocks, one series per company, $3M floor, strongest 20% by 126-session return checked on the pullback day, long only, SPY above its 200-session average
for new entries, 4 ATR initial stop, 5 ATR trailing stop, no time limit, 0.05 ATR a side, 0.10% of $300k per ATR (account size for sizing is fixed at $300,000, profits are not compounded).
  rule 1: 20-session efficiency ratio at or above 0.50 (the current rule).   rule 2: either that or the 60-session ratio at or above 0.30.
Caps on total position value (cost basis): 200%, 150%, 100% of $300,000. Exposure = position value at entry cost, summed over open positions; "at the cap" = within 5% of the cap.
Financing: money borrowed = position value above 100% of $300,000; charged each session at rate / 252 on that amount (rates 0%, 2%, 4%, 6% a year, flat, a simplification). Cash interest on idle money is NOT credited.
In-sample only (data through 2021-08-06); sealed years untouched.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
import pandas as pd

import er_stocks as B
import er_stocks_common_momentum as M
from er_stocks import CAPITAL, EPOCH, MAIN_START, END, FIRST_TRADE
from er_stocks_er_grid import er_dr, long_cands
from er_stocks_null_baseline import spy_setup, run_trades, VNAME
from er_stocks_combined_er import q_long, cands_from_q

PULL = 1.5
RATES = (0.0, 0.02, 0.04, 0.06)
CAPS = (2.0, 1.5, 1.0)


def exposure_row(P, R, dates, lo, hi, cap):
    sel = np.asarray((dates >= max(lo, FIRST_TRADE)) & (dates <= hi))
    g = P["gross"][sel] / CAPITAL * 100; n = P["open_n"][sel]
    full = g >= cap * 100 * 0.95
    ed = dates[R["sess_e"]]
    sig = np.asarray((ed >= lo) & (ed <= hi))
    return {"average position value % of account": g.mean(), "median": np.median(g), "90th percentile": np.percentile(g, 90), "% of sessions with no position": float((n == 0).mean() * 100),
            "% of sessions at the cap": float(full.mean() * 100), "% of sessions above 100% of account": float((g > 100).mean() * 100),
            "average open positions": n.mean(), "median open positions": float(np.median(n)), "most open positions": int(n.max()),
            "average open positions when at the cap": float(n[full].mean()) if full.any() else np.nan, "average position size when at the cap % of account": float((g[full] / np.maximum(n[full], 1)).mean()) if full.any() else np.nan,
            "average borrowed % of account": float(np.maximum(g - 100, 0).mean()), "trades taken": int((P["taken"] & sig).sum()), "signals skipped, account full": int((~P["taken"] & sig).sum()), "signals in period": int(sig.sum())}


def main():
    prices_path, out_dir, spy_path = sys.argv[1], Path(sys.argv[2]), sys.argv[3]
    out_dir.mkdir(parents=True, exist_ok=True)
    B.selftest(); M.selftest_common()
    M.VERSIONS.clear(); M.VERSIONS[VNAME] = (4.0, 5.0, None)
    SEG, names, dropped, cal = M.build(prices_path)
    live = [i for i in range(len(SEG)) if i not in dropped]
    E20 = {i: er_dr(SEG[i], 20) for i in live}
    E60 = {i: er_dr(SEG[i], 60) for i in live}
    chk = [i for i in live if SEG[i]["cand"]][:: 25]
    M.PULL = 2.5
    for i in chk:
        er, dr = E20[i]
        assert long_cands(SEG[i], er, dr, M.ER_MIN) == [(t, d) for (t, d) in SEG[i]["cand"] if d > 0], f"mismatch in segment {i}"
    print(f"signal check passed on {len(chk)} segments", flush=True)
    M.PULL = PULL
    dates = pd.DatetimeIndex(EPOCH + pd.to_timedelta(cal, unit="D"))
    spy_close, mk = spy_setup(spy_path, cal)
    WIN = {"2000 to 2007": (pd.Timestamp("2000-01-01"), MAIN_START - pd.Timedelta(days=1)), "2008 to Aug 2021": (MAIN_START, END), "whole 2000 to Aug 2021": (pd.Timestamp("2000-01-01"), END)}
    rules = {"20-day ratio 0.50 (current rule)": lambda a, b: a, "either 20-day 0.50 or 60-day 0.30": lambda a, b: a | b}
    pd.set_option("display.width", 300); pd.set_option("display.max_columns", 40); pd.set_option("display.max_rows", 600)
    expo, fin, yearly = [], [], []
    for name, f in rules.items():
        for i in live:
            g = SEG[i]
            g["cand"] = cands_from_q(g, f(q_long(g, *E20[i], 0.50), q_long(g, *E60[i], 0.30)), PULL)
        R = run_trades(SEG, dropped, cal, mk)
        print(f"{name}: {len(R['d']):,} signals at {PULL:g} ATR pullback", flush=True)
        key = np.random.default_rng(20261117).random(len(R["d"]))
        for cap in CAPS:
            P = B.portfolio(R, cal, (1,), M.SIZE, cap, key)
            borrowed = np.maximum(P["gross"] - CAPITAL, 0.0)
            for wn, (lo, hi) in WIN.items():
                row = {"rule": name, "cap %": int(cap * 100), "period": wn}; row.update(exposure_row(P, R, dates, lo, hi, cap)); expo.append(row)
                sel = np.asarray((dates >= max(lo, FIRST_TRADE)) & (dates <= hi))
                for rate in RATES:
                    if rate > 0 and cap <= 1.0:
                        continue
                    st, _ = B.wstats(P["pnl"] - borrowed * rate / 252.0, dates, lo, hi, P["open_n"], P["gross"])
                    if not st:
                        continue
                    fin.append({"rule": name, "cap %": int(cap * 100), "period": wn, "borrowing rate %": rate * 100, "profit per year %": st["profit per year %"], "Sharpe ratio": st["Sharpe ratio"],
                                "max drawdown %": st["max drawdown %"], "worst year %": st["worst year %"], "years positive": st["years positive"],
                                "financing cost, % of $300k per year": float(borrowed[sel].mean() * rate / CAPITAL * 100)})
            if cap == 2.0:
                yrs = pd.DatetimeIndex(dates)
                m = np.asarray((dates >= FIRST_TRADE) & (dates <= END))
                d = pd.DataFrame({"year": yrs[m].year, "gross": P["gross"][m] / CAPITAL * 100, "n": P["open_n"][m]})
                d["at cap"] = d["gross"] >= 190
                y = d.groupby("year").agg(**{"average position value % of account": ("gross", "mean"), "% of sessions at the cap": ("at cap", lambda s: s.mean() * 100), "average open positions": ("n", "mean")})
                y.insert(0, "rule", name); yearly.append(y.reset_index())
    X = pd.DataFrame(expo); X.to_csv(out_dir / "exposure_summary.csv", index=False)
    F = pd.DataFrame(fin); F.to_csv(out_dir / "financing_summary.csv", index=False)
    Y = pd.concat(yearly); Y.to_csv(out_dir / "exposure_by_year.csv", index=False)
    for nm in rules:
        for wn in ("whole 2000 to Aug 2021", "2008 to Aug 2021"):
            print(f"\n==== exposure | {nm} | {PULL:g} ATR pullback | {wn} ====")
            print(X[(X.rule == nm) & (X.period == wn)].drop(columns=["rule", "period"]).round(1).to_string(index=False))
    for wn in WIN:
        print(f"\n==== results with a charge on borrowed money (position value above 100% of $300k) | {wn} ====")
        print(F[F.period == wn].drop(columns=["period"]).round(2).to_string(index=False))
    for nm in rules:
        print(f"\n==== by year, cap 200% | {nm} ====")
        print(Y[Y.rule == nm].drop(columns=["rule"]).round(1).to_string(index=False))
    print("done")


if __name__ == "__main__":
    main()
