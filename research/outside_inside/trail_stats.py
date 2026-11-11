"""Portfolio statistics for the outside-day / inside-day trades with the 4 ATR trailing stop. IN-SAMPLE ONLY (outside days 2007-12-31 .. 2021-08-06; last 5 years sealed).

Exit tested: initial stop at the outside day's far side, then a trailing stop 4 ATR below the highest high since entry (above the lowest low for shorts),
60-session cap (see exit_grid.py). Entry as in exit_grid.py, worst-case entry-bar rule, no costs unless stated.

How the portfolio is built (plain words)
- Every trade risks a fixed 0.5% of equity (its distance from entry to the initial stop), added up, not compounded (so the numbers do not depend on a growing account).
- A trade's profit and loss is marked at each session's close in risk units and summed across all trades open on that calendar day; days with no open trade count as zero.
- Sharpe = mean daily return / standard deviation of daily returns x square root of 252 (no risk-free rate). Sortino uses only the downside deviation.
- Max drawdown = largest fall of the running total from its previous high (in % of equity at 0.5% risk per trade, and in risk units; both scale linearly with the risk per trade).
- A second block repeats it with an ASSUMED round-turn cost of 0.05 risk units per trade (illustration, not a quote).
Strategies (declared in advance): all pattern trades; with the 20-day trend; 20-day trend with efficiency ratio >= 0.3 / >= 0.5; with the 10-day trend; 10-day trend with efficiency ratio >= 0.3 / >= 0.5 / >= 0.7.
"""
import os
import sys
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
import exit_grid as eg
import trend_filter as tf

SPEC = ("trail 4 ATR below the highest high", "chandelier", 4.0, eg.CAP)
RISK_PER_TRADE = 0.005
COST_R = 0.05
TRADING_DAYS = 252


def daily_path(t, spec=SPEC):
    """Cumulative profit in risk units at the close of each session the trade is open (the last value is the final result)."""
    _, kind, param, cap = spec
    final, sessions, reason, _, _ = eg.run_exit(t, kind, param, cap)
    if reason == "stopped on entry bar":
        return [-1.0]
    pc = t["path"][3]
    return [(pc[k] - t["entry"]) / t["risk"] for k in range(sessions - 1)] + [final]


def portfolio(trades, prices, cost=0.0, spec=SPEC):
    """Returns (daily profit in risk units indexed by date, open-trade count by date, final result of each trade in risk units, setup dates)."""
    pnl, opens, finals, setups = {}, {}, [], []
    for t in trades:
        path = daily_path(t, spec)
        d = prices[t["symbol"]]["d"]
        dates = d[t["entry_idx"]: t["entry_idx"] + len(path)]
        delta = np.diff(np.r_[0.0, path])
        delta[0] -= cost
        for day, x in zip(dates, delta):
            pnl[day] = pnl.get(day, 0.0) + x
            opens[day] = opens.get(day, 0) + 1
        finals.append(path[-1] - cost)
        setups.append(t["setup_date"])
    return pnl, opens, np.array(finals), setups


def full_calendar(pnl, opens, prices):
    first, last = min(pnl), max(pnl)
    days = np.unique(np.concatenate([s["d"] for s in prices.values()]))
    days = days[(days >= first) & (days <= last)]
    return (pd.Series([pnl.get(x, 0.0) for x in days], index=pd.DatetimeIndex(days)),
            pd.Series([opens.get(x, 0) for x in days], index=pd.DatetimeIndex(days)))


def performance(daily_r, open_count, finals, risk=RISK_PER_TRADE):
    ret = daily_r * risk
    years = (ret.index[-1] - ret.index[0]).days / 365.25
    equity = ret.cumsum()
    peak = np.maximum.accumulate(np.r_[0.0, equity.values])[1:]
    dd = peak - equity.values
    since_peak = (equity.index.to_series() - equity.index.to_series().where(dd == 0).ffill().fillna(equity.index[0])).dt.days
    down = np.sqrt(np.mean(np.minimum(ret.values, 0) ** 2)) * np.sqrt(TRADING_DAYS)
    ann = ret.sum() / years
    vol = ret.std() * np.sqrt(TRADING_DAYS)
    month = ret.groupby([ret.index.year, ret.index.month]).sum()
    wins, losses = finals[finals > 0], finals[finals < 0]
    return pd.Series({
        "trades": len(finals), "trades_per_year": len(finals) / years, "win_rate": (finals > 0).mean(),
        "average_win_R": wins.mean() if len(wins) else np.nan, "average_loss_R": losses.mean() if len(losses) else np.nan,
        "profit_factor": wins.sum() / -losses.sum() if losses.sum() < 0 else np.nan, "expectancy_R_per_trade": finals.mean(),
        "best_trade_R": finals.max(), "worst_trade_R": finals.min(),
        "annual_return_pct": ann * 100, "annual_volatility_pct": vol * 100, "sharpe": ann / vol if vol > 0 else np.nan,
        "sortino": ann / down if down > 0 else np.nan, "max_drawdown_pct": dd.max() * 100, "max_drawdown_R": dd.max() / risk,
        "calmar": ann / dd.max() if dd.max() > 0 else np.nan, "longest_time_below_a_peak_days": int(since_peak.max()),
        "positive_months_pct": (month > 0).mean() * 100, "worst_month_pct": month.min() * 100, "best_month_pct": month.max() * 100,
        "average_open_trades": open_count.mean(), "max_open_trades": int(open_count.max()),
    })


def by_year(daily_r, finals_df):
    r = daily_r * RISK_PER_TRADE * 100
    out = pd.DataFrame({"return_pct": r.groupby(r.index.year).sum()})
    out["worst_peak_to_trough_in_year_pct"] = r.groupby(r.index.year).apply(lambda x: (np.maximum.accumulate(x.cumsum().values) - x.cumsum().values).max())
    out["trades_set_up"] = finals_df.groupby(finals_df["setup_year"]).size()
    out["win_rate"] = finals_df.groupby(finals_df["setup_year"])["final"].apply(lambda x: (x > 0).mean())
    return out


def main(price_path, universe_path, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    prices = eg.load_prices(price_path)
    tf.add_trend(prices)
    uni = pd.read_csv(universe_path, dtype=str)
    report = sorted({eg.PRICE_ROOTS.get(x, x) for x in uni["ibkr"]} & set(prices))
    t20 = tf.gen_trades(prices, report, "pattern", 20)
    t10 = tf.gen_trades(prices, report, "pattern", 10)
    pick = lambda ts, f: [t for t in ts if f(t)]
    strategies = {
        "all pattern trades (no filter)": t20,
        "with the 20-day trend": pick(t20, lambda t: t["with_trend"]),
        "20-day trend, efficiency ratio >= 0.3": pick(t20, lambda t: t["with_trend"] and t["er"] >= 0.3),
        "20-day trend, efficiency ratio >= 0.5": pick(t20, lambda t: t["with_trend"] and t["er"] >= 0.5),
        "with the 10-day trend": pick(t10, lambda t: t["with_trend"]),
        "10-day trend, efficiency ratio >= 0.3": pick(t10, lambda t: t["with_trend"] and t["er"] >= 0.3),
        "10-day trend, efficiency ratio >= 0.5": pick(t10, lambda t: t["with_trend"] and t["er"] >= 0.5),
        "10-day trend, efficiency ratio >= 0.7": pick(t10, lambda t: t["with_trend"] and t["er"] >= 0.7),
    }
    log = []

    def emit(x):
        print(x)
        log.append(x)

    pd.set_option("display.width", 250)
    emit("Portfolio statistics, trailing stop 4 ATR below the highest high (initial stop = outside day's far side), IN-SAMPLE 2008 to mid-2021, last 5 years sealed.\n"
         f"Each trade risks {RISK_PER_TRADE:.1%} of equity, additive; 48 report markets; worst-case entry-bar rule.\n")
    detail = {}
    for cost in (0.0, COST_R):
        rows = {}
        for name, ts in strategies.items():
            if not ts:
                continue
            pnl, opens, finals, setups = portfolio(ts, prices, cost)
            daily, open_count = full_calendar(pnl, opens, prices)
            rows[name] = performance(daily, open_count, finals)
            if cost == 0.0:
                detail[name] = (daily, pd.DataFrame({"final": finals, "setup_year": [str(x)[:4] for x in setups]}))
        table = pd.DataFrame(rows)
        label = "NO COSTS" if cost == 0 else f"WITH AN ASSUMED COST OF {COST_R} RISK UNITS PER TRADE"
        emit(f"=== {label} ===\n" + table.round(2).to_string() + "\n")
        table.to_csv(f"{out_dir}/portfolio_stats_{'no_cost' if cost == 0 else 'with_cost'}.csv")
    for name in ("all pattern trades (no filter)", "20-day trend, efficiency ratio >= 0.3", "10-day trend, efficiency ratio >= 0.5"):
        if name in detail:
            daily, fin = detail[name]
            fin = fin.copy()
            fin["setup_year"] = fin["setup_year"].astype(int)
            emit(f"=== By calendar year: {name} (no costs) ===\n" + by_year(daily, fin).round(2).to_string() + "\n")
    halves = {}
    for name, (daily, fin) in detail.items():
        for label, part in (("2008-2014", daily[daily.index <= "2014-12-31"]), ("2015-mid 2021", daily[daily.index > "2014-12-31"])):
            r = part * RISK_PER_TRADE
            halves[(name, label)] = dict(annual_return_pct=r.sum() / ((r.index[-1] - r.index[0]).days / 365.25) * 100, sharpe=r.mean() / r.std() * np.sqrt(TRADING_DAYS))
    emit("=== Two halves of the in-sample years (no costs) ===\n" + pd.DataFrame(halves).T.round(2).to_string() + "\n")
    open(f"{out_dir}/trail_stats_results.txt", "w").write("\n".join(log))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3])
