"""Initial stop width and the 130-session time limit (Michael, 16 Nov 2026: "if we expand the stop to 2 ATRs ... why do you have a time limit? I don't want to get out of a position based on a time limit").

Usage: python er_stop_and_time_limit.py futures_prices.parquet report_universe_48_markets.csv OUT_DIR

Same engine, entries, markets, costs and sizing as er_vs_breakout.py / er_robustness.py (Entries 127 to 129); the engine text is executed unchanged except for one inserted statement that keeps each market's
price arrays. The 130-session limit of the earlier runs was the length of the engine's forward window (and the longest cap of the Entry 110 grid, 60 / 90 / 130), not a tested choice. Here every trade is
simulated one at a time on the full price history of its market, so the cap can be 130, 260, 520 sessions or none (a trade then runs until its stop is hit or the data end; an open trade is marked at the last close).
Entries are the same candidate entries as before (decision days that have at least 130 later sessions), so the entry set is identical in every variant; only the exits change. One position per market is
re-applied for each variant (a longer hold blocks later entries in that market).

Variants. Frozen rule: initial stop 1, 1.5, 2, 3 ATR (trailing stop 5 ATR from the best close, unchanged) x time cap 130, 260, 520, none. Earlier system: its own stops (3 ATR initial, 3 ATR trailing) x the same caps.
Sizing: whole contracts at 0.15% and 0.25% of $300k per ATR (so a wider stop risks more per trade), and "same risk per stop-out": whole contracts at 0.15% of the account divided by the initial stop width per ATR
(so every stop-out costs about 0.15% of the account whatever the width). Short rates capped at 10 contracts per trade.
Reading rule, declared before the run: judge on the development years (2008 to Aug 2021). The sealed years were already used once (Entry 122); their figures are shown as a read-only second look and nothing is
selected on them, so no variant here can be called validated. Also reported: what the trades closed by the 130 cap did after the cap when allowed to keep running.
Checks before any new number: (1) the baseline variant (1 ATR / 5 ATR / 130) reproduces the engine's per-trade results and daily profit exactly, for both systems; (2) it matches the logged Entry 128 rows.
"""
import os
from pathlib import Path

_SRC = Path(__file__).resolve().parent / "er_vs_breakout.py"
_TXT = _SRC.read_text()
_MARK = "# ====================================================================== report section (head to head)"
_STOP = "out, yearly, daily_store = [], {}, {}"
_ANCHOR = "ATRSER[ib] = atr.copy()"
_ENGINE, _SEP, _REST = _TXT.partition(_MARK)
_DEFS = _REST.partition(_STOP)[0]
assert _SEP and _DEFS.strip() and _ENGINE.count(_ANCHOR) == 1, "could not split er_vs_breakout.py"
_ENGINE = _ENGINE.replace(_ANCHOR, _ANCHOR + "; MKT_ARR[ib] = (o.copy(), h.copy(), l.copy(), c.copy(), atr.copy(), g['file_date'].to_numpy())")
MKT_ARR = {}
exec(compile(_ENGINE + _MARK + "\n" + _DEFS, str(_SRC), "exec"), globals())

OUT = Path(out_dir)
OUT.mkdir(parents=True, exist_ok=True)
pd.set_option("display.width", 320); pd.set_option("display.max_columns", 50); pd.set_option("display.max_rows", 900); pd.set_option("display.max_colwidth", 60)
NAMES = list(SYSTEMS)
NICK = {NAMES[0]: "frozen rule", NAMES[1]: "earlier system"}
FIRST, LAST = ALLD[0], ALLD[-1]
N_DAYS = len(ALLD)
KEYS_ = {NAMES[0]: (TRENDS[0], TRIGGERS[0][0], 20), NAMES[1]: ("baseline", "20-session breakout", 20)}
CAND = {nm: dedupe_px(entries[k], k) for nm, k in KEYS_.items()}
_LISTS = {}


def lists_of(ib):
    if ib not in _LISTS:
        o, h, l, c, atr, dts = MKT_ARR[ib]
        _LISTS[ib] = (o.tolist(), h.tolist(), l.tolist(), c.tolist(), atr.tolist())
    return _LISTS[ib]


def sim_one(ib, loc, d, entry, init, trail, cap):
    """One trade on the full history of its market. Session loc+1 is the entry session (entry price = its open). Same stop logic as sim_init of er_vs_breakout.py."""
    o, h, l, c, atr = lists_of(ib)
    n = len(c)
    a0 = atr[loc]
    stop = entry - d * init * a0
    best = entry
    last = min(n - 1, loc + cap) if cap else n - 1
    for t in range(loc + 1, last + 1):
        k = t - (loc + 1)
        if (l[t] <= stop) if d > 0 else (h[t] >= stop):
            gap = k > 0 and ((o[t] <= stop) if d > 0 else (o[t] >= stop))
            px = o[t] if gap else stop
            return d * (px - entry) / a0 - COST_RT, k + 1, "stop"
        ct = c[t]
        best = max(best, ct) if d > 0 else min(best, ct)
        at = atr[t]
        if at == at:
            new = best - d * trail * at
            stop = max(stop, new) if d > 0 else min(stop, new)
        if t == last:
            return d * (ct - entry) / a0 - COST_RT, k + 1, ("time" if (cap and t == loc + cap) else "data_end")


_SIMS = {}


def simulate(nm, init, trail, cap):
    key = (nm, init, trail, cap)
    if key not in _SIMS:
        rows, d, px = CAND[nm]
        res = np.empty(len(rows)); held = np.empty(len(rows), int); why = np.empty(len(rows), "U8")
        for i in range(len(rows)):
            mid = MK[rows[i]]
            res[i], held[i], why[i] = sim_one(names[mid], rows[i] - MOFF[mid], d[i], px[i], init, trail, cap)
        _SIMS[key] = (res, held, why)
    return _SIMS[key]


def make_sd(nm, init, trail, cap):
    rows, d, px = CAND[nm]
    res, held, why = simulate(nm, init, trail, cap)
    kp = nonoverlap(rows, held)
    rr = rows[kp]
    sd = dict(rows=rr, d=d[kp], res=res[kp], held=held[kp], px=px[kp], why=why[kp], mk=mkt_names[rr], atr_pct=ATR0[rr] / px[kp], n=int(kp.sum()))
    ed, xd = [], []
    for i, r_ in enumerate(rr):
        mid = MK[r_]; loc = r_ - MOFF[mid]
        ed.append(MDATES[mid][loc + 1]); xd.append(MDATES[mid][loc + int(sd["held"][i])])
    sd["ed"], sd["xd"] = pd.DatetimeIndex(ed), pd.DatetimeIndex(xd)
    return sd


def daily_pnl(sd, w, mask):
    """Daily mark-to-market dollars on the full history (closes from the market arrays), same bookkeeping as daily_usd of the engine."""
    pnl = np.zeros(N_DAYS); opn = np.zeros(N_DAYS)
    for i in np.where(mask)[0]:
        r = sd["rows"][i]; mid = MK[r]; loc = r - MOFF[mid]; hh = int(sd["held"][i]); dn = sd["d"][i]; en = sd["px"][i]
        _o, _h, _l, c, atr, dts = MKT_ARR[names[mid]]
        a0 = atr[loc]
        cum = dn * (c[loc + 1: loc + hh + 1] - en) / a0
        cum[-1] = sd["res"][i]
        inc = np.diff(np.r_[0.0, cum]) * w[i]
        pos = ALLD.searchsorted(pd.DatetimeIndex(dts[loc + 1: loc + hh + 1]))
        pnl[pos] += inc; opn[pos] += 1
    return pnl, opn


# ---------------------------------------------------------------- checks: the simulator reproduces the engine, then the logged rows
for nm in NAMES:
    init, trail = (1.0, 5.0) if nm == NAMES[0] else (3.0, 3.0)
    sd = make_sd(nm, init, trail, 130); ref_sd = SYSTEMS[nm]
    assert len(sd["rows"]) == len(ref_sd["rows"]) and (sd["rows"] == ref_sd["rows"]).all(), f"{nm}: trade list differs from the engine"
    assert np.allclose(sd["res"], ref_sd["res"], atol=1e-9) and (sd["held"] == ref_sd["held"]).all(), f"{nm}: per-trade results differ from the engine"
    for kind, tp in (("whole contracts", 0.15), ("whole contracts", 0.25)):
        w1, a1 = sizing(sd, kind, tp, CAP_SR)
        p1, _o1 = daily_pnl(sd, w1, a1)
        p0, _o0, _h0 = daily_usd(ref_sd["rows"], ref_sd["d"], ref_sd["res"], ref_sd["held"], ref_sd["px"], w1, a1)
        assert np.allclose(p1, p0, atol=1e-6), f"{nm}: daily profit differs from the engine"
print("SIMULATOR CHECK PASSED: 1 ATR / 5 ATR / 130 (frozen) and 3 ATR / 3 ATR / 130 (earlier) reproduce the engine's trades, results and daily profit exactly", flush=True)

ref_file = Path(__file__).resolve().parent / "results_vs_breakout" / "head_to_head_summary.csv"
CUT_ = pd.Timestamp("2021-08-06")
if os.environ.get("ROBUSTNESS_SKIP_REFERENCE") == "1" or not ref_file.exists():
    print("REFERENCE CHECK SKIPPED", flush=True)
else:
    ref = pd.read_csv(ref_file)
    for nm in NAMES:
        init, trail = (1.0, 5.0) if nm == NAMES[0] else (3.0, 3.0)
        sd = make_sd(nm, init, trail, 130)
        for kind, tp in (("whole contracts", 0.15), ("whole contracts", 0.25)):
            w1, a1 = sizing(sd, kind, tp, CAP_SR); p1, o1 = daily_pnl(sd, w1, a1); st, _c = wstats(p1, o1, FIRST, LAST)
            row = ref[(ref.system == nm) & (ref.sizing == f"{kind} {tp}% per ATR, short rates capped at {CAP_SR} contracts") & (ref.markets == "all 46 markets") & (ref.window == "whole history")].iloc[0]
            for key_ in ("return_per_year_pct", "sharpe", "max_drawdown_pct"):
                assert abs(st[key_] - row[key_]) < 0.011, f"REFERENCE MISMATCH {nm} {kind} {tp} {key_}: {st[key_]:.4f} vs logged {row[key_]:.4f}"
    print("REFERENCE CHECK PASSED: whole-history return, Sharpe and drawdown match Entry 128", flush=True)

# ---------------------------------------------------------------- variants
CAPS = [(130, "130 sessions (as before)"), (260, "260 sessions"), (520, "520 sessions"), (None, "no time limit")]
VARIANTS = [(NAMES[0], init, 5.0, cap, cl) for init in (1.0, 1.5, 2.0, 3.0) for cap, cl in CAPS] + [(NAMES[1], 3.0, 3.0, cap, cl) for cap, cl in CAPS]
WINS = {"development": (FIRST, CUT_), "sealed (read-only look)": (CUT_ + pd.Timedelta(days=1), LAST), "whole history": (FIRST, LAST)}
SIZE_SET = [("same dollars per ATR", "whole contracts", 0.15), ("same dollars per ATR", "whole contracts", 0.25), ("same risk per stop-out", "whole contracts", 0.15)]
rows_out = []
for nm, init, trail, cap, cl in VARIANTS:
    sd = make_sd(nm, init, trail, cap)
    for sname, kind, tp in SIZE_SET:
        tp_eff = tp / init if sname == "same risk per stop-out" else tp
        w_, al = sizing(sd, kind, tp_eff, CAP_SR)
        pnl_, opn_ = daily_pnl(sd, w_, al)
        usd = (sd["res"] * w_)[al]; top = np.sort(usd)[::-1][:10]
        rec = dict(system=NICK[nm], initial_stop_ATR=init, trailing_stop_ATR=trail, time_limit=cl, sizing=f"{sname}: {tp}% of the account" + (" divided by the stop width" if sname.startswith("same risk") else " per ATR"),
                   trades=int(al.sum()), win_rate_pct=float((sd["res"][al] > 0).mean() * 100), avg_sessions_held=float(sd["held"][al].mean()), closed_by_time_limit=int(((sd["why"] == "time") & al).sum()),
                   still_open_at_data_end=int(((sd["why"] == "data_end") & al).sum()), top10_share_of_profit_pct=float(top.sum() / usd.sum() * 100) if usd.sum() > 0 else np.nan, total_profit_usd=float(usd.sum()))
        for wn, (lo, hi) in WINS.items():
            st, _c = wstats(pnl_, opn_, lo, hi)
            rec[f"{wn}: return a year %"] = st["return_per_year_pct"]; rec[f"{wn}: Sharpe"] = st["sharpe"]; rec[f"{wn}: worst drawdown %"] = st["max_drawdown_pct"]
            if wn == "whole history":
                rec["longest_time_under_water_sessions"] = st["longest_underwater_sessions"]; rec["years_positive_whole_history"] = st["years_positive"]
        rows_out.append(rec)
    print("done", NICK[nm], init, trail, cl, f"({time.time()-t0:.0f}s)", flush=True)
R = pd.DataFrame(rows_out)
R.round(3).to_csv(OUT / "stop_and_time_limit_variants.csv", index=False)
show_cols = ["initial_stop_ATR", "time_limit", "trades", "win_rate_pct", "avg_sessions_held", "closed_by_time_limit", "still_open_at_data_end", "development: return a year %", "development: Sharpe", "development: worst drawdown %",
             "sealed (read-only look): return a year %", "sealed (read-only look): Sharpe", "whole history: return a year %", "whole history: Sharpe", "whole history: worst drawdown %", "top10_share_of_profit_pct", "longest_time_under_water_sessions"]
for system in ("frozen rule", "earlier system"):
    for sz in R.sizing.unique():
        v = R[(R.system == system) & (R.sizing == sz)][show_cols].copy()
        v.columns = ["initial stop", "time limit", "trades", "win %", "avg held", "closed by limit", "open at end", "dev ret/yr", "dev Sharpe", "dev drawdown", "sealed ret/yr", "sealed Sharpe", "whole ret/yr", "whole Sharpe", "whole drawdown", "top-ten share %", "longest under water"]
        print(f"\n==== {system} | {sz} ===="); print(v.round(2).to_string(index=False), flush=True)

# ---------------------------------------------------------------- what the trades closed by the 130 cap did next, when allowed to run (same entries, same stops)
cut_rows = []
for nm, init, trail in ((NAMES[0], 1.0, 5.0), (NAMES[0], 2.0, 5.0), (NAMES[1], 3.0, 3.0)):
    r130, h130, w130 = simulate(nm, init, trail, 130); rno, hno, wno = simulate(nm, init, trail, None)
    cut = w130 == "time"
    extra = rno[cut] - r130[cut]
    cut_rows.append(dict(system=NICK[nm], initial_stop_ATR=init, candidate_entries=len(r130), closed_by_130_cap=int(cut.sum()), avg_ATR_result_at_the_cap=float(r130[cut].mean()),
                         avg_ATR_added_by_letting_them_run=float(extra.mean()), median_ATR_added=float(np.median(extra)), share_that_added_profit_pct=float((extra > 0).mean() * 100), share_that_gave_back_pct=float((extra < 0).mean() * 100),
                         total_ATR_added=float(extra.sum()), best_ten_additions_ATR=float(np.sort(extra)[::-1][:10].sum()), avg_extra_sessions=float((hno[cut] - h130[cut]).mean())))
CUTDF = pd.DataFrame(cut_rows)
CUTDF.round(2).to_csv(OUT / "trades_cut_by_the_130_cap.csv", index=False)
print("\n==== trades closed by the 130 cap: what letting them run added (ATR per trade, all candidate entries before the one-position rule) ===="); print(CUTDF.round(2).to_string(index=False), flush=True)
print("done", f"{time.time()-t0:.0f}s")
