"""Full risk/reward report for the two best-looking efficiency-ratio systems from the grid. IN-SAMPLE ONLY (signals 2008 to 2021-08-06; last 5 years sealed).

Both systems: buy or sell when the efficiency ratio reaches the threshold (first session it does so in that trend direction), in the direction of the trend, enter at the
next session's open, ONE fixed stop 3 ATR from the entry (ATR = 14-session average true range at the signal close). The stop NEVER moves (no trailing stop). A trade ends
when the stop is hit (gap fills at the open), or at the close of the 60th session if the stop has not been hit (a time cap). One position per market, 48 report markets.
Risk: 0.5% of equity per trade (one risk unit = the 3 ATR stop distance), profits added, not compounded (the compounded figure is shown for reference). No costs unless shown.
  System B: 20-session efficiency ratio >= 0.6.    System A: 15-session efficiency ratio >= 0.7.
These two were picked as the best of 750 grid settings, so their numbers are biased upward.
"""
import os
import sys
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import efficiency_trend as et  # noqa: E402
eg, tf, ts = et.eg, et.tf, et.ts

SYSTEMS = {"B: 20-session ratio >= 0.6, 3 ATR stop": (20, 0.6), "A: 15-session ratio >= 0.7, 3 ATR stop": (15, 0.7)}
STOP_ATR = 3.0
HOLD = et.EXITS[3]
RISK = ts.RISK_PER_TRADE


def drawdown_episodes(equity_pct):
    """equity_pct: cumulative profit in % of starting equity indexed by date (additive). Returns a table of drawdown episodes."""
    peak = equity_pct.cummax()
    dd = equity_pct - peak
    rows, start, trough_date, trough = [], None, None, 0.0
    prev_date = None
    for date, v in dd.items():
        if v < 0:
            if start is None:
                start, trough, trough_date = prev_date if prev_date is not None else date, v, date
            if v < trough:
                trough, trough_date = v, date
        elif start is not None:
            rows.append(dict(peak_date=start, trough_date=trough_date, recovery_date=date, depth_pct=trough, days_peak_to_trough=(trough_date - start).days,
                             days_peak_to_recovery=(date - start).days, ongoing=False))
            start = None
        prev_date = date
    if start is not None:
        rows.append(dict(peak_date=start, trough_date=trough_date, recovery_date=pd.NaT, depth_pct=trough, days_peak_to_trough=(trough_date - start).days,
                         days_peak_to_recovery=(dd.index[-1] - start).days, ongoing=True))
    return pd.DataFrame(rows), dd


def max_consecutive(flags):
    best = cur = 0
    for f in flags:
        cur = cur + 1 if f else 0
        best = max(best, cur)
    return best


def system_report(recs, prices, cost=0.0, risk=RISK):
    st, daily = et.portfolio_stats(recs, prices, cost)
    ret = daily * risk
    years = (ret.index[-1] - ret.index[0]).days / 365.25
    eq = ret.cumsum() * 100
    eq0 = pd.concat([pd.Series([0.0], index=[ret.index[0] - pd.Timedelta(days=1)]), eq])
    eps, dd = drawdown_episodes(eq0)
    dd = dd.iloc[1:]
    vol = ret.std() * np.sqrt(252)
    down = np.sqrt(np.mean(np.minimum(ret.values, 0) ** 2)) * np.sqrt(252)
    ann = ret.sum() / years
    comp = (1 + ret).prod() ** (1 / years) - 1
    comp_dd = ((1 + ret).cumprod() / (1 + ret).cumprod().cummax() - 1).min()
    month = ret.groupby([ret.index.year, ret.index.month]).sum()
    year = ret.groupby(ret.index.year).sum()
    roll12 = ret.rolling(252).sum().dropna()
    var95 = np.percentile(ret, 5)
    finals = np.array([r["final"] - cost for r in recs])
    sess = np.array([r["sessions"] for r in recs])
    wins, losses = finals[finals > 0], finals[finals < 0]
    df = et.records_frame(recs)
    df["result"] = finals
    big = eps[eps["depth_pct"] <= -5]
    out = {
        "PERIOD": f"{ret.index[0].date()} to {ret.index[-1].date()} ({years:.1f} years)",
        "RETURN": {
            "total profit, % of starting equity (added)": eq.iloc[-1], "average return per year, % (added)": ann * 100, "compounded annual growth rate, %": comp * 100,
            "average return per month, %": month.mean() * 100, "median month, %": month.median() * 100, "average daily return, %": ret.mean() * 100,
        },
        "RISK": {
            "annual volatility, %": vol * 100, "Sharpe ratio (no risk-free rate)": ret.mean() / ret.std() * np.sqrt(252), "Sortino ratio": ann / down,
            "downside deviation, % a year": down * 100, "worst day, %": ret.min() * 100, "best day, %": ret.max() * 100,
            "daily 5% value at risk, %": var95 * 100, "average of the worst 5% of days, %": ret[ret <= var95].mean() * 100, "skewness of daily returns": ret.skew(),
            "excess kurtosis of daily returns": ret.kurt(), "% of days positive": (ret > 0).mean() * 100, "% of days with no change (no open trade)": (ret == 0).mean() * 100,
        },
        "DRAWDOWNS (equity fall from its prior high, in % of starting equity)": {
            "worst drawdown, %": eps["depth_pct"].min(), "worst drawdown, risk units": eps["depth_pct"].min() / (risk * 100), "worst drawdown if compounded, %": comp_dd * 100,
            "average drawdown over ALL days (time-weighted), %": dd.mean(), "number of drawdown episodes": len(eps), "average depth of an episode, %": eps["depth_pct"].mean(),
            "median depth of an episode, %": eps["depth_pct"].median(), "number of episodes deeper than 5%": len(big),
            "average length of an episode, calendar days (peak to new high)": eps["days_peak_to_recovery"].mean(), "median length of an episode, days": eps["days_peak_to_recovery"].median(),
            "average length of episodes deeper than 5%, days": big["days_peak_to_recovery"].mean() if len(big) else np.nan,
            "longest time below a peak, days": eps["days_peak_to_recovery"].max(), "average days from peak to the bottom": eps["days_peak_to_trough"].mean(),
            "% of all days spent below a prior peak": (dd < 0).mean() * 100, "Ulcer index (root mean square of drawdown), %": float(np.sqrt((dd ** 2).mean())),
            "Calmar ratio (annual return / worst drawdown)": ann * 100 / abs(eps["depth_pct"].min()), "recovery factor (total profit / worst drawdown)": eq.iloc[-1] / abs(eps["depth_pct"].min()),
        },
        "MONTHS AND YEARS": {
            "% of months positive": (month > 0).mean() * 100, "best month, %": month.max() * 100, "worst month, %": month.min() * 100,
            "% of years positive": (year > 0).mean() * 100, "best calendar year, %": year.max() * 100, "worst calendar year, %": year.min() * 100,
            "average rolling 12-month return, %": roll12.mean() * 100, "best rolling 12 months, %": roll12.max() * 100, "worst rolling 12 months, %": roll12.min() * 100,
            "% of rolling 12-month windows negative": (roll12 < 0).mean() * 100,
        },
        "TRADES": {
            "trades": len(recs), "trades per year": len(recs) / years, "win rate, %": (finals > 0).mean() * 100, "average winner, risk units": wins.mean(), "average loser, risk units": losses.mean(),
            "payoff ratio (average winner / average loser)": wins.mean() / -losses.mean(), "profit factor": wins.sum() / -losses.sum(), "expectancy per trade, risk units": finals.mean(),
            "expectancy per trade, ATR": finals.mean() * STOP_ATR, "expectancy per trade, % of equity at 0.5% risk": finals.mean() * risk * 100,
            "median trade, risk units": np.median(finals), "standard deviation of a trade, risk units": finals.std(), "best trade, risk units": finals.max(), "worst trade, risk units": finals.min(),
            "plus or minus 2 standard errors on the average (clustered by date)": 2 * eg.cluster_se(finals, df["setup_date"]),
            "largest single winner as % of total profit": finals.max() / finals.sum() * 100, "top 10 winners as % of total profit": np.sort(finals)[-10:].sum() / finals.sum() * 100,
            "longest losing streak (trades in the order they close)": max_consecutive((finals[np.argsort(np.array([r["entry_idx"] + r["sessions"] for r in recs]) + 0.0001 * np.arange(len(recs)), kind="stable")] < 0)),
            "average sessions held, all trades": sess.mean(), "average sessions held, winners": sess[finals > 0].mean(), "average sessions held, losers": sess[finals < 0].mean(),
            "% of trades ended by the stop (before session 60)": (sess < eg.CAP).mean() * 100, "% of trades ended by the 60-session time cap": (sess >= eg.CAP).mean() * 100,
            "long trades": int((df["direction"] == "long").sum()), "average of long trades, risk units": df[df["direction"] == "long"]["result"].mean(),
            "short trades": int((df["direction"] == "short").sum()), "average of short trades, risk units": df[df["direction"] == "short"]["result"].mean(),
            "average stop distance, % of price": df["risk_pct"].mean(),
        },
        "EXPOSURE": {
            "average trades open at once": st["average_open_trades"], "most trades open at once": st["max_open_trades"],
        },
    }
    return out, eps, year, df, daily


def fmt(d):
    lines = []
    for sec, v in d.items():
        if isinstance(v, dict):
            lines.append(f"\n--- {sec} ---")
            for k, x in v.items():
                lines.append(f"  {k}: {x:,.2f}" if isinstance(x, (float, np.floating)) else f"  {k}: {x}")
        else:
            lines.append(f"{sec}: {v}")
    return "\n".join(lines)


def main(price_path, universe_path, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    prices = eg.load_prices(price_path)
    tf.add_trend(prices, (15, 20))
    uni = pd.read_csv(universe_path, dtype=str)
    report = sorted({eg.PRICE_ROOTS.get(x, x) for x in uni["ibkr"]} & set(prices))
    log, dailys = [], {}
    pd.set_option("display.width", 250)

    def emit(x):
        print(x)
        log.append(x)

    emit("Efficiency-ratio systems, full risk/reward report. IN-SAMPLE only (last 5 years sealed). 48 report markets, 0.5% of equity risked per trade, profits added, no costs unless shown.\n"
         "Stop: ONE fixed stop 3 ATR from the entry that never moves (no trailing stop); a trade also ends at the close of session 60 if the stop was not hit.\n")
    for name, (lb, thr) in SYSTEMS.items():
        recs = et.run_system(prices, report, HOLD, thr, lb, "fresh", "with", STOP_ATR)
        out, eps, year, df, daily = system_report(recs, prices)
        dailys[name] = daily
        emit(f"\n\n==================== SYSTEM {name} ====================\n" + fmt(out))
        e = eps.sort_values("depth_pct").head(8).copy()
        for c in ("peak_date", "trough_date", "recovery_date"):
            e[c] = pd.to_datetime(e[c]).dt.date
        emit("\n--- 8 worst drawdowns ---\n" + e.round(1).to_string(index=False))
        e.to_csv(f"{out_dir}/worst_drawdowns_{name[0]}.csv", index=False)
        y = pd.DataFrame({"return_pct": year * 100})
        pdy = df.assign(y=pd.to_datetime(df["setup_date"]).dt.year).groupby("y")["result"].agg(trades="size", mean_risk_units="mean", win_rate=lambda x: (x > 0).mean() * 100)
        emit("\n--- By calendar year (return in % of equity) ---\n" + y.join(pdy).round(2).to_string())
        mk = df.groupby("symbol")["result"].agg(trades="size", mean_risk_units="mean", total_risk_units="sum").query("trades >= 8").sort_values("mean_risk_units", ascending=False)
        emit("\n--- Best 8 and worst 8 markets (8+ trades) ---\n" + pd.concat([mk.head(8), mk.tail(8)]).round(2).to_string())
        halves = {"first half (to 2014)": df[df["half"] == "first"]["result"], "second half (2015 to mid-2021)": df[df["half"] == "second"]["result"]}
        emit("\n--- Halves ---\n" + pd.DataFrame({k: dict(trades=len(v), mean_risk_units=v.mean(), win_rate_pct=(v > 0).mean() * 100) for k, v in halves.items()}).T.round(3).to_string())
        rows = {}
        for cost in (0.0, 0.05, 0.10):
            o = system_report(recs, prices, cost)[0]
            rows[f"cost {cost:.2f} risk units per trade"] = {"annual return, %": o["RETURN"]["average return per year, % (added)"], "Sharpe": o["RISK"]["Sharpe ratio (no risk-free rate)"],
                                                           "worst drawdown, %": o["DRAWDOWNS (equity fall from its prior high, in % of starting equity)"]["worst drawdown, %"],
                                                           "expectancy, risk units": o["TRADES"]["expectancy per trade, risk units"]}
        emit("\n--- Cost scenarios (cost per trade as a share of the 3 ATR stop; 0.05 = 0.15 ATR) ---\n" + pd.DataFrame(rows).T.round(2).to_string())
        sc = {}
        for r in (0.0025, 0.005, 0.01):
            o = system_report(recs, prices, 0.0, r)[0]
            sc[f"{r * 100:.2f}% risked per trade"] = {"annual return, %": o["RETURN"]["average return per year, % (added)"], "volatility, %": o["RISK"]["annual volatility, %"],
                                                      "worst drawdown, %": o["DRAWDOWNS (equity fall from its prior high, in % of starting equity)"]["worst drawdown, %"],
                                                      "average drawdown, %": o["DRAWDOWNS (equity fall from its prior high, in % of starting equity)"]["average drawdown over ALL days (time-weighted), %"]}
        emit("\n--- Position size scaling (added, not compounded; everything scales in proportion) ---\n" + pd.DataFrame(sc).T.round(2).to_string())
    names = list(dailys)
    both = pd.concat(dailys, axis=1).fillna(0)
    emit(f"\n\nCorrelation of the two systems' daily returns: {both.corr().iloc[0, 1]:.2f}")
    open(f"{out_dir}/system_report.txt", "w").write("\n".join(log))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3])
