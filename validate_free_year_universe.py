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
        dollar_volume = sum(
            Decimal(str(bars[day]["close"])) * Decimal(str(bars[day]["volume"]))
            for day in days[index - 15:index]
        ) / 15
        row["entry_features"]["average_daily_dollars_15"] = str(dollar_volume)
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
    (output / "free_year_coverage.json").write_text(json.dumps(dataset["metadata"], indent=2))
    (output / "free_year_candidates.json").write_text(json.dumps(dataset))
    write_report(dataset, output / "free_year_candidates.html", title="Free-year integration — provisional candidates",
                 detail_limit=100, scope_note=dataset["metadata"]["scope"])
    print(json.dumps(coverage, indent=2))


def export_ownership_sample():
    from zipfile import ZipFile

    from sec_bulk_importer import rows as sec_rows

    accessions = set(["0000203596-26-000073","0000203596-26-000074","0000203596-26-000075","0000203596-26-000076","0000203596-26-000079","0000818479-26-000208","0000818479-26-000209","0000818479-26-000211","0000818479-26-000212","0000905729-26-000043","0000905729-26-000044","0000905729-26-000045","0000905729-26-000046","0000929638-26-001796","0000929638-26-001935","0000929638-26-001936","0000929638-26-001937","0000938885-26-000011","0000945621-26-000816","0000945841-26-000110","0000945841-26-000112","0000945841-26-000114","0000945841-26-000116","0000947871-26-000786","0000947871-26-000787","0000947871-26-000788","0000947871-26-000789","0000950103-26-007352","0000950142-26-001402","0001000753-26-000033","0001000753-26-000034","0001000753-26-000035","0001000753-26-000037","0001026081-26-000026","0001057352-26-000022","0001066061-26-000006","0001104659-26-012110","0001104659-26-012112","0001104659-26-012246","0001104659-26-012247","0001104659-26-012671","0001104659-26-022861","0001104659-26-023466","0001104659-26-024734","0001104659-26-032746","0001104659-26-058286","0001104659-26-058839","0001104659-26-058864","0001104659-26-058865","0001104659-26-059407","0001104659-26-059532","0001104659-26-059535","0001104659-26-059537","0001104659-26-063829","0001104659-26-065152","0001104659-26-066326","0001104659-26-070113","0001104659-26-094434","0001104659-26-094437","0001104659-26-095423","0001104659-26-095430","0001104659-26-096149","0001104659-26-096150","0001104659-26-097945","0001104659-26-103384","0001104659-26-103998","0001104659-26-104378","0001104659-26-104644","0001104659-26-107867","0001123485-25-000010","0001123485-26-000002","0001123485-26-000004","0001123485-26-000008","0001140361-26-004845","0001140361-26-006054","0001140361-26-006056","0001140361-26-006058","0001140361-26-007577","0001140361-26-007578","0001140361-26-007579","0001145037-26-000004","0001170010-26-000067","0001170010-26-000068","0001170010-26-000073","0001170010-26-000074","0001170010-26-000075","0001185533-26-000007","0001189422-26-000019","0001189793-26-000002","0001189793-26-000005","0001189793-26-000011","0001193125-26-018316","0001193125-26-018317","0001193125-26-018318","0001193125-26-018319","0001193125-26-018323","0001193125-26-018324","0001193125-26-018325","0001193125-26-018327","0001193125-26-064487","0001193125-26-086754","0001193125-26-088152","0001193125-26-088178","0001193125-26-088198","0001193125-26-088303","0001193125-26-088977","0001193125-26-091473","0001193125-26-094231","0001193125-26-095810","0001193125-26-095828","0001193125-26-098557","0001193125-26-216914","0001193125-26-219705","0001193125-26-220813","0001193125-26-221736","0001193125-26-221780","0001193125-26-221992","0001193125-26-224189","0001193125-26-227110","0001193125-26-229078","0001193125-26-229079","0001193125-26-229080","0001193125-26-229081","0001193125-26-229082","0001193125-26-230854","0001193125-26-234376","0001193125-26-234377","0001193125-26-234378","0001193125-26-241878","0001193125-26-242074","0001193125-26-242079","0001193125-26-254050","0001193125-26-255482","0001193125-26-256665","0001193125-26-259528","0001193125-26-262545","0001193125-26-262559","0001193125-26-264504","0001193125-26-266953","0001193125-26-268929","0001193125-26-269634","0001193125-26-342481","0001193125-26-344632","0001193125-26-344633","0001193125-26-344634","0001193125-26-344635","0001197066-26-000002","0001198906-26-000006","0001199045-26-000002","0001199045-26-000004","0001199045-26-000008","0001200357-26-000003","0001201007-26-000005","0001205247-26-000006","0001207407-26-000003","0001207407-26-000005","0001208500-26-000004","0001209929-26-000006","0001210982-26-000002","0001210982-26-000004","0001210982-26-000008","0001213900-26-090850","0001213900-26-090852","0001213900-26-090854","0001213900-26-090855","0001213900-26-090856","0001213900-26-090858","0001216778-26-000001","0001225208-26-003226","0001225208-26-003227","0001225208-26-003228","0001225208-26-003393","0001225208-26-003540","0001225208-26-008011","0001225208-26-008012","0001225208-26-008013","0001225208-26-008014","0001225208-26-008015","0001233565-26-000006","0001246485-26-000005","0001272064-26-000001","0001272064-26-000006","0001272064-26-000010","0001290936-26-000010","0001292814-26-002903","0001292814-26-002931","0001292814-26-003004","0001292814-26-003006","0001292814-26-003047","0001292814-26-003129","0001292814-26-003277","0001292814-26-003305","0001303609-26-000002","0001317406-26-000006","0001323134-26-000014","0001326278-26-000007","0001339736-26-000014","0001340262-26-000002","0001340262-26-000007","0001340262-26-000011","0001340406-26-000005","0001352578-26-000004","0001370423-26-000003","0001374175-26-000005","0001380659-26-000006","0001398905-26-000010","0001399121-26-000003","0001407943-26-000001","0001409460-26-000011","0001409939-25-000005","0001414109-26-000014","0001415833-26-000010","0001429832-26-000004","0001437749-26-004141","0001437749-26-004142","0001437749-26-004143","0001437749-26-004171","0001437749-26-014692","0001437749-26-014693","0001437749-26-014959","0001437749-26-015657","0001437749-26-017150","0001437749-26-017804","0001437749-26-017808","0001437749-26-017810","0001437749-26-017812","0001437749-26-017814","0001437749-26-019465","0001437749-26-019466","0001437749-26-019467","0001437749-26-019468","0001437749-26-020103","0001437749-26-020166","0001437749-26-020168","0001437749-26-020170","0001438327-26-000002","0001464273-26-000002","0001464273-26-000004","0001464273-26-000008","0001465175-26-000015","0001493152-26-023319","0001493152-26-023321","0001493152-26-024341","0001493152-26-024342","0001497570-26-000004","0001500076-26-000006","0001504089-26-000005","0001505732-26-000108","0001505732-26-000113","0001505732-26-000114","0001505732-26-000115","0001505732-26-000116","0001505910-26-000003","0001505910-26-000004","0001509559-26-000002","0001509991-26-000018","0001509991-26-000019","0001509991-26-000020","0001509991-26-000021","0001510712-26-000010","0001515156-26-000023","0001515156-26-000025","0001515156-26-000028","0001515156-26-000030","0001520138-26-000378","0001520138-26-000379","0001520138-26-000382","0001520138-26-000383","0001527204-25-000005","0001549373-26-000010","0001555132-26-000002","0001555362-26-000007","0001563441-26-000011","0001563461-26-000004","0001566340-26-000006","0001571123-25-000196","0001571123-25-000198","0001571123-25-000200","0001571123-26-000002","0001573752-26-000003","0001593636-26-000008","0001605860-26-000002","0001605873-26-000004","0001628280-26-007023","0001628280-26-007027","0001628280-26-007032","0001628280-26-007037","0001628280-26-011059","0001628280-26-011063","0001628280-26-011067","0001628280-26-011070","0001628280-26-016141","0001628280-26-016554","0001628280-26-016564","0001628280-26-016687","0001628280-26-016701","0001628280-26-016706","0001628280-26-017163","0001628280-26-017169","0001628280-26-018337","0001628280-26-034261","0001628280-26-034263","0001628280-26-034265","0001628280-26-034268","0001628280-26-034605","0001628280-26-034627","0001628280-26-035006","0001628280-26-035752","0001628280-26-035757","0001628280-26-036061","0001628280-26-038818","0001628280-26-041287","0001628280-26-041887","0001628280-26-049615","0001628280-26-049616","0001628280-26-049618","0001628280-26-049619","0001628280-26-049621","0001628280-26-049623","0001628280-26-055890","0001628280-26-055891","0001628280-26-058331","0001628280-26-058332","0001628280-26-058333","0001628280-26-058967","0001628280-26-059096","0001628280-26-059097","0001628280-26-059098","0001641823-26-000009","0001644859-26-000001","0001645027-26-000006","0001649989-26-000001","0001649989-26-000002","0001649989-26-000003","0001649989-26-000004","0001654770-26-000004","0001655046-26-000012","0001670760-26-000002","0001671772-26-000004","0001684794-26-000003","0001688490-26-000006","0001698665-25-000005","0001709407-26-000002","0001709407-26-000004","0001709407-26-000010","0001716998-26-000004","0001724169-26-000037","0001725272-26-000002","0001726978-26-000047","0001729835-26-000011","0001729840-26-000024","0001729859-26-000040","0001729897-26-000038","0001731363-26-000007","0001731365-26-000007","0001732108-26-000008","0001737782-26-000006","0001742555-26-000004","0001750247-26-000004","0001751947-26-000004","0001752640-26-000011","0001768773-26-000003","0001779740-26-000002","0001780265-26-000001","0001786877-26-000002","0001790340-26-000008","0001790340-26-000010","0001790340-26-000012","0001790340-26-000014","0001813570-26-000007","0001813613-26-000006","0001823561-26-000001","0001828369-26-000005","0001828369-26-000012","0001828536-26-000014","0001830330-26-000004","0001836958-26-000004","0001839477-26-000014","0001841409-26-000003","0001860742-26-000020","0001860742-26-000021","0001860742-26-000022","0001860742-26-000050","0001860742-26-000051","0001862739-26-000004","0001869960-26-000006","0001898688-26-000002","0001898688-26-000004","0001898688-26-000009","0001902313-26-000003","0001919434-26-000002","0001944013-26-000028","0001944013-26-000030","0001944013-26-000033","0001944013-26-000035","0001949911-26-000014","0001957684-26-000011","0001965228-26-000011","0001976607-26-000002","0001977206-26-000002","0001987329-26-000014","0001993636-26-000009","0002001171-26-000006","0002001557-26-000156","0002007895-26-000002","0002007895-26-000010","0002007895-26-000014","0002015612-26-000006","0002018803-26-000002","0002020286-26-000005","0002021289-26-000008","0002029118-26-000058","0002029118-26-000060","0002032799-26-000004","0002036762-26-000005","0002039801-26-000006","0002041385-26-000011","0002041385-26-000012","0002041385-26-000013","0002041385-26-000014","0002059504-26-000005","0002074755-26-000005","0002099433-26-000003","0002102589-26-000008","0002105391-26-000009","0002106014-26-000004","0002109729-26-000008","0002129872-26-000007","0002133385-26-000004","0002137766-26-000004","0002142208-26-000015"])
    quarters = ("2025q4", "2026q1", "2026q2", "2026q3")
    prefix = "sec/insider-transactions/quarterly-original-zips/"
    storage = client()
    filings = defaultdict(lambda: defaultdict(list))
    hashes = {}
    for quarter in quarters:
        data, digest = checked_object(storage, f"{prefix}{quarter}_form345.zip")
        hashes[quarter] = digest
        with ZipFile(BytesIO(data)) as archive:
            for table in ("NONDERIV_TRANS.tsv", "NONDERIV_HOLDING.tsv"):
                for row in sec_rows(archive, table):
                    accession = row["ACCESSION_NUMBER"]
                    if accession in accessions:
                        filings[accession][table].append(row)
    missing = sorted(accessions.difference(filings))
    output = Path("reports")
    output.mkdir(exist_ok=True)
    (output / "free_year_ownership_sample.json").write_text(json.dumps({
        "quarters": hashes, "requested": len(accessions), "missing": missing, "filings": filings,
    }))
    print(f"Recovered {len(filings)} filings of {len(accessions)} requested")
    if not filings:
        raise SystemExit("No ownership records recovered")


if __name__ == "__main__":
    export_ownership_sample()

