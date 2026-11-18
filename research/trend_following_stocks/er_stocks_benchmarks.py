"""Compare the stock system (volume-surge ranking, from results_equity/equity_daily.csv) with SPY and QQQ: buy and hold, and long only while the ETF closed above its own 200-day average (flat otherwise).
Usage: python er_stocks_benchmarks.py stock_prices_dir_unused spy_prices.parquet nasdaq_etfs.parquet OUT_DIR EQUITY_DAILY_CSV
Same basis as the stock system: a fixed $300,000 account, no compounding, idle cash earns nothing, no trading costs for the ETF rows. The 200-day rule uses the close two sessions back for the position held on a day (a one-day delay, a stand-in for filling the next session).
In-sample only (2000-01-01 to 2021-08-06, the dates of the equity file). Post hoc.
"""
import sys
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

CAPITAL = 300000.0
EPOCH = pd.Timestamp("1970-01-01")


def load(path, sym=None):
    df = pd.read_parquet(path)
    if sym is not None:
        df = df[df.symbol == sym]
    df = df.sort_values("date_i").drop_duplicates("date_i")
    return pd.Series(df["close"].to_numpy(float), index=EPOCH + pd.to_timedelta(df["date_i"].to_numpy(), unit="D"))


def main():
    spy_path, etf_path, out_dir, eq_csv = sys.argv[2], sys.argv[3], Path(sys.argv[4]), sys.argv[5]
    out_dir.mkdir(parents=True, exist_ok=True)
    eq = pd.read_csv(eq_csv, index_col=0, parse_dates=True)
    idx = eq.index
    spy = load(spy_path); qqq = load(etf_path, "QQQ")
    D = pd.DataFrame(index=idx)
    for name, s in (("SPY", spy), ("QQQ", qqq)):
        full = s.reindex(s.index.union(idx)).ffill()
        ret = full.pct_change()
        sma = full.rolling(200, min_periods=200).mean()
        on = (full > sma).astype(float).where(sma.notna(), 0.0)
        pos = on.shift(2).fillna(0.0)                         # state at the close two sessions back
        D[f"{name} buy and hold"] = (ret * CAPITAL).reindex(idx).fillna(0.0)
        D[f"{name} long only above its 200-day average, else flat"] = (ret * pos * CAPITAL).reindex(idx).fillna(0.0)
        print(f"{name}: above its 200-day average {on.reindex(idx).mean()*100:.0f}% of sessions; first data {s.index.min().date()}", flush=True)
    # the stock system: change in account value
    for c in eq.columns:
        if c.startswith("200% | Rank by signal-day volume surge") or c.startswith("100% | Rank by signal-day volume surge") or c.startswith("200% | Base rule"):
            D["Stock system: " + c.replace(" | ", " cap, ").replace("Rank by signal-day volume surge", "ranked by volume surge").replace("Base rule (random pick)", "base rule")] = eq[c].diff().fillna(eq[c].iloc[0] - CAPITAL)
    # same-day alignment note: equity_daily starts at the first date with 300,000 + cumulative pnl
    yrs = D.groupby(D.index.year).sum() / CAPITAL * 100
    yrs.round(1).to_csv(out_dir / "benchmarks_yearly.csv")
    periods = {"whole 2000 to Aug 2021": (idx.min(), idx.max()), "2000 to 2007": (idx.min(), pd.Timestamp("2007-12-31")), "2008 to Aug 2021": (pd.Timestamp("2008-01-01"), idx.max())}
    rows = []
    for pn, (lo, hi) in periods.items():
        for c in D.columns:
            u = D.loc[lo:hi, c].to_numpy(); e = np.r_[CAPITAL, CAPITAL + np.cumsum(u)]; pk = np.maximum.accumulate(e); r = u / CAPITAL
            y = D.loc[lo:hi, c].groupby(D.loc[lo:hi].index.year).sum() / CAPITAL * 100
            rows.append(dict(period=pn, system=c, profit_per_year_pct=(e[-1] - CAPITAL) / CAPITAL * 100 / (len(u) / 252.0), sharpe=r.mean() / r.std() * np.sqrt(252), max_drawdown_pct=((e - pk) / pk).min() * 100, worst_year_pct=y.min(), invested_pct_of_sessions=np.nan))
    S = pd.DataFrame(rows); S.to_csv(out_dir / "benchmarks_summary.csv", index=False)
    pd.set_option("display.width", 320); pd.set_option("display.max_colwidth", 80); pd.set_option("display.max_columns", 30)
    for pn in periods:
        print(f"\n==== {pn} ====")
        print(S[S.period == pn].drop(columns=["period", "invested_pct_of_sessions"]).round(2).to_string(index=False))
    print("\n==== profit by calendar year, % of $300,000 ====")
    v = yrs.copy(); v.columns = [c[:44] for c in v.columns]
    print(v.round(1).to_string())
    cum = CAPITAL + D.cumsum()
    fig, axs = plt.subplots(2, 1, figsize=(13, 9), sharex=True, gridspec_kw={"height_ratios": [3, 1.3]})
    cols = list(cum.columns)
    pal = ["#9aa5b1", "#c8cfd6", "#d9822b", "#e9b872", "#1f3a5f", "#5b7fb5", "#2a9d8f", "#7fc8be"]
    for c, col in zip(cols, pal * 2):
        stock = c.startswith("Stock")
        axs[0].plot(cum.index, cum[c] / 1000, color=col, lw=2.4 if stock else 1.3, label=c)
        axs[1].plot(cum.index, (cum[c] / cum[c].cummax() - 1) * 100, color=col, lw=1.0)
    axs[0].set_ylabel("Account value, $ thousands (fixed $300,000)"); axs[1].set_ylabel("Drawdown, %"); axs[0].grid(alpha=0.25); axs[1].grid(alpha=0.25)
    axs[0].legend(fontsize=8, loc="upper left"); axs[0].set_title("Stock system vs SPY and QQQ (buy and hold, and long only above the 200-day average), 2000 to Aug 2021")
    fig.tight_layout(); fig.savefig(out_dir / "benchmarks_chart.png", dpi=130)
    print("done")


if __name__ == "__main__":
    main()
