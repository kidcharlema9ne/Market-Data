"""Stocks, long only: how far above or BELOW its 200-day average must SPY be for new entries? (Michael, 18 Nov 2026, from Entry 160 part 3: the strongest-20% signals taken while SPY was 0 to 5% below its 200-day did well, more than 5% below did badly.)
Usage: python er_stocks_spy_buffer.py stock_prices.parquet OUT_DIR spy_prices.parquet

Everything is the current baseline (volume-surge ranking when the account is full, plain 4 ATR initial and 5 ATR trailing stops, 0.05 ATR a side, 0.10% of a fixed $300,000 per ATR, cap 200% and 100%, strongest 20%, $3M floor) except the SPY condition on NEW entries:
  1. simple thresholds: entries allowed when SPY is more than X% above its 200-day average, X = +5, +3, +2, +1, 0 (the current rule), -1, -2, -3, -4, -5, -6, -7, -8, -10, -15, and no condition at all;
  2. two-level bands (on above A, off below B; stays in its state in between): (0, -5), (0, -3), (0, -8), (-2, -6), (+2, -5).
Each variant is run with volume-surge ranking and with the mean of 8 random picks. Rows: profit per year, Sharpe ratio, max drawdown from the account's running peak, profit per year over drawdown, worst year, trades, share of sessions with the condition on,
average ATR per trade with SPY's move over the same holds beside it. Windows 2000 to 2007, 2008 to Aug 2021, whole. Then the signals themselves by SPY distance from its 200-day average (the shape of the effect), and start-year tables
(account started empty on 1 January of each year 2000 to 2020) for the current rule and four variants. In-sample only (data through 2021-08-06); the sealed years are never read. Post hoc: nothing here is validated.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
import pandas as pd

import er_stocks as B
import er_stocks_ideas_1_2_6 as I1
import er_stocks_many_ideas as MI
import er_stocks_nasdaq_volume as NV
import er_stocks_start_years as SY
from er_stocks import END
from er_stocks_market_band import switch

THRESHOLDS = [5, 3, 2, 1, 0, -1, -2, -3, -4, -5, -6, -7, -8, -10, -15]
BANDS = [(0, -5), (0, -3), (0, -8), (-2, -6), (2, -5)]
START_YEAR_VARIANTS = ["SPY more than 0% above (current rule)", "SPY more than -3% above", "SPY more than -5% above", "on above 0%, off below -5%", "on above 0%, off below -8%"]


def vs_key(R, FEAT, SEG):
    sym, t = I1.trade_rows(SEG, R)
    surge = np.array([FEAT[(sym[k], t[k])]["s20_sig"] for k in range(len(sym))], float)
    return -np.where(np.isfinite(surge), surge, -1e9) + np.random.default_rng(20261118).random(len(sym)) * 1e-9


def name_thr(x):
    return "no condition" if x is None else f"SPY more than {x:+d}% above" if x != 0 else "SPY more than 0% above (current rule)"


def main():
    prices_path, out_dir, spy_path = sys.argv[1], Path(sys.argv[2]), sys.argv[3]
    out_dir.mkdir(parents=True, exist_ok=True)
    pd.set_option("display.width", 320); pd.set_option("display.max_columns", 40); pd.set_option("display.max_rows", 600); pd.set_option("display.max_colwidth", 60)
    ctx, names, live, E20, dates, spy_close, mk200 = MI.setup(prices_path, spy_path)
    SEG, dropped, cal, (_, _, WIN) = ctx
    MI.check_baseline(ctx, mk200)
    FEAT = NV.build_features(ctx, E20)
    s = pd.Series(spy_close)
    dist = ((s / s.rolling(200, min_periods=200).mean() - 1.0) * 100.0).to_numpy()
    assert (switch(dist, 0, 0) == mk200).all(), "condition rebuilt from the distance differs from the standard one"
    variants = [(name_thr(x), switch(dist, x, x)) for x in THRESHOLDS] + [("no condition", np.ones(len(cal), bool))] + [(f"on above {a:+d}%, off below {b:+d}%", switch(dist, a, b)) for a, b in BANDS]
    rows, RS = [], {}
    for nm, mask in variants:
        R = MI.gen(ctx, mask)
        key = vs_key(R, FEAT, SEG); RS[nm] = (R, key, mask)
        lab = {"condition": nm, "ranking": "volume surge"}
        for cap in (2.0, 1.0):
            P = MI.portfolio_gen(R, cal, cap, key)
            for r in I1.eval_P(R, P, cap, dates, spy_close, WIN, dict(lab), on=mask):
                r["Sharpe lowest pick"] = np.nan; r["Sharpe highest pick"] = np.nan; rows.append(r)
        rr = MI.scen(ctx, R, {"condition": nm, "ranking": "random pick (mean of 8)"}, on=mask)
        rows += rr
        w = [r for r in rows if r["condition"] == nm and r["ranking"] == "volume surge" and r["period"].startswith("whole") and r["cap %"] == 200][-1]
        print(f"  {nm}: signals {len(R['d']):,}; volume surge, cap 200%, whole period: +{w['profit per year %']:.1f}% / Sharpe {w['Sharpe ratio']:.2f} / {w['max drawdown %']:.1f}% / worst year {w['worst year %']:.1f}%", flush=True)
    S = pd.DataFrame(rows)
    S["profit per year / drawdown"] = S["profit per year %"] / S["max drawdown %"].abs()
    S.round(4).to_csv(out_dir / "spy_buffer_variants.csv", index=False)
    cols = ["condition", "ranking", "profit per year %", "Sharpe ratio", "max drawdown %", "profit per year / drawdown", "worst year %", "trades taken", "% of sessions condition on", "average ATR per trade", "excess over SPY (ATR units)"]
    order = {n: i for i, (n, _) in enumerate(variants)}
    for wn in WIN:
        for cap in (200, 100):
            v = S[(S.period == wn) & (S["cap %"] == cap)].copy()
            v["o"] = v.condition.map(order); v = v.sort_values(["o", "ranking"], ascending=[True, False])
            print(f"\n==== {wn} | cap {cap}% | SPY condition on new entries ====")
            print(v[cols].round(2).to_string(index=False))

    # ---- the signals by SPY distance (shape of the effect; strength filter on, SPY condition off)
    R, key, mask = RS["no condition"]
    sym, t = I1.trade_rows(SEG, R)
    d_sig = np.array([dist[SEG[int(sym[k])]["s"][int(t[k])]] for k in range(len(sym))])
    bm = (spy_close[R["sess_x"]] / spy_close[R["sess_e"]] - 1.0) * R["px_e"] / R["a0"]
    G = pd.DataFrame({"res": R["res"], "spy": bm, "d": d_sig, "year": dates[R["sess_e"]].year.to_numpy()}).dropna(subset=["d"])
    edges = [-100, -15, -10, -8, -6, -5, -4, -3, -2, 0, 2, 4, 6, 10, 100]
    G["SPY distance from its 200-day (%)"] = pd.cut(G.d, edges)
    T = G.groupby("SPY distance from its 200-day (%)", observed=True).agg(signals=("res", "size"), **{"mean ATR": ("res", "mean"), "median ATR": ("res", "median"), "win rate %": ("res", lambda x: (x > 0).mean() * 100),
                                                                                                         "5-ATR winners %": ("res", lambda x: (x >= 5).mean() * 100), "SPY same-hold ATR": ("spy", "mean")}).reset_index()
    T["excess over SPY (ATR)"] = T["mean ATR"] - T["SPY same-hold ATR"]
    T.round(3).to_csv(out_dir / "signals_by_spy_distance.csv", index=False)
    print(f"\n==== signals of the rule (strongest 20%, no SPY condition, {len(G):,} signals) by SPY distance from its 200-day average ====")
    print(T.round(3).to_string(index=False))
    # which episodes made the -5% to 0% signals (concentration check)
    sel = (G.d > -5) & (G.d <= 0)
    Y = G[sel].groupby("year").agg(signals=("res", "size"), **{"mean ATR": ("res", "mean")}).reset_index()
    print("\nSignals taken while SPY was 0 to 5% below its 200-day, by entry year:"); print(Y.round(2).to_string(index=False)); Y.round(3).to_csv(out_dir / "band_signals_by_year.csv", index=False)

    # ---- start-year tables
    tabs = []
    for nm in START_YEAR_VARIANTS:
        key_nm = {"SPY more than -3% above": "SPY more than -3% above", "SPY more than -5% above": "SPY more than -5% above", "on above 0%, off below -5%": "on above +0%, off below -5%", "on above 0%, off below -8%": "on above +0%, off below -8%"}.get(nm, nm)
        R, key, mask = RS[key_nm]
        for cap in (2.0, 1.0):
            for y in range(2000, 2021):
                r = SY.run_window(R, key, cal, dates, spy_close, pd.Timestamp(f"{y}-01-01"), END, cap)
                if r:
                    r.update({"condition": nm, "cap %": int(cap * 100)}); tabs.append(r)
    T2 = pd.DataFrame(tabs); T2.round(3).to_csv(out_dir / "spy_buffer_start_years.csv", index=False)
    for cap in (200, 100):
        v = T2[T2["cap %"] == cap].pivot(index="start", columns="condition", values=["profit per year %", "max drawdown % (from peak)", "profit per year / drawdown"])
        print(f"\n==== start-year tables | cap {cap}% | volume-surge ranking | profit per year %, max drawdown %, profit per year / drawdown by condition ====")
        print(v.round(1).to_string())
    print("done")


if __name__ == "__main__":
    main()
