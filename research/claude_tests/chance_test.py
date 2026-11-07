"""Chance (data-snooping) test on ChatGPT's 91 liquid four-plus trades.

Imports ChatGPT's recovered code UNCHANGED (liquidity_tiers -> wider -> matrix_warm) for the cohort, entry
features, SPY bars and per-trade excess. Everything below the import is new code and only reads that cohort.

Question: if outcomes had no link to the setup features, how often would a hunt over a menu of slices
(CFO yes/no, SPY threshold, stock-decline band) still find a slice as good as the one we found?
Method: shuffle the per-trade excess among trades (all at once, and within the same calendar week to keep
common market moves together), rerun the same hunt each time, and count how often chance matches the real best.
"""
import contextlib, datetime, io, sys
with contextlib.redirect_stdout(io.StringIO()):
    from liquidity_tiers import *   # ChatGPT's code, unchanged
import numpy as np

B = 5000
FLOOR = 3_000_000
trades = []
for tier, adv, opening, entry, ticker, row in sample:
    if adv < FLOOR:
        continue
    index = days.index(entry)
    regime = float((D(spy[days[index-1]]['close']) - D(spy[days[index-16]]['close'])) /
                   mean(true_range(k) for k in range(index-14, index)))
    decline = float(-D(row['entry_features']['prior_returns']['15']['atr']))
    excess = float(returns(row)[2])
    week = datetime.date.fromisoformat(entry).isocalendar()[:2]
    trades.append(dict(cfo=tier >= 2, regime=regime, decline=decline, y=excess, week=week, tier=tier,
                       ticker=ticker, entry=entry))
N = len(trades)
assert N == 91, N
y0 = np.array([t['y'] for t in trades])
cfo = np.array([t['cfo'] for t in trades]); reg = np.array([t['regime'] for t in trades])
dec = np.array([t['decline'] for t in trades])

setup = (reg >= 0.5) & (dec >= 2) & (dec <= 5)
print(f"SELF-CHECK trades={N}  price setup n={setup.sum()} mean excess={y0[setup].mean():+.3f} "
      f"median={np.median(y0[setup]):+.3f}   (ChatGPT reported 15, +1.42, +1.27)")
cs = setup & cfo
print(f"SELF-CHECK CFO+setup n={cs.sum()} mean excess={y0[cs].mean():+.3f}   (ChatGPT tier 3 kept: 7, +1.68)")
print(f"SELF-CHECK all 91 mean excess={y0.mean():+.3f}  median={np.median(y0):+.3f}")
print(f"entry dates={len({t['entry'] for t in trades})} weeks={len({t['week'] for t in trades})}")

def build(cfos, spys, bands):
    names, masks = [], []
    for c in cfos:
        for s in spys:
            for b in bands:
                m = np.ones(N, bool)
                if c is not None: m &= (cfo == c)
                if s is not None: m &= (reg >= s)
                if b is not None: m &= (dec >= b[0]) & (dec <= b[1])
                names.append(f"CFO={c} SPY>={s} decline={b}")
                masks.append(m)
    return names, np.array(masks, float)

small = build([None, True, False], [None, 0.5], [None, (2, 5)])
bands_wide = [None] + [(lo, hi) for lo in (0.5, 1, 1.5, 2, 2.5, 3) for hi in (2, 3, 4, 5, 6, 8, 99) if hi > lo]
wide = build([None, True, False], [None, 0.0, 0.25, 0.5, 0.75, 1.0], bands_wide)

def stats(M, y, minn):
    n = M.sum(1)
    s1 = M @ y; s2 = M @ (y * y)
    with np.errstate(all='ignore'):
        mean_ = s1 / n
        var = (s2 - n * mean_ ** 2) / (n - 1)
        t = mean_ / np.sqrt(var / n)
    ok = n >= minn
    return n, mean_, t, ok

def best(M, y, minn, which):
    n, mean_, t, ok = stats(M, y, minn)
    v = np.where(ok, mean_ if which == 'mean' else t, -np.inf)
    return v.max(), int(v.argmax())

def shuffles(kind, rng):
    if kind == 'all':
        return lambda: rng.permutation(y0)
    groups = {}
    for i, t in enumerate(trades):
        groups.setdefault(t['week'], []).append(i)
    idx = [np.array(g) for g in groups.values()]
    def f():
        y = y0.copy()
        for g in idx:
            y[g] = rng.permutation(y0[g])
        return y
    return f

for label, (names, M) in (("SMALL menu (12 slices: the choices actually named in the spec)", small),
                          (f"WIDE menu ({len(small[0]) and len(wide[0])} slices: more SPY cut-offs and decline bands)", wide)):
    print("\n" + "=" * 100); print(label)
    for which, minn, what in (('mean', 15, 'best MEAN excess among slices with at least 15 trades'),
                              ('t', 8, 'best t-statistic (mean / standard error) among slices with at least 8 trades')):
        obs, k = best(M, y0, minn, which)
        n, mean_, t, ok = stats(M, y0, minn)
        print(f"\n-- {what}")
        print(f"   eligible slices: {int(ok.sum())}")
        print(f"   REAL data best: {obs:+.3f}  <- {names[k]}  (n={int(n[k])}, mean={mean_[k]:+.3f})")
        top = np.argsort(-np.where(ok, mean_ if which == 'mean' else t, -np.inf))[:5]
        for j in top:
            print(f"      top: {names[j]:<48} n={int(n[j]):<3} mean={mean_[j]:+.3f} t={t[j]:+.2f}")
        for kind in ('all', 'within-week'):
            rng = np.random.default_rng(20261107)
            f = shuffles('all' if kind == 'all' else 'wk', rng)
            sims = np.array([best(M, f(), minn, which)[0] for _ in range(B)])
            p = (1 + (sims >= obs).sum()) / (B + 1)
            print(f"   shuffle {kind:<11}: chance gets >= real best in {p*100:5.1f}% of {B} shuffles | "
                  f"typical chance best (median) {np.median(sims):+.3f}, 90th pct {np.percentile(sims,90):+.3f}, "
                  f"95th pct {np.percentile(sims,95):+.3f}")
