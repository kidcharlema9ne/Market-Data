"""Run the price-only research pilot from a candidate queue and reviewed matches.

GitHub usage: python research_pilot.py february_review_queue.json pilot.json --r2
Add --matches reviewed.json to calculate outcomes. Each match has the batch
runner's accession, issuer_cik, owner_cik, security_id and rows, plus price_symbol
and inclusive valid_from/valid_through dates from a reviewed historical crosswalk.
Without matches the command reports archive and parsing coverage only.
"""
import argparse
from collections import Counter
from datetime import date, datetime, time
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo

from research_batch import run_batch

FILINGS = "sec/edgar/free-year/originals/"
PRICES = "samples/marketparquet/stock_daily/"
ET = ZoneInfo("America/New_York")


def keys(storage, bucket, prefix):
    return {
        obj["Key"] for page in storage.get_paginator("list_objects_v2").paginate(
            Bucket=bucket, Prefix=prefix
        ) for obj in page.get("Contents", [])
    }


def archive_filings(storage, bucket, candidates, destination):
    available = keys(storage, bucket, FILINGS)
    for candidate in candidates:
        filename = candidate["submission"]
        if filename != candidate["accession"] + ".txt" or not re.fullmatch(
            r"\d{10}-\d{2}-\d{6}\.txt", filename
        ):
            raise ValueError(f"Invalid submission path: {filename}")
        key = FILINGS + filename
        if key not in available:
            continue
        obj = storage.get_object(Bucket=bucket, Key=key)
        with obj["Body"] as body:
            data = body.read()
        if sha256(data).hexdigest() != obj["Metadata"].get("verified-sha256"):
            raise ValueError(f"Archived filing failed SHA-256 verification: {key}")
        (destination / filename).write_bytes(data)


def price_series(storage, bucket, matches):
    import pyarrow.parquet as pq

    files = {
        date.fromisoformat(key[len(PRICES):-8]): key
        for key in keys(storage, bucket, PRICES)
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}\.parquet", key[len(PRICES):])
    }
    days = sorted(files)
    if len(days) != 251 or (days[0], days[-1]) != (date(2025, 11, 6), date(2026, 11, 5)):
        raise ValueError("Expected the verified 251-session R2 sample")
    series = {}
    for match in matches:
        security = match["security_id"]
        symbol = match["price_symbol"]
        start, end = (date.fromisoformat(match[k]) for k in ("valid_from", "valid_through"))
        identity = (symbol, start, end)
        if start > end or (security in series and series[security] != identity):
            raise ValueError(f"Inconsistent price mapping for {security}")
        series[security] = identity
    bars = {security: {} for security in series}
    for day in days:
        active = {}
        for security, (symbol, start, end) in series.items():
            if start <= day <= end:
                if symbol in active:
                    raise ValueError(f"Overlapping security mappings for {symbol} on {day}")
                active[symbol] = security
        if not active:
            continue
        with storage.get_object(Bucket=bucket, Key=files[day])["Body"] as body:
            table = pq.read_table(
                BytesIO(body.read()), columns=["symbol", "open", "high", "low", "close"],
                filters=[("symbol", "in", list(active))], use_threads=False,
            )
        for row in table.to_pylist():
            security = active[row.pop("symbol")]
            if day in bars[security]:
                raise ValueError(f"Duplicate OHLC for {security} on {day}")
            bars[security][day] = row
    return [datetime.combine(day, time(9, 30), ET) for day in days], bars


def evaluate(candidates, matches, base, opens, bars):
    if matches and not opens:
        raise ValueError("Reviewed matches require a price calendar")
    report = run_batch(candidates, matches, opens, bars, base=base,
                       calendar_through=opens[-1].date() if opens else date.min,
                       atr_method="simple_mean_14")
    by_accession = {row["accession"]: row for row in candidates}
    for record in report["records"]:
        record["review_flags"] = by_accession[record["accession"]].get("review_flags", [])
    report["archived_accessions"] = sum(
        record["status"] != "missing_original" for record in report["records"]
    )
    report["review_flag_counts"] = dict(Counter(
        flag for record in report["records"] for flag in record["review_flags"]
    ))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("queue", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--matches", type=Path)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--r2", action="store_true")
    source.add_argument("--local-originals", type=Path)
    args = parser.parse_args()
    candidates = json.loads(args.queue.read_text())
    matches = json.loads(args.matches.read_text()) if args.matches else []
    if args.r2:
        from r2_storage import BUCKET, client

        storage = client()
        with TemporaryDirectory() as temporary:
            base = Path(temporary)
            archive_filings(storage, BUCKET, candidates, base)
            opens, bars = price_series(storage, BUCKET, matches) if matches else ([], {})
            report = evaluate(candidates, matches, base, opens, bars)
    else:
        if matches:
            parser.error("--matches requires --r2; local originals mode audits filings only")
        report = evaluate(candidates, [], args.local_originals, [], {})
    args.output.write_text(json.dumps(report, default=str, indent=2) + "\n")
    print(json.dumps({key: report[key] for key in (
        "expected_accessions", "archived_accessions", "parsed_accessions",
        "status_counts", "review_flag_counts",
    )}, indent=2))


if __name__ == "__main__":
    main()
