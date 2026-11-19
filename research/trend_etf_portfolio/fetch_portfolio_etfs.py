"""Download SPY, QQQ, VEA, VWO, IAU, BIV, SGOV, IEF daily prices from the R2 ETF feed into OUT_DIR/portfolio_etfs.parquet (symbol, date_i, open, high, low, close, volume). Reads only."""
import hashlib, os, sys
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

BUCKET = "insider-research"; PREFIX = "marketparquet/etf_daily/"
WANT = ["SPY", "QQQ", "VEA", "VWO", "IAU", "BIV", "SGOV", "IEF"]
COLS = ["symbol", "open", "high", "low", "close", "volume"]
out_dir = Path(sys.argv[1]); out_dir.mkdir(parents=True, exist_ok=True)
client = boto3.client("s3", endpoint_url=os.environ["R2_ENDPOINT_URL"], aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"], aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"], region_name="auto")
pages = client.get_paginator("list_objects_v2").paginate(Bucket=BUCKET, Prefix=PREFIX)
keys = sorted(o["Key"] for p in pages for o in p.get("Contents", []) if o["Key"].endswith(".parquet"))
assert len(keys) > 6000, len(keys)


def read(key):
    resp = client.get_object(Bucket=BUCKET, Key=key)
    with closing(resp["Body"]) as body:
        raw = body.read()
    if hashlib.sha256(raw).hexdigest() != resp["Metadata"].get("verified-sha256"):
        raise RuntimeError(f"Unverified archive object {key}")
    t = pq.read_table(BytesIO(raw), columns=COLS)
    t = t.filter(pc.is_in(t["symbol"], value_set=pa.array(WANT)))
    n = t.num_rows
    days = (date.fromisoformat(key[len(PREFIX):-len(".parquet")]) - date(1970, 1, 1)).days
    return pa.table({"symbol": pc.cast(t["symbol"], pa.string()), "date_i": pa.array(np.full(n, days, dtype=np.int32)), **{c: pc.cast(t[c], pa.float64()) for c in COLS[1:]}})


with ThreadPoolExecutor(max_workers=8) as pool:
    tables = list(pool.map(read, keys))
out = pa.concat_tables(tables)
pq.write_table(out, out_dir / "portfolio_etfs.parquet", compression="zstd")
import collections
cnt = collections.Counter(out.column("symbol").to_pylist())
print("portfolio_etfs.parquet rows:", out.num_rows, "symbols and days:", dict(cnt), flush=True)
