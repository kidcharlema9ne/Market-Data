"""Overfitting check on the four-buyer pilot (join B). Read-only; prints to the log.

1. Uncertainty: date-cluster and week-cluster bootstrap intervals, outlier dependence, sign test.
2. Forking paths: how often does the best subgroup in a grid of decline/SPY thresholds look this good
   when outcomes are shuffled across the same trades?
3. Cost haircut and first-half versus second-half stability.
Does not change any approved rule.
"""

import random
import sqlite3
from bisect import bisect_right
from collections import defaultdict
from datetime import date
from math import comb
from pathlib import Path
from statistics import mean, median, pstdev
from tempfile import TemporaryDirectory

import exchange_calendars as xcals

from r2_storage import client
from run_current_rules import (FLAGS, FLOOR, PLACEHOLDERS, TITLE, WINDOW_FILINGS, buyer_of, find_entries,
                               load_bars, outcome, price_verdict, spy_bars)
from sec_bulk_importer import disclosure_opportunities
from validate_free_year_report import checked_object
from validate_free_year_universe import DB_KEY, END, START

random.seed(20261107)


def build_rows():
    storage = client()
    database, _ = checked_object(storage, DB_KEY)
    with TemporaryDirectory() as directory:
        path = Path(directory) / "sec.sqlite"
        path.write_bytes(database)
        del database
        with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as db:
            disclosures = list(disclosure_opportunities(db, START, END))
    days = [str(d.date()) for d in xcals.get_calendar("XNYS").sessions_in_range(START, END)]
    pairs = defaultdict(set)
    for d in disclosures:
        d["_t"] = (d.get("ticker_at_filing") or "").upper().strip()
        pairs[d["_t"]].add((d["issuer_cik"], d["security_title"]))
    provisional = {t for t, p in pairs.items() if len(p) == 1 and t and t not in PLACEHOLDERS}
    real = {d["_t"] for d in disclosures if d["_t"] and d["_t"] not in PLACEHOLDERS}
    bars = load_bars(storage, real, days)
    spy = spy_bars("2025-12-01", days[-1])
    events = defaultdict(list)
    for d in disclosures:
        t = d["_t"]
        if t not in real or FLAGS.intersection(d["review_flags"]) or not TITLE.fullmatch(" ".join((d["security_title"] or "").split())):
            continue
        if not (t in provisional or price_verdict(d, t, bars) == "confirmed"):
            continue
        buyer = buyer_of(d)
        e = bisect_right(days, d["filing_date"])
        if buyer and e < len(days):
            events[t].append((e, buyer[0], buyer[1], d["filing_date"]))
    rows = []
    for t, evs in events.items():
        for entry in find_entries(evs, len(days) - 1):
            if WINDOW_FILINGS[0] <= entry["filed"] <= WINDOW_FILINGS[1]:
                result, _ = outcome(entry, bars.get(t, {}), spy, days)
                if result:
                    result["ticker"] = t
                    rows.append(result)
    return rows


def week(day):
    y, w, _ = date.fromisoformat(day).isocalendar()
    return f"{y}-{w:02d}"


def cluster_ci(rows, key, reps=10000):
    groups = defaultdict(list)
    for r in rows:
        groups[key(r)].append(r["excess"])
    keys = list(groups)
    means = []
    for _ in range(reps):
        pick = [x for k in random.choices(keys, k=len(keys)) for x in groups[k]]
        means.append(sum(pick) / len(pick))
    means.sort()
    return means[int(0.025 * reps)], means[int(0.975 * reps)], len(keys)


def sign_p(wins, n):
    """Two-sided exact binomial p-value for beating SPY at 50 percent."""
    k = max(wins, n - wins)
    return min(1.0, 2 * sum(comb(n, i) for i in range(k, n + 1)) / 2 ** n)


def describe(label, rows):
    n = len(rows)
    ex = sorted((r["excess"] for r in rows), reverse=True)
    sd = pstdev(ex)
    lo_d, hi_d, nd = cluster_ci(rows, lambda r: r["entry_day"])
    lo_w, hi_w, nw = cluster_ci(rows, lambda r: week(r["entry_day"]))
    wins = sum(x > 0 for x in ex)
    print(f"\n{label}: {n} trades on {nd} entry dates in {nw} calendar weeks")
    print(f"  average excess {mean(ex):+.2f}   middle trade {median(ex):+.2f}   spread (std dev) {sd:.2f}   naive t-stat {mean(ex) / (sd / n ** 0.5):.2f}")
    print(f"  95% range for the average, resampling entry dates: {lo_d:+.2f} to {hi_d:+.2f}")
    print(f"  95% range for the average, resampling calendar weeks: {lo_w:+.2f} to {hi_w:+.2f}")
    print(f"  average without the best trade: {mean(ex[1:]):+.2f}; without the best three: {mean(ex[3:]):+.2f}; best trade = {ex[0]:+.2f}")
    print(f"  beat SPY {wins} of {n}; chance of a split this lopsided from a fair coin: {sign_p(wins, n):.2f}")
    print(f"  after a 0.50 ATR round-trip cost: average {mean(ex) - 0.5:+.2f}, middle trade {median(ex) - 0.5:+.2f}")
    half = sorted(r["entry_day"] for r in rows)[n // 2]
    first, second = [r["excess"] for r in rows if r["entry_day"] < half], [r["excess"] for r in rows if r["entry_day"] >= half]
    if first and second:
        print(f"  first half of dates ({len(first)} trades): {mean(first):+.2f}; second half ({len(second)}): {mean(second):+.2f}")


def forking_paths(liquid):
    lows, highs, spys = (1.0, 1.5, 2.0, 2.5, 3.0), (4.0, 5.0, 6.0, 7.0), (0.0, 0.25, 0.5, 0.75, 1.0)
    defs = [(lo, hi, sp) for lo in lows for hi in highs for sp in spys]
    members = {df: [i for i, r in enumerate(liquid) if df[0] <= r["decline"] <= df[1] and r["spy_move"] >= df[2]] for df in defs}
    members = {df: m for df, m in members.items() if len(m) >= 10}
    ex = [r["excess"] for r in liquid]
    chosen = (2.0, 5.0, 0.5)
    observed = {df: sum(ex[i] for i in m) / len(m) for df, m in members.items()}
    best_df = max(observed, key=observed.get)
    chosen_obs = observed.get(chosen)
    reps, beat_best, beat_chosen = 5000, 0, 0
    for _ in range(reps):
        shuffled = ex[:]
        random.shuffle(shuffled)
        means = [sum(shuffled[i] for i in m) / len(m) for m in members.values()]
        beat_best += max(means) >= observed[best_df]
        if chosen_obs is not None:
            m = members[chosen]
            beat_chosen += sum(shuffled[i] for i in m) / len(m) >= chosen_obs
    print(f"\nForking-paths test on the {len(liquid)} liquid four-plus trades")
    print(f"  definitions tried: {len(members)} (stock-down band x SPY-rise threshold, each with at least 10 trades)")
    print(f"  chosen setup (down 2-5 ATR, SPY up 0.5+): {len(members[chosen])} trades, average excess {chosen_obs:+.2f}")
    print(f"  best definition in the grid: down {best_df[0]}-{best_df[1]} ATR, SPY up {best_df[2]}+: {len(members[best_df])} trades, average {observed[best_df]:+.2f}")
    print(f"  chance a shuffled version reaches the chosen setup's average with that exact definition fixed in advance: {beat_chosen / reps:.3f}")
    print(f"  chance the BEST of the {len(members)} definitions in a shuffled version reaches the best observed average: {beat_best / reps:.3f}")
    ranked = sorted(observed.values(), reverse=True)
    print(f"  the chosen setup ranks {ranked.index(chosen_obs) + 1} of {len(ranked)} definitions")


def main():
    rows = build_rows()
    print(f"Join B four-plus entries with complete 21-session outcomes: {len(rows)}")
    liquid = [r for r in rows if r["adv"] >= FLOOR]
    describe("Four or more buyers, at least $3M a day", liquid)
    up = [r for r in liquid if r["spy_move"] >= 0.5]
    describe("... and SPY rising 0.5+ ATR", up)
    setup = [r for r in up if 2 <= r["decline"] <= 5]
    describe("... and stock down 2 to 5 ATR (price setup)", setup)
    describe("Price setup with a CFO", [r for r in setup if r["cfo"]])
    forking_paths(liquid)


if __name__ == "__main__":
    main()
