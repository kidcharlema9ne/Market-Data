"""Checks for the efficiency ratio and the sealed window in trend_filter.py. Run: python research/outside_inside/test_trend_filter.py"""
import os
import sys
import numpy as np
sys.path.insert(0, os.path.dirname(__file__))
import trend_filter as tf
import exit_grid as eg

up = np.arange(1.0, 41.0)
er, net = tf.efficiency_arrays(up)
assert abs(er[25] - 1.0) < 1e-12 and net[25] > 0 and np.isnan(er[10]), "straight line has efficiency 1"
zig = np.array([100.0, 101.0] * 25)
er, net = tf.efficiency_arrays(zig)
assert er[30] < 0.06, "pure chop has efficiency near 0"
down = np.arange(40.0, 0.0, -1.0)
er, net = tf.efficiency_arrays(down)
assert er[25] == 1.0 and net[25] < 0, "downtrend: efficiency 1, negative net change"
# 20 sessions: |net| / path. closes: 10 steps of +2 then 10 steps of -1 -> net = +10, path = 30 -> 1/3
steps = np.r_[100.0, 100.0 + np.cumsum(np.r_[np.full(10, 2.0), np.full(10, -1.0)])]
er, net = tf.efficiency_arrays(steps)
assert abs(er[20] - 10 / 30) < 1e-12, "hand-computed efficiency 1/3"
# sealed window: a synthetic series running past 2021-08-06 yields no trade dated after it
import pandas as pd
days = pd.bdate_range("2021-01-04", periods=400).values.astype("datetime64[D]")
rng = np.random.default_rng(5)
c = 100 + np.cumsum(rng.normal(0, 1, 400))
o = c + rng.normal(0, .3, 400)
h = np.maximum(o, c) + abs(rng.normal(0, .6, 400))
l = np.minimum(o, c) - abs(rng.normal(0, .6, 400))
s = dict(d=days, o=o, h=h, l=l, c=c)
pc = np.r_[np.nan, c[:-1]]
s["tr"] = np.maximum.reduce([h - l, abs(h - pc), abs(l - pc)])
prices = {"X": s}
tf.add_trend(prices)
for kind in ("pattern", "control A", "control B"):
    trades = tf.gen_trades(prices, ["X"], kind)
    assert trades and all(t["setup_date"] <= eg.IN_END for t in trades), f"{kind}: nothing after the in-sample end"
print("ALL PASSED")
