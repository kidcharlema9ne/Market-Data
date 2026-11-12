"""Read the latest ~45 sessions of the named tickers from the MarketParquet stock and ETF archives in R2.

Usage: python fetch_etf_recent.py OUT.parquet TICKER [TICKER ...]
Reads only a few dozen daily files and keeps only the named tickers (columns symbol, open, high, low, close, volume).
Checks the verified-sha256 object metadata like the futures fetch does.
"""
import hashlib
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from io import BytesIO

import boto3
import pyarrow as pa
import pyarrow.parquet as pq

out_path, tickers = sys.argv[1], sys.argv[2:]
BUCKET = "insider-research"
client = boto3.client(
    "s3", endpoint_url=os.environ["R2_ENDPOINT_URL"],
    aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
    aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"], region_name="auto",
)
COLS = ["symbol", "open", "high", "low", "close", "volume"]
jobs = []
for feed in ("etf_daily", "stock_daily"):
    prefix = f"marketparquet/{feed}/"
    pages = client.get_paginator("list_objects_v2").paginate(Bucket=BUCKET, Prefix=prefix)
    keys = sorted(o["Key"] for p in pages for o in p.get("Contents", []) if o["Key"].endswith(".parquet"))
    print(feed, len(keys), "files; newest", keys[-1])
    jobs += [(feed, k, prefix) for k in keys[-45:]]


def read(job):
    feed, key, prefix = job
    resp = client.get_object(Bucket=BUCKET, Key=key)
    with closing(resp["Body"]) as body:
        raw = body.read()
    if hashlib.sha256(raw).hexdigest() != resp["Metadata"].get("verified-sha256"):
        raise RuntimeError(f"Unverified archive object {key}")
    t = pq.read_table(BytesIO(raw), columns=COLS, filters=[("symbol", "in", tickers)])
    day = key[len(prefix):-len(".parquet")]
    cols = {c: t.column(c).to_pylist() for c in COLS}
    cols["file_date"] = [day] * t.num_rows
    cols["feed"] = [feed] * t.num_rows
    return pa.table(cols)


with ThreadPoolExecutor(max_workers=8) as pool:
    tables = [t for t in pool.map(read, jobs) if t.num_rows]
out = pa.concat_tables(tables)
pq.write_table(out, out_path)
print("rows", out.num_rows, "tickers found", sorted(set(out.column("symbol").to_pylist())))
