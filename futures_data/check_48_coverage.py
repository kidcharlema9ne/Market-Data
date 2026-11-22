"""Coverage check: do all 48 COT-report markets have a price series in the R2 futures archive, and how fresh is it?

Reads only (no returns research). Writes futures_data/coverage_48_report.md and prints it.
For each of the 48 markets (futures_data/report_universe_48_markets.csv) it reports the price symbol used,
first and last file date, number of trading days, missing weekdays inside the last 60 days,
and the largest one-day move in the last 60 days (a big jump may be an unadjusted roll).
"""
import csv
import hashlib
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from io import BytesIO

import boto3
import pyarrow.parquet as pq

BUCKET = "insider-research"
PREFIX = "marketparquet/futures_daily/"
# ibkr symbol -> vendor price symbol (FUTURES_DATA.md); every other symbol is identical
RENAME = {"6A": "A6", "6B": "B6", "6C": "AD", "6E": "E6", "6J": "J1", "6L": "BR", "6M": "MP",
          "6N": "N6", "6S": "E1", "ZB": "US", "BRR": "BTC", "LBR": "LBS"}

client = boto3.client(
    "s3", endpoint_url=os.environ["R2_ENDPOINT_URL"],
    aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
    aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"], region_name="auto",
)
keys = sorted(o["Key"] for p in client.get_paginator("list_objects_v2").paginate(Bucket=BUCKET, Prefix=PREFIX)
              for o in p.get("Contents", []) if o["Key"].endswith(".parquet"))
print(f"{len(keys)} files; first {keys[0]}; last {keys[-1]}", flush=True)


def read(key):
    resp = client.get_object(Bucket=BUCKET, Key=key)
    with closing(resp["Body"]) as body:
        raw = body.read()
    if hashlib.sha256(raw).hexdigest() != resp["Metadata"].get("verified-sha256"):
        raise RuntimeError(f"Unverified archive object {key}")
    t = pq.read_table(BytesIO(raw), columns=["symbol", "close"])
    return key[len(PREFIX):-len(".parquet")], dict(zip(t.column("symbol").to_pylist(), t.column("close").to_pylist()))


days, closes = [], {}
with ThreadPoolExecutor(max_workers=8) as pool:
    for day, d in pool.map(read, keys):
        days.append(day)
        for s, c in d.items():
            closes.setdefault(s, {})[day] = c
all_symbols = sorted(closes)
print(f"{len(all_symbols)} distinct price symbols in the archive", flush=True)

import datetime as dt
last_day = days[-1]
ld = dt.date.fromisoformat(last_day)
recent_weekdays = [ld - dt.timedelta(n) for n in range(0, 60) if (ld - dt.timedelta(n)).weekday() < 5]
recent_set = {d.isoformat() for d in recent_weekdays}
file_days = set(days)
missing_recent_days = sorted(recent_set - file_days)

rows = list(csv.DictReader(open("futures_data/report_universe_48_markets.csv")))
lines = ["# Coverage of the 48 COT-report markets in the R2 futures archive", "",
         f"Files: {len(keys)}; first {days[0]}; newest {last_day}. Distinct price symbols in the archive: {len(all_symbols)}.",
         f"Weekdays in the last 60 with NO file at all: {', '.join(missing_recent_days) or 'none'}.", "",
         "| COT code | report symbol | price symbol | status | first day | last day | days | days missing in last 60 | biggest 1-day move last 60 |",
         "|---|---|---|---|---|---|---|---|---|"]
missing_markets = []
for r in rows:
    ib = r["ibkr"]
    ps = RENAME.get(ib, ib)
    series = closes.get(ps)
    if not series:
        missing_markets.append(ib)
        lines.append(f"| {r['code']} | {ib} | {ps} | MISSING | | | 0 | | |")
        continue
    ds = sorted(series)
    miss = sorted(d for d in recent_set if d in file_days and d not in series)
    recent = [d for d in ds if d >= (ld - dt.timedelta(60)).isoformat()]
    worst = 0.0
    for a, b in zip(recent, recent[1:]):
        if series[a]:
            worst = max(worst, abs(series[b] / series[a] - 1))
    lines.append(f"| {r['code']} | {ib} | {ps} | ok | {ds[0]} | {ds[-1]} | {len(ds)} | {len(miss)} | {worst:.1%} |")
lines += ["", f"Markets with no price series: {', '.join(missing_markets) or 'none'}.", "",
          "Symbols in the archive that are not one of the 48 (for reference): " +
          ", ".join(s for s in all_symbols if s not in {RENAME.get(r['ibkr'], r['ibkr']) for r in rows})]
out = "\n".join(lines)
open("futures_data/coverage_48_report.md", "w").write(out + "\n")
print(out)
