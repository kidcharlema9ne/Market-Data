"""Read-only diagnostic: why do 2026 purchase candidates fail the provisional ticker join?

Nothing here changes eligibility or any approved rule. It classifies each ticker whose
filings carry more than one (issuer CIK, security title) pair and prints counts and
examples to the log, so reviewers can see which conflicts are only wording.
"""

import math
import re
import sqlite3
from collections import Counter, defaultdict
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

import exchange_calendars as xcals
import pyarrow.parquet as pq

from r2_storage import client
from sec_bulk_importer import disclosure_opportunities
from validate_free_year_report import PRICE_PREFIX, checked_object
from validate_free_year_universe import DB_KEY, END, START

PLACEHOLDERS = {"NONE", "N/A", "NA", "N.A.", "-", "--", "0", "NULL"}
TOLERANCE = 0.05  # insider average price may sit this far outside the day's low-high range

WINDOW = ("2026-01-01", "2026-09-30")
NON_COMMON = re.compile(r"preferred|warrant|\bnotes?\b|debenture|\bunits?\b|\brights?\b|option|convertible|"
                        r"bond|partnership interest|membership|trust preferred")
ADR = re.compile(r"depositary|\bads\b|\badr\b")


def norm_title(title):
    """Wording-only normalization: case, spacing, punctuation, par-value phrases, shares/stock."""
    t = (title or "").lower()
    t = re.sub(r"\$\s*[\d.,]+\s*(par value|par)?(\s*per share)?", " ", t)
    t = re.sub(r"(par value|par)\s*\$?\s*[\d.,]*(\s*per share)?", " ", t)
    t = re.sub(r"\bordinary shares\b", "ordinary stock", t)
    t = re.sub(r"\bshares\b", "stock", t)
    t = re.sub(r"[^a-z0-9 ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def classify(group):
    """group = list of disclosures sharing one ticker. Returns (category, detail)."""
    ciks = {d["issuer_cik"] for d in group}
    if len(ciks) > 1:
        return "multiple_issuer_ciks", f"{len(ciks)} CIKs"
    raw = {d["security_title"] for d in group}
    normalized = {norm_title(t) for t in raw}
    if len(normalized) == 1:
        return "wording_only", ""
    common = {n for n in normalized if not NON_COMMON.search(n)}
    if any(ADR.search(n) for n in common) and len(common) > 1:
        return "adr_and_other_shares", f"{len(common)} descriptions"
    if len(common) == 1:
        return "resolves_after_excluding_non_common", ""
    if not common:
        return "no_plain_common_title", ""
    return "multiple_common_descriptions", f"{len(common)} descriptions"


def load_ranges(storage, tickers):
    """ticker -> date -> (low, high) from the free-year price archive (split-adjusted)."""
    days = [str(d.date()) for d in xcals.get_calendar("XNYS").sessions_in_range(START, END)]
    ranges = defaultdict(dict)
    for day in days:
        data, _ = checked_object(storage, f"{PRICE_PREFIX}{day}.parquet")
        names = set(pq.ParquetFile(BytesIO(data)).schema_arrow.names)
        date_col = "date" if "date" in names else "timestamp"
        rows = pq.read_table(BytesIO(data), columns=["symbol", date_col, "low", "high"],
                             filters=[("symbol", "in", sorted(tickers))]).to_pylist()
        counts = Counter(r["symbol"] for r in rows)
        for r in rows:
            t, lo, hi = r["symbol"], r["low"], r["high"]
            if counts[t] != 1 or str(r[date_col])[:10] != day:
                continue
            if lo is None or hi is None or not (math.isfinite(lo) and math.isfinite(hi)) or lo <= 0 or hi < lo:
                continue
            ranges[t][day] = (float(lo), float(hi))
    return ranges


def price_verdict(d, ranges):
    """Does the insider's reported average price fall inside the ticker's traded range on the trade date(s)?"""
    price = d.get("insider_weighted_price")
    if not price:
        return "no_insider_price", None
    ticker = d["ticker_at_filing"].upper().strip()
    bars = [ranges.get(ticker, {}).get(x) for x in (d.get("transaction_dates") or [])]
    bars = [b for b in bars if b]
    if not bars:
        return "no_price_bar_for_trade_date", None
    lo, hi = min(b[0] for b in bars), max(b[1] for b in bars)
    p = float(price)
    ok = lo * (1 - TOLERANCE) <= p <= hi * (1 + TOLERANCE)
    return ("confirmed" if ok else "contradicted"), (p, lo, hi)


def main():
    storage = client()
    database, _ = checked_object(storage, DB_KEY)
    with TemporaryDirectory() as directory:
        path = Path(directory) / "sec.sqlite"
        path.write_bytes(database)
        del database
        with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as db:
            disclosures = list(disclosure_opportunities(db, START, END))
    window = [d for d in disclosures if WINDOW[0] <= (d["filing_date"] or "") <= WINDOW[1]]
    print(f"Disclosures {START}..{END}: {len(disclosures)}; Jan-Sep 2026 filing dates: {len(window)}")

    by_ticker = defaultdict(list)
    no_ticker = 0
    for d in window:
        ticker = (d.get("ticker_at_filing") or "").upper().strip()
        if ticker:
            by_ticker[ticker].append(d)
        else:
            no_ticker += 1
    pairs = {t: {(d["issuer_cik"], d["security_title"]) for d in g} for t, g in by_ticker.items()}
    clean = {t for t, p in pairs.items() if len(p) == 1}
    clean_n = sum(len(by_ticker[t]) for t in clean)
    conflict = {t for t in by_ticker if t not in clean}
    conflict_n = sum(len(by_ticker[t]) for t in conflict)
    print(f"No ticker on filing: {no_ticker}")
    print(f"Single-pair tickers (current provisional join): {len(clean)} tickers, {clean_n} disclosures")
    print(f"Conflicting tickers: {len(conflict)} tickers, {conflict_n} disclosures  (handoff reported 2,443)")

    cats = Counter()
    members = defaultdict(list)
    for t in sorted(conflict):
        category, detail = classify(by_ticker[t])
        cats[category] += len(by_ticker[t])
        members[category].append((len(by_ticker[t]), t, detail))
    print("\nDisclosures by conflict category (count of disclosures):")
    for category, n in cats.most_common():
        print(f"  {category}: {n} disclosures across {len(members[category])} tickers")
    recoverable = cats["wording_only"] + cats["resolves_after_excluding_non_common"]
    print(f"\nRecoverable with wording/non-common rules alone: {recoverable} of {conflict_n} conflicting disclosures")

    category_of = {t: c for c, items in members.items() for _, t, _ in items}
    real = {t for t in by_ticker if t not in PLACEHOLDERS}
    placeholder_n = sum(len(by_ticker[t]) for t in by_ticker if t in PLACEHOLDERS)
    print(f"\nPlaceholder tickers (NONE, N/A, ...): {placeholder_n} disclosures; excluded from price test")
    ranges = load_ranges(storage, real)
    print(f"Price archive loaded for {len(ranges)} of {len(real)} tickers")
    groups = defaultdict(Counter)
    contradicted = []
    for t in real:
        group = "clean (single pair)" if t in clean else category_of.get(t, "other")
        for d in by_ticker[t]:
            verdict, detail = price_verdict(d, ranges)
            groups[group][verdict] += 1
            if verdict == "contradicted" and t in clean:
                contradicted.append((t, d["accession"], d["security_title"][:40], detail))
    print("\nPrice test of reported insider price against the ticker's daily low-high range (+/-5%):")
    for group, counter in sorted(groups.items(), key=lambda kv: -sum(kv[1].values())):
        total = sum(counter.values())
        parts = ", ".join(f"{k}={v}" for k, v in counter.most_common())
        print(f"  {group}: {total} disclosures -> {parts}")
    confirmed_conflict = sum(c["confirmed"] for g, c in groups.items() if g != "clean (single pair)")
    print(f"\nConflicting disclosures whose price is confirmed by the ticker's price series: {confirmed_conflict}")
    print("\nSample of CLEAN-join disclosures contradicted by price (possible wrong match or split adjustment):")
    for t, acc, title, (p, lo, hi) in sorted(contradicted)[:20]:
        print(f"  {t:<8} {acc} {title:<40} insider ${p:.2f} vs day range ${lo:.2f}-${hi:.2f}")

    for category in cats:
        print(f"\n== Top tickers: {category} ==")
        for n, ticker, detail in sorted(members[category], reverse=True)[:25]:
            ciks = sorted({d["issuer_cik"] for d in by_ticker[ticker]})
            titles = sorted({d["security_title"] for d in by_ticker[ticker]})
            shown = "; ".join(t[:60] for t in titles[:4])
            dates = sorted({d["filing_date"] for d in by_ticker[ticker]})
            print(f"  {ticker:<8} n={n:<3} {detail:<16} ciks={','.join(ciks[:3])} files {dates[0]}..{dates[-1]} | {shown}")


if __name__ == "__main__":
    main()
