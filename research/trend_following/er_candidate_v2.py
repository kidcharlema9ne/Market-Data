"""Robustness tests of candidate version 2 (2 ATR initial stop, no time limit) next to the original frozen rule and the earlier system (Michael, 16 Nov 2026: "run those tests", Entry 130 next action).

Usage: python er_candidate_v2.py futures_prices.parquet report_universe_48_markets.csv OUT_DIR

Same engine, entries, costs and sizing as Entries 127 to 130 (this script executes the checked simulator part of er_stop_and_time_limit.py, which itself executes the engine of er_vs_breakout.py; the simulator and
reference checks run first and stop the script on any difference). Three versions, whole history Feb 2008 to Nov 2026, whole contracts on $300k, 0.05 ATR a side, short rates capped at 10 contracts per trade:
  original rule      = 1 ATR initial stop, 5 ATR trailing stop, 130-session limit (Entry 128)
  candidate version 2 = 2 ATR initial stop, 5 ATR trailing stop, no time limit
  earlier system     = 20-session breakout, 3 ATR stop, 3 ATR trailing stop (Entry 128)
Bet size: whole contracts at 0.15% and 0.25% of the account per ATR (the same position size for every version; a wider stop therefore risks more per stop-out).
Candidate version 2 was picked after looking at development-year results (Entry 130), and the sealed years are already used, so these tests can show weakness but cannot validate it.

1. Ten biggest trades (share of profit, when, which markets).
2. Remove the 1, 3, 5, 10 and 20 most profitable trades after the fact (nothing re-enters).
3. Year-block resample (10,000 draws of whole calendar years with replacement, seed 20261116, same years for every version in a draw); leave out 2020, 2022, and both.
4. Without short-rate futures (Fed funds, 1-month and 3-month SOFR, 2-year note), alone and also without 2020 and 2022.
"""
import os
from pathlib import Path

_SRC2 = Path(__file__).resolve().parent / "er_stop_and_time_limit.py"
_T2 = _SRC2.read_text()
_CUT2 = "# ---------------------------------------------------------------- variants\n"
assert _T2.count(_CUT2) == 1, "could not split er_stop_and_time_limit.py"
_HEAD2 = _T2.partition(_CUT2)[0]
exec(compile(_HEAD2, str(_SRC2), "exec"), globals())

VERSIONS = {"original rule": (NAMES[0], 1.0, 5.0, 130), "candidate version 2": (NAMES[0], 2.0, 5.0, None), "earlier system": (NAMES[1], 3.0, 3.0, 130)}
SIZES = [0.15, 0.25]
YEAR_OF_DAY = np.asarray(ALLD.year)
SD = {v: make_sd(*args) for v, args in VERSIONS.items()}
for _sd in SD.values():
    _sd["ad"] = _sd["atr_pct"] * REFPX[MK[_sd["rows"]]] * MULT[MK[_sd["rows"]]]
    _sd["is_sr"] = np.isin(_sd["mk"], SHORT_RATES)
BK = {}
for v, sd in SD.items():
    for tp in SIZES:
        w_, al_ = sizing(sd, "whole contracts", tp, CAP_SR)
        pnl_, opn_ = daily_pnl(sd, w_, al_)
        BK[(v, tp)] = dict(w=w_, al=al_, pnl=pnl_, opn=opn_)
GROUP2 = lambda m: "short-rate futures" if m in SHORT_RATES else GROUP_OF.get(m, "other")


def series_stats(u):
    eq = np.r_[CAPITAL, CAPITAL + np.cumsum(u)]
    peak = np.maximum.accumulate(eq)
    r = u / CAPITAL
    s = r.std()
    return (eq[-1] - CAPITAL) / CAPITAL * 100 / (len(u) / 252.0), (r.mean() / s * np.sqrt(252) if s > 0 else np.nan), ((eq - peak) / peak).min() * 100


def show(title, df):
    print(f"\n==== {title} ====")
    print(df.to_string(index=False), flush=True)


def lab(tp):
    return f"bet size {tp}% of the account per ATR"


def mix_of(tp, a="candidate version 2", b="earlier system"):
    return 0.5 * BK[(a, tp)]["pnl"] + 0.5 * BK[(b, tp)]["pnl"]


def line(label, u):
    r, s, d = series_stats(u)
    return {"version": label, "profit a year %": r, "score (Sharpe)": s, "worst losing stretch %": d, "total profit $": u.sum()}


base_rows = []
for tp in SIZES:
    for v in VERSIONS:
        x = line(v, BK[(v, tp)]["pnl"]); x["trades"] = int(BK[(v, tp)]["al"].sum()); x["bet size"] = lab(tp); base_rows.append(x)
    x = line("50/50 mix of version 2 and the earlier system", mix_of(tp)); x["trades"] = np.nan; x["bet size"] = lab(tp); base_rows.append(x)
BASE = pd.DataFrame(base_rows)[["bet size", "version", "trades", "profit a year %", "score (Sharpe)", "worst losing stretch %", "total profit $"]]
show("BASELINE, whole history", BASE.round(2))
BASE.round(3).to_csv(OUT / "baseline.csv", index=False)

# ================================================================== 1. ten biggest trades
top_all, sum_rows = [], []
for tp in SIZES:
    for v, sd in SD.items():
        b = BK[(v, tp)]; al = b["al"]
        f = pd.DataFrame(dict(market=sd["mk"], group=[GROUP2(m) for m in sd["mk"]], direction=np.where(sd["d"] > 0, "long", "short"), entry_date=sd["ed"].date, exit_date=sd["xd"].date, sessions_held=sd["held"],
                              result_ATR=sd["res"], contracts=b["w"] / sd["ad"], profit_usd=sd["res"] * b["w"], year=sd["ed"].year))[al]
        f = f.sort_values("profit_usd", ascending=False).reset_index(drop=True)
        total = f.profit_usd.sum(); t10 = f.head(10).copy()
        t10.insert(0, "rank", range(1, 11)); t10["share_of_all_profit_pct"] = t10.profit_usd / total * 100; t10.insert(0, "version", v); t10.insert(1, "bet size", lab(tp)); top_all.append(t10)
        ys = t10.year.value_counts().sort_index()
        sum_rows.append({"bet size": lab(tp), "version": v, "trades": len(f), "best ten trades' share of all profit %": t10.profit_usd.sum() / total * 100, "single best trade's share %": t10.share_of_all_profit_pct.iloc[0],
                         "profit from all other trades $": total - t10.profit_usd.sum(), "years of the best ten": ", ".join(f"{y} x{c}" for y, c in ys.items()), "short-rate trades among the ten": int((t10.group == "short-rate futures").sum()),
                         "different markets among the ten": t10.market.nunique()})
SUM1 = pd.DataFrame(sum_rows)
pd.concat(top_all, ignore_index=True).to_csv(OUT / "ten_biggest_trades.csv", index=False, float_format="%.2f")
SUM1.round(1).to_csv(OUT / "ten_biggest_summary.csv", index=False)
show("TEST 1: how much of the profit came from the ten biggest trades", SUM1.round(1))
for tp in SIZES:
    t = [x for x in top_all if x["bet size"].iloc[0] == lab(tp) and x["version"].iloc[0] == "candidate version 2"][0]
    show(f"TEST 1: candidate version 2, the ten biggest trades, {lab(tp)}", t[["rank", "market", "direction", "entry_date", "exit_date", "sessions_held", "result_ATR", "profit_usd", "share_of_all_profit_pct"]].round(2))

# ================================================================== 2. remove the most profitable trades
drop_rows = []
for tp in SIZES:
    for k in (0, 1, 3, 5, 10, 20):
        pn = {}
        for v, sd in SD.items():
            b = BK[(v, tp)]; al = b["al"].copy(); cand = np.where(al)[0]
            score = sd["res"] * b["w"]
            al[cand[np.argsort(-score[cand], kind="stable")][:k]] = False
            pn[v], _o = daily_pnl(sd, b["w"], al)
            x = line(v, pn[v]); x.update({"bet size": lab(tp), "best trades removed": k, "trades left": int(al.sum())}); drop_rows.append(x)
        x = line("50/50 mix of version 2 and the earlier system", 0.5 * pn["candidate version 2"] + 0.5 * pn["earlier system"]); x.update({"bet size": lab(tp), "best trades removed": k, "trades left": np.nan}); drop_rows.append(x)
DROP = pd.DataFrame(drop_rows)[["bet size", "best trades removed", "version", "trades left", "profit a year %", "score (Sharpe)", "worst losing stretch %", "total profit $"]]
DROP.round(3).to_csv(OUT / "drop_biggest_trades.csv", index=False)
for tp in SIZES:
    show(f"TEST 2: remove the most profitable trades, {lab(tp)}", DROP[DROP["bet size"] == lab(tp)].drop(columns=["bet size"]).round(2))

# ================================================================== 3. year-block resample, and leave years out
rng = np.random.default_rng(20261116)
years = np.array(sorted(set(YEAR_OF_DAY.tolist())))
block = {y: np.where(YEAR_OF_DAY == y)[0] for y in years}
SER = {}
for tp in SIZES:
    for v in VERSIONS:
        SER[(tp, v)] = BK[(v, tp)]["pnl"]
    SER[(tp, "50/50 mix of version 2 and the earlier system")] = mix_of(tp)
NDRAW = 10000
res3 = {k: np.zeros((NDRAW, 3)) for k in SER}
for it in range(NDRAW):
    pick = rng.choice(years, size=60); idx = []; tot = 0
    for y in pick:
        idx.append(block[y]); tot += len(block[y])
        if tot >= N_DAYS:
            break
    sel = np.concatenate(idx)[:N_DAYS]
    for k in SER:
        res3[k][it] = series_stats(SER[k][sel])
pct_rows, pair_rows = [], []
for k in SER:
    a = res3[k]
    q = lambda j: np.nanpercentile(a[:, j], [5, 50, 95])
    pr, ps, pdw = q(0), q(1), q(2)
    pct_rows.append({"bet size": lab(k[0]), "version": k[1], "profit a year %: bad draw (5th) / typical / good draw (95th)": f"{pr[0]:.1f} / {pr[1]:.1f} / {pr[2]:.1f}", "score (Sharpe): bad / typical / good": f"{ps[0]:.2f} / {ps[1]:.2f} / {ps[2]:.2f}",
                     "worst losing stretch %: bad / typical / good": f"{pdw[0]:.1f} / {pdw[1]:.1f} / {pdw[2]:.1f}", "share of draws that lost money %": (a[:, 0] < 0).mean() * 100})
for tp in SIZES:
    o, c, e, m = res3[(tp, "original rule")], res3[(tp, "candidate version 2")], res3[(tp, "earlier system")], res3[(tp, "50/50 mix of version 2 and the earlier system")]
    pair_rows += [{"bet size": lab(tp), "question": "version 2 earns more per year than the original rule", "share of draws %": (c[:, 0] > o[:, 0]).mean() * 100},
                  {"bet size": lab(tp), "question": "version 2 has the higher score (Sharpe) than the original rule", "share of draws %": (c[:, 1] > o[:, 1]).mean() * 100},
                  {"bet size": lab(tp), "question": "version 2 has the shallower worst losing stretch than the original rule", "share of draws %": (c[:, 2] > o[:, 2]).mean() * 100},
                  {"bet size": lab(tp), "question": "version 2 has the higher score (Sharpe) than the earlier system", "share of draws %": (c[:, 1] > e[:, 1]).mean() * 100},
                  {"bet size": lab(tp), "question": "the 50/50 mix has the shallower worst losing stretch than version 2 alone", "share of draws %": (m[:, 2] > c[:, 2]).mean() * 100}]
PCT, PAIR = pd.DataFrame(pct_rows), pd.DataFrame(pair_rows)
PCT.to_csv(OUT / "year_block_resample.csv", index=False); PAIR.round(1).to_csv(OUT / "year_block_pairs.csv", index=False)
show(f"TEST 3: {NDRAW:,} imagined 19-year histories built by redrawing whole calendar years", PCT.round(1))
show("TEST 3: which version wins in the same imagined histories", PAIR.round(1))
loo_rows = []
for tp in SIZES:
    for v in list(VERSIONS) + ["50/50 mix of version 2 and the earlier system"]:
        full = SER[(tp, v)]
        for lbl, out_years in (("all years", ()), ("without 2020", (2020,)), ("without 2022", (2022,)), ("without 2020 and 2022", (2020, 2022))):
            keep = ~np.isin(YEAR_OF_DAY, out_years); r, s, d = series_stats(full[keep])
            loo_rows.append({"bet size": lab(tp), "version": v, "years used": lbl, "profit a year %": r, "score (Sharpe)": s, "worst losing stretch %": d})
LOO = pd.DataFrame(loo_rows); LOO.round(3).to_csv(OUT / "leave_years_out.csv", index=False)
for tp in SIZES:
    show(f"TEST 3: take the two biggest years out, {lab(tp)}", LOO[LOO["bet size"] == lab(tp)].drop(columns=["bet size"]).round(2))
yr = {f"{v} {tp}%": pd.Series(SER[(tp, v)], index=ALLD).groupby(YEAR_OF_DAY).sum() / CAPITAL * 100 for tp in SIZES for v in ("original rule", "candidate version 2", "earlier system")}
YR = pd.DataFrame(yr).round(1); YR.to_csv(OUT / "profit_by_year_pct_of_account.csv")
print("\n==== TEST 3: profit by calendar year, percent of the $300k account ===="); print(YR.to_string(), flush=True)

# ================================================================== 4. without short-rate futures
ex_rows = []
for tp in SIZES:
    for v, sd in SD.items():
        b = BK[(v, tp)]; ok = b["al"] & ~sd["is_sr"]
        p, _o = daily_pnl(sd, b["w"], ok)
        usd = (sd["res"] * b["w"])[ok]; top = np.sort(usd)[::-1][:10]
        for lbl, keep in (("without short-rate futures", np.ones(N_DAYS, bool)), ("without short-rate futures and without 2020 and 2022", ~np.isin(YEAR_OF_DAY, (2020, 2022)))):
            x = line(v, p[keep]); x.update({"bet size": lab(tp), "which markets and years": lbl, "trades": int(ok.sum()), "best ten trades' share of profit %": (top.sum() / usd.sum() * 100) if usd.sum() > 0 else np.nan}); ex_rows.append(x)
EX = pd.DataFrame(ex_rows)[["bet size", "which markets and years", "version", "trades", "profit a year %", "score (Sharpe)", "worst losing stretch %", "best ten trades' share of profit %"]]
EX.round(3).to_csv(OUT / "without_short_rates.csv", index=False)
for tp in SIZES:
    show(f"TEST 4: without short-rate futures, {lab(tp)}", EX[EX["bet size"] == lab(tp)].drop(columns=["bet size"]).round(2))
print("done", f"{time.time()-t0:.0f}s")
