"""Exercise batch integration with the four archived filings and failure cases."""
import argparse
from datetime import date, datetime, time, timedelta
from pathlib import Path

from free_year_regression import CASES, ET, check_outcomes, read_prices
from research_batch import run_batch


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixtures", type=Path)
    parser.add_argument("--r2", action="store_true")
    args = parser.parse_args()
    reviewed = {"GME": (1868288, [1]), "CRM": (1225922, [1, 2]),
                "LULU": (1436534, [2]), "INTC": (1330891, [1])}
    candidates, matches = [], []
    for symbol, (accession, issuer, *_) in CASES.items():
        owner, rows = reviewed[symbol]
        candidates.append(dict(accession=accession, submission=f"{accession}.txt"))
        matches.append(dict(accession=accession, issuer_cik=issuer, owner_cik=owner,
                            security_id=symbol, rows=rows))
    missing = dict(accession="missing", submission="missing-submission.txt")
    if args.r2:
        opens, prices = read_prices()
    else:
        days = [date(2025, 12, 1) + timedelta(days=i) for i in range(340)]
        opens = [datetime.combine(day, time(9, 30), ET) for day in days if day.weekday() < 5]
        prices = {symbol: {opening.date(): dict(open=50, high=52, low=48, close=51)
                           for opening in opens} for symbol in CASES}

    def run(rows, mapping, bars):
        return run_batch(rows, mapping, opens, bars, base=args.fixtures,
                         calendar_through=opens[-1].date(), atr_method="simple_mean_14")

    report = run(candidates + [missing], matches, prices)
    assert report["expected_accessions"] == 5 and report["parsed_accessions"] == 4
    assert report["status_counts"] == {"measured": 4, "missing_original": 1}
    assert report["records"][1]["reviewed_rows"] == [1, 2]
    assert all(item["count"] == 4 for item in report["metric_coverage"])
    assert run(candidates, matches + matches[:1], prices)["status_counts"] == {
        "ambiguous_match": 1, "measured": 3,
    }
    assert run(candidates, matches[1:], prices)["status_counts"] == {
        "missing_reviewed_match": 1, "measured": 3,
    }
    assert run(candidates, matches, {})["status_counts"] == {"entry_unavailable": 4}

    if args.r2:
        for match, record in zip(matches, report["records"][:4], strict=True):
            symbol = match["security_id"]
            check_outcomes(symbol, CASES[symbol], record["outcomes"])
    print("PASS: batch coverage, missing filing, ambiguous match, absent match and missing prices"
          + ("; all 20 R2 horizons reproduced." if args.r2 else " (synthetic prices)."))


if __name__ == "__main__":
    main()
