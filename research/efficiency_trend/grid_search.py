"""Efficiency-ratio rule: grid over window x threshold x initial ATR stop x exit (stop only, or trailing ATR stop). IN-SAMPLE ONLY (signals to 2021-08-06; last 5 years sealed).

Each configuration is the same rule as efficiency_trend.py (fresh signal, trade with the trend, next open, one position per market, 48 report markets, no costs,
0.5% of equity risked per trade) with these settings varied: efficiency window 5/10/15/20/30/40 sessions, threshold 0.3-0.7, initial stop 1/1.5/2/3/4 ATR, exit =
stop only (hold until stopped, cap 60 sessions) or a trailing stop 2/3/4/6 ATR below the highest high since entry (above the lowest low for shorts).
One risk unit = the initial stop distance, so a wider stop means a smaller position at the same 0.5% risk.
Because 750 settings are compared, the best-looking one is biased upward. The check: pick the best settings using ONLY the first half of the in-sample years (to 2014)
and look at how those same settings did in the second half (2015 to mid-2021).
"""
import os
import sys
from multiprocessing import Pool
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import efficiency_trend as et  # noqa: E402
eg, tf, ts = et.eg, et.tf, et.ts

WINDOWS = (5, 10, 15, 20, 30, 40)
THRESHOLDS = (0.3, 0.4, 0.5, 0.6, 0.7)
INITIAL_STOPS = (1.0, 1.5, 2.0, 3.0, 4.0)
HOLD = next(e for e in eg.EXITS if e[0].startswith("hold until stopped"))
EXITS = [("stop only (hold until stopped)", HOLD)] + [(f"trail {x:g} ATR", (f"trail {x:g} ATR", "chandelier", float(x), eg.CAP)) for x in (2, 3, 4, 6)]
PRICES = None
REPORT = None


def sharpe(r):
    return float(r.mean() / r.std() * np.sqrt(252)) if len(r) > 5 and r.std() > 0 else np.nan


def half_sharpes(daily_r):
    r = daily_r * ts.RISK_PER_TRADE
    cut = pd.Timestamp(str(eg.HALF_SPLIT))
    return sharpe(r[r.index <= cut]), sharpe(r[r.index > cut])


def one_config(cfg):
    lb, thr, stop, (exit_name, spec) = cfg
    recs = et.run_system(PRICES, REPORT, spec, thr, lb, "fresh", "with", stop)
    base = dict(window=lb, threshold=thr, initial_stop_atr=stop, exit=exit_name)
    if len(recs) < 30:
        return dict(base, trades=len(recs))
    df = et.records_frame(recs)
    st, daily = et.portfolio_stats(recs, PRICES)
    s1, s2 = half_sharpes(daily)
    return dict(base, trades=len(recs), mean_result_risk_units=df["result"].mean(), mean_result_atr=df["result"].mean() * stop,
                plus_minus_2se=2 * eg.cluster_se(df["result"], df["setup_date"]), win_rate=(df["result"] > 0).mean(),
                annual_return_pct=st["annual_return_pct"], volatility_pct=st["annual_volatility_pct"], sharpe=st["sharpe"],
                max_drawdown_pct=st["max_drawdown_pct"], sharpe_first_half=s1, sharpe_second_half=s2)


def main(price_path, universe_path, out_dir, processes=4):
    global PRICES, REPORT
    os.makedirs(out_dir, exist_ok=True)
    PRICES = eg.load_prices(price_path)
    tf.add_trend(PRICES, WINDOWS)
    uni = pd.read_csv(universe_path, dtype=str)
    REPORT = sorted({eg.PRICE_ROOTS.get(x, x) for x in uni["ibkr"]} & set(PRICES))
    cfgs = [(lb, thr, st, ex) for lb in WINDOWS for thr in THRESHOLDS for st in INITIAL_STOPS for ex in EXITS]
    with Pool(processes) as pool:
        rows = pool.map(one_config, cfgs, chunksize=5)
    g = pd.DataFrame(rows)
    g.to_csv(f"{out_dir}/grid_results.csv", index=False)
    log = []

    def emit(x):
        print(x)
        log.append(x)

    pd.set_option("display.width", 250)
    pd.set_option("display.max_rows", 500)
    ok = g.dropna(subset=["sharpe"])
    ok = ok[ok["trades"] >= 100]
    cols = ["window", "threshold", "initial_stop_atr", "exit", "trades", "mean_result_risk_units", "mean_result_atr", "plus_minus_2se", "annual_return_pct",
            "volatility_pct", "sharpe", "max_drawdown_pct", "sharpe_first_half", "sharpe_second_half"]
    emit(f"Efficiency-ratio grid, IN-SAMPLE signals 2008 to mid-2021 (last 5 years sealed), 48 report markets, no costs, 0.5% of equity risked per trade.\n"
         f"{len(g)} settings run, {len(ok)} with at least 100 trades.\n")
    emit("=== Share of settings with a positive Sharpe: %.0f%%; median Sharpe %.2f; best %.2f ===\n" % (100 * (ok["sharpe"] > 0).mean(), ok["sharpe"].median(), ok["sharpe"].max()))
    emit("=== TOP 15 settings by full in-sample Sharpe (biased upward: best of many) ===\n" + ok.sort_values("sharpe", ascending=False).head(15)[cols].round(2).to_string(index=False) + "\n")
    top1 = ok.sort_values("sharpe_first_half", ascending=False).head(15)
    emit("=== HONEST CHECK: top 15 settings chosen using only the FIRST half (to 2014); same settings in the SECOND half (2015 to mid-2021) ===\n"
         + top1[cols].round(2).to_string(index=False) + "\n"
         + "Average second-half Sharpe of these 15: %.2f. Average second-half Sharpe of ALL settings: %.2f. " % (top1["sharpe_second_half"].mean(), ok["sharpe_second_half"].mean())
         + "Rank correlation between first-half and second-half Sharpe across all settings: %.2f.\n" % ok[["sharpe_first_half", "sharpe_second_half"]].corr(method="spearman").iloc[0, 1])
    top2 = ok.sort_values("sharpe_second_half", ascending=False).head(10)
    emit("=== Reverse check: top 10 by SECOND half, and what they did in the first half ===\n" + top2[cols].round(2).to_string(index=False) + "\n")
    for p, label in (("window", "efficiency window (sessions)"), ("threshold", "ratio threshold"), ("initial_stop_atr", "initial stop (ATR)"), ("exit", "exit")):
        m = ok.groupby(p).agg(settings=("sharpe", "size"), avg_trades=("trades", "mean"), avg_sharpe=("sharpe", "mean"), avg_first_half=("sharpe_first_half", "mean"),
                              avg_second_half=("sharpe_second_half", "mean"), avg_mean_result_atr=("mean_result_atr", "mean"), avg_max_drawdown_pct=("max_drawdown_pct", "mean"))
        emit(f"=== Average over all other settings, by {label} ===\n" + m.round(2).to_string() + "\n")
    pv = ok[ok["exit"] == EXITS[0][0]].pivot_table(index="window", columns="initial_stop_atr", values="sharpe", aggfunc="mean")
    emit("=== Stop only: Sharpe by window (rows) and initial stop in ATR (columns), averaged over thresholds ===\n" + pv.round(2).to_string() + "\n")
    pv = ok[ok["initial_stop_atr"] == 2.0].pivot_table(index="exit", columns="window", values="sharpe", aggfunc="mean")
    emit("=== Initial stop 2 ATR: Sharpe by exit (rows) and window (columns), averaged over thresholds ===\n" + pv.round(2).to_string() + "\n")
    open(f"{out_dir}/grid_summary.txt", "w").write("\n".join(log))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3])
