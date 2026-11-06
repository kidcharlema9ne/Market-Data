"""Resumable SEC quarterly insider transactions ZIP archive to Cloudflare R2."""
import hashlib, json, os, time, urllib.error, urllib.request, zipfile, io
from datetime import datetime, timezone
from r2_storage import BUCKET, client

START_YEAR = 2006
END_YEAR = 2026
END_QUARTER = 3
PREFIX = "sec/insider-transactions/quarterly-original-zips/"
agent = os.environ["SEC_USER_AGENT"].strip()
if not agent:
    raise SystemExit("SEC_USER_AGENT is required")
storage = client()
results = []
for year in range(START_YEAR, END_YEAR + 1):
    for quarter in range(1, 5):
        if year == END_YEAR and quarter > END_QUARTER:
            continue
        name = f"{year}q{quarter}_form345.zip"
        key = PREFIX + name
        url = f"https://www.sec.gov/files/datastandardsinnovation/data/insider-transactions-data-sets/{name}"
        try:
            obj = storage.head_object(Bucket=BUCKET, Key=key)
            if obj.get("Metadata", {}).get("verified-sha256"):
                print(f"SKIP previously verified {name}", flush=True)
                results.append({"name":name,"status":"reused","bytes":obj["ContentLength"],"sha256":obj["Metadata"]["verified-sha256"]})
                continue
        except storage.exceptions.ClientError as exc:
            if exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode") != 404:
                raise
        for attempt in range(1, 5):
            try:
                req = urllib.request.Request(url, headers={"User-Agent":agent,"Accept-Encoding":"identity"})
                with urllib.request.urlopen(req, timeout=90) as response:
                    payload = response.read()
                if not 1000 < len(payload) < 100_000_000:
                    raise ValueError(f"Unexpected ZIP size {len(payload)}")
                with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                    if archive.testzip() is not None:
                        raise ValueError("ZIP CRC failure")
                    if not any(n.upper().startswith("SUBMISSION") for n in archive.namelist()):
                        raise ValueError("No SUBMISSION table")
                digest = hashlib.sha256(payload).hexdigest()
                storage.put_object(Bucket=BUCKET, Key=key, Body=payload, Metadata={"verified-sha256":digest,"source":"sec-quarterly-insider-transactions"})
                obj = storage.head_object(Bucket=BUCKET, Key=key)
                if obj["ContentLength"] != len(payload) or obj.get("Metadata",{}).get("verified-sha256") != digest:
                    raise ValueError("R2 upload verification failed")
                print(f"VERIFIED {name} bytes={len(payload)} sha256={digest}",flush=True)
                results.append({"name":name,"status":"uploaded","bytes":len(payload),"sha256":digest})
                break
            except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
                if attempt == 4:
                    print(f"FAILED {name}: {exc}",flush=True)
                    results.append({"name":name,"status":"failed","error":str(exc)})
                else:
                    time.sleep(min(30, 2**attempt * 3))
        time.sleep(0.25)
summary = {"generated_utc":datetime.now(timezone.utc).isoformat(),"expected":len(results),"uploaded":sum(x["status"]=="uploaded" for x in results),"reused":sum(x["status"]=="reused" for x in results),"failed":sum(x["status"]=="failed" for x in results),"quarters":results}
os.makedirs("reports",exist_ok=True)
with open("reports/sec_bulk_archive_manifest.json","w") as f:
    json.dump(summary,f,indent=2)
print(json.dumps({k:v for k,v in summary.items() if k!="quarters"},indent=2),flush=True)
if summary["failed"]:
    raise SystemExit(f'{summary["failed"]} quarters failed; rerun to resume')
