"""Position size set from the account's current value instead of a fixed $300,000 (Michael, 17 Nov 2026).

Usage: python er_equity_scaled.py futures_prices.parquet report_universe_48_markets.csv OUT_DIR

Same trades, entries, exits, costs, whole contracts, skip rule (skip when one contract's ATR dollars exceed 2x the target) and short-rate cap (10 contracts per trade) as Entries 128 and 131 (executes the checked simulator part of er_stop_and_time_limit.py).
Only change: the dollars risked per ATR on each new trade are 0.15% (or 0.25%) of the account's value at the previous close, marked to market including open trades, instead of 0.15% (or 0.25%) of the starting $300,000. Trades already open keep their size.
No cut-down rule below a peak; no other change. Rules: original frozen rule (1 ATR stop, 5 ATR trail, 130-session limit) and version 2 (2 ATR stop, 5 ATR trail, no time limit).
Checks first: sizing off the fixed $300,000 through this same trade-by-trade code reproduces the engine's sizing and the logged Entry 128 and Entry 131 rows.
Reported, whole history, development years and sealed years (read-only look; sealed years were used in Entry 122): compound growth a year, Sharpe ratio on daily returns over the prior account value, maximum drawdown; whole history also ending account value.
For the fixed-size run the logged-style numbers are also shown (profit a year as simple dollars over $300,000).
"""
import os
from pathlib import Path

_SRC3 = Path(__file__).resolve().parent / "er_stop_and_time_limit.py"
_T3 = _SRC3.read_text()
_CUT3 = "# ---------------------------------------------------------------- variants\n"
assert _T3.count(_CUT3) == 1, "could not split er_stop_and_time_limit.py"
exec(compile(_T3.partition(_CUT3)[0], str(_SRC3), "exec"), globals())

RULES = {"original rule (1 ATR stop, 130-session limit)": (NAMES[0], 1.0, 5.0, 130), "version 2 (2 ATR stop, no time limit)": (NAMES[0], 2.0, 5.0, None)}
CUT_ = pd.Timestamp("2021-08-06")
WINS = {"development years": (FIRST, CUT_), "sealed years (read-only look)": (CUT_ + pd.Timedelta(days=1), LAST), "whole history": (FIRST, LAST)}
SDX = {}
for rname, args in RULES.items():
    sd = make_sd(*args)
    sd["ad"] = sd["atr_pct"] * REFPX[MK[sd["rows"]]] * MULT[MK[sd["rows"]]]
    sd["is_sr"] = np.isin(sd["mk"], SHORT_RATES)
    sd["ep"] = ALLD.searchsorted(sd["ed"])
    streams = []                                                         # per trade: positions and daily profit per dollar of weight (dollars per ATR)
    for i in range(sd["n"]):
        r = sd["rows"][i]; mid = MK[r]; loc = r - MOFF[mid]; hh = int(sd["held"][i])
        _o, _h, _l, c, atr, dts = MKT_ARR[names[mid]]
        cum = sd["d"][i] * (c[loc + 1: loc + hh + 1] - sd["px"][i]) / atr[loc]; cum[-1] = sd["res"][i]
        streams.append((ALLD.searchsorted(pd.DatetimeIndex(dts[loc + 1: loc + hh + 1])), np.diff(np.r_[0.0, cum])))
    sd["streams"] = streams
    SDX[rname] = sd


def run(sd, tp, scale):
    """Trade-by-trade in entry order; size from the account value at the previous close when scale, else from the fixed starting amount."""
    pnl = np.zeros(N_DAYS); order = np.argsort(sd["ep"], kind="stable"); w = np.zeros(sd["n"]); taken = np.zeros(sd["n"], bool); tgts = np.zeros(sd["n"])
    for i in order:
        e = sd["ep"][i]; eq = CAPITAL + pnl[:e].sum() if scale else CAPITAL
        tgt = max(eq, 0.0) * tp / 100.0; tgts[i] = tgt; a = sd["ad"][i]
        if tgt <= 0 or a > 2 * tgt:
            continue
        nc = max(1.0, float(np.rint(tgt / a)))
        if sd["is_sr"][i]:
            nc = min(nc, CAP_SR)
        w[i] = nc * a; taken[i] = True
        pos, inc = sd["streams"][i]; pnl[pos] += inc * w[i]
    return pnl, w, taken, tgts


def stats(pnl, lo, hi):
    eq = CAPITAL + np.cumsum(pnl); prev = np.r_[CAPITAL, eq[:-1]]; sel = np.asarray((ALLD >= lo) & (ALLD <= hi))
    r = pnl[sel] / prev[sel]; n = len(r); g = np.cumprod(1 + r); pk = np.maximum.accumulate(np.r_[1.0, g])[1:]
    return dict(growth_per_year_pct=(g[-1] ** (252.0 / n) - 1) * 100, sharpe=r.mean() / r.std() * np.sqrt(252), max_drawdown_pct=((g / pk).min() - 1) * 100, ending_value=float(eq[sel][-1]) if hi == LAST else np.nan)


# ---------------------------------------------------------------- checks
for rname, sd in SDX.items():
    for tp in (0.15, 0.25):
        w0, a0 = sizing(sd, "whole contracts", tp, CAP_SR)
        pnl, w1, taken, _t = run(sd, tp, False)
        assert (a0 == taken).all() and np.allclose(w0[a0], w1[taken]), f"{rname} {tp}: fixed-size trade-by-trade sizing differs from the engine"
        p0, o0 = daily_pnl(sd, w0, a0); assert np.allclose(p0, pnl, atol=1e-6), f"{rname} {tp}: daily profit differs"
ref131 = Path(__file__).resolve().parent / "results_candidate_v2" / "baseline.csv"
if os.environ.get("ROBUSTNESS_SKIP_REFERENCE") != "1" and ref131.exists():
    r131 = pd.read_csv(ref131)
    for rname, key in (("original rule (1 ATR stop, 130-session limit)", "original rule"), ("version 2 (2 ATR stop, no time limit)", "candidate version 2")):
        for tp in (0.15, 0.25):
            sd = SDX[rname]; pnl, w, taken, _t = run(sd, tp, False); st, _c = wstats(pnl, (pnl != 0).astype(float), FIRST, LAST)
            row = r131[(r131.version == key) & (r131["bet size"] == f"bet size {tp}% of the account per ATR")].iloc[0]
            assert abs(st["return_per_year_pct"] - row["profit a year %"]) < 0.011 and abs(st["sharpe"] - row["score (Sharpe)"]) < 0.011 and abs(st["max_drawdown_pct"] - row["worst losing stretch %"]) < 0.011, f"{rname} {tp} differs from Entry 131"
    print("CHECKS PASSED: fixed-size run reproduces the engine and the logged Entry 131 rows", flush=True)
else:
    print("CHECKS (engine equality) PASSED; logged-row comparison skipped", flush=True)

rows_out = []
for rname, sd in SDX.items():
    for tp in (0.15, 0.25):
        for scale in (False, True):
            pnl, w, taken, tgts = run(sd, tp, scale)
            rec = dict(rule=rname, bet_size=f"{tp}% per ATR", sizing="fixed $300,000 (as before)" if not scale else "scaled to current account value", trades=int(taken.sum()),
                       smallest_target_pct_of_start=float(tgts[taken].min() / CAPITAL * 100), largest_target_pct_of_start=float(tgts[taken].max() / CAPITAL * 100))
            for wn, (lo, hi) in WINS.items():
                s = stats(pnl, lo, hi); rec[f"{wn}: growth a year %"] = s["growth_per_year_pct"]; rec[f"{wn}: Sharpe"] = s["sharpe"]; rec[f"{wn}: max drawdown %"] = s["max_drawdown_pct"]
                if wn == "whole history":
                    rec["ending account value $"] = s["ending_value"]
            if not scale:
                st, _c = wstats(pnl, (pnl != 0).astype(float), FIRST, LAST); rec["logged-style profit a year % (simple, over $300k)"] = st["return_per_year_pct"]
            rows_out.append(rec)
    print("done", rname, f"({time.time()-t0:.0f}s)", flush=True)
R = pd.DataFrame(rows_out); R.round(3).to_csv(OUT / "equity_scaled.csv", index=False)
pd.set_option("display.width", 300); pd.set_option("display.max_columns", 40); pd.set_option("display.max_colwidth", 50)
for rname in RULES:
    v = R[R.rule == rname].drop(columns=["rule"]); print(f"\n==== {rname} ===="); print(v.round(2).T.to_string(), flush=True)
print("done", f"{time.time()-t0:.0f}s")
