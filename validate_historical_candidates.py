"""Unattended post-import audit of historical SEC purchase database in R2."""
import json, os, sqlite3, tempfile
from collections import Counter
from pathlib import Path
from r2_storage import BUCKET, client

KEY="sec/insider-transactions/derived/purchase_candidates.sqlite3"
storage=client()
with tempfile.TemporaryDirectory() as tmp:
    path=Path(tmp)/"candidates.sqlite3"
    storage.download_file(BUCKET,KEY,str(path))
    db=sqlite3.connect(str(path))
    integrity=db.execute("PRAGMA integrity_check").fetchone()[0]
    if integrity!="ok": raise SystemExit("SQLite integrity check failed: "+integrity)
    rows=db.execute("SELECT payload FROM purchase_candidates").fetchall()
    quarters=db.execute("SELECT name,candidate_rows FROM imported_quarters ORDER BY name").fetchall()
    counts=Counter()
    filings=set()
    opportunities=set()
    years=Counter()
    for (raw,) in rows:
        r=json.loads(raw)
        counts["rows"]+=1
        filing=r.get("filing_date")
        if not filing: counts["missing_filing_date"]+=1
        else: years[filing[:4]]+=1
        if not r.get("transaction_date"): counts["missing_transaction_date"]+=1
        if not r.get("owners"): counts["missing_owners"]+=1
        if not r.get("ticker_at_filing"): counts["missing_ticker"]+=1
        if not r.get("shares") or not r.get("price_per_share"): counts["missing_numeric"]+=1
        if r.get("acquired_disposed")!="A": counts["non_acquisition_P"]+=1
        if r.get("review_flags"): counts["flagged_rows"]+=1
        if r.get("form") not in ("4","4/A"): counts["unexpected_form"]+=1
        filings.add(r["accession"])
        opportunities.add((r["accession"],r["issuer_cik"],r["security_title"]))
    report={"stage":"sec_preprice_validation","db_key":KEY,"integrity":integrity,
      "imported_quarters":len(quarters),"candidate_rows":len(rows),
      "unique_filings":len(filings),"filing_security_opportunities":len(opportunities),
      "field_quality":dict(counts),"year_counts":dict(sorted(years.items())),
      "quarter_counts":dict(quarters),
      "historical_entry_rule":"D-051: next regular trading session open after SEC filing date; acceptance timestamp not needed",
      "status":"passed" if len(quarters)==83 and len(rows)>0 and not counts["missing_filing_date"] and not counts["unexpected_form"] else "blocked"}
    Path("reports").mkdir(exist_ok=True)
    Path("reports/preprice_validation.json").write_text(json.dumps(report,indent=2))
    print(json.dumps({k:v for k,v in report.items() if k not in ("year_counts","quarter_counts")},indent=2))
    if report["status"]!="passed": raise SystemExit("Historical SEC preprice validation blocked; see report")
