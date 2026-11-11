"""Stop-width and exit matrix for the two efficiency-ratio systems. IN-SAMPLE ONLY (signals to 2021-08-06; the last 5 years, from 2021-11-08, are SEALED).

Systems (same signals as system_report.py): buy or sell the first session the efficiency ratio reaches the threshold in the trend direction, enter at the next open,
one position per market, 48 report markets, no costs.
  - 20-session efficiency ratio >= 0.6
  - 15-session efficiency ratio >= 0.7

Position size (Michael, 11 Nov 2026): ONE ATR = 0.25% of equity (ATR = 14-session mean true range at the signal close), added not compounded. So every position holds
0.25% / ATR-in-dollars of the market, whatever the stop width. Only the exit changes between cells, so the cells compare cleanly (with fixed risk per trade a wider stop
would also shrink the position).

Grid: initial stop 2 / 3 / 4 / 5 ATR  x  10 exits
  fixed stop only (it never moves) with a time cap of 60 / 90 / 120 sessions, or NO cap
  channel trailing stop under the lowest low of the last 40 / 20 sessions (above the highest high for shorts), NO cap
  trailing stop 4 ATR / 6 ATR below the highest high since entry (above the lowest low for shorts), with the 60-session cap and with NO cap

Rules shared by every cell
  - Stops are checked every session from the second session on; a gap through the stop fills at the open, otherwise at the stop. The entry session is checked as in
    the earlier reports (a low through the stop on the entry session is a full stop-out at the stop price).
  - A trailing or channel stop is updated at each close and applies from the next session; it only ratchets toward price and never goes below the initial stop (no look-ahead).
    The channel uses the real price history up to that close (including sessions before the entry), as a standard channel does.
  - Same trade filter for every exit: the first 60 sessions of the path must exist and have no data hole (as in the earlier reports). Beyond that a longer or uncapped trade
    is closed at the close before a data hole, and at the LAST IN-SAMPLE CLOSE (the last session before 2021-11-08) if it is still open. No sealed price is used.
  - One position per market: a new signal can come at the close of the exit session; the trade set therefore depends on the exit.
Statistics per cell (all in % of starting equity at 0.25% per ATR): average return per year (added), Sharpe (no risk-free rate, daily returns over ONE common calendar for every cell),
worst drawdown, average drawdown over all days (time-weighted), Calmar (annual return / worst drawdown), trades.
The 80 cells are many comparisons on one sample: treat small gaps as noise; the best cell is biased upward.
"""
import os
import sys
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import efficiency_trend as et  # noqa: E402
eg, tf, ts = et.eg, et.tf, et.ts

ATR_EQUITY = 0.0025             # one ATR = 0.25% of equity
SYSTEMS = {"20-session ratio 0.6": (20, 0.6), "15-session ratio 0.7": (15, 0.7)}
INITIAL_STOPS = (2.0, 3.0, 4.0, 5.0)
# (label, kind, parameter, cap in sessions or None)
EXITS = [
    ("fixed stop, 60-session cap", "fixed", 0, 60),
    ("fixed stop, 90-session cap", "fixed", 0, 90),
    ("fixed stop, 120-session cap", "fixed", 0, 120),
    ("fixed stop, no cap", "fixed", 0, None),
    ("40-session channel trail, no cap", "channel", 40, None),
    ("20-session channel trail, no cap", "channel", 20, None),
    ("4 ATR trail, 60-session cap", "atr_trail", 4.0, 60),
    ("4 ATR trail, no cap", "atr_trail", 4.0, None),
    ("6 ATR trail, 60-session cap", "atr_trail", 6.0, 60),
    ("6 ATR trail, no cap", "atr_trail", 6.0, None),
]
CHANNELS = (20, 40)
BASELINE = ("fixed stop, 60-session cap", 3.0)
METRICS = [("annual_return_pct", "average return per year, %"), ("sharpe", "Sharpe ratio"), ("worst_drawdown_pct", "worst drawdown, %"),
           ("average_drawdown_pct", "average drawdown (all days), %"), ("calmar", "Calmar ratio"), ("trades", "trades")]


def clip_and_prepare(prices, symbols):
    """Drop every bar from the sealed window on, then build the signed views (long as is; short negated) and the rolling channel arrays."""
    for sym in symbols:
        s = prices[sym]
        keep = s["d"] < eg.OUT_START
        for k in ("d", "o", "h", "l", "c", "tr"):
            s[k] = s[k][keep]
        h, l = pd.Series(s["h"]), pd.Series(s["l"])
        s["view"] = {1: (s["o"], s["h"], s["l"], s["c"]), -1: (-s["o"], -s["l"], -s["h"], -s["c"])}
        s["chan"] = {}
        for n in CHANNELS:
            lo, hi = l.rolling(n).min().values, h.rolling(n).max().values
            s["chan"][n] = {1: lo, -1: -hi}      # the channel level in each direction's own (signed) terms
        s["gap_after"] = np.r_[np.diff(s["d"]).astype(int) > eg.MAX_CALENDAR_GAP, True]   # True where the next bar is a hole or there is no next bar


def candidates(s, lookback, threshold):
    """Signal bars for a system (fresh signal, with the trend, in-sample only). Independent of any position, so it is computed once."""
    d = s["d"]
    er, net = s[f"er{lookback}"], s[f"net{lookback}"]
    out = []
    for i in range(max(lookback, 14), len(d) - 1):
        if d[i] > eg.IN_END:
            break
        if np.isnan(er[i]) or net[i] == 0 or not er[i] >= threshold:
            continue
        if i > 0 and er[i - 1] >= threshold and net[i - 1] * net[i] > 0:
            continue
        out.append((i, 1 if net[i] > 0 else -1))
    return out


def simulate(s, i, direction, stop_atr, kind, param, cap):
    """Run one trade entered at the open of bar i+1. Returns None if the trade filter rejects it, else (path in ATR, entry index, reason)."""
    n, d = len(s["c"]), s["d"]
    j = i + 1
    if i < 14 or j + eg.CAP - 1 > n - 1:
        return None
    if np.any(np.diff(d[i:j + eg.CAP]).astype(int) > eg.MAX_CALENDAR_GAP):
        return None
    atr = float(np.nanmean(s["tr"][i - 13:i + 1]))
    if not atr > 0:
        return None
    o, h, l, c = s["view"][direction]
    entry = o[j]
    stop = entry - stop_atr * atr
    if l[j] <= stop:                                    # stopped on the entry session: a full loss at the stop price
        return [-stop_atr], j, "stop", atr
    chan = s["chan"][param][direction] if kind == "channel" else None
    gap_after = s["gap_after"]
    hh = -np.inf
    path = []
    k = j
    while True:
        sess = k - j + 1
        if k > j:
            if o[k] <= stop:
                path.append((o[k] - entry) / atr)
                return path, j, "stop", atr
            if l[k] <= stop:
                path.append((stop - entry) / atr)
                return path, j, "stop", atr
        path.append((c[k] - entry) / atr)
        if cap is not None and sess >= cap:
            return path, j, "cap", atr
        if gap_after[k]:                                 # data hole, or the last in-sample close: close the trade here
            return path, j, "forced", atr
        hh = max(hh, h[k])
        if kind == "atr_trail":
            stop = max(stop, hh - param * atr)
        elif kind == "channel" and not np.isnan(chan[k]):
            stop = max(stop, chan[k])
        k += 1


def run_cell(prices, cands, stop_atr, kind, param, cap):
    """One pass over all markets for one exit. Returns trade records and the daily profit in ATR units by date."""
    trades, pnl, opens = [], {}, {}
    for sym, sig in cands.items():
        s = prices[sym]
        d = s["d"]
        next_free = 0
        for i, direction in sig:
            if i < next_free:
                continue
            r = simulate(s, i, direction, stop_atr, kind, param, cap)
            if r is None:
                continue
            path, j, reason, atr = r
            trades.append(dict(symbol=sym, setup_date=d[i], entry_idx=j, direction=direction, final=path[-1], sessions=len(path), reason=reason))
            delta = np.diff(np.r_[0.0, path])
            for day, x in zip(d[j:j + len(path)], delta):
                pnl[day] = pnl.get(day, 0.0) + x
                opens[day] = opens.get(day, 0) + 1
            next_free = j + len(path) - 1
    return trades, pnl, opens


def calendar(prices, symbols, start):
    days = np.unique(np.concatenate([prices[x]["d"] for x in symbols]))
    return pd.DatetimeIndex(days[days >= start])


def cell_stats(trades, pnl, opens, days):
    ret = pd.Series([pnl.get(x, 0.0) for x in days.values.astype("datetime64[D]")], index=days) * ATR_EQUITY
    open_count = pd.Series([opens.get(x, 0) for x in days.values.astype("datetime64[D]")], index=days)
    years = (days[-1] - days[0]).days / 365.25
    eq = ret.cumsum()
    peak = np.maximum.accumulate(np.r_[0.0, eq.values])[1:]
    dd = eq.values - peak
    worst = -dd.min() * 100
    ann = ret.sum() / years * 100
    finals = np.array([t["final"] for t in trades])
    sess = np.array([t["sessions"] for t in trades])
    reasons = pd.Series([t["reason"] for t in trades]).value_counts()
    return dict(annual_return_pct=ann, volatility_pct=ret.std() * np.sqrt(252) * 100, sharpe=ret.mean() / ret.std() * np.sqrt(252) if ret.std() > 0 else np.nan,
                worst_drawdown_pct=worst, average_drawdown_pct=-dd.mean() * 100, calmar=ann / worst if worst > 0 else np.nan, trades=len(trades),
                total_profit_pct=eq.iloc[-1] * 100, win_rate_pct=(finals > 0).mean() * 100, mean_result_atr=finals.mean(), average_sessions_held=sess.mean(),
                share_ended_by_stop_pct=100 * reasons.get("stop", 0) / len(trades), share_ended_by_cap_pct=100 * reasons.get("cap", 0) / len(trades),
                forced_closes=int(reasons.get("forced", 0)), average_open_trades=open_count.mean(), max_open_trades=int(open_count.max()), longest_hold_sessions=int(sess.max()),
                best_trade_atr=finals.max(), worst_trade_atr=finals.min())


def verify_baseline(prices, report, cands_by_system, days):
    """The 3 ATR fixed stop with the 60-session cap must equal the earlier (fixed-risk) engine exactly, scaled by 1.5 (0.75% risk instead of 0.5%)."""
    for name, (lb, thr) in SYSTEMS.items():
        label, stop = BASELINE
        _, kind, param, cap = next(e for e in EXITS if e[0] == label)
        trades, pnl, opens = run_cell(prices, cands_by_system[name], stop, kind, param, cap)
        recs = et.run_system(prices, report, et.EXITS[3], thr, lb, "fresh", "with", stop)
        _, old_daily = et.portfolio_stats(recs, prices)
        new_daily = pd.Series([pnl.get(x, 0.0) for x in days.values.astype("datetime64[D]")], index=days) * ATR_EQUITY
        old = (old_daily * ts.RISK_PER_TRADE).reindex(days).fillna(0.0)
        scale = ATR_EQUITY * stop / ts.RISK_PER_TRADE                    # new size relative to the old 0.5%-risk size
        diff = float(np.abs(new_daily.values - old.values * scale).max())
        print(f"verification {name}: new trades {len(trades)}, old trades {len(recs)}, largest daily difference {diff:.2e}")
        assert len(trades) == len(recs), "trade count differs from the earlier engine"
        assert diff < 1e-9, "daily returns differ from the earlier engine"


def fmt(x):
    return f"{x:,.2f}"


def main(price_path, universe_path, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    prices = eg.load_prices(price_path)
    uni = pd.read_csv(universe_path, dtype=str)
    report = sorted({eg.PRICE_ROOTS.get(x, x) for x in uni["ibkr"]} & set(prices))
    clip_and_prepare(prices, report)                        # sealed bars are removed BEFORE anything else is computed
    tf.add_trend(prices, tuple(lb for lb, _ in SYSTEMS.values()))
    last_day = max(prices[x]["d"][-1] for x in report)
    assert last_day < eg.OUT_START, "sealed bars must be gone"
    days = calendar(prices, report, np.datetime64("2008-01-30"))
    cands_by_system = {name: {sym: candidates(prices[sym], lb, thr) for sym in report} for name, (lb, thr) in SYSTEMS.items()}
    log = []

    def emit(x):
        print(x)
        log.append(x)

    emit("Stop-width and exit matrix, IN-SAMPLE only (last 5 years from 2021-11-08 sealed; last price used "
         f"{pd.Timestamp(last_day).date()}). 48 report markets, no costs, ONE ATR = 0.25% of equity, added not compounded.\n"
         f"Common calendar for every cell: {days[0].date()} to {days[-1].date()}.\n")
    verify_baseline(prices, report, cands_by_system, days)
    emit("Verification: the 3 ATR fixed stop with the 60-session cap reproduces the earlier fixed-risk engine exactly (same trades, same daily returns after scaling by 1.5).\n")
    rows = []
    for name in SYSTEMS:
        for label, kind, param, cap in EXITS:
            for stop in INITIAL_STOPS:
                trades, pnl, opens = run_cell(prices, cands_by_system[name], stop, kind, param, cap)
                rows.append(dict(system=name, exit=label, initial_stop_atr=stop, **cell_stats(trades, pnl, opens, days)))
    g = pd.DataFrame(rows)
    g.to_csv(f"{out_dir}/exit_matrix_cells.csv", index=False)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 50)
    order = [e[0] for e in EXITS]
    for name in SYSTEMS:
        sub = g[g["system"] == name]
        emit(f"\n==================== {name} ====================")
        for col, title in METRICS:
            pv = sub.pivot(index="exit", columns="initial_stop_atr", values=col).loc[order]
            pv.columns = [f"{c:g} ATR stop" for c in pv.columns]
            emit(f"\n--- {title} (rows: exit; columns: initial stop) ---\n" + (pv.round(0).astype(int) if col == "trades" else pv.round(2)).to_string())
        extra = sub[sub["initial_stop_atr"] == 3.0].set_index("exit").loc[order][["volatility_pct", "win_rate_pct", "average_sessions_held", "longest_hold_sessions",
                                                                                 "share_ended_by_stop_pct", "share_ended_by_cap_pct", "forced_closes", "average_open_trades",
                                                                                 "max_open_trades"]]
        emit("\n--- Extra detail at the 3 ATR initial stop ---\n" + extra.round(1).to_string())
    for col, title in (("sharpe", "Sharpe"), ("calmar", "Calmar")):
        top = g.sort_values(col, ascending=False).head(10)[["system", "exit", "initial_stop_atr", "annual_return_pct", "sharpe", "worst_drawdown_pct", "average_drawdown_pct", "calmar", "trades"]]
        emit(f"\n--- Top 10 cells by {title} (biased upward: best of 80) ---\n" + top.round(2).to_string(index=False))
    emit("\nAverages across all cells by exit and by initial stop (Sharpe / Calmar):\n"
         + g.groupby("exit")[["sharpe", "calmar", "annual_return_pct", "worst_drawdown_pct"]].mean().loc[order].round(2).to_string() + "\n\n"
         + g.groupby("initial_stop_atr")[["sharpe", "calmar", "annual_return_pct", "worst_drawdown_pct"]].mean().round(2).to_string())
    open(f"{out_dir}/exit_matrix_report.txt", "w").write("\n".join(log))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3])
