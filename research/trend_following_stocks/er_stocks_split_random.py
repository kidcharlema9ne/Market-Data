"""Stocks, long only: split random baseline. Which shared ingredient gives the random entries their result: the strong-stock filter, the SPY 200-day condition, or only the wide stops? (hand-off doc 17 Nov 2026, next action 1.)
Usage: python er_stocks_split_random.py stock_prices.parquet OUT_DIR spy_prices.parquet TOP SPY K
  TOP = 0.20 (strongest 20% by 126-session return, checked on the entry decision day) or 1.0 (all stocks, no strength filter)
  SPY = on (new entries only when SPY closed above its 200-session average) or off (no market condition)
  K   = number of random draws
One cell of a 2 x 2 table per run. In each cell: (a) the real rule (20-session efficiency ratio 0.50, 1.5 ATR pullback) with that cell's TOP and SPY setting, and (b) K random draws: every eligible stock-day is equally likely to be an
entry (liquid, not a SPAC shell, valid ATR, has the 126-session ranking history, in the strongest 20% if TOP = 0.20, SPY above its 200-day if SPY = on), entry at the next open, one position per stock, with the chance per day set so the
number of trades matches (within 2%) the real rule in the SAME cell. Everything else as the current best rule: common stocks, one series per company, $3M floor, long only, 4 ATR initial stop, 5 ATR trailing stop from the best close,
no time limit, 0.05 ATR a side, 0.10% of $300k per ATR (fixed account), caps 200% and 100%. Reports profit per year, Sharpe ratio, max drawdown, worst year, and the average ATR per trade beside the SPY move over the same holds (ATR units).
Read across the four cells: random Sharpe with everything off isolates the stops; each added ingredient shows its own contribution; the real rule minus random in the same cell shows what the efficiency ratio and pullback add there.
Post hoc on development years; data through 2021-08-06 only; sealed years not read.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
import pandas as pd

import er_stocks as B
import er_stocks_common_momentum as M
from er_stocks import END, EPOCH, MAIN_START, FIRST_TRADE
from er_stocks_er_grid import er_dr, long_cands
from er_stocks_null_baseline import spy_setup, evaluate, VNAME, PULL, REF_THR

MET = ["trades taken", "win rate %", "average ATR per trade", "SPY move over the same holds (ATR units)", "excess over SPY (ATR units)", "average sessions held", "profit per year %", "Sharpe ratio", "max drawdown %", "worst year %"]


def eligible(SEG, live, cal, mk, top):
    first_i = (FIRST_TRADE - EPOCH).days
    E = {}
    for i in live:
        g = SEG[i]
        if len(g["c"]) < 3:
            continue
        rk, liq, spac, atr, c = g["rank"][:-1], g["liq"][:-1], g["spac"][:-1], g["atr"][:-1], g["c"][:-1]
        ok = np.isfinite(rk) & (rk >= 1.0 - top) & liq & ~spac & np.isfinite(atr) & (atr > 1e-6 * c) & (cal[g["s"][1:]] >= first_i) & mk[g["s"][:-1]]
        idx = np.flatnonzero(ok)
        if len(idx):
            E[i] = idx
    return E


def draw(SEG, live, E, p, seed):
    rng = np.random.default_rng(seed)
    for i in live:
        SEG[i]["cand"] = []
    for i in sorted(E):
        m = rng.random(len(E[i])) < p
        SEG[i]["cand"] = [(int(t), 1) for t in E[i][m]]


def main():
    prices_path, out_dir, spy_path, top, spy_flag, K = sys.argv[1], Path(sys.argv[2]), sys.argv[3], float(sys.argv[4]), sys.argv[5], int(sys.argv[6])
    out_dir.mkdir(parents=True, exist_ok=True)
    cell = f"{'strongest 20%' if top < 1 else 'all stocks'} | {'SPY above 200-day' if spy_flag == 'on' else 'no SPY condition'}"
    B.selftest(); M.selftest_common()
    M.VERSIONS.clear(); M.VERSIONS[VNAME] = (4.0, 5.0, None)
    SEG, names, dropped, cal = M.build(prices_path)
    live = [i for i in range(len(SEG)) if i not in dropped]
    ERC = {i: er_dr(SEG[i], M.ER_N) for i in live}
    chk = [i for i in live if SEG[i]["cand"]][:: 25]
    M.PULL = 2.5
    for i in chk:
        er, dr = ERC[i]
        assert long_cands(SEG[i], er, dr, M.ER_MIN) == [(t, d) for (t, d) in SEG[i]["cand"] if d > 0], f"mismatch in segment {i}"
    print(f"signal recomputation matches the original on {len(chk)} segments", flush=True)
    dates = pd.DatetimeIndex(EPOCH + pd.to_timedelta(cal, unit="D"))
    spy_close, mk200 = spy_setup(spy_path, cal)
    mk = mk200 if spy_flag == "on" else np.ones(len(cal), bool)
    WIN = {"2000 to 2007": (pd.Timestamp("2000-01-01"), MAIN_START - pd.Timedelta(days=1)), "2008 to Aug 2021": (MAIN_START, END), "whole 2000 to Aug 2021": (pd.Timestamp("2000-01-01"), END)}
    pd.set_option("display.width", 300); pd.set_option("display.max_columns", 40); pd.set_option("display.max_rows", 1000)

    def run():
        return M.trades_for(SEG, dropped, cal, top, VNAME, market_ok=(mk if spy_flag == "on" else None), long_only=True)

    M.PULL = PULL
    for i in live:
        er, dr = ERC[i]
        SEG[i]["cand"] = long_cands(SEG[i], er, dr, REF_THR)
    Rref = run(); n_ref = len(Rref["d"])
    ref_rows = evaluate(Rref, cal, dates, spy_close, WIN, {"entry rule": f"real rule: efficiency ratio {REF_THR:.2f}, {PULL:g} ATR pullback", "cell": cell})
    print(f"CELL {cell}: real rule {n_ref:,} signals", flush=True)
    r0 = [r for r in ref_rows if r["cap %"] == 200 and r["period"].startswith("whole")]
    if r0 and top < 1 and spy_flag == "on":
        print(f"REPRODUCTION CHECK vs project doc (+22.9% / 0.64 / -22%): got {r0[0]['profit per year %']:+.1f}% / {r0[0]['Sharpe ratio']:.2f} / {r0[0]['max drawdown %']:.0f}%", flush=True)
        if abs(r0[0]["Sharpe ratio"] - 0.64) > 0.015:
            print("!!!! MISMATCH WITH THE DOCUMENTED REFERENCE: do not trust this run until explained !!!!", flush=True)
    E = eligible(SEG, live, cal, mk, top)
    n_elig = int(sum(len(v) for v in E.values()))
    print(f"eligible stock-days for a random entry: {n_elig:,} in {len(E):,} stocks; target trades {n_ref:,}", flush=True)
    p = n_ref / n_elig * 2.0
    for it in range(8):
        draw(SEG, live, E, p, 1)
        n = len(run()["d"])
        print(f"calibration {it}: chance per eligible day {p:.6f} -> {n:,} trades", flush=True)
        if abs(n - n_ref) / n_ref < 0.02:
            break
        p *= n_ref / max(n, 1)
    rows = []
    for s in range(1, K + 1):
        draw(SEG, live, E, p, 1000 + s)
        R = run()
        rows += evaluate(R, cal, dates, spy_close, WIN, {"entry rule": "random entry", "cell": cell, "seed": s})
        print(f"random draw {s}/{K}: {len(R['d']):,} trades", flush=True)
    S = pd.DataFrame(rows); S.to_csv(out_dir / "random_per_seed.csv", index=False)
    pd.DataFrame(ref_rows).to_csv(out_dir / "real_rule.csv", index=False)
    summ = []
    for wn in WIN:
        for cap in (200, 100):
            v = S[(S.period == wn) & (S["cap %"] == cap)]
            ref = [r for r in ref_rows if r["period"] == wn and r["cap %"] == cap]
            ref = ref[0] if ref else None
            for m_ in MET:
                row = {"cell": cell, "period": wn, "cap %": cap, "measure": m_, "random mean": v[m_].mean(), "random std": v[m_].std(), "random min": v[m_].min(), "random 5th pct": v[m_].quantile(0.05),
                       "random median": v[m_].median(), "random 95th pct": v[m_].quantile(0.95), "random max": v[m_].max()}
                if ref is not None:
                    row["real rule"] = ref[m_]
                    row["share of random draws at or above the real rule"] = float((v[m_] >= ref[m_]).mean()) if m_ not in ("max drawdown %", "worst year %", "average sessions held") else np.nan
                summ.append(row)
    SM = pd.DataFrame(summ); SM.to_csv(out_dir / "split_random_summary.csv", index=False)
    for wn in WIN:
        for cap in (200, 100):
            print(f"\n==== {cell} | {K} random draws (~{n_ref:,} trades each) vs the real rule | long only | {VNAME} | cap {cap}% | {wn} ====")
            print(SM[(SM.period == wn) & (SM["cap %"] == cap)].drop(columns=["cell", "period", "cap %"]).round(2).to_string(index=False))
    print("done")


if __name__ == "__main__":
    main()
