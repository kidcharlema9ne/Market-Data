"""Exercise the audited SEC database and price archive at sample scale.

Ticker joins here are explicitly provisional. Production requires verified
effective-dated identity and eligibility. This run measures pipeline coverage.
"""

import json
import math
import os
import sqlite3
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

import exchange_calendars as xcals
import pyarrow.parquet as pq

from integrated_research_dataset import integrate
from price_outcomes import atr14
from r2_storage import BUCKET, client
from research_html_report import write_report
from sec_bulk_importer import disclosure_opportunities
from validate_free_year_report import PRICE_PREFIX, checked_object

DB_KEY = "sec/insider-transactions/derived/purchase_candidates.sqlite3"
START, END = "2025-11-06", "2026-11-05"
MATCH_DATES = ("2026-03-17", "2026-09-17")


def read_control_bars(data, day, date_col, fields):
    rows = pq.read_table(BytesIO(data), columns=["symbol", date_col, *fields]).to_pylist()
    counts = Counter(row["symbol"] for row in rows)
    bars = {}
    for row in rows:
        ticker = row["symbol"]
        values = [row[field] for field in fields]
        if not ticker or counts[ticker] != 1 or str(row[date_col])[:10] != day:
            continue
        if any(value is None or not math.isfinite(value) for value in values):
            continue
        o, h, l, c, v = values
        if 0 < l <= min(o, c) <= max(o, c) <= h and v >= 0:
            bars[ticker] = row
    return bars


def control_candidates(days, raw_bars):
    result = {}
    for entry in MATCH_DATES:
        i = days.index(entry)
        prior = days[i - 16:i]
        forward = days[i:i + 21]
        matches = {}
        for ticker, bar in raw_bars[entry].items():
            if any(ticker not in raw_bars[day] for day in prior):
                continue
            history = [raw_bars[day][ticker] for day in prior]
            risk = atr14(history, 16)
            if not risk or risk <= 0:
                continue
            close = Decimal(str(history[-1]["close"]))
            base = Decimal(str(history[0]["close"]))
            depth = (base - close) / risk
            if not 2 <= depth <= 5:
                continue
            opening = Decimal(str(bar["open"]))
            daily_dollars = sum(Decimal(str(x["close"])) * Decimal(str(x["volume"]))
                                for x in history[1:]) / 15
            complete = all(ticker in raw_bars[day] for day in forward)
            exit_close = raw_bars[forward[-1]][ticker]["close"] if complete else None
            matches[ticker] = {
                "entry_open": str(opening), "atr14": str(risk), "depth_atr": str(depth),
                "prior_close": str(close), "average_daily_dollars_15": str(daily_dollars),
                "exit_close": str(exit_close) if complete else None,
            }
        result[entry] = {"end_date": forward[-1], "stocks": matches}
    return result


def main():
    storage = client()
    database, digest = checked_object(storage, DB_KEY)
    with TemporaryDirectory() as directory:
        path = Path(directory) / "sec.sqlite"
        path.write_bytes(database)
        del database
        with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as db:
            disclosures = [row for row in disclosure_opportunities(db, START, END)]
    if not disclosures:
        raise ValueError("Audited database returned no disclosures in the sample")
    days = [str(day.date()) for day in xcals.get_calendar("XNYS").sessions_in_range(START, END)]
    identities = defaultdict(set)
    for row in disclosures:
        ticker = (row.get("ticker_at_filing") or "").upper()
        if ticker:
            identities[ticker].add((row["issuer_cik"], row["security_title"]))
    provisional = {ticker for ticker, matches in identities.items() if len(matches) == 1}
    for row in disclosures:
        ticker = (row.get("ticker_at_filing") or "").upper()
        if ticker in provisional:
            row["security_id"] = "provisional:" + ticker
            row["review_flags"].append("unverified_price_identity")
        elif ticker:
            row["review_flags"].append("conflicting_sec_ticker_identity")

    control_days = set()
    for entry in MATCH_DATES:
        i = days.index(entry)
        control_days.update(days[i - 16:i + 21])
    raw_bars = {}
    series = defaultdict(list)
    hashes = {}
    rejected_bars = Counter()
    fields = ["open", "high", "low", "close", "volume"]
    for day in days:
        data, hashes[day] = checked_object(storage, f"{PRICE_PREFIX}{day}.parquet")
        parquet = pq.ParquetFile(BytesIO(data))
        schema = set(parquet.schema_arrow.names)
        date_col = "date" if "date" in schema else "timestamp"
        if not {"symbol", date_col, *fields} <= schema or not parquet.metadata.num_rows:
            raise ValueError(f"Invalid price partition schema on {day}")
        if day in control_days:
            raw_bars[day] = read_control_bars(data, day, date_col, fields)
        rows = pq.read_table(BytesIO(data), columns=["symbol", date_col, *fields],
                             filters=[("symbol", "in", sorted(provisional))]).to_pylist()
        counts = Counter(row["symbol"] for row in rows)
        for row in rows:
            ticker = row.pop("symbol")
            if counts[ticker] != 1 or str(row.pop(date_col))[:10] != day:
                rejected_bars["duplicate_or_misdated"] += 1
                continue
            if any(row[field] is None for field in fields):
                rejected_bars["null_ohlcv"] += 1
                continue
            o, h, l, c, v = (Decimal(str(row[field])) for field in fields)
            if not all(x.is_finite() for x in (o, h, l, c, v)) or not 0 < l <= min(o, c) <= max(o, c) <= h or v < 0:
                rejected_bars["invalid_ohlcv"] += 1
                continue
            series["provisional:" + ticker].append(dict(row, date=day))

    dataset = integrate(disclosures, series, sessions=days)
    priced = [row for row in dataset["opportunities"] if row["outcome_status"] == "ok"]
    if len({row["security_id"] for row in priced}) < 2:
        raise ValueError("Multi-stock integration requires priced disclosures on at least two stocks")
    for row in priced:
        expected = days[bisect_right(days, row["filing_date"])]
        if row["next_open_date"] != expected:
            raise ValueError(f"D-051 entry mismatch for {row['accession']}")
    # Add the exploratory three-week feature to the isolated pilot artifact.
    bars_by_security = {
        security: {bar["date"]: bar for bar in bars}
        for security, bars in series.items()
    }
    for row in priced:
        index = bisect_left(days, row["next_open_date"])
        history = row.get("entry_features", {}).get("completed_session_count", 0)
        if history <= 15:
            continue
        bars = bars_by_security[row["security_id"]]
        close = Decimal(str(bars[days[index - 1]]["close"]))
        base = Decimal(str(bars[days[index - 16]]["close"]))
        risk = Decimal(row["atr14"])
        row["entry_features"]["prior_returns"]["15"] = {
            "percent": str((close / base - 1) * 100),
            "atr": str((close - base) / risk),
        }
    # Purchase-date context is descriptive. The outcome still starts after filing.
    for row in priced:
        trade_dates = row.get("transaction_dates") or []
        if not trade_dates:
            continue
        purchase_date = max(trade_dates)
        index = bisect_left(days, purchase_date)
        if index < 22 or purchase_date > row["filing_date"]:
            continue
        context_days = days[index - 22:index]
        wanted = set(context_days)
        by_day = {bar["date"]: bar for bar in series[row["security_id"]] if bar["date"] in wanted}
        if len(by_day) != len(context_days):
            continue
        history = [by_day[day] for day in context_days]
        risk = atr14(history, len(history))
        if risk is None or risk <= 0:
            continue
        row["purchase_context"] = {
            "date": purchase_date,
            "last_completed_session": context_days[-1],
            "atr14": str(risk),
            "signed_21_session_atr": str((Decimal(str(history[-1]["close"])) -
                                          Decimal(str(history[0]["close"]))) / risk),
        }
    coverage = {
        "candidate_disclosures": len(disclosures),
        "priced_candidate_disclosures": len(priced),
        "priced_provisional_tickers": len({row["security_id"] for row in priced}),
        "available_outcomes": dict(Counter(h for row in priced for h, v in row["horizons"].items() if v["status"] == "ok")),
        "review_flags": dict(Counter(flag for row in disclosures for flag in row["review_flags"])),
        "rejected_bars": dict(rejected_bars),
    }
    dataset["metadata"] = {"coverage": coverage, "database_sha256": digest,
                           "price_sha256_by_date": hashes, "commit": os.environ.get("GITHUB_SHA"),
                           "scope": "Provisional engineering sample. Ticker joins, eligibility, corporate actions and adjustments require verification."}
    output = Path("reports")
    output.mkdir(exist_ok=True)
    (output / "free_year_zero_buyer_price_candidates.json").write_text(
        json.dumps(control_candidates(days, raw_bars))
    )
    (output / "free_year_coverage.json").write_text(json.dumps(dataset["metadata"], indent=2))
    (output / "free_year_candidates.json").write_text(json.dumps(dataset))
    write_report(dataset, output / "free_year_candidates.html", title="Free-year integration — provisional candidates",
                 detail_limit=100, scope_note=dataset["metadata"]["scope"])
    print(json.dumps(coverage, indent=2))


if __name__ == "__main__":
    main()
