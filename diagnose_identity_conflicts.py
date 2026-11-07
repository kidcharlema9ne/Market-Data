"""Read-only diagnostic: why do 2026 purchase candidates fail the provisional ticker join?

Nothing here changes eligibility or any approved rule. It classifies each ticker whose
filings carry more than one (issuer CIK, security title) pair and prints counts and
examples to the log, so reviewers can see which conflicts are only wording.
"""

import re
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from tempfile import TemporaryDirectory

from r2_storage import client
from sec_bulk_importer import disclosure_opportunities
from validate_free_year_report import checked_object
from validate_free_year_universe import DB_KEY, END, START

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
