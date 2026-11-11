"""ONE-TIME OUT-OF-SAMPLE test of a single pre-declared system (Michael, 11 Nov 2026: "run that out of sample").

System (declared before looking at the sealed years; nothing was tuned on them)
  - 20-session efficiency ratio >= 0.6, buy if the 20-session change is up, sell if down, first session the ratio reaches 0.6 in that direction
  - enter at the next session's open, one position per market, 48 report markets, no costs
  - FIXED stop 3 ATR from the entry (never moves; ATR = 14-session mean true range at the signal close), 60-session time cap
  - size: one ATR = 0.25% of equity (so the 3 ATR stop risks 0.75%), added not compounded
Windows
  - in-sample (reference only): signals 2007-12-31 .. 2021-08-06, calendar 2008-01-30 .. 2021-11-05
  - purge: 2021-08-07 .. 2021-11-07 (nothing used)
  - OUT OF SAMPLE: signals from 2021-11-08 to the end of the data. Price history before that date is used only to warm up the indicators (ratio, ATR), as in any live run.
Two ways to treat the end of the data (both reported, the same system):
  - "complete paths": a trade needs its full 60 sessions of prices, as in the in-sample runs, so signals in the last 60 sessions are dropped
  - "including open positions": a trade still open at the last price is marked at the last close (so recent signals count, but their result is not final)
Check: before anything is read from the sealed years, the in-sample window is rerun with this code and must equal the committed in-sample matrix cell exactly (trades, return, Sharpe, drawdowns), with and without ZQ.
Usage: python oos_single.py prices.parquet universe.csv out_dir [smoke]     (smoke = skip the committed-result check; for local synthetic tests only)
"""
import os
import sys
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import exit_matrix as em  # noqa: E402
et, eg, tf = em.et, em.eg, em.tf

LOOKBACK, THRESHOLD, STOP_ATR, CAP = 20, 0.6, 3.0, 60
SYSTEM_NAME, EXIT_NAME = "20-session ratio 0.6", "fixed stop, 60-session cap"
IN_SIGNAL_START, IN_SIGNAL_END = np.datetime64("2007-12-31"), eg.IN_END
IN_CAL_START, IN_CAL_END = np.datetime64("2008-01-30"), np.datetime64("2021-11-05")
OOS_SIGNAL_START = eg.OUT_START
KEEP = ["annual_return_pct", "volatility_pct", "sharpe", "worst_drawdown_pct", "average_drawdown_pct", "calmar", "trades", "win_rate_pct", "mean_result_atr",
        "average_sessions_held", "share_ended_by_stop_pct", "share_ended_by_cap_pct", "forced_closes", "average_open_trades", "max_open_trades", "total_profit_pct"]


def prepare(prices, symbols):
    """Signed views and hole flags, WITHOUT clipping anything (the out-of-sample years are used here, on purpose)."""
    for sym in symbols:
        s = prices[sym]
        s["view"] = {1: (s["o"], s["h"], s["l"], s["c"]), -1: (-s["o"], -s["l"], -s["h"], -s["c"])}
        s["chan"] = {}
        s["gap_after"] = np.r_[np.diff(s["d"]).astype(int) > eg.MAX_CALENDAR_GAP, True]


def candidates_window(s, lookback, threshold, start, end):
    """Fresh signals (ratio reaches the level in the trend direction) with signal date in [start, end]. The ratio's own history before `start` is used only for the
    'fresh' test and the warm-up; no outcome is looked at."""
    d = s["d"]
    er, net = s[f"er{lookback}"], s[f"net{lookback}"]
    out = []
    for i in range(max(lookback, 14), len(d) - 1):
        if d[i] > end:
            break
        if d[i] < start:
            continue
        if np.isnan(er[i]) or net[i] == 0 or not er[i] >= threshold:
            continue
        if i > 0 and er[i - 1] >= threshold and net[i - 1] * net[i] > 0:
            continue
        out.append((i, 1 if net[i] > 0 else -1))
    return out


def simulate_partial(s, i, direction, stop_atr, kind, param, cap):
    """Same as exit_matrix.simulate (fixed stop, cap) with ONE change: the trade is not rejected when fewer than 60 sessions of prices remain; it is then marked at the
    last close (reason 'forced'). Everything else (entry, stop fill, hole check over the sessions that exist) is identical."""
    n, d = len(s["c"]), s["d"]
    j = i + 1
    if i < 14 or j > n - 1:
        return None
    if np.any(np.diff(d[i:j + eg.CAP]).astype(int) > eg.MAX_CALENDAR_GAP):
        return None
    atr = float(np.nanmean(s["tr"][i - 13:i + 1]))
    if not atr > 0:
        return None
    o, h, l, c = s["view"][direction]
    entry = o[j]
    stop = entry - stop_atr * atr
    if l[j] <= stop:
        return [-stop_atr], j, "stop", atr
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
        if s["gap_after"][k]:
            return path, j, "forced", atr
        k += 1


def run_window(prices, symbols, sig_start, sig_end, partial):
    cands = {sym: candidates_window(prices[sym], LOOKBACK, THRESHOLD, sig_start, sig_end) for sym in symbols}
    saved = em.simulate
    em.simulate = simulate_partial if partial else saved
    try:
        trades, pnl, opens = em.run_cell(prices, cands, STOP_ATR, "fixed", 0, CAP)
    finally:
        em.simulate = saved
    for t in trades:
        t["entry_date"] = prices[t["symbol"]]["d"][t["entry_idx"]]
    return trades, pnl, opens, sum(len(v) for v in cands.values())


def days_between(prices, symbols, start, end):
    days = em.calendar(prices, symbols, start)
    return days[days.values.astype("datetime64[D]") <= end]


def daily(pnl, days):
    return pd.Series([pnl.get(x, 0.0) for x in days.values.astype("datetime64[D]")], index=days) * em.ATR_EQUITY


def block_bootstrap_sharpe(ret, block=21, reps=5000, seed=1):
    x = ret.values
    n = len(x)
    rng = np.random.default_rng(seed)
    nb = int(np.ceil(n / block))
    out = np.empty(reps)
    for r in range(reps):
        starts = rng.integers(0, n - block + 1, nb)
        y = np.concatenate([x[a:a + block] for a in starts])[:n]
        out[r] = y.mean() / y.std() * np.sqrt(252) if y.std() > 0 else np.nan
    return np.nanpercentile(out, [5, 50, 95]), float(np.nanmean(out <= 0))


def check_against_committed(stats, label, csv_name):
    ref = pd.read_csv(os.path.join(HERE, "results_exit_matrix", csv_name))
    ref = ref[(ref["system"] == SYSTEM_NAME) & (ref["exit"] == EXIT_NAME) & (ref["initial_stop_atr"] == STOP_ATR)].iloc[0]
    for k in ("annual_return_pct", "sharpe", "worst_drawdown_pct", "average_drawdown_pct", "calmar", "total_profit_pct"):
        assert abs(stats[k] - ref[k]) < 1e-6, f"{label}: {k} {stats[k]} differs from the committed in-sample matrix {ref[k]}"
    assert stats["trades"] == ref["trades"], f"{label}: trade count {stats['trades']} differs from committed {ref['trades']}"
    print(f"verification {label}: equals the committed in-sample cell ({int(ref['trades'])} trades, {ref['annual_return_pct']:.2f}% a year, Sharpe {ref['sharpe']:.2f}, worst drawdown {ref['worst_drawdown_pct']:.2f}%)")


def main(price_path, universe_path, out_dir, smoke=False):
    os.makedirs(out_dir, exist_ok=True)
    prices = eg.load_prices(price_path)
    uni = pd.read_csv(universe_path, dtype=str)
    report = sorted({eg.PRICE_ROOTS.get(x, x) for x in uni["ibkr"]} & set(prices))
    prepare(prices, report)
    tf.add_trend(prices, (LOOKBACK,))
    last_day = max(prices[x]["d"][-1] for x in report)
    log = []

    def emit(x):
        print(x)
        log.append(x)

    emit(f"ONE-TIME OUT-OF-SAMPLE TEST. System: {SYSTEM_NAME}, fixed {STOP_ATR:g} ATR stop, {CAP}-session cap, one ATR = 0.25% of equity (stop risks 0.75%), no costs.\n"
         f"{len(report)} report markets with prices; last price in the data {pd.Timestamp(last_day).date()}. Out-of-sample signals from {pd.Timestamp(OOS_SIGNAL_START).date()}.\n")

    sets = {"all 48 markets": report, "without ZQ (47 markets)": [x for x in report if x != "ZQ"]}
    rows, store = [], {}
    for set_name, syms in sets.items():
        # in-sample reference + check
        t, p, o, nsig = run_window(prices, syms, IN_SIGNAL_START, IN_SIGNAL_END, False)
        d_in = days_between(prices, syms, IN_CAL_START, IN_CAL_END)
        st = em.cell_stats(t, p, o, d_in)
        if not smoke:
            check_against_committed(st, set_name, "exit_matrix_cells.csv" if set_name == "all 48 markets" else "exit_matrix_cells_without_ZQ.csv")
        rows.append(dict(markets=set_name, window="in-sample 2008-2021 (reference)", signals=nsig, **{k: st[k] for k in KEEP}))
        store[(set_name, "in")] = (t, daily(p, d_in), d_in)
        # out of sample, both end-of-data treatments
        for label, partial in (("OUT OF SAMPLE, complete paths", False), ("OUT OF SAMPLE, including open positions", True)):
            t, p, o, nsig = run_window(prices, syms, OOS_SIGNAL_START, np.datetime64("2100-01-01"), partial)
            d_out = days_between(prices, syms, OOS_SIGNAL_START, last_day)
            st = em.cell_stats(t, p, o, d_out)
            rows.append(dict(markets=set_name, window=label, signals=nsig, **{k: st[k] for k in KEEP}))
            store[(set_name, label)] = (t, daily(p, d_out), d_out)
    g = pd.DataFrame(rows)
    g.to_csv(f"{out_dir}/oos_summary.csv", index=False)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 50)
    emit("Verification passed: the in-sample window rerun with this code equals the committed in-sample matrix cell (with and without ZQ).\n" if not smoke else "SMOKE RUN: no verification.\n")
    for set_name in sets:
        sub = g[g["markets"] == set_name].set_index("window")[["signals"] + KEEP].T
        emit(f"==================== {set_name} ====================\n(returns in % of starting equity, added not compounded; mean_result_atr = average trade in ATR units, divide by {STOP_ATR:g} for risk units)\n"
             + sub.round(2).to_string() + "\n")

    for set_name in sets:
        for label in ("OUT OF SAMPLE, complete paths", "OUT OF SAMPLE, including open positions"):
            trades, ret, days = store[(set_name, label)]
            tdf = pd.DataFrame(trades)
            tdf["profit_pct"] = tdf["final"] * em.ATR_EQUITY * 100
            tdf["direction"] = tdf["direction"].map({1: "long", -1: "short"})
            tdf["year"] = pd.to_datetime(tdf["entry_date"]).dt.year
            emit(f"==================== {set_name}: {label} ====================")
            se = tdf["final"].std() / np.sqrt(len(tdf))
            emit(f"Mean trade {tdf['final'].mean():.2f} ATR (= {tdf['final'].mean() / STOP_ATR:.2f} risk units), standard error {se:.2f} ATR if trades were independent (they are clustered, so this is too small).")
            ci, p_le0 = block_bootstrap_sharpe(ret)
            emit(f"Sharpe {ret.mean() / ret.std() * np.sqrt(252):.2f}; 21-day block bootstrap of the out-of-sample daily returns: 5th / 50th / 95th percentile {ci[0]:.2f} / {ci[1]:.2f} / {ci[2]:.2f}; share of resamples with Sharpe <= 0: {p_le0 * 100:.1f}%.")
            by_year = pd.DataFrame({"return_pct": ret.groupby(ret.index.year).sum() * 100, "trades_entered": tdf.groupby("year").size(),
                                    "win_rate_pct": tdf.groupby("year")["final"].apply(lambda x: (x > 0).mean() * 100)}).fillna(0)
            emit("\nBy calendar year (first and last year are partial):\n" + by_year.round(1).to_string())
            side = tdf.groupby("direction").agg(trades=("final", "size"), win_rate_pct=("final", lambda x: (x > 0).mean() * 100), mean_atr=("final", "mean"), profit_pct=("profit_pct", "sum"))
            emit("\nLong vs short:\n" + side.round(2).to_string())
            mk = tdf.groupby("symbol").agg(trades=("final", "size"), profit_pct=("profit_pct", "sum")).sort_values("profit_pct", ascending=False)
            emit("\nBest 6 and worst 6 markets (total profit, % of equity):\n" + pd.concat([mk.head(6), mk.tail(6)]).round(1).to_string())
            top = tdf.sort_values("profit_pct", ascending=False)
            emit(f"\nConcentration: total {tdf['profit_pct'].sum():.1f}%; the 5 best trades add {top['profit_pct'].head(5).sum():.1f}%, the 5 worst {top['profit_pct'].tail(5).sum():.1f}%; best single trade {top.iloc[0]['symbol']} {top.iloc[0]['profit_pct']:.1f}%.\n")
            tdf.assign(entry_date=[str(x) for x in tdf["entry_date"]]).to_csv(f"{out_dir}/trades_{set_name[:3].strip()}_{'open' if 'open' in label else 'complete'}.csv.gz", index=False)
            ret.to_csv(f"{out_dir}/daily_returns_{set_name[:3].strip()}_{'open' if 'open' in label else 'complete'}.csv", header=["return_fraction"])
    store[("all 48 markets", "in")][1].to_csv(f"{out_dir}/daily_returns_all_in_sample.csv", header=["return_fraction"])
    store[("without ZQ (47 markets)", "in")][1].to_csv(f"{out_dir}/daily_returns_without_ZQ_in_sample.csv", header=["return_fraction"])
    open(f"{out_dir}/oos_report.txt", "w").write("\n".join(log))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3], len(sys.argv) > 4 and sys.argv[4] == "smoke")
