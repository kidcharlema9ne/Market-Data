"""Stocks, long only: do the signal-study facts help as ACCOUNT-LEVEL filters and rankings? (Michael, 18 Nov 2026; hand-off "testing the signal-study facts as account-level filters".)
Usage: python er_stocks_fact_filters.py stock_prices.parquet OUT_DIR spy_prices.parquet signal_rows.csv.gz

Everything is the current baseline (volume-surge ranking when the account is full, plain 4 ATR initial and 5 ATR trailing stops, 0.05 ATR a side, 0.10% of a fixed $300,000 per ATR, cap 200% and 100%, strongest 20%,
SPY above its 200-day, $3M floor, common stocks) except what is said below. The signals are the 18,978 signals of Entry 160 (signal_rows.csv.gz holds the 40 facts of every one; row order is checked against a fresh run).

TEN FACTS (the direction that the signal study found to be the good side is in brackets):
  passed the shuffle benchmark of Entry 160: volume surge on the biggest gap up of the last 60 sessions (higher), lower price level (lower; HINDSIGHT-CONTAMINATED: archive prices are split adjusted to today),
  gap up more recent (fewer days since that gap), lower 126-day return per unit of volatility, tighter recent 5-day range, lower 126-day return, volatility (ATR) higher than 50 sessions ago;
  from the hand-off list, leaning but not passing: choppier 126-day path (lower smoothness), quieter volume on the pullback (trigger) day, more days from signal to trigger.

PART 1, for each fact, four ways: (a) take only the better half of signals by that fact, volume-surge order when full (and the mean of 8 random picks, the luck yardstick); (b) all signals, ranked by the fact when full;
(c) better half only AND ranked by the fact when full.
  "Better half" uses NO future data: the median is of the same fact over signals whose trigger day was EARLIER (expanding); the first 1,000 signals are all kept (warm-up). A missing fact value counts as the bad side.
PART 2, points score: add up how many facts a signal is on the strictly good side of (versus the same expanding median), no fitting. Sets: the 7 that passed the benchmark, the same 6 without price level, all 10.
  Top half / top third of points (expanding threshold; ties at the cut broken by a fixed random draw), ranking by points (ties broken by volume surge), and half + points ranking. Compared with the
  walk-forward ridge model of Entry 160 used as a filter (trained only on signals already exited before each test year; test years 2006 to Aug 2021), top half / top third by an expanding threshold of its predictions.
PART 3, price level on unadjusted prices: the archive has no unadjusted prices, so the price-level result stays hindsight-contaminated (reported with a flag; the 6-fact set drops it).
PART 4, start-year tables (account started empty on 1 January 2000 to 2020) for the baseline and for every version that beats the baseline Sharpe at both caps (best 6).
Windows: 2000 to 2007, 2008 to Aug 2021, whole 2000 to Aug 2021, and 2006 to Aug 2021 (the ridge model's test years). In-sample only (data through 2021-08-06); sealed years never read.
The facts were chosen on this same data, so every result here is post hoc and optimistic: nothing is validated.
"""
import bisect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
import pandas as pd

import er_stocks as B
import er_stocks_ideas_1_2_6 as I1
import er_stocks_many_ideas as MI
import er_stocks_signal_study as SS
import er_stocks_start_years as SY
from er_stocks import END

WARM = 1000
LUCK = 0.07          # Sharpe spread between random-pick versions (hand-off)
FACTS = [
    ("volume_surge_on_that_gap", +1, "volume surge on the biggest gap up of the last 60 sessions (higher)", True),
    ("log10_price", -1, "lower price level (hindsight-contaminated)", True),
    ("days_since_that_gap", -1, "gap up more recent (fewer days since it)", True),
    ("return_per_volatility_126d", -1, "lower 126-day return per unit of volatility", True),
    ("recent_range_vs_atr", -1, "tighter recent 5-day range", True),
    ("return_126d", -1, "lower 126-day return", True),
    ("atr_now_vs_50d_ago", +1, "volatility (ATR) higher than 50 sessions ago", True),
    ("smoothness_126d", -1, "choppier 126-day path", False),
    ("volume_surge_trigger_20d", -1, "quieter volume on the pullback (trigger) day", False),
    ("days_signal_to_trigger", +1, "more days from signal to trigger", False),
]


# ---------------------------------------------------------------- helpers (no future data)
def expanding_goodness(vals, order, warm=WARM):
    """Percentile (mid-rank for ties) of each value among the values of signals that triggered EARLIER, 0 to 1; NaN while in warm-up or when the value is missing."""
    n = len(vals); g = np.full(n, np.nan); seen = []
    for pos, k in enumerate(order):
        v = vals[k]
        if not np.isfinite(v):
            continue
        if pos >= warm and seen:
            lo = bisect.bisect_left(seen, v); hi = bisect.bisect_right(seen, v)
            g[k] = (lo + 0.5 * (hi - lo)) / len(seen)
        bisect.insort(seen, v)
    return g


def expanding_quantile_keep(score, order, q, warm=WARM):
    """Keep a signal if its score is at or above the q-quantile of the scores of EARLIER signals. Warm-up signals and signals with no score are kept."""
    n = len(score); keep = np.ones(n, bool); seen = []
    for pos, k in enumerate(order):
        s = score[k]
        if not np.isfinite(s):
            continue
        if pos >= warm and seen:
            thr = seen[min(len(seen) - 1, int(q * len(seen)))]
            keep[k] = s >= thr
        bisect.insort(seen, s)
    return keep


def fact_key(vals, direction, tie):
    """Smaller key = taken first when the account is full. Missing values go last."""
    k = -direction * vals
    return np.where(np.isfinite(vals), k, 1e9) + tie


# ---------------------------------------------------------------- main
def main():
    prices_path, out_dir, spy_path, rows_path = sys.argv[1], Path(sys.argv[2]), sys.argv[3], sys.argv[4]
    out_dir.mkdir(parents=True, exist_ok=True)
    pd.set_option("display.width", 340); pd.set_option("display.max_columns", 60); pd.set_option("display.max_rows", 1500); pd.set_option("display.max_colwidth", 80)
    ctx, names, live, E20, dates, spy_close, mk200 = MI.setup(prices_path, spy_path)
    SEG, dropped, cal, (_, _, WIN) = ctx
    MI.check_baseline(ctx, mk200)
    R = MI.gen(ctx, mk200); n = len(R["d"])
    WIN2 = dict(WIN); WIN2["2006 to Aug 2021 (ridge test years)"] = (pd.Timestamp("2006-01-01"), END)
    ctx2 = (SEG, dropped, cal, (dates, spy_close, WIN2))
    whole = [k for k in WIN2 if k.startswith("whole")][0]

    D = pd.read_csv(rows_path)
    assert len(D) == n, (len(D), n)
    assert np.allclose(D["res"].to_numpy(), R["res"], atol=1e-6), "signal table does not line up with a fresh run (results differ)"
    assert (pd.to_datetime(D["entry_date"]).to_numpy() == dates[R["sess_e"]].to_numpy()).all(), "signal table does not line up with a fresh run (entry dates differ)"
    print(f"{n:,} signals; the signal table lines up with a fresh run", flush=True)
    order = np.lexsort((np.arange(n), D["sess_trigger"].to_numpy()))
    tie = np.random.default_rng(20261118).random(n) * 1e-9
    surge = D["volume_surge_signal_20d"].to_numpy(float)
    vs_key = -np.where(np.isfinite(surge), surge, -1e9) + tie
    surge_pct = pd.Series(surge).rank(pct=True).fillna(0.0).to_numpy()
    allmask = np.ones(n, bool)

    rows, registry, yearly = [], {}, {}
    vid_counter = [0]
    WHOLE_LO = pd.Timestamp("2000-01-01")

    def run(label, mask, key, with_random=False, tag=None):
        """label = dict(group, version, mode). Returns the vid. Rows for both caps and all windows."""
        Rv = R if mask.all() else SY.subset(R, mask)
        kv = key[mask]
        vid = vid_counter[0]; vid_counter[0] += 1
        registry[vid] = (mask.copy(), key.copy(), dict(label))
        for cap in (2.0, 1.0):
            P = MI.portfolio_gen(Rv, cal, cap, kv)
            for r in I1.eval_P(Rv, P, cap, dates, spy_close, WIN2, dict(label)):
                r["vid"] = vid; r["Sharpe lowest pick"] = np.nan; r["Sharpe highest pick"] = np.nan; r["share of signals kept %"] = mask.mean() * 100; rows.append(r)
            st, cy = B.wstats(P["pnl"], dates, WHOLE_LO, END, P["open_n"], P["gross"])
            yearly[(vid, int(cap * 100))] = cy
        if with_random:
            lab2 = dict(label); lab2["mode"] = label["mode"].replace("volume surge ranking when full", "random pick (mean of 8)")
            for r in MI.scen(ctx2, Rv, lab2):
                r["vid"] = -1; r["share of signals kept %"] = mask.mean() * 100; rows.append(r)
        return vid

    def show(vid, name):
        out = []
        for cap in (200, 100):
            w = [r for r in rows if r.get("vid") == vid and r["period"] == whole and r["cap %"] == cap]
            if w:
                r = w[0]; out.append(f"cap {cap}%: +{r['profit per year %']:.1f}% / Sharpe {r['Sharpe ratio']:.2f} / {r['max drawdown %']:.1f}% / worst {r['worst year %']:.1f}% / trades {r['trades taken']}")
        print(f"  {name}: " + " | ".join(out), flush=True)

    def save():
        pd.DataFrame(rows).round(4).to_csv(out_dir / "fact_filter_variants_partial.csv", index=False)

    # ---------------- baselines
    base_vid = run({"group": "baseline", "version": "all signals", "mode": "volume surge ranking when full"}, allmask, vs_key, with_random=True)
    show(base_vid, "baseline (volume surge ranking)")
    w = [r for r in rows if r.get("vid") == base_vid and r["period"] == whole and r["cap %"] == 200][0]
    print(f"  documented baseline: +25.1% / 0.69 / -21.7% / worst -16.1% (cap 200%); reproduced: +{w['profit per year %']:.1f}% / {w['Sharpe ratio']:.2f} / {w['max drawdown %']:.1f}% / {w['worst year %']:.1f}%", flush=True)
    rnd = [r for r in rows if r["vid"] == -1 and r["period"] == whole and r["cap %"] == 200][0]
    print(f"  random pick (mean of 8), unfiltered: +{rnd['profit per year %']:.1f}% / Sharpe {rnd['Sharpe ratio']:.2f} (lowest {rnd['Sharpe lowest pick']:.2f}, highest {rnd['Sharpe highest pick']:.2f})", flush=True)

    # ---------------- part 1
    print("\n=== PART 1: each fact as a filter, a ranking, and both ===", flush=True)
    good = {}                                              # fact -> goodness 0..1 (1 = best side) or NaN
    for col, direction, nice, passed in FACTS:
        vals = D[col].to_numpy(float)
        g = expanding_goodness(vals, order)
        gg = g if direction > 0 else 1.0 - g
        good[col] = gg
        warm = np.zeros(n, bool); warm[order[:WARM]] = True
        keep = warm | (np.nan_to_num(gg, nan=-1.0) >= 0.5)
        fk = fact_key(vals, direction, tie)
        print(f"- {nice} | kept {keep.mean() * 100:.0f}% of signals", flush=True)
        try:
            v1 = run({"group": "one fact", "version": nice, "mode": "better half only, volume surge ranking when full"}, keep, vs_key, with_random=True); show(v1, "better half only, volume surge order")
            v2 = run({"group": "one fact", "version": nice, "mode": "all signals, ranked by the fact when full"}, allmask, fk); show(v2, "ranked by the fact")
            v3 = run({"group": "one fact", "version": nice, "mode": "better half only AND ranked by the fact when full"}, keep, fk); show(v3, "better half and ranked by the fact")
        except Exception as ex:                            # one failure must not lose the rest
            print(f"  FAILED for {col}: {type(ex).__name__}: {ex}", flush=True)
        save()

    # ---------------- part 2
    print("\n=== PART 2: points score (how many facts a signal is on the good side of) ===", flush=True)
    warm_row = np.zeros(n, bool); warm_row[order[:WARM]] = True
    sets = {"7 facts that passed the shuffle benchmark": [c for c, d, nm, p in FACTS if p],
            "6 facts that passed, without price level": [c for c, d, nm, p in FACTS if p and c != "log10_price"],
            "all 10 facts": [c for c, d, nm, p in FACTS]}
    for sname, cols in sets.items():
        pts = np.sum([np.nan_to_num(good[c], nan=0.0) > 0.5 for c in cols], axis=0).astype(float)
        pts_key = -(pts + 0.5 * surge_pct / (1.0 + 1e-9)) * 1.0 + tie                      # points first, volume surge breaks ties
        print(f"- {sname}: points 0 to {len(cols)}; average {pts[~warm_row].mean():.2f}", flush=True)
        try:
            pts_j = pts + np.random.default_rng(777).random(n) * 0.99                      # fixed random tie-break so that a half / a third really is a half / a third
            for frac, q, nm in ((0.5, 0.5, "top half"), (1 / 3, 2 / 3, "top third")):
                keep = expanding_quantile_keep(np.where(warm_row, np.nan, pts_j), order, q)
                v = run({"group": "points score", "version": sname, "mode": f"{nm} by points, volume surge ranking when full"}, keep, vs_key, with_random=True)
                show(v, f"{nm} by points (kept {keep.mean() * 100:.0f}%), volume surge order")
                if nm == "top half":
                    v = run({"group": "points score", "version": sname, "mode": "top half by points AND ranked by points when full"}, keep, pts_key); show(v, "top half and ranked by points")
            v = run({"group": "points score", "version": sname, "mode": "all signals, ranked by points when full"}, allmask, pts_key); show(v, "ranked by points")
        except Exception as ex:
            print(f"  FAILED for {sname}: {type(ex).__name__}: {ex}", flush=True)
        save()

    # ---------------- ridge model as a filter (walk-forward, test years 2006 on)
    print("\n=== PART 2b: walk-forward ridge model as a filter (test years 2006 to Aug 2021) ===", flush=True)
    try:
        Dm = D.copy(); Dm["entry_date"] = pd.to_datetime(Dm["entry_date"]); Dm["exit_date"] = pd.to_datetime(Dm["exit_date"])
        pred, log = SS.walk_forward(Dm, SS.FACTS_STOCK, ["ridge"])
        pr = pred["ridge"]; print("  training sizes by test year: " + " ".join(f"{y}:{a}/{b}" for y, a, b in log), flush=True)
        for frac, q, nm in ((0.5, 0.5, "top half"), (1 / 3, 2 / 3, "top third")):
            keep = expanding_quantile_keep(pr, order, q, warm=300)
            v = run({"group": "ridge model", "version": "walk-forward ridge", "mode": f"{nm} by ridge prediction, volume surge ranking when full"}, keep, vs_key, with_random=True)
            show(v, f"ridge {nm} (kept {keep.mean() * 100:.0f}%)")
        np.save(out_dir / "ridge_predictions.npy", pr)
    except Exception as ex:
        print(f"  FAILED ridge: {type(ex).__name__}: {ex}", flush=True)
    save()

    # ---------------- tables
    S = pd.DataFrame(rows)
    S["profit per year / drawdown"] = S["profit per year %"] / S["max drawdown %"].abs()
    bs = S[(S.vid == base_vid)].set_index(["period", "cap %"])["Sharpe ratio"]
    S["Sharpe gain vs baseline"] = [r["Sharpe ratio"] - bs.get((r["period"], r["cap %"]), np.nan) for _, r in S.iterrows()]
    bsw = {c: bs[(whole, c)] for c in (200, 100)}
    # year-by-year consistency against the baseline (whole period)
    yb = {}
    for (vid, cap), cy in yearly.items():
        b = yearly[(base_vid, cap)]
        a = cy.reindex(b.index)
        yb[(vid, cap)] = (int((a > b).sum()), len(b), float((a - b).mean()))
    S["years beating baseline"] = [f"{yb[(int(r['vid']), r['cap %'])][0]} of {yb[(int(r['vid']), r['cap %'])][1]}" if (r["period"] == whole and r["vid"] >= 0 and (int(r["vid"]), r["cap %"]) in yb) else "" for _, r in S.iterrows()]
    S["mean yearly profit gain vs baseline (points of account)"] = [yb[(int(r["vid"]), r["cap %"])][2] if (r["period"] == whole and r["vid"] >= 0 and (int(r["vid"]), r["cap %"]) in yb) else np.nan for _, r in S.iterrows()]
    S.round(4).to_csv(out_dir / "fact_filter_variants.csv", index=False)
    cols = ["group", "version", "mode", "profit per year %", "Sharpe ratio", "Sharpe gain vs baseline", "max drawdown %", "profit per year / drawdown", "worst year %", "trades taken", "share of signals kept %", "years beating baseline"]
    for wn in WIN2:
        for cap in (200, 100):
            v = S[(S.period == wn) & (S["cap %"] == cap)]
            print(f"\n==== {wn} | cap {cap}% (random-pick rows are the mean of 8 picks; Sharpe gain vs baseline is against the unfiltered volume-surge baseline of the same window; luck spread about +/-{LUCK:.2f}) ====")
            print(v[cols].round(2).to_string(index=False))

    # ---------------- part 4: start-year tables
    cand = S[(S.period == whole) & (S.vid >= 0) & (S.vid != base_vid) & (~S["mode"].str.contains("random"))]
    pv = cand.pivot_table(index="vid", columns="cap %", values="Sharpe gain vs baseline")
    pv = pv.dropna()
    beat = pv[(pv[200] > 0) & (pv[100] > 0)].copy(); beat["sum"] = beat[200] + beat[100]
    chosen = beat.sort_values("sum", ascending=False).head(6).index.tolist()
    note = "beat the baseline Sharpe at both caps"
    if len(chosen) < 2:
        extra = pv.assign(sum=pv[200] + pv[100]).sort_values("sum", ascending=False).head(2 - len(chosen)).index.tolist()
        chosen += [e for e in extra if e not in chosen]; note = "FEW OR NONE beat the baseline at both caps; the best by Sharpe are shown anyway"
    print(f"\n==== start-year tables for the baseline and {len(chosen)} versions ({note}) ====", flush=True)
    tabs = []
    for vid in [base_vid] + chosen:
        mask, key, lab = registry[vid]
        Rv = R if mask.all() else SY.subset(R, mask); kv = key[mask]
        nm = "BASELINE" if vid == base_vid else f"{lab['version']} | {lab['mode']}"
        for cap in (2.0, 1.0):
            for y in range(2000, 2021):
                r = SY.run_window(Rv, kv, cal, dates, spy_close, pd.Timestamp(f"{y}-01-01"), END, cap)
                if r:
                    r.update({"version": nm, "cap %": int(cap * 100)}); tabs.append(r)
        print(f"  done {nm}", flush=True)
    T = pd.DataFrame(tabs); T.round(3).to_csv(out_dir / "fact_filter_start_years.csv", index=False)
    summ = []
    for cap in (200, 100):
        t = T[T["cap %"] == cap]
        b = t[t.version == "BASELINE"].set_index("start")
        for nm in [v for v in t.version.unique() if v != "BASELINE"]:
            x = t[t.version == nm].set_index("start")
            idx = x.index.intersection(b.index)
            summ.append({"cap %": cap, "version": nm, "start years": len(idx),
                         "profit per year higher than baseline in": int((x.loc[idx, "profit per year %"] > b.loc[idx, "profit per year %"]).sum()),
                         "smaller max drawdown than baseline in": int((x.loc[idx, "max drawdown % (from peak)"] > b.loc[idx, "max drawdown % (from peak)"]).sum()),
                         "higher Sharpe than baseline in": int((x.loc[idx, "Sharpe ratio"] > b.loc[idx, "Sharpe ratio"]).sum()),
                         "worst drawdown over all start years %": float(x.loc[idx, "max drawdown % (from peak)"].min()), "baseline worst drawdown %": float(b.loc[idx, "max drawdown % (from peak)"].min())})
    if summ:
        SM = pd.DataFrame(summ); SM.round(2).to_csv(out_dir / "fact_filter_start_year_summary.csv", index=False)
        print("\nStart-year scoreboard against the baseline:"); print(SM.round(2).to_string(index=False))
    for cap in (200, 100):
        v = T[T["cap %"] == cap].pivot(index="start", columns="version", values=["profit per year %", "max drawdown % (from peak)"])
        print(f"\n==== start-year tables | cap {cap}% | profit per year % and max drawdown % from peak ===="); print(v.round(1).to_string())
    print("done")


if __name__ == "__main__":
    main()
