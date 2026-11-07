"""Stand-alone test of ONE pre-specified question on ChatGPT's 91 liquid four-plus trades:
do trades entered after SPY rose >= 0.5 of its own ATR over the prior 15 sessions have higher excess?
(0.5 is the cut-off already written into D-055 before this test, not picked from these results.)
Imports ChatGPT's code unchanged for the cohort; everything else is new and read-only."""
import contextlib, datetime, io, sys
from collections import Counter, defaultdict
with contextlib.redirect_stdout(io.StringIO()):
    from liquidity_tiers import *   # ChatGPT's code, unchanged
import numpy as np

trades = []
for tier, adv, opening, entry, ticker, row in sample:
    if adv < 3_000_000: continue
    index = days.index(entry)
    regime = float((D(spy[days[index-1]]['close']) - D(spy[days[index-16]]['close'])) /
                   mean(true_range(k) for k in range(index-14, index)))
    trades.append((entry, regime, float(returns(row)[2]), ticker,
                   datetime.date.fromisoformat(entry).isocalendar()[:2]))
assert len(trades) == 91
entry = np.array([t[0] for t in trades]); reg = np.array([t[1] for t in trades])
y = np.array([t[2] for t in trades]); wk = [t[4] for t in trades]
up = reg >= 0.5
print(f"SELF-CHECK rising n={up.sum()} mean={y[up].mean():+.3f} | not rising n={(~up).sum()} mean={y[~up].mean():+.3f}")
d = y[up].mean() - y[~up].mean()
print(f"observed: rising minus not-rising = {d:+.3f} ATR")

# is the flag constant within an entry date? (it depends only on the date)
by_date = defaultdict(set)
for e, f in zip(entry, up): by_date[e].add(bool(f))
print("dates:", len(by_date), "| dates where flag differs inside a date:", sum(len(v) > 1 for v in by_date.values()))

# --- how the 39 spread over time
print("\n-- SPREAD OF THE RISING-MARKET TRADES")
print("distinct entry dates:", len(set(entry[up])), "| distinct calendar weeks:", len({wk[i] for i in np.where(up)[0]}))
wsum = defaultdict(float); wn = Counter()
for i in np.where(up)[0]:
    wsum[wk[i]] += y[i]; wn[wk[i]] += 1
tot = sum(wsum.values())
print("weeks ranked by their share of the total rising-market excess (sum of excess, trades):")
for w, s in sorted(wsum.items(), key=lambda kv: -kv[1])[:6]:
    print(f"   {w[0]}-W{w[1]:02d}: {s:+7.2f} ATR over {wn[w]} trades = {s/tot*100:5.1f}% of total {tot:+.1f}")
srt = np.sort(y[up])[::-1]
print(f"mean without best trade: {srt[1:].mean():+.3f} | without best 3 trades: {srt[3:].mean():+.3f} | median: {np.median(y[up]):+.3f}")
bw = max(wsum, key=wsum.get)
keep = np.array([wk[i] != bw for i in range(91)]) & up
print(f"mean without the single best WEEK ({bw[0]}-W{bw[1]:02d}): {y[keep].mean():+.3f} on {keep.sum()} trades")
print(f"share of rising trades with positive excess: {(y[up]>0).mean()*100:.0f}% | not rising: {(y[~up]>0).mean()*100:.0f}%")

# --- permutation tests
rng = np.random.default_rng(20261107)
B = 20000
print("\n-- PERMUTATION TESTS (one question, one cut-off)")
cnt = 0
for _ in range(B):
    yy = rng.permutation(y)
    cnt += (yy[up].mean() - yy[~up].mean()) >= d
print(f"A) shuffle results across all 91 trades: chance matches {d:+.2f} in {(cnt+1)/(B+1)*100:.1f}% of {B}")
dates = sorted(by_date); flag = np.array([list(by_date[x])[0] for x in dates])
idx = {x: i for i, x in enumerate(dates)}; di = np.array([idx[e] for e in entry])
cnt = 0; used = 0
for _ in range(B):
    f = rng.permutation(flag)[di]
    if f.sum() < 5 or (~f).sum() < 5: continue
    used += 1
    cnt += (y[f].mean() - y[~f].mean()) >= d
print(f"B) reassign the rising/not-rising label by DATE (keeps same-day trades together): "
      f"chance matches in {(cnt+1)/(used+1)*100:.1f}% of {used}")
# --- week-block bootstrap interval for the rising mean and for the difference
weeks = sorted(set(wk)); W = {w: [i for i in range(91) if wk[i] == w] for w in weeks}
bm, bd = [], []
for _ in range(10000):
    pick = rng.integers(0, len(weeks), len(weeks))
    ii = np.concatenate([W[weeks[p]] for p in pick]).astype(int)
    u = up[ii]
    if u.sum() < 5 or (~u).sum() < 5: continue
    bm.append(y[ii][u].mean()); bd.append(y[ii][u].mean() - y[ii][~u].mean())
print(f"\nC) week-block bootstrap, 95% interval: rising-market mean {np.percentile(bm,2.5):+.2f} to {np.percentile(bm,97.5):+.2f}; "
      f"difference {np.percentile(bd,2.5):+.2f} to {np.percentile(bd,97.5):+.2f}")
print("\n-- SAME QUESTION AT NEIGHBOURING CUT-OFFS (is 0.5 a lucky spot?)")
for c in (0.0, 0.25, 0.5, 0.75, 1.0):
    m = reg >= c
    print(f"   SPY >= {c:4.2f}: rising n={m.sum():3d} mean {y[m].mean():+.2f} | not rising n={(~m).sum():3d} mean {y[~m].mean():+.2f}")
