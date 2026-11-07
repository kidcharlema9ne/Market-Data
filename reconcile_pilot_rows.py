"""Try definitions of the pilot's depth-band rows to see which reproduces the spec table. Read-only."""
from collections import defaultdict
from statistics import mean
from decline_regime_test import build

TARGET = {"Flat": (132, 0.63, 0.06), "Up": (455, 0.26, 0.06)}


def equal_date(rows, key):
    by = defaultdict(list)
    for r in rows:
        by[r["entry_day"]].append(r[key])
    return mean(mean(v) for v in by.values())


def main():
    rows = build()
    print("\nSpec table: Flat 132 entries, stock +0.63, SPY +0.06; Up 455 entries, stock +0.26, SPY +0.06 (equal weight per entry date)")
    for lag_name, lag in (("lagged all three ETFs", lambda r: r["lag"]), ("no lag condition", lambda r: True)):
        for band_name, band in (("-2 < decline <= -0.5", lambda r: -2 < r["decl"] <= -0.5), ("-2 <= decline < -0.5", lambda r: -2 <= r["decl"] < -0.5)):
            for regime in ("Flat", "Up"):
                g = [r for r in rows if lag(r) and band(r) and r["regime"] == regime]
                if g:
                    print(f"  {lag_name:<22} {band_name:<22} SPY {regime.lower():<5} entries {len(g):>4}  stock {mean(r['stock'] for r in g):+.2f} (equal date {equal_date(g, 'stock'):+.2f})"
                          f"  SPY {mean(r['SPY'] for r in g):+.2f} (equal date {equal_date(g, 'SPY'):+.2f})  dates {len({r['entry_day'] for r in g})}")


if __name__ == "__main__":
    main()
