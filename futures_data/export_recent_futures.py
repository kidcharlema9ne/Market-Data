"""Refresh data/futures_recent.csv.gz (last ~700 calendar days, one row per market per day) from the STITCHED futures table in R2.

Source: marketparquet/futures_current/futures_prices_current.parquet in the bucket insider-research. That table is built by the
Market-Data workflow futures-current-build.yml (scripts build_current_futures.py and stitch_current_futures.py), which applies the
vendor's roll table so every day sits on ONE price level and adds the newest days. Do not read the raw futures_daily/ files for the
COT System: files stored before a roll are on an old price level.

Needs the three repository secrets R2_ENDPOINT_URL, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY.
If the download fails or the table is unusable, the existing file is kept untouched and the script exits 0 with a loud warning
(the report already lists markets whose prices are stale under "Not scored"), so a bad night never breaks the report.
"""
import os
import sys
from datetime import date, timedelta
from io import BytesIO

BUCKET = "insider-research"
KEY = "marketparquet/futures_current/futures_prices_current.parquet"
DAYS = 700
OUT = "prices/futures_recent.csv.gz"
COLUMNS = ["symbol", "file_date", "open", "high", "low", "close", "source", "rebase_factor"]


def warn(msg):
    print(f"WARNING: {msg}. Kept the existing {OUT} unchanged.", file=sys.stderr)


def main():
    try:
        import boto3
        import pandas as pd
        import pyarrow.parquet as pq

        client = boto3.client("s3", endpoint_url=os.environ["R2_ENDPOINT_URL"], aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
                              aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"], region_name="auto")
        raw = client.get_object(Bucket=BUCKET, Key=KEY)["Body"].read()
        df = pq.read_table(BytesIO(raw)).to_pandas()
    except Exception as exc:  # network, keys, missing object, library problems
        warn(f"could not read the stitched table ({type(exc).__name__}: {exc})")
        return

    missing = [c for c in COLUMNS if c not in df.columns]
    if missing:
        warn(f"stitched table is missing columns {missing}")
        return
    df["file_date"] = pd.to_datetime(df["file_date"]).dt.strftime("%Y-%m-%d")
    cutoff = (date.today() - timedelta(days=DAYS)).isoformat()
    df = df[df["file_date"] >= cutoff][COLUMNS].sort_values(["symbol", "file_date"])
    if df["symbol"].nunique() < 40 or df["file_date"].max() < (date.today() - timedelta(days=10)).isoformat():
        warn(f"stitched table looks wrong or stale ({df['symbol'].nunique()} symbols, newest day {df['file_date'].max()})")
        return
    os.makedirs("prices", exist_ok=True)
    df.to_csv(OUT, index=False)
    print(f"rows {len(df)}, symbols {df['symbol'].nunique()}, last day {df['file_date'].max()} (stitched, roll-adjusted)")


if __name__ == "__main__":
    main()
