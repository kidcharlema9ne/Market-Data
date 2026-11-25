"""Add the newest vendor day(s) to the stitched futures table in R2 (incremental, idempotent, safe to run every 15 minutes).

Table: marketparquet/futures_current/futures_prices_current.parquet in bucket insider-research (built once by stitch_current_futures.py).
Each run:
 1. Reads the table and update_state.json (which vendor rolls were already applied; first run: rolls detected before the table was written).
 2. Looks for missing weekdays and bars for active symbols over the last 30 calendar days, and for all weekdays after the latest stored day.
    Retries for older missing sessions even after a newer one arrives. A weekday with no vendor file is left alone.
 3. Downloads the vendor roll file. Applies new ratios to existing market bars through each roll date, then adds only missing vendor bars.
    The vendor's published daily files are already on its current roll-adjusted basis.
 4. Checks price continuity on both sides of newly inserted bars. A possible price-level seam stops the update unless FORCE_UPDATE=1.
 5. Backs up the old table and writes the new one with its applied-roll list in the same object. Requests an export again if the
    public recent file is missing rows already present in R2.
Env: R2_ENDPOINT_URL, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, MARKETPARQUET_API_KEY; optional FORCE_UPDATE.
"""
import hashlib
import json
import math
import os
import statistics
import sys
from datetime import date, timedelta
from io import BytesIO
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from trading_days import expected_day, now_et  # noqa: E402

BASE = "https://marketparquet.com"
BUCKET = "insider-research"
KEY = "marketparquet/futures_current/futures_prices_current.parquet"
PREV_KEY = "marketparquet/futures_current/futures_prices_current.prev.parquet"
STATE_KEY = "marketparquet/futures_current/update_state.json"
COLS = ["symbol", "open", "high", "low", "close", "volume"]
BAR_KEY = ["symbol", "file_date"]
PRICE = ["open", "high", "low", "close"]
BACKFILL_DAYS = 30
RECENT_FILE = "prices/futures_recent.csv.gz"
ROLL_METADATA = b"marketparquet_applied_rolls"
SEAM_FLOOR = 0.15      # a one-day move under 15 percent is never flagged
SEAM_MULTIPLE = 8.0    # and a flagged move must also exceed this many times the market's typical daily move


def http(url, token=None):
    headers = {"User-Agent": "Market-Data/1.0"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        with urlopen(Request(url, headers=headers), timeout=90) as r:
            return r.status, r.read(120_000_000)
    except HTTPError as e:
        return e.code, b""
    except (URLError, TimeoutError, OSError):
        return 0, b""


def roll_key(r):
    return f"{r['root']}|{r['roll_date']}|{float(r['ratio']):.10f}"


def apply_rolls(table, rolls):
    """Multiply the price columns of rows with file_date <= roll_date, per market. Returns the number of rows changed."""
    changed = 0
    for r in rolls:
        mask = (table["symbol"] == r["root"]) & (table["file_date"] <= r["roll_date"])
        n = int(mask.sum())
        if n:
            table.loc[mask, PRICE] = table.loc[mask, PRICE] * float(r["ratio"])
            table.loc[mask, "rebase_factor"] = table.loc[mask, "rebase_factor"] * float(r["ratio"])
            changed += n
    return changed


def candidate_days(table, target):
    """Find weekdays that may have missing bars, including gaps inside the current table."""
    latest = table["file_date"].max()
    recent = sorted(table["file_date"].unique())[-5:]
    active = table[table["file_date"].isin(recent)].groupby("symbol")["file_date"].nunique()
    active = set(active[active >= min(3, len(recent))].index)
    start = max(date.fromisoformat(table["file_date"].min()),
                min(date.fromisoformat(latest) + timedelta(days=1), target - timedelta(days=BACKFILL_DAYS - 1)))
    dates = table[table["file_date"] >= start.isoformat()].groupby("file_date")["symbol"].agg(set)
    days = {}
    for offset in range((target - start).days + 1):
        day = start + timedelta(days=offset)
        if day.weekday() < 5:
            day = day.isoformat()
            missing = active - dates.get(day, set())
            if missing:
                days[day] = missing
    return days


def missing_bars(table, vendor):
    """Select vendor bars whose market and session date are absent from the stored table."""
    observed = pd.MultiIndex.from_frame(table[BAR_KEY])
    return vendor.loc[~pd.MultiIndex.from_frame(vendor[BAR_KEY]).isin(observed)]


def vendor_bars(body, day):
    parquet = pq.ParquetFile(BytesIO(body))
    date_field = "date" if "date" in parquet.schema_arrow.names else "timestamp"
    bars = parquet.read(columns=[*COLS, date_field]).to_pandas()
    session = date.fromisoformat(day)
    oldest_stamp = (session - timedelta(days=3)).isoformat()
    stamps = bars.pop(date_field).astype(str).str[:10]
    # A daily bar may be stamped at the prior evening's session open.
    if bars.empty or not stamps.between(oldest_stamp, day).all():
        sys.exit(f"vendor file {day} has unexpected bar dates; table left unchanged")
    bars["file_date"], bars["rebase_factor"], bars["source"] = day, 1.0, "vendor_public"
    if bars["symbol"].isna().any() or bars.duplicated(BAR_KEY).any():
        sys.exit(f"vendor file {day} has missing or duplicate symbols; table left unchanged")
    return bars


def seam_check(table, added):
    """Check each close-to-close move touching a new bar against the market's usual moves."""
    flagged = []
    new_keys = pd.MultiIndex.from_frame(added[BAR_KEY])
    affected = table[table["symbol"].isin(added["symbol"])]
    for sym, g in affected.groupby("symbol"):
        g = g.sort_values("file_date")
        is_new = pd.MultiIndex.from_frame(g[BAR_KEY]).isin(new_keys)
        if (~is_new).sum() < 30:
            continue
        closes = g["close"].astype(float).tolist()
        moves = [abs(math.log(b / a)) if a > 0 and b > 0 else None for a, b in zip(closes, closes[1:])]
        touches_new = is_new[:-1] | is_new[1:]
        new_moves = [move for move, touches in zip(moves, touches_new) if touches and move is not None]
        if not new_moves:
            continue
        old_moves = [move for move, touches in zip(moves, touches_new) if not touches and move is not None]
        typical = statistics.median(old_moves[-60:] or [0.01]) or 0.005
        worst = max(new_moves)
        if worst > max(SEAM_FLOOR, SEAM_MULTIPLE * typical):
            flagged.append((sym, worst, typical))
    return flagged


def applied_rolls(s3, parquet, last_modified, rolls):
    metadata = parquet.schema.metadata or {}
    if ROLL_METADATA in metadata:
        return set(json.loads(metadata[ROLL_METADATA]))
    try:
        legacy = s3.get_object(Bucket=BUCKET, Key=STATE_KEY)
    except s3.exceptions.NoSuchKey:
        cutoff = pd.Timestamp(last_modified).tz_convert("UTC")
        applied = {roll_key(r) for r in rolls if pd.Timestamp(r["detected_at"]).tz_convert("UTC") <= cutoff}
        print(f"first run: treating {len(applied)} rolls detected before {cutoff:%Y-%m-%d %H:%M} UTC as already applied")
        return applied
    return set(json.loads(legacy["Body"].read())["applied"])


def public_export_is_behind(table, target):
    """Retry publishing if an earlier run updated R2 but did not commit the corresponding prices."""
    cutoff = (target - timedelta(days=BACKFILL_DAYS - 1)).isoformat()
    try:
        published = pd.read_csv(RECENT_FILE, usecols=BAR_KEY, dtype=str)
    except (OSError, ValueError):
        return True
    return not missing_bars(published, table[table["file_date"] >= cutoff]).empty


def set_output(**kv):
    path = os.environ.get("GITHUB_OUTPUT")
    lines = "".join(f"{k}={str(v).lower()}\n" for k, v in kv.items())
    print(lines.strip())
    if path:
        open(path, "a").write(lines)


def main():
    import boto3
    s3 = boto3.client("s3", endpoint_url=os.environ["R2_ENDPOINT_URL"], aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
                      aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"], region_name="auto")
    token = os.environ["MARKETPARQUET_API_KEY"]
    obj = s3.get_object(Bucket=BUCKET, Key=KEY)
    parquet = pq.read_table(BytesIO(obj["Body"].read()))
    table = parquet.to_pandas()
    table["file_date"] = pd.to_datetime(table["file_date"]).dt.strftime("%Y-%m-%d")
    last = table["file_date"].max()
    target = expected_day(now_et())
    target_day = target.isoformat()
    print(f"table newest day {last}, expected day {target_day}")
    candidates = candidate_days(table, target)
    if not candidates:
        set_output(ready=True, updated=public_export_is_behind(table, target))
        return

    # Fetch rolls before daily files so the backfill bars and stored table use the latest available roll basis.
    # roll file
    code, body = http(f"{BASE}/api/v1/meta/futures_rolls", token)
    if code != 200:
        sys.exit(f"roll file unavailable (HTTP {code}); table left unchanged")
    url = urljoin(BASE, json.loads(body)["download_url"])
    download = urlsplit(url)
    code, rraw = http(url, token if (download.scheme, download.netloc) == ("https", urlsplit(BASE).netloc) else None)
    if code != 200 or rraw[:4] != b"PAR1":
        sys.exit(f"roll file download failed (HTTP {code}); table left unchanged")
    rolls = pq.read_table(BytesIO(rraw)).to_pylist()
    applied = applied_rolls(s3, parquet, obj["LastModified"], rolls)
    new_rolls = [r for r in rolls if roll_key(r) not in applied]
    print(f"new rolls to apply: {[(r['root'], r['roll_date'], round(float(r['ratio']), 5)) for r in new_rolls]}")

    # newest vendor days
    additions, unavailable = [], {}
    for day, expected_symbols in candidates.items():
        code, body = http(f"{BASE}/api/data/download/futures_daily/{day}.parquet")
        if code != 200 or body[:4] != b"PAR1":
            unavailable[day] = code
            continue
        vendor = vendor_bars(body, day)
        new = missing_bars(table, vendor)
        if not new.empty:
            additions.append(new)
        unresolved = expected_symbols - set(vendor["symbol"])
        print(f"{day}: {len(new)} missing bars available, {len(unresolved)} expected symbols still missing")
    if unavailable:
        print(f"vendor files unavailable (date: HTTP status): {unavailable}")
    if not additions:
        set_output(ready=target_day not in candidates, updated=public_export_is_behind(table, target))
        return

    changed = apply_rolls(table, new_rolls)
    added = pd.concat(additions, ignore_index=True)
    out = pd.concat([table, added], ignore_index=True).sort_values(BAR_KEY).reset_index(drop=True)
    flagged = seam_check(out, added)
    if flagged and os.environ.get("FORCE_UPDATE") != "1":
        for sym, worst, typical in flagged:
            print(f"POSSIBLE SEAM {sym}: one-day move {worst:.1%} versus typical {typical:.2%}", file=sys.stderr)
        sys.exit("price-level check failed; table left unchanged (rerun with force to override)")
    for sym, worst, typical in flagged:
        print(f"forced past check: {sym} {worst:.1%} vs typical {typical:.2%}")

    s3.copy_object(Bucket=BUCKET, Key=PREV_KEY, CopySource={"Bucket": BUCKET, "Key": KEY})
    applied |= {roll_key(r) for r in new_rolls}
    revised = pa.Table.from_pandas(out, preserve_index=False)
    metadata = {**(revised.schema.metadata or {}), ROLL_METADATA: json.dumps(sorted(applied)).encode()}
    buf = BytesIO()
    pq.write_table(revised.replace_schema_metadata(metadata), buf)
    body = buf.getvalue()
    s3.put_object(Bucket=BUCKET, Key=KEY, Body=body, Metadata={"verified-sha256": hashlib.sha256(body).hexdigest()})
    print(f"updated: +{len(out) - len(table)} rows, {changed} old rows rebased, newest day {out['file_date'].max()}")
    set_output(ready=target_day not in candidate_days(out, target), updated=True)


if __name__ == "__main__":
    main()
