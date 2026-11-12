"""Efficiency-ratio-only trend system, parameters optimized one step at a time, DEVELOPMENT YEARS ONLY.

Usage: python trend_er_optimize.py futures_prices.parquet trend_universe.csv market_list.csv OUT_DIR [PREVIOUS_44_LIST.csv]

SEALED YEARS: prices after 2021-08-06 are removed the moment the file is read (development window 2007-12-31 to 2021-08-06). Nothing sealed is used.

THE RULE (Michael, 12 Nov 2026: "no 20-day high or low entry, just the efficiency ratio")
- Efficiency ratio over 20 sessions, high-low version (Michael's own definition, kept in memory): the highest high minus the lowest low of the last 20 sessions,
  divided by the sum of the last 20 true ranges (20 x the 20-day ATR). Near 1 means a smooth one-way move where every day's range adds to the total travel; near 0 means
  back and forth. The older close-based version (net close change over the sum of absolute daily close changes) is run once as a sensitivity.
- Entry: flat and efficiency ratio at least the target. Direction = sign of (close now minus close 20 sessions ago). Entered at the NEXT session's open.
- Exits: an initial stop N ATR from the entry price (ATR = 20-day average true range on the signal day); a trailing stop M ATR from the best close since entry,
  recomputed each close with the current ATR, only ever moving in the trade's favour (the later of the two stops governs); a time stop after T sessions at the close.
  A stop that is touched exits at the stop price, or at the open if the market gaps through it.
- One position per market, no pyramiding, no reversal; after an exit the market can re-enter on the same close if the entry condition still holds.
- Size: 20-day ATR of one position = budget percent of the account (reference 0.10 percent of 300,000, scaled exactly: dollar results are proportional to the budget).
  Fractional contracts; sizing on the fixed starting account.
- Cost 0.05 ATR per side (declared, not measured).

OPTIMIZATION (sequential, as Michael asked): efficiency ratio target first, then the initial stop, then the trailing stop, then the time stop. Each step holds the earlier
steps at their chosen values. Starting values before a step is optimized: target 0.30, initial stop 3 ATR, trailing stop 3 ATR, no time stop.
Objective: Sharpe (annual profit over annual volatility of the daily book). To avoid picking a lone spike, the value chosen is the one whose average Sharpe with its two
neighbours is highest; the raw best is shown beside it. Each table also shows the first half (before 2015) and second half (2015 on) so stability can be judged.
Everything chosen here was chosen after looking at the development years, so it is a lead, not a rule.
Price paths: ratio back-adjusted futures. A market with too little history uses the longest contract in its family (as in baseline_breakout.py); SO3 (3-month SONIA, started
2018) uses short sterling (L), the contract it replaced, for the development years.
"""
import sys
import time
import numpy as np
import pandas as pd

prices_path, uni_path, list_path, out_dir = sys.argv[1:5]
prev44_path = sys.argv[5] if len(sys.argv) > 5 else None
ACCOUNT = 300_000.0
DEV_START, DEV_END = pd.Timestamp("2007-12-31"), pd.Timestamp("2021-08-06")
SPLIT = pd.Timestamp("2015-01-01")
REF = 0.10
COST = 0.05
W = 20
PATH_OVERRIDE = {"SO3": "L"}
rng = np.random.default_rng(20261112)
t0 = time.time()

px = pd.read_parquet(prices_path)
px["file_date"] = pd.to_datetime(px["file_date"])
px = px[(px["file_date"] >= DEV_START) & (px["file_date"] <= DEV_END)].copy()
assert px["file_date"].max() <= DEV_END
print(f"development rows {len(px):,}; {px['file_date'].min().date()} to {px['file_date'].max().date()}; sealed years removed at load")

uni = pd.read_csv(uni_path)
fam = dict(zip(uni["price_symbol"], uni["family"]))
lst = pd.read_csv(list_path)
group = dict(zip(lst["price_symbol"], lst["group"]))
rows_by_sym = px.groupby("symbol").size().to_dict()
mapping = {}
for sym in lst["price_symbol"]:
    f = fam.get(sym)
    cands = [s for s, ff in fam.items() if ff == f and s in rows_by_sym]
    best = max(cands, key=lambda s: rows_by_sym[s]) if cands else None
    own = rows_by_sym.get(sym, 0)
    if best is None:
        mapping[sym] = None
    elif own >= 0.7 * rows_by_sym[best]:
        mapping[sym] = sym
    else:
        mapping[sym] = best
    ov = PATH_OVERRIDE.get(sym)
    if ov and rows_by_sym.get(ov, 0) >= 150 and own < 0.7 * rows_by_sym[ov]:
        mapping[sym] = ov
print("price path taken from a different contract:", {k: v for k, v in mapping.items() if v != k})
print("no development-year data:", [k for k, v in mapping.items() if v is None])

calendar = pd.DatetimeIndex(sorted(px["file_date"].unique()))
NCAL = len(calendar)
first_half = np.asarray(calendar < SPLIT)


class Mkt:
    pass


mk = {}
for sym, src in mapping.items():
    if src is None:
        continue
    g = px[px["symbol"] == src].sort_values("file_date").drop_duplicates("file_date").dropna(subset=["close", "high", "low"])
    if len(g) < 150:
        print(f"  skipped {sym}: only {len(g)} development sessions")
        continue
    c = g["close"].to_numpy(float).copy()
    o = g["open"].fillna(g["close"]).to_numpy(float).copy()
    h, l = g["high"].to_numpy(float).copy(), g["low"].to_numpy(float).copy()
    # unit glitch repair: a one-day close ratio near a power of ten (e.g. 98.5 -> 985.5) is a quoting change, not a move; rescale everything before it
    for k in range(1, len(c)):
        r = c[k] / c[k - 1]
        if r > 5 or r < 0.2:
            f = 10.0 ** round(np.log10(r))
            if f != 1.0:
                print(f"  unit glitch in {sym} (from {src}) at {g['file_date'].iloc[k].date()}: close ratio {r:.2f}; scaling earlier bars by {f:g}")
                c[:k] *= f; o[:k] *= f; h[:k] *= f; l[:k] *= f
    pc = np.r_[np.nan, c[:-1]]
    tr = np.maximum.reduce([h - l, np.abs(h - pc), np.abs(l - pc)])
    tr[0] = h[0] - l[0]
    atr = pd.Series(tr).rolling(W).mean()
    hh, ll = pd.Series(h).rolling(W).max(), pd.Series(l).rolling(W).min()
    cs = pd.Series(c)
    m = Mkt()
    m.sym, m.src = sym, src
    m.idx = calendar.get_indexer(g["file_date"])
    m.first_date = g["file_date"].iloc[0]
    m.o, m.h, m.l, m.c = o.tolist(), h.tolist(), l.tolist(), c.tolist()
    m.atr = atr.tolist()
    er_hl = (hh - ll) / (W * atr)
    path = pd.Series(np.abs(np.diff(c, prepend=np.nan))).rolling(W).sum()
    er_close = (cs - cs.shift(W)).abs() / path
    m.er = {"hl": er_hl.tolist(), "close": er_close.tolist()}
    m.dir = np.sign(cs - cs.shift(W)).fillna(0).astype(int).tolist()
    mk[sym] = m
print(f"{len(mk)} markets in the test; first date of the shortest series: {min(m.first_date for m in mk.values()).date()} to {max(m.first_date for m in mk.values()).date()}")
for k in ("hl", "close"):
    allv = np.concatenate([np.array(m.er[k], float) for m in mk.values()])
    allv = allv[~np.isnan(allv)]
    print(f"efficiency ratio ({k}) across all market-days: percentiles 10/25/50/75/90/95 = " + " ".join(f"{np.percentile(allv, q):.2f}" for q in (10, 25, 50, 75, 90, 95)))


def run_market(m, kind, er_min, init_atr, trail_atr, tmax, risk, want_trades=False):
    o, h, l, c, atr = m.o, m.h, m.l, m.c, m.atr
    er, dr = m.er[kind], m.dir
    n = len(c)
    pnl = [0.0] * n
    inpos = [0] * n
    trades = []
    ntr = nwin = 0
    side = pending = 0
    pend_atr = atr0 = stop = best = prev = entry = shares = tpnl = 0.0
    start = 0
    for i in range(n):
        if pending:
            side, atr0, entry = pending, pend_atr, o[i]
            shares = risk / atr0
            stop = entry - side * init_atr * atr0
            best = prev = entry
            start = i
            pending = 0
            cst = -COST * atr0 * shares
            pnl[i] += cst
            tpnl = cst
        if side:
            inpos[i] = 1
            hit = (l[i] <= stop) if side == 1 else (h[i] >= stop)
            reason = None
            if hit:
                if side == 1:
                    pxe = stop if o[i] >= stop else o[i]
                else:
                    pxe = stop if o[i] <= stop else o[i]
                d = shares * side * (pxe - prev) - COST * atr0 * shares
                pnl[i] += d
                tpnl += d
                reason = "stop"
            else:
                d = shares * side * (c[i] - prev)
                pnl[i] += d
                tpnl += d
                prev = c[i]
                if side == 1:
                    if c[i] > best:
                        best = c[i]
                else:
                    if c[i] < best:
                        best = c[i]
                if trail_atr is not None:
                    a = atr[i]
                    if a == a:
                        new = best - side * trail_atr * a
                        if side == 1:
                            if new > stop:
                                stop = new
                        else:
                            if new < stop:
                                stop = new
                if tmax is not None and i - start + 1 >= tmax:
                    reason = "time"
                elif i == n - 1:
                    reason = "end of development window"
                if reason:
                    d = -COST * atr0 * shares
                    pnl[i] += d
                    tpnl += d
                    pxe = c[i]
            if reason:
                ntr += 1
                nwin += 1 if tpnl > 0 else 0
                if want_trades:
                    trades.append((m.sym, side, start, i, shares, atr0, entry, pxe, tpnl, reason))
                side = 0
        if side == 0 and i < n - 1:
            e, a = er[i], atr[i]
            if e == e and a == a and a > 1e-5 * c[i] and e >= er_min and dr[i] != 0:
                pending, pend_atr = dr[i], a
    return pnl, inpos, ntr, nwin, trades


def max_dd(daily):
    cum = np.cumsum(np.r_[0.0, daily])
    return float((np.maximum.accumulate(cum) - cum).max())


def sharpe_of(x):
    sd = x.std() * np.sqrt(252)
    return float(x.mean() * 252 / sd) if sd > 0 else np.nan


def evaluate(kind, er_min, init_atr, trail_atr, tmax, detail=False):
    risk = REF / 100 * ACCOUNT
    tot = np.zeros(NCAL)
    act = np.zeros(NCAL)
    ntr = nwin = 0
    M, A, T = {}, {}, []
    for sym, m in mk.items():
        pnl, inpos, k, w, trades = run_market(m, kind, er_min, init_atr, trail_atr, tmax, risk, detail)
        s = np.zeros(NCAL)
        a = np.zeros(NCAL)
        s[m.idx] = pnl
        a[m.idx] = inpos
        tot += s
        act += a
        ntr += k
        nwin += w
        if detail:
            M[sym], A[sym] = s, a
            for t in trades:
                T.append(dict(symbol=t[0], side="long" if t[1] == 1 else "short", entry_date=pd.Timestamp(calendar[m.idx[t[2]]]).date(),
                              exit_date=pd.Timestamp(calendar[m.idx[t[3]]]).date(), sessions=t[3] - t[2] + 1, shares=t[4], atr_at_entry=t[5],
                              entry_price=t[6], exit_price=t[7], pnl_dollars=t[8], pnl_in_atr=t[8] / (t[4] * t[5]), exit_reason=t[9]))
    yrs = NCAL / 252
    ann = tot.sum() / yrs
    dd = max_dd(tot)
    r = dict(er_target=er_min, initial_stop_atr=init_atr, trailing_stop_atr=trail_atr if trail_atr is not None else np.nan,
             time_stop_sessions=tmax if tmax is not None else np.nan, trades=ntr, win_rate=nwin / ntr if ntr else np.nan,
             annual_pnl=ann, sharpe=sharpe_of(tot), max_drawdown=dd, annual_over_drawdown=ann / dd if dd > 0 else np.nan,
             sharpe_first_half=sharpe_of(tot[first_half]), sharpe_second_half=sharpe_of(tot[~first_half]),
             mean_markets_in_trade=float(act.mean()))
    if detail:
        return r, pd.DataFrame(M, index=calendar), pd.DataFrame(A, index=calendar), pd.DataFrame(T)
    return r


def pick(sh):
    sm = [float(np.nanmean(sh[max(0, i - 1):i + 2])) for i in range(len(sh))]
    return int(np.nanargmax(sm)), int(np.nanargmax(sh)), sm


pd.set_option("display.width", 250, "display.max_rows", 500, "display.max_columns", 40)
START = dict(kind="hl", er_min=0.30, init_atr=3.0, trail_atr=3.0, tmax=None)
print(f"\nstarting values before any step: efficiency ratio target 0.30 (high-low scale), initial stop 3 ATR, trailing stop 3 ATR, no time stop. Budget {REF} percent per market, annual profit in dollars at that budget.")
base = evaluate(**START)
print("starting point:", {k: round(v, 3) for k, v in base.items() if k in ("trades", "annual_pnl", "sharpe", "max_drawdown", "sharpe_first_half", "sharpe_second_half")})


def run_step(title, key, values, fixed, fname):
    rows = []
    for v in values:
        p = dict(fixed)
        p[key] = v
        rows.append(evaluate(**p))
    df = pd.DataFrame(rows)
    ib, ir, sm = pick(df["sharpe"].to_numpy())
    df["sharpe_smoothed"] = sm
    df.to_csv(f"{out_dir}/{fname}.csv", index=False)
    cols = [c for c in ("er_target", "initial_stop_atr", "trailing_stop_atr", "time_stop_sessions") if c in df.columns]
    show = df[["er_target", "initial_stop_atr", "trailing_stop_atr", "time_stop_sessions", "trades", "win_rate", "annual_pnl", "sharpe", "sharpe_smoothed",
               "max_drawdown", "sharpe_first_half", "sharpe_second_half", "mean_markets_in_trade"]]
    print(f"\n=== {title} ===")
    print(show.round(3).to_string(index=False))
    bh1 = int(np.nanargmax(df["sharpe_first_half"].to_numpy()))
    bh2 = int(np.nanargmax(df["sharpe_second_half"].to_numpy()))
    print(f"CHOSEN (best smoothed Sharpe): row {ib}; raw best Sharpe row {ir}; best in first half row {bh1}; best in second half row {bh2}")
    return values[ib], df


# ---- step 1: efficiency ratio target
# The high-low ratio (range over the sum of true ranges) lives between about 0.10 and 0.50 in practice (95th percentile 0.35), so the grid sits there; the first run used 0.30-0.85 and
# produced almost no trades above 0.45 (invalid grid for this definition).
ER_GRID = [0.20, 0.225, 0.25, 0.275, 0.30, 0.325, 0.35, 0.375, 0.40, 0.425, 0.45, 0.50]
CL_GRID = [0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85]
er_best, _ = run_step("STEP 1: efficiency ratio target (high-low version)", "er_min", ER_GRID, START, "step1_efficiency_ratio_target")
fixed = dict(START, er_min=er_best)
_r, _M, _A, _T = evaluate("hl", 0.20, 3.0, 3.0, None, detail=True)
_st = _M.stack()
print("DIAGNOSTIC single market-days with the largest absolute dollar move (target 0.20, reference budget):")
for (d, sym), v in _st.reindex(_st.abs().sort_values(ascending=False).index).head(8).items():
    m = mk[sym]
    j = list(m.idx).index(calendar.get_loc(d))
    print(f"  {sym} {d.date()} pnl {v:,.0f}; open/high/low/close {m.o[j]:.4f}/{m.h[j]:.4f}/{m.l[j]:.4f}/{m.c[j]:.4f}; previous close {m.c[j-1]:.4f}; atr {m.atr[j]:.5f}")
# ---- sensitivity: close-based efficiency ratio
run_step("SENSITIVITY: close-based efficiency ratio target (older definition)", "er_min", CL_GRID, dict(START, kind="close", er_min=0.6), "sensitivity_close_based_ratio")
_r, _M, _A, _T = evaluate("close", 0.30, 3.0, 3.0, None, detail=True)
print("worst five trades of the close-based run at 0.30 (checking the blown-up drawdown):")
print(_T.sort_values("pnl_dollars").head(5)[["symbol", "side", "entry_date", "exit_date", "shares", "atr_at_entry", "entry_price", "exit_price", "pnl_dollars", "pnl_in_atr"]].to_string(index=False))
# ---- step 2: initial stop
INIT_GRID = [1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 8.0]
init_best, _ = run_step(f"STEP 2: initial stop in ATR (efficiency ratio target {er_best})", "init_atr", INIT_GRID, fixed, "step2_initial_stop")
fixed = dict(fixed, init_atr=init_best)
# ---- step 3: trailing stop (None = no trailing stop)
TRAIL_GRID = [1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 8.0, None]
trail_best, _ = run_step(f"STEP 3: trailing stop in ATR from the best close (target {er_best}, initial stop {init_best}); the last row is no trailing stop", "trail_atr", TRAIL_GRID, fixed, "step3_trailing_stop")
fixed = dict(fixed, trail_atr=trail_best)
# ---- step 4: time stop (None = no time stop)
TIME_GRID = [10, 15, 20, 30, 40, 60, 90, 120, None]
time_best, _ = run_step(f"STEP 4: time stop in sessions (target {er_best}, initial {init_best}, trailing {trail_best}); the last row is no time stop", "tmax", TIME_GRID, fixed, "step4_time_stop")
fixed = dict(fixed, tmax=time_best)
print(f"\nFINAL PARAMETERS: efficiency ratio target {er_best}; initial stop {init_best} ATR; trailing stop {trail_best} ATR; time stop {time_best} sessions")

# ---- final book
r, M, A, T = evaluate(detail=True, **fixed)
T.to_csv(f"{out_dir}/final_trades.csv.gz", index=False)
tot = M.sum(axis=1).to_numpy()
yrs = NCAL / 252
print("\n=== FINAL BOOK at the reference budget (0.10 percent per market) ===")
print({k: round(float(v), 3) for k, v in r.items()})
print(f"average trade {T['pnl_in_atr'].mean():.2f} ATR, winners average {T.loc[T.pnl_dollars > 0, 'pnl_in_atr'].mean():.2f} ATR, losers {T.loc[T.pnl_dollars <= 0, 'pnl_in_atr'].mean():.2f} ATR, "
      f"average {T['sessions'].mean():.1f} sessions; exits: {T['exit_reason'].value_counts().to_dict()}; most markets in trade at once {int(A.sum(axis=1).max())}")
print(f"before optimization (starting values): annual {base['annual_pnl']:.0f}, Sharpe {base['sharpe']:.2f}, max drawdown {base['max_drawdown']:.0f}")

by_year = pd.DataFrame({"pnl_dollars": M.sum(axis=1).groupby(M.index.year).sum(),
                        "max_drawdown_inside_year": M.sum(axis=1).groupby(M.index.year).apply(lambda s: max_dd(s.to_numpy())),
                        "mean_markets_in_trade": A.sum(axis=1).groupby(M.index.year).mean()})
by_year.round(1).to_csv(f"{out_dir}/final_by_year.csv")
print("\nby calendar year (reference budget)")
print(by_year.round(0).to_string())

by_mkt = pd.DataFrame({"group": [group[s] for s in M.columns], "pnl_dollars": M.sum().to_numpy(),
                       "trades": T.groupby("symbol").size().reindex(M.columns).fillna(0).to_numpy(),
                       "share_of_sessions_in_trade": A.mean().to_numpy(), "price_path_from": [mk[s].src for s in M.columns]}, index=M.columns)
by_mkt["share_of_total_profit_pct"] = 100 * by_mkt["pnl_dollars"] / by_mkt["pnl_dollars"].sum()
by_mkt.sort_values("pnl_dollars").round(3).to_csv(f"{out_dir}/final_by_market.csv")
print("\nby market, sorted by profit (reference budget)")
print(by_mkt.sort_values("pnl_dollars", ascending=False)[["group", "pnl_dollars", "share_of_total_profit_pct", "trades", "share_of_sessions_in_trade", "price_path_from"]].round(2).to_string())
grp = by_mkt.groupby("group").agg(markets=("pnl_dollars", "size"), pnl_dollars=("pnl_dollars", "sum"), trades=("trades", "sum"))
grp["share_of_total_profit_pct"] = 100 * grp["pnl_dollars"] / grp["pnl_dollars"].sum()
print("\nby market group")
print(grp.round(1).to_string())
SHORT = [s for s in ("ZQ", "SR1", "SR3", "ER", "SO3") if s in M.columns]
print(f"\nshort-rate markets {SHORT}: {by_mkt.loc[SHORT, 'pnl_dollars'].sum():.0f} dollars = {by_mkt.loc[SHORT, 'share_of_total_profit_pct'].sum():.1f} percent of profit; fed funds alone {by_mkt.loc['ZQ', 'share_of_total_profit_pct']:.1f} percent")
for label, drop in (("without fed funds (ZQ)", ["ZQ"]), ("without all short rates", SHORT)):
    x = M.drop(columns=drop).sum(axis=1).to_numpy()
    print(f"book {label}: annual {x.sum() / yrs:.0f}, Sharpe {sharpe_of(x):.2f}, max drawdown {max_dd(x):.0f}")
if prev44_path:
    p44 = [s for s in pd.read_csv(prev44_path)["price_symbol"] if s in M.columns]
    new = [s for s in M.columns if s not in p44]
    for label, cols in (("the earlier 44 markets only", p44), (f"the {len(new)} added European markets only {new}", new)):
        x = M[cols].sum(axis=1).to_numpy()
        print(f"{label}: annual {x.sum() / yrs:.0f}, Sharpe {sharpe_of(x):.2f}, max drawdown {max_dd(x):.0f}")

# ---- drawdown versus budget (block bootstrap), scaled exactly
n = len(tot)
NB, BLK = 2000, 20
idx = np.empty((NB, n), dtype=np.int64)
idx[:, 0] = rng.integers(0, n, NB)
restart = rng.random((NB, n)) < 1 / BLK
fresh = rng.integers(0, n, (NB, n))
for t in range(1, n):
    idx[:, t] = np.where(restart[:, t], fresh[:, t], (idx[:, t - 1] + 1) % n)
paths = np.cumsum(np.concatenate([np.zeros((NB, 1)), tot[idx]], axis=1), axis=1)
boot = (np.maximum.accumulate(paths, axis=1) - paths).max(axis=1)
q = {k: float(np.percentile(boot, k)) for k in (50, 95, 99)}
hist = max_dd(tot)
ann = tot.sum() / yrs
rows = []
for b in (0.05, 0.10, 0.15, 0.17, 0.20, 0.25, 0.30):
    k = b / REF
    rows.append(dict(budget_percent_per_market=b, annual_pnl=ann * k, annual_pnl_pct_of_account=100 * ann * k / ACCOUNT, historical_max_drawdown=hist * k,
                     historical_max_dd_pct=100 * hist * k / ACCOUNT, resampled_median_dd=q[50] * k, resampled_95th_dd=q[95] * k,
                     resampled_95th_dd_pct=100 * q[95] * k / ACCOUNT, resampled_99th_dd=q[99] * k,
                     summed_budget_when_busiest_pct=float(A.sum(axis=1).max() * b), mean_summed_budget_pct=float(A.sum(axis=1).mean() * b)))
sc = pd.DataFrame(rows)
sc.to_csv(f"{out_dir}/final_scaling_table.csv", index=False)
print("\n=== final book: profit and drawdown by budget per market ===")
print(sc.round(2).to_string(index=False))
for target in (90_000, 100_000):
    print(f"budget per market that keeps the 95th-percentile resampled drawdown at {target:,}: {REF * target / q[95]:.3f} percent; the historical maximum at {target:,}: {REF * target / hist:.3f} percent")
pd.DataFrame([dict(step="starting values", **base)]).to_csv(f"{out_dir}/starting_point.csv", index=False)
print(f"\nDONE in {time.time() - t0:.0f} seconds")
