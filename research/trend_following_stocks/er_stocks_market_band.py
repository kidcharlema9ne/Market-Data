"""Common stocks, long only, strongest 6-month performers, frozen rule: initial stop 4 ATR, trailing stop 5 ATR, no time limit (Michael, 17 Nov 2026: put a BAND around the 200-day average so longs are not switched on and off
while the market chops around it; also try a breadth version).
Usage: python er_stocks_market_band.py stock_prices.parquet OUT_DIR spy_prices.parquet
Everything else exactly as er_stocks_wider_stops.py (Entry 137): common stocks, one series per company, $3M floor, 126-session strength ranking (top 20% and all stocks), efficiency ratio 0.50 on 20 sessions, 2.5 ATR pullback,
next open, one position per stock, 0.05 ATR a side, whole shares, 0.10% of $300k per ATR, cap 200%, data through 2021-08-06 only. The market condition only blocks NEW entries; open positions keep their stops.
Market conditions tested (each a switch that is on or off at every session, decided from the close of the decision day):
  no market condition
  SPY band of w% around its 200-session average: switch turns ON when SPY closes more than w% above the average, turns OFF when it closes more than w% below, keeps its previous state in between (w = 0, 1, 2, 3, 5). Starts off.
  breadth: the share of eligible stocks (same liquid common-stock universe as the ranking) trading above their own 200-session average; ON above 50% (no band), ON above 55% / OFF below 45% (10-point band), ON above 60% / OFF below 40% (20-point band). Starts off.
Also reports how often each switch changes state, the share of sessions it is on, and results in named market declines (SPY peak-to-trough windows, dates approximate; SPY's own change in each window is computed from the data).
Post hoc: stop width, strength filter and market condition were all chosen after seeing these development years. Grid; best row is not a result.
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

TOPS = (0.20, 1.0)
SMA_N = 200
SEED = 20261117
MIN_BREADTH = int(os.environ.get('MIN_BREADTH', '100'))  # fewest eligible stocks for a breadth reading (real data has 400+)
VNAME = "initial stop 4 ATR, trailing stop 5 ATR"
EPISODES = (("2000 to 2002 decline", "2000-03-24", "2002-10-09"), ("2007 to 2009 decline", "2007-10-09", "2009-03-09"), ("2011 summer decline", "2011-04-29", "2011-10-03"),
            ("2015 to 2016 decline", "2015-05-21", "2016-02-11"), ("late 2018 decline", "2018-09-20", "2018-12-24"), ("2020 crash", "2020-02-19", "2020-03-23"))


def switch(x, on_above, off_below):
    """Two-threshold switch; starts off; NaN keeps the previous state."""
    out = np.zeros(len(x), bool); st = False
    for i, v in enumerate(x):
        if np.isfinite(v):
            if v > on_above:
                st = True
            elif v < off_below or (on_above == off_below and v <= off_below):
                st = False
        out[i] = st
    return out


def max_dd(pnl):
    if len(pnl) == 0:
        return 0.0
    cum = np.r_[0.0, np.cumsum(pnl)] / CAPITAL * 100
    return float((cum - np.maximum.accumulate(cum)).min())


def main():
    prices_path, out_dir, spy_path = sys.argv[1], Path(sys.argv[2]), sys.argv[3]
    out_dir.mkdir(parents=True, exist_ok=True)
    B.selftest(); M.selftest_common()
    M.VERSIONS.clear(); M.VERSIONS[VNAME] = (4.0, 5.0, None)
    SEG, names, dropped, cal = M.build(prices_path)
    dates = pd.DatetimeIndex(EPOCH + pd.to_timedelta(cal, unit="D"))
    sp = (pd.read_csv(spy_path) if spy_path.endswith('.csv') else pd.read_parquet(spy_path))
    sp = sp[sp["date_i"] <= (END - EPOCH).days].sort_values("date_i").drop_duplicates("date_i")
    spc = pd.Series(sp["close"].to_numpy(float), index=np.searchsorted(cal, sp["date_i"].to_numpy()))
    spc = spc[spc.index < len(cal)]
    full = spc.reindex(range(len(cal))).ffill()
    sma = full.rolling(SMA_N, min_periods=SMA_N).mean()
    dist = ((full / sma - 1.0) * 100).to_numpy()          # percent above (+) or below (-) the 200-session average
    # breadth: share of eligible stocks above their own 200-session average
    up = np.zeros(len(cal)); tot = np.zeros(len(cal))
    for i, g in enumerate(SEG):
        if i in dropped:
            continue
        cs = pd.Series(g["c"]).rolling(SMA_N, min_periods=SMA_N).mean().to_numpy()
        m = g["liq"] & ~g["spac"] & np.isfinite(g["ret"]) & np.isfinite(cs)
        if m.any():
            up += np.bincount(g["s"][m], weights=(g["c"][m] > cs[m]).astype(float), minlength=len(cal))
            tot += np.bincount(g["s"][m], minlength=len(cal))
    breadth = np.where(tot >= MIN_BREADTH, up / np.maximum(tot, 1) * 100, np.nan)
    print(f"breadth: median {np.nanmedian(breadth) if np.isfinite(breadth).any() else float("nan"):.1f}% of eligible stocks above their own 200-session average; min {(np.nanmin(breadth) if np.isfinite(breadth).any() else float("nan")):.1f}%, max {(np.nanmax(breadth) if np.isfinite(breadth).any() else float("nan")):.1f}%", flush=True)
    COND = {"no market condition": None}
    for w in (0, 1, 2, 3, 5):
        COND[f"SPY band {w}%"] = switch(dist, w, -w)
    COND["breadth above 50%"] = switch(breadth, 50, 50)
    COND["breadth band 55/45%"] = switch(breadth, 55, 45)
    COND["breadth band 60/40%"] = switch(breadth, 60, 40)
    span_years = (dates[-1] - dates[np.argmax(np.isfinite(dist))]).days / 365.25
    sw = []
    for k, v in COND.items():
        if v is not None:
            first = int(np.argmax(np.isfinite(dist)))
            sw.append({"market condition": k, "switches per year": float((np.diff(v[first:].astype(int)) != 0).sum() / span_years), "share of sessions on %": float(v[first:].mean() * 100)})
    SW = pd.DataFrame(sw); SW.to_csv(out_dir / "switch_counts.csv", index=False)
    WIN = {"2000 to 2007": (pd.Timestamp("2000-01-01"), MAIN_START - pd.Timedelta(days=1)), "2008 to Aug 2021 (futures development years)": (MAIN_START, END), "whole in-sample 2000 to Aug 2021": (pd.Timestamp("2000-01-01"), END)}
    rows, pt, yr, epi = [], [], {}, []
    spy_d = np.r_[0.0, np.diff(full.to_numpy())]
    for top in TOPS:
        for cname, mk in COND.items():
            R = M.trades_for(SEG, dropped, cal, top, VNAME, market_ok=mk, long_only=True)
            n = len(R["d"])
            print(f"top {int(top*100)}% | {cname}: {n:,} trades", flush=True)
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
                st.update({"strongest share kept": top, "market condition": cname, "window": wn, "trades": int(inw.sum()), "win rate %": float((resa > 0).mean() * 100) if inw.any() else np.nan,
                           "average ATR per trade": float(resa.mean()) if inw.any() else np.nan})
                rows.append(st)
                if wn.startswith("whole"):
                    yr[f"top {int(top*100)}% | {cname}"] = pd.Series(cal_y)
            for en, a, b in EPISODES:
                mm = np.asarray((dates >= pd.Timestamp(a)) & (dates <= pd.Timestamp(b)))
                if mm.sum() < 2:
                    continue
                ps = P["pnl"][mm]
                spy_chg = float(full.to_numpy()[mm][-1] / full.to_numpy()[mm][0] * 100 - 100)
                epi.append({"strongest share kept": top, "market condition": cname, "episode": en, "strategy profit % of $300k": float(ps.sum() / CAPITAL * 100), "strategy worst drop %": max_dd(ps),
                            "SPY change %": spy_chg, "SPY worst drop %": float((full.to_numpy()[mm] / np.maximum.accumulate(full.to_numpy()[mm]) - 1).min() * 100)})
    S = pd.DataFrame(rows); S.to_csv(out_dir / "band_summary.csv", index=False)
    E = pd.DataFrame(epi); E.to_csv(out_dir / "declines.csv", index=False)
    pd.DataFrame(yr).round(2).to_csv(out_dir / "profit_by_year_pct.csv")
    pd.set_option("display.width", 320); pd.set_option("display.max_columns", 50); pd.set_option("display.max_rows", 800)
    print("\n==== how often each switch changes state (from the first session with a 200-session average) ====")
    print(SW.round(2).to_string(index=False))
    cols = ["market condition", "trades", "win rate %", "average ATR per trade", "profit per year %", "Sharpe ratio", "max drawdown %", "years positive", "worst year %", "first date account below zero"]
    for top in TOPS:
        for wn in WIN:
            v = S[(S.window == wn) & (S["strongest share kept"] == top)]
            print(f"\n==== top {int(top*100)}% | {VNAME} | long only | cap 200% | {wn} ====")
            print(v[cols].round(2).to_string(index=False))
    for top in TOPS:
        print(f"\n==== named market declines, top {int(top*100)}%: strategy profit % of $300k (worst drop inside window %) | SPY change % (worst drop %) ====")
        e = E[E["strongest share kept"] == top]
        tab = e.pivot(index="market condition", columns="episode", values="strategy profit % of $300k").reindex(index=list(COND), columns=[x[0] for x in EPISODES])
        tab2 = e.pivot(index="market condition", columns="episode", values="strategy worst drop %").reindex(index=list(COND), columns=[x[0] for x in EPISODES])
        out = tab.round(1).astype(str) + " (" + tab2.round(1).astype(str) + ")"
        print(out.to_string())
        s1 = e[e["market condition"] == "no market condition"].set_index("episode")
        print("SPY:", {k: f"{s1.loc[k,'SPY change %']:.1f} ({s1.loc[k,'SPY worst drop %']:.1f})" for k, _, _ in EPISODES if k in s1.index})
    print("\n==== profit by calendar year, percent of $300k ===="); print(pd.DataFrame(yr).round(1).to_string())
    print("done")


if __name__ == "__main__":
    main()
