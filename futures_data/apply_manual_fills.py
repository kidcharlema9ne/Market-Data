"""One-off repairs to the stitched futures table in R2 (idempotent): (1) add hand-checked daily bars from futures_data/manual_fills.csv,
(2) apply a price-level roll from futures_data/manual_rolls.csv that the vendor's roll file did not list.

Why: the vendor's free window missed 2026-11-09..13 and Yahoo does not carry SR3 or SR1, so both had a 5-day hole that made the report
refuse to score them. The bars come from the CME contract the vendor series follows (matched to the vendor's own numbers on the days both
exist). On 2026-11-23 the vendor's SR1 series also jumped from the Dec 2026 to the Mar 2027 contract (-0.325 points) with no adjustment;
the older rows are multiplied by the contract ratio, the same rule daily_update.py uses (rows with file_date <= last old day).
Safety: only adds missing (symbol, file_date) rows; fill closes must be within 1 percent of the previous stored close; after the roll the
move across it must be under 0.5 percent; the old table is copied to futures_prices_current.before-manual-fill.parquet first; the roll is
recorded under manual_rolls in update_state.json so it is never applied twice (daily_update.py skips a vendor roll for the same market
within 3 days of it). Writes updated=true/false to $GITHUB_OUTPUT.
Env: R2_ENDPOINT_URL, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, MARKETPARQUET_API_KEY (to look for the vendor's own ratio).
"""
import json
import os
import sys
from datetime import date
from io import BytesIO

import boto3
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from daily_update import BASE, STATE_KEY, apply_rolls, http, roll_key  # noqa: E402

BUCKET = "insider-research"
KEY = "marketparquet/futures_current/futures_prices_current.parquet"
BACKUP_KEY = "marketparquet/futures_current/futures_prices_current.before-manual-fill.parquet"
HERE = os.path.dirname(os.path.abspath(__file__))


def set_output(**kv):
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        open(path, "a").write("".join(f"{k}={str(v).lower()}\n" for k, v in kv.items()))


def vendor_roll(root, last_old_day):
    """The vendor's own roll for this market within 3 days after the last old day, or None."""
    token = os.environ.get("MARKETPARQUET_API_KEY")
    if not token:
        return None
    code, body = http(f"{BASE}/api/v1/meta/futures_rolls", token)
    if code != 200:
        return None
    url = json.loads(body)["download_url"]
    url = BASE + url if url.startswith("/") else url
    code, raw = http(url, token if url.startswith(BASE) else None)
    if code != 200 or raw[:4] != b"PAR1":
        return None
    for r in pq.read_table(BytesIO(raw)).to_pylist():
        gap = (date.fromisoformat(str(r["roll_date"])[:10]) - date.fromisoformat(last_old_day)).days
        if r["root"] == root and 0 <= gap <= 3:
            return r
    return None


def main():
    s3 = boto3.client("s3", endpoint_url=os.environ["R2_ENDPOINT_URL"], aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
                      aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"], region_name="auto")
    table = pq.read_table(BytesIO(s3.get_object(Bucket=BUCKET, Key=KEY)["Body"].read())).to_pandas()
    table["file_date"] = pd.to_datetime(table["file_date"]).dt.strftime("%Y-%m-%d")
    try:
        state = json.loads(s3.get_object(Bucket=BUCKET, Key=STATE_KEY)["Body"].read())
    except Exception as exc:
        sys.exit(f"update_state.json unreadable ({exc}); refusing to guess which rolls were applied; nothing written")
    manual = list(state.get("manual_rolls", []))
    changed = False

    # 1. fills
    fills = pd.read_csv(os.path.join(HERE, "manual_fills.csv"), dtype={"file_date": str})
    have = set(zip(table["symbol"], table["file_date"]))
    new = fills[[(s, d) not in have for s, d in zip(fills["symbol"], fills["file_date"])]].copy()
    print(f"{len(fills)} fill rows in the file, {len(new)} not yet in the table")
    for r in new.itertuples(index=False):
        prev = table[(table["symbol"] == r.symbol) & (table["file_date"] < r.file_date)].sort_values("file_date").tail(1)
        if prev.empty or abs(r.close / float(prev["close"].iloc[0]) - 1) > 0.01:
            sys.exit(f"{r.symbol} {r.file_date}: close {r.close} is over 1 percent from the previous stored close; nothing written")
        if not (r.low <= min(r.open, r.close) and r.high >= max(r.open, r.close)):
            sys.exit(f"{r.symbol} {r.file_date}: open/high/low/close inconsistent; nothing written")
    if len(new):
        add = new[[c for c in table.columns if c in new.columns]]
        table = pd.concat([table, add], ignore_index=True).sort_values(["symbol", "file_date"]).reset_index(drop=True)
        changed = True

    # 2. rolls
    applied_keys = set(state.get("applied", []))
    for m in pd.read_csv(os.path.join(HERE, "manual_rolls.csv"), dtype={"last_old_day": str}).itertuples(index=False):
        if any(x["root"] == m.root and x["last_old_day"] == m.last_old_day for x in manual):
            print(f"roll {m.root} {m.last_old_day} already applied by an earlier manual run; skipping")
            continue
        vr = vendor_roll(m.root, m.last_old_day)
        if vr is not None:
            ratio = float(vr["ratio"])
            applied_keys.add(roll_key(vr))
            print(f"using the vendor's own roll: {vr['roll_date']} ratio {ratio:.6f} (my estimate was {m.ratio})")
        else:
            ratio = float(m.ratio)
            print(f"vendor roll file has no {m.root} roll near {m.last_old_day}; using ratio {ratio:.8f}")
        g = table[table["symbol"] == m.root].sort_values("file_date")
        before = g[g["file_date"] > m.last_old_day]
        if before.empty:
            sys.exit(f"{m.root}: no rows after {m.last_old_day}; cannot check the roll; nothing written")
        n = apply_rolls(table, [dict(root=m.root, roll_date=m.last_old_day, ratio=ratio)])
        g = table[table["symbol"] == m.root].sort_values("file_date")
        last_old = float(g[g["file_date"] <= m.last_old_day]["close"].iloc[-1])
        first_new = float(before["close"].iloc[0])
        move = abs(first_new / last_old - 1)
        print(f"{m.root}: {n} rows scaled by {ratio:.8f}; close across the roll {last_old:.4f} -> {first_new:.4f} ({move:.3%})")
        if move > 0.005:
            sys.exit(f"{m.root}: move across the roll is still {move:.2%} after adjusting; nothing written")
        manual.append(dict(root=m.root, last_old_day=m.last_old_day, ratio=ratio, source="vendor" if vr is not None else "ibkr"))
        changed = True

    if not changed:
        set_output(updated=False)
        return
    s3.copy_object(Bucket=BUCKET, Key=BACKUP_KEY, CopySource={"Bucket": BUCKET, "Key": KEY})
    buf = BytesIO()
    pq.write_table(pa.Table.from_pandas(table, preserve_index=False), buf)
    s3.put_object(Bucket=BUCKET, Key=KEY, Body=buf.getvalue())
    state.update(applied=sorted(applied_keys), manual_rolls=manual)
    s3.put_object(Bucket=BUCKET, Key=STATE_KEY, Body=json.dumps(state).encode())
    print(f"written; backup at {BACKUP_KEY}")
    set_output(updated=True)


if __name__ == "__main__":
    main()
