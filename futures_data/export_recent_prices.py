"""Export the most recent daily futures bars from the CURRENT stitched series in R2 into one small CSV
(for the COT System report).

Source: marketparquet/futures_current/futures_prices_current.parquet (whole archive on one price level plus the newest days,
built by futures-current-build.yml). Keeps the newest N sessions (default 420: a 252-session price index plus history).
Output: futures_data/recent_prices.csv with columns date, symbol, open, high, low, close, source.
"""
import hashlib
import os
import sys
from io import BytesIO

import boto3
import pyarrow.parquet as pq

BUCKET = "insider-research"
KEY = "marketparquet/futures_current/futures_prices_current.parquet"
KEEP = int(sys.argv[1]) if len(sys.argv) > 1 else 420

client = boto3.client(
    "s3", endpoint_url=os.environ["R2_ENDPOINT_URL"],
    aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
    aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"], region_name="auto",
)
resp = client.get_object(Bucket=BUCKET, Key=KEY)
raw = resp["Body"].read()
if hashlib.sha256(raw).hexdigest() != resp["Metadata"].get("verified-sha256"):
    raise RuntimeError("Unverified current-series object")
df = pq.read_table(BytesIO(raw)).to_pandas()
days = sorted(df["file_date"].astype(str).unique())[-KEEP:]
out = df[df["file_date"].astype(str).isin(days)].rename(columns={"file_date": "date"})
cols = ["date", "symbol", "open", "high", "low", "close"] + (["source"] if "source" in out.columns else [])
os.makedirs("futures_data", exist_ok=True)
out[cols].sort_values(["symbol", "date"]).to_csv("futures_data/recent_prices.csv", index=False)
if KEEP >= 99999:
    allrows = df.rename(columns={"file_date": "date"})[cols].sort_values(["symbol", "date"])
    allrows.to_csv("futures_data/prices_full.csv.gz", index=False, compression="gzip")
print(f"wrote {len(out)} rows, {out['symbol'].nunique()} symbols, {days[0]} to {days[-1]}")
