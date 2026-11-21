"""Fill 2026-11-09..13 for the 17 markets the free Yahoo continuous series could not confirm, using INDIVIDUAL contract prices and
the vendor's own roll file.  Read-only: writes futures_data/contract_fill_report.md and futures_data/contract_fill_candidates.csv.

Model of the vendor series (current price level): value(d) = price of the contract the vendor was in on day d
                                                   x product of ratios of all rolls with roll_date >= d.
The contract is the expiring one up to and including a roll date and the new one after it (roll ratio = new close / expiring close
on the roll date).  Contracts are identified by matching this model to the vendor's known days (stored tail from 2026-10-20 and
the vendor public files 11-16..20) to within 0.1%; a market is filled only if every segment is identified that way and the
roll-date check (expiring close x ratio = new close) also holds.
"""
import csv
import hashlib
import json
import math
import os
from io import BytesIO
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import boto3
import pandas as pd
import pyarrow.parquet as pq
import yfinance as yf

BASE = "https://marketparquet.com"
token = os.environ["MARKETPARQUET_API_KEY"]
GAP = ["2026-11-09", "2026-11-10", "2026-11-11", "2026-11-12", "2026-11-13"]
KNOWN_FROM, KNOWN_TO = "2026-10-20", "2026-11-20"
TOL = 0.001
# price symbol: (Yahoo contract root, Yahoo exchange suffix)
MARKETS = {"ZC": ("ZC", "CBT"), "ZS": ("ZS", "CBT"), "HO": ("HO", "NYM"), "HE": ("HE", "CME"), "LE": ("LE", "CME"),
           "GF": ("GF", "CME"), "CL": ("CL", "NYM"), "BZ": ("BZ", "NYM"), "CC": ("CC", "NYB"), "KC": ("KC", "NYB"),
           "MP": ("6M", "CME"), "DX": ("DX", "NYB"), "BR": ("6L", "CME"), "RB": ("RB", "NYM"), "VX": ("VX", "CBF"),
           "SR3": ("SR3", "CME"), "SR1": ("SR1", "CME")}
CODES = [f"{m}26" for m in "UVXZ"] + [f"{m}27" for m in "FGHJKMNQUVXZ"]


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


code, body = http(f"{BASE}/api/v1/meta/futures_rolls", True)
du = json.loads(body)["download_url"]
du = BASE + du if du.startswith("/") else du
code, raw = http(du, du.startswith(BASE))
rolls = pq.read_table(BytesIO(raw)).to_pylist()

s3 = boto3.client("s3", endpoint_url=os.environ["R2_ENDPOINT_URL"], aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
                  aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"], region_name="auto")
resp = s3.get_object(Bucket="insider-research", Key="marketparquet/futures_current/futures_prices_current.parquet")
data = resp["Body"].read()
assert hashlib.sha256(data).hexdigest() == resp["Metadata"]["verified-sha256"]
st = pq.read_table(BytesIO(data)).to_pandas()
st = st[(st["file_date"] >= KNOWN_FROM) & (st["file_date"] <= KNOWN_TO) & (~st["source"].astype(str).str.startswith("yahoo"))]

report = ["# Contract-level fill for 2026-11-09..13 (read-only)", "",
          f"Tolerance {TOL:.1%}. Known vendor days used for matching: {KNOWN_FROM}..{KNOWN_TO}.", ""]
rows_out = []
summary = []
for ps, (root, suf) in MARKETS.items():
    V = st[st["symbol"] == ps].set_index("file_date")["close"].to_dict()
    rs = sorted([r for r in rolls if r["root"] == ps and r["roll_date"] >= KNOWN_FROM], key=lambda r: r["roll_date"])
    tickers = [f"{root}{c}.{suf}" for c in CODES]
    if ps == "VX":
        P = {}
        for exp in ["2026-11-18", "2026-12-16", "2027-01-20", "2027-02-17", "2027-03-17"]:
            c, b = http(f"https://cdn.cboe.com/data/us/futures/market_statistics/historical_data/VX/VX_{exp}.csv", False)
            if c != 200:
                report.append(f"- CBOE VX_{exp}: HTTP {c}")
                continue
            d = pd.read_csv(BytesIO(b), skiprows=lambda i: False)
            d.columns = [x.strip() for x in d.columns]
            tcol = next(x for x in d.columns if "Trade Date" in x)
            d["idx"] = pd.to_datetime(d[tcol]).dt.strftime("%Y-%m-%d")
            d = d.set_index("idx")
            d = d.rename(columns={"Settle": "Close_settle"})
            out = pd.DataFrame({"Open": d["Open"], "High": d["High"], "Low": d["Low"], "Close": d["Close_settle"], "Volume": d["Total Volume"]})
            P[f"VX{exp}"] = out.loc[out.index >= "2026-10-10"]
        raw_df = None
        tickers = []
    try:
        if ps == "VX":
            raise KeyError("VX handled above")
        raw_df = yf.download(tickers, start="2026-10-10", end="2026-11-22", auto_adjust=False, group_by="ticker", progress=False, threads=True)
    except KeyError:
        pass
    except Exception as e:
        summary.append((ps, f"download failed: {e}"))
        continue
    if ps != "VX":
        P = {}
    for t in tickers:
        try:
            d = raw_df[t].dropna(subset=["Close"])
        except Exception:
            continue
        if len(d):
            d = d.copy()
            d.index = [i.strftime("%Y-%m-%d") for i in d.index]
            P[t] = d
    report.append(f"## {ps}: {len(P)} contract series with data; rolls since {KNOWN_FROM}: " +
                  (", ".join(f"{r['roll_date']} x{r['ratio']:.4f}" for r in rs) or "none"))

    def cumfac(d):
        f = 1.0
        for r in rs:
            if r["roll_date"] >= d:
                f *= r["ratio"]
        return f

    def seg_days(k):
        lo = rs[k - 1]["roll_date"] if k > 0 else "0000"
        hi = rs[k]["roll_date"] if k < len(rs) else "9999"
        return lo, hi

    needed = {sum(1 for r in rs if r["roll_date"] < d) for d in GAP}
    chosen = {}
    ok = True

    def model_ratios(t, days):
        df = P[t]
        return [round(df.loc[d, "Close"] * cumfac(d) / V[d], 4) if d in df.index else None for d in days]

    for k in range(len(rs), min(needed) - 1, -1):
        lo, hi = seg_days(k)
        roll_days = {r["roll_date"] for r in rs}
        days = sorted(d for d in V if lo < d <= hi and d not in roll_days)
        scored = []
        for t, df in P.items():
            if not days or not all(d in df.index for d in days):
                continue
            err = max(abs(df.loc[d, "Close"] * cumfac(d) / V[d] - 1) for d in days)
            scored.append((err, t))
        scored.sort()
        if scored and scored[0][0] <= TOL:
            chosen[k] = scored[0][1]
            info = ""
            if k < len(rs) and k + 1 in chosen:
                rd = rs[k]["roll_date"]
                if rd in P[chosen[k]].index and rd in P[chosen[k + 1]].index:
                    gap_pct = P[chosen[k]].loc[rd, "Close"] * rs[k]["ratio"] / P[chosen[k + 1]].loc[rd, "Close"] - 1
                    info = f"; roll-day check (expiring close x ratio vs new close) differs by {gap_pct:+.2%}"
            report.append(f"- segment {k} ({lo}..{hi}): {scored[0][1]} max error {scored[0][0]:.3%} over {len(days)} known non-roll days{info}")
            continue
        report.append(f"- segment {k} ({lo}..{hi}): " + ("NOT IDENTIFIED" if k in needed else "not identified (not needed for the gap)") +
                      f"; {len(days)} known days; contracts with all days: {[t for _, t in scored][:5]}")
        for err, t in scored[:3]:
            report.append(f"    - {t}: max error {err:.3%}; model/vendor by day {dict(zip(days, model_ratios(t, days)))}")
        if not scored:
            for t, df in list(P.items())[:6]:
                report.append(f"    - {t}: has {len(df)} bars, missing known days {[d for d in days if d not in df.index][:6]}")
        if k in needed:
            ok = False
            break
    if not ok:
        summary.append((ps, "not identified"))
        continue
    fill = []
    for d in GAP:
        k = sum(1 for r in rs if r["roll_date"] < d)
        df = P[chosen[k]]
        if d not in df.index:
            ok = False
            report.append(f"- gap day {d}: contract {chosen[k]} has no bar")
            break
        f = cumfac(d)
        b = df.loc[d]
        vol = b["Volume"] if b["Volume"] == b["Volume"] else 0.0
        fill.append((ps, d, b["Open"] * f, b["High"] * f, b["Low"] * f, b["Close"] * f, float(vol), f"contract_fill:{chosen[k]}"))
    if not ok:
        summary.append((ps, "gap bars missing"))
        continue
    rows_out += fill
    summary.append((ps, f"FILLED with {', '.join(chosen[k] for k in sorted(chosen))}"))
report += ["", "## Summary", ""] + [f"- {a}: {b}" for a, b in summary]
open("futures_data/contract_fill_report.md", "w").write("\n".join(report) + "\n")
with open("futures_data/contract_fill_candidates.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["symbol", "date", "open", "high", "low", "close", "volume", "source"])
    w.writerows(rows_out)
print("\n".join(report))
