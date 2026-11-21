"""READ-ONLY: compare vendor manifest file sizes (all years) with stored R2 object sizes. No file bodies downloaded."""
import json, os, urllib.request
from collections import Counter
import boto3
BASE = "https://marketparquet.com"
AUTH = {"Authorization": f"Bearer {os.environ['MARKETPARQUET_API_KEY']}", "User-Agent": "insider-buying-research/1.0"}
st = boto3.client("s3", endpoint_url=os.environ["R2_ENDPOINT_URL"], aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
                  aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"], region_name="auto")
stored = {}
for p in st.get_paginator("list_objects_v2").paginate(Bucket="insider-research", Prefix="marketparquet/futures_daily/"):
    for o in p.get("Contents", []):
        stored[o["Key"].split("/")[-1][:-8]] = (o["Size"], o["LastModified"])
vendor, keys = {}, set()
for year in range(2007, 2027):
    m = json.loads(urllib.request.urlopen(urllib.request.Request(f"{BASE}/api/v1/manifest/futures_daily?start={year}-01-01&end={year}-12-31", headers=AUTH), timeout=90).read())
    for e in m.get("files") or []:
        keys |= set(e)
        vendor[e["date"]] = e["file_size_bytes"]
print("manifest entry fields:", sorted(k for k in keys if "url" not in k.lower()))
print(f"vendor files {len(vendor)} ({min(vendor)}..{max(vendor)}); stored {len(stored)} ({min(stored)}..{max(stored)})")
print("vendor days not stored:", sorted(set(vendor) - set(stored))[:20], "| stored days not at vendor:", sorted(set(stored) - set(vendor))[:20])
diff = sorted(d for d in vendor if d in stored and vendor[d] != stored[d][0])
print(f"size differs on {len(diff)} days:", diff[:60])
by_year = Counter(d[:4] for d in diff)
print("differing days by year:", dict(sorted(by_year.items())))
