"""SEC-only episode and insider-history features. No look-ahead, no price dependency."""
from collections import defaultdict
from datetime import date
from decimal import Decimal

def _day(s):
    return date.fromisoformat(str(s)[:10])

def _owner_ids(row):
    return sorted({str(o.get("cik","")).strip() for o in row.get("owners",[]) if o.get("cik")})

def build_episodes(disclosures, max_calendar_days=7):
    """Group disclosure opportunities by issuer/security/insider within a rolling week.

    Preserve individual accession-level opportunities and their separate future entries.
    This grouping is descriptive only; never generate a synthetic entry or performance.
    """
    expanded=[]
    for r in disclosures:
        if not r.get("filing_date") or not r.get("accession"): continue
        for owner in _owner_ids(r):
            expanded.append((str(r.get("issuer_cik") or ""),str(r.get("security_title") or ""),
                             owner,_day(r["filing_date"]),r))
    expanded.sort(key=lambda x:(x[0],x[1],x[2],x[3],x[4]["accession"]))
    episodes=[]
    for (issuer,security,owner),group in __import__("itertools").groupby(expanded,key=lambda x:x[:3]):
        current=[]
        for item in group:
            if current and (item[3]-current[-1][3]).days>max_calendar_days:
                episodes.append(_emit(issuer,security,owner,current))
                current=[]
            current.append(item)
        if current: episodes.append(_emit(issuer,security,owner,current))
    return episodes

def _emit(issuer,security,owner,items):
    records=[x[4] for x in items]
    dollars=[Decimal(str(x["aggregate_dollars"])) for x in records if x.get("aggregate_dollars") is not None]
    return {"issuer_cik":issuer,"security_title":security,"owner_cik":owner,
            "first_filing_date":items[0][3].isoformat(),"last_filing_date":items[-1][3].isoformat(),
            "disclosure_count":len(records),
            "accessions":[r["accession"] for r in records],
            "total_disclosed_dollars":str(sum(dollars)) if len(dollars)==len(records) else None,
            "review_flags":sorted({flag for r in records for flag in r.get("review_flags",[])}),
            "synthetic_entry":False}

def prior_disclosure_counts(disclosures):
    """Count *earlier* public disclosures per insider/issuer; same-date excluded."""
    expanded=[]
    for r in disclosures:
        if not r.get("filing_date"):continue
        for owner in _owner_ids(r):
            expanded.append((str(r.get("issuer_cik") or ""),owner,_day(r["filing_date"]),r["accession"]))
    expanded.sort()
    result={}
    for (issuer,owner),grp in __import__("itertools").groupby(expanded,key=lambda x:x[:2]):
        prior=0
        for day,items in __import__("itertools").groupby(grp,key=lambda x:x[2]):
            group=list(items)
            for x in group: result[(issuer,owner,x[3])]=prior
            prior+=len(group)
    return result
