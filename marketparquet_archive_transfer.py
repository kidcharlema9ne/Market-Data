"""Copy one year of a MarketParquet daily feed into Cloudflare R2 with verification.

Usage: python marketparquet_archive_transfer.py ASSET_TYPE YEAR
  ASSET_TYPE: stock_daily, etf_daily or futures_daily
Objects are written to marketparquet/{ASSET_TYPE}/{date}.parquet (the free-year
sample under samples/ is left untouched). Each object carries a verified-sha256
metadata tag; reruns skip objects whose bytes still match that tag.
"""

import hashlib
import json
import os
import sys
import time
from datetime import date, timedelta
from io import BytesIO
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from botocore.exceptions import ClientError
from pyarrow.parquet import ParquetFile

from r2_storage import BUCKET, client

BASE = "https://marketparquet.com"
MAX_BYTES = 8 * 1024 * 1024
REQUIRED = {"symbol", "open", "high", "low", "close", "volume"}
ASSETS = {"stock_daily", "etf_daily", "futures_daily"}
# Futures daily bars may be stamped at the session start (the prior evening, and
# after a weekend or holiday up to 3 days earlier), so a futures file may hold
# dates up to 3 days before its file date. Stocks and ETFs must match exactly.
FUTURES_MAX_LOOKBACK_DAYS = 3


def dates_match(actual, day, asset):
    """True if the dates found inside a file are acceptable for its file date."""
    if actual == {day}:
        return True
    if asset != "futures_daily":
        return False
    file_day = date.fromisoformat(day)
    earliest = file_day - timedelta(days=FUTURES_MAX_LOOKBACK_DAYS)
    return bool(actual) and all(earliest <= date.fromisoformat(d) <= file_day for d in actual)


def fetch(url, label, limit, headers=None, tries=4):
    last = None
    for attempt in range(tries):
        try:
            request = Request(url, headers={"User-Agent": "insider-buying-research/1.0", **(headers or {})})
            with urlopen(request, timeout=60) as response:
                return response.read(limit + 1)
        except HTTPError as error:
            last = f"HTTP {error.code}"
            if error.code in (401, 403, 404):
                break
        except (URLError, TimeoutError) as error:
            last = f"network failure ({error})"
        time.sleep(2 ** attempt)
    raise SystemExit(f"{label}: {last}")


def main(asset, year):
    token = os.environ.get("MARKETPARQUET_API_KEY", "")
    if not token:
        raise SystemExit("MARKETPARQUET_API_KEY is missing")
    auth = {"Authorization": f"Bearer {token}"}
    start, end = f"{year}-01-01", f"{year}-12-31"
    manifest = json.loads(fetch(
        f"{BASE}/api/v1/manifest/{asset}?start={start}&end={end}",
        f"manifest {asset} {year}", 5_000_000, auth,
    ))
    files = sorted(manifest.get("files") or [], key=lambda entry: entry["date"])
    if not files:
        raise SystemExit(f"{asset} {year}: manifest empty (plan={manifest.get('plan')!r}, keys={sorted(manifest)})")
    dates = [entry["date"] for entry in files]
    if len(set(dates)) != len(dates):
        raise SystemExit(f"{asset} {year}: duplicate dates in manifest")
    if any(not (start <= day <= end) for day in dates):
        raise SystemExit(f"{asset} {year}: manifest dates outside the requested year")
    # Futures start 2007-12-31, so 2007 is not a full year; every earlier complete year must be full.
    complete_year_required = int(year) < date.today().year and not (asset == "futures_daily" and int(year) < 2008)
    if complete_year_required and len(dates) < 245:
        raise SystemExit(f"{asset} {year}: only {len(dates)} dates in a complete year (expected about 248-253)")
    print(f"{asset} {year}: manifest has {len(dates)} dates {dates[0]}..{dates[-1]}", flush=True)

    storage = client()
    uploaded = skipped = 0
    rows_total = 0
    for entry in files:
        day = entry["date"]
        key = f"marketparquet/{asset}/{day}.parquet"
        size = entry["file_size_bytes"]
        if not 0 < size <= MAX_BYTES:
            raise SystemExit(f"{day}: unexpected manifest size {size}")
        try:
            info = storage.head_object(Bucket=BUCKET, Key=key)
        except ClientError as error:
            if error.response["ResponseMetadata"]["HTTPStatusCode"] != 404:
                raise
            info = None
        if info and info["ContentLength"] == size and info["Metadata"].get("verified-sha256"):
            with storage.get_object(Bucket=BUCKET, Key=key)["Body"] as body:
                if hashlib.sha256(body.read()).hexdigest() == info["Metadata"]["verified-sha256"]:
                    skipped += 1
                    continue
        url = entry["download_url"]
        if url.startswith("/"):
            url = BASE + url
        if urlsplit(url).scheme != "https":
            raise SystemExit(f"{day}: insecure download URL")
        data = fetch(url, day, size, auth if url.startswith(BASE) else None)
        if url.startswith(BASE + "/api/v1/download/"):
            # The API download endpoint returns JSON with a 60-second presigned URL.
            meta = json.loads(data)
            data = fetch(meta["download_url"], day, size)
        if len(data) != size or data[:4] != b"PAR1" or data[-4:] != b"PAR1":
            raise SystemExit(f"{day}: invalid Parquet or size mismatch (got {len(data)}, expected {size})")
        parquet = ParquetFile(BytesIO(data))
        fields = set(parquet.schema_arrow.names)
        if not REQUIRED <= fields or not {"date", "timestamp"} & fields or not parquet.metadata.num_rows:
            raise SystemExit(f"{day}: missing rows or required columns (columns={sorted(fields)})")
        date_field = "date" if "date" in fields else "timestamp"
        actual = {str(value)[:10] for value in parquet.read(columns=[date_field]).column(0).to_pylist()}
        if not dates_match(actual, day, asset):
            raise SystemExit(f"{day}: Parquet holds dates {sorted(actual)[:3]}, not {day}")
        if asset == "futures_daily" and actual != {day} and uploaded == 0:
            print(f"{asset} {day}: NOTE bars are stamped {sorted(actual)} (column {date_field!r}); columns={sorted(fields)}", flush=True)
        digest = hashlib.sha256(data).hexdigest()
        storage.put_object(Bucket=BUCKET, Key=key, Body=data, Metadata={"verified-sha256": digest})
        with storage.get_object(Bucket=BUCKET, Key=key)["Body"] as body:
            if body.read() != data:
                raise SystemExit(f"{day}: R2 bytes differ from MarketParquet")
        uploaded += 1
        rows_total += parquet.metadata.num_rows
        if uploaded % 25 == 0:
            print(f"{asset} {year}: {uploaded} uploaded so far (through {day})", flush=True)
    print(f"{asset} {year}: DONE dates={len(dates)} uploaded={uploaded} already_verified={skipped} new_rows={rows_total}")


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in ASSETS or not sys.argv[2].isdigit():
        raise SystemExit(__doc__)
    main(sys.argv[1], sys.argv[2])
