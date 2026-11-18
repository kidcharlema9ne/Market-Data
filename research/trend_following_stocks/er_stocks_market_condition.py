"""Stocks, long only: which SPY condition should switch new entries on? Moving-average windows, 50-day vs 200-day, and an efficiency ratio on SPY itself (Michael, 17 Nov 2026).
Usage: python er_stocks_market_condition.py stock_prices.parquet OUT_DIR spy_prices.parquet MODE
  MODE ma     : SPY closes above its N-session average, N = 50, 75, 100, 150, 200 (control), 250, 300; plus "no market condition".
  MODE cross  : shorter SPY average above a longer one (20/100, 50/100, 50/150, 50/200, 100/200), and the 200-day condition AND 50 above 200 together.
  MODE er     : SPY efficiency ratio over a window (|net close change| / sum of |daily close changes|) at or above a threshold with the close higher than W sessions ago. W = 200, 100, 60; seven thresholds each (the first guesses were low, so the top of each grid was raised).
Everything else is the current best rule (hand-off doc 17 Nov 2026): common stocks, one series per company, $3M floor, 20-session stock efficiency ratio 0.50 with a rising close starts a 20-session watch, buy the next
open after a close 1.5 ATR below the best high since the signal, strongest 20% by 126-session return checked on that day, long only, 4 ATR initial stop, 5 ATR trailing stop, no time limit, 0.05 ATR a side,
0.10% of $300k per ATR (fixed account, no compounding), caps 200% and 100%. The SPY condition is read from the close of the pullback (trigger) day and only blocks NEW entries; open positions keep their stops.
Windows that need a long history (250, 300) switch on later than the 200-day (reported as "first session on"), so the whole-period rows are not exactly like for like; the 2008 to 2021 rows are.
Post hoc on development years: about 40 conditions on one dataset, so the best row is not a result. Compare each row with its neighbours (a plateau means something, a lone peak does not).
Data through 2021-08-06 only; the sealed years are not read.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
import pandas as pd

import er_stocks as B
import er_stocks_common_momentum as M
from er_stocks import CAPITAL, END, EPOCH, MAIN_START, FIRST_TRADE
from er_stocks_er_grid import er_dr, long_cands
from er_stocks_null_baseline import spy_setup, run_trades, VNAME
from er_stocks_combined_er import q_long, cands_from_q

PULL = 1.5
SEED = 20261117
MA_N = (50, 75, 100, 150, 200, 250, 300)
CROSS = ((20, 100), (50, 100), (50, 150), (50, 200), (100, 200))
ER_GRID = {200: (0.03, 0.05, 0.08, 0.10, 0.15, 0.20, 0.25), 100: (0.05, 0.08, 0.12, 0.16, 0.20, 0.25, 0.30), 60: (0.08, 0.12, 0.16, 0.20, 0.25, 0.30, 0.40)}


def spy_er(close, w):
    s = pd.Series(close)
    net = s - s.shift(w)
    path = s.diff().abs().rolling(w).sum()
    return (net.abs() / path).to_numpy(), net.to_numpy()


def build_masks(mode, full, mk_control):
    s = pd.Series(full)
    sma = {n: s.rolling(n, min_periods=n).mean() for n in set(MA_N) | {a for ab in CROSS for a in ab}}
    M_ = {}
    if mode == "ma":
        M_["no market condition"] = (np.ones(len(full), bool), "none")
        for n in MA_N:
            M_[f"SPY above its {n}-day average"] = ((s > sma[n]).to_numpy(), f"average {n}")
    elif mode == "cross":
        M_["SPY above its 200-day average (control)"] = ((s > sma[200]).to_numpy(), "control")
        for a, b in CROSS:
            M_[f"{a}-day average above {b}-day average"] = ((sma[a] > sma[b]).to_numpy(), f"cross {a}/{b}")
        M_["above 200-day AND 50-day above 200-day"] = (((s > sma[200]) & (sma[50] > sma[200])).to_numpy(), "both")
    elif mode == "er":
        M_["SPY above its 200-day average (control)"] = ((s > sma[200]).to_numpy(), "control")
        for w, thrs in ER_GRID.items():
            er, net = spy_er(full, w)
            ok = np.isfinite(er)
            print(f"SPY {w}-session efficiency ratio (rising only, all sessions): percentiles 10/25/50/75/90 = " + "/".join(f"{np.nanpercentile(er[ok & (net > 0)], q):.3f}" for q in (10, 25, 50, 75, 90)), flush=True)
            for t in thrs:
                M_[f"SPY {w}-day efficiency ratio at least {t:.2f}"] = ((ok & (net > 0) & (er >= t)), f"ER {w}")
    else:
        raise SystemExit("MODE must be ma, cross or er")
    for k, (m, _) in M_.items():
        if "control" in k or k == "SPY above its 200-day average":
            assert (np.asarray(m) == mk_control).all(), "200-day control differs from the existing gate"
    return M_


def evaluate_mask(R, cal, dates, spy_close, WIN, label, on):
    rows = []
    n = len(R["d"])
    if n == 0:
        return rows
    key = np.random.default_rng(SEED).random(n)
    ed = dates[R["sess_e"]]
    bench = (spy_close[R["sess_x"]] / spy_close[R["sess_e"]] - 1.0) * R["px_e"] / R["a0"]
    for cap in (2.0, 1.0):
        P = B.portfolio(R, cal, (1,), M.SIZE, cap, key)
        for wn, (lo, hi) in WIN.items():
            st, _ = B.wstats(P["pnl"], dates, lo, hi, P["open_n"], P["gross"])
            if not st:
                continue
            sel = np.asarray((dates >= max(lo, FIRST_TRADE)) & (dates <= hi))
            g = P["gross"][sel] / CAPITAL * 100
            full_ = g >= cap * 100 * 0.95
            onw = on[sel]
            inw = P["taken"] & np.asarray((ed >= lo) & (ed <= hi))
            ra = R["res"][inw]; bm = bench[inw]; bm = bm[np.isfinite(bm)]
            avg = float(ra.mean()) if inw.any() else np.nan
            bavg = float(bm.mean()) if len(bm) else np.nan
            row = dict(label)
            row.update({"cap %": int(cap * 100), "period": wn, "profit per year %": st["profit per year %"], "Sharpe ratio": st["Sharpe ratio"], "max drawdown %": st["max drawdown %"],
                        "worst year %": st["worst year %"], "years positive": st["years positive"], "% of sessions condition on": float(onw.mean() * 100),
                        "signals": n, "trades taken": int(inw.sum()), "average open positions": st["average open positions"],
                        "% of sessions at the cap": float(full_.mean() * 100), "% of sessions at the cap, condition on only": float(full_[onw].mean() * 100) if onw.any() else np.nan,
                        "% of sessions with no position": float((P["open_n"][sel] == 0).mean() * 100),
                        "average ATR per trade": avg, "SPY move over the same holds (ATR units)": bavg, "excess over SPY (ATR units)": avg - bavg if np.isfinite(bavg) else np.nan})
            rows.append(row)
    return rows


def main():
    prices_path, out_dir, spy_path, mode = sys.argv[1], Path(sys.argv[2]), sys.argv[3], sys.argv[4]
    out_dir.mkdir(parents=True, exist_ok=True)
    B.selftest(); M.selftest_common()
    M.VERSIONS.clear(); M.VERSIONS[VNAME] = (4.0, 5.0, None)
    SEG, names, dropped, cal = M.build(prices_path)
    live = [i for i in range(len(SEG)) if i not in dropped]
    E20 = {i: er_dr(SEG[i], 20) for i in live}
    chk = [i for i in live if SEG[i]["cand"]][:: 25]
    M.PULL = 2.5
    for i in chk:
        er, dr = E20[i]
        assert long_cands(SEG[i], er, dr, M.ER_MIN) == [(t, d) for (t, d) in SEG[i]["cand"] if d > 0], f"mismatch in segment {i}"
    print(f"signal check passed on {len(chk)} segments", flush=True)
    M.PULL = PULL
    for i in live:
        g = SEG[i]
        g["cand"] = cands_from_q(g, q_long(g, *E20[i], 0.50), PULL)
    dates = pd.DatetimeIndex(EPOCH + pd.to_timedelta(cal, unit="D"))
    spy_close, mk_control = spy_setup(spy_path, cal)
    masks = build_masks(mode, spy_close, mk_control)
    WIN = {"2000 to 2007": (pd.Timestamp("2000-01-01"), MAIN_START - pd.Timedelta(days=1)), "2008 to Aug 2021": (MAIN_START, END), "whole 2000 to Aug 2021": (pd.Timestamp("2000-01-01"), END)}
    rows = []
    for name, (on, group) in masks.items():
        on = np.asarray(on, bool)
        first = dates[np.argmax(on)].date() if on.any() else None
        flips = int((on[1:] != on[:-1]).sum())
        R = run_trades(SEG, dropped, cal, on)
        print(f"{name}: on {on[np.searchsorted(cal, (FIRST_TRADE - EPOCH).days):].mean()*100:.1f}% of sessions, first on {first}, {flips} switches, {len(R['d']):,} signals taken to the account", flush=True)
        for r in evaluate_mask(R, cal, dates, spy_close, WIN, {"condition": name, "group": group, "first session on": str(first), "number of switches": flips}, on):
            rows.append(r)
    S = pd.DataFrame(rows)
    S.to_csv(out_dir / f"market_condition_{mode}.csv", index=False)
    pd.set_option("display.width", 300); pd.set_option("display.max_columns", 40); pd.set_option("display.max_rows", 600)
    cols = ["condition", "profit per year %", "Sharpe ratio", "max drawdown %", "worst year %", "years positive", "% of sessions condition on", "trades taken", "average open positions",
            "% of sessions at the cap", "% of sessions at the cap, condition on only", "average ATR per trade", "excess over SPY (ATR units)", "first session on", "number of switches"]
    for wn in WIN:
        for cap in (200, 100):
            print(f"\n==== {mode} | {wn} | cap {cap}% | long only | strongest 20% | 4 ATR stop, 5 ATR trail ====")
            print(S[(S.period == wn) & (S["cap %"] == cap)][cols].round(2).to_string(index=False))
    print("done")


if __name__ == "__main__":
    main()
