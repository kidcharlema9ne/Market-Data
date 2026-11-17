"""Download the daily stock archive from R2 into one table for the efficiency ratio stock test (reads only; no returns computed).

Usage: python fetch_stock_prices.py OUT_DIR
Writes OUT_DIR/stock_prices.parquet (symbol, date_i, open, high, low, close, volume) and OUT_DIR/spy_prices.parquet (SPY from the ETF feed, for a buy-and-hold comparison).
date_i = days since 1970-01-01 of the FILE date in the key (Entry 19: every file's date equals its name).
To keep memory small a row is kept only if that day's dollar volume (close x volume) is at least $250,000, which is far below the $3M average floor used later (an average of $3M
over 15 sessions with a day under $250k is extremely rare; the test requires all 15 sessions present, so such a stock would simply be skipped).
"""
import hashlib
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import date
from io import BytesIO
from pathlib import Path

import boto3
import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

BUCKET = "insider-research"
STOCK_PREFIX = "marketparquet/stock_daily/"
ETF_PREFIX = "marketparquet/etf_daily/"
MIN_DV = 250_000.0
COLS = ["symbol", "open", "high", "low", "close", "volume"]
out_dir = Path(sys.argv[1]); out_dir.mkdir(parents=True, exist_ok=True)

client = boto3.client("s3", endpoint_url=os.environ["R2_ENDPOINT_URL"], aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
                      aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"], region_name="auto")


def list_keys(prefix):
    pages = client.get_paginator("list_objects_v2").paginate(Bucket=BUCKET, Prefix=prefix)
    return sorted(o["Key"] for p in pages for o in p.get("Contents", []) if o["Key"].endswith(".parquet"))


def read(args):
    key, prefix, spy_only = args
    resp = client.get_object(Bucket=BUCKET, Key=key)
    with closing(resp["Body"]) as body:
        raw = body.read()
    if hashlib.sha256(raw).hexdigest() != resp["Metadata"].get("verified-sha256"):
        raise RuntimeError(f"Unverified archive object {key}")
    t = pq.read_table(BytesIO(raw), columns=COLS)
    day = key[len(prefix):-len(".parquet")]
    if spy_only:
        t = t.filter(pc.equal(t["symbol"], "SPY"))
        px = {c: pc.cast(t[c], pa.float64()) for c in COLS[1:]}
    else:
        close = pc.cast(t["close"], pa.float64()); vol = pc.cast(t["volume"], pa.float64())
        t = t.filter(pc.and_(pc.greater_equal(pc.multiply(close, vol), MIN_DV), pc.greater(close, 0)))
        px = {c: pc.cast(t[c], pa.float32()) for c in COLS[1:]}
    n = t.num_rows
    days = (date.fromisoformat(day) - date(1970, 1, 1)).days
    return pa.table({"symbol": pc.cast(t["symbol"], pa.string()), "date_i": pa.array(np.full(n, days, dtype=np.int32)), **px}), n


def pull(prefix, spy_only, outfile):
    keys = list_keys(prefix)
    print(f"{prefix}: {len(keys)} files; first {keys[0]}; last {keys[-1]}", flush=True)
    assert len(keys) > 6000, f"expected about 6,750 files, found {len(keys)}"
    tables, rows = [], 0
    with ThreadPoolExecutor(max_workers=8) as pool:
        for i, (tb, n) in enumerate(pool.map(read, [(k, prefix, spy_only) for k in keys])):
            tables.append(tb); rows += n
            if i % 1000 == 0:
                print(f"  {i} files, {rows:,} rows kept", flush=True)
    out = pa.concat_tables(tables)
    pq.write_table(out, out_dir / outfile, compression="zstd")
    print(f"{outfile}: {out.num_rows:,} rows, {out.column('symbol').combine_chunks().dictionary_encode().dictionary.__len__():,} symbols", flush=True)


pull(ETF_PREFIX, True, "spy_prices.parquet")
pull(STOCK_PREFIX, False, "stock_prices.parquet")
