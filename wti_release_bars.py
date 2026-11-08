"""Fetch five-minute CL event windows from the licensed date partitions."""
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO
from threading import Lock
from urllib.parse import urlencode, urljoin, urlsplit

import pandas as pd
from pyarrow.parquet import ParquetFile

from marketparquet_archive_transfer import BASE, fetch

AUTH = {"Authorization": "Bearer " + os.environ["MARKETPARQUET_API_KEY"]}
LOCK = Lock()
LAST = 0.0


def throttled(url, label, size, headers=None):
    global LAST
    with LOCK:
        time.sleep(max(0, LAST + 0.12 - time.monotonic()))
        LAST = time.monotonic()
    return fetch(url, label, size, headers)


def extract(day, row):
    size = row["file_size_bytes"]
    url = urljoin(BASE, row["download_url"])
    auth = AUTH if urlsplit(url).hostname == urlsplit(BASE).hostname else None
    raw = throttled(url, day, size, auth)
    if raw[:4] != b"PAR1":
        raw = throttled(json.loads(raw)["download_url"], day, size)
    if len(raw) != size:
        raise ValueError("vendor manifest size mismatch")
    pq = ParquetFile(BytesIO(raw))
    prices = pq.read(columns=["timestamp", "symbol", "open", "high", "low", "close"]).to_pandas()
    cl = prices[prices.symbol.eq("CL")].drop(columns="symbol").copy()
    cl["file_date"] = day
    return cl


def main():
    dates = pd.read_csv("wti_release_dates.csv", dtype=str).date
    assert dates.is_unique and dates.str.fullmatch(r"\d{4}-\d{2}-\d{2}").all()
    manifest = {}
    for year, group in dates.groupby(dates.str[:4]):
        query = urlencode({"start": group.min(), "end": group.max()})
        data = json.loads(throttled(f"{BASE}/api/v1/manifest/futures_5min?{query}",
                                    f"{year} manifest", 5_000_000, AUTH))
        manifest.update({row["date"]: row for row in data.get("files", [])})
    done, gaps = [], []
    with ThreadPoolExecutor(max_workers=10) as pool:
        future_dates = {pool.submit(extract, day, manifest[day]): day for day in dates if day in manifest}
        gaps.extend((day, "absent_manifest") for day in dates if day not in manifest)
        for count, future in enumerate(as_completed(future_dates), 1):
            day = future_dates[future]
            try:
                frame = future.result()
                if len(frame):
                    done.append(frame)
                else:
                    gaps.append((day, "no_cl"))
            except (Exception, SystemExit) as exc:
                gaps.append((day, type(exc).__name__))
            if count % 100 == 0:
                print(f"Processed {count} files; {len(gaps)} gaps", flush=True)
    pd.concat(done, ignore_index=True).sort_values(["file_date", "timestamp"]).to_parquet(
        "wti_eia_cl_5min.parquet", index=False)
    pd.DataFrame(gaps, columns=["date", "reason"]).to_csv("wti_price_gaps.csv", index=False)
    print(f"{len(done)}/{len(dates)} date files with CL bars; {len(gaps)} gaps", flush=True)


if __name__ == "__main__":
    main()
