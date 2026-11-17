"""Read-only look at how the stock_daily archive labels instruments (no returns computed). Usage: python inspect_stock_symbols.py OUT_FILE
Prints the schema, asset_type counts if the column exists, symbol patterns (dots, dashes, digits, length, Q suffix, -DELISTED) and samples, on three sample days; plus the symbols seen in the worst/best trades of Entry 134."""
import os, sys, re
from collections import Counter
from io import BytesIO
import boto3
import pyarrow.parquet as pq
import pandas as pd

client = boto3.client("s3", endpoint_url=os.environ["R2_ENDPOINT_URL"], aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"], aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"], region_name="auto")
B = "insider-research"
out = open(sys.argv[1], "w")
def P(*a):
    print(*a, flush=True); print(*a, file=out)
for day in ("2005-06-15", "2013-06-14", "2021-06-15"):
    t = pq.read_table(BytesIO(client.get_object(Bucket=B, Key=f"marketparquet/stock_daily/{day}.parquet")["Body"].read()))
    df = t.to_pandas()
    P(f"\n===== {day}: {len(df)} rows; columns {list(df.columns)}")
    for col in df.columns:
        if col in ("symbol", "open", "high", "low", "close", "volume", "date", "timestamp"): continue
        P(f"-- column {col}: ", df[col].value_counts(dropna=False).head(15).to_dict())
    s = df["symbol"].astype(str)
    df["dv"] = df["close"] * df["volume"]
    liquid = df[df["dv"] >= 3e6]
    P(f"rows with dollar volume >= $3M that day: {len(liquid)}")
    pats = {"has dot": s.str.contains(r"\.", regex=True), "has dash (not DELISTED only)": s.str.replace("-DELISTED", "", regex=False).str.contains("-"), "ends -DELISTED": s.str.endswith("-DELISTED"),
            "length >= 5 (base)": s.str.replace("-DELISTED", "", regex=False).str.len() >= 5, "ends Q (len>=5)": s.str.replace("-DELISTED", "", regex=False).str.match(r"^[A-Z]{4}Q$"),
            "ends W/WS/WT/U/R": s.str.replace("-DELISTED", "", regex=False).str.match(r"^[A-Z]{3,}(W|WS|WT|U|R)$"), "contains digit": s.str.contains(r"\d")}
    for k, m in pats.items():
        P(f"{k}: all {int(m.sum())}, liquid {int((m & (df['dv'] >= 3e6)).sum())}; liquid sample: {sorted(s[m & (df['dv'] >= 3e6)].tolist())[:40]}")
want = ["BAC.C-DELISTED", "CCIV-DELISTED", "LCID", "PIP-DELISTED", "DYNIQ-DELISTED", "TCO-DELISTED", "FNP-DELISTED", "LIZ-DELISTED", "AAXN-DELISTED", "TASR-DELISTED", "GPT", "SJI-DELISTED", "CSC-DELISTED", "ATRS-DELISTED"]
P("\n===== symbols from the Entry 134 extreme trades: find the first and last file day each appears in the 2021 and 2013 sample days is not enough; list on sample days")
for day in ("2013-06-14", "2021-02-10", "2012-12-14"):
    df = pq.read_table(BytesIO(client.get_object(Bucket=B, Key=f"marketparquet/stock_daily/{day}.parquet")["Body"].read())).to_pandas()
    sub = df[df["symbol"].isin(want)]
    P(day, sub.drop(columns=[c for c in ("timestamp",) if c in sub.columns]).to_string(index=False))
out.close()
