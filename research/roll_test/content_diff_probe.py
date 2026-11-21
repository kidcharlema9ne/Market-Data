"""READ-ONLY: compare the CONTENTS of every vendor futures_daily file whose size differs from the stored R2 copy.

Steps: (1) recompute the full list of days whose vendor file size differs from the stored object size (manifest vs R2 list,
no bodies); (2) for each such day download the vendor file and read the stored file; (3) for every symbol and day divide
vendor by stored for open, high, low, close (and volume); (4) report which symbols changed, whether each change is one factor
per day (spread across the four prices), the factor segments by date, and the step between segments.
Safety: R2 use is list/get only. Never prints the key, headers or presigned URLs.
"""
import csv
import json
import os
import statistics
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import boto3
import pyarrow.parquet as pq

BASE = "https://marketparquet.com"
BUCKET, PREFIX = "insider-research", "marketparquet/futures_daily/"
AUTH = {"Authorization": f"Bearer {os.environ['MARKETPARQUET_API_KEY']}"}
NOISE = 2e-6          # factor within this of 1.0 counts as unchanged
SEGMENT_TOL = 5e-4    # a new segment starts when the daily factor moves more than this from the segment's first day
WORKERS = 6


def get(url, headers=None, limit=60_000_000):
    request = Request(url, headers={"User-Agent": "insider-buying-research/1.0", **(headers or {})})
    for _ in range(4):
        try:
            with urlopen(request, timeout=90) as response:
                return response.read(limit)
        except HTTPError as error:
            if error.code in (401, 403, 404):
                raise RuntimeError(f"HTTP {error.code}")
        except (URLError, TimeoutError):
            pass
    raise RuntimeError("network failure")


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
    cols = {n: table.column(n).to_pylist() for n in ("symbol", "open", "high", "low", "close", "volume") if n in names}
    out = {}
    for i, s in enumerate(cols["symbol"]):
        out[s] = tuple(cols[n][i] for n in ("open", "high", "low", "close", "volume") if n in cols)
    return out, names


def main():
    storage = boto3.client("s3", endpoint_url=os.environ["R2_ENDPOINT_URL"],
                           aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
                           aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"], region_name="auto")
    stored = {}
    for page in storage.get_paginator("list_objects_v2").paginate(Bucket=BUCKET, Prefix=PREFIX):
        for obj in page.get("Contents", []):
            if obj["Key"].endswith(".parquet"):
                stored[obj["Key"][len(PREFIX):-8]] = obj["Size"]
    entries = {}
    for year in range(2007, 2027):
        manifest = json.loads(get(f"{BASE}/api/v1/manifest/futures_daily?start={year}-01-01&end={year}-12-31", AUTH, 20_000_000))
        for e in manifest.get("files") or []:
            entries[e["date"]] = e
    days = sorted(d for d, e in entries.items() if d in stored and e["file_size_bytes"] != stored[d])
    print(f"[1] vendor files {len(entries)}, stored {len(stored)}; size differs on {len(days)} days ({days[0]}..{days[-1]})")
    print("[1] by year:", dict(sorted(Counter(d[:4] for d in days).items())))

    def work(day):
        try:
            new, new_cols = rows_of(vendor_file(entries[day]))
            with storage.get_object(Bucket=BUCKET, Key=f"{PREFIX}{day}.parquet")["Body"] as body:
                old, old_cols = rows_of(body.read())
            return day, new, old, new_cols, old_cols, None
        except Exception as error:  # report, never crash the whole run
            return day, None, None, None, None, str(error)[:120]

    series = defaultdict(list)        # symbol -> [(day, close_factor, spread, volume_factor)]
    one_sided = Counter()
    column_diffs = Counter()
    failures = []
    days_without_price_change = []
    changed_rows = []
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for day, new, old, new_cols, old_cols, error in pool.map(work, days):
            if error:
                failures.append((day, error))
                continue
            if new_cols != old_cols:
                column_diffs[(tuple(old_cols), tuple(new_cols))] += 1
            any_change = False
            for symbol in set(new) | set(old):
                if symbol not in new or symbol not in old:
                    one_sided[(symbol, "vendor only" if symbol in new else "stored only")] += 1
                    any_change = True
                    continue
                n, o = new[symbol], old[symbol]
                ratios = [a / b for a, b in zip(n[:4], o[:4]) if a and b]
                if len(ratios) < 4:
                    if n[:4] != o[:4]:
                        any_change = True
                    continue
                volume_factor = (n[4] / o[4]) if len(n) > 4 and len(o) > 4 and n[4] and o[4] else None
                factor = ratios[3]
                spread = max(ratios) - min(ratios)
                series[symbol].append((day, factor, spread, volume_factor))
                if abs(factor - 1) > NOISE or spread > NOISE or (volume_factor is not None and abs(volume_factor - 1) > NOISE):
                    any_change = True
                    changed_rows.append((symbol, day, *ratios, volume_factor))
            if not any_change:
                days_without_price_change.append(day)
    print(f"[2] days compared {len(days) - len(failures)}, download or read failures {len(failures)}: {failures[:10]}")
    print(f"[2] column differences (stored vs vendor): {dict(column_diffs) or 'none'}")
    print(f"[2] symbols present on only one side: {dict(one_sided) or 'none'}")
    print(f"[2] differing-size days where NO symbol's open/high/low/close/volume changed: {len(days_without_price_change)} {days_without_price_change[:10]}")

    changed_symbols = sorted({r[0] for r in changed_rows})
    print(f"[3] symbols with any changed bar: {len(changed_symbols)} of {len(series)} -> {changed_symbols}")
    print(f"[3] symbol-days changed: {dict(Counter(r[0] for r in changed_rows).most_common(20))}")
    worst = {s: max(sp for _, _, sp, _ in pts) for s, pts in series.items() if s in changed_symbols}
    print("[4] largest open/high/low/close ratio spread inside one bar, per changed symbol (about 0 = one factor per day):",
          {s: f"{v:.2e}" for s, v in worst.items()})
    volume_changed = {s: sum(1 for _, _, _, v in pts if v is not None and abs(v - 1) > NOISE) for s, pts in series.items() if s in changed_symbols}
    print("[4] days where volume changed, per changed symbol:", volume_changed)

    for symbol in changed_symbols:
        points = sorted(series[symbol])
        segments, current = [], None
        for day, factor, spread, _ in points:
            if current and abs(factor - current["start"]) <= SEGMENT_TOL:
                current["last"] = day
                current["factors"].append(factor)
            else:
                current = {"first": day, "last": day, "start": factor, "factors": [factor]}
                segments.append(current)
        print(f"[5] {symbol}: compared on {len(points)} days; factor segments (vendor/stored close):")
        previous = None
        for s in segments:
            f = s["factors"]
            step = "" if previous is None else f" step from previous segment {statistics.mean(f) / previous - 1:+.4%}"
            print(f"     {s['first']}..{s['last']} days={len(f)} factor mean {statistics.mean(f):.6f} min {min(f):.6f} max {max(f):.6f}{step}")
            previous = statistics.mean(f)

    with open("content_diff_days.csv", "w", newline="") as handle:
        w = csv.writer(handle)
        w.writerow(["symbol", "date", "open_factor", "high_factor", "low_factor", "close_factor", "volume_factor"])
        for row in sorted(changed_rows, key=lambda r: (r[0], r[1])):
            w.writerow([row[0], row[1], *[f"{x:.8f}" if x is not None else "" for x in row[2:]]])
    print(f"[6] wrote content_diff_days.csv with {len(changed_rows)} changed symbol-days")


if __name__ == "__main__":
    main()
