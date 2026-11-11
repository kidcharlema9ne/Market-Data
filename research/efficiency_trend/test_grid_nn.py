"""Checks for grid_search.py and nn_walk_forward.py: no lookahead in features, sealed window, purge between train and test. Run: python research/efficiency_trend/test_grid_nn.py"""
import os
import sys
import numpy as np
import pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nn_walk_forward as nn
import grid_search as gs
eg, tf, et = nn.eg, nn.tf, nn.et

days = pd.bdate_range("2008-01-01", periods=900).values.astype("datetime64[D]")
rng = np.random.default_rng(3)
c = 100 + np.cumsum(rng.normal(0.2, 1, 900))
o = np.r_[c[0], c[:-1]]
h = np.maximum(o, c) + 0.5
l = np.minimum(o, c) - 0.5
pc = np.r_[np.nan, c[:-1]]
s = dict(d=days, o=o, h=h, l=l, c=c, tr=np.maximum.reduce([h - l, abs(h - pc), abs(l - pc)]))
prices = {"X": s}
tf.add_trend(prices, (5, 10, 20, 40))
# features at row i do not change when data after i is changed
i = 300
f1 = nn.row_features(s, i, 1)
s2 = {k: (v.copy() if hasattr(v, "copy") else v) for k, v in s.items()}
for k in ("o", "h", "l", "c", "tr"):
    s2[k][i + 1:] = s2[k][i + 1:] * 3 + 7
p2 = {"X": s2}
tf.add_trend(p2, (5, 10, 20, 40))
f2 = nn.row_features(s2, i, 1)
assert all(abs(f1[k] - f2[k]) < 1e-9 for k in f1), "features must use only data up to the signal close"
# dataset is sealed and has finite values
df = nn.build_dataset(prices, ["X"])
assert len(df) > 20 and df["setup_date"].max() <= pd.Timestamp(str(eg.IN_END)), "sealed window"
assert np.isfinite(df[nn.FEATURES].values).all()
# purge: no training trade within 90 days of the test year, and no test trade outside the year
tr, te = nn.split_year(df, 2010)
assert tr["setup_date"].max() < pd.Timestamp("2010-01-01") - pd.Timedelta(days=90)
assert te["setup_date"].min() >= pd.Timestamp("2010-01-01") and te["setup_date"].max() < pd.Timestamp("2011-01-02")
# half Sharpe helper
idx = pd.date_range("2010-01-01", "2020-01-01", freq="B")
r = pd.Series(np.where(np.arange(len(idx)) % 2 == 0, 1.0, -1.0) + 0.1, index=idx)
a, b = gs.half_sharpes(r / gs.ts.RISK_PER_TRADE)
assert a > 0 and b > 0, "positive mean gives positive Sharpe in both halves"
print("ALL PASSED")
