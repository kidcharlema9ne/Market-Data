"""Like fetch_futures_prices.py, but also appends the days in marketparquet/futures_daily_current/.

Output futures_prices_current.parquet: symbol, open, high, low, close, volume, file_date, source
(source is 'vendor_archive' for the original archive, otherwise as written by build_current_futures.py).
The original archive is not modified; a symbol's series simply continues past 2026-11-06 only where it was verified.
"""
import hashlib
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from io import BytesIO

import boto3
import pyarrow as pa
import pyarrow.parquet as pq

BUCKET = "insider-research"
MAIN, CUR = "marketparquet/futures_daily/", "marketparquet/futures_daily_current/"
c = boto3.client("s3", endpoint_url=os.environ["R2_ENDPOINT_URL"], aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
                 aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"], region_name="auto")
keys = []
for prefix in (MAIN, CUR):
    keys += sorted(o["Key"] for p in c.get_paginator("list_objects_v2").paginate(Bucket=BUCKET, Prefix=prefix)
                   for o in p.get("Contents", []) if o["Key"].endswith(".parquet"))
main_days = {k[len(MAIN):-8] for k in keys if k.startswith(MAIN)}


def read(key):
    resp = c.get_object(Bucket=BUCKET, Key=key)
    with closing(resp["Body"]) as b:
        raw = b.read()
    if hashlib.sha256(raw).hexdigest() != resp["Metadata"].get("verified-sha256"):
        raise RuntimeError(f"Unverified object {key}")
    t = pq.read_table(BytesIO(raw))
    prefix = MAIN if key.startswith(MAIN) else CUR
    day = key[len(prefix):-8]
    if prefix == CUR and day in main_days:
        return None
    n = t.num_rows
    src = ["vendor_archive"] * n if prefix == MAIN else t.column("source").to_pylist()
    cols = {k: t.column(k).to_pylist() for k in ("symbol", "open", "high", "low", "close", "volume")}
    cols["file_date"] = [day] * n
    cols["source"] = src
    return pa.table(cols)


with ThreadPoolExecutor(max_workers=8) as pool:
    tables = [t for t in pool.map(read, keys) if t is not None]
out = pa.concat_tables(tables)
pq.write_table(out, "futures_prices_current.parquet")
print("rows", out.num_rows, "newest file_date", max(out.column("file_date").to_pylist()))
