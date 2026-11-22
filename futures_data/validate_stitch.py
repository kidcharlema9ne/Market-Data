"""Read-only validation of the stitched table in R2 (marketparquet/futures_current/futures_prices_current.parquet).

For each of the 48 markets:
 1. Boundary check: where the rebase factor stops applying (last row with factor != 1 and the next row), the one-day return must look
    normal; a wrong roll ratio would show as a jump of about ln(ratio).
 2. Bridge check: return from the last archive day (2026-11-06) to the first day after it, scaled by the market's typical daily move
    times sqrt(number of sessions bridged). Values beyond about 4 would mean the new days sit on a different price level.
Writes futures_data/stitch_validation_report.md. Does not modify R2.
"""
import csv
import hashlib
import math
import os
from io import BytesIO

import boto3
import pandas as pd
import pyarrow.parquet as pq

RENAME = {"6A": "A6", "6B": "B6", "6C": "AD", "6E": "E6", "6J": "J1", "6L": "BR", "6M": "MP",
          "6N": "N6", "6S": "E1", "ZB": "US", "BRR": "BTC", "LBR": "LBS"}
s3 = boto3.client("s3", endpoint_url=os.environ["R2_ENDPOINT_URL"], aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
                  aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"], region_name="auto")
resp = s3.get_object(Bucket="insider-research", Key="marketparquet/futures_current/futures_prices_current.parquet")
raw = resp["Body"].read()
assert hashlib.sha256(raw).hexdigest() == resp["Metadata"]["verified-sha256"]
df = pq.read_table(BytesIO(raw)).to_pandas()
rows = list(csv.DictReader(open("futures_data/report_universe_48_markets.csv")))
out = ["# Stitch validation (read-only)", "", f"Rows {len(df)}; newest day {df['file_date'].max()}.", "",
       "| market | days rebased | boundary day | return across boundary | ln(factor) there | typical daily move | bridge: last archive day -> next day | sessions bridged | bridge return | bridge z | verdict |",
       "|---|---|---|---|---|---|---|---|---|---|---|"]
flags = []
for r in rows:
    ps = RENAME.get(r["ibkr"], r["ibkr"])
    g = df[df["symbol"] == ps].sort_values("file_date").reset_index(drop=True)
    c = g["close"]
    lr = (c / c.shift(1)).apply(lambda x: math.log(x) if x and x > 0 else float("nan"))
    typ = float(lr.loc[: g.index[g["file_date"] == "2026-11-06"][0]].tail(60).abs().median())
    reb = g.index[g["rebase_factor"] != 1.0]
    if len(reb):
        b = int(reb.max())
        bret = float(lr.iloc[b + 1]) if b + 1 < len(g) else float("nan")
        bdate = f"{g.loc[b, 'file_date']} -> {g.loc[b + 1, 'file_date']}"
        lf = math.log(g.loc[b, "rebase_factor"])
    else:
        bret, bdate, lf = float("nan"), "none", 0.0
    i6 = int(g.index[g["file_date"] == "2026-11-06"][0])
    nxt = g.loc[i6 + 1, "file_date"]
    sess = int(pd.bdate_range("2026-11-06", nxt).size - 1)
    bridge = float(lr.iloc[i6 + 1])
    z = bridge / (typ * math.sqrt(sess))
    bad_b = len(reb) and abs(bret) > max(4 * typ, 0.4 * abs(lf))
    bad_z = abs(z) > 4
    verdict = "ok"
    if bad_b or bad_z:
        verdict = "CHECK"
        flags.append(r["ibkr"])
    out.append(f"| {r['ibkr']} | {len(reb)} | {bdate} | {bret:+.2%} | {lf:+.2%} | {typ:.2%} | {g.loc[i6, 'file_date']} -> {nxt} | {sess} | {bridge:+.2%} | {z:+.1f} | {verdict} |")
out += ["", f"Markets to check: {', '.join(flags) or 'none'}."]
text = "\n".join(out)
open("futures_data/stitch_validation_report.md", "w").write(text + "\n")
print(text)
