"""READ-ONLY overlap test: vendor's CURRENT futures_daily files vs the files stored in R2, Sep 2026 onward.

Question answered: do the vendor's revised prices differ from the stored ones by a single multiplicative factor,
and does that factor equal the product of the published roll ratios that were detected AFTER the archive upload?
Safety: never prints the key, headers or presigned URLs. R2 use is get/list only.
"""
import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone
from io import BytesIO
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import boto3
import pyarrow.parquet as pq

BASE = "https://marketparquet.com"
BUCKET, PREFIX = "insider-research", "marketparquet/futures_daily/"
START = os.environ.get("OVERLAP_START", "2026-08-15")
END = os.environ.get("OVERLAP_END", "2026-11-21")
FOCUS = ["ES", "NQ", "CL", "NG", "ZN", "US", "MES"]
TOKEN = os.environ["MARKETPARQUET_API_KEY"]
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def get(url, headers=None, limit=60_000_000):
    request = Request(url, headers={"User-Agent": "insider-buying-research/1.0", **(headers or {})})
    for attempt in range(3):
        try:
            with urlopen(request, timeout=90) as response:
                return response.read(limit)
        except HTTPError as error:
            if error.code in (401, 403, 404):
                raise SystemExit(f"HTTP {error.code}")
        except (URLError, TimeoutError):
            pass
    raise SystemExit("network failure")


def vendor_file(entry):
    url = entry["download_url"]
    if url.startswith("/"):
        url = BASE + url
    data = get(url, AUTH if url.startswith(BASE) else None)
    if url.startswith(BASE + "/api/v1/download/"):
        data = get(json.loads(data)["download_url"])
    return data


def rows_of(data):
    table = pq.read_table(BytesIO(data))
    names = table.schema.names
    cols = {n: table.column(n).to_pylist() for n in ("symbol", "open", "high", "low", "close")}
    return {s: (o, h, l, c) for s, o, h, l, c in zip(cols["symbol"], cols["open"], cols["high"], cols["low"], cols["close"])}, names


def main():
    storage = boto3.client("s3", endpoint_url=os.environ["R2_ENDPOINT_URL"],
                           aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
                           aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"], region_name="auto")
    stored_meta = {}
    for page in storage.get_paginator("list_objects_v2").paginate(Bucket=BUCKET, Prefix=PREFIX):
        for obj in page.get("Contents", []):
            if obj["Key"].endswith(".parquet"):
                stored_meta[obj["Key"][len(PREFIX):-8]] = obj["LastModified"]
    bulk_day, _ = Counter(m.strftime("%Y-%m-%d") for m in stored_meta.values()).most_common(1)[0]
    cutoff = max(m for m in stored_meta.values() if m.strftime("%Y-%m-%d") == bulk_day)
    later = sorted((d, m.strftime("%Y-%m-%d %H:%M")) for d, m in stored_meta.items() if m.strftime("%Y-%m-%d") != bulk_day)
    print(f"[A] bulk upload day {bulk_day}, last bulk object written {cutoff:%Y-%m-%d %H:%M} UTC")
    print(f"[A] {len(later)} stored files were written on other days (file_date, uploaded):")
    for item in later:
        print("    ", item)

    rolls = pq.read_table("futures_rolls.parquet").to_pylist()
    print("[B] full roll table (root, roll_date, ratio, detected_at):")
    for r in sorted(rolls, key=lambda r: (r["roll_date"], r["root"])):
        print(f"     {r['root']:5s} {r['roll_date']} {r['ratio']:.6f} {r['detected_at'][:19]}")
    last_stored = max(stored_meta)
    after_archive = [r for r in rolls if datetime.fromisoformat(r["detected_at"]) > cutoff]
    print(f"[B] rolls detected after the archive upload: {len(after_archive)}; of those with roll_date <= last stored file {last_stored}: "
          f"{sum(1 for r in after_archive if r['roll_date'] <= last_stored)}")

    manifest = json.loads(get(f"{BASE}/api/v1/manifest/futures_daily?start={START}&end={END}", AUTH, 5_000_000))
    files = sorted(manifest.get("files") or [], key=lambda e: e["date"])
    print(f"[C] vendor manifest {START}..{END}: {len(files)} files, {files[0]['date']}..{files[-1]['date']}; keys={sorted(manifest)}")
    vendor_days = {e["date"] for e in files}
    print("[C] vendor days missing from R2:", sorted(vendor_days - set(stored_meta)))
    print("[C] R2 days in window missing from vendor:", sorted(d for d in stored_meta if START <= d <= END and d not in vendor_days))

    series = defaultdict(list)  # symbol -> [(date, ratio_close, spread_of_ohlc_ratios)]
    symbol_set_diff = Counter()
    for entry in files:
        day = entry["date"]
        if day not in stored_meta:
            continue
        new, _ = rows_of(vendor_file(entry))
        with storage.get_object(Bucket=BUCKET, Key=f"{PREFIX}{day}.parquet")["Body"] as body:
            old, _ = rows_of(body.read())
        for symbol in set(new) | set(old):
            if symbol not in new or symbol not in old:
                symbol_set_diff[symbol] += 1
                continue
            ratios = [n / o for n, o in zip(new[symbol][:4], old[symbol][:4]) if n and o]
            if len(ratios) == 4:
                series[symbol].append((day, ratios[3], max(ratios) - min(ratios)))
    print(f"[D] compared {len(series)} symbols over {len({d for s in series.values() for d, _, _ in s})} common days; "
          f"symbols present on only one side on some day: {dict(symbol_set_diff.most_common(8))}")

    changed = {}
    for symbol, points in series.items():
        points.sort()
        segments, current = [], None
        for day, ratio, spread in points:
            key = round(ratio, 6)
            if current and current["ratio"] == key:
                current["last"] = day
                current["days"] += 1
                current["spread"] = max(current["spread"], spread)
            else:
                current = {"ratio": key, "first": day, "last": day, "days": 1, "spread": spread}
                segments.append(current)
        if any(abs(s["ratio"] - 1) > 2e-6 for s in segments):
            changed[symbol] = segments
    print(f"[D] symbols where vendor prices now differ from stored: {len(changed)} of {len(series)}")

    # expected ratio = product of roll ratios detected after the archive upload with roll_date >= the bar date
    def expected(symbol, day):
        value = 1.0
        for r in after_archive:
            if r["root"] == symbol and r["roll_date"] >= day:
                value *= r["ratio"]
        return value

    agree = disagree = 0
    bad = []
    for symbol, points in series.items():
        for day, ratio, spread in points:
            if abs(ratio / expected(symbol, day) - 1) < 2e-5:
                agree += 1
            else:
                disagree += 1
                bad.append((symbol, day, ratio, expected(symbol, day)))
    print(f"[E] symbol-days where observed vendor/stored ratio == product of newly detected published ratios: {agree}; not equal: {disagree}")
    bad_symbols = Counter(s for s, *_ in bad)
    print("[E] symbols with any mismatch:", dict(bad_symbols.most_common(40)))
    worst_spread = max((sp for pts in series.values() for _, _, sp in pts), default=0)
    print(f"[E] largest open/high/low/close ratio spread within any single bar: {worst_spread:.2e} (about 0 means one multiplicative factor)")
    for symbol in FOCUS:
        print(f"[F] {symbol}: segments of observed vendor/stored close ratio:", changed.get(symbol, "no change vs stored" if symbol in series else "symbol not found"))
        print(f"    published rolls for {symbol}:", [(r['roll_date'], round(r['ratio'], 6), r['detected_at'][:10]) for r in rolls if r['root'] == symbol])
    print("[G] first 25 mismatches (symbol, date, observed, expected):", [(s, d, round(o, 6), round(e, 6)) for s, d, o, e in bad[:25]])


if __name__ == "__main__":
    main()
