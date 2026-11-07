"""Run the current four-buyer rules under three security-identity joins. Read-only; prints to the log.

Rules reproduced from spec v0.10 Sections 22-23 (exploratory pilot conventions, not new methodology):
  * distinct officer/director buyers with screened code-P common-stock purchases
  * public count reaches >= 4 within a 15-session window -> enter at the next regular open (D-051)
  * average daily dollar volume over the 15 sessions before entry (floor $3M)
  * price-only outcome from entry open to the close of session 21 (entry session = day one)
  * SPY over the same window restated in the stock's fixed pre-entry ATR(14); excess per trade
  * price setup: stock down 2-5 ATR over 15 sessions while SPY is up >= 0.5 of its own ATR

Joins:  A = current provisional join (ticker with one issuer/title pair over the full year)
        B = A plus conflicting-ticker filings whose reported price is confirmed by the ticker's price range
        C = B minus any filing whose reported price contradicts its ticker's price range
"""

import json
import math
import os
import re
import sqlite3
from bisect import bisect_right
from collections import Counter, defaultdict
from io import BytesIO
from pathlib import Path
from statistics import mean, median
from tempfile import TemporaryDirectory
from urllib.request import Request, urlopen

import exchange_calendars as xcals
import pyarrow.parquet as pq

from r2_storage import client
from sec_bulk_importer import disclosure_opportunities
from validate_free_year_report import PRICE_PREFIX, checked_object
from validate_free_year_universe import DB_KEY, END, START

PLACEHOLDERS = {"NONE", "N/A", "NA", "N.A.", "-", "--", "0", "NULL"}
TOLERANCE = 0.05
WINDOW_FILINGS = ("2026-01-01", "2026-09-30")
FLAGS = {"filing_affirms_10b5_1", "possible_10b5_1", "possible_non_discretionary", "not_acquisition",
         "missing_numeric_amount"}
TITLE = re.compile(r"(?:class [a-z0-9]+ )?common (?:stock|shares)(?:,?\s+(?:no par value|(?:par value )?\$\d+"
                   r"(?:\.\d+)?(?: par value)?(?: per share)?\.?))?", re.I)
ENTITY = re.compile(r"\b(llc|l\.l\.c|lp|l\.p|llp|ltd|inc|corp|corporation|company|co|trust|fund|funds|capital|"
                    r"partners|partnership|holdings|management|group|foundation|investments?|ventures|advisors|"
                    r"associates|equity|bancorp|bank|trustee|estate)\b\.?", re.I)
CFO = re.compile(r"\bcfo\b|chief financial|principal financial|finance chief", re.I)
BUYERS, WINDOW, FLOOR, HOLD = 4, 15, 3_000_000, 21


def fetch(url, limit, headers=None):
    with urlopen(Request(url, headers={"User-Agent": "Mozilla/5.0", **(headers or {})}), timeout=60) as response:
        return response.read(limit + 1)


def spy_bars(first, last):
    token = os.environ["MARKETPARQUET_API_KEY"]
    url = f"https://marketparquet.com/api/v1/manifest/etf_daily?start={first}&end={last}"
    files = json.loads(fetch(url, 2_000_000, {"Authorization": f"Bearer {token}"}))["files"]
    out = {}
    for row in files:
        payload = fetch(row["download_url"], 8 * 1024 * 1024)
        names = set(pq.ParquetFile(BytesIO(payload)).schema_arrow.names)
        date_field = "date" if "date" in names else "timestamp"
        bars = pq.read_table(BytesIO(payload), columns=["symbol", date_field, "open", "high", "low", "close"],
                             filters=[("symbol", "in", ["SPY"])]).to_pylist()
        if len(bars) == 1 and str(bars[0][date_field])[:10] == row["date"]:
            b = bars[0]
            out[row["date"]] = (float(b["open"]), float(b["high"]), float(b["low"]), float(b["close"]), 0.0)
    return out


def load_bars(storage, tickers, days):
    bars = defaultdict(dict)
    for day in days:
        data, _ = checked_object(storage, f"{PRICE_PREFIX}{day}.parquet")
        names = set(pq.ParquetFile(BytesIO(data)).schema_arrow.names)
        date_col = "date" if "date" in names else "timestamp"
        rows = pq.read_table(BytesIO(data), columns=["symbol", date_col, "open", "high", "low", "close", "volume"],
                             filters=[("symbol", "in", sorted(tickers))]).to_pylist()
        counts = Counter(r["symbol"] for r in rows)
        for r in rows:
            t = r["symbol"]
            if counts[t] != 1 or str(r[date_col])[:10] != day:
                continue
            vals = [r[k] for k in ("open", "high", "low", "close", "volume")]
            if any(v is None or not math.isfinite(v) for v in vals):
                continue
            o, h, l, c, v = map(float, vals)
            if 0 < l <= min(o, c) <= max(o, c) <= h and v >= 0:
                bars[t][day] = (o, h, l, c, v)
    return bars


def atr_before(series, days, e):
    """Mean of the 14 true ranges of the 14 completed sessions before entry index e."""
    if e < 15:
        return None
    window = days[e - 15:e]
    if any(d not in series for d in window):
        return None
    total = 0.0
    for k in range(1, 15):
        _, h, l, _, _ = series[window[k]]
        pc = series[window[k - 1]][3]
        total += max(h - l, abs(h - pc), abs(l - pc))
    return total / 14


def price_verdict(d, ticker, bars):
    price = d.get("insider_weighted_price")
    if not price:
        return "no_insider_price"
    rows = [bars.get(ticker, {}).get(x) for x in (d.get("transaction_dates") or [])]
    rows = [r for r in rows if r]
    if not rows:
        return "no_price_bar"
    lo, hi = min(r[2] for r in rows), max(r[1] for r in rows)
    p = float(price)
    return "confirmed" if lo * (1 - TOLERANCE) <= p <= hi * (1 + TOLERANCE) else "contradicted"


def buyer_of(d):
    """(owner_cik, is_cfo) for a sole-reporting-owner officer/director that is not an apparent entity."""
    owners = d.get("owners") or []
    if len(owners) != 1:
        return None
    o = owners[0]
    rel = (o.get("relationship") or "").lower()
    if not ("director" in rel or "officer" in rel) or not o.get("cik") or ENTITY.search(o.get("name") or ""):
        return None
    return o["cik"], bool(CFO.search(o.get("title") or ""))


def find_entries(events, last_index, window=WINDOW, threshold=BUYERS):
    """events: (entry_session_index, owner, is_cfo, filing_date). One entry per upward crossing of the count."""
    if not events:
        return []
    by_idx = defaultdict(list)
    for ev in events:
        by_idx[ev[0]].append(ev)
    entries, previous = [], 0
    for e in range(min(by_idx), min(last_index, max(by_idx) + window) + 1):
        live = [ev for i in range(e - window + 1, e + 1) for ev in by_idx.get(i, ())]
        count = len({ev[1] for ev in live})
        if count >= threshold and previous < threshold and by_idx.get(e):
            entries.append({"e": e, "buyers": count, "cfo": any(ev[2] for ev in live),
                            "filed": max(ev[3] for ev in by_idx[e])})
        previous = count
    return entries


def outcome(entry, series, spy, days):
    e = entry["e"]
    if e + HOLD - 1 >= len(days):
        return None, "forward_window_incomplete"
    entry_day, exit_day = days[e], days[e + HOLD - 1]
    if entry_day not in series or exit_day not in series:
        return None, "missing_entry_or_exit_bar"
    atr = atr_before(series, days, e)
    if not atr or atr <= 0:
        return None, "missing_atr"
    history = days[e - 15:e]
    if any(d not in series for d in history):
        return None, "missing_history"
    base_close, last_close = series[days[e - 16]][3] if days[e - 16] in series else None, series[days[e - 1]][3]
    if base_close is None:
        return None, "missing_history"
    open_, close_ = series[entry_day][0], series[exit_day][3]
    adv = mean(series[d][3] * series[d][4] for d in history)
    spy_atr = atr_before(spy, days, e)
    if not spy_atr or entry_day not in spy or exit_day not in spy or days[e - 16] not in spy or days[e - 1] not in spy:
        return None, "missing_spy"
    stock = (close_ - open_) / atr
    spy_pct = spy[exit_day][3] / spy[entry_day][0] - 1
    spy_in_atr = spy_pct / (atr / open_)
    return {
        "stock": stock, "spy": spy_in_atr, "excess": stock - spy_in_atr, "adv": adv, "cfo": entry["cfo"],
        "decline": (base_close - last_close) / atr, "spy_move": (spy[days[e - 1]][3] - spy[days[e - 16]][3]) / spy_atr,
        "entry_day": entry_day, "buyers": entry["buyers"],
        "atr_pct": atr / open_, "entry_open": open_,
    }, "ok"


def report_line(label, rows):
    n = len(rows)
    if not n:
        return f"  {label:<52} n=0"
    ex = [r["excess"] for r in rows]
    return (f"  {label:<52} n={n:<4} stock {mean(r['stock'] for r in rows):+.2f} | SPY {mean(r['spy'] for r in rows):+.2f}"
            f" | excess {mean(ex):+.2f} | median excess {median(ex):+.2f} | up {sum(r['stock'] > 0 for r in rows)}/{n}"
            f" | beat SPY {sum(x > 0 for x in ex)}/{n} | dates {len({r['entry_day'] for r in rows})}")


def main():
    storage = client()
    database, _ = checked_object(storage, DB_KEY)
    with TemporaryDirectory() as directory:
        path = Path(directory) / "sec.sqlite"
        path.write_bytes(database)
        del database
        with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as db:
            disclosures = list(disclosure_opportunities(db, START, END))
    days = [str(d.date()) for d in xcals.get_calendar("XNYS").sessions_in_range(START, END)]
    print(f"Disclosures {START}..{END}: {len(disclosures)}; sessions: {len(days)}")

    pairs = defaultdict(set)
    for d in disclosures:
        t = (d.get("ticker_at_filing") or "").upper().strip()
        d["_t"] = t
        pairs[t].add((d["issuer_cik"], d["security_title"]))
    provisional = {t for t, p in pairs.items() if len(p) == 1 and t not in PLACEHOLDERS and t}
    in_window = [d for d in disclosures if WINDOW_FILINGS[0] <= (d["filing_date"] or "") <= WINDOW_FILINGS[1]]
    unmatched = [d for d in in_window if d["_t"] not in provisional]
    print(f"Jan-Sep 2026 filings: {len(in_window)}; not on provisional join: {len(unmatched)} (handoff: 2,443)")

    flagged = [d for d in in_window if FLAGS.intersection(d["review_flags"])]
    screened_w = [d for d in in_window if not FLAGS.intersection(d["review_flags"])
                  and TITLE.fullmatch(" ".join((d["security_title"] or "").split()))]
    print(f"Screen check: {len(flagged)} flagged (handoff 1,319); {len(screened_w)} screened (handoff 6,604)")

    real = {d["_t"] for d in disclosures if d["_t"] and d["_t"] not in PLACEHOLDERS}
    bars = load_bars(storage, real, days)
    print(f"Price bars loaded for {len(bars)} of {len(real)} tickers")
    etf_first = "2025-12-01"
    spy = spy_bars(etf_first, days[-1])
    expected = [d for d in days if d >= etf_first]
    print(f"SPY bars: {len(spy)} of {len(expected)} sessions since {etf_first}")

    verdict = {}
    for i, d in enumerate(disclosures):
        verdict[i] = price_verdict(d, d["_t"], bars) if d["_t"] in real else "placeholder"
    index = {id(d): i for i, d in enumerate(disclosures)}

    def security(d, variant):
        t, v = d["_t"], verdict[index[id(d)]]
        if t not in real:
            return None
        if variant == "A":
            return t if t in provisional else None
        if variant == "B":
            return t if (t in provisional or v == "confirmed") else None
        return t if ((t in provisional or v == "confirmed") and v != "contradicted") else None

    for variant, label in (("A", "A. Current provisional join"),
                           ("B", "B. Current join + price-confirmed conflicting filings"),
                           ("C", "C. Variant B minus filings contradicted by price")):
        events = defaultdict(list)
        used = 0
        for d in disclosures:
            sec = security(d, variant)
            buyer = buyer_of(d) if sec else None
            if (not sec or not buyer or FLAGS.intersection(d["review_flags"])
                    or not TITLE.fullmatch(" ".join((d["security_title"] or "").split()))):
                continue
            e = bisect_right(days, d["filing_date"])
            if e >= len(days):
                continue
            events[sec].append((e, buyer[0], buyer[1], d["filing_date"]))
            used += 1
        entries = []
        for sec, evs in events.items():
            for entry in find_entries(evs, len(days) - 1):
                if WINDOW_FILINGS[0] <= entry["filed"] <= WINDOW_FILINGS[1]:
                    entries.append((sec, entry))
        rows, dropped = [], Counter()
        for sec, entry in entries:
            result, why = outcome(entry, bars.get(sec, {}), spy, days)
            if result:
                result["ticker"] = sec
                rows.append(result)
            else:
                dropped[why] += 1
        print(f"\n===== {label} =====")
        print(f"qualifying buyer filings used: {used}; securities: {len(events)}; four-plus entries: {len(entries)}; "
              f"complete 21-session outcomes: {len(rows)}; dropped: {dict(dropped)}")
        liquid = [r for r in rows if r["adv"] >= FLOOR]
        up = [r for r in liquid if r["spy_move"] >= 0.5]
        setup = [r for r in up if 2 <= r["decline"] <= 5]
        print(report_line("Four-plus buyers, no liquidity floor  [spec: 137, stock +0.75, SPY +0.11, excess +0.64]", rows))
        print(report_line("Four-plus, at least $3M  [spec: 91, +0.53, SPY +0.01, excess +0.53, median +0.17]", liquid))
        print(report_line("... below $3M  [spec: 46, +1.18, SPY +0.30, excess +0.88]", [r for r in rows if r["adv"] < FLOOR]))
        print(report_line("... $3M, CFO among buyers  [spec: 32, excess +0.40]", [r for r in liquid if r["cfo"]]))
        print(report_line("... $3M, no identified CFO  [spec: 59, excess +0.59]", [r for r in liquid if not r["cfo"]]))
        print(report_line("... $3M, SPY up >= 0.5 ATR  [spec: 39, stock +1.16, SPY -0.09, excess +1.25]", up))
        print(report_line("... plus stock down 2-5 ATR (price setup)  [spec: 15, excess +1.42, median +1.27]", setup))
        print(report_line("... price setup with CFO  [spec: 7, +1.29, SPY -0.38, excess +1.68]", [r for r in setup if r["cfo"]]))
        print(report_line("... price setup, no identified CFO  [spec: 8, +1.31, SPY +0.11, excess +1.20]", [r for r in setup if not r["cfo"]]))
        if variant == "A":
            print("  Price-setup trades (variant A): " + ", ".join(f"{r['ticker']} {r['entry_day']}" for r in setup))
        else:
            print("  Price-setup trades: " + ", ".join(f"{r['ticker']} {r['entry_day']}" for r in setup))


if __name__ == "__main__":
    main()
