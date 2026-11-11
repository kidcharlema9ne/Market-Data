"""Checks for trail_stats.py. Run: python research/outside_inside/test_trail_stats.py"""
import os
import sys
import numpy as np
import pandas as pd
sys.path.insert(0, os.path.dirname(__file__))
import trail_stats as ts
import test_exit_grid as tg  # noqa: F401  (re-runs the engine tests too)

t = tg.trade(tg.runup)
path = ts.daily_path(t, ("x", "chandelier", 2.0, 60))
assert np.allclose(path, [0.1, 0.7, 1.4, 2.4, 1.7]), path   # closes 101,107,114,124 then the trail exit at 117 -> 1.7
assert ts.daily_path(tg.trade([(100, 101, 95, 100)], stopped_entry=True)) == [-1.0]
# performance on a hand-made daily series (risk units): [1, 1, -3, 1] with 0.005 risk per trade
idx = pd.bdate_range("2020-01-01", periods=4)
daily = pd.Series([1.0, 1.0, -3.0, 1.0], index=idx)
perf = ts.performance(daily, pd.Series([1, 1, 1, 1], index=idx), np.array([1.0, 1.0, -3.0, 1.0]))
assert abs(perf["max_drawdown_R"] - 3.0) < 1e-9 and abs(perf["max_drawdown_pct"] - 1.5) < 1e-9, perf
assert perf["win_rate"] == 0.75 and abs(perf["profit_factor"] - 1.0) < 1e-9 and perf["trades"] == 4
ret = daily * 0.005
years = (idx[-1] - idx[0]).days / 365.25
assert abs(perf["sharpe"] - (ret.sum() / years) / (ret.std() * np.sqrt(252))) < 1e-9
print("ALL PASSED")
