"""Download every futures_daily parquet from R2 into one table (date, symbol, open, high, low, close, volume).

Reads only; no returns computed. Output: futures_prices.parquet (uploaded as a workflow artifact).
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
PREFIX = "marketparquet/futures_daily/"

client = boto3.client(
    "s3", endpoint_url=os.environ["R2_ENDPOINT_URL"],
    aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
    aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"], region_name="auto",
)
pages = client.get_paginator("list_objects_v2").paginate(Bucket=BUCKET, Prefix=PREFIX)
keys = sorted(o["Key"] for p in pages for o in p.get("Contents", []) if o["Key"].endswith(".parquet"))
print(f"{len(keys)} files; first {keys[0]}; last {keys[-1]}")


def read(key):
    resp = client.get_object(Bucket=BUCKET, Key=key)
    with closing(resp["Body"]) as body:
        raw = body.read()
    if hashlib.sha256(raw).hexdigest() != resp["Metadata"].get("verified-sha256"):
        raise RuntimeError(f"Unverified archive object {key}")
    table = pq.read_table(BytesIO(raw))
    day = key[len(PREFIX):-len(".parquet")]
    return day, table


tables = []
with ThreadPoolExecutor(max_workers=8) as pool:
    for day, table in pool.map(read, keys):
        if not tables:
            print("columns:", table.schema.names, table.schema.types)
        cols = {name: table.column(name).to_pylist() for name in ("symbol", "open", "high", "low", "close", "volume")}
        cols["file_date"] = [day] * table.num_rows
        tables.append(pa.table(cols))
out = pa.concat_tables(tables)
pq.write_table(out, "futures_prices.parquet")
print("rows", out.num_rows)
