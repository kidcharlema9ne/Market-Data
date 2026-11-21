"""Read-only probe: which MarketParquet futures_daily days newer than the R2 archive can we get, and do they line up?

Does NOT write to R2. For days after the archive's newest day (plus 8 overlap sessions before it) it downloads the
vendor file, then compares each symbol's close with the R2 copy on the overlap days. A constant ratio of 1.000 means
the vendor's adjustment base is unchanged and new days can simply be appended. A ratio other than 1 (constant across the
overlap days) means a roll changed the ratio back-adjustment and the stored history must be rescaled by that ratio.
Writes futures_data/fresh_probe_report.md.
"""
import csv
import hashlib
import json
import os
import statistics
from contextlib import closing
from io import BytesIO
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import boto3
import pyarrow.parquet as pq

BASE = "https://marketparquet.com"
BUCKET, PREFIX = "insider-research", "marketparquet/futures_daily/"
RENAME = {"6A": "A6", "6B": "B6", "6C": "AD", "6E": "E6", "6J": "J1", "6L": "BR", "6M": "MP",
          "6N": "N6", "6S": "E1", "ZB": "US", "BRR": "BTC", "LBR": "LBS"}
token = os.environ.get("MARKETPARQUET_API_KEY", "")
out = ["# Fresh futures probe (read-only)", ""]


def get(url, auth=True, limit=60_000_000):
    h = {"User-Agent": "insider-buying-research/1.0"}
    if auth and token:
        h["Authorization"] = f"Bearer {token}"
    try:
        with urlopen(Request(url, headers=h), timeout=90) as r:
            return r.status, r.read(limit)
    except HTTPError as e:
        return e.code, e.read(2000)
    except URLError as e:
        return 0, str(e).encode()


s3 = boto3.client("s3", endpoint_url=os.environ["R2_ENDPOINT_URL"], aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
                  aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"], region_name="auto")
keys = sorted(o["Key"] for p in s3.get_paginator("list_objects_v2").paginate(Bucket=BUCKET, Prefix=PREFIX)
              for o in p.get("Contents", []) if o["Key"].endswith(".parquet"))
have = [k[len(PREFIX):-8] for k in keys]
last = have[-1]
overlap = have[-8:]
out.append(f"Archive newest day: {last}. Overlap sessions compared: {overlap[0]}..{overlap[-1]}.")


def r2_closes(day):
    resp = s3.get_object(Bucket=BUCKET, Key=f"{PREFIX}{day}.parquet")
    with closing(resp["Body"]) as b:
        t = pq.read_table(BytesIO(b.read()), columns=["symbol", "close"])
    return dict(zip(t.column("symbol").to_pylist(), t.column("close").to_pylist()))


manifests = {}
for label, auth in (("with API key", True), ("no key", False)):
    code, body = get(f"{BASE}/api/v1/manifest/futures_daily?start=2026-10-01&end=2026-12-31", auth)
    try:
        m = json.loads(body)
        files = sorted(m.get("files") or [], key=lambda e: e["date"])
        manifests[label] = files
        out.append(f"- Manifest {label}: HTTP {code}; plan={m.get('plan')!r}; {len(files)} files; "
                   f"newest {files[-1]['date'] if files else 'none'}; keys {sorted(m)}")
    except Exception:
        out.append(f"- Manifest {label}: HTTP {code}; not JSON: {body[:200]!r}")
        manifests[label] = []

files = max(manifests.values(), key=len)
want = [e for e in files if e["date"] > last or e["date"] in overlap]
new_days = [e["date"] for e in want if e["date"] > last]
out.append(f"- Vendor days newer than the archive that the manifest offers: {', '.join(new_days) or 'none'}")
vendor = {}
for e in want:
    url = e["download_url"]
    url = BASE + url if url.startswith("/") else url
    code, data = get(url)
    if url.startswith(BASE + "/api/v1/download/") and code == 200:
        try:
            code, data = get(json.loads(data)["download_url"], auth=False)
        except Exception as ex:
            out.append(f"- {e['date']}: could not follow download url ({ex})")
            continue
    if code != 200 or data[:4] != b"PAR1":
        out.append(f"- {e['date']}: download failed (HTTP {code})")
        continue
    t = pq.read_table(BytesIO(data))
    vendor[e["date"]] = dict(zip(t.column("symbol").to_pylist(), t.column("close").to_pylist()))
    out.append(f"- {e['date']}: downloaded, {t.num_rows} rows")

rows = list(csv.DictReader(open("futures_data/report_universe_48_markets.csv")))
r2 = {d: r2_closes(d) for d in overlap if d in vendor}
out += ["", f"## Overlap comparison (vendor close / archive close) on {', '.join(sorted(r2)) or 'no overlap days'}", "",
        "| report symbol | price symbol | median ratio | min ratio | max ratio | verdict |", "|---|---|---|---|---|---|"]
need_rescale = []
for r in rows:
    ps = RENAME.get(r["ibkr"], r["ibkr"])
    ratios = [vendor[d][ps] / r2[d][ps] for d in r2 if ps in vendor.get(d, {}) and ps in r2[d] and r2[d][ps]]
    if not ratios:
        out.append(f"| {r['ibkr']} | {ps} | | | | no overlap |")
        continue
    med = statistics.median(ratios)
    spread = max(ratios) - min(ratios)
    verdict = "same base" if abs(med - 1) < 1e-4 and spread < 1e-4 else ("rescale by median ratio" if spread < 1e-4 else "inconsistent: check")
    if verdict != "same base":
        need_rescale.append(ps)
    out.append(f"| {r['ibkr']} | {ps} | {med:.6f} | {min(ratios):.6f} | {max(ratios):.6f} | {verdict} |")
out += ["", f"Markets needing a rescale or a check: {', '.join(need_rescale) or 'none'}."]
if new_days and vendor.get(new_days[-1]):
    cnt = sum(1 for r in rows if RENAME.get(r["ibkr"], r["ibkr"]) in vendor[new_days[-1]])
    out.append(f"Newest vendor day {new_days[-1]} carries {cnt} of the 48 markets.")
text = "\n".join(out)
open("futures_data/fresh_probe_report.md", "w").write(text + "\n")
print(text)
