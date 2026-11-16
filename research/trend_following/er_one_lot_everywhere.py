"""At least one contract in every market (Michael, 16 Nov 2026): size to 0.25% (and 0.15%) of the account per ATR as before, but never skip a market because one contract is too big; ETF stand-ins where a US ETF exists (platinum etc.).

Usage: python er_one_lot_everywhere.py futures_prices.parquet report_universe_48_markets.csv OUT_DIR

Same engine, entries, exits, costs and short-rate cap (10 contracts per trade) as Entries 127 to 131 (executes the checked simulator part of er_stop_and_time_limit.py). Two rules: the original frozen rule (1 ATR initial stop, 5 ATR
trailing stop, 130-session limit) and candidate version 2 (2 ATR initial stop, 5 ATR trailing stop, no time limit). Current sizing: contracts = target dollars per ATR / one contract's ATR in dollars, rounded, at least 1; a trade is SKIPPED when one
contract's ATR is more than twice the target ("too big"). Variants of that skip rule, all else equal:
  current rule: skip when one contract is more than 2x the target
  allow one contract up to 3x, 4x, 6x, 10x the target
  one contract in every market (no limit), futures only
  one contract in every market, but trades that are too big use a fully paid ETF stand-in where a US ETF exists (platinum PPLT, Brent BNO, gasoline UGA, silver SLV, gold GLD, wheat WEAT, soybeans SOYB, Swiss franc FXF, euro FXE, Nasdaq QQQ,
  long bonds TLT and EDV), sized exactly to the target, total ETF cash capped at $150k, simulated on the futures' percent moves (no tracking error, roll drag or fees); markets with no US ETF (heating oil, feeder cattle, coffee, cocoa) or no cash room take one futures contract.
Micro contracts are those already used by the engine (ES 5, NQ 2, GC 10, CL 100, SI 1000, RTY 5); none added. Reported per rule, bet size and variant: profit a year, steadiness score (Sharpe) and worst fall in development years, sealed years (read-only look; the
sealed years were used in Entry 122, so nothing here is validated) and the whole history; the trades added, their profit and average ATR result, the largest single position risk (dollars per ATR as a share of the account) and the average and highest total
risk open at once; and, for one contract everywhere at 0.25%, a table by market of what the added trades did.
Checks first: the current-rule variant reproduces the engine's sizing exactly, and the baseline matches the logged Entry 128 and Entry 131 rows.
"""
import os
from pathlib import Path

_SRC3 = Path(__file__).resolve().parent / "er_stop_and_time_limit.py"
_T3 = _SRC3.read_text()
_CUT3 = "# ---------------------------------------------------------------- variants\n"
assert _T3.count(_CUT3) == 1, "could not split er_stop_and_time_limit.py"
exec(compile(_T3.partition(_CUT3)[0], str(_SRC3), "exec"), globals())

ETF_OK = {"PL": "PPLT", "BZ": "BNO", "RB": "UGA", "UB": "EDV", "ZB": "TLT", "SI": "SLV", "ZW": "WEAT", "ZS": "SOYB", "6S": "FXF", "6E": "FXE", "NQ": "QQQ", "GC": "GLD"}
ETF_CAP = 150_000.0
RULES = {"original rule (1 ATR stop, 130-session limit)": (NAMES[0], 1.0, 5.0, 130), "version 2 (2 ATR stop, no time limit)": (NAMES[0], 2.0, 5.0, None)}
SDX = {}
for rname, args in RULES.items():
    sd = make_sd(*args)
    sd["ad"] = sd["atr_pct"] * REFPX[MK[sd["rows"]]] * MULT[MK[sd["rows"]]]
    sd["is_sr"] = np.isin(sd["mk"], SHORT_RATES)
    sd["ep"], sd["xp"] = ALLD.searchsorted(sd["ed"]), ALLD.searchsorted(sd["xd"])
    SDX[rname] = sd
CUT_ = pd.Timestamp("2021-08-06")
WINS = {"development years": (FIRST, CUT_), "sealed years (read-only look)": (CUT_ + pd.Timedelta(days=1), LAST), "whole history": (FIRST, LAST)}
VARIANTS = [("current rule: skip when one contract is more than 2x the bet", 2.0, False), ("allow one contract up to 3x the bet", 3.0, False), ("allow one contract up to 4x the bet", 4.0, False),
            ("allow one contract up to 6x the bet", 6.0, False), ("allow one contract up to 10x the bet", 10.0, False), ("one contract in every market (no limit), futures only", None, False),
            ("one contract in every market, ETF stand-ins where a US ETF exists", None, True)]


def book(sd, tp, cutoff, etf):
    tgt = CAPITAL * tp / 100.0; ad = sd["ad"]; n = len(ad)
    nc = np.maximum(1.0, np.rint(tgt / ad)); nc = np.where(sd["is_sr"], np.minimum(nc, CAP_SR), nc)
    w = nc * ad
    too_big = ad > 2 * tgt                                              # skipped by the current rule
    allowed = np.ones(n, bool) if cutoff is None else (ad <= cutoff * tgt)
    is_etf = np.zeros(n, bool); peak_cash = 0.0
    if etf:
        notional = tgt / sd["atr_pct"]; load = np.zeros(N_DAYS)
        cand = np.where(too_big & np.isin(sd["mk"], list(ETF_OK)))[0]
        for i in cand[np.argsort(sd["ep"][cand], kind="stable")]:
            if load[sd["ep"][i]:sd["xp"][i] + 1].max() + notional[i] <= ETF_CAP:
                load[sd["ep"][i]:sd["xp"][i] + 1] += notional[i]; is_etf[i] = True
        w = np.where(is_etf, tgt, w); peak_cash = float(load.max())
    return w, allowed, too_big, is_etf, nc, peak_cash


# ---------------------------------------------------------------- checks: current-rule variant equals the engine's sizing; baselines match logged rows
for rname, sd in SDX.items():
    for tp in (0.15, 0.25):
        w0, a0 = sizing(sd, "whole contracts", tp, CAP_SR)
        w1, a1, _tb, _e, _nc, _pc = book(sd, tp, 2.0, False)
        assert (a0 == a1).all() and np.allclose(w0[a0], w1[a1]), f"{rname} {tp}: current-rule sizing differs from the engine"
ref131 = Path(__file__).resolve().parent / "results_candidate_v2" / "baseline.csv"
if os.environ.get("ROBUSTNESS_SKIP_REFERENCE") != "1" and ref131.exists():
    r131 = pd.read_csv(ref131)
    for rname, key in (("original rule (1 ATR stop, 130-session limit)", "original rule"), ("version 2 (2 ATR stop, no time limit)", "candidate version 2")):
        for tp in (0.15, 0.25):
            sd = SDX[rname]; w1, a1, *_ = book(sd, tp, 2.0, False); p1, o1 = daily_pnl(sd, w1, a1); st, _c = wstats(p1, o1, FIRST, LAST)
            row = r131[(r131.version == key) & (r131["bet size"] == f"bet size {tp}% of the account per ATR")].iloc[0]
            assert abs(st["return_per_year_pct"] - row["profit a year %"]) < 0.011 and abs(st["sharpe"] - row["score (Sharpe)"]) < 0.011 and abs(st["max_drawdown_pct"] - row["worst losing stretch %"]) < 0.011, f"{rname} {tp} differs from Entry 131"
    print("CHECKS PASSED: current-rule sizing equals the engine; baselines match Entries 128 and 131", flush=True)
else:
    print("CHECKS (engine equality) PASSED; logged-row comparison skipped", flush=True)

rows_out, mkt_rows = [], []
for rname, sd in SDX.items():
    for tp in (0.15, 0.25):
        tgt = CAPITAL * tp / 100.0
        for vname, cutoff, etf in VARIANTS:
            w, allowed, too_big, is_etf, nc, peak_cash = book(sd, tp, cutoff, etf)
            pnl_, opn_ = daily_pnl(sd, w, allowed)
            heat = np.zeros(N_DAYS)
            for i in np.where(allowed)[0]:
                heat[sd["ep"][i]:sd["xp"][i] + 1] += w[i]
            added = allowed & too_big
            usd = sd["res"] * w
            rec = dict(rule=rname, bet_size=f"{tp}% of the account per ATR", variant=vname, trades=int(allowed.sum()), trades_added_vs_current_rule=int(added.sum()), of_which_ETF=int(is_etf.sum()),
                       profit_of_added_trades_usd=float(usd[added].sum()), avg_ATR_result_of_added_trades=float(sd["res"][added].mean()) if added.any() else np.nan,
                       share_of_added_trades_that_made_money_pct=float((sd["res"][added] > 0).mean() * 100) if added.any() else np.nan,
                       largest_single_position_risk_pct_of_account_per_ATR=float(w[allowed].max() / CAPITAL * 100), average_total_risk_open_pct_of_account_per_ATR=float(heat.mean() / CAPITAL * 100),
                       highest_total_risk_open_pct_of_account_per_ATR=float(heat.max() / CAPITAL * 100), peak_ETF_cash_usd=peak_cash)
            for wn, (lo, hi) in WINS.items():
                st, _c = wstats(pnl_, opn_, lo, hi)
                rec[f"{wn}: profit a year %"] = st["return_per_year_pct"]; rec[f"{wn}: Sharpe"] = st["sharpe"]; rec[f"{wn}: worst fall %"] = st["max_drawdown_pct"]
                if wn == "whole history":
                    rec["years positive (whole history)"] = st["years_positive"]; rec["longest time below a prior peak (sessions)"] = st["longest_underwater_sessions"]
            top = np.sort(usd[allowed])[::-1][:10]; rec["best ten trades' share of profit %"] = float(top.sum() / usd[allowed].sum() * 100) if usd[allowed].sum() > 0 else np.nan
            rows_out.append(rec)
            if tp == 0.25 and vname.startswith("one contract in every market (no limit)") or (tp == 0.25 and etf):
                for m_ in sorted(set(sd["mk"][too_big])):
                    sel = too_big & (sd["mk"] == m_)
                    mkt_rows.append(dict(rule=rname, variant=vname, market=m_, group=GROUP_OF.get(m_, "other"), trades=int(sel.sum()), of_which_ETF=int((is_etf & sel).sum()), avg_ATR_result=float(sd["res"][sel].mean()),
                                         share_that_made_money_pct=float((sd["res"][sel] > 0).mean() * 100), profit_usd=float(usd[sel].sum()), median_one_contract_ATR_pct_of_account=float(np.median(sd["ad"][sel]) / CAPITAL * 100)))
    print("done", rname, f"({time.time()-t0:.0f}s)", flush=True)
R = pd.DataFrame(rows_out)
R.round(3).to_csv(OUT / "one_lot_everywhere_variants.csv", index=False)
M = pd.DataFrame(mkt_rows)
M.round(2).to_csv(OUT / "added_markets_at_0.25pct.csv", index=False)
pd.set_option("display.width", 330); pd.set_option("display.max_columns", 50); pd.set_option("display.max_rows", 900); pd.set_option("display.max_colwidth", 70)
cols = ["variant", "trades", "trades_added_vs_current_rule", "of_which_ETF", "development years: profit a year %", "development years: Sharpe", "development years: worst fall %", "sealed years (read-only look): profit a year %", "sealed years (read-only look): Sharpe",
        "whole history: profit a year %", "whole history: Sharpe", "whole history: worst fall %", "profit_of_added_trades_usd", "avg_ATR_result_of_added_trades", "largest_single_position_risk_pct_of_account_per_ATR", "average_total_risk_open_pct_of_account_per_ATR",
        "highest_total_risk_open_pct_of_account_per_ATR", "best ten trades' share of profit %"]
short = ["variant", "trades", "added", "ETF", "dev %/yr", "dev Sharpe", "dev fall", "sealed %/yr", "sealed Sharpe", "whole %/yr", "whole Sharpe", "whole fall", "added profit $", "added avg ATR", "biggest 1 position risk %", "avg risk open %", "max risk open %", "top10 share %"]
for rname in RULES:
    for tp in (0.15, 0.25):
        v = R[(R.rule == rname) & (R.bet_size == f"{tp}% of the account per ATR")][cols].copy(); v.columns = short; v["variant"] = v.variant.str.slice(0, 62)
        print(f"\n==== {rname} | bet size {tp}% of the account per ATR ===="); print(v.round(2).to_string(index=False), flush=True)
for rname in RULES:
    g = M[(M.rule == rname) & M.variant.str.startswith("one contract in every market (no limit)")].sort_values("profit_usd", ascending=False)
    print(f"\n==== markets added back by one contract everywhere, {rname}, bet size 0.25% ===="); print(g.drop(columns=["rule", "variant"]).round(2).to_string(index=False), flush=True)
print("done", f"{time.time()-t0:.0f}s")
