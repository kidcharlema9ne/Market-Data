"""Run reviewed Form 4 opportunities against normalized prices and report coverage.

Usage: python research_batch.py manifest.json --output report.json
See run_batch() for the manifest fields. Run in the same directory as outcomes.py.
"""
import argparse
from collections import Counter
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import re
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

from outcomes import measure


def read_submission(path, accession):
    header, separator, body = path.read_bytes().partition(b"</SEC-HEADER>")
    stamps = re.findall(rb"<ACCEPTANCE-DATETIME>\s*(\d{14})\b", header)
    ids = re.findall(rb"(?m)^ACCESSION NUMBER:\s*(\S+)", header)
    documents = re.findall(rb"<ownershipDocument\b.*?</ownershipDocument>", body, re.S)
    if not separator or len(stamps) != 1 or ids != [accession.encode()] or len(documents) != 1:
        raise ValueError("Expected one acceptance timestamp and matching ownership submission")
    form = ElementTree.fromstring(documents[0])
    accepted = datetime.strptime(stamps[0].decode(), "%Y%m%d%H%M%S").replace(
        tzinfo=ZoneInfo("America/New_York")
    )
    transactions = []
    for position, txn in enumerate(form.findall("nonDerivativeTable/nonDerivativeTransaction"), 1):
        if (txn.findtext("transactionCoding/transactionCode") == "P"
                and txn.findtext("transactionAmounts/transactionAcquiredDisposedCode/value") == "A"):
            transactions.append({
                "row": position,
                "trade_date": txn.findtext("transactionDate/value"),
                "security_title": txn.findtext("securityTitle/value"),
                "shares": txn.findtext("transactionAmounts/transactionShares/value"),
                "price": txn.findtext("transactionAmounts/transactionPricePerShare/value"),
                "ownership": txn.findtext("ownershipNature/directOrIndirectOwnership/value"),
                "footnotes": sorted({note.get("id") for note in txn.iter("footnoteId")
                                     if note.get("id")}),
            })
    return {
        "accepted_at": accepted,
        "form": form.findtext("documentType"),
        "issuer_cik": int(form.findtext("issuer/issuerCik") or "0"),
        "reported_ticker": form.findtext("issuer/issuerTradingSymbol"),
        "owner_ciks": [int(cik) for cik in
                       (node.text for node in form.findall("reportingOwner/reportingOwnerId/rptOwnerCik"))
                       if cik],
        "reported_10b5_1": form.findtext("aff10b5One"),
        "candidate_rows": transactions,
    }


def run_batch(candidates, matches, session_opens, prices, *, base, calendar_through,
              atr_method):
    """Return records and counts.

    Candidates carry accession and relative submission path. Matches carry accession,
    issuer_cik, owner_cik, security_id and reviewed qualifying transaction row numbers.
    Matches must come from point-in-time identity and eligibility review. Prices map
    stable security IDs to split-consistent OHLC by session date. Dividend coverage
    is unknown for this pilot.
    """
    accession_ids = [item["accession"] for item in candidates]
    if len(set(accession_ids)) != len(accession_ids):
        raise ValueError("Candidate accessions must be unique")
    by_accession = {}
    for match in matches:
        by_accession.setdefault(match["accession"], []).append(match)

    results = []
    coverage = Counter()
    for candidate in candidates:
        accession = candidate["accession"]
        record = {"accession": accession}
        results.append(record)
        try:
            filing = read_submission(base / candidate["submission"], accession)
        except FileNotFoundError:
            record["status"] = "missing_original"
            continue
        except (OSError, ValueError, ElementTree.ParseError) as error:
            record.update(status="parse_error", detail=str(error))
            continue

        record.update(filing)
        if filing["form"] != "4":
            record["status"] = "amendment_review" if filing["form"] == "4/A" else "unexpected_form"
            continue
        if not filing["candidate_rows"]:
            record["status"] = "no_code_p_acquisition"
            continue
        if (filing["reported_10b5_1"] or "").strip().lower() in {"true", "1"}:
            record["status"] = "reported_10b5_1_review"
            continue

        reviewed = by_accession.get(accession, [])
        # Multiple plausible matches are quarantined in this pilot. A future
        # extension can represent multiple separately reviewed opportunities.
        if len(reviewed) != 1:
            record["status"] = "ambiguous_match" if reviewed else "missing_reviewed_match"
            continue
        match = reviewed[0]
        rows = {row["row"]: row for row in filing["candidate_rows"]}
        selected = match["rows"]
        if (match["issuer_cik"] != filing["issuer_cik"]
                or match["owner_cik"] not in filing["owner_ciks"]
                or not match["security_id"] or not selected
                or len(set(selected)) != len(selected) or not set(selected) <= rows.keys()):
            record["status"] = "reviewed_match_conflict"
            continue
        try:
            amounts = [(Decimal(rows[i]["shares"]), Decimal(rows[i]["price"])) for i in selected]
            if any(not value.is_finite() or value <= 0 for pair in amounts for value in pair):
                raise ValueError("Expected positive shares and price")
        except (InvalidOperation, TypeError, ValueError):
            record["status"] = "invalid_purchase_amount"
            continue

        shares = sum(quantity for quantity, _ in amounts)
        dollars = sum(quantity * price for quantity, price in amounts)
        security_id = match["security_id"]
        result = measure(
            filing["accepted_at"], session_opens, prices.get(security_id, {}),
            calendar_through=calendar_through, cash_dividends={},
            dividend_coverage_through=None, atr_method=atr_method,
        )
        record.update(status="measured" if not result["entry_issue"] else "entry_unavailable",
                      security_id=security_id, reviewed_rows=selected, purchase_dollars=dollars,
                      weighted_insider_price=dollars / shares, outcomes=result)
        for horizon, metrics in result["horizons"].items():
            for name, metric in metrics.items():
                if name == "end_date":
                    continue
                for units in ("pct", "atr"):
                    availability = "available" if metric[units] is not None else "missing"
                    coverage[(horizon, name, units, availability)] += 1

    return {
        "expected_accessions": len(candidates),
        "parsed_accessions": sum("accepted_at" in record for record in results),
        "status_counts": dict(Counter(record["status"] for record in results)),
        "metric_coverage": [
            dict(horizon=horizon, metric=metric, units=units, availability=availability, count=count)
            for (horizon, metric, units, availability), count in sorted(coverage.items())
        ],
        "records": results,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    data = json.loads(args.manifest.read_text())
    report = run_batch(
        data["candidates"], data["matches"],
        [datetime.fromisoformat(value) for value in data["session_opens"]],
        {security: {date.fromisoformat(day): row for day, row in bars.items()}
         for security, bars in data["prices"].items()},
        base=args.manifest.parent, calendar_through=date.fromisoformat(data["calendar_through"]),
        atr_method=data["atr_method"],
    )
    args.output.write_text(json.dumps(report, default=str, indent=2) + "\n")


if __name__ == "__main__":
    main()
