"""Refresh prices/etf_recent.csv.gz: daily open/high/low/close/volume for the ETF stand-ins the COT System uses (ETF_MAP in COT-System scripts/cot_system_report.py).

Each ETF is tried through a chain of free sources, in this order, and the first source that returns GOOD data wins:
  1. Yahoo Finance chart API (query1 host)
  2. Yahoo Finance chart API (query2 host)
  3. Stooq daily CSV
  4. Nasdaq.com historical-quotes API
  5. MarketParquet etf_daily files copied into R2 (bucket insider-research, marketparquet/etf_daily/; only used if the R2 secrets
     are present; these lag by days, so they are the last resort and are merged onto the existing history)
"Good" means: at least 60 sessions, every bar sane (positive, high >= low, open and close inside the range), and the newest bar no
more than 5 calendar days old. Prices are the raw (not dividend-adjusted) bars, because stops and share counts use real prices.
Full-history sources replace an ETF's stored history (this also fixes reverse splits such as VXX); the R2 fallback only merges.
If every source fails for an ETF, its existing rows are kept and the report prints "need <ticker> prices" or uses the old rows
if they are still fresh. This script never raises for a data problem and always exits 0, so the report always runs.
"""
import csv
import io
import json
import os
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pandas as pd

OUT = "prices/etf_recent.csv.gz"
DAYS = 700
MIN_ROWS = 60
MAX_AGE_DAYS = 5
UA = "Mozilla/5.0 (compatible; COT-System/1.0)"
COLS = ["symbol", "open", "high", "low", "close", "volume", "file_date"]


# Keep in step with ETF_MAP in the COT-System repo (scripts/cot_system_report.py). Add a ticker here to start tracking it.
ETFS = ["BAL", "BNO", "CANE", "CORN", "CPER", "EDV", "FXA", "FXB", "FXC", "FXE", "FXF", "FXY", "GLD", "IEF", "IEI", "PPLT",
        "SHY", "SLV", "SOYB", "TLT", "UGA", "UNG", "USO", "UUP", "VXX", "WEAT"]


def etf_list():
    return ETFS


def http(url, headers=None, tries=3):
    last = None
    for attempt in range(tries):
        try:
            with urlopen(Request(url, headers={"User-Agent": UA, **(headers or {})}), timeout=40) as resp:
                return resp.read()
        except HTTPError as exc:
            last = f"HTTP {exc.code}"
            if exc.code in (400, 401, 403, 404):
                break
        except (URLError, TimeoutError, OSError) as exc:
            last = f"network ({exc})"
        time.sleep(2 ** attempt)
    raise RuntimeError(last)


def frame(rows):
    df = pd.DataFrame(rows, columns=["file_date", "open", "high", "low", "close", "volume"])
    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["file_date"] = pd.to_datetime(df["file_date"]).dt.strftime("%Y-%m-%d")
    return df.sort_values("file_date").drop_duplicates("file_date", keep="last").reset_index(drop=True)


# ------------------------------------------------------------------------------------------ sources
def yahoo(host):
    def get(sym):
        data = json.loads(http(f"https://{host}.finance.yahoo.com/v8/finance/chart/{sym}?range=2y&interval=1d&events=div,splits"))
        res = data["chart"]["result"][0]
        off = res["meta"].get("gmtoffset", 0)
        q = res["indicators"]["quote"][0]
        rows = []
        for i, ts in enumerate(res["timestamp"]):
            d = (datetime.fromtimestamp(ts, tz=timezone.utc) + timedelta(seconds=off)).date().isoformat()
            rows.append((d, q["open"][i], q["high"][i], q["low"][i], q["close"][i], q["volume"][i]))
        return frame(rows)
    return get


def stooq(sym):
    text = http(f"https://stooq.com/q/d/l/?s={sym.lower()}.us&i=d").decode("utf-8", "replace")
    if not text.lstrip().lower().startswith("date"):
        raise RuntimeError("Stooq returned no CSV")
    df = pd.read_csv(io.StringIO(text))
    df.columns = [c.lower() for c in df.columns]
    return frame(list(zip(df["date"], df["open"], df["high"], df["low"], df["close"], df.get("volume", 0))))


def nasdaq(sym):
    start = (date.today() - timedelta(days=DAYS)).isoformat()
    url = (f"https://api.nasdaq.com/api/quote/{sym}/historical?assetclass=etf&fromdate={start}"
           f"&todate={date.today().isoformat()}&limit=9999")
    data = json.loads(http(url, {"Accept": "application/json", "Origin": "https://www.nasdaq.com", "Referer": "https://www.nasdaq.com/"}))
    trades = data["data"]["tradesTable"]["rows"]
    num = lambda s: float(str(s).replace("$", "").replace(",", "")) if s not in (None, "", "N/A") else None
    rows = [(datetime.strptime(r["date"], "%m/%d/%Y").date().isoformat(), num(r["open"]), num(r["high"]), num(r["low"]),
             num(r["close"]), num(r["volume"])) for r in trades]
    return frame(rows)


R2_CACHE = {}


def marketparquet_r2(sym):
    """Last resort: the MarketParquet etf_daily files in R2 (a lagging copy). Merged, never replacing."""
    import boto3
    import pyarrow.parquet as pq
    if "client" not in R2_CACHE:
        R2_CACHE["client"] = boto3.client("s3", endpoint_url=os.environ["R2_ENDPOINT_URL"], aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
                                          aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"], region_name="auto")
        c = R2_CACHE["client"]
        prefix = "marketparquet/etf_daily/"
        keys = sorted(o["Key"] for p in c.get_paginator("list_objects_v2").paginate(Bucket="insider-research", Prefix=prefix)
                      for o in p.get("Contents", []) if o["Key"].endswith(".parquet"))[-90:]
        frames = []
        for k in keys:
            t = pq.read_table(io.BytesIO(c.get_object(Bucket="insider-research", Key=k)["Body"].read())).to_pandas()
            t["file_date"] = k[len(prefix):-len(".parquet")]
            frames.append(t[["symbol", "open", "high", "low", "close", "volume", "file_date"]])
        R2_CACHE["all"] = pd.concat(frames, ignore_index=True)
    sub = R2_CACHE["all"]
    sub = sub[sub["symbol"] == sym]
    return frame(list(zip(sub["file_date"], sub["open"], sub["high"], sub["low"], sub["close"], sub["volume"])))


SOURCES = [("yahoo (query1)", yahoo("query1"), True), ("yahoo (query2)", yahoo("query2"), True), ("stooq", stooq, True),
           ("nasdaq.com", nasdaq, True), ("marketparquet R2 (lagging copy)", marketparquet_r2, False)]


# ------------------------------------------------------------------------------------------ checks
def good(df, today):
    """Returns (ok, reason)."""
    if df is None or len(df) < MIN_ROWS:
        return False, f"only {0 if df is None else len(df)} rows"
    px = df[["open", "high", "low", "close"]]
    if px.isna().any().any() or (px <= 0).any().any():
        df = df.dropna(subset=["open", "high", "low", "close"])
        df = df[(df[["open", "high", "low", "close"]] > 0).all(axis=1)]
        if len(df) < MIN_ROWS:
            return False, "too many empty or non-positive bars"
    bad = (df["high"] < df["low"] * (1 - 1e-9)) | (df["high"] < df[["open", "close"]].max(axis=1) * (1 - 1e-6)) \
        | (df["low"] > df[["open", "close"]].min(axis=1) * (1 + 1e-6))
    if bad.mean() > 0.02:
        return False, f"{bad.mean():.0%} of bars fail the high/low check"
    age = (today - date.fromisoformat(df["file_date"].iloc[-1])).days
    if age > MAX_AGE_DAYS:
        return False, f"newest bar is {age} days old"
    return True, ""


def clean(df):
    df = df.dropna(subset=["open", "high", "low", "close"])
    df = df[(df[["open", "high", "low", "close"]] > 0).all(axis=1)]
    return df[df["file_date"] >= (date.today() - timedelta(days=DAYS)).isoformat()]


def main():
    today = date.today()
    tickers = etf_list()
    old = pd.read_csv(OUT) if os.path.exists(OUT) else pd.DataFrame(columns=COLS)
    kept = {s: g for s, g in old.groupby("symbol")}
    have_r2 = all(k in os.environ for k in ("R2_ENDPOINT_URL", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY"))
    out, log = [], []
    for sym in tickers:
        result = None
        for name, fn, full_history in SOURCES:
            if fn is marketparquet_r2 and not have_r2:
                log.append(f"{sym}: {name}: skipped (no R2 secrets)")
                continue
            try:
                df = fn(sym)
                ok, why = good(df, today)
            except Exception as exc:  # any source failure just moves to the next source
                ok, why = False, f"{type(exc).__name__}: {exc}"
            if not ok:
                log.append(f"{sym}: {name}: rejected ({why})")
                continue
            df = clean(df)
            if not full_history and sym in kept:
                prev = kept[sym].set_index("file_date")["close"]
                both = df.set_index("file_date")["close"].reindex(prev.index).dropna()
                if len(both) >= 5 and ((both / prev.reindex(both.index) - 1).abs().median() > 0.02):
                    log.append(f"{sym}: {name}: rejected (does not match the stored history; possible split)")
                    continue
                df = pd.concat([kept[sym].drop(columns="symbol"), df]).drop_duplicates("file_date", keep="last").sort_values("file_date")
            df = df.copy()
            df["symbol"] = sym
            result = df[COLS]
            log.append(f"{sym}: {name}: OK, {len(result)} rows, newest {result['file_date'].iloc[-1]}")
            break
        if result is None and sym in kept:
            result = kept[sym][COLS]
            log.append(f"{sym}: ALL SOURCES FAILED, kept {len(result)} stored rows (newest {result['file_date'].max()})")
        elif result is None:
            log.append(f"{sym}: ALL SOURCES FAILED and nothing stored: the report will say 'need {sym} prices'")
        if result is not None:
            out.append(result)
    print("\n".join(log))
    if not out:
        print("WARNING: no ETF data at all; left the file unchanged.", file=sys.stderr)
        return
    final = pd.concat(out, ignore_index=True).sort_values(["symbol", "file_date"])
    os.makedirs("prices", exist_ok=True)
    final.to_csv(OUT, index=False)
    print(f"wrote {OUT}: {len(final)} rows, {final['symbol'].nunique()} of {len(tickers)} ETFs")


if __name__ == "__main__":
    main()
