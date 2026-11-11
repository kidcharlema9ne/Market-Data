"""Efficiency-ratio trend rule alone (NO outside-day / inside-day pattern), 2 ATR risk. IN-SAMPLE ONLY (signals 2007-12-31 .. 2021-08-06).

THE LAST 5 YEARS (signals from 2021-11-08) ARE SEALED: no signal dated after 2021-08-06 is ever built, and a trade's 60-session path then ends before 2021-11-08.

Rule (Michael, 11 Nov 2026)
- Efficiency ratio (Kaufman) over a lookback (primary 20 sessions) at the close: |close now - close lookback ago| / sum of |daily close changes| over the lookback.
- Trend direction = sign of the close change over the lookback. Signal: efficiency ratio >= 0.5 -> buy if the trend is up, sell if down.
- Entry: the NEXT session's open. Initial stop: 2 ATR from the entry (ATR = mean true range of the 14 sessions ending at the signal close). One risk unit = 2 ATR.
- Entry modes: (primary) FRESH SIGNAL = the first session the ratio reaches the threshold in that trend direction; (secondary) WHEN FLAT = any session the condition holds while no position is open in that market.
- One position per market at a time (a signal while a position is open is skipped), so the trade set depends on the exit.
- Exits tested (declared in advance; the stop is always kept): time exit at the close of session 10 / 20 / 40; hold until stopped (cap 60 sessions); trailing stop 2 / 3 / 4 ATR
  below the highest high since entry (above the lowest low for shorts), cap 60 sessions. The entry bar's stop is checked (entry is at the open, so the order is known).
- Comparisons: AGAINST the trend at the same ratio; and WITH the trend at any ratio (ratio >= 0).
- Sensitivity (secondary): thresholds 0.3 / 0.4 / 0.5 / 0.6 / 0.7 and lookbacks 10 / 20 / 40 for two exits.
- Universe: Michael's 48 report markets. No costs unless stated. Portfolio statistics as in trail_stats.py (0.5% of equity risked per trade, added not compounded).
"""
import os
import sys
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "outside_inside"))
import exit_grid as eg      # noqa: E402
import trend_filter as tf   # noqa: E402
import trail_stats as ts    # noqa: E402

STOP_ATR = 2.0
THRESHOLD = 0.5
PRIMARY_LOOKBACK = 20
LOOKBACKS = (10, 20, 40)
SENS_THRESHOLDS = (0.3, 0.4, 0.5, 0.6, 0.7)
EXIT_NAMES = ["time exit, close of session 10", "time exit, close of session 20", "time exit, close of session 40",
              "hold until stopped (cap 60 sessions)", "trail 2 ATR below the highest high", "trail 3 ATR below the highest high",
              "trail 4 ATR below the highest high"]
EXITS = [e for n in EXIT_NAMES for e in eg.EXITS if e[0] == n]
SENS_EXITS = ["hold until stopped (cap 60 sessions)", "trail 4 ATR below the highest high"]
COMPARE_EXITS = ["time exit, close of session 20", "hold until stopped (cap 60 sessions)", "trail 4 ATR below the highest high"]


def make_trade(s, i, direction, stop_atr=STOP_ATR):
    """Enter at the open of session i+1; stop stop_atr ATRs away; path of CAP sessions from the entry session."""
    n, d = len(s["c"]), s["d"]
    j = i + 1
    if i < 14 or j + eg.CAP - 1 > n - 1:
        return None
    if np.any(np.diff(d[i:j + eg.CAP]).astype(int) > eg.MAX_CALENDAR_GAP):
        return None
    atr = float(np.nanmean(s["tr"][i - 13:i + 1]))
    if not atr > 0:
        return None
    if direction == 1:
        o, h, l, c = s["o"], s["h"], s["l"], s["c"]
    else:
        o, h, l, c = -s["o"], -s["l"], -s["h"], -s["c"]
    entry = o[j]
    risk = stop_atr * atr
    stop = entry - risk
    sl = slice(j, j + eg.CAP)
    return dict(path=(o[sl].tolist(), h[sl].tolist(), l[sl].tolist(), c[sl].tolist()), entry=entry, stop=stop, risk=risk, atr=atr,
                ignore_low=False, stopped_entry=bool(l[j] <= stop), entry_idx=j, direction="long" if direction == 1 else "short",
                risk_pct=risk / abs(entry) * 100)


def run_system(prices, symbols, exit_spec, threshold, lookback, mode="fresh", side="with"):
    """One pass per exit (positions gate the next signal). Returns a list of trade records with the daily profit path in risk units."""
    out = []
    for sym in symbols:
        s = prices[sym]
        d = s["d"]
        er, net = s[f"er{lookback}"], s[f"net{lookback}"]
        next_free = 0
        for i in range(max(lookback, 14), len(d) - 1):
            if d[i] > eg.IN_END:                        # SEALED
                break
            if i < next_free or np.isnan(er[i]) or net[i] == 0:
                continue
            if not er[i] >= threshold:
                continue
            trend = 1 if net[i] > 0 else -1
            if mode == "fresh" and i > 0 and er[i - 1] >= threshold and net[i - 1] * net[i] > 0:
                continue
            direction = trend if side == "with" else -trend
            t = make_trade(s, i, direction)
            if not t:
                continue
            path = ts.daily_path(t, exit_spec)
            t.update(symbol=sym, setup_date=d[i], path_r=path, final=path[-1], sessions=len(path))
            out.append(t)
            next_free = t["entry_idx"] + len(path) - 1     # a new signal may come at the close of the exit session
    return out


def records_frame(recs):
    return pd.DataFrame([dict(symbol=r["symbol"], setup_date=str(r["setup_date"]), direction=r["direction"], result=r["final"],
                              sessions=r["sessions"], half="first" if r["setup_date"] <= eg.HALF_SPLIT else "second",
                              risk_pct=r["risk_pct"]) for r in recs])


def trade_stats(df):
    x = df["result"]
    wins, losses = x[x > 0].sum(), -x[x < 0].sum()
    return pd.Series(dict(trades=len(df), mean_result=x.mean(), plus_minus_2se=2 * eg.cluster_se(x, df["setup_date"]), median=x.median(),
                          win_rate=(x > 0).mean(), profit_factor=wins / losses if losses > 0 else np.nan, avg_sessions=df["sessions"].mean(),
                          first_half_mean=df[df["half"] == "first"]["result"].mean(), second_half_mean=df[df["half"] == "second"]["result"].mean(),
                          long_mean=df[df["direction"] == "long"]["result"].mean(), short_mean=df[df["direction"] == "short"]["result"].mean()))


def portfolio_stats(recs, prices, cost=0.0):
    pnl, opens, finals = {}, {}, []
    for r in recs:
        d = prices[r["symbol"]]["d"]
        dates = d[r["entry_idx"]: r["entry_idx"] + len(r["path_r"])]
        delta = np.diff(np.r_[0.0, r["path_r"]])
        delta[0] -= cost
        for day, x in zip(dates, delta):
            pnl[day] = pnl.get(day, 0.0) + x
            opens[day] = opens.get(day, 0) + 1
        finals.append(r["final"] - cost)
    daily, open_count = ts.full_calendar(pnl, opens, prices)
    return ts.performance(daily, open_count, np.array(finals)), daily


def main(price_path, universe_path, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    prices = eg.load_prices(price_path)
    tf.add_trend(prices, LOOKBACKS)
    uni = pd.read_csv(universe_path, dtype=str)
    report = sorted({eg.PRICE_ROOTS.get(x, x) for x in uni["ibkr"]} & set(prices))
    log = []

    def emit(x):
        print(x)
        log.append(x)

    pd.set_option("display.width", 250)
    emit("Efficiency-ratio trend rule alone (no pattern), 2 ATR initial stop, IN-SAMPLE signals 2008 to mid-2021, last 5 years sealed. 48 report markets, no costs.\n"
         "One risk unit = 2 ATR. Results are mean result per trade in risk units unless stated.\n")
    primary = {}
    for mode in ("fresh", "when flat"):
        key = "fresh" if mode == "fresh" else "whenflat"
        trows, prows = {}, {}
        for e in EXITS:
            recs = run_system(prices, report, e, THRESHOLD, PRIMARY_LOOKBACK, key)
            primary[(mode, e[0])] = recs
            trows[e[0]] = trade_stats(records_frame(recs))
            prows[e[0]] = portfolio_stats(recs, prices)[0]
        emit(f"=== PRIMARY: efficiency ratio >= {THRESHOLD} (20-session), WITH the trend, entry mode: {mode.upper()} -- per-trade statistics ===\n"
             + pd.DataFrame(trows).T.round(3).to_string() + "\n")
        emit(f"=== PRIMARY ({mode.upper()}): portfolio statistics, 0.5% of equity risked per trade ===\n"
             + pd.DataFrame(prows)[[e[0] for e in EXITS]].round(2).to_string() + "\n")
        pd.DataFrame(prows).to_csv(f"{out_dir}/portfolio_{key}.csv")
    # cost illustration for the primary entry mode
    crows = {e[0]: portfolio_stats(primary[("fresh", e[0])], prices, ts.COST_R)[0] for e in EXITS}
    emit(f"=== PRIMARY (FRESH) with an ASSUMED cost of {ts.COST_R} risk units (0.1 ATR) per trade ===\n"
         + pd.DataFrame(crows)[[e[0] for e in EXITS]].round(2).loc[["trades", "expectancy_R_per_trade", "annual_return_pct", "sharpe", "max_drawdown_pct"]].to_string() + "\n")
    by_year = {}
    for e in (x for x in EXITS if x[0] in COMPARE_EXITS):
        _, daily = portfolio_stats(primary[("fresh", e[0])], prices)
        r = daily * ts.RISK_PER_TRADE * 100
        by_year[e[0]] = r.groupby(r.index.year).sum()
    emit("=== PRIMARY (FRESH): return by calendar year, % of equity at 0.5% risk per trade ===\n" + pd.DataFrame(by_year).round(1).to_string() + "\n")
    by_mkt = records_frame(primary[("fresh", "trail 4 ATR below the highest high")])
    emit("=== PRIMARY (FRESH), trail 4 ATR: mean result by market (markets with 10+ trades) ===\n"
         + by_mkt.groupby("symbol")["result"].agg(trades="size", mean_result="mean").query("trades >= 10").sort_values("mean_result", ascending=False).round(2).to_string() + "\n")
    # comparisons
    comp = {}
    for label, thr, side in (("WITH the trend, ratio >= 0.5 (primary)", 0.5, "with"), ("AGAINST the trend, ratio >= 0.5", 0.5, "against"),
                             ("WITH the trend, any ratio (>= 0)", 0.0, "with"), ("AGAINST the trend, any ratio", 0.0, "against")):
        for e in (x for x in EXITS if x[0] in COMPARE_EXITS):
            recs = run_system(prices, report, e, thr, PRIMARY_LOOKBACK, "fresh" if thr > 0 else "whenflat", side)
            df = records_frame(recs)
            comp[(label, e[0])] = dict(trades=len(df), mean_result=df["result"].mean(), plus_minus_2se=2 * eg.cluster_se(df["result"], df["setup_date"]),
                                       sharpe=portfolio_stats(recs, prices)[0]["sharpe"])
    emit("=== COMPARISON (20-session): with vs against the trend, ratio >= 0.5 vs any ratio (any-ratio rows use the WHEN FLAT mode) ===\n"
         + pd.DataFrame(comp).T.round(3).to_string() + "\n")
    # sensitivity
    sens = {}
    for lb in LOOKBACKS:
        for thr in SENS_THRESHOLDS:
            for e in (x for x in EXITS if x[0] in SENS_EXITS):
                recs = run_system(prices, report, e, thr, lb, "fresh")
                df = records_frame(recs)
                st = portfolio_stats(recs, prices)[0]
                sens[(f"{lb}-session lookback", f"ratio >= {thr}", e[0])] = dict(
                    trades=len(df), mean_result=df["result"].mean(), plus_minus_2se=2 * eg.cluster_se(df["result"], df["setup_date"]),
                    win_rate=(df["result"] > 0).mean(), sharpe=st["sharpe"], max_drawdown_pct=st["max_drawdown_pct"])
    emit("=== SENSITIVITY (FRESH signal, WITH the trend): lookback x threshold x exit ===\n" + pd.DataFrame(sens).T.round(3).to_string() + "\n")
    primary_recs = primary[("fresh", "trail 4 ATR below the highest high")]
    records_frame(primary_recs).to_csv(f"{out_dir}/primary_trades_trail4atr.csv.gz", index=False)
    open(f"{out_dir}/efficiency_trend_results.txt", "w").write("\n".join(log))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3])
