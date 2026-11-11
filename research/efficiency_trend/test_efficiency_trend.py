"""Checks for efficiency_trend.py (sealed window, entry at the open, 2 ATR stop, one position at a time). Run: python research/efficiency_trend/test_efficiency_trend.py"""
import os
import sys
import numpy as np
import pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import efficiency_trend as et
eg, tf = et.eg, et.tf

days = pd.bdate_range("2020-01-01", periods=500).values.astype("datetime64[D]")


def series(c, rng_pad=0.5):
    c = np.asarray(c, float)
    o = np.r_[c[0], c[:-1]]            # open = prior close
    h = np.maximum(o, c) + rng_pad
    l = np.minimum(o, c) - rng_pad
    s = dict(d=days[:len(c)], o=o, h=h, l=l, c=c)
    pc = np.r_[np.nan, c[:-1]]
    s["tr"] = np.maximum.reduce([h - l, abs(h - pc), abs(l - pc)])
    return s


# A clean uptrend: efficiency ratio is high, the rule goes long at the next open with a stop 2 ATR below it
c = 100 + np.arange(500) * 1.0
s = series(c)
prices = {"X": s}
tf.add_trend(prices, et.LOOKBACKS)
t = et.make_trade(s, 40, 1)
atr = float(np.nanmean(s["tr"][27:41]))
assert abs(t["entry"] - s["o"][41]) < 1e-9 and abs(t["risk"] - 2 * atr) < 1e-9 and abs(t["stop"] - (t["entry"] - 2 * atr)) < 1e-9, "entry at the next open, stop 2 ATR"
assert not t["stopped_entry"]
recs = et.run_system(prices, ["X"], et.EXITS[3], 0.5, 20, "fresh")        # hold until stopped
assert recs and all(r["direction"] == "long" for r in recs), "uptrend gives longs"
assert all(r["setup_date"] <= eg.IN_END for r in recs), "nothing after the in-sample end"
# sealed window: in this series dates run to 2021-11 (500 business days from 2020-01-01); no setup after 2021-08-06
assert max(r["setup_date"] for r in recs) <= np.datetime64("2021-08-06")
# a downtrend gives shorts, and "against" flips the side
dn = series(1000 - np.arange(500) * 1.0)
p2 = {"X": dn}
tf.add_trend(p2, et.LOOKBACKS)
assert all(r["direction"] == "short" for r in et.run_system(p2, ["X"], et.EXITS[3], 0.5, 20, "fresh"))
assert all(r["direction"] == "long" for r in et.run_system(p2, ["X"], et.EXITS[3], 0.5, 20, "fresh", "against"))
# one position at a time: with a 10-session time exit, entries are at least 10 sessions apart; 'fresh' gives one signal in a never-ending trend
r10 = et.run_system(prices, ["X"], et.EXITS[0], 0.5, 20, "whenflat")
idx = [r["entry_idx"] for r in r10]
assert all(b - a >= 10 for a, b in zip(idx, idx[1:])), "no overlapping positions"
assert len(et.run_system(prices, ["X"], et.EXITS[0], 0.5, 20, "fresh")) == 1, "a continuous trend is one fresh signal"
# a stop is hit when price falls more than 2 ATR on the entry bar
c2 = list(c[:60]) + [c[59] - 50] + list(c[59] - 50 + np.arange(1, 441))
s2 = series(c2)
t2 = et.make_trade(s2, 59, 1)
assert t2["stopped_entry"] and et.ts.daily_path(t2, et.EXITS[3]) == [-1.0], "big drop on the entry bar is a -1 unit loss"
print("ALL PASSED")
