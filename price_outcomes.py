"""Historical OHLC outcome calculations. Requires externally validated adjusted bars."""
from datetime import date
from decimal import Decimal

HORIZONS=(11,21,43,64)

def d(x):return Decimal(str(x))

def true_range(bar,previous_close):
    high,low=d(bar["high"]),d(bar["low"])
    return max(high-low,abs(high-previous_close),abs(low-previous_close))

def atr14(bars,entry_index):
    """14 completed bars before entry; requires 15 earlier bars for first TR."""
    if entry_index<15: return None
    return sum((true_range(bars[i],d(bars[i-1]["close"])) for i in range(entry_index-14,entry_index)),Decimal(0))/14

def trading_entry_index(bars,filing_date):
    """First bar strictly after filing date (D-051)."""
    for i,bar in enumerate(bars):
        if str(bar["date"])>str(filing_date):return i
    return None

def compare_disclosure(bars,filing_date):
    """Returns filing-close descriptive baseline and next-open executable baseline.
    Bars must be ordered, unadjusted-or-adjusted consistently, and split-safe.
    No claim that filing-date close was tradable or post-disclosure.
    """
    next_idx=trading_entry_index(bars,filing_date)
    filing_idx=next((i for i,b in enumerate(bars) if str(b["date"])==str(filing_date)),None)
    if next_idx is None or filing_idx is None:return {"status":"missing_price_date"}
    atr=atr14(bars,next_idx)
    if atr is None or atr<=0:return {"status":"missing_or_invalid_entry_atr"}
    next_open=d(bars[next_idx]["open"])
    filing_close=d(bars[filing_idx]["close"])
    if next_open<=0 or filing_close<=0:return {"status":"invalid_reference_price"}
    result={"status":"ok","filing_date":str(filing_date),"filing_close":str(filing_close),
            "next_open_date":str(bars[next_idx]["date"]),"next_open":str(next_open),
            "atr14":str(atr),"entry_gap_percent":str((next_open/filing_close-1)*100),
            "entry_gap_atr":str((next_open-filing_close)/atr),"horizons":{}}
    for h in HORIZONS:
        # Entry bar is session 1; end at entry_index + h - 1.
        end=next_idx+h
        if end>len(bars):
            result["horizons"][str(h)]={"status":"insufficient_forward_bars"}
            continue
        window=bars[next_idx:end]
        high=max(d(b["high"]) for b in window)
        low=min(d(b["low"]) for b in window)
        close=d(window[-1]["close"])
        def stats(entry):
            return {"max_gain_atr":str((high-entry)/atr),
                    "max_adverse_atr":str((low-entry)/atr),
                    "end_return_atr":str((close-entry)/atr),
                    "max_gain_percent":str((high/entry-1)*100),
                    "max_adverse_percent":str((low/entry-1)*100),
                    "end_return_percent":str((close/entry-1)*100)}
        result["horizons"][str(h)]={"status":"ok","end_date":str(window[-1]["date"]),
                                    "next_open":stats(next_open),
                                    "filing_close_reference":stats(filing_close)}
    return result
