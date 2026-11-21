"""READ-ONLY probe: can the MarketParquet key fetch meta/futures_rolls, and how fresh is the R2 archive?

Safety: never prints the API key, headers or presigned URLs. R2 use is list/head only (no put, no delete).
Outputs: prints a report, writes roll_probe_report.json and (if fetched) futures_rolls.parquet.
"""
import json
import os
import sys
from collections import Counter
from datetime import datetime
from io import BytesIO
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BASE = "https://marketparquet.com"
ENDPOINT = BASE + "/api/v1/meta/futures_rolls"
BUCKET = "insider-research"
PREFIX = "marketparquet/futures_daily/"
report = {}


def call(url, headers):
    """Return (status, content_type, body_bytes). Never prints the URL."""
    request = Request(url, headers={"User-Agent": "insider-buying-research/1.0", **headers})
    try:
        with urlopen(request, timeout=90) as response:
            return response.status, response.headers.get("Content-Type", ""), response.read(60_000_000)
    except HTTPError as error:
        return error.code, error.headers.get("Content-Type", ""), error.read(20_000)
    except (URLError, TimeoutError) as error:
        return None, "", f"network failure: {type(error).__name__}".encode()


def redact(value):
    """Replace any URL-looking string so presigned links are never printed."""
    if isinstance(value, dict):
        return {k: redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value[:5]]
    if isinstance(value, str) and value.startswith(("http://", "https://", "/")):
        return "<url redacted>"
    return value


def roll_table():
    token = os.environ.get("MARKETPARQUET_API_KEY", "")
    if not token:
        raise SystemExit("MARKETPARQUET_API_KEY missing")
    status, ctype, body = call(ENDPOINT, {"Authorization": f"Bearer {token}"})
    report["step1_status"] = status
    report["step1_content_type"] = ctype
    print(f"[1] GET meta/futures_rolls -> HTTP {status}, content-type {ctype!r}, {len(body)} bytes")
    if status != 200:
        print("    body (first 300 chars, redacted):", body[:300].decode("utf8", "replace"))
        report["step1_body_head"] = body[:300].decode("utf8", "replace")
        return None
    if body[:4] == b"PAR1":
        print("    response is the Parquet file itself")
        return body
    try:
        meta = json.loads(body)
    except ValueError:
        print("    200 but body is not JSON or Parquet; head:", body[:200])
        return None
    print("    JSON keys:", sorted(meta) if isinstance(meta, dict) else type(meta).__name__)
    print("    JSON (urls redacted):", json.dumps(redact(meta))[:500])
    url = meta.get("download_url") or meta.get("url") if isinstance(meta, dict) else None
    if not url:
        print("    no download URL in the JSON, so no proof of access yet")
        return None
    if url.startswith("/"):
        url = BASE + url
    host = url.split("/")[2]
    # Send the key only if the link is on marketparquet.com itself; presigned links on other hosts get no auth.
    headers = {"Authorization": f"Bearer {token}"} if host.endswith("marketparquet.com") else {}
    status2, ctype2, data = call(url, headers)
    report["step2_status"] = status2
    report["step2_host_is_marketparquet"] = bool(headers)
    print(f"[2] follow download link -> HTTP {status2}, {len(data)} bytes, host is marketparquet.com: {bool(headers)}")
    if status2 != 200 or data[:4] != b"PAR1" or data[-4:] != b"PAR1":
        print("    NOT a valid Parquet file; head:", data[:120])
        return None
    return data


def analyse(data):
    import pyarrow.parquet as pq
    open("futures_rolls.parquet", "wb").write(data)
    table = pq.read_table(BytesIO(data))
    print(f"[3] Parquet rows={table.num_rows}")
    for name, typ in zip(table.schema.names, table.schema.types):
        print(f"    column {name}: {typ}")
    report["rows"] = table.num_rows
    report["columns"] = {n: str(t) for n, t in zip(table.schema.names, table.schema.types)}
    frame = table.to_pandas()
    print(frame.head(8).to_string())
    print(frame.tail(8).to_string())
    for col in ("roll_date", "detected_at"):
        if col in frame:
            print(f"    {col}: min {frame[col].min()}  max {frame[col].max()}")
            report[f"{col}_min"], report[f"{col}_max"] = str(frame[col].min()), str(frame[col].max())
    if "root" in frame:
        print(f"    distinct roots: {frame['root'].nunique()}; rolls per root (top 10):",
              Counter(frame["root"]).most_common(10))
    if "ratio" in frame:
        print("    ratio summary:", frame["ratio"].describe().to_dict())
    if "detected_at" in frame and "roll_date" in frame:
        gap = (frame["detected_at"].astype("datetime64[ns]") - frame["roll_date"].astype("datetime64[ns]")).dt.days
        print("    days from roll_date to detected_at:", gap.describe().to_dict())
    return frame


def archive_freshness():
    import boto3
    storage = boto3.client("s3", endpoint_url=os.environ["R2_ENDPOINT_URL"],
                           aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
                           aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"], region_name="auto")
    rows = []
    for page in storage.get_paginator("list_objects_v2").paginate(Bucket=BUCKET, Prefix=PREFIX):
        for obj in page.get("Contents", []):
            if obj["Key"].endswith(".parquet"):
                rows.append((obj["Key"][len(PREFIX):-8], obj["LastModified"]))
    rows.sort()
    print(f"[4] R2 archive: {len(rows)} files, file dates {rows[0][0]}..{rows[-1][0]} (list only, nothing written)")
    by_upload_day = Counter(modified.strftime("%Y-%m-%d") for _, modified in rows)
    print("    upload (LastModified) days, most files first:", by_upload_day.most_common(12))
    print("    earliest upload:", min(m for _, m in rows), " latest upload:", max(m for _, m in rows))
    report["r2_files"] = len(rows)
    report["r2_first_file_date"], report["r2_last_file_date"] = rows[0][0], rows[-1][0]
    report["r2_uploads_by_day"] = dict(by_upload_day.most_common(30))
    return dict(rows)


def staleness(frame, uploads):
    """A roll is 'newer than the archive' when the file for its roll_date was uploaded before the roll was detected."""
    if frame is None or "detected_at" not in frame or "roll_date" not in frame:
        return
    stale = []
    for rec in frame.itertuples():
        day = str(rec.roll_date)[:10]
        # nearest stored file on or after the roll date
        later = [d for d in uploads if d >= day]
        if not later:
            continue
        uploaded = uploads[min(later)]
        detected = datetime.fromisoformat(str(rec.detected_at)).replace(tzinfo=uploaded.tzinfo)
        if detected > uploaded:
            stale.append((rec.root, day, float(rec.ratio), str(rec.detected_at)[:19], uploaded.strftime("%Y-%m-%d %H:%M")))
    print(f"[5] rolls detected AFTER the stored file for that date was uploaded: {len(stale)} of {len(frame)}")
    for row in stale[:60]:
        print("    root={} roll_date={} ratio={:.6f} detected_at={} archive_file_uploaded={}".format(*row))
    report["rolls_newer_than_archive"] = len(stale)
    report["stale_roots"] = sorted({row[0] for row in stale})


if __name__ == "__main__":
    data = roll_table()
    frame = analyse(data) if data else None
    try:
        uploads = archive_freshness()
        staleness(frame, uploads)
    except Exception as error:  # report, never leak details
        print(f"R2 freshness step failed: {type(error).__name__}")
        report["r2_error"] = type(error).__name__
    json.dump(report, open("roll_probe_report.json", "w"), indent=2, default=str)
    print("conclusion:", "roll table ACCESSIBLE" if frame is not None else "roll table NOT proven accessible")
    sys.exit(0)
