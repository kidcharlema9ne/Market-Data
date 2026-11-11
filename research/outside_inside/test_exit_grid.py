"""Hand-built checks for the exit engine in exit_grid.py. Run: python research/outside_inside/test_exit_grid.py"""
import os
import sys
sys.path.insert(0, os.path.dirname(__file__))
import exit_grid as g


def trade(bars, entry=100.0, stop=90.0, atr=4.0, stopped_entry=False, ignore_low=False):
    """bars = list of (open, high, low, close), bar 0 is the entry bar; padded to CAP."""
    pad = [bars[-1]] * (g.CAP - len(bars))
    b = list(bars) + pad
    return dict(path=([x[0] for x in b], [x[1] for x in b], [x[2] for x in b], [x[3] for x in b]), entry=entry, stop=stop, risk=entry - stop,
                atr=atr, ignore_low=ignore_low, stopped_entry=stopped_entry)


def check(c, msg):
    assert c, msg
    print("ok:", msg)


flat = (105, 106, 104, 105)
# risk = 10. Entry bar then a run to 125 on bar 3, then fade.
runup = [(100, 102, 98, 101), (101, 108, 100, 107), (107, 115, 106, 114), (114, 125, 113, 124), (124, 124, 110, 112), (112, 113, 100, 101)]

r = g.run_exit(trade(runup), "time", 3, 3)
check(abs(r[0] - 1.4) < 1e-9 and r[1] == 3, "time exit at the close of session 3 = (114-100)/10")
r = g.run_exit(trade(runup), "target", 2.0, 20)
check(abs(r[0] - 2.0) < 1e-9 and r[2] == "target" and r[1] == 4, "target of 2 risk units (120) reached on session 4")
# stop first: bar 1 reaches both stop 90 and target 110
bad = [(100, 102, 98, 101), (101, 112, 89, 100)]
r = g.run_exit(trade(bad), "target", 1.0, 20)
check(r[0] == -1.0 and r[2] == "stop", "stop wins when stop and target are in the same later bar")
# gap through the stop
gapb = [(100, 102, 98, 101), (85, 88, 84, 86)]
r = g.run_exit(trade(gapb), "hold", 0, g.CAP)
check(abs(r[0] - (-1.5)) < 1e-9, "gap through the stop exits at the open (-1.5 risk units)")
# stopped on entry bar
r = g.run_exit(trade([(100, 101, 95, 100)], stopped_entry=True), "time", 5, 5)
check(r[0] == -1.0 and r[2] == "stopped on entry bar", "entry-bar stop is -1")
# trail 3-session low: lows 98,100,106,113 -> after session 3 trail=min(lows 3 bars)=min(100,106,113)... session3 low list [98,100,106]: min 98 <stop? stop stays 98>90
r = g.run_exit(trade(runup), "trail_low", 3, g.CAP)
# after session 4 (index 3): min(100,106,113)=100 -> stop 100; session 5 (index 4) low 110 >100 no stop; after: min(106,113,110)=106; session 6 low 100 <=106 -> exit at 106
check(abs(r[0] - 0.6) < 1e-9 and r[2] == "stop", "3-session-low trail exits at 106 on session 6")
# chandelier 2 ATR (atr 4): highest 125 after session 4 -> stop 117; session 5 low 110 <= 117 -> exit 117
r = g.run_exit(trade(runup), "chandelier", 2.0, g.CAP)
check(abs(r[0] - 1.7) < 1e-9 and r[1] == 5, "2 ATR chandelier exits at 117 on session 5")
# breakeven: high reaches 110 on session 2 -> stop to entry; time exit 20 after; later low 100 touches entry -> exit at 100 (0R) on session 6
r = g.run_exit(trade(runup), "be_time", 1.0, 20)
check(abs(r[0] - 0.0) < 1e-9 and r[1] == 6, "stop moved to entry after +1 risk unit is hit at the entry price on session 6")
# close break: session 5 close 112 < prior low 113 -> exit at close 112
r = g.run_exit(trade(runup), "close_break", 0, g.CAP)
check(abs(r[0] - 1.2) < 1e-9 and r[1] == 5, "close below the prior session's low exits at that close")
# ignore_low: entry bar low below stop is not counted
r = g.run_exit(trade([(100, 106, 85, 105)] + [flat] * 5, ignore_low=True), "time", 3, 3)
check(r[0] == 0.5 and r[4] == 0.0, "best-case rule ignores the entry bar's low")
print("ALL PASSED")
