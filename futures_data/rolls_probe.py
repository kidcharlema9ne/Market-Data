"""Read-only: fetch MarketParquet's roll file (meta/futures_rolls) with Michael's API key and report what it holds.

Prints columns, row count, date range, the newest roll, every roll since 2026-10-01, and for the 48 COT-report markets
which rolled after 2026-11-06 (the archive's last day). Writes futures_data/rolls_probe_report.md. Does not write to R2.
"""
import csv
import json
import os
from io import BytesIO
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pyarrow.parquet as pq

BASE = "https://marketparquet.com"
token = os.environ["MARKETPARQUET_API_KEY"]
RENAME = {"6A": "A6", "6B": "B6", "6C": "AD", "6E": "E6", "6J": "J1", "6L": "BR", "6M": "MP",
          "6N": "N6", "6S": "E1", "ZB": "US", "BRR": "BTC", "LBR": "LBS"}
out = ["# MarketParquet roll file probe (read-only)", ""]


def get(url, auth):
    h = {"User-Agent": "insider-buying-research/1.0"}
    if auth:
        h["Authorization"] = f"Bearer {token}"
    try:
        with urlopen(Request(url, headers=h), timeout=90) as r:
            return r.status, r.read(80_000_000)
    except HTTPError as e:
        return e.code, e.read(500)
    except URLError as e:
        return 0, str(e).encode()


data = None
for label, url in (("api", f"{BASE}/api/v1/meta/futures_rolls"), ("file", f"{BASE}/meta/futures_rolls.parquet")):
    code, body = get(url, True)
    out.append(f"- {label} {url}: HTTP {code}, {len(body)} bytes, starts {body[:60]!r}")
    if code == 200 and body[:4] == b"PAR1":
        data = body
        break
    if code == 200:
        try:
            j = json.loads(body)
            out.append(f"  JSON keys: {sorted(j)[:20]}")
            du = j.get("download_url")
            if du:
                du = BASE + du if du.startswith("/") else du
                c2, b2 = get(du, du.startswith(BASE))
                out.append(f"  followed download_url: HTTP {c2}, {len(b2)} bytes")
                if c2 == 200 and b2[:4] == b"PAR1":
                    data = b2
                    break
        except Exception as e:
            out.append(f"  not JSON: {e}")
if data is None:
    text = "\n".join(out + ["", "COULD NOT FETCH THE ROLL FILE."])
    open("futures_data/rolls_probe_report.md", "w").write(text + "\n")
    print(text)
    raise SystemExit(0)

t = pq.read_table(BytesIO(data))
out += ["", f"Columns: {t.schema.names} types {[str(x) for x in t.schema.types]}", f"Rows: {t.num_rows}"]
rows = t.to_pylist()
dcol = next((c for c in t.schema.names if "date" in c.lower()), t.schema.names[0])
scol = next((c for c in t.schema.names if "symbol" in c.lower() or "root" in c.lower()), None)
dates = sorted(str(r[dcol])[:10] for r in rows)
out.append(f"Date column {dcol!r}: oldest {dates[0]}, newest {dates[-1]}; symbol column {scol!r}")
recent = [r for r in rows if str(r[dcol])[:10] >= "2026-10-01"]
out += ["", f"## Rolls since 2026-10-01 ({len(recent)})", ""]
for r in sorted(recent, key=lambda r: str(r[dcol])):
    out.append("- " + json.dumps({k: (str(v) if not isinstance(v, (int, float, str)) else v) for k, v in r.items()}))
u = list(csv.DictReader(open("futures_data/report_universe_48_markets.csv")))
want = {RENAME.get(x["ibkr"], x["ibkr"]): x["ibkr"] for x in u}
after = [r for r in rows if scol and str(r[dcol])[:10] > "2026-11-06" and r[scol] in want]
out += ["", f"## Rolls after 2026-11-06 in the 48 markets ({len(after)})", ""]
for r in sorted(after, key=lambda r: str(r[dcol])):
    out.append("- " + json.dumps({k: (str(v) if not isinstance(v, (int, float, str)) else v) for k, v in r.items()}))
text = "\n".join(out)
open("futures_data/rolls_probe_report.md", "w").write(text + "\n")
print(text)
