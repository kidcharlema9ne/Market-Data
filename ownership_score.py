"""Exploratory ownership-score study on the four-buyer pilot (join B). Read-only; prints to the log.

Question: do first-time buyers or a larger percentage increase in an insider's holding add to profitability?
This is a SIZING study, not an exclusion rule: every trade stays in. Nothing here changes an approved rule.
Costs are shown as extra columns only (0.10 and 0.25 ATR round trip); headline numbers are before cost.
"""

import json
import random
import sqlite3
from bisect import bisect_right
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from statistics import mean, median
from tempfile import TemporaryDirectory

import exchange_calendars as xcals

from r2_storage import client
from run_current_rules import (FLAGS, FLOOR, PLACEHOLDERS, TITLE, WINDOW, WINDOW_FILINGS, buyer_of, find_entries,
                               load_bars, outcome, price_verdict, spy_bars)
from sec_bulk_importer import disclosure_opportunities, sec_date
from validate_free_year_report import checked_object
from validate_free_year_universe import DB_KEY, END, START

random.seed(20261107)
COSTS = (0.10, 0.25)


def num(x):
    try:
        return Decimal(str(x)) if x not in (None, "") else None
    except InvalidOperation:
        return None


def holding_features(d, raw):
    """New-position flag, percent increase and dollars for one buyer filing. None means unknown."""
    rows = [raw[k] for k in d["transaction_row_keys"] if k in raw]
    direct = [r for r in rows if str(r.get("direct_indirect") or "").upper().startswith("D")]
    out = {"new": None, "pct": None, "dollars": float(d["aggregate_dollars"]) if d.get("aggregate_dollars") else None}
    if not direct:
        return out
    bought = [num(r.get("shares")) for r in direct]
    if any(b is None for b in bought):
        return out
    last_day = max((sec_date(r.get("transaction_date")) or "") for r in direct)
    afters = [num(r.get("shares_after")) for r in direct if (sec_date(r.get("transaction_date")) or "") == last_day]
    afters = [a for a in afters if a is not None]
    if not afters:
        return out
    prior = max(afters) - sum(bought)
    if prior < Decimal("-0.5"):
        return out
    if prior <= Decimal("0.5"):
        out["new"] = True
        return out
    out["new"] = False
    out["pct"] = float(sum(bought) / prior)
    return out


def build():
    storage = client()
    database, _ = checked_object(storage, DB_KEY)
    with TemporaryDirectory() as directory:
        path = Path(directory) / "sec.sqlite"
        path.write_bytes(database)
        del database
        with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as db:
            raw, history = {}, defaultdict(list)  # history: (issuer_cik, owner_cik) -> [(filing_date, first transaction date)]
            keep = ("transaction_row_key", "direct_indirect", "transaction_date", "shares", "shares_after", "filing_date")
            for n, (payload,) in enumerate(db.execute("SELECT payload FROM purchase_candidates"), 1):
                r = json.loads(payload)
                raw[r["transaction_row_key"]] = {k: r.get(k) for k in keep}
                owners = r.get("owners") or []
                if len(owners) == 1 and owners[0].get("cik") and sec_date(r.get("transaction_date")):
                    history[(r["issuer_cik"], owners[0]["cik"])].append((sec_date(r.get("filing_date")), sec_date(r.get("transaction_date"))))
                if n % 20000 == 0:
                    print(f"  read {n} rows", flush=True)
            disclosures = list(disclosure_opportunities(db, START, END))
    first_filing = min(sec_date(r.get("filing_date")) or "9999" for r in raw.values())
    print(f"Raw purchase rows: {len(raw)}; earliest filing in the database: {first_filing}")

    def first_within(d, owner, months):
        if not d["transaction_dates"]:
            return None
        t0 = date.fromisoformat(d["transaction_dates"][0])
        look = date.min if months is None else t0 - timedelta(days=round(months * 30.44))
        if months is not None and look.isoformat() < first_filing:
            return None  # lookback reaches before the database starts
        prior = [t for f, t in history[(d["issuer_cik"], owner)] if f and f < d["filing_date"]]
        return not any(look.isoformat() <= t < t0.isoformat() for t in prior)

    days = [str(x.date()) for x in xcals.get_calendar("XNYS").sessions_in_range(START, END)]
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
        if not buyer or e >= len(days):
            continue
        f = holding_features(d, raw)
        for name, m in (("first3", 3), ("first6", 6), ("first12", 12), ("first24", 24), ("firstever", None)):
            f[name] = first_within(d, buyer[0], m)
        events[t].append((e, buyer[0], buyer[1], d["filing_date"], f))

    rows = []
    for t, evs in events.items():
        for entry in find_entries([ev[:4] for ev in evs], len(days) - 1):
            if not (WINDOW_FILINGS[0] <= entry["filed"] <= WINDOW_FILINGS[1]):
                continue
            result, _ = outcome(entry, bars.get(t, {}), spy, days)
            if not result:
                continue
            live = sorted((ev for ev in evs if entry["e"] - WINDOW + 1 <= ev[0] <= entry["e"]), key=lambda ev: ev[0])
            per_owner = {}
            for ev in live:
                per_owner.setdefault(ev[1], ev[4])  # earliest filing per buyer
            fs = list(per_owner.values())
            pcts = [f["pct"] for f in fs if f["pct"] is not None]
            known = [f for f in fs if f["new"] is not None]
            dollars = [f["dollars"] for f in fs]
            result.update({
                "ticker": t, "n_new": sum(f["new"] is True for f in fs), "n_known": len(known),
                "med_pct": median(pcts) if pcts else None,
                "dollars": sum(dollars) if all(x is not None for x in dollars) else None,
                "first3": sum(f["first3"] is True for f in fs) if all(f["first3"] is not None for f in fs) else None,
                "first6": sum(f["first6"] is True for f in fs) if all(f["first6"] is not None for f in fs) else None,
                "first12": sum(f["first12"] is True for f in fs) if all(f["first12"] is not None for f in fs) else None,
                "first24": sum(f["first24"] is True for f in fs) if all(f["first24"] is not None for f in fs) else None,
                "firstever": sum(f["firstever"] is True for f in fs) if all(f["firstever"] is not None for f in fs) else None,
            })
            rows.append(result)
    return rows


def ranks(values):
    order = sorted(range(len(values)), key=lambda i: values[i])
    out, i = [0.0] * len(values), 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            out[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return out


def spearman(x, y):
    if len(x) < 8:
        return None
    rx, ry = ranks(x), ranks(y)
    mx, my = mean(rx), mean(ry)
    sx = sum((a - mx) ** 2 for a in rx) ** 0.5
    sy = sum((b - my) ** 2 for b in ry) ** 0.5
    return sum((a - mx) * (b - my) for a, b in zip(rx, ry)) / (sx * sy) if sx and sy else None


def corr_range(rows, feature, reps=4000):
    use = [r for r in rows if r[feature] is not None]
    base = spearman([r[feature] for r in use], [r["excess"] for r in use])
    groups = defaultdict(list)
    for r in use:
        groups[r["entry_day"]].append(r)
    keys, vals = list(groups), []
    for _ in range(reps):
        pick = [r for k in random.choices(keys, k=len(keys)) for r in groups[k]]
        c = spearman([r[feature] for r in pick], [r["excess"] for r in pick])
        if c is not None:
            vals.append(c)
    vals.sort()
    return len(use), base, (vals[int(0.025 * len(vals))], vals[int(0.975 * len(vals))]) if vals else None


def line(label, rows):
    if not rows:
        return f"  {label:<46}{0:>4}"
    ex = [r["excess"] for r in rows]
    return (f"  {label:<46}{len(rows):>4}  stock {mean(r['stock'] for r in rows):+6.2f}  SPY {mean(r['spy'] for r in rows):+6.2f}"
            f"  excess {mean(ex):+6.2f}  middle {median(ex):+6.2f}  beat SPY {sum(x > 0 for x in ex):>3}"
            f"  after {COSTS[0]:.2f} cost {mean(ex) - COSTS[0]:+6.2f}  after {COSTS[1]:.2f} cost {mean(ex) - COSTS[1]:+6.2f}")


def terciles(rows, feature):
    use = sorted((r for r in rows if r[feature] is not None), key=lambda r: r[feature])
    n = len(use)
    lo, hi = use[n // 3][feature], use[2 * n // 3][feature]
    return lo, hi, [r for r in use if r[feature] < lo], [r for r in use if lo <= r[feature] < hi], [r for r in use if r[feature] >= hi]


def main():
    rows = build()
    liquid = [r for r in rows if r["adv"] >= FLOOR]
    print(f"\nFour-plus entries: {len(rows)}; liquid ($3M a day): {len(liquid)}")
    print(f"Coverage among liquid trades: holdings known for all buyers {sum(r['n_known'] == r['n_known'] and r['n_known'] > 0 for r in liquid)};"
          f" median percent increase available {sum(r['med_pct'] is not None for r in liquid)};"
          f" 3-month first-purchase observable {sum(r['first3'] is not None for r in liquid)};"
          f" 6-month observable {sum(r['first6'] is not None for r in liquid)}")
    print("\nBASELINE")
    print(line("All liquid four-plus trades", liquid))

    print("\nA. Buyers opening a brand-new position (zero holding before the purchase)")
    for label, test in (("No buyer new to the stock", lambda r: r["n_new"] == 0), ("One buyer new", lambda r: r["n_new"] == 1),
                        ("Two or more buyers new", lambda r: r["n_new"] >= 2)):
        print(line(label, [r for r in liquid if test(r)]))

    for months, key in ((3, "first3"), (12, "first12"), (24, "first24"), (None, "firstever")):
        span = "ever on record since 2006" if months is None else f"in the prior {months} months"
        print(f"\nB{months}. Buyers with no purchase of this company {span}")
        obs = [r for r in liquid if r[key] is not None]
        for label, test in (("No first-time buyer", lambda r: r[key] == 0), ("One first-time buyer", lambda r: r[key] == 1),
                            ("Two first-time buyers", lambda r: r[key] == 2), ("Three first-time buyers", lambda r: r[key] == 3),
                            ("Four or more first-time buyers", lambda r: r[key] >= 4)):
            print(line(label, [r for r in obs if test(r)]))

    print("\nC. Median percent increase in holdings across the buyers (existing holders only), split into thirds")
    lo, hi, a, b, c = terciles(liquid, "med_pct")
    print(f"  cutoffs: lowest third below {lo:.1%}, top third from {hi:.1%}")
    for label, grp in (("Smallest increases", a), ("Middle increases", b), ("Largest increases", c)):
        print(line(label, grp))
    print(line("No existing-holder increase (all new or unknown)", [r for r in liquid if r["med_pct"] is None]))

    print("\nD. Total dollars bought by the group, split into thirds")
    lo, hi, a, b, c = terciles(liquid, "dollars")
    print(f"  cutoffs: lowest third below ${lo:,.0f}, top third from ${hi:,.0f}")
    for label, grp in (("Smallest dollars", a), ("Middle dollars", b), ("Largest dollars", c)):
        print(line(label, grp))

    print("\nE. Rank correlation with excess return (0 means no link; range resamples entry dates)")
    for feature, label in (("n_new", "Number of new-position buyers"), ("first3", "First-time buyers, 3 months"),
                           ("first6", "First-time buyers, 6 months"), ("first12", "First-time buyers, 12 months"),
                           ("first24", "First-time buyers, 24 months"), ("firstever", "First-time buyers, ever on record"), ("med_pct", "Median percent increase"),
                           ("dollars", "Total dollars bought")):
        n, base, rng = corr_range(liquid, feature)
        print(f"  {label:<34} trades {n:>3}  correlation {base if base is None else format(base, '+.2f')}"
              f"  range {'' if rng is None else format(rng[0], '+.2f') + ' to ' + format(rng[1], '+.2f')}")

    print("\nF. Exploratory score: one point each for a new-position buyer, a top-third percent increase, a 3-month first-time buyer")
    _, top_cut, *_ = terciles(liquid, "med_pct")
    for r in liquid:
        r["score"] = int(r["n_new"] >= 1) + int(r["med_pct"] is not None and r["med_pct"] >= top_cut) + int(bool(r["first3"]))
    for s in range(4):
        print(line(f"Score {s}", [r for r in liquid if r["score"] == s]))
    weights = {0: 0.5, 1: 1.0, 2: 1.5, 3: 2.0}
    wsum = sum(weights[r["score"]] for r in liquid)
    weighted = sum(weights[r["score"]] * r["excess"] for r in liquid) / wsum
    equal = mean(r["excess"] for r in liquid)
    groups = defaultdict(list)
    for r in liquid:
        groups[r["entry_day"]].append(r)
    keys, diffs = list(groups), []
    for _ in range(4000):
        pick = [r for k in random.choices(keys, k=len(keys)) for r in groups[k]]
        diffs.append(sum(weights[r["score"]] * r["excess"] for r in pick) / sum(weights[r["score"]] for r in pick)
                     - mean(r["excess"] for r in pick))
    diffs.sort()
    print(f"  Sizing 0.5, 1.0, 1.5, 2.0 times by score: weighted average excess {weighted:+.2f} versus equal weight {equal:+.2f};"
          f" difference {weighted - equal:+.2f}, range {diffs[int(0.025 * len(diffs))]:+.2f} to {diffs[int(0.975 * len(diffs))]:+.2f}")

    print("\nG. The price-setup trades with their ownership features")
    for r in sorted((r for r in liquid if r["spy_move"] >= 0.5 and 2 <= r["decline"] <= 5), key=lambda r: r["entry_day"]):
        pct = "none" if r["med_pct"] is None else f"{r['med_pct']:.1%}"
        print(f"  {r['ticker']:<6}{r['entry_day']}  excess {r['excess']:+6.2f}  new-position buyers {r['n_new']}  median increase {pct}"
              f"  3-month first-time buyers {r['first3']}")


if __name__ == "__main__":
    main()
