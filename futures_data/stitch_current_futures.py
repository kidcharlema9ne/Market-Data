"""Stitch the R2 futures archive and the newest days into ONE price-level-consistent table, using the vendor's roll file.

Why: MarketParquet's series are ratio back-adjusted. At each roll the whole earlier series is multiplied by the roll ratio, so
a file downloaded BEFORE a roll was recorded sits on the old price level. The roll file (root, roll_date, ratio, detected_at)
lets us apply the missing ratios. Rule used here (a hypothesis that the report then tests):
    a stored file for day d and market m is multiplied by the ratio of every roll of m with roll_date >= d that was detected
    AFTER that file was written to R2 (R2 LastModified < detected_at).
Then appended: the vendor's public files for 2026-11-16..20 (verbatim, all symbols) and, only where the market needed no rebasing
of its newest stored days, the Yahoo-filled days 2026-11-09..13 from marketparquet/futures_daily_current/.
Outputs: futures_prices_current.parquet (also uploaded to R2 at marketparquet/futures_current/futures_prices_current.parquet) and
futures_data/current_stitch_report.md. The original archive is never modified.
"""
import csv
import datetime as dt
import hashlib
import json
import math
import os
import statistics
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from io import BytesIO
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import boto3
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

BASE = "https://marketparquet.com"
BUCKET, MAIN, CUR = "insider-research", "marketparquet/futures_daily/", "marketparquet/futures_daily_current/"
FINAL_KEY = "marketparquet/futures_current/futures_prices_current.parquet"
RENAME = {"6A": "A6", "6B": "B6", "6C": "AD", "6E": "E6", "6J": "J1", "6L": "BR", "6M": "MP",
          "6N": "N6", "6S": "E1", "ZB": "US", "BRR": "BTC", "LBR": "LBS"}
AFTER = ["2026-11-16", "2026-11-17", "2026-11-18", "2026-11-19", "2026-11-20"]
GAP = ["2026-11-09", "2026-11-10", "2026-11-11", "2026-11-12", "2026-11-13"]
COLS = ["symbol", "open", "high", "low", "close", "volume"]
token = os.environ["MARKETPARQUET_API_KEY"]
s3 = boto3.client("s3", endpoint_url=os.environ["R2_ENDPOINT_URL"], aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
                  aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"], region_name="auto")


def http(url, auth):
    h = {"User-Agent": "insider-buying-research/1.0"}
    if auth:
        h["Authorization"] = f"Bearer {token}"
    try:
        with urlopen(Request(url, headers=h), timeout=90) as r:
            return r.status, r.read(80_000_000)
    except HTTPError as e:
        return e.code, e.read(300)
    except URLError as e:
        return 0, str(e).encode()


# --- roll file
code, body = http(f"{BASE}/api/v1/meta/futures_rolls", True)
meta = json.loads(body)
du = meta["download_url"]
du = BASE + du if du.startswith("/") else du
code, raw = http(du, du.startswith(BASE))
assert raw[:4] == b"PAR1", "roll file not parquet"
rolls = pq.read_table(BytesIO(raw)).to_pylist()
for r in rolls:
    r["detected"] = pd.Timestamp(r["detected_at"]).tz_convert("UTC")
by_root = {}
for r in rolls:
    by_root.setdefault(r["root"], []).append(r)

# --- stored archive with write times
objs = []
for p in s3.get_paginator("list_objects_v2").paginate(Bucket=BUCKET, Prefix=MAIN):
    for o in p.get("Contents", []):
        if o["Key"].endswith(".parquet"):
            objs.append((o["Key"][len(MAIN):-8], o["Key"], pd.Timestamp(o["LastModified"]).tz_convert("UTC")))
objs.sort()


def read(item):
    day, key, lm = item
    resp = s3.get_object(Bucket=BUCKET, Key=key)
    with closing(resp["Body"]) as b:
        data = b.read()
    if hashlib.sha256(data).hexdigest() != resp["Metadata"].get("verified-sha256"):
        raise RuntimeError(f"unverified {key}")
    df = pq.read_table(BytesIO(data), columns=COLS).to_pandas()
    df["file_date"] = day
    df["lastmod"] = lm
    return df


with ThreadPoolExecutor(max_workers=8) as pool:
    df = pd.concat(list(pool.map(read, objs)), ignore_index=True)
print("stored rows", len(df), "files", len(objs), flush=True)
lm_days = pd.Series([o[2].strftime("%Y-%m-%d") for o in objs]).value_counts().sort_index()

# --- rebase rule
df["rebase_factor"] = 1.0
for root, rs in by_root.items():
    m_root = df["symbol"] == root
    if not m_root.any():
        continue
    for r in rs:
        mask = m_root & (df["file_date"] <= r["roll_date"]) & (df["lastmod"] < r["detected"])
        df.loc[mask, "rebase_factor"] *= r["ratio"]
for c in ("open", "high", "low", "close"):
    df[c] = df[c] * df["rebase_factor"]
df["source"] = "vendor_archive"
last_stored = df["file_date"].max()

# --- newest vendor public days (verbatim)
add = []
for d in AFTER:
    code, body = http(f"{BASE}/api/data/download/futures_daily/{d}.parquet", False)
    if code != 200 or body[:4] != b"PAR1":
        raise SystemExit(f"vendor public file {d} unavailable (HTTP {code})")
    t = pq.read_table(BytesIO(body), columns=COLS).to_pandas()
    t["file_date"], t["rebase_factor"], t["source"] = d, 1.0, "vendor_public"
    add.append(t)
# --- Yahoo gap days (only where the newest stored days needed no rebasing)
need = df[df["file_date"] == last_stored].set_index("symbol")["rebase_factor"]
for d in GAP:
    try:
        body = s3.get_object(Bucket=BUCKET, Key=f"{CUR}{d}.parquet")["Body"].read()
    except Exception:
        continue
    t = pq.read_table(BytesIO(body)).to_pandas()
    t = t[t["source"].str.startswith("yahoo")]
    t = t[t["symbol"].map(lambda s: abs(need.get(s, 1.0) - 1.0) < 1e-9)]
    t = t[COLS + ["source"]].copy()
    t["file_date"], t["rebase_factor"] = d, 1.0
    add.append(t)
# contract-level fill (futures_data/contract_fill.py): individual contract prices x the vendor's roll ratios, matched to the vendor's known days
if os.path.exists("futures_data/contract_fill_candidates.csv"):
    cf = pd.read_csv("futures_data/contract_fill_candidates.csv")
    if len(cf):
        cf = cf.rename(columns={"date": "file_date"})
        cf["rebase_factor"] = 1.0
        keys = set(zip(cf["symbol"], cf["file_date"]))
        add = [a[~a.apply(lambda r: (r["symbol"], r["file_date"]) in keys, axis=1)] if "source" in a.columns and a["source"].astype(str).str.startswith("yahoo").any() else a for a in add]
        add.append(cf[COLS + ["file_date", "rebase_factor", "source"]])
out = pd.concat([df.drop(columns=["lastmod"])] + add, ignore_index=True).sort_values(["symbol", "file_date"])
out.to_parquet("futures_prices_current.parquet", index=False)
raw_out = open("futures_prices_current.parquet", "rb").read()
s3.put_object(Bucket=BUCKET, Key=FINAL_KEY, Body=raw_out, Metadata={"verified-sha256": hashlib.sha256(raw_out).hexdigest()})

# --- report
u = list(csv.DictReader(open("futures_data/report_universe_48_markets.csv")))
syms = {RENAME.get(x["ibkr"], x["ibkr"]): x["ibkr"] for x in u}
rep = ["# Stitched current futures (rebased with the vendor roll file)", "",
       f"Stored files: {len(objs)}; R2 write times {objs[0][2]:%Y-%m-%d} .. {objs[-1][2]:%Y-%m-%d}; newest stored day {last_stored}.",
       f"Roll file: {len(rolls)} rolls, {min(r['roll_date'] for r in rolls)} .. {max(r['roll_date'] for r in rolls)}.",
       "", "Stored-file write dates (count of files written per day, last 25 write days):", ""]
rep += [f"- {k}: {v}" for k, v in lm_days.tail(25).items()]
rep += ["", "## Rolls after the newest stored day, per market, and the factor applied to its newest stored day", "",
        "| market | roll date | ratio | detected | files already written after detection | factor on newest stored day |", "|---|---|---|---|---|---|"]
for ps, ib in syms.items():
    for r in sorted(by_root.get(ps, []), key=lambda r: r["roll_date"]):
        if r["roll_date"] > last_stored:
            sub = df[(df["symbol"] == ps) & (df["file_date"] >= (pd.Timestamp(last_stored) - pd.Timedelta(days=10)).strftime("%Y-%m-%d"))]
            frac = (sub["lastmod"] >= r["detected"]).mean() if len(sub) else float("nan")
            f = float(need.get(ps, 1.0))
            rep.append(f"| {ib} ({ps}) | {r['roll_date']} | {r['ratio']:.4f} | {r['detected_at'][:16]} | {frac:.0%} | {f:.4f} |")
rep += ["", "## Seam check at rolls already inside the stored data (after rebasing)", "",
        "return = ln(next day close / roll day close) in the stitched series; a seam shows as return close to ln(ratio) with |ln(ratio)| well above the market's typical daily move.", "",
        "| market | roll date | ln(ratio) | return across roll | typical daily move | verdict |", "|---|---|---|---|---|---|"]
bad = 0
for ps, ib in syms.items():
    g = out[(out["symbol"] == ps)].set_index("file_date")["close"]
    for r in sorted(by_root.get(ps, []), key=lambda r: r["roll_date"]):
        d = r["roll_date"]
        if d not in g.index or d >= last_stored:
            continue
        nxt = g.index[g.index.get_loc(d) + 1]
        ret = math.log(g[nxt] / g[d])
        prior = g.loc[:d].tail(61)
        typ = statistics.median(abs(math.log(b / a)) for a, b in zip(prior.values[:-1], prior.values[1:])) or 1e-6
        lr = math.log(r["ratio"])
        seam = abs(lr) > 3 * typ and abs(ret - lr) < abs(ret) * 0.5 and abs(ret) > 2.5 * typ
        bad += seam
        rep.append(f"| {ib} | {d} | {lr:+.3%} | {ret:+.3%} | {typ:.3%} | {'POSSIBLE SEAM' if seam else 'ok'} |")
rep += ["", f"Possible seams at past rolls: {bad}.", "", "## Final series per market", "",
        "| market | last day | last source | rebased days | days across gap 11-06 to 11-16 |", "|---|---|---|---|---|"]
for ps, ib in syms.items():
    g = out[out["symbol"] == ps]
    rb = int((g["rebase_factor"] != 1.0).sum())
    ds = g["file_date"]
    gap_days = int(((ds > last_stored) & (ds < "2026-11-16")).sum())
    rep.append(f"| {ib} ({ps}) | {ds.max()} | {g.iloc[-1]['source']} | {rb} | {gap_days} of 5 |")
text = "\n".join(rep)
open("futures_data/current_stitch_report.md", "w").write(text + "\n")
print(text)
