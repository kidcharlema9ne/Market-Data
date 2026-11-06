"""Build a filing review queue from an SEC quarterly ZIP and its EDGAR master index."""
import argparse
from collections import Counter, defaultdict
import csv
from datetime import date, datetime
from io import TextIOWrapper
import json
from pathlib import Path
from zipfile import ZipFile


def accession(path):
    return Path(path).stem


def build_queue(quarter, index, manifest, month):
    with ZipFile(quarter) as archive:
        def rows(table):
            with TextIOWrapper(archive.open(table), encoding="utf-8") as source:
                yield from csv.DictReader(source, delimiter="\t")

        filings = {
            row["ACCESSION_NUMBER"]: row for row in rows("SUBMISSION.tsv")
            if row["DOCUMENT_TYPE"] in {"4", "4/A"}
            and datetime.strptime(row["FILING_DATE"], "%d-%b-%Y").date().replace(day=1) == month
        }
        purchases = defaultdict(list)
        for row in rows("NONDERIV_TRANS.tsv"):
            key = row["ACCESSION_NUMBER"]
            if key in filings and row["TRANS_CODE"] == "P" and row["TRANS_ACQUIRED_DISP_CD"] == "A":
                purchases[key].append(row)
        owners = defaultdict(set)
        for row in rows("REPORTINGOWNER.tsv"):
            if row["ACCESSION_NUMBER"] in purchases and row["RPTOWNERCIK"]:
                owners[row["ACCESSION_NUMBER"]].add(int(row["RPTOWNERCIK"]))

    paths = defaultdict(set)
    with index.open(encoding="utf-8", errors="replace") as source:
        for line in source:
            fields = line.rstrip().split("|")
            if len(fields) == 5 and fields[2] in {"4", "4/A"}:
                path = fields[-1]
                if accession(path) in purchases:
                    paths[accession(path)].add(path)

    queued = {accession(path) for path in manifest.read_text().splitlines() if path.strip()}
    result = []
    for key, transactions in sorted(purchases.items()):
        filing = filings[key]
        issuer = int(filing["ISSUERCIK"])
        ticker = filing["ISSUERTRADINGSYMBOL"].strip()
        titles = sorted({row["SECURITY_TITLE"].strip().casefold() for row in transactions})
        indexed_paths = sorted(paths[key])
        issuer_path = f"edgar/data/{issuer}/{key}.txt"
        path = issuer_path if issuer_path in indexed_paths else (
            indexed_paths[0] if len(indexed_paths) == 1 else None
        )
        flags = {
            "amendment": filing["DOCUMENT_TYPE"] == "4/A",
            "reported_10b5_1": filing["AFF10B5ONE"].lower() in {"1", "true"},
            "missing_ticker": ticker.upper() in {"", "NONE", "N/A", "NA", "-"},
            "owner_count_requires_review": len(owners[key]) != 1,
            "multiple_security_titles": len(titles) > 1,
            "unresolved_archive_path": path is None,
        }
        result.append({
            "accession": key, "submission": f"{key}.txt", "archive_path": path,
            "issuer_cik": issuer, "reported_ticker": ticker,
            "reported_owner_ciks": sorted(owners[key]), "security_titles": titles,
            "purchase_rows": len(transactions), "in_existing_manifest": key in queued,
            "review_flags": [flag for flag, applies in flags.items() if applies],
        })
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for field in ("quarter", "index", "manifest", "output"):
        parser.add_argument(field, type=Path)
    parser.add_argument("--month", required=True, help="YYYY-MM")
    args = parser.parse_args()
    queue = build_queue(args.quarter, args.index, args.manifest,
                        date.fromisoformat(f"{args.month}-01"))
    args.output.write_text(json.dumps(queue, indent=2) + "\n")
    print(json.dumps({
        "candidates": len(queue), "archive_paths": sum(bool(r["archive_path"]) for r in queue),
        "in_existing_manifest": sum(r["in_existing_manifest"] for r in queue),
        "review_flags": Counter(flag for r in queue for flag in r["review_flags"]),
    }, indent=2))


if __name__ == "__main__":
    main()
