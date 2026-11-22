"""Rebuild the COT report's 20-day trend snapshot (futures_sma20.json) from the stitched current table in R2.

Same rules as the exporter in .github/workflows/export-cot-trend.yml: the last 20 bars of each symbol, the last bar must be the newest
day, no gap of more than 7 calendar days between bars, price above / below / equal to the plain 20-day average of closes.
Source: marketparquet/futures_current/futures_prices_current.parquet (price-level consistent, through 2026-11-20).
Writes futures_data/futures_sma20_current.json. Does not modify R2.
"""
import hashlib
import json
import math
import os
from datetime import date
from io import BytesIO
from statistics import fmean

import boto3
import pyarrow.parquet as pq

s3 = boto3.client("s3", endpoint_url=os.environ["R2_ENDPOINT_URL"], aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
                  aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"], region_name="auto")
resp = s3.get_object(Bucket="insider-research", Key="marketparquet/futures_current/futures_prices_current.parquet")
raw = resp["Body"].read()
assert hashlib.sha256(raw).hexdigest() == resp["Metadata"]["verified-sha256"]
df = pq.read_table(BytesIO(raw), columns=["symbol", "file_date", "close"]).to_pandas()
latest = date.fromisoformat(df["file_date"].max())
trends, skipped = {}, {}
for sym, g in df.groupby("symbol"):
    g = g.sort_values("file_date")
    if g["file_date"].duplicated().any():
        skipped[sym] = "duplicate dates"
        continue
    tail = g.tail(20)
    days = [date.fromisoformat(d) for d in tail["file_date"]]
    if len(tail) != 20 or days[-1] != latest:
        skipped[sym] = "not current or fewer than 20 bars"
        continue
    if any((b - a).days > 7 for a, b in zip(days, days[1:])):
        skipped[sym] = "gap of more than 7 days in the last 20 bars"
        continue
    prices = [float(x) for x in tail["close"]]
    if any(not math.isfinite(x) for x in prices):
        skipped[sym] = "non-finite close"
        continue
    price, avg = prices[-1], fmean(prices)
    trends[sym] = "above" if price > avg else "below" if price < avg else "equal"
open("futures_data/futures_sma20_current.json", "w").write(json.dumps({"as_of": latest.isoformat(), "symbols": trends}, indent=2) + "\n")
print(f"{len(trends)} trend flags as of {latest}; skipped: {skipped}")
