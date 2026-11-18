"""Price-level filter on AS-TRADED prices (Michael, 18 Nov 2026; follow-up to Entry 162, where price level was hindsight-contaminated).

Usage: python er_stocks_real_price_level.py stock_prices.parquet OUT_DIR spy_prices.parquet signal_rows.csv.gz splits.csv split_coverage.csv
The archive price in the signal table is split-adjusted to today. As-traded price on the signal day = archive price x product of the ratios of every split that took effect AFTER that day
(ratio = new shares per old share; 4.0 = 4-for-1, 0.1 = 1-for-10 reverse). Splits after 2025-09-30 are ignored (the archive may not have adjusted for them).
Only symbols with status ok in split_coverage.csv get a real price; the rest are "uncovered".
Versions run (same engine, same rules as Entry 162; better half = cheaper than the median of EARLIER signals, volume-surge order when full, plus random pick among kept signals):
  baseline; archive price better half (reproduces Entry 162); archive price better half with uncovered signals kept (the fair control for coverage);
  REAL price better half with uncovered signals kept; REAL price better half with uncovered signals using the archive price.
In-sample only (data through 2021-08-06). Post hoc.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
import pandas as pd

import er_stocks as B
import er_stocks_ideas_1_2_6 as I1
import er_stocks_many_ideas as MI
import er_stocks_start_years as SY
import er_stocks_fact_filters as FF
from er_stocks import END

SPLIT_CUTOFF = pd.Timestamp("2025-09-30")


def main():
    prices_path, out_dir, spy_path, rows_path, splits_path, cov_path = sys.argv[1], Path(sys.argv[2]), sys.argv[3], sys.argv[4], sys.argv[5], sys.argv[6]
    out_dir.mkdir(parents=True, exist_ok=True)
    pd.set_option("display.width", 300); pd.set_option("display.max_columns", 60); pd.set_option("display.max_rows", 500)
    ctx, names, live, E20, dates, spy_close, mk200 = MI.setup(prices_path, spy_path)
    SEG, dropped, cal, (_, _, WIN) = ctx
    MI.check_baseline(ctx, mk200)
    R = MI.gen(ctx, mk200); n = len(R["d"])
    WIN2 = dict(WIN); WIN2["2006 to Aug 2021 (ridge test years)"] = (pd.Timestamp("2006-01-01"), END)
    ctx2 = (SEG, dropped, cal, (dates, spy_close, WIN2))
    D = pd.read_csv(rows_path)
    assert len(D) == n, (len(D), n)
    assert np.allclose(D["res"].to_numpy(), R["res"], atol=1e-6), "signal table does not line up with a fresh run"
    order = np.lexsort((np.arange(n), D["sess_trigger"].to_numpy()))
    tie = np.random.default_rng(20261118).random(n) * 1e-9
    surge = D["volume_surge_signal_20d"].to_numpy(float)
    vs_key = -np.where(np.isfinite(surge), surge, -1e9) + tie
    allmask = np.ones(n, bool)

    # ---------------- rebuild as-traded prices
    sig_sess = (D["sess_trigger"] - D["days_signal_to_trigger"]).astype(int).to_numpy()
    sig_date = pd.to_datetime(dates[sig_sess]).to_numpy()
    yahoo = D["stock"].astype(str).str.replace("-DELISTED", "", regex=False).to_numpy()
    cov = pd.read_csv(cov_path); ok = set(cov.loc[cov["status"] == "ok", "symbol"])
    S = pd.read_csv(splits_path, parse_dates=["split_date"]); S = S[S["split_date"] <= SPLIT_CUTOFF]
    by_sym = {s: g.sort_values("split_date") for s, g in S.groupby("symbol")}
    adj = 10.0 ** D["log10_price"].to_numpy(float)
    factor = np.ones(n); covered = np.zeros(n, bool)
    for k in range(n):
        s = yahoo[k]
        if s in ok:
            covered[k] = True
            g = by_sym.get(s)
            if g is not None:
                later = g[g["split_date"] > sig_date[k]]
                if len(later):
                    factor[k] = float(np.prod(later["ratio"].to_numpy()))
    real = adj * factor
    changed = covered & (np.abs(np.log(factor)) > 1e-9)
    print(f"signals with a real price: {covered.mean() * 100:.1f}% (symbols ok at Yahoo); of those, price changed by a split factor: {changed.sum() / max(covered.sum(), 1) * 100:.1f}%", flush=True)
    print(f"signals {n:,}; delisted-suffix signals covered: {covered[D['stock'].astype(str).str.contains('DELISTED').to_numpy()].mean() * 100:.1f}%", flush=True)
    # spot checks that the arithmetic matches things we know
    for sym, dt in (("GME", "2020-09-10"), ("AMC", "2021-03-24"), ("FAST", "2018-06-01"), ("SYBT", "2010-06-01")):
        m = np.where((yahoo == sym) & (pd.to_datetime(D["entry_date"]).to_numpy() >= np.datetime64(dt)))[0]
        if len(m):
            k = m[np.argmin(pd.to_datetime(D["entry_date"]).to_numpy()[m])]
            print(f"  check {sym}: entry {D['entry_date'][k]} archive price {adj[k]:.2f} x split factor {factor[k]:.3f} = as-traded {real[k]:.2f} (covered={covered[k]})", flush=True)
    rd = real[covered] / adj[covered]
    print("  split factor on covered signals: share >1 (stock later split forward) %.1f%%, share <1 (later reverse split) %.1f%%, share =1 %.1f%%" % ((rd > 1.0001).mean() * 100, (rd < 0.9999).mean() * 100, (np.abs(rd - 1) <= 1e-4).mean() * 100), flush=True)
    pd.DataFrame({"stock": D["stock"], "entry_date": D["entry_date"], "signal_date": pd.to_datetime(sig_date), "archive_price": adj, "split_factor": factor, "as_traded_price": real, "covered": covered}).to_csv(out_dir / "real_price_rows.csv.gz", index=False)

    # ---------------- per-signal lean: cheaper vs dearer half by each definition, average result in ATR (all years, covered signals only)
    res = D["res"].to_numpy(float)
    for nm, p in (("archive price", adj), ("as-traded price", real)):
        pc = p[covered]; rc = res[covered]; med = np.median(pc)
        print(f"  covered signals, {nm}: cheaper half mean {rc[pc <= med].mean():+.3f} ATR, dearer half {rc[pc > med].mean():+.3f} ATR (median price {med:.2f})", flush=True)

    # ---------------- engine
    rows, vid_counter = [], [0]

    def run(label, mask, key, with_random=False):
        Rv = R if mask.all() else SY.subset(R, mask)
        kv = key[mask]; vid = vid_counter[0]; vid_counter[0] += 1
        for cap in (2.0, 1.0):
            P = MI.portfolio_gen(Rv, cal, cap, kv)
            for r in I1.eval_P(Rv, P, cap, dates, spy_close, WIN2, dict(label)):
                r["vid"] = vid; r["share of signals kept %"] = mask.mean() * 100; rows.append(r)
        if with_random:
            lab2 = dict(label); lab2["mode"] = "random pick (mean of 8) among kept signals"
            for r in MI.scen(ctx2, Rv, lab2):
                r["vid"] = -vid - 1; r["share of signals kept %"] = mask.mean() * 100; rows.append(r)
        return vid

    def show(vid, name):
        print(f"  {name} (kept {[r for r in rows if r['vid'] == vid][0]['share of signals kept %']:.0f}% of signals)", flush=True)
        for r in rows:
            if r["vid"] == vid:
                print(f"    {r['period']:<44} cap {int(r['cap %']):>3}%: +{r['profit per year %']:.1f}% a year / Sharpe {r['Sharpe ratio']:.2f} / drawdown {r['max drawdown %']:.1f}% / worst year {r['worst year %']:.1f}% / trades {r['trades taken']}", flush=True)
        for r in rows:
            if r["vid"] == -vid - 1 and "whole" in r["period"]:
                print(f"    random pick among kept, whole period cap {int(r['cap %'])}%: Sharpe {r['Sharpe ratio']:.2f}", flush=True)

    def better_half(values, keep_uncovered):
        g = FF.expanding_goodness(values, order)
        gg = 1.0 - g                                   # lower is better
        warm = np.zeros(n, bool); warm[order[:FF.WARM]] = True
        keep = warm | (np.nan_to_num(gg, nan=-1.0) >= 0.5)
        if keep_uncovered:
            keep = keep | ~covered
        return keep

    log_adj = np.log10(adj)
    log_real_keep = np.where(covered, np.log10(real), np.nan)     # uncovered = missing, then kept
    log_real_fallback = np.log10(real)                            # uncovered use the archive price (factor 1)
    log_adj_covered_only = np.where(covered, log_adj, np.nan)

    print("\n=== baseline ===", flush=True)
    v = run({"group": "baseline", "version": "all signals", "mode": "volume surge ranking when full"}, allmask, vs_key, with_random=True); show(v, "baseline")
    print("\n=== A. archive price (split-adjusted), better half, ALL signals (should reproduce Entry 162: +28.3% / 0.77 and +19.0% / 0.84) ===", flush=True)
    v = run({"group": "A", "version": "archive price better half", "mode": "volume surge ranking when full"}, better_half(log_adj, False), vs_key, with_random=True); show(v, "archive price, better half")
    print("\n=== B. archive price, better half, uncovered signals always kept (the fair control for C) ===", flush=True)
    v = run({"group": "B", "version": "archive price, covered only filtered", "mode": "volume surge ranking when full"}, better_half(log_adj_covered_only, True), vs_key, with_random=True); show(v, "archive price, covered signals filtered")
    print("\n=== C. REAL (as-traded) price, better half, uncovered signals always kept ===", flush=True)
    v = run({"group": "C", "version": "as-traded price, covered only filtered", "mode": "volume surge ranking when full"}, better_half(log_real_keep, True), vs_key, with_random=True); show(v, "as-traded price, covered signals filtered")
    print("\n=== D. REAL price where known, archive price where not, better half ===", flush=True)
    v = run({"group": "D", "version": "as-traded price, uncovered use archive price", "mode": "volume surge ranking when full"}, better_half(log_real_fallback, False), vs_key, with_random=True); show(v, "as-traded price with archive fallback")
    pd.DataFrame(rows).round(4).to_csv(out_dir / "real_price_variants.csv", index=False)
    print("done", flush=True)


if __name__ == "__main__":
    main()
