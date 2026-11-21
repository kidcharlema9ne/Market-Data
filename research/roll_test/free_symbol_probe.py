"""READ-ONLY: does the per-symbol free daily endpoint give recent futures data that can be compared to the R2 archive?

Endpoint (documented): GET /api/data/symbol/futures/{symbol}/daily.parquet  -> 302 to a Parquet file (last 365 days).
Tests (1) whether the key works on it and without a key, (2) the latest date it holds, (3) the ratio free/stored on the
overlap, and (4) whether that ratio equals the product of published roll ratios with roll_date after the archive end.
Never prints the key, headers or redirect URLs.
"""
import csv
import json
import os
import time
import urllib.request
from io import BytesIO
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit

import boto3
import pyarrow.parquet as pq

BASE = "https://marketparquet.com"
BUCKET, PREFIX = "insider-research", "marketparquet/futures_daily/"
TOKEN = os.environ["MARKETPARQUET_API_KEY"]
MAP = {"6A": "A6", "6B": "B6", "6C": "AD", "6E": "E6", "6J": "J1", "6L": "BR", "6M": "MP", "6N": "N6", "6S": "E1",
       "ZB": "US", "BRR": "BTC", "LBR": "LBS"}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


OPENER = urllib.request.build_opener(NoRedirect)


def fetch(url, auth):
    """Return (status, body, redirect_host_flag). Follows one redirect by hand; key is sent only to marketparquet.com."""
    headers = {"User-Agent": "insider-buying-research/1.0"}
    if auth:
        headers["Authorization"] = f"Bearer {TOKEN}"
    try:
        with OPENER.open(urllib.request.Request(url, headers=headers), timeout=90) as response:
            return response.status, response.read(30_000_000)
    except HTTPError as error:
        if error.code in (301, 302, 303, 307, 308):
            target = error.headers.get("Location", "")
            if target.startswith("/"):
                target = BASE + target
            same_site = urlsplit(target).hostname and urlsplit(target).hostname.endswith("marketparquet.com")
            try:
                with OPENER.open(urllib.request.Request(target, headers={"User-Agent": "insider-buying-research/1.0",
                                                                          **({"Authorization": f"Bearer {TOKEN}"} if same_site and auth else {})}), timeout=90) as r2:
                    return r2.status, r2.read(30_000_000)
            except HTTPError as e2:
                return e2.code, e2.read(300)
        return error.code, error.read(300)
    except (URLError, TimeoutError) as error:
        return None, type(error).__name__.encode()


def stored_series(storage, symbol, dates):
    out = {}
    for day in dates:
        body = storage.get_object(Bucket=BUCKET, Key=f"{PREFIX}{day}.parquet")["Body"].read()
        table = pq.read_table(BytesIO(body), columns=["symbol", "close"]).to_pylist()
        for row in table:
            if row["symbol"] == symbol:
                out[day] = row["close"]
    return out


def main():
    storage = boto3.client("s3", endpoint_url=os.environ["R2_ENDPOINT_URL"],
                           aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
                           aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"], region_name="auto")
    stored_days = sorted(o["Key"][len(PREFIX):-8] for p in storage.get_paginator("list_objects_v2").paginate(Bucket=BUCKET, Prefix=PREFIX)
                         for o in p.get("Contents", []) if o["Key"].endswith(".parquet"))
    last_stored = stored_days[-1]
    rolls = pq.read_table("futures_rolls.parquet").to_pylist()

    # [1] key vs no key on one symbol
    for label, auth in (("with key", True), ("without key", False)):
        status, body = fetch(f"{BASE}/api/data/symbol/futures/ES/daily.parquet", auth)
        ok = body[:4] == b"PAR1"
        print(f"[1] ES per-symbol daily {label}: HTTP {status}, valid parquet={ok}, bytes={len(body)}" + ("" if ok else f", head={body[:120]!r}"))

    universe = [MAP.get(r["ibkr"], r["ibkr"]) for r in csv.DictReader(open("futures_data/report_universe_48_markets.csv"))]
    exact = lambda s: s
    print(f"[2] testing {len(universe)} universe symbols (price symbols): {universe}")
    summary = []
    for symbol in universe:
        time.sleep(1.2)  # stay under 60 requests per minute
        status, body = fetch(f"{BASE}/api/data/symbol/futures/{symbol}/daily.parquet", True)
        if body[:4] != b"PAR1":
            summary.append((symbol, f"HTTP {status} no parquet"))
            continue
        table = pq.read_table(BytesIO(body))
        names = table.schema.names
        if symbol == universe[0]:
            print("    free file columns:", names, [str(t) for t in table.schema.types])
        date_col = "date" if "date" in names else ("timestamp" if "timestamp" in names else None)
        rows = table.to_pylist()
        free = {str(r[date_col])[:10]: r["close"] for r in rows}
        days = sorted(free)
        # stored file date may differ from the bar stamp for futures (session start); compare by file-date AND by stamp
        overlap = [d for d in days if d in stored_days]
        new_days = [d for d in days if d > last_stored]
        stored = stored_series(storage, symbol, overlap[-40:]) if overlap else {}
        ratios = {d: free[d] / stored[d] for d in stored if stored[d]}
        segs = []
        for d in sorted(ratios):
            key = round(ratios[d], 6)
            if segs and segs[-1][0] == key:
                segs[-1][2] = d
            else:
                segs.append([key, d, d])
        later_rolls = [(r["roll_date"], round(r["ratio"], 6)) for r in rolls if r["root"] == symbol and r["roll_date"] > last_stored]
        summary.append((symbol, f"free {days[0]}..{days[-1]} ({len(days)} days), days after archive end: {len(new_days)}, "
                                f"free/stored close ratio segments (last 40 overlap days): {segs[:6]}, "
                                f"published rolls dated after archive end: {later_rolls}"))
    for symbol, text in summary:
        print(f"[3] {symbol}: {text}")


if __name__ == "__main__":
    main()
