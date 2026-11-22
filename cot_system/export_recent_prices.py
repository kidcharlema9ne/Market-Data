"""Export recent prices for the COT System report and print a coverage check.

Reads the MarketParquet archive in the R2 bucket (futures_daily and etf_daily), keeps the stand-in ETFs and all futures,
and writes two small files into the folder given as the first argument:
  futures_recent.csv.gz  (about 700 calendar days)
  etf_recent.csv.gz      (about 400 calendar days, only the stand-in ETFs)
Also asks MarketParquet (manifest only, no downloads) for the newest file it offers, so stale data is visible.
"""
import hashlib
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import date, timedelta
from io import BytesIO
from urllib.request import Request, urlopen

import pandas as pd
import pyarrow.parquet as pq

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from r2_storage import BUCKET, client  # noqa: E402

ETFS = ["TLT", "EDV", "IEF", "IEI", "SHY", "PPLT", "BNO", "UNG", "USO", "UGA", "CORN", "WEAT", "SOYB", "CANE", "BAL",
        "UUP", "VXX", "FXC", "FXF", "FXY", "FXE", "FXB", "FXA", "GLD", "SLV", "CPER"]
out_dir = sys.argv[1]
os.makedirs(out_dir, exist_ok=True)
storage = client()


def keys_for(asset, days):
    prefix = f"marketparquet/{asset}/"
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    pages = storage.get_paginator("list_objects_v2").paginate(Bucket=BUCKET, Prefix=prefix)
    allkeys = sorted(o["Key"] for p in pages for o in p.get("Contents", []) if o["Key"].endswith(".parquet"))
    print(f"{asset}: {len(allkeys)} files in R2, first {allkeys[0][len(prefix):-8]}, last {allkeys[-1][len(prefix):-8]}")
    return prefix, [k for k in allkeys if k[len(prefix):-8] >= cutoff]


def reader(prefix, only):
    def read(key):
        resp = storage.get_object(Bucket=BUCKET, Key=key)
        with closing(resp["Body"]) as body:
            raw = body.read()
        if hashlib.sha256(raw).hexdigest() != resp["Metadata"].get("verified-sha256"):
            raise RuntimeError(f"Unverified archive object {key}")
        df = pq.read_table(BytesIO(raw)).to_pandas()
        df = df[["symbol", "open", "high", "low", "close", "volume"]]
        if only:
            df = df[df["symbol"].isin(only)]
        df["file_date"] = key[len(prefix):-len(".parquet")]
        return df
    return read


def export_futures_current():
    """The stitched, price-level-consistent table built on 21 Nov (archive + roll ratios + free days + Yahoo/contract fills)."""
    key = "marketparquet/futures_current/futures_prices_current.parquet"
    resp = storage.get_object(Bucket=BUCKET, Key=key)
    raw = resp["Body"].read()
    if hashlib.sha256(raw).hexdigest() != resp["Metadata"].get("verified-sha256"):
        raise RuntimeError("stitched futures table failed its checksum")
    df = pq.read_table(BytesIO(raw)).to_pandas()
    print("stitched table columns:", list(df.columns))
    cutoff = (date.today() - timedelta(days=700)).isoformat()
    cols = [c for c in ("symbol", "file_date", "open", "high", "low", "close", "source", "rebase_factor") if c in df.columns]
    df = df[df["file_date"] >= cutoff][cols]
    df.to_csv(os.path.join(out_dir, "futures_recent.csv.gz"), index=False)
    print(f"futures_current: wrote futures_recent.csv.gz: {len(df)} rows, {df['symbol'].nunique()} symbols, last file date {df['file_date'].max()}")
    print(df.groupby("symbol")["file_date"].max().value_counts().head(5).to_string())


def yahoo_bars(symbol):
    req = Request(f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=2mo&interval=1d&events=div,split",
                  headers={"User-Agent": "Mozilla/5.0"})
    res = json.loads(urlopen(req, timeout=60).read())["chart"]["result"][0]
    off = res["meta"].get("gmtoffset", -18000)
    q = res["indicators"]["quote"][0]
    rows = []
    for i, t in enumerate(res["timestamp"]):
        vals = [q[k][i] for k in ("open", "high", "low", "close")]
        if None in vals:
            continue
        day = pd.Timestamp(t + off, unit="s").strftime("%Y-%m-%d")
        rows.append({"symbol": symbol, "file_date": day, "open": vals[0], "high": vals[1], "low": vals[2], "close": vals[3]})
    return pd.DataFrame(rows)


def fill_etfs(frame):
    """Add days newer than the archive: first MarketParquet's free daily files, then Yahoo (checked against the archive)."""
    last = frame["file_date"].max()
    parts = [frame]
    day = date.fromisoformat(last) + timedelta(days=1)
    free_days = []
    while day <= date.today():
        if day.weekday() < 5:
            try:
                data = urlopen(Request(f"https://marketparquet.com/api/data/download/etf_daily/{day}.parquet",
                                       headers={"User-Agent": "insider-buying-research/1.0"}), timeout=60).read()
                t = pq.read_table(BytesIO(data)).to_pandas()
                t = t[t["symbol"].isin(ETFS)][["symbol", "open", "high", "low", "close", "volume"]]
                t["file_date"] = str(day)
                parts.append(t)
                free_days.append(str(day))
            except Exception:
                pass
        day += timedelta(days=1)
    print("ETF days added from MarketParquet free files:", free_days or "none")
    frame = pd.concat(parts, ignore_index=True)
    have = frame.groupby("symbol")["file_date"].apply(set)
    out = [frame]
    for sym in ETFS:
        try:
            yb = yahoo_bars(sym)
        except Exception as e:
            print(f"Yahoo {sym}: failed ({e})")
            continue
        if yb.empty:
            print(f"Yahoo {sym}: no bars")
            continue
        mine = have.get(sym, set())
        both = yb[yb["file_date"].isin(mine)]
        if len(both) >= 3:
            ref = frame[frame["symbol"] == sym].set_index("file_date")["close"]
            ratio = (both.set_index("file_date")["close"] / ref.reindex(both["file_date"]).values).dropna()
            if ratio.empty or (ratio - 1).abs().max() > 0.005:
                print(f"Yahoo {sym}: does not match MarketParquet on overlap days (max gap {((ratio - 1).abs().max() if len(ratio) else 'n/a')}); not used")
                continue
            tag = "matched"
        else:
            tag = "no overlap with archive (BAL-type)"
        new = yb[~yb["file_date"].isin(mine)].copy()
        new["volume"] = float("nan")
        if len(new):
            out.append(new)
            print(f"Yahoo {sym}: added {len(new)} days ({new['file_date'].min()}..{new['file_date'].max()}), {tag}")
    return pd.concat(out, ignore_index=True).sort_values(["symbol", "file_date"])


export_futures_current()
for asset, days, only, name in (("etf_daily", 400, ETFS, "etf_recent.csv.gz"),):
    prefix, keys = keys_for(asset, days)
    with ThreadPoolExecutor(max_workers=8) as pool:
        frame = pd.concat(list(pool.map(reader(prefix, only), keys)), ignore_index=True)
    if asset == "etf_daily":
        frame = fill_etfs(frame)
    frame.to_csv(os.path.join(out_dir, name), index=False)
    print(f"{asset}: wrote {name}: {len(frame)} rows, {frame['symbol'].nunique()} symbols, last file date {frame['file_date'].max()}")
    if only:
        last = frame.groupby("symbol")["file_date"].agg(["min", "max", "count"])
        print(last.to_string())
        print("stand-ins missing from the archive:", sorted(set(only) - set(frame["symbol"])) or "none")

# What does MarketParquet itself offer right now? (manifest only)
token = os.environ.get("MARKETPARQUET_API_KEY", "")
start = (date.today() - timedelta(days=45)).isoformat()
for asset in ("etf_daily",):
    req = Request(f"https://marketparquet.com/api/v1/manifest/{asset}?start={start}&end={date.today().isoformat()}",
                  headers={"Authorization": f"Bearer {token}", "User-Agent": "insider-buying-research/1.0"})
    try:
        m = json.loads(urlopen(req, timeout=60).read())
        dates = sorted(f["date"] for f in m.get("files") or [])
        print(f"vendor manifest {asset}: plan={m.get('plan')!r} newest {dates[-1] if dates else None}; last 5: {dates[-5:]}")
    except Exception as e:
        print(f"vendor manifest {asset}: failed ({e})")
