"""Read-only probe of the free MarketParquet intraday sample pack.

Downloads https://marketparquet.com/api/data/sample/stock_intraday_sample.zip,
and prints, for every parquet file inside, its bytes, rows, columns, symbols,
timestamp span, rows per symbol per day, and bytes per row. Nothing is written
to R2 and no research number is produced; it exists to size the intraday feed.
"""
import io
import zipfile
from collections import defaultdict
from urllib.request import Request, urlopen

import pyarrow.parquet as pq

URL = "https://marketparquet.com/api/data/sample/stock_intraday_sample.zip"


def main():
    req = Request(URL, headers={"User-Agent": "insider-buying-research/1.0"})
    with urlopen(req, timeout=120) as r:
        blob = r.read()
    print(f"ZIP bytes: {len(blob):,}")
    z = zipfile.ZipFile(io.BytesIO(blob))
    totals = defaultdict(lambda: [0, 0])
    for info in sorted(z.infolist(), key=lambda i: i.filename):
        if info.is_dir():
            continue
        print(f"FILE {info.filename}: {info.file_size:,} bytes (zip {info.compress_size:,})")
        if not info.filename.endswith(".parquet"):
            continue
        t = pq.read_table(io.BytesIO(z.read(info.filename)))
        rows = t.num_rows
        print(f"  rows={rows:,} cols={t.schema.names} bytes/row={info.file_size/max(rows,1):.2f}")
        names = t.schema.names
        sym = t.column("symbol").to_pylist() if "symbol" in names else []
        tsname = next((n for n in names if n in ("timestamp", "datetime", "ts", "time")), None)
        if sym:
            per = defaultdict(int)
            for s in sym:
                per[s] += 1
            print(f"  symbols={len(per)} rows/symbol: min={min(per.values())} max={max(per.values())} mean={rows/len(per):.0f}")
        if tsname:
            col = t.column(tsname).to_pylist()
            print(f"  {tsname}: first={min(col)} last={max(col)} type={t.schema.field(tsname).type}")
            days = {str(c)[:10] for c in col}
            print(f"  distinct days={len(days)} -> rows/symbol/day ~ {rows/max(len(per),1)/max(len(days),1):.0f}" if sym else "")
        key = "1min" if "1min" in info.filename else "5min" if "5min" in info.filename else "30min" if "30min" in info.filename else "1hour" if ("1hour" in info.filename or "1h" in info.filename) else "other"
        totals[key][0] += info.file_size
        totals[key][1] += rows
    print("--- totals by timeframe (sample) ---")
    for k, (b, rws) in totals.items():
        print(f"{k}: {b:,} bytes, {rws:,} rows, {b/max(rws,1):.2f} bytes/row")


if __name__ == "__main__":
    main()
