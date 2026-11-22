"""Read-only: can free Yahoo Finance continuous futures fill 2026-11-09..2026-11-13 for the 48 markets?

For each market compares Yahoo's daily close with (A) the archive's stored close on the last sessions before the gap and
(B) the vendor's public files for 2026-11-16..20, which tells whether Yahoo and the vendor sit on the same contract and
price level on both sides of the gap. Flags any Yahoo daily move that looks like a contract-roll jump inside the window.
Writes futures_data/yahoo_gap_report.md and futures_data/yahoo_gap_candidates.csv (raw Yahoo bars for the gap days).
Does NOT write to R2.
"""
import csv
import datetime as dt
import os
import statistics
from contextlib import closing
from io import BytesIO
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import boto3
import pyarrow.parquet as pq
import yfinance as yf

BASE = "https://marketparquet.com"
BUCKET, PREFIX = "insider-research", "marketparquet/futures_daily/"
RENAME = {"6A": "A6", "6B": "B6", "6C": "AD", "6E": "E6", "6J": "J1", "6L": "BR", "6M": "MP",
          "6N": "N6", "6S": "E1", "ZB": "US", "BRR": "BTC", "LBR": "LBS"}
GAP = ["2026-11-09", "2026-11-10", "2026-11-11", "2026-11-12", "2026-11-13"]
BEFORE = ["2026-10-30", "2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06"]
AFTER = ["2026-11-16", "2026-11-17", "2026-11-18", "2026-11-19", "2026-11-20"]
s3 = boto3.client("s3", endpoint_url=os.environ["R2_ENDPOINT_URL"], aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
                  aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"], region_name="auto")


def stored(day):
    with closing(s3.get_object(Bucket=BUCKET, Key=f"{PREFIX}{day}.parquet")["Body"]) as b:
        t = pq.read_table(BytesIO(b.read()), columns=["symbol", "close"])
    return dict(zip(t.column("symbol").to_pylist(), t.column("close").to_pylist()))


def vendor(day):
    try:
        with urlopen(Request(f"{BASE}/api/data/download/futures_daily/{day}.parquet", headers={"User-Agent": "insider-buying-research/1.0"}), timeout=90) as r:
            t = pq.read_table(BytesIO(r.read()), columns=["symbol", "close"])
        return dict(zip(t.column("symbol").to_pylist(), t.column("close").to_pylist()))
    except (HTTPError, URLError) as e:
        print("vendor", day, e)
        return {}


S = {d: stored(d) for d in BEFORE}
V = {d: vendor(d) for d in AFTER}
rows = list(csv.DictReader(open("futures_data/report_universe_48_markets.csv")))
yt = lambda ib: f"{ib}=F"
tickers = {r["ibkr"]: yt(r["ibkr"]) for r in rows}
data = yf.download(list(tickers.values()), start="2026-08-10", end="2026-11-22", auto_adjust=False, group_by="ticker", progress=False, threads=True)

out = ["# Yahoo gap probe (read-only)", "",
       "Ratio = (archive or vendor close) / (Yahoo close). 1.000 means same contract and same price level.", "",
       "| market | price symbol | Yahoo bars in gap | ratio before gap (archive/Yahoo) | ratio after gap (vendor/Yahoo) | biggest Yahoo move 11-06..11-16 vs typical | verdict |",
       "|---|---|---|---|---|---|---|"]
cands = []
clean = []
for r in rows:
    ib = r["ibkr"]
    ps = RENAME.get(ib, ib)
    tk = tickers[ib]
    try:
        df = data[tk].dropna(subset=["Close"])
    except Exception:
        df = None
    if df is None or df.empty:
        out.append(f"| {ib} | {ps} | none | | | | NO YAHOO DATA |")
        continue
    df.index = [i.strftime("%Y-%m-%d") for i in df.index]
    gap_bars = [d for d in GAP if d in df.index]
    rb = [S[d][ps] / df.loc[d, "Close"] for d in BEFORE if ps in S[d] and d in df.index and df.loc[d, "Close"]]
    ra = [V[d][ps] / df.loc[d, "Close"] for d in AFTER if ps in V.get(d, {}) and d in df.index and df.loc[d, "Close"]]
    closes = df["Close"]
    rets = (closes / closes.shift(1) - 1).dropna().abs()
    typical = float(rets.loc[:"2026-11-05"].median()) or 1e-9
    win = rets.loc["2026-11-09":"2026-11-16"]
    big = float(win.max()) if len(win) else 0.0
    mb = statistics.median(rb) if rb else float("nan")
    ma = statistics.median(ra) if ra else float("nan")
    ok_b = rb and abs(mb - 1) < 0.003 and (max(rb) - min(rb)) < 0.003
    ok_a = ra and abs(ma - 1) < 0.003 and (max(ra) - min(ra)) < 0.003
    jump = big > max(4 * typical, 0.01)
    if len(gap_bars) < 5:
        verdict = f"incomplete ({len(gap_bars)} of 5 gap days)"
    elif ok_b and ok_a and not jump:
        verdict = "CLEAN"
        clean.append(ib)
    elif ok_b and ok_a and jump:
        verdict = "levels match but a big move/roll jump in the window: check"
    else:
        verdict = "level mismatch: do not use"
    out.append(f"| {ib} | {ps} | {len(gap_bars)} | {mb:.4f} | {ma:.4f} | {big:.1%} vs {typical:.1%} | {verdict} |")
    for d in gap_bars:
        b = df.loc[d]
        cands.append([ps, d, b["Open"], b["High"], b["Low"], b["Close"], b.get("Volume", "")])
out += ["", f"CLEAN markets ({len(clean)} of 48): {', '.join(clean) or 'none'}."]
text = "\n".join(out)
open("futures_data/yahoo_gap_report.md", "w").write(text + "\n")
with open("futures_data/yahoo_gap_candidates.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["symbol", "date", "open", "high", "low", "close", "volume"])
    w.writerows(cands)
print(text)
