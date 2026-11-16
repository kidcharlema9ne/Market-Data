"""Build the weekly COT extract for the exit tests straight from the cot-history repo, using that repo's own loader.

Keeps every weekly report since 1992-10-06 for each contract code whose latest name is in cot-history's IBKR map (so a
contract keeps its full history across CFTC renames; the earlier extract matched on name per row and lost pre-2022 history
for about 25 markets). Columns: code, name (latest), ibkr, date, oi (legacy futures-only, all delivery months), comm,
large, small (net positions).

Also writes the report universe (the markets in cot-history's COT report as of the latest week, same selection as
scripts/cot_report.py: IBKR name, 156+ weeks, continuous recent history, latest open interest >= 45,000, thin products
removed) to <universe .csv>.

Usage: python make_cot_extract.py <cot-history repo> <output .csv.gz> <universe .csv>
"""
import importlib.util
import subprocess
import sys
from pathlib import Path

import pandas as pd

repo, out, uni_out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
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
latest = df["date"].max()
uni = []
for code, g in df.groupby("code"):
    g = g.sort_values("date")
    nm = g["name"].iloc[-1]
    if nm not in cr.IBKR or len(g) < cr.MIN_HIST_WEEKS:
        continue
    tail = g.tail(cr.MIN_HIST_WEEKS)
    if (tail["date"].iloc[-1] - tail["date"].iloc[0]).days > cr.MIN_HIST_WEEKS * 7 + 28:
        continue
    if g["date"].iloc[-1] != latest or g["oi"].iloc[-1] < cr.MIN_OI or cr.IBKR[nm][0] in cr.THIN:
        continue
    uni.append(dict(code=code, ibkr=cr.IBKR[nm][0], name=nm, latest_oi=g["oi"].iloc[-1]))
uni = pd.DataFrame(uni)
from_report = cr.build(df)
from_report = from_report[(from_report["date"] == latest) & (from_report["oi"] >= cr.MIN_OI) & (~from_report["ibkr"].isin(cr.THIN))]
assert set(uni["ibkr"]) == set(from_report["ibkr"]) and len(uni) == len(from_report), "universe differs from the report"
uni.to_csv(uni_out, index=False)
print(f"report universe: {len(uni)} markets as of {latest:%Y-%m-%d}: {' '.join(sorted(uni['ibkr']))}")
res = pd.concat(frames, ignore_index=True)
res["date"] = res["date"].dt.strftime("%Y-%m-%d")
res.to_csv(out, index=False, compression="gzip")
commit = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
print(f"rows {len(res)}; codes {res['code'].nunique()}; {res['date'].min()} to {res['date'].max()}; cot-history commit {commit}")
