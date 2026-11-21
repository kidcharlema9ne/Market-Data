"""Futures trend system with a 4 ATR initial stop and a 5 ATR trailing stop, real daily returns, and their correlation with the COT gap system (Michael, 21 Nov 2026:
"Use a 4 ATR stop and a 5 ATR trailing stop, and then let's check the correlation.").

Usage: python er_four_atr_corr.py futures_prices.parquet report_universe_48_markets.csv OUT_DIR cot_gap_daily_returns.csv

Declared before the run:
- Trend system = the frozen efficiency-ratio rule, engine text executed unchanged (via er_stop_and_time_limit.py header): 20-session efficiency ratio at least 0.50, 2.5 ATR pullback, next-open entry,
  46 markets, cost 0.05 ATR a side, one position per market, whole contracts at 0.25% of $300,000 per ATR, short rates capped at 10 contracts.
- Only the exits change: initial stop 4 ATR, trailing stop 5 ATR from the best close, NO time limit (an open trade is marked at the last close). The original 1 ATR / 5 ATR / 130 run is repeated alongside for comparison.
- Daily return = daily mark-to-market dollars divided by $300,000.
- COT gap system = results_export file (normal size, $1M account, 4 ATR stop, 21-session exit, entries from 2008-12-30).
- Correlations: plain Pearson on daily, weekly (Friday), monthly, quarterly and calendar-year returns over the common dates, by development / sealed split (2021-08-06), by calendar year (daily), rolling 36 months of monthly returns.
- Check before any number: the original 1 ATR / 5 ATR / 130 run reproduces the engine's trades and daily profit exactly.
"""
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_TXT = (_HERE / "er_stop_and_time_limit.py").read_text()
_CUT = "# ---------------------------------------------------------------- checks"
_HEAD = _TXT.partition(_CUT)[0]
assert _HEAD.strip() and _CUT in _TXT
exec(compile(_HEAD, str(_HERE / "er_stop_and_time_limit.py"), "exec"), globals())

COT_FILE = sys.argv[4]
nm0 = NAMES[0]

# ---- check: original run reproduces the engine
sd = make_sd(nm0, 1.0, 5.0, 130); ref_sd = SYSTEMS[nm0]
assert len(sd["rows"]) == len(ref_sd["rows"]) and (sd["rows"] == ref_sd["rows"]).all()
assert np.allclose(sd["res"], ref_sd["res"], atol=1e-9) and (sd["held"] == ref_sd["held"]).all()
w1, a1 = sizing(sd, "whole contracts", 0.25, CAP_SR)
p1, _o1 = daily_pnl(sd, w1, a1)
p0, _o0, _h0 = daily_usd(ref_sd["rows"], ref_sd["d"], ref_sd["res"], ref_sd["held"], ref_sd["px"], w1, a1)
assert np.allclose(p1, p0, atol=1e-6)
print("CHECK PASSED: original 1 ATR / 5 ATR / 130 run reproduces the engine's trades and daily profit exactly", flush=True)

RUNS = {"original (1 ATR initial, 5 ATR trailing, 130-session limit)": (1.0, 5.0, 130),
        "new (4 ATR initial, 5 ATR trailing, no time limit)": (4.0, 5.0, None)}
daily = pd.DataFrame(index=ALLD)
summary = []
for label, (init, trail, cap) in RUNS.items():
    sdv = make_sd(nm0, init, trail, cap)
    w_, al = sizing(sdv, "whole contracts", 0.25, CAP_SR)
    pnl_, opn_ = daily_pnl(sdv, w_, al)
    usd = (sdv["res"] * w_)[al]
    short = "orig" if cap else "new"
    daily[f"profit_usd_{short}"] = pnl_
    daily[f"return_{short}"] = pnl_ / CAPITAL
    daily[f"open_trades_{short}"] = opn_
    for wn, (lo, hi) in WINS.items():
        st, _c = wstats(pnl_, opn_, lo, hi)
        summary.append(dict(run=label, window=wn, trades=int(al.sum()), win_rate_pct=float((sdv["res"][al] > 0).mean() * 100), avg_sessions_held=float(sdv["held"][al].mean()),
                            still_open_at_end=int(((sdv["why"] == "data_end") & al).sum()), **{k: st[k] for k in ("return_per_year_pct", "sharpe", "max_drawdown_pct")}))
S = pd.DataFrame(summary)
S.round(3).to_csv(OUT / "four_atr_summary.csv", index=False)
print("\n==== trend system, whole contracts 0.25% of $300k per ATR ===="); print(S.round(2).to_string(index=False), flush=True)
daily.index.name = "date"
daily.round(8).to_csv(OUT / "trend_daily_returns.csv")

# ---- correlation with the COT gap system
cot = pd.read_csv(COT_FILE, parse_dates=["date"]).set_index("date")
cot = cot[["return_normal_size", "return_double_size"]]
J = daily.join(cot, how="inner")
J = J[J.index >= pd.Timestamp("2008-12-30")]
print(f"\ncommon days: {len(J)} from {J.index[0].date()} to {J.index[-1].date()}", flush=True)


def comp(x):
    return (1 + x).prod() - 1


def agg(df, rule):
    return df.groupby(pd.Grouper(freq=rule)).agg({"return_orig": comp, "return_new": comp, "return_normal_size": comp})


def corr_row(df, label):
    out = dict(period=label, n=len(df))
    if len(df) > 5:
        out["new_vs_COT"] = df["return_new"].corr(df["return_normal_size"])
        out["orig_vs_COT"] = df["return_orig"].corr(df["return_normal_size"])
    return out


rows = []
for lab, rule in (("daily", None), ("weekly", "W-FRI"), ("monthly", "ME"), ("quarterly", "QE"), ("calendar year", "YE")):
    d_ = J if rule is None else agg(J, rule)
    rows.append(corr_row(d_, lab))
CT = pd.DataFrame(rows)
print("\n==== correlation with the COT gap system, whole common period ===="); print(CT.round(3).to_string(index=False), flush=True)

CUT2 = pd.Timestamp("2021-08-06")
rows = []
for lab, d_ in (("through Aug 2021", J[J.index <= CUT2]), ("after Aug 2021", J[J.index > CUT2])):
    for freq, rule in (("daily", None), ("monthly", "ME")):
        x = d_ if rule is None else agg(d_, rule)
        r_ = corr_row(x, f"{lab}, {freq}"); rows.append(r_)
CS = pd.DataFrame(rows)
print("\n==== split by period ===="); print(CS.round(3).to_string(index=False), flush=True)

rows = []
for y, g in J.groupby(J.index.year):
    r_ = corr_row(g, str(y)); rows.append(r_)
CY = pd.DataFrame(rows)
print("\n==== daily correlation by calendar year ===="); print(CY.round(3).to_string(index=False), flush=True)

M = agg(J, "ME")
roll = pd.DataFrame({"new_vs_COT": M["return_new"].rolling(36).corr(M["return_normal_size"]), "orig_vs_COT": M["return_orig"].rolling(36).corr(M["return_normal_size"])}).dropna()
print("\n==== rolling 36 months of monthly returns: range and latest ====")
print(roll.describe().loc[["min", "mean", "max"]].round(3).to_string()); print("latest", roll.index[-1].date(), roll.iloc[-1].round(3).to_dict(), flush=True)
roll.iloc[::6].round(3).to_csv(OUT / "rolling_36m.csv")

# combined portfolio: simple add of the two return streams (each at its own sizing), compared with each alone
comb = J["return_new"] + J["return_normal_size"]
def dd(r):
    e = (1 + r).cumprod(); return float((e / e.cummax() - 1).min() * 100)
yrs = len(J) / 252
print("\n==== for scale: each system alone and the two added together (each at normal size, simple sum of daily returns) ====")
for lab, r in (("trend new", J["return_new"]), ("COT gap", J["return_normal_size"]), ("both added", comb)):
    print(f"{lab}: {((1+r).prod()**(1/yrs)-1)*100:.2f}% a year, daily-return Sharpe {r.mean()/r.std()*np.sqrt(252):.2f}, worst drawdown {dd(r):.1f}%")
CT.round(3).to_csv(OUT / "correlations_whole_period.csv", index=False); CS.round(3).to_csv(OUT / "correlations_by_period.csv", index=False); CY.round(3).to_csv(OUT / "correlations_by_year.csv", index=False)
print("done", f"{time.time()-t0:.0f}s")
