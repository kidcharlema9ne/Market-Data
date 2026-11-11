"""Hand-built checks for outside_inside_day.py (no data needed). Run: python research/outside_inside/test_outside_inside_day.py"""
import os
import sys
import numpy as np
import pandas as pd
sys.path.insert(0, os.path.dirname(__file__))
import outside_inside_day as m


def series(bars, start="2026-01-05"):
    days = pd.bdate_range(start, periods=len(bars)).values.astype("datetime64[D]")
    a = np.array(bars, float)
    s = dict(d=days, o=a[:, 0], h=a[:, 1], l=a[:, 2], c=a[:, 3])
    pc = np.r_[np.nan, s["c"][:-1]]
    s["tr"] = np.maximum.reduce([s["h"] - s["l"], np.abs(s["h"] - pc), np.abs(s["l"] - pc)])
    return s


# 14 quiet bars (range 2), then prior day, outside day, inside day, then trade bars.
quiet = [(100, 101, 99, 100)] * 14
prior = (100, 101, 99, 100)
outside = (100, 105, 95, 100)      # high 105 > 101, low 95 < 99
inside = (100, 103, 97, 100)       # high 103 < 105, low 97 > 95 -> long stop 97, short stop 103; risk long 8 from 105; short 8 from 95


def run(after, direction=1, window=1, stop_rule="inside"):
    s = series(quiet + [prior, outside, inside] + after)
    return m.simulate(s, 15, direction, window, "stopped", stop_rule)   # index 15 = outside day


def check(cond, msg):
    assert cond, msg
    print("ok:", msg)


# 1. long, breaks 105 next day, then runs to 113 (+1R) and stays above the stop, closes 110
r = run([(104, 106, 100, 105)] + [(105, 114, 104, 110)] + [(110, 111, 109, 110)] * 20)
check(r["entry_price"] == 105 and r["stop_price"] == 97 and abs(r["risk_pct_of_price"] - 8 / 105 * 100) < 1e-9, "long entry at outside high, stop at inside low")
check(r["result_target_1.0"] == 1.0 and r["result_target_0.5"] == 0.5, "targets reached are credited exactly")
check(abs(r["best_run_risk_units"] - 9 / 8) < 1e-9, "best run measured from entry (114-105)/8")
check(r["worst_dip_risk_units"] == (105 - 100) / 8, "worst dip uses the entry bar's low too (conservative)")

# 2. long, entry bar touches stop without a gap -> stopped, flagged ambiguous
r = run([(100, 106, 96, 100)])
check(r["exit_reason"] == "stopped_on_entry_bar" and r["ambiguous_entry_bar"] and r["result_exit_session_10"] == -1.0, "ambiguous entry bar counted as stopped")

# 3. gap fill above trigger fills at the open and risk is larger
r = run([(108, 110, 107, 109)] + [(109, 110, 108, 109)] * 20)
check(r["entry_price"] == 108 and r["gap_fill"], "gap above the trigger fills at the open")
check(abs(r["risk_pct_of_price"] - 11 / 108 * 100) < 1e-9, "risk measured from the actual fill")

# 4. stop hit on a later bar; stop-out bar adds no favorable excursion
r = run([(104, 106, 100, 105), (105, 130, 96, 100)] + [(100, 101, 99, 100)] * 20)
check(r["exit_reason"] == "stopped" and r["result_exit_session_5"] == -1.0 and r["result_target_3.0"] == -1.0, "later stop-out is -1R and wins over a same-bar target")
check(r["best_run_risk_units"] == 1 / 8, "stop-out bar high ignored; only the entry bar's high counts")

# 5. stop gaps through on a later bar
r = run([(104, 106, 100, 105), (92, 93, 90, 91)] + [(91, 92, 90, 91)] * 20)
check(r["exit_reason"] == "stopped_gap" and abs(r["result_exit_session_5"] - (92 - 105) / 8) < 1e-9, "gap through the stop exits at the open")

# 6. order cancelled when the stop level trades first
check(run([(100, 104, 96.5, 100)]) is None, "stop traded before trigger cancels the order")
check(run([(100, 104, 99, 100)]) is None, "no break within one session: no trade")
r = run([(100, 104, 99, 100), (100, 106, 99, 105)] + [(105, 106, 104, 105)] * 20, window=5)
check(r is not None and r["sessions_waited"] == 2, "five-session window fills on the second session")

# 7. short mirrors long: trigger 95, stop 103, risk 8
r = run([(96, 97, 94, 95)] + [(95, 96, 86, 88)] + [(88, 89, 87, 88)] * 20, direction=-1)
check(r["entry_price"] == 95 and r["stop_price"] == 103, "short entry at outside low, stop at inside high")
check(r["result_target_1.0"] == 1.0 and abs(r["best_run_risk_units"] - 9 / 8) < 1e-9, "short run measured downward")

# 7b. stop at the outside day's far side: long stop 95 (outside low), risk 10 from 105; short stop 105, risk 10 from 95
r = run([(104, 106, 100, 105)] + [(105, 125, 104, 120)] + [(120, 121, 119, 120)] * 20, stop_rule="outside")
check(r["stop_price"] == 95 and abs(r["risk_pct_of_price"] - 10 / 105 * 100) < 1e-9 and r["result_target_1.0"] == 1.0 and abs(r["best_run_risk_units"] - 2.0) < 1e-9, "long with outside-day stop: stop 95, risk 10, run measured in those units")
r = run([(104, 106, 96, 100)] + [(100, 101, 99, 100)] * 20, stop_rule="outside")
check(r["exit_reason"] != "stopped_on_entry_bar" and r["stop_price"] == 95, "entry bar low 96 stays above the outside-day stop (it would have hit the inside-day stop)")
r = run([(100, 104, 96.5, 100), (100, 106, 99, 105)] + [(105, 106, 104, 105)] * 20, window=5, stop_rule="outside")
check(r is not None and r["sessions_waited"] == 2, "outside-day stop: a dip to 96.5 does not cancel the order")
r = run([(96, 97, 94, 95)] + [(95, 96, 86, 88)] + [(88, 89, 87, 88)] * 20, direction=-1, stop_rule="outside")
check(r["entry_price"] == 95 and r["stop_price"] == 105, "short with outside-day stop at the outside high")

# 8. setup finder: needs strict outside then strict inside
s = series(quiet + [prior, outside, inside, (104, 106, 100, 105)] + [(105, 106, 104, 105)] * 20)
df = m.find_trades({"X": s}, ["X"], np.datetime64("2026-01-01"), 1, "stopped", "inside")
check(len(df) == 1 and df.iloc[0]["direction"] == "long", "finder produces one long trade, no short (low never broke)")
s2 = series(quiet + [prior, outside, (100, 105, 97, 100), (104, 106, 100, 105)] + [(105, 106, 104, 105)] * 20)
check(m.find_trades({"X": s2}, ["X"], np.datetime64("2026-01-01"), 1).empty, "inside day equal to the outside high is not strictly inside")
print("ALL PASSED")
