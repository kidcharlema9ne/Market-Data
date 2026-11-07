"""How big is one ATR in percent and dollars for the cluster trades? Read-only, prints to the log."""
from statistics import mean, median, pstdev
from run_current_rules import FLOOR
from snooping_check import build_rows


def pct(values, q):
    v = sorted(values)
    return v[min(len(v) - 1, int(q * len(v)))]


def main():
    rows = build_rows()
    liquid = [r for r in rows if r["adv"] >= FLOOR]
    setup = [r for r in liquid if r["spy_move"] >= 0.5 and 2 <= r["decline"] <= 5]
    for label, g in (("Liquid four-plus cluster trades", liquid), ("Price setup trades", setup)):
        a = [r["atr_pct"] * 100 for r in g]
        p = [r["entry_open"] for r in g]
        v = [r["adv"] / 1e6 for r in g]
        e = [r["excess"] for r in g]
        print(f"\n{label}: {len(g)} trades")
        print(f"  one ATR as percent of the stock price: lowest quarter {pct(a, .25):.1f}%  middle {median(a):.1f}%  top quarter {pct(a, .75):.1f}%  average {mean(a):.1f}%")
        print(f"  entry price in dollars: lowest quarter {pct(p, .25):.2f}  middle {median(p):.2f}  top quarter {pct(p, .75):.2f}")
        print(f"  average daily dollar volume in millions: lowest quarter {pct(v, .25):.1f}  middle {median(v):.1f}  top quarter {pct(v, .75):.1f}")
        print(f"  spread of excess return per trade (standard deviation): {pstdev(e):.2f} ATR; average {mean(e):+.2f}")
        for size in (25_000, 50_000):
            print(f"  position ${size:,}: one ATR is about ${size * median(a) / 100:,.0f} at the middle trade; position is {size / (median(v) * 1e6):.1%} of a middle day's volume")


if __name__ == "__main__":
    main()
