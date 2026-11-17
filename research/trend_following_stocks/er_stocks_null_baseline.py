"""Stocks, long only: where does the edge come from? Random-entry baseline and low efficiency ratio thresholds (Michael, 17 Nov 2026; next action in the hand-off doc).
Usage: python er_stocks_null_baseline.py stock_prices.parquet OUT_DIR spy_prices.parquet MODE ARG
  MODE thresholds  ARG like 0.0,0.1,0.2,0.5   : the current rule (1.5 ATR pullback) with the efficiency ratio threshold that starts a watch changed (0.50 is the reference row).
  MODE random      ARG = number of random draws (seeds): buy strong stocks on random days, no efficiency ratio and no pullback, number of trades calibrated to the reference rule.
Fixed in both modes (the current best rule, hand-off doc 17 Nov 2026): common stocks, one series per company, $3M floor, strongest 20% by 126-session return, long only, SPY above its 200-session average for entries
(no band, open positions are not closed when SPY falls below), 4 ATR initial stop, 5 ATR trailing stop from the best close, no time limit, no rotation, 0.05 ATR a side, 0.10% of $300k per ATR, caps 200% and 100%.
Threshold mode: efficiency ratio over 20 sessions at or above the threshold with a rising 20-session close starts a 20-session watch, buy the next open after a close 1.5 ATR below the best high since the signal.
Random mode: every eligible stock-day (strongest 20%, liquid, not a SPAC shell, SPY above its 200-day average, valid ATR) is equally likely to be an entry; the entry is the next open. The chance per day is set so the number of trades
(after the one-position-per-stock rule) matches the reference rule's number of trades; many seeds show the spread. A stock already in a position is skipped, as in the real rule.
Benchmark (D-053 style, approximate): SPY close on the entry session to SPY close on the exit session, times entry price, divided by the fixed 20-session ATR at the signal (stock ATR units). Close to close, not the fill prices.
Post hoc on development years; the best row is not a result. Data through 2021-08-06 only; the sealed years are not read.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
import pandas as pd

import er_stocks as B
import er_stocks_common_momentum as M
from er_stocks import END, EPOCH, MAIN_START, FIRST_TRADE
from er_stocks_market_band import switch
from er_stocks_er_grid import er_dr, long_cands

VNAME = "initial stop 4 ATR, trailing stop 5 ATR"
PULL = 1.5
TOP = 0.20
REF_THR = 0.50
SEED = 20261117


def spy_setup(spy_path, cal):
    sp = (pd.read_csv(spy_path) if spy_path.endswith('.csv') else pd.read_parquet(spy_path))
    sp = sp[sp["date_i"] <= (END - EPOCH).days].sort_values("date_i").drop_duplicates("date_i")
    spc = pd.Series(sp["close"].to_numpy(float), index=np.searchsorted(cal, sp["date_i"].to_numpy()))
    spc = spc[spc.index < len(cal)]
    full = spc.reindex(range(len(cal))).ffill()
    sma = full.rolling(200, min_periods=200).mean()
    mk = switch(((full / sma - 1.0) * 100).to_numpy(), 0, 0)
    return full.to_numpy(float), mk


def evaluate(R, cal, dates, spy_close, WIN, label):
    """Account-level results (both caps, three periods) for one list of trades; label = dict of columns that identify the row."""
    rows = []
    n = len(R["d"])
    if n == 0:
        return rows
    key = np.random.default_rng(SEED).random(n)
    ed = dates[R["sess_e"]]
    bench = (spy_close[R["sess_x"]] / spy_close[R["sess_e"]] - 1.0) * R["px_e"] / R["a0"]
    for cap in (2.0, 1.0):
        P = B.portfolio(R, cal, (1,), M.SIZE, cap, key)
        for wn, (lo, hi) in WIN.items():
            st, cal_y = B.wstats(P["pnl"], dates, lo, hi, P["open_n"], P["gross"])
            if not st:
                continue
            inw = P["taken"] & np.asarray((ed >= lo) & (ed <= hi))
            ra = R["res"][inw]
            bm = bench[inw]; bm = bm[np.isfinite(bm)]
            avg = float(ra.mean()) if inw.any() else np.nan
            bavg = float(bm.mean()) if len(bm) else np.nan
            row = dict(label)
            row.update({"cap %": int(cap * 100), "period": wn, "signals": n, "trades taken": int(inw.sum()), "win rate %": float((ra > 0).mean() * 100) if inw.any() else np.nan,
                        "average ATR per trade": avg, "SPY move over the same holds (ATR units)": bavg, "excess over SPY (ATR units)": avg - bavg if np.isfinite(bavg) else np.nan,
                        "average sessions held": float(R["held"][inw].mean()) if inw.any() else np.nan,
                        "profit per year %": st["profit per year %"], "Sharpe ratio": st["Sharpe ratio"], "max drawdown %": st["max drawdown %"], "worst year %": st["worst year %"], "years positive": st["years positive"],
                        "average position value % of account": st["average position value % of account"]})
            rows.append(row)
    return rows


def threshold_cands(SEG, live, ERC, thr, pull):
    M.PULL = pull
    for i in live:
        er, dr = ERC[i]
        SEG[i]["cand"] = long_cands(SEG[i], er, dr, thr)


def eligible_rows(SEG, live, cal, mk):
    """Rows (decision days) a random entry may use: same filters as M.trades_for applies, so none is thrown away later."""
    first_i = (FIRST_TRADE - EPOCH).days
    mkb = np.asarray(mk, dtype=bool)
    E = {}
    for i in live:
        g = SEG[i]; n = len(g["c"])
        if n < 3:
            continue
        rk, liq, spac, atr, c = g["rank"][:-1], g["liq"][:-1], g["spac"][:-1], g["atr"][:-1], g["c"][:-1]
        ok = np.isfinite(rk) & (rk >= 1.0 - TOP) & liq & ~spac & np.isfinite(atr) & (atr > 1e-6 * c) & (cal[g["s"][1:]] >= first_i) & mkb[g["s"][:-1]]
        idx = np.flatnonzero(ok)
        if len(idx):
            E[i] = idx
    return E


def draw(SEG, live, E, p, seed):
    rng = np.random.default_rng(seed)
    for i in live:
        SEG[i]["cand"] = []
    for i in sorted(E):
        idx = E[i]
        m = rng.random(len(idx)) < p
        SEG[i]["cand"] = [(int(t), 1) for t in idx[m]]


def run_trades(SEG, dropped, cal, mk):
    return M.trades_for(SEG, dropped, cal, TOP, VNAME, market_ok=mk, long_only=True)


def main():
    prices_path, out_dir, spy_path, mode, arg = sys.argv[1], Path(sys.argv[2]), sys.argv[3], sys.argv[4], sys.argv[5]
    out_dir.mkdir(parents=True, exist_ok=True)
    B.selftest(); M.selftest_common()
    M.VERSIONS.clear(); M.VERSIONS[VNAME] = (4.0, 5.0, None)
    SEG, names, dropped, cal = M.build(prices_path)
    live = [i for i in range(len(SEG)) if i not in dropped]
    ERC = {i: er_dr(SEG[i], M.ER_N) for i in live}
    # check: pullback 2.5 and threshold 0.50 reproduce the original signals exactly
    chk = [i for i in live if SEG[i]["cand"]][:: 25]
    M.PULL = 2.5
    for i in chk:
        er, dr = ERC[i]
        assert long_cands(SEG[i], er, dr, M.ER_MIN) == [(t, d) for (t, d) in SEG[i]["cand"] if d > 0], f"mismatch in segment {i}"
    print(f"signal recomputation matches the original on {len(chk)} segments (pullback 2.5, threshold {M.ER_MIN})", flush=True)
    dates = pd.DatetimeIndex(EPOCH + pd.to_timedelta(cal, unit="D"))
    spy_close, mk = spy_setup(spy_path, cal)
    WIN = {"2000 to 2007": (pd.Timestamp("2000-01-01"), MAIN_START - pd.Timedelta(days=1)), "2008 to Aug 2021": (MAIN_START, END), "whole 2000 to Aug 2021": (pd.Timestamp("2000-01-01"), END)}
    pd.set_option("display.width", 300); pd.set_option("display.max_columns", 40); pd.set_option("display.max_rows", 1000)

    # reference rule (current best): threshold 0.50, pullback 1.5 ATR
    threshold_cands(SEG, live, ERC, REF_THR, PULL)
    Rref = run_trades(SEG, dropped, cal, mk)
    n_ref = len(Rref["d"])
    ref_rows = evaluate(Rref, cal, dates, spy_close, WIN, {"entry rule": f"reference: efficiency ratio {REF_THR:.2f}, {PULL:g} ATR pullback"})
    print(f"reference rule (efficiency ratio {REF_THR:.2f}, {PULL:g} ATR pullback): {n_ref:,} signals", flush=True)
    refw = [r for r in ref_rows if r["cap %"] == 200 and r["period"].startswith("whole")]
    if refw:
        r0 = refw[0]
        print(f"REPRODUCTION CHECK vs project doc (whole period, cap 200%: +22.9% / Sharpe 0.64 / -22%): got {r0['profit per year %']:+.1f}% / {r0['Sharpe ratio']:.2f} / {r0['max drawdown %']:.0f}%", flush=True)
        if abs(r0["Sharpe ratio"] - 0.64) > 0.015:
            print("!!!! MISMATCH WITH THE DOCUMENTED REFERENCE: do not trust this run until explained !!!!", flush=True)

    if mode == "thresholds":
        rows = []
        for thr in [float(x) for x in arg.split(",")]:
            threshold_cands(SEG, live, ERC, thr, PULL)
            R = run_trades(SEG, dropped, cal, mk)
            print(f"efficiency ratio threshold {thr:.2f}, pullback {PULL:g} ATR: {len(R['d']):,} signals", flush=True)
            rows += evaluate(R, cal, dates, spy_close, WIN, {"entry rule": f"efficiency ratio {thr:.2f}, {PULL:g} ATR pullback", "threshold": thr})
        S = pd.DataFrame(rows); S.to_csv(out_dir / "threshold_summary.csv", index=False)
        for wn in WIN:
            for cap in (200, 100):
                v = S[(S.period == wn) & (S["cap %"] == cap)]
                print(f"\n==== efficiency ratio threshold | {PULL:g} ATR pullback | long only | strongest 20% | SPY 200-day for entries | {VNAME} | cap {cap}% | {wn} ====")
                print(v.drop(columns=["period", "cap %", "threshold"]).round(2).to_string(index=False))
    elif mode == "random":
        K = int(arg)
        E = eligible_rows(SEG, live, cal, mk)
        n_elig = int(sum(len(v) for v in E.values()))
        print(f"eligible stock-days for a random entry: {n_elig:,} in {len(E):,} stocks; target trades {n_ref:,}", flush=True)
        p = n_ref / n_elig * 2.0
        for it in range(8):
            draw(SEG, live, E, p, 1)
            n = len(run_trades(SEG, dropped, cal, mk)["d"])
            print(f"calibration {it}: chance per eligible day {p:.6f} -> {n:,} trades", flush=True)
            if abs(n - n_ref) / n_ref < 0.02:
                break
            p *= n_ref / max(n, 1)
        print(f"chance per eligible day used: {p:.6f}", flush=True)
        rows = []
        for s in range(1, K + 1):
            draw(SEG, live, E, p, 1000 + s)
            R = run_trades(SEG, dropped, cal, mk)
            rows += evaluate(R, cal, dates, spy_close, WIN, {"entry rule": "random entry", "seed": s})
            print(f"random draw {s}/{K}: {len(R['d']):,} trades", flush=True)
        S = pd.DataFrame(rows); S.to_csv(out_dir / "random_per_seed.csv", index=False)
        pd.DataFrame(ref_rows).to_csv(out_dir / "reference_rule.csv", index=False)
        met = ["trades taken", "win rate %", "average ATR per trade", "SPY move over the same holds (ATR units)", "excess over SPY (ATR units)", "average sessions held", "profit per year %", "Sharpe ratio", "max drawdown %", "worst year %"]
        summ = []
        for wn in WIN:
            for cap in (200, 100):
                v = S[(S.period == wn) & (S["cap %"] == cap)]
                ref = [r for r in ref_rows if r["period"] == wn and r["cap %"] == cap]
                ref = ref[0] if ref else None
                for m_ in met:
                    row = {"period": wn, "cap %": cap, "measure": m_, "random mean": v[m_].mean(), "random std": v[m_].std(), "random min": v[m_].min(), "random 5th pct": v[m_].quantile(0.05), "random median": v[m_].median(),
                           "random 95th pct": v[m_].quantile(0.95), "random max": v[m_].max()}
                    if ref is not None:
                        row["reference rule"] = ref[m_]
                        row["share of random draws at or above the reference"] = float((v[m_] >= ref[m_]).mean()) if m_ not in ("max drawdown %", "worst year %", "average sessions held") else np.nan
                    summ.append(row)
        SM = pd.DataFrame(summ); SM.to_csv(out_dir / "random_summary.csv", index=False)
        for wn in WIN:
            for cap in (200, 100):
                print(f"\n==== random entries ({K} draws, ~{n_ref:,} trades each) vs the reference rule | long only | strongest 20% | SPY 200-day for entries | {VNAME} | cap {cap}% | {wn} ====")
                print(SM[(SM.period == wn) & (SM["cap %"] == cap)].drop(columns=["period", "cap %"]).round(2).to_string(index=False))
        print("\n==== random draws, whole period, cap 200% ====")
        print(S[(S.period.str.startswith("whole")) & (S["cap %"] == 200)].drop(columns=["period", "cap %", "entry rule"]).round(2).to_string(index=False))
    else:
        raise SystemExit("MODE must be thresholds or random")
    print("done")


if __name__ == "__main__":
    main()
