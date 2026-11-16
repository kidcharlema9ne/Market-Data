#!/usr/bin/env python3
"""Failed-reversal breakout WITH THE TREND (no COT filter), 48-market universe, development period only.

Usage:
  python reversal_trend.py run <universe.csv> <prices.parquet|csv> <outdir>
  python reversal_trend.py selftest

RULES (declared as C51 in docs/CANDIDATES.md BEFORE any run)
- Pattern, entry, stop, excursions, trailing exits: exactly the trade mechanics of research/cot_reversal/cot_reversal_breakout.py
  (imported in place): reversal day = higher high AND lower close than the day before (long), exact mirror for shorts; buy stop one
  tick above the reversal-day high on the NEXT session only (fill = max(open, trigger)); initial stop = reversal-day low; ATR = 14
  sessions ending at the reversal day. No COT data is used.
- Trend filters, all read at the close of the reversal day (data through that day only):
    with the 200-day average : long close > 200-session simple average of closes; short close < it.
    efficient 20-day trend   : efficiency ratio over 20 sessions = |close[i]-close[i-20]| / sum of |daily close changes| >= 0.5, and the
                               20-session change points the trade's way (long up, short down).
    just beyond 200-day avg  : long 0 < (close - average)/ATR <= 2; short -2 <= (close - average)/ATR < 0. The 2 ATR cut is fixed, not tuned.
    efficient and just beyond: both of the above.
  Any window containing a data hole (gap > 5 calendar days) gives no reading, so the filter fails.
- Benchmark (same-trend any-day): enter at the next session's open on EVERY day meeting the same trend condition (no reversal pattern),
  same market, same side, same calendar year; return = close of the Nth session - entry open, over the pre-entry ATR. Paired excess =
  trade return - the matched benchmark mean.
- Development period only: signals to 2021-08-06, no price on or after 2021-11-08 is read (Michael's standing rule).
- Costs: the standing 0.10 ATR round trip is subtracted only in the labelled net columns; everything else is gross.
"""
import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_BASE = Path(__file__).resolve().parents[1] / "cot_reversal" / "cot_reversal_breakout.py"
_spec = importlib.util.spec_from_file_location("cot_reversal_breakout", _BASE)
crb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(crb)

HORIZONS = crb.HORIZONS
DEV_LAST_SIGNAL = crb.DEV_LAST_SIGNAL
SEAL_FIRST_DAY = crb.SEAL_FIRST_DAY
EFF_LOOKBACK = 20
EFF_MIN = 0.5
SMA_LEN = 200
NEAR_ATR = 2.0
COST_ATR = 0.10
ERA_SPLIT = pd.Timestamp("2014-12-31")
PLACEBO_DRAWS = 2000
VARIANTS = ["plain", "trend200", "eff20", "near200", "eff20_near200"]
LABEL = {
    "plain": "Plain failed reversal, no trend filter (reference)",
    "trend200": "With the 200-day average (above for longs, below for shorts)",
    "eff20": "Efficient 20-day trend (efficiency 0.5 or more, moving the trade's way)",
    "near200": "Just beyond the 200-day average (0 to 2 ATR on the trade's side)",
    "eff20_near200": "Efficient 20-day trend AND just beyond the 200-day average",
}
BANDS = [("against the trade (wrong side of the 200-day)", -np.inf, 0.0), ("0 to 1 ATR", 0.0, 1.0), ("1 to 2 ATR", 1.0, 2.0),
         ("2 to 4 ATR", 2.0, 4.0), ("4 to 8 ATR", 4.0, 8.0), ("over 8 ATR", 8.0, np.inf)]


# ------------------------------------------------------------------------------------------------ features
def features(s):
    """Per-bar trend features from one cleaned series. Returns dict of arrays and the per-side variant flag arrays."""
    c, atr, hc = s["c"], s["atr"], s["hole_cum"]
    n = len(c)
    sma = np.full(n, np.nan)
    ok_s = np.zeros(n, bool)
    if n >= SMA_LEN:
        cs = np.concatenate([[0.0], np.cumsum(c)])
        idx = np.arange(SMA_LEN - 1, n)
        sma[idx] = (cs[idx + 1] - cs[idx + 1 - SMA_LEN]) / SMA_LEN
        ok_s[idx] = (hc[idx] - hc[idx - (SMA_LEN - 1)]) == 0
    er = np.full(n, np.nan)
    chg = np.full(n, np.nan)
    ok_e = np.zeros(n, bool)
    if n > EFF_LOOKBACK:
        ad = np.concatenate([[0.0], np.abs(np.diff(c))])
        cd = np.cumsum(ad)
        idx = np.arange(EFF_LOOKBACK, n)
        path = cd[idx] - cd[idx - EFF_LOOKBACK]
        net = np.abs(c[idx] - c[idx - EFF_LOOKBACK])
        er[idx] = np.where(path > 0, net / np.where(path > 0, path, 1.0), np.nan)
        chg[idx] = c[idx] - c[idx - EFF_LOOKBACK]
        ok_e[idx] = (hc[idx] - hc[idx - EFF_LOOKBACK]) == 0
    dist = np.where(np.isfinite(atr) & (atr > 0) & ok_s, (c - sma) / np.where(atr > 0, atr, 1.0), np.nan)
    flags = {}
    for side, sg in (("long", 1.0), ("short", -1.0)):
        trend = ok_s & (sg * (c - sma) > 0)
        eff = ok_e & np.isfinite(er) & (er >= EFF_MIN) & (sg * chg > 0)
        sd = sg * dist
        near = ok_s & np.isfinite(sd) & (sd > 0) & (sd <= NEAR_ATR)
        flags[side] = dict(plain=np.ones(n, bool), trend200=trend, eff20=eff, near200=near, eff20_near200=eff & near)
    return dict(sma=sma, er=er, dist=dist, flags=flags)


def anyday_returns(s):
    """For every bar i: return (in pre-entry ATR) of buying at the open of session i+1 and holding N sessions to that session's close.
    Returns {N: array} for a LONG; a short is the negative. NaN where the window is incomplete or has a hole."""
    n = len(s["d"])
    c, o, atr, hc, hole = s["c"], s["o"], s["atr"], s["hole_cum"], s["hole"]
    out = {}
    i = np.arange(n)
    for N in HORIZONS:
        j = i + 1
        k = j + N - 1
        r = np.full(n, np.nan)
        ok = (k < n) & np.isfinite(atr) & (atr > 0)
        jj, kk = j[ok], k[ok]
        good = (~hole[jj]) & (hc[kk] == hc[jj])
        idx = i[ok][good]
        r[idx] = (c[kk[good]] - o[jj[good]]) / atr[idx]
        out[N] = r
    return out


# ------------------------------------------------------------------------------------------------ collection
def collect(prices, uni):
    rows, bench, cover = [], [], []
    for u in uni.itertuples():
        sym = crb.PRICE_ROOTS.get(u.ibkr, u.ibkr)
        g = prices[(prices["symbol"] == sym) & (prices["date"] < SEAL_FIRST_DAY)]
        if g.empty:
            cover.append(dict(code=u.code, ibkr=u.ibkr, price_symbol=sym, bars=0))
            continue
        s, ndrop = crb.clean_series(g)
        n = len(s["d"])
        cover.append(dict(code=u.code, ibkr=u.ibkr, price_symbol=sym, bars=n, first=str(s["d"][0]), last=str(s["d"][-1]),
                          dropped_invalid=ndrop, holes=int(s["hole"].sum())))
        tick = crb.TICKS[u.ibkr]
        dates = pd.DatetimeIndex(s["d"]).astype("datetime64[ns]")
        f = features(s)
        ad = anyday_returns(s)
        day_ok = (np.arange(n) >= 14) & (dates <= DEV_LAST_SIGNAL) & ~s["hole"]
        years = dates.year.values
        for side, sg in (("long", 1.0), ("short", -1.0)):
            df = pd.DataFrame({"year": years, **{f"b{N}": sg * ad[N] for N in HORIZONS}})
            for v in VARIANTS:
                m = day_ok & f["flags"][side][v]
                if not m.any():
                    continue
                gm = df[m].groupby("year")[[f"b{N}" for N in HORIZONS]].mean().reset_index()
                gm["code"], gm["side"], gm["variant"] = u.code, side, v
                bench.append(gm)
        c, h, l = s["c"], s["h"], s["l"]
        for i in range(14, n):
            if s["hole"][i] or dates[i] > DEV_LAST_SIGNAL:
                continue
            pats = (("long", h[i] > h[i - 1] and c[i] < c[i - 1]), ("short", l[i] < l[i - 1] and c[i] > c[i - 1]))
            for side, pat in pats:
                if not pat:
                    continue
                t = crb.make_trade(s, i, side, tick)
                sg = 1.0 if side == "long" else -1.0
                row = dict(code=u.code, ibkr=u.ibkr, side=side, signal_date=dates[i], year=int(years[i]), filled=t is not None,
                           er20=f["er"][i], dist200_atr=f["dist"][i], withtrend_dist=sg * f["dist"][i] if np.isfinite(f["dist"][i]) else np.nan)
                for v in VARIANTS:
                    row[v] = bool(f["flags"][side][v][i])
                if t is not None:
                    row.update(entry_date=pd.Timestamp(s["d"][t["j"]]), entry_idx=t["j"], gapfill=t["gapfill"], atr=t["atr"],
                               risk_atr=t["risk"] / t["atr"])
                    for N in HORIZONS:
                        e = crb.excursions(s, t, N)
                        if e is None:
                            continue
                        mfe, mc, mo, ret = e
                        row.update({f"mfe{N}": mfe / t["atr"], f"mae{N}": mc / t["atr"], f"maeopt{N}": mo / t["atr"], f"ret{N}": ret / t["atr"]})
                    for label, opt in (("trail", False), ("trailopt", True)):
                        ex = crb.trailing_exit(s, t, optimistic=opt)
                        if ex is None:
                            row[f"{label}_ret"] = np.nan
                            continue
                        px, qx, _ = ex
                        gross = (px - t["fill"]) if side == "long" else (t["fill"] - px)
                        row[f"{label}_ret"] = gross / t["atr"]
                        row[f"{label}_dur"] = qx - t["j"] + 1
                        row[f"{label}_exit_idx"] = qx
                rows.append(row)
    tr = pd.DataFrame(rows)
    bn = pd.concat(bench, ignore_index=True) if bench else pd.DataFrame()
    return tr, bn, pd.DataFrame(cover)


# ------------------------------------------------------------------------------------------------ statistics
def with_bench(sub, v, bench):
    """Attach the matched same-trend any-day benchmark means (b1..b10) to the trades of variant v."""
    b = bench[bench["variant"] == v].drop(columns="variant")
    return sub.merge(b, on=["code", "side", "year"], how="left")


def month_ci(vals, months, reps=2000, seed=11):
    vals = np.asarray(vals, float)
    keep = np.isfinite(vals)
    vals, months = vals[keep], np.asarray(months)[keep]
    if len(vals) < 30:
        return (np.nan, np.nan)
    uniq, inv = np.unique(months, return_inverse=True)
    sums = np.bincount(inv, weights=vals)
    cnts = np.bincount(inv).astype(float)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(uniq), size=(reps, len(uniq)))
    means = sums[idx].sum(axis=1) / cnts[idx].sum(axis=1)
    return tuple(np.percentile(means, [2.5, 97.5]))


def placebo_pct(plain, sub, col, reps=PLACEBO_DRAWS, seed=5):
    """Share of random same-size, same-long/short-mix draws from the plain pattern whose mean `col` is BELOW the variant's mean."""
    x = sub[col].dropna()
    if len(x) < 10:
        return np.nan
    nl = int((sub.loc[x.index, "side"] == "long").sum())
    ns = len(x) - nl
    pl = plain[(plain["side"] == "long")][col].dropna().values
    ps = plain[(plain["side"] == "short")][col].dropna().values
    if (nl > len(pl)) or (ns > len(ps)):
        return np.nan
    rng = np.random.default_rng(seed)
    means = np.empty(reps)
    for k in range(reps):
        d = np.concatenate([rng.choice(pl, nl, replace=False) if nl else [], rng.choice(ps, ns, replace=False) if ns else []])
        means[k] = d.mean()
    return float((means < x.mean()).mean() * 100)


def f2(v, w=6):
    return f"{v:{w}.2f}" if v == v else " " * (w - 3) + "n/a"


def f0(v, w=6):
    return f"{v:{w}.0f}" if v == v else " " * (w - 3) + "n/a"


def variant_block(v, tr, plain, bench):
    sub = tr[tr["filled"] & tr[v]].copy()
    sub = with_bench(sub, v, bench)
    sub["month"] = sub["signal_date"].dt.to_period("M").astype(str)
    out = [f"\n=== {LABEL[v]} ===", f"filled trades {len(sub)}  (long {int((sub.side == 'long').sum())}, short {int((sub.side == 'short').sum())});"
           f" markets {sub.code.nunique()}; benchmark = same-trend any-day entry at the next open, same market, side and year"]
    out.append("sessions |  n   | MFE mean | MAE worst / best | exact return mean | median | benchmark | excess | excess 95% range (month clusters) | % above 0")
    summary = {}
    for N in HORIZONS:
        x = sub[sub[f"ret{N}"].notna()]
        if x.empty:
            continue
        ex = x[f"ret{N}"] - x[f"b{N}"]
        lo, hi = month_ci(ex.values, x["month"].values)
        summary[N] = dict(n=len(x), ret=x[f"ret{N}"].mean(), bench=x[f"b{N}"].mean(), excess=ex.mean(), lo=lo, hi=hi)
        out.append(f"{N:>8} | {len(x):>4} | {f2(x[f'mfe{N}'].mean())}   | {f2(x[f'mae{N}'].mean())} / {f2(x[f'maeopt{N}'].mean())}    |"
                   f" {f2(x[f'ret{N}'].mean(),8)}          | {f2(x[f'ret{N}'].median())} | {f2(x[f'b{N}'].mean(),8)}  | {f2(ex.mean(),6)} |"
                   f" {f2(lo)} to {f2(hi)}                      | {f0((x[f'ret{N}'] > 0).mean() * 100)}")
    out.append("longs and shorts apart (exact return / benchmark / excess, ATR):")
    for side in ("long", "short"):
        for N in (1, 5):
            x = sub[(sub.side == side) & sub[f"ret{N}"].notna()]
            if len(x):
                out.append(f"  {side:5} {N} sessions: n={len(x):>4}  return {f2(x[f'ret{N}'].mean())}  benchmark {f2(x[f'b{N}'].mean())}  "
                           f"excess {f2((x[f'ret{N}'] - x[f'b{N}']).mean())}")
    x = sub[sub["ret5"].notna()]
    cons = {}
    if len(x):
        ex = x["ret5"] - x["b5"]
        e1, e2 = x[x.signal_date <= ERA_SPLIT], x[x.signal_date > ERA_SPLIT]
        cons["era1"] = (e1["ret5"] - e1["b5"]).mean()
        cons["era2"] = (e2["ret5"] - e2["b5"]).mean()
        yr = ex.groupby(x["year"]).agg(["mean", "count"])
        yr = yr[yr["count"] >= 5]
        cons["years_pos"], cons["years_n"] = int((yr["mean"] > 0).sum()), len(yr)
        trim = x["ret5"].sort_values().iloc[:max(int(len(x) * 0.95), 1)]
        cons["trim5"] = trim.mean()
        mk = ex.groupby(x["code"]).agg(["mean", "count"])
        mk = mk[mk["count"] >= 10]
        cons["mk_pos"], cons["mk_n"] = int((mk["mean"] > 0).sum()), len(mk)
        out.append(f"consistency at 5 sessions: excess to 2014 {f2(cons['era1'])} (n={len(e1)}), after 2014 {f2(cons['era2'])} (n={len(e2)});"
                   f" years positive {cons['years_pos']} of {cons['years_n']}; exact return without the best 5% of trades {f2(cons['trim5'])};"
                   f" markets with positive excess {cons['mk_pos']} of {cons['mk_n']} (markets with 10+ trades)")
    p1, p5 = placebo_pct(plain, sub, "ret1"), placebo_pct(plain, sub, "ret5")
    cons["placebo5"] = p5
    if v != "plain":
        out.append(f"random draws from the plain pattern (same size, same long/short mix, {PLACEBO_DRAWS} draws): this variant's mean exact return beats"
                   f" {f0(p1)}% of draws at 1 session and {f0(p5)}% at 5 sessions")
    # trailing exits
    t = sub[sub["trail_ret"].notna()]
    ex1 = crb.one_position_per_market(sub.assign(trail_ret=sub["trail_ret"])) if len(sub) else sub
    ex1 = ex1[ex1["trail_ret"].notna()]
    for name, d in (("event set (overlapping signals allowed)", t), ("one position per market", ex1)):
        if len(d):
            out.append(f"trailing-stop exit, {name}: n={len(d)}  gross mean {f2(d.trail_ret.mean(), 7)}  median {f2(d.trail_ret.median(), 7)}  "
                       f"win rate {f0((d.trail_ret > 0).mean() * 100)}%  mean hold {f2(d.trail_dur.mean(), 5)} sessions  "
                       f"net of 0.10 ATR cost {f2(d.trail_ret.mean() - COST_ATR, 7)}  (optimistic entry-session handling, gross: {f2(d.trailopt_ret.mean(), 6)})")
    cons["exec_net"] = (ex1.trail_ret.mean() - COST_ATR) if len(ex1) else np.nan
    return "\n".join(out), summary, cons


def band_table(tr):
    sub = tr[tr["filled"] & tr["plain"] & tr["withtrend_dist"].notna()]
    out = ["\n=== Descriptive: plain failed reversal by distance from the 200-day average (positive = on the trade's side) ===",
           "NOT a filter and no benchmark here; exact close-to-entry return in ATR. The cut used in the test is fixed at 0 to 2 ATR (declared before the run).",
           "band                                          |   n  | 1 session mean | 5 sessions mean | 5 sessions median"]
    for name, a, b in BANDS:
        x = sub[(sub["withtrend_dist"] > a) & (sub["withtrend_dist"] <= b)] if a > -np.inf else sub[sub["withtrend_dist"] <= b]
        if len(x):
            out.append(f"{name:<45} | {len(x):>4} | {f2(x['ret1'].mean(), 8)}       | {f2(x['ret5'].mean(), 8)}        | {f2(x['ret5'].median(), 8)}")
    return "\n".join(out)


def report(tr, bench, cover, outdir):
    plain = tr[tr["filled"]].copy()
    first, last = tr["signal_date"].min(), tr["signal_date"].max()
    head = ["FAILED REVERSAL WITH THE TREND, no COT filter, 48-market universe, development period only",
            f"signals {first.date()} to {last.date()} (last five years sealed); markets with prices {int((cover.bars > 0).sum())} of {len(cover)}",
            f"pattern days {len(tr)}; filled next session {int(tr['filled'].sum())} ({tr['filled'].mean() * 100:.0f}%)",
            "counts of filled trades by variant: " + "; ".join(f"{LABEL[v].split(' (')[0]}: {int((tr['filled'] & tr[v]).sum())}" for v in VARIANTS),
            "All returns in ATR (14-session ATR before entry). Excursions are worst-case / best-case for the adverse side because daily bars cannot order the entry session.",
            "Costs: gross unless labelled net of the standing 0.10 ATR round trip."]
    blocks, summ, cons = [], {}, {}
    for v in VARIANTS:
        b, s, c = variant_block(v, tr, plain, bench)
        blocks.append(b)
        summ[v], cons[v] = s, c
    verdict = ["\n=== Verdict against the pass rule declared before the run (at 5 sessions) ==="]
    for v in VARIANTS[1:]:
        s5, c = summ[v].get(5), cons[v]
        if not s5:
            verdict.append(f"{LABEL[v]}: no trades")
            continue
        a = s5["lo"] > 0
        bpass = c.get("placebo5", np.nan) >= 95
        cpass = (c.get("era1", np.nan) > 0) and (c.get("era2", np.nan) > 0)
        d = c.get("exec_net", np.nan) > 0
        verdict.append(f"{LABEL[v]}: (a) paired excess {f2(s5['excess'])} with 95% range {f2(s5['lo'])} to {f2(s5['hi'])}: {'pass' if a else 'fail'};"
                       f" (b) beats {f0(c.get('placebo5', np.nan))}% of random plain draws: {'pass' if bpass else 'fail'};"
                       f" (c) both eras positive ({f2(c.get('era1', np.nan))}, {f2(c.get('era2', np.nan))}): {'pass' if cpass else 'fail'};"
                       f" (d) one-position trailing exit net of cost {f2(c.get('exec_net', np.nan))}: {'pass' if d else 'fail'}"
                       f"  => {'SHOWS SOMETHING (still a lead)' if (a and bpass and cpass and d) else 'NOT SHOWN'}")
    text = "\n".join(head) + "\n" + "\n".join(blocks) + "\n" + band_table(tr) + "\n" + "\n".join(verdict) + "\n"
    out = Path(outdir)
    (out / "reversal_trend_results.txt").write_text(text)
    tr.to_csv(out / "trades.csv.gz", index=False)
    cover.to_csv(out / "coverage.csv", index=False)
    return text


# ------------------------------------------------------------------------------------------------ self-test
def _series(c, spread=0.5):
    n = len(c)
    d = pd.bdate_range("2010-01-01", periods=n)
    c = np.asarray(c, float)
    px = pd.DataFrame({"symbol": "T", "file_date": d.strftime("%Y-%m-%d"), "open": c, "high": c + spread, "low": c - spread, "close": c, "volume": 1})
    px["date"] = pd.to_datetime(px["file_date"])
    s, nd = crb.clean_series(px)
    assert nd == 0
    return s


def selftest():
    n = 320
    s = _series(100.0 + np.arange(n))
    f = features(s)
    i = 250
    assert abs(f["er"][i] - 1.0) < 1e-12                                    # a straight line is perfectly efficient
    assert abs(f["sma"][i] - (100 + np.mean(np.arange(51, 251)))) < 1e-9      # 200-session average of closes 51..250
    assert f["flags"]["long"]["trend200"][i] and not f["flags"]["short"]["trend200"][i]
    assert f["flags"]["long"]["eff20"][i] and not f["flags"]["short"]["eff20"][i]
    assert not f["flags"]["long"]["near200"][i]                                # about 66 ATR above the average, far beyond 2 ATR
    assert not f["flags"]["long"]["eff20_near200"][i]
    assert not f["flags"]["long"]["trend200"][100]                              # fewer than 200 bars: no reading
    zig = _series(100.0 + (np.arange(n) % 2))
    fz = features(zig)
    assert fz["er"][250] < 1e-12 and not fz["flags"]["long"]["eff20"][250] and not fz["flags"]["short"]["eff20"][250]
    # just-above case: flat then a small rise puts the close within 2 ATR above the average
    c = np.r_[np.full(300, 100.0), 100.0 + 0.2 * np.arange(1, 21)]
    sn = _series(c, spread=1.0)
    fn = features(sn)
    k = len(c) - 1
    assert 0 < fn["dist"][k] <= 2.0 and fn["flags"]["long"]["near200"][k] and not fn["flags"]["short"]["near200"][k]
    ad = anyday_returns(s)
    j = 251
    assert abs(ad[5][250] - (4.0 / s["atr"][250])) < 1e-9                       # buy open[j]=c[j], close 4 sessions later = +4
    assert np.isnan(ad[10][n - 3])                                              # incomplete window
    # sealed-period rule is inherited
    assert crb.SEAL_FIRST_DAY == pd.Timestamp("2021-11-08") and crb.DEV_LAST_SIGNAL == pd.Timestamp("2021-08-06")
    print("selftest ok")


def main():
    if len(sys.argv) >= 2 and sys.argv[1] == "selftest":
        selftest()
        return
    _, uni_path, px_path, outdir = sys.argv[1:5]
    Path(outdir).mkdir(parents=True, exist_ok=True)
    uni = pd.read_csv(uni_path, dtype={"code": str})
    prices = crb.read_prices(px_path)
    tr, bench, cover = collect(prices, uni)
    print(report(tr, bench, cover, outdir))


if __name__ == "__main__":
    main()
