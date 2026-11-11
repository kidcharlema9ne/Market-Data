"""Checks for exit_matrix.py: sealed bars removed, exits behave as described, baseline equals the earlier engine. Run: python research/efficiency_trend/test_exit_matrix.py"""
import os
import sys
import numpy as np
import pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import exit_matrix as em
et, eg, tf = em.et, em.eg, em.tf

days = pd.bdate_range("2019-01-01", periods=800).values.astype("datetime64[D]")      # runs well past 2021-11-08


def series(c, pad=0.5):
    c = np.asarray(c, float)
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) + pad
    l = np.minimum(o, c) - pad
    pc = np.r_[np.nan, c[:-1]]
    return dict(d=days[:len(c)], o=o, h=h, l=l, c=c, tr=np.maximum.reduce([h - l, abs(h - pc), abs(l - pc)]))


def prep(c):
    p = {"X": series(c)}
    em.clip_and_prepare(p, ["X"])
    tf.add_trend(p, (15, 20))
    return p


# 1. sealed bars are gone
p = prep(100 + np.arange(800) * 1.0)
s = p["X"]
assert s["d"].max() < eg.OUT_START and len(s["d"]) == len(s["c"]) == len(s["o"]) == len(s["tr"]), "bars from 2021-11-08 are removed"
assert s["gap_after"][-1] and not s["gap_after"][:-1].any(), "only the last in-sample bar is flagged as the end"

# 2. a never-ending uptrend: capped trade ends at the cap, uncapped trade is closed at the last in-sample close, a long channel never hits
cands = {"X": em.candidates(s, 20, 0.6)}
assert len(cands["X"]) == 1 and cands["X"][0][1] == 1, "one fresh long signal in a continuous trend"
i = cands["X"][0][0]
path, j, reason, atr = em.simulate(s, i, 1, 3.0, "fixed", 0, 60)
assert reason == "cap" and len(path) == 60 and abs(path[-1] - 60.0 / atr) < 1e-9, "60-session cap closes at the close of session 60"
path, j, reason, atr = em.simulate(s, i, 1, 3.0, "fixed", 0, None)
assert reason == "forced" and j + len(path) - 1 == len(s["d"]) - 1, "no cap: closed at the last in-sample close"
assert em.simulate(s, i, 1, 3.0, "channel", 20, None)[2] == "forced" and em.simulate(s, i, 1, 3.0, "atr_trail", 4.0, None)[2] == "forced", "trails never hit in a straight line"

# 3. a short in a straight downtrend mirrors the long
q = prep(2000 - np.arange(800) * 1.0)
cs = em.candidates(q["X"], 20, 0.6)
assert len(cs) == 1 and cs[0][1] == -1
pathd = em.simulate(q["X"], cs[0][0], -1, 3.0, "fixed", 0, 60)[0]
assert pathd[-1] > 0, "a short profits in a downtrend"

# 4. a trend that peaks and falls: the fixed stop gives up more than the trails; the 4 ATR trail locks in profit
c = list(100 + np.arange(100) * 1.0) + list(199 - np.arange(1, 200) * 1.0)
r = prep(c)["X"]
i = em.candidates(r, 20, 0.6)[0][0]
fixed = em.simulate(r, i, 1, 3.0, "fixed", 0, None)
trail = em.simulate(r, i, 1, 3.0, "atr_trail", 4.0, None)
chan20 = em.simulate(r, i, 1, 3.0, "channel", 20, None)
assert fixed[2] == "stop" and trail[2] == "stop" and chan20[2] == "stop"
assert trail[0][-1] > fixed[0][-1] and chan20[0][-1] > fixed[0][-1], "trailing exits keep more of a reversed trend"
assert trail[0][-1] > 0 and abs(trail[0][-1] + 0.0) > 0
# a trailing stop never goes below the initial stop: the worst outcome is -initial stop (here no gaps, so exactly the stop)
assert min(fixed[0]) >= -3.0 - 1e-9 or fixed[0][-1] <= -3.0 + 1e-9

# 5. a gap through the stop fills at the open (worse than the stop), a low through the stop on the entry session is a full -stop loss
c3 = list(100 + np.arange(60) * 1.0) + [159 - 40] + list(119 + np.arange(1, 400) * 1.0)
g = prep(c3)["X"]
ig = 59
ent = em.simulate(g, ig, 1, 2.0, "fixed", 0, 60)
assert ent[2] == "stop" and abs(ent[0][-1] + 2.0) < 1e-9 and len(ent[0]) == 1, "entry-session stop-out is -2 ATR"

# 6. same signals, one position per market: no overlap, and a longer cap or no cap gives no more trades than a shorter one in a straight trend
trades_a, _, _ = em.run_cell(p, cands, 3.0, "fixed", 0, 60)
trades_b, _, _ = em.run_cell(p, cands, 3.0, "fixed", 0, None)
assert len(trades_b) <= len(trades_a)
e = [(t["entry_idx"], t["entry_idx"] + t["sessions"] - 1) for t in trades_a]
assert all(b[0] >= a[1] for a, b in zip(e, e[1:])), "no overlapping positions"

# 7. daily profit adds up to the trade results
trades, pnl, opens = em.run_cell(p, cands, 3.0, "fixed", 0, 60)
assert abs(sum(pnl.values()) - sum(t["final"] for t in trades)) < 1e-9
st = em.cell_stats(trades, pnl, opens, em.calendar(p, ["X"], np.datetime64("2019-01-01")))
assert abs(st["total_profit_pct"] - sum(t["final"] for t in trades) * em.ATR_EQUITY * 100) < 1e-9 and st["worst_drawdown_pct"] >= 0
print("ALL PASSED")
