"""Reproduce the original four price-only smoke cases from archived Form 4s."""

import argparse
from datetime import date, datetime, time
from decimal import Decimal
from io import BytesIO
from math import isclose
from pathlib import Path
import re
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

from outcomes import measure

ET = ZoneInfo("America/New_York")
PRICE_PREFIX = "samples/marketparquet/stock_daily/"
# Accession, issuer CIK, security title, baseline acceptance, entry and ATR.
CASES = {
    "GME": ("0001868288-26-000002", 1326380, "Class A Common Stock",
            "20260126090647", "2026-01-26", 23.46, 0.6648357142857143),
    "CRM": ("0001108524-26-000066", 1108524, "Common Stock",
            "20260319161552", "2026-03-20", 193.21, 7.569807142857138),
    "LULU": ("0001397187-26-000038", 1397187, "Common Stock",
             "20260323161334", "2026-03-24", 164.25, 5.73535714285715),
    "INTC": ("0000050863-26-000032", 50863, "Common Stock",
             "20260127162829", "2026-01-28", 46.6, 3.626178571428571),
}
# Baseline dates and H/L/C levels from GitHub Actions run 42207587157.
REFERENCE = {
    "GME": [("02-09", 25.93, 22.7, 24.64), ("02-24", 25.93, 22.7, 23.77),
            ("03-26", 25.93, 22.36, 22.56), ("04-27", 26.0186, 22.03, 25.41),
            ("07-24", 26.88, 20.885, 21.17)],
    "CRM": [("04-06", 198.05, 178.816, 185.03), ("04-20", 198.05, 163.52, 186.27),
            ("05-20", 198.05, 163.52, 180.1), ("06-22", 211.34, 146.32, 150.12),
            ("09-18", 268.27, 146.32, 237.92)],
    "LULU": [("04-08", 166.54, 143.96, 158.86), ("04-22", 170.1999, 143.96, 163.45),
             ("05-22", 170.1999, 116.625, 127.18), ("06-24", 170.1999, 104.44, 113.09),
             ("09-24", 170.1999, 95.35, 101.64)],
    "INTC": [("02-11", 51.49, 45.5, 48.29), ("02-26", 51.49, 42.88, 45.46),
             ("03-30", 51.49, 40.63, 41.19), ("04-29", 94.95, 40.63, 94.75),
             ("07-28", 142.35, 40.63, 86.3)],
}


def parse_fixture(path, symbol, case):
    accession, cik, title, stamp, *_ = case
    submission = path.read_bytes()
    header, _, documents = submission.partition(b"</SEC-HEADER>")
    accepted = re.findall(rb"<ACCEPTANCE-DATETIME>\s*(\d{14})\b", header)
    filing_ids = re.findall(rb"(?m)^ACCESSION NUMBER:\s*(\S+)", header)
    if accepted != [stamp.encode()] or filing_ids != [accession.encode()]:
        raise ValueError(f"{path}: unexpected accession or acceptance time")
    ownership = re.findall(rb"<ownershipDocument\b.*?</ownershipDocument>", documents, re.S)
    if len(ownership) != 1:
        raise ValueError(f"{path}: expected a single ownership document")
    form = ElementTree.fromstring(ownership[0])
    if (form.findtext("documentType") != "4"
            or int(form.findtext("issuer/issuerCik")) != cik
            or form.findtext("issuer/issuerTradingSymbol") != symbol
            or form.findtext("aff10b5One") != "0"):
        raise ValueError(f"{path}: unexpected Form 4 metadata")

    purchases = []
    for txn in form.findall("nonDerivativeTable/nonDerivativeTransaction"):
        if txn.findtext("transactionCoding/transactionCode") != "P":
            continue
        if (txn.findtext("securityTitle/value") != title
                or txn.findtext("transactionAmounts/transactionAcquiredDisposedCode/value") != "A"):
            raise ValueError(f"{path}: unexpected code-P security or direction")
        purchases.append((
            date.fromisoformat(txn.findtext("transactionDate/value")),
            Decimal(txn.findtext("transactionAmounts/transactionShares/value")),
            Decimal(txn.findtext("transactionAmounts/transactionPricePerShare/value")),
        ))
    if not purchases:
        raise ValueError(f"{path}: no matching code-P acquisitions")
    timestamp = datetime.strptime(accepted[0].decode(), "%Y%m%d%H%M%S").replace(tzinfo=ET)
    return timestamp, purchases


def read_prices():
    import pyarrow.parquet as pq
    from r2_storage import BUCKET, client

    s3 = client()
    keys = {
        date.fromisoformat(obj["Key"][len(PRICE_PREFIX):-8]): obj["Key"]
        for page in s3.get_paginator("list_objects_v2").paginate(
            Bucket=BUCKET, Prefix=PRICE_PREFIX
        )
        for obj in page.get("Contents", [])
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}\.parquet", obj["Key"][len(PRICE_PREFIX):])
    }
    days = sorted(keys)
    if len(days) != 251 or str(days[0]) != "2025-11-06" or str(days[-1]) != "2026-11-05":
        raise ValueError("Unexpected R2 sample coverage")
    # Smoke test only: reuse the previously verified sample's session list.
    opens = [datetime.combine(day, time(9, 30), ET) for day in days]
    bars = {symbol: {} for symbol in CASES}
    first = days.index(date(2026, 1, 26)) - 15
    last = days.index(date(2026, 9, 24))
    for day in days[first:last + 1]:
        with s3.get_object(Bucket=BUCKET, Key=keys[day])["Body"] as body:
            table = pq.read_table(
                BytesIO(body.read()), columns=["symbol", "open", "high", "low", "close"],
                filters=[("symbol", "in", list(CASES))], use_threads=False,
            )
        for row in table.to_pylist():
            symbol = row.pop("symbol")
            if day in bars[symbol]:
                raise ValueError(f"Duplicate R2 price row for {symbol} on {day}")
            bars[symbol][day] = row
    return opens, bars


def check_outcomes(symbol, case, result):
    _, _, _, _, entry_date, entry, atr = case
    assert str(result["entry_date"]) == entry_date, (symbol, result["entry_date"])
    assert isclose(result["entry_open"], entry, abs_tol=1e-10), symbol
    assert isclose(result["entry_atr"], atr, abs_tol=1e-10), symbol
    names = ("maximum_appreciation", "maximum_adverse_excursion", "price_only_ending_return")
    for label, (end, *levels) in zip(("11", "21", "43", "64", "6m"), REFERENCE[symbol], strict=True):
        horizon = result["horizons"][label]
        assert str(horizon["end_date"]) == f"2026-{end}", (symbol, label)
        for name, level in zip(names, levels, strict=True):
            metric = horizon[name]
            assert metric["issue"] is None, (symbol, label, name, metric)
            assert isclose(metric["pct"], 100 * (level - entry) / entry, abs_tol=1e-10)
            assert isclose(metric["atr"], (level - entry) / atr, abs_tol=1e-10)
        assert horizon["ending_total_return"]["issue"] == "unverified_dividend_coverage"
        print(f"{symbol} {label} through {horizon['end_date']}: "
              + ", ".join(f"{horizon[name]['atr']:+.5f} ATR" for name in names))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixtures", type=Path, help="Directory of original SEC submissions")
    parser.add_argument("--filings-only", action="store_true")
    args = parser.parse_args()
    parsed = {
        symbol: parse_fixture(args.fixtures / f"{case[0]}.txt", symbol, case)
        for symbol, case in CASES.items()
    }
    for symbol, (stamp, purchases) in parsed.items():
        print(f"{symbol}: {stamp.isoformat()}, {len(purchases)} code-P acquisition(s)",
              flush=True)
    if args.filings_only:
        return
    opens, bars = read_prices()
    for symbol, (stamp, _) in parsed.items():
        result = measure(stamp, opens, bars[symbol], calendar_through=opens[-1].date(),
                         cash_dividends={}, dividend_coverage_through=None,
                         atr_method="simple_mean_14")
        check_outcomes(symbol, CASES[symbol], result)
    print("PASS: four original submissions and all 20 R2 price horizons match the reference.")


if __name__ == "__main__":
    main()
