"""Export the most recent daily futures bars from R2 into one small CSV (for the COT price-gap report).

Reads only the newest N daily files (default 420 sessions, enough for a 252-session price index plus history).
Output: futures_data/recent_prices.csv with columns date, symbol, open, high, low, close.
"""
import hashlib
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from io import BytesIO

import boto3
import pyarrow.parquet as pq

BUCKET = "insider-research"
PREFIX = "marketparquet/futures_daily/"
KEEP = int(sys.argv[1]) if len(sys.argv) > 1 else 420

client = boto3.client(
    "s3", endpoint_url=os.environ["R2_ENDPOINT_URL"],
    aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
    aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"], region_name="auto",
)
pages = client.get_paginator("list_objects_v2").paginate(Bucket=BUCKET, Prefix=PREFIX)
keys = sorted(o["Key"] for p in pages for o in p.get("Contents", []) if o["Key"].endswith(".parquet"))
print(f"{len(keys)} files in bucket; newest {keys[-1]}")
keys = keys[-KEEP:]


def read(key):
    resp = client.get_object(Bucket=BUCKET, Key=key)
    with closing(resp["Body"]) as body:
        raw = body.read()
    if hashlib.sha256(raw).hexdigest() != resp["Metadata"].get("verified-sha256"):
        raise RuntimeError(f"Unverified archive object {key}")
    table = pq.read_table(BytesIO(raw))
    day = key[len(PREFIX):-len(".parquet")]
    cols = {n: table.column(n).to_pylist() for n in ("symbol", "open", "high", "low", "close")}
    return day, cols


lines = ["date,symbol,open,high,low,close"]
with ThreadPoolExecutor(max_workers=8) as pool:
    for day, cols in pool.map(read, keys):
        for i in range(len(cols["symbol"])):
            lines.append(",".join([day, str(cols["symbol"][i])] + [repr(cols[c][i]) for c in ("open", "high", "low", "close")]))
os.makedirs("futures_data", exist_ok=True)
with open("futures_data/recent_prices.csv", "w") as f:
    f.write("\n".join(lines) + "\n")
print(f"wrote {len(lines) - 1} rows for {len(keys)} sessions, {keys[0]} to {keys[-1]}")
