"""Export recent prices for the COT System report and print a coverage check.

Reads the MarketParquet archive in the R2 bucket (futures_daily and etf_daily), keeps the stand-in ETFs and all futures,
and writes two small files into the folder given as the first argument:
  futures_recent.csv.gz  (about 700 calendar days)
  etf_recent.csv.gz      (about 400 calendar days, only the stand-in ETFs)
Also asks MarketParquet (manifest only, no downloads) for the newest file it offers, so stale data is visible.
"""
import hashlib
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import date, timedelta
from io import BytesIO
from urllib.request import Request, urlopen

import pandas as pd
import pyarrow.parquet as pq

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from r2_storage import BUCKET, client  # noqa: E402

ETFS = ["TLT", "EDV", "IEF", "IEI", "SHY", "PPLT", "BNO", "UNG", "USO", "UGA", "CORN", "WEAT", "SOYB", "CANE", "BAL",
        "UUP", "VXX", "FXC", "FXF", "FXY", "FXE", "FXB", "FXA", "GLD", "SLV", "CPER"]
out_dir = sys.argv[1]
os.makedirs(out_dir, exist_ok=True)
storage = client()


def keys_for(asset, days):
    prefix = f"marketparquet/{asset}/"
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    pages = storage.get_paginator("list_objects_v2").paginate(Bucket=BUCKET, Prefix=prefix)
    allkeys = sorted(o["Key"] for p in pages for o in p.get("Contents", []) if o["Key"].endswith(".parquet"))
    print(f"{asset}: {len(allkeys)} files in R2, first {allkeys[0][len(prefix):-8]}, last {allkeys[-1][len(prefix):-8]}")
    return prefix, [k for k in allkeys if k[len(prefix):-8] >= cutoff]


def reader(prefix, only):
    def read(key):
        resp = storage.get_object(Bucket=BUCKET, Key=key)
        with closing(resp["Body"]) as body:
            raw = body.read()
        if hashlib.sha256(raw).hexdigest() != resp["Metadata"].get("verified-sha256"):
            raise RuntimeError(f"Unverified archive object {key}")
        df = pq.read_table(BytesIO(raw)).to_pandas()
        df = df[["symbol", "open", "high", "low", "close", "volume"]]
        if only:
            df = df[df["symbol"].isin(only)]
        df["file_date"] = key[len(prefix):-len(".parquet")]
        return df
    return read


for asset, days, only, name in (("futures_daily", 700, None, "futures_recent.csv.gz"), ("etf_daily", 400, ETFS, "etf_recent.csv.gz")):
    prefix, keys = keys_for(asset, days)
    with ThreadPoolExecutor(max_workers=8) as pool:
        frame = pd.concat(list(pool.map(reader(prefix, only), keys)), ignore_index=True)
    frame.to_csv(os.path.join(out_dir, name), index=False)
    print(f"{asset}: wrote {name}: {len(frame)} rows, {frame['symbol'].nunique()} symbols, last file date {frame['file_date'].max()}")
    if only:
        last = frame.groupby("symbol")["file_date"].agg(["min", "max", "count"])
        print(last.to_string())
        print("stand-ins missing from the archive:", sorted(set(only) - set(frame["symbol"])) or "none")

# What does MarketParquet itself offer right now? (manifest only)
token = os.environ.get("MARKETPARQUET_API_KEY", "")
start = (date.today() - timedelta(days=45)).isoformat()
for asset in ("etf_daily", "futures_daily"):
    req = Request(f"https://marketparquet.com/api/v1/manifest/{asset}?start={start}&end={date.today().isoformat()}",
                  headers={"Authorization": f"Bearer {token}", "User-Agent": "insider-buying-research/1.0"})
    try:
        m = json.loads(urlopen(req, timeout=60).read())
        dates = sorted(f["date"] for f in m.get("files") or [])
        print(f"vendor manifest {asset}: plan={m.get('plan')!r} newest {dates[-1] if dates else None}; last 5: {dates[-5:]}")
    except Exception as e:
        print(f"vendor manifest {asset}: failed ({e})")
