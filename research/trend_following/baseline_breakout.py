"""Baseline breakout trend system on the micro-first list, DEVELOPMENT YEARS ONLY, sized so that one position carries a fixed volatility budget.

Usage: python baseline_breakout.py futures_prices.parquet trend_universe.csv micro_first_list_v3.csv OUT_DIR [ACCOUNT]

SEALED YEARS: prices dated after 2021-08-06 are removed the moment the file is read (development window 2007-12-31 to 2021-08-06; the
sealed window starts 2021-11-08 with a three-month purge between). Nothing from the sealed years is used anywhere in this script.

THE RULE (declared before any result was seen; the numbers in it come from Michael's description, the rest are my assumptions)
- Trend quality: efficiency ratio over 20 sessions = |close now - close 20 sessions ago| / sum of the 20 daily absolute close changes.
  1.0 means a straight line, 0 means pure back and forth. Michael: "roughly 0.6". Entry needs at least 0.6 (a reference run with no filter is also shown).
- Entry: at the close, today's close is above the highest close of the previous N sessions (long) or below the lowest close of the previous N
  sessions (short), AND the efficiency ratio is at least 0.6. The trade is entered at the NEXT session's open. N = 20 and N = 55 are both run.
- Initial stop: 3 x the 20-day average true range (ATR) measured on the signal day, from the entry price. If a session's range touches the stop,
  the exit is at the stop, or at the open if the market gaps through it (so gap losses are bigger than 3 ATR).
- Exit, two versions: (a) trailing stop: 3 ATR below the highest close since entry for a long (above the lowest close for a short), recomputed each
  close with the current 20-day ATR, only ever moved in the trade's favour; (b) the earlier version: fixed 3 ATR stop plus a 60-session time exit at the close.
- One position per market, no pyramiding, no reversal (a market must be flat before a new entry).
- Size: shares are set at entry so that the 20-day ATR of the position is exactly a fixed dollar amount = budget percent x account. Reference budget
  0.10 percent of 300,000 = 300 dollars per ATR. Sizing is on the starting account (no compounding), so profit and drawdown in dollars scale in exact
  proportion to the budget; the scaling table below uses that. Fractional contracts (no rounding to whole contracts).
- Costs: 0.05 ATR per side (entry and exit) as a stand-in for slippage and commission. Declared, not measured.
- History for micro contracts that only started in 2019 (MES, MNQ, M2K, MGC, MCL, SIL, MYM, FDXS): the long-history full-size contract in the same market family
  is used for the price path (same percent moves). Mapping is printed.
- PRIMARY (chosen before running): 20-session breakout, efficiency ratio at least 0.6, trailing 3 ATR stop. The other combinations are sensitivities,
  not a search for the best.
Percent returns come from ratio back-adjusted prices; currency moves on foreign contracts are not modelled (positions are treated as dollar exposures).
"""
import sys
import numpy as np
import pandas as pd

prices_path, uni_path, list_path, out_dir = sys.argv[1:5]
ACCOUNT = float(sys.argv[5]) if len(sys.argv) > 5 else 300_000.0
DEV_START, DEV_END = pd.Timestamp("2007-12-31"), pd.Timestamp("2021-08-06")
REF_BUDGET = 0.10  # percent of the account per ATR of one position
STOP_ATR, COST_ATR, TIME_EXIT = 3.0, 0.05, 60
ER_MIN = 0.6
SCALE_GRID = [0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50, 0.75, 1.00]
rng = np.random.default_rng(20261112)

# ------------------------------------------------------------------ load, cut to development years immediately
px = pd.read_parquet(prices_path) if prices_path.endswith(".parquet") else pd.read_csv(prices_path)
px["file_date"] = pd.to_datetime(px["file_date"])
px = px[(px["file_date"] >= DEV_START) & (px["file_date"] <= DEV_END)].copy()
assert px["file_date"].max() <= DEV_END
print(f"development rows {len(px):,}; dates {px['file_date'].min().date()} to {px['file_date'].max().date()}; sealed years removed at load")

uni = pd.read_csv(uni_path)
fam = dict(zip(uni["price_symbol"], uni["family"]))
fam["MYM"] = fam.get("YM", "dow")
lst = pd.read_csv(list_path)
rows_by_sym = px.groupby("symbol").size().to_dict()

mapping = {}
for sym in lst["price_symbol"]:
    f = fam.get(sym)
    cands = [s for s, ff in fam.items() if ff == f and s in rows_by_sym and s != "MYM"]
    best = max(cands, key=lambda s: rows_by_sym[s]) if cands else None
    own = rows_by_sym.get(sym, 0)
    if best is None:
        mapping[sym] = None
    elif own >= 0.7 * rows_by_sym[best]:
        mapping[sym] = sym
    else:
        mapping[sym] = best
print("markets whose price path comes from a different, longer-history contract:",
      {k: v for k, v in mapping.items() if v != k})
print("markets with no development-year price data at all:", [k for k, v in mapping.items() if v is None])

# ------------------------------------------------------------------ per-market arrays
LOOKBACKS = (20, 55)


class Mkt:
    pass


mk = {}
for sym, src in mapping.items():
    if src is None:
        continue
    g = px[px["symbol"] == src].sort_values("file_date").drop_duplicates("file_date")
    g = g.dropna(subset=["close", "high", "low"])
    if len(g) < 150:
        print(f"  skipped {sym}: only {len(g)} development sessions")
        continue
    m = Mkt()
    m.sym, m.src = sym, src
    m.dates = g["file_date"].to_numpy()
    c = g["close"].to_numpy(float)
    o = g["open"].fillna(g["close"]).to_numpy(float)
    h, l = g["high"].to_numpy(float), g["low"].to_numpy(float)
    pc = np.r_[np.nan, c[:-1]]
    tr = np.maximum.reduce([h - l, np.abs(h - pc), np.abs(l - pc)])
    tr[0] = h[0] - l[0]
    cs = pd.Series(c)
    m.o, m.h, m.l, m.c = o, h, l, c
    m.atr = pd.Series(tr).rolling(20).mean().to_numpy()
    path = pd.Series(np.abs(np.diff(c, prepend=np.nan))).rolling(20).sum().to_numpy()
    m.er = np.abs(c - cs.shift(20).to_numpy()) / path
    m.hh = {N: cs.shift(1).rolling(N).max().to_numpy() for N in LOOKBACKS}
    m.ll = {N: cs.shift(1).rolling(N).min().to_numpy() for N in LOOKBACKS}
    mk[sym] = m
print(f"{len(mk)} markets in the test")
group = dict(zip(lst["price_symbol"], lst["group"]))
calendar = pd.DatetimeIndex(sorted(px["file_date"].unique()))
cal_pos = {d: i for i, d in enumerate(calendar)}


def run_market(m, N, exit_mode, er_min, risk_dollars, cost_atr):
    n = len(m.c)
    pnl = np.zeros(n)
    inpos = np.zeros(n, bool)
    trades = []
    side, pending, pend_atr = 0, 0, 0.0
    hh, ll = m.hh[N], m.ll[N]
    for i in range(n):
        if pending != 0:
            side, atr0 = pending, pend_atr
            entry = m.o[i]
            shares = risk_dollars / atr0
            stop = entry - side * STOP_ATR * atr0
            best, prev, start, tpnl = entry, entry, i, 0.0
            pending = 0
            c0 = -cost_atr * atr0 * shares
            pnl[i] += c0
            tpnl += c0
        if side != 0:
            inpos[i] = True
            hit = (m.l[i] <= stop) if side == 1 else (m.h[i] >= stop)
            if hit:
                if side == 1:
                    px_exit = stop if m.o[i] >= stop else m.o[i]
                else:
                    px_exit = stop if m.o[i] <= stop else m.o[i]
                d = shares * side * (px_exit - prev) - cost_atr * atr0 * shares
                pnl[i] += d
                tpnl += d
                trades.append((m.sym, side, start, i, shares, atr0, entry, px_exit, tpnl, "stop"))
                side = 0
            else:
                d = shares * side * (m.c[i] - prev)
                pnl[i] += d
                tpnl += d
                prev = m.c[i]
                if side == 1:
                    best = max(best, m.c[i])
                else:
                    best = min(best, m.c[i])
                if exit_mode == "trail" and not np.isnan(m.atr[i]):
                    new = best - side * STOP_ATR * m.atr[i]
                    stop = max(stop, new) if side == 1 else min(stop, new)
                if exit_mode == "time" and (i - start + 1) >= TIME_EXIT:
                    d = -cost_atr * atr0 * shares
                    pnl[i] += d
                    tpnl += d
                    trades.append((m.sym, side, start, i, shares, atr0, entry, m.c[i], tpnl, "time"))
                    side = 0
                elif i == n - 1:
                    d = -cost_atr * atr0 * shares
                    pnl[i] += d
                    tpnl += d
                    trades.append((m.sym, side, start, i, shares, atr0, entry, m.c[i], tpnl, "end of development window"))
                    side = 0
        if side == 0 and i < n - 1 and not (np.isnan(m.atr[i]) or np.isnan(m.er[i]) or np.isnan(hh[i])):
            if m.er[i] >= er_min:
                if m.c[i] > hh[i]:
                    pending, pend_atr = 1, m.atr[i]
                elif m.c[i] < ll[i]:
                    pending, pend_atr = -1, m.atr[i]
    return pnl, inpos, trades


def max_drawdown(daily):
    cum = np.cumsum(np.r_[0.0, daily])
    return float((np.maximum.accumulate(cum) - cum).max())


def run_variant(N, exit_mode, er_min, budget_pct=REF_BUDGET, cost_atr=COST_ATR):
    risk = budget_pct / 100 * ACCOUNT
    M, A, T = {}, {}, []
    for sym, m in mk.items():
        pnl, inpos, trades = run_market(m, N, exit_mode, er_min, risk, cost_atr)
        idx = [cal_pos[pd.Timestamp(d)] for d in m.dates]
        s = np.zeros(len(calendar))
        a = np.zeros(len(calendar))
        s[idx] = pnl
        a[idx] = inpos
        M[sym], A[sym] = s, a
        for t in trades:
            T.append(dict(symbol=t[0], side="long" if t[1] == 1 else "short", entry_date=pd.Timestamp(m.dates[t[2]]).date(),
                          exit_date=pd.Timestamp(m.dates[t[3]]).date(), sessions=t[3] - t[2] + 1, shares=t[4], atr_at_entry=t[5],
                          entry_price=t[6], exit_price=t[7], pnl_dollars=t[8], pnl_in_atr=t[8] / (t[4] * t[5]), exit_reason=t[9]))
    return pd.DataFrame(M, index=calendar), pd.DataFrame(A, index=calendar), pd.DataFrame(T)


def summarize(M, A, T, label):
    tot = M.sum(axis=1).to_numpy()
    yrs = len(M) / 252
    dd = max_drawdown(tot)
    active = A.sum(axis=1)
    ann = tot.sum() / yrs
    sd = tot.std() * np.sqrt(252)
    wins = T["pnl_dollars"] > 0 if len(T) else pd.Series(dtype=bool)
    return dict(variant=label, trades=len(T), win_rate=float(wins.mean()) if len(T) else np.nan,
                avg_trade_atr=float(T["pnl_in_atr"].mean()) if len(T) else np.nan,
                avg_winner_atr=float(T.loc[wins, "pnl_in_atr"].mean()) if wins.any() else np.nan,
                avg_loser_atr=float(T.loc[~wins, "pnl_in_atr"].mean()) if (~wins).any() else np.nan,
                avg_sessions=float(T["sessions"].mean()) if len(T) else np.nan,
                total_pnl=tot.sum(), annual_pnl=ann, annual_pnl_pct_of_account=100 * ann / ACCOUNT,
                annual_vol=sd, sharpe=ann / sd if sd > 0 else np.nan, max_drawdown_dollars=dd,
                max_drawdown_pct_of_account=100 * dd / ACCOUNT, annual_pnl_over_max_drawdown=ann / dd if dd > 0 else np.nan,
                worst_day=tot.min(), worst_20_sessions=float(pd.Series(tot).rolling(20).sum().min()),
                mean_markets_in_trade=float(active.mean()), max_markets_in_trade=int(active.max()),
                mean_summed_budget_pct=float(active.mean() * REF_BUDGET), max_summed_budget_pct=float(active.max() * REF_BUDGET))


pd.set_option("display.width", 250, "display.max_rows", 500, "display.max_columns", 40)
# ------------------------------------------------------------------ all variants at the reference budget
results, store = [], {}
for N in LOOKBACKS:
    for exit_mode in ("trail", "time"):
        for er_min, ername in ((ER_MIN, "efficiency ratio >= 0.6"), (0.0, "no efficiency filter")):
            label = f"{N}-session breakout | {'trailing 3 ATR stop' if exit_mode == 'trail' else 'fixed 3 ATR stop + 60-session exit'} | {ername}"
            M, A, T = run_variant(N, exit_mode, er_min)
            store[label] = (M, A, T)
            results.append(summarize(M, A, T, label))
res = pd.DataFrame(results)
res.to_csv(f"{out_dir}/variants_summary.csv", index=False)
print(f"\n=== all variants at the reference budget: 20-day ATR of one position = {REF_BUDGET} percent of {ACCOUNT:,.0f}; net of costs; development years ===")
print(res.round(3).T.to_string())
PRIMARY = "20-session breakout | trailing 3 ATR stop | efficiency ratio >= 0.6"
M, A, T = store[PRIMARY]
gross = summarize(*run_variant(20, "trail", ER_MIN, cost_atr=0.0), "primary, gross of costs")
print("\nPRIMARY gross of costs: annual pnl %.0f, max drawdown %.0f, trades %d" % (gross["annual_pnl"], gross["max_drawdown_dollars"], gross["trades"]))

# ------------------------------------------------------------------ primary detail
tot = M.sum(axis=1)
by_year = pd.DataFrame({"pnl_dollars": tot.groupby(tot.index.year).sum(),
                        "max_drawdown_inside_year": tot.groupby(tot.index.year).apply(lambda s: max_drawdown(s.to_numpy())),
                        "mean_markets_in_trade": A.sum(axis=1).groupby(tot.index.year).mean()})
by_year.round(1).to_csv(f"{out_dir}/primary_by_year.csv")
print("\n=== PRIMARY by calendar year (reference budget) ===")
print(by_year.round(1).to_string())
by_mkt = pd.DataFrame({"group": [group[s] for s in M.columns], "pnl_dollars": M.sum().to_numpy(),
                       "trades": T.groupby("symbol").size().reindex(M.columns).fillna(0).to_numpy(),
                       "share_of_sessions_in_trade": A.mean().to_numpy(), "stand_alone_annual_vol": M.std().to_numpy() * np.sqrt(252),
                       "price_path_from": [mk[s].src for s in M.columns]}, index=M.columns)
by_mkt.round(3).to_csv(f"{out_dir}/primary_by_market.csv")
by_grp = by_mkt.groupby("group").agg(markets=("pnl_dollars", "size"), pnl_dollars=("pnl_dollars", "sum"), trades=("trades", "sum"))
print("\n=== PRIMARY by market group ===")
print(by_grp.round(0).to_string())
print("\n=== PRIMARY by market (top and bottom five by pnl) ===")
srt = by_mkt.sort_values("pnl_dollars")
print(pd.concat([srt.head(5), srt.tail(5)]).round(1).to_string())
div_ratio = float(M.std().sum() / M.sum(axis=1).std())
print(f"\nDiversification ratio (sum of each market's stand-alone daily volatility / volatility of the whole book): {div_ratio:.2f}")
print(f"Average pairwise correlation of daily pnl between markets (days when both are in the sample): {pd.DataFrame(M.replace(0, np.nan)).corr().stack().groupby(level=0).mean().mean():.3f}")
T.to_csv(f"{out_dir}/primary_trades.csv.gz", index=False)
M.round(2).to_csv(f"{out_dir}/primary_daily_pnl_by_market_ref_budget.csv.gz")

# ------------------------------------------------------------------ drawdown versus budget, with a block bootstrap
daily = M.sum(axis=1).to_numpy()
n = len(daily)
NB, BLK = 2000, 20
idx = np.empty((NB, n), dtype=np.int64)
idx[:, 0] = rng.integers(0, n, NB)
restart = rng.random((NB, n)) < 1 / BLK
fresh = rng.integers(0, n, (NB, n))
for t in range(1, n):
    idx[:, t] = np.where(restart[:, t], fresh[:, t], (idx[:, t - 1] + 1) % n)
paths = np.cumsum(np.concatenate([np.zeros((NB, 1)), daily[idx]], axis=1), axis=1)
boot_dd = (np.maximum.accumulate(paths, axis=1) - paths).max(axis=1)
hist_dd = max_drawdown(daily)
q = {k: float(np.percentile(boot_dd, k)) for k in (50, 75, 90, 95, 99)}
print(f"\n=== PRIMARY drawdown at the reference budget {REF_BUDGET} percent: history {hist_dd:,.0f} dollars; "
      f"resampled (2,000 paths, 20-session blocks, same length) median {q[50]:,.0f}, 90th {q[90]:,.0f}, 95th {q[95]:,.0f}, 99th {q[99]:,.0f} ===")
ann_ref = daily.sum() / (n / 252)
sc = []
for b in SCALE_GRID:
    k = b / REF_BUDGET
    sc.append(dict(budget_percent_per_market=b, annual_pnl=ann_ref * k, annual_pnl_pct_of_account=100 * ann_ref * k / ACCOUNT,
                   historical_max_drawdown=hist_dd * k, historical_max_dd_pct=100 * hist_dd * k / ACCOUNT,
                   resampled_median_dd=q[50] * k, resampled_95th_dd=q[95] * k, resampled_95th_dd_pct=100 * q[95] * k / ACCOUNT,
                   resampled_99th_dd=q[99] * k, summed_budget_when_busiest_pct=float(A.sum(axis=1).max() * b),
                   mean_summed_budget_pct=float(A.sum(axis=1).mean() * b)))
sc = pd.DataFrame(sc)
sc.to_csv(f"{out_dir}/scaling_table.csv", index=False)
print(sc.round(2).to_string(index=False))
for target in (90_000, 100_000):
    print(f"Budget per market that keeps the 95th-percentile resampled drawdown at {target:,}: {REF_BUDGET * target / q[95]:.3f} percent; "
          f"that keeps the historical maximum at {target:,}: {REF_BUDGET * target / hist_dd:.3f} percent")

# ------------------------------------------------------------------ does adding markets help? random subsets of markets
syms = list(M.columns)
rows = []
for k in sorted({x for x in (3, 5, 10, 20, 30, 45) if x < len(syms)} | {len(syms)}):
    reps = 1 if k == len(syms) else 400
    sh, ratio, dd_ref = [], [], []
    for _ in range(reps):
        pick = rng.choice(len(syms), k, replace=False)
        s = M.iloc[:, pick].sum(axis=1).to_numpy()
        d = max_drawdown(s)
        a = s.sum() / (n / 252)
        sh.append(a / (s.std() * np.sqrt(252)) if s.std() > 0 else np.nan)
        ratio.append(a / d if d > 0 else np.nan)
        dd_ref.append(d)
    rows.append(dict(markets=k, draws=reps, median_sharpe=np.nanmedian(sh), p10_sharpe=np.nanpercentile(sh, 10), p90_sharpe=np.nanpercentile(sh, 90),
                     median_annual_pnl_over_max_dd=np.nanmedian(ratio), p10_ratio=np.nanpercentile(ratio, 10), p90_ratio=np.nanpercentile(ratio, 90),
                     median_max_dd_at_ref_budget=np.median(dd_ref),
                     budget_for_90k_historical_dd=REF_BUDGET * 90_000 / np.median(dd_ref),
                     annual_pnl_pct_at_that_budget=100 * (np.nanmedian(ratio) * 90_000) / ACCOUNT))
sub = pd.DataFrame(rows)
sub.to_csv(f"{out_dir}/market_count_test.csv", index=False)
print("\n=== random subsets of markets, same rule, equal budget per market (ratio columns do not depend on the budget) ===")
print(sub.round(3).to_string(index=False))
print("Reading guide: if risk-adjusted results rise with the number of markets while the budget needed for a given drawdown also rises, more markets are paying for themselves.")
print("\nDONE")
