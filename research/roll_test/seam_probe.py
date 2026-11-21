"""READ-ONLY seam check.
(1) Free per-symbol files: close-to-close returns 2026-11-02..2026-11-20 for the markets the free endpoint serves,
    flagged against each symbol's typical daily move, beside the published rolls dated in that span.
(2) Stored R2 files: return across the boundary where later-rewritten files (2026-10-12 onward) meet the older files
    (2026-10-09 -> 2026-10-12), z-scored per symbol, to see whether the rewritten files sit on a different basis.
"""
import os
import statistics
import time
import urllib.parse
import urllib.request
from io import BytesIO
from urllib.error import HTTPError

import boto3
import pyarrow.parquet as pq

BASE = "https://marketparquet.com"
BUCKET, PREFIX = "insider-research", "marketparquet/futures_daily/"
TOKEN = os.environ["MARKETPARQUET_API_KEY"]
FREE = ["CL", "NG", "ZN", "US", "SI", "GC", "YM", "ES", "MES", "NQ", "MNQ", "RTY"]


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


OPEN = urllib.request.build_opener(NoRedirect)


def free_file(symbol):
    request = urllib.request.Request(f"{BASE}/api/data/symbol/futures/{symbol}/daily.parquet",
                                     headers={"Authorization": f"Bearer {TOKEN}", "User-Agent": "insider-buying-research/1.0"})
    try:
        return OPEN.open(request, timeout=90).read(30_000_000)
    except HTTPError as error:
        if error.code not in (301, 302, 303, 307, 308):
            raise
        target = error.headers["Location"]
        if target.startswith("/"):
            target = BASE + target
        headers = {"User-Agent": "insider-buying-research/1.0"}
        if (urllib.parse.urlparse(target).hostname or "").endswith("marketparquet.com"):
            headers["Authorization"] = f"Bearer {TOKEN}"
        return OPEN.open(urllib.request.Request(target, headers=headers), timeout=90).read(30_000_000)


def main():
    rolls = pq.read_table("futures_rolls.parquet").to_pylist()
    print("[1] free-file close-to-close returns, 2026-11-02..2026-11-20 (percent); typical = median absolute daily move over the file")
    for symbol in FREE:
        time.sleep(1.2)
        table = pq.read_table(BytesIO(free_file(symbol))).to_pylist()
        key = "date" if "date" in table[0] else "timestamp"
        series = sorted((str(r[key])[:10], r["close"]) for r in table)
        moves = [abs(series[i][1] / series[i - 1][1] - 1) for i in range(1, len(series)) if series[i - 1][1]]
        typical = statistics.median(moves) * 100
        window = [(d, c) for d, c in series if "2026-11-02" <= d <= "2026-11-20"]
        text = []
        for i in range(1, len(window)):
            text.append(f"{window[i][0][5:]}:{(window[i][1] / window[i - 1][1] - 1) * 100:+.2f}")
        print(f"    {symbol} typical {typical:.2f}% | " + " ".join(text))
        mine = [(r["roll_date"], round(r["ratio"], 6)) for r in rolls if r["root"] == symbol and r["roll_date"] >= "2026-10-01"]
        if mine:
            print(f"      published rolls since 2026-10-01: {mine}")

    print("[2] stored-file boundary 2026-10-09 -> 2026-10-12 (older files meet re-uploaded files): z-scores per symbol")
    storage = boto3.client("s3", endpoint_url=os.environ["R2_ENDPOINT_URL"],
                           aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
                           aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"], region_name="auto")
    days = sorted(o["Key"][len(PREFIX):-8] for p in storage.get_paginator("list_objects_v2").paginate(Bucket=BUCKET, Prefix=PREFIX + "2026-0")
                  for o in p.get("Contents", []))
    days += sorted(o["Key"][len(PREFIX):-8] for p in storage.get_paginator("list_objects_v2").paginate(Bucket=BUCKET, Prefix=PREFIX + "2026-1")
                   for o in p.get("Contents", []))
    days = [d for d in days if d >= "2026-06-01"]
    closes = {}
    for day in days:
        body = storage.get_object(Bucket=BUCKET, Key=f"{PREFIX}{day}.parquet")["Body"].read()
        for r in pq.read_table(BytesIO(body), columns=["symbol", "close"]).to_pylist():
            closes.setdefault(r["symbol"], {})[day] = r["close"]
    flagged = []
    for symbol, by_day in closes.items():
        ds = sorted(by_day)
        rets = {ds[i]: by_day[ds[i]] / by_day[ds[i - 1]] - 1 for i in range(1, len(ds)) if by_day[ds[i - 1]]}
        scale = statistics.pstdev(rets.values()) or 1e-9
        if "2026-10-12" in rets:
            flagged.append((abs(rets["2026-10-12"]) / scale, symbol, rets["2026-10-12"] * 100))
    flagged.sort(reverse=True)
    print("    largest boundary moves (z, symbol, percent):", [(round(z, 1), s, round(p, 2)) for z, s, p in flagged[:12]])
    print("    symbols with boundary z > 3:", sum(1 for z, _, _ in flagged if z > 3), "of", len(flagged), "(about 0.3% expected by chance)")


if __name__ == "__main__":
    main()
