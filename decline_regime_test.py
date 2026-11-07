"""Noise check on the pilot lead: stock down 0.5 to under 2 ATR over 21 sessions, SPY flat or up. Read-only.

Rebuilds the pilot's cohort (all screened buys, provisional join, filings January 1 to September 30 2026), entry at the
next open after filing, 21-session hold, returns in the stock's fixed pre-entry ATR with SPY, ONEQ and IWM beside it.
Stock decline = close of session e-1 minus close of session e-22, divided by pre-entry ATR (D-054, D-055).
SPY regime = SPY close move over the same sessions divided by SPY's own ATR; flat strictly inside plus or minus 0.5.
Costs appear only as extra columns. This is the same data the lead was found in, so it is NOT independent validation.
"""

import math
import os
import random
import sqlite3
from bisect import bisect_right
from collections import defaultdict
from datetime import date
from io import BytesIO
from pathlib import Path
from statistics import mean, median
from tempfile import TemporaryDirectory

import exchange_calendars as xcals
import numpy as np
import pyarrow.parquet as pq

from r2_storage import client
from run_current_rules import FLAGS, HOLD, PLACEHOLDERS, TITLE, WINDOW_FILINGS, atr_before, fetch, load_bars
from sec_bulk_importer import disclosure_opportunities
from validate_free_year_report import checked_object
from validate_free_year_universe import DB_KEY, END, START

random.seed(20261107)
np.random.seed(20261107)
SYMBOLS = ("SPY", "ONEQ", "IWM")
COSTS = (0.10, 0.25)


def etf_bars(first, last):
    token = os.environ["MARKETPARQUET_API_KEY"]
    url = f"https://marketparquet.com/api/v1/manifest/etf_daily?start={first}&end={last}"
    files = __import__("json").loads(fetch(url, 2_000_000, {"Authorization": f"Bearer {token}"}))["files"]
    out = {s: {} for s in SYMBOLS}
    for row in files:
        payload = fetch(row["download_url"], 8 * 1024 * 1024)
        names = set(pq.ParquetFile(BytesIO(payload)).schema_arrow.names)
        date_field = "date" if "date" in names else "timestamp"
        rows = pq.read_table(BytesIO(payload), columns=["symbol", date_field, "open", "high", "low", "close"],
                             filters=[("symbol", "in", list(SYMBOLS))]).to_pylist()
        for b in rows:
            if str(b[date_field])[:10] == row["date"]:
                out[b["symbol"]][row["date"]] = (float(b["open"]), float(b["high"]), float(b["low"]), float(b["close"]), 0.0)
    return out


def build():
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
    screened = [d for d in disclosures if d["_t"] in provisional and WINDOW_FILINGS[0] <= (d["filing_date"] or "") <= WINDOW_FILINGS[1]
                and not FLAGS.intersection(d["review_flags"]) and TITLE.fullmatch(" ".join((d["security_title"] or "").split()))]
    print(f"Screened buys on the provisional join: {len(screened)}")
    bars = load_bars(storage, {d["_t"] for d in screened}, days)
    etf = etf_bars(days[0], days[-1])
    print("ETF sessions loaded: " + ", ".join(f"{s} {len(etf[s])}" for s in SYMBOLS))
    drops = defaultdict(int)
    rows = []
    for d in screened:
        e = bisect_right(days, d["filing_date"])
        if e < 22 or e + HOLD - 1 >= len(days):
            drops["entry too early or forward window incomplete"] += 1
            continue
        s = bars.get(d["_t"], {})
        need = (days[e - 22], days[e - 1], days[e], days[e + HOLD - 1])
        if any(x not in s for x in need) or any(x not in etf[sym] for sym in SYMBOLS for x in need):
            drops["missing stock or ETF bar"] += 1
            continue
        atr, spy_atr = atr_before(s, days, e), atr_before(etf["SPY"], days, e)
        if not atr or atr <= 0 or not spy_atr or spy_atr <= 0:
            drops["missing ATR"] += 1
            continue
        c0, c1, o, x = s[need[0]][3], s[need[1]][3], s[need[2]][0], s[need[3]][3]
        stock_pct = c1 / c0 - 1
        scale = o / atr
        row = {"ticker": d["_t"], "entry_day": days[e], "decl": (c1 - c0) / atr, "stock": (x - o) / atr, "lag": True}
        for sym in SYMBOLS:
            b = etf[sym]
            row["lag"] = row["lag"] and stock_pct < b[need[1]][3] / b[need[0]][3] - 1
            row[sym] = (b[need[3]][3] / b[need[2]][0] - 1) * scale
            row["exc_" + sym] = row["stock"] - row[sym]
        spy_dir = (etf["SPY"][need[1]][3] - etf["SPY"][need[0]][3]) / spy_atr
        row["regime"] = "Down" if spy_dir <= -0.5 else "Up" if spy_dir >= 0.5 else "Flat"
        rows.append(row)
    print(f"Usable entries: {len(rows)}; dropped: {dict(drops)}")
    return rows


def week(day):
    y, w, _ = date.fromisoformat(day).isocalendar()
    return f"{y}-{w:02d}"


def date_ci(rows, key="exc_SPY", reps=5000):
    groups = defaultdict(list)
    for r in rows:
        groups[r["entry_day"]].append(r[key])
    keys = list(groups)
    if len(keys) < 3:
        return None
    sums = {k: (sum(v), len(v)) for k, v in groups.items()}
    out = []
    for _ in range(reps):
        pick = random.choices(keys, k=len(keys))
        out.append(sum(sums[k][0] for k in pick) / sum(sums[k][1] for k in pick))
    out.sort()
    return out[int(0.025 * reps)], out[int(0.975 * reps)]


def line(label, rows):
    if not rows:
        return f"  {label:<44}{0:>6}"
    ex = [r["exc_SPY"] for r in rows]
    by_date = defaultdict(list)
    for r in rows:
        by_date[r["entry_day"]].append(r["exc_SPY"])
    ci = date_ci(rows)
    rng = "" if ci is None else f"{ci[0]:+.2f} to {ci[1]:+.2f}"
    return (f"  {label:<44}{len(rows):>6}{len(by_date):>6}  stock {mean(r['stock'] for r in rows):+5.2f}  SPY {mean(r['SPY'] for r in rows):+5.2f}"
            f"  ONEQ {mean(r['ONEQ'] for r in rows):+5.2f}  IWM {mean(r['IWM'] for r in rows):+5.2f}  excess vs SPY {mean(ex):+5.2f}"
            f"  middle {median(ex):+5.2f}  equal date {mean(mean(v) for v in by_date.values()):+5.2f}  range {rng:<17}"
            f"  beat SPY {sum(x > 0 for x in ex):>4}  after {COSTS[0]:.2f} {mean(ex) - COSTS[0]:+5.2f}  after {COSTS[1]:.2f} {mean(ex) - COSTS[1]:+5.2f}")


def band(r, lo, hi):
    return -hi < r["decl"] <= -lo


def forking(pool, chosen):
    bands = [(lo, hi) for lo in (0.0, 0.25, 0.5, 0.75, 1.0) for hi in (1.0, 1.5, 2.0, 3.0, 5.0) if hi > lo]
    regimes = (("Flat",), ("Up",), ("Flat", "Up"), ("Down",), ("Flat", "Up", "Down"))
    variants, masks = [], []
    for b in bands:
        for rg in regimes:
            m = np.array([band(r, *b) and r["regime"] in rg for r in pool])
            if m.sum() >= 40:
                variants.append((b, rg))
                masks.append(m)
    M = np.array(masks, dtype=float)
    counts = M.sum(axis=1)
    exc = np.array([r["exc_SPY"] for r in pool])
    observed = M @ exc / counts
    ci = variants.index(chosen)
    weeks = defaultdict(list)
    for i, r in enumerate(pool):
        weeks[week(r["entry_day"])].append(i)
    blocks = [np.array(v) for v in weeks.values()]
    reps, fixed_hits, best_hits = 3000, 0, 0
    best_obs = observed.max()
    for _ in range(reps):
        shuffled = exc.copy()
        for blk in blocks:
            shuffled[blk] = exc[np.random.permutation(blk)]
        means = M @ shuffled / counts
        fixed_hits += means[ci] >= observed[ci]
        best_hits += means.max() >= best_obs
    order = sorted(range(len(variants)), key=lambda i: -observed[i])
    print(f"\nForking-paths test: {len(variants)} variants (decline band x SPY regime, at least 40 entries each), shuffled within calendar weeks")
    print(f"  chosen variant: {int(counts[ci])} entries, average excess vs SPY {observed[ci]:+.2f}, ranks {order.index(ci) + 1} of {len(variants)}")
    b, rg = variants[order[0]]
    print(f"  best variant in the grid: down {b[0]} to {b[1]} ATR, SPY {'+'.join(rg)}: {int(counts[order[0]])} entries, average {observed[order[0]]:+.2f}")
    print(f"  chance a shuffled version matches the chosen variant with that definition fixed in advance: {fixed_hits / reps:.3f}")
    print(f"  chance the best of all {len(variants)} variants in a shuffled version matches the best observed: {best_hits / reps:.3f}")


def main():
    rows = build()
    lagged = [r for r in rows if r["lag"]]
    print(f"\nColumns: entries, entry dates, then ATR averages for the stock, SPY, ONEQ, IWM. Excess is against SPY.")
    print("\n1. Reference groups")
    print(line("All screened buys", rows))
    print(line("Stock down and lagged all three ETFs", [r for r in lagged if r["decl"] < 0]))
    print("\n2. The pilot lead: stock down 0.5 to under 2 ATR (lagged all three ETFs)")
    chosen = [r for r in lagged if band(r, 0.5, 2.0)]
    for rg in ("Down", "Flat", "Up"):
        print(line(f"SPY {rg.lower()}", [r for r in chosen if r["regime"] == rg]))
    focus = [r for r in chosen if r["regime"] in ("Flat", "Up")]
    print(line("SPY flat or up (the lead)", focus))
    print("\n3. Neighbouring bands, SPY flat or up")
    for lo, hi, label in ((0.0, 0.5, "Down under 0.5 ATR"), (0.5, 2.0, "Down 0.5 to under 2 ATR"), (2.0, 5.0, "Down 2 to under 5 ATR (the current setup)"),
                          (5.0, 99.0, "Down 5 ATR or more")):
        print(line(label, [r for r in lagged if band(r, lo, hi) and r["regime"] in ("Flat", "Up")]))

    ex = sorted((r["exc_SPY"] for r in focus), reverse=True)
    print("\n4. Dependence on a few trades (the lead)")
    print(f"  best trade {ex[0]:+.2f}; average without the best three {mean(ex[3:]):+.2f}; average without the best ten {mean(ex[10:]):+.2f}")
    print("\n5. Stability over time (the lead)")
    half = sorted(r["entry_day"] for r in focus)[len(focus) // 2]
    for label, grp in (("First half of dates", [r for r in focus if r["entry_day"] < half]), ("Second half of dates", [r for r in focus if r["entry_day"] >= half])):
        print(line(label, grp))
    for m in range(1, 10):
        grp = [r for r in focus if r["entry_day"][5:7] == f"{m:02d}"]
        if grp:
            print(f"  month {m:>2}: {len(grp):>4} entries, average excess vs SPY {mean(r['exc_SPY'] for r in grp):+.2f}, stock {mean(r['stock'] for r in grp):+.2f}, SPY {mean(r['SPY'] for r in grp):+.2f}")
    forking([r for r in lagged if r["decl"] < 0], ((0.5, 2.0), ("Flat", "Up")))


if __name__ == "__main__":
    main()
