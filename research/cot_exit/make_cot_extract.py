"""Build the weekly COT extract for the exit tests straight from the cot-history repo, using that repo's own loader.

Keeps every weekly report since 1992-10-06 for each contract code whose latest name is in cot-history's IBKR map (so a
contract keeps its full history across CFTC renames; the earlier extract matched on name per row and lost pre-2022 history
for about 25 markets). Columns: code, name (latest), ibkr, date, oi (legacy futures-only, all delivery months), comm,
large, small (net positions).

Usage: python make_cot_extract.py <cot-history repo> <output .csv.gz>
"""
import importlib.util
import subprocess
import sys
from pathlib import Path

import pandas as pd

repo, out = Path(sys.argv[1]), Path(sys.argv[2])
spec = importlib.util.spec_from_file_location("cot_report", repo / "scripts" / "cot_report.py")
cr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cr)
df = cr.load(repo)
frames = []
for code, g in df.groupby("code"):
    g = g.sort_values("date")
    nm = g["name"].iloc[-1]
    if nm not in cr.IBKR:
        continue
    g = g.assign(name=nm, ibkr=cr.IBKR[nm][0])
    frames.append(g[["code", "name", "ibkr", "date", "oi", "comm", "large", "small"]])
res = pd.concat(frames, ignore_index=True)
res["date"] = res["date"].dt.strftime("%Y-%m-%d")
res.to_csv(out, index=False, compression="gzip")
commit = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
print(f"rows {len(res)}; codes {res['code'].nunique()}; {res['date'].min()} to {res['date'].max()}; cot-history commit {commit}")
