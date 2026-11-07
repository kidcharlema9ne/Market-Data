"""Compare entry at the next open (approved rule) with entry at the close of the filing day. Read-only.

Same signals, same ATR, same exit (close of session e+20). Only the entry price and time change.
Filing-day-close entry has look-ahead risk: Forms 4 count as filed the same day if accepted by 10 p.m. Eastern.
So the 'tradeable' version keeps only entries whose four-buyer cluster was already public (accepted by 3:50 p.m. Eastern
on the filing day) and uses the cluster and CFO status known at that moment.
"""
import random
import re
import sqlite3
from bisect import bisect_right
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean, median
from tempfile import TemporaryDirectory

import exchange_calendars as xcals

from r2_storage import BUCKET, client
from run_current_rules import (FLAGS, FLOOR, HOLD, PLACEHOLDERS, TITLE, WINDOW, WINDOW_FILINGS, atr_before, buyer_of,
                               find_entries, load_bars, price_verdict, spy_bars)
from sec_bulk_importer import disclosure_opportunities
from validate_free_year_report import checked_object
from validate_free_year_universe import DB_KEY, END, START
import decline_regime_test as broad

random.seed(20261107)
COSTS = (0.10, 0.25)
ACCEPT = re.compile(rb"<ACCEPTANCE-DATETIME>\s*(\d{14})")
PREFIX = "sec/edgar/free-year/originals/"
CUTOFF = "15:50:00"


def outcome_both(entry, series, spy, days):
    e = entry["e"]
    if e + HOLD - 1 >= len(days):
        return None
    d_open, d_exit, d_prev = days[e], days[e + HOLD - 1], days[e - 1]
    if any(x not in series for x in (d_open, d_exit, d_prev)) or any(x not in spy for x in (d_open, d_exit, d_prev, days[e - 16])):
        return None
    atr = atr_before(series, days, e)
    spy_atr = atr_before(spy, days, e)
    history = days[e - 15:e]
    if not atr or atr <= 0 or not spy_atr or any(x not in series for x in history) or days[e - 16] not in series:
        return None
    o, c_prev, x = series[d_open][0], series[d_prev][3], series[d_exit][3]
    stock, stock_c = (x - o) / atr, (x - c_prev) / atr
    spy_o = (spy[d_exit][3] / spy[d_open][0] - 1) / (atr / o)
    spy_c = (spy[d_exit][3] / spy[d_prev][3] - 1) / (atr / c_prev)
    return {"stock": stock, "spy": spy_o, "excess": stock - spy_o, "stock_c": stock_c, "spy_c": spy_c, "excess_c": stock_c - spy_c,
            "adv": mean(series[d][3] * series[d][4] for d in history), "entry_day": d_open,
            "decline": (series[days[e - 16]][3] - c_prev) / atr,
            "spy_move": (spy[d_prev][3] - spy[days[e - 16]][3]) / spy_atr, "buyers": entry["buyers"]}


def acceptance(storage, accession, cache):
    if accession not in cache:
        try:
            data = storage.get_object(Bucket=BUCKET, Key=PREFIX + accession + ".txt", Range="bytes=0-6000")["Body"].read()
            m = ACCEPT.search(data)
            if not m:
                data = storage.get_object(Bucket=BUCKET, Key=PREFIX + accession + ".txt")["Body"].read()
                m = ACCEPT.search(data)
            cache[accession] = datetime.strptime(m.group(1).decode(), "%Y%m%d%H%M%S") if m else None
        except Exception:
            cache[accession] = None
    return cache[accession]


def build_cluster():
    storage = client()
    database, _ = checked_object(storage, DB_KEY)
    with TemporaryDirectory() as directory:
        path = Path(directory) / "sec.sqlite"
        path.write_bytes(database)
        del database
        with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as db:
            disclosures = list(disclosure_opportunities(db, START, END))
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
        if buyer and e < len(days):
            events[t].append((e, buyer[0], buyer[1], d["filing_date"], d["accession"]))
    cache, timing, rows = {}, Counter(), []
    for t, evs in events.items():
        for entry in find_entries(evs, len(days) - 1):
            if not (WINDOW_FILINGS[0] <= entry["filed"] <= WINDOW_FILINGS[1]):
                continue
            result = outcome_both(entry, bars.get(t, {}), spy, days)
            if not result:
                continue
            live = [ev for ev in evs if entry["e"] - WINDOW + 1 <= ev[0] <= entry["e"]]
            known = []
            for ev in live:
                if ev[3] < entry["filed"]:
                    known.append(ev)
                    continue
                at = acceptance(storage, ev[4], cache)
                if at is None:
                    timing["acceptance time unavailable"] += 1
                    continue
                clock = at.strftime("%H:%M:%S")
                timing["accepted by 3:50 pm" if clock <= CUTOFF else "accepted 3:50 to 4:00 pm" if clock <= "16:00:00" else "accepted after 4:00 pm"] += 1
                if at.strftime("%Y-%m-%d %H:%M:%S") <= f"{entry['filed']} {CUTOFF}":
                    known.append(ev)
            result.update({"ticker": t, "cfo": entry["cfo"], "tradeable": len({ev[1] for ev in known}) >= 4,
                           "cfo_close": any(ev[2] for ev in known)})
            rows.append(result)
    print(f"Cluster entries with outcomes: {len(rows)}; filings on the entry day by acceptance time: {dict(timing)}")
    return rows


def stat(rows, s, p, x):
    if not rows:
        return "     0"
    ex = [r[x] for r in rows]
    return (f"{len(rows):>4}  stock {mean(r[s] for r in rows):+5.2f}  SPY {mean(r[p] for r in rows):+5.2f}  excess {mean(ex):+5.2f}"
            f"  middle {median(ex):+5.2f}  beat SPY {sum(v > 0 for v in ex):>3}  after {COSTS[0]:.2f} {mean(ex) - COSTS[0]:+5.2f}  after {COSTS[1]:.2f} {mean(ex) - COSTS[1]:+5.2f}")


def main():
    rows = build_cluster()
    liquid = [r for r in rows if r["adv"] >= FLOOR]
    tradeable = [r for r in liquid if r["tradeable"]]
    print(f"Liquid entries: {len(liquid)}; cluster already public by 3:50 pm on the filing day: {len(tradeable)}")

    def groups(pool, cfo):
        up = lambda r: r["spy_move"] >= 0.5
        setup = lambda r: up(r) and 2 <= r["decline"] <= 5
        return [("Four or more buyers", pool), ("Exactly four buyers", [r for r in pool if r["buyers"] == 4]),
                ("Five or more buyers", [r for r in pool if r["buyers"] >= 5]), ("Four or more, SPY rising", [r for r in pool if up(r)]),
                ("Four or more, SPY not rising", [r for r in pool if not up(r)]), ("Four or more, CFO among buyers", [r for r in pool if r[cfo]]),
                ("Four or more, SPY rising, CFO", [r for r in pool if up(r) and r[cfo]]),
                ("Price setup (SPY rising, down 2 to 5 ATR)", [r for r in pool if setup(r)]),
                ("Price setup with CFO", [r for r in pool if setup(r) and r[cfo]])]

    print("\n1. All liquid cluster entries: next open versus filing-day close (close version assumes you saw the filing in time)")
    for (label, g), _ in zip(groups(liquid, "cfo"), range(99)):
        print(f"  {label:<44} OPEN  {stat(g, 'stock', 'spy', 'excess')}")
        print(f"  {'':<44} CLOSE {stat(g, 'stock_c', 'spy_c', 'excess_c')}")
    print("\n2. Only entries whose cluster was already public by 3:50 pm on the filing day (the version you could really trade)")
    for label, g in groups(tradeable, "cfo_close"):
        print(f"  {label:<44} OPEN  {stat(g, 'stock', 'spy', 'excess')}")
        print(f"  {'':<44} CLOSE {stat(g, 'stock_c', 'spy_c', 'excess_c')}")

    print("\n3. Broad pilot lead and neighbours (all screened buys, close version unconstrained)")
    allrows = broad.build()
    lagged = [r for r in allrows if r["lag"]]
    for label, lo, hi in (("Down 0.5 to under 2 ATR, SPY flat or up", 0.5, 2.0), ("Down 2 to under 5 ATR, SPY flat or up", 2.0, 5.0)):
        g = [r for r in lagged if broad.band(r, lo, hi) and r["regime"] in ("Flat", "Up")]
        print(f"  {label:<44} OPEN  {stat(g, 'stock', 'SPY', 'exc_SPY')}")
        print(f"  {'':<44} CLOSE {stat(g, 'stock_c', 'SPY_c', 'exc_SPY_c')}")
    print(f"  {'All screened buys':<44} OPEN  {stat(allrows, 'stock', 'SPY', 'exc_SPY')}")
    print(f"  {'':<44} CLOSE {stat(allrows, 'stock_c', 'SPY_c', 'exc_SPY_c')}")


if __name__ == "__main__":
    main()
