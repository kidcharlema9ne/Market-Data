"""Side-by-side quality statistics: stock system (base rule and volume-surge ranking, caps 200% and 100%) vs SPY and QQQ (buy and hold, and long only above their own 200-day average) at 100% and 200% exposure.
Usage: python er_stocks_metrics.py unused spy_prices.parquet nasdaq_etfs.parquet OUT_DIR EQUITY_DAILY_CSV
Same basis for every row: fixed $300,000 account, no compounding; ETF rows are real one-time share purchases (bought once at each entry, never re-sized while held); idle cash earns nothing, no trading costs on the ETF rows and NO financing charge on borrowed money for any row (the stock rows have none either). 200% exposure = twice $300,000 held in the ETF.
200-day rule: long only if the ETF's close two sessions back was above its 200-day average (one-day delay). In-sample 2000-01-03 to 2021-08-06, post hoc.
Drawdown (dollar basis) = dollars below the account's highest value so far, as a percent of the starting $300,000 (so account growth does not shrink it). Ulcer index = square root of the average squared dollar-basis drawdown over all sessions.
"""
import sys
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

CAP = 300000.0
EPOCH = pd.Timestamp("1970-01-01")


def load(path, sym=None):
    df = pd.read_parquet(path)
    if sym is not None:
        df = df[df.symbol == sym]
    df = df.sort_values("date_i").drop_duplicates("date_i")
    return pd.Series(df["close"].to_numpy(float), index=EPOCH + pd.to_timedelta(df["date_i"].to_numpy(), unit="D"))


def hold_pnl(P, pos, lev):
    """Shares are bought ONCE when the position turns on, with lev x $300,000 at that close, and held (no daily re-sizing) until it turns off; daily profit = shares x price change. A one-time purchase cannot lose more than 100% at lev 1."""
    out = np.zeros(len(P)); sh = 0.0
    for d in range(1, len(P)):
        if pos[d] > 0 and pos[d - 1] <= 0:
            sh = lev * CAP / P[d - 1]
        if pos[d] > 0:
            out[d] = sh * (P[d] - P[d - 1])
    return out


def metrics(u, idx):
    u = np.asarray(u, float); e = np.r_[CAP, CAP + np.cumsum(u)]; r = u / CAP
    pk = np.maximum.accumulate(e); dd_pct_peak = (e - pk) / pk * 100
    dd_dollar = (pk - e) / CAP * 100                                   # % of starting capital
    yrs = pd.Series(u, index=idx).groupby(idx.year).sum() / CAP * 100
    under = 0; longest = 0
    for fl in (e[1:] < pk[1:]):
        under = under + 1 if fl else 0; longest = max(longest, under)
    ppy = (e[-1] - CAP) / CAP * 100 / (len(u) / 252.0)
    down = np.sqrt(np.mean(np.minimum(r, 0.0) ** 2)); ulcer = np.sqrt(np.mean(dd_dollar[1:] ** 2))
    return {"profit per year %": ppy, "Sharpe": r.mean() / r.std() * np.sqrt(252), "Sortino": r.mean() / down * np.sqrt(252) if down > 0 else np.nan,
            "max drawdown % (of running peak)": dd_pct_peak.min(), "max drawdown % of starting $300k (dollars)": dd_dollar.max(), "profit per year / dollar drawdown": ppy / dd_dollar.max() if dd_dollar.max() > 0 else np.nan,
            "ulcer index": ulcer, "profit per year / ulcer": ppy / ulcer if ulcer > 0 else np.nan, "longest time under water (years)": longest / 252.0,
            "worst year %": yrs.min(), "positive years": f"{int((yrs > 0).sum())} of {len(yrs)}", "final account $": e[-1]}


def main():
    spy_path, etf_path, out_dir, eq_csv = sys.argv[2], sys.argv[3], Path(sys.argv[4]), sys.argv[5]
    out_dir.mkdir(parents=True, exist_ok=True)
    eq = pd.read_csv(eq_csv, index_col=0, parse_dates=True); idx = eq.index
    spy = load(spy_path); qqq = load(etf_path, "QQQ")
    D = {}
    for c in eq.columns:
        if "SPY" in c or "Rank by" not in c and "Base rule" not in c:
            continue
        cap, nm = c.split(" | ")
        lab = ("Stock system, " + ("volume-surge ranking" if "Rank by" in nm else "base rule")) + f", cap {cap}"
        D[lab] = eq[c].diff().fillna(eq[c].iloc[0] - CAP)
    for name, s in (("SPY", spy), ("QQQ", qqq)):
        full = s.reindex(s.index.union(idx)).ffill(); sma = full.rolling(200, min_periods=200).mean()
        on = (full > sma).astype(float).where(sma.notna(), 0.0).shift(2).fillna(0.0).reindex(idx).to_numpy()
        px = full.reindex(idx).to_numpy()
        for lev, tag in ((1.0, "100%"), (2.0, "200%")):
            D[f"{name} buy and hold, {tag}"] = hold_pnl(px, np.r_[0.0, np.ones(len(px) - 1)], lev)
            D[f"{name} above 200-day else flat, {tag}"] = hold_pnl(px, on, lev)
    D = pd.DataFrame(D, index=idx)
    order = [c for c in D.columns if c.startswith("Stock")] + [c for c in D.columns if "200-day" in c and c.endswith("200%")] + [c for c in D.columns if "200-day" in c and c.endswith("100%")] + [c for c in D.columns if "buy and hold" in c and c.endswith("200%")] + [c for c in D.columns if "buy and hold" in c and c.endswith("100%")]
    D = D[order]
    T = pd.DataFrame({c: metrics(D[c].to_numpy(), idx) for c in D.columns}).T
    T.to_csv(out_dir / "metrics_table.csv", float_format="%.3f")
    pd.set_option("display.width", 340); pd.set_option("display.max_columns", 30); pd.set_option("display.max_colwidth", 60)
    num = T.drop(columns=["positive years"]).astype(float).round(2); num["positive years"] = T["positive years"]
    print("==== whole 2000 to Aug 2021 ====")
    print(num.to_string())
    per = {"2000 to 2007": (idx.min(), pd.Timestamp("2007-12-31")), "2008 to Aug 2021": (pd.Timestamp("2008-01-01"), idx.max())}
    rows = {}
    for pn, (lo, hi) in per.items():
        sub = D.loc[lo:hi]; rows[pn] = {c: metrics(sub[c].to_numpy(), sub.index)["Sharpe"] for c in D.columns}; rows[pn + " Sortino"] = {c: metrics(sub[c].to_numpy(), sub.index)["Sortino"] for c in D.columns}
    P = pd.DataFrame(rows); P.columns = ["Sharpe 2000-07", "Sortino 2000-07", "Sharpe 2008-21", "Sortino 2008-21"] if False else list(P.columns)
    P.to_csv(out_dir / "metrics_by_period.csv", float_format="%.3f"); print("\n==== Sharpe and Sortino by period ===="); print(P.round(2).to_string())
    cum = CAP + D.cumsum()
    fig, axs = plt.subplots(2, 1, figsize=(13, 9), sharex=True, gridspec_kw={"height_ratios": [3, 1.3]})
    show = [c for c in D.columns if c.startswith("Stock") and "200%" in c] + [c for c in D.columns if c.endswith("200%")]
    pal = ["#9aa5b1", "#1f3a5f", "#d9822b", "#2a9d8f", "#c8cfd6", "#9b5de5", "#e9b872", "#5b7fb5"]
    for c, col in zip(show, pal):
        st = c.startswith("Stock"); axs[0].plot(cum.index, cum[c] / 1000, color=col, lw=2.4 if st else 1.3, label=c)
        axs[1].plot(cum.index, (cum[c].cummax() - cum[c]) / CAP * -100, color=col, lw=1.0)
    axs[0].set_ylabel("Account value, $ thousands"); axs[1].set_ylabel("Below peak, % of $300,000"); axs[0].grid(alpha=0.25); axs[1].grid(alpha=0.25); axs[0].legend(fontsize=8, loc="upper left")
    axs[0].set_title("Stock system vs SPY and QQQ, all at 200% exposure (no financing charge), 2000 to Aug 2021")
    fig.tight_layout(); fig.savefig(out_dir / "metrics_chart.png", dpi=130); print("done")


if __name__ == "__main__":
    main()
