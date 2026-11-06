"""Join SEC disclosure opportunities to validated daily bars, without look-ahead.

Security identity is explicit. Unmatched and incomplete observations remain in output.
"""
from collections import defaultdict
from price_outcomes import compare_disclosure
from sec_episode_research import build_episodes, prior_disclosure_counts

def _role(owners):
    titles=" ".join(str(o.get("title","")) for o in owners).lower()
    relationships=" ".join(str(o.get("relationship","")) for o in owners).lower()
    if "chief financial" in titles or "cfo" in titles:return "CFO"
    if "chief executive" in titles or "ceo" in titles:return "CEO"
    if "director" in relationships:return "Director"
    if "officer" in relationships:return "Officer"
    return "Unclassified"

def integrate(disclosures, bars_by_security, security_mappings=None):
    """Return disclosure-level records, episode summary and quality accounting.

    bars_by_security maps stable security_id to chronological validated daily OHLCV.
    security_mappings maps (issuer_cik,ticker_at_filing,security_title) to stable IDs,
    or supply explicit security_id on a disclosure. Never guess by ticker alone.
    """
    disclosures=list(disclosures)
    security_mappings=security_mappings or {}
    episodes=build_episodes(disclosures)
    episode_for={}
    for i,e in enumerate(episodes):
        for accession in e["accessions"]:
            episode_for.setdefault((accession,e["owner_cik"]),f"episode-{i+1}")
    history=prior_disclosure_counts(disclosures)
    result=[]
    seen=set()
    for r in disclosures:
        oid="|".join(str(r.get(k,"")) for k in ("accession","issuer_cik","security_title"))
        if oid in seen:raise ValueError("Duplicate disclosure/security opportunity: "+oid)
        seen.add(oid)
        owners=r.get("owners") or []
        owner_ids=sorted({str(o.get("cik")) for o in owners if o.get("cik")})
        key=(str(r.get("issuer_cik") or ""),str(r.get("ticker_at_filing") or ""),str(r.get("security_title") or ""))
        sid=r.get("security_id") or security_mappings.get(key)
        item={"opportunity_id":oid,"accession":r.get("accession"),"issuer_cik":r.get("issuer_cik"),
              "ticker_at_filing":r.get("ticker_at_filing"),"security_title":r.get("security_title"),
              "filing_date":r.get("filing_date"),"security_id":sid,"role":_role(owners),
              "owners":owners,"owner_ciks":owner_ids,"review_flags":r.get("review_flags",[]),
              "aggregate_dollars":r.get("aggregate_dollars"),
              "insider_weighted_price":r.get("insider_weighted_price"),
              "prior_disclosures_by_owner":{o:history.get((str(r.get("issuer_cik") or ""),o,r.get("accession")),0) for o in owner_ids},
              "episode_ids":[episode_for[(r["accession"],o)] for o in owner_ids if (r["accession"],o) in episode_for],
              "episode_id":episode_for.get((r["accession"],owner_ids[0])) if len(owner_ids)==1 else None,
              "outcome_status":"not_computed","horizons":{}}
        if not sid:
            item["outcome_status"]="unmatched_security"
        elif sid not in bars_by_security:
            item["outcome_status"]="missing_price_series"
        elif not r.get("filing_date"):
            item["outcome_status"]="missing_filing_date"
        else:
            outcome=compare_disclosure(bars_by_security[sid],r["filing_date"])
            item["outcome_status"]=outcome["status"]
            item["horizons"]=outcome.get("horizons",{})
            for k in ("next_open","next_open_date","atr14","entry_gap_atr","entry_gap_percent"):
                if k in outcome:item[k]=outcome[k]
        result.append(item)
    return {"schema_version":1,"entry_rule":"D-051: next regular session open after SEC filing date",
            "opportunities":result,"episodes":episodes,
            "counts":{"disclosures":len(result),"episodes":len(episodes),
                      "priced":sum(r["outcome_status"]=="ok" for r in result),
                      "unpriced":sum(r["outcome_status"]!="ok" for r in result)}}
