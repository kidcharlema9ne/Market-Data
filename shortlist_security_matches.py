"""Prepare security-match proposals for archived Form 4 filings.

Usage: python shortlist_security_matches.py february-pilot.json shortlist.json
The output is a review queue. Eligibility and historical listing evidence are
required before any proposal can be passed to research_pilot.py as a match.
"""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import re


def shortlist(report):
    proposals = []
    for filing in report["records"]:
        if filing["status"] != "missing_reviewed_match":
            continue
        rows = filing["candidate_rows"]
        symbol = (filing["reported_ticker"] or "").strip().upper()
        owners = sorted(set(filing["owner_ciks"]))
        titles = sorted({(row["security_title"] or "").strip().casefold() for row in rows})
        reasons = set(filing.get("review_flags", []))
        if not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,11}", symbol) or symbol in {"NONE", "NA", "NULL"}:
            reasons.add("missing_or_unusable_ticker")
        if len(owners) != 1:
            reasons.add("owner_attribution")
        if len(titles) != 1 or not titles[0]:
            reasons.add("security_class")
        if any(row["ownership"] != "D" for row in rows):
            reasons.add("indirect_or_unknown_ownership")
        if any(row["footnotes"] for row in rows):
            reasons.add("transaction_footnotes")
        if not all(re.search(r"\b(?:common (?:stock|shares?)|ordinary shares?)\b", t)
                   for t in titles):
            reasons.add("instrument_type")
        proposals.append({
            "accession": filing["accession"], "accepted_at": filing["accepted_at"],
            "issuer_cik": filing["issuer_cik"], "reported_ticker": symbol,
            "owner_ciks": owners, "security_titles": titles,
            "candidate_rows": rows, "review_reasons": sorted(reasons),
        })

    issuers = defaultdict(set)
    for proposal in proposals:
        if proposal["reported_ticker"]:
            issuers[proposal["reported_ticker"]].add(proposal["issuer_cik"])
    for proposal in proposals:
        if len(issuers[proposal["reported_ticker"]]) > 1:
            proposal["review_reasons"].append("ticker_shared_by_multiple_issuers")
        proposal["review_status"] = (
            "needs_exception_review" if proposal["review_reasons"]
            else "needs_historical_listing_verification"
        )
    return {
        "status_counts": dict(Counter(p["review_status"] for p in proposals)),
        "reason_counts": dict(Counter(r for p in proposals for r in p["review_reasons"])),
        "proposals": proposals,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("coverage_report", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = shortlist(json.loads(args.coverage_report.read_text()))
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: result[key] for key in ("status_counts", "reason_counts")}, indent=2))


if __name__ == "__main__":
    main()
