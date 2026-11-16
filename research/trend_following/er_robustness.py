"""Robustness tests of the frozen best rule against the earlier outright-strength system (Michael, 16 Nov 2026: "do 1 through 4").

Usage: python er_robustness.py futures_prices.parquet report_universe_48_markets.csv OUT_DIR

Nothing about either system is changed. The trade engine, contract values, costs, sizing and the two trade lists are the ones of er_vs_breakout.py (Entries 127 and 128): this script
executes that file's engine and definitions unchanged (everything above its "report section", and the definitions up to its results loop) and then runs four new tests on the
same trades. Before any new number is printed, it re-computes the logged headline rows (Entry 128, results_vs_breakout/head_to_head_summary.csv) and stops if they differ.

Window: whole history (Feb 2008 to Nov 2026), whole contracts on $300k, 0.05 ATR a side, short-rate futures capped at 10 contracts per trade unless a test says otherwise.
Sizings shown: whole contracts at 0.15% and 0.25% of the account per ATR, and fractional at 0.25% (the fractional case answers whether contract rounding changes the ranking).

Test 1. The ten biggest trades of each system: market, direction, dates, size, profit and share of the total, years and market groups they cluster in, and whether the other system
        was in the same market in the same direction at the same time.
Test 2. Drop-the-biggest-trades: remove the 1, 3, 5, 10 and 20 most profitable trades (ranked by dollars; also the ten best by ATR result) from the whole-history daily profit and
        recompute return, Sharpe and drawdown. Trades are removed after the fact; nothing re-enters in their place, so this is a stress test, not a forecast.
Test 3. Year-block resample: whole calendar years of daily profit are drawn with replacement (10,000 draws, fixed seed 20261116) until the history length is reached, the same
        years for every system in a draw so the two systems stay paired. Also: leave one calendar year out, and profit by calendar year.
Test 4. Combined short-rate limit in dollars per basis point (Fed funds, 1-month SOFR, 3-month SOFR, 2-year note): the signed net exposure of all open short-rate trades may not
        exceed the limit when a new trade is opened (the new trade is cut to what fits, skipped if none fits). Assumes the four markets move one-for-one in basis points (a parallel
        shift), which is the harsh case for same-direction positions. Dollars per basis point per contract: Fed funds 41.67, 1-month SOFR 41.67, 3-month SOFR 25.00 (contract
        specifications), 2-year note 39 (approximate: $204,789 contract value x about 1.9 years of price sensitivity x 0.0001). Reports the highest exposure ever reached, the loss from a
        sudden 50 and 100 basis point move against that exposure, and the worst single day of the short-rate book.
"""
import os
from pathlib import Path

_SRC = Path(__file__).resolve().parent / "er_vs_breakout.py"
_TXT = _SRC.read_text()
_MARK = "# ====================================================================== report section (head to head)"
_STOP = "out, yearly, daily_store = [], {}, {}"
_ENGINE, _SEP, _REST = _TXT.partition(_MARK)
_DEFS = _REST.partition(_STOP)[0]
assert _SEP and _DEFS.strip(), "could not split er_vs_breakout.py"
exec(compile(_ENGINE + _MARK + "\n" + _DEFS, str(_SRC), "exec"), globals())

OUT = Path(out_dir)
OUT.mkdir(parents=True, exist_ok=True)
pd.set_option("display.width", 300); pd.set_option("display.max_columns", 40); pd.set_option("display.max_rows", 900); pd.set_option("display.max_colwidth", 60)
NAMES = list(SYSTEMS)
NICK = {NAMES[0]: "frozen rule", NAMES[1]: "earlier system"}
SIZING_SET = [("whole contracts", 0.15), ("whole contracts", 0.25), ("fractional", 0.25)]
FIRST, LAST = ALLD[0], ALLD[-1]
N_DAYS = len(ALLD)
YEAR_OF_DAY = np.asarray(ALLD.year)


def csize(kind, tp):
    return f"{kind}, {tp}% of the account per ATR"


def show(title, df):
    print(f"\n==== {title} ====")
    print(df.to_string(index=False), flush=True)


def series_stats(u):
    eq = np.r_[CAPITAL, CAPITAL + np.cumsum(u)]
    peak = np.maximum.accumulate(eq)
    r = u / CAPITAL
    s = r.std()
    return (eq[-1] - CAPITAL) / CAPITAL * 100 / (len(u) / 252.0), (r.mean() / s * np.sqrt(252) if s > 0 else np.nan), ((eq - peak) / peak).min() * 100


# ---------------------------------------------------------------- per-trade dates, dollars per ATR of a contract, short-rate flags
for nm, sd in SYSTEMS.items():
    ed, xd = [], []
    for i, r_ in enumerate(sd["rows"]):
        mid = MK[r_]; loc = r_ - MOFF[mid]; h_ = int(sd["held"][i])
        ed.append(pd.Timestamp(MDATES[mid][loc + 1])); xd.append(pd.Timestamp(MDATES[mid][loc + h_]))
    sd["ed"], sd["xd"] = pd.DatetimeIndex(ed), pd.DatetimeIndex(xd)
    sd["ep"], sd["xp"] = ALLD.searchsorted(sd["ed"]), ALLD.searchsorted(sd["xd"])
    sd["ad"] = sd["atr_pct"] * REFPX[MK[sd["rows"]]] * MULT[MK[sd["rows"]]]
    sd["is_sr"] = np.isin(sd["mk"], SHORT_RATES)

# ---------------------------------------------------------------- books: daily profit of each system at each sizing (the exact head-to-head calculation)
BOOK = {}
for nm, sd in SYSTEMS.items():
    for kind, tp in SIZING_SET:
        w_, al_ = sizing(sd, kind, tp, CAP_SR)
        pnl_, opn_, _heat = daily_usd(sd["rows"], sd["d"], sd["res"], sd["held"], sd["px"], w_, al_)
        BOOK[(nm, kind, tp)] = dict(w=w_, al=al_, pnl=pnl_, opn=opn_)


def mixed(kind, tp, a=None, b=None):
    pa = BOOK[(NAMES[0], kind, tp)]["pnl"] if a is None else a
    pb = BOOK[(NAMES[1], kind, tp)]["pnl"] if b is None else b
    return 0.5 * pa + 0.5 * pb


# ---------------------------------------------------------------- reference check against the logged head-to-head rows (Entry 128)
ref_file = Path(__file__).resolve().parent / "results_vs_breakout" / "head_to_head_summary.csv"
if os.environ.get("ROBUSTNESS_SKIP_REFERENCE") == "1" or not ref_file.exists():
    print("REFERENCE CHECK SKIPPED (no logged head-to-head file, or skip requested)", flush=True)
else:
    ref = pd.read_csv(ref_file)
    for nm in NAMES:
        for kind, tp in SIZING_SET:
            b = BOOK[(nm, kind, tp)]
            st, _ = wstats(b["pnl"], b["opn"], FIRST, LAST)
            lab = f"{kind} {tp}% per ATR, short rates capped at {CAP_SR} contracts"
            row = ref[(ref.system == nm) & (ref.sizing == lab) & (ref.markets == "all 46 markets") & (ref.window == "whole history")]
            assert len(row) == 1, (nm, lab, len(row))
            row = row.iloc[0]
            for key_ in ("return_per_year_pct", "sharpe", "max_drawdown_pct"):
                assert abs(st[key_] - row[key_]) < 0.011, f"REFERENCE MISMATCH {nm} | {lab} | {key_}: now {st[key_]:.4f}, logged {row[key_]:.4f}"
    print("REFERENCE CHECK PASSED: whole-history return, Sharpe and drawdown of both systems at all three sizings match Entry 128 to within 0.01", flush=True)

rows_ = []
for kind, tp in SIZING_SET:
    for nm in NAMES:
        b = BOOK[(nm, kind, tp)]; st, cal = wstats(b["pnl"], b["opn"], FIRST, LAST)
        rows_.append(dict(sizing=csize(kind, tp), system=NICK[nm], trades=int(b["al"].sum()), return_per_year_pct=st["return_per_year_pct"], sharpe=st["sharpe"], max_drawdown_pct=st["max_drawdown_pct"], total_profit_usd=b["pnl"].sum()))
    r_, s_, d_ = series_stats(mixed(kind, tp))
    rows_.append(dict(sizing=csize(kind, tp), system="50/50 mix", trades=np.nan, return_per_year_pct=r_, sharpe=s_, max_drawdown_pct=d_, total_profit_usd=mixed(kind, tp).sum()))
BASE = pd.DataFrame(rows_).round(2)
show("BASELINE (whole history, as logged in Entry 128)", BASE)
BASE.to_csv(OUT / "baseline.csv", index=False)

# ================================================================== TEST 1: the ten biggest trades
GROUP2 = lambda m: "short-rate futures" if m in SHORT_RATES else GROUP_OF.get(m, "other")


def trades_frame(nm, kind, tp):
    sd, b = SYSTEMS[nm], BOOK[(nm, kind, tp)]
    f = pd.DataFrame(dict(market=sd["mk"], group=[GROUP2(m) for m in sd["mk"]], direction=np.where(sd["d"] > 0, "long", "short"), entry_date=sd["ed"], exit_date=sd["xd"],
                          sessions_held=sd["held"], result_ATR_after_cost=sd["res"], contracts=(b["w"] / sd["ad"]) if kind.startswith("whole") else np.nan, profit_usd=sd["res"] * b["w"]))
    f = f[b["al"]].copy()
    f["profit_rank"] = f.profit_usd.rank(ascending=False, method="first").astype(int)
    return f.sort_values("profit_rank").reset_index(drop=True)


top_rows, cluster_rows, FRAMES = [], [], {}
for kind, tp in SIZING_SET:
    for nm in NAMES:
        FRAMES[(nm, kind, tp)] = trades_frame(nm, kind, tp)
for kind, tp in SIZING_SET:
    for nm, other in ((NAMES[0], NAMES[1]), (NAMES[1], NAMES[0])):
        f, fo = FRAMES[(nm, kind, tp)], FRAMES[(other, kind, tp)]
        total = f.profit_usd.sum(); top = f.head(10).copy()
        top.insert(0, "rank", range(1, len(top) + 1))
        top["share_of_total_profit_pct"] = top.profit_usd / total * 100
        top["cumulative_share_pct"] = top.share_of_total_profit_pct.cumsum()
        orank, oprof = [], []
        for _, t in top.iterrows():
            m_ = fo[(fo.market == t.market) & (fo.direction == t.direction) & (fo.entry_date <= t.exit_date) & (fo.exit_date >= t.entry_date)]
            orank.append(int(m_.profit_rank.min()) if len(m_) else 0); oprof.append(float(m_.loc[m_.profit_rank.idxmin(), "profit_usd"]) if len(m_) else np.nan)
        top["other_system_same_market_and_direction_profit_rank"] = orank
        top["other_system_that_trade_profit_usd"] = oprof
        top.insert(0, "sizing", csize(kind, tp)); top.insert(1, "system", NICK[nm])
        top_rows.append(top)
        yrs = pd.Series(top.entry_date.dt.year).value_counts().sort_index()
        cluster_rows.append(dict(sizing=csize(kind, tp), system=NICK[nm], trades=len(f), total_profit_usd=total, ten_biggest_profit_usd=top.profit_usd.sum(), ten_biggest_share_pct=top.profit_usd.sum() / total * 100,
                                 biggest_single_share_pct=top.share_of_total_profit_pct.iloc[0], profit_of_all_other_trades_usd=total - top.profit_usd.sum(),
                                 entry_years_of_the_ten=", ".join(f"{y}x{c}" for y, c in yrs.items()), distinct_markets_in_ten=top.market.nunique(),
                                 short_rate_trades_in_ten=int((top.group == "short-rate futures").sum()), ten_in_other_systems_top_ten=int(((np.array(orank) > 0) & (np.array(orank) <= 10)).sum())))
TOP = pd.concat(top_rows, ignore_index=True)
CLUS = pd.DataFrame(cluster_rows)
TOP.to_csv(OUT / "ten_biggest_trades.csv", index=False, float_format="%.2f")
CLUS.round(2).to_csv(OUT / "ten_biggest_summary.csv", index=False)
show("TEST 1 SUMMARY: how much of the profit the ten biggest trades make, and where they cluster", CLUS.round(1))
cols1 = ["rank", "market", "group", "direction", "entry_date", "exit_date", "sessions_held", "result_ATR_after_cost", "contracts", "profit_usd", "share_of_total_profit_pct", "cumulative_share_pct",
         "other_system_same_market_and_direction_profit_rank", "other_system_that_trade_profit_usd"]
for kind, tp in SIZING_SET[:2]:
    for nm in NAMES:
        t = TOP[(TOP.sizing == csize(kind, tp)) & (TOP.system == NICK[nm])][cols1].copy()
        t["entry_date"] = t.entry_date.dt.date; t["exit_date"] = t.exit_date.dt.date
        show(f"TEST 1: ten biggest trades, {NICK[nm]}, {csize(kind, tp)} (other-system rank 0 = no overlapping trade in that market and direction)", t.round(2))

# ================================================================== TEST 2: drop the biggest trades
drop_rows = []
for kind, tp in SIZING_SET:
    for basis, ks in (("dollars", (0, 1, 3, 5, 10, 20)), ("ATR result", (10,))):
        for k in ks:
            pn = {}
            for nm in NAMES:
                sd, b = SYSTEMS[nm], BOOK[(nm, kind, tp)]
                al = b["al"].copy(); cand = np.where(al)[0]
                score = (sd["res"] * b["w"]) if basis == "dollars" else sd["res"]
                al[cand[np.argsort(-score[cand], kind="stable")][:k]] = False
                pnl_, opn_, _h = daily_usd(sd["rows"], sd["d"], sd["res"], sd["held"], sd["px"], b["w"], al)
                st, cal = wstats(pnl_, opn_, FIRST, LAST); pn[nm] = pnl_
                drop_rows.append(dict(sizing=csize(kind, tp), trades_removed=k, ranked_by=basis, system=NICK[nm], return_per_year_pct=st["return_per_year_pct"], sharpe=st["sharpe"], max_drawdown_pct=st["max_drawdown_pct"],
                                      total_profit_usd=pnl_.sum(), trades_left=int(al.sum()), avg_ATR_per_trade_left=float(sd["res"][al].mean()), years_positive=st["years_positive"]))
            r_, s_, d_ = series_stats(mixed(kind, tp, pn[NAMES[0]], pn[NAMES[1]]))
            drop_rows.append(dict(sizing=csize(kind, tp), trades_removed=k, ranked_by=basis, system="50/50 mix", return_per_year_pct=r_, sharpe=s_, max_drawdown_pct=d_, total_profit_usd=(0.5 * pn[NAMES[0]] + 0.5 * pn[NAMES[1]]).sum(),
                                  trades_left=np.nan, avg_ATR_per_trade_left=np.nan, years_positive=""))
DROP = pd.DataFrame(drop_rows)
DROP.round(2).to_csv(OUT / "drop_biggest_trades.csv", index=False)
for kind, tp in SIZING_SET:
    show(f"TEST 2: remove the most profitable trades, {csize(kind, tp)}", DROP[DROP.sizing == csize(kind, tp)].drop(columns=["sizing"]).round(2))

# ================================================================== TEST 3: year blocks
rng = np.random.default_rng(20261116)
years = np.array(sorted(set(YEAR_OF_DAY.tolist())))
block = {y: np.where(YEAR_OF_DAY == y)[0] for y in years}
SERIES = {}
for kind, tp in SIZING_SET:
    SERIES[(csize(kind, tp), "frozen rule")] = BOOK[(NAMES[0], kind, tp)]["pnl"]
    SERIES[(csize(kind, tp), "earlier system")] = BOOK[(NAMES[1], kind, tp)]["pnl"]
    SERIES[(csize(kind, tp), "50/50 mix")] = mixed(kind, tp)
KEYS = list(SERIES)
NDRAW = 10000
res3 = {k: np.zeros((NDRAW, 3)) for k in KEYS}
copies_2020_2022 = np.zeros(NDRAW, int)
for it in range(NDRAW):
    pick = rng.choice(years, size=60)
    idx, tot = [], 0
    for y in pick:
        idx.append(block[y]); tot += len(block[y])
        if tot >= N_DAYS:
            break
    sel = np.concatenate(idx)[:N_DAYS]
    copies_2020_2022[it] = int(np.isin(YEAR_OF_DAY[sel], (2020, 2022)).sum() > 0)
    for k in KEYS:
        res3[k][it] = series_stats(SERIES[k][sel])
pct_rows = []
for k in KEYS:
    a = res3[k]
    for j, met in enumerate(("return_per_year_pct", "sharpe", "max_drawdown_pct")):
        q = np.nanpercentile(a[:, j], [5, 25, 50, 75, 95])
        pct_rows.append(dict(sizing=k[0], system=k[1], measure=met, p05=q[0], p25=q[1], median=q[2], p75=q[3], p95=q[4]))
    pct_rows.append(dict(sizing=k[0], system=k[1], measure="share of draws with a negative return (%)", p05=np.nan, p25=np.nan, median=(a[:, 0] < 0).mean() * 100, p75=np.nan, p95=np.nan))
PCT = pd.DataFrame(pct_rows)
pair_rows = []
for kind, tp in SIZING_SET:
    s = csize(kind, tp); fz, er, mx = res3[(s, "frozen rule")], res3[(s, "earlier system")], res3[(s, "50/50 mix")]
    pair_rows += [dict(sizing=s, question="frozen rule has the higher Sharpe than the earlier system (same drawn years)", value=(fz[:, 1] > er[:, 1]).mean() * 100, unit="% of draws"),
                  dict(sizing=s, question="frozen rule has the higher return", value=(fz[:, 0] > er[:, 0]).mean() * 100, unit="% of draws"),
                  dict(sizing=s, question="frozen rule has the shallower worst drawdown", value=(fz[:, 2] > er[:, 2]).mean() * 100, unit="% of draws"),
                  dict(sizing=s, question="50/50 mix has the higher Sharpe than the frozen rule", value=(mx[:, 1] > fz[:, 1]).mean() * 100, unit="% of draws"),
                  dict(sizing=s, question="50/50 mix has the shallower worst drawdown than the frozen rule", value=(mx[:, 2] > fz[:, 2]).mean() * 100, unit="% of draws"),
                  dict(sizing=s, question="frozen rule Sharpe in draws that contain neither 2020 nor 2022, median", value=float(np.median(fz[copies_2020_2022 == 0, 1])) if (copies_2020_2022 == 0).any() else np.nan, unit="Sharpe"),
                  dict(sizing=s, question="earlier system Sharpe in draws that contain neither 2020 nor 2022, median", value=float(np.median(er[copies_2020_2022 == 0, 1])) if (copies_2020_2022 == 0).any() else np.nan, unit="Sharpe")]
PAIR = pd.DataFrame(pair_rows)
PCT.round(2).to_csv(OUT / "year_block_resample_percentiles.csv", index=False)
PAIR.round(2).to_csv(OUT / "year_block_resample_pairs.csv", index=False)
show(f"TEST 3: year-block resample, {NDRAW:,} draws of whole calendar years (5th, 25th, median, 75th, 95th percentile of each measure)", PCT.round(2))
show(f"TEST 3: paired comparisons in the same drawn years (share of draws containing neither 2020 nor 2022: {(copies_2020_2022 == 0).mean() * 100:.1f}%)", PAIR.round(2))

loo_rows = []
for k in KEYS:
    if k[0] == csize("fractional", 0.25):
        continue
    full = SERIES[k]
    for y in years:
        keep = YEAR_OF_DAY != y
        r_, s_, d_ = series_stats(full[keep])
        loo_rows.append(dict(sizing=k[0], system=k[1], year_left_out=int(y), return_per_year_pct=r_, sharpe=s_, max_drawdown_pct=d_, profit_of_that_year_pct_of_account=full[~keep].sum() / CAPITAL * 100))
LOO = pd.DataFrame(loo_rows)
LOO.round(2).to_csv(OUT / "leave_one_year_out.csv", index=False)
piv = LOO.pivot_table(index="year_left_out", columns=["sizing", "system"], values="sharpe").round(2)
piv.columns = [f"{a.split(',')[1].strip()[:6]} | {b}" for a, b in piv.columns]
print("\n==== TEST 3: Sharpe with one calendar year left out (whole contracts only; column = % of account per ATR | system) ====")
print(piv.to_string(), flush=True)
yr_rows = {}
for k in KEYS:
    if k[0] == csize("fractional", 0.25):
        continue
    yr_rows[f"{k[0].split(',')[1].strip()[:6]} | {k[1]}"] = pd.Series(SERIES[k], index=ALLD).groupby(YEAR_OF_DAY).sum() / CAPITAL * 100
YR = pd.DataFrame(yr_rows).round(1)
YR.to_csv(OUT / "profit_by_calendar_year_pct_of_account.csv")
print("\n==== TEST 3: profit by calendar year, percent of $300k (whole contracts; column = % of account per ATR | system) ====")
print(YR.to_string(), flush=True)

# ================================================================== TEST 4: combined short-rate limit
DV01 = {"ZQ": 41.67, "SR1": 41.67, "SR3": 25.0, "ZT": 39.0}
LIMITS4 = [("current rule: 10 contracts per trade, no combined limit", CAP_SR, None), ("combined limit $250 per basis point", CAP_SR, 250.0), ("combined limit $500 per basis point", CAP_SR, 500.0),
           ("combined limit $750 per basis point", CAP_SR, 750.0), ("combined limit $1,000 per basis point", CAP_SR, 1000.0), ("combined limit $1,500 per basis point", CAP_SR, 1500.0),
           ("no limit of any kind (reference)", None, None)]


def whole_counts(sd, tp, per_trade_cap, limit):
    tgt = CAPITAL * tp / 100.0; ad = sd["ad"]
    nc = np.maximum(1.0, np.rint(tgt / ad)); al = ad <= 2 * tgt
    if per_trade_cap:
        nc = np.where(sd["is_sr"], np.minimum(nc, per_trade_cap), nc)
    cut = 0
    if limit is not None:
        open_ = []
        for i in sorted(np.where(sd["is_sr"] & al)[0], key=lambda j: (sd["ep"][j], j)):
            ep = sd["ep"][i]; per = DV01[sd["mk"][i]]; dr = sd["d"][i]
            # the limit must hold for the whole life of the new trade: positions already open may exit before it does, which leaves the new trade's exposure alone
            times = [ep] + [xp_ + 1 for (xp_, v_) in open_ if ep <= xp_ < sd["xp"][i]]
            nets = [sum(v for (xp, v) in open_ if xp >= t_) for t_ in times]
            room = int(np.floor(((limit - max(nets)) if dr > 0 else (limit + min(nets))) / per + 1e-9))
            new = float(min(nc[i], max(room, 0)))
            cut += int(new < nc[i]); nc[i] = new
            if new >= 1:
                open_.append((sd["xp"][i], dr * new * per))
    return nc, al & (nc >= 1), cut


def exposure(sd, nc, ok):
    net, gross = np.zeros(N_DAYS), np.zeros(N_DAYS)
    for i in np.where(sd["is_sr"] & ok)[0]:
        v = nc[i] * DV01[sd["mk"][i]]
        net[sd["ep"][i]:sd["xp"][i] + 1] += sd["d"][i] * v; gross[sd["ep"][i]:sd["xp"][i] + 1] += v
    return net, gross


lim_rows = []
for tp in (0.15, 0.25):
    for lname, cap_, lim_ in LIMITS4:
        pn, nt, gr = {}, {}, {}
        for nm in NAMES:
            sd = SYSTEMS[nm]
            nc, ok, cut = whole_counts(sd, tp, cap_, lim_)
            w_ = nc * sd["ad"]
            if lname.startswith("current"):
                assert np.allclose(w_[ok], BOOK[(nm, "whole contracts", tp)]["w"][ok]) and (ok == BOOK[(nm, "whole contracts", tp)]["al"]).all(), "per-trade-cap rebuild differs from the head-to-head sizing"
            pnl_, opn_, _h = daily_usd(sd["rows"], sd["d"], sd["res"], sd["held"], sd["px"], w_, ok)
            srp, _o, _h2 = daily_usd(sd["rows"], sd["d"], sd["res"], sd["held"], sd["px"], w_, ok & sd["is_sr"])
            net, gross = exposure(sd, nc, ok); pn[nm] = pnl_; nt[nm] = net; gr[nm] = gross
            if lim_ is not None:
                assert np.abs(net).max() <= lim_ + 1e-6, f"combined limit {lim_} exceeded: {np.abs(net).max():.2f}"
            st, cal = wstats(pnl_, opn_, FIRST, LAST)
            tot_usd = (sd["res"] * w_)[ok].sum(); sr_usd = (sd["res"] * w_)[ok & sd["is_sr"]].sum()
            lim_rows.append(dict(sizing=csize("whole contracts", tp), limit=lname, system=NICK[nm], return_per_year_pct=st["return_per_year_pct"], sharpe=st["sharpe"], max_drawdown_pct=st["max_drawdown_pct"],
                                 short_rate_trades_cut_down=cut, short_rate_trades_skipped=int((sd["is_sr"] & (sd["ad"] <= 2 * CAPITAL * tp / 100.0) & ~ok).sum()), highest_net_exposure_usd_per_bp=np.abs(net).max(),
                                 highest_gross_exposure_usd_per_bp=gross.max(), loss_if_50bp_move_pct_of_account=np.abs(net).max() * 50 / CAPITAL * 100, loss_if_100bp_move_pct_of_account=np.abs(net).max() * 100 / CAPITAL * 100,
                                 worst_day_of_short_rate_book_pct_of_account=srp.min() / CAPITAL * 100, short_rate_profit_usd=sr_usd, short_rate_share_of_profit_pct=sr_usd / tot_usd * 100 if tot_usd else np.nan))
        r_, s_, d_ = series_stats(0.5 * pn[NAMES[0]] + 0.5 * pn[NAMES[1]])
        netm = 0.5 * (nt[NAMES[0]] + nt[NAMES[1]]); grm = 0.5 * (gr[NAMES[0]] + gr[NAMES[1]])
        lim_rows.append(dict(sizing=csize("whole contracts", tp), limit=lname, system="50/50 mix", return_per_year_pct=r_, sharpe=s_, max_drawdown_pct=d_, short_rate_trades_cut_down=np.nan, short_rate_trades_skipped=np.nan,
                             highest_net_exposure_usd_per_bp=np.abs(netm).max(), highest_gross_exposure_usd_per_bp=grm.max(), loss_if_50bp_move_pct_of_account=np.abs(netm).max() * 50 / CAPITAL * 100,
                             loss_if_100bp_move_pct_of_account=np.abs(netm).max() * 100 / CAPITAL * 100, worst_day_of_short_rate_book_pct_of_account=np.nan, short_rate_profit_usd=np.nan, short_rate_share_of_profit_pct=np.nan))
LIM = pd.DataFrame(lim_rows)
LIM.round(2).to_csv(OUT / "short_rate_limit.csv", index=False)
for tp in (0.15, 0.25):
    show(f"TEST 4: combined short-rate limit, {csize('whole contracts', tp)}", LIM[LIM.sizing == csize("whole contracts", tp)].drop(columns=["sizing"]).round(2))
print("\nnotes: dollars per basis point per contract: Fed funds 41.67, 1-month SOFR 41.67, 3-month SOFR 25.00, 2-year note 39 (approximate). Exposure is signed (long positive, short negative); the limit applies to the net.")
print("done", f"{time.time()-t0:.0f}s")
