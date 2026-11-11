"""Checks for oos_single.py: no bars are clipped, signal windows are respected, partial paths are marked at the last close and equal the engine otherwise.
Run: python research/efficiency_trend/test_oos_single.py"""
import os
import sys
import numpy as np
import pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import oos_single as os_
em = os_.em
eg, tf = em.eg, em.tf

days = pd.bdate_range("2019-01-01", periods=900).values.astype("datetime64[D]")


def series(c, pad=0.5, n=None):
    c = np.asarray(c, float)[:n]
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) + pad
    l = np.minimum(o, c) - pad
    pc = np.r_[np.nan, c[:-1]]
    return dict(d=days[:len(c)], o=o, h=h, l=l, c=c, tr=np.maximum.reduce([h - l, abs(h - pc), abs(l - pc)]))


def prep(c, n=None):
    p = {"X": series(c, n=n)}
    os_.prepare(p, ["X"])
    tf.add_trend(p, (20,))
    return p


# a zigzag (no trend) that turns into a straight uptrend on 2021-12-01, well inside the out-of-sample years
turn = int(np.searchsorted(days, np.datetime64("2021-12-01")))
c = np.r_[100 + (np.arange(turn) % 2) * 1.0, 100 + np.arange(900 - turn) * 1.0]
p = prep(c)
s = p["X"]

# 1. nothing is clipped
assert s["d"].max() > eg.OUT_START and len(s["d"]) == 900, "out-of-sample bars are kept"

# 2. signal windows
oos = os_.candidates_window(s, 20, 0.6, eg.OUT_START, np.datetime64("2100-01-01"))
ins = os_.candidates_window(s, 20, 0.6, os_.IN_SIGNAL_START, os_.IN_SIGNAL_END)
assert len(oos) == 1 and oos[0][1] == 1 and s["d"][oos[0][0]] >= eg.OUT_START, "one fresh long signal, in the out-of-sample window"
assert ins == [], "no in-sample signal in a zigzag"
assert abs(s["d"][oos[0][0]] - np.datetime64("2021-12-01")) < np.timedelta64(40, "D"), "the signal comes shortly after the trend starts"
i = oos[0][0]

# 3. complete path: partial and strict engines agree, trade ends at the cap
a = em.simulate(s, i, 1, 3.0, "fixed", 0, 60)
b = os_.simulate_partial(s, i, 1, 3.0, "fixed", 0, 60)
assert a[1:] == b[1:] and np.allclose(a[0], b[0]) and a[2] == "cap" and len(a[0]) == 60, "same trade when the full 60 sessions exist"

# 4. data ends 25 sessions after the entry: strict engine rejects, partial marks at the last close
p2 = prep(c, n=i + 26)
s2 = p2["X"]
assert em.simulate(s2, i, 1, 3.0, "fixed", 0, 60) is None, "strict engine drops a signal whose 60 sessions do not exist"
path, j, reason, atr = os_.simulate_partial(s2, i, 1, 3.0, "fixed", 0, 60)
assert reason == "forced" and len(path) == len(s2["c"]) - j, "marked at the last close"
assert abs(path[-1] - (s2["c"][-1] - s2["o"][j]) / atr) < 1e-9, "result equals last close minus entry open, in ATR"
assert np.allclose(path, a[0][:len(path)]), "the partial path is the start of the full path"

# 5. a stop is honoured in the partial engine (gap down through the stop fills at the open)
c3 = c.copy()
c3[i + 10:] = c3[i + 9] - 40
p3 = prep(c3, n=i + 26)
r = os_.simulate_partial(p3["X"], i, 1, 3.0, "fixed", 0, 60)
assert r[2] == "stop" and r[0][-1] < -3.0 + 1e-9, "stop fills at the open when the market gaps through it"

# 6. block bootstrap returns an ordered interval
ci, p_le0 = os_.block_bootstrap_sharpe(pd.Series(np.random.default_rng(0).normal(0.0005, 0.01, 800)), reps=300)
assert ci[0] <= ci[1] <= ci[2] and 0 <= p_le0 <= 1
print("oos_single tests passed")
