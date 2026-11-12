"""Final checks on the efficiency-ratio trend system, DEVELOPMENT YEARS ONLY (2007-12-31 to 2021-08-06; sealed years cut at load).

Usage: python trend_final_checks.py futures_prices.parquet trend_universe.csv market_list.csv OUT_DIR

The trading engine is NOT rewritten here. This script loads the first part of trend_exit_tests.py (everything before its list of systems:
price loading, unit repair, the Kaufman ratio, run_market2, max_dd, sharpe_of) and runs it unchanged, so the first rows reproduce Entry 106.

System in every row (a complete system): Kaufman efficiency ratio on closes only, 20 sessions, entry at 0.60 or above, direction = sign of the 20-session
close change, enter at the next open, initial stop 4 ATR, ATR trailing stop from the best close (4, 5, 6 or 8 ATR), NO time stop, no minimum movement,
re-entry allowed at once (the Entry 106 baseline), one ATR of each position = 0.10 percent of the 300,000 account, cost 0.05 ATR per side.

Questions answered:
1. The same book with and without fed funds (ZQ), and without all five short-rate markets (ZQ, SR1, SR3, ER, SO3): return, Sharpe, drawdown, trades.
2. Is the best-system claim robust: block-bootstrap interval for the Sharpe ratio of each trailing stop (are 0.77 to 0.80 distinguishable?).
3. Year by year inside the development years: percent of the account earned in each calendar year, worst drop inside each year, trades entered,
   how many years were positive, how much profit comes from the single best year, and which market groups earned it.
4. Budget per market that keeps the drawdown at 100,000 (historical maximum, and the 95th percentile of 2,000 block-resampled paths, 20-session blocks,
   the same method as Entry 104), with the profit that budget would have earned. Everything scales in proportion to the budget.
"""
import os
import sys
import time
import numpy as np
import pandas as pd

_here = os.path.dirname(os.path.abspath(__file__))
_src = open(os.path.join(_here, "trend_exit_tests.py")).read()
_engine = _src.split("systems = []")[0]
exec(compile(_engine, "trend_exit_tests.py (engine part, unchanged)", "exec"))

TRAILS = [4.0, 5.0, 6.0, 8.0]
UNIVERSES = {
    "all 51 markets": [],
    "without fed funds": ["ZQ"],
    "without all five short-rate markets": list(SHORT),
}
TARGET_DD = 100_000
risk = REF / 100 * ACCOUNT
years_total = NCAL / 252
cal_year = np.asarray(calendar.year).copy()
cal_year[cal_year == 2007] = 2008   # one session in 2007 (2007-12-31): counted with 2008
YEARS = sorted(set(cal_year.tolist()))
syms = list(mk.keys())

# ---- run every market once per trailing stop, keep daily profit, in-trade flags and trades
store = {}
t1 = time.time()
for trail in TRAILS:
    p = dict(er_min=0.60, init_atr=4.0, trail_atr=trail)
    pnl, pos, trades = {}, {}, {}
    for sym, m in mk.items():
        pl, ip, k, rs, trs = run_market2(m, p, risk, True)
        s = np.zeros(NCAL)
        a = np.zeros(NCAL)
        s[m.idx] = pl
        a[m.idx] = ip
        pnl[sym], pos[sym] = s, a
        trades[sym] = [dict(entry_year=int(cal_year[m.idx[t[2]]]), sessions=t[3] - t[2] + 1, pnl=t[8], reason=t[9]) for t in trs]
    store[trail] = dict(pnl=pnl, pos=pos, trades=trades)
print(f"ran {len(TRAILS)} trailing stops x {len(mk)} markets in {time.time() - t1:.0f} seconds")


def book(trail, drop):
    d = store[trail]
    keep = [s for s in syms if s not in drop]
    tot = np.sum([d["pnl"][s] for s in keep], axis=0)
    act = np.sum([d["pos"][s] for s in keep], axis=0)
    trs = [t for s in keep for t in d["trades"][s]]
    return tot, act, trs, keep


# ---- block bootstrap indices (same method as Entry 104: 2,000 paths, 20-session blocks)
NB, BLK = 2000, 20
idx = np.empty((NB, NCAL), dtype=np.int64)
idx[:, 0] = rng.integers(0, NCAL, NB)
restart = rng.random((NB, NCAL)) < 1 / BLK
fresh = rng.integers(0, NCAL, (NB, NCAL))
for t in range(1, NCAL):
    idx[:, t] = np.where(restart[:, t], fresh[:, t], (idx[:, t - 1] + 1) % NCAL)


def boot(tot):
    x = tot[idx]
    sd = x.std(axis=1) * np.sqrt(252)
    sh = np.where(sd > 0, x.mean(axis=1) * 252 / sd, np.nan)
    paths = np.cumsum(np.concatenate([np.zeros((NB, 1)), x], axis=1), axis=1)
    dd = (np.maximum.accumulate(paths, axis=1) - paths).max(axis=1)
    return sh, dd


summary, yearly, sizing, groups, marketrows = [], [], [], [], []
for trail in TRAILS:
    for uname, drop in UNIVERSES.items():
        tot, act, trs, keep = book(trail, drop)
        total = tot.sum()
        ann = total / years_total
        dd = max_dd(tot)
        sh_boot, dd_boot = boot(tot)
        by_year = {y: tot[cal_year == y].sum() for y in YEARS}
        best_year = max(by_year, key=by_year.get)
        pos_years = sum(1 for v in by_year.values() if v > 0)
        n_tr = len(trs)
        zq_trades = len(store[trail]["trades"]["ZQ"]) if "ZQ" in keep else 0
        zq_share = 100 * store[trail]["pnl"]["ZQ"].sum() / total if ("ZQ" in keep and total) else 0.0
        short_share = 100 * sum(store[trail]["pnl"][s].sum() for s in SHORT if s in keep) / total if total else np.nan
        q95 = float(np.percentile(dd_boot, 95))
        summary.append(dict(
            trailing_stop_atr=trail, markets=uname, number_of_markets=len(keep),
            annual_pct=100 * ann / ACCOUNT, sharpe=sharpe_of(tot), sharpe_lower_5pct=float(np.nanpercentile(sh_boot, 5)),
            sharpe_upper_95pct=float(np.nanpercentile(sh_boot, 95)), max_drawdown_pct=100 * dd / ACCOUNT,
            resampled_95th_drawdown_pct=100 * q95 / ACCOUNT, annual_over_drawdown=ann / dd if dd > 0 else np.nan,
            trades=n_tr, average_hold_sessions=act.sum() / n_tr if n_tr else np.nan, markets_in_trade_average=float(act.mean()),
            markets_in_trade_most=int(act.max()), sharpe_before_2015=sharpe_of(tot[first_half]), sharpe_2015_on=sharpe_of(tot[~first_half]),
            fed_funds_trades=zq_trades, fed_funds_share_pct=zq_share, short_rate_share_pct=short_share,
            positive_years=pos_years, years=len(YEARS), best_year=best_year, best_year_pct_of_account=100 * by_year[best_year] / ACCOUNT,
            best_year_share_of_total_profit_pct=100 * by_year[best_year] / total if total else np.nan,
            annual_pct_without_best_year=100 * (total - by_year[best_year]) / (years_total - 1) / ACCOUNT))
        # year by year
        for y in YEARS:
            mask = cal_year == y
            yearly.append(dict(trailing_stop_atr=trail, markets=uname, year=y, return_pct_of_account=100 * tot[mask].sum() / ACCOUNT,
                               worst_drop_inside_year_pct=100 * max_dd(tot[mask]) / ACCOUNT, trades_entered=sum(1 for t in trs if t["entry_year"] == y),
                               sessions=int(mask.sum())))
        # sizing to a drawdown of TARGET_DD
        for label, basis in (("historical maximum drawdown", dd), ("95th percentile of resampled drawdowns", q95)):
            budget = REF * TARGET_DD / basis
            k = budget / REF
            sizing.append(dict(trailing_stop_atr=trail, markets=uname, drawdown_basis=label, budget_percent_per_market=budget,
                               annual_profit_dollars=ann * k, annual_pct_of_account=100 * ann * k / ACCOUNT,
                               historical_max_drawdown_dollars=dd * k, resampled_95th_drawdown_dollars=q95 * k,
                               risk_budget_summed_over_markets_in_trade_average_pct=float(act.mean()) * budget,
                               risk_budget_summed_when_busiest_pct=float(act.max()) * budget))
        # profit by market group and by market
        gsum = {}
        for s in keep:
            gsum[group.get(s, "?")] = gsum.get(group.get(s, "?"), 0.0) + store[trail]["pnl"][s].sum()
            marketrows.append(dict(trailing_stop_atr=trail, markets=uname, symbol=s, group=group.get(s, "?"),
                                   profit_share_pct=100 * store[trail]["pnl"][s].sum() / total if total else np.nan,
                                   annual_pct_of_account=100 * store[trail]["pnl"][s].sum() / years_total / ACCOUNT,
                                   trades=len(store[trail]["trades"][s])))
        for g, v in gsum.items():
            groups.append(dict(trailing_stop_atr=trail, markets=uname, group=g, profit_share_pct=100 * v / total if total else np.nan,
                               annual_pct_of_account=100 * v / years_total / ACCOUNT))

S = pd.DataFrame(summary)
Y = pd.DataFrame(yearly)
Z = pd.DataFrame(sizing)
G = pd.DataFrame(groups)
M = pd.DataFrame(marketrows)
for name, df in (("final_checks_summary", S), ("final_checks_by_year", Y), ("final_checks_sizing", Z), ("final_checks_by_group", G), ("final_checks_by_market", M)):
    df.round(3).to_csv(f"{out_dir}/{name}.csv", index=False)

pd.set_option("display.width", 320, "display.max_rows", 600, "display.max_columns", 60, "display.max_colwidth", 60)
print("\n=== 1. with and without fed funds (and without all short-rate markets) ===")
print(S[["trailing_stop_atr", "markets", "annual_pct", "sharpe", "sharpe_lower_5pct", "sharpe_upper_95pct", "max_drawdown_pct", "resampled_95th_drawdown_pct",
         "annual_over_drawdown", "trades", "average_hold_sessions", "markets_in_trade_average", "sharpe_before_2015", "sharpe_2015_on",
         "fed_funds_trades", "fed_funds_share_pct", "short_rate_share_pct"]].round(2).to_string(index=False))
print("\n=== 2. year by year: percent of the 300,000 account earned (0.10 percent budget per market) ===")
for trail in (5.0, 8.0):
    sub = Y[Y["trailing_stop_atr"] == trail]
    pv = sub.pivot(index="year", columns="markets", values="return_pct_of_account")
    pdd = sub.pivot(index="year", columns="markets", values="worst_drop_inside_year_pct")
    ptr = sub.pivot(index="year", columns="markets", values="trades_entered")
    print(f"\n--- {trail:g} ATR trailing stop: return of the account in the year (percent) ---")
    print(pv.round(2).to_string())
    print(f"--- {trail:g} ATR trailing stop: worst drop inside the year (percent of account) ---")
    print(pdd.round(2).to_string())
    print(f"--- {trail:g} ATR trailing stop: trades entered in the year ---")
    print(ptr.to_string())
print("(2008 includes the one session of 2007-12-31; 2021 ends 2021-08-06, so it is a partial year)")
print("\n=== 2b. concentration across years ===")
print(S[["trailing_stop_atr", "markets", "positive_years", "years", "best_year", "best_year_pct_of_account", "best_year_share_of_total_profit_pct",
         "annual_pct", "annual_pct_without_best_year"]].round(2).to_string(index=False))
print("\n=== 3. profit by market group (percent of the book's total profit) ===")
for trail in (5.0, 8.0):
    sub = G[G["trailing_stop_atr"] == trail]
    print(f"\n--- {trail:g} ATR trailing stop ---")
    print(sub.pivot(index="group", columns="markets", values="profit_share_pct").round(1).to_string())
print("\n=== 3b. five largest markets by profit share ===")
for trail in (5.0, 8.0):
    for uname in UNIVERSES:
        sub = M[(M["trailing_stop_atr"] == trail) & (M["markets"] == uname)].sort_values("profit_share_pct", ascending=False).head(5)
        print(f"{trail:g} ATR, {uname}: " + "; ".join(f"{r.symbol} {r.profit_share_pct:.1f}%" for r in sub.itertuples()))
print(f"\n=== 4. budget per market that holds the drawdown at {TARGET_DD:,} ===")
print(Z.round(3).to_string(index=False))
print(f"\nDONE in {time.time() - t0:.0f} seconds")
