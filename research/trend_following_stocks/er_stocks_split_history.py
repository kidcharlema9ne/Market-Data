"""Download stock split history from Yahoo Finance for every symbol that has a signal (Michael, 18 Nov 2026).

Why: the MarketParquet archive prices are split-adjusted to today, so "price level" in the signal table is hindsight. With the split ratios we can
multiply the splits back out and get the price a trader would have seen on the day.

Usage: python er_stocks_split_history.py signal_rows.csv.gz OUT_DIR
Writes OUT_DIR/splits.csv (symbol, split_date, ratio; ratio = new shares per old share, so 4.0 is a 4-for-1 split and 0.1 is a 1-for-10 reverse split)
and OUT_DIR/split_coverage.csv (one row per symbol: status, first and last date Yahoo has, number of splits).
Status: ok = Yahoo has a full history that starts on or before the symbol's first signal; late_start = Yahoo history starts after the first signal (probably a different company that
re-used the ticker; NOT used); not_found = Yahoo has nothing (NOT used); error = failed after retries (NOT used).
The suffix -DELISTED in the archive is removed before asking Yahoo.
"""
import sys
import time
from pathlib import Path

import pandas as pd
import yfinance as yf

rows_path, out_dir = sys.argv[1], Path(sys.argv[2])
out_dir.mkdir(parents=True, exist_ok=True)
D = pd.read_csv(rows_path, usecols=["stock", "entry_date"])
D["entry_date"] = pd.to_datetime(D["entry_date"])
D["yahoo"] = D["stock"].astype(str).str.replace("-DELISTED", "", regex=False)
first = D.groupby("yahoo")["entry_date"].min()
syms = sorted(first.index)
print(f"{len(syms):,} symbols to look up", flush=True)

cov, spl = [], []
done = set()
cov_path, spl_path = out_dir / "split_coverage.csv", out_dir / "splits.csv"
if cov_path.exists():                                  # resume if a previous attempt got part way
    cov = pd.read_csv(cov_path).to_dict("records"); done = {r["symbol"] for r in cov}
    spl = pd.read_csv(spl_path).to_dict("records") if spl_path.exists() else []
    print(f"resuming: {len(done)} symbols already done", flush=True)


def save():
    pd.DataFrame(cov).to_csv(cov_path, index=False)
    pd.DataFrame(spl, columns=["symbol", "split_date", "ratio"]).to_csv(spl_path, index=False)


fails_in_a_row = 0
for i, s in enumerate(syms):
    if s in done:
        continue
    status, h0, h1, ns, err = "error", None, None, 0, ""
    for attempt in range(4):
        try:
            h = yf.Ticker(s).history(period="max", auto_adjust=False, actions=True)
            if h is None or len(h) == 0:
                status = "not_found"
            else:
                idx = h.index.tz_localize(None) if h.index.tz is not None else h.index
                h0, h1 = idx.min().date(), idx.max().date()
                status = "ok" if pd.Timestamp(h0) <= first[s] + pd.Timedelta(days=10) else "late_start"
                sp = h["Stock Splits"] if "Stock Splits" in h.columns else pd.Series(dtype=float)
                sp = sp[sp > 0]
                ns = len(sp)
                if status == "ok":
                    for d, r in zip(sp.index, sp.values):
                        spl.append({"symbol": s, "split_date": pd.Timestamp(d).tz_localize(None).date() if pd.Timestamp(d).tzinfo else pd.Timestamp(d).date(), "ratio": float(r)})
            err = ""
            break
        except Exception as ex:                        # rate limit or network: back off and retry
            err = f"{type(ex).__name__}: {str(ex)[:120]}"
            time.sleep(5 * (attempt + 1) ** 2)
    cov.append({"symbol": s, "status": status, "yahoo_first_date": h0, "yahoo_last_date": h1, "n_splits": ns, "first_signal": first[s].date(), "error": err})
    fails_in_a_row = fails_in_a_row + 1 if status == "error" else 0
    if fails_in_a_row >= 40:
        print("40 failures in a row; Yahoo is probably blocking this runner. Stopping with what we have.", flush=True)
        break
    if (i + 1) % 100 == 0:
        save()
        c = pd.DataFrame(cov)["status"].value_counts().to_dict()
        print(f"  {i + 1}/{len(syms)} done; {c}", flush=True)
    time.sleep(0.4)
save()
c = pd.DataFrame(cov)
print("coverage by status:\n" + c["status"].value_counts().to_string(), flush=True)
sig = D.merge(c[["symbol", "status"]], left_on="yahoo", right_on="symbol", how="left")
print("share of SIGNALS by status:\n" + (sig["status"].fillna("not_looked_up").value_counts(normalize=True) * 100).round(1).to_string(), flush=True)
print(f"{len(spl):,} split events kept for ok symbols", flush=True)
