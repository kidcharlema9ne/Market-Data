"""Where did the 20-session ratio 0.6 / 3 ATR fixed stop / 60-session cap system (0.25% of equity per ATR) make its money in 2008 and 2020? IN-SAMPLE only.
Daily profit is kept per market (each market run on its own; one position per market, so this equals the portfolio run split by market).
Check: the per-market profits add up to the committed in-sample total (284.07% of equity, 997 trades).
Usage: python year_breakdown.py prices.parquet universe.csv out_dir"""
import os
import sys
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import oos_single as o  # noqa: E402
em, eg, tf = o.em, o.eg, o.tf


def main(price_path, universe_path, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    prices = eg.load_prices(price_path)
    uni = pd.read_csv(universe_path, dtype=str)
    names = {eg.PRICE_ROOTS.get(a, a): n for a, n in zip(uni["ibkr"], uni["name"])}
    report = sorted(set(names) & set(prices))
    o.prepare(prices, report)
    tf.add_trend(prices, (o.LOOKBACK,))
    days = o.days_between(prices, report, o.IN_CAL_START, o.IN_CAL_END)
    dvals = days.values.astype("datetime64[D]")
    daily, ntr = {}, {}
    n_all = 0
    for sym in report:
        t, p, _, _ = o.run_window(prices, [sym], o.IN_SIGNAL_START, o.IN_SIGNAL_END, False)
        daily[sym] = pd.Series([p.get(x, 0.0) for x in dvals], index=days) * em.ATR_EQUITY * 100
        ntr[sym] = pd.DataFrame(t)
        n_all += len(t)
    D = pd.DataFrame(daily)
    total = D.values.sum()
    print(f"trades {n_all}, total profit {total:.4f}% of equity")
    assert n_all == 997 and abs(total - 284.07181371667156) < 1e-6, "per-market split does not add up to the committed in-sample result"
    out = []

    def emit(x):
        print(x)
        out.append(x)

    emit(f"Per-market profit split checks out: {n_all} trades, {total:.2f}% of equity in total (equals the committed in-sample result).\n")
    pd.set_option("display.width", 200)
    for yr in (2008, 2020):
        y = D[D.index.year == yr]
        s = y.sum().sort_values(ascending=False)
        t = pd.DataFrame(dict(market=[names.get(k, k) for k in s.index], profit_pct=s.values), index=s.index)
        sh = pd.concat(ntr.values())
        emit(f"==================== {yr}: total {s.sum():.1f}% of equity ({(s > 0).sum()} markets up, {(s < 0).sum()} down) ====================")
        emit("Top 12 markets:\n" + t.head(12).round(1).to_string())
        emit("\nBottom 6 markets:\n" + t.tail(6).round(1).to_string())
        emit(f"\nTop 5 add {s.head(5).sum():.1f}, top 10 add {s.head(10).sum():.1f}; ZQ alone {s.get('ZQ', 0):.1f}.")
        m = y.sum(axis=1).groupby(y.index.month).sum()
        emit("\nBy month (% of equity):\n" + m.round(1).to_string())
        # direction: trades entered that year, long vs short result
        sh = sh.copy()
        sh["year"] = pd.to_datetime(sh["entry_date"]).dt.year
        d = sh[sh["year"] == yr].assign(profit_pct=lambda z: z["final"] * em.ATR_EQUITY * 100)
        d["direction"] = d["direction"].map({1: "long", -1: "short"})
        emit("\nTrades entered in the year, by direction (result of each trade in full):\n" + d.groupby("direction")["profit_pct"].agg(["size", "sum"]).round(1).to_string() + "\n")
        t.assign(year=yr).to_csv(f"{out_dir}/markets_{yr}.csv")
    open(f"{out_dir}/year_breakdown_report.txt", "w").write("\n".join(out))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3])
