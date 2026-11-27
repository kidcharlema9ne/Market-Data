"""Add the newest vendor day(s) to the stitched futures table in R2 (incremental, idempotent, safe to run every 15 minutes).

Table: marketparquet/futures_current/futures_prices_current.parquet in bucket insider-research (built once by stitch_current_futures.py).
Each run:
 1. Reads the table and update_state.json (which vendor rolls were already applied; first run: rolls detected before the table was written).
 2. Applies any NEW roll from the vendor roll file: rows of that market with file_date <= roll_date are multiplied by the roll ratio
    (the same rule the stitch uses), so old days stay on the newest price level.
 3. Downloads the vendor's public file for each weekday after the table's newest day (up to the expected day) and appends it verbatim.
    If the expected day's file is not published yet the run ends quietly with ready=false; the next timer tick tries again.
 4. Safety check: a new day whose close is far outside that market's normal daily move is a possible price-level seam. Any such market
    stops the update (old table kept) unless FORCE_UPDATE=1.
 5. Saves a copy of the old table (futures_prices_current.prev.parquet), writes the new table and state. Writes updated=true/false and
    ready=true/false to $GITHUB_OUTPUT.
Env: R2_ENDPOINT_URL, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, MARKETPARQUET_API_KEY; optional FORCE_UPDATE.
"""
import json
import math
import os
import statistics
import sys
from datetime import date, timedelta
from io import BytesIO
from urllib.error import HTTPError, URLError
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
PRICE = ["open", "high", "low", "close"]
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


def seam_check(table, new_days):
    """Markets whose first new close is far outside their normal daily move versus the previous stored close."""
    flagged = []
    for sym, g in table.groupby("symbol"):
        g = g.sort_values("file_date")
        first_new = g[g["file_date"].isin(new_days)]
        if first_new.empty:
            continue
        prior = g[~g["file_date"].isin(new_days)]
        if len(prior) < 30:
            continue
        prev_close = float(prior["close"].iloc[-1])
        series = pd.concat([prior["close"], first_new["close"]]).astype(float).tolist()
        moves = [abs(math.log(b / a)) for a, b in zip(series[:-1], series[1:]) if a > 0 and b > 0]
        typical = statistics.median(moves[-61:-len(first_new)] or [0.01]) or 0.005
        worst = max(abs(math.log(float(c) / prev_close)) if i == 0 else abs(math.log(float(c) / float(first_new["close"].iloc[i - 1])))
                    for i, c in enumerate(first_new["close"]) if c > 0 and prev_close > 0)
        if worst > max(SEAM_FLOOR, SEAM_MULTIPLE * typical):
            flagged.append((sym, worst, typical))
    return flagged


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
    raw = obj["Body"].read()
    table = pq.read_table(BytesIO(raw)).to_pandas()
    table["file_date"] = pd.to_datetime(table["file_date"]).dt.strftime("%Y-%m-%d")
    last = table["file_date"].max()
    target = expected_day(now_et()).isoformat()
    print(f"table newest day {last}, expected day {target}")
    if last >= target:
        set_output(ready=True, updated=False)
        return

    # roll file
    code, body = http(f"{BASE}/api/v1/meta/futures_rolls", token)
    if code != 200:
        sys.exit(f"roll file unavailable (HTTP {code}); table left unchanged")
    url = json.loads(body)["download_url"]
    url = BASE + url if url.startswith("/") else url
    code, rraw = http(url, token if url.startswith(BASE) else None)
    if code != 200 or rraw[:4] != b"PAR1":
        sys.exit(f"roll file download failed (HTTP {code}); table left unchanged")
    rolls = pq.read_table(BytesIO(rraw)).to_pylist()
    try:
        state = json.loads(s3.get_object(Bucket=BUCKET, Key=STATE_KEY)["Body"].read())
        applied = set(state["applied"])
    except Exception:
        state = {}
        cutoff = pd.Timestamp(obj["LastModified"]).tz_convert("UTC")
        applied = {roll_key(r) for r in rolls if pd.Timestamp(r["detected_at"]).tz_convert("UTC") <= cutoff}
        print(f"first run: treating {len(applied)} rolls detected before {cutoff:%Y-%m-%d %H:%M} UTC as already applied")
    manual_rolls = state.get("manual_rolls", [])

    def done_by_hand(r):
        # a roll that apply_manual_fills.py already applied: same market, within 3 days after its last old day
        return any(m["root"] == r["root"] and 0 <= (date.fromisoformat(str(r["roll_date"])[:10]) - date.fromisoformat(m["last_old_day"])).days <= 3
                   for m in manual_rolls)
    new_rolls = [r for r in rolls if roll_key(r) not in applied and not done_by_hand(r)]
    print(f"new rolls to apply: {[(r['root'], r['roll_date'], round(float(r['ratio']), 5)) for r in new_rolls]}")

    # newest vendor days
    days, d, end = [], date.fromisoformat(last) + timedelta(days=1), date.fromisoformat(target)
    while d <= end:
        if d.weekday() < 5:
            days.append(d.isoformat())
        d += timedelta(days=1)
    add, got, missing = [], [], []
    for day in days:
        code, body = http(f"{BASE}/api/data/download/futures_daily/{day}.parquet")
        if code == 200 and body[:4] == b"PAR1":
            t = pq.read_table(BytesIO(body), columns=COLS).to_pandas()
            t["file_date"], t["rebase_factor"], t["source"] = day, 1.0, "vendor_public"
            add.append(t)
            got.append(day)
        else:
            missing.append(day)
    print(f"downloaded {got}; not available {missing}")
    ready = target in got
    if not got:
        set_output(ready=False, updated=False)
        return

    changed = apply_rolls(table, new_rolls)
    out = pd.concat([table] + [a[table.columns.intersection(a.columns)] for a in add], ignore_index=True)
    out = out.drop_duplicates(["symbol", "file_date"], keep="first").sort_values(["symbol", "file_date"]).reset_index(drop=True)
    flagged = seam_check(out, set(got))
    if flagged and os.environ.get("FORCE_UPDATE") != "1":
        for sym, worst, typical in flagged:
            print(f"POSSIBLE SEAM {sym}: one-day move {worst:.1%} versus typical {typical:.2%}", file=sys.stderr)
        sys.exit("price-level check failed; table left unchanged (rerun with force to override)")
    for sym, worst, typical in flagged:
        print(f"forced past check: {sym} {worst:.1%} vs typical {typical:.2%}")

    s3.copy_object(Bucket=BUCKET, Key=PREV_KEY, CopySource={"Bucket": BUCKET, "Key": KEY})
    buf = BytesIO()
    pq.write_table(pa.Table.from_pandas(out, preserve_index=False), buf)
    s3.put_object(Bucket=BUCKET, Key=KEY, Body=buf.getvalue())
    applied |= {roll_key(r) for r in new_rolls}
    s3.put_object(Bucket=BUCKET, Key=STATE_KEY, Body=json.dumps({"applied": sorted(applied), "manual_rolls": manual_rolls}).encode())
    print(f"updated: +{len(out) - len(table)} rows, {changed} old rows rebased, newest day {out['file_date'].max()}")
    set_output(ready=ready, updated=True)


if __name__ == "__main__":
    main()
