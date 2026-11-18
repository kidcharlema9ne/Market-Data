"""Universe size count for the stock efficiency-ratio test (Michael, 17 Nov 2026: why ~2,200 eligible stocks per day versus about 4,400 in a TradeStation scan).
Read-only: counts rows and symbols in marketparquet/stock_daily, no returns. In-sample only: files dated after 2021-08-06 are never opened (sealed years).
Usage: python universe_count.py OUT_DIR
Per year (2000 to 2021-08-06) it reports, over trading days in that year, the median / min / max of:
  all rows in the file; rows with that day's dollar volume (close x volume) at least $3M; and the test's own definition: 15-session average dollar volume at least $3M with all 15 sessions
  present (the same filtered table as fetch_stock_prices.py, days under $250k dropped), split into common stocks (er_stocks_common_momentum.is_common) and everything else.
Also: distinct symbols ever, distinct ever-eligible, how many '-DELISTED' symbols, whether well-known ETF tickers appear inside stock_daily, and samples of non-common symbols that pass the floor.
"""
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import date
from io import BytesIO
from pathlib import Path

import boto3
import numpy as np
import pandas as pd
import pyarrow.parquet as pq

BUCKET = "insider-research"
PREFIX = "marketparquet/stock_daily/"
LAST = date(2021, 8, 6)
FIRST = date(2000, 1, 1)
MIN_DV = 250_000.0
FLOOR = 3_000_000.0
ETF_TICKERS = ["SPY", "QQQ", "IWM", "DIA", "GLD", "SLV", "TLT", "IEF", "HYG", "LQD", "EEM", "EFA", "VTI", "VOO", "XLF", "XLE", "XLK", "XLV", "XLU", "ARKK", "TQQQ", "SQQQ", "UVXY", "USO", "UNG", "VXX", "SOXL", "SPXU"]
CLASS_OK = {"BRK.A", "BRK.B", "BF.A", "BF.B", "HEI.A", "MOG.A", "MOG.B", "LGF.A", "LGF.B", "JW.A", "JW.B", "HUB.A", "HUB.B", "RDS.A", "RDS.B", "FCE.A", "FCE.B", "KV.A", "KV.B", "GEF.B", "CRD.A", "CRD.B"}
out_dir = Path(sys.argv[1]); out_dir.mkdir(parents=True, exist_ok=True)
log = open(out_dir / "universe_count.txt", "w")


def P(*a):
    print(*a, flush=True); print(*a, file=log, flush=True)


def is_common(sym):  # identical to er_stocks_common_momentum.is_common
    base = sym[:-len("-DELISTED")] if sym.endswith("-DELISTED") else sym
    if "." in base:
        return base in CLASS_OK
    if not (base.isalpha() and base.isupper()):
        return False
    if len(base) >= 5 and base[-1] in "WURZPONYFL" and base != "GOOGL":
        return False
    return True


client = boto3.client("s3", endpoint_url=os.environ["R2_ENDPOINT_URL"], aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
                      aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"], region_name="auto")
pages = client.get_paginator("list_objects_v2").paginate(Bucket=BUCKET, Prefix=PREFIX)
keys = []
for p in pages:
    for o in p.get("Contents", []):
        k = o["Key"]
        if not k.endswith(".parquet"):
            continue
        d = date.fromisoformat(k[len(PREFIX):-len(".parquet")])
        if FIRST <= d <= LAST:
            keys.append((d, k))
keys.sort()
P(f"{len(keys)} stock_daily files from {keys[0][0]} to {keys[-1][0]} (files after {LAST} not opened)")


def read(item):
    d, k = item
    with closing(client.get_object(Bucket=BUCKET, Key=k)["Body"]) as b:
        raw = b.read()
    t = pq.read_table(BytesIO(raw), columns=["symbol", "close", "volume"]).to_pandas()
    t["symbol"] = t["symbol"].astype(str)
    dv = t["close"].astype("float64") * t["volume"].astype("float64")
    n_all = len(t)
    n_day3 = int((dv >= FLOOR).sum())
    etf_hits = sorted(set(t["symbol"]) & set(ETF_TICKERS))
    keep = (dv >= MIN_DV) & (t["close"] > 0)
    return d, n_all, n_day3, etf_hits, t.loc[keep, "symbol"].to_numpy(), dv[keep].to_numpy()


daily, etf_seen, sym_all_count = [], {}, set()
dates, syms, dvs = [], [], []
with ThreadPoolExecutor(max_workers=8) as pool:
    for i, (d, n_all, n_day3, etf_hits, s, v) in enumerate(pool.map(read, keys)):
        daily.append((d, n_all, n_day3))
        for e in etf_hits:
            etf_seen.setdefault(e, [d, d, 0]); etf_seen[e][1] = d; etf_seen[e][2] += 1
        dates.append(np.full(len(s), (d - date(1970, 1, 1)).days, dtype=np.int32)); syms.append(s); dvs.append(v)
        if i % 1000 == 0:
            P(f"  {i} files read")
cal = [d for d, _, _ in daily]
cal_i = np.array([(d - date(1970, 1, 1)).days for d in cal], dtype=np.int32)
df = pd.DataFrame({"date_i": np.concatenate(dates), "symbol": np.concatenate(syms), "dv": np.concatenate(dvs)})
del dates, syms, dvs
df["symbol"] = df["symbol"].astype("category")
P(f"kept rows (dollar volume >= $250k): {len(df):,}")

# test definition: 15-session average of dollar volume at least $3M with all 15 consecutive archive sessions present for the symbol
pos = pd.Series(np.arange(len(cal_i)), index=cal_i)
df["pos"] = pos.reindex(df["date_i"]).to_numpy()
df = df.sort_values(["symbol", "pos"], kind="stable").reset_index(drop=True)
g = df.groupby("symbol", observed=True)
roll_sum = g["dv"].transform(lambda x: x.rolling(15, min_periods=15).sum())
span = g["pos"].transform(lambda x: x - x.shift(14))
df["elig"] = (roll_sum / 15.0 >= FLOOR) & (span == 14)
names = df["symbol"].astype(str)
common_map = {s: is_common(s) for s in df["symbol"].cat.categories}
df["common"] = df["symbol"].map(common_map).astype(bool)
e = df[df["elig"]]
per_day = e.groupby(["pos", "common"]).size().unstack(fill_value=0).reindex(range(len(cal)), fill_value=0)
per_day = per_day.rename(columns={True: "common_elig", False: "other_elig"})
for c in ("common_elig", "other_elig"):
    if c not in per_day:
        per_day[c] = 0
t = pd.DataFrame(daily, columns=["date", "rows_all", "rows_day3m"])
t["common_elig"] = per_day["common_elig"].to_numpy(); t["other_elig"] = per_day["other_elig"].to_numpy()
t["year"] = [d.year for d in t["date"]]
t.to_csv(out_dir / "universe_by_day.csv", index=False)


def q(x):
    return f"{int(x.median()):>6,} ({int(x.min()):,} to {int(x.max()):,})"


P("\n=== Per year, median (min to max) over trading days ===")
P(f"{'year':<6}{'days':>5}  {'all rows in file':<24}{'rows >= $3M that day':<24}{'common, 15-day avg >= $3M':<28}{'non-common passing floor':<26}")
for y, gy in t.groupby("year"):
    P(f"{y:<6}{len(gy):>5}  {q(gy['rows_all']):<24}{q(gy['rows_day3m']):<24}{q(gy['common_elig']):<28}{q(gy['other_elig']):<26}")
P(f"\nWHOLE WINDOW median: common eligible {int(t['common_elig'].median()):,}; non-common passing floor {int(t['other_elig'].median()):,}; both together {int((t['common_elig'] + t['other_elig']).median()):,}; rows >= $3M single day {int(t['rows_day3m'].median()):,}")
last = t.iloc[-1]
P(f"LAST DAY {last['date']}: all rows {int(last['rows_all']):,}; rows >= $3M that day {int(last['rows_day3m']):,}; common eligible {int(last['common_elig']):,}; non-common passing {int(last['other_elig']):,}")
P(f"Last 60 days median: common eligible {int(t['common_elig'].tail(60).median()):,}; other {int(t['other_elig'].tail(60).median()):,}")

allsyms = df["symbol"].cat.categories
P("\n=== Symbols ===")
P(f"distinct symbols with at least one day over $250k: {len(allsyms):,} (common by symbol rule {sum(common_map.values()):,}; -DELISTED suffix {sum(str(s).endswith('-DELISTED') for s in allsyms):,})")
ever = e["symbol"].astype(str).unique()
P(f"distinct symbols ever eligible at the $3M 15-day floor: {len(ever):,} (common {sum(common_map[s] for s in ever):,}; non-common {sum(not common_map[s] for s in ever):,})")
P("\n=== Are well-known ETF tickers inside stock_daily? (first day, last day, days seen) ===")
if etf_seen:
    for k_, (a, b, n) in sorted(etf_seen.items()):
        P(f"  {k_}: {a} to {b}, {n} days")
else:
    P("  none of: " + ", ".join(ETF_TICKERS))
P(f"  checked {len(ETF_TICKERS)} tickers; found {len(etf_seen)}")
oth = e[~e["common"]]
top = oth.groupby("symbol", observed=True).size().sort_values(ascending=False)
top = top[top > 0]
P("\n=== Non-common symbols that pass the floor, most days first (sample of 60) ===")
P(", ".join(f"{s}({n})" for s, n in top.head(60).items()))
P("\nsealed check: last file opened " + str(cal[-1]))
log.close()
