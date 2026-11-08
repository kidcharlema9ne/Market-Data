"""Build daily entry-to-exit ATR outcomes from the stored futures archive."""
import hashlib
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import date
from io import BytesIO
from pathlib import Path

import os

import boto3
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from botocore.config import Config

from r2_storage import BUCKET

PREFIX = "marketparquet/futures_daily/"
ROOTS = set("""HG CT SI ZW HO PL ZL E6 NG US E1 SR1 MNQ A6 HE MP LE N6 KE ZN GC SR3 CL
ZF ZC GF KC BR ES VX UB ZS BZ ZM ZQ RB CC B6 DX YM ZT TN RTY AD SB J1 NQ MES""".split())
HORIZONS = (10, 21, 43, 63)
PILOT = {"ES", "ZN", "E6", "CL", "GC", "ZC"}


def read_file(storage, key):
    day = date.fromisoformat(key[len(PREFIX):-8])
    obj = storage.get_object(Bucket=BUCKET, Key=key)
    with closing(obj["Body"]) as body:
        raw = body.read()
    checksum = obj["Metadata"].get("verified-sha256")
    if not checksum or hashlib.sha256(raw).hexdigest() != checksum:
        raise RuntimeError(f"Missing or invalid checksum: {key}")
    parquet = pq.ParquetFile(BytesIO(raw))
    field = "date" if "date" in parquet.schema_arrow.names else "timestamp"
    frame = parquet.read(columns=[field, "symbol", "open", "high", "low", "close"]).to_pandas()
    frame = frame[frame.symbol.isin(ROOTS)].copy()
    embedded = pd.to_datetime(frame.pop(field)).dt.date
    offset = (pd.Timestamp(day) - pd.to_datetime(embedded)).dt.days
    frame["session"] = pd.Timestamp(day)
    frame["date_offset"] = offset
    return frame


def outcomes(frame):
    frame = frame.sort_values("session").reset_index(drop=True)
    duplicate = frame.session.duplicated(keep=False)
    o, h, l, c = (frame[col].to_numpy() for col in ("open", "high", "low", "close"))
    invalid = ~np.isfinite([o, h, l, c]).all(axis=0) | (h < np.maximum(o, c)) | (l > np.minimum(o, c))
    invalid |= duplicate.to_numpy() | ~frame.date_offset.between(0, 3).to_numpy()
    # An extreme internal gap flags the affected holding window or ATR warm-up.
    gap = frame.session.diff().dt.days.fillna(0).gt(7).to_numpy()
    previous = np.r_[np.nan, c[:-1]]
    tr = np.maximum(h - l, np.maximum(abs(h - previous), abs(l - previous)))
    tr[invalid | np.r_[True, invalid[:-1]] | gap] = np.nan
    atr = pd.Series(tr).rolling(20).mean().shift(1).to_numpy()
    atr[~np.isfinite(atr) | (atr <= 0)] = np.nan
    result = frame[["symbol", "session", "date_offset"]].copy()
    result["entry_ready"] = np.isfinite(atr) & ~invalid
    result["trend_up"] = False
    result["trend_down"] = False
    close = pd.Series(c).mask(invalid)
    avg = close.rolling(100).mean()
    result["trend_up"] = ((close > avg) & (avg > avg.shift(20))).shift(1, fill_value=False)
    result["trend_down"] = ((close < avg) & (avg < avg.shift(20))).shift(1, fill_value=False)
    result["move5"] = (close.diff(5).shift(1) / atr)
    for n in HORIZONS:
        def forward(values, operation):
            windows = pd.Series(values).rolling(n)
            return getattr(windows, operation)().shift(-(n - 1)).to_numpy()

        bad = forward(invalid.astype(float), "max") > 0
        bad |= pd.Series(gap).shift(-1).rolling(n - 1).max().shift(-(n - 2)).fillna(0).to_numpy() > 0
        valid = result.entry_ready.to_numpy() & ~bad
        result[f"exit_{n}"] = frame.session.shift(-(n - 1))
        exit_price = pd.Series(c).shift(-(n - 1)).to_numpy()
        result[f"return_{n}"] = np.where(valid, (exit_price - o) / atr, np.nan)
        result[f"up_{n}"] = np.where(valid, np.maximum(0, forward(h, "max") - o) / atr, np.nan)
        result[f"down_{n}"] = np.where(valid, np.maximum(0, o - forward(l, "min")) / atr, np.nan)
    return result


def main():
    storage = boto3.client(
        "s3", endpoint_url=os.environ["R2_ENDPOINT_URL"],
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"], region_name="auto",
        config=Config(max_pool_connections=32, retries={"max_attempts": 8, "mode": "standard"}),
    )
    pages = storage.get_paginator("list_objects_v2").paginate(Bucket=BUCKET, Prefix=PREFIX)
    keys = sorted(
        obj["Key"] for page in pages for obj in page.get("Contents", [])
        if obj["Key"].endswith(".parquet")
    )
    if not keys:
        raise RuntimeError("No futures archive objects")
    with ThreadPoolExecutor(max_workers=24) as pool:
        frames = list(pool.map(lambda key: read_file(storage, key), keys))
    prices = pd.concat(frames, ignore_index=True)
    print(f"Verified {len(keys)} stored files and read {len(prices)} relevant daily bars.", flush=True)
    pilot = prices[prices.symbol.isin(PILOT)]
    if set(pilot.symbol) != PILOT or pilot.duplicated(["symbol", "session"]).any():
        raise RuntimeError("Pilot symbol coverage or key uniqueness failed")
    if not pilot.date_offset.between(0, 3).all():
        raise RuntimeError("Pilot file date does not match the expected embedded date convention")
    print("Pilot coverage\n" + pilot.groupby("symbol").session.agg(["min", "max", "count"]).to_string(), flush=True)
    result = pd.concat([outcomes(group) for _, group in prices.groupby("symbol")], ignore_index=True)
    print(result.groupby("symbol").session.agg(["min", "max", "count"]).to_string(), flush=True)
    output = Path("cot-futures-price-outcomes.parquet")
    result.to_parquet(output, index=False, compression="zstd")


if __name__ == "__main__":
    main()
