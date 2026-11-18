"""Stocks, long only: daily account, year-by-year profit and equity chart for the base rule and four candidates (Michael, 18 Nov 2026).
Usage: python er_stocks_equity.py stock_prices.parquet OUT_DIR spy_prices.parquet nasdaq_etfs.parquet
Rows: base rule (reference pick, as in the hand-off), ranking by signal-day volume surge, gate of up-day/down-day dollar volume at least 2, graded cap by Nasdaq lead (60 sessions), SPY buy and hold on the same $300,000.
Fixed $300,000 account (no compounding): year profit = profit in dollars / $300,000. Caps 200% and 100%. In-sample only (data through 2021-08-06); 2021 is a partial year. No borrowing charge is included.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import er_stocks as B
import er_stocks_common_momentum as M
import er_stocks_ideas_1_2_6 as I1
import er_stocks_many_ideas as MI
import er_stocks_nasdaq_volume as NV
from er_stocks import CAPITAL, END, EPOCH


def main():
    prices_path, out_dir, spy_path, etf_path = sys.argv[1], Path(sys.argv[2]), sys.argv[3], sys.argv[4]
    out_dir.mkdir(parents=True, exist_ok=True)
    ctx, names, live, E20, dates, spy_close, mk200 = MI.setup(prices_path, spy_path)
    SEG, dropped, cal, (dates, _, WIN) = ctx
    MI.check_baseline(ctx, mk200)
    FEAT = NV.build_features(ctx, E20)
    Q = NV.qqq_series(etf_path, cal); qs, ss = pd.Series(Q), pd.Series(spy_close)
    lead = ((qs / qs.shift(60)) - (ss / ss.shift(60))).to_numpy() > 0
    base = MI.gen(ctx, mk200)
    n = len(base["d"]); sym, t = I1.trade_rows(SEG, base)
    ref_key = np.random.default_rng(MI.SEED).random(n)
    surge = np.array([FEAT[(sym[k], t[k])]["s20_sig"] for k in range(n)], float)
    tiny = np.random.default_rng(20261118).random(n) * 1e-9
    surge_key = -np.where(np.isfinite(surge), surge, -1e9) + tiny
    Rud = MI.gen(ctx, mk200, cond=NV.gate(FEAT, "udd_sig", lambda v: v >= 2.0))
    ud_key = np.random.default_rng(MI.SEED).random(len(Rud["d"]))
    lo = pd.Timestamp("2000-01-01"); sel = np.asarray((dates >= lo) & (dates <= END)); idx = dates[sel]
    daily = {}
    for cap in (2.0, 1.0):
        tag = f"{int(cap*100)}%"
        runs = {
            "Base rule (random pick)": MI.portfolio_gen(base, cal, cap, ref_key),
            "Rank by signal-day volume surge": MI.portfolio_gen(base, cal, cap, surge_key),
            "Gate: up/down dollar volume at least 2": MI.portfolio_gen(Rud, cal, cap, ud_key),
            "Graded cap by Nasdaq lead (60 sessions)": MI.portfolio_gen(base, cal, cap, ref_key, cap_t=np.where(lead, cap, cap * 0.5)),
        }
        for k, P in runs.items():
            daily[(tag, k)] = pd.Series(P["pnl"][sel], index=idx)
    sp = spy_close[sel]; spr = np.r_[0.0, sp[1:] / sp[:-1] - 1.0]
    spy_pnl = pd.Series(np.nan_to_num(spr) * CAPITAL, index=idx)
    D = pd.DataFrame(daily); D[("SPY", "SPY buy and hold ($300,000)")] = spy_pnl
    eq = CAPITAL + D.cumsum()
    eq.columns = [f"{a} | {b}" for a, b in eq.columns]; eq.to_csv(out_dir / "equity_daily.csv", float_format="%.0f")
    yrs = D.groupby(D.index.year).sum() / CAPITAL * 100
    yrs.columns = [f"{a} | {b}" for a, b in yrs.columns]; yrs.round(1).to_csv(out_dir / "yearly_returns.csv")
    pd.set_option("display.width", 320); pd.set_option("display.max_columns", 40); pd.set_option("display.max_colwidth", 60)
    for cap in ("200%", "100%"):
        cols = [c for c in yrs.columns if c.startswith(cap)] + ["SPY | SPY buy and hold ($300,000)"]
        v = yrs[cols].copy(); v.columns = [c.split(" | ")[1] for c in cols]
        print(f"\n==== profit by calendar year, % of $300,000 | cap {cap} (2021 is Jan to 6 Aug) ====")
        print(v.round(1).to_string())
    summ = []
    for c in D.columns:
        u = D[c].to_numpy(); e = np.r_[CAPITAL, CAPITAL + np.cumsum(u)]; pk = np.maximum.accumulate(e); r = u / CAPITAL
        summ.append(dict(series=" | ".join(c), profit_per_year_pct=(e[-1] - CAPITAL) / CAPITAL * 100 / (len(u) / 252.0), sharpe=r.mean() / r.std() * np.sqrt(252), max_drawdown_pct=((e - pk) / pk).min() * 100, worst_year_pct=yrs[" | ".join(c)].min(), final_equity=e[-1]))
    S = pd.DataFrame(summ); S.to_csv(out_dir / "summary.csv", index=False); print("\n", S.round(2).to_string(index=False))
    fig, axs = plt.subplots(2, 2, figsize=(15, 9), sharex="col", gridspec_kw={"height_ratios": [3, 1.2]})
    colors = ["#1f3a5f", "#d9822b", "#2a9d8f", "#9b5de5", "#888888"]
    for j, cap in enumerate(("200%", "100%")):
        cols = [c for c in eq.columns if c.startswith(cap)] + ["SPY | SPY buy and hold ($300,000)"]
        for c, col in zip(cols, colors):
            lab = c.split(" | ")[1]; ls = "--" if lab.startswith("SPY") else "-"
            axs[0, j].plot(eq.index, eq[c] / 1000, color=col, lw=2.2 if lab.startswith("Base") else 1.4, ls=ls, label=lab)
            axs[1, j].plot(eq.index, (eq[c] / eq[c].cummax() - 1) * 100, color=col, lw=1.0, ls=ls)
        axs[0, j].set_title(f"Account value on a fixed $300,000, cap {cap} (no compounding, no borrowing charge)")
        axs[0, j].set_ylabel("Account value, $ thousands"); axs[1, j].set_ylabel("Drawdown from peak, %")
        axs[0, j].grid(alpha=0.25); axs[1, j].grid(alpha=0.25)
    axs[0, 0].legend(loc="upper left", fontsize=9)
    fig.suptitle("Stocks trend rule, in-sample 2000 to 6 Aug 2021 (post hoc)")
    fig.tight_layout(); fig.savefig(out_dir / "equity_chart.png", dpi=130)
    print("done")


if __name__ == "__main__":
    main()
