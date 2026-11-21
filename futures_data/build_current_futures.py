"""Bring the 48 COT-report markets' daily futures up to 2026-11-20 and write them to a SEPARATE R2 prefix.

Writes marketparquet/futures_daily_current/{date}.parquet (columns date, symbol, open, high, low, close, volume, source).
The vendor-sourced archive under marketparquet/futures_daily/ is NOT touched.

Days 2026-11-09..13 (not obtainable on the current MarketParquet plan) come from free Yahoo Finance continuous futures.
Days 2026-11-16..20 are the vendor's own public files, copied verbatim.
A market is extended only if Yahoo can be checked against BOTH the stored archive (before the gap) and the vendor's public
files (after the gap):
  exact   - Yahoo equals the vendor close (ratio 1.0000 within 0.05%) on both sides: Yahoo bars used as they are.
  scaled  - Yahoo sits on a different contract month than the vendor, but the offset is steady across the gap (same within
            0.3% before and after, so the vendor did not roll in the gap and the stored history needs no rescale):
            Yahoo bars multiplied by the offset, interpolated by session.
  otherwise the market is NOT extended and stays at 2026-11-06.
Markets Yahoo does not carry (DX, VX, SR3, SR1) are not extended. Writes futures_data/current_build_report.md.
"""
import csv
import hashlib
import os
import statistics
from contextlib import closing
from io import BytesIO
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import boto3
import pyarrow as pa
import pyarrow.parquet as pq
import yfinance as yf

BASE = "https://marketparquet.com"
BUCKET, PREFIX, OUT = "insider-research", "marketparquet/futures_daily/", "marketparquet/futures_daily_current/"
RENAME = {"6A": "A6", "6B": "B6", "6C": "AD", "6E": "E6", "6J": "J1", "6L": "BR", "6M": "MP",
          "6N": "N6", "6S": "E1", "ZB": "US", "BRR": "BTC", "LBR": "LBS"}
BEFORE = ["2026-10-30", "2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06"]
GAP = ["2026-11-09", "2026-11-10", "2026-11-11", "2026-11-12", "2026-11-13"]
AFTER = ["2026-11-16", "2026-11-17", "2026-11-18", "2026-11-19", "2026-11-20"]
STEPS = {d: i + 1 for i, d in enumerate(GAP + AFTER)}  # sessions after 2026-11-06
s3 = boto3.client("s3", endpoint_url=os.environ["R2_ENDPOINT_URL"], aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
                  aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"], region_name="auto")


def stored(day):
    resp = s3.get_object(Bucket=BUCKET, Key=f"{PREFIX}{day}.parquet")
    with closing(resp["Body"]) as b:
        raw = b.read()
    if hashlib.sha256(raw).hexdigest() != resp["Metadata"].get("verified-sha256"):
        raise SystemExit(f"unverified archive object {day}")
    t = pq.read_table(BytesIO(raw), columns=["symbol", "close"])
    return dict(zip(t.column("symbol").to_pylist(), t.column("close").to_pylist()))


def vendor(day):
    try:
        req = Request(f"{BASE}/api/data/download/futures_daily/{day}.parquet", headers={"User-Agent": "insider-buying-research/1.0"})
        with urlopen(req, timeout=90) as r:
            raw = r.read()
    except (HTTPError, URLError) as e:
        raise SystemExit(f"vendor public file {day} unavailable: {e}")
    if raw[:4] != b"PAR1":
        raise SystemExit(f"vendor file {day} is not parquet")
    t = pq.read_table(BytesIO(raw))
    cols = {c: t.column(c).to_pylist() for c in ("symbol", "open", "high", "low", "close", "volume")}
    return {s: (cols["open"][i], cols["high"][i], cols["low"][i], cols["close"][i], cols["volume"][i])
            for i, s in enumerate(cols["symbol"])}


S = {d: stored(d) for d in BEFORE}
V = {d: vendor(d) for d in AFTER}
rows = list(csv.DictReader(open("futures_data/report_universe_48_markets.csv")))
tickers = {r["ibkr"]: f"{r['ibkr']}=F" for r in rows}
data = yf.download(list(tickers.values()), start="2026-10-20", end="2026-11-22", auto_adjust=False,
                   group_by="ticker", progress=False, threads=True)


def classify(rb, ra):
    if len(rb) < 4 or len(ra) < 4:
        return "not extended: too few checkable days", None
    mb, ma = statistics.median(rb), statistics.median(ra)
    sb, sa = max(rb) - min(rb), max(ra) - min(ra)
    if abs(mb - 1) < 5e-4 and abs(ma - 1) < 5e-4 and sb < 5e-4 and sa < 5e-4:
        return "exact", (1.0, 1.0)
    if sb < 0.004 and sa < 0.004 and abs(ma / mb - 1) < 0.003:
        return "scaled", (mb, ma)
    return f"not extended: offset not steady (before {mb:.4f}, after {ma:.4f}, spreads {sb:.4f}/{sa:.4f})", (mb, ma)


by_day = {d: [] for d in GAP + AFTER}
report = ["| market | price symbol | treatment | last day |", "|---|---|---|---|"]
extended = []
for r in rows:
    ib, ps = r["ibkr"], RENAME.get(r["ibkr"], r["ibkr"])
    try:
        df = data[tickers[ib]].dropna(subset=["Close"])
        df.index = [i.strftime("%Y-%m-%d") for i in df.index]
    except Exception:
        df = None
    if df is None or df.empty:
        report.append(f"| {ib} | {ps} | not extended: not on Yahoo | 2026-11-06 |")
        continue
    rb = [S[d][ps] / df.loc[d, "Close"] for d in BEFORE if ps in S[d] and d in df.index and df.loc[d, "Close"]]
    ra = [V[d][ps][3] / df.loc[d, "Close"] for d in AFTER if ps in V[d] and d in df.index and df.loc[d, "Close"]]
    verdict, ks = classify(rb, ra)
    if verdict not in ("exact", "scaled"):
        report.append(f"| {ib} | {ps} | {verdict} | 2026-11-06 |")
        continue
    if not all(d in df.index for d in GAP) or not all(ps in V[d] for d in AFTER):
        report.append(f"| {ib} | {ps} | not extended: a gap or vendor day is missing | 2026-11-06 |")
        continue
    mb, ma = ks
    for d in GAP:
        k = mb + (ma - mb) * STEPS[d] / 6.0
        b = df.loc[d]
        vol = b["Volume"] if b["Volume"] == b["Volume"] else 0.0
        by_day[d].append((ps, b["Open"] * k, b["High"] * k, b["Low"] * k, b["Close"] * k, float(vol), f"yahoo_{verdict}"))
    for d in AFTER:
        o, h, l, c, v = V[d][ps]
        by_day[d].append((ps, o, h, l, c, v, "vendor"))
    extended.append(ps)
    report.append(f"| {ib} | {ps} | {verdict} (offset before {mb:.4f}, after {ma:.4f}) | 2026-11-20 |")

for d, recs in by_day.items():
    if not recs:
        continue
    t = pa.table({"date": [d] * len(recs), "symbol": [x[0] for x in recs], "open": [float(x[1]) for x in recs],
                  "high": [float(x[2]) for x in recs], "low": [float(x[3]) for x in recs],
                  "close": [float(x[4]) for x in recs], "volume": [float(x[5]) for x in recs],
                  "source": [x[6] for x in recs]})
    buf = BytesIO()
    pq.write_table(t, buf)
    raw = buf.getvalue()
    s3.put_object(Bucket=BUCKET, Key=f"{OUT}{d}.parquet", Body=raw,
                  Metadata={"verified-sha256": hashlib.sha256(raw).hexdigest()})
    print("wrote", d, len(recs), "rows", flush=True)

text = "\n".join(["# Current-futures build (R2 prefix marketparquet/futures_daily_current/)", "",
                  f"Markets extended to 2026-11-20: {len(extended)} of 48.", ""] + report)
open("futures_data/current_build_report.md", "w").write(text + "\n")
print(text)
