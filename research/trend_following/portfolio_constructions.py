"""Drawdown of whole-contract and ETF portfolio constructions, from the committed development-years daily pnl of the primary baseline.

Usage: python portfolio_constructions.py RESULTS_DIR      (reads primary_daily_pnl_by_market_ref_budget.csv.gz, micro_first_list_v3.csv, etf_standins_all.csv)
No price data and no sealed years are read. Each market's daily pnl was produced at a position volatility of 0.10 percent of the account; a market sized to
a different volatility is that series multiplied by (its volatility / 0.10), exact because sizing is on the fixed starting account.
'One contract' means the market is sized to today's one-contract percent volatility (micro_first_list_v3.csv). 'Days in trade' is days with non-zero pnl.
ETF cash = ETF dollars for the chosen budget, counted only on days the market is in trade. Resampled drawdown = 95th percentile of 1,500 block-resampled
paths (20-session blocks, same length as the sample), seed fixed.
"""
import sys
import numpy as np
import pandas as pd

d = sys.argv[1]
M = pd.read_csv(f"{d}/primary_daily_pnl_by_market_ref_budget.csv.gz", index_col=0, parse_dates=True)
L = pd.read_csv(f"{d}/micro_first_list_v3.csv").set_index("price_symbol")
E = pd.read_csv(f"{d}/etf_standins_all.csv")
E = E[E["note"].isna()].drop_duplicates("futures", keep="first").set_index("futures")
nat = L.loc[M.columns, "percent_volatility"]
A = M != 0
yrs = len(M) / 252
rng = np.random.default_rng(7)
CAP = 0.25


def mdd(x):
    c = np.cumsum(np.r_[0, x])
    return (np.maximum.accumulate(c) - c).max()


def boot95(daily, nb=1500, blk=20):
    n = len(daily)
    idx = np.empty((nb, n), dtype=np.int64)
    idx[:, 0] = rng.integers(0, n, nb)
    rs, fr = rng.random((nb, n)) < 1 / blk, rng.integers(0, n, (nb, n))
    for t in range(1, n):
        idx[:, t] = np.where(rs[:, t], fr[:, t], (idx[:, t - 1] + 1) % n)
    p = np.cumsum(np.concatenate([np.zeros((nb, 1)), daily[idx]], axis=1), axis=1)
    return np.percentile((np.maximum.accumulate(p, axis=1) - p).max(axis=1), 95)


def report(name, scale, etf_cash=None):
    day = (M * scale).sum(axis=1).to_numpy()
    h, b = mdd(day), boot95(day)
    out = dict(construction=name, markets=int((scale > 0).sum()), annual_pnl=round(day.sum() / yrs), annual_pnl_pct=round(100 * day.sum() / yrs / 3e5, 1),
               historical_max_dd=round(h), historical_max_dd_pct=round(100 * h / 3e5, 1), resampled_95th_dd=round(b), resampled_95th_dd_pct=round(100 * b / 3e5, 1),
               sharpe=round(day.mean() / day.std() * np.sqrt(252), 2))
    if etf_cash is not None:
        c = (A * etf_cash).sum(axis=1)
        out.update(etf_cash_mean=round(c.mean()), etf_cash_95th_pct_of_days=round(c.quantile(.95)), etf_cash_peak=round(c.max()))
    return out


rows = [report("one contract of every market (today's size), all 68", nat / 0.10)]
small = (nat <= CAP).astype(float)
rows.append(report(f"one contract, only the {int(small.sum())} markets at or below {CAP} percent; the rest dropped", small * nat / 0.10))
has = pd.Series([s in E.index for s in M.columns], index=M.columns)
for b in (0.10, 0.15, 0.20):
    sc = small * nat / 0.10 + ((nat > CAP) & has).astype(float) * (b / 0.10)
    cash = pd.Series({s: (E.loc[s, "dollars_for_1pct"] * b if (nat[s] > CAP and has[s]) else 0.0) for s in M.columns})
    rows.append(report(f"at or below {CAP}: one contract; above {CAP} with an ETF: budget {b} percent each (no-ETF markets dropped)", sc, cash))
for b in (0.10, 0.15, 0.195):
    rows.append(report(f"equal budget {b} percent per market, all 68, fractional", pd.Series(b / 0.10, index=M.columns)))
r = pd.DataFrame(rows)
r.to_csv(f"{d}/portfolio_constructions.csv", index=False)
pd.set_option("display.width", 300, "display.max_columns", 30, "display.max_colwidth", 100)
print(r.to_string(index=False))
print("\nabove the cap:", ", ".join(nat[nat > CAP].index))
print("above the cap with no ETF in the archive or no candidate:", ", ".join(s for s in nat[nat > CAP].index if s not in E.index))
