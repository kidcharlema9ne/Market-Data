"""Copy the stitched futures table (all symbols, full history, one price level) from R2 to ./futures_prices.parquet unchanged.

The workflow recent-prices.yml then publishes it as a GitHub release asset (release tag prices-latest, overwritten each run) so other
repos can download the full history with a plain URL and no keys:
  https://github.com/kidcharlema9ne/Market-Data/releases/download/prices-latest/futures_prices.parquet
Columns: symbol, open, high, low, close, volume, file_date, rebase_factor, source. Exits 1 (so the old release stays) if the table
cannot be read or looks wrong. Published publicly with Michael's explicit approval (22 Nov 2026).
"""
import os
import sys
from io import BytesIO

import boto3
import pyarrow.parquet as pq

KEY = "marketparquet/futures_current/futures_prices_current.parquet"
client = boto3.client("s3", endpoint_url=os.environ["R2_ENDPOINT_URL"], aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
                      aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"], region_name="auto")
raw = client.get_object(Bucket="insider-research", Key=KEY)["Body"].read()
table = pq.read_table(BytesIO(raw))
need = {"symbol", "open", "high", "low", "close", "volume", "file_date"}
if not need <= set(table.schema.names) or table.num_rows < 400_000:
    sys.exit(f"stitched table looks wrong: {table.num_rows} rows, columns {table.schema.names}")
open("futures_prices.parquet", "wb").write(raw)
print(f"copied {table.num_rows} rows, {len(raw) / 1e6:.1f} MB")
