"""Read-only R2 inventory: total bytes and object counts by folder.

Lists every object in the insider-research bucket (no reads of object bodies,
no writes, no deletes) and prints size and count for each top-level folder and
for each second-level folder (for example marketparquet/stock_daily), plus the
first and last object date found under each marketparquet feed.
"""

import re
from collections import defaultdict

from r2_storage import BUCKET, client

DATE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def human(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:,.2f} {unit}"
        n /= 1024


def main():
    storage = client()
    top = defaultdict(lambda: [0, 0])
    second = defaultdict(lambda: [0, 0])
    dates = defaultdict(list)
    total = [0, 0]
    pages = storage.get_paginator("list_objects_v2").paginate(Bucket=BUCKET)
    for page in pages:
        for obj in page.get("Contents", []):
            key, size = obj["Key"], obj["Size"]
            parts = key.split("/")
            t = parts[0]
            s = "/".join(parts[:2]) if len(parts) > 2 else t
            for bucket, name in ((top, t), (second, s)):
                bucket[name][0] += size
                bucket[name][1] += 1
            total[0] += size
            total[1] += 1
            if len(parts) > 2:
                m = DATE.search(parts[-1])
                if m:
                    dates[s].append(m.group(1))
    print(f"BUCKET {BUCKET}: {total[1]:,} objects, {human(total[0])}")
    print("--- top-level folders ---")
    for name, (size, count) in sorted(top.items()):
        print(f"{name}: {count:,} objects, {human(size)}")
    print("--- second-level folders ---")
    for name, (size, count) in sorted(second.items()):
        span = ""
        if dates.get(name):
            span = f", dates {min(dates[name])} to {max(dates[name])}"
        print(f"{name}: {count:,} objects, {human(size)}{span}")


if __name__ == "__main__":
    main()
