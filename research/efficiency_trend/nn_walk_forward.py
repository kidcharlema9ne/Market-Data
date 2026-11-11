"""Can a neural network predict which efficiency-ratio trades pay? Walk-forward, IN-SAMPLE ONLY (signals to 2021-08-06; last 5 years sealed).

Candidate trades: every session where the 20-session efficiency ratio is >= 0.3, traded in the trend direction, entered at the next open, initial stop 2 ATR
(no one-position-per-market gate, so trades overlap; this is a prediction dataset, not a portfolio). Result of each trade under two exits: stop only (hold until
stopped, cap 60) and a 4 ATR trailing stop, in risk units (one unit = 2 ATR).
Features (all known at the signal close): efficiency ratio over 5/10/20/40 sessions, change in the 20-session ratio over 5 sessions, trend move over 5/10/20/40
sessions in ATRs (positive = with the trade direction), ATR as a share of price, distance from the 60-session extreme in ATRs, last day's move in ATRs (with
direction), today's range in ATRs, direction.
Walk-forward: for each test year 2011-2021 the models are trained only on trades from earlier years whose setup date is at least 90 days before the test year starts
(so no training trade's 60-session path overlaps the test year). Models: efficiency ratio alone (no training), ridge regression, gradient boosting, and a small neural
network (two hidden layers 32 and 16, five random starts averaged). Test: predictions are ranked within each test year into five buckets; a useful model should show
the top bucket paying more than the bottom, with the buckets rising in order.
"""
import os
import sys
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import efficiency_trend as et  # noqa: E402
eg, tf, ts = et.eg, et.tf, et.ts

STOP_ATR = 2.0
MIN_ER = 0.3
PURGE_DAYS = 90
TEST_YEARS = range(2011, 2022)
FEATURES = ["er5", "er10", "er20", "er40", "er20_change_5", "move5_atr", "move10_atr", "move20_atr", "move40_atr", "atr_pct", "dist_extreme_atr",
            "last_day_atr", "range_atr", "direction"]
HOLD = et.EXITS[3]
TRAIL4 = et.EXITS[6]


def row_features(s, i, direction):
    c, h, l, tr = s["c"], s["h"], s["l"], s["tr"]
    atr = float(np.nanmean(tr[i - 13:i + 1]))
    ext = (c[i] - h[i - 59:i + 1].max()) / atr if direction == 1 else (l[i - 59:i + 1].min() - c[i]) / atr
    f = dict(er5=s["er5"][i], er10=s["er10"][i], er20=s["er20"][i], er40=s["er40"][i], er20_change_5=s["er20"][i] - s["er20"][i - 5],
             move5_atr=direction * s["net5"][i] / atr, move10_atr=direction * s["net10"][i] / atr, move20_atr=direction * s["net20"][i] / atr,
             move40_atr=direction * s["net40"][i] / atr, atr_pct=atr / abs(c[i]) * 100, dist_extreme_atr=ext,
             last_day_atr=direction * (c[i] - c[i - 1]) / atr, range_atr=tr[i] / atr, direction=float(direction))
    return f


def build_dataset(prices, symbols):
    rows = []
    for sym in symbols:
        s = prices[sym]
        d = s["d"]
        for i in range(60, len(d) - 1):
            if d[i] > eg.IN_END:                         # SEALED
                break
            er, net = s["er20"][i], s["net20"][i]
            if np.isnan(er) or er < MIN_ER or net == 0:
                continue
            direction = 1 if net > 0 else -1
            t = et.make_trade(s, i, direction, STOP_ATR)
            if not t:
                continue
            f = row_features(s, i, direction)
            if not np.all(np.isfinite(list(f.values()))):
                continue
            f.update(symbol=sym, setup_date=d[i], y_hold=eg.run_exit(t, *HOLD[1:])[0], y_trail4=eg.run_exit(t, *TRAIL4[1:])[0])
            rows.append(f)
    df = pd.DataFrame(rows)
    df["setup_date"] = pd.to_datetime(df["setup_date"])
    return df


def split_year(df, year):
    """Train: setup at least PURGE_DAYS before the test year starts. Test: setups in the test year."""
    start = pd.Timestamp(f"{year}-01-01")
    return df[df["setup_date"] < start - pd.Timedelta(days=PURGE_DAYS)], df[(df["setup_date"] >= start) & (df["setup_date"] < start + pd.Timedelta(days=366))]


def models():
    from sklearn.ensemble import HistGradientBoostingRegressor
    from sklearn.linear_model import Ridge
    from sklearn.neural_network import MLPRegressor
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    return {
        "ridge regression": lambda seed: make_pipeline(StandardScaler(), Ridge(alpha=10.0)),
        "gradient boosting": lambda seed: HistGradientBoostingRegressor(max_depth=3, learning_rate=0.05, max_iter=150, min_samples_leaf=100, random_state=seed),
        "neural network": lambda seed: make_pipeline(StandardScaler(), MLPRegressor(hidden_layer_sizes=(32, 16), alpha=1e-2, early_stopping=True, validation_fraction=0.15,
                                                                                    max_iter=300, random_state=seed)),
    }


def bucket_table(df, pred_col, y_col):
    d = df.copy()
    d["bucket"] = d.groupby(d["setup_date"].dt.year)[pred_col].transform(lambda x: pd.qcut(x.rank(method="first"), 5, labels=False)) + 1
    d["month"] = d["setup_date"].dt.to_period("M").astype(str)
    out = {}
    for b, g in d.groupby("bucket"):
        out[f"bucket {int(b)}"] = dict(trades=len(g), mean_result=g[y_col].mean(), plus_minus_2se=2 * eg.cluster_se(g[y_col], g["month"]), win_rate=(g[y_col] > 0).mean())
    out["all trades"] = dict(trades=len(d), mean_result=d[y_col].mean(), plus_minus_2se=2 * eg.cluster_se(d[y_col], d["month"]), win_rate=(d[y_col] > 0).mean())
    return pd.DataFrame(out).T


def main(price_path, universe_path, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    prices = eg.load_prices(price_path)
    tf.add_trend(prices, (5, 10, 20, 40))
    uni = pd.read_csv(universe_path, dtype=str)
    report = sorted({eg.PRICE_ROOTS.get(x, x) for x in uni["ibkr"]} & set(prices))
    df = build_dataset(prices, report)
    log = []

    def emit(x):
        print(x)
        log.append(x)

    pd.set_option("display.width", 250)
    emit(f"Neural network walk-forward, IN-SAMPLE only. {len(df)} candidate trades (20-session ratio >= {MIN_ER}, with the trend, 2 ATR stop), "
         f"{df['setup_date'].min().date()} to {df['setup_date'].max().date()}, test years {TEST_YEARS[0]}-{TEST_YEARS[-1]}.\n")
    emit("Average result of ALL candidate trades: stop only %.3f, 4 ATR trail %.3f risk units.\n" % (df["y_hold"].mean(), df["y_trail4"].mean()))
    mk = models()
    for ycol, label in (("y_hold", "STOP ONLY (hold until stopped)"), ("y_trail4", "4 ATR TRAILING STOP")):
        test_all = []
        for year in TEST_YEARS:
            tr, te = split_year(df, year)
            if len(tr) < 1000 or len(te) < 50:
                continue
            te = te.copy()
            te["efficiency ratio alone"] = te["er20"]
            ytr = tr[ycol].clip(-1, 6).values
            for name, make in mk.items():
                te[name] = np.mean([make(seed).fit(tr[FEATURES].values, ytr).predict(te[FEATURES].values) for seed in range(5 if name == "neural network" else 1)], axis=0)
            te["year"] = year
            test_all.append(te)
        te = pd.concat(test_all)
        te.to_csv(f"{out_dir}/predictions_{ycol}.csv.gz", index=False)
        emit(f"################ Target: {label} ################\n")
        summ = {}
        for name in ["efficiency ratio alone"] + list(mk):
            per_year = te.groupby("year").apply(lambda g: g[name].corr(g[ycol], method="spearman"), include_groups=False)
            summ[name] = dict(rank_correlation_all=te[name].corr(te[ycol], method="spearman"), avg_yearly_rank_correlation=per_year.mean(), years_positive=f"{(per_year > 0).sum()} of {len(per_year)}")
            tab = bucket_table(te, name, ycol)
            summ[name]["top_bucket_mean"] = tab.loc["bucket 5", "mean_result"]
            summ[name]["bottom_bucket_mean"] = tab.loc["bucket 1", "mean_result"]
            summ[name]["top_minus_bottom"] = summ[name]["top_bucket_mean"] - summ[name]["bottom_bucket_mean"]
            emit(f"--- {name}: average result by prediction bucket (1 = lowest predicted, 5 = highest), out-of-sample years pooled ---\n" + tab.round(3).to_string() + "\n")
        emit(f"=== SUMMARY for {label} ===\n" + pd.DataFrame(summ).T.round(3).to_string() + "\n")
        nn = te.groupby("year").apply(lambda g: pd.Series(dict(trades=len(g), all_trades=g[ycol].mean(), top_bucket_nn=g[g["neural network"] >= g["neural network"].quantile(0.8)][ycol].mean(),
                                                              top_bucket_ratio=g[g["efficiency ratio alone"] >= g["efficiency ratio alone"].quantile(0.8)][ycol].mean())), include_groups=False)
        emit(f"=== By test year: average result, all trades vs top fifth by the neural network vs top fifth by the efficiency ratio alone ({label}) ===\n" + nn.round(3).to_string() + "\n")
    open(f"{out_dir}/nn_results.txt", "w").write("\n".join(log))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3])
